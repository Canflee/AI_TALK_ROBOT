import html
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}
URL_RE = re.compile(r"https?://mp\.weixin\.qq\.com/[^\s，。；）】)\]}]+")
BLOCK_MARKERS = ("环境异常", "完成验证", "访问过于频繁", "请在微信客户端打开")


@dataclass(slots=True)
class ArticleInfo:
    title: str
    author: str
    published: str
    text: str
    url: str

    def to_context(self) -> str:
        lines = [f"标题：{self.title or '未知'}"]
        if self.author:
            lines.append(f"公众号：{self.author}")
        if self.published:
            lines.append(f"发布时间：{self.published}")
        lines.append(f"链接：{self.url}")
        lines.append("正文：")
        lines.append(self.text[:6000] if self.text else "（正文没有提取到，可能主要是图片）")
        return "\n".join(lines)


def extract_wechat_article_url(text: str) -> str:
    match = URL_RE.search(text or "")
    if not match:
        return ""
    return html.unescape(match.group(0)).rstrip(".,;)]}，。；）】")


def _parse_article_html(page: str, url: str, max_chars: int) -> ArticleInfo | None:
    soup = BeautifulSoup(page, "html.parser")

    title_node = soup.select_one("#activity-name") or soup.select_one("h1.rich_media_title")
    if title_node:
        title = title_node.get_text(" ", strip=True)
    else:
        meta = soup.find("meta", attrs={"property": "og:title"})
        title = str(meta.get("content") or "") if meta else (soup.title.get_text(strip=True) if soup.title else "")

    author_node = soup.select_one("#js_name") or soup.select_one(".rich_media_meta_nickname")
    author = author_node.get_text(" ", strip=True) if author_node else ""
    if not author:
        meta = soup.find("meta", attrs={"name": "author"})
        author = str(meta.get("content") or "") if meta else ""

    published_node = soup.select_one("#publish_time")
    published = published_node.get_text(" ", strip=True) if published_node else ""

    content = soup.select_one("#js_content") or soup.select_one(".rich_media_content")
    if content:
        for tag in content.select("script,style,noscript"):
            tag.decompose()
        text = content.get_text("\n", strip=True)
    else:
        text = ""

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not title and not text:
        return None
    if any(marker in page for marker in BLOCK_MARKERS) and len(text) < 30:
        return None
    return ArticleInfo(title=title, author=author, published=published, text=text[:max_chars], url=url)


def fetch_wechat_article(url: str, max_chars: int) -> ArticleInfo | None:
    host = urlparse(url).hostname or ""
    if host != "mp.weixin.qq.com":
        return None
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.encoding = "utf-8"
    except Exception:
        logger.warning("打开公众号文章失败: %s", url, exc_info=True)
        return None
    if response.status_code != 200:
        logger.warning("公众号文章返回状态异常: %s %s", response.status_code, url)
        return None
    return _parse_article_html(response.text, url, max_chars)
