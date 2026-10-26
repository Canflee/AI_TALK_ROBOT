from abc import ABC, abstractmethod
from collections.abc import Callable

from ..models import IncomingMessage


class ChatAdapter(ABC):
    @abstractmethod
    def start(self, on_message: Callable[[IncomingMessage], None]) -> None:
        raise NotImplementedError

    @abstractmethod
    def send_text(self, session_key: str, text: str, at_wxid: str = "", at_name: str = "") -> bool:
        raise NotImplementedError

    def capture_sticker(self, session_key: str) -> str:
        return ""

    def send_file(self, session_key: str, path: str) -> bool:
        return False

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError
