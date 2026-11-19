"""
Script de compilación multi-compilador para Open OCReader (Nuitka nativo C/C++ o PyInstaller).
Permite compilar tanto la aplicación de escritorio (GUI) como el servidor API REST.

Uso:
    python scripts/windows/build_exe.py                        (GUI con Nuitka si está disponible, o PyInstaller)
    python scripts/windows/build_exe.py --compiler pyinstaller (Forzar PyInstaller)
    python scripts/windows/build_exe.py --compiler nuitka      (Forzar Nuitka: compilación nativa C y ofuscación)
    python scripts/windows/build_exe.py --target server        (Compilar Open_OCReader_Server.exe)
    python scripts/windows/build_exe.py --onefile              (Un único archivo ejecutable portátil)
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


def find_signtool() -> Optional[Path]:
    """Localiza signtool.exe en PATH o en Windows Kits (SDK)."""
    in_path = shutil.which("signtool.exe")
    if in_path:
        return Path(in_path)
    kits_root = Path(r"C:\Program Files (x86)\Windows Kits\10\bin")
    if kits_root.exists():
        candidates = sorted(kits_root.rglob("x64/signtool.exe"), reverse=True)
        if candidates:
            return candidates[0]
    return None


def sign_executable(exe_path: Path, pfx_path: str, pfx_password: Optional[str], timestamp_url: str):
    """Firma digitalmente el ejecutable .exe con SHA-256 y sellado de tiempo RFC 3161."""
    signtool = find_signtool()
    if not signtool:
        print("[AVISO] No se encontró signtool.exe (Windows SDK). Omitiendo firma digital.", file=sys.stderr)
        return

    cmd = [
        str(signtool),
        "sign",
        "/fd", "SHA256",
        "/f", pfx_path,
        "/tr", timestamp_url,
        "/td", "SHA256",
    ]
    if pfx_password:
        cmd.extend(["/p", pfx_password])
    cmd.append(str(exe_path))

    print(f"Firmando digitalmente '{exe_path.name}' con SHA-256...")
    res = subprocess.run(cmd, check=False)
    if res.returncode == 0:
        print(f"✓ Ejecutable firmado correctamente: {exe_path.name}")
    else:
        print(f"[ERROR] Falló signtool (código {res.returncode}).", file=sys.stderr)


def write_sha256_manifest(exe_path: Path):
    """Genera el fichero SHA256SUMS.txt junto al ejecutable para verificación de integridad ENS."""
    if not exe_path.exists():
        return
    h = hashlib.sha256()
    with open(exe_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    digest = h.hexdigest()
    manifest = exe_path.parent / "SHA256SUMS.txt"
    manifest.write_text(f"{digest}  {exe_path.name}\n", encoding="utf-8")
    print(f"✓ Manifiesto de integridad generado: {manifest} ({digest[:16]}...)")


def has_nuitka() -> bool:
    try:
        __import__("nuitka")
        return True
    except ImportError:
        return False


def build_with_nuitka(base_dir: Path, src_dir: Path, target: str, onefile: bool):
    entry = src_dir / ("ocr_server.py" if target == "server" else "Open_OCReader.pyw")
    out_name = "Open_OCReader_Server" if target == "server" else "Open_OCReader"
    dist_dir = base_dir / "dist"

    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        f"--output-dir={dist_dir}",
        f"--output-filename={out_name}.exe",
        "--include-package=open_ocreader",
        "--include-package=rapidocr_onnxruntime",
        "--include-package=pypdfium2",
        "--include-package-data=rapidocr_onnxruntime",
        "--include-package-data=pypdfium2",
        "--nofollow-import-to=torch,torchvision,transformers,scipy,matplotlib,pandas,IPython,pytest,notebook",
    ]

    if onefile:
        cmd.append("--onefile")

    ico_dir = base_dir / "ico"
    ico_file = ico_dir / "Open_OCReader.ico"

    if target == "gui":
        cmd.extend([
            "--windows-console-mode=disable",
            "--enable-plugin=tk-inter",
        ])
        if ico_file.exists():
            cmd.append(f"--windows-icon-from-ico={ico_file}")
        if ico_dir.exists():
            cmd.append(f"--include-data-dir={ico_dir}=ico")
    else:
        cmd.extend([
            "--windows-console-mode=force",
            "--include-package=fastapi",
            "--include-package=uvicorn",
            "--include-package=starlette",
            "--include-package=pydantic",
        ])

    cmd.append(str(entry))

    env_path = str(src_dir)
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = env_path + os.pathsep + env.get("PYTHONPATH", "")

    print(f"Compilando '{out_name}' con Nuitka (C nativo + optimización + ofuscación)...")
    result = subprocess.run(cmd, cwd=str(base_dir), env=env)
    if result.returncode != 0:
        sys.exit(result.returncode)

    # Normalizar carpeta destino de Nuitka (<entry>.dist -> dist/<out_name>)
    nuitka_dist = dist_dir / f"{entry.stem}.dist"
    final_dist = dist_dir / out_name
    if not onefile and nuitka_dist.exists():
        if final_dist.exists():
            shutil.rmtree(final_dist, ignore_errors=True)
        nuitka_dist.rename(final_dist)


def build_with_pyinstaller(base_dir: Path, src_dir: Path, target: str, onefile: bool):
    entry = src_dir / ("ocr_server.py" if target == "server" else "Open_OCReader.pyw")
    out_name = "Open_OCReader_Server" if target == "server" else "Open_OCReader"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        f"--paths={src_dir}",
        f"--name={out_name}",
        "--collect-all=rapidocr_onnxruntime",
        "--collect-all=pypdfium2",
        "--hidden-import=PIL",
        "--hidden-import=cv2",
        "--hidden-import=pypdf",
        "--hidden-import=reportlab",
        "--hidden-import=docx",
        "--hidden-import=openpyxl",
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

    ico_dir = base_dir / "ico"
    ico_file = ico_dir / "Open_OCReader.ico"

    if target == "gui":
        cmd.extend(["--windowed", "--hidden-import=windnd", "--hidden-import=win32clipboard"])
        if ico_file.exists():
            cmd.append(f"--icon={ico_file}")
        if ico_dir.exists():
            cmd.append(f"--add-data={ico_dir};ico")
    else:
        cmd.extend(["--console", "--hidden-import=uvicorn", "--hidden-import=fastapi"])

    if onefile:
        cmd.append("--onefile")

    cmd.append(str(entry))

    print(f"Compilando '{out_name}' con PyInstaller...")
    result = subprocess.run(cmd, cwd=str(base_dir))
    if result.returncode != 0:
        sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description="Compilador de Open OCReader (Nuitka / PyInstaller)")
    parser.add_argument(
        "--compiler",
        choices=["auto", "nuitka", "pyinstaller"],
        default="auto",
        help="Compilador a utilizar ('auto' usa Nuitka si está disponible).",
    )
    parser.add_argument(
        "--target",
        choices=["gui", "server"],
        default="gui",
        help="Objetivo a compilar: 'gui' (aplicación visual) o 'server' (API REST).",
    )
    parser.add_argument("--onefile", action="store_true", help="Generar un único fichero .exe portátil.")
    parser.add_argument("--sign-pfx", default=os.environ.get("OPEN_OCREADER_SIGN_PFX"), help="Certificado .pfx para Code Signing.")
    parser.add_argument("--sign-password", default=os.environ.get("OPEN_OCREADER_SIGN_PASS"), help="Contraseña del certificado .pfx.")
    parser.add_argument("--timestamp-url", default="http://timestamp.digicert.com", help="Servidor de sellado de tiempo RFC 3161.")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent.parent.parent
    src_dir = base_dir / "src"

    compiler = args.compiler
    if compiler == "auto":
        compiler = "nuitka" if has_nuitka() else "pyinstaller"

    print("=" * 65)
    print(f" Compilador: {compiler.upper()} | Objetivo: {args.target.upper()}")
    print("=" * 65)

    if compiler == "nuitka":
        build_with_nuitka(base_dir, src_dir, args.target, args.onefile)
    else:
        build_with_pyinstaller(base_dir, src_dir, args.target, args.onefile)

    out_name = "Open_OCReader_Server" if args.target == "server" else "Open_OCReader"
    exe_path = base_dir / "dist" / (f"{out_name}.exe" if args.onefile else f"{out_name}/{out_name}.exe")

    if args.sign_pfx and exe_path.exists():
        sign_executable(exe_path, args.sign_pfx, args.sign_password, args.timestamp_url)

    write_sha256_manifest(exe_path)

    print("\n" + "=" * 65)
    print(f"OK! Compilación finalizada: {exe_path}")
    print("=" * 65)


if __name__ == "__main__":
    main()
