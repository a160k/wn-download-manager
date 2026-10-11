"""
utils.py - Utility functions and configuration management for MC Download Manager.
"""
from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
import re
import urllib.parse
from typing import Any, Dict, Optional, Tuple

APP_NAME = "MCDownloadManager"
CONFIG_DIR = Path.home() / ".mc_download_manager"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "download_dir": str(DEFAULT_DOWNLOAD_DIR),
    "max_simultaneous_downloads": 3,
    "default_connections": 8,
    "speed_limit_kbs": 0,  # 0 means unlimited
    "clipboard_monitoring": True,
    "start_minimized": False,
    "notifications_enabled": True,
    "auto_start_downloads": True,
    "theme": "darkly",
    "monitored_extensions": [
        "zip", "rar", "7z", "tar", "gz", "exe", "msi", "iso",
        "mp4", "mkv", "avi", "mov", "mp3", "flac", "wav",
        "pdf", "docx", "xlsx", "pptx", "png", "jpg", "jpeg", "webp"
    ]
}

CATEGORY_MAP = {
    "Belgeler": [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".odt", ".csv", ".epub", ".rtf"],
    "Resimler": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".tiff", ".ico"],
    "Müzik": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".alac", ".opus"],
    "Video": [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".3gp"],
    "Arşivler": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso", ".dmg"],
    "Programlar": [".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".apk", ".appimage", ".deb", ".rpm"],
}


def ensure_config_dir() -> Path:
    """Ensure configuration directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR


def load_settings() -> Dict[str, Any]:
    """Load settings from JSON config file or create default if not present."""
    ensure_config_dir()
    if not CONFIG_FILE.exists():
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Merge with defaults in case of missing keys
        settings = DEFAULT_SETTINGS.copy()
        settings.update(data)
        return settings
    except Exception:
        return DEFAULT_SETTINGS.copy()


def save_settings(settings: Dict[str, Any]) -> bool:
    """Save settings dictionary to JSON file."""
    ensure_config_dir()
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
        return True
    except Exception:
        return False


def format_bytes(size_bytes: Optional[int | float]) -> str:
    """Format bytes into human readable format (e.g., 12.34 MB)."""
    if size_bytes is None or size_bytes < 0:
        return "Bilinmiyor"
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_idx = 0
    val = float(size_bytes)
    while val >= 1024.0 and unit_idx < len(units) - 1:
        val /= 1024.0
        unit_idx += 1
    if unit_idx == 0:
        return f"{int(val)} B"
    return f"{val:.2f} {units[unit_idx]}"


def format_speed(bytes_per_sec: Optional[int | float]) -> str:
    """Format download speed (e.g., 2.50 MB/s)."""
    if bytes_per_sec is None or bytes_per_sec <= 0:
        return "0 KB/s"
    return f"{format_bytes(bytes_per_sec)}/s"


def format_eta(seconds: Optional[int | float]) -> str:
    """Format estimated time remaining into HH:MM:SS or MM:SS."""
    if seconds is None or seconds < 0:
        return "--:--"
    if seconds == float("inf"):
        return "∞"
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def get_category_by_extension(filename: str) -> str:
    """Determine UI category name based on file extension."""
    ext = Path(filename).suffix.lower()
    for category, extensions in CATEGORY_MAP.items():
        if ext in extensions:
            return category
    return "Diğer"


def get_mime_type(filepath_or_name: str) -> str:
    """Guess MIME type from filename."""
    mime, _ = mimetypes.guess_type(filepath_or_name)
    return mime or "application/octet-stream"


def clean_filename(filename: str) -> str:
    """Remove illegal characters for Windows filenames."""
    filename = urllib.parse.unquote(filename)
    # Strip invalid characters: \ / : * ? " < > |
    filename = re.sub(r'[\\/*?:"<>|]', "_", filename)
    filename = filename.strip(" .")
    if not filename:
        filename = "download"
    return filename


def extract_filename_from_url(url: str, content_disposition: Optional[str] = None) -> str:
    """
    Extract or infer a filename from a URL or Content-Disposition header.
    """
    if content_disposition:
        # Match filename*=utf-8''... or filename="..."
        match_utf8 = re.search(r"filename\*\s*=\s*utf-8''([^;]+)", content_disposition, re.IGNORECASE)
        if match_utf8:
            return clean_filename(urllib.parse.unquote(match_utf8.group(1)))
        match_regular = re.search(r'filename\s*=\s*"?([^";]+)"?', content_disposition, re.IGNORECASE)
        if match_regular:
            return clean_filename(match_regular.group(1).strip())

    parsed = urllib.parse.urlparse(url)
    path = parsed.path.strip("/")
    if path:
        candidate = Path(path).name
        if candidate:
            return clean_filename(candidate)
    
    # In case path is empty, use hostname or default
    host = parsed.netloc.replace(":", "_")
    return clean_filename(f"download_{host}" if host else "download_file")


def get_unique_filepath(directory: Path | str, filename: str) -> Path:
    """
    Return unique file path if file already exists by appending (1), (2), etc.
    """
    dest_dir = Path(directory)
    dest_dir.mkdir(parents=True, exist_ok=True)
    clean_name = clean_filename(filename)
    p = dest_dir / clean_name
    if not p.exists():
        return p

    stem = p.stem
    suffix = p.suffix
    counter = 1
    while True:
        candidate = dest_dir / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def is_valid_url(url: str) -> bool:
    """Check if the string is a valid HTTP/HTTPS URL."""
    if not url or not isinstance(url, str):
        return False
    parsed = urllib.parse.urlparse(url.strip())
    return parsed.scheme.lower() in ("http", "https") and bool(parsed.netloc)
