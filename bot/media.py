import logging
import re
from dataclasses import dataclass, field
from typing import Sequence

from .article import extract_wechat_article_url, fetch_wechat_article
from .config import Settings
from .models import HistoryMessage
from .ocr import ocr_image
from .pdf import extract_pdf_text
from .search import fetch_page_text, format_results, search_web
from .video import download_frames, extract_bilibili_url, fetch_bilibili_info

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MediaContext:
    image_paths: list[str] = field(default_factory=list)
    video_text: str = ""
    link_text: str = ""
    ocr_text: str = ""
    doc_text: str = ""
    search_text: str = ""
    search_query: str = ""
    stored_text: str = ""


def clean_search_subject(text: str) -> str:
    text = re.sub(r"\[(?:图片|PDF|搜索)[^\]]*\]", " ", text, flags=re.I)
    text = re.sub(r"\((?:图片|PDF)[^)]*\)", " ", text, flags=re.I)
    text = re.sub(r"^(这是|这个是|这是来自|这是从|这个)", "", text)
    text = re.sub(r"^(你|您)?(直接|先|就)?", "", text)
    text = re.sub(r"(里的人物|里面的人物|的角色|里的角色|中的人物|的人物|图片|图里|截图)", " ", text)
    text = re.sub(r"[，,。.!！？?~：:；;]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"的$", "", text).strip()


def strip_search_words(text: str) -> str:
    text = re.sub(r"^(你)?(看看|看一下|瞧瞧)\s*", "", text)
    text = re.sub(
        r"(帮我|给我|请|麻烦|你)?"
        r"(搜索一下|搜一下|搜搜|搜下|搜索|查一下|查下|查查|百度一下|百度|联网|上网|网上|搜)",
        " ",
        text,
    )
    text = re.sub(r"\s+", " ", text).strip(" ，,。.!！？?~")
    text = re.sub(r"(看看|看一下|瞧瞧|查查|搜搜)$", "", text).strip()
    return re.sub(r"的$", "", text).strip()


def build_search_query(text: str, history: Sequence[HistoryMessage]) -> str:
    current = strip_search_words(clean_search_subject(text))
    compact = current.replace(" ", "")
    generic = {
        "", "啊", "你去", "你去啊", "你", "搜一下吧", "查一下",
        "你搜到了啥", "搜到了啥", "你查到了啥", "看到了啥", "然后呢",
        "到了啥", "了啥", "啥",
    }
    if len(compact) >= 2 and compact not in generic:
        return current
    for item in reversed(history):
        if item.role != "user" or len(item.content) > 120:
            continue
        candidate = strip_search_words(clean_search_subject(item.content))
        candidate_compact = candidate.replace(" ", "")
        if len(candidate_compact) >= 2 and candidate_compact not in generic:
            return candidate
    return ""


def enrich_message(
    settings: Settings,
    session_key: str,
    user_text: str,
    image_paths: list[str],
    file_paths: list[str],
    file_names: list[str],
    history: Sequence[HistoryMessage],
    banter: bool,
    search_query: str,
) -> MediaContext:
    ctx = MediaContext(image_paths=list(image_paths))

    video_url = extract_bilibili_url(user_text) if not banter else ""
    if video_url:
        info = fetch_bilibili_info(video_url, settings.video_info_cache_seconds)
        if info:
            frames = download_frames(
                info.url,
                info.duration,
                count=settings.video_frame_count,
                info_cache_seconds=settings.video_info_cache_seconds,
                frame_cache_seconds=settings.video_frame_cache_seconds,
                max_filesize_mb=settings.video_download_max_mb,
                min_interval=settings.video_frame_min_interval,
            )
            ctx.image_paths.extend(frames)
            ctx.video_text = info.to_context(len(frames))
            logger.info(
                "B站视频解析完成，会话=%s，BV=%s，帧数=%s",
                session_key,
                info.bvid,
                len(frames),
            )
        else:
            ctx.video_text = "（这个B站链接没解析出来）"
            logger.info("B站视频解析失败，会话=%s，链接=%s", session_key, video_url)

    article_url = extract_wechat_article_url(user_text) if not banter else ""
    if article_url and not video_url:
        article = fetch_wechat_article(article_url, settings.article_max_chars)
        if article:
            ctx.link_text = article.to_context()
            logger.info(
                "公众号文章解析完成，会话=%s，标题=%s，字符数=%s",
                session_key,
                article.title,
                len(article.text),
            )
        else:
            ctx.link_text = "（这篇公众号文章没打开，可能需要验证）"
            logger.info("公众号文章解析失败，会话=%s，链接=%s", session_key, article_url)

    if ctx.image_paths:
        ocr_parts = [
            ocr_image(path)
            for path in ctx.image_paths[:settings.ocr_max_images]
        ]
        ctx.ocr_text = "\n".join(part for part in ocr_parts if part).strip()
        logger.info("图片 OCR 完成，会话=%s，字符数=%s", session_key, len(ctx.ocr_text))

    if file_paths:
        doc_parts = [
            extract_pdf_text(
                path,
                max_pages=settings.pdf_max_pages,
                max_ocr_pages=settings.pdf_max_ocr_pages,
                max_chars=settings.pdf_max_chars,
            )
            for path in file_paths[:settings.pdf_max_files]
        ]
        ctx.doc_text = "\n\n".join(part for part in doc_parts if part).strip()
        logger.info("PDF 文本提取完成，会话=%s，字符数=%s", session_key, len(ctx.doc_text))

    if (
        not banter
        and not video_url
        and not article_url
        and settings.web_search
        and search_query
    ):
        query = search_query
        ctx.search_query = query
        results = search_web(
            query,
            settings.search_max_results,
            settings.search_cache_seconds,
        )
        if results:
            pages = []
            for item in results[:settings.search_fetch_pages]:
                if not item.url:
                    continue
                page = fetch_page_text(
                    item.url,
                    settings.search_fetch_max_chars,
                    settings.search_fetch_timeout_seconds,
                )
                if page:
                    pages.append(f"[网页内容：{item.title}]\n{page}")
            ctx.search_text = "\n\n".join(pages + [format_results(results)])
            logger.info(
                "联网搜索完成，会话=%s，关键词=%s，结果数=%s，网页数=%s",
                session_key,
                query,
                len(results),
                len(pages),
            )
        else:
            ctx.search_text = "（这次没有搜到可用结果）"
            logger.info("联网搜索无结果，会话=%s，关键词=%s", session_key, query)

    if file_paths:
        detail = ctx.doc_text[:2000] if ctx.doc_text else "(PDF文字提取失败)"
        stored_text = f"[PDF] {file_names[0]} {detail} {user_text}".strip()
    elif ctx.image_paths:
        detail = ctx.ocr_text[:2000] if ctx.ocr_text else "(图片)"
        stored_text = f"[图片] {detail} {user_text}".strip()
    else:
        stored_text = user_text
    if ctx.search_text:
        stored_text = f"{stored_text}\n[搜索 {ctx.search_query}] {ctx.search_text[:1000]}".strip()
    if ctx.video_text:
        stored_text = f"{stored_text}\n[视频] {ctx.video_text[:1200]}".strip()
    if ctx.link_text:
        stored_text = f"{stored_text}\n[文章] {ctx.link_text[:1500]}".strip()
    ctx.stored_text = stored_text
    return ctx
