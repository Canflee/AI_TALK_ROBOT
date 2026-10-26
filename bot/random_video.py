import html
import json
import logging
import random
import re
import time
from datetime import datetime

import requests

from .config import BASE_DIR, Settings
from .video import VideoInfo, fetch_bilibili_info

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}
HISTORY_FILE = BASE_DIR / "data" / "sent_videos.json"

_session: requests.Session | None = None
_cache: dict[str, tuple[float, list[dict]]] = {}


def _load_seen() -> list[str]:
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return [str(item) for item in data if item]
    except Exception:
        return []


def _mark_seen(bvid: str, limit: int) -> None:
    seen = _load_seen()
    seen.append(bvid)
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(
            json.dumps(seen[-max(1, limit):], ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        logger.debug("记录已发送视频失败", exc_info=True)


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
        try:
            _session.get("https://www.bilibili.com/", timeout=10)
        except Exception:
            logger.warning("初始化B站会话失败", exc_info=True)
    return _session


def _clean_title(value: str) -> str:
    return re.sub(r"<[^>]+>", "", html.unescape(str(value or ""))).strip()


def _duration_seconds(value: str) -> int:
    parts = [part for part in str(value or "").split(":") if part.isdigit()]
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return 0


def _play_count(item: dict) -> int:
    try:
        return int(item.get("play") or 0)
    except (TypeError, ValueError):
        return 0


def _matches_category(title: str, terms: tuple[str, ...]) -> bool:
    if not terms:
        return True
    lowered = title.lower()
    return any(term.lower() in lowered for term in terms)


def _filter_candidates(
    items: list[dict],
    category: str,
    now: float,
    min_play: int,
    settings: Settings,
) -> list[dict]:
    result = []
    for item in items:
        title = _clean_title(item.get("title"))
        duration = _duration_seconds(item.get("duration"))
        if not item.get("bvid") or not (settings.video_min_duration <= duration <= settings.video_max_duration):
            continue
        if len(re.sub(r"[^\w\u4e00-\u9fff]", "", title)) < 3:
            continue
        banned = settings.video_bad_words + settings.video_category_bad_words.get(category, ())
        if any(word in title for word in banned):
            continue
        if not _matches_category(title, settings.video_category_terms.get(category, ())):
            continue
        freshness = settings.video_freshness_days * 86400
        if int(item.get("pubdate") or 0) < now - freshness:
            continue
        if _play_count(item) < min_play:
            continue
        result.append(item)
    return result


def _search_category(category: str, settings: Settings) -> list[dict]:
    cached = _cache.get(category)
    if cached and time.time() - cached[0] < settings.video_cache_seconds:
        return cached[1]

    keywords = settings.video_category_keywords.get(category, ())
    if not keywords:
        return []
    year = datetime.now().year
    queries = [f"{year} {keyword}" for keyword in keywords]
    merged: dict[str, dict] = {}
    now = time.time()
    candidates: list[dict] = []

    for index, query in enumerate(queries):
        try:
            response = _get_session().get(
                "https://api.bilibili.com/x/web-interface/search/type",
                params={
                    "search_type": "video",
                    "keyword": query,
                    "order": "click",
                    "duration": 1,
                },
                timeout=15,
            )
            items = (response.json().get("data") or {}).get("result") or []
        except Exception as exc:
            logger.warning("B站分类搜索失败: %s (%s): %s", category, query, exc)
            time.sleep(0.5)
            continue

        for item in items:
            bvid = item.get("bvid")
            if bvid and bvid not in merged:
                merged[bvid] = item

        candidates = _filter_candidates(
            list(merged.values()), category, now, settings.video_min_play, settings
        )
        if len(candidates) >= 3:
            break
        if index < len(queries) - 1:
            time.sleep(0.4)

    if len(candidates) < 3:
        candidates = _filter_candidates(
            list(merged.values()), category, now, settings.video_fallback_min_play, settings
        )

    candidates.sort(key=_play_count, reverse=True)
    candidates = candidates[:settings.video_search_limit]
    _cache[category] = (time.time(), candidates)
    return candidates


def _popular_fallback(settings: Settings) -> VideoInfo | None:
    try:
        response = requests.get(
            "https://api.bilibili.com/x/web-interface/popular",
            params={"ps": 50, "pn": 1},
            headers=HEADERS,
            timeout=15,
        )
        items = (response.json().get("data") or {}).get("list") or []
    except Exception:
        logger.warning("获取B站热门视频失败", exc_info=True)
        return None

    now = time.time()
    freshness = settings.video_popular_freshness_days * 86400
    candidates = [
        item for item in items
        if item.get("bvid")
        and settings.video_min_duration <= int(item.get("duration") or 0) <= settings.video_max_duration
        and not any(word in str(item.get("title") or "") for word in settings.video_bad_words)
        and int(item.get("pubdate") or 0) >= now - freshness
        and int((item.get("stat") or {}).get("view") or 0) >= settings.video_min_play
    ]
    if not candidates:
        return None
    pick = random.choice(candidates)
    info = fetch_bilibili_info(
        f"https://www.bilibili.com/video/{pick['bvid']}",
        settings.video_info_cache_seconds,
    )
    if info:
        info.category = "random"
    return info


def search_bilibili_videos(query: str, limit: int = 3) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []
    try:
        response = _get_session().get(
            "https://api.bilibili.com/x/web-interface/search/type",
            params={
                "search_type": "video",
                "keyword": query,
                "order": "totalrank",
                "page": 1,
            },
            timeout=15,
        )
        items = (response.json().get("data") or {}).get("result") or []
    except Exception:
        logger.warning("B站任务搜索失败: %s", query, exc_info=True)
        return []

    results = []
    for item in items:
        bvid = item.get("bvid")
        title = _clean_title(item.get("title"))
        if not bvid or not title:
            continue
        results.append(
            {
                "title": title,
                "bvid": bvid,
                "url": f"https://www.bilibili.com/video/{bvid}",
                "author": str(item.get("author") or ""),
                "play": _play_count(item),
                "duration": str(item.get("duration") or ""),
            }
        )
        if len(results) >= limit:
            break
    return results


def random_bilibili_video(settings: Settings) -> VideoInfo | None:
    known_categories = set(settings.video_category_keywords)
    unknown = sorted(set(settings.video_weights) - known_categories)
    if unknown:
        logger.warning("VIDEO_WEIGHTS 中存在未知分类，已忽略: %s", ", ".join(unknown))
    categories = [
        category for category, weight in settings.video_weights.items()
        if weight > 0 and category in known_categories
    ]
    weights = [settings.video_weights[category] for category in categories]
    if not categories:
        return _popular_fallback(settings)

    first = random.choices(categories, weights=weights, k=1)[0]
    order = [first] + [category for category in categories if category != first]
    seen = set(_load_seen())

    for category in order:
        candidates = _search_category(category, settings)
        unseen = [item for item in candidates if item.get("bvid") not in seen]
        if not unseen:
            unseen = candidates
        if not unseen:
            continue
        pick = random.choice(unseen[:max(1, settings.video_top_candidates)])
        info = fetch_bilibili_info(
            f"https://www.bilibili.com/video/{pick['bvid']}",
            settings.video_info_cache_seconds,
        )
        if info and settings.video_min_duration <= info.duration <= settings.video_max_duration:
            info.category = category
            _mark_seen(info.bvid, settings.video_history_limit)
            logger.info(
                "随机B站视频分类=%s 播放=%s 标题=%s",
                category,
                _play_count(pick),
                info.title,
            )
            return info
    return _popular_fallback(settings)
