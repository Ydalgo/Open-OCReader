# Registro de Cambios (Changelog) — Open OCReader

Todos los cambios notables de este proyecto se documentan en este fichero.

---

## [0.2.0] - 2026-11-19

### Añadido
* **Fase 2 — Inteligencia Documental Local (`llama.cpp` + `Qwen3-VL-4B-Instruct`)**:
  * Detección automática de hardware multiplataforma (GPU **Vulkan**, **Apple Metal** y **CPU**) con respaldo automático a CPU.
  * Modelo residente en memoria durante toda la sesión (sin recargas entre texto y visión).
  * **OCR sobre letra manuscrita** mediante visión multimodal (`Qwen3-VL` + `mmproj`).
  * **Traducción contextual al español**, **resúmenes ejecutivos**, **Q&A sobre el documento** y **anonimización híbrida RGPD** (Regex determinista + IA).
  * Selector de fuente de descarga de modelos (Página Oficial Hugging Face o Releases de GitHub).
* **Interfaz Gráfica Mejorada (`GUI`)**:
  * Dos pestañas: *Conversión Estructural* e *IA Local y Manuscritos*.
  * Zona de **Arrastrar y Soltar (Drag & Drop)** y **Pegar (`Ctrl+V`)** de ficheros, rutas y capturas de pantalla.
  * Menú contextual (clic derecho) y atajos `Ctrl+C` / `Ctrl+A` en la caja de resultados.
  * Lanzador sin terminal (`Open_OCReader.pyw`) e icono oficial integrado (`ico/Open_OCReader.ico` y `.png`).
  * Barra de mantenimiento y cumplimiento: **⚖️ Legal / IA**, **🔄 Actualizar**, **♻️ Limpiar/Reinstalar**, **🧹 Caché**, **🗑️ Logs** y **📋 Logs**.
* **Modo Servidor API REST (`FastAPI` + `Uvicorn`)**:
  * Endpoints `/api/v1/health`, `/convert`, `/governance` y `/ai/*` con Swagger UI en `/docs`.
  * Puerto configurable (`--port`, `OPEN_OCREADER_PORT`, `iniciar_servidor.bat <puerto>`).
  * Cifrado **TLS 1.3** nativo (`--ssl-certfile`/`--ssl-keyfile`) y plantilla **Nginx TLS 1.3** (`deploy/nginx_tls13.conf`).
  * Servicio Linux `systemd` endurecido (`scripts/linux/open-ocreader.service`).
* **Endurecimiento de Ciberseguridad (CCN-CERT / ENS) y Gobernanza IA**:
  * Módulo `security.py`: verificación **SHA-256** de modelos y binarios, anti **Zip-Slip/Tar-Slip**, validación de *Magic Bytes*, límites anti-DoS, anti **inyección de fórmulas en Excel**, clave efímera para `llama-server`, autenticación `X-API-Key`, CORS restrictivo y Rate Limiting.
  * Logs rotativos con soporte **SIEM/Syslog JSON** y bloqueo de inmutabilidad (`OPEN_OCREADER_LOCK_LOGS=1`).
  * **Informes de Gobernanza IA y ENS en 1 clic** (`.docx`, `.md`, `.json`) y generador **SBOM CycloneDX 1.5** (`docs/sbom_cyclonedx.json` + `requirements.lock.txt`).
  * Cambio de licencia a **GNU GPL v3.0 (Copyleft fuerte)** y documentación de cumplimiento normativo (EU AI Act, RGPD, LOPDGDD, ENS, NIST AI RMF, ISO/IEC 42001).
* **Compilación nativa con Nuitka** (con respaldo PyInstaller), firma digital *Code Signing* (`--sign-pfx`) y manifiesto `SHA256SUMS.txt`.

---

## [0.1.0] - 2026-11-19

### Añadido
* **Fase 1 — Digitalización Estructural Offline (`RapidOCR / ONNX`)**:
  * Conversión fiel a **PDF Buscable (Sandwich)** con capa de texto invisible alineada por coordenadas.
  * Exportación a **Word (`.docx`)**, **Excel (`.xlsx`)**, **Texto (`.txt`)** y **JSON (`.json`)**.
  * Soporte para imágenes (`JPG`, `PNG`, `TIFF`, `BMP`, `WebP`) y `PDF` multipágina (`pypdfium2`).
  * Interfaz CLI (`ocr_tool.py`) y primera versión de GUI.
