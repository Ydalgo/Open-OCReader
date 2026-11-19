# Guía de Instalación, Compilación y Uso - Open OCReader

## 1. Estructura del Proyecto

```text
Open OCReader/
├── src/                      # Código fuente en Python
│   ├── ocr_tool.py           # CLI principal
│   ├── Open_OCReader.pyw     # Lanzador gráfico sin consola
│   └── open_ocreader/        # Paquete modular (OCR, formatos, GUI, IA, logs)
├── scripts/
│   ├── windows/              # Scripts .bat y compilador .exe para Windows
│   └── linux/                # Scripts .sh de instalación, arranque y compilación
├── models/                   # Modelos GGUF locales (Qwen3-VL-4B-Instruct)
├── bin/                      # Binarios portables de llama.cpp por sistema operativo
├── dist/                     # Ejecutables compilados independientes
├── samples/                  # Documentos de muestra para pruebas
├── logs/                     # Logs rotativos de diagnóstico
└── docs/                     # Documentación técnica
```

---

## 2. Descarga de Modelos de IA (`models/`)

Los modelos de Inteligencia Artificial (`Qwen3VL-4B-Instruct-Q4_K_M.gguf` y `mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf`) no se incluyen directamente en el código fuente por su tamaño (~2,9 GB).

Al ejecutar cualquier función de IA (manuscritos, traducción, resumen, anonimización o preguntas), si el programa detecta que no están en `models/`, **te ofrecerá elegir entre dos fuentes de descarga**:

1. **Página Oficial (Hugging Face)**: Descarga directa desde `Qwen/Qwen3-VL-4B-Instruct-GGUF`.
2. **Proyecto GitHub**: Descarga desde las Releases oficiales de `Ydalgo/Open-OCReader`.

---

## 3. Uso en Windows

### Opción A: Sin Python instalado (Ejecutable compilado)
1. Descarga el paquete compilado de Windows desde **GitHub Releases** (o compílalo con `scripts\windows\compilar.bat`).
2. Ejecuta `dist\Open_OCReader\Open_OCReader.exe` o haz doble clic en `scripts\windows\iniciar.bat`.

### Opción B: Desde el código fuente
```powershell
pip install -r requirements.txt
# Abrir interfaz gráfica sin consola:
pythonw src\Open_OCReader.pyw
# O usar por terminal:
python src\ocr_tool.py samples\factura_prueba.png
```

### Compilar el `.exe` en Windows:
Haz doble clic en **`scripts\windows\compilar.bat`** (o ejecuta `python scripts\windows\build_exe.py --onefile` para un único fichero portátil).

---

## 4. Uso en Linux

### Instalación y arranque rápido:
```bash
chmod +x scripts/linux/*.sh
./scripts/linux/instalar.sh
./scripts/linux/iniciar.sh
```

### Compilar ejecutable independiente en Linux:
```bash
./scripts/linux/compilar.sh
```
Generará el binario listo en `dist/Open_OCReader/Open_OCReader`.
