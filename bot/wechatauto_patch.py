import logging
import tempfile
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_OPEN_LOCK = threading.RLock()
_INSTALLED = False


def _is_transient_file_error(exc: Exception) -> bool:
    if isinstance(exc, PermissionError):
        return True
    return getattr(exc, "winerror", None) in (32, 33)


def _cleanup_stale_temp_files() -> None:
    root = Path(tempfile.gettempdir()) / "wechatauto_db"
    if not root.exists():
        return
    cutoff = time.time() - 3600
    for path in root.rglob("*.tmp*"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def install_wechatauto_db_retry() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from wechatauto.db import WeChatDB

    original = WeChatDB._open
    if getattr(original, "__ai_talk_retry__", False):
        _INSTALLED = True
        return

    def _open_with_retry(self, rel, *args, **kwargs):
        delay = 0.15
        with _OPEN_LOCK:
            for attempt in range(6):
                try:
                    return original(self, rel, *args, **kwargs)
                except Exception as exc:
                    if not _is_transient_file_error(exc) or attempt == 5:
                        raise
                    logger.warning(
                        "微信数据库文件被占用，重试 %s/5: %s",
                        attempt + 1,
                        exc,
                    )
                    time.sleep(delay)
                    delay = min(delay * 1.7, 2.0)

    _open_with_retry.__ai_talk_retry__ = True
    WeChatDB._open = _open_with_retry
    _cleanup_stale_temp_files()
    _INSTALLED = True
    logger.info("已启用微信数据库访问重试")
