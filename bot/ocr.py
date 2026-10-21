import asyncio
import logging
import re

logger = logging.getLogger(__name__)

_rapid = None
_rapid_checked = False


def _clean(text: str) -> str:
    text = text.replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(line for line in lines if line)
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"\s+([，。；：、？！,.!?])", r"\1", text)
    text = re.sub(r"([，。；：、？！])\s+", r"\1", text)
    return text.strip()


def _rapid_ocr(path: str) -> str:
    global _rapid, _rapid_checked
    if not _rapid_checked:
        _rapid_checked = True
        try:
            from rapidocr_onnxruntime import RapidOCR

            _rapid = RapidOCR()
            logger.info("RapidOCR 已就绪")
        except Exception:
            logger.warning("RapidOCR 不可用，改用 Windows OCR", exc_info=True)
            _rapid = None
    if _rapid is None:
        return ""
    try:
        result, _ = _rapid(path)
    except Exception:
        logger.warning("RapidOCR 识别失败", exc_info=True)
        return ""
    if not result:
        return ""
    texts = []
    for item in result:
        try:
            texts.append(str(item[1]))
        except (IndexError, TypeError):
            continue
    return _clean("\n".join(texts))


def _windows_ocr(path: str) -> str:
    try:
        from winsdk.windows.globalization import Language
        from winsdk.windows.graphics.imaging import BitmapDecoder
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.storage import FileAccessMode, StorageFile
    except Exception:
        return ""

    async def run() -> str:
        file = await StorageFile.get_file_from_path_async(path)
        stream = await file.open_async(FileAccessMode.READ)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        engine = OcrEngine.try_create_from_language(Language("zh-Hans"))
        if engine is None:
            engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            return ""
        result = await engine.recognize_async(bitmap)
        return "\n".join(line.text for line in result.lines)

    try:
        return _clean(asyncio.run(run()))
    except Exception:
        logger.warning("Windows OCR 识别失败", exc_info=True)
        return ""


def ocr_image(path: str) -> str:
    text = _rapid_ocr(path)
    if text:
        return text
    return _windows_ocr(path)
