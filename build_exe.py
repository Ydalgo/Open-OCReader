"""
Script para compilar Open OCReader en un ejecutable independiente (.exe) para Windows.
Permite ejecutar la aplicación en cualquier ordenador sin necesidad de tener Python instalado.

Uso:
    python build_exe.py            (Modo directorio: genera carpeta con Open_OCReader.exe, arranque instantáneo)
    python build_exe.py --onefile  (Modo monolitico: genera un único archivo .exe portátil)
"""

import sys
import subprocess
from pathlib import Path


def build():
    base_dir = Path(__file__).resolve().parent
    is_onefile = "--onefile" in sys.argv

    print("=" * 65)
    print(" Compilando Open OCReader a ejecutable (.exe)")
    if is_onefile:
        print(" Modo: Archivo único portátil (--onefile)")
    else:
        print(" Modo: Paquete con arranque rápido (dist/Open_OCReader/)")
    print("=" * 65)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",  # Sin ventana de consola CMD negra
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
        "--hidden-import=requests",
        "--hidden-import=huggingface_hub",
        "--hidden-import=open_ocreader.ai",
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
    ]

    if is_onefile:
        cmd.append("--onefile")

    cmd.append(str(base_dir / "Open_OCReader.pyw"))

    print("\nEjecutando PyInstaller, esto puede tomar aproximadamente 1 minuto...")
    result = subprocess.run(cmd, cwd=str(base_dir))

    if result.returncode == 0:
        dist_dir = base_dir / "dist"
        if is_onefile:
            exe_path = dist_dir / "Open_OCReader.exe"
        else:
            exe_path = dist_dir / "Open_OCReader" / "Open_OCReader.exe"

        # Crear lanzador directo en la carpeta raíz para máxima comodidad
        launcher_bat = base_dir / "Iniciar_Open_OCReader.bat"
        with open(launcher_bat, "w", encoding="utf-8") as f:
            f.write('@echo off\nstart "" "%~dp0dist\\Open_OCReader\\Open_OCReader.exe"\n')

        print("\n" + "=" * 65)
        print("✓ ¡Compilación completada con éxito!")
        print(f"Ubicación exacta del ejecutable: {exe_path}")
        print(f"Lanzador directo creado en la raíz: {launcher_bat}")
        print("=" * 65)

        # Abrir la carpeta contenedora en el Explorador de Windows para que el usuario lo vea
        try:
            target_folder = exe_path.parent if exe_path.exists() else dist_dir
            subprocess.run(["explorer.exe", str(target_folder)], check=False)
        except Exception:
            pass
    else:
        print("\n[ERROR] Falló la compilación de PyInstaller.", file=sys.stderr)
        sys.exit(result.returncode)


if __name__ == "__main__":
    build()
