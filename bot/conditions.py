import logging
from datetime import datetime

from .config import Settings
from .llm.deepseek import DeepSeekClient, DeepSeekError
from .search import fetch_page_text, format_results, search_web, simplify_query

logger = logging.getLogger(__name__)


class ConditionEvaluator:
    def __init__(self, settings: Settings, llm: DeepSeekClient):
        self.settings = settings
        self.llm = llm
        self._queries: dict[str, str] = {}

    def _chat(self, messages: list[dict], max_tokens: int) -> str:
        try:
            return self.llm.chat(
                messages,
                model=self.settings.default_model,
                temperature=0.0,
                max_tokens=max_tokens,
            )
        except DeepSeekError as exc:
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
                    "你把提醒条件改写成适合搜索引擎的一句话查询词。"
                    "只输出查询词，不要解释、引号或标点。"
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
        query = simplify_query(answer.strip().strip("\"'“”")[:100] or condition)
        self._queries[condition] = query
        return query

    def evaluate(self, condition: str) -> bool | None:
        if not self.settings.web_search:
            logger.warning("WEB_SEARCH 已关闭，无法检查条件提醒: %s", condition)
            return None
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
        for item in results[:self.settings.search_fetch_pages]:
            if not item.url:
                continue
            page = fetch_page_text(
                item.url,
                self.settings.search_fetch_max_chars,
                self.settings.search_fetch_timeout_seconds,
            )
            if page:
                pages.append(f"[网页内容：{item.title}]\n{page}")
        context = "\n\n".join(pages + [format_results(results)])[:self.settings.condition_context_chars]
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个严格的条件判断器。只根据提供的搜索结果判断条件现在是否已经成立。"
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
