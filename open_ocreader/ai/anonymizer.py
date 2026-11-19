"""
Motor de anonimización híbrida (RGPD) para Open OCReader.
Combina detección determinista por expresiones regulares (DNI, NIE, CIF, IBAN,
correos, teléfonos) con análisis semántico mediante LLM (nombres, direcciones, entidades).
"""

import re
from typing import Callable, Optional
from .runtime_manager import LlamaRuntimeManager


class DocumentAnonymizer:
    """Anonimiza datos personales y sensibles en documentos extraídos."""

    # Patrones deterministas para España / Europa
    PATTERNS = [
        # IBAN español o europeo
        (re.compile(r"\b[A-Z]{2}\d{2}[\s\-]?(?:\d{4}[\s\-]?){3,5}\d{1,4}\b"), "[IBAN]"),
        # Tarjetas de crédito (13-19 dígitos agrupados)
        (re.compile(r"\b(?:\d{4}[\s\-]?){3}\d{1,4}\b"), "[TARJETA]"),
        # Correos electrónicos
        (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
        # DNI / NIF español (8 dígitos + letra)
        (re.compile(r"\b\d{8}[\-\s]?[A-HJ-NP-TV-Z]\b", re.IGNORECASE), "[DNI]"),
        # NIE español (X/Y/Z + 7 dígitos + letra)
        (re.compile(r"\b[XYZ][\-\s]?\d{7}[\-\s]?[A-HJ-NP-TV-Z]\b", re.IGNORECASE), "[NIE]"),
        # CIF español (Letra + 7 dígitos + dígito/letra control)
        (re.compile(r"\b[ABCDEFGHJKLMNPQRSUVW][\-\s]?\d{7}[\-\s]?[0-9A-J]\b", re.IGNORECASE), "[CIF]"),
        # Teléfonos españoles o con prefijo internacional
        (re.compile(r"(?:\+34[\s\-]?)?\b[6789]\d{2}[\s\-]?\d{2,3}[\s\-]?\d{2,3}\b"), "[TELÉFONO]"),
    ]

    def __init__(self, runtime: Optional[LlamaRuntimeManager] = None):
        self.runtime = runtime or LlamaRuntimeManager.get_instance()

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
        # Paso 1: Capa determinista (elimina identificadores exactos al instante)
        pre_masked = self.anonymize_regex_only(text, mask_style=mask_style)

        if not use_llm or not pre_masked.strip():
            return pre_masked

        # Paso 2: Capa semántica (nombres propios, direcciones postales, cargos, empresas)
        if progress_cb:
            progress_cb("Analizando entidades y nombres personales con IA local...")

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

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": pre_masked},
        ]

        return self.runtime.chat_completion(
            messages=messages,
            max_tokens=max(2048, len(pre_masked) + 512),
            temperature=0.1,
            with_vision=False,
            progress_cb=progress_cb,
        )
