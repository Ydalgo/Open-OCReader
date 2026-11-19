"""
Generador de paquete instalador empresarial Windows (.msi) con WiX Toolset v5.
Produce `dist/Open_OCReader_Enterprise_Kit/Open_OCReader.msi` listo para GPO / Intune / SCCM:
  - Instala la aplicación en `C:\\Program Files\\Open OCReader\\` para todos los usuarios.
  - Crea accesos directos en Menú Inicio y Escritorio con el icono oficial.
  - Al instalarse, si existe `offline_repo\\` en la misma carpeta desde donde se lanzó el `.msi`,
    detecta automáticamente el hardware del equipo destino y aprovisiona en `C:\\ProgramData\\Open OCReader\\`
    únicamente los binarios (Vulkan/CPU) y modelos GGUF compatibles, sin necesitar Internet.
  - Cualquier usuario estándar (sin permisos de administrador) puede usar la app guardando sus
    logs y caché AST en `%LOCALAPPDATA%\\Open OCReader\\`.

Uso:
    python scripts/windows/build_msi.py
    python scripts/windows/build_msi.py --with-offline-repo   (descarga también offline_repo completo)
"""

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

from open_ocreader import __version__


WXS_TEMPLATE = r"""<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs">
  <Package Name="Open OCReader"
           Manufacturer="Ydalgo (GNU GPL v3.0)"
           Version="{version}"
           UpgradeCode="E47B9C31-6A8F-4F2C-9C14-8B7E1D2F0A91"
           Scope="perMachine">

    <MajorUpgrade DowngradeErrorMessage="Ya existe una versión más reciente de Open OCReader instalada." />
    <MediaTemplate EmbedCab="yes" CompressionLevel="high" />

    <Icon Id="AppIcon.ico" SourceFile="{ico_path}" />
    <Property Id="ARPPRODUCTICON" Value="AppIcon.ico" />
    <Property Id="ARPURLINFOABOUT" Value="https://github.com/Ydalgo/Open-OCReader" />

    <StandardDirectory Id="ProgramFiles64Folder">
      <Directory Id="INSTALLFOLDER" Name="Open OCReader" />
    </StandardDirectory>

    <StandardDirectory Id="ProgramMenuFolder">
      <Directory Id="AppProgramsFolder" Name="Open OCReader" />
    </StandardDirectory>

    <StandardDirectory Id="DesktopFolder" />

    <ComponentGroup Id="AppFiles" Directory="INSTALLFOLDER">
      <Files Include="{dist_dir}\**" />
    </ComponentGroup>

    <Component Id="ProvisionScriptComp" Directory="INSTALLFOLDER" Guid="A93D22C4-4D1B-42F7-A290-91463E0B87F5">
      <File Id="ProvisionScript" Source="{provision_ps1}" KeyPath="yes" />
    </Component>

    <Component Id="AppShortcuts" Directory="AppProgramsFolder" Guid="7C5A81B2-9F3E-4E11-8B20-41A9C7D0E112">
      <Shortcut Id="StartMenuShortcut"
                Name="Open OCReader"
                Description="Digitalización OCR, Herramientas PDF e IA Documental 100% Local"
                Target="[INSTALLFOLDER]Open_OCReader.exe"
                WorkingDirectory="INSTALLFOLDER"
                Icon="AppIcon.ico" />
      <RemoveFolder Id="RemoveAppProgramsFolder" On="uninstall" />
      <RegistryValue Root="HKCU" Key="Software\OpenOCReader" Name="installed" Type="integer" Value="1" KeyPath="yes" />
    </Component>

    <Component Id="DesktopShortcutComp" Directory="DesktopFolder" Guid="B81E44F1-3C2A-4D99-9A15-22E7B1C9D304">
      <Shortcut Id="DesktopShortcut"
                Name="Open OCReader"
                Description="Digitalización OCR, Herramientas PDF e IA Documental 100% Local"
                Target="[INSTALLFOLDER]Open_OCReader.exe"
                WorkingDirectory="INSTALLFOLDER"
                Icon="AppIcon.ico" />
      <RegistryValue Root="HKCU" Key="Software\OpenOCReader" Name="desktop_shortcut" Type="integer" Value="1" KeyPath="yes" />
    </Component>

    <!-- Acción personalizada: aprovisiona desde [SourceDir]offline_repo hacia C:\ProgramData\Open OCReader según hardware -->
    <CustomAction Id="SetProvisionCmd"
                  Property="ProvisionHardwareOffline"
                  Value='powershell.exe -NoProfile -ExecutionPolicy Bypass -File "[#ProvisionScript]" -SourceDir "[SourceDir]"' />
    <CustomAction Id="ProvisionHardwareOffline"
                  BinaryRef="Wix4UtilCA_X86"
                  DllEntry="WixQuietExec"
                  Execute="deferred"
                  Impersonate="no"
                  Return="ignore" />

    <InstallExecuteSequence>
      <Custom Action="SetProvisionCmd" Before="ProvisionHardwareOffline" Condition="NOT Installed" />
      <Custom Action="ProvisionHardwareOffline" After="InstallFiles" Condition="NOT Installed" />
    </InstallExecuteSequence>

    <Feature Id="MainFeature" Title="Open OCReader" Level="1">
      <ComponentGroupRef Id="AppFiles" />
      <ComponentRef Id="ProvisionScriptComp" />
      <ComponentRef Id="AppShortcuts" />
      <ComponentRef Id="DesktopShortcutComp" />
    </Feature>
  </Package>
</Wix>
"""


WIX_PINNED_VERSION = "5.0.2"


def find_wix() -> str:
    wix = shutil.which("wix")
    if wix:
        return wix
    user_tools = Path.home() / ".dotnet" / "tools" / "wix.exe"
    if user_tools.exists():
        return str(user_tools)
    return ""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_wix_installed() -> str:
    """
    Localiza WiX Toolset v5 y, si no está instalado, lo descarga e instala automáticamente
    vía `dotnet tool` fijando versión oficial firmada por NuGet (.NET Foundation) + extensión Util.
    """
    wix_exe = find_wix()
    if wix_exe:
        # Asegurar extensión WixToolset.Util.wixext
        subprocess.run(
            [wix_exe, "extension", "add", "-g", f"WixToolset.Util.wixext/{WIX_PINNED_VERSION}"],
            capture_output=True,
            check=False,
        )
        return wix_exe

    dotnet_exe = shutil.which("dotnet")
    if not dotnet_exe:
        print("\n[ERROR] No se encontró 'dotnet' en el sistema para instalar WiX Toolset v5 automáticamente.")
        print("Descarga el instalador oficial de .NET SDK (Microsoft) desde:")
        print("  https://dotnet.microsoft.com/download")
        print("O instala con winget: winget install Microsoft.DotNet.SDK.8")
        sys.exit(1)

    print(f"\n[WiX] WiX Toolset v5 no detectado. Instalando versión oficial fijada ({WIX_PINNED_VERSION}) vía NuGet...")
    res = subprocess.run(
        [dotnet_exe, "tool", "install", "--global", "wix", "--version", WIX_PINNED_VERSION],
        check=False,
    )
    if res.returncode != 0:
        print("[WiX] Reintentando con la última versión oficial estable de WiX...")
        res = subprocess.run([dotnet_exe, "tool", "install", "--global", "wix"], check=False)
        if res.returncode != 0:
            print("[ERROR] No se pudo instalar WiX Toolset automáticamente.", file=sys.stderr)
            sys.exit(res.returncode)

    wix_exe = find_wix()
    if not wix_exe:
        print("[ERROR] WiX se instaló pero no se localizó wix.exe en PATH ni en ~/.dotnet/tools.", file=sys.stderr)
        sys.exit(1)

    print(f"[WiX] ✓ WiX instalado: {wix_exe} (SHA-256: {_sha256_file(Path(wix_exe))[:16]}...)")
    print(f"[WiX] Instalando extensión oficial WixToolset.Util.wixext/{WIX_PINNED_VERSION}...")
    ext_res = subprocess.run(
        [wix_exe, "extension", "add", "-g", f"WixToolset.Util.wixext/{WIX_PINNED_VERSION}"],
        check=False,
    )
    if ext_res.returncode != 0:
        subprocess.run([wix_exe, "extension", "add", "-g", "WixToolset.Util.wixext"], check=False)

    return wix_exe


def main():
    parser = argparse.ArgumentParser(description="Genera el instalador empresarial Open_OCReader.msi (WiX v5).")
    parser.add_argument(
        "--with-offline-repo",
        action="store_true",
        help="Descarga también la carpeta compañera offline_repo/ (binarios Vulkan+CPU y modelos 4B+2B+BGE-M3).",
    )
    parser.add_argument(
        "--compiler",
        choices=["auto", "pyinstaller", "nuitka"],
        default="pyinstaller",
        help="Compilador para generar dist/Open_OCReader/ si aún no existe (por defecto: pyinstaller ~1-2 min).",
    )
    args = parser.parse_args()

    kit_dir = BASE_DIR / "dist" / "Open_OCReader_Enterprise_Kit"
    kit_dir.mkdir(parents=True, exist_ok=True)
    app_dist_dir = BASE_DIR / "dist" / "Open_OCReader"

    # 1. Compilar ejecutable base si no existe
    if not (app_dist_dir / "Open_OCReader.exe").exists():
        print("[1/3] Compilando ejecutable base Open_OCReader.exe...")
        rc = subprocess.run(
            [sys.executable, str(BASE_DIR / "scripts" / "windows" / "build_exe.py"), "--compiler", args.compiler],
            cwd=str(BASE_DIR),
        ).returncode
        if rc != 0:
            sys.exit(rc)

    # 2. Preparar offline_repo universal si se solicitó
    if args.with_offline_repo:
        print("\n[2/3] Preparando repositorio offline universal (GPU Vulkan + CPU + modelos 4B/2B/BGE-M3)...")
        rc = subprocess.run(
            [
                sys.executable,
                str(BASE_DIR / "scripts" / "windows" / "prepare_offline_repo.py"),
                "--output",
                str(kit_dir / "offline_repo"),
            ],
            cwd=str(BASE_DIR),
        ).returncode
        if rc != 0:
            sys.exit(rc)

    # 3. Verificar o instalar automáticamente WiX Toolset v5 (versión oficial fijada)
    wix_exe = ensure_wix_installed()

    wxs_path = BASE_DIR / "build" / "Open_OCReader.wxs"
    wxs_path.parent.mkdir(parents=True, exist_ok=True)
    ico_path = BASE_DIR / "ico" / "Open_OCReader.ico"
    provision_ps1 = BASE_DIR / "scripts" / "windows" / "provision_from_offline_repo.ps1"

    # Normalizar versión a X.Y.Z para MSI
    ver_parts = (__version__.split(".") + ["0", "0", "0"])[:3]
    msi_version = ".".join(p for p in ver_parts)

    wxs_content = WXS_TEMPLATE.format(
        version=msi_version,
        ico_path=str(ico_path),
        dist_dir=str(app_dist_dir),
        provision_ps1=str(provision_ps1),
    )
    wxs_path.write_text(wxs_content, encoding="utf-8")

    msi_out = kit_dir / f"Open_OCReader_{msi_version}_x64.msi"
    print(f"\n[3/3] Generando instalador MSI empresarial -> {msi_out} ...")
    cmd = [
        wix_exe,
        "build",
        "-arch", "x64",
        "-ext", "WixToolset.Util.wixext",
        str(wxs_path),
        "-o", str(msi_out),
    ]
    res = subprocess.run(cmd, cwd=str(BASE_DIR))
    if res.returncode != 0:
        sys.exit(res.returncode)

    # Generar SHA256SUMS.txt del MSI
    h = hashlib.sha256()
    with open(msi_out, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    (kit_dir / "SHA256SUMS.txt").write_text(f"{h.hexdigest()}  {msi_out.name}\n", encoding="utf-8")

    print("\n" + "=" * 68)
    print(f"✓ Instalador MSI generado con éxito: {msi_out}")
    print(f"  Despliegue silencioso GPO/Intune: msiexec /i \"{msi_out.name}\" /qn")
    print("=" * 68)


if __name__ == "__main__":
    main()
