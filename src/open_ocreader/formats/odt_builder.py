"""
Constructor de documentos OpenDocument Text (.odt) de alta fidelidad visual.
Recrea cada página tal cual (tamaño de página, fondos, imágenes, logos y colores)
mediante fondo limpio (inpainting) + cuadros de texto editables posicionados en
coordenadas exactas según estándar ODF 1.2 (compatible con LibreOffice / Word).
"""

import io
import zipfile
from typing import List, Optional, Tuple
from xml.sax.saxutils import escape as xml_escape
import numpy as np
from PIL import Image, ImageOps
from ..document_loader import PageData
from ..engine import OCRBox
from .docx_builder import create_clean_background, sample_text_color_hex, _group_boxes_into_lines


def build_odt(
    pages_with_boxes: List[Tuple[PageData, List[OCRBox]]],
    output_path: str,
    original_boxes_per_page: Optional[List[List[OCRBox]]] = None,
    compression: str = "high",
    grayscale: bool = False,
    preserve_layout: bool = True,
) -> str:
    """
    Genera un archivo OpenDocument Text (.odt) compatible con LibreOffice / Word.
    - preserve_layout=True: recrea tamaño de página, fondo limpio (inpainting) + cuadros editables.
    - preserve_layout=False: genera documento fluido limpio de párrafos y encabezados sin imágenes de fondo.
    """
    if not pages_with_boxes:
        raise ValueError("No hay páginas para generar el documento ODT.")

    from .pdf_builder import COMPRESSION_PRESETS
    preset = COMPRESSION_PRESETS.get(compression, COMPRESSION_PRESETS["high"])

    first_page, _ = pages_with_boxes[0]
    page_w_pt = first_page.width_pt
    page_h_pt = first_page.height_pt

    # Construir estilos de texto dinámicos y contenido por página
    auto_styles_parts: List[str] = [
        '<style:style style:name="bgFrame" style:family="graphic">'
        '<style:graphic-properties style:run-through="background" style:wrap="run-through" '
        'style:number-wrapped-paragraphs="no-limit" style:vertical-pos="from-top" '
        'style:vertical-rel="page" style:horizontal-pos="from-left" style:horizontal-rel="page" '
        'draw:stroke="none" draw:fill="none"/>'
        '</style:style>',
        '<style:style style:name="txtFrame" style:family="graphic">'
        '<style:graphic-properties style:run-through="foreground" style:wrap="run-through" '
        'style:vertical-pos="from-top" style:vertical-rel="page" '
        'style:horizontal-pos="from-left" style:horizontal-rel="page" '
        'draw:stroke="none" draw:fill="none" fo:padding="0pt"/>'
        '</style:style>',
        '<style:style style:name="PBreak" style:family="paragraph">'
        '<style:paragraph-properties fo:break-before="page" fo:margin-top="0pt" fo:margin-bottom="0pt"/>'
        '</style:style>',
        '<style:style style:name="PBox" style:family="paragraph">'
        '<style:paragraph-properties fo:margin-top="0pt" fo:margin-bottom="0pt" fo:line-height="100%"/>'
        '</style:style>',
        '<style:style style:name="PFlow" style:family="paragraph">'
        '<style:paragraph-properties fo:margin-top="0pt" fo:margin-bottom="6pt" fo:line-height="125%"/>'
        '<style:text-properties fo:font-size="11pt" style:font-name="Liberation Sans" fo:color="#111111"/>'
        '</style:style>',
        '<style:style style:name="HFlow" style:family="paragraph">'
        '<style:paragraph-properties fo:margin-top="10pt" fo:margin-bottom="6pt"/>'
        '<style:text-properties fo:font-size="14pt" fo:font-weight="bold" style:font-name="Liberation Sans" fo:color="#1f4e79"/>'
        '</style:style>',
    ]

    text_style_cache = {}
    body_elements: List[str] = []
    pictures: List[Tuple[str, bytes]] = []
    manifest_entries: List[str] = []

    for page_idx, (page_data, boxes) in enumerate(pages_with_boxes, start=1):
        if not preserve_layout:
            if page_idx > 1:
                body_elements.append('<text:p text:style-name="PBreak"/>')
            lines = _group_boxes_into_lines(boxes)
            heights = [b.height for b in boxes] if boxes else [15.0]
            median_h = sorted(heights)[len(heights) // 2]
            if lines:
                for line_boxes in lines:
                    line_txt = " ".join((b.text or "").strip() for b in line_boxes if (b.text or "").strip())
                    if not line_txt:
                        continue
                    max_h = max(b.height for b in line_boxes)
                    st = "HFlow" if max_h > median_h * 1.35 else "PFlow"
                    body_elements.append(f'<text:p text:style-name="{st}">{xml_escape(line_txt)}</text:p>')
            elif page_data.embedded_text and page_data.embedded_text.strip():
                for para in page_data.embedded_text.split("\n"):
                    if para.strip():
                        body_elements.append(f'<text:p text:style-name="PFlow">{xml_escape(para.strip())}</text:p>')
            continue

        # 1. Preparar fondo limpio preservando imágenes, iconos y colores
        erase_boxes = (
            original_boxes_per_page[page_idx - 1]
            if (original_boxes_per_page and (page_idx - 1) < len(original_boxes_per_page))
            else boxes
        )
        clean_bg = create_clean_background(page_data.image, erase_boxes)
        if grayscale:
            clean_bg = ImageOps.grayscale(clean_bg).convert("RGB")
        max_side = preset["max_side"]
        if max_side and max(clean_bg.size) > max_side:
            clean_bg.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

        bg_buf = io.BytesIO()
        bg_quality = 88 if compression == "high" else preset["quality"]
        clean_bg.save(bg_buf, format="JPEG", quality=bg_quality, optimize=True)
        pic_name = f"Pictures/page_{page_idx}.jpg"
        pictures.append((pic_name, bg_buf.getvalue()))
        manifest_entries.append(f'  <manifest:file-entry manifest:full-path="{pic_name}" manifest:media-type="image/jpeg"/>')

        # Imagen de fondo anclada a la página actual
        body_elements.append(
            f'<draw:frame draw:style-name="bgFrame" draw:name="BG_{page_idx}" '
            f'text:anchor-type="page" text:anchor-page-number="{page_idx}" '
            f'draw:z-index="0" svg:x="0pt" svg:y="0pt" '
            f'svg:width="{page_data.width_pt:.2f}pt" svg:height="{page_data.height_pt:.2f}pt">'
            f'<draw:image xlink:href="{pic_name}" xlink:type="simple" xlink:show="embed" xlink:actuate="onLoad"/>'
            f'</draw:frame>'
        )

        # 2. Cuadros de texto editables en coordenadas exactas
        rgb_np = np.array(page_data.image.convert("RGB"))
        scale_x = page_data.width_pt / float(max(page_data.width_px, 1))
        scale_y = page_data.height_pt / float(max(page_data.height_px, 1))
        heights = [b.height for b in boxes] if boxes else [15.0]
        median_h = sorted(heights)[len(heights) // 2]

        for b_idx, b in enumerate(boxes, start=1):
            text = b.text.strip()
            if not text:
                continue
            x_pt = b.min_x * scale_x
            y_pt = b.min_y * scale_y
            w_pt = max(b.width * scale_x * 1.12, 18.0)
            h_pt = max(b.height * scale_y * 1.25, 10.0)
            font_pt = round(max(5.5, min(b.height * scale_y * 0.78, 72.0)), 1)
            color_hex = "111111" if grayscale else sample_text_color_hex(rgb_np, b)
            is_bold = b.height > median_h * 1.35

            style_key = (font_pt, color_hex, is_bold)
            if style_key not in text_style_cache:
                s_name = f"T{len(text_style_cache) + 1}"
                text_style_cache[style_key] = s_name
                weight_attr = ' fo:font-weight="bold"' if is_bold else ""
                auto_styles_parts.append(
                    f'<style:style style:name="{s_name}" style:family="text">'
                    f'<style:text-properties fo:font-size="{font_pt}pt" fo:color="#{color_hex}" '
                    f'style:font-name="Liberation Sans"{weight_attr}/>'
                    f'</style:style>'
                )
            else:
                s_name = text_style_cache[style_key]

            body_elements.append(
                f'<draw:frame draw:style-name="txtFrame" draw:name="TB_{page_idx}_{b_idx}" '
                f'text:anchor-type="page" text:anchor-page-number="{page_idx}" '
                f'draw:z-index="{b_idx + 10}" svg:x="{x_pt:.2f}pt" svg:y="{y_pt:.2f}pt" '
                f'svg:width="{w_pt:.2f}pt" svg:height="{h_pt:.2f}pt">'
                f'<draw:text-box>'
                f'<text:p text:style-name="PBox"><text:span text:style-name="{s_name}">{xml_escape(text)}</text:span></text:p>'
                f'</draw:text-box>'
                f'</draw:frame>'
            )

        # Párrafo vacío para materializar cada página en el flujo del documento
        if page_idx == 1:
            body_elements.append('<text:p text:style-name="PBox"/>')
        else:
            body_elements.append('<text:p text:style-name="PBreak"/>')

    margin_pt = "0pt" if preserve_layout else "54pt"
    styles_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
    xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
    xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
    office:version="1.2">
  <office:font-face-decls>
    <style:font-face style:name="Liberation Sans" svg:font-family="'Liberation Sans', Arial, sans-serif"/>
  </office:font-face-decls>
  <office:automatic-styles>
    <style:page-layout style:name="pm1">
      <style:page-layout-properties fo:page-width="{page_w_pt:.2f}pt" fo:page-height="{page_h_pt:.2f}pt"
          fo:margin-top="{margin_pt}" fo:margin-bottom="{margin_pt}" fo:margin-left="{margin_pt}" fo:margin-right="{margin_pt}"/>
    </style:page-layout>
  </office:automatic-styles>
  <office:master-styles>
    <style:master-page style:name="Standard" style:page-layout-name="pm1"/>
  </office:master-styles>
</office:document-styles>
"""

    content_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
    xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
    xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
    office:version="1.2">
  <office:font-face-decls>
    <style:font-face style:name="Liberation Sans" svg:font-family="'Liberation Sans', Arial, sans-serif"/>
  </office:font-face-decls>
  <office:automatic-styles>
    {''.join(auto_styles_parts)}
  </office:automatic-styles>
  <office:body>
    <office:text>
      {''.join(body_elements)}
    </office:text>
  </office:body>
</office:document-content>
"""

    manifest_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">
  <manifest:file-entry manifest:full-path="/" manifest:version="1.2" manifest:media-type="application/vnd.oasis.opendocument.text"/>
  <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
  <manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>
{chr(10).join(manifest_entries)}
</manifest:manifest>
"""

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # El estándar ODF exige que 'mimetype' sea el primer archivo y SIN compresión
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        zf.writestr("styles.xml", styles_xml.encode("utf-8"))
        zf.writestr("content.xml", content_xml.encode("utf-8"))
        zf.writestr("META-INF/manifest.xml", manifest_xml.encode("utf-8"))
        for pic_name, pic_bytes in pictures:
            zf.writestr(pic_name, pic_bytes, compress_type=zipfile.ZIP_STORED)

    return output_path
