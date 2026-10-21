import base64
import io
import logging
from datetime import datetime

from .models import HistoryMessage, Persona

logger = logging.getLogger(__name__)

WEEKDAYS = ("一", "二", "三", "四", "五", "六", "日")


def image_data_url(path: str, max_side: int, quality: int) -> str:
    try:
        from PIL import Image

        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((max_side, max_side))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=quality)
        return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
    except Exception:
        logger.warning("读取图片失败: %s", path, exc_info=True)
        return ""


def build_messages(
    persona: Persona,
    history: list[HistoryMessage],
    user_text: str,
    max_images: int,
    max_image_side: int,
    jpeg_quality: int,
    summary: str = "",
    image_paths: list[str] | None = None,
    ocr_text: str = "",
    document_text: str = "",
    document_name: str = "",
    search_text: str = "",
    video_text: str = "",
    link_text: str = "",
    contact_name: str = "",
    banter: bool = False,
) -> list[dict]:
    system = persona.system_prompt
    now = datetime.now()
    time_text = now.strftime("%Y年%m月%d日 %H:%M") + f" 星期{WEEKDAYS[now.weekday()]}"
    system = (
        f"{system}\n\n[当前时间] {time_text}（本地时间，以此为准；"
        "被问现在几点/今天几号就直接回答，不要用搜索结果里的日期）"
    )
    system = (
        f"{system}\n\n[输出要求] 只输出最终要发给对方的消息。"
        "不要输出分析、计划、搜索过程、内心独白，也不要写“用户想…”“我搜一下…”“让我查一下…”“等等”这类话。"
        "如果这轮没有搜索结果，不要假装正在搜索；直接回答或说没查到。"
        "回答尽量短，除非对方要求详细；最多 3 条气泡，每条控制在 40 字内。"
    )
    if contact_name.strip():
        system = (
            f"{system}\n\n[对方微信名] {contact_name.strip()}"
            "（这是对方的名字，不是聊天内容，也不要把它当成某个术语）"
        )
    if banter:
        system = (
            f"{system}\n\n[群聊旁听模式] 这些只是群里的闲聊，对方没 @ 你。"
            "你只随口接一句吐槽或客套，不要认真回答，不要提供信息、建议或步骤，"
            "不要问问题，最多 15 个字。"
        )
    if summary.strip():
        system = f"{system}\n\n[此前对话摘要]\n{summary.strip()}"

    budget = max(persona.max_context_chars - len(user_text), 0)
    selected: list[HistoryMessage] = []
    used = 0
    for item in reversed(history):
        cost = len(item.content)
        if used + cost > budget:
            break
        selected.append(item)
        used += cost
    selected.reverse()

    messages: list[dict] = [{"role": "system", "content": system}]
    messages.extend(
        {"role": item.role, "content": item.content}
        for item in selected
        if item.role in {"user", "assistant"}
    )

    final_text = user_text.strip()
    if ocr_text.strip():
        final_text = (
            f"{final_text}\n\n[图片文字识别（可能有误，请结合图片核对）]\n{ocr_text.strip()[:4000]}"
        ).strip()
    if document_text.strip():
        label = f"PDF文字内容：{document_name}" if document_name else "PDF文字内容"
        final_text = (
            f"{final_text}\n\n[{label}（可能有误，请结合上下文核对）]\n{document_text.strip()[:6000]}"
        ).strip()
    if search_text.strip():
        final_text = (
            f"{final_text}\n\n[联网搜索结果（优先使用带今天/小时前/当前年月的最新信息；"
            "旧年份结果只作背景，不要当成当前情况；不确定就说不确定，不要编造）]\n"
            f"{search_text.strip()[:4000]}"
        ).strip()
    if video_text.strip():
        final_text = (
            f"{final_text}\n\n[视频信息（标题/简介/字幕/抽样画面；没有音频时不要编台词）]\n"
            f"{video_text.strip()[:5000]}"
        ).strip()
    if link_text.strip():
        final_text = (
            f"{final_text}\n\n[公众号文章正文（可能不完整，以此为准，不要编造）]\n"
            f"{link_text.strip()[:6000]}"
        ).strip()
    if not final_text and document_text.strip():
        final_text = "请看看这份 PDF。"
    if not final_text and search_text.strip():
        final_text = "请根据搜索结果回答。"
    if not final_text and video_text.strip():
        final_text = "请看看这个视频。"
    if not final_text and link_text.strip():
        final_text = "请看看这篇文章。"

    paths = [path for path in (image_paths or []) if path][:max_images]
    if paths:
        parts: list[dict] = [{"type": "text", "text": final_text or "请看看这张图片。"}]
        for path in paths:
            data_url = image_data_url(path, max_image_side, jpeg_quality)
            if data_url:
                parts.append({"type": "image_url", "image_url": {"url": data_url}})
        if len(parts) == 1:
            user_content: object = f"{final_text}\n(图片读取失败)".strip()
        else:
            user_content = parts
    else:
        user_content = final_text

    messages.append({"role": "user", "content": user_content})
    return messages
