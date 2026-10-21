import logging
import threading
from datetime import datetime, timedelta
from typing import Callable

from .conditions import ConditionEvaluator
from .reminders import ReminderStore

logger = logging.getLogger(__name__)


class ConditionReminderScheduler:
    def __init__(
        self,
        store: ReminderStore,
        evaluator: ConditionEvaluator,
        send: Callable[[str, str], None],
        check_interval: float,
        interval_minutes: int,
        retry_minutes: int,
        expire_days: int,
    ):
        self.store = store
        self.evaluator = evaluator
        self.send = send
        self.check_interval = check_interval
        self.interval_minutes = interval_minutes
        self.retry_minutes = retry_minutes
        self.expire_days = expire_days
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="condition-reminder-scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.check_interval):
            try:
                self._check()
            except Exception:
                logger.exception("检查条件提醒失败")

    def _check(self) -> None:
        now = datetime.now()
        for row in self.store.due_conditions(now.isoformat(timespec="seconds")):
            reminder_id = row["id"]
            session_key = str(row["session_key"])
            condition = str(row["condition_text"])

            if session_key.endswith("@chatroom"):
                self.store.mark_done(reminder_id)
                logger.info("跳过群聊条件提醒 id=%s", reminder_id)
                continue

            expires_at = self._parse_time(row["expires_at"])
            if expires_at is not None and now >= expires_at:
                self.send(session_key, f"这个提醒（{condition}）超过 {self.expire_days} 天还没成立，我先取消了")
                self.store.mark_done(reminder_id)
                logger.info("条件提醒已过期 id=%s 条件=%s", reminder_id, condition)
                continue

            try:
                result = self.evaluator.evaluate(condition)
            except Exception:
                logger.exception("评估条件提醒失败 id=%s 条件=%s", reminder_id, condition)
                result = None

            if result is True:
                self.send(session_key, f"提醒你：{condition}")
                self.store.mark_done(reminder_id)
                logger.info("已发送条件提醒 id=%s 会话=%s 条件=%s", reminder_id, session_key, condition)
                continue

            interval = int(row["check_interval_minutes"] or self.interval_minutes)
            delay = interval if result is False else min(self.retry_minutes, interval)
            next_at = now + timedelta(minutes=delay)
            label = "YES" if result is True else "NO" if result is False else "UNKNOWN"
            self.store.reschedule_condition(reminder_id, next_at, label)
            logger.info(
                "条件未满足 id=%s 条件=%s 结果=%s 下次=%s",
                reminder_id,
                condition,
                label,
                next_at.strftime("%H:%M"),
            )

    @staticmethod
    def _parse_time(value) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None
