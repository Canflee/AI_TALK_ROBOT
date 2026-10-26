import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup

from .search import HEADERS, SearchResult

logger = logging.getLogger(__name__)

BILIBILI_VIEW = "https://api.bilibili.com/x/web-interface/view"
BAD_MARKERS = (
    "页面不存在",
    "页面走丢了",
    "内容不存在",
    "视频不存在",
    "视频已失效",
    "该视频已失效",
    "稿件不可见",
    "已删除",
    "内容已被删除",
    "该内容已被删除",
    "登录后查看",
    "请先登录",
    "请登录后",
    "扫码登录",
    "登录/注册",
    "安全验证",
    "人机验证",
    "访问验证",
    "验证码",
    "账号异常",
    "付费阅读",
    "VIP专享",
    "Not Found",
    "404",
)
LOGIN_URL_MARKERS = ("login", "passport", "signin", "sign-in", "captcha", "verify")
BV_RE = re.compile(r"BV[0-9A-Za-z]{10}")
REDIRECT_PATTERNS = (
    re.compile(r"window\.location\.replace\([\"']([^\"']+)", re.I),
    re.compile(r"window\.location(?:\.href)?\s*=\s*[\"']([^\"']+)", re.I),
    re.compile(r"http-equiv=[\"']?refresh[\"']?[^>]*content=[\"'][^\"']*url=([^\"';>]+)", re.I),
)


def _decode_js_escapes(value: str) -> str:
    value = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), value)
    value = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), value)
    return value


def _extract_redirect_target(page: str, base_url: str) -> str:
    for pattern in REDIRECT_PATTERNS:
        match = pattern.search(page or "")
        if match:
            target = unquote(html.unescape(match.group(1).strip()))
            target = _decode_js_escapes(target)
            if target:
                return urljoin(base_url, target)
    return ""


def resolve_web_url(url: str, timeout: float = 8, depth: int = 0) -> str:
    if not url or depth > 2:
        return url
    try:
        response = requests.get(
            url,
            headers={
                **HEADERS,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=timeout,
            allow_redirects=True,
        )
    except Exception:
        return url
    final_url = response.url or url
    if final_url != url and "so.com/link" not in final_url:
        return final_url
    target = _extract_redirect_target(response.text, final_url)
    if target and target != url:
        return resolve_web_url(target, timeout=timeout, depth=depth + 1)
    return final_url


def check_bilibili_video(bvid: str, timeout: float = 10) -> bool:
    if not bvid:
        return False
    try:
        response = requests.get(
            BILIBILI_VIEW,
            params={"bvid": bvid},
            headers=HEADERS,
            timeout=timeout,
        )
        if response.status_code != 200:
            return False
        data = response.json()
        if int(data.get("code", -1)) != 0:
            return False
        info = data.get("data") or {}
        if not info.get("bvid"):
            return False
        state = int(info.get("state", 0) or 0)
        return state == 0
    except Exception:
        logger.debug("B站视频可用性检查失败: %s", bvid, exc_info=True)
        return False


def check_web_url(url: str, timeout: float = 8) -> bool:
    url = (url or "").strip()
    if not url:
        return False
    url = resolve_web_url(url, timeout=timeout)

    match = BV_RE.search(url)
    if match:
        return check_bilibili_video(match.group(0), timeout=timeout)

    try:
        response = requests.get(
            url,
            headers={
                **HEADERS,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=timeout,
            allow_redirects=True,
        )
    except Exception:
        logger.debug("网页访问失败: %s", url, exc_info=True)
        return False

    if response.status_code != 200:
        logger.info("网页状态异常: %s -> %s", url, response.status_code)
        return False

    final_url = (response.url or "").lower()
    if any(marker in final_url for marker in LOGIN_URL_MARKERS):
        logger.info("网页跳转到登录/验证页: %s -> %s", url, response.url)
        return False

    content_type = (response.headers.get("Content-Type") or "").lower()
    if content_type and "html" not in content_type and "text" not in content_type:
        return False
    if len(response.content) > 2 * 1024 * 1024:
        return False

    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)

    sample = f"{title}\n{text[:800]}".lower()
    for marker in BAD_MARKERS:
        if marker.lower() in sample:
            logger.info("网页内容异常（命中 %s）: %s", marker, url)
            return False
    if len(text) < 150:
        logger.info("网页正文过短，疑似无效: %s 字符数=%s", url, len(text))
        return False

    logger.debug("网页可用: %s 标题=%s 字符数=%s", url, title[:60], len(text))
    return True


def available_bilibili_videos(items: list[dict], limit: int = 3) -> list[dict]:
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(5, len(items))) as pool:
        checked = list(
            pool.map(
                lambda item: (item, check_bilibili_video(str(item.get("bvid") or ""))),
                items,
            )
        )
    available = [item for item, ok in checked if ok]
    logger.info(
        "B站链接自查：候选=%s 可用=%s",
        len(items),
        len(available),
    )
    return available[:limit]


def available_web_results(results: list[SearchResult], limit: int = 3) -> list[SearchResult]:
    if not results:
        return []

    def verify(item: SearchResult) -> SearchResult | None:
        if not item.url:
            return None
        resolved = resolve_web_url(item.url)
        if not check_web_url(resolved):
            return None
        return SearchResult(title=item.title, snippet=item.snippet, url=resolved)

    with ThreadPoolExecutor(max_workers=min(5, len(results))) as pool:
        checked = list(pool.map(verify, results))
    available = [item for item in checked if item is not None]
    logger.info(
        "网页链接自查：候选=%s 可用=%s",
        len(results),
        len(available),
    )
    return available[:limit]
