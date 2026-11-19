#!/usr/bin/env python3
"""
Open OCReader - Línea de comandos (CLI) principal.

Uso:
    python ocr_tool.py documento.png
    python ocr_tool.py factura.pdf -o factura_buscable.pdf
    python ocr_tool.py tabla.jpg -f xlsx -o datos.xlsx
    python ocr_tool.py contrato.pdf -f docx
    python ocr_tool.py notas.png -f txt
"""

import argparse
import sys
from pathlib import Path
from open_ocreader import DocumentConverter, __version__


def main():
    parser = argparse.ArgumentParser(
        prog="ocr_tool",
        description="Open OCReader - Conversión y digitalización documental 100% offline y fiel al diseño original.",
        epilog="Ejemplos:\n"
               "  python ocr_tool.py escaneo.png\n"
               "  python ocr_tool.py contrato.pdf -o contrato_buscable.pdf\n"
               "  python ocr_tool.py tabla.jpg -f xlsx -o resultado.xlsx\n"
               "  python ocr_tool.py recibo.png -f docx\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "input_file",
        help="Ruta al fichero de entrada (imágenes: JPG, PNG, TIFF, BMP, WebP o documentos PDF).",
    )

    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Ruta del fichero de salida generado. Por defecto: <nombre_original>_ocr.<formato>",
    )

    parser.add_argument(
        "-f",
        "--format",
        choices=["pdf", "docx", "xlsx", "txt", "json"],
        default="pdf",
        help="Formato de exportación deseado (por defecto: 'pdf' tipo Sandwich con texto buscable).",
    )

    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Modo silencioso (no muestra mensajes informativos en consola).",
    )

    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"Open OCReader v{__version__}",
    )

    args = parser.parse_args()

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"Error: No se ha encontrado el fichero especificado: {args.input_file}", file=sys.stderr)
        sys.exit(1)

    # Si el usuario especificó una extensión en -o pero no puso -f, deducir formato
    selected_format = args.format
    if args.output:
        out_ext = Path(args.output).suffix.lower().lstrip(".")
        if out_ext in {"pdf", "docx", "xlsx", "txt", "json"} and args.format == "pdf":
            selected_format = out_ext

    try:
        converter = DocumentConverter()
        result = converter.convert(
            input_path=str(input_path),
            output_path=args.output,
            output_format=selected_format,
            verbose=not args.quiet,
        )

        if not args.quiet:
            print(f"[Open OCReader] Fichero guardado en: {result.output_path}")

    except Exception as e:
        print(f"\n[Open OCReader] ERROR durante el procesamiento: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
