"""
Exportador a texto plano (.txt) en orden de lectura natural.
"""

from typing import List, Tuple
from ..document_loader import PageData
from ..engine import OCRBox
from .docx_builder import _group_boxes_into_lines


def build_txt(
    pages_with_boxes: List[Tuple[PageData, List[OCRBox]]],
    output_path: str,
) -> str:
    """
    Vuelca el texto reconocido en un fichero de texto plano UTF-8,
    respetando el flujo de lectura natural de arriba abajo e izquierda a derecha.
    """
    output_lines: List[str] = []

    for page_idx, (page_data, boxes) in enumerate(pages_with_boxes):
        if len(pages_with_boxes) > 1:
            output_lines.append(f"--- Página {page_idx + 1} ---")

        lines = _group_boxes_into_lines(boxes)
        for line in lines:
            line_str = " ".join(b.text.strip() for b in line if b.text.strip())
            if line_str:
                output_lines.append(line_str)

        output_lines.append("")  # Línea en blanco entre páginas

    content = "\n".join(output_lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    return output_path
