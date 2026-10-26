import logging
import re
from datetime import datetime
from typing import Sequence

from .config import Settings
from .llm.aimodel import AIModelClient, AIModelError
from .media import build_search_query
from .models import HistoryMessage
from .search import simplify_query

logger = logging.getLogger(__name__)

EXPLICIT_SEARCH_TRIGGERS = (
    "搜一下", "搜索", "搜搜", "搜下", "帮我搜", "上网搜", "联网搜", "网上搜",
    "百度一下", "百度", "查一下", "查下", "帮我查", "网上查", "查查",
)

PREFILTER_HINTS = (
    "吗", "呢", "什么", "怎么", "怎么样", "多少", "哪", "谁", "何时",
    "为什么", "是不是", "有没有", "能不能", "会不会", "要不要",
    "看看", "了解", "最新", "现在", "今天", "明天", "最近",
)

MIN_QUESTION_CHARS = 6


def wants_explicit_search(text: str) -> bool:
    return any(trigger in text for trigger in EXPLICIT_SEARCH_TRIGGERS) or text.strip().endswith("搜")


def looks_like_question(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return len(compact) >= MIN_QUESTION_CHARS and any(
        hint in text for hint in PREFILTER_HINTS
    )


def _history_text(history: Sequence[HistoryMessage]) -> str:
    lines = []
    for item in history[-6:]:
        content = " ".join(item.content.split())[:200]
        if content:
            lines.append(f"{item.role}: {content}")
    return "\n".join(lines)


def _ask(
    settings: Settings,
    llm: AIModelClient,
    messages: list[dict],
    max_tokens: int,
) -> str:
    try:
        return llm.chat(
            messages,
            model=settings.default_model,
            temperature=0.0,
            max_tokens=max_tokens,
        )
    except AIModelError as exc:
        if "空内容" not in str(exc):
            raise
        logger.info("搜索规划返回空内容，提高 token 后重试")
        return llm.chat(
            messages,
            model=settings.default_model,
            temperature=0.0,
            max_tokens=max(256, max_tokens * 2),
        )


def _generate_query(
    settings: Settings,
    llm: AIModelClient,
    text: str,
    history: Sequence[HistoryMessage],
    force: bool,
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    context = _history_text(history)

    if force:
        system = (
            "你把用户的搜索请求改写成适合搜索引擎的简短查询词。"
            "查询词尽量短，保留核心对象和地点，不要把日期、当前、实时等词堆在一起。"
            "只输出查询词，不要解释、引号或标点。"
        )
        user = f"当前时间：{now}\n用户：{text}"
        max_tokens = settings.search_query_max_tokens
    else:
        system = (
            "你是搜索规划器。判断用户消息是否需要联网查询外部或最新信息才能可靠回答。"
            "需要就输出一行：SEARCH: 查询词；不需要就只输出 NO_SEARCH。"
            "查询词要短，保留核心对象和地点，不要把日期、当前、实时等词堆在一起。"
            "不要解释，不要输出其他内容。"
        )
        user = f"当前时间：{now}\n"
        if context:
            user += f"最近对话：\n{context}\n\n"
        user += f"用户：{text}"
        max_tokens = settings.search_intent_max_tokens

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        answer = _ask(settings, llm, messages, max_tokens)
    except Exception:
        logger.warning("搜索规划失败", exc_info=True)
        return simplify_query(build_search_query(text, history)) if force else ""

    answer = answer.strip().strip("\"'“”")
    if not force:
        if "NO_SEARCH" in answer.upper():
            return ""
        match = re.search(r"SEARCH\s*[:：]\s*(.+)", answer, re.I | re.S)
        if match:
            return simplify_query(match.group(1).strip().split("\n")[0][:120])
        if answer.upper().startswith("SEARCH"):
            return simplify_query(build_search_query(text, history))
        return ""

    query = re.sub(r"^\s*SEARCH\s*[:：]\s*", "", answer, flags=re.I)
    query = query.split("\n")[0].strip()
    return simplify_query(query[:120] or build_search_query(text, history))


def plan_search(
    settings: Settings,
    llm: AIModelClient,
    text: str,
    history: Sequence[HistoryMessage],
) -> str:
    text = (text or "").strip()
    if not text or not settings.web_search:
        return ""
    if wants_explicit_search(text):
        return _generate_query(settings, llm, text, history, force=True)
    if not settings.search_intent_enabled:
        return ""
    if not looks_like_question(text):
        return ""
    return _generate_query(settings, llm, text, history, force=False)

