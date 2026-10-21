import logging
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}
URL_RE = re.compile(r"https?://[^\s，。；）】)\]}]+")
BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
FRAME_ROOT = Path(tempfile.gettempdir()) / "wechatauto_video"
_info_cache: dict[str, tuple[float, "VideoInfo"]] = {}


@dataclass(slots=True)
class VideoInfo:
    bvid: str
    title: str
    owner: str
    duration: int
    desc: str
    subtitles: str
    url: str
    category: str = ""

    def to_context(self, frames_count: int = 0) -> str:
        lines = [
            f"标题：{self.title}",
            f"UP主：{self.owner}",
            f"时长：{self.duration} 秒",
            f"链接：{self.url}",
        ]
        if self.desc:
            lines.append(f"简介：{self.desc[:800]}")
        if self.subtitles:
            lines.append(f"字幕：{self.subtitles[:3000]}")
        lines.append(f"画面：已抽取 {frames_count} 帧（没有音频，不要编造台词）")
        return "\n".join(lines)


def extract_bilibili_url(text: str) -> str:
    for match in URL_RE.finditer(text or ""):
        url = match.group(0).rstrip(".,;)]}，。；）】")
        host = urlparse(url).hostname or ""
        if host == "bilibili.com" or host.endswith(".bilibili.com") or host == "b23.tv":
            return url
    return ""


def _resolve_bvid(url: str) -> str:
    match = BV_RE.search(url)
    if match:
        return match.group(1)
    response = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
    match = BV_RE.search(response.url)
    return match.group(1) if match else ""


def _fetch_subtitles(bvid: str, cid: int) -> str:
    try:
        response = requests.get(
            "https://api.bilibili.com/x/player/v2",
            params={"bvid": bvid, "cid": cid},
            headers=HEADERS,
            timeout=12,
        )
        data = response.json().get("data") or {}
        subtitles = (data.get("subtitle") or {}).get("subtitles") or []
    except Exception:
        logger.warning("获取B站字幕失败: %s", bvid, exc_info=True)
        return ""

    parts = []
    for item in subtitles[:2]:
        url = item.get("subtitle_url") or ""
        if url.startswith("//"):
            url = "https:" + url
        if not url:
            continue
        try:
            body = requests.get(url, headers=HEADERS, timeout=12).json().get("body") or []
            text = " ".join(str(line.get("content") or "") for line in body).strip()
            if text:
                parts.append(text)
        except Exception:
            logger.warning("下载B站字幕失败: %s", url, exc_info=True)
    return "\n".join(parts)[:4000]


def fetch_bilibili_info(url: str, cache_seconds: int) -> VideoInfo | None:
    cached = _info_cache.get(url)
    if cached and time.time() - cached[0] < cache_seconds:
        return cached[1]

    try:
        bvid = _resolve_bvid(url)
    except Exception:
        logger.warning("解析B站链接失败: %s", url, exc_info=True)
        return None
    if not bvid:
        return None

    try:
        data = requests.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid},
            headers=HEADERS,
            timeout=12,
        ).json().get("data")
    except Exception:
        logger.warning("获取B站视频信息失败: %s", bvid, exc_info=True)
        return None
    if not data:
        return None

    cid = 0
    pages = data.get("pages") or []
    if pages:
        cid = int(pages[0].get("cid") or 0)
    info = VideoInfo(
        bvid=bvid,
        title=str(data.get("title") or ""),
        owner=str((data.get("owner") or {}).get("name") or ""),
        duration=int(data.get("duration") or 0),
        desc=str(data.get("desc") or ""),
        subtitles=_fetch_subtitles(bvid, cid) if cid else "",
        url=f"https://www.bilibili.com/video/{bvid}",
    )
    _info_cache[url] = (time.time(), info)
    return info


def _download_video(url: str, outdir: Path, max_filesize_mb: int) -> str:
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    outdir.mkdir(parents=True, exist_ok=True)
    formats = (
        "worstvideo[ext=mp4]/worstvideo/worst",
        "30016/30011/100022/worst",
        "worst",
    )
    for fmt in formats:
        try:
            options = {
                "format": fmt,
                "outtmpl": str(outdir / "%(id)s.%(ext)s"),
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "max_filesize": max_filesize_mb * 1024 * 1024,
            }
            with YoutubeDL(options) as ydl:
                ydl.download([url])
            break
        except DownloadError:
            logger.warning("yt-dlp 下载失败，尝试下一个格式: %s", fmt)
        except Exception:
            logger.warning("yt-dlp 下载异常: %s", fmt, exc_info=True)

    files = [
        path for path in outdir.iterdir()
        if path.is_file() and path.suffix.lower() in {".mp4", ".flv", ".webm", ".mkv", ".m4v"}
    ]
    if not files:
        return ""
    return str(max(files, key=lambda path: path.stat().st_mtime))


def download_frames(
    url: str,
    duration: int,
    count: int,
    info_cache_seconds: int,
    frame_cache_seconds: int,
    max_filesize_mb: int,
    min_interval: int,
) -> list[str]:
    info = fetch_bilibili_info(url, info_cache_seconds) if url else None
    key = info.bvid if info else re.sub(r"[^0-9A-Za-z]", "_", url)[-40:]
    outdir = FRAME_ROOT / key

    existing = sorted(outdir.glob("frame_*.jpg"))
    if existing and time.time() - existing[0].stat().st_mtime < frame_cache_seconds:
        return [str(path) for path in existing[:count]]

    if outdir.exists():
        shutil.rmtree(outdir, ignore_errors=True)
    outdir.mkdir(parents=True, exist_ok=True)

    try:
        video_path = _download_video(info.url if info else url, outdir, max_filesize_mb)
    except Exception:
        logger.warning("下载B站视频失败: %s", url, exc_info=True)
        return []
    if not video_path:
        return []

    interval = max(min_interval, int(max(duration, 30) / max(count, 1)))
    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run(
            [
                ffmpeg, "-y", "-loglevel", "error", "-i", video_path,
                "-vf", f"fps=1/{interval},scale=640:-1",
                "-frames:v", str(count),
                str(outdir / "frame_%02d.jpg"),
            ],
            check=False,
            timeout=120,
        )
    except Exception:
        logger.warning("抽帧失败: %s", url, exc_info=True)

    try:
        Path(video_path).unlink(missing_ok=True)
    except OSError:
        pass

    frames = sorted(outdir.glob("frame_*.jpg"))
    return [str(path) for path in frames[:count]]
