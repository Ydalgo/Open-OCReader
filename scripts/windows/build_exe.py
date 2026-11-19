"""
Script para compilar Open OCReader en un ejecutable independiente (.exe) para Windows.
Genera el programa en dist/Open_OCReader/ listo para usar sin Python instalado.

Uso:
    python scripts/windows/build_exe.py
    python scripts/windows/build_exe.py --onefile
"""

import sys
import subprocess
from pathlib import Path


def build():
    # Raíz del proyecto: dos niveles arriba de scripts/windows/
    base_dir = Path(__file__).resolve().parent.parent.parent
    src_dir = base_dir / "src"
    is_onefile = "--onefile" in sys.argv

    print("=" * 65)
    print(" Compilando Open OCReader a ejecutable (.exe)")
    print(" Modo:", "Archivo único portátil (--onefile)" if is_onefile else "Paquete rápido (dist/Open_OCReader/)")
    print("=" * 65)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        f"--paths={src_dir}",
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

    cmd.append(str(src_dir / "Open_OCReader.pyw"))

    result = subprocess.run(cmd, cwd=str(base_dir))

    if result.returncode == 0:
        dist_dir = base_dir / "dist"
        exe_path = dist_dir / "Open_OCReader.exe" if is_onefile else dist_dir / "Open_OCReader" / "Open_OCReader.exe"
        print("\n" + "=" * 65)
        print("OK! Compilación completada con éxito.")
        print(f"Ejecutable: {exe_path}")
        print("=" * 65)
        try:
            subprocess.run(["explorer.exe", str(exe_path.parent)], check=False)
        except Exception:
            pass
    else:
        print("\n[ERROR] Falló la compilación de PyInstaller.", file=sys.stderr)
        sys.exit(result.returncode)


if __name__ == "__main__":
    build()
