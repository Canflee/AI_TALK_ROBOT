import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from .adapter.base import ChatAdapter
from .auto_proactive import AutoProactiveScheduler
from .commands import CommandMixin
from .condition_reminders import ConditionReminderScheduler
from .conditions import ConditionEvaluator
from .config import Settings
from .documents.flow import DocumentMixin
from .documents.reader import is_document_path
from .followup import FollowUpScheduler
from .image_search import generate_image_search_query
from .intent import IntentResult, classify_intent
from .link_check import available_bilibili_videos, available_web_results
from .llm.aimodel import AIModelClient, AIModelError
from .media import enrich_message
from .media_parser import MediaParser
from .memory import MemoryStore
from .models import ChatType, IncomingMessage, RouteResult
from .pacing import IncomingPacer
from .personas import PersonaRegistry
from .proactive_flow import ProactiveMixin
from .prompt import build_messages
from .random_video import random_bilibili_video, search_bilibili_videos
from .reminder_flow import ReminderMixin
from .reminders import (
    ReminderRequest,
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
from .search import search_web
from .search_intent import plan_search
from .sending import SendingMixin
from .sticker_intent import wants_sticker_reply
from .task_check import check_task

logger = logging.getLogger(__name__)


class WeChatBot(CommandMixin, ReminderMixin, ProactiveMixin, SendingMixin, DocumentMixin):
    def __init__(
        self,
        settings: Settings,
        registry: PersonaRegistry,
        store: MemoryStore,
        llm: AIModelClient,
        adapter: ChatAdapter,
    ):
        self.settings = settings
        self.registry = registry
        self.store = store
        self.llm = llm
        self.adapter = adapter
        self._init_documents()
        self.router = Router(registry, store, banter_rate=settings.group_banter_rate)
        self._executor = ThreadPoolExecutor(max_workers=settings.max_workers, thread_name_prefix="reply")
        self._task_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="task-check")
        self._session_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._stop_event = threading.Event()
        self.paused = False
        self.incoming_pacer = IncomingPacer(
            settings.incoming_pause_every,
            settings.incoming_pause_min_seconds,
            settings.incoming_pause_max_seconds,
        )
        self.media_parser = MediaParser(settings)
        self._recent_media: dict[str, tuple[float, list[str], list[str], str]] = {}
        self._batch_lock = threading.Lock()
        self._batches: dict[str, list[RouteResult]] = {}
        self._batch_timers: dict[str, threading.Timer] = {}
        self._session_generation: dict[str, int] = {}
        self.reminder_store = ReminderStore(settings.db_path)
        self.reminder_scheduler = ReminderScheduler(
            self.reminder_store,
            self._send_reminder,
            time_interval=settings.reminder_check_seconds,
        )
        self.condition_scheduler = ConditionReminderScheduler(
            self.reminder_store,
            ConditionEvaluator(settings, self.llm),
            self._send_reminder,
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
        self._shutdown_documents()
        self.media_parser.close()
        self.adapter.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._task_executor.shutdown(wait=False, cancel_futures=True)

    def _send_reminder(self, session_key: str, text: str) -> None:
        self.store.add_message(session_key, "assistant", text)
        self._send(session_key, text)

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
        self._cancel_document_ack(message.session_key)
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

        self.incoming_pacer.note(message.session_key)

        if message.image_path or message.file_path:
            self._recent_media[message.session_key] = (
                time.time(),
                [message.image_path] if message.image_path else [],
                [message.file_path] if message.file_path else [],
                message.content or "",
            )

        if (
            message.chat_type == ChatType.PRIVATE
            and message.file_path
            and is_document_path(message.file_path)
        ):
            job_id = self._register_document_job(
                message.session_key,
                message.msg_id,
                message.file_path,
                message.file_name,
            )
            if job_id is not None:
                self._doc_executor.submit(self._ingest_document, job_id)
                return

        if self._maybe_handle_document_instruction(message):
            return
        if self._maybe_handle_media_document_request(message):
            return
        if self._maybe_handle_export_request(message):
            return

        intent = self._classify_message_intent(message)

        if (message.chat_type == ChatType.PRIVATE or message.is_at_me) and (
            intent is None or intent.intent == "reminder"
        ):
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
            llm_reminder = self._reminder_from_intent(intent)
            if llm_reminder is not None:
                if llm_reminder.kind == "time":
                    self._executor.submit(self._handle_reminder, message, llm_reminder)
                else:
                    self._executor.submit(self._handle_condition_reminder, message, llm_reminder)
                return
            if intent is not None and intent.reminder is not None:
                if message.chat_type == ChatType.GROUP:
                    self._send(message.session_key, "提醒只在私聊里设，群里我就不主动发了")
                else:
                    self._send(
                        message.session_key,
                        "没太确定提醒时间或条件，可以再说一遍，例如“晚上八点提醒我”或“下雨了提醒我”",
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
            if intent is not None:
                if message.chat_type == ChatType.GROUP:
                    self._send(message.session_key, "提醒只在私聊里设，群里我就不主动发了")
                else:
                    self._send(
                        message.session_key,
                        "没太听懂要提醒什么，可以说“晚上八点提醒我”或“下雨了提醒我”",
                    )
                return

        route = self.router.route(message)
        if route is None:
            return
        if intent is not None:
            route.intent = intent.intent
            route.intent_query = intent.query
            route.answer_mode = intent.intent == "answer"
            route.image_search = intent.image_search
        self.media_parser.submit(route)
        self._enqueue(route)

    def _classify_message_intent(self, message: IncomingMessage) -> IntentResult | None:
        if message.chat_type != ChatType.PRIVATE and not message.is_at_me:
            return None
        recent = self._recent_media.get(message.session_key)
        recent_active = recent is not None and time.time() - recent[0] <= 600
        has_image = bool(message.image_path) or bool(recent_active and recent[1])
        has_file = bool(message.file_path) or bool(recent_active and recent[2])
        has_link = (
            "http://" in message.content
            or "https://" in message.content
            or bool(recent_active and ("http://" in recent[3] or "https://" in recent[3]))
        )
        try:
            history = self.store.recent_messages(message.session_key, 8)
            result = classify_intent(
                self.llm,
                self.settings.default_model,
                message.content,
                history,
                has_image=has_image,
                has_file=has_file,
                has_link=has_link,
            )
        except Exception:
            logger.warning("意图识别失败，回退规则", exc_info=True)
            return None
        if result is not None:
            logger.info(
                "意图识别 会话=%s 意图=%s 图片搜索=%s",
                message.session_key,
                result.intent,
                result.image_search,
            )
        return result

    def _reminder_from_intent(self, intent: IntentResult | None) -> ReminderRequest | None:
        if intent is None or intent.reminder is None:
            return None
        reminder = intent.reminder
        if reminder.kind == "time":
            if reminder.due_at is None:
                return None
            if reminder.due_at <= datetime.now() - timedelta(seconds=60):
                logger.info("模型提醒时间已过去，改为询问: %s", reminder.due_at)
                return None
            return ReminderRequest(
                kind="time",
                content=reminder.content or "到点了",
                due_at=reminder.due_at,
            )
        if reminder.kind == "condition":
            condition = reminder.condition.strip()
            if not condition:
                return None
            return ReminderRequest(
                kind="condition",
                condition=condition,
                interval_minutes=reminder.interval_minutes or 0,
            )
        return None

    def _enqueue(self, route: RouteResult) -> None:
        batch: list[RouteResult] | None = None
        with self._batch_lock:
            timer = self._batch_timers.pop(route.session_key, None)
            if timer is not None:
                timer.cancel()

            items = self._batches.setdefault(route.session_key, [])
            items.append(route)
            total_chars = sum(len(item.user_text) for item in items)
            hard_limit = (
                len(items) >= self.settings.batch_max_messages
                or total_chars >= max(self.settings.batch_max_chars * 4, 8000)
            )

            if self.settings.reply_debounce <= 0 or hard_limit:
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
            batch = self._batches.pop(session_key, None)
            self._session_generation[session_key] = self._session_generation.get(session_key, 0) + 1
        if batch:
            self.media_parser.discard(batch)

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
            link_max_chars=min(
                self.settings.web_link_max_chars * self.settings.web_link_max_pages,
                30000,
            ),
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
            self.incoming_pacer.wait(session_key)
            if self._generation(session_key) != generation:
                logger.info("会话状态已变化，丢弃过期回复，会话=%s", session_key)
                return
            routes = batch
            preparsed = self.media_parser.collect(routes)
            persona = routes[-1].persona
            history = self.store.recent_messages(session_key, persona.max_history)
            sticker_routes = [route for route in routes if route.is_sticker]
            all_stickers = all(route.is_sticker for route in routes)
            sticker_question = wants_sticker_reply(
                [route.user_text for route in routes],
                history if all_stickers else [],
            )
            if sticker_question:
                logger.info("表情包被追问，强制回复，会话=%s", session_key)
            if (
                sticker_routes
                and not sticker_question
                and all_stickers
                and random.random() >= self.settings.sticker_reply_rate
            ):
                logger.info("表情包跳过回复，会话=%s", session_key)
                return

            if sticker_routes and not any(route.image_path for route in sticker_routes):
                capture = getattr(self.adapter, "capture_sticker", None)
                if capture is not None:
                    captured = capture(session_key)
                    if captured:
                        for route in sticker_routes:
                            route.user_text = "(表情包)"
                            if not route.image_path:
                                route.image_path = captured

            banter = all(route.group_banter for route in routes)
            texts = [route.user_text.strip() for route in routes if route.user_text.strip()]
            image_paths = [route.image_path for route in routes if route.image_path]
            file_paths = [route.file_path for route in routes if route.file_path]
            file_names = [route.file_name for route in routes if route.file_name]
            user_text = "\n".join(texts)
            if not user_text and image_paths:
                user_text = "请看看这张图片。"
            elif not user_text and file_paths:
                user_text = "请看看这份文档。"
            if not user_text and not image_paths and not file_paths:
                return

            image_search = any(route.image_search for route in routes)
            if image_search and not image_paths:
                recent = self._recent_media.get(session_key)
                if recent is not None and time.time() - recent[0] <= 600:
                    image_paths = [path for path in recent[1] if path]
                    if preparsed is not None:
                        for path in image_paths:
                            if path not in preparsed.image_paths:
                                preparsed.image_paths.append(path)
            if not image_paths:
                image_search = False

            intents = [route for route in routes if route.intent]
            answer_mode = any(route.answer_mode for route in routes) or image_search
            if image_search:
                search_query = ""
                if self.settings.web_search:
                    search_query = generate_image_search_query(
                        self.settings,
                        self.llm,
                        persona.model or self.settings.default_model,
                        image_paths,
                        user_text,
                    )
                    logger.info(
                        "图片识别搜索词，会话=%s 查询=%s",
                        session_key,
                        search_query or "（无）",
                    )
            elif banter:
                search_query = ""
            elif intents:
                search_query = ""
                search_routes = [route for route in routes if route.intent == "search"]
                if search_routes:
                    search_query = next(
                        (route.intent_query for route in reversed(search_routes) if route.intent_query),
                        "",
                    )
                    if not search_query:
                        search_query = plan_search(
                            self.settings,
                            self.llm,
                            user_text,
                            history,
                        )
            else:
                search_query = plan_search(
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
                preparsed=preparsed,
            )
            image_paths = ctx.image_paths

            document_name = file_names[0] if file_names else ""
            if not file_paths and routes[-1].chat_type == ChatType.PRIVATE:
                self._wait_document_text(session_key)
                job = self.document_store.latest(session_key, 30)
                if (
                    job is not None
                    and job["status"] != "cancelled"
                    and job.get("text")
                ):
                    ctx.doc_text = job["text"][:6000]
                    document_name = job["source_name"]

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
                document_name=document_name,
                search_text=ctx.search_text,
                video_text=ctx.video_text,
                link_text=ctx.link_text,
                contact_name=routes[-1].sender_name,
                banter=banter,
                answer_mode=answer_mode,
                image_search=image_search,
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
            if answer_mode:
                token_budget = max(token_budget, 3000)
            temperature = persona.temperature
            if ctx.search_text or ctx.link_text or ctx.video_text or image_paths:
                temperature = min(temperature, 0.3)
            elif answer_mode:
                temperature = min(temperature, 0.5)
            try:
                reply = self.llm.chat(
                    messages,
                    model=persona.model or self.settings.default_model,
                    temperature=temperature,
                    max_tokens=token_budget,
                )
            except AIModelError as exc:
                if "空内容" in str(exc):
                    logger.warning("模型返回空内容，提高 token 预算后重试，会话=%s", session_key)
                    try:
                        reply = self.llm.chat(
                            messages,
                            model=persona.model or self.settings.default_model,
                            temperature=temperature,
                            max_tokens=4000,
                        )
                    except AIModelError:
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

            self._send(session_key, reply)
            self._schedule_task_check(session_key, user_text, reply, history, banter)

    def _session_lock(self, session_key: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._session_locks.get(session_key)
            if lock is None:
                lock = threading.Lock()
                self._session_locks[session_key] = lock
            return lock

    def _schedule_task_check(
        self,
        session_key: str,
        user_text: str,
        reply: str,
        history,
        banter: bool,
    ) -> None:
        if banter:
            return
        self._task_executor.submit(
            self._run_task_check,
            session_key,
            user_text,
            reply,
            list(history),
            datetime.now(timezone.utc),
        )

    def _run_task_check(
        self,
        session_key: str,
        user_text: str,
        reply: str,
        history,
        reply_at: datetime,
    ) -> None:
        try:
            result = check_task(
                self.llm,
                self.settings.default_model,
                user_text,
                reply,
                history,
            )
        except Exception:
            logger.warning("任务完成检查失败，会话=%s", session_key, exc_info=True)
            return
        if result is None or result.done or result.action == "none":
            return

        last = self.store.last_user_activity(session_key)
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if last > reply_at + timedelta(seconds=2):
                logger.info("任务检查期间用户已继续发消息，跳过补发，会话=%s", session_key)
                return

        query = result.query.strip() or user_text.strip()
        if not query:
            return
        logger.info(
            "任务未完成，准备补发，会话=%s 动作=%s 查询=%s 原因=%s",
            session_key,
            result.action,
            query,
            result.reason,
        )
        if result.action == "bilibili_search":
            try:
                self._send_bilibili_task(session_key, query)
            except Exception:
                logger.exception("补发 B 站链接失败，会话=%s", session_key)
                self._send(session_key, "刚才没找到合适的链接，我再想想别的办法", split=False)
        elif result.action == "web_search":
            try:
                self._send_web_task(session_key, query)
            except Exception:
                logger.exception("补发网页链接失败，会话=%s", session_key)
                self._send(session_key, "刚才没找到合适的链接，我再想想别的办法", split=False)

    def _send_bilibili_task(self, session_key: str, query: str) -> None:
        results = available_bilibili_videos(search_bilibili_videos(query, 8), 3)
        if not results:
            self._send_web_task(session_key, query)
            return
        lines = ["找到了，给你链接："]
        for index, item in enumerate(results[:3], 1):
            lines.append(f"{index}. {item['title']}\n{item['url']}")
        text = "\n".join(lines)
        self.store.add_message(session_key, "assistant", text)
        logger.info("任务补发 B 站链接，会话=%s 查询=%s 数量=%s", session_key, query, len(results[:3]))
        self._send(session_key, text, split=False)

    def _send_web_task(self, session_key: str, query: str) -> None:
        results = available_web_results(search_web(query, 10, 0), 3)
        if not results:
            text = "没找到可用的链接，可能都失效了；换个关键词我再试试"
            self.store.add_message(session_key, "assistant", text)
            self._send(session_key, text, split=False)
            return
        lines = ["找到了这些，你看看："]
        for index, item in enumerate(results[:3], 1):
            lines.append(f"{index}. {item.title}\n{item.url}")
        text = "\n".join(lines)
        self.store.add_message(session_key, "assistant", text)
        logger.info("任务补发网页链接，会话=%s 查询=%s 数量=%s", session_key, query, len(results[:3]))
        self._send(session_key, text, split=False)
