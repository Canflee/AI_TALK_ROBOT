import logging
import random
import threading
import time
from datetime import datetime
from typing import Callable

logger = logging.getLogger(__name__)

FIRST_LINES = ("怎么不回我", "干嘛不回消息", "人呢，咋不理我", "咋还不理我")
LATER_LINES = ("你是不是把我忘了", "忙啥呢，都不理人", "咋还不回我", "还不回，真忙啊", "我还在等你回呢", "消息看到没")


class FollowUpScheduler:
    def __init__(
        self,
        target: str,
        send: Callable[[str, str], None],
        quiet_start: float,
        quiet_end: float,
        first_delay: float,
        min_interval: float,
        max_interval: float,
        check_interval: float,
    ):
        self.target = target
        self.send = send
        self.quiet_start = quiet_start
        self.quiet_end = quiet_end
        self.first_delay = first_delay
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.check_interval = check_interval
        self._awaiting = False
        self._first = False
        self._next_at = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="follow-up", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def start_waiting(self) -> None:
        with self._lock:
            self._awaiting = True
            self._first = True
            self._next_at = time.time() + self.first_delay
        logger.info("主动消息已发出，%s 分钟后未回复将追问", int(self.first_delay // 60))

    def cancel(self) -> None:
        with self._lock:
            if self._awaiting:
                logger.info("收到用户消息，停止追问")
            self._awaiting = False
            self._first = False

    def is_waiting(self) -> bool:
        with self._lock:
            return self._awaiting

    def _in_quiet(self, now: datetime) -> bool:
        hour = now.hour + now.minute / 60 + now.second / 3600
        if self.quiet_start <= self.quiet_end:
            return self.quiet_start <= hour < self.quiet_end
        return hour >= self.quiet_start or hour < self.quiet_end

    def _run(self) -> None:
        while not self._stop.wait(self.check_interval):
            with self._lock:
                if not self._awaiting:
                    continue
                next_at = self._next_at
                first = self._first
            if not self._in_quiet(datetime.now()):
                continue
            if time.time() < next_at:
                continue

            line = random.choice(FIRST_LINES if first else LATER_LINES)
            try:
                self.send(self.target, line)
            except Exception:
                logger.exception("发送追问失败")
                with self._lock:
                    self._next_at = time.time() + 5 * 60
                continue

            with self._lock:
                self._first = False
                self._next_at = time.time() + random.uniform(self.min_interval, self.max_interval)
            logger.info("已发送追问: %s", line)
