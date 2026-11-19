#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/../.."
PROJECT_DIR="$(pwd)"
CURRENT_USER="$(whoami)"

if [ -f "$PROJECT_DIR/dist/Open_OCReader_Server/Open_OCReader_Server" ]; then
    EXEC_CMD="$PROJECT_DIR/dist/Open_OCReader_Server/Open_OCReader_Server"
elif [ -d "$PROJECT_DIR/venv" ]; then
    EXEC_CMD="$PROJECT_DIR/venv/bin/python $PROJECT_DIR/src/ocr_server.py"
else
    EXEC_CMD="$(which python3) $PROJECT_DIR/src/ocr_server.py"
fi

SERVICE_TMP="/tmp/open-ocreader.service"
sed -e "s|__USER__|$CURRENT_USER|g" \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    -e "s|__EXEC_CMD__|$EXEC_CMD|g" \
    "$PROJECT_DIR/scripts/linux/open-ocreader.service" > "$SERVICE_TMP"

echo "Instalando servicio systemd en /etc/systemd/system/open-ocreader.service..."
sudo mv "$SERVICE_TMP" /etc/systemd/system/open-ocreader.service
sudo systemctl daemon-reload
sudo systemctl enable open-ocreader.service
sudo systemctl restart open-ocreader.service

echo ""
echo "Servicio instalado y activo! Comprueba su estado con: sudo systemctl status open-ocreader"
