"""
Gestor portable y multiplataforma de llama.cpp y modelos GGUF (Qwen3-VL).
Detecta automáticamente el hardware (GPU Vulkan/Metal o CPU) y el sistema operativo
(Windows, Linux, macOS), descarga los binarios y modelos según la fuente elegida
(Página Oficial o GitHub) y aplica las optimizaciones seguras de GuarIdA.
"""

import atexit
import base64
import io
import os
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import requests
from huggingface_hub import hf_hub_download
from PIL import Image
from ..logger import get_logger, get_logs_dir
from ..security import (
    SecurityError,
    generate_token,
    safe_extract_tar,
    safe_extract_zip,
    verify_sha256,
    write_private_secret_file,
)
from .hardware import (
    HardwareProfile,
    find_free_port,
    get_hardware_profile,
    has_enough_ram_for_embeddings,
    query_binary_help,
)

logger = get_logger("ai.runtime")


class LlamaRuntimeManager:
    """Gestiona binarios portables de llama.cpp (CPU/GPU) y modelos GGUF locales."""

    GITHUB_LLAMA_RELEASES_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=8"
    GITHUB_PROJECT_RELEASES_API = "https://api.github.com/repos/Ydalgo/Open-OCReader/releases/latest"
    HF_REPO_ID = "Qwen/Qwen3-VL-4B-Instruct-GGUF"
    MODEL_FILENAME = "Qwen3VL-4B-Instruct-Q4_K_M.gguf"
    MMPROJ_FILENAME = "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf"

    # Hashes SHA-256 oficiales verificados (Hugging Face LFS) de todos los modelos soportados.
    # Cualquier descarga (Hugging Face o GitHub) que no coincida se rechaza y se elimina.
    MODEL_SHA256 = {
        # VLM Principal (Perfiles standard / pro — Apache 2.0)
        "Qwen3VL-4B-Instruct-Q4_K_M.gguf": "66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a",
        "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf": "30ba2c7dd3127a4561b6cba9d13d0f711c91bdb38742e2f56d73c8cb596bd06d",
        # VLM Ligero (Perfiles light / ultra_light — Apache 2.0)
        "Qwen3VL-2B-Instruct-Q4_K_M.gguf": "089d75c52f4b7ffc56ba998ffc50aae89fcafc755f9e7208aacca281dca6c2ae",
        "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf": "f9a68fabba69c3b81e153367b2c7521030b0fa8bb0de400c9599c8e6725f9c82",
        # Embeddings Multilingüe AST Híbrido (BAAI BGE-M3 — MIT)
        "bge-m3-Q4_K_M.gguf": "6d39681b26c61279ac1f82db35a04a05009e94c415b51c858ff571489a82fc06",
    }

    _instance: Optional["LlamaRuntimeManager"] = None

    def __init__(self, base_dir: Optional[Path] = None, force_cpu: bool = False):
        from ..paths import get_app_base_dir, resolve_asset_dir

        if base_dir is None:
            self.base_dir = get_app_base_dir()
        else:
            self.base_dir = Path(base_dir)

        self.hw: HardwareProfile = get_hardware_profile(force_cpu=force_cpu)
        self.platform_key = self.hw.platform_asset_key

        # Vincular modelos VLM y Embeddings al perfil de hardware detectado
        self.tier = self.hw.ai_tier
        self.HF_REPO_ID = self.tier.vlm_repo
        self.MODEL_FILENAME = self.tier.vlm_filename
        self.MMPROJ_FILENAME = self.tier.mmproj_filename

        if base_dir is None:
            self.bin_root = resolve_asset_dir("bin")
            self.models_dir = resolve_asset_dir("models")
        else:
            self.bin_root = self.base_dir / "bin"
            self.models_dir = self.base_dir / "models"

        self.bin_dir = self.bin_root / self.platform_key

        self.server_process: Optional[subprocess.Popen] = None
        self.server_log_file = None
        self._api_key_file: Optional[Path] = None
        self._server_api_key = generate_token()
        self.port = 8089

        # Servidor ligero de embeddings (CPU -ngl 0, puerto independiente, vinculado al perfil de hardware)
        self.embed_process: Optional[subprocess.Popen] = None
        self.embed_log_file = None
        self.embed_port: int = 8095
        self._embed_api_key = generate_token()
        self._embed_api_key_file: Optional[Path] = None

        self.preferred_model_source = "official"  # 'official' | 'github'

        logger.info(
            f"LlamaRuntimeManager listo | SO: {self.hw.os_name} ({self.hw.arch}) | "
            f"RAM: {self.hw.ram_total_gb:.1f} GB ({self.hw.ram_available_gb:.1f} GB libres) | "
            f"Backend: {self.hw.backend.upper()} | Perfil IA: {self.tier.tier_name.upper()} "
            f"[{self.tier.vlm_label} + {self.tier.embed_label}]"
        )
        atexit.register(self.stop_server)

    @classmethod
    def get_instance(cls) -> "LlamaRuntimeManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def server_executable(self) -> Path:
        exe_name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
        return self.bin_dir / exe_name

    @property
    def model_path(self) -> Path:
        return self.models_dir / self.MODEL_FILENAME

    @property
    def mmproj_path(self) -> Path:
        return self.models_dir / self.MMPROJ_FILENAME

    def is_models_present(self) -> bool:
        """Comprueba si los ficheros del modelo Qwen3-VL ya existen localmente."""
        return self.model_path.exists() and self.mmproj_path.exists()

    def check_portable_hardware_mismatch(self) -> Optional[str]:
        """
        Detecta si una copia portable (USB / intranet sin Internet) trae modelos o binarios
        preparados para un hardware distinto al del equipo actual.
        En entornos aislados (air-gapped), intenta reutilizar el modelo local disponible
        y devuelve un aviso claro para el usuario.
        """
        warnings_list: List[str] = []

        # 1. Comprobar si el modelo ideal del perfil falta pero existe otro modelo Qwen3-VL ya descargado
        if self.tier.vlm_enabled and not self.is_models_present() and self.models_dir.exists():
            alt_pairs = [
                ("Qwen3VL-4B-Instruct-Q4_K_M.gguf", "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf", "Qwen3-VL-4B"),
                ("Qwen3VL-2B-Instruct-Q4_K_M.gguf", "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf", "Qwen3-VL-2B"),
            ]
            for m_f, mm_f, lbl in alt_pairs:
                if (self.models_dir / m_f).exists() and (self.models_dir / mm_f).exists():
                    expected_lbl = self.tier.vlm_label
                    self.MODEL_FILENAME = m_f
                    self.MMPROJ_FILENAME = mm_f
                    warnings_list.append(
                        f"Copia portable adaptada a otro hardware: se encontró '{lbl}' en models/ "
                        f"(este equipo recomienda '{expected_lbl}'). Se reutilizará en modo offline, "
                        f"pero puede haber pérdida de rendimiento o memoria ajustada."
                    )
                    break

        # 2. Comprobar si el binario de llama.cpp en bin/ corresponde a otro backend (ej. Vulkan vs CPU)
        if self.tier.vlm_enabled and not self.server_executable.exists() and self.bin_root.exists():
            other_bins = [p.name for p in self.bin_root.iterdir() if p.is_dir()]
            if other_bins:
                warnings_list.append(
                    f"Binario de llama.cpp en bin/ preparado para {', '.join(other_bins)}, "
                    f"pero este equipo requiere '{self.platform_key}'. Sin Internet, la IA puede fallar."
                )

        if warnings_list:
            msg = "⚠️ Aviso portable/hardware distinto: " + " | ".join(warnings_list)
            logger.warning(msg)
            return msg
        return None

    def is_ready(self) -> bool:
        """Comprueba si binario de llama.cpp y modelos existen localmente."""
        return self.server_executable.exists() and self.is_models_present()

    def ensure_llama_binary(
        self,
        source: Optional[str] = None,
        progress_cb: Optional[Callable[[str], None]] = None,
        force_cpu_fallback: bool = False,
    ) -> Path:
        """
        Descarga y extrae el binario de llama.cpp adecuado al hardware y SO actual.
        Soporta fuente oficial (ggml-org/llama.cpp) o proyecto GitHub (Ydalgo/Open-OCReader).
        """
        target_key = self.platform_key
        if force_cpu_fallback:
            if self.hw.os_name == "Windows":
                target_key = f"win-cpu-{self.hw.arch}"
            elif self.hw.os_name == "Linux":
                target_key = f"ubuntu-{self.hw.arch}"
            self.bin_dir = self.bin_root / target_key

        if self.server_executable.exists():
            return self.server_executable

        selected_source = source or self.preferred_model_source
        asset_url = None
        asset_name = None
        asset_digest = None
        tag_name = None

        # 1. Intentar desde el proyecto GitHub si el usuario lo eligió
        if selected_source == "github":
            if progress_cb:
                progress_cb(f"Buscando binario '{target_key}' en Releases de Ydalgo/Open-OCReader...")
            try:
                r = requests.get(self.GITHUB_PROJECT_RELEASES_API, timeout=15)
                if r.status_code == 200:
                    rel = r.json()
                    for asset in rel.get("assets", []):
                        if f"-bin-{target_key}." in asset["name"]:
                            asset_url = asset["browser_download_url"]
                            asset_name = asset["name"]
                            asset_digest = asset.get("digest")
                            tag_name = rel.get("tag_name")
                            break
            except Exception as e:
                logger.warning(f"No se pudo consultar GitHub Releases del proyecto: {e}")

        # 2. Fuente oficial ggml-org/llama.cpp (por defecto o respaldo automático)
        if not asset_url:
            if progress_cb:
                progress_cb(f"Buscando binario oficial de llama.cpp para {target_key}...")
            resp = requests.get(self.GITHUB_LLAMA_RELEASES_API, timeout=20)
            resp.raise_for_status()
            releases = resp.json()

            for rel in releases:
                for asset in rel.get("assets", []):
                    name = asset["name"]
                    if f"-bin-{target_key}." in name:
                        asset_url = asset["browser_download_url"]
                        asset_name = name
                        asset_digest = asset.get("digest")
                        tag_name = rel.get("tag_name")
                        break
                if asset_url:
                    break

        if not asset_url:
            raise RuntimeError(
                f"No se encontró un binario precompilado de llama.cpp para '{target_key}'."
            )

        self.bin_dir.mkdir(parents=True, exist_ok=True)
        archive_path = self.bin_dir / asset_name

        if progress_cb:
            progress_cb(f"Descargando llama.cpp ({tag_name}): {asset_name}...")

        self._download_file_stream(asset_url, archive_path, progress_cb=progress_cb, label=asset_name)

        # Verificar integridad criptográfica SHA-256 si GitHub publicó el digest
        if asset_digest:
            if progress_cb:
                progress_cb("Verificando firma SHA-256 del paquete descargado...")
            verify_sha256(archive_path, asset_digest)
            logger.info(f"Integridad SHA-256 verificada para {asset_name}.")

        if progress_cb:
            progress_cb("Extrayendo binarios portables de forma segura...")

        extract_tmp = self.bin_dir / "_tmp_extract"
        if extract_tmp.exists():
            shutil.rmtree(extract_tmp)
        extract_tmp.mkdir(parents=True, exist_ok=True)

        if asset_name.endswith(".zip"):
            safe_extract_zip(archive_path, extract_tmp)
        elif asset_name.endswith(".tar.gz"):
            safe_extract_tar(archive_path, extract_tmp)

        target_name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
        found_dir = None
        for root_p, _dirs, files in os.walk(extract_tmp):
            if target_name in files:
                found_dir = Path(root_p)
                break

        if not found_dir:
            raise RuntimeError(f"No se encontró '{target_name}' dentro del paquete {asset_name}.")

        for item in found_dir.iterdir():
            dest = self.bin_dir / item.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            shutil.move(str(item), str(dest))

        if sys.platform != "win32":
            for exec_candidate in self.bin_dir.iterdir():
                if exec_candidate.is_file() and (
                    "llama-" in exec_candidate.name or exec_candidate.suffix in {".so", ".dylib", ""}
                ):
                    os.chmod(exec_candidate, 0o755)

        shutil.rmtree(extract_tmp, ignore_errors=True)
        archive_path.unlink(missing_ok=True)

        # Guardar versión instalada para futuras comprobaciones de actualización
        if tag_name:
            try:
                (self.bin_dir / "version.txt").write_text(str(tag_name), encoding="utf-8")
            except Exception:
                pass

        if progress_cb:
            progress_cb(f"✓ llama.cpp ({target_key} - {tag_name}) listo en {self.bin_dir}")

        return self.server_executable

    def check_llama_update(self) -> Dict[str, Any]:
        """Comprueba si existe una versión más reciente de llama.cpp en GitHub Releases."""
        version_file = self.bin_dir / "version.txt"
        installed = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "desconocida"
        try:
            resp = requests.get(self.GITHUB_LLAMA_RELEASES_API, timeout=15)
            resp.raise_for_status()
            for rel in resp.json():
                for asset in rel.get("assets", []):
                    if f"-bin-{self.platform_key}." in asset["name"]:
                        latest = rel.get("tag_name", "")
                        return {
                            "installed": installed,
                            "latest": latest,
                            "update_available": bool(latest and latest != installed),
                        }
        except Exception as e:
            logger.warning(f"No se pudo consultar actualizaciones de llama.cpp: {e}")
        return {"installed": installed, "latest": "error", "update_available": False}

    def ensure_models(
        self,
        source: Optional[str] = None,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Descarga Qwen3-VL-4B-Instruct (Q4_K_M) y su proyector visual mmproj si no existen."""
        if self.is_models_present():
            return

        selected_source = source or self.preferred_model_source
        self.models_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Descargando modelos desde fuente: {selected_source}")

        if selected_source == "github":
            self._download_models_from_github(progress_cb=progress_cb)
        else:
            self._download_models_from_huggingface(progress_cb=progress_cb)

        # Verificar integridad SHA-256 de ambos ficheros del modelo
        if progress_cb:
            progress_cb("Verificando integridad criptográfica SHA-256 de los modelos...")
        verify_sha256(self.model_path, self.MODEL_SHA256.get(self.MODEL_FILENAME))
        verify_sha256(self.mmproj_path, self.MODEL_SHA256.get(self.MMPROJ_FILENAME))
        logger.info("Integridad SHA-256 verificada para Qwen3-VL y mmproj.")

        if progress_cb:
            progress_cb("✓ Modelo Qwen3-VL-4B-Instruct listo para usar offline.")

    def _download_models_from_huggingface(self, progress_cb: Optional[Callable[[str], None]] = None):
        if not self.model_path.exists():
            if progress_cb:
                progress_cb(f"Descargando desde Hugging Face (Oficial): {self.MODEL_FILENAME}...")
            hf_hub_download(
                repo_id=self.HF_REPO_ID,
                filename=self.MODEL_FILENAME,
                local_dir=str(self.models_dir),
            )

        if not self.mmproj_path.exists():
            if progress_cb:
                progress_cb(f"Descargando proyector visual desde Hugging Face: {self.MMPROJ_FILENAME}...")
            hf_hub_download(
                repo_id=self.HF_REPO_ID,
                filename=self.MMPROJ_FILENAME,
                local_dir=str(self.models_dir),
            )

    def _download_models_from_github(self, progress_cb: Optional[Callable[[str], None]] = None):
        if progress_cb:
            progress_cb("Consultando Releases en GitHub (Ydalgo/Open-OCReader)...")

        resp = requests.get(self.GITHUB_PROJECT_RELEASES_API, timeout=20)
        if resp.status_code == 404:
            raise RuntimeError(
                "Aún no existe ninguna Release publicada con los modelos en GitHub (Ydalgo/Open-OCReader). "
                "Por favor, elige 'Página Oficial (Hugging Face)' para descargarlos."
            )
        resp.raise_for_status()
        release_data = resp.json()

        assets_map = {a["name"]: a["browser_download_url"] for a in release_data.get("assets", [])}
        missing = [f for f in (self.MODEL_FILENAME, self.MMPROJ_FILENAME) if f not in assets_map]
        if missing:
            raise RuntimeError(
                f"La Release de GitHub no contiene los ficheros del modelo ({', '.join(missing)}). "
                "Por favor, selecciona 'Página Oficial (Hugging Face)'."
            )

        for fname, dest in ((self.MODEL_FILENAME, self.model_path), (self.MMPROJ_FILENAME, self.mmproj_path)):
            if not dest.exists():
                self._download_file_stream(assets_map[fname], dest, progress_cb=progress_cb, label=fname)

    @staticmethod
    def _download_file_stream(
        url: str,
        dest_path: Path,
        progress_cb: Optional[Callable[[str], None]] = None,
        label: str = "",
    ):
        if not url.lower().startswith("https://"):
            raise SecurityError(f"Descarga bloqueada: solo se permiten URLs HTTPS ({url}).")
        tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            downloaded = 0
            last_pct = -1

            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 512):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0 and progress_cb:
                            pct = int((downloaded * 100) / total)
                            if pct != last_pct and pct % 5 == 0:
                                last_pct = pct
                                progress_cb(
                                    f"Descargando {label}: {pct}% ({downloaded // (1024*1024)} / {total // (1024*1024)} MB)"
                                )
        tmp_path.replace(dest_path)

    def _build_optimized_server_cmd(self, n_ctx: int, force_cpu: bool = False) -> List[str]:
        """Construye los argumentos optimizados (estilo GuarIdA) según hardware y --help del binario."""
        self.port = find_free_port(preferred=8089)
        cpu_threads = max(2, self.hw.cpu_cores - 1)
        ngl = 0 if force_cpu else self.hw.n_gpu_layers

        cmd = [
            str(self.server_executable),
            "-m",
            str(self.model_path),
            "--mmproj",
            str(self.mmproj_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "-c",
            str(n_ctx),
            "-t",
            str(cpu_threads),
            "-ngl",
            str(ngl),
        ]

        # Consultar --help para activar optimizaciones seguras solo si el binario las soporta
        help_txt = query_binary_help(self.server_executable)
        if "--threads-batch" in help_txt or "-tb" in help_txt:
            cmd.extend(["-tb", str(self.hw.cpu_cores)])
        if "--no-webui" in help_txt:
            cmd.append("--no-webui")
        if "--flash-attn" in help_txt or "-fa" in help_txt:
            cmd.extend(["-fa", "on"])
        if "--cache-reuse" in help_txt:
            cmd.extend(["--cache-reuse", "256"])
        if "--image-min-tokens" in help_txt:
            cmd.extend(["--image-min-tokens", "1024"])

        # Seguridad: exigir clave de sesión por fichero privado (no visible en línea de comandos)
        if "--api-key-file" in help_txt:
            self._api_key_file = write_private_secret_file(self._server_api_key, prefix="llama_key_")
            cmd.extend(["--api-key-file", str(self._api_key_file)])
        if "--cors-origins" in help_txt:
            cmd.extend(["--cors-origins", "http://127.0.0.1"])
        if "--no-cors-credentials" in help_txt:
            cmd.append("--no-cors-credentials")

        return cmd

    def start_server(
        self,
        n_ctx: Optional[int] = None,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Inicia llama-server con el binario óptimo (GPU Vulkan/Metal o CPU),
        optimizaciones GuarIdA y permanencia residente en memoria.
        Si la GPU falla al inicializar, hace fallback automático a CPU.
        """
        if n_ctx is None:
            n_ctx = self.tier.recommended_n_ctx
        if self.server_process is not None and self.server_process.poll() is None:
            return

        # Modo instancia única para llama-server: cerrar procesos huérfanos si no tenemos ya el servidor de embeddings activo
        if self.embed_process is None or self.embed_process.poll() is not None:
            self._kill_orphan_llama_servers()

        self.ensure_llama_binary(source=self.preferred_model_source, progress_cb=progress_cb)
        self.ensure_models(source=self.preferred_model_source, progress_cb=progress_cb)

        try:
            self._launch_server_process(n_ctx=n_ctx, force_cpu=False, progress_cb=progress_cb)
        except Exception as gpu_err:
            if self.hw.n_gpu_layers > 0:
                logger.warning(f"Fallo iniciando con GPU ({self.hw.backend}): {gpu_err}. Reintentando en modo CPU...")
                if progress_cb:
                    progress_cb("GPU no disponible para este modelo, cambiando a modo CPU seguro...")
                self.ensure_llama_binary(
                    source=self.preferred_model_source,
                    progress_cb=progress_cb,
                    force_cpu_fallback=True,
                )
                self._launch_server_process(n_ctx=n_ctx, force_cpu=True, progress_cb=progress_cb)
            else:
                raise

    def _launch_server_process(
        self,
        n_ctx: int,
        force_cpu: bool,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> None:
        cmd = self._build_optimized_server_cmd(n_ctx=n_ctx, force_cpu=force_cpu)
        mode_lbl = "CPU" if force_cpu or self.hw.n_gpu_layers == 0 else self.hw.backend.upper()

        if progress_cb:
            progress_cb(f"Cargando Qwen3-VL en memoria ({mode_lbl})...")

        logger.info(f"Iniciando llama-server [{mode_lbl}]: {' '.join(cmd)}")

        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        llama_log_path = get_logs_dir() / "llama_server.log"
        try:
            self.server_log_file = open(llama_log_path, "a", encoding="utf-8", errors="replace")
        except PermissionError:
            import tempfile
            llama_log_path = Path(tempfile.gettempdir()) / f"llama_server_{os.getpid()}.log"
            self.server_log_file = open(llama_log_path, "a", encoding="utf-8", errors="replace")

        self.server_process = subprocess.Popen(
            cmd,
            stdout=self.server_log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )

        health_url = f"http://127.0.0.1:{self.port}/health"
        deadline = time.time() + 120.0

        while time.time() < deadline:
            ret_code = self.server_process.poll()
            if ret_code is not None:
                self.stop_server()
                raise RuntimeError(f"llama-server cerró con código {ret_code}. Revisa {llama_log_path}")
            try:
                r = requests.get(health_url, timeout=1.5)
                if r.status_code == 200:
                    logger.info(f"llama-server residente [{mode_lbl}] activo en puerto {self.port} (PID {self.server_process.pid}).")
                    if progress_cb:
                        progress_cb(f"✓ Modelo cargado en memoria ({mode_lbl}).")
                    return
            except requests.RequestException:
                pass
            time.sleep(0.5)

        self.stop_server()
        raise TimeoutError(f"Timeout iniciando llama-server. Revisa {llama_log_path}")

    @staticmethod
    def _kill_orphan_llama_servers() -> None:
        """Cierra cualquier instancia huérfana de llama-server para garantizar modo instancia única."""
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/IM", "llama-server.exe"],
                    capture_output=True,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                subprocess.run(["pkill", "-f", "llama-server"], capture_output=True, check=False)
            time.sleep(0.35)
        except Exception:
            pass

    @property
    def embed_model_path(self) -> Optional[Path]:
        if not self.tier.embed_enabled or not self.tier.embed_filename:
            return None
        return self.models_dir / self.tier.embed_filename

    def ensure_embed_model(self, progress_cb: Optional[Callable[[str], None]] = None) -> Optional[Path]:
        """Descarga y verifica con SHA-256 el modelo de embeddings BGE-M3 si no existe localmente."""
        emb_p = self.embed_model_path
        if emb_p is None:
            return None

        expected_sha = self.MODEL_SHA256.get(self.tier.embed_filename, "")
        if emb_p.exists() and emb_p.stat().st_size > 10 * 1024 * 1024:
            if not expected_sha:
                return emb_p
            try:
                verify_sha256(emb_p, expected_sha)
                return emb_p
            except SecurityError:
                logger.warning(f"Integridad SHA-256 inválida en {emb_p.name}; re-descargando...")
                emb_p.unlink(missing_ok=True)

        self.models_dir.mkdir(parents=True, exist_ok=True)
        if progress_cb:
            progress_cb(f"Descargando modelo de embeddings '{self.tier.embed_label}' ({self.tier.embed_filename})...")
        try:
            hf_hub_download(
                repo_id=self.tier.embed_repo,
                filename=self.tier.embed_filename,
                local_dir=str(self.models_dir),
            )
            if emb_p.exists() and expected_sha:
                verify_sha256(emb_p, expected_sha)
            return emb_p if emb_p.exists() else None
        except Exception as e:
            logger.warning(f"No se pudo descargar/verificar el modelo de embeddings ({self.tier.embed_filename}): {e}")
            return None

    def stop_embed_server(self) -> None:
        if self.embed_process is not None:
            try:
                self.embed_process.terminate()
                self.embed_process.wait(timeout=4)
            except Exception:
                try:
                    self.embed_process.kill()
                except Exception:
                    pass
            finally:
                self.embed_process = None
        if self.embed_log_file is not None:
            try:
                self.embed_log_file.close()
            except Exception:
                pass
            self.embed_log_file = None
        if self._embed_api_key_file is not None:
            try:
                self._embed_api_key_file.unlink(missing_ok=True)
            except Exception:
                pass
            self._embed_api_key_file = None

    def _start_embed_server(self, progress_cb: Optional[Callable[[str], None]] = None) -> bool:
        """Arranca un servidor llama-server --embedding ligero en CPU (-ngl 0) sin tocar la VRAM."""
        if self.embed_process is not None and self.embed_process.poll() is None:
            return True
        if not self.tier.embed_enabled:
            return False
        if not has_enough_ram_for_embeddings(min_free_gb=1.2):
            logger.info("RAM libre insuficiente (<1.2 GB) para embeddings; usando BM25+AST puro.")
            return False

        self.ensure_llama_binary(source=self.preferred_model_source, progress_cb=progress_cb)
        emb_path = self.ensure_embed_model(progress_cb=progress_cb)
        if emb_path is None or not emb_path.exists():
            return False

        self.embed_port = find_free_port(preferred=8095)
        self._embed_api_key_file = write_private_secret_file(self._embed_api_key, prefix="llama_emb_key_")

        cmd = [
            str(self.server_executable),
            "-m", str(emb_path),
            "--embedding",
            "--pooling", "mean",
            "--host", "127.0.0.1",
            "--port", str(self.embed_port),
            "-c", "2048",
            "-ngl", "0",
            "-t", str(max(2, min(4, self.hw.cpu_cores - 1))),
            "--no-webui",
            "--api-key-file", str(self._embed_api_key_file),
        ]

        import tempfile
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        emb_log = Path(tempfile.gettempdir()) / f"llama_embed_{os.getpid()}.log"
        self.embed_log_file = open(emb_log, "a", encoding="utf-8", errors="replace")

        if progress_cb:
            progress_cb(f"Cargando modelo de embeddings '{self.tier.embed_label}' en CPU...")

        self.embed_process = subprocess.Popen(
            cmd,
            stdout=self.embed_log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )

        health_url = f"http://127.0.0.1:{self.embed_port}/health"
        deadline = time.time() + 45.0
        while time.time() < deadline:
            if self.embed_process.poll() is not None:
                self.stop_embed_server()
                return False
            try:
                r = requests.get(health_url, timeout=1.0)
                if r.status_code == 200:
                    return True
            except requests.RequestException:
                pass
            time.sleep(0.35)

        self.stop_embed_server()
        return False

    def embed_texts(
        self,
        texts: List[str],
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> Optional[List[List[float]]]:
        """
        Calcula embeddings vectoriales para una lista de textos usando el modelo
        vinculado al perfil de hardware. Si no hay memoria suficiente o falla,
        devuelve None de forma segura para que el AST use BM25 puro.
        """
        if not texts or not self.tier.embed_enabled:
            return None

        if not self._start_embed_server(progress_cb=progress_cb):
            return None

        url = f"http://127.0.0.1:{self.embed_port}/v1/embeddings"
        headers = {"Authorization": f"Bearer {self._embed_api_key}"}
        vectors: List[List[float]] = []

        try:
            # Procesar en mini-lotes de 16 con progreso en tiempo real
            total_t = len(texts)
            for i in range(0, total_t, 16):
                batch = [t[:1400] for t in texts[i : i + 16]]
                if progress_cb and total_t > 16:
                    done_n = min(i + len(batch), total_t)
                    pct = int((done_n / total_t) * 100)
                    progress_cb(
                        f"⏳ Vectorizando con BGE-M3: {done_n}/{total_t} nodos ({pct}%) — ten paciencia, se guarda en caché SHA-256..."
                    )
                resp = requests.post(
                    url,
                    json={"model": self.tier.embed_filename, "input": batch},
                    headers=headers,
                    timeout=60,
                )
                if resp.status_code >= 400:
                    logger.warning(f"Error embeddings HTTP {resp.status_code}: {resp.text[:200]}")
                    return None
                data = resp.json().get("data", [])
                data.sort(key=lambda item: item.get("index", 0))
                for item in data:
                    vectors.append(item["embedding"])
            return vectors if len(vectors) == len(texts) else None
        except Exception as e:
            logger.warning(f"Fallo calculando embeddings (respaldo BM25 activo): {e}")
            return None
        finally:
            if not self.tier.embed_keep_resident:
                self.stop_embed_server()

    def stop_server(self) -> None:
        self.stop_embed_server()
        if self.server_process is not None:
            logger.info(f"Deteniendo llama-server (PID {self.server_process.pid})...")
            try:
                self.server_process.terminate()
                self.server_process.wait(timeout=5)
            except Exception:
                try:
                    self.server_process.kill()
                except Exception:
                    pass
            finally:
                self.server_process = None
        if self.server_log_file is not None:
            try:
                self.server_log_file.close()
            except Exception:
                pass
            self.server_log_file = None
        if self._api_key_file is not None:
            try:
                self._api_key_file.unlink(missing_ok=True)
            except Exception:
                pass
            self._api_key_file = None

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int = 2048,
        temperature: float = 0.2,
        with_vision: bool = False,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> str:
        self.start_server(progress_cb=progress_cb)

        url = f"http://127.0.0.1:{self.port}/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self._server_api_key}"}
        safe_max_tokens = max(256, min(int(max_tokens), 4096))
        payload = {
            "model": "qwen3-vl-4b",
            "messages": messages,
            "max_tokens": safe_max_tokens,
            "temperature": temperature,
            "cache_prompt": True,
            "stream": True,
        }

        if progress_cb:
            progress_cb("⏳ Evaluando contexto en Qwen3-VL (preparando respuesta)...")

        t0 = time.perf_counter()
        resp = requests.post(url, json=payload, headers=headers, timeout=240, stream=True)
        if resp.status_code >= 400:
            err_detail = resp.text[:500]
            try:
                err_json = resp.json()
                if isinstance(err_json, dict):
                    err_obj = err_json.get("error", err_json)
                    err_detail = err_obj.get("message", str(err_obj)) if isinstance(err_obj, dict) else str(err_obj)
            except Exception:
                pass
            raise RuntimeError(f"Error de llama-server (HTTP {resp.status_code}): {err_detail}")

        import json
        chunks: List[str] = []
        token_count = 0
        last_notify = 0.0

        content_type = (resp.headers.get("content-type") or "").lower()
        if "text/event-stream" in content_type:
            resp.encoding = "utf-8"
            for raw_bytes in resp.iter_lines(decode_unicode=False):
                if not raw_bytes:
                    continue
                line = raw_bytes.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    ev = json.loads(data_str)
                    delta = ev.get("choices", [{}])[0].get("delta", {})
                    piece = delta.get("content") or ""
                    if piece:
                        chunks.append(piece)
                        token_count += 1
                        now = time.perf_counter()
                        if progress_cb and (now - last_notify >= 0.45):
                            last_notify = now
                            progress_cb(
                                f"✍️ Generando respuesta con Qwen3-VL... {token_count} tokens ({now - t0:.0f}s)"
                            )
                except Exception:
                    continue
            return "".join(chunks).strip()

        # Respaldo si el servidor devolvió JSON no-streaming
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    @staticmethod
    def pil_image_to_base64_uri(image: Image.Image, max_side: int = 1600) -> str:
        img = image.convert("RGB")
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
