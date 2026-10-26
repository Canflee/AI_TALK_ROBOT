import re
from pathlib import Path

from ..pdf import extract_pdf_text

DOC_MAX_CHARS = 60000
DOC_MAX_PAGES = 50
DOC_MAX_OCR_PAGES = 20

DOCUMENT_SUFFIXES = {".pdf", ".docx", ".doc"}


class DocumentError(RuntimeError):
    pass


def is_document_path(path: str) -> bool:
    return Path(path).suffix.lower() in DOCUMENT_SUFFIXES


def document_suffix(path: str) -> str:
    return Path(path).suffix.lower()


def read_document(path: str, max_chars: int = DOC_MAX_CHARS) -> str:
    suffix = document_suffix(path)
    if suffix == ".pdf":
        text = extract_pdf_text(
            path,
            max_pages=DOC_MAX_PAGES,
            max_ocr_pages=DOC_MAX_OCR_PAGES,
            max_chars=max_chars,
        )
    elif suffix == ".docx":
        text = read_docx_text(path, max_chars=max_chars)
    elif suffix == ".doc":
        raise DocumentError("暂不支持 .doc，请先另存为 .docx 再发")
    else:
        raise DocumentError(f"不支持的文档格式：{suffix or '未知'}")

    text = _clean(text)
    if not text:
        raise DocumentError("没有提取到文字，可能是扫描件或加密文档")
    return text[:max_chars]


def read_docx_text(path: str, max_chars: int = DOC_MAX_CHARS) -> str:
    try:
        from docx import Document
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as exc:
        raise DocumentError("缺少 python-docx，请安装依赖") from exc

    try:
        document = Document(path)
    except Exception as exc:
        raise DocumentError(f"Word 文档打不开：{exc}") from exc

    parts: list[str] = []
    used = 0
    for child in document.element.body.iterchildren():
        text = ""
        if child.tag == qn("w:p"):
            text = Paragraph(child, document).text
        elif child.tag == qn("w:tbl"):
            table = Table(child, document)
            rows = []
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    rows.append(" | ".join(cells))
            text = "\n".join(rows)
        if not text.strip():
            continue
        parts.append(text.strip())
        used += len(text)
        if used >= max_chars:
            break

    for section in document.sections:
        for container in (section.header, section.footer):
            for paragraph in container.paragraphs:
                if paragraph.text.strip():
                    parts.append(paragraph.text.strip())

    return "\n\n".join(parts)


def _clean(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
