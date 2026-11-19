"""
Constructor de hojas de cálculo de Excel (.xlsx) mapeando celdas por coordenadas.
"""

from typing import List, Tuple
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from ..document_loader import PageData
from ..engine import OCRBox
from ..security import sanitize_spreadsheet_text


def build_excel(
    pages_with_boxes: List[Tuple[PageData, List[OCRBox]]],
    output_path: str,
) -> str:
    """
    Exporta el contenido detectado a un libro Excel (.xlsx),
    asignando las cajas de texto a filas y columnas basadas en sus coordenadas espaciales.
    """
    wb = openpyxl.Workbook()
    # Eliminar hoja por defecto vacía
    if wb.active:
        wb.remove(wb.active)

    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")

    for page_idx, (page_data, boxes) in enumerate(pages_with_boxes):
        sheet_name = f"Página {page_idx + 1}"
        ws = wb.create_sheet(title=sheet_name)

        if not boxes:
            continue

        # 1. Agrupar en filas por cercanía vertical
        rows = _group_into_rows(boxes)

        # 2. Identificar columnas globales de la página
        col_centers = _detect_column_centers(boxes)

        # 3. Rellenar celdas en la hoja
        for r_idx, row_boxes in enumerate(rows, start=1):
            for box in row_boxes:
                # Encontrar la columna más cercana a la posición X del texto
                c_idx = _find_best_column(box.min_x, col_centers)
                cell = ws.cell(row=r_idx, column=c_idx)

                # Si ya hay texto en la celda (colisión), concatenar
                current_val = cell.value
                box_text = box.text.strip()
                parsed_val = _try_parse_number(box_text)

                if current_val is not None:
                    cell.value = sanitize_spreadsheet_text(f"{current_val} {parsed_val}")
                else:
                    cell.value = sanitize_spreadsheet_text(parsed_val) if isinstance(parsed_val, str) else parsed_val

                # Formatear la primera fila como cabecera si tiene aspecto de tabla
                if r_idx == 1:
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = Alignment(horizontal="center", vertical="center")

        # 4. Ajustar ancho de columnas automáticamente
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    wb.save(output_path)
    return output_path


def _group_into_rows(boxes: List[OCRBox]) -> List[List[OCRBox]]:
    """Agrupa las cajas en filas según su coordenada vertical Y."""
    if not boxes:
        return []

    sorted_boxes = sorted(boxes, key=lambda b: b.center_y)
    rows: List[List[OCRBox]] = []

    for box in sorted_boxes:
        matched_row = None
        for row in rows:
            ref = row[0]
            v_tol = max(ref.height, box.height) * 0.6
            if abs(box.center_y - ref.center_y) <= v_tol:
                matched_row = row
                break

        if matched_row is not None:
            matched_row.append(box)
        else:
            rows.append([box])

    # Ordenar elementos dentro de cada fila de izquierda a derecha
    for row in rows:
        row.sort(key=lambda b: b.min_x)

    rows.sort(key=lambda row: sum(b.center_y for b in row) / len(row))
    return rows


def _detect_column_centers(boxes: List[OCRBox]) -> List[float]:
    """Detecta los centros de columna agrupando las posiciones X de todas las cajas."""
    if not boxes:
        return [0.0]

    xs = sorted([b.min_x for b in boxes])
    col_clusters: List[List[float]] = []

    # Umbral de tolerancia horizontal para considerar la misma columna (~40 píxeles)
    h_tol = 45.0

    for x in xs:
        matched = False
        for cluster in col_clusters:
            avg_x = sum(cluster) / len(cluster)
            if abs(x - avg_x) <= h_tol:
                cluster.append(x)
                matched = True
                break
        if not matched:
            col_clusters.append([x])

    centers = sorted([sum(cluster) / len(cluster) for cluster in col_clusters])
    return centers if centers else [0.0]


def _find_best_column(x: float, col_centers: List[float]) -> int:
    """Devuelve el índice de columna (1-based) más cercano a la posición horizontal X."""
    best_idx = 1
    best_dist = float("inf")

    for idx, c_x in enumerate(col_centers, start=1):
        dist = abs(x - c_x)
        if dist < best_dist:
            best_dist = dist
            best_idx = idx

    return best_idx


def _try_parse_number(text: str):
    """Intenta convertir texto con formato numérico a float o int para Excel."""
    clean = text.strip()
    # Limpiar formato monetario o separadores comunes en España (ej. 1.250,50 o 1250.50)
    if clean.endswith("€") or clean.startswith("€") or clean.startswith("$"):
        clean = clean.replace("€", "").replace("$", "").strip()

    # Probar entero
    try:
        return int(clean)
    except ValueError:
        pass

    # Probar coma decimal española (ej. 12,50)
    if "," in clean and clean.count(",") == 1 and "." not in clean:
        try:
            return float(clean.replace(",", "."))
        except ValueError:
            pass

    # Probar punto decimal estándar (ej. 12.50)
    if "." in clean and clean.count(".") == 1 and "," not in clean:
        try:
            return float(clean)
        except ValueError:
            pass

    return text
