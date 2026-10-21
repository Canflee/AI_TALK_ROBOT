import logging
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    due_at TEXT,
    condition_text TEXT NOT NULL DEFAULT '',
    check_interval_minutes INTEGER NOT NULL DEFAULT 30,
    next_check_at TEXT,
    expires_at TEXT,
    last_result TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    triggered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders(status, kind);
"""

CONDITION_TRIGGERS = ("提醒我", "提醒一下", "告诉我", "通知我", "叫我")
NEGATION_RE = re.compile(r"(不要|别|不用|停止|取消).{0,10}(提醒|叫我|告诉我|通知我)")
CANCEL_ALL_PATTERNS = (
    re.compile(r"(不要|别|不用|停止|取消)(再)?提醒我?(任何|所有|全部|一切|别的|其他|了|$)"),
    re.compile(r"(取消|停止|关掉)(所有|全部|一切)?提醒"),
    re.compile(r"(所有|全部|一切|这些)提醒.*(取消|关|停|不要|别)"),
    re.compile(r"(把)?提醒(都|全|全部|所有).*(取消|关|停)"),
    re.compile(r"以后(别|不要|不用)(再)?提醒"),
    re.compile(r"算了.*提醒.*(取消|关|停)"),
    re.compile(r"(算了[，,]?\s*)?(全部|所有|全都|全)关(掉|了)"),
    re.compile(r"(删除|删掉|删了)(所有|全部|一切)?提醒"),
)
UPDATE_REMINDER_WORDS = ("改成", "换成", "改为", "改到", "取消", "别叫", "不要叫", "不用叫")
CANCEL_RECENT_PATTERNS = (
    re.compile(r"^(算了[，,]?\s*)?(别|不要|不用)(再)?(叫|提醒)(我)?(了|啦|吧)?$"),
    re.compile(r"^(算了[，,]?\s*)?(取消|不用|不要)(了|啦|吧)?$"),
    re.compile(r"^(算了|那算了)[，,]?$"),
    re.compile(r"^算了[，,]?\s*不(叫|提醒|用)了?$"),
    re.compile(r"^(把)?(删掉|删除|删了).*(提醒|这个|那个)"),
    re.compile(r"^(把)?这个提醒(删掉|删除|删了)"),
)
CORRECTION_HINTS = ("今天", "明天", "后天", "今晚", "明早", "晚上", "早上", "上午", "下午", "中午")
REMINDER_TRIGGERS = ("提醒", "叫我", "告诉我", "通知我")
CONDITION_FILLER_RE = re.compile(
    r"(就行了|就好了|就好|就行|可以了|可以|好了|算了|没事|谢谢|拜托|随便|都行|"
    r"知道|明白|收到|一下|一声|这个|那个|了|啦|吧|呀|嘛|哦|啊|就|行|好|的|是|我|你)"
)


def wants_cancel_all_reminders(text: str) -> bool:
    text = (text or "").strip()
    return any(pattern.search(text) for pattern in CANCEL_ALL_PATTERNS)
CONDITION_HINTS = (
    "了", "到", "涨", "跌", "超过", "低于", "高于", "突破", "跌破",
    "天气", "晴", "雨", "雪", "阴", "气温", "温度",
    "金价", "价格", "汇率", "油价",
)

CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

TIME_RE = re.compile(
    r"(?:(?P<day>今天|明天|后天)\s*)?"
    r"(?:(?P<period>凌晨|早上|上午|中午|下午|晚上|傍晚)\s*)?"
    r"(?P<hour>\d{1,2}|[零一二两三四五六七八九十]{1,3})\s*(?:点|时|[:：])\s*"
    r"(?P<minute>一刻|两刻|三刻|\d{1,2}|[零一二三四五六七八九十]{1,3}|半)?\s*(?:分)?"
)

REL_TIME_RE = re.compile(
    r"(?P<num>\d+|[一二两三四五六七八九十半]+)\s*(?P<unit>分钟|分|小时|钟头)\s*(?:后|之后)"
)
INTERVAL_RE = re.compile(
    r"每\s*(?P<num>\d+|[零一二两三四五六七八九十半]+)?\s*"
    r"(?P<unit>分钟|分|小时|钟头)"
)


@dataclass(slots=True)
class ReminderRequest:
    kind: str
    content: str = ""
    due_at: datetime | None = None
    condition: str = ""
    interval_minutes: int = 0


def _to_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    if value == "半":
        return 30
    if value == "一刻":
        return 15
    if value == "两刻":
        return 30
    if value == "三刻":
        return 45
    if value.isdigit():
        return int(value)
    if value == "十":
        return 10
    if "十" in value:
        left, _, right = value.partition("十")
        tens = _to_int(left) if left else 1
        ones = _to_int(right) if right else 0
        if tens is None or ones is None:
            return None
        return tens * 10 + ones
    return CN_DIGITS.get(value)


def _build_due(match: re.Match) -> datetime | None:
    hour = _to_int(match.group("hour"))
    minute = _to_int(match.group("minute") or "0") or 0
    if hour is None or not (0 <= hour <= 23) or not (0 <= minute <= 59):
        return None

    period = match.group("period") or ""
    if period in {"下午", "晚上", "傍晚"} and hour < 12:
        hour += 12
    if period == "中午" and hour < 11:
        hour += 12
    if period in {"凌晨", "晚上"} and hour == 12:
        hour = 0

    now = datetime.now()
    day = match.group("day")
    base = now
    if day == "明天":
        base = now + timedelta(days=1)
    elif day == "后天":
        base = now + timedelta(days=2)

    due = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if due <= now:
        if day == "今天" and not period and hour < 12:
            evening = due + timedelta(hours=12)
            if evening > now:
                return evening
        due += timedelta(days=1)
    return due


def time_matches(text: str) -> list[re.Match]:
    return list(TIME_RE.finditer(text or ""))


def wants_update_reminder(text: str) -> bool:
    text = (text or "").strip()
    if not time_matches(text):
        return False
    if wants_cancel_all_reminders(text):
        return False
    return any(word in text for word in UPDATE_REMINDER_WORDS)


def wants_cancel_recent_reminder(text: str) -> bool:
    text = (text or "").strip()
    if wants_cancel_all_reminders(text):
        return False
    return any(pattern.search(text) for pattern in CANCEL_RECENT_PATTERNS)


def wants_correct_reminder_time(text: str) -> bool:
    text = (text or "").strip()
    if not time_matches(text):
        return False
    if any(trigger in text for trigger in REMINDER_TRIGGERS):
        return False
    if wants_cancel_all_reminders(text) or wants_update_reminder(text):
        return False
    if any(hint in text for hint in CORRECTION_HINTS):
        return True
    return text.startswith(("哦", "对了", "我是说", "不是", "那"))


def _extract_content(text: str, match: re.Match) -> str:
    remainder = f"{text[:match.start()]} {text[match.end():]}"
    remainder = re.sub(
        r"(提醒我一声|提醒我一下|提醒一声|提醒一下|提醒我|提醒|告诉我|通知我|"
        r"叫我(?:\s*(?:一声|一下))?)",
        " ",
        remainder,
    )
    remainder = re.sub(r"[，,。.!！？?~：:；;]", " ", remainder)
    remainder = re.sub(
        r"^(?:(?:我是说|我说|我意思是|哦对了|对了还有|顺便说|顺便|还有|另外|"
        r"哦对了|对了|那个|嗯|诶|哎|也)[，,\s]*)+",
        "",
        remainder,
    )
    remainder = re.sub(r"\s*不是(?:明天|今天|早上|晚上|上午|下午|中午|后天).*$", "", remainder)
    return re.sub(r"\s+", " ", remainder).strip()


def parse_reminder(text: str) -> ReminderRequest | None:
    text = (text or "").strip()
    if not text or not any(trigger in text for trigger in ("提醒", "叫我", "告诉我", "通知我")):
        return None
    if NEGATION_RE.search(text):
        return None

    relative = REL_TIME_RE.search(text)
    if relative:
        raw_number = relative.group("num")
        unit = relative.group("unit")
        if raw_number == "半":
            delta = timedelta(minutes=30) if unit in {"小时", "钟头"} else timedelta(seconds=30)
        else:
            number = _to_int(raw_number)
            if not number:
                return None
            delta = timedelta(minutes=number) if unit in {"分钟", "分"} else timedelta(hours=number)
        content = _extract_content(text, relative) or "到点了"
        return ReminderRequest(kind="time", content=content, due_at=datetime.now() + delta)

    time_match = TIME_RE.search(text)
    if time_match:
        due = _build_due(time_match)
        if due:
            content = _extract_content(text, time_match) or "到点了"
            return ReminderRequest(kind="time", content=content, due_at=due)

    return None


def parse_condition_reminder(text: str) -> ReminderRequest | None:
    text = (text or "").strip()
    if not text or not any(trigger in text for trigger in CONDITION_TRIGGERS):
        return None
    if NEGATION_RE.search(text):
        return None
    if REL_TIME_RE.search(text) or TIME_RE.search(text):
        return None

    interval_minutes = 0
    interval_match = INTERVAL_RE.search(text)
    if interval_match:
        raw_number = interval_match.group("num")
        unit = interval_match.group("unit")
        if raw_number:
            number = _to_int(raw_number)
            if number:
                if raw_number == "半":
                    interval_minutes = 30 if unit in {"小时", "钟头"} else 1
                else:
                    interval_minutes = number * 60 if unit in {"小时", "钟头"} else number
        else:
            interval_minutes = 60 if unit in {"小时", "钟头"} else 1
        interval_minutes = max(1, min(1440, interval_minutes))
        text = f"{text[:interval_match.start()]} {text[interval_match.end():]}"

    condition = re.sub(r"^(如果|要是|到时候|当(?!前))\s*", "", text)
    condition = re.sub(r"(帮我|请|麻烦|记得)", " ", condition)
    condition = re.sub(
        r"(提醒我一声|提醒我一下|提醒一声|提醒一下|提醒我|提醒|告诉我|通知我|"
        r"叫我(?:\s*(?:一声|一下))?)",
        " ",
        condition,
    )
    condition = re.sub(r"[，,。.!！？?~：:；;]", " ", condition)
    condition = re.sub(r"\s+", " ", condition).strip()
    if not condition:
        return None

    core = CONDITION_FILLER_RE.sub("", condition).strip()
    if len(core) < 2:
        return None
    has_number = bool(re.search(r"\d", condition))
    has_hint = any(hint in condition for hint in CONDITION_HINTS if hint != "了")
    if not (has_number or has_hint or condition.endswith("了")):
        return None
    return ReminderRequest(
        kind="condition",
        condition=condition,
        interval_minutes=interval_minutes,
    )


class ReminderStore:
    def __init__(self, db_path: Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(reminders)")}
            for name, ddl in (
                ("condition_text", "TEXT NOT NULL DEFAULT ''"),
                ("check_interval_minutes", "INTEGER NOT NULL DEFAULT 30"),
                ("next_check_at", "TEXT"),
                ("expires_at", "TEXT"),
                ("last_result", "TEXT NOT NULL DEFAULT ''"),
            ):
                if name not in columns:
                    conn.execute(f"ALTER TABLE reminders ADD COLUMN {name} {ddl}")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_condition "
                "ON reminders(kind, status, next_check_at)"
            )
            conn.execute(
                "UPDATE reminders SET status='done' WHERE kind='price' AND status='pending'"
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    def add_time(self, session_key: str, due_at: datetime, content: str) -> int:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO reminders(session_key, kind, content, due_at, created_at) VALUES(?,?,?,?,?)",
                (session_key, "time", content, due_at.isoformat(timespec="seconds"), self._now()),
            )
            return int(cursor.lastrowid)

    def add_condition(
        self,
        session_key: str,
        condition: str,
        interval_minutes: int,
        expires_at: datetime,
    ) -> int:
        now = self._now()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO reminders("
                "session_key, kind, condition_text, check_interval_minutes, "
                "next_check_at, expires_at, created_at"
                ") VALUES(?,?,?,?,?,?,?)",
                (
                    session_key,
                    "condition",
                    condition,
                    interval_minutes,
                    now,
                    expires_at.isoformat(timespec="seconds"),
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def due_time(self, now: str) -> list[sqlite3.Row]:
        conn = self._connect()
        try:
            return conn.execute(
                "SELECT * FROM reminders WHERE kind='time' AND status='pending' AND due_at<=? ORDER BY due_at",
                (now,),
            ).fetchall()
        finally:
            conn.close()

    def due_conditions(self, now: str) -> list[sqlite3.Row]:
        conn = self._connect()
        try:
            return conn.execute(
                "SELECT * FROM reminders "
                "WHERE kind='condition' AND status='pending' AND next_check_at<=? "
                "ORDER BY next_check_at",
                (now,),
            ).fetchall()
        finally:
            conn.close()

    def reschedule_condition(self, reminder_id: int, next_at: datetime, last_result: str = "") -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE reminders SET next_check_at=?, last_result=? WHERE id=?",
                (next_at.isoformat(timespec="seconds"), last_result, reminder_id),
            )

    def mark_done(self, reminder_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE reminders SET status='done', triggered_at=? WHERE id=?",
                (self._now(), reminder_id),
            )

    def list_pending(self, session_key: str) -> list[sqlite3.Row]:
        conn = self._connect()
        try:
            return conn.execute(
                "SELECT * FROM reminders "
                "WHERE session_key=? AND status='pending' AND kind IN ('time','condition') "
                "ORDER BY id",
                (session_key,),
            ).fetchall()
        finally:
            conn.close()

    def cancel(self, session_key: str, reminder_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM reminders WHERE id=? AND session_key=? AND status='pending'",
                (reminder_id, session_key),
            )
            return cursor.rowcount > 0

    def cancel_all(self, session_key: str) -> int:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE reminders SET status='done', triggered_at=? "
                "WHERE session_key=? AND status='pending' AND kind IN ('time','condition')",
                (self._now(), session_key),
            )
            return cursor.rowcount


class ReminderScheduler:
    def __init__(
        self,
        store: ReminderStore,
        send: Callable[[str, str], None],
        time_interval: float,
    ):
        self.store = store
        self.send = send
        self.time_interval = time_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="reminder-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.time_interval):
            try:
                self._check_time()
            except Exception:
                logger.exception("检查定时提醒失败")

    def _check_time(self) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        for row in self.store.due_time(now):
            if str(row["session_key"]).endswith("@chatroom"):
                self.store.mark_done(row["id"])
                logger.info("跳过群聊定时提醒 id=%s", row["id"])
                continue
            text = f"提醒你：{row['content']}" if row["content"] else "到点了。"
            self.send(row["session_key"], text)
            self.store.mark_done(row["id"])
            logger.info("已发送定时提醒 id=%s 会话=%s", row["id"], row["session_key"])
