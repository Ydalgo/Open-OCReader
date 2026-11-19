# Open OCReader 📄🔍🧠

[![Licencia: MIT](https://img.shields.io/badge/Licencia-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Versión de Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![Plataforma](https://img.shields.io/badge/plataforma-windows%20%7C%20linux%20%7C%20macos-lightgrey)]()
[![100% Offline](https://img.shields.io/badge/Privacidad-100%25%20Offline-success)]()
[![Contribuciones bienvenidas](https://img.shields.io/badge/PRs-bienvenidas-brightgreen.svg)](https://github.com/Ydalgo/Open-OCReader/pulls)

**Open OCReader** es una suite de código abierto, ligera y **100% local (offline)** para la digitalización fiel de documentos y su análisis semántico mediante Inteligencia Artificial.

---

## 📁 Estructura del Proyecto

```text
Open OCReader/
├── src/                      # Código fuente en Python
│   ├── ocr_tool.py           # CLI principal
│   ├── Open_OCReader.pyw     # Lanzador gráfico sin consola
│   └── open_ocreader/        # Núcleo modular (OCR, formatos, GUI, IA local, logs)
├── scripts/
│   ├── windows/              # Scripts .bat y compilador .exe (build_exe.py)
│   └── linux/                # Scripts .sh de instalación, ejecución y compilación
├── models/                   # Modelos GGUF locales (Qwen3-VL-4B-Instruct)
├── bin/                      # Binarios portables de llama.cpp por sistema operativo
├── dist/                     # Ejecutables independientes compilados
├── samples/                  # Muestra de prueba (factura_prueba.png)
└── docs/                     # Guías de instalación y uso por plataforma
```

---

## 🌟 Arquitectura en Dos Pilares

1. **Pilar 1: Digitalización Estructural Rápida (`RapidOCR / ONNX`)**
   - Extrae el 100% del texto de imágenes (`JPG`, `PNG`, `TIFF`, `BMP`, `WebP`) y `PDF` multipágina.
   - **PDF Buscable (Sandwich)**: Mantiene la imagen original intacta al 100% con una capa de texto invisible alineada por coordenadas.
   - Exportación a **Word (`.docx`)**, **Excel (`.xlsx`)**, **Texto (`.txt`)** y **JSON (`.json`)**.

2. **Pilar 2: Inteligencia Documental Local (`llama.cpp` + `Qwen3-VL-4B-Instruct`)**
   - **El modelo permanece cargado en memoria** durante toda la sesión para responder al instante.
   - **✍️ OCR sobre Letra Manuscrita**: Lee caligrafía humana difícil mediante visión multimodal.
   - **🌐 Traducción al Español**: Traduce documentos de cualquier idioma manteniendo términos técnicos.
   - **🔒 Anonimización RGPD**: Ocultación híbrida (Regex + IA) de DNI, NIE, CIF, IBAN, teléfonos, correos, nombres y direcciones.
   - **💬 Preguntas y Resúmenes (Q&A)**: Haz preguntas directas sobre el contenido o genera resúmenes ejecutivos.

---

## 📥 Descarga según tu Sistema Operativo

### 🪟 Windows

* **Sin Python instalado (Recomendado para usuarios)**:
  1. Descarga la versión compilada en la sección **Releases** de GitHub (o compílala tú mismo con `scripts\windows\compilar.bat`).
  2. Haz doble clic en **`scripts\windows\iniciar.bat`** (o directamente en `dist\Open_OCReader\Open_OCReader.exe`).
* **Desde el código fuente**:
  ```powershell
  git clone https://github.com/Ydalgo/Open-OCReader.git
  cd Open-OCReader
  pip install -r requirements.txt
  pythonw src\Open_OCReader.pyw
  ```

### 🐧 Linux

```bash
git clone https://github.com/Ydalgo/Open-OCReader.git
cd Open-OCReader
chmod +x scripts/linux/*.sh
./scripts/linux/instalar.sh
./scripts/linux/iniciar.sh
```
*(Para generar un binario independiente en Linux sin Python: `./scripts/linux/compilar.sh`).*

---

## 🤖 Descarga Automática de Modelos de IA

Si descargas el código fuente y la carpeta `models/` está vacía, al pulsar cualquier función de IA la aplicación te permitirá elegir desde dónde descargar **Qwen3-VL-4B-Instruct**:
* **🌐 Página Oficial (Hugging Face)**: `Qwen/Qwen3-VL-4B-Instruct-GGUF`
* **🐙 Proyecto GitHub**: Releases oficiales de `Ydalgo/Open-OCReader`

Los binarios portables de `llama.cpp` para tu sistema operativo (`Windows`, `Linux` o `macOS`) se descargan automáticamente en `bin/`.

---

## 💻 Uso desde Terminal (CLI)

```bash
# Abrir interfaz gráfica (Drag & Drop, Ctrl+V, sin ventana CMD)
python src/ocr_tool.py

# Convertir a PDF buscable manteniendo el diseño original
python src/ocr_tool.py samples/factura_prueba.png

# Exportar tabla a Excel o Word
python src/ocr_tool.py samples/factura_prueba.png -f xlsx
python src/ocr_tool.py documento.pdf -f docx

# Funciones de IA local
python src/ocr_tool.py carta_manuscrita.jpg -m
python src/ocr_tool.py contrato.pdf --ai summarize
python src/ocr_tool.py manual_en.pdf --ai translate
python src/ocr_tool.py nomina.pdf --ai anonymize
python src/ocr_tool.py factura.png --ai ask --question "¿Cuál es el total?"
```

---

## 📄 Licencia y Autoría

Distribuido bajo licencia **MIT**.

* **Ydalgo** — Creador y mantenedor del proyecto
* **Antigravity** (Google DeepMind) — Asistente de arquitectura y desarrollo

Para más detalles, consulta [docs/INSTALACION_Y_USO.md](docs/INSTALACION_Y_USO.md).
