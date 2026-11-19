"""
Orquestador principal de conversión de documentos de Open OCReader.
"""

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Optional, List, Tuple
from .engine import OCREngine, OCRBox
from .document_loader import DocumentLoader, PageData
from .formats.pdf_builder import build_sandwich_pdf
from .formats.docx_builder import build_docx
from .formats.excel_builder import build_excel
from .formats.txt_builder import build_txt
from .formats.json_builder import build_json


@dataclass
class ConversionResult:
    """Resultado del proceso de conversión."""
    input_path: str
    output_path: str
    output_format: str
    total_pages: int
    total_elements: int
    elapsed_seconds: float


class DocumentConverter:
    """
    Conversor universal de documentos: procesa entradas visuales y las exporta
    al formato deseado (PDF sandwich, DOCX, XLSX, TXT, JSON).
    """

    SUPPORTED_FORMATS = {"pdf", "docx", "xlsx", "txt", "json"}

    def __init__(self):
        self.engine = OCREngine.get_instance()

    def convert(
        self,
        input_path: str,
        output_path: Optional[str] = None,
        output_format: str = "pdf",
        verbose: bool = True,
    ) -> ConversionResult:
        """
        Ejecuta la digitalización completa del documento.
        
        :param input_path: Ruta de la imagen o PDF de entrada.
        :param output_path: Ruta de salida deseada (opcional; si se omite, se deduce).
        :param output_format: Formato deseado ('pdf', 'docx', 'xlsx', 'txt', 'json').
        :param verbose: Si es True, imprime información sobre el progreso.
        """
        fmt = output_format.lower().lstrip(".")
        if fmt not in self.SUPPORTED_FORMATS:
            raise ValueError(
                f"Formato '{output_format}' no soportado. "
                f"Formatos disponibles: {', '.join(sorted(self.SUPPORTED_FORMATS))}"
            )

        start_time = time.perf_counter()
        in_p = Path(input_path)

        # Determinar ruta de salida por defecto si no se especificó
        if not output_path:
            out_p = in_p.parent / f"{in_p.stem}_ocr.{fmt}"
            final_output_path = str(out_p)
        else:
            final_output_path = output_path

        if verbose:
            print(f"[Open OCReader] Cargando documento: {in_p.name}")

        # 1. Cargar páginas
        pages = DocumentLoader.load_pages(str(in_p))
        if verbose:
            print(f"[Open OCReader] Páginas detectadas: {len(pages)}")

        # 2. Procesar OCR en cada página
        pages_with_boxes: List[Tuple[PageData, List[OCRBox]]] = []
        total_elements = 0

        for page in pages:
            if verbose and len(pages) > 1:
                print(f"[Open OCReader] Procesando página {page.page_number}/{len(pages)}...")
            boxes = self.engine.process_image(page.image)
            total_elements += len(boxes)
            pages_with_boxes.append((page, boxes))

        # 3. Construir el fichero de salida según el formato
        if verbose:
            print(f"[Open OCReader] Generando salida en formato '{fmt.upper()}' -> {final_output_path}")

        if fmt == "pdf":
            build_sandwich_pdf(pages_with_boxes, final_output_path)
        elif fmt == "docx":
            build_docx(pages_with_boxes, final_output_path)
        elif fmt == "xlsx":
            build_excel(pages_with_boxes, final_output_path)
        elif fmt == "txt":
            build_txt(pages_with_boxes, final_output_path)
        elif fmt == "json":
            build_json(pages_with_boxes, final_output_path)

        elapsed = time.perf_counter() - start_time
        if verbose:
            print(
                f"[Open OCReader] ✓ Completado en {elapsed:.2f}s "
                f"({total_elements} elementos de texto reconocidos)."
            )

        return ConversionResult(
            input_path=str(in_p),
            output_path=final_output_path,
            output_format=fmt,
            total_pages=len(pages),
            total_elements=total_elements,
            elapsed_seconds=elapsed,
        )
