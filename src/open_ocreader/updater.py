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


def apply_update() -> str:
    """
    Actualiza el proyecto sin desinstalar ni borrar models/, bin/ o logs/.
    Si es un repositorio Git, usa 'git pull'. En caso contrario, descarga el código de main.zip.
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
    resp = requests.get(REPO_ZIP_URL, timeout=60)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        top_folder = zf.namelist()[0].split("/")[0]
        preserve = {"models", "bin", "logs", "dist", "build", "venv"}

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

            dest = root / rel_path
            if not is_within_directory(root, dest):
                raise SecurityError(f"Ruta peligrosa detectada en actualización (Zip-Slip): {member.filename}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src_f, open(dest, "wb") as dst_f:
                shutil.copyfileobj(src_f, dst_f)

    return "✓ Código fuente actualizado desde GitHub manteniendo intactos tus modelos y configuración."
