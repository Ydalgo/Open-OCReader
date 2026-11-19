"""
Traductor multilingüe contextual a cualquier idioma mediante LLM local (Qwen3-VL).
Soporta documentos largos mediante segmentación automática por bloques.
"""

from typing import Callable, Optional
from .chunking import split_text_chunks
from .runtime_manager import LlamaRuntimeManager


class DocumentTranslator:
    """Traduce documentos desde cualquier idioma a cualquier idioma destino preservando formato."""

    MAX_CHUNK_CHARS = 5500

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

        chunks = split_text_chunks(text, max_chars=self.MAX_CHUNK_CHARS, overlap=0)
        translated_parts = []

        for idx, chunk in enumerate(chunks, start=1):
            if progress_cb:
                if len(chunks) > 1:
                    progress_cb(f"Traduciendo bloque {idx}/{len(chunks)} a '{target_lang}'...")
                else:
                    progress_cb(f"Traduciendo documento a '{target_lang}' con Qwen3-VL...")

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": chunk},
            ]

            part = self.runtime.chat_completion(
                messages=messages,
                max_tokens=min(3500, max(1024, len(chunk))),
                temperature=0.2,
                with_vision=False,
                progress_cb=progress_cb,
            )
            translated_parts.append(part)

        return "\n\n".join(translated_parts).strip()

    def translate_to_spanish(
        self,
        text: str,
        source_lang: str = "auto",
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Atajo retrocompatible para traducir al español de España."""
        return self.translate(text, target_lang="español de España", source_lang=source_lang, progress_cb=progress_cb)
