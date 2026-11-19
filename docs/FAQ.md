# Preguntas Frecuentes y Solución de Problemas (FAQ) — Open OCReader

---

## 1. Windows SmartScreen muestra un aviso al abrir `Open_OCReader.exe`
**¿Por qué aparece?**  
Cuando se compila un ejecutable nuevo de código abierto sin un certificado comercial de firma de código (*Code Signing*), Windows SmartScreen muestra un aviso preventivo de *"Windows protegió su PC"*.

**Solución para uso personal:**
1. Pulsa **Más información** → **Ejecutar de todas formas**.
2. También puedes verificar el código fuente completo en `src/` o compilar tu propio `.exe` ejecutando `scripts\windows\compilar.bat`.

**Solución para empresas y Administración Pública (ENS):**  
Firma el binario con el certificado corporativo `.pfx` directamente al compilar:
```powershell
python scripts/windows/build_exe.py --sign-pfx ruta\certificado.pfx --sign-password tu_clave
```

---

## 2. El puerto `8000` ya está en uso al iniciar el Modo Servidor
Puedes elegir cualquier otro puerto libre de tres formas:
* **En Windows**: `scripts\windows\iniciar_servidor.bat 9090`
* **Por terminal**: `python src/ocr_server.py --host 0.0.0.0 --port 9090`
* **Por variable de entorno**: `OPEN_OCREADER_PORT=9090`

---

## 3. ¿Funciona completamente sin conexión a Internet (*Air-Gapped*)?
**Sí.** Una vez descargados los modelos (`models/`) y el binario `llama.cpp` (`bin/`), puedes desconectar el ordenador o servidor de Internet por completo.
* El OCR rápido (`RapidOCR`) y la IA (`Qwen3-VL-4B-Instruct`) operan 100% en local.
* La telemetría externa está desactivada por código (`HF_HUB_DISABLE_TELEMETRY=1`, `DO_NOT_TRACK=1`).

---

## 4. El modo IA va lento o falla con mi tarjeta gráfica (GPU)
* Open OCReader detecta automáticamente si tienes aceleración **Vulkan** (Windows/Linux) o **Apple Metal** (macOS).
* Si tu GPU no tiene suficiente memoria disponible para `Qwen3-VL-4B` (~5 GB), el gestor detecta el fallo al arrancar y **cambia automáticamente a modo CPU seguro** sin intervención manual.
* Además, el modelo **permanece cargado en memoria** tras la primera consulta para que las siguientes preguntas, resúmenes o traducciones sean mucho más rápidas.

---

## 5. ¿Cómo actualizo `llama.cpp` o limpio compilaciones antiguas (`build/`, `dist/`)?
* **Desde la GUI**: Pulsa **♻️ Limpiar/Reinstalar** en la barra superior y elige qué componentes refrescar.
* **Desde Windows**: Haz doble clic en `scripts\windows\limpiar_y_reinstalar.bat`.
* **Por terminal**: `python src/ocr_tool.py --clean-reinstall`

---

## 6. ¿Por qué el botón "Borrar Logs" me dice que está bloqueado?
Si la variable de entorno `OPEN_OCREADER_LOCK_LOGS=1` está activada (modo auditoría ENS / CCN-CERT), el borrado de logs se deshabilita a propósito para garantizar la inmutabilidad de la pista de auditoría.

---

## 7. ¿Cómo puedo contactar o colaborar con el proyecto?
Puedes comunicarte directamente a través de GitHub:
* **Reportar fallos o sugerir mejoras**: [GitHub Issues](https://github.com/Ydalgo/Open-OCReader/issues)
* **Enviar código o traducciones**: [Pull Requests](https://github.com/Ydalgo/Open-OCReader/pulls)
* **Reportar vulnerabilidades de seguridad en privado**: Consulta [SECURITY.md](../SECURITY.md)
