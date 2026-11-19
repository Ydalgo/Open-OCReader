#!/usr/bin/env bash
cd "$(dirname "$0")/../.."

if [ -f "dist/Open_OCReader/Open_OCReader" ]; then
    ./dist/Open_OCReader/Open_OCReader "$@"
elif [ -d "venv" ]; then
    source venv/bin/activate
    python3 src/ocr_tool.py "$@"
else
    python3 src/ocr_tool.py "$@"
fi
