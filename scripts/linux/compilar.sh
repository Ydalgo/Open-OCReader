#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/../.."

echo "================================================================"
echo "  Compilando Open OCReader para Linux (ejecutable independiente)"
echo "================================================================"

if [ -d "venv" ]; then
    source venv/bin/activate
fi

pip install pyinstaller

pyinstaller --noconfirm --clean --windowed \
    --paths="src" \
    --name="Open_OCReader" \
    --add-data="ico:ico" \
    --collect-all="rapidocr_onnxruntime" \
    --collect-all="pypdfium2" \
    --hidden-import="PIL" \
    --hidden-import="cv2" \
    --hidden-import="pypdf" \
    --hidden-import="reportlab" \
    --hidden-import="docx" \
    --hidden-import="openpyxl" \
    --hidden-import="requests" \
    --hidden-import="huggingface_hub" \
    --hidden-import="open_ocreader.ai" \
    --exclude-module="torch" \
    --exclude-module="torchvision" \
    --exclude-module="transformers" \
    --exclude-module="scipy" \
    --exclude-module="matplotlib" \
    src/Open_OCReader.pyw

echo ""
echo "Compilación completada. Binario disponible en: dist/Open_OCReader/Open_OCReader"
