import logging
import random
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

logger = logging.getLogger(__name__)


class AutoProactiveScheduler:
    def __init__(
        self,
        target: str,
        generate: Callable[[str, object], bool],
        video_provider: Callable[[], object | None],
        quiet_start: float,
        quiet_end: float,
        min_minutes: int,
        max_minutes: int,
        interval: float,
        start_delay: float,
        video_rate: float,
        active_skip_minutes: int,
        retry_min_minutes: float,
        retry_max_minutes: float,
        activity_provider: Callable[[], datetime | None] | None = None,
        hold_provider: Callable[[], bool] | None = None,
    ):
        self.target = target
        self.generate = generate
        self.video_provider = video_provider
        self.activity_provider = activity_provider
        self.hold_provider = hold_provider
        self.quiet_start = quiet_start
        self.quiet_end = quiet_end
        self.min_minutes = max(1, min_minutes)
        self.max_minutes = max(self.min_minutes, max_minutes)
        self.interval = interval
        self.start_delay = start_delay
        self.video_rate = video_rate
        self.active_skip_seconds = max(0, active_skip_minutes) * 60
        self.retry_min_seconds = max(0.0, retry_min_minutes) * 60
        self.retry_max_seconds = max(self.retry_min_seconds, retry_max_minutes * 60)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="auto-proactive", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _last_activity_ts(self) -> float | None:
        if self.activity_provider is None:
            return None
        value = self.activity_provider()
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()

    def _in_quiet(self, now: datetime) -> bool:
        hour = now.hour + now.minute / 60 + now.second / 3600
        if self.quiet_start <= self.quiet_end:
            return self.quiet_start <= hour < self.quiet_end
        return hour >= self.quiet_start or hour < self.quiet_end

    def _next_quiet_start(self, now: datetime) -> datetime:
        hour = int(self.quiet_start)
        minute = int((self.quiet_start - hour) * 60)
        start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start <= now:
            start += timedelta(days=1)
        return start

    def _next_gap(self) -> float:
        return random.uniform(self.min_minutes * 60, self.max_minutes * 60)

    def _run(self) -> None:
        self._stop.wait(self.start_delay)
        last_seen = self._last_activity_ts()
        next_at = (last_seen if last_seen is not None else time.time()) + self._next_gap()

        while not self._stop.wait(self.interval):
            now_dt = datetime.now()
            last_ts = self._last_activity_ts()

            if last_ts is not None and (last_seen is None or last_ts > last_seen + 1):
                last_seen = last_ts
                next_at = max(last_ts + self._next_gap(), time.time() + 30)
                logger.info("检测到新的聊天，主动消息重新计时")

            if not self._in_quiet(now_dt):
                continue
            if time.time() < next_at:
                continue
            if self.hold_provider and self.hold_provider():
                continue
            if last_ts is not None and time.time() - last_ts < self.active_skip_seconds:
                next_at = last_ts + self._next_gap()
                logger.info("最近有聊天，主动消息顺延")
                continue

            video = None
            if random.random() < self.video_rate:
                try:
                    video = self.video_provider()
                except Exception:
                    logger.warning("主动消息获取视频失败", exc_info=True)

            try:
                sent = self.generate(self.target, video)
            except Exception:
                logger.exception("主动消息生成失败")
                sent = False

            if sent:
                gap = self._next_gap()
                logger.info("已发送主动消息，下一次约在 %s 分钟后", round(gap / 60))
                next_at = time.time() + gap
            else:
                next_at = time.time() + random.uniform(self.retry_min_seconds, self.retry_max_seconds)
