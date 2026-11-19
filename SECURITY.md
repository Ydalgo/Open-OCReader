# Política de Seguridad — Open OCReader

## Medidas de Seguridad Implementadas en la Aplicación

1. **Verificación Criptográfica (Integridad de Descargas)**:
   - Todos los modelos GGUF descargados (`Qwen3VL-4B-Instruct` y `mmproj`) se validan mediante **SHA-256 en tiempo constante** antes de ejecutarse. Si el hash no coincide, el fichero se elimina automáticamente.
   - Los binarios de `llama.cpp` se verifican contra el `digest` SHA-256 publicado por GitHub Releases.
   - Solo se permiten descargas sobre **HTTPS**.

2. **Protección frente a Paquetes Maliciosos (Zip-Slip / Tar-Slip / Symlinks)**:
   - Toda descompresión de paquetes (binarios `llama.cpp` y actualizaciones) pasa por `safe_extract_zip` / `safe_extract_tar`, bloqueando rutas con `../`, enlaces simbólicos fuera del destino y bombas de descompresión.

3. **Protección de Entradas Documentales**:
   - Validación de extensión, tamaño máximo (`100 MB`) y **firma mágica (Magic Bytes)** antes de procesar cualquier fichero.
   - Límite de píxeles (`Image.MAX_IMAGE_PIXELS`) contra bombas de descompresión de imágenes y límite de páginas PDF (`300`).
   - **Protección contra Inyección de Fórmulas en Excel (`CSV/Excel Injection`)**: Todo texto reconocido que comience por `=`, `+`, `-`, `@` o caracteres de control se neutraliza anteponiendo un apóstrofo antes de escribir la celda.

4. **Endurecimiento del Servidor Local (`llama-server`) y API REST (`FastAPI`)**:
   - `llama-server` se inicia exclusivamente en `127.0.0.1` con una **clave API aleatoria por sesión** pasada mediante fichero privado (`0600`, no visible en la lista de procesos) y CORS bloqueado.
   - La API REST exige **autenticación `X-API-Key` / `Bearer`** en tiempo constante (si se expone fuera de `127.0.0.1` sin clave, autogenera una automáticamente al arrancar).
   - **CORS restrictivo** por defecto (solo `localhost`), cabeceras de seguridad (`X-Content-Type-Options`, `X-Frame-Options: DENY`, `Cache-Control: no-store`), **Rate Limiting** por IP y respuestas HTTP 500 saneadas sin fugar rutas internas.
   - El servicio Linux `systemd` corre con `NoNewPrivileges=true`, `PrivateTmp=true` y `ProtectSystem=strict`.

---

## Endurecimiento Recomendado en GitHub (`Ydalgo/Open-OCReader`)

Para blindar el repositorio público frente a ataques a la cadena de suministro:

1. **Activar Branch Protection en `main`** (`Settings -> Branches -> Add rule`):
   - *Require a pull request before merging*.
   - *Block force pushes* y *Prevent branch deletion*.
   - *Require signed commits* (firmas GPG o SSH).
2. **Activar Seguridad Nativa de GitHub** (`Settings -> Code security and analysis`):
   - **Secret scanning** + **Push protection** (bloquea automáticamente cualquier push que contenga un token o clave).
   - **Dependabot alerts** y **Dependabot security updates** (avisa de CVEs en `requirements.txt`).
3. **Higiene de Tokens (PAT)**:
   - Usar **Fine-grained Personal Access Tokens** con caducidad corta (30–90 días) y permisos mínimos (solo el repositorio `Open-OCReader`).
   - Rotar y revocar inmediatamente cualquier token que haya sido compartido o expuesto en historial de chat o terminal.

---

## Cómo reportar una vulnerabilidad

Si encuentras un fallo de seguridad, por favor no abras un Issue público con el exploit. Contacta de forma privada a través de **GitHub Security Advisories** en el repositorio `Ydalgo/Open-OCReader`.
