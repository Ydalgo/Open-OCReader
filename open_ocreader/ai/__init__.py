"""
Módulo de Inteligencia Artificial Local (Fase 2) para Open OCReader.
Incluye gestión portable de llama.cpp, OCR de manuscritos con Qwen3-VL,
traducción contextual al español, preguntas al documento y anonimización.
"""

from .runtime_manager import LlamaRuntimeManager
from .anonymizer import DocumentAnonymizer
from .translator import DocumentTranslator
from .document_qa import DocumentQA
from .handwriting_ocr import HandwritingOCREngine

__all__ = [
    "LlamaRuntimeManager",
    "DocumentAnonymizer",
    "DocumentTranslator",
    "DocumentQA",
    "HandwritingOCREngine",
]
