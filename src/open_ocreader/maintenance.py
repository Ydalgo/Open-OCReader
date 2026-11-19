"""
Utilidades de mantenimiento para Open OCReader:
Borrado seguro de logs, limpieza de cachés y limpieza robusta de compilaciones
(cerrando procesos zombies en Windows y gestionando permisos/ficheros bloqueados).
"""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple
from .logger import get_logger, get_logs_dir, is_log_deletion_locked

logger = get_logger("maintenance")


def _kill_blocking_processes_windows(notify_cb=None) -> List[str]:
    """
    Cierra procesos zombies en Windows que suelen mantener bloqueada la carpeta dist/ o bin/
    (Open_OCReader.exe, Open_OCReader_Server.exe, llama-server.exe).
    No mata el propio proceso si estamos corriendo como ejecutable compilado.
    """
    if sys.platform != "win32":
        return []

    killed: List[str] = []
    my_pid = os.getpid()
    is_frozen = getattr(sys, "frozen", False)
    my_exe_name = Path(sys.executable).name.lower() if is_frozen else ""

    targets = ["llama-server.exe", "Open_OCReader_Server.exe", "Open_OCReader.exe"]
    for proc_name in targets:
        if is_frozen and proc_name.lower() == my_exe_name:
            continue
        try:
            res = subprocess.run(
                ["taskkill", "/F", "/T", "/IM", proc_name],
                capture_output=True,
                text=True,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if res.returncode == 0:
                killed.append(proc_name)
                if notify_cb:
                    notify_cb(f"Proceso en segundo plano cerrado: {proc_name}")
        except Exception as e:
            logger.debug(f"No se pudo invocar taskkill para {proc_name}: {e}")

    if killed:
        # Breve pausa para que Windows libere los manejadores de archivos en dist/ y bin/
        time.sleep(0.8)

    return killed


def _robust_rmtree(target: Path, retries: int = 3) -> Tuple[bool, List[str]]:
    """
    Borra un directorio de forma robusta en Windows:
      - Quita atributos de solo lectura automáticamente.
      - Reintenta varias veces por si el antivirus o un proceso recién cerrado retiene un handle.
      - Si algún fichero sigue bloqueado, borra todo lo demás y devuelve la lista de errores.
    """
    if not target.exists():
        return True, []

    def _handle_readonly(func, path, _exc_info):
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            func(path)
        except Exception:
            pass

    for attempt in range(1, retries + 1):
        try:
            shutil.rmtree(target, onerror=_handle_readonly)
            if not target.exists():
                return True, []
        except Exception:
            pass
        if attempt < retries:
            time.sleep(0.6)

    # Último intento: borrar elemento a elemento para limpiar todo lo posible y reportar bloqueados
    locked_errors: List[str] = []
    for root_dir, dirs, files in os.walk(target, topdown=False):
        for fname in files:
            fpath = Path(root_dir) / fname
            try:
                os.chmod(fpath, stat.S_IWRITE | stat.S_IREAD)
                fpath.unlink()
            except Exception as e:
                locked_errors.append(f"{fpath.name}: {e}")
        for dname in dirs:
            dpath = Path(root_dir) / dname
            try:
                dpath.rmdir()
            except Exception:
                pass
    try:
        target.rmdir()
    except Exception:
        pass

    return (not target.exists()), locked_errors


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
            if item.suffix in {".1", ".2", ".3", ".bak"}:
                item.unlink()
                removed_files += 1
            elif item.suffix == ".log":
                with open(item, "w", encoding="utf-8") as f:
                    f.truncate(0)
                truncated_files += 1
        except Exception:
            pass

    logger.info(f"Limpieza de logs ejecutada (truncados: {truncated_files}, eliminados: {removed_files}).")
    return {"truncated": truncated_files, "removed": removed_files}


def clear_cache() -> Dict[str, int]:
    """
    Limpia ficheros temporales (capturas del portapapeles, uploads de servidor API)
    y directorios __pycache__ del proyecto.
    """
    deleted_items = 0

    temp_dirs = [
        Path(tempfile.gettempdir()) / "open_ocreader",
        Path(tempfile.gettempdir()) / "open_ocreader_api",
    ]
    for td in temp_dirs:
        if td.exists():
            for child in td.iterdir():
                try:
                    if child.is_dir():
                        _robust_rmtree(child, retries=2)
                    else:
                        child.unlink(missing_ok=True)
                    deleted_items += 1
                except Exception:
                    pass

    src_root = Path(__file__).resolve().parent.parent
    for pycache in src_root.rglob("__pycache__"):
        try:
            _robust_rmtree(pycache, retries=2)
            deleted_items += 1
        except Exception:
            pass

    # 3. Limpiar caché persistente SQLite WAL de árboles AST documentales
    try:
        from .ai.doc_cache import DocumentIndexCache
        deleted_items += DocumentIndexCache.get_instance().clear()
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
    Limpia restos antiguos del proyecto (build/, dist/, *.spec, cachés),
    cierra procesos zombies en Windows y reinstala/actualiza los componentes seleccionados.
    """
    from .ai.runtime_manager import LlamaRuntimeManager

    def notify(msg: str):
        logger.info(msg)
        if progress_cb:
            progress_cb(msg)

    rt = LlamaRuntimeManager.get_instance()
    rt.stop_server()

    # 0. Cerrar procesos zombies que puedan bloquear dist/ o bin/
    notify("Comprobando y cerrando procesos en segundo plano...")
    killed = _kill_blocking_processes_windows(notify_cb=notify)

    root = rt.base_dir
    summary: Dict[str, Any] = {
        "removed": [],
        "updated": [],
        "killed_processes": killed,
        "warnings": [],
    }

    # 1. Limpiar cachés
    notify("Limpiando cachés y temporales...")
    clear_cache()

    # 2. Limpiar compilaciones antiguas (build/, dist/, *.spec)
    if clean_builds:
        if getattr(sys, "frozen", False):
            warn = (
                "No se puede borrar dist/ mientras la aplicación se ejecuta desde el propio .exe. "
                "Cierra la app y ejecuta scripts\\windows\\limpiar_y_reinstalar.bat."
            )
            summary["warnings"].append(warn)
            notify(f"[AVISO] {warn}")
        else:
            notify("Eliminando compilaciones antiguas (build/, dist/, *.spec)...")
            for folder_name in ("build", "dist"):
                target = root / folder_name
                if target.exists():
                    ok, errs = _robust_rmtree(target, retries=3)
                    if ok:
                        summary["removed"].append(folder_name + "/")
                    else:
                        warn = f"No se pudo eliminar completamente {folder_name}/ ({len(errs)} archivo(s) bloqueados: {', '.join(errs[:3])})"
                        summary["warnings"].append(warn)
                        logger.warning(warn)
                        notify(f"[AVISO] {warn}")
            for spec_f in root.glob("*.spec"):
                try:
                    spec_f.unlink()
                    summary["removed"].append(spec_f.name)
                except Exception as e:
                    summary["warnings"].append(f"No se pudo borrar {spec_f.name}: {e}")

    # 3. Reinstalar/Actualizar binarios de llama.cpp (bin/)
    if reinstall_llama:
        notify("Limpiando binarios antiguos de llama.cpp y descargando la última versión oficial...")
        if rt.bin_root.exists():
            ok, errs = _robust_rmtree(rt.bin_root, retries=3)
            if ok:
                summary["removed"].append("bin/")
            else:
                summary["warnings"].append(f"Algunos archivos en bin/ estaban bloqueados: {', '.join(errs[:3])}")
        rt.ensure_llama_binary(progress_cb=notify)
        summary["updated"].append(f"llama.cpp ({rt.platform_key})")

    # 4. Re-descargar modelos de IA si el usuario lo solicitó explícitamente
    if reinstall_models:
        notify("Re-descargando y verificando modelos GGUF (Qwen3-VL-4B-Instruct)...")
        if rt.models_dir.exists():
            _robust_rmtree(rt.models_dir, retries=3)
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

    if summary["warnings"]:
        notify("⚠ Limpieza finalizada con avisos (revisa los detalles).")
    else:
        notify("✓ Limpieza y reinstalación completadas con éxito.")
    return summary
