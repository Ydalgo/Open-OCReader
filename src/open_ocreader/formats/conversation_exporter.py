"""
Exportador multi-formato de conversaciones y consultas de IA con sus
referencias literales extraídas directamente de los documentos originales.
Soporta: Word (.docx), PDF (.pdf), PDF/A-2b (.pdf), LibreOffice (.odt),
eBook (.epub), Markdown (.md), Texto (.txt) y JSON (.json).
"""

import html
import json
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
from xml.sax.saxutils import escape as xml_escape

import pymupdf as fitz
from docx import Document
from docx.shared import Pt, RGBColor

from .pdf_builder import _apply_pdfa_metadata_and_profile

SUPPORTED_CONVERSATION_EXPORT_FORMATS = ("docx", "pdf", "pdfa", "odt", "epub", "md", "txt", "json")


def export_conversation_with_references(
    turns: List[Any],
    output_path: str,
    output_format: str = "docx",
    title: str = "Informe de Consultas y Referencias Literales — Open OCReader",
    documents_summary: Optional[List[str]] = None,
) -> str:
    """
    Exporta una lista de ChatTurnRecord al formato elegido incluyendo, para cada consulta,
    la pregunta, la respuesta razonada y los extractos literales completos de los documentos fuente.
    """
    fmt = output_format.lower().lstrip(".")
    if fmt not in SUPPORTED_CONVERSATION_EXPORT_FORMATS:
        raise ValueError(
            f"Formato '{output_format}' no soportado para exportar conversaciones. "
            f"Válidos: {', '.join(SUPPORTED_CONVERSATION_EXPORT_FORMATS)}"
        )

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    docs_list = list(documents_summary or [])

    if fmt == "json":
        payload = {
            "title": title,
            "generated_at": generated_at,
            "documents": docs_list,
            "turns": [
                {
                    "index": idx,
                    "timestamp": getattr(t, "timestamp", ""),
                    "question": getattr(t, "question", ""),
                    "answer": getattr(t, "answer", ""),
                    "references": [
                        {
                            "doc_id": r.doc_id,
                            "ref_id": r.ref_id,
                            "file_name": r.file_name,
                            "section_path": r.section_path,
                            "score": round(float(r.score), 6),
                            "literal_text": r.literal_text or r.excerpt,
                        }
                        for r in (getattr(t, "references", None) or [])
                    ],
                }
                for idx, t in enumerate(turns, start=1)
            ],
        }
        out_p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return str(out_p)

    if fmt in ("md", "txt"):
        text_out = _render_markdown_or_text(turns, title, generated_at, docs_list, is_markdown=(fmt == "md"))
        out_p.write_text(text_out, encoding="utf-8")
        return str(out_p)

    if fmt == "docx":
        return _write_conversation_docx(turns, str(out_p), title, generated_at, docs_list)

    if fmt in ("pdf", "pdfa"):
        _write_conversation_pdf(turns, str(out_p), title, generated_at, docs_list)
        if fmt == "pdfa":
            _apply_pdfa_metadata_and_profile(str(out_p), grayscale=False)
        return str(out_p)

    if fmt == "odt":
        return _write_conversation_odt(turns, str(out_p), title, generated_at, docs_list)

    if fmt == "epub":
        return _write_conversation_epub(turns, str(out_p), title, generated_at, docs_list)

    raise ValueError(f"Formato no manejado: {fmt}")


def _render_markdown_or_text(
    turns: List[Any],
    title: str,
    generated_at: str,
    docs_list: List[str],
    is_markdown: bool,
) -> str:
    lines: List[str] = []
    if is_markdown:
        lines.append(f"# {title}")
        lines.append(f"\n*Generado el `{generated_at}` con Open OCReader (100% Local)*\n")
        if docs_list:
            lines.append("## Documentos fuente analizados")
            for d in docs_list:
                lines.append(f"- {d}")
            lines.append("")
    else:
        lines.append(title.upper())
        lines.append("=" * len(title))
        lines.append(f"Fecha: {generated_at}")
        if docs_list:
            lines.append("\nDocumentos fuente analizados:")
            for d in docs_list:
                lines.append(f"  * {d}")
        lines.append("")

    for idx, t in enumerate(turns, start=1):
        ts = getattr(t, "timestamp", "")
        ts_lbl = f" ({ts})" if ts else ""
        q = getattr(t, "question", "")
        a = getattr(t, "answer", "")
        refs = getattr(t, "references", None) or []

        if is_markdown:
            lines.append(f"---\n\n## Consulta #{idx}{ts_lbl}")
            lines.append(f"**Pregunta:** {q}\n")
            lines.append(f"**Respuesta:**\n\n{a}\n")
            if refs:
                lines.append("### Referencias Literales Extraídas de los Documentos Originales\n")
                for r in refs:
                    lit = (r.literal_text or r.excerpt or "").strip()
                    lines.append(f"#### [{r.doc_id} / {r.ref_id}] {r.file_name} — `{r.section_path}`")
                    quoted = "\n".join(f"> {ln}" if ln.strip() else ">" for ln in lit.splitlines())
                    lines.append(f"{quoted}\n")
        else:
            lines.append("-" * 68)
            lines.append(f"CONSULTA #{idx}{ts_lbl}")
            lines.append(f"Pregunta: {q}\n")
            lines.append(f"Respuesta:\n{a}\n")
            if refs:
                lines.append("Referencias Literales Extraídas de los Documentos Originales:")
                for r in refs:
                    lit = (r.literal_text or r.excerpt or "").strip()
                    lines.append(f"  [{r.doc_id} / {r.ref_id}] {r.file_name} — {r.section_path}")
                    for ln in lit.splitlines():
                        lines.append(f"      | {ln}")
                    lines.append("")

    return "\n".join(lines).strip() + "\n"


def _write_conversation_docx(
    turns: List[Any],
    output_path: str,
    title: str,
    generated_at: str,
    docs_list: List[str],
) -> str:
    doc = Document()
    doc.add_heading(title, level=0)
    meta_p = doc.add_paragraph()
    r_meta = meta_p.add_run(f"Generado el {generated_at} mediante Open OCReader (100% Local)")
    r_meta.italic = True
    r_meta.font.size = Pt(9)

    if docs_list:
        doc.add_heading("Documentos fuente analizados", level=1)
        for d in docs_list:
            doc.add_paragraph(d, style="List Bullet")

    for idx, t in enumerate(turns, start=1):
        ts = getattr(t, "timestamp", "")
        ts_lbl = f" ({ts})" if ts else ""
        doc.add_heading(f"Consulta #{idx}{ts_lbl}", level=1)

        pq = doc.add_paragraph()
        rq_lbl = pq.add_run("Pregunta: ")
        rq_lbl.bold = True
        rq_lbl.font.color.rgb = RGBColor(0x1F, 0x4E, 0x79)
        pq.add_run(getattr(t, "question", ""))

        pa_lbl = doc.add_paragraph()
        ra_lbl = pa_lbl.add_run("Respuesta razonada:")
        ra_lbl.bold = True
        ra_lbl.font.color.rgb = RGBColor(0x1E, 0x6B, 0x1E)
        doc.add_paragraph(getattr(t, "answer", ""))

        refs = getattr(t, "references", None) or []
        if refs:
            doc.add_heading("Referencias literales extraídas de los documentos originales", level=2)
            for r in refs:
                pr_hdr = doc.add_paragraph()
                pr_hdr.paragraph_format.space_before = Pt(6)
                pr_hdr.paragraph_format.space_after = Pt(2)
                rr = pr_hdr.add_run(f"[{r.doc_id} / {r.ref_id}] {r.file_name} — {r.section_path}")
                rr.bold = True
                rr.font.size = Pt(9.5)
                rr.font.color.rgb = RGBColor(0x7A, 0x4F, 0x00)

                lit = (r.literal_text or r.excerpt or "").strip()
                p_lit = doc.add_paragraph()
                p_lit.paragraph_format.left_indent = Pt(18)
                p_lit.paragraph_format.space_before = Pt(0)
                p_lit.paragraph_format.space_after = Pt(6)
                r_lit = p_lit.add_run(lit)
                r_lit.font.size = Pt(9)

    doc.save(output_path)
    return output_path


def _write_conversation_pdf(
    turns: List[Any],
    output_path: str,
    title: str,
    generated_at: str,
    docs_list: List[str],
) -> str:
    html_parts: List[str] = [
        """
        <style>
          body { font-family: sans-serif; font-size: 10.5pt; color: #1a1a1a; line-height: 1.4; }
          h1 { color: #1f4e79; font-size: 16pt; margin-bottom: 4pt; }
          h2 { color: #1f4e79; font-size: 13pt; border-bottom: 1px solid #d0d7de; padding-bottom: 3pt; margin-top: 14pt; }
          h3 { color: #7a4f00; font-size: 11pt; margin-top: 10pt; margin-bottom: 4pt; }
          .meta { color: #555555; font-size: 9pt; font-style: italic; margin-bottom: 10pt; }
          .q-box { background-color: #eef5fc; border-left: 3px solid #1f4e79; padding: 6pt 10pt; margin: 6pt 0; }
          .a-box { margin: 6pt 0 10pt 0; }
          .ref-hdr { font-weight: bold; color: #5c3c00; font-size: 9.5pt; margin-top: 6pt; }
          .ref-lit { background-color: #faf7f0; border-left: 3px solid #c9973b; padding: 5pt 9pt; font-size: 9pt; color: #2b2b2b; margin-bottom: 6pt; white-space: pre-wrap; }
        </style>
        """,
        f"<h1>{html.escape(title)}</h1>",
        f'<div class="meta">Generado el {html.escape(generated_at)} mediante Open OCReader (100% Local)</div>',
    ]

    if docs_list:
        html_parts.append("<h2>Documentos fuente analizados</h2><ul>")
        for d in docs_list:
            html_parts.append(f"<li>{html.escape(d)}</li>")
        html_parts.append("</ul>")

    for idx, t in enumerate(turns, start=1):
        ts = getattr(t, "timestamp", "")
        ts_lbl = f" ({ts})" if ts else ""
        html_parts.append(f"<h2>Consulta #{idx}{html.escape(ts_lbl)}</h2>")
        html_parts.append(
            f'<div class="q-box"><b>Pregunta:</b> {html.escape(getattr(t, "question", ""))}</div>'
        )
        ans_html = html.escape(getattr(t, "answer", "")).replace("\n", "<br/>")
        html_parts.append(f'<div class="a-box"><b>Respuesta razonada:</b><br/>{ans_html}</div>')

        refs = getattr(t, "references", None) or []
        if refs:
            html_parts.append("<h3>Referencias literales extraídas de los documentos originales</h3>")
            for r in refs:
                lit = html.escape((r.literal_text or r.excerpt or "").strip()).replace("\n", "<br/>")
                html_parts.append(
                    f'<div class="ref-hdr">[{html.escape(r.doc_id)} / {html.escape(r.ref_id)}] '
                    f'{html.escape(r.file_name)} — {html.escape(r.section_path)}</div>'
                )
                html_parts.append(f'<div class="ref-lit">{lit}</div>')

    story = fitz.Story("".join(html_parts))
    writer = fitz.DocumentWriter(output_path)
    try:
        mediabox = fitz.paper_rect("a4")
        where = mediabox + (42, 42, -42, -42)
        more = 1
        while more:
            dev = writer.begin_page(mediabox)
            more, _ = story.place(where)
            story.draw(dev, fitz.Matrix(1, 1))
            writer.end_page()
    finally:
        writer.close()

    return output_path


def _write_conversation_odt(
    turns: List[Any],
    output_path: str,
    title: str,
    generated_at: str,
    docs_list: List[str],
) -> str:
    body: List[str] = [
        f'<text:p text:style-name="Title">{xml_escape(title)}</text:p>',
        f'<text:p text:style-name="Meta">{xml_escape(f"Generado el {generated_at} mediante Open OCReader")}</text:p>',
    ]
    if docs_list:
        body.append('<text:p text:style-name="H1">Documentos fuente analizados</text:p>')
        for d in docs_list:
            body.append(f'<text:p text:style-name="Normal">• {xml_escape(d)}</text:p>')

    for idx, t in enumerate(turns, start=1):
        ts = getattr(t, "timestamp", "")
        ts_lbl = f" ({ts})" if ts else ""
        body.append(f'<text:p text:style-name="H1">{xml_escape(f"Consulta #{idx}{ts_lbl}")}</text:p>')
        body.append(f'<text:p text:style-name="Question">Pregunta: {xml_escape(getattr(t, "question", ""))}</text:p>')
        body.append('<text:p text:style-name="AnswerLabel">Respuesta razonada:</text:p>')
        for line in (getattr(t, "answer", "") or "").splitlines():
            body.append(f'<text:p text:style-name="Normal">{xml_escape(line)}</text:p>')

        refs = getattr(t, "references", None) or []
        if refs:
            body.append('<text:p text:style-name="H2">Referencias literales extraídas de los documentos originales</text:p>')
            for r in refs:
                hdr = f"[{r.doc_id} / {r.ref_id}] {r.file_name} — {r.section_path}"
                body.append(f'<text:p text:style-name="RefHeader">{xml_escape(hdr)}</text:p>')
                lit = (r.literal_text or r.excerpt or "").strip()
                for ln in lit.splitlines():
                    body.append(f'<text:p text:style-name="RefLiteral">{xml_escape(ln)}</text:p>')

    styles_xml = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
    xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
    office:version="1.2">
  <office:automatic-styles>
    <style:page-layout style:name="pm1">
      <style:page-layout-properties fo:page-width="595.28pt" fo:page-height="841.89pt"
          fo:margin-top="48pt" fo:margin-bottom="48pt" fo:margin-left="48pt" fo:margin-right="48pt"/>
    </style:page-layout>
  </office:automatic-styles>
  <office:master-styles>
    <style:master-page style:name="Standard" style:page-layout-name="pm1"/>
  </office:master-styles>
</office:document-styles>
"""

    content_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
    xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
    office:version="1.2">
  <office:automatic-styles>
    <style:style style:name="Title" style:family="paragraph">
      <style:paragraph-properties fo:margin-bottom="6pt"/>
      <style:text-properties fo:font-size="16pt" fo:font-weight="bold" fo:color="#1f4e79"/>
    </style:style>
    <style:style style:name="Meta" style:family="paragraph">
      <style:paragraph-properties fo:margin-bottom="12pt"/>
      <style:text-properties fo:font-size="9pt" fo:font-style="italic" fo:color="#555555"/>
    </style:style>
    <style:style style:name="H1" style:family="paragraph">
      <style:paragraph-properties fo:margin-top="12pt" fo:margin-bottom="4pt"/>
      <style:text-properties fo:font-size="13pt" fo:font-weight="bold" fo:color="#1f4e79"/>
    </style:style>
    <style:style style:name="H2" style:family="paragraph">
      <style:paragraph-properties fo:margin-top="8pt" fo:margin-bottom="4pt"/>
      <style:text-properties fo:font-size="11pt" fo:font-weight="bold" fo:color="#7a4f00"/>
    </style:style>
    <style:style style:name="Question" style:family="paragraph">
      <style:paragraph-properties fo:margin-bottom="6pt"/>
      <style:text-properties fo:font-size="10.5pt" fo:font-weight="bold" fo:color="#1a1a1a"/>
    </style:style>
    <style:style style:name="AnswerLabel" style:family="paragraph">
      <style:paragraph-properties fo:margin-bottom="3pt"/>
      <style:text-properties fo:font-size="10.5pt" fo:font-weight="bold" fo:color="#1e6b1e"/>
    </style:style>
    <style:style style:name="Normal" style:family="paragraph">
      <style:paragraph-properties fo:margin-bottom="4pt" fo:line-height="125%"/>
      <style:text-properties fo:font-size="10.5pt" fo:color="#1a1a1a"/>
    </style:style>
    <style:style style:name="RefHeader" style:family="paragraph">
      <style:paragraph-properties fo:margin-top="6pt" fo:margin-bottom="2pt"/>
      <style:text-properties fo:font-size="9.5pt" fo:font-weight="bold" fo:color="#5c3c00"/>
    </style:style>
    <style:style style:name="RefLiteral" style:family="paragraph">
      <style:paragraph-properties fo:margin-left="16pt" fo:margin-bottom="3pt"/>
      <style:text-properties fo:font-size="9pt" fo:color="#333333"/>
    </style:style>
  </office:automatic-styles>
  <office:body>
    <office:text>
      {''.join(body)}
    </office:text>
  </office:body>
</office:document-content>
"""

    manifest_xml = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">
  <manifest:file-entry manifest:full-path="/" manifest:version="1.2" manifest:media-type="application/vnd.oasis.opendocument.text"/>
  <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
  <manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>
</manifest:manifest>
"""

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        zf.writestr("styles.xml", styles_xml.encode("utf-8"))
        zf.writestr("content.xml", content_xml.encode("utf-8"))
        zf.writestr("META-INF/manifest.xml", manifest_xml.encode("utf-8"))

    return output_path


def _write_conversation_epub(
    turns: List[Any],
    output_path: str,
    title: str,
    generated_at: str,
    docs_list: List[str],
) -> str:
    book_id = f"urn:uuid:{uuid.uuid4()}"
    modified_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    css = """body { font-family: Georgia, serif; line-height: 1.5; margin: 1.2em; color: #1a1a1a; }
h1, h2, h3 { font-family: sans-serif; color: #1f4e79; }
.q { background: #eef5fc; border-left: 4px solid #1f4e79; padding: 0.6em; margin: 0.8em 0; }
.ref-hdr { font-weight: bold; color: #5c3c00; margin-top: 0.8em; font-family: sans-serif; }
.ref-lit { background: #faf7f0; border-left: 3px solid #c9973b; padding: 0.5em; font-size: 0.92em; white-space: pre-wrap; }
"""

    chapters: List[tuple[str, str, str, bytes]] = []
    # Capítulo 0: Portada y documentos fuente
    docs_html = "".join(f"<li>{html.escape(d)}</li>" for d in docs_list) if docs_list else "<li>Documento único</li>"
    intro_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="es" lang="es">
<head><meta charset="utf-8"/><title>{html.escape(title)}</title>
<link rel="stylesheet" type="text/css" href="../styles/style.css"/></head>
<body>
  <h1>{html.escape(title)}</h1>
  <p><em>Generado el {html.escape(generated_at)} mediante Open OCReader (100% Local)</em></p>
  <h2>Documentos fuente analizados</h2>
  <ul>{docs_html}</ul>
</body></html>"""
    chapters.append(("chap_0", "text/chap_0000.xhtml", "Portada y Documentos", intro_xhtml.encode("utf-8")))

    for idx, t in enumerate(turns, start=1):
        ts = getattr(t, "timestamp", "")
        lbl = f"Consulta #{idx}" + (f" ({ts})" if ts else "")
        q_txt = html.escape(getattr(t, "question", ""))
        a_txt = html.escape(getattr(t, "answer", "")).replace("\n", "<br/>")
        refs = getattr(t, "references", None) or []
        ref_parts: List[str] = []
        if refs:
            ref_parts.append("<h3>Referencias literales extraídas</h3>")
            for r in refs:
                lit = html.escape((r.literal_text or r.excerpt or "").strip()).replace("\n", "<br/>")
                ref_parts.append(
                    f'<p class="ref-hdr">[{html.escape(r.doc_id)} / {html.escape(r.ref_id)}] '
                    f'{html.escape(r.file_name)} — {html.escape(r.section_path)}</p>'
                    f'<div class="ref-lit">{lit}</div>'
                )
        xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="es" lang="es">
<head><meta charset="utf-8"/><title>{html.escape(lbl)}</title>
<link rel="stylesheet" type="text/css" href="../styles/style.css"/></head>
<body>
  <h2>{html.escape(lbl)}</h2>
  <div class="q"><strong>Pregunta:</strong> {q_txt}</div>
  <p><strong>Respuesta razonada:</strong><br/>{a_txt}</p>
  {"".join(ref_parts)}
</body></html>"""
        chapters.append((f"chap_{idx}", f"text/chap_{idx:04d}.xhtml", lbl, xhtml.encode("utf-8")))

    nav_items = "\n".join(
        f'      <li><a href="{fname}">{html.escape(lbl)}</a></li>'
        for _cid, fname, lbl, _b in chapters
    )
    nav_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="es" lang="es">
<head><meta charset="utf-8"/><title>Índice</title></head>
<body><nav epub:type="toc" id="toc"><h1>Índice</h1><ol>\n{nav_items}\n</ol></nav></body></html>"""

    manifest_items = [
        '    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '    <item id="css" href="styles/style.css" media-type="text/css"/>',
    ]
    spine_items = []
    for cid, fname, _lbl, _b in chapters:
        manifest_items.append(f'    <item id="{cid}" href="{fname}" media-type="application/xhtml+xml"/>')
        spine_items.append(f'    <itemref idref="{cid}"/>')

    content_opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{book_id}</dc:identifier>
    <dc:title>{html.escape(title)}</dc:title>
    <dc:language>es</dc:language>
    <dc:creator>Open OCReader</dc:creator>
    <meta property="dcterms:modified">{modified_iso}</meta>
  </metadata>
  <manifest>\n{chr(10).join(manifest_items)}\n  </manifest>
  <spine>\n{chr(10).join(spine_items)}\n  </spine>
</package>"""

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container_xml.encode("utf-8"))
        zf.writestr("OEBPS/content.opf", content_opf.encode("utf-8"))
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml.encode("utf-8"))
        zf.writestr("OEBPS/styles/style.css", css.encode("utf-8"))
        for _cid, fname, _lbl, data in chapters:
            zf.writestr(f"OEBPS/{fname}", data)

    return output_path
