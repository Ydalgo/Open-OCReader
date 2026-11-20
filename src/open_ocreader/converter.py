"""
Orquestador principal de conversión de documentos de Open OCReader.
Soporta detección inteligente de PDFs ya buscables (omite OCR redundante),
formatos estándar y de Administración Pública (PDF, PDF/A, DOCX, ODT, XLSX, ODS, CSV, EPUB, TXT, JSON),
compresión PDF y conversión a escala de grises.
"""

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Callable, List, Optional, Tuple
from .engine import OCREngine, OCRBox
from .document_loader import DocumentLoader, PageData
from .formats.pdf_builder import build_sandwich_pdf, build_translated_pdf
from .formats.docx_builder import build_docx
from .formats.odt_builder import build_odt
from .formats.excel_builder import build_excel
from .formats.ods_builder import build_ods
from .formats.csv_builder import build_csv
from .formats.epub_builder import build_epub
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
    native_text_pages: int = 0
    ocr_pages: int = 0


class DocumentConverter:
    """
    Conversor universal de documentos: procesa entradas visuales o PDFs nativos
    y los exporta al formato deseado (PDF, PDF/A, DOCX, ODT, XLSX, ODS, CSV, EPUB, TXT, JSON).
    """

    SUPPORTED_FORMATS = {"pdf", "pdfa", "docx", "odt", "xlsx", "ods", "csv", "epub", "txt", "json"}

    def __init__(self):
        self._engine: Optional[OCREngine] = None

    @property
    def engine(self) -> OCREngine:
        if self._engine is None:
            self._engine = OCREngine.get_instance()
        return self._engine

    def convert(
        self,
        input_path: str,
        output_path: Optional[str] = None,
        output_format: str = "pdf",
        verbose: bool = True,
        force_ocr: bool = False,
        pdf_compression: str = "high",
        grayscale: bool = False,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> ConversionResult:
        """
        Ejecuta la digitalización / conversión completa del documento.

        :param input_path: Ruta de la imagen o PDF de entrada.
        :param output_path: Ruta de salida deseada (opcional; si se omite, se deduce).
        :param output_format: 'pdf', 'pdfa', 'docx', 'odt', 'xlsx', 'ods', 'csv', 'epub', 'txt', 'json'.
        :param verbose: Si es True, imprime información sobre el progreso.
        :param force_ocr: Si es True, fuerza OCR aunque el PDF ya tenga texto buscable.
        :param pdf_compression: 'high', 'balanced' o 'compact' (aplica a PDF y PDF/A).
        :param grayscale: Si es True, convierte imágenes/fondos a escala de grises en PDF/PDF/A.
        :param progress_cb: Callback opcional de progreso para la GUI.
        """
        fmt = output_format.lower().lstrip(".")
        if fmt not in self.SUPPORTED_FORMATS:
            raise ValueError(
                f"Formato '{output_format}' no soportado. "
                f"Formatos disponibles: {', '.join(sorted(self.SUPPORTED_FORMATS))}"
            )

        def notify(msg: str):
            if verbose:
                print(f"[Open OCReader] {msg}")
            if progress_cb:
                progress_cb(msg)

        start_time = time.perf_counter()
        in_p = Path(input_path)
        is_pdf_input = in_p.suffix.lower() == ".pdf"

        # Extensión real de salida (pdfa usa extensión .pdf)
        file_ext = "pdf" if fmt == "pdfa" else fmt
        suffix_tag = "_pdfa" if fmt == "pdfa" else "_ocr"

        if not output_path:
            out_p = in_p.parent / f"{in_p.stem}{suffix_tag}.{file_ext}"
            final_output_path = str(out_p)
        else:
            final_output_path = output_path

        # Ruta ultrarrápida para PDF nativo -> DOCX (usa pdf2docx directamente sin rasterizar)
        if fmt == "docx" and is_pdf_input and not force_ocr:
            pdf_info = DocumentLoader.inspect_pdf_text(str(in_p))
            if pdf_info and pdf_info["all_searchable"]:
                notify(
                    f"PDF con texto buscable detectado ({pdf_info['total_pages']} pág.): "
                    f"convirtiendo a Word (.docx) de forma nativa sin OCR..."
                )
                build_docx(
                    [],
                    final_output_path,
                    source_pdf_path=str(in_p),
                    use_native_pdf_converter=True,
                )
                # Verificar si pdf2docx extrajo texto editable (en PDFs Sandwich con texto invisible puede quedar vacío)
                from docx import Document as DocxReader
                try:
                    check_doc = DocxReader(final_output_path)
                    extracted_chars = sum(len(p.text.strip()) for p in check_doc.paragraphs) + sum(
                        len(c.text.strip()) for t in check_doc.tables for r in t.rows for c in r.cells
                    )
                except Exception:
                    extracted_chars = 0

                if extracted_chars >= 15:
                    elapsed = time.perf_counter() - start_time
                    return ConversionResult(
                        input_path=str(in_p),
                        output_path=final_output_path,
                        output_format=fmt,
                        total_pages=pdf_info["total_pages"],
                        total_elements=sum(len(t.split()) for t in pdf_info["texts"]),
                        elapsed_seconds=elapsed,
                        native_text_pages=pdf_info["total_pages"],
                        ocr_pages=0,
                    )
                notify("PDF tipo Sandwich detectado: reconstruyendo Word fiel con fondo y cuadros de texto editables (sin OCR)...")

        notify(f"Cargando documento: {in_p.name}")

        # 1. Cargar páginas (incluye detección de texto nativo embebido si es PDF)
        pages = DocumentLoader.load_pages(str(in_p))
        notify(f"Páginas detectadas: {len(pages)}")

        # 2. Procesar cada página: reutilizar texto nativo si existe (salvo force_ocr=True)
        pages_with_boxes: List[Tuple[PageData, List[OCRBox]]] = []
        total_elements = 0
        native_pages = 0
        ocr_pages = 0

        for page in pages:
            if page.has_embedded_text and not force_ocr and page.native_boxes:
                notify(f"Página {page.page_number}/{len(pages)}: texto buscable nativo detectado (sin OCR).")
                boxes = page.native_boxes
                native_pages += 1
            else:
                notify(f"Página {page.page_number}/{len(pages)}: ejecutando OCR...")
                boxes = self.engine.process_image(page.image)
                ocr_pages += 1

            total_elements += len(boxes)
            pages_with_boxes.append((page, boxes))

        # 3. Construir el fichero de salida según el formato
        notify(f"Generando salida '{fmt.upper()}' -> {Path(final_output_path).name}")

        if fmt in ("pdf", "pdfa"):
            build_sandwich_pdf(
                pages_with_boxes,
                final_output_path,
                pdfa=(fmt == "pdfa"),
                compression=pdf_compression,
                grayscale=grayscale,
            )
        elif fmt == "docx":
            build_docx(
                pages_with_boxes,
                final_output_path,
                source_pdf_path=str(in_p) if is_pdf_input else None,
                use_native_pdf_converter=False,
            )
        elif fmt == "odt":
            build_odt(pages_with_boxes, final_output_path)
        elif fmt == "xlsx":
            build_excel(pages_with_boxes, final_output_path)
        elif fmt == "ods":
            build_ods(pages_with_boxes, final_output_path)
        elif fmt == "csv":
            build_csv(pages_with_boxes, final_output_path)
        elif fmt == "epub":
            build_epub(pages_with_boxes, final_output_path, title=in_p.stem)
        elif fmt == "txt":
            build_txt(pages_with_boxes, final_output_path)
        elif fmt == "json":
            build_json(pages_with_boxes, final_output_path)

        elapsed = time.perf_counter() - start_time
        notify(
            f"✓ Completado en {elapsed:.2f}s "
            f"({native_pages} pág. nativas, {ocr_pages} OCR, {total_elements} elementos)."
        )

        return ConversionResult(
            input_path=str(in_p),
            output_path=final_output_path,
            output_format=fmt,
            total_pages=len(pages),
            total_elements=total_elements,
            elapsed_seconds=elapsed,
            native_text_pages=native_pages,
            ocr_pages=ocr_pages,
        )

    def translate_document(
        self,
        input_path: str,
        output_path: Optional[str] = None,
        output_format: str = "docx",
        target_lang: str = "Español",
        source_lang: str = "auto",
        preserve_layout: bool = True,
        pdf_compression: str = "high",
        grayscale: bool = False,
        force_ocr: bool = False,
        handwriting: bool = False,
        verbose: bool = True,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> ConversionResult:
        """
        Traduce un documento completo mediante IA local (Qwen3-VL) y lo exporta
        directamente al formato solicitado (PDF, PDF/A-2b, DOCX, ODT, EPUB, XLSX, ODS, CSV, TXT, JSON)
        conservando fondos, colores, imágenes (vía inpainting) y estructura.
        """
        fmt = output_format.lower().lstrip(".")
        if fmt not in self.SUPPORTED_FORMATS:
            raise ValueError(
                f"Formato '{output_format}' no soportado. "
                f"Formatos disponibles: {', '.join(sorted(self.SUPPORTED_FORMATS))}"
            )

        def notify(msg: str):
            if verbose:
                print(f"[Open OCReader] {msg}")
            if progress_cb:
                progress_cb(msg)

        from .ai import DocumentTranslator, HandwritingOCREngine, LlamaRuntimeManager

        start_time = time.perf_counter()
        in_p = Path(input_path)
        file_ext = "pdf" if fmt == "pdfa" else fmt
        safe_lang_tag = "".join(c for c in target_lang.lower() if c.isalnum())[:12] or "trad"
        if not output_path:
            out_p = in_p.parent / f"{in_p.stem}_traducido_{safe_lang_tag}.{file_ext}"
            final_output_path = str(out_p)
        else:
            final_output_path = output_path

        notify(f"Cargando documento para traducir a '{target_lang}': {in_p.name}")
        pages = DocumentLoader.load_pages(str(in_p))
        notify(f"Páginas detectadas: {len(pages)}")

        runtime = LlamaRuntimeManager.get_instance()
        translator = DocumentTranslator(runtime)
        hw_engine = HandwritingOCREngine(runtime) if handwriting else None

        pages_with_trans_boxes: List[Tuple[PageData, List[OCRBox]]] = []
        original_boxes_per_page: List[List[OCRBox]] = []
        total_elements = 0
        native_pages = 0
        ocr_pages = 0
        effective_preserve = preserve_layout

        for page in pages:
            if page.has_embedded_text and not force_ocr and not handwriting and page.native_boxes:
                notify(f"Página {page.page_number}/{len(pages)}: extrayendo texto nativo buscable...")
                orig_boxes = page.native_boxes
                native_pages += 1
            elif hw_engine is not None:
                notify(f"Página {page.page_number}/{len(pages)}: transcribiendo manuscrito con Qwen3-VL Visión...")
                hw_txt = hw_engine.transcribe_image(page.image, progress_cb=notify)
                raw_lines = [ln.strip() for ln in hw_txt.splitlines() if ln.strip()]
                orig_boxes = []
                n_ln = max(len(raw_lines), 1)
                margin_x = page.width_px * 0.06
                usable_w = max(page.width_px * 0.88, 40.0)
                usable_h = max(page.height_px * 0.88, 40.0)
                step_y = usable_h / float(n_ln)
                line_h = min(step_y * 0.82, max(page.height_px * 0.03, 18.0))
                for i_ln, ln_txt in enumerate(raw_lines):
                    y0 = (page.height_px * 0.06) + i_ln * step_y
                    y1 = y0 + line_h
                    x0 = margin_x
                    x1 = margin_x + usable_w
                    orig_boxes.append(OCRBox(box=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]], text=ln_txt, score=0.95))
                if orig_boxes:
                    # En manuscritos transcritos por VLM sin polígonos exactos, flujo limpio evita solapamientos
                    effective_preserve = False
                ocr_pages += 1
            else:
                notify(f"Página {page.page_number}/{len(pages)}: ejecutando OCR estructural...")
                orig_boxes = self.engine.process_image(page.image)
                ocr_pages += 1

            original_boxes_per_page.append(orig_boxes)
            notify(f"Página {page.page_number}/{len(pages)}: traduciendo contexto a '{target_lang}' con Qwen3-VL...")
            trans_boxes = translator.translate_boxes(
                orig_boxes,
                target_lang=target_lang,
                source_lang=source_lang,
                progress_cb=notify,
            )
            page.embedded_text = "\n".join((b.text or "").strip() for b in trans_boxes if (b.text or "").strip())
            total_elements += len(trans_boxes)
            pages_with_trans_boxes.append((page, trans_boxes))

        notify(f"Ensamblando documento traducido ({fmt.upper()}) -> {Path(final_output_path).name}")

        if fmt in ("pdf", "pdfa"):
            build_translated_pdf(
                pages_with_trans_boxes,
                final_output_path,
                pdfa=(fmt == "pdfa"),
                compression=pdf_compression,
                grayscale=grayscale,
                preserve_layout=effective_preserve,
                original_boxes_per_page=original_boxes_per_page,
            )
        elif fmt == "docx":
            build_docx(
                pages_with_trans_boxes,
                final_output_path,
                source_pdf_path=None,
                use_native_pdf_converter=False,
                original_boxes_per_page=original_boxes_per_page,
                compression=pdf_compression,
                grayscale=grayscale,
                preserve_layout=effective_preserve,
            )
        elif fmt == "odt":
            build_odt(
                pages_with_trans_boxes,
                final_output_path,
                original_boxes_per_page=original_boxes_per_page,
                compression=pdf_compression,
                grayscale=grayscale,
                preserve_layout=effective_preserve,
            )
        elif fmt == "epub":
            build_epub(
                pages_with_trans_boxes,
                final_output_path,
                title=f"{in_p.stem} ({target_lang})",
                include_page_images=effective_preserve,
            )
        elif fmt == "xlsx":
            build_excel(pages_with_trans_boxes, final_output_path)
        elif fmt == "ods":
            build_ods(pages_with_trans_boxes, final_output_path)
        elif fmt == "csv":
            build_csv(pages_with_trans_boxes, final_output_path)
        elif fmt == "txt":
            build_txt(pages_with_trans_boxes, final_output_path)
        elif fmt == "json":
            build_json(pages_with_trans_boxes, final_output_path)

        elapsed = time.perf_counter() - start_time
        notify(
            f"✓ Traducción a '{target_lang}' ({fmt.upper()}) completada en {elapsed:.2f}s "
            f"({len(pages)} página(s), {total_elements} bloques)."
        )

        return ConversionResult(
            input_path=str(in_p),
            output_path=final_output_path,
            output_format=fmt,
            total_pages=len(pages),
            total_elements=total_elements,
            elapsed_seconds=elapsed,
            native_text_pages=native_pages,
            ocr_pages=ocr_pages,
        )
