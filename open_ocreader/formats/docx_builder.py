"""
Constructor de documentos Word (.docx) respetando la estructura de lectura.
"""

from typing import List, Tuple
from docx import Document
from docx.shared import Pt, Inches
from ..document_loader import PageData
from ..engine import OCRBox


def build_docx(
    pages_with_boxes: List[Tuple[PageData, List[OCRBox]]],
    output_path: str,
) -> str:
    """
    Genera un archivo Microsoft Word (.docx) reconstruyendo párrafos y líneas
    en orden de lectura natural a partir de las coordenadas del OCR.
    """
    doc = Document()

    # Configurar márgenes estándar (1 pulgada)
    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)

    total_pages = len(pages_with_boxes)

    for page_idx, (page_data, boxes) in enumerate(pages_with_boxes):
        if not boxes:
            continue

        # 1. Agrupar cajas en líneas horizontales
        lines = _group_boxes_into_lines(boxes)

        # 2. Calcular altura mediana para detectar posibles títulos
        heights = [b.height for b in boxes]
        median_h = sorted(heights)[len(heights) // 2] if heights else 15.0

        for line_boxes in lines:
            line_text = " ".join(b.text.strip() for b in line_boxes if b.text.strip())
            if not line_text:
                continue

            max_box_h = max(b.height for b in line_boxes)

            p = doc.add_paragraph()
            run = p.add_run(line_text)

            # Si la altura es un 40% mayor que la mediana, formatear como título o negrita
            if max_box_h > median_h * 1.4:
                run.bold = True
                run.font.size = Pt(14)
            else:
                run.font.size = Pt(11)

        # Añadir salto de página si hay más páginas
        if page_idx < total_pages - 1:
            doc.add_page_break()

    doc.save(output_path)
    return output_path


def _group_boxes_into_lines(boxes: List[OCRBox]) -> List[List[OCRBox]]:
    """Agrupa las cajas de texto en líneas horizontales según su proximidad vertical."""
    if not boxes:
        return []

    # Ordenar inicialmente por posición vertical (Y)
    sorted_by_y = sorted(boxes, key=lambda b: b.center_y)
    lines: List[List[OCRBox]] = []

    for box in sorted_by_y:
        matched_line = None
        for line in lines:
            # Si el centro vertical coincide con la línea existente dentro de un umbral
            ref_box = line[0]
            v_threshold = max(ref_box.height, box.height) * 0.5
            if abs(box.center_y - ref_box.center_y) <= v_threshold:
                matched_line = line
                break

        if matched_line is not None:
            matched_line.append(box)
        else:
            lines.append([box])

    # Ordenar cada línea de izquierda a derecha (X)
    for line in lines:
        line.sort(key=lambda b: b.min_x)

    # Ordenar las líneas completas de arriba hacia abajo
    lines.sort(key=lambda line: sum(b.center_y for b in line) / len(line))
    return lines
