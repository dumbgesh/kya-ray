"""
desktop/ui/components.py - Reusable PySide6 UI components for Kya-Ray.

Matched to reference design:
- IntentBadge: Royal blue uppercase pill badge (EXPLAIN, SUMMARY, CODE, CREATE) on soft blue background.
- CopyButton: Clean 32x32px rounded square icon button with copy icon / checkmark state.
- ResizeGripHandle: Clean 32x32px rounded square size grip with 3x3 dot matrix.
- LoadingIndicator: Clean subtle thinking indicator.
- SourceTextCard: Preserved for API and backward compatibility.
"""

from typing import Optional, Callable
from PySide6.QtCore import Qt, Signal, QTimer, QRectF, QPointF, QSize
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
    QApplication,
)

from desktop.utils.clipboard import set_clipboard_text
from desktop.utils.config import INTENT_DISPLAY_LABELS


class IntentBadge(QLabel):
    """A pill-shaped badge displaying the detected intent in uppercase royal blue."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("", parent)
        self.setObjectName("intentBadge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(22)
        self._intent_raw = ""
        self.setVisible(False)

    def set_intent(self, intent_key: str):
        label = INTENT_DISPLAY_LABELS.get(intent_key, "")
        self._intent_raw = label
        if label:
            super().setText(label)  # Keeps "Explain", "Code", etc. for test assertions
            self.setVisible(True)
            self.updateGeometry()
            self.update()
        else:
            super().setText("")
            self.setVisible(False)

    def sizeHint(self) -> QSize:
        text = (self._intent_raw or self.text()).upper()
        if not text:
            return super().sizeHint()
        font = self.font()
        font.setPixelSize(11)
        font.setBold(True)
        fm = QFontMetrics(font)
        text_width = fm.horizontalAdvance(text)
        return QSize(text_width + 20, 22)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        # Draw pill background
        painter.setPen(QPen(QColor("#D2E3FC"), 1))
        painter.setBrush(QBrush(QColor("#EBF2FF")))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 10, 10)

        # Draw uppercase text matching reference
        display_text = (self._intent_raw or self.text()).upper()
        if display_text:
            painter.setPen(QColor("#2563EB"))
            font = self.font()
            font.setPixelSize(11)
            font.setBold(True)
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, display_text)


class SourceTextCard(QFrame):
    """Displays a preview of the selected text captured from the user's screen."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("sourceCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        self._prefix_label = QLabel("SELECTED", self)
        self._prefix_label.setObjectName("sourcePrefix")

        self._text_label = QLabel("", self)
        self._text_label.setObjectName("sourceSnippet")
        self._text_label.setWordWrap(True)

        layout.addWidget(self._prefix_label)
        layout.addWidget(self._text_label)

    def set_text(self, text: str):
        cleaned = text.strip() if text else ""
        if len(cleaned) > 160:
            preview = cleaned[:157] + "..."
        else:
            preview = cleaned

        self._text_label.setText(preview)
        self.setVisible(bool(cleaned))


class CopyButton(QPushButton):
    """Copy button rendered as a clean 32x32 icon button matching the reference."""

    def __init__(self, get_text_callback: Optional[Callable[[], str]] = None, parent: Optional[QWidget] = None):
        super().__init__("Copy", parent)
        self.setObjectName("actionButton")
        self.setToolTip("Copy response")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("copied", "false")
        self.setFixedSize(32, 32)
        self.get_text_callback = get_text_callback
        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.timeout.connect(self._reset_state)
        self.clicked.connect(self._handle_copy)

    def _handle_copy(self):
        text_to_copy = self.get_text_callback() if self.get_text_callback else ""
        if text_to_copy:
            set_clipboard_text(text_to_copy)
            app = QApplication.instance()
            if app:
                app.processEvents()

            self.setText("✓ Copied!")
            self.setProperty("copied", "true")
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()
            self._reset_timer.start(1500)

    def _reset_state(self):
        self.setText("Copy")
        self.setProperty("copied", "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        is_copied = (self.property("copied") == "true")
        is_hovered = self.underMouse()
        is_pressed = self.isDown()

        # Background and border styling
        if is_copied:
            bg_color = QColor("#E6F4EA")
            border_color = QColor("#A7F3D0")
        elif is_pressed:
            bg_color = QColor("#D1D5DB")
            border_color = QColor("#9CA3AF")
        elif is_hovered:
            bg_color = QColor("#E5E7EB")
            border_color = QColor("#D1D5DB")
        else:
            bg_color = QColor("#F3F4F6")
            border_color = QColor("#E5E7EB")

        rect = self.rect()
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 8, 8)

        if is_copied:
            # Draw green checkmark
            painter.setPen(QPen(QColor("#10B981"), 2))
            cx = rect.center().x()
            cy = rect.center().y()
            p1 = QPointF(cx - 5, cy)
            p2 = QPointF(cx - 1, cy + 4)
            p3 = QPointF(cx + 5, cy - 4)
            painter.drawLine(p1, p2)
            painter.drawLine(p2, p3)
        else:
            # Draw copy icon (overlapping rounded rectangles)
            icon_color = QColor("#4B5563")
            painter.setPen(QPen(icon_color, 1.4))
            painter.setBrush(Qt.BrushStyle.NoBrush)

            # Rear rectangle
            painter.drawRoundedRect(QRectF(13, 9, 10, 10), 2, 2)
            # Front rectangle
            painter.setBrush(QBrush(bg_color))
            painter.drawRoundedRect(QRectF(9, 13, 10, 10), 2, 2)


class ResizeGripHandle(QSizeGrip):
    """Clean 32x32 drag/resize handle showing a 3x3 dot grid matching reference."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("gripHandle")
        self.setToolTip("Resize")
        self.setFixedSize(32, 32)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        is_hovered = self.underMouse()
        bg_color = QColor("#E5E7EB") if is_hovered else QColor("#F3F4F6")
        border_color = QColor("#D1D5DB") if is_hovered else QColor("#E5E7EB")

        rect = self.rect()
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 8, 8)

        # Draw 3x3 dots grid
        dot_color = QColor("#8C93A0")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(dot_color))

        center_x = rect.center().x()
        center_y = rect.center().y()
        spacing = 4
        dot_radius = 1.25

        for row in (-1, 0, 1):
            for col in (-1, 0, 1):
                dx = center_x + col * spacing
                dy = center_y + row * spacing
                painter.drawEllipse(QPointF(dx, dy), dot_radius, dot_radius)


class LoadingIndicator(QLabel):
    """Subtle thinking state indicator."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("", parent)
        self.setObjectName("loadingIndicator")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._step = 0
        self._timer = QTimer(self)
        self._timer.setInterval(320)
        self._timer.timeout.connect(self._update_dots)
        self.setVisible(False)
        self.setStyleSheet(
            "font-size: 13px; font-weight: 500; color: #6B7280; padding: 12px 0px;"
        )

    def start(self):
        self._step = 0
        self.setText("Thinking...")
        self.setVisible(True)
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self.setVisible(False)

    def _update_dots(self):
        dots = ["Thinking.", "Thinking..", "Thinking..."]
        self.setText(dots[self._step % len(dots)])
        self._step += 1
