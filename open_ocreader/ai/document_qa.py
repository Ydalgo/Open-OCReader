"""
Motor de preguntas y respuestas (Q&A) y resúmenes sobre el contenido del documento.
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
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Responde en español a una pregunta basada estrictamente en el documento."""
        if not document_text.strip():
            return "El documento no contiene texto legible."

        if progress_cb:
            progress_cb("Analizando el contenido del documento para responder...")

        system_prompt = (
            "Eres un asistente documental experto que responde siempre en español de España.\n"
            "Responde a la pregunta del usuario basándote ÚNICAMENTE en el texto del documento proporcionado.\n"
            "Si el dato solicitado no aparece en el documento, indícalo claramente sin inventar ni suponer nada."
        )

        user_prompt = (
            f"=== CONTENIDO DEL DOCUMENTO ===\n{document_text}\n=== FIN DEL DOCUMENTO ===\n\n"
            f"Pregunta del usuario: {question}"
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
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Genera un resumen ejecutivo y puntos clave del documento en español."""
        if not document_text.strip():
            return "El documento no contiene texto legible."

        if progress_cb:
            progress_cb("Generando resumen ejecutivo del documento...")

        system_prompt = (
            "Eres un analista documental experto. Resume el siguiente documento en español de España.\n"
            "Estructura tu respuesta con:\n"
            "1. **Tipo de documento y propósito** (1-2 líneas).\n"
            "2. **Puntos clave / Datos principales** (en lista de viñetas).\n"
            "3. **Fechas, importes o plazos relevantes** (si los hubiera)."
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
