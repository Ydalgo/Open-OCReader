"""
Constructor de PDF tipo 'Sandwich' (Buscable y con fidelidad visual 100%).
Soporta:
  - Compresión configurable ('high', 'balanced', 'compact').
  - Conversión a escala de grises (grayscale) para reducir tamaño y estandarizar escaneos.
  - Generación de PDF/A-2b (estándar de archivo a largo plazo para Administraciones Públicas)
    con perfil de color sRGB OutputIntent y metadatos XMP pdfaid.
"""

import html
import io
from datetime import datetime, timezone
from typing import List, Optional, Tuple
import numpy as np
import pymupdf as fitz
from PIL import Image, ImageCms, ImageOps
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from ..document_loader import PageData
from ..engine import OCRBox

try:
    import pikepdf
    HAS_PIKEPDF = True
except ImportError:
    HAS_PIKEPDF = False


COMPRESSION_PRESETS = {
    "high": {"quality": 92, "max_side": 0},        # Sin reescalado, máxima calidad
    "balanced": {"quality": 75, "max_side": 2200}, # Equilibrado (ideal oficina)
    "compact": {"quality": 55, "max_side": 1500},  # Máxima compresión (tamaño mínimo)
}


def _prepare_page_image(
    img: Image.Image,
    compression: str = "high",
    grayscale: bool = False,
) -> ImageReader:
    """Optimiza la imagen de fondo según el nivel de compresión y escala de grises."""
    preset = COMPRESSION_PRESETS.get(compression, COMPRESSION_PRESETS["high"])
    work = img.copy()

    if grayscale:
        work = ImageOps.grayscale(work)
    elif work.mode not in ("RGB", "L"):
        work = work.convert("RGB")

    max_side = preset["max_side"]
    if max_side and max(work.size) > max_side:
        work.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    work.save(buf, format="JPEG", quality=preset["quality"], optimize=True)
    buf.seek(0)
    return ImageReader(buf)


def _apply_pdfa_metadata_and_profile(pdf_path: str, grayscale: bool = False) -> None:
    """
    Post-procesa el PDF con pikepdf para añadir cumplimiento PDF/A-2b:
      - Metadatos XMP con pdfaid:part=2 y pdfaid:conformance=B
      - OutputIntent GTS_PDFA1 con perfil ICC sRGB embebido
      - Sin cifrado ni compresión de flujos incompatible
    """
    if not HAS_PIKEPDF:
        return

    icc_bytes = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    xmp_xml = f"""<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description rdf:about=""
        xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/"
        xmlns:dc="http://purl.org/dc/elements/1.1/"
        xmlns:xmp="http://ns.adobe.com/xap/1.0/"
        xmlns:pdf="http://ns.adobe.com/pdf/1.3/">
      <pdfaid:part>2</pdfaid:part>
      <pdfaid:conformance>B</pdfaid:conformance>
      <pdf:Producer>Open OCReader (PDF/A-2b)</pdf:Producer>
      <xmp:CreatorTool>Open OCReader</xmp:CreatorTool>
      <xmp:CreateDate>{now_iso}</xmp:CreateDate>
      <xmp:ModifyDate>{now_iso}</xmp:ModifyDate>
      <dc:format>application/pdf</dc:format>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>""".encode("utf-8")

    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        # 1. Adjuntar metadatos XMP
        metadata_stream = pikepdf.Stream(pdf, xmp_xml)
        metadata_stream["/Type"] = pikepdf.Name("/Metadata")
        metadata_stream["/Subtype"] = pikepdf.Name("/XML")
        pdf.Root["/Metadata"] = pdf.make_indirect(metadata_stream)

        # 2. Adjuntar perfil ICC sRGB como OutputIntent PDF/A
        icc_stream = pikepdf.Stream(pdf, icc_bytes)
        icc_stream["/N"] = 3
        icc_stream["/Alternate"] = pikepdf.Name("/DeviceRGB")

        output_intent = pikepdf.Dictionary(
            Type=pikepdf.Name("/OutputIntent"),
            S=pikepdf.Name("/GTS_PDFA1"),
            OutputConditionIdentifier=pikepdf.String("sRGB IEC61966-2.1"),
            RegistryName=pikepdf.String("http://www.color.org"),
            Info=pikepdf.String("sRGB IEC61966-2.1"),
            DestOutputProfile=pdf.make_indirect(icc_stream),
        )
        pdf.Root["/OutputIntents"] = pikepdf.Array([pdf.make_indirect(output_intent)])

        # Guardar con versión PDF 1.7 (estándar para PDF/A-2b) y sin cifrado
        pdf.save(
            pdf_path,
            min_version="1.7",
            linearize=False,
            object_stream_mode=pikepdf.ObjectStreamMode.preserve,
        )


def build_sandwich_pdf(
    pages_with_boxes: List[Tuple[PageData, List[OCRBox]]],
    output_path: str,
    pdfa: bool = False,
    compression: str = "high",
    grayscale: bool = False,
) -> str:
    """
    Crea un PDF donde cada página contiene:
      1. La imagen del documento como fondo (con compresión/escala de grises opcionales).
      2. Una capa invisible de texto con render mode 3 alineada exactamente en las coordenadas (x, y, w, h).
      3. Si pdfa=True, añade perfil ICC sRGB y metadatos XMP para cumplimiento PDF/A-2b.
    """
    if not pages_with_boxes:
        raise ValueError("No hay páginas para generar el PDF.")

    first_page, _ = pages_with_boxes[0]
    c = canvas.Canvas(output_path, pagesize=(first_page.width_pt, first_page.height_pt))
    c.setCreator("Open OCReader")
    c.setTitle("Documento digitalizado - Open OCReader")

    for page_data, boxes in pages_with_boxes:
        c.setPageSize((page_data.width_pt, page_data.height_pt))

        # 1. Dibujar imagen de fondo optimizada
        img_reader = _prepare_page_image(
            page_data.image,
            compression=compression,
            grayscale=grayscale,
        )
        c.drawImage(
            img_reader,
            0,
            0,
            width=page_data.width_pt,
            height=page_data.height_pt,
            preserveAspectRatio=False,
        )

        # 2. Factores de escala entre píxeles de la imagen original y puntos del PDF
        scale_x = page_data.width_pt / float(page_data.width_px)
        scale_y = page_data.height_pt / float(page_data.height_px)

        # 3. Superponer la capa de texto invisible
        for item in boxes:
            text = item.text.strip()
            if not text:
                continue

            min_x = item.min_x
            max_x = item.max_x
            min_y = item.min_y
            max_y = item.max_y

            box_w_pt = max((max_x - min_x) * scale_x, 1.0)
            box_h_pt = max((max_y - min_y) * scale_y, 1.0)

            pdf_x = min_x * scale_x
            pdf_y = page_data.height_pt - (max_y * scale_y)

            font_size = max(box_h_pt * 0.85, 4.0)
            font_name = "Helvetica"

            natural_w = c.stringWidth(text, font_name, font_size)
            if natural_w > 0:
                horiz_scale = (box_w_pt / natural_w) * 100.0
                horiz_scale = max(30.0, min(horiz_scale, 300.0))
            else:
                horiz_scale = 100.0

            text_obj = c.beginText()
            text_obj.setTextRenderMode(3)
            text_obj.setFont(font_name, font_size)
            text_obj.setHorizScale(horiz_scale)
            text_obj.setTextOrigin(pdf_x, pdf_y + (box_h_pt * 0.12))
            text_obj.textLine(text)

            c.drawText(text_obj)

        c.showPage()

    c.save()

    if pdfa:
        _apply_pdfa_metadata_and_profile(output_path, grayscale=grayscale)

    return output_path


def build_translated_pdf(
    pages_with_boxes: List[Tuple[PageData, List[OCRBox]]],
    output_path: str,
    pdfa: bool = False,
    compression: str = "high",
    grayscale: bool = False,
    preserve_layout: bool = True,
    original_boxes_per_page: Optional[List[List[OCRBox]]] = None,
) -> str:
    """
    Construye un PDF (o PDF/A-2b) con texto traducido visible y seleccionable Unicode.
    - Si preserve_layout=True: conserva fondos, imágenes, logotipos y colores originales
      limpiando el texto original mediante inpainting y superponiendo la traducción
      en coordenadas equivalentes con color/tamaño reales.
    - Si preserve_layout=False: genera páginas limpias fluidas sin imagen de fondo escaneada.
    """
    if not pages_with_boxes:
        raise ValueError("No hay páginas para generar el PDF traducido.")

    from .docx_builder import create_clean_background, sample_text_color_hex, _group_boxes_into_lines

    preset = COMPRESSION_PRESETS.get(compression, COMPRESSION_PRESETS["high"])
    doc = fitz.open()
    try:
        for idx, (page_data, trans_boxes) in enumerate(pages_with_boxes):
            w_pt = max(float(page_data.width_pt), 100.0)
            h_pt = max(float(page_data.height_pt), 100.0)
            new_page = doc.new_page(width=w_pt, height=h_pt)

            if preserve_layout:
                erase_boxes = (
                    original_boxes_per_page[idx]
                    if (original_boxes_per_page and idx < len(original_boxes_per_page))
                    else trans_boxes
                )
                clean_bg = create_clean_background(page_data.image, erase_boxes)
                if grayscale:
                    clean_bg = ImageOps.grayscale(clean_bg).convert("RGB")

                max_side = preset["max_side"]
                if max_side and max(clean_bg.size) > max_side:
                    clean_bg.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

                buf = io.BytesIO()
                clean_bg.save(buf, format="JPEG", quality=preset["quality"], optimize=True)
                new_page.insert_image(new_page.rect, stream=buf.getvalue())

                rgb_np = np.array(page_data.image.convert("RGB"))
                scale_x = w_pt / float(max(page_data.width_px, 1))
                scale_y = h_pt / float(max(page_data.height_px, 1))
                heights = [b.height for b in trans_boxes] if trans_boxes else [15.0]
                median_h = sorted(heights)[len(heights) // 2]

                for b in trans_boxes:
                    txt = (b.text or "").strip()
                    if not txt:
                        continue
                    x_pt = max(2.0, min(w_pt - 20.0, b.min_x * scale_x))
                    y_pt = max(2.0, min(h_pt - 14.0, b.min_y * scale_y))
                    w_box = max(b.width * scale_x * 1.12, 24.0)
                    h_box = max(b.height * scale_y * 1.28, 12.0)

                    rect = fitz.Rect(
                        x_pt,
                        y_pt,
                        min(w_pt - 2.0, x_pt + w_box),
                        min(h_pt - 2.0, y_pt + h_box),
                    )
                    if rect.width < 4 or rect.height < 4:
                        continue

                    font_pt = max(5.5, min(h_box * 0.72, 64.0))
                    color_hex = "111111" if grayscale else sample_text_color_hex(rgb_np, b)
                    bold_css = "font-weight:bold;" if b.height > median_h * 1.35 else ""
                    snippet = (
                        f'<div style="font-family:sans-serif;font-size:{font_pt:.1f}pt;'
                        f'color:#{color_hex};line-height:1.05;{bold_css}">{html.escape(txt)}</div>'
                    )
                    new_page.insert_htmlbox(rect, snippet, scale_low=0)
            else:
                lines = _group_boxes_into_lines(trans_boxes)
                heights = [b.height for b in trans_boxes] if trans_boxes else [15.0]
                median_h = sorted(heights)[len(heights) // 2]
                html_parts = []
                if lines:
                    for line_boxes in lines:
                        line_txt = " ".join((b.text or "").strip() for b in line_boxes if (b.text or "").strip())
                        if not line_txt:
                            continue
                        max_h = max(b.height for b in line_boxes)
                        if max_h > median_h * 1.35:
                            html_parts.append(
                                f'<h3 style="font-family:sans-serif;color:#1f4e79;margin:6px 0 4px 0;">'
                                f'{html.escape(line_txt)}</h3>'
                            )
                        else:
                            html_parts.append(
                                f'<p style="font-family:sans-serif;font-size:10.5pt;color:#111111;'
                                f'line-height:1.35;margin:3px 0;">{html.escape(line_txt)}</p>'
                            )
                else:
                    raw_text = (page_data.embedded_text or "").strip()
                    for para in raw_text.split("\n"):
                        if para.strip():
                            html_parts.append(
                                f'<p style="font-family:sans-serif;font-size:10.5pt;color:#111111;'
                                f'line-height:1.35;margin:3px 0;">{html.escape(para.strip())}</p>'
                            )

                body_html = f"<div>{''.join(html_parts) or '<p></p>'}</div>"
                clean_rect = fitz.Rect(36, 36, max(72.0, w_pt - 36), max(72.0, h_pt - 36))
                new_page.insert_htmlbox(clean_rect, body_html, scale_low=0)

        doc.save(output_path, deflate=True, garbage=4)
    finally:
        doc.close()

    if pdfa:
        _apply_pdfa_metadata_and_profile(output_path, grayscale=grayscale)

    return output_path
