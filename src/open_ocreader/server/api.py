"""
API REST endurecida de Open OCReader basada en FastAPI.

Controles de seguridad integrados:
  - Autenticación por API Key (X-API-Key / Authorization: Bearer) en tiempo constante.
  - CORS restrictivo por defecto (solo localhost; configurable vía OPEN_OCREADER_CORS_ORIGINS).
  - Limitación de tasa (Rate Limiting) en memoria por IP cliente (anti-DoS).
  - Límite estricto de tamaño de subida en streaming (100 MB máx., HTTP 413).
  - Validación de extensión, firma mágica y directorios temporales privados (0700).
  - Cabeceras de seguridad HTTP (X-Content-Type-Options, X-Frame-Options, Cache-Control).
  - Respuestas de error saneadas (sin fugar rutas internas ni trazas al cliente).
"""

import os
import shutil
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Deque, Dict, Optional
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .. import __version__
from ..converter import DocumentConverter
from ..document_loader import DocumentLoader
from ..engine import OCREngine
from ..formats.docx_builder import _group_boxes_into_lines
from ..logger import get_logger
from ..security import (
    MAX_INPUT_FILE_BYTES,
    SecurityError,
    constant_time_equals,
    iter_safe_lines,
    private_temp_dir,
    sanitize_filename,
    validate_input_file,
)

logger = get_logger("server.api")

# Rate limiter en memoria: máximo 30 peticiones por minuto por IP
_RATE_LIMIT_MAX_REQS = int(os.environ.get("OPEN_OCREADER_RATE_LIMIT", "30"))
_RATE_LIMIT_WINDOW_S = 60.0
_rate_buckets: Dict[str, Deque[float]] = defaultdict(deque)


def _cleanup_paths(*paths: Path):
    for p in paths:
        try:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.exists():
                p.unlink(missing_ok=True)
        except Exception:
            pass


def _save_upload_to_temp(upload: UploadFile) -> Path:
    """Guarda el fichero subido en un directorio temporal privado (0700) limitando el tamaño en streaming."""
    temp_dir = private_temp_dir(prefix="open_ocreader_api_")
    safe_name = sanitize_filename(upload.filename or "documento.bin")
    dest = temp_dir / safe_name

    total = 0
    try:
        with open(dest, "wb") as buffer:
            while True:
                chunk = upload.file.read(256 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_INPUT_FILE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"El fichero supera el tamaño máximo permitido ({MAX_INPUT_FILE_BYTES // (1024**2)} MB).",
                    )
                buffer.write(chunk)
        validate_input_file(dest)
        return dest
    except HTTPException:
        _cleanup_paths(temp_dir)
        raise
    except SecurityError as se:
        _cleanup_paths(temp_dir)
        raise HTTPException(status_code=400, detail=str(se))
    except Exception as e:
        _cleanup_paths(temp_dir)
        logger.exception(f"[API] Error guardando upload: {e}")
        raise HTTPException(status_code=500, detail="Error interno al recibir el fichero.")


def _extract_document_text(file_path: Path, handwriting: bool = False, force_ocr: bool = False) -> str:
    text, _stats = DocumentLoader.extract_text_smart(
        str(file_path),
        handwriting=handwriting,
        force_ocr=force_ocr,
    )
    return text[:250_000].strip()


def _is_pdf_tools_disabled() -> bool:
    return os.environ.get("OPEN_OCREADER_DISABLE_PDF_TOOLS", "").strip().lower() in {"1", "true", "yes"}


def _verify_api_key(
    x_api_key: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> None:
    """Valida la clave API si OPEN_OCREADER_API_KEY está configurada."""
    expected = os.environ.get("OPEN_OCREADER_API_KEY", "").strip()
    if not expected:
        return

    provided = x_api_key
    if not provided and authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()

    if not provided or not constant_time_equals(provided, expected):
        raise HTTPException(status_code=401, detail="No autorizado: clave API inválida o ausente.")


def create_app() -> FastAPI:
    api = FastAPI(
        title="Open OCReader API",
        description="API REST 100% local y endurecida para digitalización OCR fiel e IA documental (Qwen3-VL).",
        version=__version__,
    )

    # CORS restrictivo por defecto (solo localhost); ampliable explícitamente por variable de entorno
    raw_origins = os.environ.get("OPEN_OCREADER_CORS_ORIGINS", "http://127.0.0.1,http://localhost")
    allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]

    api.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "X-API-Key", "Content-Type"],
    )

    @api.middleware("http")
    async def security_and_rate_limit_middleware(request: Request, call_next):
        # Soporte seguro para proxy inverso Nginx (L-01): Usar X-Real-IP si la conexión procede de 127.0.0.1
        client_ip = request.client.host if request.client else "unknown"
        if client_ip in ("127.0.0.1", "::1", "localhost") or os.environ.get("OPEN_OCREADER_TRUST_PROXY", "").strip().lower() in ("1", "true", "yes"):
            x_real = request.headers.get("X-Real-IP")
            x_forwarded = request.headers.get("X-Forwarded-For")
            if x_real:
                client_ip = x_real.strip()
            elif x_forwarded:
                client_ip = x_forwarded.split(",")[0].strip()

        now = time.monotonic()
        bucket = _rate_buckets[client_ip]
        while bucket and now - bucket[0] > _RATE_LIMIT_WINDOW_S:
            bucket.popleft()
        if len(bucket) >= _RATE_LIMIT_MAX_REQS:
            return JSONResponse(
                status_code=429,
                content={"detail": "Demasiadas solicitudes. Inténtalo de nuevo en unos segundos."},
            )
        bucket.append(now)

        # Purga periódica para evitar fugas de memoria en DDoS con IPs aleatorias
        if len(_rate_buckets) > 1000:
            stale = [ip for ip, b in _rate_buckets.items() if not b or (now - b[-1] > _RATE_LIMIT_WINDOW_S * 2)]
            for ip in stale:
                _rate_buckets.pop(ip, None)

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @api.get("/api/v1/health")
    def health_check(
        x_api_key: Optional[str] = Header(default=None),
        authorization: Optional[str] = Header(default=None),
    ):
        expected_key = os.environ.get("OPEN_OCREADER_API_KEY", "").strip()
        is_auth = False
        if not expected_key:
            is_auth = True
        else:
            provided = x_api_key
            if not provided and authorization and authorization.lower().startswith("bearer "):
                provided = authorization[7:].strip()
            if provided and constant_time_equals(provided, expected_key):
                is_auth = True

        if not is_auth:
            # L-01: Sin autenticación previa devolver estrictamente solo status y version
            return {
                "status": "ok",
                "version": __version__,
            }

        from ..ai import LlamaRuntimeManager
        rt = LlamaRuntimeManager.get_instance()
        return {
            "status": "ok",
            "version": __version__,
            "auth_required": bool(expected_key),
            "pdf_tools_enabled": not _is_pdf_tools_disabled(),
            "hardware": {
                "os": rt.hw.os_name,
                "arch": rt.hw.arch,
                "backend": rt.hw.backend,
                "cpu_cores": rt.hw.cpu_cores,
                "ram_total_gb": rt.hw.ram_total_gb,
                "has_vulkan": rt.hw.has_vulkan,
                "ai_tier": rt.tier.tier_name,
                "vlm_model": rt.tier.vlm_label,
                "embed_model": rt.tier.embed_label,
            },
            "ai_models_ready": rt.is_models_present(),
        }

    @api.get("/api/v1/governance", dependencies=[Depends(_verify_api_key)])
    def governance_report():
        from ..governance import collect_governance_data
        return JSONResponse(collect_governance_data())

    @api.post("/api/v1/convert", dependencies=[Depends(_verify_api_key)])
    def convert_document(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        format: str = Form("pdf"),
        force_ocr: bool = Form(False),
        compression: str = Form("high"),
        grayscale: bool = Form(False),
    ):
        fmt = format.lower().lstrip(".")
        if fmt not in DocumentConverter.SUPPORTED_FORMATS:
            raise HTTPException(
                status_code=400,
                detail=f"Formato '{format}' no soportado. Válidos: {', '.join(sorted(DocumentConverter.SUPPORTED_FORMATS))}",
            )

        in_path = _save_upload_to_temp(file)
        ext = "pdf" if fmt == "pdfa" else fmt
        out_path = in_path.parent / f"{in_path.stem}_ocr.{ext}"
        background_tasks.add_task(_cleanup_paths, in_path.parent)

        try:
            logger.info(f"[API] Convirtiendo '{in_path.name}' -> {fmt}")
            DocumentConverter().convert(
                str(in_path),
                str(out_path),
                fmt,
                verbose=False,
                force_ocr=force_ocr,
                pdf_compression=compression,
                grayscale=grayscale,
            )
            return FileResponse(
                path=str(out_path),
                filename=out_path.name,
                media_type="application/octet-stream",
            )
        except SecurityError as se:
            raise HTTPException(status_code=400, detail=str(se))
        except Exception as e:
            logger.exception(f"[API] Error en conversión: {e}")
            raise HTTPException(status_code=500, detail="Error interno al convertir el documento.")

    @api.post("/api/v1/ai/transcribe", dependencies=[Depends(_verify_api_key)])
    def ai_transcribe(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        handwriting: bool = Form(False),
    ):
        in_path = _save_upload_to_temp(file)
        background_tasks.add_task(_cleanup_paths, in_path.parent)
        try:
            text = _extract_document_text(in_path, handwriting=handwriting)
            return JSONResponse({"filename": in_path.name, "handwriting_mode": handwriting, "text": text})
        except SecurityError as se:
            raise HTTPException(status_code=400, detail=str(se))
        except Exception as e:
            logger.exception(f"[API] Error en transcribe: {e}")
            raise HTTPException(status_code=500, detail="Error interno al transcribir el documento.")

    @api.post("/api/v1/ai/summarize", dependencies=[Depends(_verify_api_key)])
    def ai_summarize(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        handwriting: bool = Form(False),
        lang: str = Form("es"),
    ):
        from ..ai import DocumentQA, LlamaRuntimeManager
        from ..i18n import get_llm_language_name
        in_path = _save_upload_to_temp(file)
        background_tasks.add_task(_cleanup_paths, in_path.parent)
        try:
            text = _extract_document_text(in_path, handwriting=handwriting)
            summary = DocumentQA(LlamaRuntimeManager.get_instance()).summarize(
                text, response_lang=get_llm_language_name(lang)
            )
            return JSONResponse({"filename": in_path.name, "lang": lang, "summary": summary})
        except SecurityError as se:
            raise HTTPException(status_code=400, detail=str(se))
        except Exception as e:
            logger.exception(f"[API] Error en summarize: {e}")
            raise HTTPException(status_code=500, detail="Error interno al resumir el documento.")

    @api.post("/api/v1/ai/translate", dependencies=[Depends(_verify_api_key)])
    def ai_translate(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        target_lang: str = Form("Español"),
        handwriting: bool = Form(False),
    ):
        from ..ai import DocumentTranslator, LlamaRuntimeManager
        in_path = _save_upload_to_temp(file)
        background_tasks.add_task(_cleanup_paths, in_path.parent)
        try:
            text = _extract_document_text(in_path, handwriting=handwriting)
            translation = DocumentTranslator(LlamaRuntimeManager.get_instance()).translate(
                text, target_lang=target_lang
            )
            return JSONResponse({"filename": in_path.name, "target_lang": target_lang, "translation": translation})
        except SecurityError as se:
            raise HTTPException(status_code=400, detail=str(se))
        except Exception as e:
            logger.exception(f"[API] Error en translate: {e}")
            raise HTTPException(status_code=500, detail="Error interno al traducir el documento.")

    @api.post("/api/v1/ai/translate-document", dependencies=[Depends(_verify_api_key)])
    def ai_translate_document(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        format: str = Form("docx"),
        target_lang: str = Form("Español"),
        source_lang: str = Form("auto"),
        preserve_layout: bool = Form(True),
        compression: str = Form("high"),
        grayscale: bool = Form(False),
        force_ocr: bool = Form(False),
        handwriting: bool = Form(False),
    ):
        fmt = format.lower().lstrip(".")
        if fmt not in DocumentConverter.SUPPORTED_FORMATS:
            raise HTTPException(
                status_code=400,
                detail=f"Formato '{format}' no soportado. Válidos: {', '.join(sorted(DocumentConverter.SUPPORTED_FORMATS))}",
            )
        in_path = _save_upload_to_temp(file)
        ext = "pdf" if fmt == "pdfa" else fmt
        safe_tag = "".join(c for c in target_lang.lower() if c.isalnum())[:10] or "trad"
        out_path = in_path.parent / f"{in_path.stem}_traducido_{safe_tag}.{ext}"
        background_tasks.add_task(_cleanup_paths, in_path.parent)
        try:
            logger.info(f"[API] Traduciendo documento '{in_path.name}' -> '{target_lang}' ({fmt})")
            DocumentConverter().translate_document(
                input_path=str(in_path),
                output_path=str(out_path),
                output_format=fmt,
                target_lang=target_lang,
                source_lang=source_lang,
                preserve_layout=preserve_layout,
                pdf_compression=compression,
                grayscale=grayscale,
                force_ocr=force_ocr,
                handwriting=handwriting,
                verbose=False,
            )
            return FileResponse(
                path=str(out_path),
                filename=out_path.name,
                media_type="application/octet-stream",
            )
        except SecurityError as se:
            raise HTTPException(status_code=400, detail=str(se))
        except Exception as e:
            logger.exception(f"[API] Error en translate-document: {e}")
            raise HTTPException(status_code=500, detail="Error interno al traducir el documento completo.")

    @api.post("/api/v1/ai/anonymize", dependencies=[Depends(_verify_api_key)])
    def ai_anonymize(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        mask_style: str = Form("tags"),
        use_llm: bool = Form(True),
        handwriting: bool = Form(False),
    ):
        from ..ai import DocumentAnonymizer, LlamaRuntimeManager
        if mask_style not in {"tags", "blocks"}:
            raise HTTPException(status_code=400, detail="mask_style debe ser 'tags' o 'blocks'.")
        in_path = _save_upload_to_temp(file)
        background_tasks.add_task(_cleanup_paths, in_path.parent)
        try:
            rt = LlamaRuntimeManager.get_instance()
            effective_llm = use_llm and rt.tier.vlm_enabled
            text = _extract_document_text(in_path, handwriting=handwriting)
            anonymized = DocumentAnonymizer(rt).anonymize(
                text, mask_style=mask_style, use_llm=effective_llm
            )
            return JSONResponse({
                "filename": in_path.name,
                "used_llm": effective_llm,
                "anonymized_text": anonymized,
            })
        except SecurityError as se:
            raise HTTPException(status_code=400, detail=str(se))
        except Exception as e:
            logger.exception(f"[API] Error en anonymize: {e}")
            raise HTTPException(status_code=500, detail="Error interno al anonimizar el documento.")

    @api.post("/api/v1/ai/ask", dependencies=[Depends(_verify_api_key)])
    def ai_ask(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        question: str = Form(...),
        handwriting: bool = Form(False),
        lang: str = Form("es"),
        export_format: Optional[str] = Form(None),
    ):
        from datetime import datetime
        from ..ai import DocumentQA, LlamaRuntimeManager
        from ..ai.multi_doc_chat import ChatTurnRecord
        from ..formats.conversation_exporter import (
            SUPPORTED_CONVERSATION_EXPORT_FORMATS,
            export_conversation_with_references,
        )
        from ..i18n import get_llm_language_name

        if len(question) > 2000:
            raise HTTPException(status_code=400, detail="La pregunta supera el límite de 2000 caracteres.")

        exp_fmt = export_format.lower().lstrip(".") if export_format else None
        if exp_fmt and exp_fmt not in SUPPORTED_CONVERSATION_EXPORT_FORMATS:
            raise HTTPException(
                status_code=400,
                detail=f"export_format '{export_format}' no soportado. Válidos: {', '.join(SUPPORTED_CONVERSATION_EXPORT_FORMATS)}",
            )

        in_path = _save_upload_to_temp(file)
        background_tasks.add_task(_cleanup_paths, in_path.parent)
        try:
            text = _extract_document_text(in_path, handwriting=handwriting)
            answer, refs = DocumentQA(LlamaRuntimeManager.get_instance()).ask_with_references(
                text,
                question,
                response_lang=get_llm_language_name(lang),
                file_name=in_path.name,
            )
            if exp_fmt:
                ext = "pdf" if exp_fmt == "pdfa" else exp_fmt
                out_path = in_path.parent / f"{in_path.stem}_consulta.{ext}"
                turn = ChatTurnRecord(
                    question=question,
                    answer=answer,
                    references=refs,
                    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
                export_conversation_with_references(
                    turns=[turn],
                    output_path=str(out_path),
                    output_format=exp_fmt,
                    title=f"Consulta y Referencias Literales — {in_path.name}",
                    documents_summary=[f"[DOC-1] {in_path.name}"],
                )
                return FileResponse(
                    path=str(out_path),
                    filename=out_path.name,
                    media_type="application/octet-stream",
                )

            return JSONResponse({
                "filename": in_path.name,
                "lang": lang,
                "question": question,
                "answer": answer,
                "references": [
                    {
                        "doc_id": r.doc_id,
                        "ref_id": r.ref_id,
                        "file_name": r.file_name,
                        "section_path": r.section_path,
                        "literal_text": r.literal_text,
                    }
                    for r in refs
                ],
            })
        except SecurityError as se:
            raise HTTPException(status_code=400, detail=str(se))
        except Exception as e:
            logger.exception(f"[API] Error en ask: {e}")
            raise HTTPException(status_code=500, detail="Error interno al procesar la pregunta.")

    @api.post("/api/v1/pdf/{action}", dependencies=[Depends(_verify_api_key)])
    def pdf_tool_endpoint(
        action: str,
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        password: str = Form(""),
        watermark_text: str = Form(""),
        clean_scan: bool = Form(False),
        compression: str = Form("balanced"),
        grayscale: bool = Form(False),
        pdfa: bool = Form(False),
    ):
        if _is_pdf_tools_disabled():
            raise HTTPException(status_code=403, detail="Herramientas PDF deshabilitadas por política ENS.")
        from ..pdf_tools import optimize_pdf, remove_signatures, remove_watermarks, unlock_pdf

        in_path = _save_upload_to_temp(file)
        background_tasks.add_task(_cleanup_paths, in_path.parent)
        try:
            if action == "unlock":
                res = unlock_pdf(str(in_path), password=password)
            elif action == "remove-signatures":
                res = remove_signatures(str(in_path))
            elif action == "remove-watermarks":
                res = remove_watermarks(str(in_path), watermark_text=watermark_text, clean_scan_watermark=clean_scan)
            elif action == "optimize":
                res = optimize_pdf(str(in_path), compression=compression, grayscale=grayscale, pdfa=pdfa)
            else:
                raise HTTPException(status_code=400, detail=f"Acción PDF no válida: {action}")
            out_p = Path(res["output_path"])
            return FileResponse(path=str(out_p), filename=out_p.name, media_type="application/pdf")
        except HTTPException:
            raise
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve))
        except Exception as e:
            logger.exception(f"[API] Error en herramienta PDF '{action}': {e}")
            raise HTTPException(status_code=500, detail="Error interno procesando el PDF.")

    return api


app = create_app()
