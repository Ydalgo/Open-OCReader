"""
Árbol de Nodos Documental (AST de documentos), Compresión BPE y Búsqueda Híbrida BM25+RRF.
Inspirado en la arquitectura de contexto de GuarIdA (ADR 0009 / ADR 0012):
  - Descompone documentos largos en una jerarquía de nodos (DOCUMENTO -> CAPITULO -> SECCION -> PARRAFO).
  - Poda el contexto enviando únicamente el esqueleto padre + nodos relevantes minificados para BPE.
  - Reduce drásticamente el consumo de tokens y evita desbordamientos de n_ctx en llama-server.
"""

from dataclasses import dataclass, field
from enum import Enum
import math
import re
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple
import unicodedata
import numpy as np


_RE_WORDS = re.compile(r"[a-zA-Z0-9_áéíóúÁÉÍÓÚñÑüÜ]{2,}")
_RE_HEADING_NUM = re.compile(
    r"^(?:(?:CAP[ÍI]TULO|T[ÍI]TULO|SECCI[ÓO]N|ART[ÍI]CULO|ANEXO|CL[ÁA]USULA|TEMA|PARTE)\s+[0-9IVXLCDM]+|"
    r"\d+(?:\.\d+){0,3}[\.\)\-\s]+[A-ZÁÉÍÓÚÑ])",
    re.IGNORECASE,
)
_RE_DECORATIVE = re.compile(r"^[\*\-=_~#•·\.]{5,}$")


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def tokenizar_texto(texto: str) -> List[str]:
    return [_normalize(w) for w in _RE_WORDS.findall(texto)]


def minificar_texto_bpe(texto: str) -> str:
    """
    Comprime texto documental para tokenizadores BPE sin perder semántica:
    elimina líneas decorativas repetitivas (****, ----), espacios duplicados y
    saltos de línea excesivos.
    """
    lineas_out: List[str] = []
    for raw in texto.splitlines():
        line = re.sub(r"[ \t]{2,}", " ", raw.strip())
        if not line:
            continue
        if _RE_DECORATIVE.match(line):
            continue
        lineas_out.append(line)
    return "\n".join(lineas_out)


class TipoNodoDoc(str, Enum):
    DOCUMENTO = "documento"
    CAPITULO = "capitulo"
    SECCION = "seccion"
    PARRAFO = "parrafo"


@dataclass
class NodoDocumento:
    """Nodo estructural del árbol AST de un documento (con soporte vectorial opcional)."""
    id_nodo: str
    tipo: TipoNodoDoc
    titulo: str
    contenido: str
    orden: int = 0
    padre_id: Optional[str] = None
    hijos_ids: List[str] = field(default_factory=list)
    simbolos: Set[str] = field(default_factory=set)
    embedding: Optional[List[float]] = None

    def to_dict(self) -> Dict[str, object]:
        d: Dict[str, object] = {
            "id_nodo": self.id_nodo,
            "tipo": self.tipo.value,
            "titulo": self.titulo,
            "contenido": self.contenido,
            "orden": self.orden,
            "padre_id": self.padre_id,
            "hijos_ids": list(self.hijos_ids),
        }
        if self.embedding:
            # Redondear a 5 decimales para compresión zstd/zlib aún más compacta
            d["embedding"] = [round(float(x), 5) for x in self.embedding]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "NodoDocumento":
        contenido = str(data.get("contenido", ""))
        titulo = str(data.get("titulo", ""))
        emb = data.get("embedding")
        return cls(
            id_nodo=str(data["id_nodo"]),
            tipo=TipoNodoDoc(str(data["tipo"])),
            titulo=titulo,
            contenido=contenido,
            orden=int(data.get("orden", 0)),
            padre_id=data.get("padre_id"),
            hijos_ids=list(data.get("hijos_ids", [])),
            simbolos=set(tokenizar_texto(f"{titulo} {contenido}")),
            embedding=list(emb) if isinstance(emb, list) and emb else None,
        )


class IndiceBM25Doc:
    """Índice invertido BM25Okapi puro en memoria RAM (<1 ms por consulta)."""

    def __init__(self, corpus: Sequence[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.corpus_size = len(corpus)
        self.tokens_doc = [tokenizar_texto(doc) for doc in corpus]
        self.doc_lens = [len(t) for t in self.tokens_doc]
        self.avgdl = sum(self.doc_lens) / max(1, self.corpus_size)

        self.df: Dict[str, int] = {}
        self.tf: List[Dict[str, int]] = []
        for tokens in self.tokens_doc:
            counts: Dict[str, int] = {}
            for tok in tokens:
                counts[tok] = counts.get(tok, 0) + 1
            self.tf.append(counts)
            for tok in counts:
                self.df[tok] = self.df.get(tok, 0) + 1

        self.idf: Dict[str, float] = {
            tok: math.log(1.0 + (self.corpus_size - freq + 0.5) / (freq + 0.5))
            for tok, freq in self.df.items()
        }

    def consultar(self, consulta: str, top_k: int = 10) -> List[Tuple[int, float]]:
        if self.corpus_size == 0:
            return []
        tokens_q = tokenizar_texto(consulta)
        if not tokens_q:
            return []

        scores = [0.0] * self.corpus_size
        for tok in tokens_q:
            idf = self.idf.get(tok, 0.0)
            if idf <= 0.0:
                continue
            for idx, counts in enumerate(self.tf):
                f = counts.get(tok, 0)
                if f > 0:
                    dl = self.doc_lens[idx]
                    denom = f + self.k1 * (1.0 - self.b + self.b * (dl / self.avgdl))
                    scores[idx] += idf * (f * (self.k1 + 1.0)) / max(1e-6, denom)

        ranked = [(i, s) for i, s in enumerate(scores) if s > 0.0]
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked[:top_k]


class ArbolNodosDocumento:
    """
    Árbol jerárquico de nodos documentales con búsqueda BM25 + RRF y poda de contexto BPE.
    """

    def __init__(self, titulo: str = "Documento") -> None:
        self.titulo = titulo
        self.nodos: Dict[str, NodoDocumento] = {}
        self._bm25: Optional[IndiceBM25Doc] = None
        self._hojas_ordenadas: List[NodoDocumento] = []

    def agregar_nodo(self, nodo: NodoDocumento) -> None:
        self.nodos[nodo.id_nodo] = nodo
        if nodo.padre_id and nodo.padre_id in self.nodos:
            padre = self.nodos[nodo.padre_id]
            if nodo.id_nodo not in padre.hijos_ids:
                padre.hijos_ids.append(nodo.id_nodo)

    @staticmethod
    def _es_encabezado(linea: str) -> Optional[TipoNodoDoc]:
        s = linea.strip()
        if not s or len(s) > 120:
            return None
        if s.startswith("# "):
            return TipoNodoDoc.CAPITULO
        if s.startswith(("## ", "### ")):
            return TipoNodoDoc.SECCION
        if _RE_HEADING_NUM.match(s):
            if re.match(r"^(?:CAP[ÍI]TULO|T[ÍI]TULO|PARTE|ANEXO)\b", s, re.IGNORECASE):
                return TipoNodoDoc.CAPITULO
            return TipoNodoDoc.SECCION
        # Línea corta en MAYÚSCULAS (típico encabezado de documento oficial/contrato)
        letters = [c for c in s if c.isalpha()]
        if 4 <= len(letters) <= 70 and sum(1 for c in letters if c.isupper()) / len(letters) > 0.85:
            return TipoNodoDoc.SECCION
        return None

    @classmethod
    def construir_desde_texto(
        cls,
        texto: str,
        titulo: str = "Documento",
        max_chars_hoja: int = 1600,
    ) -> "ArbolNodosDocumento":
        """Parsea texto completo en un árbol AST documental (DOCUMENTO -> CAPITULO -> SECCION -> PARRAFO)."""
        arbol = cls(titulo=titulo)
        raiz_id = "doc::raiz"
        arbol.agregar_nodo(
            NodoDocumento(
                id_nodo=raiz_id,
                tipo=TipoNodoDoc.DOCUMENTO,
                titulo=titulo,
                contenido="",
                orden=0,
            )
        )

        current_cap_id = raiz_id
        current_sec_id = raiz_id
        buffer_lines: List[str] = []
        orden = 1

        def flush_buffer():
            nonlocal orden
            raw = "\n".join(buffer_lines).strip()
            buffer_lines.clear()
            if not raw:
                return
            # Subdividir bloques excesivamente largos respetando saltos de línea
            pos = 0
            while pos < len(raw):
                end = min(pos + max_chars_hoja, len(raw))
                if end < len(raw):
                    cut = raw.rfind("\n", pos + max_chars_hoja // 2, end)
                    if cut == -1:
                        cut = raw.rfind(" ", pos + max_chars_hoja // 2, end)
                    if cut > pos:
                        end = cut
                frag = raw[pos:end].strip()
                if frag:
                    nid = f"nodo::{orden}"
                    padre = arbol.nodos.get(current_sec_id)
                    lbl = padre.titulo if padre and padre.id_nodo != raiz_id else f"Bloque {orden}"
                    arbol.agregar_nodo(
                        NodoDocumento(
                            id_nodo=nid,
                            tipo=TipoNodoDoc.PARRAFO,
                            titulo=lbl,
                            contenido=frag,
                            orden=orden,
                            padre_id=current_sec_id,
                            simbolos=set(tokenizar_texto(f"{lbl} {frag}")),
                        )
                    )
                    orden += 1
                pos = end

        for linea in texto.splitlines():
            tipo_h = cls._es_encabezado(linea)
            if tipo_h is not None:
                flush_buffer()
                clean_title = linea.strip().lstrip("#").strip()
                nid = f"nodo::{orden}"
                if tipo_h == TipoNodoDoc.CAPITULO:
                    padre_id = raiz_id
                    current_cap_id = nid
                    current_sec_id = nid
                else:
                    padre_id = current_cap_id
                    current_sec_id = nid

                arbol.agregar_nodo(
                    NodoDocumento(
                        id_nodo=nid,
                        tipo=tipo_h,
                        titulo=clean_title,
                        contenido=clean_title,
                        orden=orden,
                        padre_id=padre_id,
                        simbolos=set(tokenizar_texto(clean_title)),
                    )
                )
                orden += 1
            else:
                buffer_lines.append(linea)
                if sum(len(x) + 1 for x in buffer_lines) >= max_chars_hoja:
                    flush_buffer()

        flush_buffer()
        arbol._reconstruir_indice()
        return arbol

    def _reconstruir_indice(self) -> None:
        self._hojas_ordenadas = sorted(
            [n for n in self.nodos.values() if n.tipo == TipoNodoDoc.PARRAFO and n.contenido.strip()],
            key=lambda n: n.orden,
        )
        corpus = [f"{n.titulo}\n{n.contenido}" for n in self._hojas_ordenadas]
        self._bm25 = IndiceBM25Doc(corpus)
        self._reconstruir_matriz_vectorial()

    def _reconstruir_matriz_vectorial(self) -> None:
        """Construye matriz float32 normalizada en RAM para similitud coseno BLAS (<0.5 ms)."""
        vecs = []
        idxs = []
        for i, n in enumerate(self._hojas_ordenadas):
            if n.embedding:
                vecs.append(n.embedding)
                idxs.append(i)
        if vecs:
            mat = np.array(vecs, dtype=np.float32)
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            norms[norms == 0.0] = 1.0
            self._vec_matrix: Optional[np.ndarray] = mat / norms
            self._vec_indices: List[int] = idxs
        else:
            self._vec_matrix = None
            self._vec_indices = []

    @property
    def has_embeddings(self) -> bool:
        return getattr(self, "_vec_matrix", None) is not None and len(getattr(self, "_vec_indices", [])) > 0

    def indexar_embeddings(
        self,
        embed_batch_fn: Callable[[List[str]], Optional[List[List[float]]]],
    ) -> int:
        """Vectoriza los nodos hoja que aún no tengan embedding y actualiza la matriz float32."""
        pendientes = [n for n in self._hojas_ordenadas if not n.embedding]
        if not pendientes:
            self._reconstruir_matriz_vectorial()
            return len(self._vec_indices)

        textos = [f"{self._ruta_jerarquica(n)}\n{minificar_texto_bpe(n.contenido)[:1400]}" for n in pendientes]
        vectores = embed_batch_fn(textos)
        if not vectores or len(vectores) != len(pendientes):
            return 0

        for nodo, vec in zip(pendientes, vectores):
            if vec:
                nodo.embedding = vec

        self._reconstruir_matriz_vectorial()
        return len(self._vec_indices)

    def buscar_nodos_relevantes(
        self,
        consulta: str,
        top_k: int = 5,
        vector_consulta: Optional[List[float]] = None,
    ) -> List[Tuple[NodoDocumento, float]]:
        """
        Recupera los nodos más relevantes mediante Fusión Híbrida RRF real:
          - Ranking denso vectorial (coseno BLAS float32) si hay embeddings activos.
          - Ranking léxico BM25Okapi.
          - Impulso estructural por coincidencia de títulos/símbolos.
        """
        if not self._hojas_ordenadas:
            return []
        if self._bm25 is None:
            self._reconstruir_indice()

        tokens_q = set(tokenizar_texto(consulta))
        rrf_scores: Dict[int, float] = {i: 0.0 for i in range(len(self._hojas_ordenadas))}
        k_rrf = 60.0

        # 1. Ranking Léxico BM25
        if self._bm25 is not None:
            for rank, (idx, _sc) in enumerate(self._bm25.consultar(consulta, top_k=top_k * 4), start=1):
                rrf_scores[idx] += 1.0 / (k_rrf + rank)

        # 2. Ranking Denso Vectorial (si hay embeddings cacheados + vector de consulta)
        if vector_consulta and self.has_embeddings and self._vec_matrix is not None:
            q = np.array(vector_consulta, dtype=np.float32)
            nq = float(np.linalg.norm(q))
            if nq > 0.0 and q.shape[0] == self._vec_matrix.shape[1]:
                q = q / nq
                sims = np.dot(self._vec_matrix, q)
                order = np.argsort(-sims)[: top_k * 4]
                for rank, pos in enumerate(order, start=1):
                    orig_idx = self._vec_indices[int(pos)]
                    rrf_scores[orig_idx] += 1.35 / (k_rrf + rank)

        # 3. Boost estructural por coincidencia en título del nodo o de su sección padre
        for idx, nodo in enumerate(self._hojas_ordenadas):
            if tokens_q:
                solap = len(tokens_q & nodo.simbolos)
                if solap > 0:
                    rrf_scores[idx] += min(0.025, 0.004 * solap)
                titulo_tokens = set(tokenizar_texto(nodo.titulo))
                if tokens_q & titulo_tokens:
                    rrf_scores[idx] += 0.015
            if idx == 0:
                rrf_scores[idx] += 0.003

        ranked = [(self._hojas_ordenadas[i], sc) for i, sc in rrf_scores.items() if sc > 0.0]
        ranked.sort(key=lambda x: (-x[1], x[0].orden))
        return ranked[:top_k]

    def construir_contexto_optimo(
        self,
        nodos_relevantes: List[Tuple[NodoDocumento, float]],
        max_chars: int = 9000,
        comprimir_bpe: bool = True,
    ) -> str:
        """
        Ensambla un contexto ultra-compacto combinando:
          - Esqueleto jerárquico (Capítulo -> Sección padre)
          - Contenido podado y minificado para BPE en orden cronológico del documento.
        """
        # Ordenar los nodos elegidos por orden de aparición natural en el documento
        seleccion = sorted(nodos_relevantes, key=lambda x: x[0].orden)
        bloques: List[str] = []
        usados = 0

        for nodo, _score in seleccion:
            ruta_jerarquica = self._ruta_jerarquica(nodo)
            cuerpo = minificar_texto_bpe(nodo.contenido) if comprimir_bpe else nodo.contenido
            bloque = f"[{ruta_jerarquica}]\n{cuerpo}"
            if usados + len(bloque) + 6 > max_chars and bloques:
                break
            bloques.append(bloque)
            usados += len(bloque) + 6

        return "\n\n---\n\n".join(bloques)

    def _ruta_jerarquica(self, nodo: NodoDocumento) -> str:
        partes: List[str] = []
        actual: Optional[NodoDocumento] = nodo
        visitados: Set[str] = set()
        while actual is not None and actual.id_nodo not in visitados:
            visitados.add(actual.id_nodo)
            if actual.tipo != TipoNodoDoc.DOCUMENTO and actual.titulo:
                if not partes or partes[-1] != actual.titulo:
                    partes.append(actual.titulo)
            actual = self.nodos.get(actual.padre_id) if actual.padre_id else None
        partes.reverse()
        return " > ".join(partes) if partes else f"Sección {nodo.orden}"

    def obtener_bloques_para_resumen(self, max_chars_bloque: int = 10000) -> List[str]:
        """Agrupa las hojas del árbol en bloques semánticos minificados para Map-Reduce."""
        bloques: List[str] = []
        actual_parts: List[str] = []
        actual_len = 0

        for nodo in self._hojas_ordenadas:
            ruta = self._ruta_jerarquica(nodo)
            cuerpo = minificar_texto_bpe(nodo.contenido)
            pieza = f"[{ruta}]\n{cuerpo}"
            if actual_len + len(pieza) + 4 > max_chars_bloque and actual_parts:
                bloques.append("\n\n".join(actual_parts))
                actual_parts = []
                actual_len = 0
            actual_parts.append(pieza)
            actual_len += len(pieza) + 4

        if actual_parts:
            bloques.append("\n\n".join(actual_parts))
        return bloques

    def to_dict(self) -> Dict[str, object]:
        return {
            "titulo": self.titulo,
            "nodos": [n.to_dict() for n in sorted(self.nodos.values(), key=lambda x: x.orden)],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "ArbolNodosDocumento":
        arbol = cls(titulo=str(data.get("titulo", "Documento")))
        for nd in data.get("nodos", []):
            nodo = NodoDocumento.from_dict(nd)
            arbol.nodos[nodo.id_nodo] = nodo
        arbol._reconstruir_indice()
        return arbol
