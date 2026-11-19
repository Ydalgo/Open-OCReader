"""
Interfaz gráfica de usuario (GUI) nativa para Open OCReader.
Incluye zona de arrastrar y soltar (Drag & Drop), soporte para pegar (Ctrl+V)
desde el portapapeles y ejecución en segundo plano.
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

# Intentar cargar soporte nativo de Drag & Drop en Windows
try:
    import windnd
    HAS_WINDND = True
except ImportError:
    HAS_WINDND = False

# Intentar cargar soporte de portapapeles de Windows para ficheros copiados
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
        self.root.title("Open OCReader - Suite de Digitalización Documental")
        self.root.geometry("700x680")
        self.root.minsize(620, 620)

        # Configurar estilo ttk moderno
        self.style = ttk.Style()
        try:
            self.style.theme_use("vista" if "vista" in self.style.theme_names() else "clam")
        except Exception:
            pass

        self.input_path_var = tk.StringVar()
        self.output_path_var = tk.StringVar()
        self.format_var = tk.StringVar(value="pdf")
        self.status_var = tk.StringVar(value="Arrastra un fichero a la caja, pulsa 'Examinar' o pega con Ctrl+V.")
        self.last_generated_file = None

        self._build_ui()
        self._setup_drag_and_drop()
        self._setup_clipboard_paste()

    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding="16 14 16 14")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. Cabecera
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 10))

        title_lbl = ttk.Label(
            header_frame,
            text="Open OCReader 📄🔍",
            font=("Segoe UI", 16, "bold"),
        )
        title_lbl.pack(anchor="w")

        subtitle_lbl = ttk.Label(
            header_frame,
            text="Digitalización 100% local, privada y fiel al diseño original. Sin ventanas terminales.",
            font=("Segoe UI", 9),
            foreground="#555555",
        )
        subtitle_lbl.pack(anchor="w")

        # 2. Sección: Zona de Arrastrar y Soltar (Drop Zone)
        drop_frame = ttk.LabelFrame(main_frame, text=" 1. Fichero de entrada ", padding="10")
        drop_frame.pack(fill=tk.X, pady=(0, 10))

        # Canvas interactivo para simular la zona de Drop
        self.drop_canvas = tk.Canvas(
            drop_frame,
            bg="#f4f6f9",
            height=75,
            highlightthickness=1,
            highlightbackground="#b0c4de",
            relief="flat",
        )
        self.drop_canvas.pack(fill=tk.X, pady=(0, 8))

        self.drop_text_id = self.drop_canvas.create_text(
            330, 38,
            text="📥 Arrastra y suelta aquí tu fichero (PDF, JPG, PNG, TIFF)\no usa el botón 'Examinar' o pulsa Pegar (Ctrl + V)",
            font=("Segoe UI", 10, "italic"),
            fill="#334466",
            justify="center",
        )
        self.drop_canvas.bind("<Configure>", self._center_drop_text)
        self.drop_canvas.bind("<Button-1>", lambda e: self._browse_input())

        # Barra de botones y campo de ruta
        entry_row = ttk.Frame(drop_frame)
        entry_row.pack(fill=tk.X)

        self.input_entry = ttk.Entry(entry_row, textvariable=self.input_path_var, font=("Segoe UI", 9))
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        btn_paste = ttk.Button(entry_row, text="📋 Pegar (Ctrl+V)", command=self._paste_from_clipboard)
        btn_paste.pack(side=tk.LEFT, padx=(0, 6))

        btn_browse_in = ttk.Button(entry_row, text="Examinar...", command=self._browse_input)
        btn_browse_in.pack(side=tk.RIGHT)

        # 3. Sección: Formato de salida
        format_group = ttk.LabelFrame(main_frame, text=" 2. Formato de salida deseado ", padding="8")
        format_group.pack(fill=tk.X, pady=(0, 10))

        for label_text, fmt_key, desc in self.FORMAT_OPTIONS:
            rb_frame = ttk.Frame(format_group)
            rb_frame.pack(fill=tk.X, pady=1)

            rb = ttk.Radiobutton(
                rb_frame,
                text=label_text,
                value=fmt_key,
                variable=self.format_var,
                command=self._on_format_changed,
            )
            rb.pack(side=tk.LEFT)

            desc_lbl = ttk.Label(rb_frame, text=f"— {desc}", font=("Segoe UI", 8), foreground="#666666")
            desc_lbl.pack(side=tk.LEFT, padx=(8, 0))

        # 4. Sección: Destino
        output_group = ttk.LabelFrame(main_frame, text=" 3. Destino del fichero ", padding="8")
        output_group.pack(fill=tk.X, pady=(0, 12))

        output_entry_frame = ttk.Frame(output_group)
        output_entry_frame.pack(fill=tk.X)

        self.output_entry = ttk.Entry(output_entry_frame, textvariable=self.output_path_var, font=("Segoe UI", 9))
        self.output_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        btn_browse_out = ttk.Button(output_entry_frame, text="Guardar como...", command=self._browse_output)
        btn_browse_out.pack(side=tk.RIGHT)

        # 5. Sección de Acción y Progreso
        action_frame = ttk.Frame(main_frame)
        action_frame.pack(fill=tk.X, pady=(2, 6))

        self.btn_convert = ttk.Button(
            action_frame,
            text="🚀  Digitalizar y Convertir",
            command=self._start_conversion,
        )
        self.btn_convert.pack(fill=tk.X, ipady=6)

        # Barra de progreso
        self.progress_bar = ttk.Progressbar(main_frame, mode="indeterminate")
        self.progress_bar.pack(fill=tk.X, pady=(4, 4))

        # Etiqueta de estado
        self.status_lbl = ttk.Label(
            main_frame,
            textvariable=self.status_var,
            font=("Segoe UI", 9),
            foreground="#222222",
            wraplength=650,
        )
        self.status_lbl.pack(anchor="w")

        # 6. Botones de acción posterior (Abrir fichero / carpeta)
        self.post_action_frame = ttk.Frame(main_frame)
        self.post_action_frame.pack(fill=tk.X, pady=(8, 0))

        self.btn_open_file = ttk.Button(
            self.post_action_frame,
            text="📄 Abrir fichero generado",
            command=self._open_file,
            state=tk.DISABLED,
        )
        self.btn_open_file.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_open_folder = ttk.Button(
            self.post_action_frame,
            text="📁 Abrir carpeta contenedora",
            command=self._open_folder,
            state=tk.DISABLED,
        )
        self.btn_open_folder.pack(side=tk.LEFT)

    def _center_drop_text(self, event):
        """Centra el texto dentro del área de arrastrar y soltar."""
        self.drop_canvas.coords(self.drop_text_id, event.width / 2, event.height / 2)

    def _setup_drag_and_drop(self):
        """Configura el arrastrar y soltar de ficheros mediante windnd en Windows."""
        if HAS_WINDND:
            try:
                windnd.hook_dropfiles(self.root, func=self._on_files_dropped)
            except Exception as e:
                print(f"[Aviso] No se pudo inicializar Drag & Drop: {e}")

    def _on_files_dropped(self, files):
        """Callback cuando se sueltan ficheros sobre la ventana."""
        if not files:
            return

        # En Windows windnd devuelve bytes o str
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
        """Asocia la combinación Ctrl+V para pegar ficheros o imágenes."""
        self.root.bind_all("<Control-v>", lambda e: self._paste_from_clipboard())
        self.root.bind_all("<Control-V>", lambda e: self._paste_from_clipboard())

    def _paste_from_clipboard(self):
        """Pega un fichero copiado en el Explorador, una imagen capturada o una ruta de texto."""
        # 1. Comprobar si hay una imagen directa en el portapapeles (ej. recorte de pantalla con Win+Shift+S)
        try:
            img = ImageGrab.grabclipboard()
            if img is not None:
                # Guardar en un fichero temporal en la carpeta temporal de usuario
                temp_dir = Path(tempfile.gettempdir()) / "open_ocreader"
                temp_dir.mkdir(parents=True, exist_ok=True)
                timestamp = int(time.time())
                temp_img_path = temp_dir / f"captura_portapapeles_{timestamp}.png"
                img.save(str(temp_img_path))
                self._set_input_file(str(temp_img_path))
                self.status_var.set("✓ Imagen capturada del portapapeles cargada correctamente.")
                return
        except Exception:
            pass

        # 2. Comprobar si hay ficheros copiados en el portapapeles de Windows (CF_HDROP)
        if HAS_WIN32CLIP:
            try:
                win32clipboard.OpenClipboard()
                try:
                    if win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
                        files = win32clipboard.GetClipboardData(win32con.CF_HDROP)
                        if files:
                            self._set_input_file(files[0])
                            self.status_var.set(f"✓ Fichero pegado desde el portapapeles: {Path(files[0]).name}")
                            return
                finally:
                    win32clipboard.CloseClipboard()
            except Exception:
                pass

        # 3. Comprobar si el portapapeles contiene texto con una ruta de fichero existente
        try:
            clipboard_text = self.root.clipboard_get().strip().strip('"').strip("'")
            if Path(clipboard_text).is_file():
                self._set_input_file(clipboard_text)
                self.status_var.set(f"✓ Ruta cargada: {Path(clipboard_text).name}")
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
        self._update_default_output()
        # Actualizar aspecto del drop_canvas para mostrar el fichero cargado
        self.drop_canvas.config(bg="#eaf4ea", highlightbackground="#88bb88")
        self.drop_canvas.itemconfigure(
            self.drop_text_id,
            text=f"✓ Fichero seleccionado: {path_obj.name}\n(Haz clic para cambiarlo o pulsa 'Digitalizar y Convertir')",
            fill="#1e6b1e",
        )
        self.status_var.set(f"Fichero listo: {path_obj.name}")

    def _browse_input(self):
        filetypes = [
            ("Ficheros soportados", "*.pdf;*.png;*.jpg;*.jpeg;*.tiff;*.tif;*.bmp;*.webp"),
            ("Documentos PDF (*.pdf)", "*.pdf"),
            ("Imágenes (*.png;*.jpg;*.jpeg;*.tiff;*.bmp)", "*.png;*.jpg;*.jpeg;*.tiff;*.bmp"),
            ("Todos los archivos (*.*)", "*.*"),
        ]
        chosen = filedialog.askopenfilename(
            title="Seleccionar documento o imagen",
            filetypes=filetypes,
        )
        if chosen:
            self._set_input_file(chosen)

    def _browse_output(self):
        fmt = self.format_var.get()
        ext = f".{fmt}"
        filetypes = [
            (f"Fichero {fmt.upper()} (*{ext})", f"*{ext}"),
            ("Todos los archivos (*.*)", "*.*"),
        ]
        chosen = filedialog.asksaveasfilename(
            title="Guardar documento resultante como...",
            defaultextension=ext,
            filetypes=filetypes,
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
        default_out = in_p.parent / f"{in_p.stem}_ocr.{fmt}"
        self.output_path_var.set(str(default_out))

    def _start_conversion(self):
        in_path = self.input_path_var.get().strip()
        out_path = self.output_path_var.get().strip()
        fmt = self.format_var.get()

        if not in_path:
            messagebox.showwarning("Fichero no especificado", "Por favor, arrastra o selecciona un fichero primero.")
            return

        if not Path(in_path).exists():
            messagebox.showerror("Error", f"No se ha encontrado el fichero:\n{in_path}")
            return

        if not out_path:
            self._update_default_output()
            out_path = self.output_path_var.get().strip()

        # Deshabilitar controles mientras procesa
        self.btn_convert.config(state=tk.DISABLED)
        self.btn_open_file.config(state=tk.DISABLED)
        self.btn_open_folder.config(state=tk.DISABLED)
        self.progress_bar.start(10)
        self.status_var.set(f"Procesando '{Path(in_path).name}'... Espere por favor.")

        thread = threading.Thread(
            target=self._run_conversion_worker,
            args=(in_path, out_path, fmt),
            daemon=True,
        )
        thread.start()

    def _run_conversion_worker(self, in_path: str, out_path: str, fmt: str):
        try:
            start_t = time.perf_counter()
            converter = DocumentConverter()
            result = converter.convert(
                input_path=in_path,
                output_path=out_path,
                output_format=fmt,
                verbose=False,
            )
            elapsed = time.perf_counter() - start_t
            self.root.after(0, self._on_conversion_success, result, elapsed)
        except Exception as e:
            self.root.after(0, self._on_conversion_error, str(e))

    def _on_conversion_success(self, result, elapsed: float):
        self.progress_bar.stop()
        self.btn_convert.config(state=tk.NORMAL)
        self.last_generated_file = result.output_path
        self.btn_open_file.config(state=tk.NORMAL)
        self.btn_open_folder.config(state=tk.NORMAL)

        msg = (
            f"✓ Completado con éxito en {elapsed:.2f}s.\n"
            f"Páginas: {result.total_pages} | Elementos reconocidos: {result.total_elements}\n"
            f"Guardado en: {result.output_path}"
        )
        self.status_var.set(msg)
        messagebox.showinfo(
            "Conversión completada",
            f"¡El documento se ha digitalizado y guardado con éxito!\n\nDestino: {result.output_path}",
        )

    def _on_conversion_error(self, err_msg: str):
        self.progress_bar.stop()
        self.btn_convert.config(state=tk.NORMAL)
        self.status_var.set(f"Error al procesar: {err_msg}")
        messagebox.showerror("Error de conversión", f"Ocurrió un error durante el OCR:\n\n{err_msg}")

    def _open_file(self):
        if self.last_generated_file and Path(self.last_generated_file).exists():
            try:
                self._open_path_crossplatform(self.last_generated_file)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo abrir el archivo:\n{e}")

    def _open_folder(self):
        if self.last_generated_file:
            folder = str(Path(self.last_generated_file).parent)
            try:
                self._open_path_crossplatform(folder)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo abrir la carpeta:\n{e}")

    @staticmethod
    def _open_path_crossplatform(path: str):
        """Abre un archivo o carpeta en Windows, Linux o macOS."""
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)


def launch_gui():
    """Punto de entrada para iniciar la aplicación gráfica."""
    root = tk.Tk()
    app = OpenOCReaderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
