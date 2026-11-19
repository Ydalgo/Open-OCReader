#!/usr/bin/env python3
"""
Open OCReader - Modo Servidor API REST (para clientes web y servicios del SO).

Uso:
    python src/ocr_server.py
    python src/ocr_server.py --host 0.0.0.0 --port 8000
"""

import argparse
import sys
from pathlib import Path
import uvicorn

# Asegurar que src/ esté en sys.path
SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from open_ocreader.logger import setup_logging


def main():
    parser = argparse.ArgumentParser(
        prog="ocr_server",
        description="Open OCReader API Server (FastAPI + Uvicorn)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Dirección de escucha (ej. 0.0.0.0 para red local).")
    parser.add_argument("--port", type=int, default=8000, help="Puerto HTTP (por defecto: 8000).")
    args = parser.parse_args()

    logger = setup_logging()
    logger.info(f"Iniciando servidor API REST en http://{args.host}:{args.port} (Swagger en /docs)")
    print(f"[Open OCReader Server] Escuchando en http://{args.host}:{args.port}")
    print(f"[Open OCReader Server] Documentación interactiva Swagger UI: http://{args.host}:{args.port}/docs")

    uvicorn.run(
        "open_ocreader.server.api:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
