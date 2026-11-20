"""
Constructor de documentos Microsoft Word (.docx) de alta fidelidad visual.
- Para PDFs con texto nativo: utiliza pdf2docx (basado en PyMuPDF) para preservar
  tablas, columnas, fuentes, colores, imágenes y fondos de forma nativa.
- Para imágenes y PDFs escaneados (OCR): reconstruye el documento con fidelidad visual
  exacta (fondo con imágenes/gráficos preservados mediante inpainting del texto rasterizado
  + cuadros de texto editables posicionados en coordenadas exactas con su color y tamaño).
"""

import io
from typing import List, Optional, Tuple
import cv2
import numpy as np
from PIL import Image, ImageOps
from docx import Document
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Emu, Pt
from ..document_loader import PageData
from ..engine import OCRBox

try:
    from pdf2docx import Converter as PDF2DocxConverter
    HAS_PDF2DOCX = True
except ImportError:
    HAS_PDF2DOCX = False


def sample_text_color_hex(img_rgb: np.ndarray, box: OCRBox) -> str:
    """
    Estima el color RGB del texto dentro de una caja OCR comparando el interior
    con el color de fondo del borde de la caja. Devuelve color hexadecimal 'RRGGBB'.
    """
    h, w = img_rgb.shape[:2]
    x0 = max(0, int(box.min_x))
    y0 = max(0, int(box.min_y))
    x1 = min(w, max(x0 + 1, int(box.max_x)))
    y1 = min(h, max(y0 + 1, int(box.max_y)))

    crop = img_rgb[y0:y1, x0:x1]
    if crop.size == 0:
        return "000000"

    # Color de fondo estimado desde los bordes de la caja
    top = crop[0, :, :]
    bottom = crop[-1, :, :]
    left = crop[:, 0, :]
    right = crop[:, -1, :]
    border = np.concatenate([top, bottom, left, right], axis=0)
    bg_color = np.median(border, axis=0)

    # Los píxeles de texto son los más distantes al color de fondo
    pixels = crop.reshape(-1, 3).astype(np.float32)
    dists = np.linalg.norm(pixels - bg_color.astype(np.float32), axis=1)
    threshold = np.percentile(dists, 93)
    fg_pixels = pixels[dists >= threshold]

    if len(fg_pixels) == 0:
        return "000000"

    fg_color = np.median(fg_pixels, axis=0).astype(int)
    fg_color = np.clip(fg_color, 0, 255)
    return f"{fg_color[0]:02X}{fg_color[1]:02X}{fg_color[2]:02X}"


def create_clean_background(pil_image: Image.Image, boxes: List[OCRBox]) -> Image.Image:
    """
    Genera una copia del fondo de la página eliminando el texto rasterizado
    mediante inpainting (OpenCV) para conservar intactos fondos, iconos, logos,
    tablas, fotos y colores sin duplicar texto visualmente.
    """
    rgb = np.array(pil_image.convert("RGB"))
    if not boxes:
        return pil_image.convert("RGB")

    h, w = rgb.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)

    for b in boxes:
        x0 = max(0, int(b.min_x) - 2)
        y0 = max(0, int(b.min_y) - 2)
        x1 = min(w, int(b.max_x) + 2)
        y1 = min(h, int(b.max_y) + 2)
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = 255

    # Para imágenes muy grandes, acelerar inpainting en resolución controlada y reescalar solo las zonas enmascaradas
    max_inpaint_side = 1600
    if max(h, w) > max_inpaint_side:
        scale = max_inpaint_side / float(max(h, w))
        sw, sh = max(1, int(w * scale)), max(1, int(h * scale))
        small_bgr = cv2.cvtColor(cv2.resize(rgb, (sw, sh), interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2BGR)
        small_mask = cv2.resize(mask, (sw, sh), interpolation=cv2.INTER_NEAREST)
        inpainted_small = cv2.inpaint(small_bgr, small_mask, 3, cv2.INPAINT_TELEA)
        inpainted_rgb = cv2.cvtColor(
            cv2.resize(inpainted_small, (w, h), interpolation=cv2.INTER_LINEAR),
            cv2.COLOR_BGR2RGB,
        )
        # Mantener píxeles originales fuera de las cajas de texto para nitidez 100% en gráficos
        result = rgb.copy()
        result[mask > 0] = inpainted_rgb[mask > 0]
    else:
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        inpainted_bgr = cv2.inpaint(bgr, mask, 3, cv2.INPAINT_TELEA)
        result = cv2.cvtColor(inpainted_bgr, cv2.COLOR_BGR2RGB)

    return Image.fromarray(result)


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _add_behind_page_image(paragraph, doc, img_bytes: bytes, width_pt: float, height_pt: float, pic_id: int):
    """Inserta una imagen anclada a la página completa detrás del texto (behindDoc=1)."""
    rel_id = doc.part.relate_to(
        doc.part.package.image_parts.get_or_add_image_part(io.BytesIO(img_bytes)),
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
    )
    cx = int(width_pt * 12700)   # 1 pt = 12700 EMU
    cy = int(height_pt * 12700)

    drawing_xml = f"""
    <w:drawing {nsdecls('w', 'wp', 'a', 'pic', 'r')}>
      <wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0"
                 relativeHeight="0" behindDoc="1" locked="0" layoutInCell="1" allowOverlap="1">
        <wp:simplePos x="0" y="0"/>
        <wp:positionH relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionH>
        <wp:positionV relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionV>
        <wp:extent cx="{cx}" cy="{cy}"/>
        <wp:effectExtent l="0" t="0" r="0" b="0"/>
        <wp:wrapNone/>
        <wp:docPr id="{pic_id}" name="PageBackground_{pic_id}"/>
        <wp:cNvGraphicFramePr/>
        <a:graphic>
          <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
            <pic:pic>
              <pic:nvPicPr>
                <pic:cNvPr id="{pic_id}" name="PageBackground_{pic_id}.jpg"/>
                <pic:cNvPicPr/>
              </pic:nvPicPr>
              <pic:blipFill>
                <a:blip r:embed="{rel_id}"/>
                <a:stretch><a:fillRect/></a:stretch>
              </pic:blipFill>
              <pic:spPr>
                <a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>
                <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
              </pic:spPr>
            </pic:pic>
          </a:graphicData>
        </a:graphic>
      </wp:anchor>
    </w:drawing>
    """
    run = paragraph.add_run()
    run._r.append(parse_xml(drawing_xml))


def _add_positioned_textbox(
    paragraph,
    x_pt: float,
    y_pt: float,
    w_pt: float,
    h_pt: float,
    text: str,
    font_size_pt: float,
    color_hex: str,
    shape_id: int,
    bold: bool = False,
):
    """Inserta un cuadro de texto editable flotante posicionado en coordenadas exactas (pt)."""
    escaped = _xml_escape(text)
    half_pt = max(10, int(round(font_size_pt * 2)))
    bold_xml = "<w:b/>" if bold else ""
    # Margen holgado para que Word/WPS (Calibri más ancha que la fuente original) no parta la línea
    box_w = max(w_pt * 1.35 + 6.0, 18.0)
    box_h = max(h_pt * 1.5, 12.0)

    pict_xml = f"""
    <w:pict {nsdecls('w')} xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
      <v:shape id="TextBox_{shape_id}" type="#_x0000_t202"
               style="position:absolute;margin-left:{x_pt:.2f}pt;margin-top:{y_pt:.2f}pt;width:{box_w:.2f}pt;height:{box_h:.2f}pt;z-index:{shape_id + 10};mso-position-horizontal-relative:page;mso-position-vertical-relative:page;mso-wrap-style:none"
               filled="f" stroked="f">
        <v:textbox inset="0pt,0pt,0pt,0pt" style="mso-wrap-style:none">
          <w:txbxContent>
            <w:p>
              <w:pPr><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>
              <w:r>
                <w:rPr>
                  <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/>
                  {bold_xml}
                  <w:color w:val="{color_hex}"/>
                  <w:sz w:val="{half_pt}"/>
                  <w:szCs w:val="{half_pt}"/>
                </w:rPr>
                <w:t xml:space="preserve">{escaped}</w:t>
              </w:r>
            </w:p>
          </w:txbxContent>
        </v:textbox>
      </v:shape>
    </w:pict>
    """
    run = paragraph.add_run()
    run._r.append(parse_xml(pict_xml))


def build_docx(
    pages_with_boxes: List[Tuple[PageData, List[OCRBox]]],
    output_path: str,
    source_pdf_path: Optional[str] = None,
    use_native_pdf_converter: bool = False,
    original_boxes_per_page: Optional[List[List[OCRBox]]] = None,
    compression: str = "high",
    grayscale: bool = False,
    preserve_layout: bool = True,
) -> str:
    """
    Genera un archivo Microsoft Word (.docx) de alta fidelidad visual.
    Si el origen es un PDF con texto nativo y pdf2docx está disponible,
    utiliza pdf2docx para conservar tablas, columnas, fondos e imágenes originales.
    En caso contrario (imágenes, escaneos o documentos traducidos), recrea el documento:
    - preserve_layout=True: fondo limpio (inpainting) + cuadros de texto editables posicionados.
    - preserve_layout=False: documento fluido limpio de párrafos y encabezados estándar.
    """
    # 1. Ruta nativa para PDFs con texto buscable
    if use_native_pdf_converter and source_pdf_path and HAS_PDF2DOCX:
        try:
            cv = PDF2DocxConverter(source_pdf_path)
            try:
                cv.convert(output_path)
            finally:
                cv.close()
            return output_path
        except Exception:
            # Si pdf2docx falla con un PDF corrupto o atípico, continuar con el motor fiel
            pass

    from .pdf_builder import COMPRESSION_PRESETS
    preset = COMPRESSION_PRESETS.get(compression, COMPRESSION_PRESETS["high"])

    # 2. Ruta fiel visual o documento fluido
    doc = Document()
    shape_counter = 100

    for page_idx, (page_data, boxes) in enumerate(pages_with_boxes):
        if page_idx == 0:
            section = doc.sections[0]
        else:
            section = doc.add_section()

        section.page_width = Pt(page_data.width_pt)
        section.page_height = Pt(page_data.height_pt)

        if not preserve_layout:
            section.top_margin = Pt(54)
            section.bottom_margin = Pt(54)
            section.left_margin = Pt(54)
            section.right_margin = Pt(54)
            lines = _group_boxes_into_lines(boxes)
            heights = [b.height for b in boxes] if boxes else [15.0]
            median_h = sorted(heights)[len(heights) // 2]
            if lines:
                for line_boxes in lines:
                    line_txt = " ".join((b.text or "").strip() for b in line_boxes if (b.text or "").strip())
                    if not line_txt:
                        continue
                    max_h = max(b.height for b in line_boxes)
                    if max_h > median_h * 1.35:
                        doc.add_heading(line_txt, level=2)
                    else:
                        doc.add_paragraph(line_txt)
            elif page_data.embedded_text and page_data.embedded_text.strip():
                for para in page_data.embedded_text.split("\n"):
                    if para.strip():
                        doc.add_paragraph(para.strip())
            continue

        section.top_margin = Emu(0)
        section.bottom_margin = Emu(0)
        section.left_margin = Emu(0)
        section.right_margin = Emu(0)

        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)

        # Fondo visual limpio (usa las cajas originales si se traduce para borrar texto origen)
        erase_boxes = (
            original_boxes_per_page[page_idx]
            if (original_boxes_per_page and page_idx < len(original_boxes_per_page))
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
        _add_behind_page_image(
            p,
            doc,
            bg_buf.getvalue(),
            page_data.width_pt,
            page_data.height_pt,
            pic_id=page_idx + 1,
        )

        # Posicionar cada caja de texto editable con su color y tamaño real
        rgb_np = np.array(page_data.image.convert("RGB"))
        scale_x = page_data.width_pt / float(max(page_data.width_px, 1))
        scale_y = page_data.height_pt / float(max(page_data.height_px, 1))

        heights = [b.height for b in boxes] if boxes else [15.0]
        median_h = sorted(heights)[len(heights) // 2]

        for b in boxes:
            text = b.text.strip()
            if not text:
                continue
            x_pt = b.min_x * scale_x
            y_pt = b.min_y * scale_y
            w_pt = max(b.width * scale_x, 12.0)
            h_pt = max(b.height * scale_y, 8.0)
            font_pt = max(5.5, min(h_pt * 0.78, 72.0))
            # Ajustar el cuerpo al ancho real de la caja (Calibri ≈ 0.5 em por carácter)
            font_pt = max(5.5, min(font_pt, (w_pt * 1.05) / (max(len(text), 1) * 0.5)))
            color_hex = "111111" if grayscale else sample_text_color_hex(rgb_np, b)
            is_bold = b.height > median_h * 1.35

            shape_counter += 1
            _add_positioned_textbox(
                p,
                x_pt=x_pt,
                y_pt=y_pt,
                w_pt=w_pt,
                h_pt=h_pt,
                text=text,
                font_size_pt=font_pt,
                color_hex=color_hex,
                shape_id=shape_counter,
                bold=is_bold,
            )

    doc.save(output_path)
    return output_path


def _group_boxes_into_lines(boxes: List[OCRBox]) -> List[List[OCRBox]]:
    """Agrupa las cajas de texto en líneas horizontales según su proximidad vertical."""
    if not boxes:
        return []

    sorted_by_y = sorted(boxes, key=lambda b: b.center_y)
    lines: List[List[OCRBox]] = []

    for box in sorted_by_y:
        matched_line = None
        for line in lines:
            ref_box = line[0]
            v_threshold = max(ref_box.height, box.height) * 0.5
            if abs(box.center_y - ref_box.center_y) <= v_threshold:
                matched_line = line
                break

        if matched_line is not None:
            matched_line.append(box)
        else:
            lines.append([box])

    for line in lines:
        line.sort(key=lambda b: b.min_x)

    lines.sort(key=lambda line: sum(b.center_y for b in line) / len(line))
    return lines
