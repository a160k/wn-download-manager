"""
clipboard_monitor.py - Background clipboard listener for MC Download Manager.
"""
from __future__ import annotations

import logging
from pathlib import Path
import threading
import time
import tkinter as tk
from typing import Callable, List, Optional
import urllib.parse

from utils import is_valid_url

logger = logging.getLogger("MCDownloadManager.Clipboard")


class ClipboardMonitor:
    """Monitors system clipboard for downloadable URLs and triggers callbacks."""

    def __init__(
        self,
        on_url_detected: Callable[[str], None],
        monitored_extensions: Optional[List[str]] = None,
        check_interval_seconds: float = 1.0,
    ):
        self.on_url_detected = on_url_detected
        self.monitored_extensions = [
            ext.lower().lstrip(".") for ext in (monitored_extensions or [])
        ]
        self.check_interval = check_interval_seconds
        
        self._last_clipboard_text = ""
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def set_extensions(self, extensions: List[str]) -> None:
        self.monitored_extensions = [ext.lower().lstrip(".") for ext in extensions]

    def start(self) -> None:
        """Start clipboard monitoring in background."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop, name="ClipboardMonitorThread", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop clipboard monitoring."""
        self._running = False
        self._stop_event.set()

    def _get_clipboard_text(self) -> Optional[str]:
        """Safely fetch clipboard text using tkinter root or fallback."""
        try:
            root = tk.Tk()
            root.withdraw()
            text = root.clipboard_get()
            root.destroy()
            return text
        except Exception:
            return None

    def _is_downloadable_url(self, text: str) -> bool:
        """Check if clipboard content looks like an actionable download URL."""
        cleaned = text.strip()
        if not is_valid_url(cleaned):
            return False

        parsed = urllib.parse.urlparse(cleaned)
        path = parsed.path.lower()
        suffix = Path(path).suffix.lstrip(".")

        # If extension matches monitored list
        if suffix and suffix in self.monitored_extensions:
            return True

        # Video platforms always trigger
        video_domains = [
            "youtube.com", "youtu.be", "vimeo.com", "dailymotion.com",
            "tiktok.com", "instagram.com", "twitter.com", "x.com"
        ]
        if any(vd in parsed.netloc.lower() for vd in video_domains):
            return True

        # Common download keywords in URL or query
        download_keywords = ["download", "dl", "getfile", "attachment", "archive"]
        if any(kw in cleaned.lower() for kw in download_keywords):
            return True

        return False

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                clip_text = self._get_clipboard_text()
                if clip_text and clip_text != self._last_clipboard_text:
                    self._last_clipboard_text = clip_text
                    if self._is_downloadable_url(clip_text):
                        logger.info(f"Detected downloadable URL in clipboard: {clip_text}")
                        try:
                            self.on_url_detected(clip_text.strip())
                        except Exception as e:
                            logger.error(f"Error executing on_url_detected: {e}")
            except Exception as e:
                logger.debug(f"Clipboard read error: {e}")

            time.sleep(self.check_interval)
