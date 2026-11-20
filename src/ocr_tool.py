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


def extract_full_text(
    input_path: Path,
    handwriting: bool = False,
    force_ocr: bool = False,
    verbose: bool = True,
) -> str:
    """Extrae el texto completo del documento (texto nativo si es PDF buscable, o OCR/Qwen3-VL)."""
    cb = print if verbose else None
    text, _stats = DocumentLoader.extract_text_smart(
        str(input_path),
        handwriting=handwriting,
        force_ocr=force_ocr,
        progress_cb=cb,
    )
    return text


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
    parser.add_argument(
        "--gui-engine",
        choices=["auto", "qt", "tk"],
        default="auto",
        help="Motor gráfico: 'qt' (PySide6 nativo, por defecto en 'auto') o 'tk' (respaldo Tkinter).",
    )
    parser.add_argument("-o", "--output", default=None, help="Ruta del fichero de salida generado.")
    parser.add_argument(
        "-f",
        "--format",
        choices=["pdf", "pdfa", "docx", "odt", "xlsx", "ods", "csv", "epub", "txt", "json"],
        default="pdf",
        help="Formato de exportación deseado (por defecto: 'pdf').",
    )
    parser.add_argument("--force-ocr", action="store_true", help="Fuerza OCR aunque el PDF ya tenga texto buscable.")
    parser.add_argument(
        "--compression",
        choices=["high", "balanced", "compact"],
        default="high",
        help="Nivel de compresión para salida PDF/PDF/A (high, balanced, compact).",
    )
    parser.add_argument("--grayscale", action="store_true", help="Convierte imágenes/fondos a escala de grises en PDF/PDF/A.")
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
    parser.add_argument(
        "--target-lang",
        default="Español",
        help="Idioma destino para '--ai translate' (ej. 'English', 'Français', 'Deutsch', '日本語').",
    )
    parser.add_argument(
        "--lang",
        choices=["es", "en", "sv", "fr", "de", "pt", "it"],
        default="es",
        help="Idioma de respuesta de la IA para resúmenes y preguntas (por defecto: 'es').",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="Modo silencioso.")
    parser.add_argument("--clear-logs", action="store_true", help="Limpia todos los archivos de log.")
    parser.add_argument("--clear-cache", action="store_true", help="Limpia cachés y archivos temporales.")
    parser.add_argument("--clean-reinstall", action="store_true", help="Borra build/, dist/, bin/ y reinstala llama.cpp y dependencias.")
    parser.add_argument("--check-update", action="store_true", help="Comprueba si hay una nueva versión en GitHub.")
    parser.add_argument("--update", action="store_true", help="Actualiza el proyecto desde GitHub sin desinstalar.")
    parser.add_argument(
        "--governance-report",
        default=None,
        metavar="RUTA",
        help="Genera un informe de gobernanza de IA y ENS (.docx, .md o .json) en la ruta indicada.",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"Open OCReader v{__version__} | Software Libre GNU GPL v3.0 (Copyleft) | 100% Local (EU AI Act / RGPD / ENS)",
    )

    args = parser.parse_args()

    # Comandos de mantenimiento y actualización rápida
    if args.governance_report:
        from open_ocreader.governance import generate_governance_report
        out = generate_governance_report(args.governance_report)
        print(f"[Open OCReader] Informe de gobernanza IA generado en: {out}")
        sys.exit(0)

    if args.clean_reinstall:
        from open_ocreader.maintenance import clean_and_reinstall
        res = clean_and_reinstall(progress_cb=print)
        print(f"[Open OCReader] Limpieza y reinstalación completada: {res}")
        sys.exit(0)

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
        launch_gui(engine=args.gui_engine)
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
            text = extract_full_text(
                input_path,
                handwriting=args.handwriting,
                force_ocr=args.force_ocr,
                verbose=verbose,
            )

            if args.ai:
                from open_ocreader.ai import (
                    LlamaRuntimeManager,
                    DocumentAnonymizer,
                    DocumentTranslator,
                    DocumentQA,
                )
                runtime = LlamaRuntimeManager.get_instance()

                from open_ocreader.i18n import get_llm_language_name
                response_lang = get_llm_language_name(args.lang)

                if args.ai == "summarize":
                    result_text = DocumentQA(runtime).summarize(text, response_lang=response_lang, progress_cb=cb)
                elif args.ai == "translate":
                    result_text = DocumentTranslator(runtime).translate(text, target_lang=args.target_lang, progress_cb=cb)
                elif args.ai == "anonymize":
                    result_text = DocumentAnonymizer(runtime).anonymize(text, progress_cb=cb)
                elif args.ai == "ask":
                    if not args.question:
                        print("Error: Debes especificar '--question \"tu pregunta\"' con '--ai ask'.", file=sys.stderr)
                        sys.exit(1)
                    result_text = DocumentQA(runtime).ask(text, args.question, response_lang=response_lang, progress_cb=cb)
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

        # Caso 2: Conversión estructural estándar
        selected_format = args.format
        if args.output:
            out_ext = Path(args.output).suffix.lower().lstrip(".")
            if out_ext in DocumentConverter.SUPPORTED_FORMATS and args.format == "pdf":
                selected_format = out_ext

        converter = DocumentConverter()
        result = converter.convert(
            input_path=str(input_path),
            output_path=args.output,
            output_format=selected_format,
            verbose=verbose,
            force_ocr=args.force_ocr,
            pdf_compression=args.compression,
            grayscale=args.grayscale,
        )

        if verbose:
            print(f"[Open OCReader] Fichero guardado en: {result.output_path}")

    except Exception as e:
        print(f"\n[Open OCReader] ERROR durante el procesamiento: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
