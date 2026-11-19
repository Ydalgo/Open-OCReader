"""
Caché persistente optimizada de documentos y árboles AST (inspirada en GuarIdA/cache.py):
  - SQLite en modo WAL (sin bloqueos en lecturas concurrentes).
  - Deduplicación por hash SHA-256 del fichero de entrada.
  - Compresión transparente con zstd (si está instalado) o zlib (~75-85% ahorro en disco).
Permite reabrir PDFs largos o escaneados en milisegundos sin repetir OCR ni re-indexar el árbol.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Generator, Optional, Tuple
import zlib
from ..logger import get_logs_dir
from .doc_tree import ArbolNodosDocumento

try:
    import zstandard as zstd
    _HAS_ZSTD = True
except ImportError:
    zstd = None
    _HAS_ZSTD = False


def _compress_blob(text: str) -> Tuple[str, bytes]:
    raw = text.encode("utf-8")
    if _HAS_ZSTD and zstd is not None:
        return "zstd", zstd.ZstdCompressor(level=3).compress(raw)
    return "zlib", zlib.compress(raw, level=6)


def _decompress_blob(algo: str, data: bytes) -> str:
    if not data:
        return ""
    if algo == "zstd" and _HAS_ZSTD and zstd is not None:
        return zstd.ZstdDecompressor().decompress(data).decode("utf-8")
    if algo == "zlib":
        return zlib.decompress(data).decode("utf-8")
    return data.decode("utf-8")


def compute_file_sha256(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class DocumentIndexCache:
    """Almacén SQLite WAL + compresión zstd/zlib para texto extraído y Árbol AST documental."""

    _instance: Optional["DocumentIndexCache"] = None

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            cache_dir = get_logs_dir().parent / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = cache_dir / "doc_ast_cache.db"
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @classmethod
    def get_instance(cls) -> "DocumentIndexCache":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @contextmanager
    def _session(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), timeout=20.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._session() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documentos_ast (
                    cache_key TEXT PRIMARY KEY,
                    file_sha256 TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    mode_key TEXT NOT NULL,
                    compresion TEXT NOT NULL,
                    texto_blob BLOB NOT NULL,
                    arbol_blob BLOB NOT NULL,
                    nodos_count INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_doc_sha ON documentos_ast(file_sha256);"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_projects (
                    name TEXT PRIMARY KEY,
                    files_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def save_project(self, name: str, file_paths: list) -> None:
        """Guarda un proyecto/sesión de chat con la ruta y el SHA-256 de cada archivo."""
        entries = []
        for fp in file_paths:
            p = Path(fp)
            if p.exists():
                entries.append({
                    "path": str(p.resolve()),
                    "name": p.name,
                    "sha256": compute_file_sha256(str(p)),
                })
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO chat_projects (name, files_json, updated_at) VALUES (?, ?, ?)",
                (name.strip(), json.dumps(entries, ensure_ascii=False), now_iso),
            )

    def list_projects(self) -> list:
        """Devuelve la lista de proyectos guardados [(name, num_files, updated_at), ...]."""
        try:
            with self._session() as conn:
                rows = conn.execute(
                    "SELECT name, files_json, updated_at FROM chat_projects ORDER BY updated_at DESC"
                ).fetchall()
            out = []
            for r in rows:
                files = json.loads(r["files_json"])
                out.append((r["name"], len(files), r["updated_at"]))
            return out
        except Exception:
            return []

    def load_project(self, name: str) -> Optional[list]:
        """Carga las entradas [{path, name, sha256}] de un proyecto guardado."""
        try:
            with self._session() as conn:
                row = conn.execute(
                    "SELECT files_json FROM chat_projects WHERE name = ?",
                    (name,),
                ).fetchone()
            return json.loads(row["files_json"]) if row else None
        except Exception:
            return None

    def delete_project(self, name: str) -> None:
        with self._session() as conn:
            conn.execute("DELETE FROM chat_projects WHERE name = ?", (name,))

    def get(
        self,
        file_path: str,
        mode_key: str = "smart",
    ) -> Optional[Tuple[str, ArbolNodosDocumento]]:
        """Recupera (texto_completo, ArbolNodosDocumento) en milisegundos si el SHA-256 ya está en caché."""
        try:
            sha = compute_file_sha256(file_path)
            ckey = f"{sha}:{mode_key}"
            with self._session() as conn:
                row = conn.execute(
                    "SELECT compresion, texto_blob, arbol_blob FROM documentos_ast WHERE cache_key = ?",
                    (ckey,),
                ).fetchone()
                if row is None:
                    return None
                algo = row["compresion"]
                texto = _decompress_blob(algo, row["texto_blob"])
                arbol_json = _decompress_blob(algo, row["arbol_blob"])
                arbol = ArbolNodosDocumento.from_dict(json.loads(arbol_json))
                return texto, arbol
        except Exception:
            return None

    def put(
        self,
        file_path: str,
        texto: str,
        arbol: ArbolNodosDocumento,
        mode_key: str = "smart",
    ) -> None:
        """Guarda texto y árbol AST comprimidos con zstd/zlib indexados por SHA-256."""
        try:
            sha = compute_file_sha256(file_path)
            ckey = f"{sha}:{mode_key}"
            algo_t, texto_blob = _compress_blob(texto)
            _algo_a, arbol_blob = _compress_blob(json.dumps(arbol.to_dict(), ensure_ascii=False))
            now_iso = datetime.now(timezone.utc).isoformat()
            with self._session() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO documentos_ast
                    (cache_key, file_sha256, file_name, mode_key, compresion, texto_blob, arbol_blob, nodos_count, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ckey,
                        sha,
                        Path(file_path).name,
                        mode_key,
                        algo_t,
                        texto_blob,
                        arbol_blob,
                        len(arbol.nodos),
                        now_iso,
                    ),
                )
        except Exception:
            pass

    def clear(self) -> int:
        """Vacía la caché persistente de documentos AST."""
        try:
            with self._session() as conn:
                cur = conn.execute("DELETE FROM documentos_ast;")
                deleted = cur.rowcount or 0
            with self._session() as conn:
                conn.execute("VACUUM;")
            return deleted
        except Exception:
            return 0
