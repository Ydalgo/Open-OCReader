#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/../.."

echo "================================================================"
echo "  Instalando dependencias de Open OCReader para Linux"
echo "================================================================"

TARGET_PY="python3.12"

# 1. Instalar dependencias del sistema y asegurar Python 3.12 fijado
if command -v apt-get >/dev/null 2>&1; then
    echo "Instalando paquetes del sistema necesarios (Python 3.12, OpenGL, GLib, Tkinter, PySide6 deps, audio TTS y visor)..."
    sudo apt-get update && sudo apt-get install -y \
        software-properties-common \
        xdg-utils \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        qpdf \
        espeak-ng \
        libegl1 \
        libxkbcommon-x11-0 \
        libdbus-1-3

    # Intentar instalar Python 3.12 oficial o vía PPA si el sistema trae una versión distinta (ej. Ubuntu 24.04 o superior)
    if ! command -v python3.12 >/dev/null 2>&1; then
        sudo apt-get install -y python3.12 python3.12-venv python3.12-tk || {
            echo "Añadiendo PPA deadsnakes para garantizar Python 3.12 reproducible..."
            sudo add-apt-repository -y ppa:deadsnakes/ppa
            sudo apt-get update
            sudo apt-get install -y python3.12 python3.12-venv python3.12-tk
        }
    else
        sudo apt-get install -y python3.12-venv python3.12-tk || true
    fi
    TARGET_PY="python3.12"
elif command -v python3.12 >/dev/null 2>&1; then
    TARGET_PY="python3.12"
else
    TARGET_PY="python3"
fi

echo "Usando intérprete Python: $($TARGET_PY --version)"

# 2. Crear entorno virtual con la versión fijada
if [ -d "venv" ]; then
    # Verificar si el venv existente usa la versión esperada
    VENV_VER=$(./venv/bin/python --version 2>&1 || true)
    echo "Entorno virtual existente: $VENV_VER"
else
    echo "Creando entorno virtual Python reproducible en ./venv..."
    $TARGET_PY -m venv venv
fi

source venv/bin/activate
pip install --upgrade pip

# 3. Instalación de dependencias (soporta modo offline si existen wheels para Linux o pip online)
if [ -d "offline_repo/wheels_linux" ]; then
    echo "Instalando paquetes desde repositorio offline local (offline_repo/wheels_linux)..."
    pip install --no-index --find-links=offline_repo/wheels_linux -r requirements.txt
else
    pip install -r requirements.txt
fi

echo ""
echo "Instalación completada. Ejecuta ./scripts/linux/iniciar.sh para abrir la aplicación."
