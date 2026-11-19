"""
Módulo del motor OCR offline basado en RapidOCR (ONNX Runtime).
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple
import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR


@dataclass
class OCRBox:
    """Representa una región de texto reconocida por el motor OCR."""
    box: List[List[float]]  # [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
    text: str
    score: float

    @property
    def min_x(self) -> float:
        return min(p[0] for p in self.box)

    @property
    def max_x(self) -> float:
        return max(p[0] for p in self.box)

    @property
    def min_y(self) -> float:
        return min(p[1] for p in self.box)

    @property
    def max_y(self) -> float:
        return max(p[1] for p in self.box)

    @property
    def width(self) -> float:
        return max(self.max_x - self.min_x, 1.0)

    @property
    def height(self) -> float:
        return max(self.max_y - self.min_y, 1.0)

    @property
    def center_x(self) -> float:
        return (self.min_x + self.max_x) / 2.0

    @property
    def center_y(self) -> float:
        return (self.min_y + self.max_y) / 2.0


class OCREngine:
    """
    Envoltorio del motor RapidOCR para ejecución local y ágil en CPU.
    """

    _instance: Optional["OCREngine"] = None

    def __init__(self):
        # Inicializa RapidOCR con parámetros optimizados
        self.engine = RapidOCR()

    @classmethod
    def get_instance(cls) -> "OCREngine":
        """Patrón Singleton para evitar recargar pesos del modelo en memoria."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def process_image(self, image: Image.Image) -> List[OCRBox]:
        """
        Procesa una imagen PIL y devuelve la lista de bloques de texto detectados.
        """
        # Convertir imagen PIL a RGB y a matriz numpy
        if image.mode != "RGB":
            img_rgb = image.convert("RGB")
        else:
            img_rgb = image

        img_np = np.array(img_rgb)

        results, _elapse = self.engine(img_np)
        boxes: List[OCRBox] = []

        if not results:
            return boxes

        for item in results:
            # item = [box, text, score]
            box_coords = item[0]
            text = str(item[1]).strip()
            score = float(item[2])

            if text:
                boxes.append(OCRBox(box=box_coords, text=text, score=score))

        return boxes
