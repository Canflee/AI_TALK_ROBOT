import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from ..models import ChatType, IncomingMessage
from ..prompt import image_data_url
from .processor import process_document
from .reader import DocumentError, is_document_path, read_document
from .store import DocumentStore
from .writer import write_outputs

logger = logging.getLogger(__name__)

DOC_PENDING_MINUTES = 30
DOC_PARSE_WAIT_SECONDS = 120

EXPORT_PATTERN = re.compile(
    r"(?:写成|转成|导出|生成|整理成|做成|保存成|弄成|发我|给我).{0,8}"
    r"(?:word|docx|pdf|文档|文件)"
    r"|(?:word|docx|pdf).{0,6}(?:给我|发我|导出)"
    r"|(?:整理|导出).{0,4}(?:聊天记录|对话记录|记录)",
    re.I,
)
DOC_OUTPUT_PATTERN = re.compile(
    r"(?:写成|转成|导出|生成|整理成|做成|保存成|弄成|发我|给我).{0,8}"
    r"(?:word|docx|pdf|文档|文件)"
    r"|(?:word|docx|pdf).{0,6}(?:给我|发我|导出)",
    re.I,
)

CHAT_EXPORT_PATTERN = re.compile(
    r"(?:聊天记录|对话记录|聊天内容|导出记录|导出聊天)",
    re.I,
)

DOC_ACTION_WORDS = (
    "总结", "摘要", "概括", "提炼", "翻译", "译成", "英文", "中文",
    "改写", "润色", "重写", "扩写", "缩写", "提取", "整理", "排版",
    "格式", "转成", "转换", "生成", "做成", "输出", "分点", "要点",
    "重点", "表格", "邮件", "大纲", "校对", "检查", "修改", "分析",
    "评价", "讲了什么", "说什么", "内容", "主要", "看看", "看下",
    "看一下", "改", "列", "处理", "ppt", "幻灯片", "演示", "写成", "变成",
    "完成", "做完", "解题", "做题", "解答", "答案", "作业", "题目", "证明", "计算", "推导", "写",
)
DOC_CANCEL_WORDS = (
    "算了", "不用了", "不弄了", "不处理了", "取消", "先不弄",
    "暂时不用", "没事了", "不用处理", "不做了",
)

DOC_HELP = """文档处理：
#doc                 查看最近文档和帮助
#doc status          查看最近文档状态
#doc cancel          取消最近文档任务
#doc <要求>          处理最近收到的 PDF/Word，例如：
  #doc 总结成一页
  #doc 翻译成英文
  #doc 改写成正式邮件
处理结果会生成 Word 和 PDF，保存到 data/processed/ 后发给你。"""


class DocumentMixin:
    def _init_documents(self) -> None:
        self.document_store = DocumentStore(self.settings.db_path)
        self._doc_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="doc")
        self._doc_ack_timers: dict[str, threading.Timer] = {}
        self._doc_ack_lock = threading.Lock()

    def _shutdown_documents(self) -> None:
        with self._doc_ack_lock:
            timers = list(self._doc_ack_timers.values())
            self._doc_ack_timers.clear()
        for timer in timers:
            timer.cancel()
        self._doc_executor.shutdown(wait=False, cancel_futures=True)

    def _cancel_document_ack(self, session_key: str) -> None:
        with self._doc_ack_lock:
            timer = self._doc_ack_timers.pop(session_key, None)
        if timer is not None:
            timer.cancel()

    def _wait_document_text(self, session_key: str) -> None:
        job = self.document_store.latest(session_key, DOC_PENDING_MINUTES)
        if job is None or job["status"] != "pending":
            return
        deadline = time.time() + DOC_PARSE_WAIT_SECONDS
        while time.time() < deadline:
            time.sleep(0.5)
            job = self.document_store.get(job["id"])
            if job is None or job["status"] != "pending":
                return

    def _schedule_document_ack(self, session_key: str, job_id: int) -> None:
        self._cancel_document_ack(session_key)
        with self._batch_lock:
            if self._batches.get(session_key):
                return
        timer = threading.Timer(
            self.settings.reply_debounce,
            self._send_document_ack,
            args=(session_key, job_id),
        )
        timer.daemon = True
        with self._doc_ack_lock:
            self._doc_ack_timers[session_key] = timer
        timer.start()

    def _send_document_ack(self, session_key: str, job_id: int) -> None:
        with self._doc_ack_lock:
            self._doc_ack_timers.pop(session_key, None)
        with self._batch_lock:
            if self._batches.get(session_key):
                return
        job = self.document_store.get(job_id)
        if job is None or job["status"] != "awaiting":
            return
        self._send(
            session_key,
            f"收到《{job['source_name']}》，已经看过了，大概 {len(job['text'] or '')} 字。\n"
            "你想让我做什么？总结、翻译、改写、提取重点都可以，直接回复要求就行。",
            split=False,
        )

    def _register_document_job(
        self,
        session_key: str,
        msg_id: str,
        source_path: str,
        source_name: str,
    ) -> int | None:
        if not is_document_path(source_path):
            return None
        try:
            job_id = self.document_store.create(
                session_key=session_key,
                msg_id=msg_id,
                source_path=source_path,
                source_name=source_name or Path(source_path).name,
                source_type=Path(source_path).suffix.lower().lstrip("."),
            )
            logger.info("文档任务已登记，会话=%s 任务=%s 文件=%s", session_key, job_id, source_name)
            return job_id
        except Exception:
            logger.exception("登记文档任务失败，会话=%s", session_key)
            return None

    def _ingest_document(self, job_id: int) -> None:
        job = self.document_store.get(job_id)
        if job is None or job["status"] == "cancelled":
            return
        session_key = job["session_key"]
        source = Path(job["source_path"])
        try:
            if not source.exists():
                raise DocumentError("原文件已经不在了，请重新发一次")
            text = read_document(str(source))
            current = self.document_store.get(job_id)
            if current is not None and current["status"] in {"queued", "processing", "cancelled"}:
                self.document_store.update(job_id, text=text)
                return
            self.document_store.update(job_id, text=text, status="awaiting", error="")
            logger.info(
                "文档读取完成，任务=%s 文件=%s 字符数=%s",
                job_id,
                job["source_name"],
                len(text),
            )
            self._schedule_document_ack(session_key, job_id)
        except Exception as exc:
            logger.exception("读取文档失败，任务=%s", job_id)
            self.document_store.update(job_id, status="failed", error=str(exc)[:500])
            self._send(session_key, f"收到文件了，但没能读出来：{exc}")

    def _maybe_handle_document_instruction(self, message: IncomingMessage) -> bool:
        if message.chat_type != ChatType.PRIVATE or message.file_path:
            return False
        text = message.content.strip()
        if not text or text.startswith("#"):
            return False
        job = self.document_store.latest(message.session_key, DOC_PENDING_MINUTES)
        if job is None or job["status"] != "awaiting":
            return False

        if self._is_document_cancel(text):
            self.document_store.update(job["id"], status="cancelled")
            self._send(message.session_key, "好，那这个文档先不处理了")
            return True
        if not self._looks_like_document_instruction(text):
            return False

        self.document_store.update(
            job["id"],
            status="queued",
            instruction=text,
            error="",
        )
        self._send(
            message.session_key,
            f"开始处理《{job['source_name']}》，输出 {self._format_label(self._requested_formats(text))}",
        )
        self._doc_executor.submit(self._run_document_job, job["id"])
        return True

    def _maybe_handle_export_request(self, message: IncomingMessage) -> bool:
        if message.chat_type != ChatType.PRIVATE or message.file_path:
            return False
        text = message.content.strip()
        if not text or text.startswith("#"):
            return False
        if not EXPORT_PATTERN.search(text):
            return False

        job = self.document_store.latest(message.session_key, DOC_PENDING_MINUTES)
        if job is not None and job["status"] == "pending":
            self._send(message.session_key, "文档还在读，稍等几秒再发要求")
            return True
        if job is not None and job["status"] in {"queued", "processing"}:
            self._send(message.session_key, "这个文档正在处理，等我发结果就行")
            return True
        if job is not None and job["status"] in {"awaiting", "done", "failed"}:
            formats = self._requested_formats(text)
            self.document_store.update(
                job["id"],
                status="queued",
                instruction=text,
                error="",
            )
            self._send(
                message.session_key,
                f"好，我把《{job['source_name']}》处理成 {self._format_label(formats)} 发你",
            )
            self._doc_executor.submit(self._run_document_job, job["id"])
            return True

        if not CHAT_EXPORT_PATTERN.search(text):
            return False

        formats = self._requested_formats(text)
        self._send(
            message.session_key,
            f"好，我把最近的聊天整理成 {self._format_label(formats)}",
        )
        self._doc_executor.submit(self._run_chat_export, message.session_key, formats)
        return True

    def _maybe_handle_media_document_request(self, message: IncomingMessage) -> bool:
        if message.chat_type != ChatType.PRIVATE or message.file_path:
            return False
        text = message.content.strip()
        if not text or text.startswith("#"):
            return False
        if not self._is_output_request(text):
            return False
        if CHAT_EXPORT_PATTERN.search(text):
            return False

        with self._batch_lock:
            pending = list(self._batches.get(message.session_key, []))
        image_paths: list[str] = []
        file_paths: list[str] = []
        texts: list[str] = []
        for route in pending:
            if route.image_path:
                image_paths.append(route.image_path)
            if route.file_path:
                file_paths.append(route.file_path)
            if route.user_text.strip():
                texts.append(route.user_text.strip())

        recent = self._recent_media.get(message.session_key)
        if recent is not None and time.time() - recent[0] <= 600:
            image_paths.extend(recent[1])
            file_paths.extend(recent[2])
            if recent[3].strip():
                texts.append(recent[3].strip())

        image_paths = list(dict.fromkeys(path for path in image_paths if path and Path(path).exists()))
        file_paths = list(dict.fromkeys(path for path in file_paths if path and Path(path).exists()))
        if not image_paths and not file_paths:
            return False

        self._drop_batch(message.session_key)
        formats = self._requested_formats(text)
        instruction = "\n".join(texts + [text]).strip()
        title = "作业解答" if any(word in instruction for word in ("题", "作业", "解答", "计算", "证明")) else "整理结果"
        self._send(
            message.session_key,
            f"好，我把这部分内容整理成 {self._format_label(formats)}，稍等",
        )
        self._doc_executor.submit(
            self._run_media_document,
            message.session_key,
            image_paths,
            file_paths,
            instruction,
            formats,
            title,
        )
        return True

    def _run_media_document(
        self,
        session_key: str,
        image_paths: list[str],
        file_paths: list[str],
        instruction: str,
        formats: tuple[str, ...],
        title: str,
    ) -> None:
        try:
            history = self.store.recent_messages(session_key, 12)
            context_lines = []
            for item in history[-8:]:
                content = item.content.strip()
                if not content:
                    continue
                label = "对方" if item.role == "user" else "我"
                context_lines.append(f"{label}: {content[:1500]}")
            file_texts = []
            for path in file_paths[: self.settings.pdf_max_files]:
                try:
                    file_texts.append(read_document(path))
                except Exception:
                    logger.warning("读取文件失败: %s", path, exc_info=True)

            user_text = (
                "最近对话：\n"
                + ("\n".join(context_lines) if context_lines else "（无）")
                + "\n\n用户要求：\n"
                + (instruction or "请解答图片中的题目")
            )
            if file_texts:
                user_text += "\n\n文件内容：\n" + "\n\n".join(file_texts)[:30000]

            system = (
                "你是一个作业解答和文档整理助手。根据用户提供的图片、文件和最近对话，"
                "完整解答题目或整理内容。只输出最终正文，适合直接放进 Word/PDF。"
                "保留题目、步骤、公式、数字和最终答案；不要输出分析、计划、聊天口吻或“以下是”开场白。"
                "不要使用 Markdown 代码块或表格；标题可以单独一行，列表用“- ”开头。"
                "原文没有的信息不要编造。"
            )
            messages: list[dict] = [{"role": "system", "content": system}]
            if image_paths:
                parts: list[dict] = [{"type": "text", "text": user_text}]
                for path in image_paths[: self.settings.prompt_max_images]:
                    data_url = image_data_url(
                        path,
                        self.settings.prompt_max_image_side,
                        self.settings.prompt_image_quality,
                    )
                    if data_url:
                        parts.append({"type": "image_url", "image_url": {"url": data_url}})
                messages.append({"role": "user", "content": parts})
            else:
                messages.append({"role": "user", "content": user_text})

            answer = self.llm.chat(
                messages,
                model=self.settings.default_model,
                temperature=0.3,
                max_tokens=self.settings.doc_max_output_tokens,
            ).strip()
            if not answer:
                raise DocumentError("模型没有生成内容")

            export_id = time.time_ns() // 1_000_000
            docx_path, pdf_path = write_outputs(answer, export_id, title, formats)
            logger.info(
                "图片/作业文档处理完成，会话=%s Word=%s PDF=%s",
                session_key,
                docx_path,
                pdf_path,
            )
            self._send(session_key, "整理好了，文件发你")
            sent = []
            if docx_path is not None and self.adapter.send_file(session_key, str(docx_path)):
                sent.append("Word")
            if pdf_path is not None and self.adapter.send_file(session_key, str(pdf_path)):
                sent.append("PDF")
            expected = int(docx_path is not None) + int(pdf_path is not None)
            if not sent:
                self._send(session_key, "文件发送失败了，结果保存在 data/processed 里")
            elif len(sent) < expected:
                self._send(session_key, "有一个格式没生成或没发出去")
        except Exception as exc:
            logger.exception("图片/作业文档处理失败，会话=%s", session_key)
            self._send(session_key, f"整理失败：{exc}")

    def _run_chat_export(self, session_key: str, formats: tuple[str, ...]) -> None:
        history = self.store.recent_messages(session_key, 30)
        text = self._format_chat_export(history)
        if not text:
            self._send(session_key, "最近没有可以导出的聊天内容")
            return
        export_id = time.time_ns() // 1_000_000
        try:
            docx_path, pdf_path = write_outputs(text, export_id, "聊天记录", formats)
            logger.info(
                "聊天记录导出完成，会话=%s 目录=%s",
                session_key,
                (docx_path or pdf_path).parent,
            )
            self._send(session_key, "整理好了，文件发你")
            sent = []
            if docx_path is not None and self.adapter.send_file(session_key, str(docx_path)):
                sent.append("Word")
            if pdf_path is not None and self.adapter.send_file(session_key, str(pdf_path)):
                sent.append("PDF")
            expected = int(docx_path is not None) + int(pdf_path is not None)
            if not sent:
                self._send(session_key, "文件发送失败了，结果保存在 data/processed 里")
            elif len(sent) < expected:
                self._send(session_key, "有一个格式没生成或没发出去")
        except Exception as exc:
            logger.exception("聊天记录导出失败，会话=%s", session_key)
            self._send(session_key, f"导出失败：{exc}")

    def _format_chat_export(self, history) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = ["# 聊天记录", f"导出时间：{now}", ""]
        used = 0
        for item in history:
            content = item.content.strip()
            if not content:
                continue
            if item.role == "user":
                label = item.sender or "对方"
                content = self._clean_export_content(content)
            elif item.role == "assistant":
                label = "助手"
            else:
                continue
            if not content:
                continue
            lines.extend([f"## {label}", content, ""])
            used += len(content)
            if used >= 50000:
                break
        return "\n".join(lines).strip()

    @staticmethod
    def _clean_export_content(text: str) -> str:
        for marker in ("\n[搜索 ", "\n[视频]", "\n[文章]", "\n[文档]"):
            if marker in text:
                text = text.split(marker, 1)[0]
        text = re.sub(r"^\[(?:图片|文档)\][^\n]*\n?", "", text).strip()
        return text[:2000]

    @staticmethod
    def _is_output_request(text: str) -> bool:
        return bool(DOC_OUTPUT_PATTERN.search(text or ""))

    @staticmethod
    def _requested_formats(text: str) -> tuple[str, ...]:
        lowered = (text or "").lower()
        wants_pdf = "pdf" in lowered
        wants_word = any(word in lowered for word in ("word", "docx", "doc", "文档"))
        if wants_word and not wants_pdf:
            return ("docx",)
        if wants_pdf and not wants_word:
            return ("pdf",)
        return ("docx", "pdf")

    @staticmethod
    def _format_label(formats: tuple[str, ...]) -> str:
        names = {"docx": "Word", "pdf": "PDF"}
        return " 和 ".join(names[item] for item in formats if item in names)

    def _recent_answers(self, session_key: str) -> str:
        history = self.store.recent_messages(session_key, 20)
        parts = []
        for item in history:
            if item.role != "assistant":
                continue
            content = item.content.strip()
            if not content:
                continue
            if any(skip in content for skip in ("发不了 Word", "发不了Word", "文件发你", "开始处理")):
                continue
            parts.append(content)
        return "\n\n".join(parts)[-15000:]

    def _handle_doc_command(self, message: IncomingMessage, parts: list[str]) -> None:
        if message.chat_type != ChatType.PRIVATE:
            self._send(message.session_key, "文档处理只在私聊里用")
            return
        if not self.settings.allows_reply(message.session_key):
            return

        action = " ".join(parts[1:]).strip()
        lowered = action.lower()
        job = self.document_store.latest(message.session_key, DOC_PENDING_MINUTES)

        if not action or lowered in {"help", "帮助"}:
            if job is not None:
                self._send(message.session_key, f"{self._describe_job(job)}\n\n{DOC_HELP}", split=False)
            else:
                self._send(message.session_key, f"先发一个 PDF 或 Word 给我。\n\n{DOC_HELP}", split=False)
            return

        if lowered in {"status", "状态"}:
            if job is None:
                self._send(message.session_key, "最近 30 分钟没有收到文档")
            else:
                self._send(message.session_key, self._describe_job(job), split=False)
            return

        if lowered in {"cancel", "取消"}:
            if job is None:
                self._send(message.session_key, "没有可取消的文档任务")
                return
            if job["status"] in {"queued", "processing"}:
                self._send(message.session_key, "这个文档已经在处理了，暂时不能取消")
                return
            self.document_store.update(job["id"], status="cancelled")
            self._send(message.session_key, "这个文档任务已取消")
            return

        if job is None:
            self._send(message.session_key, "最近 30 分钟没有收到 PDF 或 Word，先发文件再发 #doc 要求")
            return
        if job["status"] == "pending":
            self._send(message.session_key, "文档还在读，稍等几秒再发要求")
            return
        if job["status"] in {"queued", "processing"}:
            self._send(message.session_key, "这个文档正在处理，等我发结果就行")
            return

        self.document_store.update(job["id"], status="queued", instruction=action, error="")
        self._send(message.session_key, f"开始处理《{job['source_name']}》，大概需要一会儿")
        self._doc_executor.submit(self._run_document_job, job["id"])

    def _run_document_job(self, job_id: int) -> None:
        job = self.document_store.get(job_id)
        if job is None:
            return
        if job["status"] == "cancelled":
            return
        session_key = job["session_key"]
        source = Path(job["source_path"])
        try:
            if not source.exists():
                raise DocumentError("原文件已经不在了，请重新发一次")
            self.document_store.update(job_id, status="processing")
            text = job.get("text") or read_document(str(source))
            logger.info(
                "文档解析完成，任务=%s 文件=%s 字符数=%s",
                job_id,
                job["source_name"],
                len(text),
            )
            instruction = job["instruction"] or "总结这份文档"
            if self._is_output_request(instruction):
                answers = self._recent_answers(session_key)
                if answers:
                    text = f"【原文档】\n{text}\n\n【已有解答/讨论】\n{answers}"
                instruction = (
                    "把原文档内容和已有解答整理成一份完整、干净的文档。"
                    "保留题目、标题、公式和推导；如果是作业或题目，写出完整解答。"
                    "不要输出聊天记录、对话口吻或分析过程。"
                )
            result = process_document(
                self.llm,
                job["source_name"],
                text,
                instruction,
                self.settings.default_model,
                max_tokens=self.settings.doc_max_output_tokens,
                retry_max_tokens=self.settings.doc_retry_output_tokens,
            )
            result = result.strip()
            if not result:
                raise DocumentError("模型没有生成内容")

            formats = self._requested_formats(job["instruction"] or "")
            docx_path, pdf_path = write_outputs(result, job_id, job["source_name"], formats)
            self.document_store.update(
                job_id,
                status="done",
                output_docx=str(docx_path or ""),
                output_pdf=str(pdf_path or ""),
                error="",
            )
            logger.info("文档处理完成，任务=%s Word=%s PDF=%s", job_id, docx_path, pdf_path)

            self._send(session_key, "处理好了，文件发你")
            sent = []
            if docx_path is not None and self.adapter.send_file(session_key, str(docx_path)):
                sent.append("Word")
            if pdf_path is not None and self.adapter.send_file(session_key, str(pdf_path)):
                sent.append("PDF")
            expected = int(docx_path is not None) + int(pdf_path is not None)
            if not sent:
                self._send(session_key, "文件发送失败了，结果保存在 data/processed 里")
            elif len(sent) < expected:
                self._send(session_key, "有一个格式没生成或没发出去")
        except Exception as exc:
            logger.exception("文档处理失败，任务=%s", job_id)
            self.document_store.update(job_id, status="failed", error=str(exc)[:500])
            if "空内容" in str(exc):
                self._send(
                    session_key,
                    "模型这次思考用完了输出额度，没生成出来。可以把作业拆成几题再发一次",
                )
            else:
                self._send(session_key, f"文档处理失败：{exc}")

    @staticmethod
    def _is_document_cancel(text: str) -> bool:
        compact = text.strip().rstrip("。！!，,.")
        if "提醒" in compact:
            return False
        return compact in DOC_CANCEL_WORDS or (
            len(compact) <= 20 and any(word in compact for word in DOC_CANCEL_WORDS)
        )

    @staticmethod
    def _looks_like_document_instruction(text: str) -> bool:
        if len(text) > 120:
            return False
        lowered = text.lower()
        return any(word in lowered for word in DOC_ACTION_WORDS)

    @staticmethod
    def _describe_job(job: dict) -> str:
        status = {
            "pending": "正在读取",
            "awaiting": "已读取，等你说要做什么",
            "queued": "排队中",
            "processing": "处理中",
            "done": "已完成",
            "failed": "失败",
            "cancelled": "已取消",
        }.get(job["status"], job["status"])
        return f"最近文档：《{job['source_name']}》\n状态：{status}"
