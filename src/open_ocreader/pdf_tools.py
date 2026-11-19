"""
Herramientas avanzadas de manipulación de PDF para Open OCReader:
  - Desbloqueo de PDFs protegidos con contraseña o restricciones de permisos (pikepdf).
  - Eliminación de firmas digitales y sellos de formulario AcroForm (pikepdf).
  - Limpieza de marcas de agua vectoriales, anotaciones, capas OCG y marcas en escaneos (PyMuPDF + OpenCV).
  - Optimización rápida: compresión, escala de grises y conversión a PDF/A-2b.
"""

import io
from pathlib import Path
from typing import Any, Dict, List, Optional
import cv2
import numpy as np
from PIL import Image, ImageOps
import pikepdf
import pymupdf as fitz
from .formats.pdf_builder import COMPRESSION_PRESETS, _apply_pdfa_metadata_and_profile
from .logger import get_logger

logger = get_logger("pdf_tools")

WATERMARK_OCG_KEYWORDS = (
    "watermark", "marca", "agua", "fondo", "background",
    "draft", "borrador", "confidential", "confidencial",
    "copia", "copy", "sello", "stamp", "sample", "muestra",
)


def unlock_pdf(
    input_path: str,
    output_path: Optional[str] = None,
    password: str = "",
) -> Dict[str, Any]:
    """
    Desbloquea un PDF eliminando restricciones de propietario (copia, impresión, edición)
    y/o eliminando el cifrado de apertura si se facilita la contraseña correcta.
    """
    in_p = Path(input_path)
    out_p = Path(output_path) if output_path else in_p.parent / f"{in_p.stem}_desbloqueado.pdf"

    try:
        with pikepdf.open(str(in_p), password=password or "") as pdf:
            was_encrypted = pdf.is_encrypted
            # Eliminar permisos de modificación restrictivos si existieran
            if "/Perms" in pdf.Root:
                del pdf.Root["/Perms"]
            pdf.save(str(out_p), encryption=False)
    except pikepdf.PasswordError:
        raise ValueError(
            "El PDF está protegido con contraseña de apertura y la clave introducida no es válida. "
            "Introduce la contraseña correcta para desbloquearlo."
        )

    logger.info(f"PDF desbloqueado: {in_p.name} -> {out_p.name} (estaba cifrado={was_encrypted})")
    return {
        "output_path": str(out_p),
        "was_encrypted": was_encrypted,
        "message": (
            f"PDF desbloqueado y guardado sin restricciones en: {out_p.name}"
            if was_encrypted
            else f"El PDF no tenía clave de apertura; restricciones eliminadas en: {out_p.name}"
        ),
    }


def remove_signatures(
    input_path: str,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Elimina firmas digitales criptográficas (/FT /Sig), bloqueos DocMDP/Perms
    y anotaciones visuales de firma (/Widget asociadas a campos /Sig).
    """
    in_p = Path(input_path)
    out_p = Path(output_path) if output_path else in_p.parent / f"{in_p.stem}_sin_firmas.pdf"

    removed_fields = 0
    removed_annots = 0

    with pikepdf.open(str(in_p)) as pdf:
        # 1. Quitar bloqueos de permisos de firma (DocMDP / UR3)
        if "/Perms" in pdf.Root:
            del pdf.Root["/Perms"]

        # 2. Limpiar campos /Sig dentro de /AcroForm
        if "/AcroForm" in pdf.Root:
            acro = pdf.Root["/AcroForm"]
            if "/SigFlags" in acro:
                del acro["/SigFlags"]

            if "/Fields" in acro:
                new_fields = []
                for field in list(acro["/Fields"]):
                    ft = field.get("/FT", None)
                    if ft == pikepdf.Name("/Sig"):
                        removed_fields += 1
                    else:
                        new_fields.append(field)
                acro["/Fields"] = pikepdf.Array(new_fields)

        # 3. Eliminar anotaciones Widget de firma en cada página
        for page in pdf.pages:
            if "/Annots" not in page:
                continue
            kept_annots = []
            for annot in list(page["/Annots"]):
                try:
                    subtype = annot.get("/Subtype", None)
                    ft = annot.get("/FT", None)
                    parent = annot.get("/Parent", None)
                    parent_ft = parent.get("/FT", None) if parent is not None else None
                    if subtype == pikepdf.Name("/Widget") and (
                        ft == pikepdf.Name("/Sig") or parent_ft == pikepdf.Name("/Sig")
                    ):
                        removed_annots += 1
                        continue
                except Exception:
                    pass
                kept_annots.append(annot)
            page["/Annots"] = pikepdf.Array(kept_annots)

        pdf.save(str(out_p), encryption=False)

    logger.info(
        f"Firmas eliminadas en {in_p.name}: {removed_fields} campos /Sig, {removed_annots} anotaciones."
    )
    return {
        "output_path": str(out_p),
        "removed_fields": removed_fields,
        "removed_annots": removed_annots,
        "message": (
            f"Eliminadas {removed_fields} firma(s) y {removed_annots} sello(s) visual(es). "
            f"Guardado en: {out_p.name}"
        ),
    }


def _clean_scan_watermark_image(pil_img: Image.Image) -> Image.Image:
    """
    Limpia marcas de agua claras o de color suave en documentos escaneados
    preservando el texto oscuro nítido.
    """
    rgb = np.array(pil_img.convert("RGB"))
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    # 1. Detectar píxeles claros (marcas de agua grises suaves > 175 de luminancia)
    light_bg_mask = gray > 175

    # 2. Detectar marcas de agua de color pálido (saturación moderada/alta pero valor alto > 130)
    pale_color_mask = (hsv[:, :, 1] > 35) & (hsv[:, :, 2] > 130)

    cleaned = rgb.copy()
    cleaned[light_bg_mask | pale_color_mask] = [255, 255, 255]
    return Image.fromarray(cleaned)


def remove_watermarks(
    input_path: str,
    output_path: Optional[str] = None,
    watermark_text: str = "",
    remove_annotations: bool = True,
    remove_ocg: bool = True,
    clean_scan_watermark: bool = False,
) -> Dict[str, Any]:
    """
    Elimina marcas de agua de un PDF combinando técnicas vectoriales y opcionalmente
    limpieza de imagen para escaneos:
      - Anotaciones /Watermark y /Stamp.
      - Capas opcionales (OCG) relacionadas con marcas de agua o fondos.
      - Texto de marca de agua específico (redacción transparente sin caja negra).
      - Limpieza OpenCV para marcas de agua grises/coloreadas quemadas en escaneos.
    """
    in_p = Path(input_path)
    out_p = Path(output_path) if output_path else in_p.parent / f"{in_p.stem}_sin_marcas.pdf"

    removed_annots = 0
    removed_text_hits = 0
    removed_ocgs = 0

    doc = fitz.open(str(in_p))
    try:
        # 1. Ocultar capas opcionales (OCG) con nombre de marca de agua
        if remove_ocg:
            ocgs = doc.get_ocgs()
            off_xrefs = []
            for xref, info in ocgs.items():
                name = str(info.get("name", "")).lower()
                if any(kw in name for kw in WATERMARK_OCG_KEYWORDS):
                    off_xrefs.append(xref)
                    removed_ocgs += 1
            if off_xrefs:
                doc.set_layer(-1, off=off_xrefs)

        # 2. Recorrer páginas: eliminar anotaciones Watermark/Stamp y texto indicado
        for page in doc:
            if remove_annotations:
                annots_to_del = []
                for annot in page.annots() or []:
                    atype = (annot.type[1] or "").lower()
                    if atype in ("watermark", "stamp", "freetext"):
                        if atype in ("watermark", "stamp") or (
                            watermark_text and watermark_text.lower() in (annot.info.get("content", "") or "").lower()
                        ):
                            annots_to_del.append(annot)
                for a in annots_to_del:
                    page.delete_annot(a)
                    removed_annots += 1

            if watermark_text.strip():
                hits = page.search_for(watermark_text.strip())
                for rect in hits:
                    page.add_redact_annot(rect, fill=None)
                    removed_text_hits += 1
                if hits:
                    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        # 3. Limpieza de marcas de agua en escaneos (imagen rasterizada)
        if clean_scan_watermark:
            clean_doc = fitz.open()
            try:
                for page in doc:
                    pix = page.get_pixmap(dpi=180)
                    pil_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    cleaned_pil = _clean_scan_watermark_image(pil_img)
                    buf = io.BytesIO()
                    cleaned_pil.save(buf, format="JPEG", quality=88, optimize=True)
                    new_page = clean_doc.new_page(width=page.rect.width, height=page.rect.height)
                    new_page.insert_image(new_page.rect, stream=buf.getvalue())
                clean_doc.save(str(out_p), deflate=True, garbage=4)
            finally:
                clean_doc.close()
        else:
            doc.save(str(out_p), deflate=True, garbage=4)
    finally:
        doc.close()

    logger.info(
        f"Limpieza marcas de agua en {in_p.name}: annots={removed_annots}, "
        f"ocg={removed_ocgs}, texto={removed_text_hits}, scan={clean_scan_watermark}"
    )
    return {
        "output_path": str(out_p),
        "removed_annots": removed_annots,
        "removed_ocgs": removed_ocgs,
        "removed_text_hits": removed_text_hits,
        "message": (
            f"Limpieza completada (anotaciones: {removed_annots}, capas OCG: {removed_ocgs}, "
            f"coincidencias texto: {removed_text_hits}). Guardado en: {out_p.name}"
        ),
    }


def optimize_pdf(
    input_path: str,
    output_path: Optional[str] = None,
    compression: str = "balanced",
    grayscale: bool = False,
    pdfa: bool = False,
) -> Dict[str, Any]:
    """
    Comprime un PDF, lo convierte opcionalmente a escala de grises y/o a estándar PDF/A-2b.
    """
    in_p = Path(input_path)
    suffix = "_pdfa" if pdfa else "_optimizado"
    out_p = Path(output_path) if output_path else in_p.parent / f"{in_p.stem}{suffix}.pdf"

    preset = COMPRESSION_PRESETS.get(compression, COMPRESSION_PRESETS["balanced"])
    orig_size = in_p.stat().st_size

    doc = fitz.open(str(in_p))
    out_doc = fitz.open()
    try:
        dpi = 150 if compression == "compact" else (180 if compression == "balanced" else 220)
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            pil_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            if grayscale:
                pil_img = ImageOps.grayscale(pil_img)
            if preset["max_side"] and max(pil_img.size) > preset["max_side"]:
                pil_img.thumbnail((preset["max_side"], preset["max_side"]), Image.Resampling.LANCZOS)

            buf = io.BytesIO()
            pil_img.save(buf, format="JPEG", quality=preset["quality"], optimize=True)
            new_page = out_doc.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(new_page.rect, stream=buf.getvalue())

            # Preservar capa de texto invisible si el PDF original tenía texto
            text_dict = page.get_text("dict")
            for block in text_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        txt = (span.get("text") or "").strip()
                        if not txt:
                            continue
                        origin = span.get("origin", (0, 0))
                        size = max(4.0, float(span.get("size", 10.0)))
                        new_page.insert_text(
                            fitz.Point(origin[0], origin[1]),
                            txt,
                            fontsize=size,
                            render_mode=3,  # Texto invisible seleccionable
                        )

        out_doc.save(str(out_p), deflate=True, garbage=4)
    finally:
        doc.close()
        out_doc.close()

    if pdfa:
        _apply_pdfa_metadata_and_profile(str(out_p), grayscale=grayscale)

    new_size = out_p.stat().st_size
    pct = (1.0 - (new_size / orig_size)) * 100.0 if orig_size > 0 else 0.0
    return {
        "output_path": str(out_p),
        "original_bytes": orig_size,
        "new_bytes": new_size,
        "saved_percent": pct,
        "message": (
            f"PDF optimizado: {orig_size / 1024:.0f} KB → {new_size / 1024:.0f} KB "
            f"({pct:+.1f}%). Guardado en: {out_p.name}"
        ),
    }
