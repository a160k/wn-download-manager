"""
video_downloader.py - yt-dlp wrapper for multimedia and streaming video downloads in MC Download Manager.
"""
from __future__ import annotations

import logging
from pathlib import Path
import re
import threading
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("MCDownloadManager.Video")

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

QUALITY_FORMAT_MAP = {
    "En İyi": "bestvideo+bestaudio/best",
    "4K (2160p)": "bestvideo[height<=2160]+bestaudio/best[height<=2160]",
    "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "Yalnızca Ses (MP3)": "bestaudio/best",
}


def is_video_site(url: str) -> bool:
    """Check if the URL belongs to popular video platforms supported by yt-dlp."""
    if not url:
        return False
    video_domains = [
        "youtube.com", "youtu.be", "vimeo.com", "dailymotion.com",
        "tiktok.com", "facebook.com", "instagram.com", "twitter.com",
        "x.com", "twitch.tv", "bilibili.com", "soundcloud.com"
    ]
    url_lower = url.lower()
    return any(domain in url_lower for domain in video_domains)


def fetch_video_info(url: str) -> Optional[Dict[str, Any]]:
    """Extract metadata (title, formats, thumbnail, duration) from URL without downloading."""
    if yt_dlp is None:
        return None

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None
            return {
                "title": info.get("title", "Video"),
                "duration": info.get("duration", 0),
                "thumbnail": info.get("thumbnail"),
                "uploader": info.get("uploader", ""),
                "is_playlist": info.get("_type") == "playlist" or "entries" in info,
                "entries_count": len(info.get("entries", [])) if "entries" in info else 1,
            }
    except Exception as e:
        logger.error(f"Failed to fetch video info: {e}")
        return None


class VideoDownloadTask:
    """Manages yt-dlp download in a background thread with progress reporting."""

    def __init__(
        self,
        download_id: int,
        url: str,
        dest_folder: str | Path,
        quality: str = "En İyi",
        is_audio_only: bool = False,
        progress_callback: Optional[Callable[[int, int, int, float, float, str], None]] = None,
        status_callback: Optional[Callable[[int, str, str], None]] = None,
        metadata_callback: Optional[Callable[[int, str, str, int, str], None]] = None,
    ):
        self.download_id = download_id
        self.url = url
        self.dest_folder = Path(dest_folder)
        self.quality = quality
        self.is_audio_only = is_audio_only or ("Ses" in quality)
        
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.metadata_callback = metadata_callback

        self.status = "Bekliyor"
        self.error_message = ""
        self._cancel_flag = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.downloaded_bytes = 0
        self.total_bytes = 0
        self.current_speed = 0.0
        self.eta = 0.0
        self.target_filepath = ""

    def start(self) -> None:
        self._cancel_flag.clear()
        self.status = "İndiriliyor"
        self._notify_status("İndiriliyor")
        self._thread = threading.Thread(
            target=self._run, name=f"VideoDownload-{self.download_id}", daemon=True
        )
        self._thread.start()

    def cancel(self) -> None:
        self._cancel_flag.set()
        self.status = "İptal Edildi"
        self._notify_status("İptal Edildi")

    def _notify_status(self, status: str, error: str = "") -> None:
        if self.status_callback:
            try:
                self.status_callback(self.download_id, status, error or self.error_message)
            except Exception as e:
                logger.debug(f"Video status callback error: {e}")

    def _progress_hook(self, d: Dict[str, Any]) -> None:
        if self._cancel_flag.is_set():
            raise Exception("İndirme kullanıcı tarafından iptal edildi.")

        status = d.get("status")
        if status == "downloading":
            self.downloaded_bytes = d.get("downloaded_bytes", 0) or 0
            self.total_bytes = (
                d.get("total_bytes") or d.get("total_bytes_estimate") or self.total_bytes or 0
            )

            # --- YÜZDE HESAPLAMA EKLENTİSİ ---
            if self.total_bytes > 0:
                self.progress = (self.downloaded_bytes / self.total_bytes) * 100
            else:
                p_str = d.get("_percent_str", "0%").strip().replace("%", "")
                try:
                    self.progress = float(p_str)
                except ValueError:
                    self.progress = 0.0

            self.speed = d.get("speed", 0) or 0
            self.status = "İndiriliyor"
            self._notify_status("İndiriliyor")

        status = d.get("status")
        if status == "downloading":
            self.downloaded_bytes = d.get("downloaded_bytes", 0) or 0
            self.total_bytes = (
                d.get("total_bytes") or d.get("total_bytes_estimate") or self.total_bytes or 0
            )
            self.current_speed = float(d.get("speed") or 0.0)
            self.eta = float(d.get("eta") or 0.0)
            
            # File name notification if available
            filename = d.get("filename")
            if filename and not self.target_filepath:
                self.target_filepath = filename
                p = Path(filename)
                if self.metadata_callback:
                    cat = "Müzik" if self.is_audio_only else "Video"
                    self.metadata_callback(self.download_id, p.name, str(p), self.total_bytes, cat)

            if self.progress_callback:
                try:
                    self.progress_callback(
                        self.download_id,
                        self.downloaded_bytes,
                        self.total_bytes,
                        self.current_speed,
                        self.eta,
                        "İndiriliyor",
                    )
                except Exception as e:
                    logger.debug(f"Video progress hook callback error: {e}")

        elif status == "finished":
            self.status = "Dönüştürülüyor"
            self._notify_status("Dönüştürülüyor")

    def _run(self) -> None:
        if yt_dlp is None:
            self.status = "Hata"
            self.error_message = "yt-dlp kütüphanesi yüklü değil."
            self._notify_status("Hata", self.error_message)
            return

        fmt = QUALITY_FORMAT_MAP.get(self.quality, "bestvideo+bestaudio/best")
        outtmpl = str(self.dest_folder / "%(title)s.%(ext)s")

        ydl_opts: Dict[str, Any] = {
            "format": fmt,
            "outtmpl": outtmpl,
            "progress_hooks": [self._progress_hook],
            "quiet": True,
            "no_warnings": True,
            "noplaylist": False,
            "ignoreerrors": True,

            # --- ALTYAZI DÜZELTMESİ ---
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["tr", "en", "tr-TR", "en-US", "tr.*", "en.*"],
            "convertsubtitles": "srt",  # Otomatik VTT altyazıları SRT'ye dönüştürür
            "postprocessors": [
                {
                    "key": "FFmpegSubtitlesConvertor",
                    "format": "srt",
                }
            ],
            "encoding": "utf-8",
        }

        if self.is_audio_only:
            ydl_opts["format"] = "bestaudio/best"
            ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=True)
                if info:
                    title = info.get("title", "Video")
                    ext = "mp3" if self.is_audio_only else (info.get("ext") or "mp4")
                    final_name = f"{title}.{ext}"
                    final_path = self.dest_folder / final_name
                    if self.metadata_callback:
                        cat = "Müzik" if self.is_audio_only else "Video"
                        filesize = self.total_bytes or (
                            final_path.stat().st_size if final_path.exists() else 0
                        )
                        self.metadata_callback(
                            self.download_id, final_name, str(final_path), filesize, cat
                        )

            if not self._cancel_flag.is_set():
                self.status = "Tamamlandı"
                if self.progress_callback:
                    self.progress_callback(
                        self.download_id,
                        self.total_bytes or self.downloaded_bytes,
                        self.total_bytes or self.downloaded_bytes,
                        0.0,
                        0.0,
                        "Tamamlandı",
                    )
                self._notify_status("Tamamlandı")

        except Exception as e:
            if self._cancel_flag.is_set():
                self.status = "İptal Edildi"
                self._notify_status("İptal Edildi")
            else:
                logger.error(f"yt-dlp execution error: {e}")
                self.status = "Hata"
                self.error_message = str(e)
                self._notify_status("Hata", str(e))
