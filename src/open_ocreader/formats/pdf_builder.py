"""
Constructor de PDF tipo 'Sandwich' (Buscable y con fidelidad visual 100%).
"""

from typing import List, Tuple
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from ..document_loader import PageData
from ..engine import OCRBox


def build_sandwich_pdf(
    pages_with_boxes: List[Tuple[PageData, List[OCRBox]]],
    output_path: str,
) -> str:
    """
    Crea un PDF donde cada página contiene:
      1. La imagen original del escaneo en alta resolución como fondo (fidelidad visual 100%).
      2. Una capa invisible de texto con render mode 3 alineada exactamente en las coordenadas (x, y, w, h).
    
    :param pages_with_boxes: Lista de tuplas (PageData, lista de OCRBox).
    :param output_path: Ruta del fichero PDF resultante.
    :return: Ruta del fichero generado.
    """
    if not pages_with_boxes:
        raise ValueError("No hay páginas para generar el PDF.")

    first_page, _ = pages_with_boxes[0]
    c = canvas.Canvas(output_path, pagesize=(first_page.width_pt, first_page.height_pt))

    for page_data, boxes in pages_with_boxes:
        # Ajustar dimensiones de la página actual
        c.setPageSize((page_data.width_pt, page_data.height_pt))

        # 1. Dibujar la imagen escaneada original cubriendo toda la página
        img_reader = ImageReader(page_data.image)
        c.drawImage(
            img_reader,
            0,
            0,
            width=page_data.width_pt,
            height=page_data.height_pt,
            preserveAspectRatio=False,
        )

        # 2. Factores de escala entre píxeles de la imagen y puntos del PDF
        scale_x = page_data.width_pt / float(page_data.width_px)
        scale_y = page_data.height_pt / float(page_data.height_px)

        # 3. Superponer la capa de texto invisible
        for item in boxes:
            text = item.text.strip()
            if not text:
                continue

            # Coordenadas en píxeles
            min_x = item.min_x
            max_x = item.max_x
            min_y = item.min_y
            max_y = item.max_y

            # Conversión a puntos PDF (el origen Y en PDF está abajo, no arriba)
            box_w_pt = max((max_x - min_x) * scale_x, 1.0)
            box_h_pt = max((max_y - min_y) * scale_y, 1.0)

            pdf_x = min_x * scale_x
            pdf_y = page_data.height_pt - (max_y * scale_y)

            # Ajuste de tamaño de fuente y escala horizontal
            font_size = max(box_h_pt * 0.85, 4.0)
            font_name = "Helvetica"

            # Calcular ancho natural del texto con la fuente seleccionada
            natural_w = c.stringWidth(text, font_name, font_size)
            if natural_w > 0:
                horiz_scale = (box_w_pt / natural_w) * 100.0
                # Limitar escala horizontal entre 30% y 300% para evitar distorsiones extremas
                horiz_scale = max(30.0, min(horiz_scale, 300.0))
            else:
                horiz_scale = 100.0

            # Renderizado en Modo 3: Texto invisible (ni trazo ni relleno)
            # Los visores de PDF (Acrobat, Chrome, Edge) lo indexan y permiten seleccionar y copiar
            text_obj = c.beginText()
            text_obj.setTextRenderMode(3)
            text_obj.setFont(font_name, font_size)
            text_obj.setHorizScale(horiz_scale)
            # Pequeño desplazamiento hacia arriba para compensar la línea base del texto
            text_obj.setTextOrigin(pdf_x, pdf_y + (box_h_pt * 0.12))
            text_obj.textLine(text)

            c.drawText(text_obj)

        c.showPage()

    c.save()
    return output_path
