# Guía de Despliegue y Puesta en Marcha — Modo Servidor API REST

Esta guía detalla paso a paso cómo iniciar, configurar, proteger y verificar **Open OCReader** en **Modo Servidor API REST**, diseñado para integrarse con clientes web, aplicaciones internas o flujos automatizados en Windows y GNU/Linux.

---

## 1. Arquitectura del Modo Servidor

El modo servidor expone el motor OCR (`RapidOCR`) y el motor de IA local (`llama.cpp` + `Qwen3-VL-4B-Instruct`) a través de una API REST (**FastAPI + Uvicorn**) con documentación interactiva OpenAPI (**Swagger UI** en `/docs`).

* **Aislamiento de red**: Todos los documentos se procesan en memoria y directorios temporales privados (`0700`) dentro del propio servidor, eliminándose al finalizar cada petición.
* **Puerto configurable**: Por defecto escucha en el puerto **`8000`**, pero puede seleccionarse libremente mediante `--port`, parámetro del lanzador o la variable de entorno `OPEN_OCREADER_PORT`.

---

## 2. Puesta en Marcha en Windows

### Inicio rápido (puerto por defecto `8000` o puerto personalizado)
* **Puerto estándar (`8000`)**: Ejecuta `scripts\windows\iniciar_servidor.bat`.
* **Puerto personalizado (ejemplo `9090`)**:
  ```powershell
  scripts\windows\iniciar_servidor.bat 9090
  ```
  O directamente desde consola:
  ```powershell
  python src/ocr_server.py --host 0.0.0.0 --port 9090
  ```

### Autenticación automática
Si el servidor se enlaza a una interfaz de red externa (`0.0.0.0`) y no se ha definido `OPEN_OCREADER_API_KEY`, **autogenera una clave aleatoria segura** al arrancar y la muestra en consola.

Para fijar una clave persistente antes de arrancar:
```powershell
$env:OPEN_OCREADER_API_KEY="tu-clave-segura-de-32-caracteres"
$env:OPEN_OCREADER_PORT="8443"
python src/ocr_server.py --host 0.0.0.0
```

---

## 3. Verificación y Pruebas desde el Navegador (Swagger UI)

1. Abre un navegador y accede a `http://127.0.0.1:<PUERTO>/docs` (por ejemplo, `http://127.0.0.1:8000/docs`).
2. **Comprobar estado del servicio**: Despliega `GET /api/v1/health` → **Try it out** → **Execute**. Debe devolver HTTP `200` con `"status": "ok"`, el hardware detectado y el estado de los modelos.
3. **Probar conversión documental**: Despliega `POST /api/v1/convert` → **Try it out**:
   * Introduce tu clave en el campo `x-api-key`.
   * Selecciona un fichero PDF o imagen en `file`.
   * Especifica el formato deseado en `format` (`pdf`, `docx`, `xlsx`, `txt` o `json`).
   * Pulsa **Execute** para descargar el documento convertido.

---

## 4. Despliegue como Servicio Permanente en GNU/Linux (`systemd`)

```bash
# 1. Instalar dependencias y entorno virtual
chmod +x scripts/linux/*.sh
./scripts/linux/instalar.sh

# 2. Registrar y activar el servicio systemd endurecido
./scripts/linux/instalar_servicio.sh
```

Para cambiar el puerto en `systemd`, edita `/etc/systemd/system/open-ocreader.service` (flag `--port`), ejecuta `sudo systemctl daemon-reload` y reinicia el servicio:
```bash
sudo systemctl status open-ocreader
sudo systemctl restart open-ocreader
```

---

## 5. Cifrado en Tránsito (TLS 1.3) para Producción

En entornos corporativos o de la Administración Pública (ENS / CCN-CERT), el tráfico HTTP debe ir cifrado con **TLS 1.3**:

### Opción A: TLS directo en Uvicorn
```bash
python src/ocr_server.py --host 0.0.0.0 --port 8443 \
  --ssl-certfile /ruta/certificado.fullchain.pem \
  --ssl-keyfile /ruta/clave_privada.key
```

### Opción B: Proxy inverso Nginx (Recomendado)
Se incluye la plantilla endurecida **`deploy/nginx_tls13.conf`** configurada con **TLS 1.3 exclusivo**, HSTS y límite de subida de 100 MB.

---

## 6. Variables de Entorno de Configuración y Auditoría (SIEM / ENS)

| Variable | Descripción | Valor por defecto |
| :--- | :--- | :--- |
| `OPEN_OCREADER_HOST` | Interfaz de red de escucha | `127.0.0.1` |
| `OPEN_OCREADER_PORT` | Puerto TCP del servidor API | `8000` |
| `OPEN_OCREADER_API_KEY` | Clave secreta para autenticar peticiones (`X-API-Key` / `Bearer`) | Autogenerada en red externa |
| `OPEN_OCREADER_CORS_ORIGINS` | Orígenes web autorizados (separados por coma) | `http://127.0.0.1,http://localhost` |
| `OPEN_OCREADER_RATE_LIMIT` | Peticiones máximas por minuto y por IP | `30` |
| `OPEN_OCREADER_LOG_FORMAT` | Formato de logs (`text` o `json` para SIEM) | `text` |
| `OPEN_OCREADER_SYSLOG_HOST` | Host del colector Syslog/SIEM corporativo | *(desactivado)* |
| `OPEN_OCREADER_SYSLOG_PORT` | Puerto del colector Syslog/SIEM | `514` |
| `OPEN_OCREADER_LOCK_LOGS` | `1` bloquea el borrado de logs (inmutabilidad ENS) | `0` |

---

## 7. Despliegue Contenerizado (`Docker` / `Docker Compose`) e Interfaz Web Móvil

Puedes levantar el servidor REST completo **y** la interfaz Web responsiva 100 % offline para móviles y navegadores de escritorio mediante `Dockerfile` y `docker-compose.yml`:

### Arranque rápido HTTP (red local / intranet)
```bash
# Construye e inicia el contenedor no-root (usuario ocreader, puerto 8000)
docker compose up -d --build
```
* **Interfaz Web Móvil/PC**: abre `http://<IP-DEL-SERVIDOR>:8000/` (o `/app`) desde cualquier dispositivo en la red. Incluye captura de cámara/archivos, conversión, traducción, IA Local (`Lectura Fácil UNE 153101 EX` en `POST /api/v1/ai/easy-read`), anonimización RGPD y chat con citas literales, además de panel de accesibilidad integrado.
* **Swagger UI**: `http://<IP-DEL-SERVIDOR>:8000/docs`.

### Arranque en producción con Nginx TLS 1.3 (`--profile tls`)
1. Coloca `fullchain.pem` y `privkey.pem` en `./deploy/certs/`.
2. Inicia el stack completo con proxy inverso endurecido (`deploy/nginx_docker_tls13.conf`):
```bash
docker compose --profile tls up -d --build
```
Esto expone HTTPS **TLS 1.3** en el puerto **`8443`** (y redirección HTTP en **`8080`**).

### Volúmenes persistentes y límites de contenedor
* El servicio `open-ocreader-server` monta `./models`, `./bin`, `./cache`, `./logs` y `./config` en `/app/*`, ejecuta con `no-new-privileges:true`, usuario no privilegiado (`ocreader`, UID `10001`), telemetría desactivada (`HF_HUB_DISABLE_TELEMETRY=1`, `DO_NOT_TRACK=1`), límite de memoria configurable (`OCREADER_MEM_LIMIT`, `8g` por defecto) y `HEALTHCHECK` automático cada 30 s contra `/api/v1/health`.
