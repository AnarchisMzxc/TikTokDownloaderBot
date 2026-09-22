import asyncio
import logging
import os
import re
import ffmpeg
import uuid
from dataclasses import dataclass
from typing import Optional

import requests
import yt_dlp

from config import cfg

logger = logging.getLogger(__name__)
URL_RE = re.compile(r"https?://\S+")
TIKWM_API = "https://www.tikwm.com/api/"
_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
class UnsupportedLinkError(Exception):
    pass

class DownloadError(Exception):
    pass

@dataclass
class MediaResult:
    file_path: str
    title: str
    duration: Optional[float] = None
    is_audio: bool = False

def extract_url(text: str) -> Optional[str]:
    match = URL_RE.search(text or "")
    if not match:
        return None
    return match.group(0).rstrip(".,;:!?)>]}\"'\u00bb")
def is_supported(url: str) -> bool:
    return any(host in url for host in cfg.supported_hosts)
def _is_tiktok(url: str) -> bool:
    return "tiktok.com" in url
def _job_dir() -> str:
    path = os.path.join(cfg.download_dir, uuid.uuid4().hex)
    os.makedirs(path, exist_ok=True)
    return path

def _base_ydl_opts(out_dir: str) -> dict:
    opts = {
        "outtmpl": os.path.join(out_dir, "%(title).80s.%(ext)s"),
        "format": f"bv*[height<={cfg.max_video_height}]+ba/b[height<={cfg.max_video_height}]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
    }
    if cfg.cookies_file:
        opts["cookiefile"] = cfg.cookies_file
    if cfg.proxy_url:
        opts["proxy"] = cfg.proxy_url
    return opts


def _sync_download_video(url: str) -> MediaResult:
    out_dir = _job_dir()
    opts = _base_ydl_opts(out_dir)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            if not os.path.exists(file_path):
                root, _ = os.path.splitext(file_path)
                candidate = root + ".mp4"
                if os.path.exists(candidate):
                    file_path = candidate
            return MediaResult(
                file_path=file_path,
                title=info.get("title") or "video",
                duration=info.get("duration"),
            )
    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(str(e)) from e


def _sync_download_audio(url: str) -> MediaResult:
    out_dir = _job_dir()
    opts = _base_ydl_opts(out_dir)
    opts.update({
        "format": "ba/b",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    })
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            root, _ = os.path.splitext(file_path)
            mp3_path = root + ".mp3"
            return MediaResult(
                file_path=mp3_path if os.path.exists(mp3_path) else file_path,
                title=info.get("title") or "audio",
                duration=info.get("duration"),
                is_audio=True,
            )
    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(str(e)) from e


def _sync_trim_clip(url: str, start_sec: int = 0, duration_sec: int = 30) -> MediaResult:
    full = _sync_download_video_any(url)
    out_path = os.path.join(os.path.dirname(full.file_path), "clip.mp4")
    try:
        (
            ffmpeg
            .input(full.file_path, ss=start_sec, t=duration_sec)
            .output(out_path, c="copy", avoid_negative_ts="make_zero")
            .overwrite_output()
            .run(quiet=True)
        )
    except ffmpeg.Error:
        (
            ffmpeg
            .input(full.file_path, ss=start_sec, t=duration_sec)
            .output(out_path, vcodec="libx264", acodec="aac")
            .overwrite_output()
            .run(quiet=True)
        )

    return MediaResult(file_path=out_path, title=full.title, duration=duration_sec)

def _tikwm_fetch_meta(url: str) -> dict:
    resp = requests.get(
        TIKWM_API, params={"url": url, "hd": 1}, headers=_HTTP_HEADERS, timeout=20
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0 or "data" not in payload:
        raise DownloadError(f"tikwm: {payload.get('msg', 'unexpected response')}")
    return payload["data"]
def _download_stream(url: str, dest_path: str):
    with requests.get(url, stream=True, headers=_HTTP_HEADERS, timeout=60) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)

def _sync_tikwm_download_video(url: str) -> MediaResult:
    meta = _tikwm_fetch_meta(url)
    media_url = meta.get("hdplay") or meta.get("play")
    if not media_url:
        raise DownloadError("tikwm: no video URL in response")
    out_dir = _job_dir()
    dest = os.path.join(out_dir, "video.mp4")
    _download_stream(media_url, dest)
    return MediaResult(
        file_path=dest,
        title=meta.get("title") or "tiktok video",
        duration=meta.get("duration"),
    )

def _sync_tikwm_download_audio(url: str) -> MediaResult:
    meta = _tikwm_fetch_meta(url)
    media_url = meta.get("music")
    if not media_url:
        raise DownloadError("tikwm: no audio URL in response")
    out_dir = _job_dir()
    dest = os.path.join(out_dir, "audio.mp3")
    _download_stream(media_url, dest)
    return MediaResult(
        file_path=dest,
        title=meta.get("title") or "tiktok audio",
        duration=meta.get("duration"),
        is_audio=True,
    )

def _sync_download_video_any(url: str) -> MediaResult:
    if _is_tiktok(url) and cfg.tiktok_backend in ("auto", "tikwm"):
        try:
            return _sync_tikwm_download_video(url)
        except Exception as e:
            if cfg.tiktok_backend == "tikwm":
                raise DownloadError(str(e)) from e
            logger.warning("tikwm video download failed (%s), falling back to yt-dlp", e)
    return _sync_download_video(url)


def _sync_download_audio_any(url: str) -> MediaResult:
    if _is_tiktok(url) and cfg.tiktok_backend in ("auto", "tikwm"):
        try:
            return _sync_tikwm_download_audio(url)
        except Exception as e:
            if cfg.tiktok_backend == "tikwm":
                raise DownloadError(str(e)) from e
            logger.warning("tikwm audio download failed (%s), falling back to yt-dlp", e)
    return _sync_download_audio(url)


async def download_video(url: str) -> MediaResult:
    if not is_supported(url):
        raise UnsupportedLinkError(url)
    return await asyncio.to_thread(_sync_download_video_any, url)


async def download_audio(url: str) -> MediaResult:
    if not is_supported(url):
        raise UnsupportedLinkError(url)
    return await asyncio.to_thread(_sync_download_audio_any, url)


async def trim_clip(url: str, start_sec: int = 0, duration_sec: int = 30) -> MediaResult:
    if not is_supported(url):
        raise UnsupportedLinkError(url)
    return await asyncio.to_thread(_sync_trim_clip, url, start_sec, duration_sec)


def cleanup(result: MediaResult):
    try:
        job_dir = os.path.dirname(result.file_path)
        for fname in os.listdir(job_dir):
            os.remove(os.path.join(job_dir, fname))
        os.rmdir(job_dir)
    except OSError:
        logger.warning("Could not fully clean up %s", result.file_path, exc_info=True)


class _CollectingLogger:
    def __init__(self):
        self.lines: list[str] = []
    def debug(self, msg):
        self.lines.append(msg)
    def info(self, msg):
        self.lines.append(msg)
    def warning(self, msg):
        self.lines.append(f"WARNING: {msg}")
    def error(self, msg):
        self.lines.append(f"ERROR: {msg}")

def _sync_debug_extract(url: str) -> str:
    collector = _CollectingLogger()
    opts = _base_ydl_opts(_job_dir())
    opts.update({
        "verbose": True,
        "quiet": False,
        "no_warnings": False,
        "logger": collector,
        "skip_download": True,
    })
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=False)
    except Exception as e:
        collector.lines.append(f"\n--- EXCEPTION ---\n{e!r}")
    return "\n".join(collector.lines)


async def debug_extract(url: str) -> str:
    return await asyncio.to_thread(_sync_debug_extract, url)
