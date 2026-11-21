#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/../.."

echo "================================================================"
echo "  Instalando dependencias de Open OCReader para Linux"
echo "================================================================"

if command -v apt-get >/dev/null 2>&1; then
    echo "Instalando paquetes del sistema necesarios (OpenGL, GLib, Tkinter, PySide6 deps, audio TTS y visor)..."
    sudo apt-get update && sudo apt-get install -y \
        python3-pip \
        python3-venv \
        python3-tk \
        xdg-utils \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        qpdf \
        espeak-ng \
        libegl1 \
        libxkbcommon-x11-0 \
        libdbus-1-3
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
