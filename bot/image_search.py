import logging
import re

from .config import Settings
from .llm.aimodel import AIModelClient, AIModelError
from .prompt import image_data_url

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是图片搜索词生成器。看图片后只输出适合搜索引擎的简短关键词：
发色、发型、瞳色、服装、配饰、画风、明显文字或 logo。
不要猜角色名、作品名或画师名。不要解释、不要引号、不要 Markdown。
最多 30 个字，用空格分隔。"""


def generate_image_search_query(
    settings: Settings,
    llm: AIModelClient,
    model: str,
    image_paths: list[str],
    user_text: str = "",
) -> str:
    parts: list[dict] = [{"type": "text", "text": "请为这张图片生成搜索关键词。"}]
    if user_text.strip():
        parts[0]["text"] = f"用户想识别这张图。用户消息：{user_text.strip()[:100]}"
    for path in image_paths[: settings.prompt_max_images]:
        data_url = image_data_url(
            path,
            settings.prompt_max_image_side,
            settings.prompt_image_quality,
        )
        if data_url:
            parts.append({"type": "image_url", "image_url": {"url": data_url}})
    if len(parts) == 1:
        return ""

    try:
        raw = llm.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": parts},
            ],
            model=model,
            temperature=0.0,
            max_tokens=96,
            request_timeout=30,
        )
    except AIModelError:
        logger.warning("图片搜索词生成失败", exc_info=True)
        return ""

    query = re.sub(r"^(搜索词|关键词)[:：]\s*", "", raw.strip())
    query = query.replace("\n", " ")
    query = re.sub(r"[\"'“”‘’`*#]", "", query)
    query = re.sub(r"[，,。；;].*$", "", query).strip()
    return query[:60]
