"""
gui.py - Modern Graphical User Interface for MC Download Manager using ttkbootstrap.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Any, Dict, List, Optional

try:
    import ttkbootstrap as tb
    from ttkbootstrap.constants import *
except ImportError:
    import tkinter.ttk as tb
    from tkinter.constants import *

try:
    from plyer import notification
except ImportError:
    notification = None

from assets.icon import create_default_icon_image, get_app_icon_image
from database import DownloadDatabase
from download_engine import DownloadEngine
from utils import (
    clean_filename,
    extract_filename_from_url,
    format_bytes,
    format_eta,
    format_speed,
    get_category_by_extension,
    is_valid_url,
    load_settings,
    save_settings,
)
from video_downloader import VideoDownloadTask, fetch_video_info, is_video_site

logger = logging.getLogger("MCDownloadManager.GUI")


def show_desktop_notification(title: str, message: str) -> None:
    """Show a desktop notification using plyer if enabled."""
    if notification:
        try:
            notification.notify(
                title=title,
                message=message,
                app_name="WN Download Manager",
                timeout=5,
            )
        except Exception as e:
            logger.debug(f"Notification error: {e}")


class AddDownloadDialog(tb.Toplevel):
    """Dialog for creating a new direct or video download."""

    def __init__(self, parent: "MainWindow", initial_url: str = ""):
        super().__init__(parent)
        self.parent = parent
        self.title("Yeni İndirme Ekle")
        self.geometry("640x680")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.settings = parent.settings
        self.dest_folder = self.settings.get("download_dir", str(Path.home() / "Downloads"))

        self.url_var = tk.StringVar(value=initial_url)
        self.filename_var = tk.StringVar()
        self.folder_var = tk.StringVar(value=self.dest_folder)
        self.connections_var = tk.IntVar(value=self.settings.get("default_connections", 8))
        self.auto_start_var = tk.BooleanVar(value=True)
        self.is_video_var = tk.BooleanVar(value=False)
        self.video_quality_var = tk.StringVar(value="En İyi")
        self.user_agent_var = tk.StringVar()
        self.referer_var = tk.StringVar()
        self.cookie_var = tk.StringVar()

        self._build_ui()
        if initial_url:
            self._on_url_change()

    def _build_ui(self) -> None:
        container = tb.Frame(self, padding=20)
        container.pack(fill=BOTH, expand=True)

        # URL Frame
        url_frame = tb.Labelframe(container, text=" İndirme Bağlantısı ", padding=10)
        url_frame.pack(fill=X, pady=(0, 10))

        tb.Label(url_frame, text="URL:").grid(row=0, column=0, sticky=W, padx=(0, 5), pady=5)
        url_entry = tb.Entry(url_frame, textvariable=self.url_var, width=55)
        url_entry.grid(row=0, column=1, sticky=EW, padx=5, pady=5)
        url_entry.bind("<KeyRelease>", lambda e: self._on_url_change())

        tb.Button(
            url_frame,
            text="Yapıştır & İncele",
            bootstyle="secondary-outline",
            command=self._paste_and_inspect,
        ).grid(row=0, column=2, padx=5, pady=5)

        # File options
        opts_frame = tb.Labelframe(container, text=" Dosya & Kayıt Seçenekleri ", padding=10)
        opts_frame.pack(fill=X, pady=(0, 10))

        tb.Label(opts_frame, text="Dosya Adı:").grid(row=0, column=0, sticky=W, padx=(0, 5), pady=5)
        tb.Entry(opts_frame, textvariable=self.filename_var, width=45).grid(
            row=0, column=1, columnspan=2, sticky=EW, padx=5, pady=5
        )

        tb.Label(opts_frame, text="Kayıt Klasörü:").grid(row=1, column=0, sticky=W, padx=(0, 5), pady=5)
        tb.Entry(opts_frame, textvariable=self.folder_var, width=40).grid(
            row=1, column=1, sticky=EW, padx=5, pady=5
        )
        tb.Button(
            opts_frame,
            text="Gözat...",
            bootstyle="secondary",
            command=self._browse_folder,
        ).grid(row=1, column=2, padx=5, pady=5)

        tb.Label(opts_frame, text="Bağlantı Sayısı:").grid(row=2, column=0, sticky=W, padx=(0, 5), pady=5)
        conn_spin = tb.Spinbox(
            opts_frame, from_=1, to=32, textvariable=self.connections_var, width=5
        )
        conn_spin.grid(row=2, column=1, sticky=W, padx=5, pady=5)

        # Video Section
        self.video_frame = tb.Labelframe(container, text=" Video / Ses Ayarları ", padding=10)
        self.video_frame.pack(fill=X, pady=(0, 10))

        tb.Checkbutton(
            self.video_frame,
            text="Video İndirici (yt-dlp) Kullan",
            variable=self.is_video_var,
            bootstyle="round-toggle",
        ).grid(row=0, column=0, sticky=W, padx=5, pady=5)

        tb.Label(self.video_frame, text="Kalite:").grid(row=0, column=1, sticky=W, padx=10, pady=5)
        qualities = ["En İyi", "4K (2160p)", "1080p", "720p", "480p", "Yalnızca Ses (MP3)"]
        tb.Combobox(
            self.video_frame,
            values=qualities,
            textvariable=self.video_quality_var,
            state="readonly",
            width=18,
        ).grid(row=0, column=2, sticky=W, padx=5, pady=5)

        # Advanced / Headers Accordion
        adv_frame = tb.Labelframe(container, text=" Özel Başlıklar (Opsiyonel) ", padding=10)
        adv_frame.pack(fill=X, pady=(0, 10))

        tb.Label(adv_frame, text="User-Agent:").grid(row=0, column=0, sticky=W, padx=5, pady=2)
        tb.Entry(adv_frame, textvariable=self.user_agent_var, width=48).grid(
            row=0, column=1, sticky=EW, padx=5, pady=2
        )

        tb.Label(adv_frame, text="Referer:").grid(row=1, column=0, sticky=W, padx=5, pady=2)
        tb.Entry(adv_frame, textvariable=self.referer_var, width=48).grid(
            row=1, column=1, sticky=EW, padx=5, pady=2
        )

        # Bottom buttons
        bottom_frame = tb.Frame(container)
        bottom_frame.pack(fill=X, pady=(10, 0))

        tb.Checkbutton(
            bottom_frame,
            text="Hemen Başlat",
            variable=self.auto_start_var,
            bootstyle="success-square-toggle",
        ).pack(side=LEFT)

        tb.Button(
            bottom_frame,
            text="İptal",
            bootstyle="secondary",
            command=self.destroy,
        ).pack(side=RIGHT, padx=(5, 0))

        tb.Button(
            bottom_frame,
            text="İndir",
            bootstyle="primary",
            command=self._on_submit,
        ).pack(side=RIGHT, padx=5)

    def _paste_and_inspect(self) -> None:
        try:
            clip = self.clipboard_get()
            if clip:
                self.url_var.set(clip.strip())
                self._on_url_change()
        except Exception:
            pass

    def _on_url_change(self) -> None:
        url = self.url_var.get().strip()
        if not url:
            return

        if is_video_site(url):
            self.is_video_var.set(True)
            # Async fetch video title
            threading.Thread(target=self._fetch_video_title, args=(url,), daemon=True).start()
        else:
            fname = extract_filename_from_url(url)
            self.filename_var.set(fname)

    def _fetch_video_title(self, url: str) -> None:
        info = fetch_video_info(url)
        if info and "title" in info:
            clean = clean_filename(info["title"])
            self.after(0, lambda: self.filename_var.set(f"{clean}.mp4"))

    def _browse_folder(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.folder_var.get())
        if chosen:
            self.folder_var.set(chosen)

    def _on_submit(self) -> None:
        url = self.url_var.get().strip()
        if not is_valid_url(url):
            messagebox.showerror("Geçersiz URL", "Lütfen geçerli bir http veya https bağlantısı girin.")
            return

        dest_folder = Path(self.folder_var.get())
        if not dest_folder.exists():
            try:
                dest_folder.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Klasör Hatası", f"Klasör oluşturulamadı: {e}")
                return

        fname = self.filename_var.get().strip() or extract_filename_from_url(url)
        dest_path = dest_folder / fname

        headers: Dict[str, str] = {}
        if self.user_agent_var.get().strip():
            headers["User-Agent"] = self.user_agent_var.get().strip()
        if self.referer_var.get().strip():
            headers["Referer"] = self.referer_var.get().strip()

        is_video = self.is_video_var.get()
        quality = self.video_quality_var.get()
        connections = self.connections_var.get()
        auto_start = self.auto_start_var.get()

        self.parent.add_download_from_dialog(
            url=url,
            filename=fname,
            dest_path=str(dest_path),
            is_video=is_video,
            video_quality=quality,
            connections=connections,
            headers=headers,
            auto_start=auto_start,
        )
        self.destroy()


class SettingsDialog(tb.Toplevel):
    """Configuration dialog for WN Download Manager."""

    def __init__(self, parent: "MainWindow"):
        super().__init__(parent)
        self.parent = parent
        self.title("Ayarlar - WN Download Manager")
        self.geometry("540x480")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.settings = parent.settings.copy()

        self.folder_var = tk.StringVar(value=self.settings.get("download_dir", ""))
        self.max_concurrent_var = tk.IntVar(value=self.settings.get("max_simultaneous_downloads", 3))
        self.conns_var = tk.IntVar(value=self.settings.get("default_connections", 8))
        self.speed_limit_var = tk.IntVar(value=self.settings.get("speed_limit_kbs", 0))
        self.clipboard_var = tk.BooleanVar(value=self.settings.get("clipboard_monitoring", True))
        self.start_minimized_var = tk.BooleanVar(value=self.settings.get("start_minimized", False))
        self.notifications_var = tk.BooleanVar(value=self.settings.get("notifications_enabled", True))

        self._build_ui()

    def _build_ui(self) -> None:
        container = tb.Frame(self, padding=20)
        container.pack(fill=BOTH, expand=True)

        # General Group
        gen_group = tb.Labelframe(container, text=" Genel Ayarlar ", padding=15)
        gen_group.pack(fill=X, pady=(0, 15))

        tb.Label(gen_group, text="Varsayılan Klasör:").grid(row=0, column=0, sticky=W, pady=5)
        tb.Entry(gen_group, textvariable=self.folder_var, width=32).grid(
            row=0, column=1, sticky=EW, padx=5, pady=5
        )
        tb.Button(
            gen_group, text="Gözat...", bootstyle="secondary", command=self._browse
        ).grid(row=0, column=2, padx=5, pady=5)

        tb.Label(gen_group, text="Eşzamanlı İndirme Limiti:").grid(row=1, column=0, sticky=W, pady=5)
        tb.Spinbox(gen_group, from_=1, to=10, textvariable=self.max_concurrent_var, width=6).grid(
            row=1, column=1, sticky=W, padx=5, pady=5
        )

        tb.Label(gen_group, text="Varsayılan Bağlantı Sayısı:").grid(row=2, column=0, sticky=W, pady=5)
        tb.Spinbox(gen_group, from_=1, to=32, textvariable=self.conns_var, width=6).grid(
            row=2, column=1, sticky=W, padx=5, pady=5
        )

        tb.Label(gen_group, text="Hız Sınırı (KB/s, 0=Sınırsız):").grid(row=3, column=0, sticky=W, pady=5)
        tb.Spinbox(gen_group, from_=0, to=1000000, increment=100, textvariable=self.speed_limit_var, width=10).grid(
            row=3, column=1, sticky=W, padx=5, pady=5
        )

        # Automation & System Group
        auto_group = tb.Labelframe(container, text=" Entegrasyon & Bildirimler ", padding=15)
        auto_group.pack(fill=X, pady=(0, 15))

        tb.Checkbutton(
            auto_group,
            text="Panoyu (Clipboard) otomatik izle ve bağlantıları yakala",
            variable=self.clipboard_var,
            bootstyle="round-toggle",
        ).pack(anchor=W, pady=4)

        tb.Checkbutton(
            auto_group,
            text="Masaüstü bildirimlerini göster",
            variable=self.notifications_var,
            bootstyle="round-toggle",
        ).pack(anchor=W, pady=4)

        tb.Checkbutton(
            auto_group,
            text="Uygulama açılışında simge durumuna küçült",
            variable=self.start_minimized_var,
            bootstyle="round-toggle",
        ).pack(anchor=W, pady=4)

        # Buttons
        btn_frame = tb.Frame(container)
        btn_frame.pack(fill=X, pady=(10, 0))

        tb.Button(btn_frame, text="İptal", bootstyle="secondary", command=self.destroy).pack(side=RIGHT, padx=5)
        tb.Button(btn_frame, text="Kaydet", bootstyle="success", command=self._save).pack(side=RIGHT)

    def _browse(self) -> None:
        p = filedialog.askdirectory(initialdir=self.folder_var.get())
        if p:
            self.folder_var.set(p)

    def _save(self) -> None:
        self.settings["download_dir"] = self.folder_var.get()
        self.settings["max_simultaneous_downloads"] = self.max_concurrent_var.get()
        self.settings["default_connections"] = self.conns_var.get()
        self.settings["speed_limit_kbs"] = self.speed_limit_var.get()
        self.settings["clipboard_monitoring"] = self.clipboard_var.get()
        self.settings["start_minimized"] = self.start_minimized_var.get()
        self.settings["notifications_enabled"] = self.notifications_var.get()

        save_settings(self.settings)
        self.parent.apply_settings(self.settings)
        self.destroy()


class DownloadDetailDialog(tb.Toplevel):
    """Dialog showing detailed segment progress and logs for a download."""

    def __init__(self, parent: "MainWindow", download_record: Dict[str, Any]):
        super().__init__(parent)
        self.parent = parent
        self.download_id = download_record["id"]
        self.record = download_record

        self.title(f"İndirme Detayları - {self.record.get('filename', 'Dosya')}")
        self.geometry("700x520")
        self.transient(parent)

        self._build_ui()
        self._update_loop()

    def _build_ui(self) -> None:
        container = tb.Frame(self, padding=15)
        container.pack(fill=BOTH, expand=True)

        # File Overview Info
        info_frame = tb.Labelframe(container, text=" Bilgiler ", padding=10)
        info_frame.pack(fill=X, pady=(0, 10))

        tb.Label(info_frame, text=f"Dosya: {self.record.get('filename')}", font="-weight bold").pack(anchor=W)
        tb.Label(info_frame, text=f"URL: {self.record.get('url')}").pack(anchor=W)
        tb.Label(info_frame, text=f"Konum: {self.record.get('filepath')}").pack(anchor=W)
        
        size_str = format_bytes(self.record.get("filesize", 0))
        tb.Label(info_frame, text=f"Toplam Boyut: {size_str}").pack(anchor=W)

        # Segment Progress Visualizer
        seg_frame = tb.Labelframe(container, text=" Parça (Segment) Durumu ", padding=10)
        seg_frame.pack(fill=BOTH, expand=True, pady=(0, 10))

        # Canvas for segment blocks
        self.segment_canvas = tk.Canvas(seg_frame, height=90, bg="#2b2b2b", highlightthickness=0)
        self.segment_canvas.pack(fill=X, pady=5)

        # Treeview for segment list
        columns = ("segment", "range", "downloaded", "percent", "status")
        self.seg_tree = tb.Treeview(seg_frame, columns=columns, show="headings", height=6)
        self.seg_tree.heading("segment", text="Parça")
        self.seg_tree.heading("range", text="Aralık")
        self.seg_tree.heading("downloaded", text="İndirilen")
        self.seg_tree.heading("percent", text="Yüzde")
        self.seg_tree.heading("status", text="Durum")

        self.seg_tree.column("segment", width=60, anchor=CENTER)
        self.seg_tree.column("range", width=180, anchor=CENTER)
        self.seg_tree.column("downloaded", width=120, anchor=E)
        self.seg_tree.column("percent", width=80, anchor=CENTER)
        self.seg_tree.column("status", width=100, anchor=CENTER)

        self.seg_tree.pack(fill=BOTH, expand=True)

        # Close button
        tb.Button(container, text="Kapat", bootstyle="secondary", command=self.destroy).pack(side=RIGHT)

    def _update_loop(self) -> None:
        if not self.winfo_exists():
            return

        task = self.parent.engine.get_task(self.download_id)
        if task and task.segments:
            # Update canvas visualizer
            self.segment_canvas.delete("all")
            width = self.segment_canvas.winfo_width()
            if width > 1:
                num_segs = len(task.segments)
                block_w = (width - (num_segs * 4)) / max(1, num_segs)
                for idx, s in enumerate(task.segments):
                    pct = (s.downloaded_bytes / s.total_bytes) if s.total_bytes > 0 else 0
                    x1 = idx * (block_w + 4) + 2
                    x2 = x1 + block_w
                    y1 = 10
                    y2 = 70
                    # Outline
                    self.segment_canvas.create_rectangle(x1, y1, x2, y2, fill="#3a3a3a", outline="#555")
                    # Fill according to progress
                    fill_y1 = y2 - ((y2 - y1) * pct)
                    self.segment_canvas.create_rectangle(x1, fill_y1, x2, y2, fill="#00bc8c", outline="")
                    self.segment_canvas.create_text(
                        (x1 + x2) / 2, y1 + 15, text=f"#{idx+1}", fill="white", font="-size 8 -weight bold"
                    )
                    self.segment_canvas.create_text(
                        (x1 + x2) / 2, y2 - 15, text=f"{int(pct*100)}%", fill="white", font="-size 8"
                    )

            # Update Treeview rows
            for item in self.seg_tree.get_children():
                self.seg_tree.delete(item)

            for s in task.segments:
                pct_str = f"{(s.downloaded_bytes / s.total_bytes * 100):.1f}%" if s.total_bytes > 0 else "0%"
                self.seg_tree.insert(
                    "",
                    END,
                    values=(
                        f"#{s.index + 1}",
                        f"{s.start_byte} - {s.end_byte}",
                        format_bytes(s.downloaded_bytes),
                        pct_str,
                        s.status,
                    ),
                )

        self.after(1000, self._update_loop)


class MainWindow(tb.Window):


    def _delete_selected_with_file(self):
        selected_items = self.tree.selection()
        for item in selected_items:
            item_values = self.tree.item(item, "values")
            download_id = item_values[0]  # ID sütunu

            # Veritabanından indirme bilgilerini al
            download = self.db.get_download(download_id)
            if download and download.get("file_path"):
                file_path = Path(download["file_path"])
                # Fiziksel dosyayı diskten sil
                try:
                    if file_path.exists():
                        file_path.unlink()
                except Exception as e:
                    logger.error(f"Dosya diskten silinirken hata oluştu: {e}")

            self.db.delete_download(download_id)
            self.tree.delete(item)


    """Main application window for MC Download Manager."""

    CATEGORIES = ["Tümü", "Belgeler", "Resimler", "Müzik", "Video", "Arşivler", "Programlar", "Diğer"]

    def __init__(self):
        super().__init__(themename="darkly")
        self.title("WN Download Manager")
        self.geometry("1080x680")
        self.minsize(800, 500)

        self.settings = load_settings()
        self.db = DownloadDatabase()
        self.engine = DownloadEngine(
            max_concurrent=self.settings.get("max_simultaneous_downloads", 3),
            default_connections=self.settings.get("default_connections", 8),
            speed_limit_kbs=self.settings.get("speed_limit_kbs", 0),
        )
        self.engine.start_engine()

        # In-memory tracking for video tasks
        self.video_tasks: Dict[int, VideoDownloadTask] = {}
        self.current_category = "Tümü"
        self.search_term = ""

        # Setup icon
        try:
            self._icon_pil = get_app_icon_image()
            self._icon_photo = tb.PhotoImage(self._icon_pil)
            self.iconphoto(False, self._icon_photo)
        except Exception as e:
            logger.debug(f"Could not set Tk icon: {e}")

        self._build_ui()
        self._setup_shortcuts()
        self._load_downloads_from_db()
        self._start_status_updater()

        # Handle close event (minimize to tray vs exit)
        self.protocol("WM_DELETE_WINDOW", self.on_close_window)

    def _build_ui(self) -> None:
        # 1. Top Toolbar
        toolbar = tb.Frame(self, bootstyle="secondary", padding=6)
        toolbar.pack(side=TOP, fill=X)

        tb.Button(
            toolbar,
            text="➕ URL Ekle",
            bootstyle="success",
            command=self.open_add_dialog,
        ).pack(side=LEFT, padx=3)

        tb.Button(
            toolbar,
            text="▶ Devam Et",
            bootstyle="primary-outline",
            command=self.resume_selected,
        ).pack(side=LEFT, padx=3)

        tb.Button(
            toolbar,
            text="⏸ Duraklat",
            bootstyle="warning-outline",
            command=self.pause_selected,
        ).pack(side=LEFT, padx=3)

        tb.Button(
            toolbar,
            text="⏹ İptal Et",
            bootstyle="danger-outline",
            command=self.cancel_selected,
        ).pack(side=LEFT, padx=3)

        tb.Button(
            toolbar,
            text="🗑 Sil",
            bootstyle="secondary-outline",
            command=self.delete_selected,
        ).pack(side=LEFT, padx=3)

        tb.Separator(toolbar, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=8)

        tb.Button(
            toolbar,
            text="⚙ Ayarlar",
            bootstyle="info-outline",
            command=self.open_settings_dialog,
        ).pack(side=LEFT, padx=3)

        # Search bar on toolbar right side
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self._on_search_change())
        search_entry = tb.Entry(
            toolbar, textvariable=self.search_var, width=22, bootstyle="secondary"
        )
        search_entry.pack(side=RIGHT, padx=5)
        tb.Label(toolbar, text="🔍 Ara:", bootstyle="secondary-inverse").pack(side=RIGHT)

        # 2. Main Body (Sidebar + Content Treeview)
        body = tb.Frame(self)
        body.pack(side=TOP, fill=BOTH, expand=True)

        # Sidebar for Categories
        sidebar = tb.Labelframe(body, text=" Kategoriler ", padding=10, width=170)
        sidebar.pack(side=LEFT, fill=Y, padx=(10, 5), pady=10)
        sidebar.pack_propagate(False)

        self.category_buttons: Dict[str, tb.Button] = {}
        cat_icons = {
            "Tümü": "📁",
            "Belgeler": "📄",
            "Resimler": "🖼",
            "Müzik": "🎵",
            "Video": "🎬",
            "Arşivler": "📦",
            "Programlar": "⚡",
            "Diğer": "📎",
        }

        for cat in self.CATEGORIES:
            icon = cat_icons.get(cat, "•")
            btn = tb.Button(
                sidebar,
                text=f"{icon} {cat}",
                bootstyle="link",
                compound=LEFT,
                command=lambda c=cat: self.select_category(c),
            )
            btn.pack(fill=X, pady=2)
            self.category_buttons[cat] = btn

        # Only highlight the default category button visually;
        # the actual select_category (which calls refresh_downloads
        # and needs self.tree) is deferred to the end of _build_ui.
        self.category_buttons["Tümü"].configure(bootstyle="primary")

        # Download List Frame
        tree_frame = tb.Frame(body, padding=(5, 10, 10, 10))
        tree_frame.pack(side=LEFT, fill=BOTH, expand=True)

        columns = (
            "id",
            "filename",
            "size",
            "progress",
            "speed",
            "eta",
            "status",
            "category",
            "date_added",
        )
        self.tree = tb.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
            bootstyle="dark",
        )

        self.tree.heading("id", text="ID")
        self.tree.heading("filename", text="Dosya Adı")
        self.tree.heading("size", text="Boyut")
        self.tree.heading("progress", text="İlerleme")
        self.tree.heading("speed", text="Hız")
        self.tree.heading("eta", text="Kalan Süre")
        self.tree.heading("status", text="Durum")
        self.tree.heading("category", text="Kategori")
        self.tree.heading("date_added", text="Eklenme Tarihi")

        self.tree.column("id", width=45, anchor=CENTER)
        self.tree.column("filename", width=250, anchor=W)
        self.tree.column("size", width=85, anchor=E)
        self.tree.column("progress", width=80, anchor=CENTER)
        self.tree.column("speed", width=85, anchor=E)
        self.tree.column("eta", width=75, anchor=CENTER)
        self.tree.column("status", width=95, anchor=CENTER)
        self.tree.column("category", width=75, anchor=CENTER)
        self.tree.column("date_added", width=130, anchor=CENTER)

        tree_scroll_y = tb.Scrollbar(tree_frame, orient=VERTICAL, command=self.tree.yview)
        tree_scroll_x = tb.Scrollbar(tree_frame, orient=HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)

        self.tree.grid(row=0, column=0, sticky=NSEW)
        tree_scroll_y.grid(row=0, column=1, sticky=NS)
        tree_scroll_x.grid(row=1, column=0, sticky=EW)

        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        # Bind events
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Button-3>", self._on_tree_right_click)

        # Context Menu
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="▶ Devam Et", command=self.resume_selected)
        self.context_menu.add_command(label="⏸ Duraklat", command=self.pause_selected)
        self.context_menu.add_command(label="⏹ İptal Et", command=self.cancel_selected)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="📂 Dosyayı Aç", command=self.open_file)
        self.context_menu.add_command(label="📁 Klasörü Aç", command=self.open_folder)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🗑 Listeden Kaldır", command=lambda: self.delete_selected(delete_file=False))
        self.context_menu.add_command(label="❌ Dosya ile Birlikte Sil", command=lambda: self.delete_selected(delete_file=True))
        self.context_menu.add_separator()
        self.context_menu.add_command(label="ℹ Detayları Göster", command=self.show_selected_details)

        # 3. Status Bar
        self.statusbar = tb.Frame(self, bootstyle="secondary", padding=4)
        self.statusbar.pack(side=BOTTOM, fill=X)

        self.lbl_status_summary = tb.Label(
            self.statusbar,
            text="Aktif İndirmeler: 0 | Toplam Hız: 0 KB/s",
            font="-size 9",
        )
        self.lbl_status_summary.pack(side=LEFT, padx=10)

        self.lbl_status_info = tb.Label(
            self.statusbar,
            text="WN Download Manager Hazır",
            font="-size 9",
            bootstyle="secondary-inverse",
        )
        self.lbl_status_info.pack(side=RIGHT, padx=10)

        # Now that self.tree and all widgets exist, apply the default category
        self.select_category("Tümü")

    def _setup_shortcuts(self) -> None:
        self.bind("<Control-n>", lambda e: self.open_add_dialog())
        self.bind("<Control-N>", lambda e: self.open_add_dialog())
        self.bind("<Delete>", lambda e: self.delete_selected())
        self.bind("<F5>", lambda e: self.refresh_downloads())

    def select_category(self, cat: str) -> None:
        self.current_category = cat
        for name, btn in self.category_buttons.items():
            if name == cat:
                btn.configure(bootstyle="primary")
            else:
                btn.configure(bootstyle="link")
        self.refresh_downloads()

    def _on_search_change(self) -> None:
        self.search_term = self.search_var.get().strip()
        self.refresh_downloads()

    def _load_downloads_from_db(self) -> None:
        self.db.recover_interrupted_downloads()
        self.refresh_downloads()

    def refresh_downloads(self) -> None:
        """Fetch records from database and reload treeview."""
        downloads = self.db.get_all_downloads(
            category=self.current_category, search_term=self.search_term
        )

        # Maintain selected IDs
        selected_ids = {self.tree.item(i)["values"][0] for i in self.tree.selection() if self.tree.item(i)["values"]}

        # Clear and repopulate
        for item in self.tree.get_children():
            self.tree.delete(item)

        for d in downloads:
            did = d["id"]
            # Check if active task has live speed/progress
            task = self.engine.get_task(did)
            vid_task = self.video_tasks.get(did)

            status = d["status"]
            speed_str = "0 KB/s"
            eta_str = "--:--"
            progress_str = "0%"

            if task and task.status == "İndiriliyor":
                status = "İndiriliyor"
                speed_str = format_speed(task.current_speed)
                eta_str = format_eta(task.eta)
                if task.filesize > 0:
                    pct = (sum(s.downloaded_bytes for s in task.segments) / task.filesize) * 100
                    progress_str = f"{pct:.1f}%"
            elif vid_task and vid_task.status == "İndiriliyor":
                status = "İndiriliyor"
                speed_str = format_speed(vid_task.current_speed)
                eta_str = format_eta(vid_task.eta)
                if vid_task.total_bytes > 0:
                    pct = (vid_task.downloaded_bytes / vid_task.total_bytes) * 100
                    progress_str = f"{pct:.1f}%"
            elif d["filesize"] > 0:
                pct = (d["downloaded_bytes"] / d["filesize"]) * 100
                progress_str = f"{pct:.1f}%"
                if d["status"] == "Tamamlandı":
                    progress_str = "100%"

            item_id = self.tree.insert(
                "",
                END,
                values=(
                    did,
                    d["filename"],
                    format_bytes(d["filesize"]),
                    progress_str,
                    speed_str,
                    eta_str,
                    status,
                    d["category"],
                    d["date_added"],
                ),
            )

            if did in selected_ids:
                self.tree.selection_add(item_id)

    def _start_status_updater(self) -> None:
        """Periodic background status update for the statusbar and active tree items."""
        total_speed = self.engine.get_total_speed()
        for vt in self.video_tasks.values():
            if vt.status == "İndiriliyor":
                total_speed += vt.current_speed

        active_count = self.engine.get_active_count() + sum(
            1 for vt in self.video_tasks.values() if vt.status == "İndiriliyor"
        )

        self.lbl_status_summary.configure(
            text=f"Aktif İndirmeler: {active_count} | Toplam Hız: {format_speed(total_speed)}"
        )

        # Update rows for active downloads in treeview
        for item in self.tree.get_children():
            values = list(self.tree.item(item, "values"))
            if not values:
                continue
            did = int(values[0])
            task = self.engine.get_task(did)
            vid_task = self.video_tasks.get(did)

            if task and task.status == "İndiriliyor":
                total_dl = sum(s.downloaded_bytes for s in task.segments)
                pct = (total_dl / task.filesize * 100) if task.filesize > 0 else 0
                values[3] = f"{pct:.1f}%"
                values[4] = format_speed(task.current_speed)
                values[5] = format_eta(task.eta)
                values[6] = task.status
                self.tree.item(item, values=values)

            elif vid_task and vid_task.status == "İndiriliyor":
                pct = (
                    (vid_task.downloaded_bytes / vid_task.total_bytes * 100)
                    if vid_task.total_bytes > 0
                    else 0
                )
                values[3] = f"{pct:.1f}%"
                values[4] = format_speed(vid_task.current_speed)
                values[5] = format_eta(vid_task.eta)
                values[6] = vid_task.status
                self.tree.item(item, values=values)

        self.after(500, self._start_status_updater)

    def open_add_dialog(self, initial_url: str = "") -> None:
        AddDownloadDialog(self, initial_url=initial_url)

    def open_settings_dialog(self) -> None:
        SettingsDialog(self)

    def apply_settings(self, new_settings: Dict[str, Any]) -> None:
        self.settings = new_settings
        self.engine.max_concurrent = new_settings.get("max_simultaneous_downloads", 3)
        self.engine.default_connections = new_settings.get("default_connections", 8)
        self.engine.speed_limit_kbs = new_settings.get("speed_limit_kbs", 0)

    def add_download_from_dialog(
        self,
        url: str,
        filename: str,
        dest_path: str,
        is_video: bool = False,
        video_quality: str = "En İyi",
        connections: int = 8,
        headers: Optional[Dict[str, str]] = None,
        auto_start: bool = True,
    ) -> None:
        cat = get_category_by_extension(filename)
        status = "Bekliyor" if auto_start else "Duraklatıldı"

        did = self.db.add_download(
            url=url,
            filename=filename,
            filepath=dest_path,
            filesize=0,
            category=cat,
            num_connections=connections,
            headers=headers or {},
            download_type="video" if is_video else "direct",
            status=status,
        )

        if is_video:
            vtask = VideoDownloadTask(
                download_id=did,
                url=url,
                dest_folder=Path(dest_path).parent,
                quality=video_quality,
                progress_callback=self._on_download_progress,
                status_callback=self._on_download_status_change,
                metadata_callback=self._on_metadata_updated,
            )
            self.video_tasks[did] = vtask
            if auto_start:
                vtask.start()
        else:
            self.engine.add_task(
                download_id=did,
                url=url,
                dest_path=dest_path,
                num_connections=connections,
                headers=headers,
                auto_start=auto_start,
                progress_callback=self._on_download_progress,
                status_callback=self._on_download_status_change,
                metadata_callback=self._on_metadata_updated,
            )

        self.refresh_downloads()

    def _on_download_progress(
        self, did: int, downloaded: int, total: int, speed: float, eta: float, status: str
    ) -> None:
        # Update database periodically
        self.db.update_download_progress(did, downloaded, total)

    def _on_download_status_change(self, did: int, status: str, error: str) -> None:
        completed = status == "Tamamlandı"
        self.db.update_download_status(did, status, error, completed=completed)

        if completed and self.settings.get("notifications_enabled", True):
            rec = self.db.get_download(did)
            fname = rec["filename"] if rec else f"İndirme #{did}"
            show_desktop_notification("İndirme Tamamlandı", f"{fname} başarıyla indirildi.")

        self.after(0, self.refresh_downloads)

    def _on_metadata_updated(
        self, did: int, filename: str, filepath: str, filesize: int, category: str
    ) -> None:
        self.db.update_download_metadata(did, filename, filepath, filesize, category)
        self.after(0, self.refresh_downloads)

    def _get_selected_ids(self) -> List[int]:
        selected = []
        for item in self.tree.selection():
            values = self.tree.item(item, "values")
            if values:
                selected.append(int(values[0]))
        return selected

    def resume_selected(self) -> None:
        for did in self._get_selected_ids():
            if did in self.video_tasks:
                self.video_tasks[did].start()
            else:
                self.engine.resume_task(did)
            self.db.update_download_status(did, "Bekliyor")
        self.refresh_downloads()

    def pause_selected(self) -> None:
        for did in self._get_selected_ids():
            if did in self.video_tasks:
                self.video_tasks[did].cancel()
            else:
                self.engine.pause_task(did)
            self.db.update_download_status(did, "Duraklatıldı")
        self.refresh_downloads()

    def cancel_selected(self) -> None:
        for did in self._get_selected_ids():
            if did in self.video_tasks:
                self.video_tasks[did].cancel()
            else:
                self.engine.cancel_task(did)
            self.db.update_download_status(did, "İptal Edildi")
        self.refresh_downloads()

    def delete_selected(self, delete_file: bool = False) -> None:
        ids = self._get_selected_ids()
        if not ids:
            return

        msg = "Seçilen indirmeleri kaldırmak istiyor musunuz?"
        if delete_file:
            msg = "Seçilen indirmeler ve bilgisayarınızdaki dosyaları kalıcı olarak silinecek. Emin misiniz?"

        if not messagebox.askyesno("Onayla", msg):
            return

        for did in ids:
            rec = self.db.get_download(did)
            if did in self.video_tasks:
                self.video_tasks[did].cancel()
                self.video_tasks.pop(did, None)
            else:
                self.engine.remove_task(did)

            if delete_file and rec and rec.get("filepath"):
                fp = Path(rec["filepath"])
                if fp.exists():
                    try:
                        fp.unlink()
                    except Exception as e:
                        logger.error(f"Failed to delete file {fp}: {e}")

            self.db.delete_download(did)

        self.refresh_downloads()

    def open_file(self) -> None:
        ids = self._get_selected_ids()
        if not ids:
            return
        rec = self.db.get_download(ids[0])
        if rec and rec.get("filepath"):
            fp = Path(rec["filepath"])
            if fp.exists():
                os.startfile(str(fp))
            else:
                messagebox.showwarning("Bulunamadı", "Dosya belirtilen konumda bulunamadı.")

    def open_folder(self) -> None:
        ids = self._get_selected_ids()
        if not ids:
            return
        rec = self.db.get_download(ids[0])
        if rec and rec.get("filepath"):
            parent_dir = Path(rec["filepath"]).parent
            if parent_dir.exists():
                subprocess.Popen(["explorer", str(parent_dir)])

    def show_selected_details(self) -> None:
        ids = self._get_selected_ids()
        if not ids:
            return
        rec = self.db.get_download(ids[0])
        if rec:
            DownloadDetailDialog(self, rec)

    def _on_tree_double_click(self, event) -> None:
        self.show_selected_details()

    def _on_tree_right_click(self, event) -> None:
        item = self.tree.identify_row(event.y)
        if item:
            if item not in self.tree.selection():
                self.tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def on_close_window(self) -> None:
        """Handle window close: minimize or exit based on settings."""
        self.withdraw()  # Minimize to system tray
