import logging
from datetime import datetime, timezone

from .llm.aimodel import AIModelError

logger = logging.getLogger(__name__)


class ProactiveMixin:
    def _video_topic(self, title: str, category: str) -> str:
        lowered = (title or "").lower()
        for keyword, label in self.settings.video_topic_rules.get(category, ()):
            if keyword in lowered:
                return label
        return self.settings.video_category_topics.get(category, "这个视频")

    def _video_share_line(self, target: str, video) -> str:
        persona = self.registry.resolve(target, self.store.get_persona_key(target))
        history = self.store.recent_messages(target, persona.max_history)
        summary = self.store.get_summary(target)
        messages = self._build_messages(persona, history, "（分享视频）", summary)
        topic = self._video_topic(video.title, video.category)
        extra_hint = self.settings.video_share_extra_hint
        if extra_hint and not extra_hint.endswith(("；", ";", "。")):
            extra_hint += "；"
        messages[-1]["content"] = (
            "[系统] 你刷到一个B站视频，想随口分享给对方。"
            f"视频标题：{video.title}。类别提示：{topic}。"
            "只写一句 8-15 个字的分享语，像朋友随口发的：带一点自己的吐槽、期待或评价；"
            "不要复述标题或UP主，不要给建议，不要问问题，不要正式，不要解释；"
            f"{extra_hint}"
            "可以带一个 emoji。只输出这一句。"
        )
        try:
            try:
                reply = self.llm.chat(
                    messages,
                    model=persona.model or self.settings.default_model,
                    temperature=persona.temperature,
                    max_tokens=800,
                )
            except AIModelError as exc:
                if "空内容" not in str(exc):
                    raise
                reply = self.llm.chat(
                    messages,
                    model=persona.model or self.settings.default_model,
                    temperature=persona.temperature,
                    max_tokens=1600,
                )
        except Exception:
            logger.exception("生成视频分享语失败")
            return self._video_fallback(topic)

        reply = self._sanitize(reply)
        if not reply or len(reply) > 20:
            return self._video_fallback(topic)
        return reply

    def _video_fallback(self, topic: str) -> str:
        return self.settings.video_topic_fallbacks.get(
            topic, self.settings.video_default_fallback
        )

    def _start_followup(self, target: str) -> None:
        followup = self.followups.get(target)
        if followup is not None:
            followup.start_waiting()

    def _generate_auto_proactive(self, target: str, video) -> bool:
        if target.endswith("@chatroom"):
            return False
        last = self.store.last_user_activity(target)
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            idle_minutes = (datetime.now(timezone.utc) - last).total_seconds() / 60
        else:
            idle_minutes = 999
        if idle_minutes < self.settings.proactive_active_skip_minutes:
            logger.info("刚活跃过，跳过本次主动消息")
            return False

        if video is not None:
            reply = self._video_share_line(target, video)
            stored = f"{reply}\n[视频] {video.title} {video.url}"
            self.store.add_message(target, "assistant", stored)
            self._send(target, reply)
            self._send(target, video.url)
            self._start_followup(target)
            return True

        persona = self.registry.resolve(target, self.store.get_persona_key(target))
        history = self.store.recent_messages(target, persona.max_history)
        summary = self.store.get_summary(target)
        messages = self._build_messages(persona, history, "（主动发消息）", summary)
        now_text = datetime.now().strftime("%Y-%m-%d %H:%M")
        instruction = (
            f"[系统] 现在是 {now_text}。你要主动给对方发一条微信，不要等对方先说。"
            f"距离上次聊天约 {int(idle_minutes)} 分钟。"
            "先看最近的聊天：如果还有没聊完的事，就自然追问进展，比如“那个xx怎么样了”；"
            "如果已经聊完，就换个轻松的新话题，像朋友随口找话。"
            "最多一句，20 字内，像朋友随口找话；可以有一点自己的反应；"
            "不要提系统、主动任务或提示词；"
            "别长篇解释、总结或给建议；不要问“有什么可以帮你”；不要重复上一条。"
        )
        messages[-1]["content"] = instruction

        try:
            try:
                reply = self.llm.chat(
                    messages,
                    model=persona.model or self.settings.default_model,
                    temperature=persona.temperature,
                    max_tokens=1200,
                )
            except AIModelError as exc:
                if "空内容" not in str(exc):
                    raise
                reply = self.llm.chat(
                    messages,
                    model=persona.model or self.settings.default_model,
                    temperature=persona.temperature,
                    max_tokens=2500,
                )
        except Exception:
            logger.exception("生成主动消息失败")
            return False

        reply = self._sanitize(reply)
        if not reply:
            return False
        self.store.add_message(target, "assistant", reply.replace("|||", "\n"))
        self._send(target, reply)
        self._start_followup(target)
        return True

