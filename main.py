import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bot.adapter.console import ConsoleAdapter
from bot.adapter.wechatauto import WeChat4Adapter
from bot.bot import WeChatBot
from bot.config import load_settings
from bot.llm.deepseek import DeepSeekClient
from bot.memory import MemoryStore
from bot.personas import PersonaRegistry
from bot.wechat_check import check_weixin4


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
    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"配置错误: {exc}")
        return 1
    setup_logging(settings.log_level)
    logger = logging.getLogger("main")

    if not settings.api_key:
        logger.error("未配置 DEEPSEEK_API_KEY，请复制 .env.example 为 .env 并填写")
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
    llm = DeepSeekClient(
        settings.api_key,
        settings.base_url,
        settings.deepseek_timeout_seconds,
        settings.deepseek_max_retries,
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
