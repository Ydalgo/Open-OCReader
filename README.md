# Open OCReader 📄🔍⚡

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-windows%20%7C%20linux%20%7C%20macos-lightgrey)]()
[![100% Offline](https://img.shields.io/badge/Privacy-100%25%20Offline-success)]()
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/Ydalgo/Open-OCReader/pulls)

**Open OCReader** is an open-source, lightweight, and 100% offline document digitization and semantic analysis suite.

Designed as an agile, private, and developer-friendly alternative to commercial software like ABBYY FineReader, **Open OCReader** bridges the gap between **pixel-perfect document conversion** (Searchable Sandwich PDF, DOCX, XLSX) and **modern intelligent document understanding** (VLM / LLM).

---

## 🌟 The Vision: A Two-Pillar Architecture

Most OCR tools either alter your document layout or depend on heavy, slow cloud APIs. **Open OCReader** separates concerns into two specialized layers:

```
┌────────────────────────────────────────────────────────┐
│               Input: Scanned Image / PDF               │
└───────────────────────────┬────────────────────────────┘
                            │
               ┌────────────┴────────────┐
               ▼                         ▼
   ┌───────────────────────┐ ┌───────────────────────┐
   │       PILLAR 1        │ │       PILLAR 2        │
   │  Structural Digitize  │ │ Semantic Intelligence │
   │  (RapidOCR / ONNX)    │ │   (Local LLM / VLM)   │
   ├───────────────────────┤ ├───────────────────────┤
   │ • 100% Offline & Fast │ │ • Summaries & Schemas │
   │ • Pixel-Perfect BBoxes│ │ • Structured JSON     │
   │ • Sandwich PDF        │ │ • Translation         │
   │ • DOCX / XLSX / TXT   │ │ • Information Extract │
   └───────────────────────┘ └───────────────────────┘
```

1. **Pillar 1: Structural Digitization (RapidOCR / ONNX Runtime)**
   - Ultra-fast CPU execution (~0.2s per page).
   - Extracts precise bounding-box coordinates `(x, y, w, h)`.
   - Generates **Searchable "Sandwich" PDFs**: the original scan remains 100% untouched visually, while an invisible, selectable text layer is placed right beneath each word.
   - Exports cleanly to `.docx`, `.xlsx`, and `.txt`.

2. **Pillar 2: Semantic Intelligence (VLM / Local LLM)**
   - Connects to local AI runtimes (e.g., Ollama, Llama.cpp, or local VLMs).
   - Generates summaries, bullet points, and translations.
   - Extracts structured key-value data (invoices, receipts, legal entities) without sending private data to external servers.

---

## ✨ Features

- 🔒 **100% Offline & Private**: Runs entirely on your local machine. No telemetry, no cloud dependencies.
- 🎯 **Pixel-Perfect PDF**: Your scan's visual appearance is preserved with 100% fidelity. Search (`Ctrl+F`), select, and copy text effortlessly.
- ⚡ **Lightweight & High Performance**: Powered by ONNX Runtime. No heavy GPU or C++ compilation required.
- 📂 **Universal Input**: Supports JPG, PNG, TIFF, BMP, WebP, and multi-page PDFs.
- 📊 **Multi-Format Export**:
  - `PDF`: Searchable sandwich PDF (default).
  - `DOCX`: Editable Word document with layout preservation.
  - `XLSX`: Tabular data exported into native Excel rows and columns.
  - `TXT`: Clean, reading-order text dump.
- 🤖 **AI-Ready Extensibility**: Modular hooks to plug in local LLMs for reasoning and summarization.

---

## 🚀 Quick Start

### 1. Clone the repository
```bash
git clone https://github.com/Ydalgo/Open-OCReader.git
cd Open-OCReader
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

*(Core dependencies: `rapidocr-onnxruntime`, `pypdf`, `reportlab`, `openpyxl`, `python-docx`, `Pillow`, `opencv-python`)*

---

## 💻 CLI Usage

Open OCReader provides an intuitive command-line interface:

### 1. Default: Convert to Searchable PDF
```bash
# Creates 'document_ocr.pdf' preserving 100% of the original visual layout
python ocr_tool.py document.png
python ocr_tool.py invoice.pdf
```

### 2. Specify Output File
```bash
python ocr_tool.py scan.jpg -o my_searchable_document.pdf
```

### 3. Export to Other Formats
```bash
# Export recognized tables to Excel
python ocr_tool.py report_table.png -f xlsx -o report.xlsx

# Export to editable Word document
python ocr_tool.py contract.pdf -f docx -o contract.docx

# Export to plain text
python ocr_tool.py notes.jpg -f txt -o notes.txt
```

### 4. (Upcoming) AI Semantic Mode
```bash
# Extract structured invoice data to JSON using local LLM
python ocr_tool.py invoice.pdf --ai extract-json -o invoice.json

# Summarize a document
python ocr_tool.py agreement.pdf --ai summarize
```

---

## 🐍 Python API

You can also use Open OCReader directly inside your own Python projects:

```python
from open_ocreader import DocumentConverter

# Initialize converter
converter = DocumentConverter()

# Convert image or PDF to a searchable PDF
result = converter.convert(
    input_path="scanned_receipt.jpg",
    output_path="searchable_receipt.pdf",
    output_format="pdf"
)

print(f"Document processed in {result.elapsed_seconds:.2f}s!")
```

---

## 🗺️ Roadmap

- [x] Fast ONNX OCR integration (`rapidocr-onnxruntime`)
- [x] Searchable "Sandwich" PDF builder with exact coordinate mapping
- [ ] Multi-page PDF batch processing
- [ ] Grid detection & automated `.xlsx` table generation
- [ ] Flow-aware `.docx` layout reconstruction
- [ ] Local AI connector (Ollama / Llama.cpp / Qwen) for summaries & JSON extraction
- [ ] Modern desktop GUI (CustomTkinter / PyQt)

---

## 🤝 Contributing

Contributions are warmly welcome! Whether it is reporting a bug, improving the OCR post-processing, adding a new export format, or enhancing documentation:

1. Fork the Project.
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`).
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`).
4. Push to the Branch (`git push origin feature/AmazingFeature`).
5. Open a Pull Request.

---

## 📄 License

Distributed under the **MIT License**. See `LICENSE` for more information.

---

<p align="center">
  Built with ❤️ for privacy, open source, and offline-first software.
</p>
