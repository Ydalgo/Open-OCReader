"""
Sistema de comprobación y actualización in-place desde GitHub (Ydalgo/Open-OCReader).
Permite actualizar el código sin desinstalar ni perder los modelos (models/) o binarios (bin/).
"""

import io
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
import requests
from .logger import get_logger
from .security import SecurityError, is_within_directory

logger = get_logger("updater")

MAX_UPDATE_SIZE = 50 * 1024 * 1024  # 50 MB límite de descarga de código fuente
BLOCKED_UPDATE_EXTENSIONS = {".exe", ".dll", ".so", ".dylib", ".pyd", ".bin", ".com", ".scr"}

REPO_RAW_INIT = "https://raw.githubusercontent.com/Ydalgo/Open-OCReader/main/src/open_ocreader/__init__.py"
REPO_ZIP_URL = "https://github.com/Ydalgo/Open-OCReader/archive/refs/heads/main.zip"


@dataclass
class UpdateInfo:
    current_version: str
    remote_version: str
    update_available: bool
    message: str


def _parse_version(ver_str: str) -> Tuple[int, ...]:
    nums = re.findall(r"\d+", ver_str)
    return tuple(int(n) for n in nums) if nums else (0,)


def get_project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def check_for_updates(current_version: str) -> UpdateInfo:
    """Consulta la versión actual en la rama main de GitHub y la compara con la local."""
    try:
        resp = requests.get(REPO_RAW_INIT, timeout=10)
        resp.raise_for_status()
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', resp.text)
        if not match:
            return UpdateInfo(
                current_version=current_version,
                remote_version="desconocida",
                update_available=False,
                message="No se pudo leer el número de versión remoto en GitHub.",
            )

        remote_ver = match.group(1)
        is_newer = _parse_version(remote_ver) > _parse_version(current_version)
        msg = (
            f"¡Nueva versión disponible: v{remote_ver} (tienes v{current_version})!"
            if is_newer
            else f"Ya tienes la última versión instalada (v{current_version})."
        )
        return UpdateInfo(
            current_version=current_version,
            remote_version=remote_ver,
            update_available=is_newer,
            message=msg,
        )
    except Exception as e:
        logger.warning(f"Error consultando actualizaciones en GitHub: {e}")
        return UpdateInfo(
            current_version=current_version,
            remote_version="error",
            update_available=False,
            message=f"No se pudo conectar con GitHub: {e}",
        )


def apply_update(expected_sha256: Optional[str] = None) -> str:
    """
    Actualiza el proyecto sin desinstalar ni borrar models/, bin/ o logs/.
    Si es un repositorio Git, usa 'git pull'. En caso contrario, descarga el código de main.zip
    validando límites de tamaño, integridad y sanitización estricta.
    """
    root = get_project_root()

    # Caso 1: Existe .git (instalación desde código fuente con Git)
    if (root / ".git").exists() and shutil.which("git"):
        logger.info("Actualizando mediante 'git pull origin main'...")
        proc = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Error al ejecutar git pull:\n{proc.stderr}")
        return f"✓ Repositorio actualizado con Git:\n{proc.stdout.strip()}"

    # Caso 2: Instalación sin .git (descarga limpia de src/, scripts/, docs/, README.md, requirements.txt)
    if getattr(sys, "frozen", False):
        return (
            "Estás ejecutando la versión compilada (.exe). "
            "Para actualizar el binario, descarga la última compilación o ejecuta scripts/windows/compilar.bat "
            "sobre el código fuente actualizado."
        )

    logger.info("Descargando paquete de actualización desde GitHub...")
    resp = requests.get(REPO_ZIP_URL, timeout=60, stream=True)
    resp.raise_for_status()

    # Proteger contra DoS por descargas gigantes (Content-Length y streaming)
    content_length = resp.headers.get("Content-Length")
    if content_length and int(content_length) > MAX_UPDATE_SIZE:
        raise SecurityError(
            f"El paquete de actualización supera el límite máximo permitido ({MAX_UPDATE_SIZE // (1024**2)} MB)."
        )

    buf = io.BytesIO()
    total_bytes = 0
    for chunk in resp.iter_content(chunk_size=128 * 1024):
        total_bytes += len(chunk)
        if total_bytes > MAX_UPDATE_SIZE:
            raise SecurityError(
                f"La descarga del paquete de actualización superó los {MAX_UPDATE_SIZE // (1024**2)} MB permitidos."
            )
        buf.write(chunk)

    payload = buf.getvalue()
    if expected_sha256:
        import hashlib
        import hmac
        actual_hash = hashlib.sha256(payload).hexdigest().lower()
        clean_exp = expected_sha256.lower().removeprefix("sha256:")
        if not hmac.compare_digest(actual_hash, clean_exp):
            raise SecurityError(
                f"Firma SHA-256 no válida para la actualización. Esperado: {clean_exp}, Obtenido: {actual_hash}"
            )

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        top_folder = zf.namelist()[0].split("/")[0]
        preserve = {"models", "bin", "logs", "dist", "build", "venv", "cache", "projects"}

        for member in zf.infolist():
            if member.is_dir():
                continue
            mode = (member.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise SecurityError(f"Enlace simbólico bloqueado en paquete de actualización: {member.filename}")
            rel_path = member.filename[len(top_folder) + 1 :]
            if not rel_path:
                continue
            first_part = rel_path.split("/")[0]
            if first_part in preserve:
                continue

            # Bloquear la inyección de ejecutables o librerías nativas arbitrarias mediante el zip
            member_suffix = Path(rel_path).suffix.lower()
            if member_suffix in BLOCKED_UPDATE_EXTENSIONS:
                raise SecurityError(
                    f"Archivo ejecutable no permitido en actualización de código: {member.filename}"
                )

            dest = root / rel_path
            if not is_within_directory(root, dest):
                raise SecurityError(f"Ruta peligrosa detectada en actualización (Zip-Slip): {member.filename}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src_f, open(dest, "wb") as dst_f:
                shutil.copyfileobj(src_f, dst_f)

    return "✓ Código fuente actualizado desde GitHub manteniendo intactos tus modelos y configuración."
