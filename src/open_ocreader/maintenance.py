"""
Utilidades de mantenimiento para Open OCReader:
Borrado seguro de logs (incluso con ficheros abiertos en Windows) y limpieza de cachés.
"""

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict
from .logger import get_logger, get_logs_dir, is_log_deletion_locked

logger = get_logger("maintenance")


def clear_logs() -> Dict[str, int]:
    """
    Limpia los ficheros de log de la aplicación y de llama-server.
    En modo auditoría ENS (OPEN_OCREADER_LOCK_LOGS=1) el borrado está bloqueado.
    """
    if is_log_deletion_locked():
        logger.warning("Intento de borrado de logs bloqueado por política ENS (OPEN_OCREADER_LOCK_LOGS=1).")
        raise PermissionError("El borrado de logs está deshabilitado por política de auditoría ENS.")
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


def clean_and_reinstall(
    clean_builds: bool = True,
    reinstall_llama: bool = True,
    reinstall_models: bool = False,
    upgrade_deps: bool = True,
    progress_cb=None,
) -> Dict[str, Any]:
    """
    Limpia restos antiguos del proyecto (build/, dist/, *.spec, cachés) y
    reinstala/actualiza los componentes seleccionados (llama.cpp, dependencias, modelos).
    """
    import subprocess
    import sys
    from .ai.runtime_manager import LlamaRuntimeManager

    def notify(msg: str):
        logger.info(msg)
        if progress_cb:
            progress_cb(msg)

    rt = LlamaRuntimeManager.get_instance()
    rt.stop_server()
    root = rt.base_dir
    summary: Dict[str, Any] = {"removed": [], "updated": []}

    # 1. Limpiar cachés
    notify("Limpiando cachés y temporales...")
    clear_cache()

    # 2. Limpiar compilaciones antiguas (build/, dist/, *.spec) — solo si no estamos corriendo desde dentro de dist/
    if clean_builds and not getattr(sys, "frozen", False):
        notify("Eliminando compilaciones antiguas (build/, dist/, *.spec)...")
        for folder_name in ("build", "dist"):
            target = root / folder_name
            if target.exists():
                try:
                    shutil.rmtree(target)
                    summary["removed"].append(folder_name + "/")
                except Exception as e:
                    logger.warning(f"No se pudo borrar {target}: {e}")
        for spec_f in root.glob("*.spec"):
            try:
                spec_f.unlink()
                summary["removed"].append(spec_f.name)
            except Exception:
                pass

    # 3. Reinstalar/Actualizar binarios de llama.cpp (bin/)
    if reinstall_llama:
        notify("Limpiando binarios antiguos de llama.cpp y descargando la última versión oficial...")
        if rt.bin_root.exists():
            shutil.rmtree(rt.bin_root, ignore_errors=True)
            summary["removed"].append("bin/")
        rt.ensure_llama_binary(progress_cb=notify)
        summary["updated"].append(f"llama.cpp ({rt.platform_key})")

    # 4. Re-descargar modelos de IA si el usuario lo solicitó explícitamente
    if reinstall_models:
        notify("Re-descargando y verificando modelos GGUF (Qwen3-VL-4B-Instruct)...")
        if rt.models_dir.exists():
            shutil.rmtree(rt.models_dir, ignore_errors=True)
            summary["removed"].append("models/")
        rt.ensure_models(progress_cb=notify)
        summary["updated"].append("Qwen3-VL-4B-Instruct (SHA-256 verificado)")

    # 5. Actualizar dependencias de Python si corremos desde código fuente
    req_file = root / "requirements.txt"
    if upgrade_deps and not getattr(sys, "frozen", False) and req_file.exists():
        notify("Actualizando librerías Python (requirements.txt)...")
        res = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file), "--upgrade"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            summary["updated"].append("Dependencias Python (requirements.txt)")
        else:
            logger.warning(f"pip install --upgrade devolvió código {res.returncode}: {res.stderr[:300]}")

    notify("✓ Limpieza y reinstalación completadas con éxito.")
    return summary
