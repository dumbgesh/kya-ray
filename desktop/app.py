"""
desktop/app.py - Main entry point connecting PySide6 UI and AppOrchestrator.

Responsibilities:
1. Thread-safe communication: Background events from HotkeyListener / OllamaClient
   are routed through Qt signals to guarantee all UI updates happen on the Qt main thread.
2. Manages application lifecycle: Prevents accidental process exit on window dismiss,
   and handles clean shutdown and background thread cleanup on exit or Ctrl+C.
3. Coordinates manual intent changes from the UI back into the orchestrator.
"""

import signal
import sys
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from desktop.core.orchestrator import AppOrchestrator
from desktop.ui.bubble import AssistantBubbleWindow
from desktop.ui.setup_window import ApiKeySetupWindow
from desktop.utils.config import APP_NAME, APP_VERSION, SHORTCUT_COMBINATION_NAME
from desktop.utils.credentials import has_stored_api_key
from desktop.utils.logger import setup_safe_logging


class AppSignalBridge(QObject):
    """
    Thread-safe Qt signal bridge.
    Orchestrator callbacks (dispatched on worker threads) emit these signals,
    which Qt delivers to the GUI widgets on the main event loop.
    """

    sig_generating = Signal(str, str, object)        # text, intent, run_id
    sig_chunk = Signal(str, object)                  # chunk, run_id
    sig_explanation = Signal(str, str, str, object)   # text, explanation, intent, run_id
    sig_error = Signal(str, str, object)              # text, error, run_id
    sig_no_selection = Signal(object)                # run_id
    sig_dismiss = Signal()
    sig_startup_notice = Signal(str, str)            # status, message


class KyaRayApplication:
    """
    Main application manager linking PySide6 UI with the backend orchestrator.
    """

    def __init__(
        self,
        qapp: Optional[QApplication] = None,
        orchestrator: Optional[AppOrchestrator] = None,
        window: Optional[AssistantBubbleWindow] = None,
    ):
        self.qapp = qapp or QApplication.instance() or QApplication(sys.argv)
        # Ensure application remains running in background when floating panel is dismissed
        self.qapp.setQuitOnLastWindowClosed(False)

        self.bridge = AppSignalBridge()
        self.window = window or AssistantBubbleWindow()
        self.setup_window: Optional[ApiKeySetupWindow] = None
        self._is_shutting_down = False

        # Build or wrap the orchestrator with callbacks forwarding into the Qt signal bridge
        self.orchestrator = orchestrator or AppOrchestrator(
            on_generating=self._cb_generating,
            on_chunk=self._cb_chunk,
            on_explanation=self._cb_explanation,
            on_error=self._cb_error,
            on_no_selection=self._cb_no_selection,
            on_dismiss=self._cb_dismiss,
            on_startup_notice=self._cb_startup_notice,
        )

        # Wire Qt signals to UI slots
        self._wire_signals()

    # -------------------------------------------------------------------------
    # Orchestrator callbacks (called from background threads)
    # -------------------------------------------------------------------------
    def _cb_generating(self, text: str, intent: str, run_id: Optional[int]):
        self.bridge.sig_generating.emit(text, intent, run_id)

    def _cb_chunk(self, chunk: str, run_id: Optional[int]):
        self.bridge.sig_chunk.emit(chunk, run_id)

    def _cb_explanation(self, text: str, explanation: str, intent: str, run_id: Optional[int]):
        self.bridge.sig_explanation.emit(text, explanation, intent, run_id)

    def _cb_error(self, text: str, error: str, run_id: Optional[int]):
        self.bridge.sig_error.emit(text, error, run_id)

    def _cb_no_selection(self, run_id: Optional[int]):
        self.bridge.sig_no_selection.emit(run_id)

    def _cb_dismiss(self):
        self.bridge.sig_dismiss.emit()

    def _cb_startup_notice(self, status: str, message: str):
        self.bridge.sig_startup_notice.emit(status, message)

    # -------------------------------------------------------------------------
    # Signal connections
    # -------------------------------------------------------------------------
    def _wire_signals(self):
        # Bridge -> UI (delivered on Qt main thread)
        self.bridge.sig_generating.connect(self._on_ui_generating)
        self.bridge.sig_chunk.connect(self._on_ui_chunk)
        self.bridge.sig_explanation.connect(self._on_ui_explanation)
        self.bridge.sig_error.connect(self._on_ui_error)
        self.bridge.sig_no_selection.connect(self._on_ui_no_selection)
        self.bridge.sig_dismiss.connect(self._on_ui_dismiss)
        self.bridge.sig_startup_notice.connect(self._on_ui_startup_notice)

        # UI -> App lifecycle and configuration
        self.window.exit_requested.connect(self.shutdown)
        self.window.setup_requested.connect(lambda: self.open_setup_window(is_update=True))
        self.qapp.aboutToQuit.connect(self.shutdown)

    # -------------------------------------------------------------------------
    # UI Slot Handlers (running on Qt main thread)
    # -------------------------------------------------------------------------
    def _on_ui_generating(self, text: str, intent: str, run_id: Optional[int]):
        self.window.show_generating(text, intent=intent, run_id=run_id)

    def _on_ui_chunk(self, chunk: str, run_id: Optional[int]):
        self.window.append_stream_chunk(chunk, run_id=run_id)

    def _on_ui_explanation(self, text: str, explanation: str, intent: str, run_id: Optional[int]):
        self.window.show_explanation(text, explanation, intent=intent, run_id=run_id)

    def _on_ui_error(self, text: str, error: str, run_id: Optional[int]):
        self.window.show_error(text, error, run_id=run_id)
        # If the key was invalid or revoked, pop open the setup window to allow replacing it
        err_lower = error.lower()
        if "authentication error" in err_lower or "missing groq api key" in err_lower or "invalid groq api key" in err_lower:
            self.open_setup_window(is_update=True)

    def _on_ui_no_selection(self, run_id: Optional[int]):
        self.window.show_no_selection(run_id=run_id)

    def _on_ui_dismiss(self):
        self.window.dismiss()

    def _on_ui_startup_notice(self, status: str, message: str):
        self.window.show_startup_notice(status, message)
        if status == "groq_unconfigured":
            self.open_setup_window(is_update=False)

    # -------------------------------------------------------------------------
    # API Key Setup & Lifecycle Management
    # -------------------------------------------------------------------------
    def open_setup_window(self, is_update: bool = False):
        """Displays the API key setup window centered on the active screen."""
        if self.setup_window is None:
            self.setup_window = ApiKeySetupWindow(is_update=is_update)
            self.setup_window.key_configured.connect(self._on_key_configured)
        else:
            self.setup_window.is_update = is_update
            self.setup_window.headline_label.setText(
                "Update your API key" if is_update else "Let's get you started."
            )
            self.setup_window.desc_label.setText(
                "Enter a new Groq API key to replace the currently stored credential."
                if is_update
                else "Kya-Ray uses Groq to power its AI responses. Add your API key to get started."
            )

        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.center().x() - self.setup_window.width() // 2
            y = geo.center().y() - self.setup_window.height() // 2
            self.setup_window.move(max(10, x), max(10, y))

        self.setup_window.show()
        self.setup_window.raise_()
        self.setup_window.activateWindow()

    def _on_key_configured(self, api_key: str):
        """Callback triggered when the user saves a verified API key."""
        if self.orchestrator and self.orchestrator.backend_manager:
            self.orchestrator.backend_manager.ensure_running()
        self.window.show_startup_notice(
            "ready",
            "Groq API key verified and connected!\n\nHighlight text in any application and press Ctrl + Alt + Space.",
            popup=True,
        )

    def check_first_launch_setup(self) -> bool:
        """
        Determines whether a valid API key exists locally.
        If no key is configured, displays the first-launch setup window.
        Returns True if setup window was opened, False if key already exists.
        """
        if not has_stored_api_key():
            self.open_setup_window(is_update=False)
            return True
        return False

    def start(self, check_prereqs: bool = True):
        """Prints banner and starts the global hotkey listener and orchestrator."""
        print("=" * 60, flush=True)
        print(f"{APP_NAME} v{APP_VERSION} - Native Desktop Companion", flush=True)
        print("=" * 60, flush=True)
        print("Instructions:", flush=True)
        print(f"  * Select text in any window and press {SHORTCUT_COMBINATION_NAME}.", flush=True)
        print("  * A floating panel displays a concise AI response.", flush=True)
        print("  * Drag anywhere on the header to reposition.", flush=True)
        print("  * Press Esc or click [X] to dismiss.", flush=True)
        print("  * Right-click the panel and choose 'Exit Kya-Ray' to quit.", flush=True)
        print("=" * 60 + "\n", flush=True)

        self.orchestrator.start(check_prereqs=check_prereqs)
        self.check_first_launch_setup()

    def shutdown(self):
        """Clean shutdown of background listener, threads, and UI."""
        if self._is_shutting_down:
            return
        self._is_shutting_down = True
        print(f"\n{APP_NAME} shutting down cleanly...", flush=True)

        try:
            self.orchestrator.stop()
        except Exception as e:
            print(f"[Warning] Error stopping orchestrator: {e}", flush=True)

        try:
            self.window.dismiss()
            self.window.close()
        except Exception:
            pass

        self.qapp.quit()

    def run(self, check_prereqs: bool = True) -> int:
        """Starts the application and enters the Qt main loop with Ctrl+C support."""
        self.start(check_prereqs=check_prereqs)

        # Allow Python interpreter to process signals (Ctrl+C) periodically
        sigint_timer = QTimer()
        sigint_timer.setInterval(400)
        sigint_timer.timeout.connect(lambda: None)
        sigint_timer.start()

        signal.signal(signal.SIGINT, lambda *args: self.shutdown())

        return self.qapp.exec()


def run_embedded_backend(host: str = "127.0.0.1", port: int = 8000):
    """Runs the FastAPI backend via uvicorn in an isolated process."""
    import uvicorn
    from backend.main import app
    from desktop.utils.logger import setup_safe_logging

    setup_safe_logging()
    uvicorn.run(app, host=host, port=port, log_level="info")


def main():
    """Application entrypoint."""
    import multiprocessing
    multiprocessing.freeze_support()

    # If invoked with --backend, run the embedded backend server directly
    if "--backend" in sys.argv:
        from desktop.utils.config import BACKEND_HOST, BACKEND_PORT
        host = BACKEND_HOST
        port = BACKEND_PORT
        for i, arg in enumerate(sys.argv):
            if arg == "--host" and i + 1 < len(sys.argv):
                host = sys.argv[i + 1]
            elif arg == "--port" and i + 1 < len(sys.argv):
                try:
                    port = int(sys.argv[i + 1])
                except ValueError:
                    pass
        run_embedded_backend(host=host, port=port)
        sys.exit(0)

    setup_safe_logging()
    app = KyaRayApplication()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
