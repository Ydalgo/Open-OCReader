"""
Exportador a JSON estructurado con coordenadas, confianza y metadatos.
"""

import json
from typing import List, Tuple
from ..document_loader import PageData
from ..engine import OCRBox


def build_json(
    pages_with_boxes: List[Tuple[PageData, List[OCRBox]]],
    output_path: str,
) -> str:
    """
    Exporta la estructura completa de páginas y cajas de texto detectadas
    con coordenadas de polígonos y puntuación de confianza a formato JSON.
    """
    data = {
        "total_pages": len(pages_with_boxes),
        "pages": []
    }

    for page_data, boxes in pages_with_boxes:
        page_info = {
            "page_number": page_data.page_number,
            "width_px": page_data.width_px,
            "height_px": page_data.height_px,
            "width_pt": page_data.width_pt,
            "height_pt": page_data.height_pt,
            "elements_count": len(boxes),
            "elements": [
                {
                    "text": b.text,
                    "confidence": round(b.score, 4),
                    "bounding_box": {
                        "min_x": round(b.min_x, 2),
                        "max_x": round(b.max_x, 2),
                        "min_y": round(b.min_y, 2),
                        "max_y": round(b.max_y, 2),
                        "width": round(b.width, 2),
                        "height": round(b.height, 2),
                    },
                    "polygon": b.box,
                }
                for b in boxes
            ],
        }
        data["pages"].append(page_info)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return output_path
