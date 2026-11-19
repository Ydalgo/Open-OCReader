"""
Resolución de rutas multiusuario y compatible con instalaciones en C:\\Program Files\\ (MSI)
así como modo portable (USB / carpeta local) y código fuente.

Regla de permisos en Windows:
  - Modo portable / desarrollo (carpeta escribible): usa <base_dir>/{bin,models,logs,cache}.
  - Modo instalado vía MSI (C:\\Program Files\\Open OCReader\\, solo lectura para usuarios estándar):
      * Datos compartidos de solo lectura (bin/, models/): busca primero en C:\\ProgramData\\Open OCReader\\
        (donde el instalador MSI aprovisiona desde offline_repo\\ según el hardware) y si el usuario
        descarga modelos nuevos sin privilegios de administrador, usa %LOCALAPPDATA%\\Open OCReader\\.
      * Datos escribibles por usuario (logs/, cache/): siempre en %LOCALAPPDATA%\\Open OCReader\\.
  - Variable de entorno OPEN_OCREADER_DATA_DIR: permite a un administrador fijar una ruta personalizada.
"""

import os
import sys
from pathlib import Path


def _is_dir_writable(directory: Path) -> bool:
    """Comprueba de forma segura si el usuario actual tiene permiso de escritura en un directorio."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".write_test_{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def get_app_base_dir() -> Path:
    """Devuelve la carpeta raíz donde reside el ejecutable o el repositorio fuente."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def get_user_data_dir() -> Path:
    """
    Devuelve el directorio escribible para datos de usuario (logs, cache, descargas sin admin).
    Funciona para cualquier usuario estándar de Windows independientemente de sus permisos.
    """
    env_dir = os.environ.get("OPEN_OCREADER_DATA_DIR", "").strip()
    if env_dir:
        p = Path(env_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    base = get_app_base_dir()
    if _is_dir_writable(base):
        return base

    # Instalación en Program Files u otra ruta de solo lectura -> usar carpeta del usuario
    if sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        user_dir = Path(local_app) / "Open OCReader"
    elif sys.platform == "darwin":
        user_dir = Path.home() / "Library" / "Application Support" / "Open OCReader"
    else:
        xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        user_dir = Path(xdg) / "open-ocreader"

    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def get_shared_programdata_dir() -> Path:
    """Carpeta compartida de máquina donde el instalador MSI deposita bin/ y models/ para todos los usuarios."""
    if sys.platform == "win32":
        prog_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return Path(prog_data) / "Open OCReader"
    return Path("/var/lib/open-ocreader")


def resolve_asset_dir(folder_name: str) -> Path:
    """
    Resuelve la ruta efectiva de 'bin' o 'models' con compatibilidad total:
      1. OPEN_OCREADER_DATA_DIR/<folder_name> (si existe variable de entorno).
      2. <app_base_dir>/<folder_name> si existe y contiene ficheros (modo portable / dev).
      3. <ProgramData>/Open OCReader/<folder_name> si el instalador MSI lo aprovisionó para todos los usuarios.
      4. <user_data_dir>/<folder_name> (siempre escribible para descargas bajo demanda sin permisos admin).
    """
    env_dir = os.environ.get("OPEN_OCREADER_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir) / folder_name

    base = get_app_base_dir()
    local_candidate = base / folder_name
    if local_candidate.exists() and any(local_candidate.iterdir()):
        return local_candidate

    # Soporte para ejecutar desde dist/Open_OCReader/ en desarrollo
    parent_candidate = base.parent.parent / folder_name
    if not getattr(sys, "frozen", False) and parent_candidate.exists() and any(parent_candidate.iterdir()):
        return parent_candidate

    shared_candidate = get_shared_programdata_dir() / folder_name
    if shared_candidate.exists() and any(shared_candidate.iterdir()):
        return shared_candidate

    # Si el directorio base es escribible (modo portable/dev), usar <base>/<folder_name>
    if _is_dir_writable(base):
        return local_candidate

    # En instalación MSI de solo lectura sin aprovisionamiento previo -> %LOCALAPPDATA%\Open OCReader
    return get_user_data_dir() / folder_name
