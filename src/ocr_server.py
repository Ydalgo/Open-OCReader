#!/usr/bin/env python3
"""
Open OCReader - Modo Servidor API REST endurecido (para clientes web y servicios del SO).

Uso:
    python src/ocr_server.py
    python src/ocr_server.py --host 0.0.0.0 --port 8000
"""

import argparse
import os
import sys
from pathlib import Path
import uvicorn

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from open_ocreader.logger import setup_logging
from open_ocreader.security import generate_token


def main():
    parser = argparse.ArgumentParser(
        prog="ocr_server",
        description="Open OCReader API Server endurecido (FastAPI + Uvicorn)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Dirección de escucha (por defecto: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8000, help="Puerto HTTP (por defecto: 8000).")
    parser.add_argument(
        "--api-key",
        default=None,
        help="Clave API (también configurable por variable de entorno OPEN_OCREADER_API_KEY).",
    )
    args = parser.parse_args()

    logger = setup_logging()

    if args.api_key:
        os.environ["OPEN_OCREADER_API_KEY"] = args.api_key
    elif args.host not in {"127.0.0.1", "localhost", "::1"} and not os.environ.get("OPEN_OCREADER_API_KEY"):
        # Protección automática: si se expone fuera de localhost sin clave, generar una clave aleatoria segura
        generated = generate_token()
        os.environ["OPEN_OCREADER_API_KEY"] = generated
        print("=" * 70)
        print("[SEGURIDAD] Escuchando en red externa sin OPEN_OCREADER_API_KEY.")
        print(f"[SEGURIDAD] Clave API autogenerada para esta sesión: {generated}")
        print("[SEGURIDAD] Envíala en la cabecera 'X-API-Key' o 'Authorization: Bearer <clave>'.")
        print("=" * 70)

    logger.info(f"Iniciando servidor API REST en http://{args.host}:{args.port} (Swagger en /docs)")
    print(f"[Open OCReader Server] Escuchando en http://{args.host}:{args.port}")
    print(f"[Open OCReader Server] Documentación Swagger UI: http://{args.host}:{args.port}/docs")

    uvicorn.run(
        "open_ocreader.server.api:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
