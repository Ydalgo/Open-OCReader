# Política de Seguridad — Open OCReader

## Medidas de Seguridad Implementadas en la Aplicación

1. **Verificación Criptográfica (Integridad de Descargas)**:
   - Todos los modelos GGUF descargados (`Qwen3VL-4B`, `Qwen3VL-2B`, `mmproj` y `BGE-M3`) se validan mediante **SHA-256 en tiempo constante** antes de ejecutarse. Si el hash no coincide, el fichero se elimina automáticamente.
   - Los binarios de `llama.cpp` se verifican contra el `digest` SHA-256 o checksums oficiales del release, con modo estricto configurable (`OPEN_OCREADER_STRICT_VERIFY=1`).
   - El aprovisionador MSI para entornos cerrados (`provision_from_offline_repo.ps1`) calcula y verifica el hash SHA-256 de cada modelo antes de copiarlo a `C:\ProgramData\Open OCReader\` y aplica permisos restrictivos mediante `icacls` (solo lectura/ejecución para usuarios estándar, impidiendo secuestro de binarios o DLLs).
   - Solo se permiten descargas sobre **HTTPS**.

2. **Protección frente a Paquetes Maliciosos y Actualizaciones In-Place**:
   - Toda descompresión de paquetes (binarios `llama.cpp` y actualizaciones) pasa por `safe_extract_zip` / `safe_extract_tar`, bloqueando rutas con `../` (Zip-Slip), enlaces simbólicos fuera del destino y bombas de descompresión.
   - El sistema de actualización de código fuente (`updater.py`) restringe el tamaño máximo a 50 MB en streaming, admite validación SHA-256 y bloquea la inyección de binarios ejecutables (`.exe`, `.dll`, `.so`, `.bin`).

3. **Protección de Entradas Documentales y Herramientas PDF**:
   - Validación estricta de extensión, tamaño máximo (`100 MB`) y **firma mágica (Magic Bytes) específica por formato** (incluyendo cabecera doble `RIFF....WEBP` para WebP).
   - Límite de píxeles (`Image.MAX_IMAGE_PIXELS`) contra bombas de descompresión de imágenes y límite de páginas PDF (`300` en OCR, `500` en herramientas PDF de desbloqueo, firmas y marcas de agua).
   - **Mitigación contra Inyección Indirecta de Prompts (Indirect Prompt Injection)**: Sanitización automática de secuencias delimitadoras (`===`, `<|im_start|>`, `<|im_end|>`, etc.) en el texto documental antes de enviarlo al LLM, junto a directivas de seguridad en el prompt de sistema para que el modelo nunca ejecute instrucciones encontradas dentro de los documentos.
   - **Protección contra Inyección de Fórmulas en Excel (`CSV/Excel Injection`)**: Todo texto reconocido que comience por `=`, `+`, `-`, `@` o caracteres de control se neutraliza anteponiendo un apóstrofo antes de escribir la celda.

4. **Endurecimiento del Servidor Local (`llama-server`) y API REST (`FastAPI`)**:
   - `llama-server` se inicia exclusivamente en `127.0.0.1` con una **clave API aleatoria por sesión** pasada mediante fichero privado (`0600`, no visible en la lista de procesos) y CORS bloqueado.
   - La API REST exige **autenticación `X-API-Key` / `Bearer`** en tiempo constante (si se expone fuera de `127.0.0.1` sin clave, autogenera una automáticamente al arrancar).
   - **CORS restrictivo** por defecto (solo `localhost`), cabeceras de seguridad (`X-Content-Type-Options`, `X-Frame-Options: DENY`, `Cache-Control: no-store`), **Rate Limiting** por IP con purga periódica contra fugas de memoria en DDoS y soporte controlado para proxies inversos (`OPEN_OCREADER_TRUST_PROXY=1`).
   - El endpoint `/api/v1/health` público no revela telemetría de hardware interna ni rutas del sistema si el cliente no está autenticado.
   - El servicio Linux `systemd` corre con `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectSystem=strict` y rutas de escritura acotadas estrictamente a `logs/`, `models/`, `bin/`, `cache/` y `projects/`.

---

## Endurecimiento Recomendado en GitHub (`Ydalgo/Open-OCReader`)

Para blindar el repositorio público frente a ataques a la cadena de suministro:

1. **Activar Branch Protection en `main`** (`Settings -> Branches -> Add rule`):
   - *Require a pull request before merging*.
   - *Block force pushes* y *Prevent branch deletion*.
   - *Require signed commits* (firmas GPG o SSH).
2. **Activar Seguridad Nativa de GitHub** (`Settings -> Code security and analysis`):
   - **Secret scanning** + **Push protection** (bloquea automáticamente cualquier push que contenga un token o clave).
   - **Dependabot alerts** y **Dependabot security updates** (avisa de CVEs en `requirements.txt` y `requirements.lock.txt`).
   - *(Agradecimiento especial a **[GitHub Dependabot](https://github.com/dependabot) (`dependabot[bot]`)** por su mantenimiento proactivo de las dependencias de producción como `pillow`, `pypdf` y `python-multipart`).*
3. **Higiene de Tokens (PAT)**:
   - Usar **Fine-grained Personal Access Tokens** con caducidad corta (30–90 días) y permisos mínimos (solo el repositorio `Open-OCReader`).
   - Rotar y revocar inmediatamente cualquier token que haya sido compartido o expuesto en historial de chat o terminal.

---

## Cómo reportar una vulnerabilidad

Si encuentras un fallo de seguridad, por favor no abras un Issue público con el exploit. Contacta de forma privada a través de **GitHub Security Advisories** en el repositorio `Ydalgo/Open-OCReader`.
