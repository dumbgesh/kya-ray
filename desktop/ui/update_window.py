"""
desktop/ui/update_window.py - Polished Software Update Dialog Window.

Matches Kya-Ray's floating card design system:
- Outer soft grey container (#F0F1F4) with 16px radius and drop shadow.
- Inner pure white card (#FFFFFF) with 12px radius and #E2E4E9 border.
- Clean header with title, drag support, and close button.
- Version & Release Channel selector (Stable / Beta).
- Formatted release notes viewer (QTextBrowser with Markdown).
- Streaming download progress bar and throughput stats.
- Two-step restart confirmation protecting against unexpected shutdowns.
- Full Qt signal integration with UpdateController.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from desktop.ui.styles import LIGHT_THEME_QSS, PALETTE
from desktop.ui.update_controller import (
    DownloadProgress,
    DownloadResult,
    UpdateCheckResult,
    UpdateController,
    UpdateUIState,
)


class UpdateWindow(QWidget):
    """
    Polished desktop window for checking, downloading, verifying,
    and confirming installation of Kya-Ray software updates.
    """

    def __init__(
        self,
        controller: UpdateController,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.controller = controller
        self._drag_pos = QPoint()

        # Frameless, floating on-top tool window matching Kya-Ray's other dialogs
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(LIGHT_THEME_QSS)

        self.resize(520, 460)
        self.setMinimumSize(460, 400)

        # Build UI layout and elements
        self._setup_ui()

        # Connect controller signals to UI slots
        self._wire_controller_signals()

        # Keyboard shortcuts
        self._esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._esc_shortcut.activated.connect(self.close)
        self._close_shortcut = QShortcut(QKeySequence("Ctrl+W"), self)
        self._close_shortcut.activated.connect(self.close)

        # Sync UI with current controller state
        self._update_ui_for_state(self.controller.current_state, self.controller.status_message)

    # -------------------------------------------------------------------------
    # UI Construction
    # -------------------------------------------------------------------------
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

        self.title_label = QLabel("Software Update", self.header_frame)
        self.title_label.setObjectName("titleLabel")

        self.close_btn = QPushButton("✕", self.header_frame)
        self.close_btn.setObjectName("closeButton")
        self.close_btn.setToolTip("Close (Esc)")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.close)

        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.close_btn)
        card_layout.addWidget(self.header_frame)

        # Header Divider
        divider1 = QFrame(self.inner_card)
        divider1.setObjectName("divider")
        divider1.setFixedHeight(1)
        divider1.setStyleSheet("background-color: #E2E4E9;")
        card_layout.addWidget(divider1)

        # --- Content Body ---
        content_widget = QWidget(self.inner_card)
        body_layout = QVBoxLayout(content_widget)
        body_layout.setContentsMargins(22, 16, 22, 16)
        body_layout.setSpacing(12)

        # 3. Version & Channel Bar
        info_bar = QWidget(content_widget)
        info_layout = QHBoxLayout(info_bar)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(10)

        self.version_badge = QLabel(f"Installed: v{self.controller.current_version}", info_bar)
        self.version_badge.setStyleSheet(
            "background-color: #F3F4F6;"
            "color: #374151;"
            "font-size: 12px;"
            "font-weight: 600;"
            "padding: 3px 8px;"
            "border-radius: 6px;"
            "border: 1px solid #E5E7EB;"
        )

        self.channel_label = QLabel("Channel:", info_bar)
        self.channel_label.setStyleSheet("font-size: 12px; color: #6B7280; font-weight: 500;")

        self.channel_combo = QComboBox(info_bar)
        self.channel_combo.addItem("Beta (Pre-releases)", userData=True)
        self.channel_combo.addItem("Stable Only", userData=False)
        self.channel_combo.setCurrentIndex(0 if self.controller.allow_prereleases else 1)
        self.channel_combo.setStyleSheet(
            "QComboBox {"
            "    background-color: #F9FAFB;"
            "    border: 1px solid #D1D5DB;"
            "    border-radius: 6px;"
            "    padding: 3px 8px;"
            "    font-size: 12px;"
            "    color: #111827;"
            "}"
            "QComboBox:focus {"
            "    border: 1px solid #2563EB;"
            "}"
        )
        self.channel_combo.currentIndexChanged.connect(self._on_channel_changed)

        info_layout.addWidget(self.version_badge)
        info_layout.addStretch()
        info_layout.addWidget(self.channel_label)
        info_layout.addWidget(self.channel_combo)
        body_layout.addWidget(info_bar)

        # 4. Status Headline & Description
        self.headline_label = QLabel("Check for Updates", content_widget)
        self.headline_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #111827;")
        self.headline_label.setWordWrap(True)
        body_layout.addWidget(self.headline_label)

        self.desc_label = QLabel("Kya-Ray can check GitHub for the latest release.", content_widget)
        self.desc_label.setStyleSheet("font-size: 13px; line-height: 1.4; color: #4B5563;")
        self.desc_label.setWordWrap(True)
        body_layout.addWidget(self.desc_label)

        # 5. Progress Bar and Stats (visible during download)
        self.progress_container = QWidget(content_widget)
        progress_layout = QVBoxLayout(self.progress_container)
        progress_layout.setContentsMargins(0, 4, 0, 4)
        progress_layout.setSpacing(4)

        self.progress_bar = QProgressBar(self.progress_container)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setStyleSheet(
            "QProgressBar {"
            "    border: 1px solid #E5E7EB;"
            "    border-radius: 4px;"
            "    background-color: #F3F4F6;"
            "}"
            "QProgressBar::chunk {"
            "    background-color: #2563EB;"
            "    border-radius: 3px;"
            "}"
        )

        self.progress_stats_label = QLabel("", self.progress_container)
        self.progress_stats_label.setStyleSheet("font-size: 11.5px; color: #6B7280; font-weight: 500;")

        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.progress_stats_label)
        self.progress_container.setVisible(False)
        body_layout.addWidget(self.progress_container)

        # 6. Release Notes Browser
        self.notes_browser = QTextBrowser(content_widget)
        self.notes_browser.setOpenExternalLinks(True)
        self.notes_browser.setStyleSheet(
            "QTextBrowser {"
            "    background-color: #F9FAFB;"
            "    border: 1px solid #E5E7EB;"
            "    border-radius: 8px;"
            "    padding: 10px 12px;"
            "    font-size: 12.5px;"
            "    color: #374151;"
            "    line-height: 1.4;"
            "}"
        )
        self.notes_browser.setVisible(False)
        body_layout.addWidget(self.notes_browser, stretch=1)

        # 7. Restart Confirmation Banner (Visible only in RESTART_CONFIRMATION)
        self.restart_card = QFrame(content_widget)
        self.restart_card.setStyleSheet(
            "QFrame {"
            "    background-color: #EFF6FF;"
            "    border: 1px solid #BFDBFE;"
            "    border-radius: 8px;"
            "    padding: 8px 12px;"
            "}"
        )
        restart_layout = QVBoxLayout(self.restart_card)
        restart_layout.setContentsMargins(10, 8, 10, 8)
        restart_layout.setSpacing(4)

        restart_title = QLabel("⚠️ Application Restart Required", self.restart_card)
        restart_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #1E40AF; border: none; background: transparent;")
        restart_desc = QLabel(
            "Kya-Ray will close and launch the detached updater to replace application files.\n"
            "The app will automatically restart once installation succeeds.",
            self.restart_card,
        )
        restart_desc.setWordWrap(True)
        restart_desc.setStyleSheet("font-size: 12px; color: #1E3A8A; border: none; background: transparent;")

        restart_layout.addWidget(restart_title)
        restart_layout.addWidget(restart_desc)
        self.restart_card.setVisible(False)
        body_layout.addWidget(self.restart_card)

        # 8. Error Card (Visible in ERROR / DOWNLOAD_FAILED)
        self.error_card = QFrame(content_widget)
        self.error_card.setStyleSheet(
            "QFrame {"
            "    background-color: #FEF2F2;"
            "    border: 1px solid #FECACA;"
            "    border-radius: 8px;"
            "    padding: 8px 12px;"
            "}"
        )
        err_layout = QVBoxLayout(self.error_card)
        err_layout.setContentsMargins(10, 8, 10, 8)
        err_layout.setSpacing(2)

        self.error_title = QLabel("Update Issue", self.error_card)
        self.error_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #991B1B; border: none; background: transparent;")
        self.error_detail = QLabel("", self.error_card)
        self.error_detail.setWordWrap(True)
        self.error_detail.setStyleSheet("font-size: 12px; color: #B91C1C; border: none; background: transparent;")

        err_layout.addWidget(self.error_title)
        err_layout.addWidget(self.error_detail)
        self.error_card.setVisible(False)
        body_layout.addWidget(self.error_card)

        card_layout.addWidget(content_widget, stretch=1)

        # Bottom Divider
        divider2 = QFrame(self.inner_card)
        divider2.setObjectName("divider")
        divider2.setFixedHeight(1)
        divider2.setStyleSheet("background-color: #E2E4E9;")
        card_layout.addWidget(divider2)

        # --- Footer / Button Bar ---
        footer_widget = QWidget(self.inner_card)
        footer_layout = QHBoxLayout(footer_widget)
        footer_layout.setContentsMargins(20, 12, 20, 14)
        footer_layout.setSpacing(10)

        self.secondary_btn = QPushButton("Close", footer_widget)
        self.secondary_btn.setFixedHeight(34)
        self.secondary_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.secondary_btn.setStyleSheet(
            "QPushButton {"
            "    background-color: #F3F4F6;"
            "    border: 1px solid #E5E7EB;"
            "    border-radius: 8px;"
            "    font-size: 13px;"
            "    font-weight: 500;"
            "    color: #4B5563;"
            "    padding: 0px 14px;"
            "}"
            "QPushButton:hover {"
            "    background-color: #E5E7EB;"
            "    color: #111827;"
            "}"
        )
        self.secondary_btn.clicked.connect(self._handle_secondary_action)

        self.primary_btn = QPushButton("Check for Updates", footer_widget)
        self.primary_btn.setFixedHeight(34)
        self.primary_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.primary_btn.setStyleSheet(
            "QPushButton {"
            "    background-color: #2563EB;"
            "    color: #FFFFFF;"
            "    border: none;"
            "    border-radius: 8px;"
            "    font-size: 13px;"
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
        self.primary_btn.clicked.connect(self._handle_primary_action)

        footer_layout.addWidget(self.secondary_btn)
        footer_layout.addStretch()
        footer_layout.addWidget(self.primary_btn)
        card_layout.addWidget(footer_widget)

        outer_container_layout.addWidget(self.inner_card)
        outer_layout.addWidget(self.container)

    # -------------------------------------------------------------------------
    # Signal Connections
    # -------------------------------------------------------------------------
    def _wire_controller_signals(self):
        bridge = self.controller.bridge
        bridge.sig_state_changed.connect(self._on_state_changed_slot)
        bridge.sig_download_progress.connect(self._on_download_progress_slot)
        bridge.sig_check_finished.connect(self._on_check_finished_slot)
        bridge.sig_handoff_started.connect(self._on_handoff_started_slot)
        bridge.sig_handoff_failed.connect(self._on_handoff_failed_slot)

    def _on_channel_changed(self, index: int):
        allow_pre = self.channel_combo.currentData()
        self.controller.allow_prereleases = bool(allow_pre)

    # -------------------------------------------------------------------------
    # State Synchronization Slots
    # -------------------------------------------------------------------------
    def _on_state_changed_slot(self, state_str: str, message: str):
        try:
            state = UpdateUIState(state_str)
        except ValueError:
            return
        self._update_ui_for_state(state, message)

    def _on_download_progress_slot(self, prog: DownloadProgress):
        pct = int(prog.percent) if prog.percent else 0
        self.progress_bar.setValue(pct)
        mb_down = prog.downloaded_bytes / (1024 * 1024)
        if prog.total_bytes and prog.total_bytes > 0:
            mb_total = prog.total_bytes / (1024 * 1024)
            speed_mb = prog.speed_bytes_per_sec / (1024 * 1024)
            stats = f"{mb_down:.1f} MB of {mb_total:.1f} MB ({pct}%) • {speed_mb:.1f} MB/s"
        else:
            stats = f"{mb_down:.1f} MB downloaded"
        self.progress_stats_label.setText(stats)

    def _on_check_finished_slot(self, result: UpdateCheckResult):
        if result.is_update_available and result.release_info:
            body_md = result.release_info.body or "No changelog provided for this release."
            self.notes_browser.setMarkdown(f"### What's New in v{result.release_info.version}\n\n{body_md}")
            self.notes_browser.setVisible(True)
        else:
            self.notes_browser.setVisible(False)

    def _on_handoff_started_slot(self):
        self._update_ui_for_state(UpdateUIState.APPLYING_UPDATE, "Launching detached updater...")

    def _on_handoff_failed_slot(self, error_msg: str):
        self.error_detail.setText(f"Failed to start installer: {error_msg}")
        self.error_card.setVisible(True)

    def _update_ui_for_state(self, state: UpdateUIState, message: str):
        # Default visibility resets
        self.progress_container.setVisible(False)
        self.restart_card.setVisible(False)
        self.error_card.setVisible(False)
        self.primary_btn.setEnabled(True)
        self.secondary_btn.setEnabled(True)

        if state == UpdateUIState.IDLE:
            self.headline_label.setText("Check for Updates")
            self.desc_label.setText(message or f"Kya-Ray is currently on version v{self.controller.current_version}.")
            self.primary_btn.setText("Check for Updates")
            self.secondary_btn.setText("Close")
            self.notes_browser.setVisible(False)

        elif state == UpdateUIState.CHECKING:
            self.headline_label.setText("Checking for updates...")
            self.desc_label.setText("Connecting to GitHub releases...")
            self.primary_btn.setText("Checking...")
            self.primary_btn.setEnabled(False)
            self.secondary_btn.setText("Close")
            self.notes_browser.setVisible(False)

        elif state == UpdateUIState.UP_TO_DATE:
            self.headline_label.setText("You're up to date!")
            self.desc_label.setText(message or f"Kya-Ray v{self.controller.current_version} is the latest release.")
            self.primary_btn.setText("Check Again")
            self.secondary_btn.setText("Close")
            self.notes_browser.setVisible(False)

        elif state == UpdateUIState.UPDATE_AVAILABLE:
            ver_str = (
                str(self.controller.check_result.latest_version)
                if self.controller.check_result and self.controller.check_result.latest_version
                else "New"
            )
            self.headline_label.setText(f"Kya-Ray v{ver_str} is available!")
            self.desc_label.setText(message or "A newer release is ready to download and install.")
            self.primary_btn.setText("Download Update")
            self.secondary_btn.setText("Later")
            # Keep notes browser visible if it contains content
            if self.notes_browser.toPlainText().strip():
                self.notes_browser.setVisible(True)

        elif state == UpdateUIState.DOWNLOADING:
            self.headline_label.setText("Downloading Update...")
            self.desc_label.setText("Streaming release package from GitHub...")
            self.progress_container.setVisible(True)
            self.primary_btn.setText("Cancel Download")
            self.secondary_btn.setText("Close")

        elif state == UpdateUIState.DOWNLOAD_CANCELLED:
            self.headline_label.setText("Download Cancelled")
            self.desc_label.setText(message or "The update download was cancelled.")
            self.primary_btn.setText("Try Again")
            self.secondary_btn.setText("Close")

        elif state == UpdateUIState.DOWNLOAD_FAILED:
            self.headline_label.setText("Download Failed")
            self.desc_label.setText("The download could not be completed.")
            self.error_detail.setText(message or "An error occurred during download.")
            self.error_card.setVisible(True)
            self.primary_btn.setText("Retry Download")
            self.secondary_btn.setText("Close")

        elif state == UpdateUIState.DOWNLOAD_VERIFIED:
            self.headline_label.setText("Update Package Verified")
            self.desc_label.setText("SHA-256 integrity check passed successfully.")
            self.primary_btn.setText("Restart & Install")
            self.secondary_btn.setText("Later")

        elif state == UpdateUIState.READY_TO_INSTALL:
            self.headline_label.setText("Ready to Install")
            self.desc_label.setText("The verified update package is ready to be installed.")
            self.primary_btn.setText("Restart & Install")
            self.secondary_btn.setText("Later")

        elif state == UpdateUIState.RESTART_CONFIRMATION:
            self.headline_label.setText("Confirm Application Restart")
            self.desc_label.setText("To apply the update, Kya-Ray will shut down and launch the updater.")
            self.restart_card.setVisible(True)
            self.primary_btn.setText("Confirm Restart")
            self.secondary_btn.setText("Cancel")

        elif state == UpdateUIState.APPLYING_UPDATE:
            self.headline_label.setText("Applying Update...")
            self.desc_label.setText(message or "Handoff to detached updater in progress...")
            self.primary_btn.setText("Updating...")
            self.primary_btn.setEnabled(False)
            self.secondary_btn.setEnabled(False)

        elif state == UpdateUIState.ERROR:
            self.headline_label.setText("Update Check Failed")
            self.desc_label.setText("Unable to check for updates.")
            self.error_detail.setText(message or "Unknown error occurred.")
            self.error_card.setVisible(True)
            self.primary_btn.setText("Retry Check")
            self.secondary_btn.setText("Close")

    # -------------------------------------------------------------------------
    # Button Actions
    # -------------------------------------------------------------------------
    def _handle_primary_action(self):
        state = self.controller.current_state

        if state in (UpdateUIState.IDLE, UpdateUIState.UP_TO_DATE, UpdateUIState.ERROR):
            self.controller.check_for_updates(manual=True)

        elif state == UpdateUIState.UPDATE_AVAILABLE:
            self.controller.start_download()

        elif state == UpdateUIState.DOWNLOADING:
            self.controller.cancel_download()

        elif state in (UpdateUIState.DOWNLOAD_CANCELLED, UpdateUIState.DOWNLOAD_FAILED):
            self.controller.start_download()

        elif state in (UpdateUIState.DOWNLOAD_VERIFIED, UpdateUIState.READY_TO_INSTALL):
            # Prompt two-step restart confirmation
            self.controller.request_install_and_restart(confirmed=False)

        elif state == UpdateUIState.RESTART_CONFIRMATION:
            # Explicit user confirmation granted
            self.controller.request_install_and_restart(confirmed=True)

    def _handle_secondary_action(self):
        if self.controller.current_state == UpdateUIState.RESTART_CONFIRMATION:
            # User cancels restart: revert to READY_TO_INSTALL safely
            self.controller.set_state(UpdateUIState.READY_TO_INSTALL, "Update is ready to install.")
        else:
            self.close()

    # -------------------------------------------------------------------------
    # Window Lifecycle & Dragging Support
    # -------------------------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        self._update_ui_for_state(self.controller.current_state, self.controller.status_message)

    def closeEvent(self, event):
        if self.controller.current_state == UpdateUIState.RESTART_CONFIRMATION:
            self.controller.set_state(UpdateUIState.READY_TO_INSTALL, "Update is ready to install.")
        super().closeEvent(event)

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
