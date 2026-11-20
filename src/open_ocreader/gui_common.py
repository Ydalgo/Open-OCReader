"""
Constantes, textos legales y utilidades de sistema compartidas entre las interfaces Qt 6 y Tkinter.
Sin dependencias de ningún toolkit gráfico para garantizar portabilidad total.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

GITHUB_REPO_URL = "https://github.com/Ydalgo/Open-OCReader"
GUARIDA_REPO_URL = "https://github.com/Ydalgo/GuarIdA"

FORMAT_OPTIONS = [
    ("PDF Buscable (Sandwich)", "pdf", "Diseño visual 100% original + texto invisible"),
    ("PDF/A-2b (Archivo Público)", "pdfa", "Estándar oficial de archivo Adm. Públicas"),
    ("Microsoft Word (.docx)", "docx", "Documento editable fiel (fondos e imágenes)"),
    ("OpenDocument Text (.odt)", "odt", "LibreOffice fiel con fondos e imágenes"),
    ("Microsoft Excel (.xlsx)", "xlsx", "Hoja de cálculo por coordenadas"),
    ("OpenDocument Calc (.ods)", "ods", "Hoja de cálculo libre por coordenadas"),
    ("CSV Tabular (.csv)", "csv", "Datos tabulares separados por punto y coma"),
    ("eBook (.epub)", "epub", "Libro electrónico para Kindle/Kobo/Calibre"),
    ("Texto plano (.txt)", "txt", "Volcado de texto en orden de lectura"),
    ("JSON Estructurado (.json)", "json", "Coordenadas geométricas y confianza"),
]

COMPRESSION_LABELS = [
    ("Alta calidad (original)", "high"),
    ("Equilibrada (recomendada)", "balanced"),
    ("Máxima compresión (ligero)", "compact"),
]

EXPORT_CONV_FORMATS = [
    ("Word (.docx)", "docx"),
    ("PDF (.pdf)", "pdf"),
    ("PDF/A-2b (.pdf)", "pdfa"),
    ("LibreOffice (.odt)", "odt"),
    ("eBook (.epub)", "epub"),
    ("Markdown (.md)", "md"),
    ("Texto (.txt)", "txt"),
    ("JSON (.json)", "json"),
]

LEGAL_COMPLIANCE_TEXT = (
    "1. CUMPLIMIENTO DE NORMATIVAS DE IA Y PRIVACIDAD\n"
    "============================================================\n"
    "Open OCReader opera 100% EN LOCAL (offline / on-premise), sin enviar\n"
    "documentos ni datos personales a servidores externos ni a la nube.\n\n"
    "• Reglamento Europeo de IA (EU AI Act — Reglamento (UE) 2024/1689):\n"
    "  Herramienta auxiliar de productividad documental (riesgo mínimo/limitado).\n"
    "  Se separa el OCR determinista (RapidOCR) de la IA generativa (Qwen3-VL).\n"
    "  IMPORTANTE: Toda salida de IA (resumen, traducción, Q&A o anonimización)\n"
    "  requiere supervisión humana (Human-in-the-Loop) antes de su uso oficial.\n\n"
    "• RGPD (UE) y LOPDGDD (España):\n"
    "  Cumple privacidad desde el diseño (Art. 25) y evita transferencias\n"
    "  internacionales de datos. La anonimización asistida debe validarse\n"
    "  siempre por el responsable del tratamiento antes de publicar documentos.\n\n"
    "• Administración Pública y ENS (Esquema Nacional de Seguridad):\n"
    "  Apto para redes aisladas (air-gapped), con verificación SHA-256,\n"
    "  logs auditables y API autenticada con clave de acceso.\n\n"
    "• Accesibilidad Universal (UNE 153101 EX y WCAG AAA):\n"
    "  Incluye escalado global (90%-180%), temas de alto contraste >15:1,\n"
    "  tipografía cómoda para dislexia, Lectura Fácil IA, lectura por voz TTS\n"
    "  100% offline y navegación íntegra por teclado y lectores de pantalla.\n\n"
    "• Estándares Internacionales (NIST AI RMF, HIPAA, CCPA, ISO/IEC 42001):\n"
    "  Arquitectura abierta, auditable y libre de telemetría.\n\n"
    "2. LICENCIA DE SOFTWARE LIBRE (GNU GPL v3.0 — COPYLEFT)\n"
    "============================================================\n"
    "Open OCReader es Código Libre bajo GNU General Public License v3.0\n"
    "(https://www.gnu.org/licenses/gpl-3.0.html).\n\n"
    "• Uso libre: Permitido en ámbito personal, empresas y Administración.\n"
    "• Atribución obligatoria: Debe mantenerse siempre el reconocimiento\n"
    "  expreso a los autores originales (Ydalgo y colaboradores).\n"
    "• Copyleft fuerte (Compartir Igual): Si reproduces, modificas o creas\n"
    "  una versión derivada de este software, DEBES distribuirla también\n"
    "  como código libre bajo la misma licencia GNU GPL v3.0.\n"
    "  No está permitido cerrar el código en un producto privativo.\n\n"
    "3. CRÉDITOS Y PROYECTO HERMANO: GUARIDA\n"
    "============================================================\n"
    "Gran parte de la arquitectura técnica, la optimización de hardware\n"
    "y la ingeniería de contexto de Open OCReader provienen directamente de\n"
    "las investigaciones, decisiones técnicas y código de mi proyecto hermano:\n\n"
    "🛡️ GUARIDA: Guardián de Identidad y Asistencia con IA Local Soberana\n"
    "Repositorio oficial: https://github.com/Ydalgo/GuarIdA\n\n"
    "Componentes y estructuras transferidas desde GuarIdA:\n"
    "• Árbol de Nodos Documental (AST): Descomposición jerárquica de documentos\n"
    "  (secciones, tablas y bloques) eliminando el límite de contexto del LLM.\n"
    "• Compresión de Vocabulario BPE: Minificación de tokens para alta densidad.\n"
    "• Recuperación Híbrida RRF: Fusión de ranking léxico BM25 + Embeddings BGE-M3.\n"
    "• Persistencia Segregada SQLite WAL: Con compresión zstd/zlib por SHA-256.\n"
    "• Observador de Hardware en tiempo real y perfiles dinámicos adaptativos.\n"
    "• Reutilización de KV Cache (cache_prompt) para respuestas inmediatas.\n\n"
    "👉 ¡Te invito a pasarte por mi proyecto GuarIdA, echarle un vistazo y seguir su evolución!\n"
    "Actualmente lo sigo desarrollando activamente para impulsar la soberanía y privacidad documental.\n\n"
    "4. EXENCIÓN DE RESPONSABILIDAD SOBRE EL MODELO DE IA\n"
    "============================================================\n"
    "• Integridad de Pesos Oficiales: Open OCReader ejecuta modelos abiertos oficiales\n"
    "  (Qwen3-VL de Alibaba y BGE-M3 de BAAI). El autor NO modifica, NO altera,\n"
    "  NO entrena ni interviene los pesos originales de los modelos neuronales.\n"
    "• Descargo de Responsabilidad: El autor (Ydalgo) no se hace responsable de las\n"
    "  respuestas, opiniones, redacciones imprecisas, alucinaciones o expresiones\n"
    "  inadecuadas que el modelo de lenguaje de terceros pudiera formular.\n"
    "• Rieles Éticos (Prompt Madre): Se ha integrado un sistema estricto de salvaguardas\n"
    "  institucionales con rieles de cortesía, neutralidad absoluta y rigor analítico\n"
    "  para garantizar que el modelo mantenga siempre un tono respetuoso y profesional.\n"
    "• Supervisión Humana (Human-in-the-Loop): Es responsabilidad ineludible del usuario\n"
    "  verificar y validar toda salida generada por la IA antes de su utilización oficial.\n"
)


def resolve_ico_dir() -> Optional[Path]:
    """Localiza el directorio de recursos gráficos 'ico/' en modo fuente o compilado."""
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([exe_dir / "ico", exe_dir / "_internal" / "ico"])
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "ico")
    else:
        candidates.append(Path(__file__).resolve().parent.parent.parent / "ico")
    return next((d for d in candidates if d.exists()), None)


def strip_leading_emoji(text: str) -> str:
    """Elimina el emoji inicial para acompañar limpiamente a un icono vectorial en color."""
    s = (text or "").strip()
    if not s:
        return ""
    parts = s.split(" ", 1)
    if len(parts) == 2 and parts[0] and not parts[0][0].isalnum():
        s = parts[1].strip()
    return f" {s}" if s else ""


def detect_os_dark_mode() -> bool:
    """Detecta si el sistema operativo tiene activado el modo oscuro."""
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return int(val) == 0
        except Exception:
            pass
    return False


def open_path_crossplatform(path: str):
    """Abre un fichero o carpeta con la aplicación nativa del sistema operativo."""
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)


def acquire_single_instance_lock():
    """Garantiza instancia única de la GUI mediante Mutex en Windows o flock en Unix."""
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            mutex = kernel32.CreateMutexW(None, False, "Global\\OpenOCReader_SingleInstance_Mutex_v1")
            if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                if mutex:
                    kernel32.CloseHandle(mutex)
                return None
            return mutex
        except Exception:
            return True
    try:
        import fcntl
        lock_path = Path(tempfile.gettempdir()) / "open_ocreader.lock"
        fp = open(lock_path, "w", encoding="utf-8")
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fp
    except Exception:
        return None


def release_single_instance_lock(lock_handle):
    """Libera el handle de instancia única al cerrar."""
    if sys.platform == "win32" and isinstance(lock_handle, int):
        try:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(lock_handle)
        except Exception:
            pass
    elif lock_handle is not None and hasattr(lock_handle, "close"):
        try:
            lock_handle.close()
        except Exception:
            pass


def focus_existing_window_windows():
    """Trae al frente una ventana ya abierta de Open OCReader en Windows."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "Open OCReader - Digitalización e IA Documental 100% Local")
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
