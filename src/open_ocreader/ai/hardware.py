"""
Detección automática de hardware (CPU, GPU Vulkan, CUDA, Metal) y selección
del perfil óptimo de ejecución para llama.cpp en Windows, Linux y macOS.
Inspirado en la arquitectura de detección nativa de GuarIdA.
"""

import ctypes
import os
import platform
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class HardwareProfile:
    """Perfil de hardware detectado para seleccionar el binario y flags óptimos."""
    os_name: str              # 'Windows', 'Linux', 'Darwin'
    arch: str                 # 'x64', 'arm64'
    cpu_cores: int
    has_vulkan: bool
    has_cuda: bool
    has_metal: bool
    backend: str              # 'vulkan', 'metal', 'cpu'
    platform_asset_key: str   # Ej: 'win-vulkan-x64', 'win-cpu-x64', 'ubuntu-vulkan-x64', 'macos-arm64'
    n_gpu_layers: int         # 99 si hay aceleración GPU, 0 si es solo CPU


def detect_vulkan_support() -> bool:
    """Comprueba si el sistema dispone de runtime Vulkan operativo."""
    try:
        sistema = platform.system()
        if sistema == "Windows":
            ctypes.cdll.LoadLibrary("vulkan-1.dll")
            return True
        elif sistema == "Linux":
            ctypes.cdll.LoadLibrary("libvulkan.so.1")
            return True
    except Exception:
        pass
    return False


def detect_cuda_support() -> bool:
    """Comprueba si hay GPU NVIDIA CUDA disponible."""
    if shutil.which("nvidia-smi"):
        return True
    try:
        sistema = platform.system()
        if sistema == "Windows":
            ctypes.cdll.LoadLibrary("nvcuda.dll")
            return True
        elif sistema == "Linux":
            ctypes.cdll.LoadLibrary("libcuda.so.1")
            return True
    except Exception:
        pass
    return False


def get_hardware_profile(force_cpu: bool = False) -> HardwareProfile:
    """Analiza el sistema actual y devuelve el perfil de ejecución óptimo."""
    sistema = platform.system()
    machine = platform.machine().lower()
    is_arm64 = "arm" in machine or "aarch64" in machine
    arch = "arm64" if is_arm64 else "x64"
    cores = os.cpu_count() or 4

    has_vulkan = False if force_cpu else detect_vulkan_support()
    has_cuda = False if force_cpu else detect_cuda_support()
    has_metal = (sistema == "Darwin" and is_arm64 and not force_cpu)

    if sistema == "Windows":
        if has_vulkan and not is_arm64:
            backend = "vulkan"
            asset_key = "win-vulkan-x64"
            ngl = 99
        else:
            backend = "cpu"
            asset_key = f"win-cpu-{arch}"
            ngl = 0
    elif sistema == "Linux":
        if has_vulkan:
            backend = "vulkan"
            asset_key = f"ubuntu-vulkan-{arch}"
            ngl = 99
        else:
            backend = "cpu"
            asset_key = f"ubuntu-{arch}"
            ngl = 0
    elif sistema == "Darwin":
        if is_arm64:
            backend = "metal"
            asset_key = "macos-arm64"
            ngl = 99
        else:
            backend = "cpu"
            asset_key = "macos-x64"
            ngl = 0
    else:
        backend = "cpu"
        asset_key = f"ubuntu-{arch}"
        ngl = 0

    return HardwareProfile(
        os_name=sistema,
        arch=arch,
        cpu_cores=cores,
        has_vulkan=has_vulkan,
        has_cuda=has_cuda,
        has_metal=has_metal,
        backend=backend,
        platform_asset_key=asset_key,
        n_gpu_layers=ngl,
    )


def find_free_port(host: str = "127.0.0.1", preferred: int = 8089) -> int:
    """Devuelve el puerto preferido si está libre o busca uno alternativo disponible."""
    for port in [preferred] + list(range(preferred + 1, preferred + 25)):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.15)
                if s.connect_ex((host, port)) == 0:
                    continue
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s_bind:
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    s_bind.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                s_bind.bind((host, port))
                return port
        except OSError:
            continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s_ef:
        s_ef.bind((host, 0))
        return int(s_ef.getsockname()[1])


def query_binary_help(binary_path: Path) -> str:
    """Consulta los flags soportados por el binario llama-server mediante --help."""
    if not binary_path.is_file():
        return ""
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        proc = subprocess.run(
            [str(binary_path), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=creationflags,
            check=False,
        )
        return (proc.stdout or "") + "\n" + (proc.stderr or "")
    except Exception:
        return ""
