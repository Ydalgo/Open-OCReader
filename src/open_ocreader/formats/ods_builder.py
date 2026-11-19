"""
Constructor de hojas de cálculo OpenDocument Spreadsheet (.ods) estándar ODF 1.2.
Mapea las cajas de texto en filas y columnas según coordenadas espaciales.
"""

import zipfile
from typing import Dict, List, Tuple
from xml.sax.saxutils import escape as xml_escape
from ..document_loader import PageData
from ..engine import OCRBox
from ..security import sanitize_spreadsheet_text
from .excel_builder import _detect_column_centers, _find_best_column, _group_into_rows, _try_parse_number


def build_ods(
    pages_with_boxes: List[Tuple[PageData, List[OCRBox]]],
    output_path: str,
) -> str:
    """Exporta las páginas detectadas a un libro OpenDocument (.ods)."""
    tables_xml: List[str] = []

    for page_idx, (_page_data, boxes) in enumerate(pages_with_boxes, start=1):
        sheet_name = xml_escape(f"Página {page_idx}")
        rows = _group_into_rows(boxes)
        col_centers = _detect_column_centers(boxes)
        num_cols = max(len(col_centers), 1)

        row_xml_parts: List[str] = []
        for r_idx, row_boxes in enumerate(rows, start=1):
            cells: Dict[int, object] = {}
            for box in row_boxes:
                c_idx = _find_best_column(box.min_x, col_centers)
                parsed = _try_parse_number(box.text.strip())
                if c_idx in cells:
                    cells[c_idx] = sanitize_spreadsheet_text(f"{cells[c_idx]} {parsed}")
                else:
                    cells[c_idx] = sanitize_spreadsheet_text(parsed) if isinstance(parsed, str) else parsed

            cell_parts: List[str] = []
            for c_idx in range(1, num_cols + 1):
                val = cells.get(c_idx)
                if val is None or val == "":
                    cell_parts.append("<table:table-cell/>")
                elif isinstance(val, (int, float)):
                    cell_parts.append(
                        f'<table:table-cell office:value-type="float" office:value="{val}">'
                        f'<text:p>{val}</text:p></table:table-cell>'
                    )
                else:
                    txt = xml_escape(str(val))
                    cell_parts.append(
                        f'<table:table-cell office:value-type="string">'
                        f'<text:p>{txt}</text:p></table:table-cell>'
                    )

            row_xml_parts.append(f'<table:table-row>{"".join(cell_parts)}</table:table-row>')

        if not row_xml_parts:
            row_xml_parts.append("<table:table-row><table:table-cell/></table:table-row>")

        tables_xml.append(
            f'<table:table table:name="{sheet_name}">'
            f'<table:table-column table:number-columns-repeated="{num_cols}"/>'
            f'{"".join(row_xml_parts)}'
            f'</table:table>'
        )

    content_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
    xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    office:version="1.2">
  <office:body>
    <office:spreadsheet>
      {"".join(tables_xml)}
    </office:spreadsheet>
  </office:body>
</office:document-content>
"""

    manifest_xml = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">
  <manifest:file-entry manifest:full-path="/" manifest:version="1.2" manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/>
  <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
</manifest:manifest>
"""

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet", compress_type=zipfile.ZIP_STORED)
        zf.writestr("content.xml", content_xml.encode("utf-8"))
        zf.writestr("META-INF/manifest.xml", manifest_xml.encode("utf-8"))

    return output_path
