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


def _extract_document_text(file_path: Path, handwriting: bool = False) -> str:
    pages = DocumentLoader.load_pages(str(file_path))
    texts = []
    if handwriting:
        from ..ai import HandwritingOCREngine, LlamaRuntimeManager
        runtime = LlamaRuntimeManager.get_instance()
        hw = HandwritingOCREngine(runtime)
        for p in pages:
            texts.append(hw.transcribe_image(p.image))
    else:
        ocr = OCREngine.get_instance()
        for p in pages:
            boxes = ocr.process_image(p.image)
            lines = _group_boxes_into_lines(boxes)
            texts.append("\n".join(" ".join(b.text for b in line) for line in lines))
    return iter_safe_lines(texts, max_chars=200_000).strip()


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
        client_ip = request.client.host if request.client else "unknown"
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

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @api.get("/api/v1/health")
    def health_check():
        from ..ai import LlamaRuntimeManager
        rt = LlamaRuntimeManager.get_instance()
        return {
            "status": "ok",
            "version": __version__,
            "auth_required": bool(os.environ.get("OPEN_OCREADER_API_KEY", "").strip()),
            "hardware": {
                "os": rt.hw.os_name,
                "arch": rt.hw.arch,
                "backend": rt.hw.backend,
                "cpu_cores": rt.hw.cpu_cores,
                "has_vulkan": rt.hw.has_vulkan,
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
    ):
        fmt = format.lower().lstrip(".")
        if fmt not in DocumentConverter.SUPPORTED_FORMATS:
            raise HTTPException(
                status_code=400,
                detail=f"Formato '{format}' no soportado. Válidos: {', '.join(sorted(DocumentConverter.SUPPORTED_FORMATS))}",
            )

        in_path = _save_upload_to_temp(file)
        out_path = in_path.parent / f"{in_path.stem}_ocr.{fmt}"
        background_tasks.add_task(_cleanup_paths, in_path.parent)

        try:
            logger.info(f"[API] Convirtiendo '{in_path.name}' -> {fmt}")
            DocumentConverter().convert(str(in_path), str(out_path), fmt, verbose=False)
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
    ):
        from ..ai import DocumentQA, LlamaRuntimeManager
        in_path = _save_upload_to_temp(file)
        background_tasks.add_task(_cleanup_paths, in_path.parent)
        try:
            text = _extract_document_text(in_path, handwriting=handwriting)
            summary = DocumentQA(LlamaRuntimeManager.get_instance()).summarize(text)
            return JSONResponse({"filename": in_path.name, "summary": summary})
        except SecurityError as se:
            raise HTTPException(status_code=400, detail=str(se))
        except Exception as e:
            logger.exception(f"[API] Error en summarize: {e}")
            raise HTTPException(status_code=500, detail="Error interno al resumir el documento.")

    @api.post("/api/v1/ai/translate", dependencies=[Depends(_verify_api_key)])
    def ai_translate(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        handwriting: bool = Form(False),
    ):
        from ..ai import DocumentTranslator, LlamaRuntimeManager
        in_path = _save_upload_to_temp(file)
        background_tasks.add_task(_cleanup_paths, in_path.parent)
        try:
            text = _extract_document_text(in_path, handwriting=handwriting)
            translation = DocumentTranslator(LlamaRuntimeManager.get_instance()).translate_to_spanish(text)
            return JSONResponse({"filename": in_path.name, "translation": translation})
        except SecurityError as se:
            raise HTTPException(status_code=400, detail=str(se))
        except Exception as e:
            logger.exception(f"[API] Error en translate: {e}")
            raise HTTPException(status_code=500, detail="Error interno al traducir el documento.")

    @api.post("/api/v1/ai/anonymize", dependencies=[Depends(_verify_api_key)])
    def ai_anonymize(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        mask_style: str = Form("tags"),
        handwriting: bool = Form(False),
    ):
        from ..ai import DocumentAnonymizer, LlamaRuntimeManager
        if mask_style not in {"tags", "blocks"}:
            raise HTTPException(status_code=400, detail="mask_style debe ser 'tags' o 'blocks'.")
        in_path = _save_upload_to_temp(file)
        background_tasks.add_task(_cleanup_paths, in_path.parent)
        try:
            text = _extract_document_text(in_path, handwriting=handwriting)
            anonymized = DocumentAnonymizer(LlamaRuntimeManager.get_instance()).anonymize(text, mask_style=mask_style)
            return JSONResponse({"filename": in_path.name, "anonymized_text": anonymized})
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
    ):
        from ..ai import DocumentQA, LlamaRuntimeManager
        if len(question) > 2000:
            raise HTTPException(status_code=400, detail="La pregunta supera el límite de 2000 caracteres.")
        in_path = _save_upload_to_temp(file)
        background_tasks.add_task(_cleanup_paths, in_path.parent)
        try:
            text = _extract_document_text(in_path, handwriting=handwriting)
            answer = DocumentQA(LlamaRuntimeManager.get_instance()).ask(text, question)
            return JSONResponse({"filename": in_path.name, "question": question, "answer": answer})
        except SecurityError as se:
            raise HTTPException(status_code=400, detail=str(se))
        except Exception as e:
            logger.exception(f"[API] Error en ask: {e}")
            raise HTTPException(status_code=500, detail="Error interno al procesar la pregunta.")

    return api


app = create_app()
