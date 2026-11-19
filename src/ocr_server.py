#!/usr/bin/env python3
"""
Open OCReader - Modo Servidor API REST endurecido (TLS 1.3, API Key, SIEM).

Uso:
    python src/ocr_server.py
    python src/ocr_server.py --host 0.0.0.0 --port 8443 --ssl-certfile cert.pem --ssl-keyfile key.pem
"""

import argparse
import os
import ssl
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
        description="Open OCReader API Server endurecido (FastAPI + Uvicorn + TLS 1.3)",
    )
    default_host = os.environ.get("OPEN_OCREADER_HOST", "127.0.0.1")
    default_port = int(os.environ.get("OPEN_OCREADER_PORT", "8000"))

    parser.add_argument("--host", default=default_host, help=f"Dirección de escucha (por defecto: {default_host}).")
    parser.add_argument("--port", type=int, default=default_port, help=f"Puerto HTTP/HTTPS (por defecto: {default_port}).")
    parser.add_argument("--api-key", default=None, help="Clave API (o variable OPEN_OCREADER_API_KEY).")
    parser.add_argument("--ssl-certfile", default=None, help="Ruta al certificado TLS (.pem/.crt) para HTTPS.")
    parser.add_argument("--ssl-keyfile", default=None, help="Ruta a la clave privada TLS (.pem/.key) para HTTPS.")
    args = parser.parse_args()

    logger = setup_logging()

    is_external = args.host not in {"127.0.0.1", "localhost", "::1"}
    if args.api_key:
        os.environ["OPEN_OCREADER_API_KEY"] = args.api_key
    elif is_external and not os.environ.get("OPEN_OCREADER_API_KEY"):
        generated = generate_token()
        os.environ["OPEN_OCREADER_API_KEY"] = generated
        print("=" * 70)
        print("[SEGURIDAD] Escuchando en red externa sin OPEN_OCREADER_API_KEY.")
        print(f"[SEGURIDAD] Clave API autogenerada para esta sesión: {generated}")
        print("[SEGURIDAD] Envíala en 'X-API-Key' o 'Authorization: Bearer <clave>'.")
        print("=" * 70)

    has_tls = bool(args.ssl_certfile and args.ssl_keyfile)
    if is_external and not has_tls:
        logger.warning("Servidor escuchando en red externa sin TLS directo. Usa --ssl-certfile/--ssl-keyfile o proxy inverso TLS 1.3.")
        print("[AVISO ENS/CCN-CERT] Escuchando fuera de localhost sin TLS. En producción usa TLS 1.3 (deploy/nginx_tls13.conf o --ssl-certfile).")

    scheme = "https" if has_tls else "http"
    logger.info(f"Iniciando servidor API REST en {scheme}://{args.host}:{args.port} (TLS={has_tls})")
    print(f"[Open OCReader Server] Escuchando en {scheme}://{args.host}:{args.port}")
    print(f"[Open OCReader Server] Documentación Swagger UI: {scheme}://{args.host}:{args.port}/docs")

    uvicorn_kwargs = {
        "host": args.host,
        "port": args.port,
        "log_level": "info",
    }
    if has_tls:
        uvicorn_kwargs["ssl_certfile"] = args.ssl_certfile
        uvicorn_kwargs["ssl_keyfile"] = args.ssl_keyfile
        uvicorn_kwargs["ssl_version"] = ssl.PROTOCOL_TLS_SERVER

    uvicorn.run("open_ocreader.server.api:app", **uvicorn_kwargs)


if __name__ == "__main__":
    main()
