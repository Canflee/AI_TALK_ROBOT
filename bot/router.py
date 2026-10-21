import random

from .memory import MemoryStore
from .models import ChatType, IncomingMessage, RouteResult
from .personas import PersonaRegistry

class Router:
    def __init__(self, registry: PersonaRegistry, store: MemoryStore, banter_rate: float):
        self.registry = registry
        self.store = store
        self.banter_rate = banter_rate

    def route(self, msg: IncomingMessage) -> RouteResult | None:
        text = msg.content.strip()
        if not text and not msg.image_path and not msg.file_path:
            return None

        persona = self.registry.resolve(msg.session_key, self.store.get_persona_key(msg.session_key))
        if persona.whitelist and msg.session_key not in persona.whitelist:
            return None

        matched = self._match(msg, persona, text)
        if matched is None:
            if (
                msg.chat_type == ChatType.GROUP
                and not msg.is_at_me
                and persona.trigger != "off"
                and not msg.image_path
                and not msg.file_path
                and not msg.is_sticker
                and random.random() < self.banter_rate
            ):
                return RouteResult(
                    persona=persona,
                    user_text=text,
                    session_key=msg.session_key,
                    chat_type=msg.chat_type,
                    sender_id=msg.sender_id,
                    sender_name=msg.sender_name,
                    msg_id=msg.msg_id,
                    group_banter=True,
                )
            return None
        user_text, is_group_mention = matched

        return RouteResult(
            persona=persona,
            user_text=user_text,
            session_key=msg.session_key,
            chat_type=msg.chat_type,
            sender_id=msg.sender_id,
            sender_name=msg.sender_name,
            msg_id=msg.msg_id,
            is_group_mention=is_group_mention,
            image_path=msg.image_path,
            file_path=msg.file_path,
            file_name=msg.file_name,
            is_sticker=msg.is_sticker,
        )

    def _match(self, msg: IncomingMessage, persona, text: str) -> tuple[str, bool] | None:
        if persona.trigger == "off":
            return None

        if persona.trigger == "prefix":
            if not text.startswith(persona.prefix):
                return None
            cleaned = text[len(persona.prefix):].strip()
            return (cleaned, False) if cleaned else None

        if msg.chat_type == ChatType.GROUP:
            if persona.trigger != "mention" or not msg.is_at_me:
                return None
            cleaned = self._strip_leading_mention(text)
            return (cleaned, True) if cleaned else None

        return text, False

    @staticmethod
    def _strip_leading_mention(text: str) -> str:
        if not text.startswith("@"):
            return text.strip()
        first, sep, rest = text.partition("\u2005")
        if sep:
            return rest.strip()
        if " " in text:
            return text.split(" ", 1)[1].strip()
        return ""
