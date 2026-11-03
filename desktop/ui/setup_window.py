"""
desktop/ui/setup_window.py - First-Launch and Settings API Key Configuration Window.

Provides a polished, native graphical setup interface matching the Kya-Ray design:
- Title: "Let's get you started."
- Description: "Kya-Ray uses Groq to power its AI responses. Add your API key to get started."
- Password-style input field with Show/Hide toggle
- Direct link to Groq API keys console
- Primary action button: "Connect and continue"
- Asynchronous non-blocking validation against Groq API
- Secure storage to Windows Credential Manager upon verified validation
"""

import threading
from typing import Optional

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop.ui.styles import LIGHT_THEME_QSS, PALETTE
from desktop.utils.credentials import get_stored_api_key, store_api_key
from desktop.utils.validator import validate_groq_api_key


class ApiKeySetupWindow(QWidget):
    """
    Polished floating window for first-launch Groq API key configuration and credential replacement.
    """

    key_configured = Signal(str)  # Emitted when a key is successfully validated and saved
    dismissed = Signal()

    def __init__(self, parent: Optional[QWidget] = None, is_update: bool = False):
        super().__init__(parent)
        self.is_update = is_update
        self._drag_pos = QPoint()
        self._is_validating = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(LIGHT_THEME_QSS)

        self._setup_ui()
        self.resize(500, 340)
        self.setMinimumSize(440, 310)

        # Keyboard shortcuts
        self._esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._esc_shortcut.activated.connect(self.dismiss)

        self._close_shortcut = QShortcut(QKeySequence("Ctrl+W"), self)
        self._close_shortcut.activated.connect(self.dismiss)

    def _setup_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(10, 10, 10, 10)
        outer_layout.setSpacing(0)

        # 1. Outer Container Frame (Soft grey #F0F1F4, rounded corners 16px)
        self.container = QFrame(self)
        self.container.setObjectName("containerFrame")

        shadow = QGraphicsDropShadowEffect(self.container)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 45))
        shadow.setOffset(0, 6)
        self.container.setGraphicsEffect(shadow)

        outer_container_layout = QVBoxLayout(self.container)
        outer_container_layout.setContentsMargins(12, 12, 12, 12)
        outer_container_layout.setSpacing(0)

        # 2. Inner Content Card (Pure white #FFFFFF, border #E2E4E9, rounded corners 12px)
        self.inner_card = QFrame(self.container)
        self.inner_card.setObjectName("innerCard")

        card_layout = QVBoxLayout(self.inner_card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # --- Header Bar ---
        self.header_frame = QFrame(self.inner_card)
        self.header_frame.setObjectName("headerBar")
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(20, 14, 16, 10)
        header_layout.setSpacing(8)

        self.title_label = QLabel("Kya-Ray", self.header_frame)
        self.title_label.setObjectName("titleLabel")

        self.close_btn = QPushButton("✕", self.header_frame)
        self.close_btn.setObjectName("closeButton")
        self.close_btn.setToolTip("Close (Esc)")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.dismiss)

        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.close_btn)
        card_layout.addWidget(self.header_frame)

        # Header Divider
        divider = QFrame(self.inner_card)
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        card_layout.addWidget(divider)

        # --- Content Body ---
        content_widget = QWidget(self.inner_card)
        body_layout = QVBoxLayout(content_widget)
        body_layout.setContentsMargins(24, 18, 24, 20)
        body_layout.setSpacing(10)

        # Headline
        headline_text = "Update your API key" if self.is_update else "Let's get you started."
        self.headline_label = QLabel(headline_text, content_widget)
        self.headline_label.setStyleSheet("font-size: 17px; font-weight: 700; color: #111827;")

        # Description
        desc_text = (
            "Enter a new Groq API key to replace the currently stored credential."
            if self.is_update
            else "Kya-Ray uses Groq to power its AI responses. Add your API key to get started."
        )
        self.desc_label = QLabel(desc_text, content_widget)
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet("font-size: 13px; line-height: 1.5; color: #4B5563;")

        # Clickable Link to Groq Console
        self.link_label = QLabel(
            '<a href="https://console.groq.com/keys" style="color: #2563EB; text-decoration: none; font-weight: 500;">'
            'Get a free API key at console.groq.com/keys &rarr;</a>',
            content_widget,
        )
        self.link_label.setOpenExternalLinks(True)
        self.link_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.link_label.setStyleSheet("font-size: 12.5px; padding-bottom: 4px;")

        # Input Label
        self.input_label = QLabel("Enter your API key", content_widget)
        self.input_label.setStyleSheet("font-size: 12.5px; font-weight: 600; color: #374151; margin-top: 4px;")

        # Input Row (Field + Show/Hide Toggle)
        input_container = QWidget(content_widget)
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(6)

        self.key_input = QLineEdit(input_container)
        self.key_input.setPlaceholderText("Enter new key (gsk_...)" if self.is_update else "gsk_...")
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setStyleSheet(
            "QLineEdit {"
            "    background-color: #F9FAFB;"
            "    border: 1px solid #D1D5DB;"
            "    border-radius: 8px;"
            "    padding: 7px 10px;"
            "    font-size: 13px;"
            "    color: #111827;"
            "}"
            "QLineEdit:focus {"
            "    border: 1.5px solid #2563EB;"
            "    background-color: #FFFFFF;"
            "}"
        )
        self.key_input.returnPressed.connect(self._handle_submit)

        # Show/Hide Toggle Button
        self.toggle_btn = QPushButton("Show", input_container)
        self.toggle_btn.setFixedSize(54, 32)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.setStyleSheet(
            "QPushButton {"
            "    background-color: #F3F4F6;"
            "    border: 1px solid #E5E7EB;"
            "    border-radius: 6px;"
            "    font-size: 12px;"
            "    font-weight: 500;"
            "    color: #4B5563;"
            "}"
            "QPushButton:hover {"
            "    background-color: #E5E7EB;"
            "    color: #111827;"
            "}"
        )
        self.toggle_btn.clicked.connect(self._toggle_password_visibility)

        input_layout.addWidget(self.key_input, stretch=1)
        input_layout.addWidget(self.toggle_btn)

        # Status / Feedback Label
        self.status_label = QLabel("", content_widget)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 12px; font-weight: 500; min-height: 18px;")

        # Primary Action Button
        btn_label = "Update and continue" if self.is_update else "Connect and continue"
        self.submit_btn = QPushButton(btn_label, content_widget)
        self.submit_btn.setFixedHeight(36)
        self.submit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.submit_btn.setStyleSheet(
            "QPushButton {"
            "    background-color: #2563EB;"
            "    color: #FFFFFF;"
            "    border: none;"
            "    border-radius: 8px;"
            "    font-size: 13.5px;"
            "    font-weight: 600;"
            "    padding: 0px 16px;"
            "}"
            "QPushButton:hover {"
            "    background-color: #1D4ED8;"
            "}"
            "QPushButton:pressed {"
            "    background-color: #1E40AF;"
            "}"
            "QPushButton:disabled {"
            "    background-color: #93C5FD;"
            "    color: #FFFFFF;"
            "}"
        )
        self.submit_btn.clicked.connect(self._handle_submit)

        body_layout.addWidget(self.headline_label)
        body_layout.addWidget(self.desc_label)
        body_layout.addWidget(self.link_label)
        body_layout.addWidget(self.input_label)
        body_layout.addWidget(input_container)
        body_layout.addWidget(self.status_label)
        body_layout.addWidget(self.submit_btn)

        card_layout.addWidget(content_widget, stretch=1)
        outer_container_layout.addWidget(self.inner_card)
        outer_layout.addWidget(self.container)

    def _toggle_password_visibility(self):
        """Toggles between hidden and plain text echo modes."""
        if self.key_input.echoMode() == QLineEdit.EchoMode.Password:
            self.key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.toggle_btn.setText("Hide")
        else:
            self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.toggle_btn.setText("Show")

    def _handle_submit(self):
        """Initiates background validation of the entered key."""
        if self._is_validating:
            return

        api_key = self.key_input.text().strip()
        if not api_key:
            self._show_error("Please enter an API key.")
            self.key_input.setFocus()
            return

        if not api_key.startswith("gsk_"):
            self._show_error("Invalid key format. Groq API keys start with 'gsk_'.")
            self.key_input.setFocus()
            return

        # Enter validating state
        self._is_validating = True
        self.submit_btn.setEnabled(False)
        self.submit_btn.setText("Connecting...")
        self.key_input.setEnabled(False)
        self.status_label.setStyleSheet("font-size: 12px; font-weight: 500; color: #2563EB;")
        self.status_label.setText("Verifying API key with Groq...")

        # Asynchronously validate in a background thread to keep UI completely responsive
        def _worker():
            is_valid, error_msg = validate_groq_api_key(api_key, timeout=8.0)
            # Route result back to Qt event loop
            QApplication.instance().postEvent(
                self,
                _ValidationEvent(is_valid=is_valid, error_msg=error_msg, api_key=api_key),
            )

        threading.Thread(target=_worker, daemon=True, name="kya-ray-key-validator").start()

    def customEvent(self, event):
        """Processes completion event delivered from the validation thread."""
        if isinstance(event, _ValidationEvent):
            self._on_validation_result(event.is_valid, event.error_msg, event.api_key)
        else:
            super().customEvent(event)

    def _on_validation_result(self, is_valid: bool, error_msg: str, api_key: str):
        """Processes validation results on the Qt main thread."""
        self._is_validating = False
        self.key_input.setEnabled(True)
        self.submit_btn.setEnabled(True)
        self.submit_btn.setText("Update and continue" if self.is_update else "Connect and continue")

        if is_valid:
            # Securely store in Windows Credential Manager
            saved = store_api_key(api_key)
            if not saved:
                self._show_error("Could not write to Windows Credential Manager.")
                return

            self.status_label.setStyleSheet("font-size: 12px; font-weight: 600; color: #10B981;")
            self.status_label.setText("✓ Connected successfully!")

            self.key_configured.emit(api_key)
            self.hide()
        else:
            self._show_error(error_msg or "Failed to validate API key.")
            self.key_input.setFocus()
            self.key_input.selectAll()

    def _show_error(self, message: str):
        self.status_label.setStyleSheet("font-size: 12px; font-weight: 500; color: #D93025;")
        self.status_label.setText(message)

    def dismiss(self):
        """Closes or cancels setup window."""
        self.hide()
        self.dismissed.emit()

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


from PySide6.QtCore import QEvent


class _ValidationEvent(QEvent):
    """Custom Qt event for delivering background validation result to main thread."""

    EVENT_TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, is_valid: bool, error_msg: str, api_key: str):
        super().__init__(_ValidationEvent.EVENT_TYPE)
        self.is_valid = is_valid
        self.error_msg = error_msg
        self.api_key = api_key

