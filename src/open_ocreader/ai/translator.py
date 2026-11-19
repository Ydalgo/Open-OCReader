"""
Traductor multilingüe contextual a cualquier idioma mediante LLM local (Qwen3-VL).
"""

from typing import Callable, Optional
from .runtime_manager import LlamaRuntimeManager


class DocumentTranslator:
    """Traduce documentos desde cualquier idioma a cualquier idioma destino preservando formato."""

    def __init__(self, runtime: Optional[LlamaRuntimeManager] = None):
        self.runtime = runtime or LlamaRuntimeManager.get_instance()

    def translate(
        self,
        text: str,
        target_lang: str = "Español",
        source_lang: str = "auto",
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Traduce el texto al idioma destino indicado preservando párrafos, cifras y terminología.
        """
        if not text.strip():
            return ""

        if progress_cb:
            progress_cb(f"Traduciendo documento a '{target_lang}' con Qwen3-VL...")

        lang_hint = (
            "detecting the source language automatically"
            if source_lang == "auto"
            else f"from '{source_lang}'"
        )

        system_prompt = (
            f"You are an expert professional translator. Translate the following text into {target_lang} ({lang_hint}).\n"
            "STRICT RULES:\n"
            "1. Preserve the professional, legal, or technical tone of the original document.\n"
            "2. Keep paragraphs, lists, dates, and exact numbers intact.\n"
            "3. Do not summarize or omit any information.\n"
            f"4. Return ONLY the final translation in {target_lang}, without introductions or commentary."
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

    def translate_to_spanish(
        self,
        text: str,
        source_lang: str = "auto",
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Atajo retrocompatible para traducir al español de España."""
        return self.translate(text, target_lang="español de España", source_lang=source_lang, progress_cb=progress_cb)
