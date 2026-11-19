"""
Interfaz gráfica de usuario (GUI) nativa para Open OCReader.
Permite seleccionar ficheros de entrada, formato y destino de forma visual.
"""

import os
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from .converter import DocumentConverter


class OpenOCReaderGUI:
    """Ventana principal de la interfaz gráfica de Open OCReader."""

    FORMAT_OPTIONS = [
        ("PDF Buscable (Sandwich)", "pdf", "Conserva el diseño visual 100% original con capa de texto invisible"),
        ("Microsoft Word (.docx)", "docx", "Documento editable estructurado en párrafos y títulos"),
        ("Microsoft Excel (.xlsx)", "xlsx", "Tabla de cálculo con celdas mapeadas por coordenadas"),
        ("Texto plano (.txt)", "txt", "Volcado de texto en orden de lectura natural"),
        ("JSON Estructurado (.json)", "json", "Coordenadas geométricas, polígonos y puntuación de confianza"),
    ]

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Open OCReader - Suite de Digitalización Documental")
        self.root.geometry("680x620")
        self.root.minsize(580, 560)

        # Configurar estilo ttk moderno
        self.style = ttk.Style()
        try:
            self.style.theme_use("vista" if "vista" in self.style.theme_names() else "clam")
        except Exception:
            pass

        self.input_path_var = tk.StringVar()
        self.output_path_var = tk.StringVar()
        self.format_var = tk.StringVar(value="pdf")
        self.status_var = tk.StringVar(value="Selecciona un fichero para comenzar.")
        self.last_generated_file = None

        self._build_ui()

    def _build_ui(self):
        # Contenedor principal con margen
        main_frame = ttk.Frame(self.root, padding="16 16 16 16")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. Cabecera
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 14))

        title_lbl = ttk.Label(
            header_frame,
            text="Open OCReader 📄🔍",
            font=("Segoe UI", 16, "bold"),
        )
        title_lbl.pack(anchor="w")

        subtitle_lbl = ttk.Label(
            header_frame,
            text="Digitalización y conversión documental 100% local, privada y fiel al diseño original.",
            font=("Segoe UI", 9),
            foreground="#555555",
        )
        subtitle_lbl.pack(anchor="w")

        # 2. Sección: Fichero de entrada
        input_group = ttk.LabelFrame(main_frame, text=" 1. Fichero de entrada (Imagen o PDF) ", padding="10")
        input_group.pack(fill=tk.X, pady=(0, 12))

        input_entry_frame = ttk.Frame(input_group)
        input_entry_frame.pack(fill=tk.X)

        self.input_entry = ttk.Entry(input_entry_frame, textvariable=self.input_path_var, font=("Segoe UI", 9))
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        btn_browse_in = ttk.Button(input_entry_frame, text="Examinar...", command=self._browse_input)
        btn_browse_in.pack(side=tk.RIGHT)

        # 3. Sección: Formato de salida
        format_group = ttk.LabelFrame(main_frame, text=" 2. Formato de salida ", padding="10")
        format_group.pack(fill=tk.X, pady=(0, 12))

        for label_text, fmt_key, desc in self.FORMAT_OPTIONS:
            rb_frame = ttk.Frame(format_group)
            rb_frame.pack(fill=tk.X, pady=2)

            rb = ttk.Radiobutton(
                rb_frame,
                text=label_text,
                value=fmt_key,
                variable=self.format_var,
                command=self._on_format_changed,
            )
            rb.pack(side=tk.LEFT)

            desc_lbl = ttk.Label(rb_frame, text=f"({desc})", font=("Segoe UI", 8), foreground="#666666")
            desc_lbl.pack(side=tk.LEFT, padx=(8, 0))

        # 4. Sección: Destino
        output_group = ttk.LabelFrame(main_frame, text=" 3. Fichero de salida ", padding="10")
        output_group.pack(fill=tk.X, pady=(0, 14))

        output_entry_frame = ttk.Frame(output_group)
        output_entry_frame.pack(fill=tk.X)

        self.output_entry = ttk.Entry(output_entry_frame, textvariable=self.output_path_var, font=("Segoe UI", 9))
        self.output_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        btn_browse_out = ttk.Button(output_entry_frame, text="Guardar como...", command=self._browse_output)
        btn_browse_out.pack(side=tk.RIGHT)

        # 5. Sección de Acción y Progreso
        action_frame = ttk.Frame(main_frame)
        action_frame.pack(fill=tk.X, pady=(4, 8))

        self.btn_convert = ttk.Button(
            action_frame,
            text="🚀  Digitalizar y Convertir",
            command=self._start_conversion,
        )
        self.btn_convert.pack(fill=tk.X, ipady=6)

        # Barra de progreso
        self.progress_bar = ttk.Progressbar(main_frame, mode="indeterminate")
        self.progress_bar.pack(fill=tk.X, pady=(6, 6))

        # Etiqueta de estado
        self.status_lbl = ttk.Label(
            main_frame,
            textvariable=self.status_var,
            font=("Segoe UI", 9),
            foreground="#222222",
            wraplength=620,
        )
        self.status_lbl.pack(anchor="w")

        # 6. Botones de acción posterior (Abrir fichero / carpeta)
        self.post_action_frame = ttk.Frame(main_frame)
        self.post_action_frame.pack(fill=tk.X, pady=(12, 0))

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
            self.input_path_var.set(chosen)
            self._update_default_output()

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
        """Actualiza la extensión del fichero de salida cuando el usuario cambia el formato."""
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
            messagebox.showwarning("Fichero no especificado", "Por favor, selecciona un fichero de entrada.")
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

        # Ejecutar OCR en un hilo separado para que la ventana no se congele
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
                os.startfile(self.last_generated_file)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo abrir el archivo:\n{e}")

    def _open_folder(self):
        if self.last_generated_file:
            folder = str(Path(self.last_generated_file).parent)
            try:
                os.startfile(folder)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo abrir la carpeta:\n{e}")


def launch_gui():
    """Punto de entrada para iniciar la aplicación gráfica."""
    root = tk.Tk()
    app = OpenOCReaderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
