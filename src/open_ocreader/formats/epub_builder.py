"""
Constructor de libros electrónicos EPUB 3 (.epub) estándar sin dependencias externas pesadas.
Compatible con Kindle (Send-to-Kindle), Kobo, Calibre, Apple Books y lectores móviles.
"""

import html
import io
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple
from ..document_loader import PageData
from ..engine import OCRBox
from .docx_builder import _group_boxes_into_lines


def build_epub(
    pages_with_boxes: List[Tuple[PageData, List[OCRBox]]],
    output_path: str,
    title: str = "",
    include_page_images: bool = False,
) -> str:
    """
    Genera un eBook EPUB 3 válido con texto reflujo (reflowable) estructurado por páginas,
    índice navegable (nav.xhtml) y estilos tipográficos limpios para lectura cómoda.
    """
    if not pages_with_boxes:
        raise ValueError("No hay páginas para generar el eBook EPUB.")

    book_title = title or Path(output_path).stem.replace("_ocr", "").replace("_", " ").strip() or "Documento Open OCReader"
    book_id = f"urn:uuid:{uuid.uuid4()}"
    modified_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    css = """body { font-family: Georgia, serif; line-height: 1.55; margin: 1.2em; color: #1a1a1a; }
h1, h2 { font-family: sans-serif; color: #1f4e79; margin-top: 1.2em; }
p { margin: 0.55em 0; text-align: justify; }
.page-img { max-width: 100%; height: auto; display: block; margin: 0.8em auto; border: 1px solid #ddd; }
"""

    chapter_files: List[Tuple[str, str, str]] = []  # (id, filename, label)
    chapter_contents: List[Tuple[str, bytes]] = []
    extra_images: List[Tuple[str, bytes]] = []

    for idx, (page_data, boxes) in enumerate(pages_with_boxes, start=1):
        chap_id = f"page_{idx}"
        chap_file = f"text/page_{idx:04d}.xhtml"
        chap_label = f"Página {idx}"
        chapter_files.append((chap_id, chap_file, chap_label))

        body_parts: List[str] = [f"<h2>{html.escape(chap_label)}</h2>"]

        if include_page_images:
            img_buf = io.BytesIO()
            img_copy = page_data.image.convert("RGB")
            img_copy.thumbnail((1200, 1200))
            img_copy.save(img_buf, format="JPEG", quality=80, optimize=True)
            img_rel = f"images/page_{idx:04d}.jpg"
            extra_images.append((img_rel, img_buf.getvalue()))
            body_parts.append(f'<img class="page-img" src="../{img_rel}" alt="{html.escape(chap_label)}"/>')

        if page_data.has_embedded_text and page_data.embedded_text.strip():
            for para in page_data.embedded_text.split("\n\n"):
                cleaned = " ".join(line.strip() for line in para.splitlines() if line.strip())
                if cleaned:
                    body_parts.append(f"<p>{html.escape(cleaned)}</p>")
        else:
            lines = _group_boxes_into_lines(boxes)
            heights = [b.height for b in boxes] if boxes else [15.0]
            median_h = sorted(heights)[len(heights) // 2]
            for line_boxes in lines:
                line_text = " ".join(b.text.strip() for b in line_boxes if b.text.strip())
                if not line_text:
                    continue
                max_h = max(b.height for b in line_boxes)
                if max_h > median_h * 1.4:
                    body_parts.append(f"<h2>{html.escape(line_text)}</h2>")
                else:
                    body_parts.append(f"<p>{html.escape(line_text)}</p>")

        xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="es" lang="es">
<head>
  <meta charset="utf-8"/>
  <title>{html.escape(book_title)} - {html.escape(chap_label)}</title>
  <link rel="stylesheet" type="text/css" href="../styles/style.css"/>
</head>
<body>
  {"".join(body_parts)}
</body>
</html>
"""
        chapter_contents.append((f"OEBPS/{chap_file}", xhtml.encode("utf-8")))

    # Navegación EPUB 3 (nav.xhtml)
    nav_items = "\n".join(
        f'      <li><a href="{fname}">{html.escape(lbl)}</a></li>'
        for _cid, fname, lbl in chapter_files
    )
    nav_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="es" lang="es">
<head>
  <meta charset="utf-8"/>
  <title>Índice</title>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>Índice</h1>
    <ol>
{nav_items}
    </ol>
  </nav>
</body>
</html>
"""

    manifest_items = [
        '    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '    <item id="css" href="styles/style.css" media-type="text/css"/>',
    ]
    spine_items = []
    for cid, fname, _lbl in chapter_files:
        manifest_items.append(f'    <item id="{cid}" href="{fname}" media-type="application/xhtml+xml"/>')
        spine_items.append(f'    <itemref idref="{cid}"/>')
    for idx, (img_rel, _b) in enumerate(extra_images, start=1):
        manifest_items.append(f'    <item id="img_{idx}" href="{img_rel}" media-type="image/jpeg"/>')

    content_opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{book_id}</dc:identifier>
    <dc:title>{html.escape(book_title)}</dc:title>
    <dc:language>es</dc:language>
    <dc:creator>Open OCReader</dc:creator>
    <meta property="dcterms:modified">{modified_iso}</meta>
  </metadata>
  <manifest>
{chr(10).join(manifest_items)}
  </manifest>
  <spine>
{chr(10).join(spine_items)}
  </spine>
</package>
"""

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container_xml.encode("utf-8"))
        zf.writestr("OEBPS/content.opf", content_opf.encode("utf-8"))
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml.encode("utf-8"))
        zf.writestr("OEBPS/styles/style.css", css.encode("utf-8"))
        for path_in_zip, data in chapter_contents:
            zf.writestr(path_in_zip, data)
        for img_rel, data in extra_images:
            zf.writestr(f"OEBPS/{img_rel}", data, compress_type=zipfile.ZIP_STORED)

    return output_path
