import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_required(name: str) -> str:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        raise ValueError(f"缺少环境变量 {name}，请参考 .env.example")
    return raw.strip()


def _env_bool(name: str) -> bool:
    return _env_required(name).lower() in {"1", "true", "yes", "on"}


def _env_int(name: str) -> int:
    raw = _env_required(name)
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数，当前值: {raw!r}") from exc


def _env_float(name: str) -> float:
    raw = _env_required(name)
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是数字，当前值: {raw!r}") from exc


def _env_list(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _env_weights(name: str) -> dict[str, float]:
    weights: dict[str, float] = {}
    for pair in _env_required(name).split(","):
        pair = pair.strip()
        if not pair:
            continue
        key, separator, value = pair.partition(":")
        if not separator:
            key, separator, value = pair.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"{name} 格式应为 类别:权重,类别:权重，当前片段: {pair!r}")
        try:
            weights[key.strip().lower()] = float(value.strip())
        except ValueError as exc:
            raise ValueError(f"{name} 的权重必须是数字，当前片段: {pair!r}") from exc
    if not weights:
        raise ValueError(f"{name} 不能为空")
    return weights


def _env_rate(name: str) -> float:
    return min(max(_env_float(name), 0.0), 1.0)


def _env_map_list(name: str, required: bool = False) -> dict[str, tuple[str, ...]]:
    raw = os.getenv(name, "").strip()
    if not raw:
        if required:
            raise ValueError(f"缺少环境变量 {name}，请参考 .env.example")
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        key, separator, value = part.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"{name} 格式应为 分类=词1|词2;分类=词1|词2，当前片段: {part!r}")
        items = tuple(item.strip() for item in value.split("|") if item.strip())
        if not items:
            raise ValueError(f"{name} 的分类 {key.strip()!r} 不能为空")
        result[key.strip().lower()] = items
    if required and not result:
        raise ValueError(f"{name} 不能为空")
    return result


def _env_map(name: str, delimiter: str = ";", lower_keys: bool = False) -> dict[str, str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return {}
    result: dict[str, str] = {}
    for part in raw.split(delimiter):
        part = part.strip()
        if not part:
            continue
        key, separator, value = part.partition("=")
        if not separator or not key.strip() or not value.strip():
            raise ValueError(f"{name} 格式应为 键=值{delimiter}键=值，当前片段: {part!r}")
        key = key.strip()
        result[key.lower() if lower_keys else key] = value.strip()
    return result


def _env_topic_rules(name: str) -> dict[str, tuple[tuple[str, str], ...]]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return {}
    result: dict[str, list[tuple[str, str]]] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        left, separator, label = part.partition("=")
        if not separator or "." not in left or not label.strip():
            raise ValueError(
                f"{name} 格式应为 分类.关键词=话题,分类.关键词=话题，当前片段: {part!r}"
            )
        category, keyword = left.split(".", 1)
        category = category.strip().lower()
        keyword = keyword.strip().lower()
        if not category or not keyword:
            raise ValueError(f"{name} 的分类和关键词不能为空，当前片段: {part!r}")
        result.setdefault(category, []).append((keyword, label.strip()))
    return {key: tuple(value) for key, value in result.items()}


def _resolve(path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else BASE_DIR / path


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    default_model: str
    deepseek_timeout_seconds: float
    deepseek_max_retries: int
    db_path: Path
    personas_path: Path
    log_level: str
    admin_wxids: frozenset[str]
    reply_whitelist: frozenset[str]
    bot_name: str
    reply_target_name: str
    split_limit: int
    bubble_limit: int
    max_bubbles: int
    send_delay_min: float
    send_delay_max: float
    max_workers: int
    send_error_notice: bool
    skip_wechat_check: bool
    adapter: str
    wechat4_interval: float
    wechat_max_file_mb: int
    wechat_max_sticker_mb: int
    reply_debounce: float
    batch_max_messages: int
    batch_max_chars: int
    group_banter_rate: float
    sticker_reply_rate: float
    ocr_max_images: int
    pdf_max_files: int
    web_search: bool
    search_intent_enabled: bool
    search_intent_max_tokens: int
    search_query_max_tokens: int
    search_max_results: int
    search_cache_seconds: int
    search_fetch_pages: int
    search_fetch_max_chars: int
    search_fetch_timeout_seconds: float
    article_max_chars: int
    pdf_max_pages: int
    pdf_max_ocr_pages: int
    pdf_max_chars: int
    prompt_max_images: int
    prompt_max_image_side: int
    prompt_image_quality: int
    video_frame_count: int
    video_info_cache_seconds: int
    video_frame_cache_seconds: int
    video_frame_min_interval: int
    video_download_max_mb: int
    video_weights: dict[str, float]
    video_bad_words: tuple[str, ...]
    video_category_keywords: dict[str, tuple[str, ...]]
    video_category_terms: dict[str, tuple[str, ...]]
    video_category_bad_words: dict[str, tuple[str, ...]]
    video_category_topics: dict[str, str]
    video_topic_rules: dict[str, tuple[tuple[str, str], ...]]
    video_topic_fallbacks: dict[str, str]
    video_default_fallback: str
    video_share_extra_hint: str
    video_min_play: int
    video_fallback_min_play: int
    video_min_duration: int
    video_max_duration: int
    video_freshness_days: int
    video_top_candidates: int
    video_search_limit: int
    video_history_limit: int
    video_cache_seconds: int
    video_popular_freshness_days: int
    reminder_check_seconds: float
    condition_check_seconds: float
    condition_interval_minutes: int
    condition_retry_minutes: int
    condition_search_cache_seconds: int
    condition_expire_days: int
    condition_query_max_tokens: int
    condition_judge_max_tokens: int
    condition_context_chars: int
    proactive_enabled: bool
    proactive_targets: tuple[str, ...]
    proactive_quiet_start: float
    proactive_quiet_end: float
    proactive_min_minutes: int
    proactive_max_minutes: int
    proactive_video_rate: float
    proactive_check_seconds: float
    proactive_start_delay_seconds: float
    proactive_active_skip_minutes: int
    proactive_retry_min_minutes: float
    proactive_retry_max_minutes: float
    followup_first_delay_minutes: float
    followup_min_interval_minutes: float
    followup_max_interval_minutes: float
    followup_check_seconds: float

    def allows_reply(self, session_key: str) -> bool:
        return not self.reply_whitelist or session_key in self.reply_whitelist


def load_settings() -> Settings:
    load_dotenv(BASE_DIR / ".env")
    admins = frozenset(_env_list("ADMIN_WXIDS"))
    reply_whitelist = frozenset(_env_list("REPLY_WHITELIST"))

    raw_proactive = _env_list("PROACTIVE_WHITELIST")
    if raw_proactive:
        proactive_targets = raw_proactive
    else:
        fallback_target = os.getenv("PROACTIVE_TARGET_WXID", "").strip()
        proactive_targets = (fallback_target,) if fallback_target else ()
    proactive_targets = tuple(
        dict.fromkeys(
            target for target in proactive_targets
            if target and not target.endswith("@chatroom")
        )
    )

    send_delay_min = _env_float("REPLY_SEND_DELAY_MIN")
    send_delay_max = max(send_delay_min, _env_float("REPLY_SEND_DELAY_MAX"))
    proactive_min_minutes = max(1, _env_int("PROACTIVE_MIN_MINUTES"))
    proactive_max_minutes = max(proactive_min_minutes, _env_int("PROACTIVE_MAX_MINUTES"))
    followup_min_minutes = max(1.0, _env_float("FOLLOWUP_MIN_INTERVAL_MINUTES"))
    followup_max_minutes = max(followup_min_minutes, _env_float("FOLLOWUP_MAX_INTERVAL_MINUTES"))
    retry_min_minutes = max(0.0, _env_float("PROACTIVE_RETRY_MIN_MINUTES"))
    retry_max_minutes = max(retry_min_minutes, _env_float("PROACTIVE_RETRY_MAX_MINUTES"))
    video_min_duration = max(1, _env_int("VIDEO_MIN_DURATION"))
    video_max_duration = max(video_min_duration, _env_int("VIDEO_MAX_DURATION"))

    return Settings(
        api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
        base_url=_env_required("DEEPSEEK_BASE_URL"),
        default_model=_env_required("DEEPSEEK_MODEL"),
        deepseek_timeout_seconds=_env_float("DEEPSEEK_TIMEOUT_SECONDS"),
        deepseek_max_retries=_env_int("DEEPSEEK_MAX_RETRIES"),
        db_path=_resolve(_env_required("DB_PATH")),
        personas_path=_resolve(_env_required("PERSONAS_PATH")),
        log_level=_env_required("LOG_LEVEL").upper(),
        admin_wxids=admins,
        reply_whitelist=reply_whitelist,
        bot_name=_env_required("BOT_NAME"),
        reply_target_name=os.getenv("REPLY_TARGET_NAME", "").strip(),
        split_limit=_env_int("REPLY_SPLIT_LIMIT"),
        bubble_limit=_env_int("REPLY_BUBBLE_LIMIT"),
        max_bubbles=_env_int("REPLY_MAX_BUBBLES"),
        send_delay_min=send_delay_min,
        send_delay_max=send_delay_max,
        max_workers=_env_int("BOT_WORKERS"),
        send_error_notice=_env_bool("SEND_ERROR_NOTICE"),
        skip_wechat_check=_env_bool("SKIP_WECHAT_CHECK"),
        adapter=_env_required("ADAPTER").lower(),
        wechat4_interval=_env_float("WECHAT4_INTERVAL"),
        wechat_max_file_mb=_env_int("WECHAT_MAX_FILE_MB"),
        wechat_max_sticker_mb=_env_int("WECHAT_MAX_STICKER_MB"),
        reply_debounce=_env_float("REPLY_DEBOUNCE"),
        batch_max_messages=_env_int("BATCH_MAX_MESSAGES"),
        batch_max_chars=_env_int("BATCH_MAX_CHARS"),
        group_banter_rate=_env_rate("GROUP_BANTER_RATE"),
        sticker_reply_rate=_env_rate("STICKER_REPLY_RATE"),
        ocr_max_images=_env_int("OCR_MAX_IMAGES"),
        pdf_max_files=_env_int("PDF_MAX_FILES"),
        web_search=_env_bool("WEB_SEARCH"),
        search_intent_enabled=_env_bool("SEARCH_INTENT_ENABLED"),
        search_intent_max_tokens=_env_int("SEARCH_INTENT_MAX_TOKENS"),
        search_query_max_tokens=_env_int("SEARCH_QUERY_MAX_TOKENS"),
        search_max_results=_env_int("SEARCH_MAX_RESULTS"),
        search_cache_seconds=_env_int("SEARCH_CACHE_SECONDS"),
        search_fetch_pages=_env_int("SEARCH_FETCH_PAGES"),
        search_fetch_max_chars=_env_int("SEARCH_FETCH_MAX_CHARS"),
        search_fetch_timeout_seconds=_env_float("SEARCH_FETCH_TIMEOUT_SECONDS"),
        article_max_chars=_env_int("ARTICLE_MAX_CHARS"),
        pdf_max_pages=_env_int("PDF_MAX_PAGES"),
        pdf_max_ocr_pages=_env_int("PDF_MAX_OCR_PAGES"),
        pdf_max_chars=_env_int("PDF_MAX_CHARS"),
        prompt_max_images=_env_int("PROMPT_MAX_IMAGES"),
        prompt_max_image_side=_env_int("PROMPT_MAX_IMAGE_SIDE"),
        prompt_image_quality=_env_int("PROMPT_IMAGE_QUALITY"),
        video_frame_count=_env_int("VIDEO_FRAME_COUNT"),
        video_info_cache_seconds=_env_int("VIDEO_INFO_CACHE_SECONDS"),
        video_frame_cache_seconds=_env_int("VIDEO_FRAME_CACHE_SECONDS"),
        video_frame_min_interval=_env_int("VIDEO_FRAME_MIN_INTERVAL"),
        video_download_max_mb=_env_int("VIDEO_DOWNLOAD_MAX_MB"),
        video_weights=_env_weights("VIDEO_WEIGHTS"),
        video_bad_words=_env_list("VIDEO_BAD_WORDS"),
        video_category_keywords=_env_map_list("VIDEO_CATEGORY_KEYWORDS", required=True),
        video_category_terms=_env_map_list("VIDEO_CATEGORY_TERMS"),
        video_category_bad_words=_env_map_list("VIDEO_CATEGORY_BAD_WORDS"),
        video_category_topics=_env_map("VIDEO_CATEGORY_TOPICS", lower_keys=True),
        video_topic_rules=_env_topic_rules("VIDEO_TOPIC_RULES"),
        video_topic_fallbacks=_env_map("VIDEO_TOPIC_FALLBACKS", ","),
        video_default_fallback=_env_required("VIDEO_DEFAULT_FALLBACK"),
        video_share_extra_hint=os.getenv("VIDEO_SHARE_EXTRA_HINT", "").strip(),
        video_min_play=_env_int("VIDEO_MIN_PLAY"),
        video_fallback_min_play=_env_int("VIDEO_FALLBACK_MIN_PLAY"),
        video_min_duration=video_min_duration,
        video_max_duration=video_max_duration,
        video_freshness_days=_env_int("VIDEO_FRESHNESS_DAYS"),
        video_top_candidates=_env_int("VIDEO_TOP_CANDIDATES"),
        video_search_limit=_env_int("VIDEO_SEARCH_LIMIT"),
        video_history_limit=_env_int("VIDEO_HISTORY_LIMIT"),
        video_cache_seconds=_env_int("VIDEO_CACHE_SECONDS"),
        video_popular_freshness_days=_env_int("VIDEO_POPULAR_FRESHNESS_DAYS"),
        reminder_check_seconds=_env_float("REMINDER_CHECK_SECONDS"),
        condition_check_seconds=_env_float("CONDITION_CHECK_SECONDS"),
        condition_interval_minutes=_env_int("CONDITION_INTERVAL_MINUTES"),
        condition_retry_minutes=_env_int("CONDITION_RETRY_MINUTES"),
        condition_search_cache_seconds=_env_int("CONDITION_SEARCH_CACHE_SECONDS"),
        condition_expire_days=_env_int("CONDITION_EXPIRE_DAYS"),
        condition_query_max_tokens=_env_int("CONDITION_QUERY_MAX_TOKENS"),
        condition_judge_max_tokens=_env_int("CONDITION_JUDGE_MAX_TOKENS"),
        condition_context_chars=_env_int("CONDITION_CONTEXT_CHARS"),
        proactive_enabled=_env_bool("PROACTIVE_ENABLED"),
        proactive_targets=proactive_targets,
        proactive_quiet_start=_env_float("PROACTIVE_QUIET_START"),
        proactive_quiet_end=_env_float("PROACTIVE_QUIET_END"),
        proactive_min_minutes=proactive_min_minutes,
        proactive_max_minutes=proactive_max_minutes,
        proactive_video_rate=_env_rate("PROACTIVE_VIDEO_RATE"),
        proactive_check_seconds=_env_float("PROACTIVE_CHECK_SECONDS"),
        proactive_start_delay_seconds=_env_float("PROACTIVE_START_DELAY_SECONDS"),
        proactive_active_skip_minutes=_env_int("PROACTIVE_ACTIVE_SKIP_MINUTES"),
        proactive_retry_min_minutes=retry_min_minutes,
        proactive_retry_max_minutes=retry_max_minutes,
        followup_first_delay_minutes=_env_float("FOLLOWUP_FIRST_DELAY_MINUTES"),
        followup_min_interval_minutes=followup_min_minutes,
        followup_max_interval_minutes=followup_max_minutes,
        followup_check_seconds=_env_float("FOLLOWUP_CHECK_SECONDS"),
    )
