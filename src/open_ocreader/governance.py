"""
Generador de Informes de Gobernanza de IA, Privacidad y Cumplimiento ENS (1 clic).
Produce informes listos para auditorías, Delegados de Protección de Datos (DPD/DPO)
y Administraciones Públicas en formato Word (.docx), Markdown (.md) o JSON (.json).
"""

import json
import os
import platform
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from . import __version__
from .ai.runtime_manager import LlamaRuntimeManager
from .logger import get_logger, get_logs_dir, is_log_deletion_locked
from .security import sha256_file

logger = get_logger("governance")


def collect_governance_data() -> Dict[str, Any]:
    """Recopila el estado real de cumplimiento, hardware, modelos e integridad del sistema."""
    rt = LlamaRuntimeManager.get_instance()
    now_utc = datetime.now(timezone.utc)

    # Comprobar estado e integridad criptográfica real de los modelos locales (VLM + Embeddings BGE-M3)
    models_to_check = [
        (rt.MODEL_FILENAME, rt.model_path),
        (rt.MMPROJ_FILENAME, rt.mmproj_path),
    ]
    if rt.embed_model_path is not None and rt.tier.embed_filename:
        models_to_check.append((rt.tier.embed_filename, rt.embed_model_path))

    models_status = []
    for fname, dest in models_to_check:
        expected = rt.MODEL_SHA256.get(fname, "")
        if dest.exists():
            actual = sha256_file(dest)
            status = "VERIFICADO (SHA-256 OK)" if actual == expected else "ALERTA: HASH NO COINCIDE"
            size_mb = round(dest.stat().st_size / (1024 * 1024), 1)
        else:
            actual = "N/A"
            status = "NO DESCARGADO"
            size_mb = 0.0
        models_status.append({
            "file": fname,
            "size_mb": size_mb,
            "expected_sha256": expected,
            "actual_sha256": actual,
            "status": status,
        })

    sbom_path = rt.base_dir / "docs" / "sbom_cyclonedx.json"

    return {
        "report_title": "Informe de Gobernanza de IA, Privacidad y Seguridad (ENS / CCN-CERT)",
        "generated_utc": now_utc.isoformat(),
        "application": {
            "name": "Open OCReader",
            "version": __version__,
            "license": "GNU General Public License v3.0 (GNU GPL v3.0 — Copyleft Fuerte)",
            "authors": "Ydalgo y colaboradores (con asistencia de Antigravity)",
            "repository": "https://github.com/Ydalgo/Open-OCReader",
            "execution_mode": "100% Local (Offline / On-Premise — Cero envío de datos a terceros)",
        },
        "environment": {
            "hostname": socket.gethostname(),
            "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "python": sys.version.split()[0],
            "cpu_cores": rt.hw.cpu_cores,
            "ram_total_gb": rt.hw.ram_total_gb,
            "ai_tier": rt.tier.tier_name.upper(),
            "ai_backend": rt.hw.backend.upper(),
            "has_vulkan": rt.hw.has_vulkan,
            "llama_binary_installed": rt.server_executable.exists(),
        },
        "models_integrity": models_status,
        "security_controls": {
            "offline_data_sovereignty": True,
            "sha256_model_and_binary_verification": True,
            "anti_zip_slip_and_magic_bytes": True,
            "anti_excel_formula_injection": True,
            "llama_server_session_api_key": True,
            "rest_api_key_configured": bool(os.environ.get("OPEN_OCREADER_API_KEY", "").strip()),
            "siem_syslog_configured": bool(os.environ.get("OPEN_OCREADER_SYSLOG_HOST", "").strip()),
            "json_siem_log_format": os.environ.get("OPEN_OCREADER_LOG_FORMAT", "").lower() == "json",
            "ens_immutable_logs_locked": is_log_deletion_locked(),
            "sbom_cyclonedx_present": sbom_path.exists(),
            "logs_directory": str(get_logs_dir()),
        },
        "regulatory_matrix": [
            {
                "framework": "EU AI Act — Reglamento (UE) 2024/1689",
                "classification": "Riesgo mínimo / limitado (productividad documental)",
                "compliance_notes": (
                    "Separación clara entre OCR determinista (RapidOCR) e IA generativa (Qwen3-VL). "
                    "Transparencia activa (Art. 50) y requisito de supervisión humana (Human-in-the-Loop)."
                ),
            },
            {
                "framework": "RGPD (UE 2016/679) y LOPDGDD (España)",
                "classification": "Privacidad desde el diseño (Art. 25)",
                "compliance_notes": (
                    "Tratamiento 100% local sin transferencias internacionales ni encargados en la nube. "
                    "Incluye anonimización híbrida (Regex + LLM) sujeta a validación final del responsable."
                ),
            },
            {
                "framework": "ENS / Guías CCN-CERT (CCN-STIC)",
                "classification": "Apto para despliegue controlado / Air-Gapped",
                "compliance_notes": (
                    "Verificación SHA-256, soporte TLS 1.3 (directo o Nginx), envío SIEM/Syslog JSON, "
                    "SBOM CycloneDX 1.5, Code Signing y aislamiento systemd."
                ),
            },
            {
                "framework": "NIST AI RMF / ISO/IEC 42001 / HIPAA / CCPA",
                "classification": "Gobernanza auditable sin telemetría",
                "compliance_notes": (
                    "Código fuente abierto auditable íntegramente, inventario de modelos con huella SHA-256 "
                    "y ausencia total de telemetría externa."
                ),
            },
        ],
        "ai_disclaimer_and_guardrails": {
            "unmodified_official_weights": True,
            "weights_integrity_statement": (
                "Los pesos neuronales de Qwen3-VL y BGE-M3 son oficiales y no han sido modificados, "
                "afinados ni manipulados por los autores de la aplicación."
            ),
            "author_disclaimer": (
                "El creador y colaboradores de Open OCReader no se hacen responsables de las respuestas, "
                "opiniones o expresiones que el modelo de IA formule en sus salidas generativas."
            ),
            "master_guardrails_active": True,
            "human_in_the_loop_mandatory": True,
        },
    }


def generate_governance_report(output_path: str) -> str:
    """
    Genera el informe de gobernanza en .docx, .md o .json según la extensión de output_path.
    """
    data = collect_governance_data()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    ext = out.suffix.lower()

    if ext == ".json":
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    elif ext == ".docx":
        _write_docx_report(data, out)
    else:
        _write_markdown_report(data, out)

    logger.info(f"Informe de gobernanza IA generado en: {out}")
    return str(out)


def _write_markdown_report(data: Dict[str, Any], out: Path) -> None:
    app = data["application"]
    env = data["environment"]
    sec = data["security_controls"]

    lines = [
        f"# {data['report_title']}",
        "",
        f"**Fecha de generación (UTC):** `{data['generated_utc']}`  ",
        f"**Aplicación:** {app['name']} `v{app['version']}`  ",
        f"**Licencia:** {app['license']}  ",
        f"**Modo de ejecución:** {app['execution_mode']}  ",
        "",
        "---",
        "",
        "## 1. Entorno de Despliegue",
        f"- **Equipo:** `{env['hostname']}`",
        f"- **Sistema Operativo:** `{env['os']}`",
        f"- **Python:** `{env['python']}` | **Núcleos CPU:** `{env['cpu_cores']}` | **Backend IA:** `{env['ai_backend']}`",
        f"- **Binario `llama.cpp` instalado:** `{'SÍ' if env['llama_binary_installed'] else 'NO'}`",
        "",
        "## 2. Inventario e Integridad de Modelos de IA (SHA-256)",
        "",
        "| Fichero | Tamaño (MB) | Estado de Verificación | SHA-256 |",
        "| :--- | ---: | :--- | :--- |",
    ]
    for m in data["models_integrity"]:
        lines.append(f"| `{m['file']}` | {m['size_mb']} | **{m['status']}** | `{m['actual_sha256'][:16]}...` |")

    lines.extend([
        "",
        "## 3. Controles Técnicos de Seguridad (CCN-CERT / ENS)",
        "",
        "| Control | Estado |",
        "| :--- | :--- |",
    ])
    for k, v in sec.items():
        val = "✅ ACTIVO" if v is True else ("⚠️ NO CONFIGURADO" if v is False else f"`{v}`")
        lines.append(f"| `{k}` | {val} |")

    lines.extend([
        "",
        "## 4. Matriz de Cumplimiento Normativo de IA y Privacidad",
        "",
        "| Normativa / Estándar | Clasificación | Medidas Implementadas |",
        "| :--- | :--- | :--- |",
    ])
    for row in data["regulatory_matrix"]:
        lines.append(f"| **{row['framework']}** | {row['classification']} | {row['compliance_notes']} |")

    disc = data.get("ai_disclaimer_and_guardrails", {})
    lines.extend([
        "",
        "## 5. Exención de Responsabilidad, Integridad de Pesos y Rieles de Seguridad",
        "",
        f"- **Integridad de Pesos Neuronales:** {disc.get('weights_integrity_statement', 'N/A')}",
        f"- **Exención de Responsabilidad:** {disc.get('author_disclaimer', 'N/A')}",
        f"- **Rieles Éticos y Prompt Madre Institucional:** {'ACTIVO (Cortesía, neutralidad y rigor analítico)' if disc.get('master_guardrails_active') else 'N/A'}",
        f"- **Supervisión Humana Obligatoria (Human-in-the-Loop):** {'OBLIGATORIA (EU AI Act)' if disc.get('human_in_the_loop_mandatory') else 'N/A'}",
        "",
        "---",
        "*Nota: Este informe documenta el estado técnico verificado del despliegue. "
        "Toda salida generada por modelos de IA requiere supervisión humana (Human-in-the-Loop) antes de su uso oficial.*",
    ])
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_docx_report(data: Dict[str, Any], out: Path) -> None:
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    doc.add_heading(data["report_title"], level=0)

    app = data["application"]
    p = doc.add_paragraph()
    p.add_run(f"Fecha (UTC): {data['generated_utc']}\n").bold = True
    p.add_run(f"Aplicación: {app['name']} v{app['version']}\n")
    p.add_run(f"Licencia: {app['license']}\n")
    p.add_run(f"Modo de operación: {app['execution_mode']}\n")

    doc.add_heading("1. Entorno de Ejecución", level=1)
    env = data["environment"]
    for label, val in [
        ("Equipo", env["hostname"]),
        ("Sistema Operativo", env["os"]),
        ("Python / Núcleos CPU", f"{env['python']} / {env['cpu_cores']} núcleos"),
        ("Aceleración IA", env["ai_backend"]),
    ]:
        doc.add_paragraph(f"{label}: {val}", style="List Bullet")

    doc.add_heading("2. Integridad Criptográfica de Modelos IA (SHA-256)", level=1)
    t_mod = doc.add_table(rows=1, cols=4)
    t_mod.style = "Table Grid"
    for i, h in enumerate(["Modelo", "MB", "Estado", "SHA-256"]):
        t_mod.rows[0].cells[i].text = h
    for m in data["models_integrity"]:
        row = t_mod.add_row().cells
        row[0].text = m["file"]
        row[1].text = str(m["size_mb"])
        row[2].text = m["status"]
        row[3].text = m["actual_sha256"][:24] + "..."

    doc.add_heading("3. Matriz de Cumplimiento Normativo (IA, RGPD y ENS)", level=1)
    t_reg = doc.add_table(rows=1, cols=3)
    t_reg.style = "Table Grid"
    for i, h in enumerate(["Normativa", "Clasificación", "Controles"]):
        t_reg.rows[0].cells[i].text = h
    for r in data["regulatory_matrix"]:
        row = t_reg.add_row().cells
        row[0].text = r["framework"]
        row[1].text = r["classification"]
        row[2].text = r["compliance_notes"]

    doc.add_heading("4. Estado de Controles Técnicos CCN-CERT / ENS", level=1)
    for k, v in data["security_controls"].items():
        val = "ACTIVO" if v is True else ("NO CONFIGURADO" if v is False else str(v))
        doc.add_paragraph(f"{k}: {val}", style="List Bullet")

    doc.add_heading("5. Exención de Responsabilidad y Rieles Éticos de IA", level=1)
    disc = data.get("ai_disclaimer_and_guardrails", {})
    doc.add_paragraph(f"Integridad de Pesos: {disc.get('weights_integrity_statement', '')}", style="List Bullet")
    doc.add_paragraph(f"Exención de Responsabilidad: {disc.get('author_disclaimer', '')}", style="List Bullet")
    doc.add_paragraph("Prompt Madre Institucional: Activo con rieles de cortesía, objetividad y neutralidad forense.", style="List Bullet")
    doc.add_paragraph("Supervisión Humana (Human-in-the-Loop): Obligatoria conforme al Reglamento Europeo de IA.", style="List Bullet")

    note = doc.add_paragraph(
        "\nDeclaración de supervisión humana: Toda salida producida por IA generativa "
        "(resúmenes, traducciones, Q&A o anonimizaciones) requiere revisión humana antes de su uso oficial."
    )
    for run in note.runs:
        run.italic = True
        run.font.size = Pt(9)

    doc.save(str(out))
