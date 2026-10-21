import logging
import re
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

def _clean(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _pypdf_text(path: str, max_pages: int) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(path)
        parts = []
        for page in reader.pages[:max_pages]:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        return _clean("\n".join(parts))
    except Exception:
        logger.warning("pypdf 提取失败: %s", path, exc_info=True)
        return ""


def _render_ocr(path: str, max_ocr_pages: int, max_chars: int) -> str:
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz

        from .ocr import ocr_image

        doc = fitz.open(path)
        parts = []
        with tempfile.TemporaryDirectory() as tmp:
            for index in range(min(len(doc), max_ocr_pages)):
                page = doc[index]
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                image_path = str(Path(tmp) / f"page_{index}.png")
                pix.save(image_path)
                text = ocr_image(image_path)
                if text:
                    parts.append(text)
                if sum(len(part) for part in parts) >= max_chars:
                    break
        doc.close()
        return _clean("\n\n".join(parts))
    except Exception:
        logger.warning("PDF 渲染 OCR 失败: %s", path, exc_info=True)
        return ""


def extract_pdf_text(
    path: str,
    max_pages: int,
    max_ocr_pages: int,
    max_chars: int,
) -> str:
    text = _pypdf_text(path, max_pages)
    if len(text) >= 40:
        return text[:max_chars]
    ocr = _render_ocr(path, max_ocr_pages, max_chars)
    return (ocr or text)[:max_chars]
