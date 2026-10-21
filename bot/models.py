from dataclasses import dataclass, field
from enum import Enum


class ChatType(str, Enum):
    PRIVATE = "private"
    GROUP = "group"


@dataclass(slots=True)
class IncomingMessage:
    msg_id: str
    session_key: str
    chat_type: ChatType
    sender_id: str
    sender_name: str
    content: str
    is_at_me: bool = False
    room_id: str = ""
    image_path: str = ""
    file_path: str = ""
    file_name: str = ""
    is_sticker: bool = False


@dataclass(slots=True)
class HistoryMessage:
    role: str
    content: str
    sender: str = ""


@dataclass(slots=True)
class Persona:
    key: str
    display_name: str
    system_prompt: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 1200
    max_history: int = 20
    max_context_chars: int = 6000
    cooldown: float = 2.0
    trigger: str = "private_all"
    prefix: str = ""
    whitelist: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RouteResult:
    persona: Persona
    user_text: str
    session_key: str
    chat_type: ChatType
    sender_id: str
    sender_name: str
    msg_id: str
    is_group_mention: bool = False
    image_path: str = ""
    file_path: str = ""
    file_name: str = ""
    is_sticker: bool = False
    group_banter: bool = False
