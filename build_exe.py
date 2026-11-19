"""
Script para compilar Open OCReader en un ejecutable independiente (.exe) para Windows.
Permite ejecutar la aplicación en cualquier ordenador sin necesidad de tener Python instalado.

Uso:
    python build_exe.py
"""

import sys
import subprocess
from pathlib import Path


def build():
    print("=" * 60)
    print(" Compilando Open OCReader a ejecutable (.exe)")
    print("=" * 60)

    base_dir = Path(__file__).resolve().parent

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",  # Sin ventana de consola CMD
        "--name=Open_OCReader",
        "--collect-all=rapidocr_onnxruntime",
        "--collect-all=pypdfium2",
        "--hidden-import=PIL",
        "--hidden-import=cv2",
        "--hidden-import=pypdf",
        "--hidden-import=reportlab",
        "--hidden-import=docx",
        "--hidden-import=openpyxl",
        "--hidden-import=windnd",
        "--hidden-import=win32clipboard",
        # Excluir paquetes pesados de Anaconda no requeridos por Open OCReader
        "--exclude-module=torch",
        "--exclude-module=torchvision",
        "--exclude-module=transformers",
        "--exclude-module=scipy",
        "--exclude-module=matplotlib",
        "--exclude-module=IPython",
        "--exclude-module=pytest",
        "--exclude-module=notebook",
        "--exclude-module=pandas",
        str(base_dir / "Open_OCReader.pyw"),
    ]

    print("Ejecutando PyInstaller...")
    result = subprocess.run(cmd, cwd=str(base_dir))

    if result.returncode == 0:
        dist_dir = base_dir / "dist" / "Open_OCReader"
        exe_path = dist_dir / "Open_OCReader.exe"
        print("\n" + "=" * 60)
        print("✓ ¡Compilación completada con éxito!")
        print(f"Carpeta del programa: {dist_dir}")
        print(f"Ejecutable listo para usar: {exe_path}")
        print("Puedes copiar esa carpeta o comprimirla en .zip para cualquier PC sin Python.")
        print("=" * 60)
    else:
        print("\n[ERROR] Falló la compilación de PyInstaller.", file=sys.stderr)
        sys.exit(result.returncode)


if __name__ == "__main__":
    build()
