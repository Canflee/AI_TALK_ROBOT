import logging
from datetime import datetime, timedelta

from .models import ChatType, IncomingMessage
from .reminders import _build_due, _to_int, time_matches

logger = logging.getLogger(__name__)


class ReminderMixin:
    def _handle_reminder(self, message: IncomingMessage, request) -> None:
        if message.chat_type == ChatType.GROUP:
            self._send(message.session_key, "提醒只在私聊里设，群里我就不主动发了")
            return
        reminder_id = self.reminder_store.add_time(
            message.session_key,
            request.due_at,
            request.content,
        )
        when = request.due_at.strftime("%m-%d %H:%M")
        suffix = "" if request.content == "到点了" else f"：{request.content}"
        self._send(message.session_key, f"好，{when} 提醒你{suffix}")
        logger.info("已设置定时提醒 id=%s 会话=%s 时间=%s", reminder_id, message.session_key, when)

    def _handle_cancel_all_reminders(self, message: IncomingMessage) -> None:
        if message.chat_type == ChatType.GROUP:
            self._send(message.session_key, "提醒只在私聊里设，群里我就不主动发了")
            return
        count = self.reminder_store.cancel_all(message.session_key)
        if count:
            self._send(message.session_key, f"好，已取消 {count} 条提醒")
            logger.info("已取消全部提醒 会话=%s 数量=%s", message.session_key, count)
        else:
            self._send(message.session_key, "现在没有待提醒的事")

    def _handle_update_reminder(self, message: IncomingMessage, text: str) -> None:
        if message.chat_type == ChatType.GROUP:
            self._send(message.session_key, "提醒只在私聊里设，群里我就不主动发了")
            return
        rows = [
            row for row in self.reminder_store.list_pending(message.session_key)
            if row["kind"] == "time"
        ]
        matches = time_matches(text)
        if not matches:
            return

        old_match = matches[0] if len(matches) >= 2 else None
        change_words = ("改成", "换成", "改为", "改到")
        new_match = matches[-1] if len(matches) >= 2 else (
            matches[0] if any(word in text for word in change_words) else None
        )

        target = None
        old_due = _build_due(old_match) if old_match else None
        if old_due:
            for row in rows:
                due = self._parse_due(row["due_at"])
                if due and due.strftime("%H:%M") == old_due.strftime("%H:%M"):
                    target = row
                    break
        if target is None and rows:
            target = rows[-1]
            old_due = self._parse_due(target["due_at"])

        if new_match is None:
            if target is None:
                self._send(message.session_key, "没找到要取消的提醒")
                return
            when = old_due.strftime("%m-%d %H:%M") if old_due else "那条"
            self.reminder_store.cancel(message.session_key, target["id"])
            self._send(message.session_key, f"好，已取消 {when} 的提醒")
            return

        new_due = _build_due(new_match)
        if new_due is None:
            self._send(message.session_key, "这个时间我没看懂")
            return
        if old_due and new_match.group("day") is None and not new_match.group("period"):
            hour = _to_int(new_match.group("hour"))
            minute = _to_int(new_match.group("minute") or "0") or 0
            if hour is not None and hour < 12 and old_due.hour >= 12:
                candidate = old_due.replace(hour=hour + 12, minute=minute, second=0, microsecond=0)
                if candidate <= datetime.now():
                    candidate += timedelta(days=1)
                new_due = candidate

        if target is not None:
            self.reminder_store.cancel(message.session_key, target["id"])
        content = str(target["content"]) if target is not None else ""
        if not content:
            content = "到点了"
        self.reminder_store.add_time(message.session_key, new_due, content)
        when = new_due.strftime("%m-%d %H:%M")
        if old_due:
            self._send(
                message.session_key,
                f"好，已把 {old_due.strftime('%m-%d %H:%M')} 改成 {when} 提醒你",
            )
        else:
            self._send(message.session_key, f"好，{when} 提醒你")
        logger.info(
            "已更新提醒 会话=%s 旧=%s 新=%s",
            message.session_key,
            old_due.strftime("%m-%d %H:%M") if old_due else "",
            when,
        )

    def _handle_cancel_recent_reminder(self, message: IncomingMessage) -> None:
        if message.chat_type == ChatType.GROUP:
            self._send(message.session_key, "提醒只在私聊里设，群里我就不主动发了")
            return
        rows = [
            row for row in self.reminder_store.list_pending(message.session_key)
            if row["kind"] == "time"
        ]
        if not rows:
            self._send(message.session_key, "现在没有要取消的提醒")
            return
        target = rows[-1]
        due = self._parse_due(target["due_at"])
        self.reminder_store.cancel(message.session_key, target["id"])
        when = due.strftime("%m-%d %H:%M") if due else "最近那条"
        self._send(message.session_key, f"好，已取消 {when} 的提醒")
        logger.info("已取消最近提醒 会话=%s id=%s", message.session_key, target["id"])

    def _handle_correct_reminder_time(self, message: IncomingMessage, text: str) -> None:
        if message.chat_type == ChatType.GROUP:
            self._send(message.session_key, "提醒只在私聊里设，群里我就不主动发了")
            return
        rows = [
            row for row in self.reminder_store.list_pending(message.session_key)
            if row["kind"] == "time"
        ]
        if not rows:
            self._send(message.session_key, "现在没有要修改的提醒")
            return
        matches = time_matches(text)
        if not matches:
            return
        target = rows[-1]
        old_due = self._parse_due(target["due_at"])
        new_match = matches[-1]
        new_due = _build_due(new_match)
        if new_due is None:
            self._send(message.session_key, "这个时间我没看懂")
            return
        if old_due and new_match.group("day") is None and not new_match.group("period"):
            hour = _to_int(new_match.group("hour"))
            minute = _to_int(new_match.group("minute") or "0") or 0
            if hour is not None and hour < 12 and old_due.hour >= 12:
                candidate = old_due.replace(hour=hour + 12, minute=minute, second=0, microsecond=0)
                if candidate <= datetime.now():
                    candidate += timedelta(days=1)
                new_due = candidate

        self.reminder_store.cancel(message.session_key, target["id"])
        content = str(target["content"]) or "到点了"
        self.reminder_store.add_time(message.session_key, new_due, content)
        when = new_due.strftime("%m-%d %H:%M")
        self._send(message.session_key, f"好，改成 {when} 提醒你")
        logger.info(
            "已修正提醒时间 会话=%s 旧=%s 新=%s",
            message.session_key,
            old_due.strftime("%m-%d %H:%M") if old_due else "",
            when,
        )

    @staticmethod
    def _parse_due(value) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    def _handle_condition_reminder(self, message: IncomingMessage, request) -> None:
        if message.chat_type == ChatType.GROUP:
            self._send(message.session_key, "提醒只在私聊里设，群里我就不主动发了")
            return
        expires_at = datetime.now() + timedelta(days=self.settings.condition_expire_days)
        interval = request.interval_minutes or self.settings.condition_interval_minutes
        reminder_id = self.reminder_store.add_condition(
            message.session_key,
            request.condition,
            interval,
            expires_at,
        )
        self._send(
            message.session_key,
            f"好，我每 {interval} 分钟看一下，"
            f"{request.condition} 就提醒你",
        )
        logger.info(
            "已设置条件提醒 id=%s 会话=%s 条件=%s",
            reminder_id,
            message.session_key,
            request.condition,
        )
