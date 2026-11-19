"""
API REST de Open OCReader basada en FastAPI.
Soporta clientes web (CORS habilitado) para conversión estructural (PDF/DOCX/XLSX/TXT/JSON)
y procesamiento con IA local (Qwen3-VL: manuscritos, resumen, traducción, anonimización y Q&A).
"""

import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .. import __version__
from ..converter import DocumentConverter
from ..document_loader import DocumentLoader
from ..engine import OCREngine
from ..formats.docx_builder import _group_boxes_into_lines
from ..logger import get_logger

logger = get_logger("server.api")


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
    temp_dir = Path(tempfile.gettempdir()) / "open_ocreader_api" / uuid.uuid4().hex
    temp_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(upload.filename or "documento.bin").name
    dest = temp_dir / safe_name
    with open(dest, "wb") as buffer:
        shutil.copyfileobj(upload.file, buffer)
    return dest


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
    return "\n\n".join(texts).strip()


def create_app() -> FastAPI:
    api = FastAPI(
        title="Open OCReader API",
        description="API REST 100% local para digitalización OCR fiel (PDF Sandwich, DOCX, XLSX) e IA documental (Qwen3-VL).",
        version=__version__,
    )

    api.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @api.get("/api/v1/health")
    def health_check():
        from ..ai import LlamaRuntimeManager
        rt = LlamaRuntimeManager.get_instance()
        return {
            "status": "ok",
            "version": __version__,
            "hardware": {
                "os": rt.hw.os_name,
                "arch": rt.hw.arch,
                "backend": rt.hw.backend,
                "cpu_cores": rt.hw.cpu_cores,
                "has_vulkan": rt.hw.has_vulkan,
            },
            "ai_models_ready": rt.is_models_present(),
        }

    @api.post("/api/v1/convert")
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
        except Exception as e:
            logger.exception(f"[API] Error en conversión: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @api.post("/api/v1/ai/transcribe")
    def ai_transcribe(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        handwriting: bool = Form(False),
    ):
        in_path = _save_upload_to_temp(file)
        background_tasks.add_task(_cleanup_paths, in_path.parent)
        try:
            text = _extract_document_text(in_path, handwriting=handwriting)
            return JSONResponse({"filename": file.filename, "handwriting_mode": handwriting, "text": text})
        except Exception as e:
            logger.exception(f"[API] Error en transcribe: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @api.post("/api/v1/ai/summarize")
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
            return JSONResponse({"filename": file.filename, "summary": summary})
        except Exception as e:
            logger.exception(f"[API] Error en summarize: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @api.post("/api/v1/ai/translate")
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
            return JSONResponse({"filename": file.filename, "translation": translation})
        except Exception as e:
            logger.exception(f"[API] Error en translate: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @api.post("/api/v1/ai/anonymize")
    def ai_anonymize(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        mask_style: str = Form("tags"),
        handwriting: bool = Form(False),
    ):
        from ..ai import DocumentAnonymizer, LlamaRuntimeManager
        in_path = _save_upload_to_temp(file)
        background_tasks.add_task(_cleanup_paths, in_path.parent)
        try:
            text = _extract_document_text(in_path, handwriting=handwriting)
            anonymized = DocumentAnonymizer(LlamaRuntimeManager.get_instance()).anonymize(text, mask_style=mask_style)
            return JSONResponse({"filename": file.filename, "anonymized_text": anonymized})
        except Exception as e:
            logger.exception(f"[API] Error en anonymize: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @api.post("/api/v1/ai/ask")
    def ai_ask(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        question: str = Form(...),
        handwriting: bool = Form(False),
    ):
        from ..ai import DocumentQA, LlamaRuntimeManager
        in_path = _save_upload_to_temp(file)
        background_tasks.add_task(_cleanup_paths, in_path.parent)
        try:
            text = _extract_document_text(in_path, handwriting=handwriting)
            answer = DocumentQA(LlamaRuntimeManager.get_instance()).ask(text, question)
            return JSONResponse({"filename": file.filename, "question": question, "answer": answer})
        except Exception as e:
            logger.exception(f"[API] Error en ask: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return api


app = create_app()
