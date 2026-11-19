"""
Detección automática de hardware (CPU, RAM, GPU Vulkan/CUDA/Metal) y selección
del perfil óptimo de modelos de IA (VLM principal + Embeddings AST + n_ctx)
para llama.cpp en Windows, Linux y macOS.
Inspirado en la arquitectura de observación de hardware de GuarIdA.
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
from typing import Tuple

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False


@dataclass(frozen=True)
class AITierSpec:
    """Especificación de modelos de IA, capacidades y límites seguros vinculados al hardware."""
    tier_name: str              # 'ocr_only', 'ultra_light', 'light', 'standard', 'pro'
    vlm_enabled: bool
    vlm_label: str
    vlm_repo: str
    vlm_filename: str
    mmproj_filename: str
    embed_enabled: bool
    embed_label: str
    embed_repo: str
    embed_filename: str
    embed_keep_resident: bool
    recommended_n_ctx: int
    max_chat_docs: int
    locked_features_hint: str = ""


@dataclass(frozen=True)
class HardwareProfile:
    """Perfil de hardware detectado para seleccionar binario, flags y modelos óptimos."""
    os_name: str              # 'Windows', 'Linux', 'Darwin'
    arch: str                 # 'x64', 'arm64'
    cpu_cores: int
    ram_total_gb: float
    ram_available_gb: float
    has_vulkan: bool
    has_cuda: bool
    has_metal: bool
    backend: str              # 'vulkan', 'metal', 'cpu'
    platform_asset_key: str   # Ej: 'win-vulkan-x64', 'win-cpu-x64', 'ubuntu-vulkan-x64', 'macos-arm64'
    n_gpu_layers: int         # 99 si hay aceleración GPU, 0 si es solo CPU
    ai_tier: AITierSpec


def detect_ram_gb() -> Tuple[float, float]:
    """Devuelve (ram_total_gb, ram_available_gb) usando psutil o respaldo nativo del SO."""
    if HAS_PSUTIL and psutil is not None:
        vm = psutil.virtual_memory()
        return round(vm.total / (1024 ** 3), 2), round(vm.available / (1024 ** 3), 2)

    if platform.system() == "Windows":
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return round(stat.ullTotalPhys / (1024 ** 3), 2), round(stat.ullAvailPhys / (1024 ** 3), 2)
        except Exception:
            pass

    return 8.0, 4.0


def has_enough_ram_for_embeddings(min_free_gb: float = 1.2) -> bool:
    """Comprobación anti-OOM en tiempo real antes de levantar el servidor de embeddings."""
    _total, avail = detect_ram_gb()
    return avail >= min_free_gb


def select_ai_tier(ram_total_gb: float, has_gpu: bool) -> AITierSpec:
    """
    Vincula toda la pila de IA (VLM principal + Embeddings AST + Chat multi-documento + n_ctx)
    a la capacidad real de memoria y aceleración del equipo.
    """
    if ram_total_gb >= 15.0:
        return AITierSpec(
            tier_name="pro",
            vlm_enabled=True,
            vlm_label="Qwen3-VL-4B (Q4_K_M)",
            vlm_repo="Qwen/Qwen3-VL-4B-Instruct-GGUF",
            vlm_filename="Qwen3VL-4B-Instruct-Q4_K_M.gguf",
            mmproj_filename="mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf",
            embed_enabled=True,
            embed_label="BGE-M3 (Q4_K_M, multilingüe)",
            embed_repo="gpustack/bge-m3-GGUF",
            embed_filename="bge-m3-Q4_K_M.gguf",
            embed_keep_resident=True,
            recommended_n_ctx=8192,
            max_chat_docs=50,
            locked_features_hint="",
        )
    elif ram_total_gb >= 10.0:
        return AITierSpec(
            tier_name="standard",
            vlm_enabled=True,
            vlm_label="Qwen3-VL-4B (Q4_K_M)",
            vlm_repo="Qwen/Qwen3-VL-4B-Instruct-GGUF",
            vlm_filename="Qwen3VL-4B-Instruct-Q4_K_M.gguf",
            mmproj_filename="mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf",
            embed_enabled=True,
            embed_label="BGE-M3 (Q4_K_M, bajo demanda)",
            embed_repo="gpustack/bge-m3-GGUF",
            embed_filename="bge-m3-Q4_K_M.gguf",
            embed_keep_resident=False,
            recommended_n_ctx=8192,
            max_chat_docs=25,
            locked_features_hint="",
        )
    elif ram_total_gb >= 6.0:
        return AITierSpec(
            tier_name="light",
            vlm_enabled=True,
            vlm_label="Qwen3-VL-2B (Q4_K_M, equipo modesto)",
            vlm_repo="Qwen/Qwen3-VL-2B-Instruct-GGUF",
            vlm_filename="Qwen3VL-2B-Instruct-Q4_K_M.gguf",
            mmproj_filename="mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf",
            embed_enabled=True,
            embed_label="BGE-M3 (Q4_K_M, bajo demanda)",
            embed_repo="gpustack/bge-m3-GGUF",
            embed_filename="bge-m3-Q4_K_M.gguf",
            embed_keep_resident=False,
            recommended_n_ctx=6144,
            max_chat_docs=10,
            locked_features_hint="Con ≥10 GB RAM se activa automáticamente Qwen3-VL-4B (mayor precisión) y hasta 25-50 documentos en chat.",
        )
    elif ram_total_gb >= 4.0:
        return AITierSpec(
            tier_name="ultra_light",
            vlm_enabled=True,
            vlm_label="Qwen3-VL-2B (Q4_K_M, memoria reducida)",
            vlm_repo="Qwen/Qwen3-VL-2B-Instruct-GGUF",
            vlm_filename="Qwen3VL-2B-Instruct-Q4_K_M.gguf",
            mmproj_filename="mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf",
            embed_enabled=False,
            embed_label="Solo BM25 + AST (0 MB extra)",
            embed_repo="",
            embed_filename="",
            embed_keep_resident=False,
            recommended_n_ctx=4096,
            max_chat_docs=5,
            locked_features_hint="Con ≥6 GB RAM se desbloquean embeddings semánticos BGE-M3 (sinónimos y búsqueda multilingüe); con ≥10 GB RAM, Qwen3-VL-4B.",
        )
    else:
        return AITierSpec(
            tier_name="ocr_only",
            vlm_enabled=False,
            vlm_label="No disponible (<4 GB RAM)",
            vlm_repo="",
            vlm_filename="",
            mmproj_filename="",
            embed_enabled=False,
            embed_label="No disponible (<4 GB RAM)",
            embed_repo="",
            embed_filename="",
            embed_keep_resident=False,
            recommended_n_ctx=0,
            max_chat_docs=0,
            locked_features_hint=(
                "Tu equipo dispone de menos de 4 GB de RAM. Con un hardware más potente (≥6 GB RAM) "
                "podrás utilizar automáticamente: lectura de letra manuscrita (Qwen3-VL), resúmenes ejecutivos, "
                "traducción contextual a cualquier idioma, chat multi-documento con citas (BGE-M3 + AST) "
                "y refuerzo semántico de anonimización RGPD."
            ),
        )


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
    """Analiza el sistema actual y devuelve el perfil completo de ejecución y modelos IA."""
    sistema = platform.system()
    machine = platform.machine().lower()
    is_arm64 = "arm" in machine or "aarch64" in machine
    arch = "arm64" if is_arm64 else "x64"
    cores = os.cpu_count() or 4
    ram_total, ram_avail = detect_ram_gb()

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

    ai_tier = select_ai_tier(ram_total_gb=ram_total, has_gpu=(ngl > 0))

    return HardwareProfile(
        os_name=sistema,
        arch=arch,
        cpu_cores=cores,
        ram_total_gb=ram_total,
        ram_available_gb=ram_avail,
        has_vulkan=has_vulkan,
        has_cuda=has_cuda,
        has_metal=has_metal,
        backend=backend,
        platform_asset_key=asset_key,
        n_gpu_layers=ngl,
        ai_tier=ai_tier,
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
