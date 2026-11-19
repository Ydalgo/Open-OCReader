"""
Motor de preguntas y respuestas (Q&A) y resúmenes sobre el contenido del documento.
Responde siempre en el idioma configurado por el usuario en la interfaz o petición.
"""

from typing import Callable, Optional
from .runtime_manager import LlamaRuntimeManager


class DocumentQA:
    """Permite interactuar con el documento, hacer preguntas y generar resúmenes."""

    def __init__(self, runtime: Optional[LlamaRuntimeManager] = None):
        self.runtime = runtime or LlamaRuntimeManager.get_instance()

    def ask(
        self,
        document_text: str,
        question: str,
        response_lang: str = "español de España",
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Responde en el idioma solicitado basándose estrictamente en el documento."""
        if not document_text.strip():
            return "No readable text found in the document."

        if progress_cb:
            progress_cb(f"Analizando documento para responder en {response_lang}...")

        system_prompt = (
            f"You are an expert document assistant. You MUST ALWAYS reply in {response_lang}.\n"
            "Answer the user's question strictly based on the provided document text.\n"
            f"If the requested information does not appear in the document, state it clearly in {response_lang} without inventing anything."
        )

        user_prompt = (
            f"=== DOCUMENT CONTENT ===\n{document_text}\n=== END OF DOCUMENT ===\n\n"
            f"User question: {question}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        return self.runtime.chat_completion(
            messages=messages,
            max_tokens=1536,
            temperature=0.2,
            with_vision=False,
            progress_cb=progress_cb,
        )

    def summarize(
        self,
        document_text: str,
        response_lang: str = "español de España",
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Genera un resumen ejecutivo y puntos clave del documento en el idioma elegido."""
        if not document_text.strip():
            return "No readable text found in the document."

        if progress_cb:
            progress_cb(f"Generando resumen ejecutivo en {response_lang}...")

        system_prompt = (
            f"You are an expert document analyst. Summarize the following document strictly in {response_lang}.\n"
            "Structure your response with:\n"
            "1. Document type and purpose (1-2 lines).\n"
            "2. Key points / Main data (bullet list).\n"
            "3. Relevant dates, amounts, or deadlines (if any)."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": document_text},
        ]

        return self.runtime.chat_completion(
            messages=messages,
            max_tokens=1536,
            temperature=0.2,
            with_vision=False,
            progress_cb=progress_cb,
        )
