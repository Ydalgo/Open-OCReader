"""
Constructor de ficheros CSV (.csv) en UTF-8 con BOM (compatible con Excel y LibreOffice).
Agrupa las cajas detectadas en filas y columnas según coordenadas espaciales.
"""

import csv
from typing import Dict, List, Tuple
from ..document_loader import PageData
from ..engine import OCRBox
from ..security import sanitize_spreadsheet_text
from .excel_builder import _detect_column_centers, _find_best_column, _group_into_rows


def build_csv(
    pages_with_boxes: List[Tuple[PageData, List[OCRBox]]],
    output_path: str,
    delimiter: str = ";",
) -> str:
    """Exporta las tablas/datos del documento a un archivo CSV limpio."""
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=delimiter)

        for page_idx, (_page_data, boxes) in enumerate(pages_with_boxes, start=1):
            if not boxes:
                continue
            if len(pages_with_boxes) > 1 and page_idx > 1:
                writer.writerow([])
                writer.writerow([f"--- Página {page_idx} ---"])

            rows = _group_into_rows(boxes)
            col_centers = _detect_column_centers(boxes)
            num_cols = max(len(col_centers), 1)

            for row_boxes in rows:
                cells: Dict[int, str] = {}
                for box in row_boxes:
                    c_idx = _find_best_column(box.min_x, col_centers)
                    txt = box.text.strip()
                    if c_idx in cells:
                        cells[c_idx] = sanitize_spreadsheet_text(f"{cells[c_idx]} {txt}")
                    else:
                        cells[c_idx] = sanitize_spreadsheet_text(txt)

                writer.writerow([cells.get(c, "") for c in range(1, num_cols + 1)])

    return output_path
