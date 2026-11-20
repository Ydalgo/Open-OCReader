"""
Interfaz gráfica de usuario (GUI) nativa para Open OCReader.
Incluye:
  - Pestaña 1: Conversión rápida y fiel (PDF Sandwich, DOCX, XLSX, TXT, JSON) con Drag & Drop y Ctrl+V.
  - Pestaña 2: Inteligencia Documental Local (Qwen3-VL vía llama.cpp) para letra manuscrita,
               traducción al español, anonimización RGPD, resúmenes y preguntas Q&A.
"""

import os
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font as tkfont
from PIL import Image, ImageDraw, ImageGrab, ImageTk
from .accessibility import (
    AccessibilityConfig,
    THEME_DISPLAY_LABELS,
    VALID_THEME_MODES,
    get_accessible_palette,
    get_tts_engine,
)
from .converter import DocumentConverter
from .document_loader import DocumentLoader
from .engine import OCREngine
from .i18n import (
    SUPPORTED_UI_LANGUAGES,
    TRANSLATION_TARGET_LANGUAGES,
    get_llm_language_name,
    tr,
)
from .logger import get_logger, get_logs_dir

GITHUB_REPO_URL = "https://github.com/Ydalgo/Open-OCReader"

logger = get_logger("gui")

# Soporte nativo de Drag & Drop en Windows
try:
    import windnd
    HAS_WINDND = True
except ImportError:
    HAS_WINDND = False

# Soporte de portapapeles de Windows para ficheros copiados
try:
    import win32clipboard
    import win32con
    HAS_WIN32CLIP = True
except ImportError:
    HAS_WIN32CLIP = False


def _resolve_ico_dir() -> Path | None:
    """Localiza el directorio de recursos gráficos 'ico/' en modo fuente o compilado."""
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([exe_dir / "ico", exe_dir / "_internal" / "ico"])
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "ico")
    else:
        candidates.append(Path(__file__).resolve().parent.parent.parent / "ico")
    return next((d for d in candidates if d.exists()), None)


def _strip_leading_emoji(text: str) -> str:
    """Elimina el emoji inicial monocromo para acompañar limpiamente al icono en color."""
    s = (text or "").strip()
    if not s:
        return ""
    parts = s.split(" ", 1)
    if len(parts) == 2 and parts[0] and not parts[0][0].isalnum():
        s = parts[1].strip()
    return f" {s}" if s else ""


def _render_icon_photo(draw_fn, master: tk.Misc, size: int = 16) -> ImageTk.PhotoImage:
    """Renderiza un icono vectorial sobre un lienzo 64x64 (anti-aliased LANCZOS)."""
    canvas_64 = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas_64)
    draw_fn(draw, 64)
    small = canvas_64.resize((size, size), Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(small, master=master)


def _resolve_dyslexia_font() -> str:
    """Selecciona OpenDyslexic si está instalada o Verdana como tipografía clara espaciada."""
    try:
        fams = {f.lower(): f for f in tkfont.families()}
        for cand in ("opendyslexic", "opendyslexic3", "opendyslexicalta"):
            if cand in fams:
                return fams[cand]
        for cand in ("verdana", "tahoma", "arial"):
            if cand in fams:
                return fams[cand]
    except Exception:
        pass
    return "Verdana" if sys.platform == "win32" else "DejaVu Sans"


def _build_supersampled_ui_icons(
    master: tk.Misc,
    dark_mode: bool,
    size: int = 16,
    logo_size: int = 34,
) -> dict[str, ImageTk.PhotoImage]:
    """Genera iconos nítidos a todo color y carga el logotipo oficial de la cabecera."""
    icons: dict[str, ImageTk.PhotoImage] = {}

    # Logo oficial de cabecera escalado proporcionalmente
    ico_dir = _resolve_ico_dir()
    if ico_dir and (ico_dir / "Open_OCReader.png").exists():
        try:
            logo_pil = Image.open(ico_dir / "Open_OCReader.png").convert("RGBA")
            logo_pil = logo_pil.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
            icons["logo"] = ImageTk.PhotoImage(logo_pil, master=master)
        except Exception:
            pass

    def _d_convert(d: ImageDraw.ImageDraw, h: int):
        # Hoja azul-blanca con flecha verde de conversión
        d.rounded_rectangle([8, 6, 44, 56], radius=6, fill="#e8f1fb", outline="#1a5fb4", width=5)
        d.line([16, 20, 36, 20], fill="#1a5fb4", width=4)
        d.line([16, 30, 30, 30], fill="#1a5fb4", width=4)
        d.ellipse([30, 28, 58, 58], fill="#16a34a", outline="#ffffff", width=3)
        d.line([38, 43, 50, 43], fill="#ffffff", width=5)
        d.polygon([(46, 36), (54, 43), (46, 50)], fill="#ffffff")

    def _d_translate(d: ImageDraw.ImageDraw, h: int):
        # Globo terráqueo azul cielo con meridianos
        d.ellipse([6, 6, 58, 58], fill="#0284c7", outline="#0369a1", width=4)
        d.arc([18, 6, 46, 58], start=0, end=360, fill="#bae6fd", width=4)
        d.line([8, 24, 56, 24], fill="#bae6fd", width=4)
        d.line([8, 40, 56, 40], fill="#bae6fd", width=4)
        d.line([32, 6, 32, 58], fill="#e0f2fe", width=3)

    def _d_chat(d: ImageDraw.ImageDraw, h: int):
        # Burbuja de diálogo verde esmeralda con líneas
        d.rounded_rectangle([6, 8, 58, 48], radius=12, fill="#059669", outline="#047857", width=3)
        d.polygon([(16, 46), (14, 58), (28, 46)], fill="#059669")
        d.line([16, 22, 48, 22], fill="#ffffff", width=4)
        d.line([16, 33, 40, 33], fill="#d1fae5", width=4)

    def _d_ai(d: ImageDraw.ImageDraw, h: int):
        # Chip / nodo neuronal violeta con núcleo dorado
        for pos in (18, 32, 46):
            d.line([pos, 4, pos, 60], fill="#7c3aed", width=4)
            d.line([4, pos, 60, pos], fill="#7c3aed", width=4)
        d.rounded_rectangle([12, 12, 52, 52], radius=10, fill="#6d28d9", outline="#a78bfa", width=4)
        d.polygon([(32, 18), (37, 27), (46, 32), (37, 37), (32, 46), (27, 37), (18, 32), (27, 27)], fill="#fbbf24")

    def _d_anonymize(d: ImageDraw.ImageDraw, h: int):
        # Escudo dorado RGPD con cerradura oscura
        d.polygon([(32, 4), (56, 14), (52, 42), (32, 60), (12, 42), (8, 14)], fill="#f59e0b", outline="#b45309", width=4)
        d.ellipse([24, 20, 40, 34], fill="#451a03")
        d.polygon([(27, 30), (37, 30), (39, 44), (25, 44)], fill="#451a03")

    def _d_pdf_tools(d: ImageDraw.ImageDraw, h: int):
        # Documento rojo PDF + insignia de herramienta metálica
        d.rounded_rectangle([8, 6, 46, 56], radius=6, fill="#dc2626", outline="#991b1b", width=4)
        d.line([16, 20, 38, 20], fill="#ffffff", width=4)
        d.line([16, 30, 32, 30], fill="#fecaca", width=4)
        d.ellipse([32, 32, 58, 58], fill="#334155", outline="#ffffff", width=3)
        d.line([39, 39, 51, 51], fill="#e2e8f0", width=5)

    def _d_accessibility(d: ImageDraw.ImageDraw, h: int):
        # Símbolo universal de accesibilidad azul cobalto / blanco y aro dorado
        d.ellipse([4, 4, 60, 60], fill="#1d4ed8", outline="#fbbf24", width=4)
        d.ellipse([26, 12, 38, 24], fill="#ffffff")
        d.line([14, 29, 50, 29], fill="#ffffff", width=5)
        d.line([32, 26, 32, 40], fill="#ffffff", width=6)
        d.line([32, 39, 21, 52], fill="#ffffff", width=5)
        d.line([32, 39, 43, 52], fill="#ffffff", width=5)

    def _d_tts_speak(d: ImageDraw.ImageDraw, h: int):
        # Altavoz azul/turquesa con ondas de sonido verde esmeralda
        d.polygon([(8, 24), (20, 24), (34, 12), (34, 52), (20, 40), (8, 40)], fill="#0284c7", outline="#0369a1", width=3)
        d.arc([34, 18, 50, 46], start=300, end=60, fill="#10b981", width=5)
        d.arc([36, 10, 58, 54], start=305, end=55, fill="#34d399", width=4)

    def _d_tts_stop(d: ImageDraw.ImageDraw, h: int):
        # Cuadrado redondeado rojo de parada inmediata
        d.ellipse([6, 6, 58, 58], fill="#fee2e2", outline="#dc2626", width=4)
        d.rounded_rectangle([20, 20, 44, 44], radius=4, fill="#dc2626")

    def _d_easy_read(d: ImageDraw.ImageDraw, h: int):
        # Libro abierto turquesa/verde con estrella de lectura fácil
        d.rounded_rectangle([6, 12, 32, 52], radius=5, fill="#0d9488", outline="#115e59", width=3)
        d.rounded_rectangle([32, 12, 58, 52], radius=5, fill="#14b8a6", outline="#115e59", width=3)
        d.line([12, 24, 26, 24], fill="#ffffff", width=3)
        d.line([12, 34, 26, 34], fill="#ccfbf1", width=3)
        d.polygon([(45, 22), (48, 29), (55, 31), (48, 34), (45, 41), (42, 34), (35, 31), (42, 29)], fill="#fde047")

    def _d_github(d: ImageDraw.ImageDraw, h: int):
        fill_c = "#e2e8f0" if dark_mode else "#24292f"
        line_c = "#1e1f22" if dark_mode else "#ffffff"
        d.ellipse([6, 6, 58, 58], fill=fill_c)
        d.line([24, 18, 24, 46], fill=line_c, width=5)
        d.line([24, 34, 40, 22], fill=line_c, width=5)
        d.ellipse([18, 14, 30, 26], fill=line_c)
        d.ellipse([18, 40, 30, 52], fill=line_c)
        d.ellipse([34, 16, 46, 28], fill=line_c)

    def _d_legal(d: ImageDraw.ImageDraw, h: int):
        # Balanza institucional azul/oro
        d.line([32, 10, 32, 54], fill="#1d4ed8", width=5)
        d.line([16, 54, 48, 54], fill="#1d4ed8", width=5)
        d.line([10, 18, 54, 18], fill="#f59e0b", width=5)
        d.polygon([(6, 36), (22, 36), (14, 20)], fill="#f59e0b")
        d.polygon([(42, 36), (58, 36), (50, 20)], fill="#f59e0b")

    def _d_update(d: ImageDraw.ImageDraw, h: int):
        d.arc([8, 8, 56, 56], start=35, end=215, fill="#0284c7", width=6)
        d.arc([8, 8, 56, 56], start=215, end=35, fill="#0ea5e9", width=6)
        d.polygon([(48, 12), (58, 26), (40, 26)], fill="#0284c7")
        d.polygon([(16, 52), (6, 38), (24, 38)], fill="#0ea5e9")

    def _d_reinstall(d: ImageDraw.ImageDraw, h: int):
        d.arc([10, 10, 54, 54], start=0, end=300, fill="#16a34a", width=6)
        d.polygon([(44, 18), (58, 20), (50, 6)], fill="#16a34a")
        d.ellipse([24, 24, 40, 40], fill="#22c55e")

    def _d_cache(d: ImageDraw.ImageDraw, h: int):
        # Destello/limpieza ámbar-naranja
        d.polygon([(32, 6), (39, 25), (58, 32), (39, 39), (32, 58), (25, 39), (6, 32), (25, 25)], fill="#ea580c")
        d.ellipse([26, 26, 38, 38], fill="#fef08a")

    def _d_clear_logs(d: ImageDraw.ImageDraw, h: int):
        # Papelera roja
        d.line([14, 14, 50, 14], fill="#dc2626", width=6)
        d.line([24, 8, 40, 8], fill="#dc2626", width=5)
        d.rounded_rectangle([16, 18, 48, 56], radius=6, fill="#ef4444", outline="#991b1b", width=4)
        d.line([26, 26, 26, 48], fill="#ffffff", width=4)
        d.line([38, 26, 38, 48], fill="#ffffff", width=4)

    def _d_view_logs(d: ImageDraw.ImageDraw, h: int):
        # Portapapeles gris/azul con líneas
        d.rounded_rectangle([12, 12, 52, 56], radius=6, fill="#f8fafc", outline="#475569", width=5)
        d.rounded_rectangle([22, 6, 42, 16], radius=3, fill="#0284c7")
        d.line([20, 26, 44, 26], fill="#334155", width=4)
        d.line([20, 36, 44, 36], fill="#334155", width=4)
        d.line([20, 46, 36, 46], fill="#64748b", width=4)

    specs = {
        "tab_convert": _d_convert,
        "tab_translate": _d_translate,
        "tab_chat": _d_chat,
        "tab_ai": _d_ai,
        "tab_anonymize": _d_anonymize,
        "tab_pdf_tools": _d_pdf_tools,
        "accessibility": _d_accessibility,
        "tts_speak": _d_tts_speak,
        "tts_stop": _d_tts_stop,
        "easy_read": _d_easy_read,
        "github": _d_github,
        "legal": _d_legal,
        "update": _d_update,
        "reinstall": _d_reinstall,
        "cache": _d_cache,
        "clear_logs": _d_clear_logs,
        "view_logs": _d_view_logs,
    }
    for key, fn in specs.items():
        icons[key] = _render_icon_photo(fn, master=master, size=size)
    return icons


class ResponsiveFlowFrame(ttk.Frame):
    """Contenedor elástico que envuelve sus widgets en filas sin recortar texto jamás."""

    def __init__(self, master: tk.Misc, align: str = "left", hgap: int = 5, vgap: int = 4, **kwargs):
        kwargs.setdefault("height", 30)
        super().__init__(master, **kwargs)
        self._align = align
        self._hgap = hgap
        self._vgap = vgap
        self._items: list[tk.Widget] = []
        self._relayout_job = None
        self._last_sig = None
        self._last_width = 0
        self.bind("<Configure>", self._on_configure)

    def add_item(self, widget: tk.Widget):
        """Registra un widget hijo y programa su redistribución fluida."""
        self._items.append(widget)
        self._schedule_relayout()
        return widget

    def set_align(self, align: str):
        if align != self._align:
            self._align = align
            self._last_sig = None
            self._schedule_relayout()

    def set_gaps(self, hgap: int, vgap: int):
        if hgap != self._hgap or vgap != self._vgap:
            self._hgap = hgap
            self._vgap = vgap
            self._last_sig = None
            self._schedule_relayout()

    def total_single_row_width(self) -> int:
        if not self._items:
            return 0
        return sum(max(24, w.winfo_reqwidth()) for w in self._items) + max(0, len(self._items) - 1) * self._hgap

    def _on_configure(self, event):
        if event.widget is not self:
            return
        if event.width > 20 and event.width != self._last_width:
            self._last_width = event.width
            self._schedule_relayout()

    def _schedule_relayout(self):
        if self._relayout_job is not None:
            try:
                self.after_cancel(self._relayout_job)
            except Exception:
                pass
        self._relayout_job = self.after_idle(self.relayout)

    def relayout(self, avail_width: Optional[int] = None, force: bool = False):
        self._relayout_job = None
        if not self._items:
            return
        w = avail_width or self.winfo_width()
        if w <= 24:
            w = max(320, self.master.winfo_width() - 24)
        if w <= 24:
            return

        dims = [(widget, max(20, widget.winfo_reqwidth()), max(20, widget.winfo_reqheight())) for widget in self._items]
        sig = (w, self._align, self._hgap, self._vgap, tuple((id(wd), ww, wh) for wd, ww, wh in dims))
        if not force and sig == self._last_sig:
            return
        self._last_sig = sig

        rows: list[tuple[list[tuple[tk.Widget, int, int]], int, int]] = []
        cur_row: list[tuple[tk.Widget, int, int]] = []
        cur_w = 0
        cur_h = 0

        for wd, ww, wh in dims:
            needed = ww if not cur_row else (cur_w + self._hgap + ww)
            if cur_row and needed > w:
                rows.append((cur_row, cur_w, cur_h))
                cur_row = [(wd, ww, wh)]
                cur_w = ww
                cur_h = wh
            else:
                cur_row.append((wd, ww, wh))
                cur_w = needed
                cur_h = max(cur_h, wh)
        if cur_row:
            rows.append((cur_row, cur_w, cur_h))

        y = 0
        for row_items, row_w, row_h in rows:
            x = max(0, w - row_w) if self._align == "right" else 0
            for wd, ww, wh in row_items:
                wd.place(x=x, y=y + max(0, (row_h - wh) // 2), width=ww, height=wh)
                x += ww + self._hgap
            y += row_h + self._vgap

        total_h = max(24, y - self._vgap + 2 if rows else 24)
        if self.winfo_reqheight() != total_h:
            self.configure(height=total_h)


class VerticalScrollableFrame(ttk.Frame):
    """Marco con desplazamiento vertical inteligente para pantallas pequeñas o zoom alto."""

    def __init__(self, master: tk.Misc, bg: str = "#f5f6f8", **kwargs):
        super().__init__(master, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg=bg)
        self.vbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.inner = ttk.Frame(self.canvas)
        self._win_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self._sync_job = None
        self._last_scroll_sig = None

        self.canvas.bind("<Configure>", lambda e: self._schedule_sync())
        self.inner.bind("<Configure>", lambda e: self._schedule_sync())

    def set_background(self, bg: str):
        self.canvas.configure(bg=bg)

    def _schedule_sync(self):
        if self._sync_job is not None:
            try:
                self.after_cancel(self._sync_job)
            except Exception:
                pass
        self._sync_job = self.after_idle(self.sync_scrollregion)

    def sync_scrollregion(self):
        self._sync_job = None
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 24 or ch < 24:
            return
        req_h = max(ch, self.inner.winfo_reqheight())
        sig = (cw, ch, req_h)
        if sig == self._last_scroll_sig:
            return
        self._last_scroll_sig = sig
        self.canvas.itemconfigure(self._win_id, width=cw, height=req_h)
        self.canvas.configure(scrollregion=(0, 0, cw, req_h))
        if req_h <= ch + 2:
            self.canvas.yview_moveto(0.0)

    def scroll_widget_into_view(self, widget: Optional[tk.Misc]):
        if widget is None:
            return
        try:
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()
            req_h = self.inner.winfo_reqheight()
            if req_h <= ch + 2 or ch < 40:
                return
            wy = widget.winfo_rooty() - self.inner.winfo_rooty()
            wh = widget.winfo_height()
            top_vis = self.canvas.canvasy(0)
            bot_vis = top_vis + ch
            if wy < top_vis:
                self.canvas.yview_moveto(max(0.0, wy / max(1, req_h)))
            elif wy + wh > bot_vis:
                target_top = (wy + wh) - ch + 16
                self.canvas.yview_moveto(min(1.0, max(0.0, target_top / max(1, req_h))))
        except Exception:
            pass

    def handle_mousewheel(self, event) -> Optional[str]:
        # Dejar que cuadros de texto / listas internas hagan su propio scroll
        cur = event.widget
        while cur is not None:
            if isinstance(cur, (tk.Text, tk.Listbox, ttk.Treeview)):
                return None
            if cur is self.canvas or cur is self:
                break
            cur = getattr(cur, "master", None)
        ch = self.canvas.winfo_height()
        req_h = self.inner.winfo_reqheight()
        if req_h <= ch + 2:
            return None
        delta = -1 if getattr(event, "delta", 0) > 0 else 1
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        self.canvas.yview_scroll(delta * 3, "units")
        return "break"


class OpenOCReaderGUI:
    """Ventana principal de la interfaz gráfica de Open OCReader."""

    FORMAT_OPTIONS = [
        ("PDF Buscable (Sandwich)", "pdf", "Diseño visual 100% original + texto invisible"),
        ("PDF/A-2b (Archivo Público)", "pdfa", "Estándar oficial de archivo Adm. Públicas"),
        ("Microsoft Word (.docx)", "docx", "Documento editable fiel (fondos e imágenes)"),
        ("OpenDocument Text (.odt)", "odt", "LibreOffice fiel con fondos e imágenes"),
        ("Microsoft Excel (.xlsx)", "xlsx", "Hoja de cálculo por coordenadas"),
        ("OpenDocument Calc (.ods)", "ods", "Hoja de cálculo libre por coordenadas"),
        ("CSV Tabular (.csv)", "csv", "Datos tabulares separados por punto y coma"),
        ("eBook (.epub)", "epub", "Libro electrónico para Kindle/Kobo/Calibre"),
        ("Texto plano (.txt)", "txt", "Volcado de texto en orden de lectura"),
        ("JSON Estructurado (.json)", "json", "Coordenadas geométricas y confianza"),
    ]

    COMPRESSION_LABELS = [
        ("Alta calidad (original)", "high"),
        ("Equilibrada (recomendada)", "balanced"),
        ("Máxima compresión (ligero)", "compact"),
    ]

    EXPORT_CONV_FORMATS = [
        ("Word (.docx)", "docx"),
        ("PDF (.pdf)", "pdf"),
        ("PDF/A-2b (.pdf)", "pdfa"),
        ("LibreOffice (.odt)", "odt"),
        ("eBook (.epub)", "epub"),
        ("Markdown (.md)", "md"),
        ("Texto (.txt)", "txt"),
        ("JSON (.json)", "json"),
    ]

    def __init__(self, root: tk.Tk):
        self.root = root
        self._ui_ready = False
        self.root.title("Open OCReader - Digitalización e IA Documental 100% Local")
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        win_w = min(1240, max(780, sw - 50))
        win_h = min(860, max(600, sh - 70))
        self.root.geometry(f"{win_w}x{win_h}")
        self.root.minsize(680, 520)
        self._window_icon_ref = None
        self._apply_window_icon()

        # Preferencias persistentes de accesibilidad universal y tema visual
        self.a11y = AccessibilityConfig.load()
        self.tts = get_tts_engine()
        self._os_dark_mode = self._detect_os_dark_mode()
        self.palette = get_accessible_palette(self.a11y.theme_mode, self._os_dark_mode)
        self.is_dark_mode = self.palette.get("is_dark") == "1"
        self.text_font_size = self.a11y.text_font_size

        # Registros dinámicos para re-escalado (A-/A+) y cambio de tema/contraste en vivo
        self._zoomable_texts = []
        self._tracked_labels = []
        self._wrapping_labels = []
        self._scaled_entries = []
        self._scaled_listboxes = []
        self._flow_frames: list[ResponsiveFlowFrame] = []
        self._radio_grid_groups = []
        self._has_input_file_loaded = False
        self._last_root_size = (0, 0)
        self._resize_job = None
        self._header_stacked = None
        self._tabs_compact_mode = None
        self._tts_speaking_active = False

        self.zoom_pct_var = tk.StringVar(value=f"{self.a11y.zoom_percent}%")
        self.style = ttk.Style()
        self._apply_os_theme_and_fonts()

        # Perfil de hardware detectado para adaptar la interfaz y las capacidades de IA
        from .ai.hardware import get_hardware_profile
        self.hw = get_hardware_profile()
        self.ai_tier = self.hw.ai_tier

        self.ui_lang = "es"
        self.ui_lang_var = tk.StringVar(value="Español")
        self.translate_lang_var = tk.StringVar(value="Español")
        self.input_path_var = tk.StringVar()
        self.output_path_var = tk.StringVar()
        self.format_var = tk.StringVar(value="pdf")
        self.format_desc_var = tk.StringVar(value="Conserva el diseño visual 100% original con capa de texto invisible.")
        self.force_ocr_var = tk.BooleanVar(value=False)
        self.grayscale_var = tk.BooleanVar(value=False)
        self.compression_var = tk.StringVar(value="Alta calidad (original)")
        self.status_var = tk.StringVar(value="Arrastra un fichero, pulsa 'Examinar' o pega con Ctrl+V.")
        self.ai_status_var = tk.StringVar(value="Listo. Selecciona un documento y elige una acción inteligente.")
        self.handwriting_var = tk.BooleanVar(value=False)
        self.ai_force_ocr_var = tk.BooleanVar(value=False)
        self.question_var = tk.StringVar()

        # Variables de Chat Multi-Documento
        self.chat_engine = None
        self.chat_doc_paths = []
        self.chat_question_var = tk.StringVar()
        self.chat_status_var = tk.StringVar(value="Añade uno o varios documentos (PDF o imágenes) y haz preguntas con citas.")
        self.chat_count_var = tk.StringVar(value="")
        self.chat_export_fmt_var = tk.StringVar(value="Word (.docx)")

        # Variables de pestaña Traducir Documento (directo a fichero fiel)
        self.trans_source_lang_var = tk.StringVar(value="Auto-detectar")
        self.trans_target_lang_var = tk.StringVar(value="Español")
        self.trans_format_var = tk.StringVar(value="docx")
        self.trans_format_desc_var = tk.StringVar(
            value="ℹ️ Documento editable fiel (fondos, imágenes, tablas y texto traducido)"
        )
        self.trans_preserve_layout_var = tk.BooleanVar(value=True)
        self.trans_grayscale_var = tk.BooleanVar(value=False)
        self.trans_force_ocr_var = tk.BooleanVar(value=False)
        self.trans_handwriting_var = tk.BooleanVar(value=False)
        self.trans_compression_var = tk.StringVar(value=self.COMPRESSION_LABELS[0][0])
        self.trans_output_path_var = tk.StringVar()
        self.trans_status_var = tk.StringVar(
            value="Selecciona un fichero arriba, elige idioma y formato de salida traducido."
        )
        self.last_translated_file: Optional[str] = None

        # Variables de exportación en IA y Manuscritos / Preguntas con citas
        self.ai_export_fmt_var = tk.StringVar(value="Word (.docx)")
        self.last_ai_turn_record = None
        self.ai_turn_records = []

        # Variables de Anonimización RGPD independiente (Paso 1: 100% Python + Paso 2: IA opcional)
        self.anon_mask_style_var = tk.StringVar(value="tags")
        self.anon_use_llm_var = tk.BooleanVar(value=bool(self.ai_tier.vlm_enabled))
        self.anon_status_var = tk.StringVar(value="Listo. Selecciona un documento arriba y pulsa 'Anonimizar documento'.")

        # Variables de Herramientas PDF
        self.pdf_password_var = tk.StringVar()
        self.wm_text_var = tk.StringVar()
        self.wm_annots_var = tk.BooleanVar(value=True)
        self.wm_scan_var = tk.BooleanVar(value=False)
        self.opt_compression_var = tk.StringVar(value="Equilibrada (recomendada)")
        self.opt_grayscale_var = tk.BooleanVar(value=False)
        self.opt_pdfa_var = tk.BooleanVar(value=False)
        self.pdf_tools_status_var = tk.StringVar(value="Selecciona un PDF arriba y elige una herramienta.")
        self.last_pdf_tool_file = None

        self.last_generated_file = None
        self.cached_doc_text = None
        self.cached_doc_tree = None
        self.cached_doc_key = None  # (file_path, handwriting_flag, force_ocr_flag)

        icon_px, logo_px = self._calc_icon_sizes()
        self._ui_icons = _build_supersampled_ui_icons(self.root, self.is_dark_mode, size=icon_px, logo_size=logo_px)
        self._build_ui()
        self._setup_drag_and_drop()
        self._setup_clipboard_paste()
        self._setup_accessibility_shortcuts()
        self.root.bind("<Configure>", self._on_root_configure)
        self.root.after(60, self._relayout_responsive_containers)
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        self._ui_ready = True

    def _calc_icon_sizes(self) -> tuple[int, int]:
        ui_sz = getattr(getattr(self, "a11y", None), "ui_font_size", 10)
        icon_px = max(16, min(28, int(round(ui_sz * 1.6))))
        logo_px = max(32, min(52, int(round(ui_sz * 3.4))))
        return icon_px, logo_px

    def _get_ui_font_family(self) -> str:
        if self.a11y.dyslexia_friendly:
            return _resolve_dyslexia_font()
        return "Segoe UI" if sys.platform == "win32" else "TkDefaultFont"

    def _get_text_font_family(self, prefer_mono: bool = False) -> str:
        if self.a11y.dyslexia_friendly:
            return _resolve_dyslexia_font()
        if prefer_mono:
            return "Consolas" if sys.platform == "win32" else "DejaVu Sans Mono"
        return "Segoe UI" if sys.platform == "win32" else "TkTextFont"

    def _get_font_tuple(self, size_delta: int = 0, bold: bool = False, italic: bool = False, mono: bool = False) -> tuple:
        fam = self._get_text_font_family(prefer_mono=mono) if mono else self._get_ui_font_family()
        sz = max(8, self.a11y.ui_font_size + size_delta)
        styles = []
        if bold:
            styles.append("bold")
        if italic:
            styles.append("italic")
        return (fam, sz, " ".join(styles)) if styles else (fam, sz)

    @staticmethod
    def _detect_os_dark_mode() -> bool:
        """Detecta si Windows tiene activado el tema oscuro para adaptar colores y contraste."""
        if sys.platform == "win32":
            try:
                import winreg
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                ) as key:
                    val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                    return int(val) == 0
            except Exception:
                pass
        return False

    def _apply_os_theme_and_fonts(self):
        """Aplica fuentes globales escalables y paleta accesible (claro/oscuro/WCAG AAA/dislexia)."""
        self.palette = get_accessible_palette(self.a11y.theme_mode, self._os_dark_mode)
        self.is_dark_mode = self.palette.get("is_dark") == "1"
        p = self.palette
        fam = self._get_ui_font_family()
        ui_sz = self.a11y.ui_font_size
        large = self.a11y.large_targets

        for fname in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                f = tkfont.nametofont(fname)
                f.configure(family=fam, size=ui_sz)
            except Exception:
                pass

        # En tema claro estándar sin objetivos ampliados podemos usar vista o clam;
        # clam garantiza contraste AAA, tema crema y zero clipping en pestañas cuando se hace zoom.
        use_clam = p["mode"] != "light" or large or ui_sz >= 12 or self.a11y.dyslexia_friendly
        try:
            if use_clam:
                self.style.theme_use("clam")
            else:
                self.style.theme_use("vista" if "vista" in self.style.theme_names() else "clam")
        except Exception:
            pass

        btn_pad = (10, 6) if large else (6, 3)
        tab_pad = (12, 7) if large else (9, 4)
        chk_pad = (6, 4) if large else (2, 1)
        is_hc = p["mode"].startswith("high_contrast")
        bw = 2 if is_hc else 1

        self.root.configure(bg=p["bg"])
        self.style.configure(".", background=p["bg"], foreground=p["fg"], font=(fam, ui_sz))
        self.style.configure("TFrame", background=p["bg"])
        self.style.configure("TLabelframe", background=p["bg"], foreground=p["fg"], borderwidth=bw)
        self.style.configure(
            "TLabelframe.Label",
            background=p["bg"],
            foreground=p["accent"],
            font=(fam, ui_sz, "bold"),
        )
        self.style.configure("TLabel", background=p["bg"], foreground=p["fg"])
        self.style.configure("TCheckbutton", background=p["bg"], foreground=p["fg"], padding=chk_pad)
        self.style.configure("TRadiobutton", background=p["bg"], foreground=p["fg"], padding=chk_pad)
        self.style.map(
            "TCheckbutton",
            background=[("active", p["btn_active"])],
            foreground=[("active", p["fg"])],
        )
        self.style.map(
            "TRadiobutton",
            background=[("active", p["btn_active"])],
            foreground=[("active", p["fg"])],
        )

        if self.style.theme_use() == "clam":
            self.style.configure(
                "TButton",
                background=p["btn_bg"],
                foreground=p["fg"],
                bordercolor=p["accent"] if is_hc else p["muted"],
                focuscolor=p["focus_ring"],
                focusthickness=2 if (is_hc or large) else 1,
                padding=btn_pad,
                font=(fam, ui_sz),
            )
            self.style.map(
                "TButton",
                background=[("active", p["btn_active"]), ("focus", p["btn_active"])],
                foreground=[("disabled", p["muted"])],
            )
            self.style.configure(
                "TEntry",
                fieldbackground=p["input_bg"],
                foreground=p["input_fg"],
                insertcolor=p["input_fg"],
                bordercolor=p["accent"] if is_hc else p["muted"],
                padding=6 if large else 3,
            )
            self.style.configure(
                "TCombobox",
                fieldbackground=p["input_bg"],
                background=p["btn_bg"],
                foreground=p["input_fg"],
                arrowcolor=p["fg"],
                bordercolor=p["accent"] if is_hc else p["muted"],
                padding=5 if large else 2,
            )
            self.style.map(
                "TCombobox",
                fieldbackground=[("readonly", p["input_bg"])],
                foreground=[("readonly", p["input_fg"])],
                selectbackground=[("readonly", p["btn_active"])],
                selectforeground=[("readonly", p["fg"])],
            )
            self.style.configure("TNotebook", background=p["bg"], bordercolor=p["accent"] if is_hc else p["muted"])
            self.style.configure(
                "TNotebook.Tab",
                background=p["tab_bg"],
                foreground=p["fg"],
                focuscolor=p["focus_ring"],
                padding=tab_pad,
                font=(fam, ui_sz),
            )
            self.style.map(
                "TNotebook.Tab",
                background=[("selected", p["tab_sel_bg"]), ("active", p["btn_active"])],
                foreground=[("selected", p["accent"])],
                font=[("selected", (fam, ui_sz, "bold"))],
            )
        else:
            self.style.configure("TButton", padding=btn_pad, font=(fam, ui_sz))
            self.style.configure("TEntry", padding=6 if large else 3)
            self.style.configure("TCombobox", padding=5 if large else 2)
            self.style.configure("TNotebook.Tab", padding=tab_pad, font=(fam, ui_sz))

        # Adaptar listas desplegables internas de Combobox al tema activo
        try:
            self.root.option_add("*TCombobox*Listbox.background", p["input_bg"])
            self.root.option_add("*TCombobox*Listbox.foreground", p["input_fg"])
            self.root.option_add("*TCombobox*Listbox.selectBackground", p["accent"])
            self.root.option_add("*TCombobox*Listbox.selectForeground", p["bg"])
            self.root.option_add("*TCombobox*Listbox.font", (fam, ui_sz))
        except Exception:
            pass

    def _track_label(
        self,
        lbl: ttk.Label,
        role: str = "fg",
        size_delta: int = 0,
        bold: bool = False,
        italic: bool = False,
        underline: bool = False,
        wrap: bool = False,
    ) -> ttk.Label:
        """Registra una etiqueta para que responda en vivo a tema, contraste, dislexia, zoom y envoltorio."""
        self._tracked_labels.append((lbl, role, size_delta, bold, italic, underline, wrap))
        self._apply_single_label_style(lbl, role, size_delta, bold, italic, underline)
        if wrap:
            self._wrapping_labels.append(lbl)
        return lbl

    def _apply_single_label_style(
        self,
        lbl: ttk.Label,
        role: str,
        size_delta: int,
        bold: bool,
        italic: bool,
        underline: bool,
    ):
        fam = self._get_ui_font_family()
        sz = max(8, self.a11y.ui_font_size + size_delta)
        styles = []
        if bold:
            styles.append("bold")
        if italic:
            styles.append("italic")
        if underline:
            styles.append("underline")
        font_spec = (fam, sz, " ".join(styles)) if styles else (fam, sz)
        try:
            lbl.configure(font=font_spec, foreground=self.palette.get(role, self.palette["fg"]))
        except Exception:
            pass

    def _register_scaled_entry(self, widget: tk.Widget, size_delta: int = -1):
        self._scaled_entries.append((widget, size_delta))
        try:
            widget.configure(font=self._get_font_tuple(size_delta=size_delta))
        except Exception:
            pass
        return widget

    def _register_zoomable_text(self, text_widget: tk.Text, family: str = "Segoe UI"):
        """Registra un área de texto para permitir zoom (A-/A+, Ctrl+Rueda), tema AAA y modo dislexia."""
        p = self.palette
        is_mono = family.lower() in {"consolas", "monospace", "courier", "dejavu sans mono"}
        eff_fam = self._get_text_font_family(prefer_mono=is_mono)
        extra_sp = (4, 3, 6) if self.a11y.dyslexia_friendly else (1, 1, 2)
        text_widget.configure(
            font=(eff_fam, self.text_font_size),
            bg=p["input_bg"],
            fg=p["input_fg"],
            insertbackground=p["input_fg"],
            selectbackground=p["accent"],
            selectforeground=p["bg"],
            spacing1=extra_sp[0],
            spacing2=extra_sp[1],
            spacing3=extra_sp[2],
            highlightthickness=1,
            highlightcolor=p["focus_ring"],
            highlightbackground=p["muted"],
        )
        self._zoomable_texts.append((text_widget, is_mono))
        text_widget.bind("<Control-MouseWheel>", self._on_ctrl_mousewheel)
        text_widget.bind("<Control-Button-4>", lambda e: self._adjust_global_zoom(1))
        text_widget.bind("<Control-Button-5>", lambda e: self._adjust_global_zoom(-1))

    def _on_ctrl_mousewheel(self, event):
        delta = 1 if event.delta > 0 else -1
        self._adjust_global_zoom(delta)
        return "break"

    def _adjust_text_zoom(self, delta: int):
        """Compatibilidad con llamadas previas: escala de forma global toda la UI y los textos."""
        self._adjust_global_zoom(delta)

    def _adjust_global_zoom(self, delta: int):
        new_ui = max(9, min(18, self.a11y.ui_font_size + delta))
        new_txt = max(9, min(24, self.a11y.text_font_size + delta))
        if new_ui == self.a11y.ui_font_size and new_txt == self.a11y.text_font_size:
            return
        self.a11y.ui_font_size = new_ui
        self.a11y.text_font_size = new_txt
        self.text_font_size = new_txt
        self.zoom_pct_var.set(f"{self.a11y.zoom_percent}%")
        self._refresh_all_themes_and_fonts()

    def _reset_global_zoom(self):
        self.a11y.ui_font_size = 10
        self.a11y.text_font_size = 11
        self.text_font_size = 11
        self.zoom_pct_var.set(f"{self.a11y.zoom_percent}%")
        self._refresh_all_themes_and_fonts()

    def _refresh_all_themes_and_fonts(self, save_prefs: bool = True):
        """Reaplica colores, fuentes, interlineado, iconos y geometría elástica en caliente."""
        self._apply_os_theme_and_fonts()
        p = self.palette
        fam = self._get_ui_font_family()

        if hasattr(self, "scroll_root"):
            self.scroll_root.set_background(p["bg"])

        for lbl, role, sdelta, bold, italic, underline, _wrap in self._tracked_labels:
            self._apply_single_label_style(lbl, role, sdelta, bold, italic, underline)

        for entry_w, sdelta in self._scaled_entries:
            try:
                entry_w.configure(font=self._get_font_tuple(size_delta=sdelta))
            except Exception:
                pass

        for lb in self._scaled_listboxes:
            try:
                lb.configure(
                    font=self._get_font_tuple(size_delta=-1),
                    bg=p["input_bg"],
                    fg=p["input_fg"],
                    selectbackground=p["accent"],
                    selectforeground=p["bg"],
                )
            except Exception:
                pass

        extra_sp = (4, 3, 6) if self.a11y.dyslexia_friendly else (1, 1, 2)
        for widget, is_mono in self._zoomable_texts:
            try:
                eff_fam = self._get_text_font_family(prefer_mono=is_mono)
                widget.configure(
                    font=(eff_fam, self.text_font_size),
                    bg=p["input_bg"],
                    fg=p["input_fg"],
                    insertbackground=p["input_fg"],
                    selectbackground=p["accent"],
                    selectforeground=p["bg"],
                    spacing1=extra_sp[0],
                    spacing2=extra_sp[1],
                    spacing3=extra_sp[2],
                    highlightcolor=p["focus_ring"],
                    highlightbackground=p["muted"],
                )
                if widget is getattr(self, "chat_history_text", None):
                    widget.tag_configure("user_lbl", font=(fam, self.text_font_size, "bold"), foreground=p["accent"])
                    widget.tag_configure("ai_lbl", font=(fam, self.text_font_size, "bold"), foreground=p["ok"])
                    widget.tag_configure(
                        "ref_lbl",
                        font=(fam, max(9, self.text_font_size - 1), "bold"),
                        foreground=p["warn"],
                    )
                    widget.tag_configure(
                        "ref_body",
                        font=(self._get_text_font_family(prefer_mono=True), max(9, self.text_font_size - 1)),
                        foreground=p["muted"],
                    )
            except Exception:
                pass

        if hasattr(self, "drop_canvas"):
            if self._has_input_file_loaded:
                self.drop_canvas.configure(bg=p["drop_bg"], highlightbackground=p["ok"])
                self.drop_canvas.itemconfigure(
                    self.drop_text_id,
                    fill=p["ok"],
                    font=self._get_font_tuple(size_delta=-1, bold=True),
                )
            else:
                self.drop_canvas.configure(bg=p["drop_bg"], highlightbackground=p["drop_border"])
                self.drop_canvas.itemconfigure(
                    self.drop_text_id,
                    fill=p["accent"],
                    font=self._get_font_tuple(size_delta=-1, italic=True),
                )

        # Regenerar iconos proporcionales a la escala actual
        icon_px, logo_px = self._calc_icon_sizes()
        new_icons = _build_supersampled_ui_icons(self.root, self.is_dark_mode, size=icon_px, logo_size=logo_px)
        self._apply_icon_refs(new_icons)
        self._ui_icons = new_icons

        if save_prefs:
            try:
                self.a11y.save()
            except Exception:
                pass

        self.root.after_idle(self._relayout_responsive_containers)

    def _apply_icon_refs(self, icons: dict):
        mapping = [
            ("header_logo_lbl", "logo"),
            ("btn_accessibility", "accessibility"),
            ("btn_tts_read", "tts_speak"),
            ("btn_tts_stop", "tts_stop"),
            ("btn_ai_easy_read", "easy_read"),
            ("btn_github", "github"),
            ("btn_legal", "legal"),
            ("btn_update", "update"),
            ("btn_reinstall", "reinstall"),
            ("btn_cache", "cache"),
            ("btn_clear_logs", "clear_logs"),
            ("btn_view_logs", "view_logs"),
        ]
        for attr, key in mapping:
            w = getattr(self, attr, None)
            ic = icons.get(key)
            if w is not None and ic is not None:
                try:
                    w.configure(image=ic)
                except Exception:
                    pass
        tab_map = [
            ("tab_convert", "tab_convert"),
            ("tab_translate", "tab_translate"),
            ("tab_chat", "tab_chat"),
            ("tab_ai", "tab_ai"),
            ("tab_anonymize", "tab_anonymize"),
            ("tab_pdf_tools", "tab_pdf_tools"),
        ]
        if hasattr(self, "notebook"):
            for attr, key in tab_map:
                tab_w = getattr(self, attr, None)
                ic = icons.get(key)
                if tab_w is not None and ic is not None:
                    try:
                        self.notebook.tab(tab_w, image=ic)
                    except Exception:
                        pass

    def _apply_window_icon(self):
        """Aplica el icono de Open OCReader (.ico en Windows, .png en Linux/macOS)."""
        ico_dir = _resolve_ico_dir()
        if not ico_dir:
            return

        ico_file = ico_dir / "Open_OCReader.ico"
        png_file = ico_dir / "Open_OCReader.png"

        try:
            if sys.platform == "win32" and ico_file.exists():
                self.root.iconbitmap(str(ico_file))
            elif png_file.exists():
                self._window_icon_ref = tk.PhotoImage(file=str(png_file))
                self.root.iconphoto(True, self._window_icon_ref)
        except Exception as e:
            logger.warning(f"No se pudo cargar el icono de ventana: {e}")

    def _icon_kwargs(self, key: str) -> dict:
        ic = self._ui_icons.get(key)
        return {"image": ic, "compound": tk.LEFT} if ic is not None else {}

    def _tab_label(self, key: str) -> str:
        raw = _strip_leading_emoji(tr(self.ui_lang, key)).strip()
        return f" {raw} "

    def _register_radio_grid(self, parent_frame: ttk.Frame, radios: list[ttk.Radiobutton]):
        parent_frame.columnconfigure(0, weight=1)
        parent_frame.columnconfigure(1, weight=1)
        self._radio_grid_groups.append((parent_frame, radios))
        self._reflow_single_radio_grid(parent_frame, radios)

    def _reflow_single_radio_grid(self, grid_frame: ttk.Frame, radios: list[ttk.Radiobutton]):
        avail_w = grid_frame.winfo_width()
        if avail_w <= 40:
            avail_w = max(600, self.root.winfo_width() - 80)
        max_rb_w = max((rb.winfo_reqwidth() for rb in radios), default=240)
        cols = 2 if (max_rb_w * 2 + 48 <= avail_w and self.a11y.ui_font_size < 15) else 1
        for idx, rb in enumerate(radios):
            r = idx // cols
            c = idx % cols
            rb.grid(row=r, column=c, sticky="w", padx=(4, 14), pady=2 if self.a11y.large_targets else 1)

    def _relayout_header(self):
        if not hasattr(self, "header_frame"):
            return
        w = self.header_frame.winfo_width()
        if w <= 40:
            w = max(720, self.root.winfo_width() - 32)
        brand_w = max(340, self.brand_col.winfo_reqwidth())
        # En pantallas anchas con fuente <= 11pt dejamos barra a la derecha; si no, apilamos limpia debajo
        min_tools_area = 460 if self.a11y.ui_font_size <= 11 else 540
        stacked = (w - brand_w - 20) < min_tools_area or self.a11y.ui_font_size >= 13
        if stacked != self._header_stacked:
            self._header_stacked = stacked
            self.brand_col.grid_forget()
            self.tools_flow.grid_forget()
            if stacked:
                self.header_frame.columnconfigure(0, weight=1)
                self.header_frame.columnconfigure(1, weight=0)
                self.brand_col.grid(row=0, column=0, sticky="w", pady=(0, 4))
                self.tools_flow.set_align("left")
                self.tools_flow.grid(row=1, column=0, sticky="ew")
            else:
                self.header_frame.columnconfigure(0, weight=0)
                self.header_frame.columnconfigure(1, weight=1)
                self.brand_col.grid(row=0, column=0, sticky="nw", padx=(0, 12))
                self.tools_flow.set_align("right")
                self.tools_flow.grid(row=0, column=1, sticky="new")
        self.tools_flow.relayout(force=True)

    def _update_notebook_tab_labels(self):
        if not hasattr(self, "notebook"):
            return
        nb_w = self.notebook.winfo_width()
        if nb_w <= 40:
            nb_w = max(720, self.root.winfo_width() - 32)
        # Estimar ancho mínimo cómodo para etiquetas completas
        full_needed = int(780 * (self.a11y.ui_font_size / 10.0) * (1.12 if self.a11y.large_targets else 1.0))
        compact = nb_w < full_needed
        if (compact, self.ui_lang) != self._tabs_compact_mode:
            self._tabs_compact_mode = (compact, self.ui_lang)
            suffix = "_short" if compact else ""
            pairs = [
                ("tab_convert", f"tab_convert{suffix}"),
                ("tab_translate", f"tab_translate{suffix}"),
                ("tab_chat", f"tab_chat{suffix}"),
                ("tab_ai", f"tab_ai{suffix}"),
                ("tab_anonymize", f"tab_anonymize{suffix}"),
                ("tab_pdf_tools", f"tab_pdf_tools{suffix}"),
            ]
            for attr, key in pairs:
                tab_w = getattr(self, attr, None)
                if tab_w is not None:
                    try:
                        self.notebook.tab(tab_w, text=self._tab_label(key))
                    except Exception:
                        pass

    def _update_wrapping_labels(self):
        base_w = self.root.winfo_width()
        if base_w <= 80:
            base_w = 900
        for lbl in self._wrapping_labels:
            try:
                pw = lbl.master.winfo_width()
                eff_w = pw if pw > 120 else base_w - 48
                if lbl is getattr(self, "subtitle_lbl", None):
                    target = max(280, min(680, eff_w - 20))
                elif lbl is getattr(self, "footer_lbl", None):
                    target = max(280, base_w - 230)
                else:
                    target = max(240, eff_w - 24)
                lbl.configure(wraplength=target)
            except Exception:
                pass

    def _relayout_responsive_containers(self):
        self._resize_job = None
        try:
            self.root.update_idletasks()
        except Exception:
            return
        self._relayout_header()
        for ff in self._flow_frames:
            try:
                ff.relayout(force=True)
            except Exception:
                pass
        for gf, rbs in self._radio_grid_groups:
            try:
                self._reflow_single_radio_grid(gf, rbs)
            except Exception:
                pass
        self._update_notebook_tab_labels()
        self._update_wrapping_labels()
        if hasattr(self, "drop_canvas"):
            cw = self.drop_canvas.winfo_width()
            if cw > 40:
                self._layout_drop_canvas(cw)
        if hasattr(self, "scroll_root"):
            self.scroll_root.sync_scrollregion()

    def _on_root_configure(self, event):
        if event.widget is not self.root:
            return
        cur = (event.width, event.height)
        if cur == self._last_root_size:
            return
        self._last_root_size = cur
        if self._resize_job is not None:
            try:
                self.root.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self.root.after(45, self._relayout_responsive_containers)

    def _build_ui(self):
        self.scroll_root = VerticalScrollableFrame(self.root, bg=self.palette["bg"])
        self.scroll_root.pack(fill=tk.BOTH, expand=True)

        main_frame = ttk.Frame(self.scroll_root.inner, padding="10 8 10 8")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Cabecera común responsiva: marca a la izquierda y barra de herramientas fluida (nunca recorta botones)
        self.header_frame = ttk.Frame(main_frame)
        self.header_frame.pack(fill=tk.X, pady=(0, 6))

        self.brand_col = ttk.Frame(self.header_frame)
        brand_top = ttk.Frame(self.brand_col)
        brand_top.pack(anchor="w")
        logo_ic = self._ui_icons.get("logo")
        if logo_ic is not None:
            self.header_logo_lbl = ttk.Label(brand_top, image=logo_ic)
            self.header_logo_lbl.pack(side=tk.LEFT, padx=(0, 8))
        title_lbl = ttk.Label(brand_top, text="Open OCReader")
        self._track_label(title_lbl, role="fg", size_delta=6, bold=True)
        title_lbl.pack(side=tk.LEFT)

        self.subtitle_lbl = ttk.Label(self.brand_col, text=tr(self.ui_lang, "subtitle"))
        self._track_label(self.subtitle_lbl, role="muted", size_delta=-2, wrap=True)
        self.subtitle_lbl.pack(anchor="w", pady=(2, 0))

        self.tools_flow = ResponsiveFlowFrame(self.header_frame, align="right", hgap=5, vgap=4)
        self._flow_frames.append(self.tools_flow)

        self.lang_combo = ttk.Combobox(
            self.tools_flow,
            textvariable=self.ui_lang_var,
            values=[name for _code, name in SUPPORTED_UI_LANGUAGES],
            state="readonly",
            width=9,
        )
        self.lang_combo.bind("<<ComboboxSelected>>", self._on_ui_language_changed)
        self._register_scaled_entry(self.lang_combo, size_delta=0)
        self.tools_flow.add_item(self.lang_combo)

        self.btn_accessibility = ttk.Button(
            self.tools_flow,
            text=_strip_leading_emoji(tr(self.ui_lang, "btn_accessibility")).strip(),
            command=self._open_accessibility_dialog,
            **self._icon_kwargs("accessibility"),
        )
        self.tools_flow.add_item(self.btn_accessibility)

        zoom_group = ttk.Frame(self.tools_flow)
        ttk.Button(zoom_group, text="A-", width=3, command=lambda: self._adjust_global_zoom(-1)).pack(side=tk.LEFT, padx=(0, 1))
        ttk.Button(zoom_group, textvariable=self.zoom_pct_var, width=5, command=self._reset_global_zoom).pack(side=tk.LEFT, padx=1)
        ttk.Button(zoom_group, text="A+", width=3, command=lambda: self._adjust_global_zoom(1)).pack(side=tk.LEFT, padx=(1, 0))
        self.tools_flow.add_item(zoom_group)

        tts_group = ttk.Frame(self.tools_flow)
        self.btn_tts_read = ttk.Button(
            tts_group,
            text=_strip_leading_emoji(tr(self.ui_lang, "btn_tts_read")).strip(),
            command=self._speak_active_output,
            **self._icon_kwargs("tts_speak"),
        )
        self.btn_tts_read.pack(side=tk.LEFT, padx=(0, 2))
        self.btn_tts_stop = ttk.Button(
            tts_group,
            text="",
            width=3,
            command=self._stop_tts,
            **self._icon_kwargs("tts_stop"),
        )
        self.btn_tts_stop.pack(side=tk.LEFT)
        self.tools_flow.add_item(tts_group)

        self.btn_github = ttk.Button(
            self.tools_flow,
            text=_strip_leading_emoji(tr(self.ui_lang, "btn_github")).strip(),
            command=lambda: webbrowser.open(GITHUB_REPO_URL),
            **self._icon_kwargs("github"),
        )
        self.tools_flow.add_item(self.btn_github)

        self.btn_legal = ttk.Button(
            self.tools_flow,
            text=_strip_leading_emoji(tr(self.ui_lang, "btn_legal")).strip(),
            command=self._show_legal_compliance,
            **self._icon_kwargs("legal"),
        )
        self.tools_flow.add_item(self.btn_legal)

        self.btn_update = ttk.Button(
            self.tools_flow,
            text=_strip_leading_emoji(tr(self.ui_lang, "btn_update")).strip(),
            command=self._check_updates_gui,
            **self._icon_kwargs("update"),
        )
        self.tools_flow.add_item(self.btn_update)

        self.btn_reinstall = ttk.Button(
            self.tools_flow,
            text=_strip_leading_emoji(tr(self.ui_lang, "btn_reinstall")).strip(),
            command=self._open_clean_reinstall_dialog,
            **self._icon_kwargs("reinstall"),
        )
        self.tools_flow.add_item(self.btn_reinstall)

        self.btn_cache = ttk.Button(
            self.tools_flow,
            text=_strip_leading_emoji(tr(self.ui_lang, "btn_cache")).strip(),
            command=self._clear_cache_gui,
            **self._icon_kwargs("cache"),
        )
        self.tools_flow.add_item(self.btn_cache)

        self.btn_clear_logs = ttk.Button(
            self.tools_flow,
            text=_strip_leading_emoji(tr(self.ui_lang, "btn_clear_logs")).strip(),
            command=self._clear_logs_gui,
            **self._icon_kwargs("clear_logs"),
        )
        self.tools_flow.add_item(self.btn_clear_logs)

        self.btn_view_logs = ttk.Button(
            self.tools_flow,
            text=_strip_leading_emoji(tr(self.ui_lang, "btn_view_logs")).strip(),
            command=self._open_logs,
            **self._icon_kwargs("view_logs"),
        )
        self.tools_flow.add_item(self.btn_view_logs)

        # Selector de fichero común en la parte superior
        self.drop_frame = ttk.LabelFrame(main_frame, text=tr(self.ui_lang, "input_group"), padding="6")
        self.drop_frame.pack(fill=tk.X, pady=(0, 6))

        self.drop_canvas = tk.Canvas(
            self.drop_frame,
            bg=self.palette["drop_bg"],
            height=34,
            highlightthickness=1,
            highlightbackground=self.palette["drop_border"],
            relief="flat",
            takefocus=1,
        )
        self.drop_canvas.pack(fill=tk.X, pady=(0, 4))

        self.drop_text_id = self.drop_canvas.create_text(
            350,
            17,
            text=tr(self.ui_lang, "drop_prompt"),
            font=self._get_font_tuple(size_delta=-1, italic=True),
            fill=self.palette["accent"],
            justify="center",
            width=660,
        )
        self.drop_canvas.bind("<Configure>", self._center_drop_text)
        self.drop_canvas.bind("<Button-1>", lambda e: self._browse_input())
        self.drop_canvas.bind("<Return>", lambda e: self._browse_input())
        self.drop_canvas.bind("<space>", lambda e: self._browse_input())

        entry_row = ttk.Frame(self.drop_frame)
        entry_row.pack(fill=tk.X)

        self.input_entry = ttk.Entry(entry_row, textvariable=self.input_path_var)
        self._register_scaled_entry(self.input_entry, size_delta=-1)
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        self.btn_paste = ttk.Button(entry_row, text=tr(self.ui_lang, "btn_paste"), command=self._paste_from_clipboard)
        self.btn_paste.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_browse = ttk.Button(entry_row, text=tr(self.ui_lang, "btn_browse"), command=self._browse_input)
        self.btn_browse.pack(side=tk.RIGHT)

        # Comprobación rápida de entorno portable / hardware distinto (equipos sin Internet / intranet)
        try:
            from .ai.runtime_manager import LlamaRuntimeManager
            mismatch_msg = LlamaRuntimeManager.get_instance().check_portable_hardware_mismatch()
            if mismatch_msg:
                lbl_mm = ttk.Label(main_frame, text=mismatch_msg)
                self._track_label(lbl_mm, role="warn", size_delta=-2, bold=True, wrap=True)
                lbl_mm.pack(anchor="w", pady=(0, 4))
        except Exception:
            pass

        # Pestañas (Notebook) adaptadas al hardware — etiquetas elásticas sin recortes
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.tab_convert = ttk.Frame(self.notebook, padding="8")
        self.tab_translate = ttk.Frame(self.notebook, padding="8")
        self.tab_chat = ttk.Frame(self.notebook, padding="8")
        self.tab_ai = ttk.Frame(self.notebook, padding="8")
        self.tab_anonymize = ttk.Frame(self.notebook, padding="8")
        self.pdf_tools_disabled = os.environ.get("OPEN_OCREADER_DISABLE_PDF_TOOLS", "").strip().lower() in {"1", "true", "yes"}
        self.tab_pdf_tools = ttk.Frame(self.notebook, padding="8") if not self.pdf_tools_disabled else None

        self.notebook.add(
            self.tab_convert,
            text=self._tab_label("tab_convert"),
            **self._icon_kwargs("tab_convert"),
        )
        self.notebook.add(
            self.tab_translate,
            text=self._tab_label("tab_translate"),
            **self._icon_kwargs("tab_translate"),
        )
        self.notebook.add(
            self.tab_chat,
            text=self._tab_label("tab_chat"),
            **self._icon_kwargs("tab_chat"),
        )
        self.notebook.add(
            self.tab_ai,
            text=self._tab_label("tab_ai"),
            **self._icon_kwargs("tab_ai"),
        )
        self.notebook.add(
            self.tab_anonymize,
            text=self._tab_label("tab_anonymize"),
            **self._icon_kwargs("tab_anonymize"),
        )
        if self.tab_pdf_tools is not None:
            self.notebook.add(
                self.tab_pdf_tools,
                text=self._tab_label("tab_pdf_tools"),
                **self._icon_kwargs("tab_pdf_tools"),
            )

        self._build_convert_tab()
        self._build_translate_tab()
        self._build_chat_tab()
        self._build_ai_tab()
        self._build_anonymize_tab()
        if self.tab_pdf_tools is not None:
            self._build_pdf_tools_tab()

        # Pie informativo permanente: licencia libre, aviso normativo de IA y enlace GitHub
        footer_bar = ttk.Frame(main_frame)
        footer_bar.pack(fill=tk.X, pady=(6, 0))

        self.footer_lbl = ttk.Label(footer_bar, text=tr(self.ui_lang, "footer"))
        self._track_label(self.footer_lbl, role="muted", size_delta=-2, wrap=True)
        self.footer_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        github_link = ttk.Label(footer_bar, text="GitHub: Ydalgo/Open-OCReader", cursor="hand2")
        self._track_label(github_link, role="accent", size_delta=-2, underline=True)
        github_link.pack(side=tk.RIGHT, padx=(8, 0))
        github_link.bind("<Button-1>", lambda e: webbrowser.open(GITHUB_REPO_URL))

    def _make_flow_row(self, parent: tk.Misc, align: str = "left", hgap: int = 8, vgap: int = 4) -> ResponsiveFlowFrame:
        ff = ResponsiveFlowFrame(parent, align=align, hgap=hgap, vgap=vgap)
        self._flow_frames.append(ff)
        return ff

    def _build_convert_tab(self):
        # Formato de salida elástico (2 columnas en ancho normal, 1 columna en pantallas estrechas o zoom alto)
        self.format_group = ttk.LabelFrame(self.tab_convert, text=tr(self.ui_lang, "format_group"), padding="6")
        self.format_group.pack(fill=tk.X, pady=(0, 5))

        grid_frame = ttk.Frame(self.format_group)
        grid_frame.pack(fill=tk.X)

        self.format_widgets = {}
        conv_radios = []
        for _label_text, fmt_key, _desc in self.FORMAT_OPTIONS:
            lbl_txt, _desc_txt = tr(self.ui_lang, f"fmt_{fmt_key}")
            rb = ttk.Radiobutton(
                grid_frame,
                text=lbl_txt,
                value=fmt_key,
                variable=self.format_var,
                command=self._on_format_changed,
            )
            self.format_widgets[fmt_key] = (rb, None)
            conv_radios.append(rb)
        self._register_radio_grid(grid_frame, conv_radios)

        # Banda descriptiva dinámica del formato seleccionado
        fmt_desc_lbl = ttk.Label(self.format_group, textvariable=self.format_desc_var)
        self._track_label(fmt_desc_lbl, role="accent", size_delta=-2, italic=True, wrap=True)
        fmt_desc_lbl.pack(anchor="w", fill=tk.X, padx=(4, 4), pady=(3, 0))

        # Opciones de OCR inteligente, compresión PDF y escala de grises (flujo adaptativo sin recortes)
        pdf_opts = ttk.LabelFrame(self.tab_convert, text=" Opciones de OCR y optimización PDF ", padding="6")
        pdf_opts.pack(fill=tk.X, pady=(0, 5))

        opts_row1 = self._make_flow_row(pdf_opts, hgap=14, vgap=4)
        opts_row1.pack(fill=tk.X)
        opts_row1.add_item(
            ttk.Checkbutton(
                opts_row1,
                text="Forzar OCR (re-escanear aunque el PDF ya tenga texto buscable)",
                variable=self.force_ocr_var,
            )
        )
        opts_row1.add_item(
            ttk.Checkbutton(
                opts_row1,
                text="Escala de grises (blanco y negro)",
                variable=self.grayscale_var,
            )
        )

        opts_row2 = self._make_flow_row(pdf_opts, hgap=8, vgap=4)
        opts_row2.pack(fill=tk.X, pady=(4, 0))
        opts_row2.add_item(ttk.Label(opts_row2, text="Compresión PDF / PDF-A:"))
        conv_comp_cb = ttk.Combobox(
            opts_row2,
            textvariable=self.compression_var,
            values=[lbl for lbl, _code in self.COMPRESSION_LABELS],
            state="readonly",
            width=26,
        )
        self._register_scaled_entry(conv_comp_cb, size_delta=-1)
        opts_row2.add_item(conv_comp_cb)
        hint_ocr_lbl = ttk.Label(opts_row2, text="(PDF ya buscable: omite OCR automáticamente)")
        self._track_label(hint_ocr_lbl, role="ok", size_delta=-2)
        opts_row2.add_item(hint_ocr_lbl)

        # Destino
        self.output_group = ttk.LabelFrame(self.tab_convert, text=tr(self.ui_lang, "output_group"), padding="6")
        self.output_group.pack(fill=tk.X, pady=(0, 6))

        output_entry_frame = ttk.Frame(self.output_group)
        output_entry_frame.pack(fill=tk.X)

        out_entry = ttk.Entry(output_entry_frame, textvariable=self.output_path_var)
        self._register_scaled_entry(out_entry, size_delta=-1)
        out_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.btn_save_as = ttk.Button(output_entry_frame, text=tr(self.ui_lang, "btn_save_as"), command=self._browse_output)
        self.btn_save_as.pack(side=tk.RIGHT)

        # Botón convertir
        self.btn_convert = ttk.Button(
            self.tab_convert,
            text=tr(self.ui_lang, "btn_convert"),
            command=self._start_conversion,
        )
        self.btn_convert.pack(fill=tk.X, ipady=4, pady=(2, 4))

        self.progress_bar = ttk.Progressbar(self.tab_convert, mode="indeterminate")
        self.progress_bar.pack(fill=tk.X, pady=(0, 4))

        conv_status_lbl = ttk.Label(self.tab_convert, textvariable=self.status_var)
        self._track_label(conv_status_lbl, role="fg", size_delta=-1, wrap=True)
        conv_status_lbl.pack(anchor="w", fill=tk.X)

        post_frame = self._make_flow_row(self.tab_convert, hgap=8, vgap=4)
        post_frame.pack(fill=tk.X, pady=(6, 0))

        self.btn_open_file = ttk.Button(post_frame, text=tr(self.ui_lang, "btn_open_file"), command=self._open_file, state=tk.DISABLED)
        post_frame.add_item(self.btn_open_file)

        self.btn_open_folder = ttk.Button(post_frame, text=tr(self.ui_lang, "btn_open_folder"), command=self._open_folder, state=tk.DISABLED)
        post_frame.add_item(self.btn_open_folder)

    def _render_hardware_locked_notice(self, parent, section_title: str, features: list):
        """Muestra un aviso claro y limpio cuando el hardware no alcanza los requisitos de una función IA."""
        box = ttk.LabelFrame(parent, text=f" 💻 {section_title} — Hardware insuficiente ", padding="16")
        box.pack(fill=tk.BOTH, expand=True, pady=12)

        hw_lbl = ttk.Label(
            box,
            text=f"Equipo detectado: {self.hw.ram_total_gb:.1f} GB RAM | {self.hw.cpu_cores} núcleos | {self.hw.backend.upper()}",
        )
        self._track_label(hw_lbl, role="warn", size_delta=-1, bold=True, wrap=True)
        hw_lbl.pack(anchor="w", fill=tk.X, pady=(0, 8))

        desc_lbl = ttk.Label(
            box,
            text="Con un hardware más potente (≥6 GB de RAM, recomendado ≥10–16 GB RAM o GPU Vulkan/Metal), "
                 "se desbloquearían automáticamente las siguientes funciones locales:",
        )
        self._track_label(desc_lbl, role="fg", size_delta=-1, wrap=True)
        desc_lbl.pack(anchor="w", fill=tk.X, pady=(0, 8))

        for feat in features:
            f_lbl = ttk.Label(box, text=f"  • {feat}")
            self._track_label(f_lbl, role="muted", size_delta=-1, wrap=True)
            f_lbl.pack(anchor="w", fill=tk.X, pady=2)

        foot_lbl = ttk.Label(
            box,
            text="Mientras tanto, puedes utilizar con total normalidad la Conversión Estructural (10 formatos), "
                 "el Anonimizador RGPD 100% Python y las Herramientas PDF.",
        )
        self._track_label(foot_lbl, role="ok", size_delta=-2, italic=True, wrap=True)
        foot_lbl.pack(anchor="w", fill=tk.X, pady=(12, 0))

    # ---------------- PESTAÑA 1B: TRADUCIR DOCUMENTO ----------------
    def _build_translate_tab(self):
        if not self.ai_tier.vlm_enabled:
            self._render_hardware_locked_notice(
                self.tab_translate,
                "Traducción Fiel de Documentos a Fichero",
                [
                    "Traducción contextual completa directa a PDF, PDF/A-2b, Word (.docx), ODT y eBook (.epub).",
                    "Preservación de fondos, colores, logotipos e imágenes originales mediante inpainting IA.",
                    "Soporte multilingüe 100% offline (Español, English, Svenska, Français, Deutsch, etc.).",
                ],
            )
            return

        # 1. Idiomas origen y destino
        lang_grp = ttk.LabelFrame(self.tab_translate, text=" 🌐 Idiomas de traducción contextual ", padding="6")
        lang_grp.pack(fill=tk.X, pady=(0, 5))

        lang_row = self._make_flow_row(lang_grp, hgap=8, vgap=4)
        lang_row.pack(fill=tk.X)

        lang_row.add_item(ttk.Label(lang_row, text="Idioma origen:"))
        self.trans_src_combo = ttk.Combobox(
            lang_row,
            textvariable=self.trans_source_lang_var,
            values=["Auto-detectar"] + TRANSLATION_TARGET_LANGUAGES,
            width=16,
        )
        self._register_scaled_entry(self.trans_src_combo, size_delta=-1)
        lang_row.add_item(self.trans_src_combo)

        lang_row.add_item(ttk.Label(lang_row, text="Idioma destino:"))
        self.trans_dst_combo = ttk.Combobox(
            lang_row,
            textvariable=self.trans_target_lang_var,
            values=TRANSLATION_TARGET_LANGUAGES,
            width=16,
        )
        self._register_scaled_entry(self.trans_dst_combo, size_delta=-1)
        self.trans_dst_combo.bind("<<ComboboxSelected>>", lambda e: self._update_default_translate_output())
        lang_row.add_item(self.trans_dst_combo)

        t_hint_lbl = ttk.Label(lang_row, text="Traducción contextual con Qwen3-VL y Prompt Madre")
        self._track_label(t_hint_lbl, role="ok", size_delta=-2, italic=True)
        lang_row.add_item(t_hint_lbl)

        # 2. Selector de formato traducido (1 o 2 columnas elásticas)
        fmt_grp = ttk.LabelFrame(self.tab_translate, text=" 📁 Formato del documento traducido ", padding="6")
        fmt_grp.pack(fill=tk.X, pady=(0, 5))

        grid_f = ttk.Frame(fmt_grp)
        grid_f.pack(fill=tk.X)

        trans_radios = []
        for _lbl, fmt_key, _desc in self.FORMAT_OPTIONS:
            lbl_txt, _desc_txt = tr(self.ui_lang, f"fmt_{fmt_key}")
            rb = ttk.Radiobutton(
                grid_f,
                text=lbl_txt,
                value=fmt_key,
                variable=self.trans_format_var,
                command=self._on_trans_format_changed,
            )
            trans_radios.append(rb)
        self._register_radio_grid(grid_f, trans_radios)

        trans_desc_lbl = ttk.Label(fmt_grp, textvariable=self.trans_format_desc_var)
        self._track_label(trans_desc_lbl, role="accent", size_delta=-2, italic=True, wrap=True)
        trans_desc_lbl.pack(anchor="w", fill=tk.X, padx=(4, 4), pady=(3, 0))

        # 3. Opciones de maquetación, color, imagen y OCR
        vis_grp = ttk.LabelFrame(self.tab_translate, text=" 🎨 Maquetación y optimización de color e imagen ", padding="6")
        vis_grp.pack(fill=tk.X, pady=(0, 5))

        r1 = self._make_flow_row(vis_grp, hgap=14, vgap=4)
        r1.pack(fill=tk.X)
        r1.add_item(
            ttk.Checkbutton(
                r1,
                text="Preservar diseño visual, colores, fondos e imágenes (Inpainting)",
                variable=self.trans_preserve_layout_var,
            )
        )
        r1.add_item(
            ttk.Checkbutton(
                r1,
                text="Escala de grises (blanco y negro)",
                variable=self.trans_grayscale_var,
            )
        )

        r2 = self._make_flow_row(vis_grp, hgap=10, vgap=4)
        r2.pack(fill=tk.X, pady=(4, 0))
        r2.add_item(
            ttk.Checkbutton(
                r2,
                text="Forzar OCR (re-escanear)",
                variable=self.trans_force_ocr_var,
            )
        )
        r2.add_item(
            ttk.Checkbutton(
                r2,
                text="Modo letra manuscrita (Visión)",
                variable=self.trans_handwriting_var,
            )
        )
        r2.add_item(ttk.Label(r2, text="Compresión:"))
        trans_comp_cb = ttk.Combobox(
            r2,
            textvariable=self.trans_compression_var,
            values=[lbl for lbl, _code in self.COMPRESSION_LABELS],
            state="readonly",
            width=24,
        )
        self._register_scaled_entry(trans_comp_cb, size_delta=-1)
        r2.add_item(trans_comp_cb)

        # 4. Fichero de salida traducido
        out_grp = ttk.LabelFrame(self.tab_translate, text=" 💾 Fichero traducido de salida ", padding="6")
        out_grp.pack(fill=tk.X, pady=(0, 6))

        out_row = ttk.Frame(out_grp)
        out_row.pack(fill=tk.X)
        trans_out_entry = ttk.Entry(out_row, textvariable=self.trans_output_path_var)
        self._register_scaled_entry(trans_out_entry, size_delta=-1)
        trans_out_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Button(out_row, text="Guardar como...", command=self._browse_translate_output).pack(side=tk.RIGHT)

        # 5. Botón principal, progreso y apertura rápida
        self.btn_translate_doc = ttk.Button(
            self.tab_translate,
            text="🌐  Traducir y Generar Documento",
            command=self._start_document_translation,
        )
        self.btn_translate_doc.pack(fill=tk.X, ipady=4, pady=(2, 4))

        self.trans_progress = ttk.Progressbar(self.tab_translate, mode="indeterminate")
        self.trans_progress.pack(fill=tk.X, pady=(0, 4))

        trans_status_lbl = ttk.Label(self.tab_translate, textvariable=self.trans_status_var)
        self._track_label(trans_status_lbl, role="fg", size_delta=-1, wrap=True)
        trans_status_lbl.pack(anchor="w", fill=tk.X)

        post_trans = self._make_flow_row(self.tab_translate, hgap=8, vgap=4)
        post_trans.pack(fill=tk.X, pady=(5, 0))
        self.btn_open_trans_file = ttk.Button(
            post_trans, text="📄 Abrir documento traducido", command=self._open_translated_file, state=tk.DISABLED
        )
        post_trans.add_item(self.btn_open_trans_file)
        self.btn_open_trans_folder = ttk.Button(
            post_trans, text="📁 Abrir carpeta", command=self._open_translated_folder, state=tk.DISABLED
        )
        post_trans.add_item(self.btn_open_trans_folder)

    def _on_trans_format_changed(self):
        fmt = self.trans_format_var.get()
        _lbl, desc_txt = tr(self.ui_lang, f"fmt_{fmt}")
        self.trans_format_desc_var.set(f"ℹ️ {desc_txt}")
        self._update_default_translate_output()

    def _update_default_translate_output(self):
        in_val = self.input_path_var.get().strip()
        if not in_val:
            return
        in_p = Path(in_val)
        fmt = self.trans_format_var.get()
        ext = "pdf" if fmt == "pdfa" else fmt
        tgt = self.trans_target_lang_var.get().strip() or "trad"
        lang_tag = "".join(c for c in tgt.lower() if c.isalnum())[:10] or "trad"
        self.trans_output_path_var.set(str(in_p.parent / f"{in_p.stem}_traducido_{lang_tag}.{ext}"))

    def _browse_translate_output(self):
        fmt = self.trans_format_var.get()
        ext = ".pdf" if fmt == "pdfa" else f".{fmt}"
        chosen = filedialog.asksaveasfilename(
            title="Guardar documento traducido como...",
            defaultextension=ext,
            filetypes=[(f"Fichero {fmt.upper()} (*{ext})", f"*{ext}"), ("Todos (*.*)", "*.*")],
        )
        if chosen:
            self.trans_output_path_var.set(chosen)

    def _start_document_translation(self):
        in_path = self.input_path_var.get().strip()
        if not in_path or not Path(in_path).exists():
            messagebox.showwarning("Aviso", "Selecciona primero un fichero de entrada arriba.")
            return

        from .ai import LlamaRuntimeManager
        runtime = LlamaRuntimeManager.get_instance()
        if not runtime.is_models_present():
            chosen_source = self._ask_model_download_source()
            if not chosen_source:
                return
            runtime.preferred_model_source = chosen_source

        out_path = self.trans_output_path_var.get().strip()
        if not out_path:
            self._update_default_translate_output()
            out_path = self.trans_output_path_var.get().strip()

        fmt = self.trans_format_var.get()
        target_lang = self.trans_target_lang_var.get().strip() or get_llm_language_name(self.ui_lang)
        raw_src = self.trans_source_lang_var.get().strip()
        source_lang = "auto" if (not raw_src or raw_src.lower().startswith("auto")) else raw_src
        preserve_layout = self.trans_preserve_layout_var.get()
        grayscale = self.trans_grayscale_var.get()
        force_ocr = self.trans_force_ocr_var.get()
        handwriting = self.trans_handwriting_var.get()
        comp_lbl = self.trans_compression_var.get()
        comp_code = next((c for lbl, c in self.COMPRESSION_LABELS if lbl == comp_lbl), "high")

        self.btn_translate_doc.config(state=tk.DISABLED)
        self.btn_open_trans_file.config(state=tk.DISABLED)
        self.btn_open_trans_folder.config(state=tk.DISABLED)
        self.trans_progress.start(10)
        self.trans_status_var.set(f"Iniciando traducción a '{target_lang}' ({fmt.upper()})...")

        def worker():
            try:
                converter = DocumentConverter()
                res = converter.translate_document(
                    input_path=in_path,
                    output_path=out_path,
                    output_format=fmt,
                    target_lang=target_lang,
                    source_lang=source_lang,
                    preserve_layout=preserve_layout,
                    pdf_compression=comp_code,
                    grayscale=grayscale,
                    force_ocr=force_ocr,
                    handwriting=handwriting,
                    verbose=False,
                    progress_cb=lambda m: self.root.after(0, self.trans_status_var.set, m),
                )

                def on_ok():
                    self.trans_progress.stop()
                    self.btn_translate_doc.config(state=tk.NORMAL)
                    self.last_translated_file = res.output_path
                    self.btn_open_trans_file.config(state=tk.NORMAL)
                    self.btn_open_trans_folder.config(state=tk.NORMAL)
                    msg = (
                        f"✓ Documento traducido ({res.total_pages} pág., {res.total_elements} bloques) "
                        f"en {res.elapsed_seconds:.2f}s → {Path(res.output_path).name}"
                    )
                    self.trans_status_var.set(msg)
                    self._announce(f"Traducción completada al {target_lang} en {Path(res.output_path).name}")

                self.root.after(0, on_ok)
            except Exception as e:
                logger.exception(f"Error en traducción directa de documento: {e}")

                def on_err(msg=str(e)):
                    self.trans_progress.stop()
                    self.btn_translate_doc.config(state=tk.NORMAL)
                    self.trans_status_var.set(f"Error en traducción: {msg}")
                    self._announce(f"Error en traducción: {msg}")
                    messagebox.showerror("Error al traducir documento", msg)

                self.root.after(0, on_err)

        threading.Thread(target=worker, daemon=True).start()

    def _open_translated_file(self):
        if self.last_translated_file and Path(self.last_translated_file).exists():
            self._open_path_crossplatform(self.last_translated_file)

    def _open_translated_folder(self):
        if self.last_translated_file:
            self._open_path_crossplatform(str(Path(self.last_translated_file).parent))

    # ---------------- PESTAÑA 2: CHAT MULTI-DOCUMENTO CON CITAS ----------------
    def _build_chat_tab(self):
        if not self.ai_tier.vlm_enabled:
            self._render_hardware_locked_notice(
                self.tab_chat,
                "Chat Multi-Documento con Citas",
                [
                    "Cargar múltiples PDFs e imágenes en una misma sesión de chat.",
                    "Búsqueda híbrida semántica (BGE-M3 + BM25 + Árbol AST) sin límite de páginas.",
                    "Respuestas justificadas con citas exactas [REF-N: archivo.pdf — Sección].",
                ],
            )
            return

        # Banda de hardware y límite recomendado
        tier = self.ai_tier
        info_txt = (
            f"💻 Perfil {tier.tier_name.upper()} ({self.hw.ram_total_gb:.1f} GB RAM) → "
            f"{tier.vlm_label} + {tier.embed_label} | Hasta {tier.max_chat_docs} documentos (sin límite de páginas vía AST)"
        )
        chat_hw_lbl = ttk.Label(self.tab_chat, text=info_txt)
        self._track_label(chat_hw_lbl, role="accent", size_delta=-2, bold=True, wrap=True)
        chat_hw_lbl.pack(anchor="w", fill=tk.X, pady=(0, 4))

        if tier.locked_features_hint:
            chat_hint_lbl = ttk.Label(self.tab_chat, text=f"ℹ️ {tier.locked_features_hint}")
            self._track_label(chat_hint_lbl, role="warn", size_delta=-2, italic=True, wrap=True)
            chat_hint_lbl.pack(anchor="w", fill=tk.X, pady=(0, 4))

        # Panel superior: documentos cargados, proyectos guardados y progreso de indexación
        docs_frame = ttk.LabelFrame(self.tab_chat, text=" 📚 Documentos y Proyectos de Chat ", padding="6")
        docs_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))

        list_row = ttk.Frame(docs_frame)
        list_row.pack(fill=tk.X)

        lb_container = ttk.Frame(list_row)
        lb_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        lb_scroll = ttk.Scrollbar(lb_container, orient=tk.VERTICAL)
        lb_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.chat_docs_listbox = tk.Listbox(
            lb_container,
            height=3,
            font=self._get_font_tuple(size_delta=-1),
            selectmode=tk.EXTENDED,
            yscrollcommand=lb_scroll.set,
            bg=self.palette["input_bg"],
            fg=self.palette["input_fg"],
            selectbackground=self.palette["accent"],
            selectforeground=self.palette["bg"],
        )
        self.chat_docs_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._scaled_listboxes.append(self.chat_docs_listbox)
        lb_scroll.config(command=self.chat_docs_listbox.yview)

        doc_btns = ttk.Frame(list_row)
        doc_btns.pack(side=tk.RIGHT, fill=tk.Y)
        row_b1 = ttk.Frame(doc_btns)
        row_b1.pack(fill=tk.X, pady=1)
        self.btn_chat_add = ttk.Button(row_b1, text="➕ Añadir archivos...", command=self._chat_add_files)
        self.btn_chat_add.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        self.btn_chat_add_top = ttk.Button(row_b1, text="📥 Archivo superior", command=self._chat_add_current)
        self.btn_chat_add_top.pack(side=tk.LEFT, fill=tk.X, expand=True)

        row_b2 = ttk.Frame(doc_btns)
        row_b2.pack(fill=tk.X, pady=1)
        self.btn_chat_save_proj = ttk.Button(row_b2, text="💾 Guardar proyecto", command=self._chat_save_project)
        self.btn_chat_save_proj.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        self.btn_chat_load_proj = ttk.Button(row_b2, text="📂 Cargar proyecto", command=self._chat_load_project)
        self.btn_chat_load_proj.pack(side=tk.LEFT, fill=tk.X, expand=True)

        row_b3 = ttk.Frame(doc_btns)
        row_b3.pack(fill=tk.X, pady=1)
        self.btn_chat_remove = ttk.Button(row_b3, text="🗑️ Quitar", command=self._chat_remove_selected)
        self.btn_chat_remove.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        self.btn_chat_clear = ttk.Button(row_b3, text="🧹 Nueva sesión", command=self._chat_clear)
        self.btn_chat_clear.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Progreso y contador SIEMPRE visibles dentro del panel de documentos
        self.chat_progress = ttk.Progressbar(docs_frame, mode="indeterminate")
        self.chat_progress.pack(fill=tk.X, pady=(6, 2))

        status_row = ttk.Frame(docs_frame)
        status_row.pack(fill=tk.X)
        chat_st_lbl = ttk.Label(status_row, textvariable=self.chat_status_var)
        self._track_label(chat_st_lbl, role="accent", size_delta=-1, bold=True, wrap=True)
        chat_st_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        chat_cnt_lbl = ttk.Label(status_row, textvariable=self.chat_count_var)
        self._track_label(chat_cnt_lbl, role="ok", size_delta=-1)
        chat_cnt_lbl.pack(side=tk.RIGHT, padx=(8, 0))

        # Barra inferior de pregunta EMPAQUETADA ANTES del historial (siempre visible en pantalla)
        input_bar = ttk.LabelFrame(self.tab_chat, text=" 💬 Preguntar a los documentos cargados (Ctrl+Rueda para Zoom) ", padding="6")
        input_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))

        ask_row = ttk.Frame(input_bar)
        ask_row.pack(fill=tk.X)

        self.chat_entry = ttk.Entry(ask_row, textvariable=self.chat_question_var)
        self._register_scaled_entry(self.chat_entry, size_delta=0)
        self.chat_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6), ipady=3)
        self.chat_entry.bind("<Return>", lambda e: self._chat_send())

        ttk.Button(ask_row, text="A-", width=3, command=lambda: self._adjust_global_zoom(-1)).pack(side=tk.LEFT, padx=1)
        ttk.Button(ask_row, text="A+", width=3, command=lambda: self._adjust_global_zoom(1)).pack(side=tk.LEFT, padx=(1, 6))

        self.btn_chat_send = ttk.Button(ask_row, text="💬 Enviar pregunta", command=self._chat_send)
        self.btn_chat_send.pack(side=tk.RIGHT, ipadx=8, ipady=2)

        export_row = self._make_flow_row(input_bar, hgap=6, vgap=4)
        export_row.pack(fill=tk.X, pady=(6, 0))
        export_row.add_item(ttk.Label(export_row, text="Exportar chat (citas literales):"))
        chat_exp_cb = ttk.Combobox(
            export_row,
            textvariable=self.chat_export_fmt_var,
            values=[lbl for lbl, _code in self.EXPORT_CONV_FORMATS],
            state="readonly",
            width=18,
        )
        self._register_scaled_entry(chat_exp_cb, size_delta=-1)
        export_row.add_item(chat_exp_cb)
        export_row.add_item(
            ttk.Button(
                export_row,
                text="📥 Exportar chat + citas",
                command=self._chat_export_conversation,
            )
        )
        export_row.add_item(
            ttk.Button(
                export_row,
                text="🔊 Leer respuesta",
                command=self._speak_active_output,
            )
        )
        export_row.add_item(
            ttk.Button(
                export_row,
                text="⏹️ Callar",
                command=self._stop_tts,
            )
        )

        # Historial de conversación con citas (ocupa el espacio central restante)
        chat_box_frame = ttk.Frame(self.tab_chat)
        chat_box_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        chat_scroll = ttk.Scrollbar(chat_box_frame)
        chat_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.chat_history_text = tk.Text(
            chat_box_frame,
            height=6,
            wrap=tk.WORD,
            yscrollcommand=chat_scroll.set,
            padx=10,
            pady=8,
            state=tk.DISABLED,
        )
        self.chat_history_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        chat_scroll.config(command=self.chat_history_text.yview)
        self._register_zoomable_text(self.chat_history_text, family="Segoe UI")

        fam = self._get_ui_font_family()
        mono_fam = self._get_text_font_family(prefer_mono=True)
        self.chat_history_text.tag_configure("user_lbl", font=(fam, self.text_font_size, "bold"), foreground=self.palette["accent"])
        self.chat_history_text.tag_configure("ai_lbl", font=(fam, self.text_font_size, "bold"), foreground=self.palette["ok"])
        self.chat_history_text.tag_configure("ref_lbl", font=(fam, max(9, self.text_font_size - 1), "bold"), foreground=self.palette["warn"])
        self.chat_history_text.tag_configure("ref_body", font=(mono_fam, max(9, self.text_font_size - 1)), foreground=self.palette["muted"])

    def _ensure_chat_engine(self):
        if self.chat_engine is None:
            from .ai.multi_doc_chat import MultiDocumentChat
            self.chat_engine = MultiDocumentChat()
        return self.chat_engine

    def _on_tab_changed(self, event=None):
        """Mantiene intacto el contenido, recalcula alturas elásticas y anuncia la pestaña si hay guía de voz."""
        try:
            self.root.update_idletasks()
            if hasattr(self, "chat_history_text"):
                self.chat_history_text.see(tk.END)
            if hasattr(self, "scroll_root"):
                self.scroll_root.sync_scrollregion()
            if self._ui_ready and self.a11y.voice_guidance and hasattr(self, "notebook"):
                sel = self.notebook.select()
                if sel:
                    tab_title = self.notebook.tab(sel, "text").strip()
                    if tab_title:
                        self._announce(f"Pestaña {tab_title}")
        except Exception:
            pass

    def _chat_append_message(self, tag_lbl: str, sender: str, text: str, refs=None):
        self.chat_history_text.config(state=tk.NORMAL)
        self.chat_history_text.insert(tk.END, f"{sender}:\n", tag_lbl)
        self.chat_history_text.insert(tk.END, f"{text}\n")
        if refs:
            self.chat_history_text.insert(tk.END, "📚 Referencias consultadas (con extracto literal original):\n", "ref_lbl")
            for r in refs:
                self.chat_history_text.insert(
                    tk.END,
                    f"  • [{r.doc_id} / {r.ref_id}] {r.file_name} — {r.section_path}\n",
                    "ref_body",
                )
                lit_preview = (getattr(r, "literal_text", "") or r.excerpt or "").strip().replace("\n", " ")
                if len(lit_preview) > 260:
                    lit_preview = lit_preview[:257] + "..."
                if lit_preview:
                    self.chat_history_text.insert(tk.END, f"      «{lit_preview}»\n", "ref_body")
        self.chat_history_text.insert(tk.END, "\n")
        self.chat_history_text.see(tk.END)
        self.chat_history_text.config(state=tk.DISABLED)

    def _export_turns_dialog(self, turns, fmt_label: str, default_stem: str, title: str, docs_summary=None):
        """Helper compartido para exportar conversaciones o consultas con citas literales al formato elegido."""
        from .formats.conversation_exporter import export_conversation_with_references

        fmt_code = next((c for lbl, c in self.EXPORT_CONV_FORMATS if lbl == fmt_label), "docx")
        ext = ".pdf" if fmt_code == "pdfa" else f".{fmt_code}"
        chosen = filedialog.asksaveasfilename(
            title=f"Exportar informe ({fmt_label})",
            initialfile=f"{default_stem}{ext}",
            defaultextension=ext,
            filetypes=[(f"{fmt_label} (*{ext})", f"*{ext}"), ("Todos (*.*)", "*.*")],
        )
        if not chosen:
            return None
        return export_conversation_with_references(
            turns=turns,
            output_path=chosen,
            output_format=fmt_code,
            title=title,
            documents_summary=docs_summary,
        )

    def _chat_export_conversation(self):
        if self.chat_engine is None or not getattr(self.chat_engine, "turn_records", None):
            messagebox.showinfo(
                "Sin conversación",
                "Realiza al menos una pregunta en el chat para poder exportar la conversación con sus citas literales.",
            )
            return
        try:
            doc_ids = self.chat_engine.get_document_id_map()
            docs_summary = [
                f"[{doc_ids[p]}] {fname} ({len(tree.nodos)} nodos AST)"
                for p, (fname, tree) in self.chat_engine.documents.items()
            ]
            out = self._export_turns_dialog(
                turns=self.chat_engine.turn_records,
                fmt_label=self.chat_export_fmt_var.get(),
                default_stem="Conversacion_Documentos_Referencias",
                title="Informe de Chat Multi-Documento y Referencias Literales — Open OCReader",
                docs_summary=docs_summary,
            )
            if out:
                self.chat_status_var.set(f"✓ Conversación y citas literales exportadas: {Path(out).name}")
                if messagebox.askyesno("Exportación completada", f"Archivo generado:\n{out}\n\n¿Deseas abrirlo ahora?"):
                    self._open_path_crossplatform(out)
        except Exception as e:
            logger.exception(f"Error exportando conversación: {e}")
            messagebox.showerror("Error al exportar", f"No se pudo exportar la conversación:\n{e}")

    def _chat_add_files(self):
        filetypes = [
            ("Documentos y capturas", "*.pdf;*.png;*.jpg;*.jpeg;*.tiff;*.tif;*.bmp;*.webp"),
            ("PDF (*.pdf)", "*.pdf"),
            ("Todos (*.*)", "*.*"),
        ]
        chosen = filedialog.askopenfilenames(title="Seleccionar documentos para chatear", filetypes=filetypes)
        if chosen:
            self._chat_index_paths(list(chosen))

    def _chat_add_current(self):
        in_p = self.input_path_var.get().strip()
        if not in_p or not Path(in_p).exists():
            messagebox.showwarning("Aviso", "Selecciona primero un fichero arriba.")
            return
        self._chat_index_paths([in_p])

    def _chat_index_paths(self, paths):
        self.btn_chat_add.config(state=tk.DISABLED)
        self.btn_chat_send.config(state=tk.DISABLED)
        self.chat_progress.start(10)
        self.chat_status_var.set(
            f"⏳ Cargando e indexando {len(paths)} archivo(s)... Ten paciencia, se guardarán en caché SHA-256."
        )

        def worker():
            eng = self._ensure_chat_engine()
            added_msgs = []
            errors = []
            total = len(paths)
            for idx, p in enumerate(paths, start=1):
                fname_short = Path(p).name
                self.root.after(
                    0,
                    self.chat_status_var.set,
                    f"⏳ Procesando archivo {idx}/{total}: '{fname_short}' (no cierres, indexando AST/BGE-M3)...",
                )
                try:
                    fname, n_nodes = eng.add_document(
                        p,
                        progress_cb=lambda m, i=idx, t=total: self.root.after(
                            0, self.chat_status_var.set, f"[{i}/{t}] {m}"
                        ),
                    )
                    added_msgs.append(f"{fname} ({n_nodes} nodos)")
                    self.root.after(0, self._refresh_chat_docs_ui)
                except Exception as e:
                    errors.append(f"{fname_short}: {e}")

            def done():
                self.chat_progress.stop()
                self.btn_chat_add.config(state=tk.NORMAL)
                self.btn_chat_send.config(state=tk.NORMAL)
                self._refresh_chat_docs_ui()
                if added_msgs:
                    self.chat_status_var.set(f"✓ Listos para chatear: {', '.join(added_msgs)}")
                    self._announce(f"Documentos indexados para chat: {', '.join(added_msgs)}")
                    self.chat_entry.focus_set()
                if errors:
                    messagebox.showwarning("Avisos al añadir documentos", "\n".join(errors))

            self.root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _chat_save_project(self):
        """Guarda la lista de documentos actual como proyecto reutilizable con verificación SHA-256."""
        if not self.chat_doc_paths:
            messagebox.showwarning("Sin documentos", "Añade al menos un documento antes de guardar el proyecto.")
            return
        from tkinter import simpledialog
        name = simpledialog.askstring(
            "Guardar Proyecto de Chat",
            "Nombre del proyecto (los índices AST y embeddings se conservarán por SHA-256):",
            parent=self.root,
        )
        if not name or not name.strip():
            return
        from .ai.doc_cache import DocumentIndexCache
        DocumentIndexCache.get_instance().save_project(name.strip(), self.chat_doc_paths)
        self.chat_status_var.set(f"✓ Proyecto '{name.strip()}' guardado ({len(self.chat_doc_paths)} archivo(s)).")

    def _chat_load_project(self):
        """Abre un selector de proyectos guardados y recarga al instante los ficheros cuyo SHA-256 coincide."""
        from .ai.doc_cache import DocumentIndexCache
        cache = DocumentIndexCache.get_instance()
        projects = cache.list_projects()
        if not projects:
            messagebox.showinfo("Proyectos", "Todavía no hay proyectos guardados. Añade archivos y pulsa '💾 Guardar proyecto'.")
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("Cargar Proyecto de Chat (caché SHA-256)")
        dlg.geometry("520x320")
        dlg.configure(bg=self.palette["bg"])
        dlg.transient(self.root)
        dlg.grab_set()

        frame = ttk.Frame(dlg, padding="12")
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="Selecciona un proyecto guardado:", font=self._get_font_tuple(bold=True)).pack(anchor="w", pady=(0, 6))

        lb = tk.Listbox(
            frame,
            font=self._get_font_tuple(),
            bg=self.palette["input_bg"],
            fg=self.palette["input_fg"],
            selectbackground=self.palette["accent"],
            selectforeground=self.palette["bg"],
        )
        lb.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        for pname, nfiles, upd in projects:
            lb.insert(tk.END, f"📁 {pname}  —  {nfiles} archivo(s)  ({upd[:10]})")

        btn_bar = ttk.Frame(frame)
        btn_bar.pack(fill=tk.X)

        def do_load():
            sel = lb.curselection()
            if not sel:
                return
            pname = projects[sel[0]][0]
            entries = cache.load_project(pname) or []
            dlg.destroy()
            valid_paths = [e["path"] for e in entries if Path(e["path"]).exists()]
            missing = [e["name"] for e in entries if not Path(e["path"]).exists()]
            if missing:
                messagebox.showwarning("Archivos movidos", f"No se encontraron en disco:\n- " + "\n- ".join(missing))
            if valid_paths:
                self._chat_clear(confirm=False)
                self._chat_index_paths(valid_paths)

        def do_delete():
            sel = lb.curselection()
            if not sel:
                return
            pname = projects[sel[0]][0]
            if messagebox.askyesno("Eliminar proyecto", f"¿Eliminar el proyecto '{pname}'?", parent=dlg):
                cache.delete_project(pname)
                dlg.destroy()
                self._chat_load_project()

        ttk.Button(btn_bar, text="📂 Cargar seleccionado", command=do_load).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_bar, text="🗑️ Eliminar", command=do_delete).pack(side=tk.LEFT)
        ttk.Button(btn_bar, text="Cancelar", command=dlg.destroy).pack(side=tk.RIGHT)

    def _refresh_chat_docs_ui(self):
        self.chat_docs_listbox.delete(0, tk.END)
        self.chat_doc_paths = []
        if self.chat_engine is None:
            self.chat_count_var.set("")
            return
        doc_ids = self.chat_engine.get_document_id_map()
        for path_str, (fname, tree) in self.chat_engine.documents.items():
            did = doc_ids[path_str]
            emb_tag = "BGE-M3+BM25" if tree.has_embeddings else "BM25+AST"
            self.chat_docs_listbox.insert(tk.END, f"[{did}] 📄 {fname}  ({len(tree.nodos)} nodos AST | {emb_tag})")
            self.chat_doc_paths.append(path_str)
        self.chat_count_var.set(
            f"📚 {len(self.chat_doc_paths)}/{self.ai_tier.max_chat_docs} documento(s) | "
            f"{self.chat_engine.total_nodes} nodos AST listos."
        )

    def _chat_remove_selected(self):
        if self.chat_engine is None:
            return
        sel = list(self.chat_docs_listbox.curselection())
        for idx in reversed(sel):
            if 0 <= idx < len(self.chat_doc_paths):
                self.chat_engine.remove_document(self.chat_doc_paths[idx])
        self._refresh_chat_docs_ui()

    def _chat_clear(self, confirm: bool = True):
        if confirm and self.chat_doc_paths:
            if not messagebox.askyesno(
                "Nueva sesión de chat",
                "¿Seguro que deseas vaciar la lista de documentos y el historial actual del chat?",
                parent=self.root,
            ):
                return
        if self.chat_engine is not None:
            self.chat_engine.clear()
        self._refresh_chat_docs_ui()
        self.chat_history_text.config(state=tk.NORMAL)
        self.chat_history_text.delete("1.0", tk.END)
        self.chat_history_text.config(state=tk.DISABLED)
        self.chat_status_var.set("Sesión de chat reiniciada.")

    def _chat_send(self):
        question = self.chat_question_var.get().strip()
        if not question:
            return
        eng = self._ensure_chat_engine()
        if not eng.documents:
            messagebox.showwarning("Sin documentos", "Añade al menos un documento arriba antes de preguntar.")
            return

        from .ai import LlamaRuntimeManager
        runtime = LlamaRuntimeManager.get_instance()
        if not runtime.is_models_present():
            chosen_source = self._ask_model_download_source()
            if not chosen_source:
                return
            runtime.preferred_model_source = chosen_source

        self.chat_question_var.set("")
        self._chat_append_message("user_lbl", "Tú", question)
        self.btn_chat_send.config(state=tk.DISABLED)
        self.btn_chat_add.config(state=tk.DISABLED)
        self.chat_progress.start(10)

        def worker():
            try:
                response_lang = get_llm_language_name(self.ui_lang)
                ans, refs = eng.ask(
                    question,
                    response_lang=response_lang,
                    progress_cb=lambda m: self.root.after(0, self.chat_status_var.set, m),
                )

                def on_ok():
                    self.chat_progress.stop()
                    self.btn_chat_send.config(state=tk.NORMAL)
                    self.btn_chat_add.config(state=tk.NORMAL)
                    self._chat_append_message("ai_lbl", "Asistente (con citas)", ans, refs=refs)
                    self.chat_status_var.set(f"✓ Respuesta generada citando {len(refs)} referencia(s).")
                    if self.a11y.voice_guidance:
                        self._speak_text(ans)

                self.root.after(0, on_ok)
            except Exception as e:
                logger.exception(f"Error en chat multi-documento: {e}")

                def on_err(msg=str(e)):
                    self.chat_progress.stop()
                    self.btn_chat_send.config(state=tk.NORMAL)
                    self.btn_chat_add.config(state=tk.NORMAL)
                    self.chat_status_var.set(f"Error: {msg}")
                    self._announce(f"Error en chat: {msg}")
                    messagebox.showerror("Error en Chat", msg)

                self.root.after(0, on_err)

        threading.Thread(target=worker, daemon=True).start()

    # ---------------- PESTAÑA 3: IA LOCAL Y MANUSCRITOS ----------------
    def _build_ai_tab(self):
        self.ai_buttons = []
        if not self.ai_tier.vlm_enabled:
            self._render_hardware_locked_notice(
                self.tab_ai,
                "IA Local y Manuscritos",
                [
                    "Lectura de letra manuscrita mediante visión multimodal (Qwen3-VL).",
                    "Resúmenes ejecutivos y adaptación a Lectura Fácil (Norma UNE 153101 EX).",
                    "Traducción contextual a cualquier idioma 100% offline.",
                ],
            )
            return

        tier = self.ai_tier
        hw_text = (
            f"💻 Hardware: {self.hw.ram_total_gb:.1f} GB RAM | {self.hw.backend.upper()} | "
            f"Perfil {tier.tier_name.upper()} → {tier.vlm_label} + {tier.embed_label} (ctx={tier.recommended_n_ctx})"
        )
        ai_hw_lbl = ttk.Label(self.tab_ai, text=hw_text)
        self._track_label(ai_hw_lbl, role="accent", size_delta=-2, bold=True, wrap=True)
        ai_hw_lbl.pack(anchor="w", fill=tk.X, pady=(0, 4))

        if tier.locked_features_hint:
            ai_hint_lbl = ttk.Label(self.tab_ai, text=f"ℹ️ {tier.locked_features_hint}")
            self._track_label(ai_hint_lbl, role="warn", size_delta=-2, italic=True, wrap=True)
            ai_hint_lbl.pack(anchor="w", fill=tk.X, pady=(0, 4))

        # Opción de lectura manuscrita + forzar OCR (fluido sin recortes)
        opts_frame = self._make_flow_row(self.tab_ai, hgap=14, vgap=4)
        opts_frame.pack(fill=tk.X, pady=(0, 6))

        self.chk_handwriting = ttk.Checkbutton(
            opts_frame,
            text=tr(self.ui_lang, "chk_handwriting"),
            variable=self.handwriting_var,
        )
        opts_frame.add_item(self.chk_handwriting)
        opts_frame.add_item(
            ttk.Checkbutton(
                opts_frame,
                text="Forzar OCR (ignorar texto embebido)",
                variable=self.ai_force_ocr_var,
            )
        )

        # Botones de acciones IA enfocadas (Transcribir, Resumir, Lectura Fácil, Traducir)
        self.ai_actions_frame = ttk.LabelFrame(self.tab_ai, text=tr(self.ui_lang, "ai_actions_group"), padding="8")
        self.ai_actions_frame.pack(fill=tk.X, pady=(0, 6))

        btn_row = self._make_flow_row(self.ai_actions_frame, hgap=6, vgap=4)
        btn_row.pack(fill=tk.X)

        self.btn_ai_transcribe = ttk.Button(
            btn_row, text=tr(self.ui_lang, "btn_transcribe"), command=lambda: self._run_ai_action("transcribe")
        )
        btn_row.add_item(self.btn_ai_transcribe)

        self.btn_ai_summarize = ttk.Button(
            btn_row, text=tr(self.ui_lang, "btn_summarize"), command=lambda: self._run_ai_action("summarize")
        )
        btn_row.add_item(self.btn_ai_summarize)

        self.btn_ai_easy_read = ttk.Button(
            btn_row,
            text=tr(self.ui_lang, "btn_easy_read"),
            command=lambda: self._run_ai_action("easy_read"),
            **self._icon_kwargs("easy_read"),
        )
        btn_row.add_item(self.btn_ai_easy_read)

        self.btn_ai_translate = ttk.Button(
            btn_row, text=tr(self.ui_lang, "btn_translate"), command=lambda: self._run_ai_action("translate")
        )
        btn_row.add_item(self.btn_ai_translate)

        self.translate_lang_combo = ttk.Combobox(
            btn_row,
            textvariable=self.translate_lang_var,
            values=TRANSLATION_TARGET_LANGUAGES,
            width=16,
        )
        self._register_scaled_entry(self.translate_lang_combo, size_delta=-1)
        btn_row.add_item(self.translate_lang_combo)

        ask_row = ttk.Frame(self.ai_actions_frame)
        ask_row.pack(fill=tk.X, pady=(6, 0))
        self.ai_lbl_question = ttk.Label(ask_row, text=tr(self.ui_lang, "lbl_question"))
        self.ai_lbl_question.pack(side=tk.LEFT, padx=(0, 6))
        self.ai_question_entry = ttk.Entry(ask_row, textvariable=self.question_var)
        self._register_scaled_entry(self.ai_question_entry, size_delta=0)
        self.ai_question_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.ai_question_entry.bind("<Return>", lambda e: self._run_ai_action("ask"))
        self.btn_ai_ask = ttk.Button(
            ask_row,
            text=tr(self.ui_lang, "btn_ask"),
            command=lambda: self._run_ai_action("ask"),
        )
        self.btn_ai_ask.pack(side=tk.RIGHT)

        self.ai_buttons.extend(
            [self.btn_ai_transcribe, self.btn_ai_summarize, self.btn_ai_easy_read, self.btn_ai_translate, self.btn_ai_ask]
        )

        # Progreso y estado IA
        self.ai_progress = ttk.Progressbar(self.tab_ai, mode="indeterminate")
        self.ai_progress.pack(fill=tk.X, pady=(2, 4))

        ai_st_lbl = ttk.Label(self.tab_ai, textvariable=self.ai_status_var)
        self._track_label(ai_st_lbl, role="fg", size_delta=-1, wrap=True)
        ai_st_lbl.pack(anchor="w", fill=tk.X, pady=(0, 4))

        # Botones inferiores IA en flujo elástico (empaquetados antes del área expandible para que nunca desaparezcan)
        ai_bottom = self._make_flow_row(self.tab_ai, hgap=6, vgap=4)
        ai_bottom.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))

        ai_bottom.add_item(ttk.Button(ai_bottom, text="📋 Copiar texto", command=self._copy_ai_output))
        ai_bottom.add_item(ttk.Button(ai_bottom, text="💾 Guardar .txt", command=self._save_ai_output))
        ai_bottom.add_item(ttk.Button(ai_bottom, text="🔊 Leer en voz alta", command=self._speak_active_output))
        ai_bottom.add_item(ttk.Button(ai_bottom, text="⏹️ Callar", command=self._stop_tts))
        ai_bottom.add_item(ttk.Label(ai_bottom, text="Exportar consulta + citas:"))
        ai_exp_cb = ttk.Combobox(
            ai_bottom,
            textvariable=self.ai_export_fmt_var,
            values=[lbl for lbl, _code in self.EXPORT_CONV_FORMATS],
            state="readonly",
            width=16,
        )
        self._register_scaled_entry(ai_exp_cb, size_delta=-1)
        ai_bottom.add_item(ai_exp_cb)
        ai_bottom.add_item(
            ttk.Button(
                ai_bottom,
                text="📥 Exportar informe...",
                command=self._export_ai_output_with_refs,
            )
        )

        # Área de texto resultado
        text_frame = ttk.Frame(self.tab_ai)
        text_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.ai_output_text = tk.Text(
            text_frame,
            height=6,
            wrap=tk.WORD,
            yscrollcommand=scrollbar.set,
            padx=8,
            pady=6,
        )
        self.ai_output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.ai_output_text.yview)
        self._register_zoomable_text(self.ai_output_text, family="Consolas")

        # Atajos de teclado explícitos y menú contextual (clic derecho) para copiar o escuchar
        self.ai_output_text.bind("<Control-c>", self._copy_selection)
        self.ai_output_text.bind("<Control-C>", self._copy_selection)
        self.ai_output_text.bind("<Control-a>", self._select_all_output)
        self.ai_output_text.bind("<Control-A>", self._select_all_output)
        self.ai_output_text.bind("<Button-3>", self._show_text_context_menu)

        self.text_context_menu = tk.Menu(self.root, tearoff=0)
        self.text_context_menu.add_command(label="🔊 Leer texto seleccionado / todo", command=self._speak_active_output)
        self.text_context_menu.add_command(label="⏹️ Detener lectura de voz", command=self._stop_tts)
        self.text_context_menu.add_separator()
        self.text_context_menu.add_command(label="📋 Copiar selección", command=self._copy_selection)
        self.text_context_menu.add_command(label="📋 Copiar todo", command=self._copy_ai_output)
        self.text_context_menu.add_separator()
        self.text_context_menu.add_command(label="Seleccionar todo (Ctrl+A)", command=self._select_all_output)

    # ---------------- PESTAÑA 4: ANONIMIZADOR RGPD (100% PYTHON + IA OPCIONAL) ----------------
    def _build_anonymize_tab(self):
        info_grp = ttk.LabelFrame(
            self.tab_anonymize,
            text=" 🔒 Anonimizador RGPD (Motor determinista 100% Python — funciona en cualquier hardware) ",
            padding="8",
        )
        info_grp.pack(fill=tk.X, pady=(0, 8))

        anon_info_lbl = ttk.Label(
            info_grp,
            text="Detecta y oculta instantáneamente sin IA: DNI, NIE, CIF, IBAN, Tarjetas, NUSS, Emails, "
                 "Teléfonos, IPs, Matrículas, Direcciones postales y Nombres con tratamiento (Don/Doña/Sr./Sra.).",
        )
        self._track_label(anon_info_lbl, role="muted", size_delta=-2, wrap=True)
        anon_info_lbl.pack(anchor="w", fill=tk.X, pady=(0, 6))

        ctrl_row = self._make_flow_row(info_grp, hgap=10, vgap=4)
        ctrl_row.pack(fill=tk.X, pady=(0, 4))
        ctrl_row.add_item(ttk.Label(ctrl_row, text="Estilo de ocultación:"))
        ctrl_row.add_item(ttk.Radiobutton(ctrl_row, text="Etiquetas ([DNI], [NOMBRE])", value="tags", variable=self.anon_mask_style_var))
        ctrl_row.add_item(ttk.Radiobutton(ctrl_row, text="Bloques negros (████████)", value="blocks", variable=self.anon_mask_style_var))

        if self.ai_tier.vlm_enabled:
            mode_row = ttk.Frame(info_grp)
            mode_row.pack(fill=tk.X, pady=(4, 0))
            ttk.Radiobutton(
                mode_row,
                text="⚡ Paso 1 solo (100% Python instantáneo — sin IA)",
                value=False,
                variable=self.anon_use_llm_var,
            ).pack(anchor="w")
            ttk.Radiobutton(
                mode_row,
                text=f"🧠 Paso 1 + Paso 2 (IA local {self.ai_tier.vlm_label}: nombres propios sin tratamiento y empresas)",
                value=True,
                variable=self.anon_use_llm_var,
            ).pack(anchor="w")
        else:
            anon_hw_lbl = ttk.Label(
                info_grp,
                text="ℹ️ Modo Paso 1 (100% Python) activo. Con ≥6 GB RAM se desbloquea además "
                     "el Paso 2 (refuerzo semántico IA) para nombres propios sin tratamiento y empresas.",
            )
            self._track_label(anon_hw_lbl, role="warn", size_delta=-1, italic=True, wrap=True)
            anon_hw_lbl.pack(anchor="w", fill=tk.X, pady=(4, 0))

        self.btn_run_anon = ttk.Button(
            self.tab_anonymize,
            text="🔒  Anonimizar documento seleccionado",
            command=self._run_anonymize_standalone,
        )
        self.btn_run_anon.pack(fill=tk.X, ipady=5, pady=(0, 6))

        self.anon_progress = ttk.Progressbar(self.tab_anonymize, mode="indeterminate")
        self.anon_progress.pack(fill=tk.X, pady=(0, 4))
        anon_st_lbl = ttk.Label(self.tab_anonymize, textvariable=self.anon_status_var)
        self._track_label(anon_st_lbl, role="fg", size_delta=-1, wrap=True)
        anon_st_lbl.pack(anchor="w", fill=tk.X, pady=(0, 4))

        anon_bottom = self._make_flow_row(self.tab_anonymize, hgap=8, vgap=4)
        anon_bottom.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))
        anon_bottom.add_item(ttk.Button(anon_bottom, text="📋 Copiar resultado", command=self._copy_anon_output))
        anon_bottom.add_item(ttk.Button(anon_bottom, text="💾 Guardar como .txt", command=self._save_anon_output))
        anon_bottom.add_item(ttk.Button(anon_bottom, text="🔊 Leer resultado", command=self._speak_active_output))
        anon_bottom.add_item(ttk.Button(anon_bottom, text="⏹️ Callar", command=self._stop_tts))

        anon_txt_frame = ttk.Frame(self.tab_anonymize)
        anon_txt_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        anon_scroll = ttk.Scrollbar(anon_txt_frame)
        anon_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.anon_output_text = tk.Text(
            anon_txt_frame,
            height=6,
            wrap=tk.WORD,
            yscrollcommand=anon_scroll.set,
            padx=8,
            pady=8,
        )
        self.anon_output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        anon_scroll.config(command=self.anon_output_text.yview)
        self._register_zoomable_text(self.anon_output_text, family="Consolas")

    def _run_anonymize_standalone(self):
        in_path = self.input_path_var.get().strip()
        if not in_path or not Path(in_path).exists():
            messagebox.showwarning("Aviso", "Selecciona primero un fichero de entrada arriba.")
            return

        use_llm = self.anon_use_llm_var.get() and self.ai_tier.vlm_enabled
        if use_llm:
            from .ai import LlamaRuntimeManager
            runtime = LlamaRuntimeManager.get_instance()
            if not runtime.is_models_present():
                chosen = self._ask_model_download_source()
                if not chosen:
                    return
                runtime.preferred_model_source = chosen

        self.btn_run_anon.config(state=tk.DISABLED)
        self.anon_progress.start(10)
        self.anon_status_var.set("Extrayendo texto y aplicando anonimización RGPD...")

        def worker():
            try:
                from .ai.anonymizer import DocumentAnonymizer

                doc_text, _stats = DocumentLoader.extract_text_smart(
                    in_path,
                    handwriting=False,
                    force_ocr=False,
                    progress_cb=lambda m: self.root.after(0, self.anon_status_var.set, m),
                )
                anon = DocumentAnonymizer()
                masked = anon.anonymize(
                    doc_text,
                    mask_style=self.anon_mask_style_var.get(),
                    use_llm=use_llm,
                    progress_cb=lambda m: self.root.after(0, self.anon_status_var.set, m),
                )
                mode_lbl = "Python + IA local" if use_llm else "100% Python determinista"

                def on_ok():
                    self.anon_progress.stop()
                    self.btn_run_anon.config(state=tk.NORMAL)
                    self.anon_output_text.delete("1.0", tk.END)
                    self.anon_output_text.insert("1.0", masked)
                    self.anon_status_var.set(f"✓ Anonimización completada ({mode_lbl}). Revisa el resultado antes de publicar.")
                    self._announce("Anonimización completada.")

                self.root.after(0, on_ok)
            except Exception as e:
                logger.exception(f"Error en anonimización: {e}")

                def on_err(msg=str(e)):
                    self.anon_progress.stop()
                    self.btn_run_anon.config(state=tk.NORMAL)
                    self.anon_status_var.set(f"Error: {msg}")
                    self._announce(f"Error en anonimización: {msg}")
                    messagebox.showerror("Error al anonimizar", msg)

                self.root.after(0, on_err)

        threading.Thread(target=worker, daemon=True).start()

    def _copy_anon_output(self):
        content = self.anon_output_text.get("1.0", tk.END).strip()
        if content:
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.anon_status_var.set("✓ Texto anonimizado copiado al portapapeles.")

    def _save_anon_output(self):
        content = self.anon_output_text.get("1.0", tk.END).strip()
        if not content:
            return
        chosen = filedialog.asksaveasfilename(
            title="Guardar documento anonimizado",
            defaultextension=".txt",
            filetypes=[("Archivo de texto (*.txt)", "*.txt")],
        )
        if chosen:
            Path(chosen).write_text(content, encoding="utf-8")
            self.anon_status_var.set(f"✓ Guardado en: {chosen}")

    def _build_pdf_tools_tab(self):
        """Pestaña 5: Desbloqueo de PDFs, borrado de firmas, limpieza de marcas de agua y optimización."""
        self.pdf_tool_buttons = []

        # Aviso de uso legítimo y cumplimiento normativo
        legal_pdf_lbl = ttk.Label(
            self.tab_pdf_tools,
            text="⚖️ Aviso legal: utiliza estas herramientas únicamente sobre documentos propios o con autorización legítima "
                 "(no realiza crackeo de claves de apertura; respeta propiedad intelectual, RGPD y autenticidad documental).",
        )
        self._track_label(legal_pdf_lbl, role="warn", size_delta=-2, italic=True, wrap=True)
        legal_pdf_lbl.pack(anchor="w", fill=tk.X, pady=(0, 8))

        # 1. Desbloqueo de PDFs con clave o restricciones
        unlock_grp = ttk.LabelFrame(self.tab_pdf_tools, text=" 🔓 Desbloquear PDF (quitar contraseña o restricciones de copia/impresión) ", padding="8")
        unlock_grp.pack(fill=tk.X, pady=(0, 8))

        u_row = self._make_flow_row(unlock_grp, hgap=8, vgap=4)
        u_row.pack(fill=tk.X)
        u_row.add_item(ttk.Label(u_row, text="Contraseña (opcional si solo tiene restricciones):"))
        pw_entry = ttk.Entry(u_row, textvariable=self.pdf_password_var, show="•", width=22)
        self._register_scaled_entry(pw_entry, size_delta=-1)
        u_row.add_item(pw_entry)
        btn_unlock = ttk.Button(u_row, text="🔓 Desbloquear PDF", command=lambda: self._run_pdf_tool("unlock"))
        u_row.add_item(btn_unlock)
        self.pdf_tool_buttons.append(btn_unlock)

        # 2. Eliminación de firmas digitales
        sig_grp = ttk.LabelFrame(self.tab_pdf_tools, text=" ✍️ Borrar Firmas Digitales y Sellos de Formulario ", padding="8")
        sig_grp.pack(fill=tk.X, pady=(0, 8))

        s_row = self._make_flow_row(sig_grp, hgap=10, vgap=4)
        s_row.pack(fill=tk.X)
        sig_info_lbl = ttk.Label(
            s_row,
            text="Elimina campos criptográficos (/Sig), bloqueos de edición (DocMDP) y sellos visuales.",
        )
        self._track_label(sig_info_lbl, role="muted", size_delta=-2)
        s_row.add_item(sig_info_lbl)
        btn_sig = ttk.Button(s_row, text="🗑️ Borrar firmas del PDF", command=lambda: self._run_pdf_tool("signatures"))
        s_row.add_item(btn_sig)
        self.pdf_tool_buttons.append(btn_sig)

        # 3. Limpieza de marcas de agua
        wm_grp = ttk.LabelFrame(self.tab_pdf_tools, text=" 🧽 Limpiar Marcas de Agua (Vectoriales, Capas OCG y Escaneos) ", padding="8")
        wm_grp.pack(fill=tk.X, pady=(0, 8))

        wm_row1 = self._make_flow_row(wm_grp, hgap=8, vgap=4)
        wm_row1.pack(fill=tk.X, pady=(0, 4))
        wm_row1.add_item(ttk.Label(wm_row1, text="Texto de marca a borrar (opcional, ej. BORRADOR):"))
        wm_entry = ttk.Entry(wm_row1, textvariable=self.wm_text_var, width=28)
        self._register_scaled_entry(wm_entry, size_delta=-1)
        wm_row1.add_item(wm_entry)

        wm_row2 = self._make_flow_row(wm_grp, hgap=10, vgap=4)
        wm_row2.pack(fill=tk.X)
        wm_row2.add_item(ttk.Checkbutton(wm_row2, text="Eliminar /Watermark y capas OCG", variable=self.wm_annots_var))
        wm_row2.add_item(ttk.Checkbutton(wm_row2, text="Limpiar marca en escaneos (OpenCV)", variable=self.wm_scan_var))
        btn_wm = ttk.Button(wm_row2, text="🧽 Limpiar marcas de agua", command=lambda: self._run_pdf_tool("watermarks"))
        wm_row2.add_item(btn_wm)
        self.pdf_tool_buttons.append(btn_wm)

        # 4. Compresión rápida, escala de grises y PDF/A
        opt_grp = ttk.LabelFrame(self.tab_pdf_tools, text=" 🗜️ Comprimir PDF, Escala de Grises y PDF/A-2b ", padding="8")
        opt_grp.pack(fill=tk.X, pady=(0, 10))

        opt_row = self._make_flow_row(opt_grp, hgap=8, vgap=4)
        opt_row.pack(fill=tk.X)
        opt_row.add_item(ttk.Label(opt_row, text="Compresión:"))
        opt_comp_cb = ttk.Combobox(
            opt_row,
            textvariable=self.opt_compression_var,
            values=[lbl for lbl, _code in self.COMPRESSION_LABELS],
            state="readonly",
            width=24,
        )
        self._register_scaled_entry(opt_comp_cb, size_delta=-1)
        opt_row.add_item(opt_comp_cb)
        opt_row.add_item(ttk.Checkbutton(opt_row, text="Escala de grises", variable=self.opt_grayscale_var))
        opt_row.add_item(ttk.Checkbutton(opt_row, text="Estándar PDF/A-2b", variable=self.opt_pdfa_var))
        btn_opt = ttk.Button(opt_row, text="🗜️ Optimizar PDF", command=lambda: self._run_pdf_tool("optimize"))
        opt_row.add_item(btn_opt)
        self.pdf_tool_buttons.append(btn_opt)

        # Progreso y botones resultado
        self.pdf_tools_progress = ttk.Progressbar(self.tab_pdf_tools, mode="indeterminate")
        self.pdf_tools_progress.pack(fill=tk.X, pady=(2, 6))

        pdf_st_lbl = ttk.Label(self.tab_pdf_tools, textvariable=self.pdf_tools_status_var)
        self._track_label(pdf_st_lbl, role="fg", size_delta=-1, wrap=True)
        pdf_st_lbl.pack(anchor="w", fill=tk.X)

        post_pdf = self._make_flow_row(self.tab_pdf_tools, hgap=8, vgap=4)
        post_pdf.pack(fill=tk.X, pady=(8, 0))
        self.btn_pdf_open_file = ttk.Button(
            post_pdf,
            text="📄 Abrir PDF resultante",
            command=lambda: self.last_pdf_tool_file and self._open_path_crossplatform(self.last_pdf_tool_file),
            state=tk.DISABLED,
        )
        post_pdf.add_item(self.btn_pdf_open_file)
        self.btn_pdf_open_folder = ttk.Button(
            post_pdf,
            text="📁 Abrir carpeta",
            command=lambda: self.last_pdf_tool_file and self._open_path_crossplatform(str(Path(self.last_pdf_tool_file).parent)),
            state=tk.DISABLED,
        )
        post_pdf.add_item(self.btn_pdf_open_folder)

    def _get_compression_code(self, label: str) -> str:
        for lbl, code in self.COMPRESSION_LABELS:
            if lbl == label:
                return code
        return "high"

    def _run_pdf_tool(self, tool_action: str):
        in_path = self.input_path_var.get().strip()
        if not in_path or not Path(in_path).exists():
            messagebox.showwarning("Aviso", "Selecciona primero un fichero PDF arriba.")
            return
        if Path(in_path).suffix.lower() != ".pdf":
            messagebox.showwarning("Solo PDF", "Las herramientas de esta pestaña operan sobre ficheros PDF (.pdf).")
            return

        for b in self.pdf_tool_buttons:
            b.config(state=tk.DISABLED)
        self.btn_pdf_open_file.config(state=tk.DISABLED)
        self.btn_pdf_open_folder.config(state=tk.DISABLED)
        self.pdf_tools_progress.start(10)
        self.pdf_tools_status_var.set("Procesando PDF...")

        def worker():
            try:
                from .pdf_tools import optimize_pdf, remove_signatures, remove_watermarks, unlock_pdf

                if tool_action == "unlock":
                    res = unlock_pdf(in_path, password=self.pdf_password_var.get())
                elif tool_action == "signatures":
                    res = remove_signatures(in_path)
                elif tool_action == "watermarks":
                    res = remove_watermarks(
                        in_path,
                        watermark_text=self.wm_text_var.get(),
                        remove_annotations=self.wm_annots_var.get(),
                        remove_ocg=self.wm_annots_var.get(),
                        clean_scan_watermark=self.wm_scan_var.get(),
                    )
                elif tool_action == "optimize":
                    res = optimize_pdf(
                        in_path,
                        compression=self._get_compression_code(self.opt_compression_var.get()),
                        grayscale=self.opt_grayscale_var.get(),
                        pdfa=self.opt_pdfa_var.get(),
                    )
                else:
                    raise ValueError(f"Acción desconocida: {tool_action}")

                def on_ok():
                    self.pdf_tools_progress.stop()
                    for b in self.pdf_tool_buttons:
                        b.config(state=tk.NORMAL)
                    self.last_pdf_tool_file = res["output_path"]
                    self.btn_pdf_open_file.config(state=tk.NORMAL)
                    self.btn_pdf_open_folder.config(state=tk.NORMAL)
                    self.pdf_tools_status_var.set(f"✓ {res['message']}")
                    self._announce(res["message"])
                    messagebox.showinfo("Operación completada", res["message"])

                self.root.after(0, on_ok)
            except Exception as e:
                logger.exception(f"Error en herramienta PDF '{tool_action}': {e}")

                def on_err(msg=str(e)):
                    self.pdf_tools_progress.stop()
                    for b in self.pdf_tool_buttons:
                        b.config(state=tk.NORMAL)
                    self.pdf_tools_status_var.set(f"Error: {msg}")
                    self._announce(f"Error en herramienta PDF: {msg}")
                    messagebox.showerror("Error en Herramienta PDF", msg)

                self.root.after(0, on_err)

        threading.Thread(target=worker, daemon=True).start()

    def _layout_drop_canvas(self, width: int):
        """Reajusta el ancho de salto de línea y la altura del área de arrastre según el zoom."""
        wrap_w = max(240, int(width) - 24)
        self.drop_canvas.itemconfigure(self.drop_text_id, width=wrap_w)
        bbox = self.drop_canvas.bbox(self.drop_text_id)
        if bbox:
            text_h = max(18, bbox[3] - bbox[1])
            target_h = max(34, text_h + 14)
        else:
            target_h = 34
        if int(float(self.drop_canvas.cget("height"))) != target_h:
            self.drop_canvas.configure(height=target_h)
        self.drop_canvas.coords(self.drop_text_id, width / 2, target_h / 2)

    def _center_drop_text(self, event):
        self._layout_drop_canvas(event.width)

    def _on_ui_language_changed(self, event=None):
        """Actualiza en caliente el idioma de toda la interfaz y del motor de IA."""
        selected_name = self.ui_lang_var.get()
        for code, name in SUPPORTED_UI_LANGUAGES:
            if name == selected_name:
                self.ui_lang = code
                break
        # Sincronizar el idioma destino de traducción por defecto con el idioma elegido
        self.translate_lang_var.set(selected_name)
        self.trans_target_lang_var.set(selected_name)
        self._apply_language()
        self._update_default_translate_output()

    def _apply_language(self):
        lang = self.ui_lang
        self.root.title(tr(lang, "window_title"))
        self.subtitle_lbl.config(text=tr(lang, "subtitle"))
        self.btn_accessibility.config(text=_strip_leading_emoji(tr(lang, "btn_accessibility")).strip())
        self.btn_tts_read.config(text=_strip_leading_emoji(tr(lang, "btn_tts_read")).strip())
        self.btn_github.config(text=_strip_leading_emoji(tr(lang, "btn_github")).strip())
        self.btn_legal.config(text=_strip_leading_emoji(tr(lang, "btn_legal")).strip())
        self.btn_update.config(text=_strip_leading_emoji(tr(lang, "btn_update")).strip())
        self.btn_reinstall.config(text=_strip_leading_emoji(tr(lang, "btn_reinstall")).strip())
        self.btn_cache.config(text=_strip_leading_emoji(tr(lang, "btn_cache")).strip())
        self.btn_clear_logs.config(text=_strip_leading_emoji(tr(lang, "btn_clear_logs")).strip())
        self.btn_view_logs.config(text=_strip_leading_emoji(tr(lang, "btn_view_logs")).strip())
        self.drop_frame.config(text=tr(lang, "input_group"))
        self.btn_paste.config(text=tr(lang, "btn_paste"))
        self.btn_browse.config(text=tr(lang, "btn_browse"))
        self._tabs_compact_mode = None
        self._update_notebook_tab_labels()
        self.format_group.config(text=tr(lang, "format_group"))
        for fmt_key, (rb, desc_lbl) in self.format_widgets.items():
            lbl_txt, desc_txt = tr(lang, f"fmt_{fmt_key}")
            rb.config(text=lbl_txt)
            if desc_lbl is not None:
                desc_lbl.config(text=f"— {desc_txt}")
        self._on_format_changed()
        if self.ai_tier.vlm_enabled and hasattr(self, "trans_format_desc_var"):
            self._on_trans_format_changed()
        self.output_group.config(text=tr(lang, "output_group"))
        self.btn_save_as.config(text=tr(lang, "btn_save_as"))
        self.btn_convert.config(text=tr(lang, "btn_convert"))
        self.btn_open_file.config(text=tr(lang, "btn_open_file"))
        self.btn_open_folder.config(text=tr(lang, "btn_open_folder"))
        if self.ai_tier.vlm_enabled:
            self.chk_handwriting.config(text=tr(lang, "chk_handwriting"))
            self.ai_actions_frame.config(text=tr(lang, "ai_actions_group"))
            self.btn_ai_transcribe.config(text=tr(lang, "btn_transcribe"))
            self.btn_ai_summarize.config(text=tr(lang, "btn_summarize"))
            if hasattr(self, "btn_ai_easy_read"):
                self.btn_ai_easy_read.config(text=_strip_leading_emoji(tr(lang, "btn_easy_read")).strip())
            self.btn_ai_translate.config(text=tr(lang, "btn_translate"))
            if hasattr(self, "ai_lbl_question"):
                self.ai_lbl_question.config(text=tr(lang, "lbl_question"))
            if hasattr(self, "btn_ai_ask"):
                self.btn_ai_ask.config(text=tr(lang, "btn_ask"))
        self.footer_lbl.config(text=tr(lang, "footer"))
        if not self.input_path_var.get().strip():
            self.drop_canvas.itemconfigure(self.drop_text_id, text=tr(lang, "drop_prompt"))
            self.status_var.set(tr(lang, "status_ready"))
            self.ai_status_var.set(tr(lang, "ai_status_ready"))
        else:
            name = Path(self.input_path_var.get().strip()).name
            self.drop_canvas.itemconfigure(self.drop_text_id, text=tr(lang, "drop_selected", name=name))
        self.root.after_idle(self._relayout_responsive_containers)

    def _setup_drag_and_drop(self):
        if HAS_WINDND:
            try:
                windnd.hook_dropfiles(self.root, func=self._on_files_dropped)
            except Exception:
                pass

    def _on_files_dropped(self, files):
        if not files:
            return
        first = files[0]
        if isinstance(first, bytes):
            try:
                file_path = first.decode("utf-8")
            except UnicodeDecodeError:
                file_path = first.decode("mbcs", errors="ignore")
        else:
            file_path = str(first)
        self._set_input_file(file_path)

    def _setup_clipboard_paste(self):
        self.root.bind_all("<Control-v>", self._on_ctrl_v)
        self.root.bind_all("<Control-V>", self._on_ctrl_v)

    def _on_ctrl_v(self, event):
        # Si el foco está dentro de la caja de pregunta o de resultado, permitir pegado normal de texto
        focused = self.root.focus_get()
        if isinstance(focused, (ttk.Entry, tk.Entry, tk.Text)) and focused != self.input_entry:
            return
        self._paste_from_clipboard()

    def _paste_from_clipboard(self):
        try:
            img = ImageGrab.grabclipboard()
            if img is not None:
                temp_dir = Path(tempfile.gettempdir()) / "open_ocreader"
                temp_dir.mkdir(parents=True, exist_ok=True)
                temp_img_path = temp_dir / f"captura_portapapeles_{int(time.time())}.png"
                img.save(str(temp_img_path))
                self._set_input_file(str(temp_img_path))
                self.status_var.set("✓ Imagen capturada del portapapeles cargada correctamente.")
                return
        except Exception:
            pass

        if HAS_WIN32CLIP:
            try:
                win32clipboard.OpenClipboard()
                try:
                    if win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
                        files = win32clipboard.GetClipboardData(win32con.CF_HDROP)
                        if files:
                            self._set_input_file(files[0])
                            return
                finally:
                    win32clipboard.CloseClipboard()
            except Exception:
                pass

        try:
            clipboard_text = self.root.clipboard_get().strip().strip('"').strip("'")
            if Path(clipboard_text).is_file():
                self._set_input_file(clipboard_text)
                return
        except Exception:
            pass

        self.status_var.set("No se detectó ningún fichero ni imagen compatible en el portapapeles.")

    def _set_input_file(self, file_path: str):
        path_obj = Path(file_path)
        if not path_obj.exists():
            messagebox.showerror("Error", f"El fichero no existe:\n{file_path}")
            return

        self.input_path_var.set(str(path_obj.resolve()))
        self._has_input_file_loaded = True
        self.cached_doc_text = None
        self.cached_doc_key = None
        self.last_ai_turn_record = None
        self.ai_turn_records = []
        self._update_default_output()
        self._update_default_translate_output()

        p = self.palette
        self.drop_canvas.config(bg=p["drop_bg"], highlightbackground=p["ok"])
        self.drop_canvas.itemconfigure(
            self.drop_text_id,
            text=f"✓ Fichero seleccionado: {path_obj.name}  (Haz clic para cambiar)",
            fill=p["ok"],
            font=self._get_font_tuple(size_delta=-1, bold=True),
        )
        cw = self.drop_canvas.winfo_width()
        if cw > 40:
            self._layout_drop_canvas(cw)
        self.status_var.set(f"Fichero listo: {path_obj.name}")
        self.trans_status_var.set(f"Fichero listo para traducir: {path_obj.name}")
        self.ai_status_var.set(f"Documento cargado: {path_obj.name}. Elige una acción de IA.")
        self._announce(f"Archivo seleccionado: {path_obj.name}")

    def _browse_input(self):
        filetypes = [
            ("Ficheros soportados", "*.pdf;*.png;*.jpg;*.jpeg;*.tiff;*.tif;*.bmp;*.webp"),
            ("Documentos PDF (*.pdf)", "*.pdf"),
            ("Imágenes", "*.png;*.jpg;*.jpeg;*.tiff;*.bmp"),
            ("Todos los archivos (*.*)", "*.*"),
        ]
        chosen = filedialog.askopenfilename(title="Seleccionar documento o imagen", filetypes=filetypes)
        if chosen:
            self._set_input_file(chosen)

    def _browse_output(self):
        fmt = self.format_var.get()
        ext = ".pdf" if fmt == "pdfa" else f".{fmt}"
        chosen = filedialog.asksaveasfilename(
            title="Guardar documento resultante como...",
            defaultextension=ext,
            filetypes=[(f"Fichero {fmt.upper()} (*{ext})", f"*{ext}"), ("Todos (*.*)", "*.*")],
        )
        if chosen:
            self.output_path_var.set(chosen)

    def _on_format_changed(self):
        fmt = self.format_var.get()
        _lbl, desc_txt = tr(self.ui_lang, f"fmt_{fmt}")
        self.format_desc_var.set(f"ℹ️ {desc_txt}")
        self._update_default_output()

    def _update_default_output(self):
        in_val = self.input_path_var.get().strip()
        if not in_val:
            return
        in_p = Path(in_val)
        fmt = self.format_var.get()
        if fmt == "pdfa":
            self.output_path_var.set(str(in_p.parent / f"{in_p.stem}_pdfa.pdf"))
        else:
            self.output_path_var.set(str(in_p.parent / f"{in_p.stem}_ocr.{fmt}"))

    # ---------------- LÓGICA CONVERSIÓN ESTRUCTURAL ----------------
    def _start_conversion(self):
        in_path = self.input_path_var.get().strip()
        out_path = self.output_path_var.get().strip()
        fmt = self.format_var.get()

        if not in_path or not Path(in_path).exists():
            messagebox.showwarning("Aviso", "Por favor, selecciona un fichero de entrada válido.")
            return

        if not out_path:
            self._update_default_output()
            out_path = self.output_path_var.get().strip()

        self.btn_convert.config(state=tk.DISABLED)
        self.btn_open_file.config(state=tk.DISABLED)
        self.btn_open_folder.config(state=tk.DISABLED)
        self.progress_bar.start(10)
        self.status_var.set(f"Procesando '{Path(in_path).name}'...")

        threading.Thread(target=self._run_conversion_worker, args=(in_path, out_path, fmt), daemon=True).start()

    def _run_conversion_worker(self, in_path: str, out_path: str, fmt: str):
        try:
            force_ocr = self.force_ocr_var.get()
            grayscale = self.grayscale_var.get()
            compression = self._get_compression_code(self.compression_var.get())
            logger.info(
                f"Iniciando conversión GUI: {in_path} -> {out_path} ({fmt}, force_ocr={force_ocr}, "
                f"compression={compression}, grayscale={grayscale})"
            )
            start_t = time.perf_counter()
            result = DocumentConverter().convert(
                in_path,
                out_path,
                fmt,
                verbose=False,
                force_ocr=force_ocr,
                pdf_compression=compression,
                grayscale=grayscale,
                progress_cb=lambda m: self.root.after(0, self.status_var.set, m),
            )
            elapsed = time.perf_counter() - start_t
            logger.info(
                f"Conversión completada en {elapsed:.2f}s "
                f"({result.native_text_pages} nativas, {result.ocr_pages} OCR, {result.total_elements} elementos)."
            )
            self.root.after(0, self._on_conversion_success, result, elapsed)
        except Exception as e:
            logger.exception(f"Error en conversión GUI para '{in_path}': {e}")
            self.root.after(0, self._on_conversion_error, str(e))

    def _on_conversion_success(self, result, elapsed: float):
        self.progress_bar.stop()
        self.btn_convert.config(state=tk.NORMAL)
        self.last_generated_file = result.output_path
        self.btn_open_file.config(state=tk.NORMAL)
        self.btn_open_folder.config(state=tk.NORMAL)

        self.status_var.set(
            f"✓ Completado en {elapsed:.2f}s ({result.total_pages} pág.: "
            f"{result.native_text_pages} texto nativo, {result.ocr_pages} OCR).\n"
            f"Guardado en: {result.output_path}"
        )
        self._announce(f"Conversión completada en {Path(result.output_path).name}")
        messagebox.showinfo("Completado", f"Documento guardado con éxito en:\n{result.output_path}")

    def _on_conversion_error(self, err_msg: str):
        self.progress_bar.stop()
        self.btn_convert.config(state=tk.NORMAL)
        self.status_var.set(f"Error: {err_msg}")
        self._announce(f"Error en conversión: {err_msg}")
        messagebox.showerror("Error", f"Error durante el procesamiento:\n{err_msg}")

    # ---------------- LÓGICA IA DOCUMENTAL ----------------
    def _run_ai_action(self, action: str):
        in_path = self.input_path_var.get().strip()
        if not in_path or not Path(in_path).exists():
            messagebox.showwarning("Aviso", "Selecciona primero un fichero de entrada arriba.")
            return

        question = self.question_var.get().strip()
        if action == "ask" and not question:
            messagebox.showwarning("Pregunta vacía", "Escribe la pregunta que deseas hacer sobre el documento.")
            return

        use_handwriting = self.handwriting_var.get()
        needs_llm = (action != "transcribe") or use_handwriting

        if needs_llm:
            from .ai import LlamaRuntimeManager
            runtime = LlamaRuntimeManager.get_instance()
            if not runtime.is_models_present():
                chosen_source = self._ask_model_download_source()
                if not chosen_source:
                    return
                runtime.preferred_model_source = chosen_source

        for b in self.ai_buttons:
            b.config(state=tk.DISABLED)
        self.ai_progress.start(10)
        self.ai_status_var.set("Preparando análisis con IA local...")

        threading.Thread(
            target=self._ai_worker,
            args=(in_path, action, question, use_handwriting),
            daemon=True,
        ).start()

    def _ask_model_download_source(self):
        """Diálogo visual para elegir desde dónde descargar el modelo si no existe localmente."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Descargar Modelo de IA (Qwen3-VL-4B)")
        dialog.geometry("500x240")
        dialog.configure(bg=self.palette["bg"])
        dialog.transient(self.root)
        dialog.grab_set()

        result = {"source": None}

        frame = ttk.Frame(dialog, padding="16")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text="No se ha encontrado el modelo de IA en la carpeta 'models/'.",
            font=self._get_font_tuple(bold=True),
            wraplength=460,
        ).pack(anchor="w", pady=(0, 6))

        ttk.Label(
            frame,
            text="Para usar la IA local (manuscritos, lectura fácil, traducción y Q&A), "
                 "elige desde dónde deseas descargar los ficheros GGUF (~2,9 GB):",
            font=self._get_font_tuple(size_delta=-1),
            wraplength=460,
        ).pack(anchor="w", pady=(0, 14))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X)

        def pick(src):
            result["source"] = src
            dialog.destroy()

        ttk.Button(
            btn_frame,
            text="🌐 Página Oficial (Hugging Face)",
            command=lambda: pick("official"),
        ).pack(fill=tk.X, pady=3)

        ttk.Button(
            btn_frame,
            text="🐙 Proyecto GitHub (Ydalgo/Open-OCReader)",
            command=lambda: pick("github"),
        ).pack(fill=tk.X, pady=3)

        ttk.Button(btn_frame, text="Cancelar", command=dialog.destroy).pack(fill=tk.X, pady=(6, 0))

        self.root.wait_window(dialog)
        return result["source"]

    def _on_closing(self):
        """Detiene locuciones TTS y libera el servidor llama.cpp al cerrar la ventana."""
        try:
            self.tts.stop()
        except Exception:
            pass
        try:
            from .ai import LlamaRuntimeManager
            LlamaRuntimeManager.get_instance().stop_server()
        except Exception:
            pass
        self.root.destroy()

    def _ai_worker(self, in_path: str, action: str, question: str, use_handwriting: bool):
        try:
            from .ai import (
                LlamaRuntimeManager,
                DocumentAnonymizer,
                DocumentTranslator,
                DocumentQA,
                HandwritingOCREngine,
            )

            def update_status(msg: str):
                self.root.after(0, self.ai_status_var.set, msg)

            from .ai.doc_cache import DocumentIndexCache
            from .ai.doc_tree import ArbolNodosDocumento

            runtime = LlamaRuntimeManager.get_instance()
            use_force_ocr = self.ai_force_ocr_var.get()
            cache_key = (in_path, use_handwriting, use_force_ocr)
            mode_key = f"hw={int(use_handwriting)}_focr={int(use_force_ocr)}"

            # Paso 1: Recuperar desde memoria RAM o caché persistente SQLite WAL+zstd/zlib (SHA-256)
            if self.cached_doc_key == cache_key and self.cached_doc_text is not None and self.cached_doc_tree is not None:
                doc_text = self.cached_doc_text
                doc_tree = self.cached_doc_tree
            else:
                disk_cache = DocumentIndexCache.get_instance()
                cached_hit = disk_cache.get(in_path, mode_key=mode_key)
                if cached_hit is not None:
                    doc_text, doc_tree = cached_hit
                    update_status(
                        f"✓ Recuperado desde caché AST comprimida ({len(doc_tree.nodos)} nodos, 0 ms OCR)."
                    )
                else:
                    update_status("Paso 1: Analizando documento y extrayendo texto...")
                    t0 = time.perf_counter()
                    doc_text, stats = DocumentLoader.extract_text_smart(
                        in_path,
                        handwriting=use_handwriting,
                        force_ocr=use_force_ocr,
                        progress_cb=update_status,
                    )
                    update_status("Construyendo Árbol AST documental y guardando en caché comprimida...")
                    doc_tree = ArbolNodosDocumento.construir_desde_texto(
                        doc_text,
                        titulo=Path(in_path).stem,
                    )
                    # Si el documento es extenso y el perfil de hardware soporta embeddings, vectorizar nodos AST una sola vez
                    if len(doc_text) > 9500 and runtime.tier.embed_enabled:
                        update_status(f"Vectorizando {len(doc_tree.nodos)} nodos AST con {runtime.tier.embed_label}...")
                        doc_tree.indexar_embeddings(lambda batch: runtime.embed_texts(batch, progress_cb=update_status))
                    disk_cache.put(in_path, doc_text, doc_tree, mode_key=mode_key)
                    dt = time.perf_counter() - t0
                    logger.info(
                        f"Extracción + Árbol AST completados en {dt:.2f}s ({len(doc_text)} chars, "
                        f"{len(doc_tree.nodos)} nodos, nativas={stats['native_pages']}, ocr={stats['ocr_pages']})."
                    )

                self.cached_doc_text = doc_text
                self.cached_doc_tree = doc_tree
                self.cached_doc_key = cache_key

            from datetime import datetime
            from .ai.multi_doc_chat import ChatReference, ChatTurnRecord

            response_lang = get_llm_language_name(self.ui_lang)
            target_translate_lang = self.translate_lang_var.get().strip() or response_lang
            fname = Path(in_path).name
            ts_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            turn_record = None

            if action == "transcribe":
                output_text = doc_text
                turn_record = ChatTurnRecord(
                    question="Transcripción completa del documento",
                    answer=output_text,
                    references=[],
                    timestamp=ts_now,
                )
            elif action == "summarize":
                output_text = DocumentQA(runtime).summarize(
                    doc_text, response_lang=response_lang, progress_cb=update_status, doc_tree=doc_tree
                )
                turn_record = ChatTurnRecord(
                    question="Resumen ejecutivo del documento",
                    answer=output_text,
                    references=[
                        ChatReference(
                            ref_id="REF-1",
                            doc_id="DOC-1",
                            file_name=fname,
                            section_path="Documento fuente",
                            score=1.0,
                            excerpt=doc_text[:180],
                            literal_text=doc_text.strip()[:8000],
                        )
                    ],
                    timestamp=ts_now,
                )
            elif action == "easy_read":
                output_text = DocumentQA(runtime).summarize_easy_read(
                    doc_text, response_lang=response_lang, progress_cb=update_status, doc_tree=doc_tree
                )
                turn_record = ChatTurnRecord(
                    question="Adaptación a Lectura Fácil (Norma UNE 153101 EX)",
                    answer=output_text,
                    references=[
                        ChatReference(
                            ref_id="REF-1",
                            doc_id="DOC-1",
                            file_name=fname,
                            section_path="Documento fuente",
                            score=1.0,
                            excerpt=doc_text[:180],
                            literal_text=doc_text.strip()[:8000],
                        )
                    ],
                    timestamp=ts_now,
                )
            elif action == "translate":
                output_text = DocumentTranslator(runtime).translate(
                    doc_text, target_lang=target_translate_lang, progress_cb=update_status
                )
                turn_record = ChatTurnRecord(
                    question=f"Traducción contextual a {target_translate_lang}",
                    answer=output_text,
                    references=[
                        ChatReference(
                            ref_id="REF-1",
                            doc_id="DOC-1",
                            file_name=fname,
                            section_path="Texto original completo",
                            score=1.0,
                            excerpt=doc_text[:180],
                            literal_text=doc_text.strip()[:8000],
                        )
                    ],
                    timestamp=ts_now,
                )
            elif action == "anonymize":
                output_text = DocumentAnonymizer(runtime).anonymize(doc_text, progress_cb=update_status)
                turn_record = ChatTurnRecord(
                    question="Anonimización RGPD del documento",
                    answer=output_text,
                    references=[],
                    timestamp=ts_now,
                )
            elif action == "ask":
                ans, refs = DocumentQA(runtime).ask_with_references(
                    doc_text,
                    question,
                    response_lang=response_lang,
                    progress_cb=update_status,
                    doc_tree=doc_tree,
                    file_name=fname,
                )
                turn_record = ChatTurnRecord(
                    question=question,
                    answer=ans,
                    references=refs,
                    timestamp=ts_now,
                )
                ref_lines = []
                if refs:
                    ref_lines.append("\n\n📚 REFERENCIAS LITERALES EXTRAÍDAS DEL DOCUMENTO ORIGINAL:")
                    for r in refs:
                        ref_lines.append(
                            f"\n• [{r.doc_id} / {r.ref_id}] {r.file_name} — {r.section_path}\n"
                            f"«{(r.literal_text or r.excerpt).strip()}»"
                        )
                output_text = ans + "\n".join(ref_lines)
            else:
                output_text = doc_text

            self.root.after(0, self._on_ai_success, output_text, turn_record)
        except Exception as e:
            logger.exception(f"Error en acción IA '{action}' para '{in_path}': {e}")
            self.root.after(0, self._on_ai_error, str(e))

    def _on_ai_success(self, result_text: str, turn_record=None):
        self.ai_progress.stop()
        for b in self.ai_buttons:
            b.config(state=tk.NORMAL)
        if turn_record is not None:
            self.last_ai_turn_record = turn_record
            self.ai_turn_records.append(turn_record)
        self.ai_output_text.delete("1.0", tk.END)
        self.ai_output_text.insert("1.0", result_text)
        self.ai_status_var.set("✓ Proceso de IA completado con éxito.")
        if self.a11y.voice_guidance:
            self._speak_text(result_text)

    def _on_ai_error(self, err_msg: str):
        self.ai_progress.stop()
        for b in self.ai_buttons:
            b.config(state=tk.NORMAL)
        self.ai_status_var.set(f"Error en IA: {err_msg}")
        self._announce(f"Error en IA: {err_msg}")
        messagebox.showerror("Error de IA", f"Ocurrió un error al ejecutar la IA:\n\n{err_msg}")

    def _copy_selection(self, event=None):
        try:
            selected = self.ai_output_text.get(tk.SEL_FIRST, tk.SEL_LAST)
            if selected:
                self.root.clipboard_clear()
                self.root.clipboard_append(selected)
                self.ai_status_var.set("✓ Selección copiada al portapapeles.")
        except tk.TclError:
            # Si no hay texto seleccionado, copiar todo
            self._copy_ai_output()
        return "break"

    def _select_all_output(self, event=None):
        self.ai_output_text.tag_add(tk.SEL, "1.0", tk.END)
        self.ai_output_text.mark_set(tk.INSERT, "1.0")
        self.ai_output_text.see(tk.INSERT)
        return "break"

    def _show_text_context_menu(self, event):
        try:
            self.text_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.text_context_menu.grab_release()

    def _copy_ai_output(self):
        content = self.ai_output_text.get("1.0", tk.END).strip()
        if content:
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.ai_status_var.set("✓ Resultado copiado al portapapeles.")

    def _save_ai_output(self):
        content = self.ai_output_text.get("1.0", tk.END).strip()
        if not content:
            return
        chosen = filedialog.asksaveasfilename(
            title="Guardar resultado de IA",
            defaultextension=".txt",
            filetypes=[("Archivo de texto (*.txt)", "*.txt"), ("Markdown (*.md)", "*.md")],
        )
        if chosen:
            Path(chosen).write_text(content, encoding="utf-8")
            self.ai_status_var.set(f"✓ Guardado en: {chosen}")

    def _export_ai_output_with_refs(self):
        """Exporta las preguntas/resultados de la pestaña IA con sus referencias literales al formato elegido."""
        content = self.ai_output_text.get("1.0", tk.END).strip()
        turns = list(self.ai_turn_records)
        if not turns and self.last_ai_turn_record is not None:
            turns = [self.last_ai_turn_record]
        if not turns and not content:
            messagebox.showinfo(
                "Sin resultados",
                "Realiza una consulta, resumen o traducción primero para exportarlo al formato deseado.",
            )
            return
        if not turns and content:
            from datetime import datetime
            from .ai.multi_doc_chat import ChatTurnRecord
            turns = [
                ChatTurnRecord(
                    question="Resultado generado en pantalla",
                    answer=content,
                    references=[],
                    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
            ]

        try:
            in_val = self.input_path_var.get().strip()
            fname = Path(in_val).name if in_val else "Documento"
            stem = f"{Path(in_val).stem}_consulta_referencias" if in_val else "Consulta_IA_Referencias"
            out = self._export_turns_dialog(
                turns=turns,
                fmt_label=self.ai_export_fmt_var.get(),
                default_stem=stem,
                title=f"Informe de Consulta e IA con Referencias Literales — {fname}",
                docs_summary=[f"[DOC-1] {fname}"] if in_val else None,
            )
            if out:
                self.ai_status_var.set(f"✓ Exportado con referencias literales: {Path(out).name}")
                if messagebox.askyesno("Exportación completada", f"Archivo generado:\n{out}\n\n¿Deseas abrirlo ahora?"):
                    self._open_path_crossplatform(out)
        except Exception as e:
            logger.exception(f"Error exportando consulta IA: {e}")
            messagebox.showerror("Error al exportar", f"No se pudo exportar el informe:\n{e}")

    def _open_file(self):
        if self.last_generated_file and Path(self.last_generated_file).exists():
            self._open_path_crossplatform(self.last_generated_file)

    def _open_folder(self):
        if self.last_generated_file:
            self._open_path_crossplatform(str(Path(self.last_generated_file).parent))

    def _open_logs(self):
        logs_dir = get_logs_dir()
        log_file = logs_dir / "open_ocreader.log"
        if log_file.exists():
            self._open_path_crossplatform(str(log_file))
        else:
            self._open_path_crossplatform(str(logs_dir))

    def _show_legal_compliance(self):
        """Muestra el aviso de cumplimiento de normativas de IA, privacidad, GuarIdA y licencia libre GNU GPL v3.0."""
        win = tk.Toplevel(self.root)
        win.title("Cumplimiento Normativo de IA, Créditos GuarIdA y Licencia Libre — Open OCReader")
        win.geometry("740x600")
        win.configure(bg=self.palette["bg"])
        win.transient(self.root)

        frame = ttk.Frame(win, padding="14")
        frame.pack(fill=tk.BOTH, expand=True)

        scroll = ttk.Scrollbar(frame)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        txt = tk.Text(
            frame,
            wrap=tk.WORD,
            font=self._get_font_tuple(),
            bg=self.palette["input_bg"],
            fg=self.palette["input_fg"],
            yscrollcommand=scroll.set,
            padx=10,
            pady=10,
        )
        txt.pack(fill=tk.BOTH, expand=True)
        scroll.config(command=txt.yview)

        info_text = (
            "1. CUMPLIMIENTO DE NORMATIVAS DE IA Y PRIVACIDAD\n"
            "============================================================\n"
            "Open OCReader opera 100% EN LOCAL (offline / on-premise), sin enviar\n"
            "documentos ni datos personales a servidores externos ni a la nube.\n\n"
            "• Reglamento Europeo de IA (EU AI Act — Reglamento (UE) 2024/1689):\n"
            "  Herramienta auxiliar de productividad documental (riesgo mínimo/limitado).\n"
            "  Se separa el OCR determinista (RapidOCR) de la IA generativa (Qwen3-VL).\n"
            "  IMPORTANTE: Toda salida de IA (resumen, traducción, Q&A o anonimización)\n"
            "  requiere supervisión humana (Human-in-the-Loop) antes de su uso oficial.\n\n"
            "• RGPD (UE) y LOPDGDD (España):\n"
            "  Cumple privacidad desde el diseño (Art. 25) y evita transferencias\n"
            "  internacionales de datos. La anonimización asistida debe validarse\n"
            "  siempre por el responsable del tratamiento antes de publicar documentos.\n\n"
            "• Administración Pública y ENS (Esquema Nacional de Seguridad):\n"
            "  Apto para redes aisladas (air-gapped), con verificación SHA-256,\n"
            "  logs auditables y API autenticada con clave de acceso.\n\n"
            "• Accesibilidad Universal (UNE 153101 EX y WCAG AAA):\n"
            "  Incluye escalado global (90%-180%), temas de alto contraste >15:1,\n"
            "  tipografía cómoda para dislexia, Lectura Fácil IA, lectura por voz TTS\n"
            "  100% offline y navegación íntegra por teclado.\n\n"
            "• Estándares Internacionales (NIST AI RMF, HIPAA, CCPA, ISO/IEC 42001):\n"
            "  Arquitectura abierta, auditable y libre de telemetría.\n\n"
            "2. LICENCIA DE SOFTWARE LIBRE (GNU GPL v3.0 — COPYLEFT)\n"
            "============================================================\n"
            "Open OCReader es Código Libre bajo GNU General Public License v3.0\n"
            "(https://www.gnu.org/licenses/gpl-3.0.html).\n\n"
            "• Uso libre: Permitido en ámbito personal, empresas y Administración.\n"
            "• Atribución obligatoria: Debe mantenerse siempre el reconocimiento\n"
            "  expreso a los autores originales (Ydalgo y colaboradores).\n"
            "• Copyleft fuerte (Compartir Igual): Si reproduces, modificas o creas\n"
            "  una versión derivada de este software, DEBES distribuirla también\n"
            "  como código libre bajo la misma licencia GNU GPL v3.0.\n"
            "  No está permitido cerrar el código en un producto privativo.\n\n"
            "3. CRÉDITOS Y PROYECTO HERMANO: GUARIDA\n"
            "============================================================\n"
            "Gran parte de la arquitectura técnica, la optimización de hardware\n"
            "y la ingeniería de contexto de Open OCReader provienen directamente de\n"
            "las investigaciones, decisiones técnicas y código del proyecto hermano:\n\n"
            "🛡️ GUARIDA: Guardián de Identidad y Asistencia con IA Local Soberana\n"
            "Repositorio oficial: https://github.com/Ydalgo/GuarIdA\n\n"
            "Componentes y estructuras transferidas desde GuarIdA:\n"
            "• Árbol de Nodos Documental (AST): Descomposición jerárquica de documentos\n"
            "  (secciones, tablas y bloques) eliminando el límite de contexto del LLM.\n"
            "• Compresión de Vocabulario BPE: Minificación de tokens para alta densidad.\n"
            "• Recuperación Híbrida RRF: Fusión de ranking léxico BM25 + Embeddings BGE-M3.\n"
            "• Persistencia Segregada SQLite WAL: Con compresión zstd/zlib por SHA-256.\n"
            "• Observador de Hardware en tiempo real y perfiles dinámicos adaptativos.\n"
            "• Reutilización de KV Cache (cache_prompt) para respuestas inmediatas.\n\n"
            "👉 ¡Te invito a pasarte por mi proyecto GuarIdA, echarle un vistazo y seguir su evolución!\n"
            "Actualmente lo sigo desarrollando activamente para impulsar la soberanía y privacidad documental.\n\n"
            "4. EXENCIÓN DE RESPONSABILIDAD SOBRE EL MODELO DE IA\n"
            "============================================================\n"
            "• Integridad de Pesos Oficiales: Open OCReader ejecuta modelos abiertos oficiales\n"
            "  (Qwen3-VL de Alibaba y BGE-M3 de BAAI). El autor NO modifica, NO altera,\n"
            "  NO entrena ni interviene los pesos originales de los modelos neuronales.\n"
            "• Descargo de Responsabilidad: El autor (Ydalgo) no se hace responsable de las\n"
            "  respuestas, opiniones, redacciones imprecisas, alucinaciones o expresiones\n"
            "  inadecuadas que el modelo de lenguaje de terceros pudiera formular.\n"
            "• Rieles Éticos (Prompt Madre): Se ha integrado un sistema estricto de salvaguardas\n"
            "  institucionales con rieles de cortesía, neutralidad absoluta y rigor analítico\n"
            "  para garantizar que el modelo mantenga siempre un tono respetuoso y profesional.\n"
            "• Supervisión Humana (Human-in-the-Loop): Es responsabilidad ineludible del usuario\n"
            "  verificar y validar toda salida generada por la IA antes de su utilización oficial.\n"
        )
        txt.insert("1.0", info_text)
        txt.config(state=tk.DISABLED)

        btn_bar = ttk.Frame(win)
        btn_bar.pack(fill=tk.X, padx=14, pady=(6, 12))

        ttk.Button(
            btn_bar,
            text="📑 Generar Informe de Gobernanza IA (1 clic)",
            command=lambda: self._export_governance_report(win),
        ).pack(side=tk.LEFT)
        ttk.Button(
            btn_bar,
            text="🛡️ Conocer proyecto GuarIdA (GitHub)",
            command=lambda: webbrowser.open("https://github.com/Ydalgo/GuarIdA"),
        ).pack(side=tk.LEFT, padx=8)
        ttk.Button(btn_bar, text="🔊 Leer", command=lambda: self._speak_text(info_text)).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_bar, text="Cerrar", command=win.destroy).pack(side=tk.RIGHT)

    def _export_governance_report(self, parent_win=None):
        chosen = filedialog.asksaveasfilename(
            parent=parent_win or self.root,
            title="Guardar Informe de Gobernanza de IA y ENS",
            initialfile="Informe_Gobernanza_IA_OpenOCReader.docx",
            defaultextension=".docx",
            filetypes=[
                ("Documento Word (*.docx)", "*.docx"),
                ("Markdown (*.md)", "*.md"),
                ("JSON estructurado (*.json)", "*.json"),
            ],
        )
        if not chosen:
            return
        try:
            from .governance import generate_governance_report
            out_path = generate_governance_report(chosen)
            self.status_var.set(f"✓ Informe de gobernanza generado en: {out_path}")
            if messagebox.askyesno(
                "Informe generado",
                f"Informe de Gobernanza de IA generado con éxito:\n{out_path}\n\n¿Deseas abrirlo ahora?",
                parent=parent_win or self.root,
            ):
                self._open_path_crossplatform(out_path)
        except Exception as e:
            logger.exception(f"Error generando informe de gobernanza: {e}")
            messagebox.showerror("Error", f"No se pudo generar el informe:\n{e}", parent=parent_win or self.root)

    def _clear_cache_gui(self):
        from .maintenance import clear_cache
        self.cached_doc_text = None
        self.cached_doc_key = None
        res = clear_cache()
        self.status_var.set(f"✓ Caché limpiada ({res['deleted']} elementos eliminados).")
        messagebox.showinfo("Caché limpiada", f"Se han eliminado {res['deleted']} elementos temporales y de caché.")

    def _clear_logs_gui(self):
        if not messagebox.askyesno("Borrar Logs", "¿Deseas vaciar todos los archivos de registro (logs)?"):
            return
        from .maintenance import clear_logs
        res = clear_logs()
        self.status_var.set("✓ Logs limpiados correctamente.")
        messagebox.showinfo(
            "Logs limpiados",
            f"Logs truncados: {res['truncated']} | Copias antiguas eliminadas: {res['removed']}",
        )

    def _check_updates_gui(self):
        from . import __version__
        from .ai import LlamaRuntimeManager
        from .updater import check_for_updates, apply_update

        self.status_var.set("Consultando actualizaciones de código y llama.cpp en GitHub...")

        def worker():
            info = check_for_updates(__version__)
            rt = LlamaRuntimeManager.get_instance()
            llama_info = rt.check_llama_update()

            def on_result():
                llama_msg = (
                    f"Motor llama.cpp: versión instalada '{llama_info['installed']}' → nueva '{llama_info['latest']}' disponible."
                    if llama_info["update_available"]
                    else f"Motor llama.cpp: al día ({llama_info['latest']})."
                )
                self.status_var.set(f"{info.message} | {llama_msg}")

                if info.update_available or llama_info["update_available"]:
                    if messagebox.askyesno(
                        "Actualización disponible",
                        f"{info.message}\n{llama_msg}\n\n¿Deseas actualizar ahora sin perder tus modelos?",
                    ):
                        try:
                            msgs = []
                            if info.update_available:
                                msgs.append(apply_update())
                            if llama_info["update_available"]:
                                from .maintenance import clean_and_reinstall
                                clean_and_reinstall(
                                    clean_builds=False,
                                    reinstall_llama=True,
                                    reinstall_models=False,
                                    upgrade_deps=False,
                                )
                                msgs.append(f"✓ llama.cpp actualizado a {llama_info['latest']}.")
                            messagebox.showinfo("Actualizado", "\n".join(msgs) + "\n\nReinicia la app para aplicar los cambios.")
                        except Exception as e:
                            messagebox.showerror("Error al actualizar", str(e))
                else:
                    messagebox.showinfo("Actualizaciones", f"{info.message}\n\n{llama_msg}")
            self.root.after(0, on_result)

        threading.Thread(target=worker, daemon=True).start()

    def _open_clean_reinstall_dialog(self):
        """Ventana para limpiar compilaciones antiguas (build, dist, bin) y reinstalar limpiamente."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Limpiar Proyecto y Reinstalar Componentes")
        dialog.geometry("540x340")
        dialog.configure(bg=self.palette["bg"])
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding="16")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text="Selecciona qué deseas limpiar y reinstalar:",
            font=self._get_font_tuple(bold=True),
        ).pack(anchor="w", pady=(0, 10))

        v_builds = tk.BooleanVar(value=True)
        v_llama = tk.BooleanVar(value=True)
        v_deps = tk.BooleanVar(value=True)
        v_models = tk.BooleanVar(value=False)

        ttk.Checkbutton(frame, text="Eliminar compilaciones antiguas (build/, dist/, *.spec) y cachés", variable=v_builds).pack(anchor="w", pady=3)
        ttk.Checkbutton(frame, text="Reinstalar última versión oficial de llama.cpp (bin/) con parches", variable=v_llama).pack(anchor="w", pady=3)
        ttk.Checkbutton(frame, text="Actualizar librerías Python (requirements.txt)", variable=v_deps).pack(anchor="w", pady=3)
        ttk.Checkbutton(frame, text="Re-descargar y verificar modelos de IA (models/ ~2,9 GB)", variable=v_models).pack(anchor="w", pady=3)

        status_lbl_var = tk.StringVar(value="Listo para limpiar y reinstalar.")
        st_lbl = ttk.Label(frame, textvariable=status_lbl_var, wraplength=480)
        st_lbl.configure(font=self._get_font_tuple(size_delta=-2), foreground=self.palette["muted"])
        st_lbl.pack(anchor="w", pady=(12, 6))

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=tk.X, pady=(6, 0))

        def run_clean():
            btn_go.config(state=tk.DISABLED)
            def worker():
                try:
                    from .maintenance import clean_and_reinstall
                    res = clean_and_reinstall(
                        clean_builds=v_builds.get(),
                        reinstall_llama=v_llama.get(),
                        reinstall_models=v_models.get(),
                        upgrade_deps=v_deps.get(),
                        progress_cb=lambda m: self.root.after(0, status_lbl_var.set, m),
                    )
                    def done():
                        self.cached_doc_text = None
                        self.cached_doc_key = None
                        msg = (
                            f"Eliminado: {', '.join(res['removed']) or 'nada'}\n"
                            f"Actualizado: {', '.join(res['updated']) or 'nada'}"
                        )
                        if res.get("killed_processes"):
                            msg += f"\nProcesos cerrados: {', '.join(res['killed_processes'])}"
                        if res.get("warnings"):
                            msg += "\n\nAvisos:\n- " + "\n- ".join(res["warnings"])
                            messagebox.showwarning("Limpieza con avisos", msg, parent=dialog)
                        else:
                            messagebox.showinfo("Limpieza completada", msg, parent=dialog)
                        dialog.destroy()
                    self.root.after(0, done)
                except Exception as e:
                    logger.exception(f"Error en limpieza y reinstalación: {e}")
                    self.root.after(0, lambda: messagebox.showerror("Error", str(e), parent=dialog))
                    self.root.after(0, lambda: btn_go.config(state=tk.NORMAL))
            threading.Thread(target=worker, daemon=True).start()

        btn_go = ttk.Button(btn_row, text="♻️ Ejecutar limpieza y reinstalación", command=run_clean)
        btn_go.pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Cancelar", command=dialog.destroy).pack(side=tk.RIGHT)

    # ---------------- SUITE DE ACCESIBILIDAD UNIVERSAL ----------------
    def _announce(self, text: str):
        """Anuncia estados relevantes por voz cuando está activa la guía de voz accesible."""
        if self._ui_ready and self.a11y.voice_guidance and text:
            self.tts.speak(text, rate=self.a11y.tts_rate)

    def _speak_text(self, text: str):
        """Lee un texto de forma asíncrona con el motor TTS offline del sistema."""
        if not text:
            return
        self._tts_speaking_active = True
        self.tts.speak(text, rate=self.a11y.tts_rate)

    def _stop_tts(self):
        """Detiene de inmediato la síntesis de voz en curso."""
        self._tts_speaking_active = False
        self.tts.stop()

    def _get_tts_active_text(self) -> str:
        """Determina el contenido más relevante de la pestaña activa (o la selección actual) para leerlo en voz alta."""
        for tw in (
            getattr(self, "ai_output_text", None),
            getattr(self, "chat_history_text", None),
            getattr(self, "anon_output_text", None),
        ):
            if tw is not None:
                try:
                    sel_txt = tw.get(tk.SEL_FIRST, tk.SEL_LAST).strip()
                    if sel_txt:
                        return sel_txt
                except tk.TclError:
                    pass

        try:
            cur_tab = self.notebook.select()
        except Exception:
            cur_tab = ""

        if cur_tab == str(getattr(self, "tab_chat", "")):
            if self.chat_engine is not None and getattr(self.chat_engine, "turn_records", None):
                last_turn = self.chat_engine.turn_records[-1]
                return last_turn.answer or self.chat_status_var.get()
            if hasattr(self, "chat_history_text"):
                txt = self.chat_history_text.get("1.0", tk.END).strip()
                if txt:
                    return txt
            return self.chat_status_var.get()

        if cur_tab == str(getattr(self, "tab_ai", "")):
            if hasattr(self, "ai_output_text"):
                txt = self.ai_output_text.get("1.0", tk.END).strip()
                if txt:
                    return txt
            return self.ai_status_var.get()

        if cur_tab == str(getattr(self, "tab_anonymize", "")):
            if hasattr(self, "anon_output_text"):
                txt = self.anon_output_text.get("1.0", tk.END).strip()
                if txt:
                    return txt
            return self.anon_status_var.get()

        if cur_tab == str(getattr(self, "tab_translate", "")):
            return self.trans_status_var.get()

        if self.tab_pdf_tools is not None and cur_tab == str(self.tab_pdf_tools):
            return self.pdf_tools_status_var.get()

        return self.status_var.get()

    def _speak_active_output(self):
        txt = self._get_tts_active_text()
        if txt:
            self._speak_text(txt)

    def _toggle_tts_active_tab(self):
        if self._tts_speaking_active:
            self._stop_tts()
        else:
            self._speak_active_output()

    def _toggle_high_contrast(self):
        """Alterna con un atajo (Ctrl+Shift+H) entre Alto Contraste Oscuro AAA y el modo automático."""
        if self.a11y.theme_mode == "high_contrast_dark":
            self.a11y.theme_mode = "auto"
            msg = "Tema visual restaurado a automático."
        else:
            self.a11y.theme_mode = "high_contrast_dark"
            msg = "Alto contraste WCAG AAA activado."
        self._refresh_all_themes_and_fonts()
        self.status_var.set(msg)
        self._announce(msg)

    def _select_tab_index(self, idx: int):
        try:
            tabs = self.notebook.tabs()
            if 0 <= idx < len(tabs):
                self.notebook.select(tabs[idx])
        except Exception:
            pass

    def _trigger_primary_tab_action(self):
        try:
            cur_tab = self.notebook.select()
        except Exception:
            return
        if cur_tab == str(getattr(self, "tab_convert", "")):
            self._start_conversion()
        elif cur_tab == str(getattr(self, "tab_translate", "")):
            if hasattr(self, "btn_translate_doc"):
                self._start_document_translation()
        elif cur_tab == str(getattr(self, "tab_chat", "")):
            if hasattr(self, "btn_chat_send"):
                self._chat_send()
        elif cur_tab == str(getattr(self, "tab_ai", "")):
            if self.question_var.get().strip():
                self._run_ai_action("ask")
            elif hasattr(self, "btn_ai_summarize"):
                self._run_ai_action("summarize")
        elif cur_tab == str(getattr(self, "tab_anonymize", "")):
            self._run_anonymize_standalone()

    def _setup_accessibility_shortcuts(self):
        """Registra atajos de teclado universales para uso sin ratón y lectores de pantalla."""
        self.root.bind_all("<MouseWheel>", self.scroll_root.handle_mousewheel)
        self.root.bind_all("<Button-4>", self.scroll_root.handle_mousewheel)
        self.root.bind_all("<Button-5>", self.scroll_root.handle_mousewheel)
        self.root.bind_all("<FocusIn>", lambda e: self.scroll_root.scroll_widget_into_view(e.widget))

        for seq in ("<Control-plus>", "<Control-KP_Add>", "<Control-equal>"):
            self.root.bind_all(seq, lambda e: (self._adjust_global_zoom(1), "break")[1])
        for seq in ("<Control-minus>", "<Control-KP_Subtract>"):
            self.root.bind_all(seq, lambda e: (self._adjust_global_zoom(-1), "break")[1])
        for seq in ("<Control-0>", "<Control-KP_0>"):
            self.root.bind_all(seq, lambda e: (self._reset_global_zoom(), "break")[1])

        for seq in ("<F2>", "<Alt-a>", "<Alt-A>"):
            self.root.bind_all(seq, lambda e: (self._open_accessibility_dialog(), "break")[1])
        for seq in ("<Control-Shift-L>", "<Control-Shift-l>"):
            self.root.bind_all(seq, lambda e: (self._toggle_tts_active_tab(), "break")[1])
        for seq in ("<Control-Shift-H>", "<Control-Shift-h>"):
            self.root.bind_all(seq, lambda e: (self._toggle_high_contrast(), "break")[1])
        for seq in ("<Control-o>", "<Control-O>"):
            self.root.bind_all(seq, lambda e: (self._browse_input(), "break")[1])
        for seq in ("<Control-Return>", "<Control-KP_Enter>"):
            self.root.bind_all(seq, lambda e: (self._trigger_primary_tab_action(), "break")[1])
        for i in range(1, 7):
            self.root.bind_all(f"<Alt-KeyPress-{i}>", lambda e, idx=i - 1: (self._select_tab_index(idx), "break")[1])

    def _open_accessibility_dialog(self):
        """Centro de Accesibilidad Universal: perfiles rápidos, contraste, dislexia, TTS y motricidad."""
        if getattr(self, "_a11y_win", None) is not None and self._a11y_win.winfo_exists():
            self._a11y_win.lift()
            self._a11y_win.focus_force()
            return

        dlg = tk.Toplevel(self.root)
        self._a11y_win = dlg
        dlg.title("♿ Centro de Accesibilidad Universal — Open OCReader")
        sw = dlg.winfo_screenwidth()
        sh = dlg.winfo_screenheight()
        dw = min(760, max(540, sw - 80))
        dh = min(680, max(500, sh - 90))
        dlg.geometry(f"{dw}x{dh}")
        dlg.minsize(480, 420)
        dlg.configure(bg=self.palette["bg"])
        dlg.transient(self.root)

        scroll_box = VerticalScrollableFrame(dlg, bg=self.palette["bg"])
        scroll_box.pack(fill=tk.BOTH, expand=True)
        body = ttk.Frame(scroll_box.inner, padding="14")
        body.pack(fill=tk.BOTH, expand=True)

        header_lbl = ttk.Label(
            body,
            text="♿ Adaptabilidad Universal (Visión, Cognición, Audición y Motricidad)",
            font=self._get_font_tuple(size_delta=2, bold=True),
            wraplength=dw - 60,
        )
        header_lbl.pack(anchor="w", pady=(0, 4))

        sub_lbl = ttk.Label(
            body,
            text="Todos los ajustes se aplican en vivo y se guardan localmente sin telemetría.",
            font=self._get_font_tuple(size_delta=-1, italic=True),
            foreground=self.palette["muted"],
            wraplength=dw - 60,
        )
        sub_lbl.pack(anchor="w", pady=(0, 10))

        # Variables sincronizadas con el diálogo
        theme_label_by_code = THEME_DISPLAY_LABELS
        code_by_theme_label = {v: k for k, v in THEME_DISPLAY_LABELS.items()}
        v_theme = tk.StringVar(value=theme_label_by_code.get(self.a11y.theme_mode, theme_label_by_code["auto"]))
        v_dyslexia = tk.BooleanVar(value=self.a11y.dyslexia_friendly)
        v_large = tk.BooleanVar(value=self.a11y.large_targets)
        v_voice = tk.BooleanVar(value=self.a11y.voice_guidance)
        v_rate = tk.IntVar(value=self.a11y.tts_rate)

        def sync_vars_from_cfg():
            v_theme.set(theme_label_by_code.get(self.a11y.theme_mode, theme_label_by_code["auto"]))
            v_dyslexia.set(self.a11y.dyslexia_friendly)
            v_large.set(self.a11y.large_targets)
            v_voice.set(self.a11y.voice_guidance)
            v_rate.set(self.a11y.tts_rate)

        relayout_cb = [lambda: None]

        def apply_controls(announce_msg: Optional[str] = None):
            self.a11y.theme_mode = code_by_theme_label.get(v_theme.get(), "auto")
            self.a11y.dyslexia_friendly = v_dyslexia.get()
            self.a11y.large_targets = v_large.get()
            self.a11y.voice_guidance = v_voice.get()
            self.a11y.tts_rate = int(v_rate.get())
            self.a11y.clamp()
            self.zoom_pct_var.set(f"{self.a11y.zoom_percent}%")
            self._refresh_all_themes_and_fonts()
            scroll_box.set_background(self.palette["bg"])
            dlg.configure(bg=self.palette["bg"])
            dlg.after_idle(relayout_cb[0])
            if announce_msg:
                self._speak_text(announce_msg)

        def apply_preset(preset: str):
            if preset == "standard":
                self.a11y.ui_font_size = 10
                self.a11y.text_font_size = 11
                self.a11y.theme_mode = "auto"
                self.a11y.dyslexia_friendly = False
                self.a11y.large_targets = False
                self.a11y.voice_guidance = False
                self.a11y.tts_rate = 0
                msg = None
            elif preset == "low_vision":
                self.a11y.ui_font_size = 14
                self.a11y.text_font_size = 16
                self.a11y.theme_mode = "high_contrast_dark"
                self.a11y.large_targets = True
                msg = "Perfil de baja visión activado: texto al 140% y alto contraste oscuro."
            elif preset == "screen_reader":
                self.a11y.voice_guidance = True
                self.a11y.large_targets = True
                self.a11y.tts_rate = 0
                msg = "Guía de voz local activada. Usa Alt 1 a 6 para cambiar de pestaña y Control Shift L para leer resultados."
            elif preset == "dyslexia":
                self.a11y.theme_mode = "dyslexia_cream"
                self.a11y.dyslexia_friendly = True
                self.a11y.ui_font_size = 12
                self.a11y.text_font_size = 13
                msg = None
            elif preset == "motor":
                self.a11y.large_targets = True
                self.a11y.ui_font_size = max(12, self.a11y.ui_font_size)
                self.a11y.text_font_size = max(13, self.a11y.text_font_size)
                msg = None
            else:
                msg = None
            self.text_font_size = self.a11y.text_font_size
            sync_vars_from_cfg()
            apply_controls(announce_msg=msg)

        # 1. Perfiles rápidos en un clic
        preset_grp = ttk.LabelFrame(body, text=" ⚡ Perfiles Rápidos en 1 Clic ", padding="8")
        preset_grp.pack(fill=tk.X, pady=(0, 8))
        p_flow = ResponsiveFlowFrame(preset_grp, hgap=6, vgap=6)
        p_flow.pack(fill=tk.X)
        p_flow.add_item(ttk.Button(p_flow, text="🖥️ Estándar (100%)", command=lambda: apply_preset("standard")))
        p_flow.add_item(ttk.Button(p_flow, text="👁️ Baja Visión (140% + AAA)", command=lambda: apply_preset("low_vision")))
        p_flow.add_item(ttk.Button(p_flow, text="🦯 Voz y Ceguera (TTS)", command=lambda: apply_preset("screen_reader")))
        p_flow.add_item(ttk.Button(p_flow, text="📖 Dislexia / Crema Cálida", command=lambda: apply_preset("dyslexia")))
        p_flow.add_item(ttk.Button(p_flow, text="🖐️ Botones Grandes / Motriz", command=lambda: apply_preset("motor")))

        # 2. Visión y Contraste
        vis_grp = ttk.LabelFrame(body, text=" 🎨 Visión, Contraste (WCAG AAA) y Escala Global ", padding="8")
        vis_grp.pack(fill=tk.X, pady=(0, 8))

        t_flow = ResponsiveFlowFrame(vis_grp, hgap=8, vgap=4)
        t_flow.pack(fill=tk.X, pady=(0, 6))
        t_flow.add_item(ttk.Label(t_flow, text="Perfil cromático:"))
        theme_cb = ttk.Combobox(
            t_flow,
            textvariable=v_theme,
            values=[THEME_DISPLAY_LABELS[k] for k in VALID_THEME_MODES],
            state="readonly",
            width=44,
        )
        theme_cb.bind("<<ComboboxSelected>>", lambda e: apply_controls())
        t_flow.add_item(theme_cb)

        z_flow = ResponsiveFlowFrame(vis_grp, hgap=6, vgap=4)
        z_flow.pack(fill=tk.X)
        z_flow.add_item(ttk.Label(z_flow, text="Tamaño global de interfaz y textos:"))
        z_flow.add_item(ttk.Button(z_flow, text="➖ Reducir (A-)", command=lambda: (self._adjust_global_zoom(-1), relayout_cb[0]())))
        z_flow.add_item(ttk.Button(z_flow, textvariable=self.zoom_pct_var, width=6, command=lambda: (self._reset_global_zoom(), relayout_cb[0]())))
        z_flow.add_item(ttk.Button(z_flow, text="➕ Ampliar (A+)", command=lambda: (self._adjust_global_zoom(1), relayout_cb[0]())))

        # 3. Cognitivo y Dislexia
        cog_grp = ttk.LabelFrame(body, text=" 📖 Accesibilidad Cognitiva y Dislexia ", padding="8")
        cog_grp.pack(fill=tk.X, pady=(0, 8))
        ttk.Checkbutton(
            cog_grp,
            text="Tipografía amiga para dislexia (OpenDyslexic si instalada / Verdana + interlineado amplio)",
            variable=v_dyslexia,
            command=apply_controls,
        ).pack(anchor="w")
        cog_tip_lbl = ttk.Label(
            cog_grp,
            text="Consejo: en la pestaña 'IA y Visión' dispones del botón '♿ Lectura Fácil' para adaptar textos "
                 "legales, médicos o administrativos según las pautas UNE 153101 EX.",
            font=self._get_font_tuple(size_delta=-2, italic=True),
            foreground=self.palette["accent"],
            wraplength=dw - 72,
        )
        cog_tip_lbl.pack(anchor="w", pady=(4, 0))

        # 4. Audio y Lectura por Voz
        tts_grp = ttk.LabelFrame(body, text=" 🔊 Lectura en Voz Alta Local (TTS Offline — Sin Nube) ", padding="8")
        tts_grp.pack(fill=tk.X, pady=(0, 8))
        ttk.Checkbutton(
            tts_grp,
            text="Activar guía de voz automática (anuncia pestañas, archivos cargados y respuestas generadas)",
            variable=v_voice,
            command=apply_controls,
        ).pack(anchor="w", pady=(0, 4))

        rate_flow = ResponsiveFlowFrame(tts_grp, hgap=8, vgap=4)
        rate_flow.pack(fill=tk.X)
        rate_flow.add_item(ttk.Label(rate_flow, text="Velocidad de voz:"))
        rate_flow.add_item(ttk.Radiobutton(rate_flow, text="Lenta (-2)", value=-2, variable=v_rate, command=apply_controls))
        rate_flow.add_item(ttk.Radiobutton(rate_flow, text="Normal (0)", value=0, variable=v_rate, command=apply_controls))
        rate_flow.add_item(ttk.Radiobutton(rate_flow, text="Rápida (+2)", value=2, variable=v_rate, command=apply_controls))
        rate_flow.add_item(
            ttk.Button(
                rate_flow,
                text="🔊 Probar lectura",
                command=lambda: self._speak_text(
                    "Open OCReader. Lector de voz local operativo con privacidad del cien por cien."
                ),
            )
        )
        rate_flow.add_item(ttk.Button(rate_flow, text="⏹️ Detener voz", command=self._stop_tts))

        # 5. Motricidad y Teclado
        mot_grp = ttk.LabelFrame(body, text=" 🖐️ Motricidad y Atajos Universales de Teclado ", padding="8")
        mot_grp.pack(fill=tk.X, pady=(0, 8))
        ttk.Checkbutton(
            mot_grp,
            text="Ampliar áreas clicables y bordes de foco (botones, pestañas y casillas anti-temblor)",
            variable=v_large,
            command=apply_controls,
        ).pack(anchor="w", pady=(0, 6))

        shortcuts_txt = (
            "Atajos globales disponibles sin ratón:\n"
            "  • Alt + 1..6 → Cambiar entre pestañas     • Alt + A / F2 → Abrir este Centro de Accesibilidad\n"
            "  • Ctrl + '+' / Ctrl + '-' / Ctrl + 0 → Zoom global (A+ / A- / 100%)\n"
            "  • Ctrl + Shift + L → Leer o detener lectura del texto activo     • Ctrl + Shift + H → Alto Contraste AAA\n"
            "  • Ctrl + O → Abrir fichero de entrada     • Ctrl + Enter → Ejecutar acción principal de la pestaña"
        )
        shortcuts_lbl = ttk.Label(
            mot_grp,
            text=shortcuts_txt,
            font=self._get_font_tuple(size_delta=-2, mono=True),
            foreground=self.palette["muted"],
            wraplength=dw - 72,
        )
        shortcuts_lbl.pack(anchor="w")

        foot = ttk.Frame(body)
        foot.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(foot, text="Cerrar y Guardar", command=dlg.destroy).pack(side=tk.RIGHT)

        def relayout_dlg():
            if not dlg.winfo_exists():
                return
            dlg.update_idletasks()
            cur_w = max(420, dlg.winfo_width() - 72)
            header_lbl.configure(font=self._get_font_tuple(size_delta=2, bold=True), wraplength=cur_w)
            sub_lbl.configure(
                font=self._get_font_tuple(size_delta=-1, italic=True),
                foreground=self.palette["muted"],
                wraplength=cur_w,
            )
            cog_tip_lbl.configure(
                font=self._get_font_tuple(size_delta=-2, italic=True),
                foreground=self.palette["accent"],
                wraplength=cur_w,
            )
            shortcuts_lbl.configure(
                font=self._get_font_tuple(size_delta=-2, mono=True),
                foreground=self.palette["muted"],
                wraplength=cur_w,
            )
            theme_cb.configure(font=self._get_font_tuple(size_delta=-1))
            for ff in (p_flow, t_flow, z_flow, rate_flow):
                ff.relayout(force=True)
            scroll_box.sync_scrollregion()

        relayout_cb[0] = relayout_dlg
        dlg.bind("<Configure>", lambda e: dlg.after_idle(relayout_dlg) if e.widget is dlg else None)
        dlg.after(50, relayout_dlg)

    @staticmethod
    def _open_path_crossplatform(path: str):
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)


def _acquire_single_instance_lock():
    """
    Garantiza modo de instancia única para Open OCReader.
    En Windows usa un Mutex nombrado del sistema; en Linux/macOS un fichero lock.
    Devuelve el handle del lock si se adquirió, o None si ya hay otra instancia abierta.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            mutex = kernel32.CreateMutexW(None, False, "Global\\OpenOCReader_SingleInstance_Mutex_v1")
            ERROR_ALREADY_EXISTS = 183
            if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
                if mutex:
                    kernel32.CloseHandle(mutex)
                return None
            return mutex
        except Exception:
            return True
    else:
        try:
            import fcntl
            lock_path = Path(tempfile.gettempdir()) / "open_ocreader.lock"
            fp = open(lock_path, "w", encoding="utf-8")
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fp
        except Exception:
            return None


def _focus_existing_window_windows():
    """Intenta traer al frente la ventana existente de Open OCReader en Windows."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "Open OCReader - Digitalización e IA Documental 100% Local")
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def launch_gui_tk():
    """Lanza la interfaz de respaldo ligero basada en Tkinter."""
    # Activar soporte HiDPI nativo en Windows para que las fuentes y ventanas respeten el escalado del SO
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    lock_handle = _acquire_single_instance_lock()
    if lock_handle is None:
        _focus_existing_window_windows()
        tmp_root = tk.Tk()
        tmp_root.withdraw()
        messagebox.showinfo(
            "Open OCReader ya está abierto",
            "Ya hay una instancia de Open OCReader en ejecución.\n"
            "Se ha activado el modo de instancia única para evitar conflictos con el motor de IA y los logs.",
        )
        tmp_root.destroy()
        return

    import atexit

    def _cleanup_on_exit():
        try:
            from .ai import LlamaRuntimeManager
            LlamaRuntimeManager.get_instance().stop_server()
        except Exception:
            pass
        if sys.platform == "win32" and isinstance(lock_handle, int):
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(lock_handle)
            except Exception:
                pass

    atexit.register(_cleanup_on_exit)

    root = tk.Tk()
    OpenOCReaderGUI(root)
    root.mainloop()


def launch_gui(engine: str = "auto"):
    """Lanza la interfaz gráfica principal (Qt 6 / PySide6 por defecto con respaldo Tkinter)."""
    selected = (engine or "auto").strip().lower()
    if selected == "auto":
        selected = os.environ.get("OPEN_OCREADER_GUI", "auto").strip().lower()
    if selected in {"auto", "qt", "qt6", "pyside6"}:
        try:
            from .gui_qt import launch_gui_qt
            launch_gui_qt()
            return
        except ImportError as e:
            if selected in {"qt", "qt6", "pyside6"}:
                logger.warning(f"PySide6 no disponible ({e}); usando respaldo Tkinter.")
            else:
                logger.info(f"PySide6 no detectado ({e}); iniciando interfaz Tkinter de respaldo.")
        except Exception as e:
            logger.exception(f"Fallo iniciando interfaz Qt 6 ({e}); cambiando a Tkinter.")
    launch_gui_tk()


if __name__ == "__main__":
    launch_gui()
