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
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import ImageGrab
from .converter import DocumentConverter
from .document_loader import DocumentLoader
from .engine import OCREngine
from .formats.docx_builder import _group_boxes_into_lines
from .logger import get_logger, get_logs_dir

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


class OpenOCReaderGUI:
    """Ventana principal de la interfaz gráfica de Open OCReader."""

    FORMAT_OPTIONS = [
        ("PDF Buscable (Sandwich)", "pdf", "Conserva el diseño visual 100% original con capa de texto invisible"),
        ("Microsoft Word (.docx)", "docx", "Documento editable estructurado en párrafos y títulos"),
        ("Microsoft Excel (.xlsx)", "xlsx", "Tabla de cálculo con celdas mapeadas por coordenadas"),
        ("Texto plano (.txt)", "txt", "Volcado de texto en orden de lectura natural"),
        ("JSON Estructurado (.json)", "json", "Coordenadas geométricas, polígonos y confianza"),
    ]

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Open OCReader - Digitalización e IA Documental 100% Local")
        self.root.geometry("760x740")
        self.root.minsize(680, 660)
        self._window_icon_ref = None
        self._apply_window_icon()

        self.style = ttk.Style()
        try:
            self.style.theme_use("vista" if "vista" in self.style.theme_names() else "clam")
        except Exception:
            pass

        self.input_path_var = tk.StringVar()
        self.output_path_var = tk.StringVar()
        self.format_var = tk.StringVar(value="pdf")
        self.status_var = tk.StringVar(value="Arrastra un fichero, pulsa 'Examinar' o pega con Ctrl+V.")
        self.ai_status_var = tk.StringVar(value="Listo. Selecciona un documento y elige una acción inteligente.")
        self.handwriting_var = tk.BooleanVar(value=False)
        self.question_var = tk.StringVar()

        self.last_generated_file = None
        self.cached_doc_text = None
        self.cached_doc_key = None  # (file_path, handwriting_flag)

        self._build_ui()
        self._setup_drag_and_drop()
        self._setup_clipboard_paste()
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _apply_window_icon(self):
        """Aplica el icono de Open OCReader (.ico en Windows, .png en Linux/macOS)."""
        candidates = []
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            candidates.append(exe_dir / "ico")
            candidates.append(exe_dir / "_internal" / "ico")
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                candidates.append(Path(meipass) / "ico")
        else:
            candidates.append(Path(__file__).resolve().parent.parent.parent / "ico")

        ico_dir = next((d for d in candidates if d.exists()), None)
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

    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding="14 12 14 12")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Cabecera común
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 8))

        title_row = ttk.Frame(header_frame)
        title_row.pack(fill=tk.X)
        ttk.Label(title_row, text="Open OCReader 📄🔍🧠", font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT)

        tools_row = ttk.Frame(title_row)
        tools_row.pack(side=tk.RIGHT)
        ttk.Button(tools_row, text="⚖️ Legal / IA", command=self._show_legal_compliance).pack(side=tk.LEFT, padx=2)
        ttk.Button(tools_row, text="🔄 Actualizar", command=self._check_updates_gui).pack(side=tk.LEFT, padx=2)
        ttk.Button(tools_row, text="🧹 Caché", command=self._clear_cache_gui).pack(side=tk.LEFT, padx=2)
        ttk.Button(tools_row, text="🗑️ Logs", command=self._clear_logs_gui).pack(side=tk.LEFT, padx=2)
        ttk.Button(tools_row, text="📋 Logs", command=self._open_logs).pack(side=tk.LEFT, padx=(2, 0))

        ttk.Label(
            header_frame,
            text="Conversión fiel a PDF/Word/Excel + IA Local (Qwen3-VL) para manuscritos, traducción y anonimización.",
            font=("Segoe UI", 9),
            foreground="#555555",
        ).pack(anchor="w")

        # Selector de fichero común en la parte superior
        drop_frame = ttk.LabelFrame(main_frame, text=" Fichero de entrada (Imagen o PDF) ", padding="8")
        drop_frame.pack(fill=tk.X, pady=(0, 10))

        self.drop_canvas = tk.Canvas(
            drop_frame,
            bg="#f4f6f9",
            height=64,
            highlightthickness=1,
            highlightbackground="#b0c4de",
            relief="flat",
        )
        self.drop_canvas.pack(fill=tk.X, pady=(0, 6))

        self.drop_text_id = self.drop_canvas.create_text(
            350, 32,
            text="📥 Arrastra y suelta aquí tu fichero (PDF, JPG, PNG, TIFF) o pulsa Pegar (Ctrl + V)",
            font=("Segoe UI", 10, "italic"),
            fill="#334466",
            justify="center",
        )
        self.drop_canvas.bind("<Configure>", self._center_drop_text)
        self.drop_canvas.bind("<Button-1>", lambda e: self._browse_input())

        entry_row = ttk.Frame(drop_frame)
        entry_row.pack(fill=tk.X)

        self.input_entry = ttk.Entry(entry_row, textvariable=self.input_path_var, font=("Segoe UI", 9))
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        ttk.Button(entry_row, text="📋 Pegar (Ctrl+V)", command=self._paste_from_clipboard).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(entry_row, text="Examinar...", command=self._browse_input).pack(side=tk.RIGHT)

        # Pestañas (Notebook)
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.tab_convert = ttk.Frame(self.notebook, padding="10")
        self.tab_ai = ttk.Frame(self.notebook, padding="10")

        self.notebook.add(self.tab_convert, text="  📄 Conversión Estructural (Rápida)  ")
        self.notebook.add(self.tab_ai, text="  🧠 IA Local y Manuscritos (Qwen3-VL)  ")

        self._build_convert_tab()
        self._build_ai_tab()

        # Pie informativo permanente: licencia libre y aviso normativo de IA
        footer_lbl = ttk.Label(
            main_frame,
            text="Software Libre GNU GPL v3.0 (atribución y copyleft obligatorios) • 100% Local (EU AI Act / RGPD / ENS) • Revisar salidas de IA.",
            font=("Segoe UI", 8),
            foreground="#555555",
        )
        footer_lbl.pack(anchor="w", pady=(6, 0))

    def _build_convert_tab(self):
        # Formato de salida
        format_group = ttk.LabelFrame(self.tab_convert, text=" Formato de salida ", padding="8")
        format_group.pack(fill=tk.X, pady=(0, 10))

        for label_text, fmt_key, desc in self.FORMAT_OPTIONS:
            rb_frame = ttk.Frame(format_group)
            rb_frame.pack(fill=tk.X, pady=2)

            ttk.Radiobutton(
                rb_frame,
                text=label_text,
                value=fmt_key,
                variable=self.format_var,
                command=self._on_format_changed,
            ).pack(side=tk.LEFT)

            ttk.Label(rb_frame, text=f"— {desc}", font=("Segoe UI", 8), foreground="#666666").pack(side=tk.LEFT, padx=(8, 0))

        # Destino
        output_group = ttk.LabelFrame(self.tab_convert, text=" Fichero de salida ", padding="8")
        output_group.pack(fill=tk.X, pady=(0, 12))

        output_entry_frame = ttk.Frame(output_group)
        output_entry_frame.pack(fill=tk.X)

        ttk.Entry(output_entry_frame, textvariable=self.output_path_var, font=("Segoe UI", 9)).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8)
        )
        ttk.Button(output_entry_frame, text="Guardar como...", command=self._browse_output).pack(side=tk.RIGHT)

        # Botón convertir
        self.btn_convert = ttk.Button(
            self.tab_convert,
            text="🚀  Digitalizar y Convertir",
            command=self._start_conversion,
        )
        self.btn_convert.pack(fill=tk.X, ipady=6, pady=(2, 6))

        self.progress_bar = ttk.Progressbar(self.tab_convert, mode="indeterminate")
        self.progress_bar.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(
            self.tab_convert,
            textvariable=self.status_var,
            font=("Segoe UI", 9),
            foreground="#222222",
            wraplength=690,
        ).pack(anchor="w")

        post_frame = ttk.Frame(self.tab_convert)
        post_frame.pack(fill=tk.X, pady=(10, 0))

        self.btn_open_file = ttk.Button(post_frame, text="📄 Abrir fichero", command=self._open_file, state=tk.DISABLED)
        self.btn_open_file.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_open_folder = ttk.Button(post_frame, text="📁 Abrir carpeta", command=self._open_folder, state=tk.DISABLED)
        self.btn_open_folder.pack(side=tk.LEFT)

    def _build_ai_tab(self):
        # Opción de lectura manuscrita
        opts_frame = ttk.Frame(self.tab_ai)
        opts_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Checkbutton(
            opts_frame,
            text="✍️ Modo Letra Manuscrita (usa Qwen3-VL Visión en lugar de RapidOCR para leer caligrafía)",
            variable=self.handwriting_var,
        ).pack(anchor="w")

        # Botones de acciones IA
        actions_frame = ttk.LabelFrame(self.tab_ai, text=" Acciones sobre el documento ", padding="8")
        actions_frame.pack(fill=tk.X, pady=(0, 8))

        btn_row = ttk.Frame(actions_frame)
        btn_row.pack(fill=tk.X)

        self.ai_buttons = []
        btns_spec = [
            ("✍️ Transcribir", "transcribe"),
            ("📝 Resumir", "summarize"),
            ("🌐 Traducir al español", "translate"),
            ("🔒 Anonimizar (RGPD)", "anonymize"),
        ]
        for label, action_id in btns_spec:
            b = ttk.Button(btn_row, text=label, command=lambda act=action_id: self._run_ai_action(act))
            b.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=3)
            self.ai_buttons.append(b)

        # Preguntar al documento
        qa_frame = ttk.Frame(actions_frame)
        qa_frame.pack(fill=tk.X, pady=(8, 0))

        ttk.Label(qa_frame, text="💬 Pregunta:").pack(side=tk.LEFT, padx=(0, 6))
        q_entry = ttk.Entry(qa_frame, textvariable=self.question_var, font=("Segoe UI", 9))
        q_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        q_entry.bind("<Return>", lambda e: self._run_ai_action("ask"))

        b_ask = ttk.Button(qa_frame, text="Preguntar", command=lambda: self._run_ai_action("ask"))
        b_ask.pack(side=tk.RIGHT)
        self.ai_buttons.append(b_ask)

        # Progreso y estado IA
        self.ai_progress = ttk.Progressbar(self.tab_ai, mode="indeterminate")
        self.ai_progress.pack(fill=tk.X, pady=(2, 4))

        ttk.Label(
            self.tab_ai,
            textvariable=self.ai_status_var,
            font=("Segoe UI", 8),
            foreground="#333333",
            wraplength=690,
        ).pack(anchor="w", pady=(0, 4))

        # Área de texto resultado
        text_frame = ttk.Frame(self.tab_ai)
        text_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.ai_output_text = tk.Text(
            text_frame,
            wrap=tk.WORD,
            font=("Consolas", 9),
            yscrollcommand=scrollbar.set,
            padx=8,
            pady=8,
        )
        self.ai_output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.ai_output_text.yview)

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

        # Botones inferiores IA
        ai_bottom = ttk.Frame(self.tab_ai)
        ai_bottom.pack(fill=tk.X, pady=(6, 0))

        ttk.Button(ai_bottom, text="📋 Copiar texto", command=self._copy_ai_output).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(ai_bottom, text="💾 Guardar como .txt", command=self._save_ai_output).pack(side=tk.LEFT)

    def _center_drop_text(self, event):
        self.drop_canvas.coords(self.drop_text_id, event.width / 2, event.height / 2)

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
        self._update_default_output()

        self.drop_canvas.config(bg="#eaf4ea", highlightbackground="#88bb88")
        self.drop_canvas.itemconfigure(
            self.drop_text_id,
            text=f"✓ Fichero seleccionado: {path_obj.name}  (Haz clic para cambiar)",
            fill="#1e6b1e",
        )
        self.status_var.set(f"Fichero listo: {path_obj.name}")
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
        ext = f".{fmt}"
        chosen = filedialog.asksaveasfilename(
            title="Guardar documento resultante como...",
            defaultextension=ext,
            filetypes=[(f"Fichero {fmt.upper()} (*{ext})", f"*{ext}"), ("Todos (*.*)", "*.*")],
        )
        if chosen:
            self.output_path_var.set(chosen)

    def _on_format_changed(self):
        self._update_default_output()

    def _update_default_output(self):
        in_val = self.input_path_var.get().strip()
        if not in_val:
            return
        in_p = Path(in_val)
        fmt = self.format_var.get()
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
            logger.info(f"Iniciando conversión GUI: {in_path} -> {out_path} ({fmt})")
            start_t = time.perf_counter()
            result = DocumentConverter().convert(in_path, out_path, fmt, verbose=False)
            elapsed = time.perf_counter() - start_t
            logger.info(f"Conversión completada en {elapsed:.2f}s ({result.total_elements} elementos).")
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
            f"✓ Completado en {elapsed:.2f}s ({result.total_pages} pág., {result.total_elements} elementos).\n"
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

            runtime = LlamaRuntimeManager.get_instance()
            cache_key = (in_path, use_handwriting)

            # Paso 1: Extraer texto completo con la parte básica de Python (RapidOCR) o caché
            if self.cached_doc_key == cache_key and self.cached_doc_text is not None:
                doc_text = self.cached_doc_text
            else:
                update_status("Paso 1: Extrayendo todo el texto con el motor base (RapidOCR)...")
                pages = DocumentLoader.load_pages(in_path)
                texts = []

                if use_handwriting:
                    hw_engine = HandwritingOCREngine(runtime)
                    for p in pages:
                        update_status(f"Leyendo manuscrito página {p.page_number}/{len(pages)} con Qwen3-VL (Visión)...")
                        texts.append(hw_engine.transcribe_image(p.image, progress_cb=update_status))
                else:
                    ocr = OCREngine.get_instance()
                    for p in pages:
                        update_status(f"Ejecutando OCR base en página {p.page_number}/{len(pages)}...")
                        boxes = ocr.process_image(p.image)
                        lines = _group_boxes_into_lines(boxes)
                        texts.append("\n".join(" ".join(b.text for b in line) for line in lines))

                doc_text = "\n\n".join(texts).strip()
                self.cached_doc_text = doc_text
                self.cached_doc_key = cache_key
                logger.info(f"OCR completado ({len(doc_text)} caracteres extraídos, manuscrito={use_handwriting}).")

            if action == "transcribe":
                output_text = doc_text
            elif action == "summarize":
                output_text = DocumentQA(runtime).summarize(doc_text, progress_cb=update_status)
            elif action == "translate":
                output_text = DocumentTranslator(runtime).translate_to_spanish(doc_text, progress_cb=update_status)
            elif action == "anonymize":
                output_text = DocumentAnonymizer(runtime).anonymize(doc_text, progress_cb=update_status)
            elif action == "ask":
                output_text = DocumentQA(runtime).ask(doc_text, question, progress_cb=update_status)
            else:
                output_text = doc_text

            self.root.after(0, self._on_ai_success, output_text)
        except Exception as e:
            logger.exception(f"Error en acción IA '{action}' para '{in_path}': {e}")
            self.root.after(0, self._on_ai_error, str(e))

    def _on_ai_success(self, result_text: str):
        self.ai_progress.stop()
        for b in self.ai_buttons:
            b.config(state=tk.NORMAL)
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
        """Muestra el aviso de cumplimiento de normativas de IA, privacidad y licencia libre GNU GPL v3.0."""
        win = tk.Toplevel(self.root)
        win.title("Cumplimiento Normativo de IA y Licencia Libre — Open OCReader")
        win.geometry("660x520")
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
            "  No está permitido cerrar el código en un producto privativo.\n"
        )
        txt.insert("1.0", info_text)
        txt.config(state=tk.DISABLED)

        ttk.Button(win, text="Cerrar", command=win.destroy).pack(pady=(6, 10))

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
        from .updater import check_for_updates, apply_update

        self.status_var.set("Consultando actualizaciones en GitHub...")

        def worker():
            info = check_for_updates(__version__)
            def on_result():
                self.status_var.set(info.message)
                if info.update_available:
                    if messagebox.askyesno(
                        "Actualización disponible",
                        f"{info.message}\n\n¿Deseas descargar y aplicar la actualización ahora sin perder tus modelos?",
                    ):
                        try:
                            msg = apply_update()
                            messagebox.showinfo("Actualizado", f"{msg}\n\nReinicia la aplicación para aplicar los cambios.")
                        except Exception as e:
                            messagebox.showerror("Error al actualizar", str(e))
                else:
                    messagebox.showinfo("Actualizaciones", info.message)
            self.root.after(0, on_result)

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _open_path_crossplatform(path: str):
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)


def launch_gui():
    root = tk.Tk()
    OpenOCReaderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
