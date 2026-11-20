# ==============================================================================
# Dockerfile - Open OCReader Server (API REST + Web UI Móvil 100% Local)
# Endurecido para despliegues on-premise, intranet y contenedor no-root (ENS/RGPD)
# ==============================================================================
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    DO_NOT_TRACK=1 \
    OPEN_OCREADER_HOST=0.0.0.0 \
    OPEN_OCREADER_PORT=8000 \
    OPEN_OCREADER_DATA_DIR=/app

# Dependencias nativas mínimas (OpenCV/PDFium/QPDF/TTS Linux)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    qpdf \
    espeak-ng \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Usuario no privilegiado
RUN groupadd -g 10001 ocreader && \
    useradd -u 10001 -g ocreader -m -s /bin/bash ocreader

WORKDIR /app

COPY requirements-server.txt /app/requirements-server.txt
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements-server.txt

COPY src/ /app/src/
COPY ico/ /app/ico/
COPY LICENSE README.md /app/

RUN mkdir -p /app/models /app/bin /app/cache /app/logs /app/config && \
    chown -R ocreader:ocreader /app

USER ocreader

VOLUME ["/app/models", "/app/bin", "/app/cache", "/app/logs", "/app/config"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

ENTRYPOINT ["python", "src/ocr_server.py"]
