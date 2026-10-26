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
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".doc"}
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
        self._gui = None
        self._gui_lock = threading.Lock()
        self._capture_wx = None

    def start(self, on_message) -> None:
        try:
            from wechatauto import WeChatDB
            from wechatauto.db import Listener
            from ..wechatauto_patch import install_wechatauto_db_retry
        except ImportError as exc:
            raise RuntimeError("未安装 wechatauto-replica，请使用 Python 3.12 安装依赖") from exc

        try:
            install_wechatauto_db_retry()
        except Exception:
            logger.warning("启用微信数据库访问重试失败", exc_info=True)

        self._on_message = on_message
        try:
            from wechatauto import rhythm

            profile = rhythm.profile()
            if profile.name == "off":
                profile = rhythm.set_profile("natural")
            rhythm.configure(gap=(0.0, 0.0), burst=0, window=0.0, cooloff=(0.0, 0.0))
            logger.info("拟人节奏档位: %s（点击随机化开启，发送频率限制关闭）", profile.name)
        except Exception:
            logger.warning("初始化拟人节奏失败，使用默认行为", exc_info=True)
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
                elif self._document_name(quoted_title, quoted_content):
                    file_name = self._document_name(quoted_title, quoted_content)
                    origin = self._find_message_by_server_id(session_key, svrid)
                    if origin:
                        file_path = self._download_file(origin, session_key, file_name)
                    content = f"[引用文档 {file_name}] {title}".strip()
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
                    file_name = self._document_name(title, xml)
                    if not file_name:
                        return None
                    file_path = self._download_file(message, session_key, file_name)
                    content = f"(文档: {file_name})" if file_path else f"(文档还没同步到电脑: {file_name})"
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
        md5_match = re.search(r'md5="([0-9a-fA-F]{32})"', xml)
        md5 = md5_match.group(1).lower() if md5_match else ""

        if md5:
            for ext in (".gif", ".png", ".jpg", ".jpeg", ".webp"):
                cached = MEDIA_DIR / f"sticker_{md5}{ext}"
                if cached.exists():
                    return str(cached)

        urls = self._sticker_urls(xml)
        if not urls:
            logger.warning("表情包没有可用的下载地址，会话=%s local_id=%s", session_key, local_id)
            return ""

        for url in urls[:3]:
            host = (urlparse(url).hostname or "").lower()
            if not self._trusted_media_host(host):
                logger.warning("表情包地址不可信: %s", host)
                continue
            try:
                response = requests.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0", "Referer": "https://weixin.qq.com/"},
                    timeout=10,
                )
                response.raise_for_status()
            except Exception:
                logger.warning(
                    "下载表情包失败，会话=%s local_id=%s 地址=%s",
                    session_key,
                    local_id,
                    url,
                    exc_info=True,
                )
                continue

            data = response.content
            if not data or len(data) > self.max_sticker_bytes:
                continue
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
                continue

            MEDIA_DIR.mkdir(parents=True, exist_ok=True)
            name = md5 or f"{session_key}_{local_id}"
            target = MEDIA_DIR / f"sticker_{name}{ext}"
            target.write_bytes(data)
            return str(target)

        return ""

    @staticmethod
    def _sticker_urls(xml: str) -> list[str]:
        urls: list[str] = []
        for attr in ("cdnurl", "thumburl", "externurl", "url"):
            for match in re.finditer(rf'(?<![\w]){attr}="([^"]+)"', xml):
                url = html.unescape(match.group(1)).strip()
                if url.startswith(("http://", "https://")) and url not in urls:
                    urls.append(url)
        return urls

    @staticmethod
    def _trusted_media_host(host: str) -> bool:
        return any(
            host == suffix or host.endswith(f".{suffix}")
            for suffix in ("qq.com", "qpic.cn", "wechat.com", "weixin.qq.com", "gtimg.cn", "gtimg.com")
        )

    @staticmethod
    def _xml_value(xml: str, tag: str) -> str:
        match = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
        return html.unescape(match.group(1)).strip() if match else ""

    def _document_name(self, name: str, xml: str = "") -> str:
        name = Path(html.unescape(name or "")).name.strip()
        if not name:
            return ""
        suffix = Path(name).suffix.lower()
        if not suffix:
            ext = self._xml_value(xml, "fileext").lower().lstrip(".")
            if ext:
                name = f"{name}.{ext}"
        return name if Path(name).suffix.lower() in DOCUMENT_EXTENSIONS else ""

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
        lookup_name = safe_name
        safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", safe_name)
        target_stem = Path(lookup_name).stem.lower()
        target_suffix = Path(lookup_name).suffix.lower()
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
                        if path.is_file()
                        and (
                            path.name.lower() == lookup_name.lower()
                            or (
                                path.stem.lower() == target_stem
                                and path.suffix.lower() == target_suffix
                            )
                        )
                    ]
            except Exception:
                logger.warning("查找文档文件失败: %s", safe_name, exc_info=True)

            if matches:
                try:
                    source = max(matches, key=lambda path: path.stat().st_mtime)
                    if source.stat().st_size > self.max_file_bytes:
                        logger.warning("文档文件过大，跳过: %s", source)
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
                    logger.warning("复制文档文件失败: %s", safe_name, exc_info=True)
                    return ""

            if attempt < len(delays) - 1:
                logger.info("文档尚未落盘，稍后重试: %s", safe_name)

        logger.warning("文档本地文件不存在: %s", safe_name)
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

    def _get_gui(self):
        if self._gui is not None:
            return self._gui
        with self._gui_lock:
            if self._gui is None:
                from wechatauto.guia import WeChatGUI

                gui = WeChatGUI()
                if self._db is not None:
                    gui._cached_db = self._db
                self._patch_focus_input(gui)
                self._gui = gui
        return self._gui

    @staticmethod
    def _patch_focus_input(gui) -> None:
        if getattr(gui, "_ai_talk_focus_patched", False):
            return
        from wechatauto import rhythm

        def _focus_lower(box=None) -> bool:
            if box is None:
                box = gui.get_input_box()
            if not box:
                return False
            x0, y0, x1, y1 = (int(value) for value in box)
            height = max(1, y1 - y0)
            top = y0 + max(8, int(height * 0.35))
            bottom = y0 + max(top - y0 + 1, int(height * 0.62))
            cx, cy = rhythm.point((x0, top, x1, bottom))
            gui.wx_click(gui.origin_x + cx, gui.origin_y + cy)
            time.sleep(0.6)
            return True

        gui.focus_input = _focus_lower
        gui._ai_talk_focus_patched = True
        logger.info("输入框点击位置已下移：35%-62% 高度")

    def capture_sticker(self, session_key: str) -> str:
        if self._db is None:
            return ""
        try:
            from wechatauto import WeChat
        except ImportError:
            return ""

        try:
            target = self._send_target(session_key)
            with self._send_lock:
                if self._capture_wx is None:
                    self._capture_wx = WeChat(gui=self._get_gui(), db=self._db)
                self._capture_wx.ChatWith(target)
                for message in self._capture_wx.GetAllMessage():
                    if getattr(message, "type", None) != "emotion":
                        continue
                    path = message.capture(save_dir=str(MEDIA_DIR))
                    if path:
                        logger.info("表情包截图成功，会话=%s", session_key)
                        return str(path)
        except Exception:
            logger.warning("表情包截图失败，会话=%s", session_key, exc_info=True)
        return ""

    def send_text(self, session_key: str, text: str, at_wxid: str = "", at_name: str = "") -> bool:
        if not text.strip():
            return False
        try:
            gui = self._get_gui()
        except Exception:
            logger.exception("初始化微信界面失败")
            return False

        body = text
        if at_wxid and at_name:
            body = f"@{at_name} {text}"
        target = self._send_target(session_key)

        with self._send_lock:
            response = None
            last_reason = ""
            for attempt in range(3):
                error: Exception | None = None
                try:
                    response = gui.send_msg(body, who=target, verify=False)
                except Exception as exc:
                    error = exc
                    response = None
                    logger.warning(
                        "发送微信 4.x 消息异常（%s/3），会话=%s: %s",
                        attempt + 1,
                        session_key,
                        exc,
                    )

                if response is not None and response.is_success:
                    return True

                reason = str(response.get("message") if response is not None else (error or ""))
                last_reason = reason or "未知"
                if attempt < 2 and self._is_transient_send_error(error, reason):
                    logger.warning(
                        "发送失败，%s 秒后重试（%s/3）: %s",
                        1.5 + attempt,
                        attempt + 1,
                        last_reason,
                    )
                    if error is not None and self._is_com_error(error):
                        if attempt == 0:
                            self._refresh_uia(gui)
                        else:
                            try:
                                with self._gui_lock:
                                    self._gui = None
                                gui = self._get_gui()
                            except Exception:
                                logger.exception("重新初始化微信界面失败，会话=%s", session_key)
                    time.sleep(1.5 + attempt)
                    continue
                break

        logger.error(
            "发送微信 4.x 消息失败，会话=%s，目标=%s，原因=%s",
            session_key,
            target,
            last_reason,
        )
        return False

    @staticmethod
    def _is_com_error(error: Exception) -> bool:
        text = f"{type(error).__name__}: {error}"
        return (
            type(error).__name__ == "COMError"
            or "COMError" in text
            or "事件无法调用任何订户" in text
        )

    def _is_transient_send_error(self, error: Exception | None, reason: str) -> bool:
        if error is not None and self._is_com_error(error):
            return True
        return any(key in reason for key in ("输入框", "会话", "窗口", "超时", "事件无法调用任何订户"))

    def _refresh_uia(self, gui) -> None:
        refresh = getattr(gui, "_get_uia", None)
        if not callable(refresh):
            return
        try:
            refresh(refresh=True)
        except Exception:
            logger.debug("刷新微信 UIA 失败", exc_info=True)

    def send_file(self, session_key: str, path: str) -> bool:
        if not path or not Path(path).is_file():
            logger.warning("待发送文件不存在: %s", path)
            return False
        try:
            gui = self._get_gui()
        except Exception:
            logger.exception("初始化微信界面失败")
            return False

        target = self._send_target(session_key)
        with self._send_lock:
            response = None
            last_reason = ""
            for attempt in range(3):
                error: Exception | None = None
                try:
                    response = gui.send_file(path, who=target, verify=True)
                except Exception as exc:
                    error = exc
                    response = None
                    logger.warning(
                        "发送微信 4.x 文件异常（%s/3），会话=%s 文件=%s: %s",
                        attempt + 1,
                        session_key,
                        path,
                        exc,
                    )

                if response is not None and response.is_success:
                    logger.info("文件已发送并确认，会话=%s 文件=%s", session_key, path)
                    return True

                reason = str(response.get("message") if response is not None else (error or ""))
                last_reason = reason or "未知"
                if attempt < 2 and (
                    error is not None
                    or self._is_transient_send_error(None, reason)
                    or "未确认" in reason
                    or "数据库" in reason
                ):
                    logger.warning(
                        "文件发送失败，%s 秒后重试（%s/3）: %s",
                        1.5 + attempt,
                        attempt + 1,
                        last_reason,
                    )
                    if attempt == 0:
                        self._refresh_uia(gui)
                    else:
                        try:
                            with self._gui_lock:
                                self._gui = None
                            gui = self._get_gui()
                        except Exception:
                            logger.exception("重新初始化微信界面失败，会话=%s", session_key)
                    time.sleep(1.5 + attempt)
                    continue
                break

        logger.error(
            "发送微信 4.x 文件失败，会话=%s，文件=%s，原因=%s",
            session_key,
            path,
            last_reason,
        )
        return False

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                logger.debug("停止微信 4.x 监听失败", exc_info=True)
            self._listener = None
        self._db = None
        self._gui = None
        self._capture_wx = None
        logger.info("微信 4.x 适配器已停止")
