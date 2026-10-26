import re
from collections.abc import Sequence

from .models import HistoryMessage

STICKER_MARKER_PATTERN = re.compile(
    r"[（(](?:表情包|动画表情|收到一个表情包[^）)]*|图片[^）)]*)[）)]"
)

STICKER_QUERY_CUES = (
    "表情包", "表情", "动图", "gif",
    "这个图", "这张图", "这图", "图片",
    "看看", "看下", "看一下", "瞧瞧", "瞅瞅",
    "什么梗", "什么意思", "这是啥", "是什么", "是啥",
    "像谁", "是谁", "认识吗", "评价", "可爱吗", "好笑吗",
    "发个表情", "来个表情", "发张图", "来张图",
)

NEGATIVE_PATTERNS = (
    re.compile(r"(?:不要|别|不用|甭)(?:再)?(?:发|来|用)?[^，。！？]{0,4}(?:表情|图)"),
)


def clean_sticker_text(text: str) -> str:
    return STICKER_MARKER_PATTERN.sub(" ", text or "").strip()


def is_sticker_question(text: str) -> bool:
    cleaned = clean_sticker_text(text)
    if not cleaned:
        return False
    if any(pattern.search(cleaned) for pattern in NEGATIVE_PATTERNS):
        return False
    return any(cue in cleaned.lower() for cue in STICKER_QUERY_CUES)


def wants_sticker_reply(texts: Sequence[str], history: Sequence[HistoryMessage]) -> bool:
    if any(is_sticker_question(text) for text in texts):
        return True
    recent_user = [item.content for item in history if item.role == "user"][-3:]
    return any(is_sticker_question(text) for text in recent_user)
