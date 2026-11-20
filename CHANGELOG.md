# Registro de Cambios (Changelog) — Open OCReader

Todos los cambios notables de este proyecto se documentan en este fichero.

---

## [0.3.1] - 2026-11-20

### Añadido y Reconocimientos
* **Reconocimiento y Créditos al Proyecto Hermano GuarIdA**:
  * Inclusión de atribución formal y detallada en `README.md`, `docs/CUMPLIMIENTO_IA_Y_LICENCIA.md` y la ventana `⚖️ Legal / IA` de la interfaz gráfica.
  * Desglose explícito de los componentes estructurales y algoritmos adaptados del proyecto hermano **[GuarIdA](https://github.com/Ydalgo/GuarIdA)**: Árbol de Nodos Documental (AST), Compresión BPE/Minificación, Búsqueda Híbrida RRF (BM25Okapi + BGE-M3), Persistencia Segregada SQLite WAL comprimida por SHA-256, Observación Dinámica de Hardware y Reutilización de KV Cache (`cache_prompt`).
  * Enlace visible y botón interactivo en la GUI para invitar a la comunidad a conocer, seguir y colaborar en el proyecto GuarIdA.
* **Descargo de Responsabilidad e Integridad de Pesos Neuronales**:
  * Declaración legal y técnica explícita en `README.md`, `docs/CUMPLIMIENTO_IA_Y_LICENCIA.md`, `gui.py` e informe de gobernanza `governance.py`.
  * Se aclara formalmente que Open OCReader ejecuta modelos abiertos oficiales (`Qwen3-VL` y `BGE-M3`) **sin modificar, alterar ni entrenar sus pesos numéricos originales**, y que el autor no asume responsabilidad alguna por respuestas groseras, imprecisas o alucinadas que el modelo de terceros pudiera generar.
* **Prompt Madre Institucional y Rieles de Comportamiento (`guardrails.py`)**:
  * Sistema centralizado de guardrails inyectado como base en todas las tareas generativas (`document_qa.py`, `multi_doc_chat.py`, `translator.py`).
  * Impone rieles de cortesía innegociable, respeto absoluto, neutralidad forense ante documentos conflictivos, rigor analítico, honestidad ante lagunas de información y obligación estricta de responder siempre en el idioma activo de la interfaz del programa.
* **Nueva pestaña `🌐 Traducir Documento` (Traducción directa fiel a fichero)**:
  * Traducción contextual completa directa a **10 formatos** (`PDF`, `PDF/A-2b`, `Word .docx`, `LibreOffice .odt`, `eBook .epub`, `XLSX`, `ODS`, `CSV`, `TXT`, `JSON`), con fusión de líneas sin mezclar columnas (`merge_boxes_into_contextual_lines`), preservación de fondos/imágenes (*inpainting* sobre cajas originales), escala de grises, compresión y endpoint REST `POST /api/v1/ai/translate-document`.
* **Exportación de Conversaciones y Preguntas con Referencias Literales (`conversation_exporter.py`)**:
  * En **💬 Chat con Archivos** y **🧠 IA y Manuscritos** (con barra directa de pregunta integrada), exportación completa a **8 formatos** (`DOCX`, `PDF`, `PDF/A-2b`, `ODT`, `EPUB`, `Markdown`, `TXT`, `JSON`) anexando para cada cita el **texto literal íntegro extraído de los documentos originales**, además de soporte `export_format` y `references[].literal_text` en `POST /api/v1/ai/ask`.
* **Actualización de Dependencias y Agradecimiento a GitHub Dependabot (`PR #1`)**:
  * Integración y fusión limpia del Pull Request #1 de `dependabot[bot]` (`pillow>=13.0.0`, `pypdf>=6.21.4`, `python-multipart>=0.0.31`) manteniendo actualizadas las librerías en `requirements.txt` y `requirements.lock.txt`.
  * Agradecimiento formal a **GitHub Dependabot** en `README.md` y `SECURITY.md` por su auditoría continua de la cadena de suministro.
* **Iconos Vectoriales en Color Anti-Aliased, Logotipo de Cabecera y Capturas v0.3.1**:
  * Sustitución de los glifos monocromos de Tkinter/GDI por iconos vectoriales a todo color supermuestreados 4x (`LANCZOS`) en las 6 pestañas y en todos los botones superiores de acciones, junto al logotipo oficial en cabecera (`ico/Open_OCReader.png`).
  * Actualización de las capturas de pantalla reales en `docs/screenshots/` (`gui_conversion.png`, `gui_translate.png`, `gui_chat.png`, `gui_ia.png`) mostradas en la portada de `README.md`.

### Seguridad y Auditoría Completa
* **Mitigación contra Inyección Indirecta de Prompts (Indirect Prompt Injection)**:
  * Nueva función `sanitize_llm_input` que neutraliza delimitadores y tokens de control (`===`, `<|im_start|>`, `<|im_end|>`, etc.) en textos de documentos no confiables antes de inyectarlos al LLM.
  * Instrucciones defensivas en el system prompt de `document_qa.py`, `multi_doc_chat.py` y `translator.py`.
* **Verificación estricta de Firmas Mágicas (Magic Bytes)**:
  * Comprobación estricta por extensión en `security.py`, requiriendo cabecera dual `RIFF....WEBP` para imágenes WebP y rechazando contenedores multimedia ajenos.
* **Blindaje de Actualizador In-Place (`updater.py`)**:
  * Límite defensivo de 50 MB en streaming contra bombas de descompresión / DoS, validación opcional de hash SHA-256 y bloqueo estricto de binarios ejecutables (`.exe`, `.dll`, `.so`, `.bin`).
* **Protección DoS en Herramientas PDF (`pdf_tools.py`)**:
  * Validación obligatoria de archivos con `validate_input_file()` y límite de seguridad de 300 páginas (`MAX_PDF_PAGES`) en desbloqueo, firmas, marcas de agua y optimización.
* **Aprovisionamiento Offline MSI Endurecido (`provision_from_offline_repo.ps1`)**:
  * Validación criptográfica SHA-256 (`Get-FileHash`) de cada modelo GGUF antes de copiar a `ProgramData`.
  * Fijación de permisos ACL restrictivos con `icacls` (solo lectura/ejecución para usuarios estándar, impidiendo secuestro de binarios o DLLs).
* **Integridad Obligatoria de Binarios llama.cpp (`runtime_manager.py`)**:
  * Extracción de digest SHA-256 de notas de versión y rechazo obligatorio incondicional (`raise SecurityError`) si no se dispone de verificación criptográfica.
* **Endurecimiento de Servidor API REST (`server/api.py`)**:
  * Uso de `X-Real-IP` si la conexión procede de `127.0.0.1` (proxy Nginx) y soporte para `OPEN_OCREADER_TRUST_PROXY=1`.
  * Purga periódica de buckets inactivos en el middleware de rate-limiting para evitar fugas de memoria en DDoS.
  * Respuesta mínima sin autenticar en `/api/v1/health` (`{"status": "ok", "version": "..."}`), exponiendo el detalle de hardware únicamente con `X-API-Key` válida.
* **Servicio Linux endurecido (`scripts/linux/open-ocreader.service`)**:
  * Inclusión de `cache/` y `projects/` en `ReadWritePaths=` para garantizar persistencia de SQLite WAL en sistemas con `ProtectSystem=strict`.

---

## [0.3.0] - 2026-11-19

### Añadido
* **Detección inteligente de PDFs ya buscables (0 OCR redundante)**: analiza página a página si el PDF ya tiene texto embebido para extraerlo en milisegundos en IA y Conversión (con opción *Forzar OCR*).
* **Nuevos formatos de salida y fidelidad visual**:
  * **PDF/A-2b** (estándar oficial de archivo para Administraciones Públicas con perfil ICC sRGB y metadatos XMP `pdfaid`).
  * **Compresión PDF** (*Alta calidad*, *Equilibrada*, *Máxima compresión*) y opción **Escala de grises**.
  * **Word (`.docx`) y OpenDocument Text (`.odt`) fieles**: `pdf2docx` en PDFs nativos y reconstrucción exacta con fondo preservado (*inpainting* OpenCV) + cuadros de texto editables con color y tamaño reales en escaneos.
  * **OpenDocument Calc (`.ods`)**, **CSV (`.csv`)** y **eBook EPUB 3 (`.epub`)**.
* **Nueva pestaña "🛠️ Herramientas PDF"** (`pikepdf` + `PyMuPDF` + `OpenCV`):
  * Desbloqueo de PDFs (restricciones o contraseña autorizada), eliminación de firmas digitales (`/Sig`), limpieza de marcas de agua (vectoriales, OCG y escaneos) y optimización directa.
  * Aviso legal de uso legítimo y política ENS `OPEN_OCREADER_DISABLE_PDF_TOOLS=1`.
* **Motor IA vinculado al Hardware + Árbol AST Híbrido (inspirado en GuarIdA)**:
  * Perfiles automáticos de hardware (`ocr_only` / `ultra_light` / `light` / `standard` / `pro`) que adaptan la interfaz (ocultando funciones incompatibles con aviso claro) y seleccionan `Qwen3-VL-4B` o `Qwen3-VL-2B` (Apache 2.0) + **`BGE-M3` (MIT)** con verificación SHA-256 oficial y protección anti-OOM.
  * **Nueva pestaña "💬 Chat con Archivos" (Multi-Documento con Citas)**: carga múltiples PDFs/imágenes identificados como `[DOC-1]`, `[DOC-2]`, ..., guarda y recarga **proyectos por SHA-256** sin re-indexar, y justifica cada respuesta citando documento y sección con streaming en tiempo real (`UTF-8`).
  * **Nueva pestaña "🔒 Anonimizar (RGPD)" en 2 pasos**: Paso 1 determinista 100% Python (funciona en cualquier hardware sin IA) + Paso 2 opcional potenciado con IA local en hardware compatible.
  * **Árbol de Nodos Documental (AST) + BM25/RRF + Compresión BPE + KV Cache (`cache_prompt`)** y **caché persistente SQLite WAL comprimida (`zstd`/`zlib`) por SHA-256** (`doc_ast_cache.db`).
* **Accesibilidad, Idiomas y Despliegue Empresarial**:
  * Soporte **HiDPI nativo en Windows**, detección automática de **tema claro/oscuro del SO**, **Zoom en textos** (`A-`/`A+` y `Ctrl+Rueda`), y nuevo idioma **Sueco (`Svenska`)** para interfaz, IA y traducción contextual.
  * **Kit Instalador Empresarial MSI (`build_msi.py` + `prepare_offline_repo.py` + `compilar_msi.bat`)**: descarga automática de WiX v5 + `offline_repo/` universal (GPU Vulkan + CPU + modelos 4B/2B/BGE-M3), aprovisionamiento por hardware en `C:\ProgramData\Open OCReader\` y rutas escribibles por usuario en `%LOCALAPPDATA%\Open OCReader\` sin requerir permisos de administrador ni Python instalado.
  * **Modo Servidor API REST actualizado**: soporta los 10 formatos, extracción sin OCR en PDFs buscables, anonimización 2 pasos y endpoints `/api/v1/pdf/{unlock|remove-signatures|remove-watermarks|optimize}`.
* **Modo instancia única** (Mutex Windows / `flock` Linux), cierre automático de procesos `llama-server` huérfanos, archivo oficial `LICENSE` (GNU GPL v3.0) y vínculo directo a GitHub en la interfaz.

### Mejorado
* **Script de compilación (`build_exe.py`)**: fases en tiempo real, progreso de compilación C de Nuitka (`--show-progress`), tiempo transcurrido y ETA estimado.
* **Limpieza robusta (`maintenance.py` y `limpiar_y_reinstalar.bat`)**: cierra procesos zombies (`Open_OCReader.exe`, `llama-server.exe`), gestiona archivos de solo lectura y reporta explícitamente cualquier archivo bloqueado.
* **Documentación y Gobernanza**: matriz completa ENS / EU AI Act / Licencias por modelo con SHA-256 verificados y SBOM CycloneDX actualizado.

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
