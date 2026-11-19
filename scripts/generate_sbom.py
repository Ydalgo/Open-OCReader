#!/usr/bin/env python3
"""
Generador de SBOM (Software Bill of Materials) estándar CycloneDX 1.5
y fichero de dependencias fijadas (requirements.lock.txt) para auditorías ENS / CCN-CERT.

Uso:
    python scripts/generate_sbom.py
"""

import importlib.metadata as md
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path


def parse_direct_requirements(req_file: Path) -> list[str]:
    names = []
    for line in req_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pkg = re.split(r"[>=<!~\s\[]", line, maxsplit=1)[0].strip()
        if pkg:
            names.append(pkg)
    return names


def generate():
    base_dir = Path(__file__).resolve().parent.parent
    req_file = base_dir / "requirements.txt"
    lock_file = base_dir / "requirements.lock.txt"
    sbom_file = base_dir / "docs" / "sbom_cyclonedx.json"

    direct_pkgs = parse_direct_requirements(req_file)
    lock_lines = [
        "# Dependencias fijadas automáticamente por scripts/generate_sbom.py",
        f"# Generado UTC: {datetime.now(timezone.utc).isoformat()}",
        "",
    ]

    components = []
    seen = set()

    for pkg_name in direct_pkgs:
        try:
            dist = md.distribution(pkg_name)
        except md.PackageNotFoundError:
            continue

        norm_name = dist.metadata["Name"]
        version = dist.version
        if norm_name.lower() in seen:
            continue
        seen.add(norm_name.lower())

        lock_lines.append(f"{norm_name}=={version}")

        lic = dist.metadata.get("License") or dist.metadata.get("License-Expression") or "UNKNOWN"
        lic = lic.splitlines()[0].strip()[:80]
        purl = f"pkg:pypi/{norm_name.lower()}@{version}"

        components.append({
            "type": "library",
            "name": norm_name,
            "version": version,
            "purl": purl,
            "licenses": [{"license": {"name": lic}}],
            "scope": "required",
        })

    # Añadir componentes IA y binarios externos declarados
    components.extend([
        {
            "type": "machine-learning-model",
            "name": "Qwen3-VL-4B-Instruct-GGUF",
            "version": "Q4_K_M",
            "hashes": [{"alg": "SHA-256", "content": "66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a"}],
            "licenses": [{"license": {"id": "Apache-2.0"}}],
        },
        {
            "type": "application",
            "name": "llama.cpp",
            "version": "b12547+",
            "licenses": [{"license": {"id": "MIT"}}],
        },
    ])

    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": {
                "type": "application",
                "name": "Open OCReader",
                "version": "0.2.0",
                "licenses": [{"license": {"id": "GPL-3.0-only"}}],
                "supplier": {"name": "Ydalgo"},
            },
        },
        "components": components,
    }

    lock_file.write_text("\n".join(lock_lines) + "\n", encoding="utf-8")
    sbom_file.parent.mkdir(parents=True, exist_ok=True)
    sbom_file.write_text(json.dumps(sbom, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"✓ Dependencias fijadas guardadas en: {lock_file} ({len(seen)} paquetes)")
    print(f"✓ SBOM CycloneDX 1.5 generado en:    {sbom_file} ({len(components)} componentes)")


if __name__ == "__main__":
    generate()
