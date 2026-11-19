"""
Sistema centralizado de registro (Logging) para Open OCReader.
Soporta:
  - Ficheros rotativos locales en 'logs/open_ocreader.log'.
  - Formato JSON estructurado para SIEM (OPEN_OCREADER_LOG_FORMAT=json).
  - Envío centralizado a Syslog/SIEM (OPEN_OCREADER_SYSLOG_HOST, PORT, PROTO).
  - Modo inmutable de auditoría ENS (OPEN_OCREADER_LOCK_LOGS=1).
"""

import json
import logging
import os
import socket
import sys
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler, SysLogHandler
from pathlib import Path
from typing import Optional


class JsonSiemFormatter(logging.Formatter):
    """Formateador JSON estructurado compatible con SIEM (Wazuh, Elastic, Splunk, QRadar)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "function": record.funcName,
            "line": record.lineno,
            "app": "open-ocreader",
            "host": socket.gethostname(),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def ensure_standard_streams():
    """Evita AttributeError en modo --windowed / pythonw.exe y desactiva telemetría de terceros."""
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("DO_NOT_TRACK", "1")
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")


def get_logs_dir() -> Path:
    """Obtiene y crea la carpeta de logs en la raíz del proyecto o junto al ejecutable."""
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parent.parent.parent

    logs_dir = base_dir / "logs"
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        import tempfile
        logs_dir = Path(tempfile.gettempdir()) / "Open_OCReader_logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

    return logs_dir


def is_log_deletion_locked() -> bool:
    """Devuelve True si el administrador activó inmutabilidad ENS de logs."""
    return os.environ.get("OPEN_OCREADER_LOCK_LOGS", "").strip().lower() in {"1", "true", "yes"}


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configura el logger principal (rotativo local + SIEM/Syslog opcional + captura global)."""
    ensure_standard_streams()
    logger = logging.getLogger("open_ocreader")
    if logger.handlers:
        return logger

    logger.setLevel(level)
    logs_dir = get_logs_dir()
    log_file = logs_dir / "open_ocreader.log"

    use_json = os.environ.get("OPEN_OCREADER_LOG_FORMAT", "text").strip().lower() == "json"
    if use_json:
        formatter: logging.Formatter = JsonSiemFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s:%(funcName)s:%(lineno)d] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # 1. Fichero rotativo local
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    logger.addHandler(file_handler)

    # 2. Envío centralizado a SIEM / Syslog (si se configura OPEN_OCREADER_SYSLOG_HOST)
    syslog_host = os.environ.get("OPEN_OCREADER_SYSLOG_HOST", "").strip()
    if syslog_host:
        try:
            syslog_port = int(os.environ.get("OPEN_OCREADER_SYSLOG_PORT", "514"))
            proto = os.environ.get("OPEN_OCREADER_SYSLOG_PROTO", "udp").strip().lower()
            socktype = socket.SOCK_STREAM if proto == "tcp" else socket.SOCK_DGRAM
            siem_handler = SysLogHandler(address=(syslog_host, syslog_port), socktype=socktype)
            siem_handler.setFormatter(JsonSiemFormatter())
            siem_handler.setLevel(level)
            logger.addHandler(siem_handler)
        except Exception as e:
            logger.warning(f"No se pudo conectar el handler SIEM/Syslog ({syslog_host}): {e}")

    # 3. Consola (solo si hay stdout real)
    if sys.stdout is not None and sys.stdout.name != os.devnull:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
        )
        console_handler.setLevel(logging.WARNING)
        logger.addHandler(console_handler)

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
    setup_logging()
    if name:
        return logging.getLogger(f"open_ocreader.{name}")
    return logging.getLogger("open_ocreader")
