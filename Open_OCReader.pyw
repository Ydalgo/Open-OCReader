#!/usr/bin/env pythonw
"""
Lanzador directo sin consola de comandos para Open OCReader en Windows.
Al ejecutarse con pythonw o hacer doble clic en el explorador,
inicia la interfaz gráfica directamente sin abrir ninguna ventana de terminal (CMD).
"""

import sys
from pathlib import Path

# Asegurar que el directorio del proyecto está en sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from open_ocreader.gui import launch_gui

if __name__ == "__main__":
    launch_gui()
