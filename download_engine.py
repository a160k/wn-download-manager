"""
download_engine.py - Core multi-threaded download engine with Range support for MC Download Manager.
"""
from __future__ import annotations

import collections
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, List, Optional
import urllib.parse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from utils import (
    clean_filename,
    extract_filename_from_url,
    get_category_by_extension,
    get_unique_filepath,
)

logger = logging.getLogger("MCDownloadManager.Engine")

CHUNK_SIZE = 64 * 1024  # 64 KB read buffer
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class SegmentInfo:
    """Tracks state and progress of an individual segment."""

    def __init__(self, index: int, start_byte: int, end_byte: int):
        self.index = index
        self.start_byte = start_byte
        self.end_byte = end_byte
        self.total_bytes = (end_byte - start_byte + 1) if end_byte >= start_byte else 0
        self.downloaded_bytes = 0
        self.status = "Hazırlanıyor"  # Hazırlanıyor, İndiriliyor, Tamamlandı, Hata, Duraklatıldı

    @property
    def current_byte(self) -> int:
        return self.start_byte + self.downloaded_bytes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "total_bytes": self.total_bytes,
            "downloaded_bytes": self.downloaded_bytes,
            "progress_percent": (
                (self.downloaded_bytes / self.total_bytes * 100) if self.total_bytes > 0 else 0
            ),
            "status": self.status,
        }


class DownloadTask:
    """Controls and executes a single download operation."""

    def __init__(
        self,
        download_id: int,
        url: str,
        dest_path: str | Path,
        num_connections: int = 8,
        headers: Optional[Dict[str, str]] = None,
        speed_limit_kbs: int = 0,
        progress_callback: Optional[Callable[[int, int, int, float, float, str], None]] = None,
        segment_callback: Optional[Callable[[int, List[Dict[str, Any]]], None]] = None,
        status_callback: Optional[Callable[[int, str, str], None]] = None,
        metadata_callback: Optional[Callable[[int, str, str, int, str], None]] = None,
    ):
        self.download_id = download_id
        self.url = url
        self.dest_path = Path(dest_path)
        self.num_connections = max(1, min(32, num_connections))
        self.headers = headers or {}
        self.speed_limit_kbs = speed_limit_kbs
        
        self.progress_callback = progress_callback
        self.segment_callback = segment_callback
        self.status_callback = status_callback
        self.metadata_callback = metadata_callback

        self.status = "Bekliyor"  # Bekliyor, İndiriliyor, Duraklatıldı, Tamamlandı, Hata, İptal Edildi
        self.error_message = ""
        self.filesize: int = 0
        self.supports_ranges = False
        self.segments: List[SegmentInfo] = []
        
        self._pause_event = threading.Event()
        self._cancel_event = threading.Event()
        self._threads: List[threading.Thread] = []
        self._lock = threading.Lock()

        # Speed estimation
        self._speed_samples = collections.deque(maxlen=10)
        self._last_calc_time = time.time()
        self._last_calc_bytes = 0
        self.current_speed = 0.0  # bytes/sec
        self.eta = 0.0  # seconds

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retries = Retry(
            total=5,
            backoff_factor=1.0,
            status_forcelist=[500, 502, 503, 504, 429],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=32, pool_maxsize=32)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _get_request_headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        req_headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept-Encoding": "identity"}
        req_headers.update(self.headers)
        if extra:
            req_headers.update(extra)
        return req_headers

    def get_part_file(self, segment_idx: int) -> Path:
        return self.dest_path.parent / f"{self.dest_path.name}.part.{segment_idx}"

    def inspect_remote_file(self) -> bool:
        """Fetch headers to determine Content-Length, filename, and Accept-Ranges."""
        session = self._create_session()
        try:
            req_headers = self._get_request_headers({"Range": "bytes=0-0"})
            resp = session.get(self.url, headers=req_headers, stream=True, timeout=15, allow_redirects=True)
            
            # Check range support
            if resp.status_code == 206:
                self.supports_ranges = True
                content_range = resp.headers.get("Content-Range", "")
                if "/" in content_range:
                    try:
                        self.filesize = int(content_range.split("/")[-1])
                    except ValueError:
                        self.filesize = 0
            else:
                self.supports_ranges = resp.headers.get("Accept-Ranges", "").lower() == "bytes"
                self.filesize = int(resp.headers.get("Content-Length", 0))

            # Detect Content-Disposition filename
            cd = resp.headers.get("Content-Disposition")
            inferred_filename = extract_filename_from_url(resp.url or self.url, cd)
            
            # If current dest_path is generic or doesn't match inferred, update it
            if inferred_filename and (self.dest_path.name == "download" or not self.dest_path.suffix):
                new_dest = get_unique_filepath(self.dest_path.parent, inferred_filename)
                self.dest_path = new_dest
                if self.metadata_callback:
                    category = get_category_by_extension(new_dest.name)
                    self.metadata_callback(self.download_id, new_dest.name, str(new_dest), self.filesize, category)

            resp.close()
            return True
        except Exception as e:
            logger.error(f"Error inspecting remote file: {e}")
            self.error_message = str(e)
            return False
        finally:
            session.close()

    def start(self) -> None:
        """Start or resume the download in a worker thread."""
        self._pause_event.clear()
        self._cancel_event.clear()
        self.status = "İndiriliyor"
        self._notify_status("İndiriliyor")

        worker = threading.Thread(target=self._run, name=f"Download-{self.download_id}", daemon=True)
        worker.start()

    def pause(self) -> None:
        """Pause the download gracefully."""
        self._pause_event.set()
        self.status = "Duraklatıldı"
        self._notify_status("Duraklatıldı")

    def cancel(self) -> None:
        """Cancel the download and clean up temporary segment files."""
        self._cancel_event.set()
        self._pause_event.set()
        self.status = "İptal Edildi"
        self._notify_status("İptal Edildi")
        self._cleanup_parts()

    def _cleanup_parts(self) -> None:
        """Remove temporary part files."""
        for i in range(max(1, len(self.segments) or self.num_connections)):
            pf = self.get_part_file(i)
            if pf.exists():
                try:
                    pf.unlink()
                except OSError:
                    pass

    def _notify_status(self, status: str, error: str = "") -> None:
        if self.status_callback:
            try:
                self.status_callback(self.download_id, status, error or self.error_message)
            except Exception as e:
                logger.debug(f"Status callback error: {e}")

    def _notify_progress(self) -> None:
        total_downloaded = sum(s.downloaded_bytes for s in self.segments)
        
        # Calculate speed and ETA
        now = time.time()
        dt = now - self._last_calc_time
        if dt >= 0.5:
            db = total_downloaded - self._last_calc_bytes
            speed = max(0.0, db / dt)
            self._speed_samples.append(speed)
            self.current_speed = sum(self._speed_samples) / len(self._speed_samples)
            
            if self.filesize > 0 and self.current_speed > 0:
                remaining_bytes = max(0, self.filesize - total_downloaded)
                self.eta = remaining_bytes / self.current_speed
            else:
                self.eta = 0.0

            self._last_calc_time = now
            self._last_calc_bytes = total_downloaded

        if self.progress_callback:
            try:
                self.progress_callback(
                    self.download_id,
                    total_downloaded,
                    self.filesize,
                    self.current_speed,
                    self.eta,
                    self.status,
                )
            except Exception as e:
                logger.debug(f"Progress callback error: {e}")

        if self.segment_callback:
            try:
                segment_data = [s.to_dict() for s in self.segments]
                self.segment_callback(self.download_id, segment_data)
            except Exception as e:
                logger.debug(f"Segment callback error: {e}")

    def _run(self) -> None:
        try:
            # 1. Inspect remote file if not already known
            if self.filesize <= 0:
                if not self.inspect_remote_file():
                    self.status = "Hata"
                    self._notify_status("Hata", self.error_message or "Sunucuya bağlanılamadı")
                    return

            # Ensure parent folder exists
            self.dest_path.parent.mkdir(parents=True, exist_ok=True)

            # 2. Divide into segments
            if not self.supports_ranges or self.filesize <= 0 or self.num_connections <= 1:
                # Fallback to single connection
                num_parts = 1
                self.segments = [SegmentInfo(0, 0, max(0, self.filesize - 1))]
            else:
                num_parts = self.num_connections
                part_size = self.filesize // num_parts
                self.segments = []
                for i in range(num_parts):
                    start = i * part_size
                    end = (start + part_size - 1) if (i < num_parts - 1) else (self.filesize - 1)
                    self.segments.append(SegmentInfo(i, start, end))

            # 3. Check existing part files for resuming
            for s in self.segments:
                pf = self.get_part_file(s.index)
                if pf.exists():
                    existing_bytes = pf.stat().st_size
                    if s.total_bytes > 0 and existing_bytes <= s.total_bytes:
                        s.downloaded_bytes = existing_bytes
                    elif s.total_bytes == 0:
                        s.downloaded_bytes = existing_bytes
                    else:
                        # Corrupted or oversized part file, restart segment
                        pf.unlink(missing_ok=True)
                        s.downloaded_bytes = 0

            # 4. Spawn threads for segments
            self._threads = []
            for s in self.segments:
                t = threading.Thread(
                    target=self._download_segment,
                    args=(s,),
                    name=f"Segment-{self.download_id}-{s.index}",
                    daemon=True,
                )
                self._threads.append(t)
                t.start()

            # Wait for all segments to finish
            for t in self._threads:
                t.join()

            if self._cancel_event.is_set():
                self.status = "İptal Edildi"
                self._notify_status("İptal Edildi")
                self._cleanup_parts()
                return

            if self._pause_event.is_set():
                self.status = "Duraklatıldı"
                self._notify_status("Duraklatıldı")
                return

            # Check if all segments are completed
            all_done = True
            for s in self.segments:
                if s.status != "Tamamlandı":
                    all_done = False
                    break

            if not all_done:
                if not self.error_message:
                    self.error_message = "Parçaların tümü indirilemedi."
                self.status = "Hata"
                self._notify_status("Hata", self.error_message)
                return

            # 5. Merge segments into target file
            self.status = "Birleştiriliyor"
            self._notify_status("Birleştiriliyor")
            self._merge_segments()

            # Verify integrity if filesize is known
            if self.filesize > 0 and self.dest_path.exists():
                actual_size = self.dest_path.stat().st_size
                if actual_size != self.filesize:
                    self.status = "Hata"
                    self.error_message = (
                        f"Dosya boyutu uyuşmazlığı: Beklenen {self.filesize}, İndirilen {actual_size}"
                    )
                    self._notify_status("Hata", self.error_message)
                    return

            self._cleanup_parts()
            self.status = "Tamamlandı"
            self._notify_progress()
            self._notify_status("Tamamlandı")

        except Exception as e:
            logger.exception(f"Unexpected error in download task {self.download_id}: {e}")
            self.status = "Hata"
            self.error_message = str(e)
            self._notify_status("Hata", str(e))

    def _download_segment(self, segment: SegmentInfo) -> None:
        """Download a specific segment chunk."""
        if segment.total_bytes > 0 and segment.downloaded_bytes >= segment.total_bytes:
            segment.status = "Tamamlandı"
            return

        segment.status = "İndiriliyor"
        part_file = self.get_part_file(segment.index)
        session = self._create_session()

        max_retries = 3
        retry_count = 0

        while retry_count < max_retries and not self._pause_event.is_set() and not self._cancel_event.is_set():
            try:
                headers = self._get_request_headers()
                
                # If ranges are supported, add Range header
                if self.supports_ranges and segment.end_byte >= segment.current_byte:
                    headers["Range"] = f"bytes={segment.current_byte}-{segment.end_byte}"
                    expected_status = 206
                else:
                    expected_status = 200

                mode = "ab" if segment.downloaded_bytes > 0 else "wb"
                
                with session.get(self.url, headers=headers, stream=True, timeout=20) as resp:
                    if resp.status_code not in (expected_status, 200):
                        raise requests.RequestException(f"HTTP Durum Kodu: {resp.status_code}")

                    with open(part_file, mode) as f:
                        for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                            if self._pause_event.is_set() or self._cancel_event.is_set():
                                break
                            if chunk:
                                f.write(chunk)
                                chunk_len = len(chunk)
                                with self._lock:
                                    segment.downloaded_bytes += chunk_len
                                self._notify_progress()

                                # Speed throttling per segment if global limit is set
                                if self.speed_limit_kbs > 0:
                                    seg_limit_bytes = (self.speed_limit_kbs * 1024) / max(1, len(self.segments))
                                    expected_time = chunk_len / seg_limit_bytes
                                    time.sleep(max(0.001, expected_time * 0.5))

                if self._pause_event.is_set() or self._cancel_event.is_set():
                    segment.status = "Duraklatıldı"
                    break

                # Segment finished
                segment.status = "Tamamlandı"
                break

            except Exception as e:
                retry_count += 1
                logger.warning(
                    f"Segment {segment.index} attempt {retry_count}/{max_retries} failed: {e}"
                )
                if retry_count >= max_retries:
                    segment.status = "Hata"
                    self.error_message = f"Parça {segment.index} indirme hatası: {e}"
                else:
                    time.sleep(2 ** retry_count)
            finally:
                pass

        session.close()

    def _merge_segments(self) -> None:
        """Combine all segment parts into the destination file."""
        temp_dest = self.dest_path.parent / f"{self.dest_path.name}.temp_final"
        with open(temp_dest, "wb") as outfile:
            for s in self.segments:
                pf = self.get_part_file(s.index)
                if pf.exists():
                    with open(pf, "rb") as infile:
                        while True:
                            buf = infile.read(CHUNK_SIZE * 4)
                            if not buf:
                                break
                            outfile.write(buf)

        # Atomic replace / move on Windows
        if self.dest_path.exists():
            self.dest_path.unlink()
        temp_dest.replace(self.dest_path)


class DownloadEngine:
    """Manages concurrent downloads, task queue, and lifecycle."""

    def __init__(self, max_concurrent: int = 3, default_connections: int = 8, speed_limit_kbs: int = 0):
        self.max_concurrent = max_concurrent
        self.default_connections = default_connections
        self.speed_limit_kbs = speed_limit_kbs
        self.tasks: Dict[int, DownloadTask] = {}
        self._lock = threading.Lock()
        self._active_downloads: Dict[int, DownloadTask] = {}
        self._dispatcher_thread: Optional[threading.Thread] = None
        self._stop_dispatcher = threading.Event()

    def start_engine(self) -> None:
        self._stop_dispatcher.clear()
        if self._dispatcher_thread is None or not self._dispatcher_thread.is_alive():
            self._dispatcher_thread = threading.Thread(
                target=self._dispatcher_loop, name="DownloadDispatcher", daemon=True
            )
            self._dispatcher_thread.start()

    def stop_engine(self) -> None:
        self._stop_dispatcher.set()
        with self._lock:
            for task in list(self.tasks.values()):
                if task.status == "İndiriliyor":
                    task.pause()

    def _dispatcher_loop(self) -> None:
        """Periodically check for queued downloads and start them up to max_concurrent."""
        while not self._stop_dispatcher.is_set():
            with self._lock:
                active_count = sum(1 for t in self.tasks.values() if t.status == "İndiriliyor")
                if active_count < self.max_concurrent:
                    for task in self.tasks.values():
                        if task.status == "Bekliyor":
                            task.speed_limit_kbs = self.speed_limit_kbs
                            task.start()
                            active_count += 1
                            if active_count >= self.max_concurrent:
                                break
            time.sleep(0.5)

    def add_task(
        self,
        download_id: int,
        url: str,
        dest_path: str | Path,
        num_connections: Optional[int] = None,
        headers: Optional[Dict[str, str]] = None,
        auto_start: bool = True,
        progress_callback: Optional[Callable] = None,
        segment_callback: Optional[Callable] = None,
        status_callback: Optional[Callable] = None,
        metadata_callback: Optional[Callable] = None,
    ) -> DownloadTask:
        """Register a new download task."""
        conns = num_connections if num_connections is not None else self.default_connections
        task = DownloadTask(
            download_id=download_id,
            url=url,
            dest_path=dest_path,
            num_connections=conns,
            headers=headers,
            speed_limit_kbs=self.speed_limit_kbs,
            progress_callback=progress_callback,
            segment_callback=segment_callback,
            status_callback=status_callback,
            metadata_callback=metadata_callback,
        )
        with self._lock:
            self.tasks[download_id] = task

        if auto_start:
            task.status = "Bekliyor"
        else:
            task.status = "Duraklatıldı"

        return task

    def resume_task(self, download_id: int) -> bool:
        with self._lock:
            task = self.tasks.get(download_id)
            if task and task.status in ("Duraklatıldı", "Hata", "Bekliyor"):
                task.status = "Bekliyor"
                return True
        return False

    def pause_task(self, download_id: int) -> bool:
        with self._lock:
            task = self.tasks.get(download_id)
            if task and task.status in ("İndiriliyor", "Bekliyor"):
                task.pause()
                return True
        return False

    def cancel_task(self, download_id: int) -> bool:
        with self._lock:
            task = self.tasks.get(download_id)
            if task:
                task.cancel()
                return True
        return False

    def remove_task(self, download_id: int) -> None:
        with self._lock:
            task = self.tasks.pop(download_id, None)
            if task:
                task.cancel()

    def get_task(self, download_id: int) -> Optional[DownloadTask]:
        with self._lock:
            return self.tasks.get(download_id)

    def get_total_speed(self) -> float:
        with self._lock:
            return sum(t.current_speed for t in self.tasks.values() if t.status == "İndiriliyor")

    def get_active_count(self) -> int:
        with self._lock:
            return sum(1 for t in self.tasks.values() if t.status == "İndiriliyor")
