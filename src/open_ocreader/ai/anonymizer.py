"""
Motor de anonimización híbrida (RGPD) para Open OCReader.
Combina detección determinista por expresiones regulares (DNI, NIE, CIF, IBAN,
correos, teléfonos) con análisis semántico mediante LLM (nombres, direcciones, entidades).
Soporta documentos largos mediante segmentación automática.
"""

import re
from typing import Callable, Optional
from .chunking import split_text_chunks
from .runtime_manager import LlamaRuntimeManager


class DocumentAnonymizer:
    """Anonimiza datos personales y sensibles en documentos extraídos."""

    MAX_CHUNK_CHARS = 5500

    # Patrones deterministas 100% Python (funcionan en cualquier hardware sin IA)
    PATTERNS = [
        (re.compile(r"\b[A-Z]{2}\d{2}[\s\-]?(?:\d{4}[\s\-]?){3,5}\d{1,4}\b"), "[IBAN]"),
        (re.compile(r"\b(?:\d{4}[\s\-]?){3}\d{1,4}\b"), "[TARJETA]"),
        (re.compile(r"\b\d{2}[\s\-]?\d{8}[\s\-]?\d{2}\b"), "[NUSS]"),
        (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
        (re.compile(r"\b\d{8}[\-\s]?[A-HJ-NP-TV-Z]\b", re.IGNORECASE), "[DNI]"),
        (re.compile(r"\b[XYZ][\-\s]?\d{7}[\-\s]?[A-HJ-NP-TV-Z]\b", re.IGNORECASE), "[NIE]"),
        (re.compile(r"\b[ABCDEFGHJKLMNPQRSUVW][\-\s]?\d{7}[\-\s]?[0-9A-J]\b", re.IGNORECASE), "[CIF]"),
        (re.compile(r"(?:\+34[\s\-]?)?\b[6789]\d{2}[\s\-]?\d{2,3}[\s\-]?\d{2,3}\b"), "[TELÉFONO]"),
        (re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"), "[IP]"),
        (re.compile(r"\b\d{4}[\s\-]?[BCDFGHJKLMNPRSTVWXYZ]{3}\b"), "[MATRÍCULA]"),
        (
            re.compile(
                r"\b(?:Don|Doña|D\.|Dña\.|Sr\.|Sra\.|Dr\.|Dra\.)\s+"
                r"[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,3}\b"
            ),
            "[NOMBRE]",
        ),
        (
            re.compile(
                r"\b(?:Calle|C/|Avda\.|Avenida|Plaza|Pza\.|Paseo|Camino|Carretera|Ronda)\s+"
                r"[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ0-9\s\.ºª\-]{2,45}(?:,?\s*(?:n[º°]?\.?\s*)?\d{1,4})?",
                re.IGNORECASE,
            ),
            "[DIRECCIÓN]",
        ),
    ]

    def __init__(self, runtime: Optional[LlamaRuntimeManager] = None):
        self._runtime = runtime

    @property
    def runtime(self) -> LlamaRuntimeManager:
        if self._runtime is None:
            self._runtime = LlamaRuntimeManager.get_instance()
        return self._runtime

    def anonymize_regex_only(self, text: str, mask_style: str = "tags") -> str:
        """
        Aplica únicamente la capa determinista ultrarrápida (Regex).
        :param mask_style: 'tags' ([DNI], [EMAIL]...) o 'blocks' (████████)
        """
        result = text
        for pattern, tag in self.PATTERNS:
            replacement = "████████" if mask_style == "blocks" else tag
            result = pattern.sub(replacement, result)
        return result

    def anonymize(
        self,
        text: str,
        mask_style: str = "tags",
        use_llm: bool = True,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Anonimiza el texto completo combinando Regex y comprensión semántica del LLM.
        """
        pre_masked = self.anonymize_regex_only(text, mask_style=mask_style)

        if not use_llm or not pre_masked.strip():
            return pre_masked

        tag_instruction = (
            "etiquetas descriptivas como [NOMBRE], [DIRECCIÓN], [EMPRESA]"
            if mask_style == "tags"
            else "bloques negros '████████'"
        )

        system_prompt = (
            "Eres un experto en privacidad y cumplimiento del RGPD.\n"
            "Tu tarea es reescribir el texto sustituyendo TODOS los nombres propios de personas "
            "(incluyendo tratamientos como Don, Doña, Sr., Sra.), direcciones postales, localidades "
            "y nombres de empresas privadas por "
            f"{tag_instruction}.\n"
            "EJEMPLOS:\n"
            "- 'Don Juan Pérez García, vecino de Madrid' -> '[NOMBRE], vecino de [DIRECCIÓN]'\n"
            "- 'Firmado por María López en Calle Mayor 10' -> 'Firmado por [NOMBRE] en [DIRECCIÓN]'\n"
            "- 'Empresa Ejemplo S.L. paga a Carlos Ruiz' -> '[EMPRESA] paga a [NOMBRE]'\n\n"
            "REGLAS ESTRICTAS:\n"
            "1. Sustituye SIEMPRE los nombres y apellidos de personas.\n"
            "2. Mantén intactas las etiquetas que ya existan como [DNI], [EMAIL], [TELÉFONO], [IBAN] o ████████.\n"
            "3. NO resumas ni traduzcas el resto del texto.\n"
            "4. Devuelve ÚNICAMENTE el texto anonimizado, sin explicaciones."
        )

        chunks = split_text_chunks(pre_masked, max_chars=self.MAX_CHUNK_CHARS, overlap=0)
        anonymized_parts = []

        for idx, chunk in enumerate(chunks, start=1):
            if progress_cb:
                if len(chunks) > 1:
                    progress_cb(f"Anonimizando bloque {idx}/{len(chunks)} con IA local...")
                else:
                    progress_cb("Analizando entidades y nombres personales con IA local...")

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": chunk},
            ]

            part = self.runtime.chat_completion(
                messages=messages,
                max_tokens=min(3500, max(1024, len(chunk) + 256)),
                temperature=0.1,
                with_vision=False,
                progress_cb=progress_cb,
            )
            anonymized_parts.append(part)

        return "\n\n".join(anonymized_parts).strip()
