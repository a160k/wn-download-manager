"""
database.py - SQLite persistence for download history and state in MC Download Manager.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional

from utils import ensure_config_dir

DB_PATH = ensure_config_dir() / "downloads.db"


class DownloadDatabase:
    """Thread-safe SQLite database manager for downloads."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path: Optional[Path] = None):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DownloadDatabase, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, db_path: Optional[Path] = None):
        if getattr(self, "_initialized", False):
            return
        self.db_path = Path(db_path) if db_path else DB_PATH
        self._db_lock = threading.Lock()
        self._init_db()
        self._initialized = True

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        with self._db_lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS downloads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        url TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        filepath TEXT NOT NULL,
                        filesize INTEGER DEFAULT 0,
                        downloaded_bytes INTEGER DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'Bekliyor',
                        date_added TEXT NOT NULL,
                        date_completed TEXT,
                        category TEXT NOT NULL DEFAULT 'Diğer',
                        num_connections INTEGER DEFAULT 8,
                        headers TEXT DEFAULT '{}',
                        error_message TEXT DEFAULT '',
                        download_type TEXT DEFAULT 'direct'
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def add_download(
        self,
        url: str,
        filename: str,
        filepath: str,
        filesize: int = 0,
        category: str = "Diğer",
        num_connections: int = 8,
        headers: Optional[Dict[str, str]] = None,
        download_type: str = "direct",
        status: str = "Bekliyor",
    ) -> int:
        """Insert a new download record and return its ID."""
        date_added = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        headers_json = json.dumps(headers or {}, ensure_ascii=False)

        with self._db_lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO downloads (
                        url, filename, filepath, filesize, downloaded_bytes,
                        status, date_added, category, num_connections,
                        headers, download_type
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        url,
                        filename,
                        str(filepath),
                        filesize,
                        0,
                        status,
                        date_added,
                        category,
                        num_connections,
                        headers_json,
                        download_type,
                    ),
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def get_download(self, download_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single download record by ID."""
        with self._db_lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM downloads WHERE id = ?", (download_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    def get_all_downloads(self, category: Optional[str] = None, search_term: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch all downloads with optional filtering by category and search keyword."""
        with self._db_lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                query = "SELECT * FROM downloads WHERE 1=1"
                params: List[Any] = []

                if category and category != "Tümü":
                    query += " AND category = ?"
                    params.append(category)

                if search_term:
                    query += " AND (filename LIKE ? OR url LIKE ?)"
                    wildcard = f"%{search_term}%"
                    params.extend([wildcard, wildcard])

                query += " ORDER BY id DESC"
                cursor.execute(query, tuple(params))
                rows = cursor.fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def update_download_progress(self, download_id: int, downloaded_bytes: int, filesize: Optional[int] = None) -> None:
        """Update downloaded bytes and optionally total filesize."""
        with self._db_lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                if filesize is not None and filesize > 0:
                    cursor.execute(
                        "UPDATE downloads SET downloaded_bytes = ?, filesize = ? WHERE id = ?",
                        (downloaded_bytes, filesize, download_id),
                    )
                else:
                    cursor.execute(
                        "UPDATE downloads SET downloaded_bytes = ? WHERE id = ?",
                        (downloaded_bytes, download_id),
                    )
                conn.commit()
            finally:
                conn.close()

    def update_download_status(
        self, download_id: int, status: str, error_message: str = "", completed: bool = False
    ) -> None:
        """Update status and completion date."""
        with self._db_lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                if completed:
                    date_completed = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute(
                        """
                        UPDATE downloads 
                        SET status = ?, error_message = ?, date_completed = ?
                        WHERE id = ?
                        """,
                        (status, error_message, date_completed, download_id),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE downloads 
                        SET status = ?, error_message = ?
                        WHERE id = ?
                        """,
                        (status, error_message, download_id),
                    )
                conn.commit()
            finally:
                conn.close()

    def update_download_metadata(
        self, download_id: int, filename: str, filepath: str, filesize: int, category: str
    ) -> None:
        """Update file details once determined from HTTP headers."""
        with self._db_lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE downloads 
                    SET filename = ?, filepath = ?, filesize = ?, category = ?
                    WHERE id = ?
                    """,
                    (filename, str(filepath), filesize, category, download_id),
                )
                conn.commit()
            finally:
                conn.close()

    def delete_download(self, download_id: int) -> bool:
        """Delete a download record by ID."""
        with self._db_lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM downloads WHERE id = ?", (download_id,))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    def recover_interrupted_downloads(self) -> None:
        """On startup, transition any active 'İndiriliyor' states to 'Duraklatıldı'."""
        with self._db_lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE downloads SET status = 'Duraklatıldı' WHERE status = 'İndiriliyor'"
                )
                conn.commit()
            finally:
                conn.close()
