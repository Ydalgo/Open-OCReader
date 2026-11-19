"""
Gestor portable y multiplataforma de llama.cpp y modelos GGUF (Qwen3-VL).
Detecta automáticamente el sistema operativo (Windows, Linux, macOS), descarga los
binarios oficiales si no existen y gestiona el ciclo de vida del servidor local.
"""

import atexit
import base64
import io
import os
import platform
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

logger = get_logger("ai.runtime")


class LlamaRuntimeManager:
    """Gestiona binarios portables de llama.cpp y modelos GGUF locales."""

    GITHUB_RELEASES_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=8"
    HF_REPO_ID = "Qwen/Qwen3-VL-4B-Instruct-GGUF"
    MODEL_FILENAME = "Qwen3VL-4B-Instruct-Q4_K_M.gguf"
    MMPROJ_FILENAME = "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf"

    _instance: Optional["LlamaRuntimeManager"] = None

    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            if getattr(sys, "frozen", False):
                # Cuando se ejecuta como .exe compilado, usar la carpeta del ejecutable
                self.base_dir = Path(sys.executable).resolve().parent
            else:
                self.base_dir = Path(__file__).resolve().parent.parent.parent
        else:
            self.base_dir = Path(base_dir)

        self.platform_key = self._detect_platform_key()

        # Si corre desde dist/Open_OCReader/ y los modelos/binarios ya están en la raíz del proyecto, reutilizarlos
        self.bin_root = self.base_dir / "bin"
        if not self.bin_root.exists() and (self.base_dir.parent.parent / "bin").exists():
            self.bin_root = self.base_dir.parent.parent / "bin"

        self.models_dir = self.base_dir / "models"
        if not self.models_dir.exists() and (self.base_dir.parent.parent / "models").exists():
            self.models_dir = self.base_dir.parent.parent / "models"

        self.bin_dir = self.bin_root / self.platform_key

        self.server_process: Optional[subprocess.Popen] = None
        self.server_log_file = None
        self.port = 8089
        self.server_with_vision = False

        logger.info(f"LlamaRuntimeManager inicializado. Base dir: {self.base_dir}, Plataforma: {self.platform_key}")
        atexit.register(self.stop_server)

    @classmethod
    def get_instance(cls) -> "LlamaRuntimeManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _detect_platform_key() -> str:
        """Detecta el identificador de plataforma oficial de las releases de llama.cpp."""
        machine = platform.machine().lower()
        is_arm64 = "arm" in machine or "aarch64" in machine

        if sys.platform == "win32":
            return "win-cpu-arm64" if is_arm64 else "win-cpu-x64"
        elif sys.platform == "darwin":
            return "macos-arm64" if is_arm64 else "macos-x64"
        else:
            return "ubuntu-arm64" if is_arm64 else "ubuntu-x64"

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

    def is_ready(self) -> bool:
        """Comprueba si tanto el binario de llama.cpp como los archivos del modelo están descargados."""
        return (
            self.server_executable.exists()
            and self.model_path.exists()
            and self.mmproj_path.exists()
        )

    def ensure_llama_binary(self, progress_cb: Optional[Callable[[str], None]] = None) -> Path:
        """Descarga y extrae el binario oficial de llama.cpp para el SO actual si no existe."""
        if self.server_executable.exists():
            return self.server_executable

        if progress_cb:
            progress_cb(f"Buscando última versión oficial de llama.cpp para {self.platform_key}...")

        resp = requests.get(self.GITHUB_RELEASES_API, timeout=20)
        resp.raise_for_status()
        releases = resp.json()

        asset_url = None
        asset_name = None
        tag_name = None

        for rel in releases:
            for asset in rel.get("assets", []):
                name = asset["name"]
                if f"-bin-{self.platform_key}." in name:
                    asset_url = asset["browser_download_url"]
                    asset_name = name
                    tag_name = rel.get("tag_name")
                    break
            if asset_url:
                break

        if not asset_url:
            raise RuntimeError(
                f"No se encontró un binario precompilado de llama.cpp para la plataforma '{self.platform_key}'."
            )

        self.bin_dir.mkdir(parents=True, exist_ok=True)
        archive_path = self.bin_dir / asset_name

        if progress_cb:
            progress_cb(f"Descargando llama.cpp ({tag_name}): {asset_name}...")

        with requests.get(asset_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(archive_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)

        if progress_cb:
            progress_cb("Extrayendo binarios portables...")

        # Extraer en directorio temporal y mover archivos clave a bin_dir
        extract_tmp = self.bin_dir / "_tmp_extract"
        if extract_tmp.exists():
            shutil.rmtree(extract_tmp)
        extract_tmp.mkdir(parents=True, exist_ok=True)

        if asset_name.endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(extract_tmp)
        elif asset_name.endswith(".tar.gz"):
            with tarfile.open(archive_path, "r:gz") as tf:
                tf.extractall(extract_tmp)

        # Buscar dónde quedó llama-server dentro del archivo extraído
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

        # Permisos de ejecución en Linux / macOS
        if sys.platform != "win32":
            for exec_candidate in self.bin_dir.iterdir():
                if exec_candidate.is_file() and (
                    "llama-" in exec_candidate.name or exec_candidate.suffix in {".so", ".dylib", ""}
                ):
                    os.chmod(exec_candidate, 0o755)

        # Limpiar temporales
        shutil.rmtree(extract_tmp, ignore_errors=True)
        archive_path.unlink(missing_ok=True)

        if progress_cb:
            progress_cb(f"✓ llama.cpp listo en {self.bin_dir}")

        return self.server_executable

    def ensure_models(self, progress_cb: Optional[Callable[[str], None]] = None) -> None:
        """Descarga Qwen3-VL-4B-Instruct (Q4_K_M) y su proyector visual mmproj si no existen."""
        self.models_dir.mkdir(parents=True, exist_ok=True)

        if not self.model_path.exists():
            if progress_cb:
                progress_cb(f"Descargando modelo principal {self.MODEL_FILENAME} (~2.5 GB)...")
            hf_hub_download(
                repo_id=self.HF_REPO_ID,
                filename=self.MODEL_FILENAME,
                local_dir=str(self.models_dir),
            )

        if not self.mmproj_path.exists():
            if progress_cb:
                progress_cb(f"Descargando proyector visual {self.MMPROJ_FILENAME}...")
            hf_hub_download(
                repo_id=self.HF_REPO_ID,
                filename=self.MMPROJ_FILENAME,
                local_dir=str(self.models_dir),
            )

        if progress_cb:
            progress_cb("✓ Modelo Qwen3-VL-4B-Instruct listo para usar offline.")

    def start_server(
        self,
        with_vision: bool = True,
        n_ctx: int = 8192,
        threads: Optional[int] = None,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Inicia llama-server en segundo plano sin consola visible."""
        if self.server_process is not None and self.server_process.poll() is None:
            # Ya está corriendo con la configuración deseada
            if self.server_with_vision == with_vision:
                return
            self.stop_server()

        self.ensure_llama_binary(progress_cb=progress_cb)
        self.ensure_models(progress_cb=progress_cb)

        cpu_threads = threads or max(2, (os.cpu_count() or 4) - 1)
        cmd = [
            str(self.server_executable),
            "-m",
            str(self.model_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "-c",
            str(n_ctx),
            "-t",
            str(cpu_threads),
        ]

        if with_vision:
            cmd.extend(["--mmproj", str(self.mmproj_path)])

        if progress_cb:
            progress_cb("Iniciando motor local Qwen3-VL en memoria...")

        logger.info(f"Iniciando llama-server (vision={with_vision}): {' '.join(cmd)}")

        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW

        llama_log_path = get_logs_dir() / "llama_server.log"
        self.server_log_file = open(llama_log_path, "a", encoding="utf-8", errors="replace")

        self.server_process = subprocess.Popen(
            cmd,
            stdout=self.server_log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        self.server_with_vision = with_vision

        # Esperar hasta que /health responda
        health_url = f"http://127.0.0.1:{self.port}/health"
        deadline = time.time() + 120.0

        while time.time() < deadline:
            ret_code = self.server_process.poll()
            if ret_code is not None:
                err_msg = f"El proceso de llama-server se cerró inesperadamente (código {ret_code}). Revisa {llama_log_path}"
                logger.error(err_msg)
                raise RuntimeError(err_msg)
            try:
                r = requests.get(health_url, timeout=1.5)
                if r.status_code == 200:
                    logger.info(f"llama-server operativo en puerto {self.port} (PID {self.server_process.pid}).")
                    if progress_cb:
                        progress_cb("✓ Motor IA local listo.")
                    return
            except requests.RequestException:
                pass
            time.sleep(0.5)

        logger.error("Timeout esperando a que llama-server responda en /health.")
        self.stop_server()
        raise TimeoutError(f"Tiempo de espera agotado al inicializar llama-server. Revisa {llama_log_path}")

    def stop_server(self) -> None:
        """Detiene el proceso del servidor local y libera la memoria."""
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

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int = 2048,
        temperature: float = 0.2,
        with_vision: bool = False,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Envía una petición de chat (texto o imagen+texto) al servidor llama.cpp local."""
        self.start_server(with_vision=with_vision, progress_cb=progress_cb)

        url = f"http://127.0.0.1:{self.port}/v1/chat/completions"
        payload = {
            "model": "qwen3-vl-4b",
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        resp = requests.post(url, json=payload, timeout=180)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    @staticmethod
    def pil_image_to_base64_uri(image: Image.Image, max_side: int = 1600) -> str:
        """Convierte una imagen PIL a Data URI base64 optimizada para visión."""
        img = image.convert("RGB")
        # Redimensionar proporcionalmente si supera max_side para acelerar inferencia
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
