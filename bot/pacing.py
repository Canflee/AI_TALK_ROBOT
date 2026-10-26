import logging
import random
import threading
import time

logger = logging.getLogger(__name__)


class IncomingPacer:
    def __init__(self, every: int, min_seconds: float, max_seconds: float):
        self.every = max(1, every)
        self.min_seconds = max(0.0, min_seconds)
        self.max_seconds = max(self.min_seconds, max_seconds)
        self._counts: dict[str, int] = {}
        self._next_reply_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def note(self, session_key: str) -> None:
        with self._lock:
            count = self._counts.get(session_key, 0) + 1
            if count < self.every:
                self._counts[session_key] = count
                return

            self._counts[session_key] = 0
            pause = random.uniform(self.min_seconds, self.max_seconds)
            now = time.time()
            if self._next_reply_at.get(session_key, 0.0) <= now:
                self._next_reply_at[session_key] = now + pause
        logger.info(
            "会话=%s 已收到 %s 条消息，回复前暂停 %.1f 秒",
            session_key,
            self.every,
            pause,
        )

    def wait(self, session_key: str) -> None:
        while True:
            with self._lock:
                until = self._next_reply_at.get(session_key, 0.0)
                now = time.time()
                if until <= now:
                    self._next_reply_at.pop(session_key, None)
                    return
                delay = until - now
            logger.info("会话=%s 回复前等待 %.1f 秒", session_key, delay)
            time.sleep(delay)
