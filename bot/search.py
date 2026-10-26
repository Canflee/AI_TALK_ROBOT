import logging
import re
import time
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

_cache: dict[str, tuple[float, list["SearchResult"]]] = {}

DATE_RE = re.compile(r"(?:19|20)\d{2}\s*[-/年.]\s*\d{1,2}\s*[-/月.]\s*\d{1,2}\s*日?")
YEAR_MONTH_RE = re.compile(r"(?:19|20)\d{2}\s*年\s*\d{1,2}\s*月")
MONTH_DAY_RE = re.compile(r"\d{1,2}\s*月\s*\d{1,2}\s*日")
QUESTION_TAIL_RE = re.compile(r"(怎么样|怎样|如何|多少|吗|呢|呀|啊)+$")


def simplify_query(query: str) -> str:
    original = query.strip()
    query = DATE_RE.sub(" ", query)
    query = YEAR_MONTH_RE.sub(" ", query)
    query = MONTH_DAY_RE.sub(" ", query)
    # 保留"实时"，只替换其他时间词
    query = re.sub(r"\s*(当前|目前)\s*", " ", query)
    query = re.sub(r"\s*(现在)\s*", " 现在", query)
    for word in ("实时",):
        query = query.replace(word, " ")
    query = QUESTION_TAIL_RE.sub("", query)
    query = re.sub(r"\s+", " ", query).strip(" ，,。.!！？?~：:；;")
    parts = [part for part in query.split() if part]
    deduped = []
    for part in parts:
        if any(part != other and part in other for other in parts):
            continue
        if part not in deduped:
            deduped.append(part)
    return " ".join(deduped) or original


@dataclass(slots=True)
class SearchResult:
    title: str
    snippet: str
    url: str = ""


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*反馈$", "", text)
    return text


def _search_360(query: str, max_results: int) -> list[SearchResult]:
    response = requests.get(
        "https://www.so.com/s",
        params={"q": query},
        headers=HEADERS,
        timeout=12,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results: list[SearchResult] = []
    for item in soup.select("li.res-list"):
        heading = item.select_one("h3")
        link = heading.select_one("a") if heading else None
        title = _clean(link.get_text(" ", strip=True)) if link else ""
        if not title:
            continue
        node = item.select_one(".res-desc, .res-comm-con, .res-comm-context")
        if node:
            snippet = _clean(node.get_text(" ", strip=True))
        else:
            snippet = _clean(item.get_text(" ", strip=True).replace(title, "", 1))
        if "广告" in title[:10] or "广告" in snippet[:10]:
            continue
        url = str(link.get("href") or "") if link else ""
        results.append(SearchResult(title=title, snippet=snippet[:300], url=url))
        if len(results) >= max_results:
            break
    return results


def _search_bing(query: str, max_results: int) -> list[SearchResult]:
    response = requests.get(
        "https://cn.bing.com/search",
        params={"q": query, "mkt": "zh-CN"},
        headers=HEADERS,
        timeout=12,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results: list[SearchResult] = []
    for item in soup.select("li.b_algo"):
        link = item.select_one("h2 a")
        title = _clean(link.get_text(" ", strip=True)) if link else ""
        if not title:
            continue
        node = item.select_one(".b_caption p") or item.select_one("p")
        snippet = _clean(node.get_text(" ", strip=True)) if node else ""
        url = str(link.get("href") or "") if link else ""
        results.append(SearchResult(title=title, snippet=snippet[:300], url=url))
        if len(results) >= max_results:
            break
    return results


def search_web(query: str, max_results: int, cache_seconds: int) -> list[SearchResult]:
    query = query.strip()
    if not query:
        return []

    cached = _cache.get(query)
    if cached and time.time() - cached[0] < cache_seconds:
        return cached[1]

    for engine in (_search_360, _search_bing):
        try:
            results = engine(query, max_results)
        except Exception:
            logger.warning("搜索失败: %s (%s)", query, engine.__name__, exc_info=True)
            continue
        if results:
            _cache[query] = (time.time(), results)
            return results
    return []


def format_results(results: list[SearchResult]) -> str:
    lines = []
    for index, item in enumerate(results, 1):
        lines.append(f"{index}. {item.title}")
        if item.snippet:
            lines.append(item.snippet)
    return "\n".join(lines)


def fetch_page_text(url: str, max_chars: int, timeout: float) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
        return ""
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout)
        if response.status_code != 200:
            return ""
        content_type = (response.headers.get("Content-Type") or "").lower()
        if content_type and "html" not in content_type and "text" not in content_type:
            return ""
        if len(response.content) > 2 * 1024 * 1024:
            return ""
        response.encoding = response.apparent_encoding or response.encoding or "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception:
        logger.warning("抓取网页失败: %s", url, exc_info=True)
        return ""

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text[:max_chars].strip()
