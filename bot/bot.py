import logging
import random
import threading
from concurrent.futures import ThreadPoolExecutor

from .adapter.base import ChatAdapter
from .auto_proactive import AutoProactiveScheduler
from .commands import CommandMixin
from .condition_reminders import ConditionReminderScheduler
from .conditions import ConditionEvaluator
from .config import Settings
from .followup import FollowUpScheduler
from .llm.deepseek import DeepSeekClient, DeepSeekError
from .media import enrich_message
from .memory import MemoryStore
from .models import ChatType, IncomingMessage, RouteResult
from .personas import PersonaRegistry
from .proactive_flow import ProactiveMixin
from .prompt import build_messages
from .random_video import random_bilibili_video
from .reminder_flow import ReminderMixin
from .reminders import (
    ReminderScheduler,
    ReminderStore,
    parse_condition_reminder,
    parse_reminder,
    wants_cancel_all_reminders,
    wants_cancel_recent_reminder,
    wants_correct_reminder_time,
    wants_update_reminder,
)
from .router import Router
from .search_intent import plan_search
from .sending import SendingMixin

logger = logging.getLogger(__name__)


class WeChatBot(CommandMixin, ReminderMixin, ProactiveMixin, SendingMixin):
    def __init__(
        self,
        settings: Settings,
        registry: PersonaRegistry,
        store: MemoryStore,
        llm: DeepSeekClient,
        adapter: ChatAdapter,
    ):
        self.settings = settings
        self.registry = registry
        self.store = store
        self.llm = llm
        self.adapter = adapter
        self.router = Router(registry, store, banter_rate=settings.group_banter_rate)
        self._executor = ThreadPoolExecutor(max_workers=settings.max_workers, thread_name_prefix="reply")
        self._session_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._stop_event = threading.Event()
        self.paused = False
        self._batch_lock = threading.Lock()
        self._batches: dict[str, list[RouteResult]] = {}
        self._batch_timers: dict[str, threading.Timer] = {}
        self._session_generation: dict[str, int] = {}
        self.reminder_store = ReminderStore(settings.db_path)
        self.reminder_scheduler = ReminderScheduler(
            self.reminder_store,
            self._send,
            time_interval=settings.reminder_check_seconds,
        )
        self.condition_scheduler = ConditionReminderScheduler(
            self.reminder_store,
            ConditionEvaluator(settings, self.llm),
            self._send,
            check_interval=settings.condition_check_seconds,
            interval_minutes=settings.condition_interval_minutes,
            retry_minutes=settings.condition_retry_minutes,
            expire_days=settings.condition_expire_days,
        )
        self.followups: dict[str, FollowUpScheduler] = {}
        self.auto_proactives: dict[str, AutoProactiveScheduler] = {}
        for target in settings.proactive_targets:
            followup = FollowUpScheduler(
                target,
                self._send,
                quiet_start=settings.proactive_quiet_start,
                quiet_end=settings.proactive_quiet_end,
                first_delay=settings.followup_first_delay_minutes * 60,
                min_interval=settings.followup_min_interval_minutes * 60,
                max_interval=settings.followup_max_interval_minutes * 60,
                check_interval=settings.followup_check_seconds,
            )
            self.followups[target] = followup
            self.auto_proactives[target] = AutoProactiveScheduler(
                target,
                self._generate_auto_proactive,
                lambda: random_bilibili_video(settings),
                activity_provider=lambda target=target: self.store.last_activity(target),
                hold_provider=lambda followup=followup: followup.is_waiting() or self.paused,
                quiet_start=settings.proactive_quiet_start,
                quiet_end=settings.proactive_quiet_end,
                min_minutes=settings.proactive_min_minutes,
                max_minutes=settings.proactive_max_minutes,
                interval=settings.proactive_check_seconds,
                start_delay=settings.proactive_start_delay_seconds,
                video_rate=settings.proactive_video_rate,
                active_skip_minutes=settings.proactive_active_skip_minutes,
                retry_min_minutes=settings.proactive_retry_min_minutes,
                retry_max_minutes=settings.proactive_retry_max_minutes,
            )

    def run(self) -> None:
        self.adapter.start(self._on_message)
        self.reminder_scheduler.start()
        self.condition_scheduler.start()
        if self.settings.proactive_enabled:
            if not self.settings.proactive_targets:
                logger.warning(
                    "未配置主动发送白名单（PROACTIVE_WHITELIST / PROACTIVE_TARGET_WXID），"
                    "已跳过主动消息和追问"
                )
            for target, scheduler in self.auto_proactives.items():
                scheduler.start()
                self.followups[target].start()
                logger.info("主动消息已启用，目标=%s", target)
        logger.info("机器人已启动，提醒和主动消息调度已启动，等待消息（Ctrl+C 退出）")
        try:
            while not self._stop_event.wait(1.0):
                pass
        finally:
            self.stop()

    def stop(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        with self._batch_lock:
            timers = list(self._batch_timers.values())
            self._batch_timers.clear()
            self._batches.clear()
        for timer in timers:
            timer.cancel()
        self.reminder_scheduler.stop()
        self.condition_scheduler.stop()
        for scheduler in self.auto_proactives.values():
            scheduler.stop()
        for followup in self.followups.values():
            followup.stop()
        self.adapter.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _on_message(self, message: IncomingMessage) -> None:
        logger.info(
            "收到消息 会话=%s 发送者=%s(%s) 长度=%s",
            message.session_key,
            message.sender_name,
            message.sender_id,
            len(message.content),
        )
        if not self.store.claim_message(message.msg_id):
            logger.info("跳过已处理消息 会话=%s msg_id=%s", message.session_key, message.msg_id)
            return
        followup = self.followups.get(message.sender_id)
        if followup is not None:
            followup.cancel()
        command = self._parse_command(message)
        if command is not None:
            name = command[0].lower()
            if name in {"pause", "暂停"}:
                self.paused = True
                for item in self.followups.values():
                    item.cancel()
                self._drop_batch(message.session_key)
                self._send(message.session_key, "好，先不打扰你")
                return
            if name in {"resume", "恢复"}:
                self.paused = False
                self._send(message.session_key, "回来了")
                return
            if self.paused:
                return
            self._drop_batch(message.session_key)
            self._executor.submit(self._handle_command, message, command)
            return

        if self.paused:
            logger.info("暂停中，忽略消息")
            return

        if not self.settings.allows_reply(message.session_key):
            logger.info("会话不在回复白名单，忽略消息，会话=%s", message.session_key)
            return

        if message.chat_type == ChatType.PRIVATE or message.is_at_me:
            if wants_cancel_all_reminders(message.content):
                self._executor.submit(self._handle_cancel_all_reminders, message)
                return
            if wants_update_reminder(message.content):
                self._executor.submit(self._handle_update_reminder, message, message.content)
                return
            if wants_cancel_recent_reminder(message.content):
                self._executor.submit(self._handle_cancel_recent_reminder, message)
                return
            if wants_correct_reminder_time(message.content):
                self._executor.submit(
                    self._handle_correct_reminder_time,
                    message,
                    message.content,
                )
                return
            reminder = parse_reminder(message.content)
            if reminder is not None:
                self._executor.submit(self._handle_reminder, message, reminder)
                return
            condition = parse_condition_reminder(message.content)
            if condition is not None:
                self._executor.submit(self._handle_condition_reminder, message, condition)
                return

        route = self.router.route(message)
        if route is None:
            return
        self._enqueue(route)

    def _enqueue(self, route: RouteResult) -> None:
        batch: list[RouteResult] | None = None
        with self._batch_lock:
            timer = self._batch_timers.pop(route.session_key, None)
            if timer is not None:
                timer.cancel()

            items = self._batches.setdefault(route.session_key, [])
            items.append(route)
            total_chars = sum(len(item.user_text) for item in items)
            reached_limit = (
                len(items) >= self.settings.batch_max_messages
                or total_chars >= self.settings.batch_max_chars
            )

            if self.settings.reply_debounce <= 0 or reached_limit:
                self._batches.pop(route.session_key, None)
                batch = items
            else:
                timer = threading.Timer(
                    self.settings.reply_debounce,
                    self._flush_batch,
                    args=(route.session_key,),
                )
                timer.daemon = True
                self._batch_timers[route.session_key] = timer
                timer.start()

        if batch is not None:
            self._executor.submit(self._process_batch, batch)

    def _flush_batch(self, session_key: str) -> None:
        with self._batch_lock:
            self._batch_timers.pop(session_key, None)
            batch = self._batches.pop(session_key, None)
        if batch:
            self._executor.submit(self._process_batch, batch)

    def _drop_batch(self, session_key: str) -> None:
        with self._batch_lock:
            timer = self._batch_timers.pop(session_key, None)
            if timer is not None:
                timer.cancel()
            self._batches.pop(session_key, None)
            self._session_generation[session_key] = self._session_generation.get(session_key, 0) + 1

    def _generation(self, session_key: str) -> int:
        with self._batch_lock:
            return self._session_generation.get(session_key, 0)

    def _build_messages(self, persona, history, user_text, summary="", **kwargs):
        return build_messages(
            persona,
            history,
            user_text,
            max_images=self.settings.prompt_max_images,
            max_image_side=self.settings.prompt_max_image_side,
            jpeg_quality=self.settings.prompt_image_quality,
            summary=summary,
            **kwargs,
        )

    def _process_batch(self, batch: list[RouteResult]) -> None:
        if not batch:
            return
        if self.paused:
            return
        session_key = batch[0].session_key
        lock = self._session_lock(session_key)
        with lock:
            generation = self._generation(session_key)
            routes = batch
            if all(route.is_sticker for route in routes) and random.random() >= self.settings.sticker_reply_rate:
                logger.info("表情包跳过回复，会话=%s", session_key)
                return

            banter = all(route.group_banter for route in routes)
            persona = routes[-1].persona
            texts = [route.user_text.strip() for route in routes if route.user_text.strip()]
            image_paths = [route.image_path for route in routes if route.image_path]
            file_paths = [route.file_path for route in routes if route.file_path]
            file_names = [route.file_name for route in routes if route.file_name]
            user_text = "\n".join(texts)
            if not user_text and image_paths:
                user_text = "请看看这张图片。"
            elif not user_text and file_paths:
                user_text = "请看看这份 PDF。"
            if not user_text and not image_paths and not file_paths:
                return

            history = self.store.recent_messages(session_key, persona.max_history)
            search_query = "" if banter else plan_search(
                self.settings,
                self.llm,
                user_text,
                history,
            )
            ctx = enrich_message(
                self.settings,
                session_key,
                user_text,
                image_paths,
                file_paths,
                file_names,
                history,
                banter,
                search_query,
            )
            image_paths = ctx.image_paths

            self.store.add_message(session_key, "user", ctx.stored_text, sender=routes[-1].sender_name)
            summary = self.store.get_summary(session_key)
            messages = self._build_messages(
                persona,
                history,
                user_text,
                summary,
                image_paths=image_paths,
                ocr_text=ctx.ocr_text,
                document_text=ctx.doc_text,
                document_name=file_names[0] if file_names else "",
                search_text=ctx.search_text,
                video_text=ctx.video_text,
                link_text=ctx.link_text,
                contact_name=routes[-1].sender_name,
                banter=banter,
            )

            if banter:
                token_budget = 800
            elif image_paths:
                token_budget = max(persona.max_tokens, 3000)
            elif file_paths:
                token_budget = max(persona.max_tokens, 2500)
            else:
                token_budget = persona.max_tokens
            if ctx.search_text:
                token_budget = max(token_budget, 2500)
            if ctx.video_text:
                token_budget = max(token_budget, 3500)
            if ctx.link_text:
                token_budget = max(token_budget, 3000)
            try:
                reply = self.llm.chat(
                    messages,
                    model=persona.model or self.settings.default_model,
                    temperature=persona.temperature,
                    max_tokens=token_budget,
                )
            except DeepSeekError as exc:
                if "空内容" in str(exc):
                    logger.warning("模型返回空内容，提高 token 预算后重试，会话=%s", session_key)
                    try:
                        reply = self.llm.chat(
                            messages,
                            model=persona.model or self.settings.default_model,
                            temperature=persona.temperature,
                            max_tokens=4000,
                        )
                    except DeepSeekError:
                        logger.exception("重试后仍无法生成回复，会话=%s，人设=%s", session_key, persona.key)
                        if self.settings.send_error_notice:
                            self._send(session_key, "抱歉，我刚刚走神了，请稍后再试。")
                        return
                else:
                    logger.exception("生成回复失败，会话=%s，人设=%s", session_key, persona.key)
                    if self.settings.send_error_notice:
                        self._send(session_key, "抱歉，我刚刚走神了，请稍后再试。")
                    return

            if self._generation(session_key) != generation:
                logger.info("会话状态已变化，丢弃过期回复，会话=%s", session_key)
                return

            reply = self._sanitize(reply)
            if not reply:
                reply = "嗯嗯，我在。"
            self.store.add_message(session_key, "assistant", reply.replace("|||", "\n"))
            logger.info(
                "已回复会话=%s 人设=%s 消息数=%s 图片数=%s 字符数=%s",
                session_key,
                persona.key,
                len(routes),
                len(image_paths),
                len(reply),
            )

            last = routes[-1]
            at_wxid = last.sender_id if last.chat_type == ChatType.GROUP and last.is_group_mention else ""
            at_name = last.sender_name if at_wxid else ""
            self._send(session_key, reply, at_wxid, at_name)

    def _session_lock(self, session_key: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._session_locks.get(session_key)
            if lock is None:
                lock = threading.Lock()
                self._session_locks[session_key] = lock
            return lock
