"""
desktop/ui/bubble.py - Main PySide6 Assistant Floating Bubble Window.

Matched to reference design:
- Outer floating window: Soft light grey (#F0F1F4) with rounded corners (16px).
- Inner content panel: Pure white (#FFFFFF) with subtle grey border (#E2E4E9) and rounded corners (12px).
- Full width horizontal dividers below header and above footer.
- Flush vertical alignment across Title, Response content, and Footer status label.
- Dynamic window height:
  * Short responses: Shrinks vertically to fit (~220-260px), removing empty space.
  * Medium responses: Expands naturally as content grows.
  * Long responses: Caps at ~70% screen height, making content scrollable while header & footer remain visible.
  * Streaming: Controlled, throttled resizing (80ms) to eliminate flickering/jitter.
- Preserved Step 10 Run-ID protection and reliability safeguards.
"""

import sys
from typing import Optional

from PySide6.QtCore import QPoint, QSize, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from desktop.ui.components import (
    CopyButton,
    IntentBadge,
    LoadingIndicator,
    ResizeGripHandle,
)
from desktop.ui.styles import LIGHT_THEME_QSS, PALETTE
from desktop.utils.config import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MAX_WINDOW_HEIGHT,
    MAX_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    get_mouse_position,
)

BROWSER_DEFAULT_STYLESHEET = """
body, p {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 13.5px;
    line-height: 1.55;
    color: #374151;
    margin-top: 0px;
    margin-bottom: 8px;
    padding: 0px;
}
h1, h2, h3, h4 {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #111827;
    font-weight: 700;
    margin-top: 0px;
    margin-bottom: 10px;
    padding: 0px;
}
h1 { font-size: 17px; }
h2 { font-size: 16px; }
h3 { font-size: 15px; }
h4 { font-size: 14px; }
code {
    font-family: "Cascadia Code", Consolas, Menlo, Monaco, "Courier New", monospace;
    font-size: 12.5px;
    background-color: #F1F3F5;
    color: #1F2937;
    border-radius: 3px;
    padding: 1px 4px;
}
pre {
    font-family: "Cascadia Code", Consolas, Menlo, Monaco, "Courier New", monospace;
    font-size: 12.5px;
    background-color: #F8F9FA;
    border: 1px solid #E5E7EB;
    border-radius: 6px;
    padding: 8px 10px;
    color: #1F2937;
    margin: 6px 0px;
    white-space: pre-wrap;
    word-wrap: break-word;
}
ul, ol {
    margin-left: 18px;
    margin-top: 4px;
    margin-bottom: 8px;
    color: #374151;
}
li {
    margin-bottom: 4px;
    font-size: 13.5px;
    line-height: 1.5;
}
blockquote {
    margin: 8px 0px;
    padding-left: 12px;
    border-left: 3px solid #2563EB;
    color: #4B5563;
    font-style: italic;
}
table {
    border-collapse: collapse;
    margin: 8px 0px;
    width: 100%;
}
th, td {
    border: 1px solid #E5E7EB;
    padding: 5px 8px;
    font-size: 13px;
    text-align: left;
}
th {
    background-color: #F9FAFB;
    font-weight: 600;
    color: #111827;
}
hr {
    border: none;
    background-color: #E5E7EB;
    height: 1px;
    margin: 10px 0px;
}
a {
    color: #2563EB;
    text-decoration: none;
}
a:hover {
    text-decoration: underline;
}
"""


class ResponseBrowser(QTextBrowser):
    """QTextBrowser subclass with dynamic sizeHint reflecting actual document height."""

    def sizeHint(self) -> QSize:
        doc = self.document()
        vp_w = self.viewport().width() if self.viewport() else 540
        if vp_w < 50:
            vp_w = 540
        doc.setTextWidth(vp_w)
        doc_h = int(doc.documentLayout().documentSize().height())
        return QSize(vp_w, max(24, doc_h + 4))


class AssistantBubbleWindow(QWidget):
    """
    Floating assistant window displayed upon shortcut activation.
    Renders selected text context, active intent, and the generated response.
    """

    dismissed = Signal()
    exit_requested = Signal()
    setup_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        # Frameless, floating on-top tool window
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(LIGHT_THEME_QSS)

        self._drag_pos = QPoint()
        self._current_text = ""
        self._current_response = ""
        self._current_intent = "-explain"
        self._active_run_id: Optional[int] = None
        self._dismissed: bool = False

        # Anti-flicker throttle timer for streaming resize updates (80ms)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(80)
        self._resize_timer.timeout.connect(self.adjust_window_height)

        self._setup_ui()
        self.resize(DEFAULT_WINDOW_WIDTH, 230)
        self.setMinimumSize(MIN_WINDOW_WIDTH, 200)

        # Escape and Ctrl+W shortcuts
        self._esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._esc_shortcut.activated.connect(self.dismiss)

        self._close_shortcut = QShortcut(QKeySequence("Ctrl+W"), self)
        self._close_shortcut.activated.connect(self.dismiss)

    def _setup_ui(self):
        # Outer transparent layout accommodating the drop shadow
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(0)

        # 1. Outer Container Frame (Light grey #F0F1F4, rounded corners 16px)
        self.container = QFrame(self)
        self.container.setObjectName("containerFrame")

        # Soft floating elevation drop shadow
        shadow = QGraphicsDropShadowEffect(self.container)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 35))
        shadow.setOffset(0, 4)
        self.container.setGraphicsEffect(shadow)

        outer_container_layout = QVBoxLayout(self.container)
        outer_container_layout.setContentsMargins(12, 12, 12, 12)
        outer_container_layout.setSpacing(0)

        # 2. Inner Content Card (Pure white #FFFFFF, subtle border #E2E4E9, rounded corners 12px)
        self.inner_card = QFrame(self.container)
        self.inner_card.setObjectName("innerCard")

        # Vertical layout with 0 margins so dividers can span edge-to-edge
        card_layout = QVBoxLayout(self.inner_card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # --- Header Section ---
        self.header_frame = QFrame(self.inner_card)
        self.header_frame.setObjectName("headerBar")
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(20, 14, 20, 10)
        header_layout.setSpacing(8)

        self.title_label = QLabel("Kya-Ray", self.header_frame)
        self.title_label.setObjectName("titleLabel")

        self.intent_badge = IntentBadge(self.header_frame)

        self.minimize_btn = QPushButton("—", self.header_frame)
        self.minimize_btn.setObjectName("minimizeButton")
        self.minimize_btn.setToolTip("Minimize")
        self.minimize_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.minimize_btn.clicked.connect(self.dismiss)

        self.close_btn = QPushButton("✕", self.header_frame)
        self.close_btn.setObjectName("closeButton")
        self.close_btn.setToolTip("Dismiss (Esc)")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.dismiss)

        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.intent_badge)
        header_layout.addWidget(self.minimize_btn)
        header_layout.addWidget(self.close_btn)
        card_layout.addWidget(self.header_frame)

        # Top Horizontal Divider (spans edge-to-edge of inner card)
        header_divider = QFrame(self.inner_card)
        header_divider.setObjectName("divider")
        header_divider.setFixedHeight(1)
        card_layout.addWidget(header_divider)

        # --- Central Response Section ---
        self.content_container = QWidget(self.inner_card)
        content_layout = QVBoxLayout(self.content_container)
        content_layout.setContentsMargins(20, 14, 20, 14)
        content_layout.setSpacing(0)

        # Loading State
        self.loading_indicator = LoadingIndicator(self.content_container)
        content_layout.addWidget(self.loading_indicator)
        self.loading_indicator.setVisible(False)

        # Response Text Browser
        self.response_browser = ResponseBrowser(self.content_container)
        self.response_browser.setObjectName("responseBrowser")
        self.response_browser.setOpenExternalLinks(True)
        self.response_browser.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.response_browser.document().setDocumentMargin(0)
        self.response_browser.document().setDefaultStyleSheet(BROWSER_DEFAULT_STYLESHEET)
        content_layout.addWidget(self.response_browser, stretch=1)

        card_layout.addWidget(self.content_container, stretch=1)

        # Bottom Horizontal Divider (spans edge-to-edge of inner card)
        footer_divider = QFrame(self.inner_card)
        footer_divider.setObjectName("divider")
        footer_divider.setFixedHeight(1)
        card_layout.addWidget(footer_divider)

        # --- Footer Section ---
        self.footer_frame = QFrame(self.inner_card)
        self.footer_frame.setObjectName("footerBar")
        footer_layout = QHBoxLayout(self.footer_frame)
        footer_layout.setContentsMargins(20, 10, 20, 14)
        footer_layout.setSpacing(8)

        self.status_label = QLabel("Ready when you are.", self.footer_frame)
        self.status_label.setObjectName("statusLabel")
        self.hint_label = self.status_label  # Backward-compatibility alias

        self.copy_btn = CopyButton(get_text_callback=self.get_response_text, parent=self.footer_frame)
        self.size_grip = ResizeGripHandle(self.footer_frame)

        footer_layout.addWidget(self.status_label)
        footer_layout.addStretch()
        footer_layout.addWidget(self.copy_btn)
        footer_layout.addWidget(self.size_grip)
        card_layout.addWidget(self.footer_frame)

        outer_container_layout.addWidget(self.inner_card)
        outer_layout.addWidget(self.container)

    # -------------------------------------------------------------------------
    # Backward compatibility helper for legacy source card calls
    # -------------------------------------------------------------------------
    @property
    def source_card(self):
        """Safe non-visual dummy property preserving backwards compatibility."""
        class _DummySourceCard:
            def set_text(self, text: str): pass
            def setVisible(self, v: bool): pass
            def isVisible(self): return False
        return _DummySourceCard()

    # -------------------------------------------------------------------------
    # Dynamic Window Height Adjustment
    # -------------------------------------------------------------------------
    def adjust_window_height(self):
        """
        Dynamically adjusts the window height to tightly fit the response content:
        - Short responses: Shrinks vertically to eliminate empty blank space (target ~220-260px).
        - Medium responses: Expands naturally as content grows.
        - Long responses: Caps at approximately 70% of available screen height, enabling scrolling.
        """
        # Detect monitor where the window is currently located
        center_pt = self.geometry().center()
        screen = QGuiApplication.screenAt(center_pt) or self.screen() or QGuiApplication.primaryScreen()
        screen_geo = screen.availableGeometry() if screen else None
        if screen_geo:
            max_window_h = int(screen_geo.height() * 0.70)
        else:
            max_window_h = 650

        min_window_h = 220

        # Calculate rendered content height
        if self.loading_indicator.isVisible():
            content_h = max(36, self.loading_indicator.sizeHint().height())
        else:
            doc = self.response_browser.document()
            vp_w = self.response_browser.viewport().width() if self.response_browser.viewport() else 0
            if vp_w < 50:
                vp_w = self.width() - 80  # total horizontal padding: 16 + 24 + 40
            doc.setTextWidth(vp_w)
            content_h = int(doc.documentLayout().documentSize().height())

        # Exact chrome overhead from components:
        # Header (margins 24 + height ~24 = ~48)
        header_h = self.header_frame.sizeHint().height() if hasattr(self, "header_frame") else 48
        # Footer (margins 24 + button 32 = ~56)
        footer_h = self.footer_frame.sizeHint().height() if hasattr(self, "footer_frame") else 56
        # Dividers (1 + 1 = 2) + Content padding (14 + 14 = 28) + Outer card margins (12 + 12 = 24) + Outer layout margins (8 + 8 = 16)
        overhead = header_h + footer_h + 2 + 28 + 24 + 16

        target_h = overhead + content_h + 16
        clamped_h = max(min_window_h, min(target_h, max_window_h))

        # Only resize if height difference is meaningful (>= 4px) to avoid jitter
        if abs(self.height() - clamped_h) >= 4:
            self.resize(self.width(), clamped_h)
            # Ensure window stays within screen bounds if expanded downwards
            if screen_geo and (self.y() + clamped_h > screen_geo.bottom() - 10):
                new_y = max(screen_geo.top() + 10, screen_geo.bottom() - clamped_h - 10)
                self.move(self.x(), new_y)

    # -------------------------------------------------------------------------
    # Window dragging & interactions
    # -------------------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and not self._drag_pos.isNull():
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = QPoint()
        event.accept()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        copy_action = menu.addAction("Copy Response")
        copy_action.triggered.connect(self.copy_btn.click)
        menu.addSeparator()
        setup_action = menu.addAction("Configure API Key...")
        setup_action.triggered.connect(self.setup_requested.emit)
        menu.addSeparator()
        dismiss_action = menu.addAction("Dismiss (Esc)")
        dismiss_action.triggered.connect(self.dismiss)
        exit_action = menu.addAction("Exit Kya-Ray")
        exit_action.triggered.connect(self.exit_requested.emit)
        menu.exec(event.globalPos())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
            event.accept()
        elif event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_C:
            # If user has no specific selection highlighted in response browser, copy full response
            if not self.response_browser.textCursor().hasSelection():
                self.copy_btn.click()
                event.accept()
            else:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    # -------------------------------------------------------------------------
    # Public State Methods
    # -------------------------------------------------------------------------
    def set_intent(self, intent_key: str):
        """Updates the non-interactive detected intent badge."""
        self._current_intent = intent_key
        self.intent_badge.set_intent(intent_key)

    def show_generating(self, text: str, intent: str = "-explain", run_id: Optional[int] = None):
        """Displays generating / thinking state for the selected text."""
        self._dismissed = False
        self._active_run_id = run_id
        self._current_text = text
        self._current_response = ""
        self.set_intent(intent)

        self._resize_timer.stop()
        self.response_browser.setVisible(False)
        self.copy_btn.setEnabled(False)
        self.status_label.setText("Thinking...")
        self.loading_indicator.start()

        if not self.isVisible():
            self.position_near_mouse()
            self.show()
            self.raise_()
            self.activateWindow()

        self.adjust_window_height()

    def show_explanation(self, text: str, explanation: str, intent: str = "-explain", run_id: Optional[int] = None):
        """Displays completed response formatted with markdown."""
        if self._dismissed:
            return
        if run_id is not None and self._active_run_id is not None and run_id != self._active_run_id:
            return

        self._resize_timer.stop()
        self._current_text = text
        self._current_response = explanation
        self.set_intent(intent)

        self.loading_indicator.stop()
        self.response_browser.setMarkdown(explanation)
        self.response_browser.setVisible(True)
        self.copy_btn.setEnabled(True)
        self.status_label.setText("Ready when you are.")

        if not self.isVisible():
            self.position_near_mouse()
            self.show()
            self.raise_()
            self.activateWindow()

        self.adjust_window_height()

    def append_stream_chunk(self, chunk: str, run_id: Optional[int] = None):
        """Appends an incremental streaming token/chunk and refreshes view."""
        if self._dismissed:
            return
        if run_id is not None and self._active_run_id is not None and run_id != self._active_run_id:
            return

        if self.loading_indicator.isVisible():
            self.loading_indicator.stop()
            self.response_browser.setVisible(True)
            self.status_label.setText("Generating...")

        self._current_response += chunk
        self.response_browser.setMarkdown(self._current_response)
        scrollbar = self.response_browser.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())

        # Throttled auto-expand during streaming (every 80ms)
        if not self._resize_timer.isActive():
            self._resize_timer.start()

    def finish_stream(self, text: str = "", intent: str = "-explain", run_id: Optional[int] = None):
        """Finalizes the streaming response."""
        if self._dismissed:
            return
        if run_id is not None and self._active_run_id is not None and run_id != self._active_run_id:
            return

        self._resize_timer.stop()
        self.loading_indicator.stop()
        self.response_browser.setVisible(True)
        self.status_label.setText("Ready when you are.")
        self.copy_btn.setEnabled(bool(self._current_response.strip()))
        if intent:
            self.set_intent(intent)
        self.adjust_window_height()

    def show_error(self, text: str, error_message: str, run_id: Optional[int] = None):
        """Displays an error state."""
        if self._dismissed:
            return
        if run_id is not None and self._active_run_id is not None and run_id != self._active_run_id:
            return

        self._resize_timer.stop()
        self._current_text = text
        self._current_response = error_message

        self.intent_badge.setVisible(False)
        self.loading_indicator.stop()
        self.status_label.setText("Error encountered")
        self.response_browser.setHtml(
            f"<div style='color: {PALETTE['error']}; font-weight: bold; font-size: 14px;'>Error:</div>"
            f"<div style='color: {PALETTE['text_body']}; margin-top: 6px; font-size: 13px;'>{error_message}</div>"
        )
        self.response_browser.setVisible(True)
        self.copy_btn.setEnabled(False)

        if not self.isVisible():
            self.position_near_mouse()
            self.show()
            self.raise_()
            self.activateWindow()

        self.adjust_window_height()

    def show_no_selection(self, run_id: Optional[int] = None):
        """Displays friendly prompt when no text was highlighted."""
        if run_id is not None and self._active_run_id is not None and run_id != self._active_run_id:
            return

        self._resize_timer.stop()
        self._current_text = ""
        self._current_response = ""

        self.intent_badge.setVisible(False)
        self.loading_indicator.stop()
        self.status_label.setText("No selection")
        self.response_browser.setHtml(
            "<div style='color: #2563EB; font-weight: 700; font-size: 14px;'>No text selected</div>"
            "<div style='color: #4B5563; margin-top: 6px; font-size: 13px; line-height: 1.5;'>"
            "Select text in any application and press <b>Ctrl + Alt + Space</b> to see an explanation or summary."
            "</div>"
        )
        self.response_browser.setVisible(True)
        self.copy_btn.setEnabled(False)

        if not self.isVisible():
            self.position_near_mouse()
            self.show()
            self.raise_()
            self.activateWindow()

        self.adjust_window_height()

    def show_startup_notice(self, status: str, message: str, popup: bool = True):
        """Displays startup prerequisite notice if backend or model is unconfigured.
        Prepares notice content and opens window if popup is True or window was already active.
        """
        self._resize_timer.stop()
        self._current_text = ""
        self._current_response = message

        self.intent_badge.setVisible(False)
        self.loading_indicator.stop()
        self.status_label.setText(f"Prerequisite ({status})")
        title_color = PALETTE["error"] if status == "offline" else PALETTE["primary"]
        self.response_browser.setHtml(
            f"<div style='color: {title_color}; font-weight: bold; font-size: 14px;'>Prerequisite Notice ({status})</div>"
            f"<div style='color: {PALETTE['text_body']}; margin-top: 6px; font-size: 13px; white-space: pre-wrap;'>{message}</div>"
            f"<div style='color: {PALETTE['text_muted']}; margin-top: 8px; font-size: 12px;'>"
            f"Kya-Ray is active in the background. Press <b>Ctrl + Alt + Space</b> once ready.</div>"
        )
        self.response_browser.setVisible(True)
        self.copy_btn.setEnabled(False)

        if popup or self.isVisible():
            if not self.isVisible():
                self.position_near_mouse()
                self.show()
                self.raise_()
                self.activateWindow()
            self.adjust_window_height()

    def dismiss(self):
        """Hides the assistant window and invalidates active in-flight run."""
        self._resize_timer.stop()
        self.loading_indicator.stop()
        self._dismissed = True
        self._active_run_id = None
        self.hide()
        self.dismissed.emit()

    def get_response_text(self) -> str:
        """Returns the current raw response text."""
        return self._current_response

    def position_near_mouse(self, x: Optional[int] = None, y: Optional[int] = None):
        """Positions window adjacent to the cursor while keeping it within screen bounds."""
        if x is None or y is None:
            pos = get_mouse_position()
            if pos is not None:
                x, y = pos
            else:
                screen = self.screen() or QGuiApplication.primaryScreen()
                if screen:
                    center = screen.geometry().center()
                    x, y = center.x(), center.y()
                else:
                    x, y = 200, 200

        # Detect the exact monitor where the mouse cursor is located (multi-monitor support)
        cursor_pt = QPoint(x, y)
        screen = QGuiApplication.screenAt(cursor_pt) or self.screen() or QGuiApplication.primaryScreen()
        screen_geo = screen.availableGeometry() if screen else None

        win_w = self.width()
        win_h = self.height()

        target_x = x + 15
        target_y = y + 15

        if screen_geo:
            if target_x + win_w > screen_geo.right() - 10:
                target_x = max(screen_geo.left() + 10, x - win_w - 15)
            if target_y + win_h > screen_geo.bottom() - 10:
                target_y = max(screen_geo.top() + 10, y - win_h - 15)

        self.move(target_x, target_y)


def main():
    """Standalone entrypoint for launching and previewing the PySide6 UI."""
    app = QApplication.instance() or QApplication(sys.argv)

    window = AssistantBubbleWindow()
    window.show_explanation(
        text="FastAPI is a modern web framework.",
        explanation=(
            "### Here's the idea.\n\n"
            "Your response begins here. It gets the space it deserves, without the selected-text "
            "preview taking up valuable room.\n\n"
            "Code, lists, headings and explanations should all render comfortably."
        ),
        intent="-explain",
    )
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
