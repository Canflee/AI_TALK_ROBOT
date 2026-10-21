import html
import logging
import re
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from ..config import BASE_DIR
from ..models import ChatType, IncomingMessage
from .base import ChatAdapter

logger = logging.getLogger(__name__)

TEXT_TYPE = "文本"
IMAGE_TYPE = "图片"
FILE_TYPE = "文件/链接/卡片"
STICKER_TYPES = {"动画表情", "表情"}
MEDIA_DIR = BASE_DIR / "data" / "media"


class WeChat4Adapter(ChatAdapter):
    def __init__(
        self,
        interval: float,
        max_file_bytes: int,
        max_sticker_bytes: int,
    ):
        self.interval = interval
        self.max_file_bytes = max_file_bytes
        self.max_sticker_bytes = max_sticker_bytes
        self._db = None
        self._listener = None
        self._on_message = None
        self._self_wxid = ""
        self._self_nick = ""
        self._nicks: dict[str, str] = {}
        self._send_targets: dict[str, str] = {}
        self._send_lock = threading.Lock()
        self._media = None

    def start(self, on_message) -> None:
        try:
            from wechatauto import WeChatDB
            from wechatauto.db import Listener
        except ImportError as exc:
            raise RuntimeError("未安装 wechatauto-replica，请使用 Python 3.12 安装依赖") from exc

        self._on_message = on_message
        try:
            from wechatauto import rhythm

            rhythm.set_profile("off")
        except Exception:
            logger.warning("关闭库内置拟人节流失败", exc_info=True)
        try:
            self._db = WeChatDB()
            info = self._db.get_self_info()
        except Exception as exc:
            raise RuntimeError(f"读取微信 4.x 数据库失败，请确认微信已登录并保持运行: {exc}") from exc

        self._self_wxid = str(info.get("username") or self._db.wxid or "")
        self._self_nick = str(info.get("nick_name") or info.get("remark") or "")
        try:
            self._nicks = dict(self._db.nickname_map() or {})
        except Exception:
            logger.warning("加载联系人昵称失败，将使用 wxid", exc_info=True)
            self._nicks = {}
        if self._self_wxid:
            self._nicks[self._self_wxid] = self._self_nick or self._self_wxid

        try:
            from wechatauto import MediaDownloader

            self._media = MediaDownloader(self._db)
            key = self._media.detect_image_key()
            if key:
                logger.info("图片解密密钥已就绪")
            else:
                logger.warning("未获取到图片解密密钥，图片消息可能无法读取")
        except Exception:
            logger.warning("初始化图片下载器失败，图片消息可能无法读取", exc_info=True)
            self._media = None

        self._listener = Listener(self._db, interval=self.interval)
        self._listener.add_all(self._on_db_message)
        self._listener.start()
        logger.info("微信 4.x 适配器已启动，账号: %s (%s)", self._self_nick or "未知", self._self_wxid)

    def _on_db_message(self, message: dict, _listener) -> None:
        try:
            incoming = self._convert(message)
        except Exception:
            logger.exception("转换微信 4.x 消息失败")
            return
        if incoming is None:
            return
        try:
            self._on_message(incoming)
        except Exception:
            logger.exception("处理微信 4.x 消息失败")

    def _convert(self, message: dict) -> IncomingMessage | None:
        msg_type = message.get("type")
        if msg_type not in (TEXT_TYPE, IMAGE_TYPE, FILE_TYPE, *STICKER_TYPES):
            return None

        sender_wxid = str(message.get("sender_username") or "")
        if sender_wxid and sender_wxid == self._self_wxid:
            return None

        session_key = str(message.get("username") or sender_wxid)
        if not session_key:
            return None

        is_group = session_key.endswith("@chatroom")
        chat_type = ChatType.GROUP if is_group else ChatType.PRIVATE
        sender_id = sender_wxid or session_key
        sender_name = self._nicks.get(sender_id) or sender_id

        image_path = ""
        file_path = ""
        file_name = ""
        if msg_type == IMAGE_TYPE:
            image_path = self._download_image(message, session_key)
            content = "(图片)" if image_path else "(图片还没同步到电脑，暂时读不到)"
        elif msg_type in STICKER_TYPES:
            image_path = self._download_sticker(
                str(message.get("content") or ""), session_key, message.get("local_id")
            )
            content = "(表情包)" if image_path else "(收到一个表情包，但没下载下来)"
        elif msg_type == FILE_TYPE:
            xml = str(message.get("content") or "")
            title = self._xml_value(xml, "title")
            refer = self._refer_block(xml)
            if refer:
                quote_type = self._xml_value(refer, "type")
                quoted_content = self._xml_value(refer, "content")
                quoted_title = self._xml_value(quoted_content, "title") if "<" in quoted_content else ""
                quoted_url = self._xml_value(quoted_content, "url") if "<" in quoted_content else ""
                svrid = self._xml_value(refer, "svrid")
                if quote_type == "3":
                    origin = self._find_message_by_server_id(session_key, svrid)
                    if origin:
                        image_path = self._download_image(origin, session_key)
                    content = f"[引用图片] {title}".strip()
                elif quoted_url:
                    if "bilibili.com" in quoted_url or "b23.tv" in quoted_url:
                        content = f"[引用视频 {quoted_title}] {quoted_url} {title}".strip()
                    elif "mp.weixin.qq.com" in quoted_url:
                        content = f"[引用文章 {quoted_title}] {quoted_url} {title}".strip()
                    else:
                        content = f"[引用链接 {quoted_title}] {quoted_url} {title}".strip()
                elif quote_type in ("6", "49") and ".pdf" in quoted_content.lower():
                    file_name = quoted_title or "PDF"
                    origin = self._find_message_by_server_id(session_key, svrid)
                    if origin:
                        file_path = self._download_file(origin, session_key, file_name)
                    content = f"[引用PDF {file_name}] {title}".strip()
                elif quoted_content and "<" not in quoted_content:
                    content = f"[引用: {quoted_content}] {title}".strip()
                else:
                    content = f"[引用] {title}".strip()
            else:
                url = self._xml_value(xml, "url")
                if url and ("bilibili.com" in url or "b23.tv" in url):
                    content = f"[链接 {title}] {url}".strip()
                elif url and "mp.weixin.qq.com" in url:
                    content = f"[公众号文章 {title}] {url}".strip()
                else:
                    file_name = title
                    if not file_name.lower().endswith(".pdf"):
                        return None
                    file_path = self._download_file(message, session_key, file_name)
                    content = f"(PDF: {file_name})" if file_path else f"(PDF 还没同步到电脑: {file_name})"
        else:
            content = str(message.get("content") or "").strip()
            if not content:
                return None

        is_at_me = is_group and self._is_mentioned(content)

        return IncomingMessage(
            msg_id=f"{session_key}:{message.get('shard', '')}:{message.get('local_id', '')}",
            session_key=session_key,
            chat_type=chat_type,
            sender_id=sender_id,
            sender_name=sender_name,
            content=content,
            is_at_me=is_at_me,
            room_id=session_key if is_group else "",
            image_path=image_path,
            file_path=file_path,
            file_name=file_name,
            is_sticker=msg_type in STICKER_TYPES,
        )

    def _download_image(self, message: dict, session_key: str) -> str:
        if self._media is None:
            return ""
        local_id = message.get("local_id")
        if local_id is None:
            return ""
        delays = (0.0, 0.5, 1.0, 2.0)
        for attempt, delay in enumerate(delays):
            if delay:
                time.sleep(delay)
            try:
                MEDIA_DIR.mkdir(parents=True, exist_ok=True)
                path = self._media.download_image(
                    session_key,
                    int(local_id),
                    save_dir=str(MEDIA_DIR),
                    shard=message.get("shard"),
                    tier="best",
                )
            except Exception:
                logger.warning("下载图片失败，会话=%s local_id=%s", session_key, local_id, exc_info=True)
                path = None
            if path:
                return str(path)
            if attempt < len(delays) - 1:
                logger.info("图片尚未落盘，稍后重试，会话=%s local_id=%s", session_key, local_id)
        logger.warning("图片本地副本不存在，会话=%s local_id=%s", session_key, local_id)
        return ""

    @staticmethod
    def _file_title(xml: str) -> str:
        match = re.search(r"<title>(.*?)</title>", xml, re.S)
        return html.unescape(match.group(1)).strip() if match else ""

    def _download_sticker(self, xml: str, session_key: str, local_id) -> str:
        match = re.search(r'cdnurl="([^"]+)"', xml)
        if not match:
            return ""
        url = html.unescape(match.group(1))
        md5_match = re.search(r'md5="([0-9a-fA-F]{32})"', xml)
        md5 = md5_match.group(1).lower() if md5_match else ""

        if md5:
            for ext in (".gif", ".png", ".jpg", ".jpeg", ".webp"):
                cached = MEDIA_DIR / f"sticker_{md5}{ext}"
                if cached.exists():
                    return str(cached)

        host = urlparse(url).hostname or ""
        if host != "qq.com" and not host.endswith(".qq.com"):
            logger.warning("表情包地址不可信: %s", host)
            return ""

        try:
            response = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://weixin.qq.com/"},
                timeout=30,
            )
            response.raise_for_status()
        except Exception:
            logger.warning("下载表情包失败，会话=%s local_id=%s", session_key, local_id, exc_info=True)
            return ""

        data = response.content
        if not data or len(data) > self.max_sticker_bytes:
            return ""
        if data.startswith(b"GIF"):
            ext = ".gif"
        elif data.startswith(b"\x89PNG"):
            ext = ".png"
        elif data.startswith(b"\xff\xd8"):
            ext = ".jpg"
        elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            ext = ".webp"
        else:
            logger.warning("表情包格式不支持，会话=%s local_id=%s", session_key, local_id)
            return ""

        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        name = md5 or f"{session_key}_{local_id}"
        target = MEDIA_DIR / f"sticker_{name}{ext}"
        target.write_bytes(data)
        return str(target)

    @staticmethod
    def _xml_value(xml: str, tag: str) -> str:
        match = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
        return html.unescape(match.group(1)).strip() if match else ""

    @staticmethod
    def _refer_block(xml: str) -> str:
        match = re.search(r"<refermsg>(.*?)</refermsg>", xml, re.S)
        return html.unescape(match.group(1)).strip() if match else ""

    def _find_message_by_server_id(self, user: str, svrid: str) -> dict | None:
        try:
            target = int(svrid)
        except (TypeError, ValueError):
            return None
        try:
            for conn, table in self._db._msg_conns(user):
                row = conn.execute(
                    f'SELECT local_id FROM "{table}" WHERE server_id=? LIMIT 1',
                    (target,),
                ).fetchone()
                if row:
                    return {
                        "local_id": row[0],
                        "username": user,
                        "shard": self._db._shard_label(conn),
                    }
        except Exception:
            logger.warning("查找引用消息失败，svrid=%s", svrid, exc_info=True)
        return None

    def _download_file(self, message: dict, session_key: str, file_name: str) -> str:
        if self._db is None:
            return ""
        safe_name = Path(file_name).name
        if not safe_name:
            return ""
        base = Path(self._db.account_dir) / "msg" / "file"
        local_id = message.get("local_id", "")
        delays = (0.0, 0.5, 1.0, 2.0)
        for attempt, delay in enumerate(delays):
            if delay:
                time.sleep(delay)
            matches = []
            try:
                if base.exists():
                    matches = [
                        path for path in base.rglob("*")
                        if path.is_file() and path.name == safe_name
                    ]
            except Exception:
                logger.warning("查找 PDF 文件失败: %s", safe_name, exc_info=True)

            if matches:
                try:
                    source = max(matches, key=lambda path: path.stat().st_mtime)
                    if source.stat().st_size > self.max_file_bytes:
                        logger.warning("PDF 文件过大，跳过: %s", source)
                        return ""
                    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
                    target = MEDIA_DIR / f"{session_key}_{local_id}_{safe_name}"
                    if target.exists() and target.stat().st_size == source.stat().st_size:
                        return str(target)
                    if target.exists():
                        try:
                            target.chmod(0o666)
                        except OSError:
                            pass
                    shutil.copyfile(source, target)
                    return str(target)
                except Exception:
                    logger.warning("复制 PDF 文件失败: %s", safe_name, exc_info=True)
                    return ""

            if attempt < len(delays) - 1:
                logger.info("PDF 尚未落盘，稍后重试: %s", safe_name)

        logger.warning("PDF 本地文件不存在: %s", safe_name)
        return ""

    def _is_mentioned(self, content: str) -> bool:
        names = {self._self_nick}
        names.discard("")
        return any(f"@{name}" in content for name in names)

    def _send_target(self, session_key: str) -> str:
        cached = self._send_targets.get(session_key)
        if cached:
            return cached
        name = session_key
        try:
            if session_key.endswith("@chatroom"):
                name = self._db.group_id_to_name(session_key) or session_key
            else:
                name = self._db.get_nickname(session_key) or session_key
        except Exception:
            logger.warning("解析发送目标失败: %s", session_key, exc_info=True)
        self._send_targets[session_key] = name
        return name

    def send_text(self, session_key: str, text: str, at_wxid: str = "", at_name: str = "") -> bool:
        if not text.strip():
            return False
        try:
            from wechatauto.guia import quick_send
        except ImportError:
            logger.error("wechatauto 未安装，无法发送消息")
            return False

        body = text
        if at_wxid and at_name:
            body = f"@{at_name} {text}"
        target = self._send_target(session_key)

        with self._send_lock:
            response = None
            for attempt in range(2):
                try:
                    response = quick_send(body, who=target, verify=False)
                except Exception:
                    logger.exception("发送微信 4.x 消息失败，会话=%s", session_key)
                    response = None

                if response is not None and response.is_success:
                    return True

                reason = str(response.get("message") if response is not None else "")
                transient = any(key in reason for key in ("输入框", "会话", "窗口", "超时"))
                if attempt == 0 and transient:
                    logger.warning("发送失败，1.5 秒后重试: %s", reason)
                    time.sleep(1.5)
                    continue
                break

        if response is not None and response.is_success:
            return True
        logger.error("发送微信 4.x 消息失败，会话=%s，目标=%s，原因=%s", session_key, target, response.get("message") if response else "未知")
        return False

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                logger.debug("停止微信 4.x 监听失败", exc_info=True)
            self._listener = None
        self._db = None
        logger.info("微信 4.x 适配器已停止")
