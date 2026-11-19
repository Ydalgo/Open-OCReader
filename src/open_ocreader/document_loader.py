"""
Cargador universal de documentos: imágenes (PNG, JPG, TIFF, BMP, WebP) y PDFs.
Incluye detección inteligente de texto buscable embebido en PDFs página por página
para evitar OCR innecesario cuando el documento ya es seleccionable.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from PIL import Image, ImageSequence
import pypdfium2 as pdfium
from .engine import OCRBox, OCREngine
from .security import MAX_IMAGE_PIXELS, MAX_PDF_PAGES, SecurityError, validate_input_file

try:
    import pymupdf as fitz
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

# Protección frente a bombas de descompresión de imágenes (DecompressionBomb)
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

# Umbral mínimo de caracteres alfanuméricos para considerar que una página PDF ya tiene texto buscable
MIN_EMBEDDED_TEXT_CHARS = 15


@dataclass
class PageData:
    """Información y contenido visual de una página."""
    page_number: int
    image: Image.Image
    width_pt: float
    height_pt: float
    embedded_text: str = ""
    has_embedded_text: bool = False
    native_boxes: List[OCRBox] = field(default_factory=list)

    @property
    def width_px(self) -> int:
        return self.image.width

    @property
    def height_px(self) -> int:
        return self.image.height


class DocumentLoader:
    """Carga y normaliza documentos para el proceso de OCR o extracción directa."""

    SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}

    @staticmethod
    def _has_meaningful_text(text: str) -> bool:
        alnum = sum(1 for c in text if c.isalnum())
        return alnum >= MIN_EMBEDDED_TEXT_CHARS

    @classmethod
    def inspect_pdf_text(cls, file_path: str) -> Optional[Dict[str, object]]:
        """
        Inspecciona rápidamente un PDF SIN rasterizar imágenes para saber qué páginas
        ya contienen texto buscable embebido.
        Devuelve None si no es un PDF.
        """
        path = Path(file_path)
        if path.suffix.lower() != ".pdf" or not path.exists():
            return None

        validate_input_file(path)

        texts_per_page: List[str] = []
        searchable_flags: List[bool] = []

        if HAS_PYMUPDF:
            doc = fitz.open(str(path))
            try:
                if len(doc) > MAX_PDF_PAGES:
                    raise SecurityError(
                        f"El PDF tiene {len(doc)} páginas y supera el límite seguro de {MAX_PDF_PAGES} páginas."
                    )
                for page in doc:
                    txt = (page.get_text("text") or "").strip()
                    texts_per_page.append(txt)
                    searchable_flags.append(cls._has_meaningful_text(txt))
            finally:
                doc.close()
        else:
            pdf = pdfium.PdfDocument(str(path))
            try:
                total_pages = len(pdf)
                if total_pages > MAX_PDF_PAGES:
                    raise SecurityError(
                        f"El PDF tiene {total_pages} páginas y supera el límite seguro de {MAX_PDF_PAGES} páginas."
                    )
                for idx in range(total_pages):
                    page = pdf[idx]
                    tp = page.get_textpage()
                    txt = (tp.get_text_range() or "").strip()
                    texts_per_page.append(txt)
                    searchable_flags.append(cls._has_meaningful_text(txt))
            finally:
                pdf.close()

        native_count = sum(1 for f in searchable_flags if f)
        total = len(searchable_flags)
        return {
            "total_pages": total,
            "native_pages": native_count,
            "scanned_pages": total - native_count,
            "all_searchable": total > 0 and native_count == total,
            "texts": texts_per_page,
            "flags": searchable_flags,
        }

    @classmethod
    def extract_text_smart(
        cls,
        file_path: str,
        handwriting: bool = False,
        force_ocr: bool = False,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> Tuple[str, Dict[str, int]]:
        """
        Extrae el texto completo del documento de la forma más rápida posible:
          - Si es un PDF y una página ya tiene texto buscable (y no es manuscrito ni force_ocr),
            extrae el texto nativo directamente en milisegundos sin rasterizar ni lanzar RapidOCR.
          - Solo rasteriza y ejecuta OCR en las páginas escaneadas (o en imágenes).
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"No se ha encontrado el fichero: {file_path}")
        validate_input_file(path)

        from .formats.docx_builder import _group_boxes_into_lines

        ext = path.suffix.lower()
        if ext == ".pdf" and not handwriting and not force_ocr:
            info = cls.inspect_pdf_text(str(path))
            if info is not None:
                total = info["total_pages"]
                native_count = info["native_pages"]
                texts: List[str] = list(info["texts"])
                flags: List[bool] = list(info["flags"])

                if info["all_searchable"]:
                    if progress_cb:
                        progress_cb(
                            f"PDF con texto buscable detectado ({total} pág.): extracción directa sin OCR."
                        )
                    return "\n\n".join(t for t in texts if t).strip(), {
                        "total_pages": total,
                        "native_pages": total,
                        "ocr_pages": 0,
                    }

                # PDF híbrido o completamente escaneado: solo renderizar y pasar OCR donde falta texto
                ocr_indices = [i for i, has_t in enumerate(flags) if not has_t]
                if progress_cb:
                    progress_cb(
                        f"PDF analizado: {native_count} pág. con texto nativo, "
                        f"{len(ocr_indices)} pág. requieren OCR..."
                    )

                pdf = pdfium.PdfDocument(str(path))
                ocr = OCREngine.get_instance()
                try:
                    for count, idx in enumerate(ocr_indices, start=1):
                        if progress_cb:
                            progress_cb(
                                f"Ejecutando OCR en página escaneada {idx + 1}/{total} ({count}/{len(ocr_indices)})..."
                            )
                        pil_img = pdf[idx].render(scale=2.5).to_pil()
                        boxes = ocr.process_image(pil_img)
                        lines = _group_boxes_into_lines(boxes)
                        texts[idx] = "\n".join(" ".join(b.text for b in line) for line in lines)
                finally:
                    pdf.close()

                return "\n\n".join(t for t in texts if t).strip(), {
                    "total_pages": total,
                    "native_pages": native_count,
                    "ocr_pages": len(ocr_indices),
                }

        # Caso imágenes, manuscrito o force_ocr=True
        pages = cls.load_pages(str(path))
        texts_out: List[str] = []

        if handwriting:
            from .ai import HandwritingOCREngine, LlamaRuntimeManager
            runtime = LlamaRuntimeManager.get_instance()
            hw_engine = HandwritingOCREngine(runtime)
            for p in pages:
                if progress_cb:
                    progress_cb(f"Leyendo manuscrito página {p.page_number}/{len(pages)} con Qwen3-VL (Visión)...")
                texts_out.append(hw_engine.transcribe_image(p.image, progress_cb=progress_cb))
        else:
            ocr = OCREngine.get_instance()
            for p in pages:
                if progress_cb:
                    progress_cb(f"Ejecutando OCR base en página {p.page_number}/{len(pages)}...")
                boxes = ocr.process_image(p.image)
                lines = _group_boxes_into_lines(boxes)
                texts_out.append("\n".join(" ".join(b.text for b in line) for line in lines))

        return "\n\n".join(t for t in texts_out if t).strip(), {
            "total_pages": len(pages),
            "native_pages": 0,
            "ocr_pages": len(pages),
        }

    @classmethod
    def load_pages(cls, file_path: str, render_scale: float = 2.5) -> List[PageData]:
        """
        Carga las páginas del documento como objetos PageData.

        :param file_path: Ruta al fichero (imagen o PDF).
        :param render_scale: Factor de escala al rasterizar PDFs (2.5 ≈ 180 DPI).
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"No se ha encontrado el fichero: {file_path}")

        # Validación de seguridad: extensión, tamaño y firma mágica
        validate_input_file(path)

        ext = path.suffix.lower()
        if ext == ".pdf":
            return cls._load_pdf(path, render_scale)
        elif ext in cls.SUPPORTED_IMAGE_EXTS:
            return cls._load_image(path)
        else:
            try:
                return cls._load_image(path)
            except Exception as e:
                raise ValueError(
                    f"Formato de archivo no soportado ({ext}). "
                    f"Formatos válidos: PDF, JPG, PNG, TIFF, BMP, WebP. Error: {e}"
                )

    @classmethod
    def _extract_native_boxes_pymupdf(
        cls, fitz_page, scale_x: float, scale_y: float
    ) -> List[OCRBox]:
        """Convierte las líneas de texto nativo de PyMuPDF en OCRBox en coordenadas de píxeles."""
        boxes: List[OCRBox] = []
        text_dict = fitz_page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                line_text = "".join(s.get("text", "") for s in spans).strip()
                if not line_text:
                    continue
                x0, y0, x1, y1 = line.get("bbox", (0, 0, 0, 0))
                px0, py0 = x0 * scale_x, y0 * scale_y
                px1, py1 = x1 * scale_x, y1 * scale_y
                boxes.append(
                    OCRBox(
                        box=[[px0, py0], [px1, py0], [px1, py1], [px0, py1]],
                        text=line_text,
                        score=1.0,
                    )
                )
        return boxes

    @classmethod
    def _load_pdf(cls, path: Path, render_scale: float) -> List[PageData]:
        pages: List[PageData] = []
        pdf = pdfium.PdfDocument(str(path))
        fitz_doc = fitz.open(str(path)) if HAS_PYMUPDF else None

        try:
            total_pages = len(pdf)
            if total_pages > MAX_PDF_PAGES:
                raise SecurityError(
                    f"El PDF tiene {total_pages} páginas y supera el límite seguro de {MAX_PDF_PAGES} páginas."
                )
            for idx in range(total_pages):
                page = pdf[idx]
                w_pt, h_pt = page.get_size()
                pil_img = page.render(scale=render_scale).to_pil()

                embedded_text = ""
                native_boxes: List[OCRBox] = []
                if fitz_doc is not None and idx < len(fitz_doc):
                    fpage = fitz_doc[idx]
                    embedded_text = (fpage.get_text("text") or "").strip()
                    if cls._has_meaningful_text(embedded_text):
                        sx = pil_img.width / float(w_pt) if w_pt else render_scale
                        sy = pil_img.height / float(h_pt) if h_pt else render_scale
                        native_boxes = cls._extract_native_boxes_pymupdf(fpage, sx, sy)
                else:
                    tp = page.get_textpage()
                    embedded_text = (tp.get_text_range() or "").strip()

                has_text = cls._has_meaningful_text(embedded_text)
                pages.append(
                    PageData(
                        page_number=idx + 1,
                        image=pil_img,
                        width_pt=float(w_pt),
                        height_pt=float(h_pt),
                        embedded_text=embedded_text,
                        has_embedded_text=has_text,
                        native_boxes=native_boxes,
                    )
                )
        finally:
            pdf.close()
            if fitz_doc is not None:
                fitz_doc.close()

        return pages

    @classmethod
    def _load_image(cls, path: Path) -> List[PageData]:
        pages: List[PageData] = []
        with Image.open(path) as img:
            dpi_info = img.info.get("dpi")
            dpi_x = 72.0
            if dpi_info and isinstance(dpi_info, (tuple, list)) and len(dpi_info) > 0 and dpi_info[0] > 0:
                dpi_x = float(dpi_info[0])
            elif max(img.size) > 1400:
                dpi_x = 150.0

            scale_pt = 72.0 / dpi_x

            frame_idx = 1
            for frame in ImageSequence.Iterator(img):
                frame_copy = frame.copy().convert("RGB")
                w_pt = frame_copy.width * scale_pt
                h_pt = frame_copy.height * scale_pt
                pages.append(
                    PageData(
                        page_number=frame_idx,
                        image=frame_copy,
                        width_pt=w_pt,
                        height_pt=h_pt,
                    )
                )
                frame_idx += 1

        return pages
