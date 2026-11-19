"""
Utilidades de segmentación (chunking) y recuperación relevante para documentos largos.
Evita errores HTTP 400 por exceder el tamaño de contexto (n_ctx) de llama-server.
"""

import re
import unicodedata
from typing import List


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


_STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al",
    "a", "en", "con", "por", "para", "sobre", "entre", "sin", "que", "cual",
    "cuales", "como", "donde", "cuando", "quien", "quienes", "es", "son", "fue",
    "ser", "esta", "estan", "hay", "este", "esta", "estos", "estas", "ese",
    "esa", "y", "o", "u", "pero", "si", "no", "su", "sus", "mi", "mis", "tu",
    "the", "and", "for", "with", "that", "this", "from", "what", "which", "who",
    "where", "when", "how", "are", "was", "were", "have", "has", "had", "does",
}


def split_text_chunks(text: str, max_chars: int = 12000, overlap: int = 300) -> List[str]:
    """
    Divide un texto largo en bloques respetando saltos de párrafo o línea
    para no superar la ventana de contexto del LLM.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    start = 0
    total = len(text)

    while start < total:
        end = min(start + max_chars, total)
        if end < total:
            # Intentar cortar en un salto de párrafo o línea cerca del límite
            split_pos = text.rfind("\n\n", start + max_chars // 2, end)
            if split_pos == -1:
                split_pos = text.rfind("\n", start + max_chars // 2, end)
            if split_pos == -1:
                split_pos = text.rfind(" ", start + max_chars // 2, end)
            if split_pos > start:
                end = split_pos

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= total:
            break
        start = max(end - overlap, start + 1)

    return chunks


def select_relevant_chunks(document_text: str, question: str, max_total_chars: int = 12000) -> str:
    """
    Si el documento supera max_total_chars, selecciona los fragmentos más relevantes
    para la pregunta usando coincidencia de términos (BM25 simplificado) y los devuelve
    en orden de aparición original.
    """
    if len(document_text) <= max_total_chars:
        return document_text

    chunks = split_text_chunks(document_text, max_chars=2400, overlap=250)
    if not chunks:
        return document_text[:max_total_chars]

    q_words = [
        w for w in re.findall(r"[a-z0-9]{3,}", _normalize(question))
        if w not in _STOPWORDS
    ]

    scored = []
    for idx, chunk in enumerate(chunks):
        norm_chunk = _normalize(chunk)
        score = 0
        for w in q_words:
            count = norm_chunk.count(w)
            if count > 0:
                score += 2 + min(count, 5)
        # Ligero impulso a la primera página (título / contexto general)
        if idx == 0:
            score += 1
        scored.append((score, idx, chunk))

    # Ordenar por relevancia descendente y recoger hasta llenar presupuesto
    scored.sort(key=lambda x: (-x[0], x[1]))

    chosen = []
    used_chars = 0
    for _score, idx, chunk in scored:
        if used_chars + len(chunk) + 40 > max_total_chars and chosen:
            continue
        chosen.append((idx, chunk))
        used_chars += len(chunk) + 40
        if used_chars >= max_total_chars:
            break

    # Restaurar orden cronológico del documento
    chosen.sort(key=lambda x: x[0])
    parts = [f"[Fragmento {idx + 1}/{len(chunks)}]\n{chunk}" for idx, chunk in chosen]
    return "\n\n---\n\n".join(parts)
