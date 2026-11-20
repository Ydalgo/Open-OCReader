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
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageDraw, ImageGrab, ImageTk
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
    """Renderiza un icono vectorial sobre un lienzo 4x (anti-aliased LANCZOS)."""
    hi = size * 4
    img = Image.new("RGBA", (hi, hi), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_fn(draw, hi)
    small = img.resize((size, size), Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(small, master=master)


def _build_supersampled_ui_icons(master: tk.Misc, dark_mode: bool) -> dict[str, ImageTk.PhotoImage]:
    """Genera iconos nítidos a todo color y carga el logotipo oficial de la cabecera."""
    icons: dict[str, ImageTk.PhotoImage] = {}

    # Logo oficial de cabecera (34x34 con esquinas limpias)
    ico_dir = _resolve_ico_dir()
    if ico_dir and (ico_dir / "Open_OCReader.png").exists():
        try:
            logo_pil = Image.open(ico_dir / "Open_OCReader.png").convert("RGBA")
            logo_pil = logo_pil.resize((34, 34), Image.Resampling.LANCZOS)
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
        "github": _d_github,
        "legal": _d_legal,
        "update": _d_update,
        "reinstall": _d_reinstall,
        "cache": _d_cache,
        "clear_logs": _d_clear_logs,
        "view_logs": _d_view_logs,
    }
    for key, fn in specs.items():
        icons[key] = _render_icon_photo(fn, master=master, size=16)
    return icons


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
        self.root.title("Open OCReader - Digitalización e IA Documental 100% Local")
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        win_w = min(1240, max(960, sw - 50))
        win_h = min(860, max(680, sh - 70))
        self.root.geometry(f"{win_w}x{win_h}")
        self.root.minsize(920, 640)
        self._window_icon_ref = None
        self._apply_window_icon()

        # Tema claro/oscuro sincronizado con el SO y fuentes legibles con Zoom (A-/A+ y Ctrl+Rueda)
        self.is_dark_mode = self._detect_os_dark_mode()
        self.text_font_size = 11
        self._zoomable_texts = []

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

        self._ui_icons = _build_supersampled_ui_icons(self.root, self.is_dark_mode)
        self._build_ui()
        self._setup_drag_and_drop()
        self._setup_clipboard_paste()
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

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
        """Aplica fuentes cómodas del sistema operativo y paleta adaptada a tema claro/oscuro."""
        import tkinter.font as tkfont

        # Escalar fuentes base del sistema para una lectura cómoda sin forzar la vista
        for fname in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                f = tkfont.nametofont(fname)
                f.configure(family="Segoe UI" if sys.platform == "win32" else f.actual("family"), size=10)
            except Exception:
                pass

        if self.is_dark_mode:
            self.palette = {
                "bg": "#1e1f22",
                "fg": "#e8eaed",
                "muted": "#b0b6bf",
                "accent": "#6cb4ff",
                "ok": "#6dd58c",
                "warn": "#f6c177",
                "input_bg": "#2b2d30",
                "input_fg": "#f1f3f4",
                "drop_bg": "#262a30",
                "drop_border": "#4c6ef5",
            }
            try:
                self.style.theme_use("clam")
            except Exception:
                pass
            p = self.palette
            self.root.configure(bg=p["bg"])
            self.style.configure(".", background=p["bg"], foreground=p["fg"], font=("Segoe UI", 10))
            self.style.configure("TFrame", background=p["bg"])
            self.style.configure("TLabelframe", background=p["bg"], foreground=p["fg"])
            self.style.configure("TLabelframe.Label", background=p["bg"], foreground=p["accent"], font=("Segoe UI", 10, "bold"))
            self.style.configure("TLabel", background=p["bg"], foreground=p["fg"])
            self.style.configure("TCheckbutton", background=p["bg"], foreground=p["fg"])
            self.style.configure("TRadiobutton", background=p["bg"], foreground=p["fg"])
            self.style.configure("TButton", background="#35383e", foreground=p["fg"], padding=(5, 2))
            self.style.map("TButton", background=[("active", "#464b54")])
            self.style.configure("TEntry", fieldbackground=p["input_bg"], foreground=p["input_fg"])
            self.style.configure("TCombobox", fieldbackground=p["input_bg"], foreground=p["input_fg"])
            self.style.configure("TNotebook", background=p["bg"])
            self.style.configure("TNotebook.Tab", background="#2b2d30", foreground=p["fg"], padding=(6, 3))
            self.style.map("TNotebook.Tab", background=[("selected", "#3c4048")], foreground=[("selected", p["accent"])])
        else:
            self.palette = {
                "bg": "#f5f6f8",
                "fg": "#1a1a1a",
                "muted": "#4f5560",
                "accent": "#1a5fb4",
                "ok": "#1e6b1e",
                "warn": "#8a4b00",
                "input_bg": "#ffffff",
                "input_fg": "#111111",
                "drop_bg": "#f0f4fa",
                "drop_border": "#88a8d0",
            }
            try:
                self.style.theme_use("vista" if "vista" in self.style.theme_names() else "clam")
            except Exception:
                pass
            self.style.configure(".", font=("Segoe UI", 10))
            self.style.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"))
            self.style.configure("TButton", padding=(5, 2))
            self.style.configure("TNotebook.Tab", padding=(6, 3))

    def _register_zoomable_text(self, text_widget: tk.Text, family: str = "Segoe UI"):
        """Registra un área de texto para permitir zoom con botones A-/A+ y Ctrl + Rueda del ratón."""
        p = self.palette
        text_widget.configure(
            font=(family, self.text_font_size),
            bg=p["input_bg"],
            fg=p["input_fg"],
            insertbackground=p["input_fg"],
        )
        self._zoomable_texts.append((text_widget, family))
        text_widget.bind("<Control-MouseWheel>", self._on_ctrl_mousewheel)
        text_widget.bind("<Control-Button-4>", lambda e: self._adjust_text_zoom(1))
        text_widget.bind("<Control-Button-5>", lambda e: self._adjust_text_zoom(-1))

    def _on_ctrl_mousewheel(self, event):
        delta = 1 if event.delta > 0 else -1
        self._adjust_text_zoom(delta)
        return "break"

    def _adjust_text_zoom(self, delta: int):
        new_size = max(9, min(24, self.text_font_size + delta))
        if new_size == self.text_font_size:
            return
        self.text_font_size = new_size
        for widget, family in self._zoomable_texts:
            try:
                widget.configure(font=(family, self.text_font_size))
                if widget is getattr(self, "chat_history_text", None):
                    widget.tag_configure("user_lbl", font=("Segoe UI", self.text_font_size, "bold"))
                    widget.tag_configure("ai_lbl", font=("Segoe UI", self.text_font_size, "bold"))
                    widget.tag_configure("ref_lbl", font=("Segoe UI", max(9, self.text_font_size - 1), "bold"))
                    widget.tag_configure("ref_body", font=("Consolas", max(9, self.text_font_size - 1)))
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

    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding="10 8 10 8")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Cabecera común: logo + título + subtítulo a la izquierda; barra en 2 filas a la derecha (sin recortes HiDPI)
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 6))

        brand_col = ttk.Frame(header_frame)
        brand_col.pack(side=tk.LEFT, fill=tk.Y)

        brand_top = ttk.Frame(brand_col)
        brand_top.pack(anchor="w")
        logo_ic = self._ui_icons.get("logo")
        if logo_ic is not None:
            ttk.Label(brand_top, image=logo_ic).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(brand_top, text="Open OCReader", font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT)

        self.subtitle_lbl = ttk.Label(
            brand_col,
            text=tr(self.ui_lang, "subtitle"),
            font=("Segoe UI", 8),
            foreground=self.palette["muted"],
            wraplength=560,
        )
        self.subtitle_lbl.pack(anchor="w", pady=(2, 0))

        tools_col = ttk.Frame(header_frame)
        tools_col.pack(side=tk.RIGHT, anchor="ne")

        tools_row1 = ttk.Frame(tools_col)
        tools_row1.pack(anchor="e", pady=(0, 3))

        self.lang_combo = ttk.Combobox(
            tools_row1,
            textvariable=self.ui_lang_var,
            values=[name for _code, name in SUPPORTED_UI_LANGUAGES],
            state="readonly",
            width=9,
        )
        self.lang_combo.pack(side=tk.LEFT, padx=(0, 4))
        self.lang_combo.bind("<<ComboboxSelected>>", self._on_ui_language_changed)

        self.btn_github = ttk.Button(
            tools_row1,
            text=_strip_leading_emoji(tr(self.ui_lang, "btn_github")),
            command=lambda: webbrowser.open(GITHUB_REPO_URL),
            **self._icon_kwargs("github"),
        )
        self.btn_github.pack(side=tk.LEFT, padx=2)
        ttk.Button(tools_row1, text="A-", width=3, command=lambda: self._adjust_text_zoom(-1)).pack(side=tk.LEFT, padx=1)
        ttk.Button(tools_row1, text="A+", width=3, command=lambda: self._adjust_text_zoom(1)).pack(side=tk.LEFT, padx=(1, 3))
        self.btn_legal = ttk.Button(
            tools_row1,
            text=_strip_leading_emoji(tr(self.ui_lang, "btn_legal")),
            command=self._show_legal_compliance,
            **self._icon_kwargs("legal"),
        )
        self.btn_legal.pack(side=tk.LEFT, padx=2)

        tools_row2 = ttk.Frame(tools_col)
        tools_row2.pack(anchor="e")

        self.btn_update = ttk.Button(
            tools_row2,
            text=_strip_leading_emoji(tr(self.ui_lang, "btn_update")),
            command=self._check_updates_gui,
            **self._icon_kwargs("update"),
        )
        self.btn_update.pack(side=tk.LEFT, padx=2)
        self.btn_reinstall = ttk.Button(
            tools_row2,
            text=_strip_leading_emoji(tr(self.ui_lang, "btn_reinstall")),
            command=self._open_clean_reinstall_dialog,
            **self._icon_kwargs("reinstall"),
        )
        self.btn_reinstall.pack(side=tk.LEFT, padx=2)
        self.btn_cache = ttk.Button(
            tools_row2,
            text=_strip_leading_emoji(tr(self.ui_lang, "btn_cache")),
            command=self._clear_cache_gui,
            **self._icon_kwargs("cache"),
        )
        self.btn_cache.pack(side=tk.LEFT, padx=2)
        self.btn_clear_logs = ttk.Button(
            tools_row2,
            text=_strip_leading_emoji(tr(self.ui_lang, "btn_clear_logs")),
            command=self._clear_logs_gui,
            **self._icon_kwargs("clear_logs"),
        )
        self.btn_clear_logs.pack(side=tk.LEFT, padx=2)
        self.btn_view_logs = ttk.Button(
            tools_row2,
            text=_strip_leading_emoji(tr(self.ui_lang, "btn_view_logs")),
            command=self._open_logs,
            **self._icon_kwargs("view_logs"),
        )
        self.btn_view_logs.pack(side=tk.LEFT, padx=(2, 0))

        # Selector de fichero común en la parte superior
        self.drop_frame = ttk.LabelFrame(main_frame, text=tr(self.ui_lang, "input_group"), padding="6")
        self.drop_frame.pack(fill=tk.X, pady=(0, 6))

        self.drop_canvas = tk.Canvas(
            self.drop_frame,
            bg=self.palette["drop_bg"],
            height=30,
            highlightthickness=1,
            highlightbackground=self.palette["drop_border"],
            relief="flat",
        )
        self.drop_canvas.pack(fill=tk.X, pady=(0, 4))

        self.drop_text_id = self.drop_canvas.create_text(
            350, 15,
            text=tr(self.ui_lang, "drop_prompt"),
            font=("Segoe UI", 9, "italic"),
            fill=self.palette["accent"],
            justify="center",
        )
        self.drop_canvas.bind("<Configure>", self._center_drop_text)
        self.drop_canvas.bind("<Button-1>", lambda e: self._browse_input())

        entry_row = ttk.Frame(self.drop_frame)
        entry_row.pack(fill=tk.X)

        self.input_entry = ttk.Entry(entry_row, textvariable=self.input_path_var, font=("Segoe UI", 9))
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
                ttk.Label(
                    main_frame,
                    text=mismatch_msg,
                    font=("Segoe UI", 8, "bold"),
                    foreground="#8a4b00",
                    wraplength=880,
                ).pack(anchor="w", pady=(0, 4))
        except Exception:
            pass

        # Pestañas (Notebook) adaptadas al hardware — estado independiente en segundo plano por pestaña
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
            text=f"{_strip_leading_emoji(tr(self.ui_lang, 'tab_convert'))} ",
            **self._icon_kwargs("tab_convert"),
        )
        self.notebook.add(
            self.tab_translate,
            text=f"{_strip_leading_emoji(tr(self.ui_lang, 'tab_translate'))} ",
            **self._icon_kwargs("tab_translate"),
        )
        self.notebook.add(
            self.tab_chat,
            text=" Chat Docs ",
            **self._icon_kwargs("tab_chat"),
        )
        self.notebook.add(
            self.tab_ai,
            text=f"{_strip_leading_emoji(tr(self.ui_lang, 'tab_ai'))} ",
            **self._icon_kwargs("tab_ai"),
        )
        self.notebook.add(
            self.tab_anonymize,
            text=" Anonimizar (RGPD) ",
            **self._icon_kwargs("tab_anonymize"),
        )
        if self.tab_pdf_tools is not None:
            self.notebook.add(
                self.tab_pdf_tools,
                text=f"{_strip_leading_emoji(tr(self.ui_lang, 'tab_pdf_tools'))} ",
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

        self.footer_lbl = ttk.Label(
            footer_bar,
            text=tr(self.ui_lang, "footer"),
            font=("Segoe UI", 8),
            foreground="#555555",
        )
        self.footer_lbl.pack(side=tk.LEFT)

        github_link = ttk.Label(
            footer_bar,
            text="GitHub: Ydalgo/Open-OCReader",
            font=("Segoe UI", 8, "underline"),
            foreground="#1a5fb4",
            cursor="hand2",
        )
        github_link.pack(side=tk.RIGHT)
        github_link.bind("<Button-1>", lambda e: webbrowser.open(GITHUB_REPO_URL))

    def _build_convert_tab(self):
        # Formato de salida limpio en 2 columnas sin saturación de texto
        self.format_group = ttk.LabelFrame(self.tab_convert, text=tr(self.ui_lang, "format_group"), padding="6")
        self.format_group.pack(fill=tk.X, pady=(0, 5))

        grid_frame = ttk.Frame(self.format_group)
        grid_frame.pack(fill=tk.X)
        grid_frame.columnconfigure(0, weight=1)
        grid_frame.columnconfigure(1, weight=1)

        self.format_widgets = {}
        for idx, (_label_text, fmt_key, _desc) in enumerate(self.FORMAT_OPTIONS):
            row_i = idx // 2
            col_i = idx % 2
            lbl_txt, _desc_txt = tr(self.ui_lang, f"fmt_{fmt_key}")
            rb = ttk.Radiobutton(
                grid_frame,
                text=lbl_txt,
                value=fmt_key,
                variable=self.format_var,
                command=self._on_format_changed,
            )
            rb.grid(row=row_i, column=col_i, sticky="w", padx=(4, 14), pady=1)
            self.format_widgets[fmt_key] = (rb, None)

        # Banda descriptiva dinámica del formato seleccionado
        ttk.Label(
            self.format_group,
            textvariable=self.format_desc_var,
            font=("Segoe UI", 8, "italic"),
            foreground="#1f4e79",
        ).pack(anchor="w", padx=(4, 0), pady=(3, 0))

        # Opciones de OCR inteligente, compresión PDF y escala de grises
        pdf_opts = ttk.LabelFrame(self.tab_convert, text=" Opciones de OCR y optimización PDF ", padding="6")
        pdf_opts.pack(fill=tk.X, pady=(0, 5))

        opts_row1 = ttk.Frame(pdf_opts)
        opts_row1.pack(fill=tk.X)

        ttk.Checkbutton(
            opts_row1,
            text="Forzar OCR (re-escanear aunque el PDF ya tenga texto buscable)",
            variable=self.force_ocr_var,
        ).pack(side=tk.LEFT)

        ttk.Checkbutton(
            opts_row1,
            text="Escala de grises (blanco y negro)",
            variable=self.grayscale_var,
        ).pack(side=tk.RIGHT)

        opts_row2 = ttk.Frame(pdf_opts)
        opts_row2.pack(fill=tk.X, pady=(4, 0))

        ttk.Label(opts_row2, text="Compresión PDF / PDF-A:").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Combobox(
            opts_row2,
            textvariable=self.compression_var,
            values=[lbl for lbl, _code in self.COMPRESSION_LABELS],
            state="readonly",
            width=26,
        ).pack(side=tk.LEFT)
        ttk.Label(
            opts_row2,
            text=" (PDF ya buscable: omite OCR automáticamente)",
            font=("Segoe UI", 8),
            foreground="#2e6b2e",
        ).pack(side=tk.LEFT, padx=(6, 0))

        # Destino
        self.output_group = ttk.LabelFrame(self.tab_convert, text=tr(self.ui_lang, "output_group"), padding="6")
        self.output_group.pack(fill=tk.X, pady=(0, 6))

        output_entry_frame = ttk.Frame(self.output_group)
        output_entry_frame.pack(fill=tk.X)

        ttk.Entry(output_entry_frame, textvariable=self.output_path_var, font=("Segoe UI", 9)).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8)
        )
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

        ttk.Label(
            self.tab_convert,
            textvariable=self.status_var,
            font=("Segoe UI", 9),
            foreground="#222222",
            wraplength=920,
        ).pack(anchor="w")

        post_frame = ttk.Frame(self.tab_convert)
        post_frame.pack(fill=tk.X, pady=(6, 0))

        self.btn_open_file = ttk.Button(post_frame, text=tr(self.ui_lang, "btn_open_file"), command=self._open_file, state=tk.DISABLED)
        self.btn_open_file.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_open_folder = ttk.Button(post_frame, text=tr(self.ui_lang, "btn_open_folder"), command=self._open_folder, state=tk.DISABLED)
        self.btn_open_folder.pack(side=tk.LEFT)

    def _render_hardware_locked_notice(self, parent, section_title: str, features: list):
        """Muestra un aviso claro y limpio cuando el hardware no alcanza los requisitos de una función IA."""
        box = ttk.LabelFrame(parent, text=f" 💻 {section_title} — Hardware insuficiente ", padding="16")
        box.pack(fill=tk.BOTH, expand=True, pady=12)

        ttk.Label(
            box,
            text=f"Equipo detectado: {self.hw.ram_total_gb:.1f} GB RAM | {self.hw.cpu_cores} núcleos | {self.hw.backend.upper()}",
            font=("Segoe UI", 9, "bold"),
            foreground="#6b4f00",
        ).pack(anchor="w", pady=(0, 8))

        ttk.Label(
            box,
            text="Con un hardware más potente (≥6 GB de RAM, recomendado ≥10–16 GB RAM o GPU Vulkan/Metal), "
                 "se desbloquearían automáticamente las siguientes funciones locales:",
            font=("Segoe UI", 9),
            wraplength=760,
        ).pack(anchor="w", pady=(0, 8))

        for feat in features:
            ttk.Label(box, text=f"  • {feat}", font=("Segoe UI", 9), foreground="#333333").pack(anchor="w", pady=2)

        ttk.Label(
            box,
            text="Mientras tanto, puedes utilizar con total normalidad la Conversión Estructural (10 formatos), "
                 "el Anonimizador RGPD 100% Python y las Herramientas PDF.",
            font=("Segoe UI", 8, "italic"),
            foreground="#1e6b1e",
            wraplength=760,
        ).pack(anchor="w", pady=(12, 0))

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

        lang_row = ttk.Frame(lang_grp)
        lang_row.pack(fill=tk.X)

        ttk.Label(lang_row, text="Idioma origen:").pack(side=tk.LEFT, padx=(0, 6))
        self.trans_src_combo = ttk.Combobox(
            lang_row,
            textvariable=self.trans_source_lang_var,
            values=["Auto-detectar"] + TRANSLATION_TARGET_LANGUAGES,
            width=16,
        )
        self.trans_src_combo.pack(side=tk.LEFT, padx=(0, 14))

        ttk.Label(lang_row, text="Idioma destino:").pack(side=tk.LEFT, padx=(0, 6))
        self.trans_dst_combo = ttk.Combobox(
            lang_row,
            textvariable=self.trans_target_lang_var,
            values=TRANSLATION_TARGET_LANGUAGES,
            width=16,
        )
        self.trans_dst_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.trans_dst_combo.bind("<<ComboboxSelected>>", lambda e: self._update_default_translate_output())

        ttk.Label(
            lang_row,
            text="Traducción contextual con Qwen3-VL y Prompt Madre",
            font=("Segoe UI", 8, "italic"),
            foreground="#1e6b1e",
        ).pack(side=tk.RIGHT)

        # 2. Selector de formato traducido (10 formatos en 2 columnas)
        fmt_grp = ttk.LabelFrame(self.tab_translate, text=" 📁 Formato del documento traducido ", padding="6")
        fmt_grp.pack(fill=tk.X, pady=(0, 5))

        grid_f = ttk.Frame(fmt_grp)
        grid_f.pack(fill=tk.X)
        grid_f.columnconfigure(0, weight=1)
        grid_f.columnconfigure(1, weight=1)

        for idx, (_lbl, fmt_key, _desc) in enumerate(self.FORMAT_OPTIONS):
            row_i = idx // 2
            col_i = idx % 2
            lbl_txt, _desc_txt = tr(self.ui_lang, f"fmt_{fmt_key}")
            ttk.Radiobutton(
                grid_f,
                text=lbl_txt,
                value=fmt_key,
                variable=self.trans_format_var,
                command=self._on_trans_format_changed,
            ).grid(row=row_i, column=col_i, sticky="w", padx=(4, 14), pady=1)

        ttk.Label(
            fmt_grp,
            textvariable=self.trans_format_desc_var,
            font=("Segoe UI", 8, "italic"),
            foreground="#1f4e79",
        ).pack(anchor="w", padx=(4, 0), pady=(3, 0))

        # 3. Opciones de maquetación, color, imagen y OCR
        vis_grp = ttk.LabelFrame(self.tab_translate, text=" 🎨 Maquetación y optimización de color e imagen ", padding="6")
        vis_grp.pack(fill=tk.X, pady=(0, 5))

        r1 = ttk.Frame(vis_grp)
        r1.pack(fill=tk.X)
        ttk.Checkbutton(
            r1,
            text="Preservar diseño visual, colores, fondos e imágenes (Inpainting)",
            variable=self.trans_preserve_layout_var,
        ).pack(side=tk.LEFT)
        ttk.Checkbutton(
            r1,
            text="Escala de grises (blanco y negro)",
            variable=self.trans_grayscale_var,
        ).pack(side=tk.RIGHT)

        r2 = ttk.Frame(vis_grp)
        r2.pack(fill=tk.X, pady=(3, 0))
        ttk.Checkbutton(
            r2,
            text="Forzar OCR (re-escanear)",
            variable=self.trans_force_ocr_var,
        ).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(
            r2,
            text="Modo letra manuscrita (Visión)",
            variable=self.trans_handwriting_var,
        ).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Label(r2, text="Compresión:").pack(side=tk.LEFT, padx=(6, 4))
        ttk.Combobox(
            r2,
            textvariable=self.trans_compression_var,
            values=[lbl for lbl, _code in self.COMPRESSION_LABELS],
            state="readonly",
            width=24,
        ).pack(side=tk.LEFT)

        # 4. Fichero de salida traducido
        out_grp = ttk.LabelFrame(self.tab_translate, text=" 💾 Fichero traducido de salida ", padding="6")
        out_grp.pack(fill=tk.X, pady=(0, 6))

        out_row = ttk.Frame(out_grp)
        out_row.pack(fill=tk.X)
        ttk.Entry(out_row, textvariable=self.trans_output_path_var, font=("Segoe UI", 9)).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8)
        )
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

        ttk.Label(
            self.tab_translate,
            textvariable=self.trans_status_var,
            font=("Segoe UI", 9),
            foreground=self.palette["fg"],
            wraplength=920,
        ).pack(anchor="w")

        post_trans = ttk.Frame(self.tab_translate)
        post_trans.pack(fill=tk.X, pady=(5, 0))
        self.btn_open_trans_file = ttk.Button(
            post_trans, text="📄 Abrir documento traducido", command=self._open_translated_file, state=tk.DISABLED
        )
        self.btn_open_trans_file.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_open_trans_folder = ttk.Button(
            post_trans, text="📁 Abrir carpeta", command=self._open_translated_folder, state=tk.DISABLED
        )
        self.btn_open_trans_folder.pack(side=tk.LEFT)

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
                    self.trans_status_var.set(
                        f"✓ Documento traducido ({res.total_pages} pág., {res.total_elements} bloques) "
                        f"en {res.elapsed_seconds:.2f}s → {Path(res.output_path).name}"
                    )

                self.root.after(0, on_ok)
            except Exception as e:
                logger.exception(f"Error en traducción directa de documento: {e}")

                def on_err(msg=str(e)):
                    self.trans_progress.stop()
                    self.btn_translate_doc.config(state=tk.NORMAL)
                    self.trans_status_var.set(f"Error en traducción: {msg}")
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
        ttk.Label(self.tab_chat, text=info_txt, font=("Segoe UI", 8, "bold"), foreground="#1f4e79").pack(anchor="w", pady=(0, 4))

        if tier.locked_features_hint:
            ttk.Label(
                self.tab_chat,
                text=f"ℹ️ {tier.locked_features_hint}",
                font=("Segoe UI", 8, "italic"),
                foreground="#6b4f00",
                wraplength=820,
            ).pack(anchor="w", pady=(0, 4))

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
            font=("Segoe UI", 9),
            selectmode=tk.EXTENDED,
            yscrollcommand=lb_scroll.set,
            bg=self.palette["input_bg"],
            fg=self.palette["input_fg"],
        )
        self.chat_docs_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
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
        ttk.Label(status_row, textvariable=self.chat_status_var, font=("Segoe UI", 9, "bold"), foreground=self.palette["accent"]).pack(side=tk.LEFT)
        ttk.Label(status_row, textvariable=self.chat_count_var, font=("Segoe UI", 9), foreground=self.palette["ok"]).pack(side=tk.RIGHT)

        # Barra inferior de pregunta EMPAQUETADA ANTES del historial (siempre visible en pantalla)
        input_bar = ttk.LabelFrame(self.tab_chat, text=" 💬 Preguntar a los documentos cargados (Ctrl+Rueda para Zoom) ", padding="6")
        input_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))

        ask_row = ttk.Frame(input_bar)
        ask_row.pack(fill=tk.X)

        self.chat_entry = ttk.Entry(ask_row, textvariable=self.chat_question_var, font=("Segoe UI", 11))
        self.chat_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6), ipady=3)
        self.chat_entry.bind("<Return>", lambda e: self._chat_send())

        ttk.Button(ask_row, text="A-", width=3, command=lambda: self._adjust_text_zoom(-1)).pack(side=tk.LEFT, padx=1)
        ttk.Button(ask_row, text="A+", width=3, command=lambda: self._adjust_text_zoom(1)).pack(side=tk.LEFT, padx=(1, 6))

        self.btn_chat_send = ttk.Button(ask_row, text="💬 Enviar pregunta", command=self._chat_send)
        self.btn_chat_send.pack(side=tk.RIGHT, ipadx=8, ipady=2)

        export_row = ttk.Frame(input_bar)
        export_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(export_row, text="Exportar conversación (con referencias literales):").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Combobox(
            export_row,
            textvariable=self.chat_export_fmt_var,
            values=[lbl for lbl, _code in self.EXPORT_CONV_FORMATS],
            state="readonly",
            width=18,
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            export_row,
            text="📥 Exportar chat + citas literales",
            command=self._chat_export_conversation,
        ).pack(side=tk.LEFT)

        # Historial de conversación con citas (ocupa el espacio central restante)
        chat_box_frame = ttk.Frame(self.tab_chat)
        chat_box_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        chat_scroll = ttk.Scrollbar(chat_box_frame)
        chat_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.chat_history_text = tk.Text(
            chat_box_frame,
            wrap=tk.WORD,
            yscrollcommand=chat_scroll.set,
            padx=10,
            pady=8,
            state=tk.DISABLED,
        )
        self.chat_history_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        chat_scroll.config(command=self.chat_history_text.yview)
        self._register_zoomable_text(self.chat_history_text, family="Segoe UI")

        self.chat_history_text.tag_configure("user_lbl", font=("Segoe UI", self.text_font_size, "bold"), foreground=self.palette["accent"])
        self.chat_history_text.tag_configure("ai_lbl", font=("Segoe UI", self.text_font_size, "bold"), foreground=self.palette["ok"])
        self.chat_history_text.tag_configure("ref_lbl", font=("Segoe UI", max(9, self.text_font_size - 1), "bold"), foreground=self.palette["warn"])
        self.chat_history_text.tag_configure("ref_body", font=("Consolas", max(9, self.text_font_size - 1)), foreground=self.palette["muted"])

    def _ensure_chat_engine(self):
        if self.chat_engine is None:
            from .ai.multi_doc_chat import MultiDocumentChat
            self.chat_engine = MultiDocumentChat()
        return self.chat_engine

    def _on_tab_changed(self, event=None):
        """Mantiene intacto el contenido y refresca el repintado al cambiar de pestaña mientras hay tareas activas."""
        try:
            self.root.update_idletasks()
            if hasattr(self, "chat_history_text"):
                self.chat_history_text.see(tk.END)
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
        dlg.geometry("500x300")
        dlg.transient(self.root)
        dlg.grab_set()

        frame = ttk.Frame(dlg, padding="12")
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="Selecciona un proyecto guardado:", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))

        lb = tk.Listbox(frame, font=("Segoe UI", 10), bg=self.palette["input_bg"], fg=self.palette["input_fg"])
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

                self.root.after(0, on_ok)
            except Exception as e:
                logger.exception(f"Error en chat multi-documento: {e}")

                def on_err(msg=str(e)):
                    self.chat_progress.stop()
                    self.btn_chat_send.config(state=tk.NORMAL)
                    self.btn_chat_add.config(state=tk.NORMAL)
                    self.chat_status_var.set(f"Error: {msg}")
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
                    "Resúmenes ejecutivos automáticos de documentos extensos (Map-Reduce AST).",
                    "Traducción contextual a cualquier idioma 100% offline.",
                ],
            )
            return

        tier = self.ai_tier
        hw_text = (
            f"💻 Hardware: {self.hw.ram_total_gb:.1f} GB RAM | {self.hw.backend.upper()} | "
            f"Perfil {tier.tier_name.upper()} → {tier.vlm_label} + {tier.embed_label} (ctx={tier.recommended_n_ctx})"
        )
        ttk.Label(
            self.tab_ai,
            text=hw_text,
            font=("Segoe UI", 8, "bold"),
            foreground="#1f4e79",
        ).pack(anchor="w", pady=(0, 4))

        if tier.locked_features_hint:
            ttk.Label(
                self.tab_ai,
                text=f"ℹ️ {tier.locked_features_hint}",
                font=("Segoe UI", 8, "italic"),
                foreground="#6b4f00",
                wraplength=820,
            ).pack(anchor="w", pady=(0, 4))

        # Opción de lectura manuscrita + forzar OCR
        opts_frame = ttk.Frame(self.tab_ai)
        opts_frame.pack(fill=tk.X, pady=(0, 8))

        self.chk_handwriting = ttk.Checkbutton(
            opts_frame,
            text=tr(self.ui_lang, "chk_handwriting"),
            variable=self.handwriting_var,
        )
        self.chk_handwriting.pack(side=tk.LEFT)

        ttk.Checkbutton(
            opts_frame,
            text="Forzar OCR (ignorar texto embebido)",
            variable=self.ai_force_ocr_var,
        ).pack(side=tk.RIGHT)

        # Botones de acciones IA enfocadas (Transcribir, Resumir, Traducir)
        self.ai_actions_frame = ttk.LabelFrame(self.tab_ai, text=tr(self.ui_lang, "ai_actions_group"), padding="8")
        self.ai_actions_frame.pack(fill=tk.X, pady=(0, 8))

        btn_row = ttk.Frame(self.ai_actions_frame)
        btn_row.pack(fill=tk.X)

        self.btn_ai_transcribe = ttk.Button(btn_row, text=tr(self.ui_lang, "btn_transcribe"), command=lambda: self._run_ai_action("transcribe"))
        self.btn_ai_transcribe.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=3)

        self.btn_ai_summarize = ttk.Button(btn_row, text=tr(self.ui_lang, "btn_summarize"), command=lambda: self._run_ai_action("summarize"))
        self.btn_ai_summarize.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=3)

        self.btn_ai_translate = ttk.Button(btn_row, text=tr(self.ui_lang, "btn_translate"), command=lambda: self._run_ai_action("translate"))
        self.btn_ai_translate.pack(side=tk.LEFT, padx=(6, 4))

        self.translate_lang_combo = ttk.Combobox(
            btn_row,
            textvariable=self.translate_lang_var,
            values=TRANSLATION_TARGET_LANGUAGES,
            width=18,
        )
        self.translate_lang_combo.pack(side=tk.LEFT)

        ask_row = ttk.Frame(self.ai_actions_frame)
        ask_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(ask_row, text=tr(self.ui_lang, "lbl_question")).pack(side=tk.LEFT, padx=(0, 6))
        self.ai_question_entry = ttk.Entry(ask_row, textvariable=self.question_var, font=("Segoe UI", 10))
        self.ai_question_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.ai_question_entry.bind("<Return>", lambda e: self._run_ai_action("ask"))
        self.btn_ai_ask = ttk.Button(
            ask_row,
            text=tr(self.ui_lang, "btn_ask"),
            command=lambda: self._run_ai_action("ask"),
        )
        self.btn_ai_ask.pack(side=tk.RIGHT)

        self.ai_buttons.extend([self.btn_ai_transcribe, self.btn_ai_summarize, self.btn_ai_translate, self.btn_ai_ask])

        # Progreso y estado IA
        self.ai_progress = ttk.Progressbar(self.tab_ai, mode="indeterminate")
        self.ai_progress.pack(fill=tk.X, pady=(2, 4))

        ttk.Label(
            self.tab_ai,
            textvariable=self.ai_status_var,
            font=("Segoe UI", 8),
            foreground="#333333",
            wraplength=780,
        ).pack(anchor="w", pady=(0, 4))

        # Botones inferiores IA (empaquetados antes del área expandible para que nunca desaparezcan)
        ai_bottom = ttk.Frame(self.tab_ai)
        ai_bottom.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))

        ttk.Button(ai_bottom, text="📋 Copiar texto", command=self._copy_ai_output).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(ai_bottom, text="💾 Guardar .txt", command=self._save_ai_output).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Label(ai_bottom, text="Exportar consulta + referencias literales:").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Combobox(
            ai_bottom,
            textvariable=self.ai_export_fmt_var,
            values=[lbl for lbl, _code in self.EXPORT_CONV_FORMATS],
            state="readonly",
            width=16,
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            ai_bottom,
            text="📥 Exportar informe...",
            command=self._export_ai_output_with_refs,
        ).pack(side=tk.LEFT)

        # Área de texto resultado
        text_frame = ttk.Frame(self.tab_ai)
        text_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.ai_output_text = tk.Text(
            text_frame,
            height=10,
            wrap=tk.WORD,
            yscrollcommand=scrollbar.set,
            padx=8,
            pady=6,
        )
        self.ai_output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.ai_output_text.yview)
        self._register_zoomable_text(self.ai_output_text, family="Consolas")

        # Atajos de teclado explícitos y menú contextual (clic derecho) para copiar fácilmente
        self.ai_output_text.bind("<Control-c>", self._copy_selection)
        self.ai_output_text.bind("<Control-C>", self._copy_selection)
        self.ai_output_text.bind("<Control-a>", self._select_all_output)
        self.ai_output_text.bind("<Control-A>", self._select_all_output)
        self.ai_output_text.bind("<Button-3>", self._show_text_context_menu)

        self.text_context_menu = tk.Menu(self.root, tearoff=0)
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

        ttk.Label(
            info_grp,
            text="Detecta y oculta instantáneamente sin IA: DNI, NIE, CIF, IBAN, Tarjetas, NUSS, Emails, "
                 "Teléfonos, IPs, Matrículas, Direcciones postales y Nombres con tratamiento (Don/Doña/Sr./Sra.).",
            font=("Segoe UI", 8),
            foreground="#333333",
            wraplength=820,
        ).pack(anchor="w", pady=(0, 6))

        ctrl_row = ttk.Frame(info_grp)
        ctrl_row.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(ctrl_row, text="Estilo de ocultación:").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Radiobutton(ctrl_row, text="Etiquetas ([DNI], [NOMBRE])", value="tags", variable=self.anon_mask_style_var).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Radiobutton(ctrl_row, text="Bloques negros (████████)", value="blocks", variable=self.anon_mask_style_var).pack(side=tk.LEFT)

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
                text=f"🧠 Paso 1 + Paso 2 (Potenciado con IA local {self.ai_tier.vlm_label}: detecta además nombres sin tratamiento, apellidos y empresas)",
                value=True,
                variable=self.anon_use_llm_var,
            ).pack(anchor="w")
        else:
            ttk.Label(
                info_grp,
                text="ℹ️ Modo Paso 1 (100% Python) activo. Con un hardware más potente (≥6 GB RAM) se desbloquea además "
                     "el Paso 2 (refuerzo semántico IA) para detectar nombres propios sin tratamiento y empresas.",
                font=("Segoe UI", 9, "italic"),
                foreground=self.palette["warn"],
                wraplength=820,
            ).pack(anchor="w", pady=(4, 0))

        self.btn_run_anon = ttk.Button(
            self.tab_anonymize,
            text="🔒  Anonimizar documento seleccionado",
            command=self._run_anonymize_standalone,
        )
        self.btn_run_anon.pack(fill=tk.X, ipady=5, pady=(0, 6))

        self.anon_progress = ttk.Progressbar(self.tab_anonymize, mode="indeterminate")
        self.anon_progress.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(self.tab_anonymize, textvariable=self.anon_status_var, font=("Segoe UI", 8), foreground="#333333").pack(anchor="w", pady=(0, 4))

        anon_txt_frame = ttk.Frame(self.tab_anonymize)
        anon_txt_frame.pack(fill=tk.BOTH, expand=True)
        anon_scroll = ttk.Scrollbar(anon_txt_frame)
        anon_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.anon_output_text = tk.Text(
            anon_txt_frame,
            wrap=tk.WORD,
            yscrollcommand=anon_scroll.set,
            padx=8,
            pady=8,
        )
        self.anon_output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        anon_scroll.config(command=self.anon_output_text.yview)
        self._register_zoomable_text(self.anon_output_text, family="Consolas")

        anon_bottom = ttk.Frame(self.tab_anonymize)
        anon_bottom.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(anon_bottom, text="📋 Copiar resultado", command=self._copy_anon_output).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(anon_bottom, text="💾 Guardar como .txt", command=self._save_anon_output).pack(side=tk.LEFT)

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

                self.root.after(0, on_ok)
            except Exception as e:
                logger.exception(f"Error en anonimización: {e}")

                def on_err(msg=str(e)):
                    self.anon_progress.stop()
                    self.btn_run_anon.config(state=tk.NORMAL)
                    self.anon_status_var.set(f"Error: {msg}")
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
        """Pestaña 3: Desbloqueo de PDFs, borrado de firmas, limpieza de marcas de agua y optimización."""
        self.pdf_tool_buttons = []

        # Aviso de uso legítimo y cumplimiento normativo
        ttk.Label(
            self.tab_pdf_tools,
            text="⚖️ Aviso legal: utiliza estas herramientas únicamente sobre documentos propios o con autorización legítima "
                 "(no realiza crackeo de claves de apertura; respeta propiedad intelectual, RGPD y autenticidad documental).",
            font=("Segoe UI", 8, "italic"),
            foreground="#6b4f00",
            wraplength=840,
        ).pack(anchor="w", pady=(0, 8))

        # 1. Desbloqueo de PDFs con clave o restricciones
        unlock_grp = ttk.LabelFrame(self.tab_pdf_tools, text=" 🔓 Desbloquear PDF (quitar contraseña o restricciones de copia/impresión) ", padding="8")
        unlock_grp.pack(fill=tk.X, pady=(0, 8))

        u_row = ttk.Frame(unlock_grp)
        u_row.pack(fill=tk.X)
        ttk.Label(u_row, text="Contraseña de apertura (opcional si solo tiene restricciones):").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Entry(u_row, textvariable=self.pdf_password_var, show="•", width=22).pack(side=tk.LEFT, padx=(0, 8))
        btn_unlock = ttk.Button(u_row, text="🔓 Desbloquear PDF", command=lambda: self._run_pdf_tool("unlock"))
        btn_unlock.pack(side=tk.RIGHT)
        self.pdf_tool_buttons.append(btn_unlock)

        # 2. Eliminación de firmas digitales
        sig_grp = ttk.LabelFrame(self.tab_pdf_tools, text=" ✍️ Borrar Firmas Digitales y Sellos de Formulario ", padding="8")
        sig_grp.pack(fill=tk.X, pady=(0, 8))

        s_row = ttk.Frame(sig_grp)
        s_row.pack(fill=tk.X)
        ttk.Label(
            s_row,
            text="Elimina campos criptográficos (/Sig), bloqueos de edición (DocMDP) y sellos visuales de firma.",
            font=("Segoe UI", 8),
            foreground="#444444",
        ).pack(side=tk.LEFT)
        btn_sig = ttk.Button(s_row, text="🗑️ Borrar firmas del PDF", command=lambda: self._run_pdf_tool("signatures"))
        btn_sig.pack(side=tk.RIGHT)
        self.pdf_tool_buttons.append(btn_sig)

        # 3. Limpieza de marcas de agua
        wm_grp = ttk.LabelFrame(self.tab_pdf_tools, text=" 🧽 Limpiar Marcas de Agua (Vectoriales, Capas OCG y Escaneos) ", padding="8")
        wm_grp.pack(fill=tk.X, pady=(0, 8))

        wm_row1 = ttk.Frame(wm_grp)
        wm_row1.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(wm_row1, text="Texto de marca a borrar (opcional, ej. BORRADOR, CONFIDENCIAL):").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Entry(wm_row1, textvariable=self.wm_text_var, width=28).pack(side=tk.LEFT, fill=tk.X, expand=True)

        wm_row2 = ttk.Frame(wm_grp)
        wm_row2.pack(fill=tk.X)
        ttk.Checkbutton(wm_row2, text="Eliminar anotaciones /Watermark y capas OCG", variable=self.wm_annots_var).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Checkbutton(wm_row2, text="Limpiar marca gris/color en escaneos (OpenCV)", variable=self.wm_scan_var).pack(side=tk.LEFT)
        btn_wm = ttk.Button(wm_row2, text="🧽 Limpiar marcas de agua", command=lambda: self._run_pdf_tool("watermarks"))
        btn_wm.pack(side=tk.RIGHT)
        self.pdf_tool_buttons.append(btn_wm)

        # 4. Compresión rápida, escala de grises y PDF/A
        opt_grp = ttk.LabelFrame(self.tab_pdf_tools, text=" 🗜️ Comprimir PDF, Escala de Grises y PDF/A-2b ", padding="8")
        opt_grp.pack(fill=tk.X, pady=(0, 10))

        opt_row = ttk.Frame(opt_grp)
        opt_row.pack(fill=tk.X)
        ttk.Label(opt_row, text="Compresión:").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Combobox(
            opt_row,
            textvariable=self.opt_compression_var,
            values=[lbl for lbl, _code in self.COMPRESSION_LABELS],
            state="readonly",
            width=24,
        ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Checkbutton(opt_row, text="Escala de grises", variable=self.opt_grayscale_var).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Checkbutton(opt_row, text="Estándar PDF/A-2b", variable=self.opt_pdfa_var).pack(side=tk.LEFT)
        btn_opt = ttk.Button(opt_row, text="🗜️ Optimizar PDF", command=lambda: self._run_pdf_tool("optimize"))
        btn_opt.pack(side=tk.RIGHT)
        self.pdf_tool_buttons.append(btn_opt)

        # Progreso y botones resultado
        self.pdf_tools_progress = ttk.Progressbar(self.tab_pdf_tools, mode="indeterminate")
        self.pdf_tools_progress.pack(fill=tk.X, pady=(2, 6))

        ttk.Label(
            self.tab_pdf_tools,
            textvariable=self.pdf_tools_status_var,
            font=("Segoe UI", 9),
            foreground="#222222",
            wraplength=820,
        ).pack(anchor="w")

        post_pdf = ttk.Frame(self.tab_pdf_tools)
        post_pdf.pack(fill=tk.X, pady=(8, 0))
        self.btn_pdf_open_file = ttk.Button(
            post_pdf,
            text="📄 Abrir PDF resultante",
            command=lambda: self.last_pdf_tool_file and self._open_path_crossplatform(self.last_pdf_tool_file),
            state=tk.DISABLED,
        )
        self.btn_pdf_open_file.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_pdf_open_folder = ttk.Button(
            post_pdf,
            text="📁 Abrir carpeta",
            command=lambda: self.last_pdf_tool_file and self._open_path_crossplatform(str(Path(self.last_pdf_tool_file).parent)),
            state=tk.DISABLED,
        )
        self.btn_pdf_open_folder.pack(side=tk.LEFT)

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
                    messagebox.showinfo("Operación completada", res["message"])

                self.root.after(0, on_ok)
            except Exception as e:
                logger.exception(f"Error en herramienta PDF '{tool_action}': {e}")

                def on_err(msg=str(e)):
                    self.pdf_tools_progress.stop()
                    for b in self.pdf_tool_buttons:
                        b.config(state=tk.NORMAL)
                    self.pdf_tools_status_var.set(f"Error: {msg}")
                    messagebox.showerror("Error en Herramienta PDF", msg)

                self.root.after(0, on_err)

        threading.Thread(target=worker, daemon=True).start()

    def _center_drop_text(self, event):
        self.drop_canvas.coords(self.drop_text_id, event.width / 2, event.height / 2)

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
        self.btn_github.config(text=_strip_leading_emoji(tr(lang, "btn_github")))
        self.btn_legal.config(text=_strip_leading_emoji(tr(lang, "btn_legal")))
        self.btn_update.config(text=_strip_leading_emoji(tr(lang, "btn_update")))
        self.btn_reinstall.config(text=_strip_leading_emoji(tr(lang, "btn_reinstall")))
        self.btn_cache.config(text=_strip_leading_emoji(tr(lang, "btn_cache")))
        self.btn_clear_logs.config(text=_strip_leading_emoji(tr(lang, "btn_clear_logs")))
        self.btn_view_logs.config(text=_strip_leading_emoji(tr(lang, "btn_view_logs")))
        self.drop_frame.config(text=tr(lang, "input_group"))
        self.btn_paste.config(text=tr(lang, "btn_paste"))
        self.btn_browse.config(text=tr(lang, "btn_browse"))
        self.notebook.tab(self.tab_convert, text=f"{_strip_leading_emoji(tr(lang, 'tab_convert'))} ")
        self.notebook.tab(self.tab_translate, text=f"{_strip_leading_emoji(tr(lang, 'tab_translate'))} ")
        self.notebook.tab(self.tab_ai, text=f"{_strip_leading_emoji(tr(lang, 'tab_ai'))} ")
        if self.tab_pdf_tools is not None:
            self.notebook.tab(self.tab_pdf_tools, text=f"{_strip_leading_emoji(tr(lang, 'tab_pdf_tools'))} ")
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
            self.btn_ai_translate.config(text=tr(lang, "btn_translate"))
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
        self.cached_doc_text = None
        self.cached_doc_key = None
        self.last_ai_turn_record = None
        self.ai_turn_records = []
        self._update_default_output()
        self._update_default_translate_output()

        self.drop_canvas.config(bg="#eaf4ea", highlightbackground="#88bb88")
        self.drop_canvas.itemconfigure(
            self.drop_text_id,
            text=f"✓ Fichero seleccionado: {path_obj.name}  (Haz clic para cambiar)",
            fill="#1e6b1e",
        )
        self.status_var.set(f"Fichero listo: {path_obj.name}")
        self.trans_status_var.set(f"Fichero listo para traducir: {path_obj.name}")
        self.ai_status_var.set(f"Documento cargado: {path_obj.name}. Elige una acción de IA.")

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
        messagebox.showinfo("Completado", f"Documento guardado con éxito en:\n{result.output_path}")

    def _on_conversion_error(self, err_msg: str):
        self.progress_bar.stop()
        self.btn_convert.config(state=tk.NORMAL)
        self.status_var.set(f"Error: {err_msg}")
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
        dialog.geometry("480x210")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        result = {"source": None}

        frame = ttk.Frame(dialog, padding="16")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text="No se ha encontrado el modelo de IA en la carpeta 'models/'.",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=(0, 6))

        ttk.Label(
            frame,
            text="Para usar la IA local (manuscritos, traducción, Q&A y anonimización),\n"
                 "elige desde dónde deseas descargar los ficheros GGUF (~2,9 GB):",
            font=("Segoe UI", 9),
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
        """Libera el servidor llama.cpp en memoria al cerrar la ventana."""
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

    def _on_ai_error(self, err_msg: str):
        self.ai_progress.stop()
        for b in self.ai_buttons:
            b.config(state=tk.NORMAL)
        self.ai_status_var.set(f"Error en IA: {err_msg}")
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
        win.geometry("700x580")
        win.transient(self.root)

        frame = ttk.Frame(win, padding="14")
        frame.pack(fill=tk.BOTH, expand=True)

        scroll = ttk.Scrollbar(frame)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        txt = tk.Text(frame, wrap=tk.WORD, font=("Segoe UI", 9), yscrollcommand=scroll.set, padx=10, pady=10)
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
            "👉 ¡Te invitamos a conocer, seguir y colaborar en el proyecto GuarIdA!\n"
            "Actualmente en desarrollo activo para la soberanía y privacidad documental.\n\n"
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
        dialog.geometry("500x310")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding="16")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text="Selecciona qué deseas limpiar y reinstalar:",
            font=("Segoe UI", 10, "bold"),
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
        ttk.Label(frame, textvariable=status_lbl_var, font=("Segoe UI", 8), foreground="#444444", wraplength=460).pack(anchor="w", pady=(12, 6))

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


def launch_gui():
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


if __name__ == "__main__":
    launch_gui()
