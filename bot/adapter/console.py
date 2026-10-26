import logging
import sys
import threading
import uuid

from ..models import ChatType, IncomingMessage
from .base import ChatAdapter

logger = logging.getLogger(__name__)


class ConsoleAdapter(ChatAdapter):
    def __init__(self, bot_name: str):
        self.bot_name = bot_name
        self._running = False
        self._thread: threading.Thread | None = None
        self._on_message = None

    def start(self, on_message) -> None:
        self._on_message = on_message
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="console-input", daemon=True)
        self._thread.start()
        print("控制台模式已启动，直接输入内容回车即可对话，Ctrl+C 退出。")

    def _loop(self) -> None:
        while self._running:
            try:
                line = sys.stdin.readline()
            except Exception:
                logger.exception("读取控制台输入失败")
                break
            if not line:
                break
            text = line.strip()
            if not text:
                continue
            if text in {"/quit", "/exit"}:
                print("再见。")
                break
            message = IncomingMessage(
                msg_id=f"console-{uuid.uuid4().hex}",
                session_key="console-session",
                chat_type=ChatType.PRIVATE,
                sender_id="console",
                sender_name="你",
                content=text,
                is_at_me=True,
            )
            try:
                self._on_message(message)
            except Exception:
                logger.exception("处理控制台消息失败")

    def send_text(self, session_key: str, text: str, at_wxid: str = "", at_name: str = "") -> bool:
        print(f"\n{self.bot_name}: {text}\n")
        return True

    def send_file(self, session_key: str, path: str) -> bool:
        print(f"\n{self.bot_name} 发送文件: {path}\n")
        return True

    def stop(self) -> None:
        self._running = False
