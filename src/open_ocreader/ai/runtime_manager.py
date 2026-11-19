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

    # Hashes SHA-256 de referencia de los modelos oficiales (Qwen/Qwen3-VL-4B-Instruct-GGUF).
    # Cualquier descarga (Hugging Face o GitHub) que no coincida se rechaza y se elimina.
    MODEL_SHA256 = {
        "Qwen3VL-4B-Instruct-Q4_K_M.gguf": "66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a",
        "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf": "30ba2c7dd3127a4561b6cba9d13d0f711c91bdb38742e2f56d73c8cb596bd06d",
    }

    _instance: Optional["LlamaRuntimeManager"] = None

    def __init__(self, base_dir: Optional[Path] = None, force_cpu: bool = False):
        if base_dir is None:
            if getattr(sys, "frozen", False):
                self.base_dir = Path(sys.executable).resolve().parent
            else:
                self.base_dir = Path(__file__).resolve().parent.parent.parent.parent
        else:
            self.base_dir = Path(base_dir)

        self.hw: HardwareProfile = get_hardware_profile(force_cpu=force_cpu)
        self.platform_key = self.hw.platform_asset_key

        self.bin_root = self.base_dir / "bin"
        if not self.bin_root.exists() and (self.base_dir.parent.parent / "bin").exists():
            self.bin_root = self.base_dir.parent.parent / "bin"

        self.models_dir = self.base_dir / "models"
        if not self.models_dir.exists() and (self.base_dir.parent.parent / "models").exists():
            self.models_dir = self.base_dir.parent.parent / "models"

        self.bin_dir = self.bin_root / self.platform_key

        self.server_process: Optional[subprocess.Popen] = None
        self.server_log_file = None
        self._api_key_file: Optional[Path] = None
        # Clave aleatoria por sesión: ninguna web ni proceso ajeno puede usar el LLM local
        self._server_api_key = generate_token()
        self.port = 8089
        self.preferred_model_source = "official"  # 'official' | 'github'

        logger.info(
            f"LlamaRuntimeManager listo | SO: {self.hw.os_name} ({self.hw.arch}) | "
            f"Backend: {self.hw.backend.upper()} ({self.platform_key}) | Núcleos: {self.hw.cpu_cores}"
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
        n_ctx: int = 8192,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Inicia llama-server con el binario óptimo (GPU Vulkan/Metal o CPU),
        optimizaciones GuarIdA y permanencia residente en memoria.
        Si la GPU falla al inicializar, hace fallback automático a CPU.
        """
        if self.server_process is not None and self.server_process.poll() is None:
            return

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

    def stop_server(self) -> None:
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
        payload = {
            "model": "qwen3-vl-4b",
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=180)
        resp.raise_for_status()
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
