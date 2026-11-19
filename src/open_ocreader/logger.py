"""
Sistema centralizado de registro (Logging) para Open OCReader.
Guarda todos los eventos, errores, stack traces completos y salida de llama-server
en ficheros rotativos dentro de la carpeta 'logs/'.
"""

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


def ensure_standard_streams():
    """
    En aplicaciones sin consola (--windowed / pythonw.exe), sys.stdout y sys.stderr son None.
    Librerías como tqdm o huggingface_hub fallan con AttributeError si intentan escribir en None.
    """
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")


def get_logs_dir() -> Path:
    """Obtiene y crea la carpeta de logs en la raíz del proyecto o junto al ejecutable."""
    if getattr(sys, "frozen", False):
        # Si corre empaquetado como .exe con PyInstaller
        base_dir = Path(sys.executable).resolve().parent
    else:
        # src/open_ocreader/logger.py -> raíz del proyecto
        base_dir = Path(__file__).resolve().parent.parent.parent

    logs_dir = base_dir / "logs"
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Fallback a carpeta temporal del usuario si no hay permisos de escritura
        import tempfile
        logs_dir = Path(tempfile.gettempdir()) / "Open_OCReader_logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

    return logs_dir


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """
    Configura el logger principal con rotación de archivos (máx 5MB x 3 ficheros)
    y captura global de excepciones no controladas.
    """
    ensure_standard_streams()
    logger = logging.getLogger("open_ocreader")
    if logger.handlers:
        return logger

    logger.setLevel(level)
    logs_dir = get_logs_dir()
    log_file = logs_dir / "open_ocreader.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s:%(funcName)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Manejador de archivo rotativo
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    logger.addHandler(file_handler)

    # Manejador de consola (solo si hay stdout disponible, ej. modo CLI)
    if sys.stdout is not None:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
        )
        console_handler.setLevel(logging.WARNING)
        logger.addHandler(console_handler)

    # Capturar excepciones no controladas en el hilo principal y en hilos secundarios
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical("Excepción crítica no controlada:", exc_info=(exc_type, exc_value, exc_traceback))

    def handle_thread_exception(args):
        logger.critical(
            f"Excepción crítica en hilo '{args.thread.name}':",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = handle_exception
    threading.excepthook = handle_thread_exception

    logger.info("=" * 60)
    logger.info(f"Open OCReader iniciado (Python {sys.version.split()[0]}, Plataforma: {sys.platform})")
    logger.info(f"Fichero de logs activo: {log_file}")
    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Devuelve un sub-logger configurado bajo el espacio 'open_ocreader'."""
    setup_logging()
    if name:
        return logging.getLogger(f"open_ocreader.{name}")
    return logging.getLogger("open_ocreader")
