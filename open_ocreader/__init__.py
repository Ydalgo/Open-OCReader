"""
Open OCReader - Suite de digitalización y análisis documental 100% offline.
"""

from .engine import OCREngine, OCRBox
from .document_loader import DocumentLoader, PageData
from .converter import DocumentConverter, ConversionResult
from .formats.pdf_builder import build_sandwich_pdf
from .formats.docx_builder import build_docx
from .formats.excel_builder import build_excel
from .formats.txt_builder import build_txt
from .formats.json_builder import build_json

__version__ = "0.1.0"
__all__ = [
    "OCREngine",
    "OCRBox",
    "DocumentLoader",
    "PageData",
    "DocumentConverter",
    "ConversionResult",
    "build_sandwich_pdf",
    "build_docx",
    "build_excel",
    "build_txt",
    "build_json",
]
