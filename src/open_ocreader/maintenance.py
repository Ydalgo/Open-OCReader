"""
Utilidades de mantenimiento para Open OCReader:
Borrado seguro de logs (incluso con ficheros abiertos en Windows) y limpieza de cachés.
"""

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Dict
from .logger import get_logger, get_logs_dir

logger = get_logger("maintenance")


def clear_logs() -> Dict[str, int]:
    """
    Limpia los ficheros de log de la aplicación y de llama-server.
    En Windows los logs activos se truncan de forma segura sin romper los descriptores abiertos.
    """
    logs_dir = get_logs_dir()
    removed_files = 0
    truncated_files = 0

    for item in logs_dir.iterdir():
        if not item.is_file():
            continue
        try:
            # Eliminar rotaciones antiguas (.log.1, .log.2, etc.)
            if item.suffix in {".1", ".2", ".3", ".bak"}:
                item.unlink()
                removed_files += 1
            elif item.suffix == ".log":
                # Intentar truncar a 0 bytes (funciona incluso si está abierto por otro handler)
                with open(item, "w", encoding="utf-8") as f:
                    f.truncate(0)
                truncated_files += 1
        except Exception:
            # Si llama-server tiene bloqueo exclusivo temporal, intentar limpiar en silencio
            pass

    logger.info(f"Limpieza de logs ejecutada (truncados: {truncated_files}, eliminados: {removed_files}).")
    return {"truncated": truncated_files, "removed": removed_files}


def clear_cache() -> Dict[str, int]:
    """
    Limpia ficheros temporales (capturas del portapapeles, uploads de servidor API)
    y directorios __pycache__ del proyecto.
    """
    deleted_items = 0

    # 1. Limpiar carpeta temporal de Open OCReader (portapapeles y API)
    temp_dirs = [
        Path(tempfile.gettempdir()) / "open_ocreader",
        Path(tempfile.gettempdir()) / "open_ocreader_api",
    ]
    for td in temp_dirs:
        if td.exists():
            for child in td.iterdir():
                try:
                    if child.is_dir():
                        shutil.rmtree(child, ignore_errors=True)
                    else:
                        child.unlink(missing_ok=True)
                    deleted_items += 1
                except Exception:
                    pass

    # 2. Limpiar __pycache__ dentro de src/ si corre desde código fuente
    src_root = Path(__file__).resolve().parent.parent
    for pycache in src_root.rglob("__pycache__"):
        try:
            shutil.rmtree(pycache, ignore_errors=True)
            deleted_items += 1
        except Exception:
            pass

    logger.info(f"Limpieza de caché completada ({deleted_items} elementos eliminados).")
    return {"deleted": deleted_items}
