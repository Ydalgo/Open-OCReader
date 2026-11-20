"""
Interfaz gráfica nativa en Qt 6 (PySide6) para Open OCReader.

Ventajas clave sobre Tkinter en Windows, Linux y macOS:
  - Iconos vectoriales renderizados por QPainter con antialiasing y escalado HiDPI nativo.
  - Maquetación 100% elástica (FlowLayout + QScrollArea): cero textos o botones recortados
    en cualquier tamaño de ventana o zoom global (90% - 180%).
  - Accesibilidad universal completa: temas WCAG AAA (>15:1), modo crema/dislexia,
    Lectura Fácil (UNE 153101 EX), lector de voz local (TTS offline), objetivos ampliados
    anti-temblor, atajos globales y metadatos nativos para lectores de pantalla (NVDA/Narrador/Orca).
"""

from __future__ import annotations

import atexit
import os
import sys
import tempfile
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .accessibility import (
    THEME_DISPLAY_LABELS,
    VALID_THEME_MODES,
    AccessibilityConfig,
    get_accessible_palette,
    get_tts_engine,
)
from .converter import DocumentConverter
from .document_loader import DocumentLoader
from .gui_common import (
    COMPRESSION_LABELS,
    EXPORT_CONV_FORMATS,
    FORMAT_OPTIONS,
    GITHUB_REPO_URL,
    GUARIDA_REPO_URL,
    LEGAL_COMPLIANCE_TEXT,
    acquire_single_instance_lock,
    detect_os_dark_mode,
    focus_existing_window_windows,
    open_path_crossplatform,
    release_single_instance_lock,
    resolve_ico_dir,
    strip_leading_emoji,
)
from .i18n import (
    SUPPORTED_UI_LANGUAGES,
    TRANSLATION_TARGET_LANGUAGES,
    get_llm_language_name,
    tr,
)
from .logger import get_logger, get_logs_dir

logger = get_logger("gui_qt")


class _JobSignals(QObject):
    """Puente seguro entre hilos en segundo plano y el hilo principal de Qt."""

    progress = Signal(str)
    done = Signal(object)
    failed = Signal(str)


class FlowLayout(QLayout):
    """Layout elástico que redistribuye los controles en varias filas según el ancho."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        margin: int = 0,
        h_spacing: int = 6,
        v_spacing: int = 6,
        align_right: bool = False,
    ):
        super().__init__(parent)
        self._items: List[QLayoutItem] = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._align_right = align_right
        self.setContentsMargins(margin, margin, margin, margin)

    def set_align_right(self, align_right: bool):
        if self._align_right != align_right:
            self._align_right = align_right
            self.invalidate()

    def addItem(self, item: QLayoutItem):
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> Optional[QLayoutItem]:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> Optional[QLayoutItem]:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        effective = rect.adjusted(left, top, -right, -bottom)
        avail_w = max(120, effective.width())

        rows: List[tuple[List[tuple[QLayoutItem, QSize]], int, int]] = []
        cur_row: List[tuple[QLayoutItem, QSize]] = []
        cur_w = 0
        cur_h = 0

        for item in self._items:
            wd = item.widget()
            if wd is not None and not wd.isVisible():
                continue
            sh = item.sizeHint()
            needed = sh.width() if not cur_row else (cur_w + self._h_spacing + sh.width())
            if cur_row and needed > avail_w:
                rows.append((cur_row, cur_w, cur_h))
                cur_row = [(item, sh)]
                cur_w = sh.width()
                cur_h = sh.height()
            else:
                cur_row.append((item, sh))
                cur_w = needed
                cur_h = max(cur_h, sh.height())
        if cur_row:
            rows.append((cur_row, cur_w, cur_h))

        y = effective.y()
        for row_items, row_w, row_h in rows:
            x = effective.x() + (max(0, avail_w - row_w) if self._align_right else 0)
            for item, sh in row_items:
                if not test_only:
                    y_off = max(0, (row_h - sh.height()) // 2)
                    item.setGeometry(QRect(QPoint(x, y + y_off), sh))
                x += sh.width() + self._h_spacing
            y += row_h + self._v_spacing

        total_h = (y - effective.y() - self._v_spacing) if rows else 0
        return total_h + top + bottom


class _AdaptiveColumns(QWidget):
    """Contenedor de dos columnas que se apila en una sola cuando falta ancho.

    En pantallas anchas (p. ej. pantalla completa) aprovecha el fondo lateral
    colocando los bloques en paralelo y evita barras de desplazamiento verticales.
    """

    def __init__(self, left_widgets: List[QWidget], right_widgets: List[QWidget]):
        super().__init__()
        self._wide: Optional[bool] = None
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(5)
        self._col_l = QWidget()
        self._col_r = QWidget()
        for col, widgets in ((self._col_l, left_widgets), (self._col_r, right_widgets)):
            vl = QVBoxLayout(col)
            vl.setContentsMargins(0, 0, 0, 0)
            vl.setSpacing(5)
            for wd in widgets:
                vl.addWidget(wd)
            vl.addStretch(1)
        self.set_wide(False)

    def set_wide(self, wide: bool):
        if wide == self._wide:
            return
        self._wide = wide
        self._grid.removeWidget(self._col_l)
        self._grid.removeWidget(self._col_r)
        if wide:
            self._grid.addWidget(self._col_l, 0, 0)
            self._grid.addWidget(self._col_r, 0, 1)
            self._grid.setColumnStretch(0, 1)
            self._grid.setColumnStretch(1, 1)
        else:
            self._grid.addWidget(self._col_l, 0, 0)
            self._grid.addWidget(self._col_r, 1, 0)
            self._grid.setColumnStretch(0, 1)
            self._grid.setColumnStretch(1, 0)
        self._grid.invalidate()


class _DropZoneFrame(QFrame):
    """Zona interactiva de arrastrar/soltar y apertura rápida de ficheros."""

    clicked = Signal()
    file_dropped = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        self.label = QLabel("")
        self.label.setObjectName("dropZoneLabel")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        lay.addWidget(self.label)

    def setText(self, text: str):
        self.label.setText(text)
        self.setAccessibleDescription(text)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        for url in urls:
            local_p = url.toLocalFile()
            if local_p and Path(local_p).is_file():
                self.file_dropped.emit(local_p)
                event.acceptProposedAction()
                return
        event.ignore()


def _paint_icon(draw_fn: Callable[[QPainter], None], size_px: int) -> QIcon:
    """Dibuja un icono vectorial Qt sobre un lienzo lógico 64x64 con antialiasing."""
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    draw_fn(p)
    p.end()
    if size_px != 64:
        pm = pm.scaled(size_px, size_px, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return QIcon(pm)


def _build_qt_icons(dark_mode: bool, icon_px: int = 18, logo_px: int = 40) -> Dict[str, object]:
    """Genera el conjunto completo de iconos vectoriales a color y el logotipo oficial."""
    icons: Dict[str, object] = {}

    ico_dir = resolve_ico_dir()
    if ico_dir and (ico_dir / "Open_OCReader.png").exists():
        raw_logo = QPixmap(str(ico_dir / "Open_OCReader.png"))
        if not raw_logo.isNull():
            icons["app_icon"] = QIcon(raw_logo)
            icons["logo_pixmap"] = raw_logo.scaled(
                logo_px, logo_px, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )

    def _pen(color: str, width: float = 4.0) -> QPen:
        return QPen(QColor(color), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)

    def _d_convert(p: QPainter):
        p.setPen(_pen("#1a5fb4", 4.5))
        p.setBrush(QColor("#e8f1fb"))
        p.drawRoundedRect(8, 6, 36, 50, 6, 6)
        p.drawLine(15, 20, 34, 20)
        p.drawLine(15, 30, 28, 30)
        p.setPen(_pen("#ffffff", 3))
        p.setBrush(QColor("#16a34a"))
        p.drawEllipse(30, 28, 28, 28)
        p.setPen(_pen("#ffffff", 4.5))
        p.drawLine(37, 42, 49, 42)
        path = QPainterPath()
        path.moveTo(45, 35)
        path.lineTo(53, 42)
        path.lineTo(45, 49)
        p.setBrush(QColor("#ffffff"))
        p.setPen(Qt.NoPen)
        p.drawPath(path)

    def _d_translate(p: QPainter):
        p.setPen(_pen("#0369a1", 4))
        p.setBrush(QColor("#0284c7"))
        p.drawEllipse(6, 6, 52, 52)
        p.setPen(_pen("#bae6fd", 3.5))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(18, 6, 28, 52)
        p.drawLine(8, 24, 56, 24)
        p.drawLine(8, 40, 56, 40)
        p.drawLine(32, 6, 32, 58)

    def _d_chat(p: QPainter):
        p.setPen(_pen("#047857", 3.5))
        p.setBrush(QColor("#059669"))
        p.drawRoundedRect(6, 8, 52, 39, 10, 10)
        tail = QPainterPath()
        tail.moveTo(16, 45)
        tail.lineTo(14, 57)
        tail.lineTo(28, 45)
        p.drawPath(tail)
        p.setPen(_pen("#ffffff", 4))
        p.drawLine(15, 21, 47, 21)
        p.setPen(_pen("#d1fae5", 4))
        p.drawLine(15, 32, 40, 32)

    def _d_ai(p: QPainter):
        p.setPen(_pen("#7c3aed", 4))
        for pos in (18, 32, 46):
            p.drawLine(pos, 4, pos, 60)
            p.drawLine(4, pos, 60, pos)
        p.setPen(_pen("#a78bfa", 3.5))
        p.setBrush(QColor("#6d28d9"))
        p.drawRoundedRect(12, 12, 40, 40, 8, 8)
        star = QPainterPath()
        pts = [(32, 18), (37, 27), (46, 32), (37, 37), (32, 46), (27, 37), (18, 32), (27, 27)]
        star.moveTo(*pts[0])
        for pt in pts[1:]:
            star.lineTo(*pt)
        star.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#fbbf24"))
        p.drawPath(star)

    def _d_anonymize(p: QPainter):
        p.setPen(_pen("#b45309", 4))
        p.setBrush(QColor("#f59e0b"))
        shield = QPainterPath()
        for idx, pt in enumerate([(32, 4), (56, 14), (52, 42), (32, 60), (12, 42), (8, 14)]):
            if idx == 0:
                shield.moveTo(*pt)
            else:
                shield.lineTo(*pt)
        shield.closeSubpath()
        p.drawPath(shield)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#451a03"))
        p.drawEllipse(24, 19, 16, 14)
        keyhole = QPainterPath()
        keyhole.moveTo(27, 29)
        keyhole.lineTo(37, 29)
        keyhole.lineTo(39, 44)
        keyhole.lineTo(25, 44)
        keyhole.closeSubpath()
        p.drawPath(keyhole)

    def _d_pdf_tools(p: QPainter):
        p.setPen(_pen("#991b1b", 4))
        p.setBrush(QColor("#dc2626"))
        p.drawRoundedRect(8, 6, 38, 50, 6, 6)
        p.setPen(_pen("#ffffff", 4))
        p.drawLine(15, 20, 36, 20)
        p.setPen(_pen("#fecaca", 4))
        p.drawLine(15, 30, 30, 30)
        p.setPen(_pen("#ffffff", 3))
        p.setBrush(QColor("#334155"))
        p.drawEllipse(32, 32, 26, 26)
        p.setPen(_pen("#e2e8f0", 4.5))
        p.drawLine(39, 39, 51, 51)

    def _d_accessibility(p: QPainter):
        p.setPen(_pen("#fbbf24", 4))
        p.setBrush(QColor("#1d4ed8"))
        p.drawEllipse(4, 4, 56, 56)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(26, 12, 12, 12)
        p.setPen(_pen("#ffffff", 5))
        p.drawLine(14, 29, 50, 29)
        p.drawLine(32, 26, 32, 40)
        p.drawLine(32, 39, 21, 52)
        p.drawLine(32, 39, 43, 52)

    def _d_tts_speak(p: QPainter):
        p.setPen(_pen("#0369a1", 3))
        p.setBrush(QColor("#0284c7"))
        sp = QPainterPath()
        for idx, pt in enumerate([(8, 24), (20, 24), (34, 12), (34, 52), (20, 40), (8, 40)]):
            sp.moveTo(*pt) if idx == 0 else sp.lineTo(*pt)
        sp.closeSubpath()
        p.drawPath(sp)
        p.setBrush(Qt.NoBrush)
        p.setPen(_pen("#10b981", 4.5))
        p.drawArc(30, 18, 20, 28, -55 * 16, 110 * 16)
        p.setPen(_pen("#34d399", 4))
        p.drawArc(34, 10, 24, 44, -55 * 16, 110 * 16)

    def _d_tts_stop(p: QPainter):
        p.setPen(_pen("#dc2626", 4))
        p.setBrush(QColor("#fee2e2"))
        p.drawEllipse(6, 6, 52, 52)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#dc2626"))
        p.drawRoundedRect(20, 20, 24, 24, 4, 4)

    def _d_easy_read(p: QPainter):
        p.setPen(_pen("#115e59", 3))
        p.setBrush(QColor("#0d9488"))
        p.drawRoundedRect(6, 12, 26, 40, 5, 5)
        p.setBrush(QColor("#14b8a6"))
        p.drawRoundedRect(32, 12, 26, 40, 5, 5)
        p.setPen(_pen("#ffffff", 3))
        p.drawLine(12, 24, 26, 24)
        p.setPen(_pen("#ccfbf1", 3))
        p.drawLine(12, 34, 26, 34)
        star = QPainterPath()
        pts = [(45, 21), (48, 28), (55, 30), (48, 33), (45, 40), (42, 33), (35, 30), (42, 28)]
        star.moveTo(*pts[0])
        for pt in pts[1:]:
            star.lineTo(*pt)
        star.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#fde047"))
        p.drawPath(star)

    def _d_github(p: QPainter):
        fill_c = "#e2e8f0" if dark_mode else "#24292f"
        line_c = "#1e1f22" if dark_mode else "#ffffff"
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(fill_c))
        p.drawEllipse(6, 6, 52, 52)
        p.setPen(_pen(line_c, 4.5))
        p.drawLine(24, 18, 24, 46)
        p.drawLine(24, 34, 40, 22)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(line_c))
        p.drawEllipse(18, 14, 12, 12)
        p.drawEllipse(18, 40, 12, 12)
        p.drawEllipse(34, 16, 12, 12)

    def _d_legal(p: QPainter):
        p.setPen(_pen("#1d4ed8", 5))
        p.drawLine(32, 10, 32, 54)
        p.drawLine(16, 54, 48, 54)
        p.setPen(_pen("#f59e0b", 4.5))
        p.drawLine(10, 18, 54, 18)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#f59e0b"))
        for tri in ([(6, 36), (22, 36), (14, 20)], [(42, 36), (58, 36), (50, 20)]):
            tp = QPainterPath()
            tp.moveTo(*tri[0])
            tp.lineTo(*tri[1])
            tp.lineTo(*tri[2])
            tp.closeSubpath()
            p.drawPath(tp)

    def _d_update(p: QPainter):
        p.setBrush(Qt.NoBrush)
        p.setPen(_pen("#0284c7", 5.5))
        p.drawArc(8, 8, 48, 48, 35 * 16, 145 * 16)
        p.setPen(_pen("#0ea5e9", 5.5))
        p.drawArc(8, 8, 48, 48, 215 * 16, 145 * 16)
        p.setPen(Qt.NoPen)
        for col, tri in (
            ("#0284c7", [(48, 12), (58, 26), (40, 26)]),
            ("#0ea5e9", [(16, 52), (6, 38), (24, 38)]),
        ):
            tp = QPainterPath()
            tp.moveTo(*tri[0])
            tp.lineTo(*tri[1])
            tp.lineTo(*tri[2])
            tp.closeSubpath()
            p.setBrush(QColor(col))
            p.drawPath(tp)

    def _d_reinstall(p: QPainter):
        p.setBrush(Qt.NoBrush)
        p.setPen(_pen("#16a34a", 5.5))
        p.drawArc(10, 10, 44, 44, 0, 300 * 16)
        tp = QPainterPath()
        tp.moveTo(44, 18)
        tp.lineTo(58, 20)
        tp.lineTo(50, 6)
        tp.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#16a34a"))
        p.drawPath(tp)
        p.setBrush(QColor("#22c55e"))
        p.drawEllipse(24, 24, 16, 16)

    def _d_cache(p: QPainter):
        star = QPainterPath()
        pts = [(32, 6), (39, 25), (58, 32), (39, 39), (32, 58), (25, 39), (6, 32), (25, 25)]
        star.moveTo(*pts[0])
        for pt in pts[1:]:
            star.lineTo(*pt)
        star.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ea580c"))
        p.drawPath(star)
        p.setBrush(QColor("#fef08a"))
        p.drawEllipse(26, 26, 12, 12)

    def _d_clear_logs(p: QPainter):
        p.setPen(_pen("#dc2626", 5.5))
        p.drawLine(14, 14, 50, 14)
        p.drawLine(24, 8, 40, 8)
        p.setPen(_pen("#991b1b", 3.5))
        p.setBrush(QColor("#ef4444"))
        p.drawRoundedRect(16, 18, 32, 38, 6, 6)
        p.setPen(_pen("#ffffff", 4))
        p.drawLine(26, 26, 26, 48)
        p.drawLine(38, 26, 38, 48)

    def _d_view_logs(p: QPainter):
        p.setPen(_pen("#475569", 4.5))
        p.setBrush(QColor("#f8fafc"))
        p.drawRoundedRect(12, 12, 40, 44, 6, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#0284c7"))
        p.drawRoundedRect(22, 6, 20, 10, 3, 3)
        p.setPen(_pen("#334155", 4))
        p.drawLine(20, 26, 44, 26)
        p.drawLine(20, 36, 44, 36)
        p.setPen(_pen("#64748b", 4))
        p.drawLine(20, 46, 36, 46)

    specs = {
        "tab_convert": _d_convert,
        "tab_translate": _d_translate,
        "tab_chat": _d_chat,
        "tab_ai": _d_ai,
        "tab_anonymize": _d_anonymize,
        "tab_pdf_tools": _d_pdf_tools,
        "accessibility": _d_accessibility,
        "tts_speak": _d_tts_speak,
        "tts_stop": _d_tts_stop,
        "easy_read": _d_easy_read,
        "github": _d_github,
        "legal": _d_legal,
        "update": _d_update,
        "reinstall": _d_reinstall,
        "cache": _d_cache,
        "clear_logs": _d_clear_logs,
        "view_logs": _d_view_logs,
    }
    for key, fn in specs.items():
        icons[key] = _paint_icon(fn, icon_px)
    return icons


def _resolve_qt_dyslexia_font() -> str:
    fams = {f.lower(): f for f in QFontDatabase.families()}
    for cand in ("opendyslexic", "opendyslexic3", "opendyslexicalta", "verdana", "tahoma", "arial"):
        if cand in fams:
            return fams[cand]
    return "Verdana" if sys.platform == "win32" else "DejaVu Sans"


def _build_qt_stylesheet(
    palette: Dict[str, str],
    font_family: str,
    ui_size: int,
    large_targets: bool,
) -> str:
    p = palette
    is_hc = p["mode"].startswith("high_contrast")
    border_col = p["accent"] if is_hc else p["muted"]
    btn_pad = "8px 13px" if large_targets else "5px 10px"
    btn_min_h = "34px" if large_targets else "26px"
    tab_pad = "9px 15px" if large_targets else "6px 12px"
    chk_sp = "8px" if large_targets else "6px"
    focus_w = "2px" if (is_hc or large_targets) else "1px"
    return f"""
        QMainWindow, QDialog, QScrollArea, QWidget#scrollContent {{
            background-color: {p["bg"]};
            color: {p["fg"]};
            font-family: "{font_family}";
            font-size: {ui_size}pt;
        }}
        QWidget {{
            color: {p["fg"]};
            font-family: "{font_family}";
            font-size: {ui_size}pt;
        }}
        QGroupBox {{
            border: {2 if is_hc else 1}px solid {border_col};
            border-radius: 6px;
            margin-top: {ui_size + 3}px;
            padding: 5px 8px;
            background-color: {p["bg"]};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 6px;
            color: {p["accent"]};
            font-weight: bold;
        }}
        QLabel {{
            background: transparent;
            color: {p["fg"]};
        }}
        QLabel[role="muted"] {{ color: {p["muted"]}; font-size: {max(8, ui_size - 2)}pt; }}
        QLabel[role="accent"] {{ color: {p["accent"]}; font-weight: bold; }}
        QLabel[role="accent_italic"] {{ color: {p["accent"]}; font-style: italic; font-size: {max(8, ui_size - 1)}pt; }}
        QLabel[role="ok"] {{ color: {p["ok"]}; font-size: {max(8, ui_size - 1)}pt; }}
        QLabel[role="warn"] {{ color: {p["warn"]}; font-style: italic; font-size: {max(8, ui_size - 1)}pt; }}
        QLabel[role="title"] {{ color: {p["fg"]}; font-size: {ui_size + 6}pt; font-weight: bold; }}
        QPushButton {{
            background-color: {p["btn_bg"]};
            color: {p["fg"]};
            border: {2 if is_hc else 1}px solid {border_col};
            border-radius: 5px;
            padding: {btn_pad};
            min-height: {btn_min_h};
        }}
        QPushButton:hover {{
            background-color: {p["btn_active"]};
            border-color: {p["accent"]};
        }}
        QPushButton:focus {{
            border: {focus_w} solid {p["focus_ring"]};
            background-color: {p["btn_active"]};
        }}
        QPushButton:disabled {{
            color: {p["muted"]};
            background-color: {p["tab_bg"]};
        }}
        QPushButton#primaryBtn {{
            background-color: {p["accent"]};
            color: {p["bg"]};
            font-weight: bold;
            padding: {btn_pad};
            border-color: {p["accent"]};
        }}
        QPushButton#primaryBtn:hover {{
            opacity: 0.92;
        }}
        QPushButton#primaryBtn:disabled {{
            background-color: {p["tab_bg"]};
            color: {p["muted"]};
            border-color: {p["muted"]};
        }}
        QLineEdit, QComboBox {{
            background-color: {p["input_bg"]};
            color: {p["input_fg"]};
            border: {2 if is_hc else 1}px solid {border_col};
            border-radius: 4px;
            padding: {6 if large_targets else 4}px 8px;
            selection-background-color: {p["accent"]};
            selection-color: {p["bg"]};
        }}
        QLineEdit:focus, QComboBox:focus {{
            border: 2px solid {p["focus_ring"]};
        }}
        QComboBox QAbstractItemView {{
            background-color: {p["input_bg"]};
            color: {p["input_fg"]};
            selection-background-color: {p["accent"]};
            selection-color: {p["bg"]};
        }}
        QTextEdit, QListWidget {{
            background-color: {p["input_bg"]};
            color: {p["input_fg"]};
            border: {2 if is_hc else 1}px solid {border_col};
            border-radius: 5px;
            padding: 6px;
            selection-background-color: {p["accent"]};
            selection-color: {p["bg"]};
        }}
        QTextEdit:focus, QListWidget:focus {{
            border: 2px solid {p["focus_ring"]};
        }}
        QCheckBox, QRadioButton {{
            spacing: {chk_sp};
            padding: {4 if large_targets else 2}px 4px;
            color: {p["fg"]};
        }}
        QTabWidget::pane {{
            border: {2 if is_hc else 1}px solid {border_col};
            border-radius: 6px;
            background-color: {p["bg"]};
            top: -1px;
        }}
        QTabBar::tab {{
            background-color: {p["tab_bg"]};
            color: {p["fg"]};
            border: 1px solid {border_col};
            border-bottom: none;
            border-top-left-radius: 5px;
            border-top-right-radius: 5px;
            padding: {tab_pad};
            margin-right: 3px;
        }}
        QTabBar::tab:selected {{
            background-color: {p["tab_sel_bg"]};
            color: {p["accent"]};
            font-weight: bold;
            border-color: {p["accent"]};
        }}
        QTabBar::tab:hover:!selected {{
            background-color: {p["btn_active"]};
        }}
        QFrame#dropZone {{
            background-color: {p["drop_bg"]};
            border: 2px dashed {p["drop_border"]};
            border-radius: 6px;
        }}
        QFrame#dropZone[loaded="true"] {{
            border-color: {p["ok"]};
        }}
        QLabel#dropZoneLabel {{
            color: {p["accent"]};
            font-style: italic;
        }}
        QFrame#dropZone[loaded="true"] QLabel#dropZoneLabel {{
            color: {p["ok"]};
            font-style: normal;
            font-weight: bold;
        }}
        QProgressBar {{
            border: 1px solid {border_col};
            border-radius: 4px;
            background-color: {p["input_bg"]};
            text-align: center;
            height: 14px;
        }}
        QProgressBar::chunk {{
            background-color: {p["accent"]};
            border-radius: 3px;
        }}
        QScrollBar:vertical {{
            border: none;
            background: {p["tab_bg"]};
            width: 11px;
            margin: 2px;
            border-radius: 5px;
        }}
        QScrollBar::handle:vertical {{
            background: {p["muted"]};
            min-height: 28px;
            border-radius: 5px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {p["accent"]};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar:horizontal {{
            border: none;
            background: {p["tab_bg"]};
            height: 11px;
            margin: 2px;
            border-radius: 5px;
        }}
        QScrollBar::handle:horizontal {{
            background: {p["muted"]};
            min-width: 28px;
            border-radius: 5px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {p["accent"]};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}
    """


class OpenOCReaderQtWindow(QMainWindow):
    """Ventana principal de Open OCReader en Qt 6 con accesibilidad universal."""

    def __init__(self, initial_lang: str = "es"):
        super().__init__()
        self._ui_ready = False
        self.a11y = AccessibilityConfig.load()
        self.tts = get_tts_engine()
        self._os_dark_mode = detect_os_dark_mode()
        self.palette = get_accessible_palette(self.a11y.theme_mode, self._os_dark_mode)
        self.is_dark_mode = self.palette.get("is_dark") == "1"

        from .ai.hardware import get_hardware_profile
        self.hw = get_hardware_profile()
        self.ai_tier = self.hw.ai_tier

        self.ui_lang = initial_lang
        self._pending_jobs: set = set()
        self._flow_layouts: List[FlowLayout] = []
        self._radio_grids: List[tuple[QGridLayout, List[QRadioButton]]] = []
        self._header_stacked: Optional[bool] = None
        self._tabs_compact: Optional[bool] = None
        self._tts_speaking_active = False

        # Estado de ficheros y caché
        self.input_file_path = ""
        self.last_generated_file: Optional[str] = None
        self.last_translated_file: Optional[str] = None
        self.last_pdf_tool_file: Optional[str] = None
        self.cached_doc_text = None
        self.cached_doc_tree = None
        self.cached_doc_key = None

        self.chat_engine = None
        self.chat_doc_paths: List[str] = []
        self.last_ai_turn_record = None
        self.ai_turn_records = []
        self._a11y_dlg: Optional[QDialog] = None

        self.setWindowTitle(tr(self.ui_lang, "window_title"))
        screen = QApplication.primaryScreen()
        if screen is not None:
            ag = screen.availableGeometry()
            win_w = min(1240, max(780, ag.width() - 50))
            win_h = min(860, max(600, ag.height() - 60))
        else:
            win_w, win_h = 1180, 820
        self.resize(win_w, win_h)
        self.setMinimumSize(680, 520)

        self._icons = _build_qt_icons(self.is_dark_mode, icon_px=self._calc_icon_px(), logo_px=self._calc_logo_px())
        if "app_icon" in self._icons:
            self.setWindowIcon(self._icons["app_icon"])

        self._build_ui()
        self._setup_shortcuts()
        self._apply_theme_and_fonts(save_prefs=False)
        self._ui_ready = True

    def _calc_icon_px(self) -> int:
        return max(16, min(28, int(round(self.a11y.ui_font_size * 1.7))))

    def _calc_logo_px(self) -> int:
        return max(34, min(52, int(round(self.a11y.ui_font_size * 3.6))))

    def _get_ui_font_family(self) -> str:
        if self.a11y.dyslexia_friendly:
            return _resolve_qt_dyslexia_font()
        return "Segoe UI" if sys.platform == "win32" else QApplication.font().family()

    def _get_text_font_family(self, prefer_mono: bool = False) -> str:
        if self.a11y.dyslexia_friendly:
            return _resolve_qt_dyslexia_font()
        if prefer_mono:
            return "Consolas" if sys.platform == "win32" else "DejaVu Sans Mono"
        return self._get_ui_font_family()

    def _run_bg(
        self,
        work_fn: Callable[[Callable[[str], None]], object],
        on_ok: Callable[[object], None],
        on_err: Callable[[str], None],
        on_progress: Optional[Callable[[str], None]] = None,
    ):
        """Ejecuta una tarea pesada en hilo secundario entregando señales seguras a Qt."""
        job = _JobSignals(self)
        self._pending_jobs.add(job)
        if on_progress is not None:
            job.progress.connect(on_progress, Qt.QueuedConnection)

        def _finish(res):
            self._pending_jobs.discard(job)
            job.deleteLater()
            on_ok(res)

        def _fail(msg: str):
            self._pending_jobs.discard(job)
            job.deleteLater()
            on_err(msg)

        job.done.connect(_finish, Qt.QueuedConnection)
        job.failed.connect(_fail, Qt.QueuedConnection)

        def _runner():
            try:
                res = work_fn(job.progress.emit)
                job.done.emit(res)
            except Exception as exc:
                job.failed.emit(str(exc))

        threading.Thread(target=_runner, daemon=True).start()

    @staticmethod
    def _new_scroll_tab() -> QScrollArea:
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setObjectName("scrollContent")
        sc.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(5)
        sc._inner_layout = lay  # type: ignore[attr-defined]
        return sc

    # ---------------- CONSTRUCCIÓN DE LA INTERFAZ ----------------
    def _build_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.scroll_area = scroll
        self.setCentralWidget(scroll)

        root_content = QWidget()
        root_content.setObjectName("scrollContent")
        scroll.setWidget(root_content)

        main_lay = QVBoxLayout(root_content)
        main_lay.setContentsMargins(12, 10, 12, 10)
        main_lay.setSpacing(8)

        # Cabecera elástica (marca + barra fluida multi-fila)
        self.header_grid = QGridLayout()
        self.header_grid.setContentsMargins(0, 0, 0, 0)
        self.header_grid.setSpacing(8)
        main_lay.addLayout(self.header_grid)

        self.brand_widget = QWidget()
        brand_lay = QVBoxLayout(self.brand_widget)
        brand_lay.setContentsMargins(0, 0, 0, 0)
        brand_lay.setSpacing(2)

        brand_top = QHBoxLayout()
        brand_top.setContentsMargins(0, 0, 0, 0)
        brand_top.setSpacing(8)
        self.logo_lbl = QLabel()
        if "logo_pixmap" in self._icons:
            self.logo_lbl.setPixmap(self._icons["logo_pixmap"])
        brand_top.addWidget(self.logo_lbl)
        self.title_lbl = QLabel("Open OCReader")
        self.title_lbl.setProperty("role", "title")
        brand_top.addWidget(self.title_lbl)
        brand_top.addStretch(1)
        brand_lay.addLayout(brand_top)

        self.subtitle_lbl = QLabel(tr(self.ui_lang, "subtitle"))
        self.subtitle_lbl.setProperty("role", "muted")
        self.subtitle_lbl.setWordWrap(True)
        brand_lay.addWidget(self.subtitle_lbl)

        self.tools_widget = QWidget()
        self.tools_flow = FlowLayout(self.tools_widget, margin=0, h_spacing=5, v_spacing=4, align_right=True)
        self._flow_layouts.append(self.tools_flow)

        self.lang_combo = QComboBox()
        for _code, name in SUPPORTED_UI_LANGUAGES:
            self.lang_combo.addItem(name)
        self.lang_combo.setAccessibleName("Idioma de interfaz")
        self.lang_combo.currentIndexChanged.connect(self._on_ui_language_changed)
        self.tools_flow.addWidget(self.lang_combo)

        self.btn_accessibility = QPushButton(strip_leading_emoji(tr(self.ui_lang, "btn_accessibility")).strip())
        self.btn_accessibility.setAccessibleName("Centro de Accesibilidad Universal (Alt+A o F2)")
        self.btn_accessibility.clicked.connect(self._open_accessibility_dialog)
        self.tools_flow.addWidget(self.btn_accessibility)

        zoom_wrap = QWidget()
        zoom_lay = QHBoxLayout(zoom_wrap)
        zoom_lay.setContentsMargins(0, 0, 0, 0)
        zoom_lay.setSpacing(2)
        btn_zm = QPushButton("A-")
        btn_zm.setAccessibleName("Reducir tamaño de texto e interfaz (Ctrl+-)")
        btn_zm.clicked.connect(lambda: self._adjust_global_zoom(-1))
        self.btn_zoom_pct = QPushButton(f"{self.a11y.zoom_percent}%")
        self.btn_zoom_pct.setAccessibleName("Restablecer zoom al 100% (Ctrl+0)")
        self.btn_zoom_pct.clicked.connect(self._reset_global_zoom)
        btn_zp = QPushButton("A+")
        btn_zp.setAccessibleName("Aumentar tamaño de texto e interfaz (Ctrl++)")
        btn_zp.clicked.connect(lambda: self._adjust_global_zoom(1))
        for b in (btn_zm, self.btn_zoom_pct, btn_zp):
            zoom_lay.addWidget(b)
        self.tools_flow.addWidget(zoom_wrap)

        tts_wrap = QWidget()
        tts_lay = QHBoxLayout(tts_wrap)
        tts_lay.setContentsMargins(0, 0, 0, 0)
        tts_lay.setSpacing(2)
        self.btn_tts_read = QPushButton(strip_leading_emoji(tr(self.ui_lang, "btn_tts_read")).strip())
        self.btn_tts_read.setAccessibleName("Leer resultado en voz alta (Ctrl+Shift+L)")
        self.btn_tts_read.clicked.connect(self._speak_active_output)
        self.btn_tts_stop = QPushButton("")
        self.btn_tts_stop.setAccessibleName("Detener lectura en voz alta")
        self.btn_tts_stop.setToolTip("Detener lectura de voz")
        self.btn_tts_stop.clicked.connect(self._stop_tts)
        tts_lay.addWidget(self.btn_tts_read)
        tts_lay.addWidget(self.btn_tts_stop)
        self.tools_flow.addWidget(tts_wrap)

        self.btn_github = QPushButton(strip_leading_emoji(tr(self.ui_lang, "btn_github")).strip())
        self.btn_github.clicked.connect(lambda: webbrowser.open(GITHUB_REPO_URL))
        self.tools_flow.addWidget(self.btn_github)

        self.btn_legal = QPushButton(strip_leading_emoji(tr(self.ui_lang, "btn_legal")).strip())
        self.btn_legal.clicked.connect(self._show_legal_compliance)
        self.tools_flow.addWidget(self.btn_legal)

        self.btn_update = QPushButton(strip_leading_emoji(tr(self.ui_lang, "btn_update")).strip())
        self.btn_update.clicked.connect(self._check_updates_gui)
        self.tools_flow.addWidget(self.btn_update)

        self.btn_reinstall = QPushButton(strip_leading_emoji(tr(self.ui_lang, "btn_reinstall")).strip())
        self.btn_reinstall.clicked.connect(self._open_clean_reinstall_dialog)
        self.tools_flow.addWidget(self.btn_reinstall)

        self.btn_cache = QPushButton(strip_leading_emoji(tr(self.ui_lang, "btn_cache")).strip())
        self.btn_cache.clicked.connect(self._clear_cache_gui)
        self.tools_flow.addWidget(self.btn_cache)

        self.btn_clear_logs = QPushButton(strip_leading_emoji(tr(self.ui_lang, "btn_clear_logs")).strip())
        self.btn_clear_logs.clicked.connect(self._clear_logs_gui)
        self.tools_flow.addWidget(self.btn_clear_logs)

        self.btn_view_logs = QPushButton(strip_leading_emoji(tr(self.ui_lang, "btn_view_logs")).strip())
        self.btn_view_logs.clicked.connect(self._open_logs)
        self.tools_flow.addWidget(self.btn_view_logs)

        # Selector de fichero común superior
        self.input_group = QGroupBox(tr(self.ui_lang, "input_group"))
        in_lay = QVBoxLayout(self.input_group)
        in_lay.setSpacing(6)

        self.drop_zone = _DropZoneFrame()
        self.drop_zone.setText(tr(self.ui_lang, "drop_prompt"))
        self.drop_zone.clicked.connect(self._browse_input)
        self.drop_zone.file_dropped.connect(self._set_input_file)
        in_lay.addWidget(self.drop_zone)

        entry_row = QHBoxLayout()
        entry_row.setSpacing(6)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Ruta del documento o imagen (PDF, JPG, PNG, TIFF...)")
        self.input_edit.setAccessibleName("Ruta del fichero de entrada")
        entry_row.addWidget(self.input_edit, 1)
        self.btn_paste = QPushButton(tr(self.ui_lang, "btn_paste"))
        self.btn_paste.clicked.connect(self._paste_from_clipboard)
        entry_row.addWidget(self.btn_paste)
        self.btn_browse = QPushButton(tr(self.ui_lang, "btn_browse"))
        self.btn_browse.clicked.connect(self._browse_input)
        entry_row.addWidget(self.btn_browse)
        in_lay.addLayout(entry_row)
        main_lay.addWidget(self.input_group)

        try:
            from .ai.runtime_manager import LlamaRuntimeManager
            mismatch_msg = LlamaRuntimeManager.get_instance().check_portable_hardware_mismatch()
            if mismatch_msg:
                mm = QLabel(mismatch_msg)
                mm.setProperty("role", "warn")
                mm.setWordWrap(True)
                main_lay.addWidget(mm)
        except Exception:
            pass

        # Pestañas principales (cada pestaña con QScrollArea propio para cero recortes y altura independiente)
        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setMinimumHeight(400)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        main_lay.addWidget(self.tabs, 1)

        self.tab_convert = self._new_scroll_tab()
        self.tab_translate = self._new_scroll_tab()
        self.tab_chat = self._new_scroll_tab()
        self.tab_ai = self._new_scroll_tab()
        self.tab_anonymize = self._new_scroll_tab()
        self.pdf_tools_disabled = os.environ.get("OPEN_OCREADER_DISABLE_PDF_TOOLS", "").strip().lower() in {"1", "true", "yes"}
        self.tab_pdf_tools = self._new_scroll_tab() if not self.pdf_tools_disabled else None

        self.tabs.addTab(self.tab_convert, tr(self.ui_lang, "tab_convert"))
        self.tabs.addTab(self.tab_translate, tr(self.ui_lang, "tab_translate"))
        self.tabs.addTab(self.tab_chat, tr(self.ui_lang, "tab_chat"))
        self.tabs.addTab(self.tab_ai, tr(self.ui_lang, "tab_ai"))
        self.tabs.addTab(self.tab_anonymize, tr(self.ui_lang, "tab_anonymize"))
        if self.tab_pdf_tools is not None:
            self.tabs.addTab(self.tab_pdf_tools, tr(self.ui_lang, "tab_pdf_tools"))

        self._build_convert_tab()
        self._build_translate_tab()
        self._build_chat_tab()
        self._build_ai_tab()
        self._build_anonymize_tab()
        if self.tab_pdf_tools is not None:
            self._build_pdf_tools_tab()

        # Pie permanente
        footer_row = QHBoxLayout()
        footer_row.setSpacing(8)
        self.footer_lbl = QLabel(tr(self.ui_lang, "footer"))
        self.footer_lbl.setProperty("role", "muted")
        self.footer_lbl.setWordWrap(True)
        footer_row.addWidget(self.footer_lbl, 1)

        gh_lbl = QLabel('<a href="#">GitHub: Ydalgo/Open-OCReader</a>')
        gh_lbl.setTextInteractionFlags(Qt.LinksAccessibleByMouse | Qt.LinksAccessibleByKeyboard)
        gh_lbl.linkActivated.connect(lambda _u: webbrowser.open(GITHUB_REPO_URL))
        footer_row.addWidget(gh_lbl)
        main_lay.addLayout(footer_row)

        self._apply_qt_icon_refs()
        self._relayout_responsive()

    def _build_radio_format_grid(
        self,
        parent_lay: QVBoxLayout,
        default_fmt: str,
        on_change: Callable[[str], None],
    ) -> tuple[QButtonGroup, Dict[str, QRadioButton], QLabel]:
        grid_wrap = QWidget()
        grid = QGridLayout(grid_wrap)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        grp = QButtonGroup(self)
        radios: Dict[str, QRadioButton] = {}
        radio_list: List[QRadioButton] = []
        for _lbl, fmt_key, _desc in FORMAT_OPTIONS:
            lbl_txt, _desc_txt = tr(self.ui_lang, f"fmt_{fmt_key}")
            rb = QRadioButton(lbl_txt)
            rb.setProperty("fmt_key", fmt_key)
            if fmt_key == default_fmt:
                rb.setChecked(True)
            rb.toggled.connect(lambda checked, fk=fmt_key: checked and on_change(fk))
            grp.addButton(rb)
            radios[fmt_key] = rb
            radio_list.append(rb)

        self._radio_grids.append((grid, radio_list))
        self._reflow_radio_grid(grid, radio_list)
        parent_lay.addWidget(grid_wrap)

        desc_lbl = QLabel("")
        desc_lbl.setProperty("role", "accent_italic")
        desc_lbl.setWordWrap(True)
        parent_lay.addWidget(desc_lbl)
        return grp, radios, desc_lbl

    def _build_convert_tab(self):
        lay = self.tab_convert._inner_layout
        lay.setSpacing(5)

        self.conv_fmt_grp_box = QGroupBox(tr(self.ui_lang, "format_group"))
        fmt_lay = QVBoxLayout(self.conv_fmt_grp_box)
        self.conv_format_val = "pdf"
        self.conv_fmt_group, self.conv_fmt_radios, self.conv_fmt_desc_lbl = self._build_radio_format_grid(
            fmt_lay, "pdf", self._on_conv_format_changed
        )

        opts_box = QGroupBox(" Opciones de OCR y optimización PDF ")
        opts_lay = QVBoxLayout(opts_box)

        r1_wrap = QWidget()
        r1 = FlowLayout(r1_wrap, h_spacing=14, v_spacing=4)
        self._flow_layouts.append(r1)
        self.conv_force_ocr_chk = QCheckBox("Forzar OCR (re-escanear aunque el PDF ya tenga texto buscable)")
        self.conv_grayscale_chk = QCheckBox("Escala de grises (blanco y negro)")
        r1.addWidget(self.conv_force_ocr_chk)
        r1.addWidget(self.conv_grayscale_chk)
        opts_lay.addWidget(r1_wrap)

        r2_wrap = QWidget()
        r2 = FlowLayout(r2_wrap, h_spacing=8, v_spacing=4)
        self._flow_layouts.append(r2)
        r2.addWidget(QLabel("Compresión PDF / PDF-A:"))
        self.conv_comp_combo = QComboBox()
        for lbl, _c in COMPRESSION_LABELS:
            self.conv_comp_combo.addItem(lbl)
        r2.addWidget(self.conv_comp_combo)
        hint = QLabel("(PDF ya buscable: omite OCR automáticamente)")
        hint.setProperty("role", "ok")
        r2.addWidget(hint)
        opts_lay.addWidget(r2_wrap)

        self.conv_out_box = QGroupBox(tr(self.ui_lang, "output_group"))
        out_lay = QHBoxLayout(self.conv_out_box)
        self.conv_out_edit = QLineEdit()
        out_lay.addWidget(self.conv_out_edit, 1)
        self.btn_save_as = QPushButton(tr(self.ui_lang, "btn_save_as"))
        self.btn_save_as.clicked.connect(self._browse_conv_output)
        out_lay.addWidget(self.btn_save_as)
        self._add_columns(lay, [self.conv_fmt_grp_box], [opts_box, self.conv_out_box])

        self.btn_convert = QPushButton(tr(self.ui_lang, "btn_convert"))
        self.btn_convert.setObjectName("primaryBtn")
        self.btn_convert.clicked.connect(self._start_conversion)
        lay.addWidget(self.btn_convert)

        self.conv_progress = QProgressBar()
        self.conv_progress.setRange(0, 100)
        self.conv_progress.setValue(0)
        self.conv_progress.setTextVisible(False)
        lay.addWidget(self.conv_progress)

        self.conv_status_lbl = QLabel(tr(self.ui_lang, "status_ready"))
        self.conv_status_lbl.setWordWrap(True)
        lay.addWidget(self.conv_status_lbl)

        post_wrap = QWidget()
        post_flow = FlowLayout(post_wrap, h_spacing=8, v_spacing=4)
        self._flow_layouts.append(post_flow)
        self.btn_open_file = QPushButton(tr(self.ui_lang, "btn_open_file"))
        self.btn_open_file.setEnabled(False)
        self.btn_open_file.clicked.connect(lambda: self.last_generated_file and open_path_crossplatform(self.last_generated_file))
        self.btn_open_folder = QPushButton(tr(self.ui_lang, "btn_open_folder"))
        self.btn_open_folder.setEnabled(False)
        self.btn_open_folder.clicked.connect(
            lambda: self.last_generated_file and open_path_crossplatform(str(Path(self.last_generated_file).parent))
        )
        post_flow.addWidget(self.btn_open_file)
        post_flow.addWidget(self.btn_open_folder)
        lay.addWidget(post_wrap)
        lay.addStretch(1)
        self._on_conv_format_changed("pdf")

    def _render_hardware_locked(self, parent_tab: QWidget, section_title: str, features: List[str]):
        lay = parent_tab._inner_layout
        box = QGroupBox(f" 💻 {section_title} — Hardware insuficiente ")
        bl = QVBoxLayout(box)
        hw_l = QLabel(f"Equipo detectado: {self.hw.ram_total_gb:.1f} GB RAM | {self.hw.cpu_cores} núcleos | {self.hw.backend.upper()}")
        hw_l.setProperty("role", "warn")
        hw_l.setWordWrap(True)
        bl.addWidget(hw_l)
        info = QLabel("Con ≥6 GB de RAM (recomendado ≥10–16 GB RAM o GPU Vulkan/Metal), se desbloquearían:")
        info.setWordWrap(True)
        bl.addWidget(info)
        for feat in features:
            fl = QLabel(f"  • {feat}")
            fl.setWordWrap(True)
            bl.addWidget(fl)
        bl.addStretch(1)
        lay.addWidget(box)

    def _build_translate_tab(self):
        if not self.ai_tier.vlm_enabled:
            self._render_hardware_locked(
                self.tab_translate,
                "Traducción Fiel de Documentos a Fichero",
                [
                    "Traducción contextual directa a PDF, PDF/A-2b, Word (.docx), ODT y eBook (.epub).",
                    "Preservación de fondos, colores e imágenes mediante inpainting IA.",
                ],
            )
            return

        lay = self.tab_translate._inner_layout
        lay.setSpacing(4)

        lang_box = QGroupBox(" 🌐 Idiomas de traducción contextual ")
        ll = FlowLayout(lang_box, margin=8, h_spacing=8, v_spacing=4)
        self._flow_layouts.append(ll)
        ll.addWidget(QLabel("Idioma origen:"))
        self.trans_src_combo = QComboBox()
        self.trans_src_combo.addItem("Auto-detectar")
        self.trans_src_combo.addItems(TRANSLATION_TARGET_LANGUAGES)
        ll.addWidget(self.trans_src_combo)

        ll.addWidget(QLabel("Idioma destino:"))
        self.trans_dst_combo = QComboBox()
        self.trans_dst_combo.addItems(TRANSLATION_TARGET_LANGUAGES)
        self.trans_dst_combo.currentIndexChanged.connect(lambda: self._update_default_trans_output())
        ll.addWidget(self.trans_dst_combo)

        t_hint = QLabel("Traducción contextual con Qwen3-VL y Prompt Madre")
        t_hint.setProperty("role", "ok")
        ll.addWidget(t_hint)

        fmt_box = QGroupBox(" 📁 Formato del documento traducido ")
        fmt_lay = QVBoxLayout(fmt_box)
        fmt_lay.setSpacing(2)
        self.trans_format_val = "docx"
        self.trans_fmt_group, self.trans_fmt_radios, self.trans_fmt_desc_lbl = self._build_radio_format_grid(
            fmt_lay, "docx", self._on_trans_format_changed
        )

        vis_box = QGroupBox(" 🎨 Maquetación y optimización de color e imagen ")
        vis_lay = QVBoxLayout(vis_box)
        vis_lay.setSpacing(2)
        vr1_w = QWidget()
        vr1 = FlowLayout(vr1_w, h_spacing=12, v_spacing=4)
        self._flow_layouts.append(vr1)
        self.trans_preserve_chk = QCheckBox("Preservar diseño visual, colores, fondos e imágenes (Inpainting)")
        self.trans_preserve_chk.setChecked(True)
        self.trans_grayscale_chk = QCheckBox("Escala de grises (blanco y negro)")
        vr1.addWidget(self.trans_preserve_chk)
        vr1.addWidget(self.trans_grayscale_chk)
        vis_lay.addWidget(vr1_w)

        vr2_w = QWidget()
        vr2 = FlowLayout(vr2_w, h_spacing=10, v_spacing=4)
        self._flow_layouts.append(vr2)
        self.trans_force_ocr_chk = QCheckBox("Forzar OCR (re-escanear)")
        self.trans_hw_chk = QCheckBox("Modo letra manuscrita (Visión)")
        vr2.addWidget(self.trans_force_ocr_chk)
        vr2.addWidget(self.trans_hw_chk)
        vr2.addWidget(QLabel("Compresión:"))
        self.trans_comp_combo = QComboBox()
        for lbl, _c in COMPRESSION_LABELS:
            self.trans_comp_combo.addItem(lbl)
        vr2.addWidget(self.trans_comp_combo)
        vis_lay.addWidget(vr2_w)

        out_box = QGroupBox(" 💾 Fichero traducido de salida ")
        ol = QHBoxLayout(out_box)
        self.trans_out_edit = QLineEdit()
        ol.addWidget(self.trans_out_edit, 1)
        btn_t_save = QPushButton("Guardar como...")
        btn_t_save.clicked.connect(self._browse_trans_output)
        ol.addWidget(btn_t_save)
        self._add_columns(lay, [lang_box, fmt_box], [vis_box, out_box])

        self.btn_translate_doc = QPushButton("🌐  Traducir y Generar Documento")
        self.btn_translate_doc.setObjectName("primaryBtn")
        self.btn_translate_doc.clicked.connect(self._start_document_translation)
        lay.addWidget(self.btn_translate_doc)

        self.trans_progress = QProgressBar()
        self.trans_progress.setRange(0, 100)
        self.trans_progress.setValue(0)
        self.trans_progress.setTextVisible(False)
        lay.addWidget(self.trans_progress)

        self.trans_status_lbl = QLabel("Selecciona un fichero arriba, elige idioma y formato de salida traducido.")
        self.trans_status_lbl.setWordWrap(True)
        lay.addWidget(self.trans_status_lbl)

        pt_wrap = QWidget()
        pt_flow = FlowLayout(pt_wrap, h_spacing=8, v_spacing=4)
        self._flow_layouts.append(pt_flow)
        self.btn_open_trans_file = QPushButton("📄 Abrir documento traducido")
        self.btn_open_trans_file.setEnabled(False)
        self.btn_open_trans_file.clicked.connect(
            lambda: self.last_translated_file and open_path_crossplatform(self.last_translated_file)
        )
        self.btn_open_trans_folder = QPushButton("📁 Abrir carpeta")
        self.btn_open_trans_folder.setEnabled(False)
        self.btn_open_trans_folder.clicked.connect(
            lambda: self.last_translated_file and open_path_crossplatform(str(Path(self.last_translated_file).parent))
        )
        pt_flow.addWidget(self.btn_open_trans_file)
        pt_flow.addWidget(self.btn_open_trans_folder)
        lay.addWidget(pt_wrap)
        lay.addStretch(1)
        self._on_trans_format_changed("docx")

    def _build_chat_tab(self):
        if not self.ai_tier.vlm_enabled:
            self._render_hardware_locked(
                self.tab_chat,
                "Chat Multi-Documento con Citas",
                [
                    "Cargar múltiples PDFs e imágenes en una misma sesión.",
                    "Búsqueda híbrida semántica (BGE-M3 + BM25 + Árbol AST) sin límite de páginas.",
                    "Respuestas justificadas con citas exactas y extracto literal.",
                ],
            )
            return

        lay = self.tab_chat._inner_layout
        lay.setSpacing(5)
        tier = self.ai_tier
        hw_l = QLabel(
            f"💻 Perfil {tier.tier_name.upper()} ({self.hw.ram_total_gb:.1f} GB RAM) → "
            f"{tier.vlm_label} + {tier.embed_label} | Hasta {tier.max_chat_docs} documentos (sin límite de páginas vía AST)"
        )
        hw_l.setProperty("role", "accent")
        hw_l.setWordWrap(True)
        lay.addWidget(hw_l)

        docs_box = QGroupBox(" 📚 Documentos y Proyectos de Chat ")
        dl = QVBoxLayout(docs_box)
        dl.setSpacing(4)

        top_row = QHBoxLayout()
        self.chat_docs_list = QListWidget()
        self.chat_docs_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.chat_docs_list.setMaximumHeight(82)
        top_row.addWidget(self.chat_docs_list, 1)

        btn_grid = QGridLayout()
        btn_grid.setSpacing(4)
        self.btn_chat_add = QPushButton("➕ Añadir archivos...")
        self.btn_chat_add.clicked.connect(self._chat_add_files)
        btn_chat_top = QPushButton("📥 Archivo superior")
        btn_chat_top.clicked.connect(self._chat_add_current)
        btn_save_p = QPushButton("💾 Guardar proyecto")
        btn_save_p.clicked.connect(self._chat_save_project)
        btn_load_p = QPushButton("📂 Cargar proyecto")
        btn_load_p.clicked.connect(self._chat_load_project)
        btn_rem = QPushButton("🗑️ Quitar")
        btn_rem.clicked.connect(self._chat_remove_selected)
        btn_clr = QPushButton("🧹 Nueva sesión")
        btn_clr.clicked.connect(lambda: self._chat_clear(confirm=True))

        self._chat_btn_grid = (btn_grid, [self.btn_chat_add, btn_chat_top, btn_save_p, btn_load_p, btn_rem, btn_clr])
        self._reflow_chat_buttons()
        top_row.addLayout(btn_grid)
        dl.addLayout(top_row)

        self.chat_progress = QProgressBar()
        self.chat_progress.setRange(0, 100)
        self.chat_progress.setValue(0)
        self.chat_progress.setTextVisible(False)
        dl.addWidget(self.chat_progress)

        st_row = QHBoxLayout()
        self.chat_status_lbl = QLabel("Añade uno o varios documentos (PDF o imágenes) y haz preguntas con citas.")
        self.chat_status_lbl.setProperty("role", "accent")
        self.chat_status_lbl.setWordWrap(True)
        self.chat_count_lbl = QLabel("")
        self.chat_count_lbl.setProperty("role", "ok")
        st_row.addWidget(self.chat_status_lbl, 1)
        st_row.addWidget(self.chat_count_lbl)
        dl.addLayout(st_row)
        lay.addWidget(docs_box)

        self.chat_history_edit = QTextEdit()
        self.chat_history_edit.setReadOnly(True)
        self.chat_history_edit.setMinimumHeight(60)
        self.chat_history_edit.setAccessibleName("Historial de conversación multi-documento")
        lay.addWidget(self.chat_history_edit, 1)

        ask_box = QGroupBox(" 💬 Preguntar a los documentos cargados ")
        al = QVBoxLayout(ask_box)
        ask_row = QHBoxLayout()
        self.chat_question_edit = QLineEdit()
        self.chat_question_edit.setPlaceholderText("Escribe tu pregunta sobre los documentos cargados...")
        self.chat_question_edit.returnPressed.connect(self._chat_send)
        ask_row.addWidget(self.chat_question_edit, 1)
        self.btn_chat_send = QPushButton("💬 Enviar pregunta")
        self.btn_chat_send.setObjectName("primaryBtn")
        self.btn_chat_send.clicked.connect(self._chat_send)
        ask_row.addWidget(self.btn_chat_send)
        al.addLayout(ask_row)

        exp_w = QWidget()
        exp_flow = FlowLayout(exp_w, h_spacing=6, v_spacing=4)
        self._flow_layouts.append(exp_flow)
        exp_flow.addWidget(QLabel("Exportar chat (citas literales):"))
        self.chat_export_combo = QComboBox()
        for lbl, _c in EXPORT_CONV_FORMATS:
            self.chat_export_combo.addItem(lbl)
        exp_flow.addWidget(self.chat_export_combo)
        btn_exp = QPushButton("📥 Exportar chat + citas")
        btn_exp.clicked.connect(self._chat_export_conversation)
        exp_flow.addWidget(btn_exp)
        btn_read = QPushButton("🔊 Leer respuesta")
        btn_read.clicked.connect(self._speak_active_output)
        exp_flow.addWidget(btn_read)
        btn_stop = QPushButton("⏹️ Callar")
        btn_stop.clicked.connect(self._stop_tts)
        exp_flow.addWidget(btn_stop)
        al.addWidget(exp_w)
        lay.addWidget(ask_box)

    def _build_ai_tab(self):
        self.ai_buttons: List[QPushButton] = []
        if not self.ai_tier.vlm_enabled:
            self._render_hardware_locked(
                self.tab_ai,
                "IA Local y Manuscritos",
                [
                    "Lectura de letra manuscrita mediante visión multimodal (Qwen3-VL).",
                    "Resúmenes ejecutivos y Lectura Fácil (Norma UNE 153101 EX).",
                    "Traducción contextual y consultas con citas literales.",
                ],
            )
            return

        lay = self.tab_ai._inner_layout
        lay.setSpacing(5)
        tier = self.ai_tier
        hw_l = QLabel(
            f"💻 Hardware: {self.hw.ram_total_gb:.1f} GB RAM | {self.hw.backend.upper()} | "
            f"Perfil {tier.tier_name.upper()} → {tier.vlm_label} + {tier.embed_label} (ctx={tier.recommended_n_ctx})"
        )
        hw_l.setProperty("role", "accent")
        hw_l.setWordWrap(True)
        lay.addWidget(hw_l)

        opts_w = QWidget()
        opts_flow = FlowLayout(opts_w, h_spacing=14, v_spacing=4)
        self._flow_layouts.append(opts_flow)
        self.ai_hw_chk = QCheckBox(tr(self.ui_lang, "chk_handwriting"))
        self.ai_force_ocr_chk = QCheckBox("Forzar OCR (ignorar texto embebido)")
        opts_flow.addWidget(self.ai_hw_chk)
        opts_flow.addWidget(self.ai_force_ocr_chk)
        lay.addWidget(opts_w)

        self.ai_actions_box = QGroupBox(tr(self.ui_lang, "ai_actions_group"))
        aal = QVBoxLayout(self.ai_actions_box)

        btn_w = QWidget()
        btn_flow = FlowLayout(btn_w, h_spacing=6, v_spacing=4)
        self._flow_layouts.append(btn_flow)
        self.btn_ai_transcribe = QPushButton(tr(self.ui_lang, "btn_transcribe"))
        self.btn_ai_transcribe.clicked.connect(lambda: self._run_ai_action("transcribe"))
        self.btn_ai_summarize = QPushButton(tr(self.ui_lang, "btn_summarize"))
        self.btn_ai_summarize.clicked.connect(lambda: self._run_ai_action("summarize"))
        self.btn_ai_easy_read = QPushButton(strip_leading_emoji(tr(self.ui_lang, "btn_easy_read")).strip())
        self.btn_ai_easy_read.setAccessibleName("Adaptar documento a Lectura Fácil UNE 153101 EX")
        self.btn_ai_easy_read.clicked.connect(lambda: self._run_ai_action("easy_read"))
        self.btn_ai_translate = QPushButton(tr(self.ui_lang, "btn_translate"))
        self.btn_ai_translate.clicked.connect(lambda: self._run_ai_action("translate"))
        self.ai_trans_lang_combo = QComboBox()
        self.ai_trans_lang_combo.addItems(TRANSLATION_TARGET_LANGUAGES)

        for w in (
            self.btn_ai_transcribe,
            self.btn_ai_summarize,
            self.btn_ai_easy_read,
            self.btn_ai_translate,
            self.ai_trans_lang_combo,
        ):
            btn_flow.addWidget(w)
        aal.addWidget(btn_w)

        ask_row = QHBoxLayout()
        self.ai_lbl_question = QLabel(tr(self.ui_lang, "lbl_question"))
        ask_row.addWidget(self.ai_lbl_question)
        self.ai_question_edit = QLineEdit()
        self.ai_question_edit.setPlaceholderText("Haz una pregunta directa sobre este documento...")
        self.ai_question_edit.returnPressed.connect(lambda: self._run_ai_action("ask"))
        ask_row.addWidget(self.ai_question_edit, 1)
        self.btn_ai_ask = QPushButton(tr(self.ui_lang, "btn_ask"))
        self.btn_ai_ask.setObjectName("primaryBtn")
        self.btn_ai_ask.clicked.connect(lambda: self._run_ai_action("ask"))
        ask_row.addWidget(self.btn_ai_ask)
        aal.addLayout(ask_row)
        lay.addWidget(self.ai_actions_box)

        self.ai_buttons.extend(
            [self.btn_ai_transcribe, self.btn_ai_summarize, self.btn_ai_easy_read, self.btn_ai_translate, self.btn_ai_ask]
        )

        self.ai_progress = QProgressBar()
        self.ai_progress.setRange(0, 100)
        self.ai_progress.setValue(0)
        self.ai_progress.setTextVisible(False)
        lay.addWidget(self.ai_progress)

        self.ai_status_lbl = QLabel(tr(self.ui_lang, "ai_status_ready"))
        self.ai_status_lbl.setWordWrap(True)
        lay.addWidget(self.ai_status_lbl)

        self.ai_output_edit = QTextEdit()
        self.ai_output_edit.setMinimumHeight(105)
        self.ai_output_edit.setAccessibleName("Resultado del análisis de IA")
        self.ai_output_edit.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ai_output_edit.customContextMenuRequested.connect(self._show_ai_context_menu)
        lay.addWidget(self.ai_output_edit, 1)

        bot_w = QWidget()
        bot_flow = FlowLayout(bot_w, h_spacing=6, v_spacing=4)
        self._flow_layouts.append(bot_flow)
        btn_cp = QPushButton("📋 Copiar texto")
        btn_cp.clicked.connect(self._copy_ai_output)
        btn_sv = QPushButton("💾 Guardar .txt")
        btn_sv.clicked.connect(self._save_ai_output)
        btn_rd = QPushButton("🔊 Leer en voz alta")
        btn_rd.clicked.connect(self._speak_active_output)
        btn_st = QPushButton("⏹️ Callar")
        btn_st.clicked.connect(self._stop_tts)
        self.ai_export_combo = QComboBox()
        for lbl, _c in EXPORT_CONV_FORMATS:
            self.ai_export_combo.addItem(lbl)
        btn_exp = QPushButton("📥 Exportar informe...")
        btn_exp.clicked.connect(self._export_ai_output_with_refs)
        for w in (btn_cp, btn_sv, btn_rd, btn_st, QLabel("Exportar consulta + citas:"), self.ai_export_combo, btn_exp):
            bot_flow.addWidget(w)
        lay.addWidget(bot_w)

    def _build_anonymize_tab(self):
        lay = self.tab_anonymize._inner_layout
        lay.setSpacing(5)

        info_box = QGroupBox(" 🔒 Anonimizador RGPD (Motor determinista 100% Python — funciona en cualquier hardware) ")
        il = QVBoxLayout(info_box)
        desc = QLabel(
            "Detecta y oculta instantáneamente sin IA: DNI, NIE, CIF, IBAN, Tarjetas, NUSS, Emails, "
            "Teléfonos, IPs, Matrículas, Direcciones postales y Nombres con tratamiento (Don/Doña/Sr./Sra.)."
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        il.addWidget(desc)

        ctrl_w = QWidget()
        ctrl_flow = FlowLayout(ctrl_w, h_spacing=10, v_spacing=4)
        self._flow_layouts.append(ctrl_flow)
        ctrl_flow.addWidget(QLabel("Estilo de ocultación:"))
        self.anon_mask_tags_rb = QRadioButton("Etiquetas ([DNI], [NOMBRE])")
        self.anon_mask_tags_rb.setChecked(True)
        self.anon_mask_blocks_rb = QRadioButton("Bloques negros (████████)")
        mask_grp = QButtonGroup(self)
        mask_grp.addButton(self.anon_mask_tags_rb)
        mask_grp.addButton(self.anon_mask_blocks_rb)
        ctrl_flow.addWidget(self.anon_mask_tags_rb)
        ctrl_flow.addWidget(self.anon_mask_blocks_rb)
        il.addWidget(ctrl_w)

        if self.ai_tier.vlm_enabled:
            self.anon_step1_rb = QRadioButton("⚡ Paso 1 solo (100% Python instantáneo — sin IA)")
            self.anon_step2_rb = QRadioButton(
                f"🧠 Paso 1 + Paso 2 (IA local {self.ai_tier.vlm_label}: nombres propios sin tratamiento y empresas)"
            )
            self.anon_step2_rb.setChecked(True)
            mode_grp = QButtonGroup(self)
            mode_grp.addButton(self.anon_step1_rb)
            mode_grp.addButton(self.anon_step2_rb)
            il.addWidget(self.anon_step1_rb)
            il.addWidget(self.anon_step2_rb)
        else:
            self.anon_step1_rb = None
            self.anon_step2_rb = None
            hw_hint = QLabel("ℹ️ Modo Paso 1 (100% Python) activo. Con ≥6 GB RAM se desbloquea el refuerzo semántico IA.")
            hw_hint.setProperty("role", "warn")
            hw_hint.setWordWrap(True)
            il.addWidget(hw_hint)
        lay.addWidget(info_box)

        self.btn_run_anon = QPushButton("🔒  Anonimizar documento seleccionado")
        self.btn_run_anon.setObjectName("primaryBtn")
        self.btn_run_anon.clicked.connect(self._run_anonymize_standalone)
        lay.addWidget(self.btn_run_anon)

        self.anon_progress = QProgressBar()
        self.anon_progress.setRange(0, 100)
        self.anon_progress.setValue(0)
        self.anon_progress.setTextVisible(False)
        lay.addWidget(self.anon_progress)

        self.anon_status_lbl = QLabel("Listo. Selecciona un documento arriba y pulsa 'Anonimizar documento'.")
        self.anon_status_lbl.setWordWrap(True)
        lay.addWidget(self.anon_status_lbl)

        self.anon_output_edit = QTextEdit()
        self.anon_output_edit.setMinimumHeight(105)
        lay.addWidget(self.anon_output_edit, 1)

        bot_w = QWidget()
        bot_flow = FlowLayout(bot_w, h_spacing=8, v_spacing=4)
        self._flow_layouts.append(bot_flow)
        btn_cp = QPushButton("📋 Copiar resultado")
        btn_cp.clicked.connect(self._copy_anon_output)
        btn_sv = QPushButton("💾 Guardar como .txt")
        btn_sv.clicked.connect(self._save_anon_output)
        btn_rd = QPushButton("🔊 Leer resultado")
        btn_rd.clicked.connect(self._speak_active_output)
        btn_st = QPushButton("⏹️ Callar")
        btn_st.clicked.connect(self._stop_tts)
        for w in (btn_cp, btn_sv, btn_rd, btn_st):
            bot_flow.addWidget(w)
        lay.addWidget(bot_w)

    def _build_pdf_tools_tab(self):
        self.pdf_tool_buttons: List[QPushButton] = []
        lay = self.tab_pdf_tools._inner_layout
        lay.setSpacing(5)

        legal_l = QLabel(
            "⚖️ Aviso legal: utiliza estas herramientas únicamente sobre documentos propios o con autorización legítima "
            "(no realiza crackeo de claves de apertura; respeta propiedad intelectual, RGPD y autenticidad documental)."
        )
        legal_l.setProperty("role", "warn")
        legal_l.setWordWrap(True)
        lay.addWidget(legal_l)

        u_box = QGroupBox(" 🔓 Desbloquear PDF (quitar contraseña o restricciones de copia/impresión) ")
        ul = FlowLayout(u_box, margin=8, h_spacing=8, v_spacing=4)
        self._flow_layouts.append(ul)
        ul.addWidget(QLabel("Contraseña (opcional si solo tiene restricciones):"))
        self.pdf_pw_edit = QLineEdit()
        self.pdf_pw_edit.setEchoMode(QLineEdit.Password)
        self.pdf_pw_edit.setFixedWidth(190)
        ul.addWidget(self.pdf_pw_edit)
        btn_unlock = QPushButton("🔓 Desbloquear PDF")
        btn_unlock.clicked.connect(lambda: self._run_pdf_tool("unlock"))
        ul.addWidget(btn_unlock)
        self.pdf_tool_buttons.append(btn_unlock)

        s_box = QGroupBox(" ✍️ Borrar Firmas Digitales y Sellos de Formulario ")
        sl = FlowLayout(s_box, margin=8, h_spacing=10, v_spacing=4)
        self._flow_layouts.append(sl)
        s_info = QLabel("Elimina campos criptográficos (/Sig), bloqueos de edición (DocMDP) y sellos visuales.")
        s_info.setProperty("role", "muted")
        sl.addWidget(s_info)
        btn_sig = QPushButton("🗑️ Borrar firmas del PDF")
        btn_sig.clicked.connect(lambda: self._run_pdf_tool("signatures"))
        sl.addWidget(btn_sig)
        self.pdf_tool_buttons.append(btn_sig)

        w_box = QGroupBox(" 🧽 Limpiar Marcas de Agua (Vectoriales, Capas OCG y Escaneos) ")
        wl = QVBoxLayout(w_box)
        wr1_w = QWidget()
        wr1 = FlowLayout(wr1_w, h_spacing=8, v_spacing=4)
        self._flow_layouts.append(wr1)
        wr1.addWidget(QLabel("Texto de marca a borrar (opcional, ej. BORRADOR):"))
        self.wm_text_edit = QLineEdit()
        self.wm_text_edit.setMinimumWidth(220)
        wr1.addWidget(self.wm_text_edit)
        wl.addWidget(wr1_w)

        wr2_w = QWidget()
        wr2 = FlowLayout(wr2_w, h_spacing=10, v_spacing=4)
        self._flow_layouts.append(wr2)
        self.wm_annots_chk = QCheckBox("Eliminar /Watermark y capas OCG")
        self.wm_annots_chk.setChecked(True)
        self.wm_scan_chk = QCheckBox("Limpiar marca en escaneos (OpenCV)")
        btn_wm = QPushButton("🧽 Limpiar marcas de agua")
        btn_wm.clicked.connect(lambda: self._run_pdf_tool("watermarks"))
        wr2.addWidget(self.wm_annots_chk)
        wr2.addWidget(self.wm_scan_chk)
        wr2.addWidget(btn_wm)
        wl.addWidget(wr2_w)
        self.pdf_tool_buttons.append(btn_wm)

        o_box = QGroupBox(" 🗜️ Comprimir PDF, Escala de Grises y PDF/A-2b ")
        ol = FlowLayout(o_box, margin=8, h_spacing=8, v_spacing=4)
        self._flow_layouts.append(ol)
        ol.addWidget(QLabel("Compresión:"))
        self.pdf_opt_comp_combo = QComboBox()
        for lbl, _c in COMPRESSION_LABELS:
            self.pdf_opt_comp_combo.addItem(lbl)
        self.pdf_opt_comp_combo.setCurrentIndex(1)
        ol.addWidget(self.pdf_opt_comp_combo)
        self.pdf_opt_gray_chk = QCheckBox("Escala de grises")
        self.pdf_opt_pdfa_chk = QCheckBox("Estándar PDF/A-2b")
        btn_opt = QPushButton("🗜️ Optimizar PDF")
        btn_opt.clicked.connect(lambda: self._run_pdf_tool("optimize"))
        ol.addWidget(self.pdf_opt_gray_chk)
        ol.addWidget(self.pdf_opt_pdfa_chk)
        ol.addWidget(btn_opt)
        self.pdf_tool_buttons.append(btn_opt)
        self._add_columns(lay, [u_box, s_box], [w_box, o_box])

        self.pdf_tools_progress = QProgressBar()
        self.pdf_tools_progress.setRange(0, 100)
        self.pdf_tools_progress.setValue(0)
        self.pdf_tools_progress.setTextVisible(False)
        lay.addWidget(self.pdf_tools_progress)

        self.pdf_tools_status_lbl = QLabel("Selecciona un PDF arriba y elige una herramienta.")
        self.pdf_tools_status_lbl.setWordWrap(True)
        lay.addWidget(self.pdf_tools_status_lbl)

        pp_w = QWidget()
        pp_f = FlowLayout(pp_w, h_spacing=8, v_spacing=4)
        self._flow_layouts.append(pp_f)
        self.btn_pdf_open_file = QPushButton("📄 Abrir PDF resultante")
        self.btn_pdf_open_file.setEnabled(False)
        self.btn_pdf_open_file.clicked.connect(
            lambda: self.last_pdf_tool_file and open_path_crossplatform(self.last_pdf_tool_file)
        )
        self.btn_pdf_open_folder = QPushButton("📁 Abrir carpeta")
        self.btn_pdf_open_folder.setEnabled(False)
        self.btn_pdf_open_folder.clicked.connect(
            lambda: self.last_pdf_tool_file and open_path_crossplatform(str(Path(self.last_pdf_tool_file).parent))
        )
        pp_f.addWidget(self.btn_pdf_open_file)
        pp_f.addWidget(self.btn_pdf_open_folder)
        lay.addWidget(pp_w)
        lay.addStretch(1)

    # ---------------- DISEÑO ELÁSTICO, ZOOM Y TEMAS ----------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_responsive()

    def _is_wide_layout(self) -> bool:
        """True si hay ancho suficiente para colocar los bloques en dos columnas."""
        needed = int(1100 * (self.a11y.ui_font_size / 10.0))
        return self.width() >= needed and self.a11y.ui_font_size < 15

    def _add_columns(self, lay: QVBoxLayout, left: List[QWidget], right: List[QWidget]):
        cols = _AdaptiveColumns(left, right)
        if not hasattr(self, "_adaptive_cols"):
            self._adaptive_cols: List[_AdaptiveColumns] = []
        self._adaptive_cols.append(cols)
        lay.addWidget(cols)

    def _reflow_chat_buttons(self):
        grid, btns = getattr(self, "_chat_btn_grid", (None, []))
        if grid is None:
            return
        cols = 3 if getattr(self, "_wide_now", False) else 2
        for b in btns:
            grid.removeWidget(b)
        for i, b in enumerate(btns):
            grid.addWidget(b, i // cols, i % cols)

    def _reflow_radio_grid(self, grid: QGridLayout, radios: List[QRadioButton]):
        if getattr(self, "_wide_now", False):
            avail_w = max(300, self.width() // 2 - 80)
            cols = 2 if (avail_w >= 440 and self.a11y.ui_font_size < 15) else 1
        else:
            avail_w = max(480, self.width() - 80)
            cols = 2 if (avail_w >= 680 and self.a11y.ui_font_size < 15) else 1
        for idx, rb in enumerate(radios):
            grid.removeWidget(rb)
        for idx, rb in enumerate(radios):
            grid.addWidget(rb, idx // cols, idx % cols, Qt.AlignLeft)

    def _relayout_responsive(self):
        w = max(self.width(), 680)
        stacked = w < 1040 or self.a11y.ui_font_size >= 13
        if stacked != self._header_stacked:
            self._header_stacked = stacked
            self.header_grid.removeWidget(self.brand_widget)
            self.header_grid.removeWidget(self.tools_widget)
            if stacked:
                self.header_grid.setColumnStretch(0, 1)
                self.header_grid.setColumnStretch(1, 0)
                self.header_grid.addWidget(self.brand_widget, 0, 0)
                self.tools_flow.set_align_right(False)
                self.header_grid.addWidget(self.tools_widget, 1, 0)
            else:
                self.header_grid.setColumnStretch(0, 0)
                self.header_grid.setColumnStretch(1, 1)
                self.header_grid.addWidget(self.brand_widget, 0, 0, Qt.AlignTop | Qt.AlignLeft)
                self.tools_flow.set_align_right(True)
                self.header_grid.addWidget(self.tools_widget, 0, 1, Qt.AlignTop)

        full_needed = int(780 * (self.a11y.ui_font_size / 10.0) * (1.12 if self.a11y.large_targets else 1.0))
        compact = w < full_needed
        if (compact, self.ui_lang) != self._tabs_compact:
            self._tabs_compact = (compact, self.ui_lang)
            suffix = "_short" if compact else ""
            tab_pairs = [
                (self.tab_convert, f"tab_convert{suffix}"),
                (self.tab_translate, f"tab_translate{suffix}"),
                (self.tab_chat, f"tab_chat{suffix}"),
                (self.tab_ai, f"tab_ai{suffix}"),
                (self.tab_anonymize, f"tab_anonymize{suffix}"),
                (self.tab_pdf_tools, f"tab_pdf_tools{suffix}"),
            ]
            for tab_w, key in tab_pairs:
                if tab_w is not None:
                    idx = self.tabs.indexOf(tab_w)
                    if idx >= 0:
                        self.tabs.setTabText(idx, strip_leading_emoji(tr(self.ui_lang, key)).strip())

        self._wide_now = self._is_wide_layout()
        for ac in getattr(self, "_adaptive_cols", []):
            ac.set_wide(self._wide_now)
        self._reflow_chat_buttons()
        for grid, rbs in self._radio_grids:
            self._reflow_radio_grid(grid, rbs)
        for fl in self._flow_layouts:
            fl.invalidate()

    def _apply_qt_icon_refs(self):
        ic_map = [
            ("btn_accessibility", "accessibility"),
            ("btn_tts_read", "tts_speak"),
            ("btn_tts_stop", "tts_stop"),
            ("btn_github", "github"),
            ("btn_legal", "legal"),
            ("btn_update", "update"),
            ("btn_reinstall", "reinstall"),
            ("btn_cache", "cache"),
            ("btn_clear_logs", "clear_logs"),
            ("btn_view_logs", "view_logs"),
            ("btn_ai_easy_read", "easy_read"),
        ]
        ic_px = self._calc_icon_px()
        for attr, key in ic_map:
            btn = getattr(self, attr, None)
            ic = self._icons.get(key)
            if btn is not None and isinstance(ic, QIcon):
                btn.setIcon(ic)
                btn.setIconSize(QSize(ic_px, ic_px))

        if "logo_pixmap" in self._icons:
            self.logo_lbl.setPixmap(self._icons["logo_pixmap"])

        tab_ic = [
            (self.tab_convert, "tab_convert"),
            (self.tab_translate, "tab_translate"),
            (self.tab_chat, "tab_chat"),
            (self.tab_ai, "tab_ai"),
            (self.tab_anonymize, "tab_anonymize"),
            (self.tab_pdf_tools, "tab_pdf_tools"),
        ]
        self.tabs.setIconSize(QSize(ic_px, ic_px))
        for tab_w, key in tab_ic:
            if tab_w is not None and isinstance(self._icons.get(key), QIcon):
                idx = self.tabs.indexOf(tab_w)
                if idx >= 0:
                    self.tabs.setTabIcon(idx, self._icons[key])

    def _apply_theme_and_fonts(self, save_prefs: bool = True):
        self.palette = get_accessible_palette(self.a11y.theme_mode, self._os_dark_mode)
        self.is_dark_mode = self.palette.get("is_dark") == "1"
        fam = self._get_ui_font_family()
        qss = _build_qt_stylesheet(
            self.palette,
            font_family=fam,
            ui_size=self.a11y.ui_font_size,
            large_targets=self.a11y.large_targets,
        )
        self.setStyleSheet(qss)
        QApplication.instance().setFont(QFont(fam, self.a11y.ui_font_size))

        self._icons = _build_qt_icons(self.is_dark_mode, icon_px=self._calc_icon_px(), logo_px=self._calc_logo_px())
        self._apply_qt_icon_refs()

        txt_fam = self._get_text_font_family(prefer_mono=True)
        chat_fam = self._get_text_font_family(prefer_mono=False)
        for attr, f_name in (("ai_output_edit", txt_fam), ("anon_output_edit", txt_fam), ("chat_history_edit", chat_fam)):
            ed = getattr(self, attr, None)
            if ed is not None:
                ed.setFont(QFont(f_name, self.a11y.text_font_size))

        self.btn_zoom_pct.setText(f"{self.a11y.zoom_percent}%")
        self._relayout_responsive()
        if save_prefs:
            try:
                self.a11y.save()
            except Exception:
                pass

    def _adjust_global_zoom(self, delta: int):
        new_ui = max(9, min(18, self.a11y.ui_font_size + delta))
        new_txt = max(9, min(24, self.a11y.text_font_size + delta))
        if new_ui == self.a11y.ui_font_size and new_txt == self.a11y.text_font_size:
            return
        self.a11y.ui_font_size = new_ui
        self.a11y.text_font_size = new_txt
        self._apply_theme_and_fonts()

    def _reset_global_zoom(self):
        self.a11y.ui_font_size = 10
        self.a11y.text_font_size = 11
        self._apply_theme_and_fonts()

    # ---------------- ACCIONES COMUNES, IDIOMA Y ARCHIVOS ----------------
    def _on_ui_language_changed(self, _idx: int = 0):
        selected_name = self.lang_combo.currentText()
        for code, name in SUPPORTED_UI_LANGUAGES:
            if name == selected_name:
                self.ui_lang = code
                break
        if hasattr(self, "ai_trans_lang_combo"):
            self.ai_trans_lang_combo.setCurrentText(selected_name)
        if hasattr(self, "trans_dst_combo"):
            self.trans_dst_combo.setCurrentText(selected_name)
        self._apply_language()
        self._update_default_trans_output()

    def _apply_language(self):
        lang = self.ui_lang
        self.setWindowTitle(tr(lang, "window_title"))
        self.subtitle_lbl.setText(tr(lang, "subtitle"))
        self.btn_accessibility.setText(strip_leading_emoji(tr(lang, "btn_accessibility")).strip())
        self.btn_tts_read.setText(strip_leading_emoji(tr(lang, "btn_tts_read")).strip())
        self.btn_github.setText(strip_leading_emoji(tr(lang, "btn_github")).strip())
        self.btn_legal.setText(strip_leading_emoji(tr(lang, "btn_legal")).strip())
        self.btn_update.setText(strip_leading_emoji(tr(lang, "btn_update")).strip())
        self.btn_reinstall.setText(strip_leading_emoji(tr(lang, "btn_reinstall")).strip())
        self.btn_cache.setText(strip_leading_emoji(tr(lang, "btn_cache")).strip())
        self.btn_clear_logs.setText(strip_leading_emoji(tr(lang, "btn_clear_logs")).strip())
        self.btn_view_logs.setText(strip_leading_emoji(tr(lang, "btn_view_logs")).strip())
        self.input_group.setTitle(tr(lang, "input_group"))
        self.btn_paste.setText(tr(lang, "btn_paste"))
        self.btn_browse.setText(tr(lang, "btn_browse"))
        self.conv_fmt_grp_box.setTitle(tr(lang, "format_group"))
        for fmt_key, rb in self.conv_fmt_radios.items():
            lbl_txt, _desc = tr(lang, f"fmt_{fmt_key}")
            rb.setText(lbl_txt)
        self._on_conv_format_changed(self.conv_format_val)
        if self.ai_tier.vlm_enabled and hasattr(self, "trans_fmt_radios"):
            self._on_trans_format_changed(self.trans_format_val)
        self.conv_out_box.setTitle(tr(lang, "output_group"))
        self.btn_save_as.setText(tr(lang, "btn_save_as"))
        self.btn_convert.setText(tr(lang, "btn_convert"))
        self.btn_open_file.setText(tr(lang, "btn_open_file"))
        self.btn_open_folder.setText(tr(lang, "btn_open_folder"))
        if self.ai_tier.vlm_enabled and hasattr(self, "ai_actions_box"):
            self.ai_hw_chk.setText(tr(lang, "chk_handwriting"))
            self.ai_actions_box.setTitle(tr(lang, "ai_actions_group"))
            self.btn_ai_transcribe.setText(tr(lang, "btn_transcribe"))
            self.btn_ai_summarize.setText(tr(lang, "btn_summarize"))
            self.btn_ai_easy_read.setText(strip_leading_emoji(tr(lang, "btn_easy_read")).strip())
            self.btn_ai_translate.setText(tr(lang, "btn_translate"))
            self.ai_lbl_question.setText(tr(lang, "lbl_question"))
            self.btn_ai_ask.setText(tr(lang, "btn_ask"))
        self.footer_lbl.setText(tr(lang, "footer"))
        if not self.input_file_path:
            self.drop_zone.setText(tr(lang, "drop_prompt"))
            self.conv_status_lbl.setText(tr(lang, "status_ready"))
            if hasattr(self, "ai_status_lbl"):
                self.ai_status_lbl.setText(tr(lang, "ai_status_ready"))
        else:
            self.drop_zone.setText(tr(lang, "drop_selected", name=Path(self.input_file_path).name))
        self._tabs_compact = None
        self._relayout_responsive()

    def _browse_input(self):
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar documento o imagen",
            "",
            "Ficheros soportados (*.pdf *.png *.jpg *.jpeg *.tiff *.tif *.bmp *.webp);;PDF (*.pdf);;Todos (*.*)",
        )
        if chosen:
            self._set_input_file(chosen)

    def _paste_from_clipboard(self):
        focused = QApplication.focusWidget()
        if isinstance(focused, (QLineEdit, QTextEdit)) and focused is not self.input_edit:
            return
        cb = QApplication.clipboard()
        mime = cb.mimeData()
        if mime is not None:
            if mime.hasImage():
                img = cb.image()
                if not img.isNull():
                    temp_dir = Path(tempfile.gettempdir()) / "open_ocreader"
                    temp_dir.mkdir(parents=True, exist_ok=True)
                    temp_p = temp_dir / f"captura_portapapeles_{int(time.time())}.png"
                    img.save(str(temp_p))
                    self._set_input_file(str(temp_p))
                    self.conv_status_lbl.setText("✓ Imagen capturada del portapapeles cargada correctamente.")
                    return
            if mime.hasUrls():
                for u in mime.urls():
                    lp = u.toLocalFile()
                    if lp and Path(lp).is_file():
                        self._set_input_file(lp)
                        return
            txt = cb.text().strip().strip('"').strip("'")
            if txt and Path(txt).is_file():
                self._set_input_file(txt)
                return
        self.conv_status_lbl.setText("No se detectó ningún fichero ni imagen compatible en el portapapeles.")

    def _set_input_file(self, file_path: str):
        p = Path(file_path)
        if not p.exists():
            QMessageBox.critical(self, "Error", f"El fichero no existe:\n{file_path}")
            return
        resolved = str(p.resolve())
        self.input_file_path = resolved
        self.input_edit.setText(resolved)
        self.cached_doc_text = None
        self.cached_doc_tree = None
        self.cached_doc_key = None
        self.last_ai_turn_record = None
        self.ai_turn_records = []

        self.drop_zone.setProperty("loaded", True)
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)
        self.drop_zone.setText(tr(self.ui_lang, "drop_selected", name=p.name))
        self._update_default_conv_output()
        self._update_default_trans_output()

        self.conv_status_lbl.setText(f"Fichero listo: {p.name}")
        if hasattr(self, "trans_status_lbl"):
            self.trans_status_lbl.setText(f"Fichero listo para traducir: {p.name}")
        if hasattr(self, "ai_status_lbl"):
            self.ai_status_lbl.setText(f"Documento cargado: {p.name}. Elige una acción de IA.")
        self._announce(f"Archivo seleccionado: {p.name}")

    def _get_input_path(self) -> str:
        val = self.input_edit.text().strip() or self.input_file_path
        self.input_file_path = val
        return val

    def _get_compression_code(self, label: str) -> str:
        return next((c for lbl, c in COMPRESSION_LABELS if lbl == label), "high")

    # ---------------- CONVERSIÓN ----------------
    def _on_conv_format_changed(self, fmt_key: str):
        self.conv_format_val = fmt_key
        _lbl, desc_txt = tr(self.ui_lang, f"fmt_{fmt_key}")
        self.conv_fmt_desc_lbl.setText(f"ℹ️ {desc_txt}")
        self._update_default_conv_output()

    def _update_default_conv_output(self):
        in_val = self._get_input_path()
        if not in_val:
            return
        in_p = Path(in_val)
        fmt = self.conv_format_val
        if fmt == "pdfa":
            self.conv_out_edit.setText(str(in_p.parent / f"{in_p.stem}_pdfa.pdf"))
        else:
            self.conv_out_edit.setText(str(in_p.parent / f"{in_p.stem}_ocr.{fmt}"))

    def _browse_conv_output(self):
        fmt = self.conv_format_val
        ext = ".pdf" if fmt == "pdfa" else f".{fmt}"
        chosen, _ = QFileDialog.getSaveFileName(self, "Guardar documento resultante como...", f"salida{ext}")
        if chosen:
            self.conv_out_edit.setText(chosen)

    def _start_conversion(self):
        in_path = self._get_input_path()
        if not in_path or not Path(in_path).exists():
            QMessageBox.warning(self, "Aviso", "Por favor, selecciona un fichero de entrada válido.")
            return
        out_path = self.conv_out_edit.text().strip()
        if not out_path:
            self._update_default_conv_output()
            out_path = self.conv_out_edit.text().strip()
        fmt = self.conv_format_val
        force_ocr = self.conv_force_ocr_chk.isChecked()
        grayscale = self.conv_grayscale_chk.isChecked()
        comp = self._get_compression_code(self.conv_comp_combo.currentText())

        self.btn_convert.setEnabled(False)
        self.btn_open_file.setEnabled(False)
        self.btn_open_folder.setEnabled(False)
        self.conv_progress.setRange(0, 0)
        self.conv_status_lbl.setText(f"Procesando '{Path(in_path).name}'...")

        def work(cb):
            t0 = time.perf_counter()
            res = DocumentConverter().convert(
                in_path,
                out_path,
                fmt,
                verbose=False,
                force_ocr=force_ocr,
                pdf_compression=comp,
                grayscale=grayscale,
                progress_cb=cb,
            )
            return res, time.perf_counter() - t0

        def ok(payload):
            result, elapsed = payload
            self.conv_progress.setRange(0, 100)
            self.conv_progress.setValue(100)
            self.btn_convert.setEnabled(True)
            self.last_generated_file = result.output_path
            self.btn_open_file.setEnabled(True)
            self.btn_open_folder.setEnabled(True)
            self.conv_status_lbl.setText(
                f"✓ Completado en {elapsed:.2f}s ({result.total_pages} pág.: "
                f"{result.native_text_pages} texto nativo, {result.ocr_pages} OCR). Guardado en: {result.output_path}"
            )
            self._announce(f"Conversión completada en {Path(result.output_path).name}")
            QMessageBox.information(self, "Completado", f"Documento guardado con éxito en:\n{result.output_path}")

        def err(msg: str):
            self.conv_progress.setRange(0, 100)
            self.conv_progress.setValue(0)
            self.btn_convert.setEnabled(True)
            self.conv_status_lbl.setText(f"Error: {msg}")
            self._announce(f"Error en conversión: {msg}")
            QMessageBox.critical(self, "Error", f"Error durante el procesamiento:\n{msg}")

        self._run_bg(work, ok, err, self.conv_status_lbl.setText)

    # ---------------- TRADUCCIÓN DIRECTA ----------------
    def _on_trans_format_changed(self, fmt_key: str):
        self.trans_format_val = fmt_key
        _lbl, desc_txt = tr(self.ui_lang, f"fmt_{fmt_key}")
        self.trans_fmt_desc_lbl.setText(f"ℹ️ {desc_txt}")
        self._update_default_trans_output()

    def _update_default_trans_output(self):
        if not hasattr(self, "trans_out_edit"):
            return
        in_val = self._get_input_path()
        if not in_val:
            return
        in_p = Path(in_val)
        fmt = self.trans_format_val
        ext = "pdf" if fmt == "pdfa" else fmt
        tgt = self.trans_dst_combo.currentText().strip() or "trad"
        lang_tag = "".join(c for c in tgt.lower() if c.isalnum())[:10] or "trad"
        self.trans_out_edit.setText(str(in_p.parent / f"{in_p.stem}_traducido_{lang_tag}.{ext}"))

    def _browse_trans_output(self):
        fmt = self.trans_format_val
        ext = ".pdf" if fmt == "pdfa" else f".{fmt}"
        chosen, _ = QFileDialog.getSaveFileName(self, "Guardar documento traducido como...", f"traducido{ext}")
        if chosen:
            self.trans_out_edit.setText(chosen)

    def _ensure_models_ready(self) -> bool:
        from .ai import LlamaRuntimeManager
        rt = LlamaRuntimeManager.get_instance()
        if rt.is_models_present():
            return True
        src = self._ask_model_download_source()
        if not src:
            return False
        rt.preferred_model_source = src
        return True

    def _ask_model_download_source(self) -> Optional[str]:
        dlg = QDialog(self)
        dlg.setWindowTitle("Descargar Modelo de IA (Qwen3-VL)")
        dlg.setMinimumWidth(460)
        lay = QVBoxLayout(dlg)
        lbl = QLabel("No se ha encontrado el modelo de IA en 'models/'. Elige origen de descarga (~2,9 GB):")
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        picked = {"src": None}
        for txt, code in (("🌐 Página Oficial (Hugging Face)", "official"), ("🐙 Proyecto GitHub (Ydalgo/Open-OCReader)", "github")):
            b = QPushButton(txt)
            b.clicked.connect(lambda _c=False, v=code: (picked.__setitem__("src", v), dlg.accept()))
            lay.addWidget(b)
        b_cancel = QPushButton("Cancelar")
        b_cancel.clicked.connect(dlg.reject)
        lay.addWidget(b_cancel)
        dlg.exec()
        return picked["src"]

    def _start_document_translation(self):
        in_path = self._get_input_path()
        if not in_path or not Path(in_path).exists():
            QMessageBox.warning(self, "Aviso", "Selecciona primero un fichero de entrada arriba.")
            return
        if not self._ensure_models_ready():
            return
        out_path = self.trans_out_edit.text().strip()
        if not out_path:
            self._update_default_trans_output()
            out_path = self.trans_out_edit.text().strip()

        fmt = self.trans_format_val
        target_lang = self.trans_dst_combo.currentText().strip() or get_llm_language_name(self.ui_lang)
        raw_src = self.trans_src_combo.currentText().strip()
        source_lang = "auto" if (not raw_src or raw_src.lower().startswith("auto")) else raw_src
        preserve = self.trans_preserve_chk.isChecked()
        gray = self.trans_grayscale_chk.isChecked()
        focr = self.trans_force_ocr_chk.isChecked()
        hw = self.trans_hw_chk.isChecked()
        comp = self._get_compression_code(self.trans_comp_combo.currentText())

        self.btn_translate_doc.setEnabled(False)
        self.btn_open_trans_file.setEnabled(False)
        self.btn_open_trans_folder.setEnabled(False)
        self.trans_progress.setRange(0, 0)
        self.trans_status_lbl.setText(f"Iniciando traducción a '{target_lang}' ({fmt.upper()})...")

        def work(cb):
            return DocumentConverter().translate_document(
                input_path=in_path,
                output_path=out_path,
                output_format=fmt,
                target_lang=target_lang,
                source_lang=source_lang,
                preserve_layout=preserve,
                pdf_compression=comp,
                grayscale=gray,
                force_ocr=focr,
                handwriting=hw,
                verbose=False,
                progress_cb=cb,
            )

        def ok(res):
            self.trans_progress.setRange(0, 100)
            self.trans_progress.setValue(100)
            self.btn_translate_doc.setEnabled(True)
            self.last_translated_file = res.output_path
            self.btn_open_trans_file.setEnabled(True)
            self.btn_open_trans_folder.setEnabled(True)
            self.trans_status_lbl.setText(
                f"✓ Documento traducido ({res.total_pages} pág., {res.total_elements} bloques) "
                f"en {res.elapsed_seconds:.2f}s → {Path(res.output_path).name}"
            )
            self._announce(f"Traducción completada al {target_lang}")

        def err(msg: str):
            self.trans_progress.setRange(0, 100)
            self.trans_progress.setValue(0)
            self.btn_translate_doc.setEnabled(True)
            self.trans_status_lbl.setText(f"Error en traducción: {msg}")
            self._announce(f"Error en traducción: {msg}")
            QMessageBox.critical(self, "Error al traducir documento", msg)

        self._run_bg(work, ok, err, self.trans_status_lbl.setText)

    # ---------------- CHAT MULTI-DOCUMENTO ----------------
    def _ensure_chat_engine(self):
        if self.chat_engine is None:
            from .ai.multi_doc_chat import MultiDocumentChat
            self.chat_engine = MultiDocumentChat()
        return self.chat_engine

    def _chat_append_message(self, sender_role: str, sender: str, text: str, refs=None):
        p = self.palette
        color = p["accent"] if sender_role == "user" else p["ok"]
        self.chat_history_edit.append(f'<b style="color:{color}">{self._html_esc(sender)}:</b>')
        self.chat_history_edit.append(f'<div style="margin-bottom:4px;">{self._html_esc(text).replace(chr(10), "<br/>")}</div>')
        if refs:
            self.chat_history_edit.append(
                f'<b style="color:{p["warn"]}">📚 Referencias consultadas (extracto literal original):</b>'
            )
            for r in refs:
                lit_preview = (getattr(r, "literal_text", "") or r.excerpt or "").strip().replace("\n", " ")
                if len(lit_preview) > 260:
                    lit_preview = lit_preview[:257] + "..."
                self.chat_history_edit.append(
                    f'<span style="color:{p["muted"]};font-family:monospace;">'
                    f'&nbsp;&nbsp;• [{self._html_esc(r.doc_id)} / {self._html_esc(r.ref_id)}] '
                    f'{self._html_esc(r.file_name)} — {self._html_esc(r.section_path)}</span>'
                )
                if lit_preview:
                    self.chat_history_edit.append(
                        f'<span style="color:{p["muted"]};font-style:italic;">'
                        f'&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;«{self._html_esc(lit_preview)}»</span>'
                    )
        self.chat_history_edit.append("")

    @staticmethod
    def _html_esc(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _refresh_chat_docs_ui(self):
        self.chat_docs_list.clear()
        self.chat_doc_paths = []
        if self.chat_engine is None:
            self.chat_count_lbl.setText("")
            return
        doc_ids = self.chat_engine.get_document_id_map()
        for path_str, (fname, tree) in self.chat_engine.documents.items():
            did = doc_ids[path_str]
            emb_tag = "BGE-M3+BM25" if tree.has_embeddings else "BM25+AST"
            self.chat_docs_list.addItem(f"[{did}] 📄 {fname}  ({len(tree.nodos)} nodos AST | {emb_tag})")
            self.chat_doc_paths.append(path_str)
        self.chat_count_lbl.setText(
            f"📚 {len(self.chat_doc_paths)}/{self.ai_tier.max_chat_docs} doc(s) | {self.chat_engine.total_nodes} nodos AST"
        )

    def _chat_add_files(self):
        chosen, _ = QFileDialog.getOpenFileNames(
            self,
            "Seleccionar documentos para chatear",
            "",
            "Documentos y capturas (*.pdf *.png *.jpg *.jpeg *.tiff *.tif *.bmp *.webp);;PDF (*.pdf);;Todos (*.*)",
        )
        if chosen:
            self._chat_index_paths(list(chosen))

    def _chat_add_current(self):
        in_p = self._get_input_path()
        if not in_p or not Path(in_p).exists():
            QMessageBox.warning(self, "Aviso", "Selecciona primero un fichero arriba.")
            return
        self._chat_index_paths([in_p])

    def _chat_index_paths(self, paths: List[str]):
        self.btn_chat_add.setEnabled(False)
        self.btn_chat_send.setEnabled(False)
        self.chat_progress.setRange(0, 0)
        self.chat_status_lbl.setText(f"⏳ Indexando {len(paths)} archivo(s) en caché SHA-256...")

        def work(cb):
            eng = self._ensure_chat_engine()
            added, errs = [], []
            for idx, p in enumerate(paths, start=1):
                try:
                    fname, n_nodes = eng.add_document(p, progress_cb=lambda m, i=idx: cb(f"[{i}/{len(paths)}] {m}"))
                    added.append(f"{fname} ({n_nodes} nodos)")
                except Exception as exc:
                    errs.append(f"{Path(p).name}: {exc}")
            return added, errs

        def ok(res):
            added, errs = res
            self.chat_progress.setRange(0, 100)
            self.chat_progress.setValue(100)
            self.btn_chat_add.setEnabled(True)
            self.btn_chat_send.setEnabled(True)
            self._refresh_chat_docs_ui()
            if added:
                self.chat_status_lbl.setText(f"✓ Listos: {', '.join(added)}")
                self._announce(f"Documentos indexados: {', '.join(added)}")
                self.chat_question_edit.setFocus()
            if errs:
                QMessageBox.warning(self, "Avisos al añadir documentos", "\n".join(errs))

        def err(msg: str):
            self.chat_progress.setRange(0, 100)
            self.chat_progress.setValue(0)
            self.btn_chat_add.setEnabled(True)
            self.btn_chat_send.setEnabled(True)
            self.chat_status_lbl.setText(f"Error: {msg}")

        self._run_bg(work, ok, err, self.chat_status_lbl.setText)

    def _chat_save_project(self):
        if not self.chat_doc_paths:
            QMessageBox.warning(self, "Sin documentos", "Añade al menos un documento antes de guardar.")
            return
        name, ok = QInputDialog.getText(self, "Guardar Proyecto de Chat", "Nombre del proyecto:")
        if ok and name.strip():
            from .ai.doc_cache import DocumentIndexCache
            DocumentIndexCache.get_instance().save_project(name.strip(), self.chat_doc_paths)
            self.chat_status_lbl.setText(f"✓ Proyecto '{name.strip()}' guardado ({len(self.chat_doc_paths)} archivo(s)).")

    def _chat_load_project(self):
        from .ai.doc_cache import DocumentIndexCache
        cache = DocumentIndexCache.get_instance()
        projects = cache.list_projects()
        if not projects:
            QMessageBox.information(self, "Proyectos", "No hay proyectos guardados todavía.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Cargar Proyecto de Chat (SHA-256)")
        dlg.resize(500, 320)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Selecciona un proyecto guardado:"))
        lb = QListWidget()
        for pname, nfiles, upd in projects:
            lb.addItem(f"📁 {pname}  —  {nfiles} archivo(s)  ({upd[:10]})")
        lay.addWidget(lb, 1)
        row = QHBoxLayout()
        b_load = QPushButton("📂 Cargar seleccionado")
        b_del = QPushButton("🗑️ Eliminar")
        b_cancel = QPushButton("Cancelar")

        def do_load():
            idx = lb.currentRow()
            if idx < 0:
                return
            pname = projects[idx][0]
            entries = cache.load_project(pname) or []
            dlg.accept()
            valid = [e["path"] for e in entries if Path(e["path"]).exists()]
            if valid:
                self._chat_clear(confirm=False)
                self._chat_index_paths(valid)

        def do_del():
            idx = lb.currentRow()
            if idx < 0:
                return
            pname = projects[idx][0]
            if QMessageBox.question(dlg, "Eliminar", f"¿Eliminar el proyecto '{pname}'?") == QMessageBox.Yes:
                cache.delete_project(pname)
                dlg.reject()
                self._chat_load_project()

        b_load.clicked.connect(do_load)
        b_del.clicked.connect(do_del)
        b_cancel.clicked.connect(dlg.reject)
        row.addWidget(b_load)
        row.addWidget(b_del)
        row.addStretch(1)
        row.addWidget(b_cancel)
        lay.addLayout(row)
        dlg.exec()

    def _chat_remove_selected(self):
        if self.chat_engine is None:
            return
        rows = sorted({idx.row() for idx in self.chat_docs_list.selectedIndexes()}, reverse=True)
        for r in rows:
            if 0 <= r < len(self.chat_doc_paths):
                self.chat_engine.remove_document(self.chat_doc_paths[r])
        self._refresh_chat_docs_ui()

    def _chat_clear(self, confirm: bool = True):
        if confirm and self.chat_doc_paths:
            if QMessageBox.question(self, "Nueva sesión", "¿Vaciar documentos e historial actual?") != QMessageBox.Yes:
                return
        if self.chat_engine is not None:
            self.chat_engine.clear()
        self._refresh_chat_docs_ui()
        self.chat_history_edit.clear()
        self.chat_status_lbl.setText("Sesión de chat reiniciada.")

    def _chat_send(self):
        q = self.chat_question_edit.text().strip()
        if not q:
            return
        eng = self._ensure_chat_engine()
        if not eng.documents:
            QMessageBox.warning(self, "Sin documentos", "Añade al menos un documento arriba antes de preguntar.")
            return
        if not self._ensure_models_ready():
            return
        self.chat_question_edit.clear()
        self._chat_append_message("user", "Tú", q)
        self.btn_chat_send.setEnabled(False)
        self.btn_chat_add.setEnabled(False)
        self.chat_progress.setRange(0, 0)
        resp_lang = get_llm_language_name(self.ui_lang)

        def work(cb):
            return eng.ask(q, response_lang=resp_lang, progress_cb=cb)

        def ok(res):
            ans, refs = res
            self.chat_progress.setRange(0, 100)
            self.chat_progress.setValue(100)
            self.btn_chat_send.setEnabled(True)
            self.btn_chat_add.setEnabled(True)
            self._chat_append_message("ai", "Asistente (con citas)", ans, refs=refs)
            self.chat_status_lbl.setText(f"✓ Respuesta generada citando {len(refs)} referencia(s).")
            if self.a11y.voice_guidance:
                self._speak_text(ans)

        def err(msg: str):
            self.chat_progress.setRange(0, 100)
            self.chat_progress.setValue(0)
            self.btn_chat_send.setEnabled(True)
            self.btn_chat_add.setEnabled(True)
            self.chat_status_lbl.setText(f"Error: {msg}")
            QMessageBox.critical(self, "Error en Chat", msg)

        self._run_bg(work, ok, err, self.chat_status_lbl.setText)

    def _export_turns_dialog(self, turns, fmt_label: str, default_stem: str, title: str, docs_summary=None):
        from .formats.conversation_exporter import export_conversation_with_references

        fmt_code = next((c for lbl, c in EXPORT_CONV_FORMATS if lbl == fmt_label), "docx")
        ext = ".pdf" if fmt_code == "pdfa" else f".{fmt_code}"
        chosen, _ = QFileDialog.getSaveFileName(self, f"Exportar informe ({fmt_label})", f"{default_stem}{ext}")
        if not chosen:
            return None
        return export_conversation_with_references(
            turns=turns,
            output_path=chosen,
            output_format=fmt_code,
            title=title,
            documents_summary=docs_summary,
        )

    def _chat_export_conversation(self):
        if self.chat_engine is None or not getattr(self.chat_engine, "turn_records", None):
            QMessageBox.information(self, "Sin conversación", "Realiza al menos una pregunta para exportar.")
            return
        try:
            doc_ids = self.chat_engine.get_document_id_map()
            docs_summary = [f"[{doc_ids[p]}] {fname} ({len(tree.nodos)} nodos AST)" for p, (fname, tree) in self.chat_engine.documents.items()]
            out = self._export_turns_dialog(
                turns=self.chat_engine.turn_records,
                fmt_label=self.chat_export_combo.currentText(),
                default_stem="Conversacion_Documentos_Referencias",
                title="Informe de Chat Multi-Documento y Referencias Literales — Open OCReader",
                docs_summary=docs_summary,
            )
            if out:
                self.chat_status_lbl.setText(f"✓ Exportado: {Path(out).name}")
                if QMessageBox.question(self, "Exportación completada", f"Archivo generado:\n{out}\n\n¿Abrir ahora?") == QMessageBox.Yes:
                    open_path_crossplatform(out)
        except Exception as e:
            QMessageBox.critical(self, "Error al exportar", str(e))

    # ---------------- IA LOCAL Y LECTURA FÁCIL ----------------
    def _run_ai_action(self, action: str):
        in_path = self._get_input_path()
        if not in_path or not Path(in_path).exists():
            QMessageBox.warning(self, "Aviso", "Selecciona primero un fichero de entrada arriba.")
            return
        question = self.ai_question_edit.text().strip()
        if action == "ask" and not question:
            QMessageBox.warning(self, "Pregunta vacía", "Escribe la pregunta que deseas hacer sobre el documento.")
            return
        use_hw = self.ai_hw_chk.isChecked()
        needs_llm = (action != "transcribe") or use_hw
        if needs_llm and not self._ensure_models_ready():
            return

        for b in self.ai_buttons:
            b.setEnabled(False)
        self.ai_progress.setRange(0, 0)
        self.ai_status_lbl.setText("Preparando análisis con IA local...")

        resp_lang = get_llm_language_name(self.ui_lang)
        tgt_trans = self.ai_trans_lang_combo.currentText().strip() or resp_lang
        use_focr = self.ai_force_ocr_chk.isChecked()

        def work(cb):
            from .ai import DocumentAnonymizer, DocumentQA, DocumentTranslator, LlamaRuntimeManager
            from .ai.doc_cache import DocumentIndexCache
            from .ai.doc_tree import ArbolNodosDocumento
            from .ai.multi_doc_chat import ChatReference, ChatTurnRecord

            rt = LlamaRuntimeManager.get_instance()
            ck = (in_path, use_hw, use_focr)
            mk = f"hw={int(use_hw)}_focr={int(use_focr)}"
            if self.cached_doc_key == ck and self.cached_doc_text is not None and self.cached_doc_tree is not None:
                doc_text, doc_tree = self.cached_doc_text, self.cached_doc_tree
            else:
                dc = DocumentIndexCache.get_instance()
                hit = dc.get(in_path, mode_key=mk)
                if hit is not None:
                    doc_text, doc_tree = hit
                    cb(f"✓ Recuperado desde caché AST ({len(doc_tree.nodos)} nodos, 0 ms OCR).")
                else:
                    cb("Analizando documento y extrayendo texto...")
                    doc_text, _stats = DocumentLoader.extract_text_smart(in_path, handwriting=use_hw, force_ocr=use_focr, progress_cb=cb)
                    doc_tree = ArbolNodosDocumento.construir_desde_texto(doc_text, titulo=Path(in_path).stem)
                    if len(doc_text) > 9500 and rt.tier.embed_enabled:
                        cb(f"Vectorizando {len(doc_tree.nodos)} nodos AST con {rt.tier.embed_label}...")
                        doc_tree.indexar_embeddings(lambda batch: rt.embed_texts(batch, progress_cb=cb))
                    dc.put(in_path, doc_text, doc_tree, mode_key=mk)
                self.cached_doc_text, self.cached_doc_tree, self.cached_doc_key = doc_text, doc_tree, ck

            fname = Path(in_path).name
            ts_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            turn_rec = None

            if action == "transcribe":
                out_t = doc_text
                turn_rec = ChatTurnRecord(question="Transcripción completa", answer=out_t, references=[], timestamp=ts_now)
            elif action == "summarize":
                out_t = DocumentQA(rt).summarize(doc_text, response_lang=resp_lang, progress_cb=cb, doc_tree=doc_tree)
                turn_rec = ChatTurnRecord(
                    question="Resumen ejecutivo",
                    answer=out_t,
                    references=[ChatReference("REF-1", "DOC-1", fname, "Documento fuente", 1.0, doc_text[:180], doc_text.strip()[:8000])],
                    timestamp=ts_now,
                )
            elif action == "easy_read":
                out_t = DocumentQA(rt).summarize_easy_read(doc_text, response_lang=resp_lang, progress_cb=cb, doc_tree=doc_tree)
                turn_rec = ChatTurnRecord(
                    question="Adaptación a Lectura Fácil (Norma UNE 153101 EX)",
                    answer=out_t,
                    references=[ChatReference("REF-1", "DOC-1", fname, "Documento fuente", 1.0, doc_text[:180], doc_text.strip()[:8000])],
                    timestamp=ts_now,
                )
            elif action == "translate":
                out_t = DocumentTranslator(rt).translate(doc_text, target_lang=tgt_trans, progress_cb=cb)
                turn_rec = ChatTurnRecord(
                    question=f"Traducción contextual a {tgt_trans}",
                    answer=out_t,
                    references=[ChatReference("REF-1", "DOC-1", fname, "Texto original", 1.0, doc_text[:180], doc_text.strip()[:8000])],
                    timestamp=ts_now,
                )
            elif action == "ask":
                ans, refs = DocumentQA(rt).ask_with_references(
                    doc_text, question, response_lang=resp_lang, progress_cb=cb, doc_tree=doc_tree, file_name=fname
                )
                turn_rec = ChatTurnRecord(question=question, answer=ans, references=refs, timestamp=ts_now)
                ref_lines = []
                if refs:
                    ref_lines.append("\n\n📚 REFERENCIAS LITERALES EXTRAÍDAS DEL DOCUMENTO ORIGINAL:")
                    for r in refs:
                        ref_lines.append(f"\n• [{r.doc_id} / {r.ref_id}] {r.file_name} — {r.section_path}\n«{(r.literal_text or r.excerpt).strip()}»")
                out_t = ans + "\n".join(ref_lines)
            else:
                out_t = doc_text
            return out_t, turn_rec

        def ok(payload):
            result_text, turn_rec = payload
            self.ai_progress.setRange(0, 100)
            self.ai_progress.setValue(100)
            for b in self.ai_buttons:
                b.setEnabled(True)
            if turn_rec is not None:
                self.last_ai_turn_record = turn_rec
                self.ai_turn_records.append(turn_rec)
            self.ai_output_edit.setPlainText(result_text)
            self.ai_status_lbl.setText("✓ Proceso de IA completado con éxito.")
            if self.a11y.voice_guidance:
                self._speak_text(result_text)

        def err(msg: str):
            self.ai_progress.setRange(0, 100)
            self.ai_progress.setValue(0)
            for b in self.ai_buttons:
                b.setEnabled(True)
            self.ai_status_lbl.setText(f"Error en IA: {msg}")
            self._announce(f"Error en IA: {msg}")
            QMessageBox.critical(self, "Error de IA", msg)

        self._run_bg(work, ok, err, self.ai_status_lbl.setText)

    def _show_ai_context_menu(self, pos):
        menu = self.ai_output_edit.createStandardContextMenu()
        menu.addSeparator()
        act_read = menu.addAction("🔊 Leer seleccionado / todo")
        act_stop = menu.addAction("⏹️ Detener lectura de voz")
        act = menu.exec(self.ai_output_edit.mapToGlobal(pos))
        if act == act_read:
            self._speak_active_output()
        elif act == act_stop:
            self._stop_tts()

    def _copy_ai_output(self):
        txt = self.ai_output_edit.toPlainText().strip()
        if txt:
            QApplication.clipboard().setText(txt)
            self.ai_status_lbl.setText("✓ Resultado copiado al portapapeles.")

    def _save_ai_output(self):
        txt = self.ai_output_edit.toPlainText().strip()
        if not txt:
            return
        chosen, _ = QFileDialog.getSaveFileName(self, "Guardar resultado de IA", "resultado_ia.txt", "Texto (*.txt);;Markdown (*.md)")
        if chosen:
            Path(chosen).write_text(txt, encoding="utf-8")
            self.ai_status_lbl.setText(f"✓ Guardado en: {chosen}")

    def _export_ai_output_with_refs(self):
        from .ai.multi_doc_chat import ChatTurnRecord

        content = self.ai_output_edit.toPlainText().strip()
        turns = list(self.ai_turn_records)
        if not turns and self.last_ai_turn_record is not None:
            turns = [self.last_ai_turn_record]
        if not turns and not content:
            QMessageBox.information(self, "Sin resultados", "Realiza primero una consulta, resumen o Lectura Fácil.")
            return
        if not turns and content:
            turns = [ChatTurnRecord("Resultado en pantalla", content, [], datetime.now().strftime("%Y-%m-%d %H:%M:%S"))]
        try:
            in_val = self._get_input_path()
            fname = Path(in_val).name if in_val else "Documento"
            stem = f"{Path(in_val).stem}_consulta_referencias" if in_val else "Consulta_IA_Referencias"
            out = self._export_turns_dialog(
                turns=turns,
                fmt_label=self.ai_export_combo.currentText(),
                default_stem=stem,
                title=f"Informe de Consulta e IA con Referencias Literales — {fname}",
                docs_summary=[f"[DOC-1] {fname}"] if in_val else None,
            )
            if out:
                self.ai_status_lbl.setText(f"✓ Exportado: {Path(out).name}")
                if QMessageBox.question(self, "Exportación completada", f"Archivo generado:\n{out}\n\n¿Abrir ahora?") == QMessageBox.Yes:
                    open_path_crossplatform(out)
        except Exception as e:
            QMessageBox.critical(self, "Error al exportar", str(e))

    # ---------------- ANONIMIZADOR & HERRAMIENTAS PDF ----------------
    def _run_anonymize_standalone(self):
        in_path = self._get_input_path()
        if not in_path or not Path(in_path).exists():
            QMessageBox.warning(self, "Aviso", "Selecciona primero un fichero de entrada arriba.")
            return
        use_llm = bool(self.anon_step2_rb is not None and self.anon_step2_rb.isChecked() and self.ai_tier.vlm_enabled)
        if use_llm and not self._ensure_models_ready():
            return
        mask_style = "blocks" if self.anon_mask_blocks_rb.isChecked() else "tags"
        self.btn_run_anon.setEnabled(False)
        self.anon_progress.setRange(0, 0)
        self.anon_status_lbl.setText("Extrayendo texto y aplicando anonimización RGPD...")

        def work(cb):
            from .ai.anonymizer import DocumentAnonymizer
            txt, _ = DocumentLoader.extract_text_smart(in_path, handwriting=False, force_ocr=False, progress_cb=cb)
            masked = DocumentAnonymizer().anonymize(txt, mask_style=mask_style, use_llm=use_llm, progress_cb=cb)
            return masked, ("Python + IA local" if use_llm else "100% Python determinista")

        def ok(res):
            masked, mlbl = res
            self.anon_progress.setRange(0, 100)
            self.anon_progress.setValue(100)
            self.btn_run_anon.setEnabled(True)
            self.anon_output_edit.setPlainText(masked)
            self.anon_status_lbl.setText(f"✓ Anonimización completada ({mlbl}).")
            self._announce("Anonimización completada.")

        def err(msg: str):
            self.anon_progress.setRange(0, 100)
            self.anon_progress.setValue(0)
            self.btn_run_anon.setEnabled(True)
            self.anon_status_lbl.setText(f"Error: {msg}")
            QMessageBox.critical(self, "Error al anonimizar", msg)

        self._run_bg(work, ok, err, self.anon_status_lbl.setText)

    def _copy_anon_output(self):
        txt = self.anon_output_edit.toPlainText().strip()
        if txt:
            QApplication.clipboard().setText(txt)
            self.anon_status_lbl.setText("✓ Texto anonimizado copiado.")

    def _save_anon_output(self):
        txt = self.anon_output_edit.toPlainText().strip()
        if not txt:
            return
        chosen, _ = QFileDialog.getSaveFileName(self, "Guardar documento anonimizado", "anonimizado.txt", "Texto (*.txt)")
        if chosen:
            Path(chosen).write_text(txt, encoding="utf-8")
            self.anon_status_lbl.setText(f"✓ Guardado en: {chosen}")

    def _run_pdf_tool(self, tool_action: str):
        in_path = self._get_input_path()
        if not in_path or not Path(in_path).exists():
            QMessageBox.warning(self, "Aviso", "Selecciona primero un fichero PDF arriba.")
            return
        if Path(in_path).suffix.lower() != ".pdf":
            QMessageBox.warning(self, "Solo PDF", "Las herramientas de esta pestaña operan sobre PDF (.pdf).")
            return
        for b in self.pdf_tool_buttons:
            b.setEnabled(False)
        self.btn_pdf_open_file.setEnabled(False)
        self.btn_pdf_open_folder.setEnabled(False)
        self.pdf_tools_progress.setRange(0, 0)
        self.pdf_tools_status_lbl.setText("Procesando PDF...")

        pw = self.pdf_pw_edit.text()
        wm_txt = self.wm_text_edit.text()
        wm_ann = self.wm_annots_chk.isChecked()
        wm_scan = self.wm_scan_chk.isChecked()
        comp = self._get_compression_code(self.pdf_opt_comp_combo.currentText())
        gray = self.pdf_opt_gray_chk.isChecked()
        pdfa = self.pdf_opt_pdfa_chk.isChecked()

        def work(_cb):
            from .pdf_tools import optimize_pdf, remove_signatures, remove_watermarks, unlock_pdf
            if tool_action == "unlock":
                return unlock_pdf(in_path, password=pw)
            if tool_action == "signatures":
                return remove_signatures(in_path)
            if tool_action == "watermarks":
                return remove_watermarks(in_path, watermark_text=wm_txt, remove_annotations=wm_ann, remove_ocg=wm_ann, clean_scan_watermark=wm_scan)
            if tool_action == "optimize":
                return optimize_pdf(in_path, compression=comp, grayscale=gray, pdfa=pdfa)
            raise ValueError(f"Acción desconocida: {tool_action}")

        def ok(res):
            self.pdf_tools_progress.setRange(0, 100)
            self.pdf_tools_progress.setValue(100)
            for b in self.pdf_tool_buttons:
                b.setEnabled(True)
            self.last_pdf_tool_file = res["output_path"]
            self.btn_pdf_open_file.setEnabled(True)
            self.btn_pdf_open_folder.setEnabled(True)
            self.pdf_tools_status_lbl.setText(f"✓ {res['message']}")
            self._announce(res["message"])
            QMessageBox.information(self, "Operación completada", res["message"])

        def err(msg: str):
            self.pdf_tools_progress.setRange(0, 100)
            self.pdf_tools_progress.setValue(0)
            for b in self.pdf_tool_buttons:
                b.setEnabled(True)
            self.pdf_tools_status_lbl.setText(f"Error: {msg}")
            QMessageBox.critical(self, "Error en Herramienta PDF", msg)

        self._run_bg(work, ok, err)

    # ---------------- ACCESIBILIDAD, VOZ Y MODALES ----------------
    def _on_tab_changed(self, idx: int):
        if self._ui_ready and self.a11y.voice_guidance and 0 <= idx < self.tabs.count():
            self._announce(f"Pestaña {self.tabs.tabText(idx).strip()}")

    def _announce(self, text: str):
        if self._ui_ready and self.a11y.voice_guidance and text:
            self.tts.speak(text, rate=self.a11y.tts_rate)

    def _speak_text(self, text: str):
        if text:
            self._tts_speaking_active = True
            self.tts.speak(text, rate=self.a11y.tts_rate)

    def _stop_tts(self):
        self._tts_speaking_active = False
        self.tts.stop()

    def _speak_active_output(self):
        for attr in ("ai_output_edit", "chat_history_edit", "anon_output_edit"):
            ed = getattr(self, attr, None)
            if ed is not None and ed.textCursor().hasSelection():
                sel = ed.textCursor().selectedText().strip()
                if sel:
                    self._speak_text(sel)
                    return
        cur = self.tabs.currentWidget()
        if cur is self.tab_chat:
            if self.chat_engine and getattr(self.chat_engine, "turn_records", None):
                self._speak_text(self.chat_engine.turn_records[-1].answer)
                return
            if hasattr(self, "chat_status_lbl"):
                self._speak_text(self.chat_status_lbl.text())
                return
        if cur is self.tab_ai and hasattr(self, "ai_output_edit"):
            self._speak_text(self.ai_output_edit.toPlainText().strip() or self.ai_status_lbl.text())
            return
        if cur is self.tab_anonymize:
            self._speak_text(self.anon_output_edit.toPlainText().strip() or self.anon_status_lbl.text())
            return
        if cur is self.tab_translate and hasattr(self, "trans_status_lbl"):
            self._speak_text(self.trans_status_lbl.text())
            return
        if self.tab_pdf_tools is not None and cur is self.tab_pdf_tools:
            self._speak_text(self.pdf_tools_status_lbl.text())
            return
        self._speak_text(self.conv_status_lbl.text())

    def _toggle_tts_active_tab(self):
        if self._tts_speaking_active:
            self._stop_tts()
        else:
            self._speak_active_output()

    def _toggle_high_contrast(self):
        if self.a11y.theme_mode == "high_contrast_dark":
            self.a11y.theme_mode = "auto"
            msg = "Tema visual restaurado a automático."
        else:
            self.a11y.theme_mode = "high_contrast_dark"
            msg = "Alto contraste WCAG AAA activado."
        self._apply_theme_and_fonts()
        self.conv_status_lbl.setText(msg)
        self._announce(msg)

    def _trigger_primary_action(self):
        cur = self.tabs.currentWidget()
        if cur is self.tab_convert:
            self._start_conversion()
        elif cur is self.tab_translate and hasattr(self, "btn_translate_doc"):
            self._start_document_translation()
        elif cur is self.tab_chat and hasattr(self, "btn_chat_send"):
            self._chat_send()
        elif cur is self.tab_ai and hasattr(self, "ai_question_edit"):
            if self.ai_question_edit.text().strip():
                self._run_ai_action("ask")
            else:
                self._run_ai_action("summarize")
        elif cur is self.tab_anonymize:
            self._run_anonymize_standalone()

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl++"), self, activated=lambda: self._adjust_global_zoom(1))
        QShortcut(QKeySequence("Ctrl+="), self, activated=lambda: self._adjust_global_zoom(1))
        QShortcut(QKeySequence("Ctrl+-"), self, activated=lambda: self._adjust_global_zoom(-1))
        QShortcut(QKeySequence("Ctrl+0"), self, activated=self._reset_global_zoom)
        QShortcut(QKeySequence("F2"), self, activated=self._open_accessibility_dialog)
        QShortcut(QKeySequence("Alt+A"), self, activated=self._open_accessibility_dialog)
        QShortcut(QKeySequence("Ctrl+Shift+L"), self, activated=self._toggle_tts_active_tab)
        QShortcut(QKeySequence("Ctrl+Shift+H"), self, activated=self._toggle_high_contrast)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self._browse_input)
        QShortcut(QKeySequence("Ctrl+V"), self, activated=self._paste_from_clipboard)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._trigger_primary_action)
        for i in range(1, 7):
            QShortcut(QKeySequence(f"Alt+{i}"), self, activated=lambda idx=i - 1: idx < self.tabs.count() and self.tabs.setCurrentIndex(idx))

    def _open_accessibility_dialog(self):
        if self._a11y_dlg is not None and self._a11y_dlg.isVisible():
            self._a11y_dlg.raise_()
            self._a11y_dlg.activateWindow()
            return

        dlg = QDialog(self)
        self._a11y_dlg = dlg
        dlg.setWindowTitle("♿ Centro de Accesibilidad Universal — Open OCReader")
        dlg.resize(740, 620)
        dlg_lay = QVBoxLayout(dlg)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setObjectName("scrollContent")
        bl = QVBoxLayout(body)
        scroll.setWidget(body)
        dlg_lay.addWidget(scroll, 1)

        head = QLabel("♿ Adaptabilidad Universal (Visión, Cognición, Audición y Motricidad)")
        head.setProperty("role", "accent")
        head.setWordWrap(True)
        bl.addWidget(head)

        theme_cb = QComboBox()
        for k in VALID_THEME_MODES:
            theme_cb.addItem(THEME_DISPLAY_LABELS[k], k)
        chk_dys = QCheckBox("Tipografía amiga para dislexia (OpenDyslexic si instalada / Verdana + interlineado amplio)")
        chk_voice = QCheckBox("Activar guía de voz automática (anuncia pestañas, archivos cargados y resultados)")
        chk_large = QCheckBox("Ampliar áreas clicables y foco (botones y pestañas anti-temblor)")

        rb_slow = QRadioButton("Lenta (-2)")
        rb_norm = QRadioButton("Normal (0)")
        rb_fast = QRadioButton("Rápida (+2)")
        rate_grp = QButtonGroup(dlg)
        for rb in (rb_slow, rb_norm, rb_fast):
            rate_grp.addButton(rb)

        btn_zoom_lbl = QPushButton(f"{self.a11y.zoom_percent}%")
        btn_zoom_lbl.clicked.connect(lambda: (self._reset_global_zoom(), sync_from_cfg()))

        def sync_from_cfg():
            idx = max(0, theme_cb.findData(self.a11y.theme_mode))
            theme_cb.blockSignals(True)
            theme_cb.setCurrentIndex(idx)
            theme_cb.blockSignals(False)
            for chk, val in ((chk_dys, self.a11y.dyslexia_friendly), (chk_voice, self.a11y.voice_guidance), (chk_large, self.a11y.large_targets)):
                chk.blockSignals(True)
                chk.setChecked(val)
                chk.blockSignals(False)
            for rb, target in ((rb_slow, -2), (rb_norm, 0), (rb_fast, 2)):
                rb.setChecked(self.a11y.tts_rate == target)
            btn_zoom_lbl.setText(f"{self.a11y.zoom_percent}%")

        def apply_controls(announce: Optional[str] = None):
            self.a11y.theme_mode = theme_cb.currentData() or "auto"
            self.a11y.dyslexia_friendly = chk_dys.isChecked()
            self.a11y.voice_guidance = chk_voice.isChecked()
            self.a11y.large_targets = chk_large.isChecked()
            self.a11y.tts_rate = -2 if rb_slow.isChecked() else (2 if rb_fast.isChecked() else 0)
            self._apply_theme_and_fonts()
            dlg.setStyleSheet(self.styleSheet())
            btn_zoom_lbl.setText(f"{self.a11y.zoom_percent}%")
            if announce:
                self._speak_text(announce)

        def apply_preset(preset: str):
            msg = None
            if preset == "standard":
                self.a11y.ui_font_size, self.a11y.text_font_size = 10, 11
                self.a11y.theme_mode, self.a11y.dyslexia_friendly, self.a11y.large_targets, self.a11y.voice_guidance = "auto", False, False, False
                self.a11y.tts_rate = 0
            elif preset == "low_vision":
                self.a11y.ui_font_size, self.a11y.text_font_size = 14, 16
                self.a11y.theme_mode, self.a11y.large_targets = "high_contrast_dark", True
                msg = "Perfil de baja visión activado: texto al 140% y alto contraste oscuro."
            elif preset == "screen_reader":
                self.a11y.voice_guidance, self.a11y.large_targets, self.a11y.tts_rate = True, True, 0
                msg = "Guía de voz local activada. Alt 1 a 6 para cambiar pestaña y Control Shift L para leer."
            elif preset == "dyslexia":
                self.a11y.theme_mode, self.a11y.dyslexia_friendly = "dyslexia_cream", True
                self.a11y.ui_font_size, self.a11y.text_font_size = 12, 13
            elif preset == "motor":
                self.a11y.large_targets = True
                self.a11y.ui_font_size = max(12, self.a11y.ui_font_size)
                self.a11y.text_font_size = max(13, self.a11y.text_font_size)
            sync_from_cfg()
            apply_controls(announce=msg)

        p_box = QGroupBox(" ⚡ Perfiles Rápidos en 1 Clic ")
        pf = FlowLayout(p_box, margin=8, h_spacing=6, v_spacing=6)
        for label, code in (
            ("🖥️ Estándar (100%)", "standard"),
            ("👁️ Baja Visión (140% + AAA)", "low_vision"),
            ("🦯 Voz y Ceguera (TTS)", "screen_reader"),
            ("📖 Dislexia / Crema Cálida", "dyslexia"),
            ("🖐️ Botones Grandes / Motriz", "motor"),
        ):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, p_code=code: apply_preset(p_code))
            pf.addWidget(b)
        bl.addWidget(p_box)

        v_box = QGroupBox(" 🎨 Visión, Contraste (WCAG AAA) y Escala Global ")
        vl = QVBoxLayout(v_box)
        tr_w = QWidget()
        tr_f = FlowLayout(tr_w, h_spacing=8, v_spacing=4)
        tr_f.addWidget(QLabel("Perfil cromático:"))
        theme_cb.currentIndexChanged.connect(lambda: apply_controls())
        tr_f.addWidget(theme_cb)
        vl.addWidget(tr_w)

        zr_w = QWidget()
        zr_f = FlowLayout(zr_w, h_spacing=6, v_spacing=4)
        zr_f.addWidget(QLabel("Tamaño global de interfaz y textos:"))
        b_dec = QPushButton("➖ Reducir (A-)")
        b_dec.clicked.connect(lambda: (self._adjust_global_zoom(-1), sync_from_cfg()))
        b_inc = QPushButton("➕ Ampliar (A+)")
        b_inc.clicked.connect(lambda: (self._adjust_global_zoom(1), sync_from_cfg()))
        for w in (b_dec, btn_zoom_lbl, b_inc):
            zr_f.addWidget(w)
        vl.addWidget(zr_w)
        bl.addWidget(v_box)

        c_box = QGroupBox(" 📖 Accesibilidad Cognitiva y Dislexia ")
        cl = QVBoxLayout(c_box)
        chk_dys.toggled.connect(lambda: apply_controls())
        cl.addWidget(chk_dys)
        c_tip = QLabel("En la pestaña 'IA y Visión' tienes el botón '♿ Lectura Fácil' basado en la norma UNE 153101 EX.")
        c_tip.setProperty("role", "accent_italic")
        c_tip.setWordWrap(True)
        cl.addWidget(c_tip)
        bl.addWidget(c_box)

        t_box = QGroupBox(" 🔊 Lectura en Voz Alta Local (TTS Offline — Sin Nube) ")
        tl = QVBoxLayout(t_box)
        chk_voice.toggled.connect(lambda: apply_controls())
        tl.addWidget(chk_voice)
        rf_w = QWidget()
        rf = FlowLayout(rf_w, h_spacing=8, v_spacing=4)
        rf.addWidget(QLabel("Velocidad:"))
        for rb in (rb_slow, rb_norm, rb_fast):
            rb.toggled.connect(lambda c: c and apply_controls())
            rf.addWidget(rb)
        b_test = QPushButton("🔊 Probar lectura")
        b_test.clicked.connect(lambda: self._speak_text("Open OCReader. Lector de voz local operativo con privacidad del cien por cien."))
        b_stop = QPushButton("⏹️ Detener voz")
        b_stop.clicked.connect(self._stop_tts)
        rf.addWidget(b_test)
        rf.addWidget(b_stop)
        tl.addWidget(rf_w)
        bl.addWidget(t_box)

        m_box = QGroupBox(" 🖐️ Motricidad y Atajos Universales de Teclado ")
        ml = QVBoxLayout(m_box)
        chk_large.toggled.connect(lambda: apply_controls())
        ml.addWidget(chk_large)
        sc_lbl = QLabel(
            "Alt+1..6: Cambiar pestaña  |  Alt+A / F2: Accesibilidad  |  Ctrl++/Ctrl+-/Ctrl+0: Zoom global\n"
            "Ctrl+Shift+L: Leer/Detener voz  |  Ctrl+Shift+H: Alto Contraste AAA  |  Ctrl+O: Abrir fichero  |  Ctrl+Enter: Ejecutar"
        )
        sc_lbl.setProperty("role", "muted")
        sc_lbl.setWordWrap(True)
        ml.addWidget(sc_lbl)
        bl.addWidget(m_box)
        bl.addStretch(1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        b_close = QPushButton("Cerrar y Guardar")
        b_close.clicked.connect(dlg.accept)
        foot.addWidget(b_close)
        dlg_lay.addLayout(foot)

        sync_from_cfg()
        dlg.setStyleSheet(self.styleSheet())
        dlg.show()

    def _show_legal_compliance(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Cumplimiento Normativo de IA, Créditos GuarIdA y Licencia Libre — Open OCReader")
        dlg.resize(740, 600)
        dlg.setStyleSheet(self.styleSheet())
        lay = QVBoxLayout(dlg)
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(LEGAL_COMPLIANCE_TEXT)
        lay.addWidget(txt, 1)

        bar = QHBoxLayout()
        b_gov = QPushButton("📑 Generar Informe de Gobernanza IA (1 clic)")
        b_gov.clicked.connect(lambda: self._export_governance_report(dlg))
        b_gua = QPushButton("🛡️ Conocer mi proyecto GuarIdA (GitHub)")
        b_gua.clicked.connect(lambda: webbrowser.open(GUARIDA_REPO_URL))
        b_tts = QPushButton("🔊 Leer")
        b_tts.clicked.connect(lambda: self._speak_text(LEGAL_COMPLIANCE_TEXT))
        b_cls = QPushButton("Cerrar")
        b_cls.clicked.connect(dlg.accept)
        for w in (b_gov, b_gua, b_tts):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(b_cls)
        lay.addLayout(bar)
        dlg.exec()

    def _export_governance_report(self, parent_dlg=None):
        chosen, _ = QFileDialog.getSaveFileName(
            parent_dlg or self,
            "Guardar Informe de Gobernanza de IA y ENS",
            "Informe_Gobernanza_IA_OpenOCReader.docx",
            "Word (*.docx);;Markdown (*.md);;JSON (*.json)",
        )
        if not chosen:
            return
        try:
            from .governance import generate_governance_report
            out_p = generate_governance_report(chosen)
            self.conv_status_lbl.setText(f"✓ Informe de gobernanza generado en: {out_p}")
            if QMessageBox.question(parent_dlg or self, "Informe generado", f"Guardado:\n{out_p}\n\n¿Abrir ahora?") == QMessageBox.Yes:
                open_path_crossplatform(out_p)
        except Exception as e:
            QMessageBox.critical(parent_dlg or self, "Error", str(e))

    def _clear_cache_gui(self):
        from .maintenance import clear_cache
        self.cached_doc_text = None
        self.cached_doc_key = None
        res = clear_cache()
        self.conv_status_lbl.setText(f"✓ Caché limpiada ({res['deleted']} elementos eliminados).")
        QMessageBox.information(self, "Caché limpiada", f"Se han eliminado {res['deleted']} elementos temporales y de caché.")

    def _clear_logs_gui(self):
        if QMessageBox.question(self, "Borrar Logs", "¿Deseas vaciar todos los archivos de registro (logs)?") != QMessageBox.Yes:
            return
        from .maintenance import clear_logs
        res = clear_logs()
        self.conv_status_lbl.setText("✓ Logs limpiados correctamente.")
        QMessageBox.information(self, "Logs limpiados", f"Truncados: {res['truncated']} | Eliminados: {res['removed']}")

    def _open_logs(self):
        logs_dir = get_logs_dir()
        log_file = logs_dir / "open_ocreader.log"
        open_path_crossplatform(str(log_file if log_file.exists() else logs_dir))

    def _check_updates_gui(self):
        from . import __version__
        from .ai import LlamaRuntimeManager
        from .updater import apply_update, check_for_updates

        self.conv_status_lbl.setText("Consultando actualizaciones en GitHub...")

        def work(_cb):
            return check_for_updates(__version__), LlamaRuntimeManager.get_instance().check_llama_update()

        def ok(res):
            info, llama_info = res
            llama_msg = (
                f"Motor llama.cpp: '{llama_info['installed']}' → '{llama_info['latest']}' disponible."
                if llama_info["update_available"]
                else f"Motor llama.cpp: al día ({llama_info['latest']})."
            )
            self.conv_status_lbl.setText(f"{info.message} | {llama_msg}")
            if info.update_available or llama_info["update_available"]:
                if QMessageBox.question(self, "Actualización disponible", f"{info.message}\n{llama_msg}\n\n¿Actualizar ahora?") == QMessageBox.Yes:
                    msgs = []
                    if info.update_available:
                        msgs.append(apply_update())
                    if llama_info["update_available"]:
                        from .maintenance import clean_and_reinstall
                        clean_and_reinstall(clean_builds=False, reinstall_llama=True, reinstall_models=False, upgrade_deps=False)
                        msgs.append(f"✓ llama.cpp actualizado a {llama_info['latest']}.")
                    QMessageBox.information(self, "Actualizado", "\n".join(msgs))
            else:
                QMessageBox.information(self, "Actualizaciones", f"{info.message}\n\n{llama_msg}")

        self._run_bg(work, ok, lambda m: QMessageBox.warning(self, "Aviso", m))

    def _open_clean_reinstall_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Limpiar Proyecto y Reinstalar Componentes")
        dlg.resize(520, 320)
        dlg.setStyleSheet(self.styleSheet())
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Selecciona qué deseas limpiar y reinstalar:"))
        cb_b = QCheckBox("Eliminar compilaciones antiguas (build/, dist/, *.spec) y cachés")
        cb_b.setChecked(True)
        cb_l = QCheckBox("Reinstalar última versión oficial de llama.cpp (bin/)")
        cb_l.setChecked(True)
        cb_d = QCheckBox("Actualizar librerías Python (requirements.txt)")
        cb_d.setChecked(True)
        cb_m = QCheckBox("Re-descargar y verificar modelos de IA (models/ ~2,9 GB)")
        for w in (cb_b, cb_l, cb_d, cb_m):
            lay.addWidget(w)
        st = QLabel("Listo para limpiar y reinstalar.")
        st.setWordWrap(True)
        lay.addWidget(st)
        row = QHBoxLayout()
        b_go = QPushButton("♻️ Ejecutar limpieza y reinstalación")
        b_cls = QPushButton("Cancelar")
        b_cls.clicked.connect(dlg.reject)
        row.addWidget(b_go)
        row.addStretch(1)
        row.addWidget(b_cls)
        lay.addLayout(row)

        def go():
            b_go.setEnabled(False)
            from .maintenance import clean_and_reinstall

            self._run_bg(
                lambda cb: clean_and_reinstall(
                    clean_builds=cb_b.isChecked(),
                    reinstall_llama=cb_l.isChecked(),
                    reinstall_models=cb_m.isChecked(),
                    upgrade_deps=cb_d.isChecked(),
                    progress_cb=cb,
                ),
                lambda res: (
                    QMessageBox.information(dlg, "Completado", f"Eliminado: {res['removed']}\nActualizado: {res['updated']}"),
                    dlg.accept(),
                ),
                lambda m: (b_go.setEnabled(True), QMessageBox.critical(dlg, "Error", m)),
                st.setText,
            )

        b_go.clicked.connect(go)
        dlg.exec()

    def closeEvent(self, event):
        try:
            self.tts.stop()
        except Exception:
            pass
        try:
            from .ai import LlamaRuntimeManager
            LlamaRuntimeManager.get_instance().stop_server()
        except Exception:
            pass
        super().closeEvent(event)


def launch_gui_qt():
    """Inicia la interfaz gráfica nativa en Qt 6 (PySide6) en modo de instancia única."""
    app = QApplication.instance() or QApplication(sys.argv)

    lock_handle = acquire_single_instance_lock()
    if lock_handle is None:
        focus_existing_window_windows()
        QMessageBox.information(
            None,
            "Open OCReader ya está abierto",
            "Ya hay una instancia de Open OCReader en ejecución.\n"
            "Se ha activado el modo de instancia única para evitar conflictos con el motor de IA y los logs.",
        )
        return

    def _cleanup():
        try:
            from .ai import LlamaRuntimeManager
            LlamaRuntimeManager.get_instance().stop_server()
        except Exception:
            pass
        release_single_instance_lock(lock_handle)

    atexit.register(_cleanup)

    window = OpenOCReaderQtWindow()
    window.show()
    app.exec()
