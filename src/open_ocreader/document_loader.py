"""
Cargador universal de documentos: imágenes (PNG, JPG, TIFF, BMP, WebP) y PDFs.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Generator
from PIL import Image, ImageSequence
import pypdfium2 as pdfium


@dataclass
class PageData:
    """Información y contenido visual de una página."""
    page_number: int
    image: Image.Image
    width_pt: float
    height_pt: float

    @property
    def width_px(self) -> int:
        return self.image.width

    @property
    def height_px(self) -> int:
        return self.image.height


class DocumentLoader:
    """Carga y normaliza documentos para el proceso de OCR."""

    SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}

    @classmethod
    def load_pages(cls, file_path: str, render_scale: float = 2.5) -> List[PageData]:
        """
        Carga las páginas del documento como objetos PageData.
        
        :param file_path: Ruta al fichero (imagen o PDF).
        :param render_scale: Factor de escala al rasterizar PDFs (2.5 ≈ 180 DPI, equilibrio óptimo velocidad/precisión).
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"No se ha encontrado el fichero: {file_path}")

        ext = path.suffix.lower()
        if ext == ".pdf":
            return cls._load_pdf(path, render_scale)
        elif ext in cls.SUPPORTED_IMAGE_EXTS:
            return cls._load_image(path)
        else:
            # Intentar abrir con PIL por si tiene extensión no estándar
            try:
                return cls._load_image(path)
            except Exception as e:
                raise ValueError(
                    f"Formato de archivo no soportado ({ext}). "
                    f"Formatos válidos: PDF, JPG, PNG, TIFF, BMP, WebP. Error: {e}"
                )

    @classmethod
    def _load_pdf(cls, path: Path, render_scale: float) -> List[PageData]:
        pages: List[PageData] = []
        pdf = pdfium.PdfDocument(str(path))

        try:
            for idx in range(len(pdf)):
                page = pdf[idx]
                # Dimensiones originales en puntos PDF (1/72 de pulgada)
                w_pt, h_pt = page.get_size()

                # Renderizar página como imagen PIL para OCR y fondo
                pil_img = page.render(scale=render_scale).to_pil()
                pages.append(
                    PageData(
                        page_number=idx + 1,
                        image=pil_img,
                        width_pt=float(w_pt),
                        height_pt=float(h_pt),
                    )
                )
        finally:
            pdf.close()

        return pages

    @classmethod
    def _load_image(cls, path: Path) -> List[PageData]:
        pages: List[PageData] = []
        with Image.open(path) as img:
            # Obtener DPI si está disponible en metadatos EXIF
            dpi_info = img.info.get("dpi")
            dpi_x = 72.0
            if dpi_info and isinstance(dpi_info, (tuple, list)) and len(dpi_info) > 0 and dpi_info[0] > 0:
                dpi_x = float(dpi_info[0])
            elif max(img.size) > 1400:
                dpi_x = 150.0  # Estimación estándar para escaneos de alta resolución sin DPI en cabecera

            scale_pt = 72.0 / dpi_x

            # Manejar posibles imágenes multipágina (ej. TIFF)
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
