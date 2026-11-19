"""
Utilidades de seguridad centralizadas de Open OCReader.

- Extracción segura de ZIP/TAR (evita Zip-Slip / Tar-Slip, enlaces simbólicos y bombas).
- Verificación de integridad SHA-256 de descargas.
- Directorios temporales privados (evita ataques de enlaces simbólicos en /tmp).
- Saneado de celdas de hoja de cálculo (evita inyección de fórmulas CSV/Excel).
- Validación de ficheros de entrada (extensión, tamaño y firma mágica).
"""

import hashlib
import hmac
import os
import secrets
import stat
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable, Optional

# Límites defensivos
MAX_ARCHIVE_TOTAL_BYTES = 2 * 1024**3        # 2 GB descomprimidos como máximo por paquete
MAX_ARCHIVE_MEMBERS = 5000
MAX_INPUT_FILE_BYTES = 100 * 1024**2          # 100 MB por documento de entrada
MAX_PDF_PAGES = 300
MAX_IMAGE_PIXELS = 80_000_000                 # ~80 MP por página (antibombas de descompresión)

ALLOWED_INPUT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

# Firmas mágicas de los formatos admitidos
_MAGIC_SIGNATURES = (
    b"%PDF-",
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"II*\x00",
    b"MM\x00*",
    b"BM",
    b"RIFF",
)


class SecurityError(Exception):
    """Error lanzado cuando una comprobación de seguridad falla."""


# ---------------------------------------------------------------- Integridad
def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_sha256(path: Path, expected: Optional[str]) -> None:
    """Verifica el hash SHA-256 de un fichero. Lanza SecurityError si no coincide."""
    if not expected:
        raise SecurityError(f"No hay hash de referencia para verificar '{path.name}'. Descarga rechazada.")
    expected = expected.lower().removeprefix("sha256:")
    actual = sha256_file(path)
    if not hmac.compare_digest(actual, expected):
        try:
            path.unlink()
        except OSError:
            pass
        raise SecurityError(
            f"Integridad comprometida en '{path.name}': SHA-256 esperado {expected}, obtenido {actual}. "
            "El fichero ha sido eliminado."
        )


# ---------------------------------------------------------------- Rutas seguras
def is_within_directory(base: Path, target: Path) -> bool:
    base = base.resolve()
    try:
        target.resolve().relative_to(base)
        return True
    except ValueError:
        return False


def safe_extract_zip(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "r") as zf:
        members = zf.infolist()
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise SecurityError("El paquete contiene demasiados ficheros.")
        total = sum(m.file_size for m in members)
        if total > MAX_ARCHIVE_TOTAL_BYTES:
            raise SecurityError("El paquete descomprimido supera el tamaño máximo permitido.")
        for m in members:
            # Rechazar enlaces simbólicos dentro del zip
            mode = (m.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise SecurityError(f"Enlace simbólico no permitido en el paquete: {m.filename}")
            target = dest / m.filename
            if not is_within_directory(dest, target):
                raise SecurityError(f"Ruta peligrosa detectada en el paquete (Zip-Slip): {m.filename}")
        zf.extractall(dest)


def safe_extract_tar(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:*") as tf:
        members = tf.getmembers()
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise SecurityError("El paquete contiene demasiados ficheros.")
        total = 0
        for m in members:
            if m.isdev():
                raise SecurityError(f"Dispositivo no permitido en el paquete: {m.name}")
            if m.issym() or m.islnk():
                link_target = (dest / m.name).parent / m.linkname
                if not is_within_directory(dest, link_target):
                    raise SecurityError(f"Enlace que escapa del destino: {m.name} -> {m.linkname}")
            if not is_within_directory(dest, dest / m.name):
                raise SecurityError(f"Ruta peligrosa detectada en el paquete (Tar-Slip): {m.name}")
            total += max(m.size, 0)
        if total > MAX_ARCHIVE_TOTAL_BYTES:
            raise SecurityError("El paquete descomprimido supera el tamaño máximo permitido.")
        try:
            tf.extractall(dest, filter="data")  # Python >= 3.12 / parches de seguridad
        except TypeError:
            tf.extractall(dest)


# ---------------------------------------------------------------- Temporales
def private_temp_dir(prefix: str = "open_ocreader_") -> Path:
    """Crea un directorio temporal único con permisos 0700 (no predecible)."""
    return Path(tempfile.mkdtemp(prefix=prefix))


def write_private_secret_file(content: str, prefix: str = "ocr_key_") -> Path:
    """Escribe un secreto en un fichero temporal accesible solo por el usuario actual."""
    fd, path = tempfile.mkstemp(prefix=prefix, text=True)
    try:
        os.write(fd, content.encode("utf-8"))
    finally:
        os.close(fd)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return Path(path)


def generate_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# ---------------------------------------------------------------- Validación de entradas
def validate_input_file(path: Path, max_bytes: int = MAX_INPUT_FILE_BYTES) -> None:
    """Comprueba extensión, tamaño y firma mágica de un documento de entrada."""
    if not path.is_file():
        raise SecurityError(f"El fichero no existe o no es un fichero regular: {path.name}")
    ext = path.suffix.lower()
    if ext not in ALLOWED_INPUT_EXTENSIONS:
        raise SecurityError(
            f"Extensión '{ext}' no permitida. Válidas: {', '.join(sorted(ALLOWED_INPUT_EXTENSIONS))}"
        )
    size = path.stat().st_size
    if size == 0:
        raise SecurityError("El fichero está vacío.")
    if size > max_bytes:
        raise SecurityError(f"El fichero supera el tamaño máximo permitido ({max_bytes // (1024**2)} MB).")
    with open(path, "rb") as f:
        head = f.read(16)
    if not any(head.startswith(sig) for sig in _MAGIC_SIGNATURES):
        raise SecurityError("El contenido del fichero no corresponde a un PDF o imagen válidos.")


def sanitize_filename(name: str, default: str = "documento") -> str:
    """Devuelve un nombre de fichero seguro (sin rutas, sin caracteres de control)."""
    base = Path(name or default).name
    cleaned = "".join(c for c in base if c.isalnum() or c in "._- ").strip(" .")
    return cleaned[:150] or default


# ---------------------------------------------------------------- Hojas de cálculo
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def sanitize_spreadsheet_text(value: str) -> str:
    """Neutraliza la inyección de fórmulas (CSV/Excel injection) anteponiendo un apóstrofo."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def iter_safe_lines(lines: Iterable[str], max_chars: int = 200_000) -> str:
    """Une líneas limitando el tamaño total (evita prompts gigantes contra el LLM)."""
    out, total = [], 0
    for line in lines:
        total += len(line) + 1
        if total > max_chars:
            break
        out.append(line)
    return "\n".join(out)
