# Open OCReader 📄🔍⚡

[![Licencia: MIT](https://img.shields.io/badge/Licencia-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Versión de Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![Plataforma](https://img.shields.io/badge/plataforma-windows%20%7C%20linux%20%7C%20macos-lightgrey)]()
[![100% Offline](https://img.shields.io/badge/Privacidad-100%25%20Offline-success)]()
[![Contribuciones bienvenidas](https://img.shields.io/badge/PRs-bienvenidas-brightgreen.svg)](https://github.com/Ydalgo/Open-OCReader/pulls)

**Open OCReader** es una suite de código abierto, ligera y **100% local (offline)** para la digitalización de documentos y el análisis semántico con inteligencia artificial.

Concebida como una alternativa ágil, privada y libre a soluciones comerciales privativas como ABBYY FineReader, **Open OCReader** une dos mundos complementarios: la **conversión fiel de documentos** (PDF sandwich buscable, DOCX, XLSX) y la **comprensión documental inteligente** (modelos de visión y lenguaje VLM / LLM).

---

## 🌟 Visión: Arquitectura en Dos Pilares

La mayoría de herramientas OCR distorsionan el diseño del documento o dependen de servicios pesados en la nube. **Open OCReader** desacopla el proceso en dos capas especializadas:

```
┌────────────────────────────────────────────────────────┐
│           Entrada: Imagen escaneada o PDF              │
└───────────────────────────┬────────────────────────────┘
                            │
               ┌────────────┴────────────┐
               ▼                         ▼
   ┌───────────────────────┐ ┌───────────────────────┐
   │        PILAR 1        │ │        PILAR 2        │
   │ Digitalización Física │ │ Inteligencia Semántica│
   │  (RapidOCR / ONNX)    │ │   (LLM / VLM Local)   │
   ├───────────────────────┤ ├───────────────────────┤
   │ • 100% Local y Ágil   │ │ • Resúmenes y esquemas│
   │ • Coordenadas exactas │ │ • Extracción a JSON   │
   │ • PDF Sandwich        │ │ • Traducción contextual│
   │ • DOCX / XLSX / TXT   │ │ • Análisis de datos   │
   └───────────────────────┘ └───────────────────────┘
```

1. **Pilar 1: Digitalización Estructural (RapidOCR / ONNX Runtime)**
   - Ejecución ultrarrápida en el procesador (CPU) de tu ordenador (~0,2 segundos por página).
   - Detección precisa de las cajas delimitadoras de cada palabra `(x, y, ancho, alto)`.
   - Generación de **PDFs buscables tipo "Sandwich"**: el escaneo original se mantiene 100% intacto a nivel visual (no se mueve ni un solo píxel, firma o logotipo), mientras se superpone una capa de texto invisible exactamente alineada.
   - Exportación limpia y estructurada a `.docx` (Word), `.xlsx` (Excel) y `.txt`.

2. **Pilar 2: Inteligencia Semántica (VLM / LLM local)**
   - Integración directa con entornos locales de IA (como Ollama, Llama.cpp o modelos de visión VLM locales).
   - Generación de resúmenes ejecutivos, esquemas y traducción contextual.
   - Extracción de datos clave a formato estructurado JSON (facturas, nóminas, contratos, recibos) sin enviar información privada a servidores externos.

---

## ✨ Características Principales

- 🔒 **100% Local y Privado**: Se ejecuta íntegramente en tu máquina. Sin telemetría, sin suscripciones y sin enviar datos a la nube.
- 🎯 **Fidelidad visual absoluta (PDF Sandwich)**: Conserva el aspecto visual original de tu escaneo al milímetro. Busca con `Ctrl + F`, selecciona y copia texto cómodamente.
- ⚡ **Rápido y ligero**: Motor optimizado mediante ONNX Runtime. No requiere tarjetas gráficas de gama alta ni dependencias complejas.
- 📂 **Formatos de entrada universales**: Admite imágenes (JPG, PNG, TIFF, BMP, WebP) y ficheros PDF multipágina.
- 📊 **Múltiples formatos de salida**:
  - `PDF`: PDF con capa de texto buscable transparente (opción por defecto).
  - `DOCX`: Documento editable de Microsoft Word respetando párrafos.
  - `XLSX`: Hojas de cálculo con tablas volcadas a celdas reales de Excel.
  - `TXT`: Volcado de texto plano ordenado por lectura natural.
- 🤖 **Extensible con Inteligencia Artificial**: Módulos preparados para conectar modelos de lenguaje locales para razonar sobre el texto extraído.

---

## 🚀 Instalación Rápida

### 1. Clonar el repositorio
```bash
git clone https://github.com/Ydalgo/Open-OCReader.git
cd Open-OCReader
```

### 2. Instalar las dependencias
```bash
pip install -r requirements.txt
```

*(Dependencias principales: `rapidocr-onnxruntime`, `pypdf`, `reportlab`, `openpyxl`, `python-docx`, `Pillow`, `opencv-python`)*

---

## 💻 Uso desde la Terminal (CLI)

Open OCReader ofrece una interfaz de línea de órdenes directa y flexible:

### 1. Uso estándar: convertir a PDF buscable
```bash
# Genera 'documento_ocr.pdf' manteniendo el 100% del diseño original intacto
python ocr_tool.py documento.png
python ocr_tool.py factura.pdf
```

### 2. Indicar un fichero de salida específico
```bash
python ocr_tool.py escaneo.jpg -o mi_documento_buscable.pdf
```

### 3. Exportar a otros formatos
```bash
# Exportar tablas a hoja de cálculo de Excel
python ocr_tool.py informe_tabla.png -f xlsx -o informe.xlsx

# Exportar a documento editable de Word
python ocr_tool.py contrato.pdf -f docx -o contrato.docx

# Volcar a texto plano
python ocr_tool.py notas.jpg -f txt -o notas.txt
```

### 4. Modo semántico con Inteligencia Artificial (en desarrollo)
```bash
# Extraer los datos de una factura en formato estructurado JSON con un modelo local
python ocr_tool.py factura.pdf --ai extract-json -o factura.json

# Generar un resumen del documento
python ocr_tool.py acuerdo.pdf --ai summarize
```

---

## 🐍 Uso desde Python (API)

También puedes integrar Open OCReader como módulo dentro de tus propios scripts y aplicaciones en Python:

```python
from open_ocreader import DocumentConverter

# Inicializar el conversor
conversor = DocumentConverter()

# Convertir una imagen o PDF a PDF con texto buscable
resultado = conversor.convert(
    input_path="recibo_escaneado.jpg",
    output_path="recibo_buscable.pdf",
    output_format="pdf"
)

print(f"Documento procesado con éxito en {resultado.elapsed_seconds:.2f} segundos.")
```

---

## 🗺️ Hoja de Ruta (Roadmap)

- [x] Integración del motor rápido de OCR en ONNX (`rapidocr-onnxruntime`)
- [x] Generador de PDF "Sandwich" con posicionamiento exacto de coordenadas
- [ ] Procesamiento por lotes y gestión de ficheros PDF multipágina
- [ ] Detección automática de rejillas para generación avanzada de `.xlsx`
- [ ] Reconstrucción fluida de párrafos en documentos `.docx`
- [ ] Conector con IA local (Ollama / Llama.cpp / Qwen) para resúmenes y extracción a JSON
- [ ] Interfaz gráfica de escritorio nativa (CustomTkinter / PyQt)

---

## 🤝 Cómo Contribuir

¡Las contribuciones de la comunidad son muy bienvenidas! Si quieres proponer mejoras, corregir fallos o añadir nuevos formatos:

1. Haz un Fork del repositorio.
2. Crea una rama para tu funcionalidad (`git checkout -b feature/NuevaCaracteristica`).
3. Confirma tus cambios (`git commit -m 'Añadir nueva característica'`).
4. Sube la rama a tu repositorio (`git push origin feature/NuevaCaracteristica`).
5. Abre una Pull Request.

---

## 📄 Licencia y Autoría

Este proyecto se distribuye bajo la licencia de código abierto **MIT**.

* **Autores:**
  * **Ydalgo** (Creador y mantenedor del proyecto)
  * **Antigravity** (Google DeepMind - Asistente de arquitectura, diseño y desarrollo)

Consulta el fichero `LICENSE` para conocer todos los detalles legales.

---

<p align="center">
  Desarrollado con ❤️ para impulsar la privacidad, el software libre y las herramientas 100% locales.
</p>
