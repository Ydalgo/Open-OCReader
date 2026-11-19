"""
Traductor multilingüe contextual al español de España mediante LLM local.
"""

from typing import Callable, Optional
from .runtime_manager import LlamaRuntimeManager


class DocumentTranslator:
    """Traduce documentos de cualquier idioma al español manteniendo contexto y estructura."""

    def __init__(self, runtime: Optional[LlamaRuntimeManager] = None):
        self.runtime = runtime or LlamaRuntimeManager.get_instance()

    def translate_to_spanish(
        self,
        text: str,
        source_lang: str = "auto",
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Traduce el texto al español de España preservando párrafos, cifras y terminología.
        """
        if not text.strip():
            return ""

        if progress_cb:
            progress_cb("Traduciendo documento al español con Qwen3-VL...")

        lang_hint = (
            "detectando automáticamente el idioma de origen"
            if source_lang == "auto"
            else f"desde el idioma '{source_lang}'"
        )

        system_prompt = (
            f"Eres un traductor profesional experto. Traduce el siguiente texto al español de España ({lang_hint}).\n"
            "REGLAS ESTRICTAS:\n"
            "1. Mantén el tono profesional, jurídico o técnico del documento original.\n"
            "2. Conserva la estructura de párrafos, listas, fechas y cifras exactas.\n"
            "3. No resumas ni omitas información.\n"
            "4. Devuelve ÚNICAMENTE la traducción final al español, sin introducciones ni notas."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]

        return self.runtime.chat_completion(
            messages=messages,
            max_tokens=max(2048, len(text) * 2),
            temperature=0.2,
            with_vision=False,
            progress_cb=progress_cb,
        )
