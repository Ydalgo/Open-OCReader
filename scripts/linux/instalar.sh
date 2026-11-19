#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/../.."

echo "================================================================"
echo "  Instalando dependencias de Open OCReader para Linux"
echo "================================================================"

if command -v apt-get >/dev/null 2>&1; then
    echo "Instalando python3-tk y xdg-utils..."
    sudo apt-get update && sudo apt-get install -y python3-tk python3-venv xdg-utils
fi

if [ ! -d "venv" ]; then
    echo "Creando entorno virtual Python en ./venv..."
    python3 -m venv venv
fi

source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "Instalación completada. Ejecuta ./scripts/linux/iniciar.sh para abrir la aplicación."
