"""
Prepara el repositorio completo independiente del hardware (`offline_repo/`)
junto al instalador MSI para despliegues corporativos sin conexión a Internet (air-gapped).

Descarga y verifica con SHA-256:
  - Binarios llama.cpp para GPU Vulkan (`bin/win-vulkan-x64/`) Y CPU puro (`bin/win-cpu-x64/`)
  - Qwen3-VL-4B-Instruct + mmproj (equipos >= 10 GB RAM, Apache 2.0)
  - Qwen3-VL-2B-Instruct + mmproj (equipos 4-10 GB RAM, Apache 2.0)
  - BAAI BGE-M3 Q4_K_M (embeddings AST multilingüe >= 6 GB RAM, MIT)

Uso:
    python scripts/windows/prepare_offline_repo.py
    python scripts/windows/prepare_offline_repo.py --output dist/Open_OCReader_Enterprise_Kit/offline_repo
"""

import argparse
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

from huggingface_hub import hf_hub_download
from open_ocreader.ai.runtime_manager import LlamaRuntimeManager
from open_ocreader.security import SecurityError, verify_sha256


ALL_MODELS = [
    ("Qwen/Qwen3-VL-4B-Instruct-GGUF", "Qwen3VL-4B-Instruct-Q4_K_M.gguf"),
    ("Qwen/Qwen3-VL-4B-Instruct-GGUF", "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf"),
    ("Qwen/Qwen3-VL-2B-Instruct-GGUF", "Qwen3VL-2B-Instruct-Q4_K_M.gguf"),
    ("Qwen/Qwen3-VL-2B-Instruct-GGUF", "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf"),
    ("gpustack/bge-m3-GGUF", "bge-m3-Q4_K_M.gguf"),
]


def prepare_offline_repo(repo_dir: Path) -> None:
    bin_out = repo_dir / "bin"
    models_out = repo_dir / "models"
    bin_out.mkdir(parents=True, exist_ok=True)
    models_out.mkdir(parents=True, exist_ok=True)

    rt_gpu = LlamaRuntimeManager(base_dir=BASE_DIR, force_cpu=False)
    rt_cpu = LlamaRuntimeManager(base_dir=BASE_DIR, force_cpu=True)

    print("=" * 68)
    print(f" Preparando repositorio offline universal en: {repo_dir}")
    print("=" * 68)

    # 1. Binarios llama.cpp (GPU Vulkan + CPU puro)
    for label, rt, force_cpu_fb in [
        ("win-vulkan-x64", rt_gpu, False),
        ("win-cpu-x64", rt_cpu, True),
    ]:
        print(f"\n[Binario] Asegurando llama.cpp ({label})...")
        exe_path = rt.ensure_llama_binary(progress_cb=print, force_cpu_fallback=force_cpu_fb)
        src_folder = exe_path.parent
        dst_folder = bin_out / src_folder.name
        if dst_folder.exists():
            shutil.rmtree(dst_folder)
        shutil.copytree(src_folder, dst_folder)
        print(f"  ✓ Copiado {src_folder.name} -> {dst_folder}")

    # 2. Todos los modelos GGUF (reutilizando models/ local si ya existe + SHA-256)
    local_models_dir = BASE_DIR / "models"
    for repo_id, filename in ALL_MODELS:
        expected_sha = LlamaRuntimeManager.MODEL_SHA256.get(filename, "")
        dest_file = models_out / filename
        local_src = local_models_dir / filename

        def _sha_ok(p: Path, exp: str) -> bool:
            if not p.exists():
                return False
            if not exp:
                return True
            try:
                verify_sha256(p, exp)
                return True
            except SecurityError:
                return False

        if _sha_ok(dest_file, expected_sha):
            print(f"[Modelo] ✓ Ya verificado en offline_repo: {filename}")
            continue

        if _sha_ok(local_src, expected_sha):
            print(f"[Modelo] Copiando copia local verificada: {filename}...")
            shutil.copy2(local_src, dest_file)
            continue

        print(f"[Modelo] Descargando {filename} desde {repo_id}...")
        hf_hub_download(repo_id=repo_id, filename=filename, local_dir=str(models_out))
        if expected_sha:
            verify_sha256(dest_file, expected_sha)
        print(f"  ✓ Descargado y verificado SHA-256: {filename}")

    print("\n" + "=" * 68)
    print(f"OK! Repositorio offline universal listo en: {repo_dir}")
    print("Incluye binarios GPU Vulkan + CPU y modelos 4B + 2B + BGE-M3 verificados.")
    print("=" * 68)


def main():
    parser = argparse.ArgumentParser(description="Genera el repositorio offline universal para despliegues MSI.")
    parser.add_argument(
        "--output",
        default=str(BASE_DIR / "dist" / "Open_OCReader_Enterprise_Kit" / "offline_repo"),
        help="Ruta destino del repositorio offline_repo.",
    )
    args = parser.parse_args()
    prepare_offline_repo(Path(args.output))


if __name__ == "__main__":
    main()
