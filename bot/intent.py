import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from .llm.aimodel import AIModelClient, AIModelError
from .models import HistoryMessage

logger = logging.getLogger(__name__)

VALID_INTENTS = {"chat", "search", "reminder", "answer"}
WEEKDAYS = ("一", "二", "三", "四", "五", "六", "日")

SYSTEM_PROMPT = """你是微信聊天意图分类器。根据最近对话、当前时间和用户消息，只输出一行 JSON：
{"intent":"chat|search|reminder|answer","query":"","reminder":null,"image_search":false}

规则：
- chat：纯聊天、情绪、吐槽、问候。
- search：需要联网查询实时、最新或外部信息。
- reminder：用户提到未来时间/条件 + 事件，需要提醒对方；或者明确要求提醒。
- answer：要求解答题目、做作业、解释知识、分析图片或文件、写完整答案。
- 如果附带图片，用户想识别、搜索或了解图片里的人物、角色、作品、物品，或者明确要求搜图，image_search 设为 true；只是让你描述图片、看内容或做题时设为 false。
- image_search=true 时 intent 可以是 answer，query 留空，由后续逻辑生成图片特征词再联网搜。
- query 只在 search 时填写，写成简短搜索词，不要堆日期、当前、实时等冗余词；其他意图留空。

reminder 识别规则（重要）：
- 用户说"明天下午三点开会""后天九点见""明天记得吃药""后天记得交报告"等隐含提醒 → 识别为 reminder
- 用户说"提醒我明天下午三点开会" → 识别为 reminder
- 用户说"明天下午三点有个会" + 上下文提到提醒 → 识别为 reminder
- 条件提醒："上海天晴了提醒我""金价到 890 提醒我" → 识别为 condition reminder
- 时间提醒："明天七点""后天九点" → 识别为 time reminder
- 不确定时选 chat。

reminder 字段：
{"kind":"time|condition","content":"要提醒的事情","time":"YYYY-MM-DD HH:MM","condition":"条件","interval_minutes":0}
- 时间提醒：time 必须是完整的本地日期时间，且必须是未来时间。用户说"今天/今晚/明天"时按当前时间推算；如果按今天算该时间已经过去，就写成明天同一时间，绝对不要输出过去时间。
- 内容提醒：content 只写要提醒的事情，去掉"提醒我/叫我一声/哦对了/一下"等填充词。如果只是叫一声，content 写"到点了"。
- 条件提醒：condition 写条件本身，例如"上海天晴了""金价到达 890"；用户说"每 5 分钟"时 interval_minutes 填 5，否则填 0。
- 取消/修改提醒时 reminder 可以为 null，由后续逻辑处理。

示例（当前时间 2026-10-25 19:00）：
用户：哦对了今天七点一刻叫我一声
{"intent":"reminder","query":"","reminder":{"kind":"time","content":"到点了","time":"2026-10-25 19:15","condition":"","interval_minutes":0},"image_search":false}

用户：上海天晴了提醒我
{"intent":"reminder","query":"","reminder":{"kind":"condition","content":"","time":"","condition":"上海天晴了","interval_minutes":0},"image_search":false}

用户附带图片：搜一下这个是谁
{"intent":"answer","query":"","reminder":null,"image_search":true}

用户附带图片：描述一下这张图
{"intent":"answer","query":"","reminder":null,"image_search":false}

只输出 JSON，不要解释、不要 Markdown。"""


@dataclass(slots=True)
class ReminderIntent:
    kind: str
    content: str = ""
    due_at: datetime | None = None
    condition: str = ""
    interval_minutes: int = 0


@dataclass(slots=True)
class IntentResult:
    intent: str
    query: str = ""
    reminder: ReminderIntent | None = None
    image_search: bool = False


def _history_text(history: Sequence[HistoryMessage]) -> str:
    lines = []
    for item in history[-6:]:
        content = " ".join(item.content.split())[:200]
        if content:
            lines.append(f"{item.role}: {content}")
    return "\n".join(lines)


def _parse_due(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _clean_content(value: str) -> str:
    content = (value or "").strip().strip("，,。；;！!？?")
    content = re.sub(r"^(哦?对了|提醒我|提醒你|叫我|叫你|通知我|告诉我)\s*", "", content)
    content = re.sub(r"(一下|一声)$", "", content).strip()
    if content in {"", "提醒", "叫", "提醒我", "叫你", "叫你一声", "叫我", "叫我一声", "叫一声"}:
        return "到点了"
    return content[:100]


def _clean_condition(value: str) -> str:
    condition = (value or "").strip().strip("，,。；;！!？?")
    condition = re.sub(r"(的时候|时)?(提醒我|通知我|告诉我|叫我).*$", "", condition).strip()
    return condition[:200]


def classify_intent(
    llm: AIModelClient,
    model: str,
    text: str,
    history: Sequence[HistoryMessage],
    has_image: bool = False,
    has_file: bool = False,
    has_link: bool = False,
) -> IntentResult | None:
    message = (text or "").strip()
    if not message and not (has_image or has_file or has_link):
        return None

    now = datetime.now()
    now_text = now.strftime("%Y-%m-%d %H:%M") + f" 星期{WEEKDAYS[now.weekday()]}"
    user_parts = [f"当前时间：{now_text}"]
    context = _history_text(history)
    if context:
        user_parts.append(f"最近对话：\n{context}")
    flags = []
    if has_image:
        flags.append("附带图片")
    if has_file:
        flags.append("附带文件")
    if has_link:
        flags.append("包含链接")
    if flags:
        user_parts.append("附件标记：" + "、".join(flags))
    user_parts.append(f"用户消息：{message or '（无文字，只有附件）'}")

    try:
        raw = llm.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "\n\n".join(user_parts)},
            ],
            model=model,
            temperature=0.0,
            max_tokens=320,
            request_timeout=30,
        )
    except AIModelError:
        logger.warning("意图分类失败", exc_info=True)
        return None

    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        logger.warning("意图分类返回无法解析: %s", raw[:200])
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("意图分类 JSON 解析失败: %s", raw[:200])
        return None
    intent = str(data.get("intent") or "").strip().lower()
    if intent not in VALID_INTENTS:
        return None
    query = str(data.get("query") or "").strip()[:120]
    raw_image_search = data.get("image_search")
    image_search = str(raw_image_search).strip().lower() in {"1", "true", "yes", "on"}
    image_search = image_search and has_image
    reminder = None
    reminder_data = data.get("reminder")
    if intent == "reminder" and isinstance(reminder_data, dict):
        kind = str(reminder_data.get("kind") or "").strip().lower()
        if kind in {"time", "condition"}:
            try:
                interval = int(reminder_data.get("interval_minutes") or 0)
            except (TypeError, ValueError):
                interval = 0
            reminder = ReminderIntent(
                kind=kind,
                content=_clean_content(str(reminder_data.get("content") or "")),
                due_at=_parse_due(str(reminder_data.get("time") or "")),
                condition=_clean_condition(str(reminder_data.get("condition") or "")),
                interval_minutes=max(0, interval),
            )
    return IntentResult(intent=intent, query=query, reminder=reminder, image_search=image_search)
