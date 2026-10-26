import logging
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor

from .config import Settings
from .media import MediaContext, merge_media_contexts, parse_media
from .models import RouteResult

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://", re.I)


class MediaParser:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="media-parse")
        self._futures: dict[str, Future] = {}
        self._lock = threading.Lock()

    @staticmethod
    def should_parse(route: RouteResult) -> bool:
        if route.group_banter:
            return False
        if route.image_path or route.file_path:
            return True
        return bool(URL_RE.search(route.user_text or ""))

    def submit(self, route: RouteResult) -> None:
        if not self.should_parse(route):
            return
        with self._lock:
            if route.msg_id in self._futures:
                return
            future = self._executor.submit(
                parse_media,
                self.settings,
                route.session_key,
                route.user_text,
                [route.image_path] if route.image_path else [],
                [route.file_path] if route.file_path else [],
                route.group_banter,
            )
            self._futures[route.msg_id] = future

    def collect(self, routes: list[RouteResult]) -> MediaContext | None:
        contexts: list[MediaContext] = []
        missing = False
        for route in routes:
            if not self.should_parse(route):
                continue
            with self._lock:
                future = self._futures.pop(route.msg_id, None)
            if future is None:
                missing = True
                continue
            try:
                contexts.append(future.result(timeout=180))
            except Exception:
                logger.warning("媒体预解析失败，会话=%s，msg_id=%s", route.session_key, route.msg_id, exc_info=True)
                missing = True
        if missing:
            return None
        if not contexts:
            return None
        return merge_media_contexts(contexts)

    def discard(self, routes: list[RouteResult]) -> None:
        with self._lock:
            for route in routes:
                future = self._futures.pop(route.msg_id, None)
                if future is not None:
                    future.cancel()

    def close(self) -> None:
        with self._lock:
            futures = list(self._futures.values())
            self._futures.clear()
        for future in futures:
            future.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)
