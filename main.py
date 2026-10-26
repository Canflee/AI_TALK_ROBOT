import atexit
import ctypes
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bot.adapter.console import ConsoleAdapter
from bot.adapter.wechatauto import WeChat4Adapter
from bot.bot import WeChatBot
from bot.config import load_settings
from bot.llm.aimodel import AIModelClient
from bot.memory import MemoryStore
from bot.personas import PersonaRegistry
from bot.wechat_check import check_weixin4

_SINGLE_INSTANCE_MUTEX = "Local\\ai_talk_bot_single_instance"
_mutex_handle = None
_kernel32 = None


def _get_kernel32():
    global _kernel32
    if _kernel32 is None:
        lib = ctypes.WinDLL("kernel32", use_last_error=True)
        lib.CreateMutexW.restype = ctypes.c_void_p
        lib.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
        lib.CloseHandle.argtypes = (ctypes.c_void_p,)
        _kernel32 = lib
    return _kernel32


def _acquire_single_instance() -> bool:
    global _mutex_handle
    if sys.platform != "win32":
        return True
    kernel32 = _get_kernel32()
    handle = kernel32.CreateMutexW(None, False, _SINGLE_INSTANCE_MUTEX)
    if not handle:
        return True
    if ctypes.get_last_error() == 183:
        kernel32.CloseHandle(handle)
        return False
    _mutex_handle = handle
    return True


def _release_single_instance() -> None:
    global _mutex_handle
    if _mutex_handle is None:
        return
    _get_kernel32().CloseHandle(_mutex_handle)
    _mutex_handle = None


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    for name in ("openai", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def main() -> int:
    if not _acquire_single_instance():
        print("已有 ai_talk 实例在运行，请先关闭旧的 run.bat / main.py")
        return 1
    atexit.register(_release_single_instance)

    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"配置错误: {exc}")
        return 1
    setup_logging(settings.log_level)
    logger = logging.getLogger("main")

    if not settings.api_key:
        logger.error("未配置 AIMODEL_API_KEY，请复制 .env.example 为 .env 并填写")
        return 1

    if settings.adapter not in {"wechatauto", "console"}:
        logger.error("ADAPTER 只能是 wechatauto 或 console，当前为: %s", settings.adapter)
        return 1

    if settings.adapter == "wechatauto" and not settings.skip_wechat_check:
        problem = check_weixin4()
        if problem:
            logger.error("%s", problem)
            return 1

    try:
        registry = PersonaRegistry.load(settings.personas_path, settings.default_model)
    except (OSError, ValueError) as exc:
        logger.error("加载人设配置失败: %s", exc)
        return 1

    store = MemoryStore(settings.db_path)
    llm = AIModelClient(
        settings.api_key,
        settings.base_url,
        settings.aimodel_timeout_seconds,
        settings.aimodel_max_retries,
        settings.llm_extra_body,
    )
    if settings.adapter == "console":
        adapter = ConsoleAdapter(settings.bot_name)
    else:
        adapter = WeChat4Adapter(
            interval=settings.wechat4_interval,
            max_file_bytes=settings.wechat_max_file_mb * 1024 * 1024,
            max_sticker_bytes=settings.wechat_max_sticker_mb * 1024 * 1024,
        )
    bot = WeChatBot(settings, registry, store, llm, adapter)

    if not settings.admin_wxids:
        logger.warning("未配置 ADMIN_WXIDS，仅 #id 和 #help 可用")

    try:
        bot.run()
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        bot.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
