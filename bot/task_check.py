import json
import logging
import re
from dataclasses import dataclass
from typing import Sequence

from .llm.aimodel import AIModelClient, AIModelError
from .models import HistoryMessage

logger = logging.getLogger(__name__)

VALID_ACTIONS = {"none", "web_search", "bilibili_search"}

SYSTEM_PROMPT = """你是微信聊天任务完成检查器。根据最近对话、用户这轮消息和机器人回复，判断用户的任务是否已经完成。
只输出一行 JSON：
{"done":true|false,"action":"none|web_search|bilibili_search","query":"","reason":""}

规则：
- 普通聊天、情绪、玩笑、问候，done=true，action=none。
- 已经给出答案、文件、链接、图片结果，done=true，action=none。
- 如果用户明确要求找链接、找视频、搜索实时信息，而机器人只说“正在搜 / 等一下 / 马上发 / 稍后”但没有给出实际结果，done=false。
- 如果上下文是找 B 站视频、动画、番剧、UP 主，action=bilibili_search；其他找信息用 web_search。
- done=false 且需要继续找时，query 填简短搜索词；其他情况 query 留空。
- 不要因为机器人说了“等一下”就认为完成；也不要在普通聊天里硬找东西。
- 不确定时 done=true，避免无意义重复。
- 只输出 JSON，不要解释、不要 Markdown。"""


@dataclass(slots=True)
class TaskCheck:
    done: bool
    action: str = "none"
    query: str = ""
    reason: str = ""


def _history_text(history: Sequence[HistoryMessage]) -> str:
    lines = []
    for item in history[-8:]:
        content = " ".join(item.content.split())[:300]
        if content:
            label = "对方" if item.role == "user" else "机器人"
            lines.append(f"{label}: {content}")
    return "\n".join(lines)


def check_task(
    llm: AIModelClient,
    model: str,
    user_text: str,
    reply: str,
    history: Sequence[HistoryMessage],
) -> TaskCheck | None:
    user_parts = []
    context = _history_text(history)
    if context:
        user_parts.append(f"最近对话：\n{context}")
    user_parts.append(f"用户这轮消息：{user_text[:1000]}")
    user_parts.append(f"机器人回复：{reply[:1500]}")

    try:
        raw = llm.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "\n\n".join(user_parts)},
            ],
            model=model,
            temperature=0.0,
            max_tokens=256,
            request_timeout=30,
        )
    except AIModelError:
        logger.warning("任务完成检查失败", exc_info=True)
        return None

    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        logger.warning("任务完成检查返回无法解析: %s", raw[:200])
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("任务完成检查 JSON 解析失败: %s", raw[:200])
        return None

    done = bool(data.get("done"))
    raw_action = str(data.get("action") or "none").strip().lower()
    action = raw_action if raw_action in VALID_ACTIONS else "none"
    query = str(data.get("query") or "").strip()[:120]
    reason = str(data.get("reason") or "").strip()[:200]
    if done:
        action = "none"
    return TaskCheck(done=done, action=action, query=query, reason=reason)
