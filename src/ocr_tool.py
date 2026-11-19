#!/usr/bin/env python3
"""
Open OCReader - Línea de comandos (CLI) principal.

Uso:
    python ocr_tool.py                                     (abre la interfaz gráfica)
    python ocr_tool.py documento.png                       (convierte a PDF buscable)
    python ocr_tool.py factura.pdf -f xlsx                 (exporta a Excel)
    python ocr_tool.py carta_manuscrita.jpg -m -f txt      (OCR manuscrito con IA visual)
    python ocr_tool.py contrato.pdf --ai summarize         (resumen con IA local)
    python ocr_tool.py ingles.pdf --ai translate           (traducir al español)
    python ocr_tool.py nomina.pdf --ai anonymize           (anonimizar datos RGPD)
"""

import argparse
import sys
from pathlib import Path
from open_ocreader import DocumentConverter, DocumentLoader, OCREngine, launch_gui, __version__


def hide_console_window():
    """Oculta la ventana de terminal cmd en Windows cuando se activa el modo gráfico."""
    if sys.platform == "win32":
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)  # 0 = SW_HIDE
        except Exception:
            pass


def extract_full_text(input_path: Path, handwriting: bool = False, verbose: bool = True) -> str:
    """Extrae el texto completo del documento (con RapidOCR o Qwen3-VL si es manuscrito)."""
    pages = DocumentLoader.load_pages(str(input_path))
    if not pages:
        return ""

    texts = []
    if handwriting:
        from open_ocreader.ai import HandwritingOCREngine, LlamaRuntimeManager
        runtime = LlamaRuntimeManager.get_instance()
        hw_engine = HandwritingOCREngine(runtime)
        cb = print if verbose else None
        for page in pages:
            if verbose:
                print(f"[Open OCReader IA] Leyendo manuscrito página {page.page_number}/{len(pages)}...")
            t = hw_engine.transcribe_image(page.image, progress_cb=cb)
            texts.append(t)
    else:
        from open_ocreader.formats.docx_builder import _group_boxes_into_lines
        engine = OCREngine.get_instance()
        for page in pages:
            boxes = engine.process_image(page.image)
            lines = _group_boxes_into_lines(boxes)
            page_text = "\n".join(" ".join(b.text for b in line) for line in lines)
            texts.append(page_text)

    return "\n\n".join(texts).strip()


def main():
    parser = argparse.ArgumentParser(
        prog="ocr_tool",
        description="Open OCReader - Conversión e Inteligencia Documental 100% offline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "input_file",
        nargs="?",
        default=None,
        help="Ruta al fichero de entrada (imágenes o PDF). Si se omite, abre la interfaz gráfica.",
    )

    parser.add_argument("-g", "--gui", action="store_true", help="Forzar la apertura de la interfaz gráfica.")
    parser.add_argument("-o", "--output", default=None, help="Ruta del fichero de salida generado.")
    parser.add_argument(
        "-f",
        "--format",
        choices=["pdf", "docx", "xlsx", "txt", "json"],
        default="pdf",
        help="Formato de exportación deseado (por defecto: 'pdf').",
    )
    parser.add_argument(
        "-m",
        "--handwriting",
        action="store_true",
        help="Activa el modo de OCR visual avanzado con Qwen3-VL para letra manuscrita.",
    )
    parser.add_argument(
        "--ai",
        choices=["summarize", "translate", "anonymize", "ask"],
        default=None,
        help="Ejecuta una acción de IA local sobre el documento: summarize, translate, anonymize, ask.",
    )
    parser.add_argument(
        "--question",
        default=None,
        help="Pregunta a responder cuando se usa '--ai ask'.",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="Modo silencioso.")
    parser.add_argument("--clear-logs", action="store_true", help="Limpia todos los archivos de log.")
    parser.add_argument("--clear-cache", action="store_true", help="Limpia cachés y archivos temporales.")
    parser.add_argument("--check-update", action="store_true", help="Comprueba si hay una nueva versión en GitHub.")
    parser.add_argument("--update", action="store_true", help="Actualiza el proyecto desde GitHub sin desinstalar.")
    parser.add_argument("-v", "--version", action="version", version=f"Open OCReader v{__version__}")

    args = parser.parse_args()

    # Comandos de mantenimiento y actualización rápida
    if args.clear_logs:
        from open_ocreader.maintenance import clear_logs
        res = clear_logs()
        print(f"[Open OCReader] Logs limpiados (truncados: {res['truncated']}, eliminados: {res['removed']}).")
        sys.exit(0)

    if args.clear_cache:
        from open_ocreader.maintenance import clear_cache
        res = clear_cache()
        print(f"[Open OCReader] Caché limpiada ({res['deleted']} elementos eliminados).")
        sys.exit(0)

    if args.check_update or args.update:
        from open_ocreader.updater import check_for_updates, apply_update
        info = check_for_updates(__version__)
        print(f"[Open OCReader] {info.message}")
        if args.update and info.update_available:
            print(apply_update())
        sys.exit(0)

    if not args.input_file or args.gui:
        hide_console_window()
        launch_gui()
        sys.exit(0)

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"Error: No se ha encontrado el fichero especificado: {args.input_file}", file=sys.stderr)
        sys.exit(1)

    verbose = not args.quiet

    try:
        # Caso 1: Modo IA Semántica o Manuscrito puro a texto/IA
        if args.ai or args.handwriting:
            cb = print if verbose else None
            text = extract_full_text(input_path, handwriting=args.handwriting, verbose=verbose)

            if args.ai:
                from open_ocreader.ai import (
                    LlamaRuntimeManager,
                    DocumentAnonymizer,
                    DocumentTranslator,
                    DocumentQA,
                )
                runtime = LlamaRuntimeManager.get_instance()

                if args.ai == "summarize":
                    result_text = DocumentQA(runtime).summarize(text, progress_cb=cb)
                elif args.ai == "translate":
                    result_text = DocumentTranslator(runtime).translate_to_spanish(text, progress_cb=cb)
                elif args.ai == "anonymize":
                    result_text = DocumentAnonymizer(runtime).anonymize(text, progress_cb=cb)
                elif args.ai == "ask":
                    if not args.question:
                        print("Error: Debes especificar '--question \"tu pregunta\"' con '--ai ask'.", file=sys.stderr)
                        sys.exit(1)
                    result_text = DocumentQA(runtime).ask(text, args.question, progress_cb=cb)
            else:
                result_text = text

            if args.output:
                out_file = Path(args.output)
                out_file.write_text(result_text, encoding="utf-8")
                if verbose:
                    print(f"[Open OCReader] Resultado guardado en: {out_file}")
            else:
                print("\n" + "=" * 50)
                print(result_text)
                print("=" * 50)
            return

        # Caso 2: Conversión estructural estándar (RapidOCR -> PDF Sandwich, DOCX, XLSX, TXT, JSON)
        selected_format = args.format
        if args.output:
            out_ext = Path(args.output).suffix.lower().lstrip(".")
            if out_ext in {"pdf", "docx", "xlsx", "txt", "json"} and args.format == "pdf":
                selected_format = out_ext

        converter = DocumentConverter()
        result = converter.convert(
            input_path=str(input_path),
            output_path=args.output,
            output_format=selected_format,
            verbose=verbose,
        )

        if verbose:
            print(f"[Open OCReader] Fichero guardado en: {result.output_path}")

    except Exception as e:
        print(f"\n[Open OCReader] ERROR durante el procesamiento: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
