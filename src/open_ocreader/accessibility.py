"""
Módulo de Accesibilidad Universal 100% Local para Open OCReader.

Cubre tres ejes de accesibilidad sin telemetría ni servicios externos:
  1. Visual: escalado global de UI (A-/A+ 90%-180%), alto contraste WCAG AAA (>15:1)
     claro y oscuro, tema crema anti-estrés visual y lector de voz local (TTS offline).
  2. Cognitiva: tipografía amiga para dislexia (OpenDyslexic o Verdana espaciada)
     y soporte de prompts de Lectura Fácil (Norma UNE 153101 EX).
  3. Motora: objetivos táctiles/clic ampliados (anti-temblor), navegación por
     teclado completa y atajos globales sin ratón.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Optional

from .logger import get_logger
from .paths import get_user_data_dir

logger = get_logger("accessibility")

VALID_THEME_MODES = (
    "auto",
    "light",
    "dark",
    "high_contrast_dark",
    "high_contrast_light",
    "dyslexia_cream",
)

THEME_DISPLAY_LABELS: Dict[str, str] = {
    "auto": "Automático (según el sistema operativo)",
    "light": "Claro estándar",
    "dark": "Oscuro estándar",
    "high_contrast_dark": "Alto Contraste Oscuro (WCAG AAA ≥15:1)",
    "high_contrast_light": "Alto Contraste Claro (WCAG AAA ≥15:1)",
    "dyslexia_cream": "Crema Cálido / Anti-estrés visual (Irlen/Dislexia)",
}


def _get_config_file_path() -> Path:
    """Devuelve la ruta del fichero de configuración de accesibilidad escribible."""
    try:
        cfg_dir = get_user_data_dir() / "config"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        probe = cfg_dir / f".probe_{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return cfg_dir / "accessibility.json"
    except Exception:
        fallback_dir = Path.home() / ".open_ocreader"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        return fallback_dir / "accessibility.json"


@dataclass
class AccessibilityConfig:
    """Preferencias persistentes de accesibilidad universal."""

    ui_font_size: int = 10
    text_font_size: int = 11
    theme_mode: str = "auto"
    dyslexia_friendly: bool = False
    large_targets: bool = False
    voice_guidance: bool = False
    tts_rate: int = 0

    def __post_init__(self):
        self.clamp()

    def clamp(self):
        try:
            self.ui_font_size = max(9, min(18, int(self.ui_font_size)))
        except Exception:
            self.ui_font_size = 10
        try:
            self.text_font_size = max(9, min(24, int(self.text_font_size)))
        except Exception:
            self.text_font_size = 11
        if self.theme_mode not in VALID_THEME_MODES:
            self.theme_mode = "auto"
        self.dyslexia_friendly = bool(self.dyslexia_friendly)
        self.large_targets = bool(self.large_targets)
        self.voice_guidance = bool(self.voice_guidance)
        try:
            self.tts_rate = max(-5, min(5, int(self.tts_rate)))
        except Exception:
            self.tts_rate = 0

    @property
    def zoom_percent(self) -> int:
        return int(round((self.ui_font_size / 10.0) * 100))

    @classmethod
    def load(cls) -> "AccessibilityConfig":
        """Carga las preferencias desde disco o devuelve valores por defecto."""
        cfg_path = _get_config_file_path()
        if not cfg_path.exists():
            fallback = Path.home() / ".open_ocreader" / "accessibility.json"
            if fallback.exists():
                cfg_path = fallback
            else:
                return cls()
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return cls()
            known = {f.name for f in cls.__dataclass_fields__.values()}
            filtered = {k: v for k, v in raw.items() if k in known}
            return cls(**filtered)
        except Exception as e:
            logger.warning(f"No se pudo leer config de accesibilidad ({cfg_path}): {e}")
            return cls()

    def save(self) -> Path:
        """Persiste las preferencias en formato JSON en disco."""
        self.clamp()
        cfg_path = _get_config_file_path()
        try:
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(
                json.dumps(asdict(self), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return cfg_path
        except Exception as e:
            logger.warning(f"No se pudo guardar en {cfg_path}, usando respaldo home: {e}")
            fallback = Path.home() / ".open_ocreader" / "accessibility.json"
            fallback.parent.mkdir(parents=True, exist_ok=True)
            fallback.write_text(
                json.dumps(asdict(self), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return fallback


def get_accessible_palette(theme_mode: str, os_dark: bool) -> Dict[str, str]:
    """
    Devuelve la paleta cromática completa para el perfil visual elegido.
    Incluye modos WCAG AAA (contraste >15:1) y modo crema para estrés visual/dislexia.
    """
    resolved = theme_mode
    if resolved == "auto":
        resolved = "dark" if os_dark else "light"

    if resolved == "high_contrast_dark":
        return {
            "mode": "high_contrast_dark",
            "is_dark": "1",
            "bg": "#000000",
            "fg": "#ffffff",
            "muted": "#ffff00",
            "accent": "#00ffff",
            "ok": "#00ff66",
            "warn": "#ffff00",
            "input_bg": "#0a0a0a",
            "input_fg": "#ffffff",
            "drop_bg": "#00141f",
            "drop_border": "#00ffff",
            "btn_bg": "#1a1a1a",
            "btn_active": "#00384d",
            "tab_bg": "#121212",
            "tab_sel_bg": "#004466",
            "focus_ring": "#ffff00",
        }

    if resolved == "high_contrast_light":
        return {
            "mode": "high_contrast_light",
            "is_dark": "0",
            "bg": "#ffffff",
            "fg": "#000000",
            "muted": "#1f1f1f",
            "accent": "#000099",
            "ok": "#005500",
            "warn": "#7a0000",
            "input_bg": "#ffffff",
            "input_fg": "#000000",
            "drop_bg": "#eef4ff",
            "drop_border": "#000099",
            "btn_bg": "#e4e4e4",
            "btn_active": "#c2dbff",
            "tab_bg": "#e0e0e0",
            "tab_sel_bg": "#ffffff",
            "focus_ring": "#0000cc",
        }

    if resolved == "dyslexia_cream":
        return {
            "mode": "dyslexia_cream",
            "is_dark": "0",
            "bg": "#faf6eb",
            "fg": "#1f1d1a",
            "muted": "#575047",
            "accent": "#0b4f6c",
            "ok": "#1b5e20",
            "warn": "#8a4b00",
            "input_bg": "#fffdf7",
            "input_fg": "#1f1d1a",
            "drop_bg": "#f3ebd6",
            "drop_border": "#0b4f6c",
            "btn_bg": "#efe8d5",
            "btn_active": "#dfd3b4",
            "tab_bg": "#ece3cc",
            "tab_sel_bg": "#fffdf7",
            "focus_ring": "#0b4f6c",
        }

    if resolved == "dark":
        return {
            "mode": "dark",
            "is_dark": "1",
            "bg": "#1e1f22",
            "fg": "#e8eaed",
            "muted": "#b0b6bf",
            "accent": "#6cb4ff",
            "ok": "#6dd58c",
            "warn": "#f6c177",
            "input_bg": "#2b2d30",
            "input_fg": "#f1f3f4",
            "drop_bg": "#262a30",
            "drop_border": "#4c6ef5",
            "btn_bg": "#35383e",
            "btn_active": "#464b54",
            "tab_bg": "#2b2d30",
            "tab_sel_bg": "#3c4048",
            "focus_ring": "#6cb4ff",
        }

    # "light" por defecto
    return {
        "mode": "light",
        "is_dark": "0",
        "bg": "#f5f6f8",
        "fg": "#1a1a1a",
        "muted": "#4f5560",
        "accent": "#1a5fb4",
        "ok": "#1e6b1e",
        "warn": "#8a4b00",
        "input_bg": "#ffffff",
        "input_fg": "#111111",
        "drop_bg": "#f0f4fa",
        "drop_border": "#88a8d0",
        "btn_bg": "#e7e9ee",
        "btn_active": "#d4dce8",
        "tab_bg": "#e6e9ef",
        "tab_sel_bg": "#ffffff",
        "focus_ring": "#1a5fb4",
    }


def strip_text_for_speech(text: str) -> str:
    """Limpia sintaxis Markdown, símbolos decorativos y etiquetas técnicas para lectura natural."""
    if not text:
        return ""
    s = re.sub(r"\[(?:DOC|REF)-\d+[^\]]*\]", "", text)
    s = re.sub(r"```.*?```", " bloque de código omitido ", s, flags=re.DOTALL)
    s = re.sub(r"[#*_`~►▸•▪■●✓✗⏳📚📥📄📁🧠💬🔒🌐🛠️⚖️📋💾🧹🗑️♻️🔄🐙]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Limitar locución continua extensa manteniendo fluidez
    if len(s) > 12000:
        s = s[:12000]
    return s


class LocalTTSEngine:
    """Motor de síntesis de voz (Text-to-Speech) 100% local sin conexión."""

    _instance: Optional["LocalTTSEngine"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._cmd_queue: "queue.Queue[tuple]" = queue.Queue()
        self._proc: Optional[subprocess.Popen] = None
        self._proc_lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._sapi_checked = False
        self._has_win32_sapi = False

    @classmethod
    def get_instance(cls) -> "LocalTTSEngine":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def is_available(self) -> bool:
        if sys.platform == "win32":
            if not self._sapi_checked:
                try:
                    import win32com.client  # noqa: F401
                    self._has_win32_sapi = True
                except ImportError:
                    self._has_win32_sapi = False
                self._sapi_checked = True
            return self._has_win32_sapi or bool(shutil.which("powershell"))
        if sys.platform == "darwin":
            return bool(shutil.which("say"))
        return bool(shutil.which("spd-say") or shutil.which("espeak-ng") or shutil.which("espeak"))

    def _ensure_win_worker(self):
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._win_sapi_loop, daemon=True)
        self._worker.start()

    def _win_sapi_loop(self):
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            SVSFlagsAsync = 1
            SVSFPurgeBeforeSpeak = 2
        except Exception as e:
            logger.debug(f"SAPI COM no disponible en hilo TTS, se usará respaldo PowerShell: {e}")
            voice = None
            pythoncom = None

        while True:
            item = self._cmd_queue.get()
            if not item:
                continue
            action = item[0]
            if action == "stop":
                self._kill_subproc()
                if voice is not None:
                    try:
                        voice.Speak("", 1 | 2)
                    except Exception:
                        pass
            elif action == "speak":
                _act, clean_text, rate = item
                if not clean_text:
                    continue
                if voice is not None:
                    try:
                        voice.Rate = max(-10, min(10, int(rate)))
                        voice.Speak(clean_text, SVSFlagsAsync | SVSFPurgeBeforeSpeak)
                        continue
                    except Exception as e:
                        logger.debug(f"Fallo al reproducir con SAPI COM: {e}")
                self._speak_subprocess_fallback(clean_text, rate)

        if pythoncom is not None:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    def _kill_subproc(self):
        with self._proc_lock:
            if self._proc is not None and self._proc.poll() is None:
                try:
                    self._proc.terminate()
                except Exception:
                    pass
            self._proc = None

    def _speak_subprocess_fallback(self, clean_text: str, rate: int):
        self._kill_subproc()
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            if sys.platform == "win32":
                ps = shutil.which("powershell")
                if not ps:
                    return
                env = os.environ.copy()
                env["OCREADER_TTS_TEXT"] = clean_text
                env["OCREADER_TTS_RATE"] = str(max(-10, min(10, int(rate))))
                script = (
                    "Add-Type -AssemblyName System.Speech; "
                    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    "$s.Rate = [int]$env:OCREADER_TTS_RATE; "
                    "$s.Speak($env:OCREADER_TTS_TEXT)"
                )
                with self._proc_lock:
                    self._proc = subprocess.Popen(
                        [ps, "-NoProfile", "-Command", script],
                        env=env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=creationflags,
                    )
            elif sys.platform == "darwin" and shutil.which("say"):
                wpm = max(90, min(320, 175 + int(rate) * 25))
                with self._proc_lock:
                    self._proc = subprocess.Popen(
                        ["say", "-r", str(wpm), clean_text],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            else:
                if shutil.which("spd-say"):
                    pct = max(-90, min(90, int(rate) * 15))
                    cmd = ["spd-say", "-r", str(pct), clean_text]
                elif shutil.which("espeak-ng"):
                    wpm = max(90, min(320, 165 + int(rate) * 25))
                    cmd = ["espeak-ng", "-s", str(wpm), clean_text]
                elif shutil.which("espeak"):
                    wpm = max(90, min(320, 165 + int(rate) * 25))
                    cmd = ["espeak", "-s", str(wpm), clean_text]
                else:
                    return
                with self._proc_lock:
                    self._proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
        except Exception as e:
            logger.debug(f"Error lanzando síntesis de voz subprocess: {e}")

    def speak(self, text: str, rate: int = 0):
        """Reproduce en voz alta el texto de manera asíncrona sin bloquear la GUI."""
        clean = strip_text_for_speech(text)
        if not clean:
            return
        if sys.platform == "win32":
            self._ensure_win_worker()
            # Vaciar pendientes para responder al instante al último clic del usuario
            while not self._cmd_queue.empty():
                try:
                    self._cmd_queue.get_nowait()
                except Exception:
                    break
            self._cmd_queue.put(("speak", clean, rate))
        else:
            threading.Thread(
                target=self._speak_subprocess_fallback,
                args=(clean, rate),
                daemon=True,
            ).start()

    def stop(self):
        """Detiene inmediatamente cualquier locución en curso."""
        self._kill_subproc()
        if sys.platform == "win32":
            self._ensure_win_worker()
            while not self._cmd_queue.empty():
                try:
                    self._cmd_queue.get_nowait()
                except Exception:
                    break
            self._cmd_queue.put(("stop",))
        elif shutil.which("spd-say"):
            try:
                subprocess.run(
                    ["spd-say", "-C"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1,
                    check=False,
                )
            except Exception:
                pass


def get_tts_engine() -> LocalTTSEngine:
    """Devuelve la instancia única del motor TTS local."""
    return LocalTTSEngine.get_instance()
