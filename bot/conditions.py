import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

from .config import Settings
from .llm.aimodel import AIModelClient, AIModelError
from .search import fetch_page_text, format_results, search_web, simplify_query

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
SUN_URL = "https://api.open-meteo.com/v1/forecast"

DAYLIGHT_WORDS = (
    ("太阳出来了", "light"),
    ("太阳下山了", "dark"),
    ("太阳下山", "dark"),
    ("天亮了", "light"),
    ("天黑了", "dark"),
    ("天亮", "light"),
    ("天黑", "dark"),
    ("日出", "light"),
    ("日落", "dark"),
)


def parse_daylight_condition(condition: str) -> tuple[str, str] | None:
    text = re.sub(r"[\s，,。.!！？?~：:；;]+", "", condition or "")
    text = re.sub(r"(了吗|了没|了没有|没有|吗|呢|呀|啊|了)$", "", text)
    for word, target in DAYLIGHT_WORDS:
        if text.endswith(word):
            city = text[: -len(word)]
            if 0 < len(city) <= 20:
                return city, target
    return None


class ConditionEvaluator:
    def __init__(self, settings: Settings, llm: AIModelClient):
        self.settings = settings
        self.llm = llm
        self._queries: dict[str, str] = {}
        self._geo: dict[str, tuple[float, float] | None] = {}
        self._sun: dict[tuple[float, float, str], tuple[datetime, datetime]] = {}

    def _chat(self, messages: list[dict], max_tokens: int) -> str:
        try:
            return self.llm.chat(
                messages,
                model=self.settings.default_model,
                temperature=0.0,
                max_tokens=max_tokens,
            )
        except AIModelError as exc:
            if "空内容" not in str(exc):
                raise
            logger.info("条件判断返回空内容，提高 token 后重试")
            return self.llm.chat(
                messages,
                model=self.settings.default_model,
                temperature=0.0,
                max_tokens=max(256, max_tokens * 2),
            )

    def _query(self, condition: str) -> str:
        cached = self._queries.get(condition)
        if cached:
            return cached
        messages = [
            {
                "role": "system",
                "content": (
                    "你把提醒条件改写成适合搜索引擎的查询词。\n"
                    "必须保留条件里的关键判断词（例如天黑、天亮、涨、跌、到达），"
                    "并补上能直接验证的实时关键词（例如 现在、实时、最新、今日）。\n"
                    "不要简化成宽泛的话题词，例如不要把'上海天黑了'改成'上海天气'。\n"
                    "只输出查询词，不要解释、引号或标点。\n"
                ),
            },
            {
                "role": "user",
                "content": f"条件：{condition}\n当前时间：{datetime.now():%Y-%m-%d %H:%M}",
            },
        ]
        try:
            answer = self._chat(messages, self.settings.condition_query_max_tokens)
        except Exception:
            logger.warning("生成条件搜索词失败，直接使用条件原文", exc_info=True)
            return condition
        query = simplify_query(answer.strip().strip("\"'""")[:100] or condition)
        self._queries[condition] = query
        return query

    def _geocode(self, city: str) -> tuple[float, float] | None:
        key = city.strip()
        if key in self._geo:
            return self._geo[key]
        coordinate = None
        names = [key]
        stripped = re.sub(r"(特别行政区|自治区|市|省|区|县)$", "", key)
        if stripped and stripped != key:
            names.append(stripped)
        for name in names:
            try:
                response = requests.get(
                    GEOCODE_URL,
                    params={"name": name, "count": 1, "language": "zh", "format": "json"},
                    timeout=8,
                )
                response.raise_for_status()
                items = (response.json() or {}).get("results") or []
            except Exception:
                logger.warning("地理编码失败: %s", name, exc_info=True)
                continue
            if items:
                coordinate = (float(items[0]["latitude"]), float(items[0]["longitude"]))
                break
        self._geo[key] = coordinate
        return coordinate

    def _sun_times(self, latitude: float, longitude: float) -> tuple[datetime, datetime] | None:
        key = (round(latitude, 3), round(longitude, 3), datetime.now().strftime("%Y-%m-%d"))
        cached = self._sun.get(key)
        if cached:
            return cached
        try:
            response = requests.get(
                SUN_URL,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "daily": "sunrise,sunset",
                    "timezone": "auto",
                    "forecast_days": 1,
                },
                timeout=8,
            )
            response.raise_for_status()
            data = response.json()
            daily = data.get("daily") or {}
            offset = timezone(timedelta(seconds=int(data.get("utc_offset_seconds") or 0)))
            sunrise = datetime.fromisoformat(daily["sunrise"][0]).replace(tzinfo=offset)
            sunset = datetime.fromisoformat(daily["sunset"][0]).replace(tzinfo=offset)
        except Exception:
            logger.warning("获取日出日落失败: %s,%s", latitude, longitude, exc_info=True)
            return None
        self._sun[key] = (sunrise, sunset)
        return sunrise, sunset

    def _daylight(self, condition: str) -> bool | None:
        parsed = parse_daylight_condition(condition)
        if not parsed:
            return None
        city, target = parsed
        coordinate = self._geocode(city)
        if not coordinate:
            logger.info("天亮/天黑条件未找到城市: %s", city)
            return None
        times = self._sun_times(*coordinate)
        if not times:
            return None
        sunrise, sunset = times
        now = datetime.now(sunrise.tzinfo)
        is_light = sunrise <= now < sunset
        result = is_light if target == "light" else not is_light
        logger.info(
            "天亮判断 城市=%s 目标=%s 日出=%s 日落=%s 现在=%s 结果=%s",
            city,
            target,
            sunrise.strftime("%H:%M"),
            sunset.strftime("%H:%M"),
            now.strftime("%H:%M"),
            "YES" if result else "NO",
        )
        return result

    def evaluate(self, condition: str) -> bool | None:
        if not self.settings.web_search:
            logger.warning("WEB_SEARCH 已关闭，无法检查条件提醒: %s", condition)
            return None
        daylight = self._daylight(condition)
        if daylight is not None:
            return daylight
        query = self._query(condition)
        results = search_web(
            query,
            self.settings.search_max_results,
            self.settings.condition_search_cache_seconds,
        )
        if not results:
            logger.info("条件检查没有搜索到结果: %s", condition)
            return None

        pages = []
        candidates = [
            item
            for item in results[: self.settings.search_fetch_pages]
            if item.url
        ]
        if candidates:
            with ThreadPoolExecutor(max_workers=min(5, len(candidates))) as pool:
                fetched = list(
                    pool.map(
                        lambda item: (
                            item,
                            fetch_page_text(
                                item.url,
                                self.settings.search_fetch_max_chars,
                                self.settings.search_fetch_timeout_seconds,
                            ),
                        ),
                        candidates,
                    )
                )
            for item, page in fetched:
                if page:
                    pages.append(f"[网页内容：{item.title}]\n{page}")
        context = "\n\n".join(pages + [format_results(results)])[:self.settings.condition_context_chars]
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个严格的条件判断器。只根据提供的搜索结果判断条件现在是否已经成立。"
                    "如果搜索结果给出了今日日出/日落时间、实时天气或实时报价等数据，"
                    "可以结合当前时间直接推算条件是否成立。"
                    "信息不足、需要预测未来、结果矛盾或无法确认时回答 UNKNOWN。"
                    "不要使用记忆，不要编造。只回答 YES、NO 或 UNKNOWN。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"条件：{condition}\n"
                    f"当前时间：{datetime.now():%Y-%m-%d %H:%M}\n"
                    f"搜索结果：\n{context}"
                ),
            },
        ]
        try:
            answer = self._chat(messages, self.settings.condition_judge_max_tokens)
        except Exception:
            logger.warning("判断条件失败: %s", condition, exc_info=True)
            return None

        normalized = answer.strip().upper()
        if normalized.startswith("YES") or normalized.startswith("是"):
            return True
        if normalized.startswith("NO") or normalized.startswith("否") or normalized.startswith("不是"):
            return False
        return None
