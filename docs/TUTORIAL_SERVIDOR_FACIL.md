# 🧸 Tutorial Súper Fácil: Cómo poner en marcha el Modo Servidor de Open OCReader

> *Explicado paso a paso, sin palabros complicados, como si se lo explicaras a alguien que nunca ha montado un servidor.*

---

## 1. ¿Qué es el "Modo Servidor" y para qué sirve?

Imagina que **Open OCReader** es una ventanilla mágica de correos:
* Normalmente, tú abres la ventana en tu ordenador y arrastras un PDF o una foto.
* Con el **Modo Servidor**, dejas esa ventanilla abierta en un ordenador (o en un servidor de tu oficina) para que **otras páginas web, programas o compañeros de tu red** puedan enviarle fotos o PDFs por la red y recibir automáticamente:
  * El PDF buscable, Word o Excel.
  * Un resumen, una traducción al español o el documento anonimizado con IA.

---

## 2. Paso a Paso en Windows (en 2 minutos)

### Paso 1: Encender la ventanilla (el servidor)
1. Abre la carpeta del proyecto `Open OCReader`.
2. Entra en `scripts` → `windows`.
3. Haz **doble clic** en **`iniciar_servidor.bat`**.

Verás una ventana negra con algo parecido a esto:
```text
======================================================================
[SEGURIDAD] Clave API autogenerada para esta sesión: aBcDeFg123456...
[SEGURIDAD] Envíala en 'X-API-Key' o 'Authorization: Bearer <clave>'.
======================================================================
[Open OCReader Server] Escuchando en http://0.0.0.0:8000
[Open OCReader Server] Documentación Swagger UI: http://0.0.0.0:8000/docs
```

🔑 **¡Ojo a la contraseña!** Como el servidor escucha en tu red, se inventa automáticamente una **llave secreta (`Clave API`)** para que ningún desconocido pueda colarse. Cópiala si vas a hacer pruebas.

*(Si quieres elegir tú mismo la contraseña en vez de que sea aleatoria, escribe antes en PowerShell: `$env:OPEN_OCREADER_API_KEY="mi-clave-super-secreta"` y luego `python src/ocr_server.py --host 0.0.0.0 --port 8000`).*

---

### Paso 2: Probarlo desde tu navegador (sin escribir código)
1. Abre Chrome, Edge o Firefox en tu ordenador.
2. Escribe en la barra de direcciones:
   👉 **`http://127.0.0.1:8000/docs`**
3. Verás una página interactiva con botones de colores (**Swagger UI**):
   * Pulsa en **`GET /api/v1/health`** → **Try it out** → **Execute**.
     Si responde `"status": "ok"`, ¡tu servidor está vivo y funcionando! 🎉
   * Pulsa en **`POST /api/v1/convert`** → **Try it out**:
     - En **`x-api-key`** pega la clave secreta que apareció en la ventana negra.
     - En **`file`** elige una imagen o PDF de tu ordenador.
     - En **`format`** escribe `pdf`, `docx`, `xlsx` o `txt`.
     - Pulsa **Execute** → abajo te aparecerá un enlace **Download file** con tu documento ya convertido.

---

### Paso 3: ¿Cómo lo apago?
Simplemente cierra la ventana negra (o pulsa `Ctrl + C` dentro de ella). ¡Listo!

---

## 3. Paso a Paso en Linux (para que arranque solo siempre)

Si tienes un ordenador o servidor con **Ubuntu / Debian / Linux**:

### Paso 1: Instalar todo
Abre una terminal en la carpeta de `Open OCReader` y escribe:
```bash
chmod +x scripts/linux/*.sh
./scripts/linux/instalar.sh
```

### Paso 2: Encenderlo para que arranque solo al encender el PC
```bash
./scripts/linux/instalar_servicio.sh
```
¡Ya está! Eso instala un servicio del sistema (`systemd`) con medidas de seguridad activadas.

### Paso 3: Comandos útiles en Linux
* **Ver si está funcionando**: `sudo systemctl status open-ocreader`
* **Reiniciarlo**: `sudo systemctl restart open-ocreader`
* **Apagarlo**: `sudo systemctl stop open-ocreader`

---

## 4. Ponerle el "Candado Verde" (HTTPS / TLS 1.3) para empresas o Administración

Si vas a usar el servidor dentro de una red de empresa o Administración Pública, **nunca envíes documentos sin cifrar (HTTP)**. Tienes dos formas facilísimas de ponerle candado HTTPS:

### Forma A (Directa, con tus certificados `.pem`)
```bash
python src/ocr_server.py --host 0.0.0.0 --port 8443 \
  --ssl-certfile /ruta/a/certificado.pem \
  --ssl-keyfile /ruta/a/clave_privada.key
```

### Forma B (Profesional con Nginx)
Ya hemos dejado lista una plantilla con **TLS 1.3 exclusivo** en **`deploy/nginx_tls13.conf`**. Solo tienes que cambiar `ocr.tu-organizacion.es` por el dominio de tu servidor y copiarla a `/etc/nginx/sites-enabled/`.

---

## 5. Opciones Extra para Administradores (SIEM y Auditoría ENS)

Si tu empresa tiene un sistema de monitorización de seguridad (**SIEM** como Wazuh, Splunk o Elastic), basta con añadir estas variables de entorno antes de arrancar el servidor:

| Variable | Qué hace | Ejemplo |
| :--- | :--- | :--- |
| `OPEN_OCREADER_API_KEY` | Fija la contraseña de acceso a la API | `mi-clave-larga-32-chars` |
| `OPEN_OCREADER_CORS_ORIGINS` | Qué páginas web tienen permiso para llamar al servidor | `https://intranet.miempresa.es` |
| `OPEN_OCREADER_LOG_FORMAT` | Cambia los logs a formato JSON para máquinas | `json` |
| `OPEN_OCREADER_SYSLOG_HOST` | Envía cada evento en directo a tu SIEM | `10.0.0.50` |
| `OPEN_OCREADER_LOCK_LOGS` | Impide que nadie pueda borrar los logs (auditoría ENS) | `1` |
