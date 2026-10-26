import random
import re
import time

SENSITIVE_REPLACEMENTS = {
    "主人": "你",
    "瞅瞅": "看看",
}

ACTION_WORDS = (
    "尾巴", "歪头", "歪了歪", "甩", "叹", "笑", "看", "想", "挠", "眨", "伸", "摸",
    "小声", "轻声", "压低", "凑近", "鼓", "叉腰", "点头", "摇头", "拍", "晃", "转",
    "眯", "哈欠", "嘀咕", "嘟囔", "挑眉", "耸肩", "低头", "抬头", "盯", "揉", "蹭",
    "蜷", "瘫", "懒腰", "耳朵", "鳍", "懒", "无奈", "认真", "随意", "淡淡", "默默",
    "好奇", "疑惑", "得意", "开心", "委屈", "无语", "尴尬", "坏笑", "偷笑", "苦笑",
    "叹气", "摇", "歪", "瞟", "瞥", "瞪", "翻白眼", "摊手", "摆手", "挥手", "戳",
    "捏", "抱", "靠", "坐", "站", "躺", "趴", "滚", "摆", "抖", "哼", "咳", "顿",
    "沉默", "安静",
)

ACTION_PATTERN = re.compile(r"[（(]([^（）()]{1,40})[）)]")
LEADING_ACTION_PATTERN = re.compile(r"^\s*[（(]([^（）()]{1,20})[）)]\s*")
REPEAT_STRIP_RE = re.compile(r"[\s\*_`#，。！？!?、,.;:：\"“”'‘’()（）\[\]【】\-]+")


def _repeat_key(text: str) -> str:
    return REPEAT_STRIP_RE.sub("", text or "").lower()

META_LINE_PATTERNS = (
    re.compile(r"^(用户|对方|他|她)(想|要|需要|希望|问|在问|说的是)"),
    re.compile(r"^(等等|等一下|稍等)[^。！？!?]*(搜|查|先)"),
    re.compile(r"^(好[，,]?\s*)?(我|让我|我来)(先)?(搜索|搜一下|搜搜|搜下|查一下|查一查|查下|查询)"),
    re.compile(r"^(搜一下|搜索一下|搜搜|查一下|查一查|先搜|先查)"),
    re.compile(r"(让我|我来)(搜索|搜一下|搜搜|查一下|查一查|查下)"),
    re.compile(r"(我|咱)(需要|应该|得)(先)?(搜索|搜一下|搜搜|查一下|查一查|查下)"),
    re.compile(r"(搜索工具|调用搜索|系统提示|提示词|作为助手|AI助手|根据设定)"),
)


class SendingMixin:
    def _strip_target_prefix(self, text: str) -> str:
        name = self.settings.reply_target_name.strip()
        if not name:
            return text
        return re.sub(rf"^\s*{re.escape(name)}\s*[，,、:：]\s*", "", text)

    def _sanitize(self, text: str) -> str:
        text = re.sub(r"<ds_safety>.*?</ds_safety>", "", text, flags=re.S | re.I)
        text = re.sub(r"</?ds_safety>", "", text, flags=re.I)
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.S)
        text = re.sub(r"__(.+?)__", r"\1", text, flags=re.S)
        text = self._strip_target_prefix(text)
        for word, replacement in SENSITIVE_REPLACEMENTS.items():
            text = text.replace(word, replacement)
        text = self._strip_meta(text)
        text = re.sub(r"\n+", "|||", text)
        text = self._dedupe_repeated(text)
        return self._strip_actions(text)

    @staticmethod
    def _dedupe_repeated(text: str) -> str:
        parts = text.split("|||")
        seen = set()
        kept = []
        for part in parts:
            key = _repeat_key(part)
            if len(key) >= 8 and key in seen:
                continue
            if key:
                seen.add(key)
            kept.append(part)
        return "|||".join(kept)

    @staticmethod
    def _strip_meta(text: str) -> str:
        kept = []
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped and any(pattern.search(stripped) for pattern in META_LINE_PATTERNS):
                continue
            kept.append(line)
        cleaned = "\n".join(kept)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @staticmethod
    def _strip_actions(text: str) -> str:
        leading = LEADING_ACTION_PATTERN.match(text)
        if leading:
            inner = leading.group(1)
            if re.search(r"[\u4e00-\u9fff]", inner) and not re.search(r"[0-9A-Za-z]", inner):
                text = text[leading.end():]

        def replace(match: re.Match) -> str:
            inner = match.group(1)
            return "" if any(word in inner for word in ACTION_WORDS) else match.group(0)

        text = ACTION_PATTERN.sub(replace, text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _split_bubbles(
        text: str,
        limit: int = 80,
        max_bubbles: int = 8,
        split_limit: int = 1500,
    ) -> list[str]:
        raw = [part.strip() for part in re.split(r"\|\|\||\n+", text) if part.strip()]
        bubbles: list[str] = []
        for part in raw:
            if len(part) <= split_limit:
                bubbles.append(part)
                continue

            sentences = [
                segment.strip()
                for segment in re.split(r"(?<=[。！？!?])(?=[^。！？!?])", part)
                if segment.strip()
            ]
            current = ""
            for sentence in sentences:
                if len(sentence) > limit:
                    if current:
                        bubbles.append(current)
                        current = ""
                    bubbles.append(sentence)
                    continue
                candidate = f"{current}{sentence}" if current else sentence
                if len(candidate) <= limit:
                    current = candidate
                else:
                    if current:
                        bubbles.append(current)
                    current = sentence
            if current:
                bubbles.append(current)

        cleaned = [bubble.rstrip("。").strip() for bubble in bubbles if bubble.strip()]
        unique = []
        seen = set()
        for bubble in cleaned:
            key = _repeat_key(bubble)
            if len(key) >= 8 and key in seen:
                continue
            if key:
                seen.add(key)
            unique.append(bubble)
        return unique[:max_bubbles]

    def _send(
        self,
        session_key: str,
        text: str,
        at_wxid: str = "",
        at_name: str = "",
        split: bool = True,
        max_bubbles: int | None = None,
    ) -> None:
        text = self._strip_target_prefix(text).strip()
        if not text:
            return
        if not split:
            self.adapter.send_text(session_key, text, at_wxid, at_name)
            return

        limit = self.settings.max_bubbles
        if max_bubbles is not None:
            limit = max(1, min(limit, max_bubbles))
        bubbles = self._split_bubbles(
            text,
            limit=self.settings.bubble_limit,
            max_bubbles=limit,
            split_limit=self.settings.split_limit,
        )
        first = True
        for bubble in bubbles:
            bubble = self._strip_target_prefix(bubble).strip()
            if not bubble:
                continue
            for chunk in self._split_text(bubble, self.settings.split_limit):
                if not first:
                    time.sleep(
                        random.uniform(
                            self.settings.send_delay_min,
                            self.settings.send_delay_max,
                        )
                    )
                self.adapter.send_text(session_key, chunk, at_wxid if first else "", at_name)
                first = False

    @staticmethod
    def _split_text(text: str, limit: int) -> list[str]:
        if limit <= 0 or len(text) <= limit:
            return [text] if text else []
        chunks: list[str] = []
        current = ""
        for paragraph in text.split("\n"):
            candidate = f"{current}\n{paragraph}" if current else paragraph
            if len(candidate) <= limit:
                current = candidate
                continue
            if current:
                chunks.append(current)
                current = ""
            remaining = paragraph
            while len(remaining) > limit:
                cut = remaining.rfind("。", 0, limit)
                cut = cut + 1 if cut >= limit // 2 else limit
                chunks.append(remaining[:cut])
                remaining = remaining[cut:]
            current = remaining
        if current:
            chunks.append(current)
        return [chunk for chunk in chunks if chunk.strip()]
