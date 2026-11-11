"""
desktop/ui/update_controller.py - Update State Machine and Background Thread Coordinator.

Coordinates update detection, streaming downloads, SHA-256 verification, and
safe handoff to the detached standalone updater while ensuring thread safety with Qt.
"""

import logging
import os
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, Union

from PySide6.QtCore import QObject, Signal

from desktop.updater.checker import UpdateChecker, get_current_version
from desktop.updater.cli import launch_detached_updater
from desktop.updater.downloader import (
    DownloadProgress,
    DownloadResult,
    DownloadStatus,
    ReleaseAsset,
    UpdateDownloader,
)
from desktop.updater.models import (
    ReleaseInfo,
    UpdateCheckResult,
    UpdateCheckStatus,
)
from version import SemVer

logger = logging.getLogger("kya_ray.ui.updater")


class UpdateUIState(str, Enum):
    IDLE = "idle"
    CHECKING = "checking"
    UP_TO_DATE = "up_to_date"
    UPDATE_AVAILABLE = "update_available"
    DOWNLOADING = "downloading"
    DOWNLOAD_CANCELLED = "download_cancelled"
    DOWNLOAD_FAILED = "download_failed"
    DOWNLOAD_VERIFIED = "download_verified"
    READY_TO_INSTALL = "ready_to_install"
    RESTART_CONFIRMATION = "restart_confirmation"
    APPLYING_UPDATE = "applying_update"
    ERROR = "error"


class UpdateSignalBridge(QObject):
    """
    Qt Signal Bridge ensuring all worker callbacks emit signals delivered
    safely onto the Qt main GUI thread.
    """
    sig_state_changed = Signal(str, str)          # state_name, display_message
    sig_check_started = Signal()
    sig_check_finished = Signal(object)           # UpdateCheckResult
    sig_download_started = Signal()
    sig_download_progress = Signal(object)        # DownloadProgress
    sig_download_finished = Signal(object)       # DownloadResult
    sig_handoff_started = Signal()
    sig_handoff_failed = Signal(str)              # error_message
    sig_update_available_alert = Signal(object)   # UpdateCheckResult


class UpdateController(QObject):
    """
    Orchestrates the entire update workflow for the UI without blocking GUI events.
    """

    BACKGROUND_COOLDOWN_SECONDS = 3600 * 4  # 4 hours between background checks

    def __init__(
        self,
        parent: Optional[QObject] = None,
        checker: Optional[UpdateChecker] = None,
        downloader: Optional[UpdateDownloader] = None,
        get_backend_pid_fn: Optional[Callable[[], Optional[int]]] = None,
    ):
        super().__init__(parent)
        self.checker = checker or UpdateChecker()
        self.downloader = downloader or UpdateDownloader()
        self._get_backend_pid_fn = get_backend_pid_fn

        self.bridge = UpdateSignalBridge()

        # Connect internal signal delivery to main-thread slots
        self.bridge.sig_check_finished.connect(self._on_check_finished_slot)
        self.bridge.sig_download_progress.connect(self._on_download_progress_slot)
        self.bridge.sig_download_finished.connect(self._on_download_finished_slot)

        self.current_state = UpdateUIState.IDLE
        self.status_message = "Ready"

        self.current_version: SemVer = self.checker.get_current_version()
        self.allow_prereleases: bool = self.current_version.is_prerelease

        self.check_result: Optional[UpdateCheckResult] = None
        self.download_result: Optional[DownloadResult] = None
        self.download_progress: Optional[DownloadProgress] = None

        self.cancel_event = threading.Event()
        self.last_check_timestamp: float = 0.0

        self._active_download_thread: Optional[threading.Thread] = None
        self._active_check_thread: Optional[threading.Thread] = None

    # -------------------------------------------------------------------------
    # State Management Helper
    # -------------------------------------------------------------------------
    def set_state(self, state: UpdateUIState, message: str = ""):
        self.current_state = state
        self.status_message = message
        self.bridge.sig_state_changed.emit(state.value, message)

    # -------------------------------------------------------------------------
    # Update Checking Flow
    # -------------------------------------------------------------------------
    def check_for_updates(
        self,
        manual: bool = True,
        force: bool = False,
        allow_prereleases: Optional[bool] = None,
    ) -> bool:
        """
        Initiates an update check outside the UI thread.
        Returns True if a check was started, False if busy or rate-limited by cooldown.
        """
        # Prevent concurrent check or download collision
        if self.current_state in (
            UpdateUIState.CHECKING,
            UpdateUIState.DOWNLOADING,
            UpdateUIState.APPLYING_UPDATE,
        ):
            logger.debug("Update check skipped: updater is currently %s", self.current_state)
            return False

        now = time.time()
        if not manual and not force:
            if now - self.last_check_timestamp < self.BACKGROUND_COOLDOWN_SECONDS:
                logger.debug("Background check skipped: within cooldown window")
                return False

        if allow_prereleases is not None:
            self.allow_prereleases = bool(allow_prereleases)

        self.set_state(UpdateUIState.CHECKING, "Checking GitHub for updates...")
        self.bridge.sig_check_started.emit()

        def _worker():
            try:
                # Use cache only for background checks; manual check bypasses cache
                res = self.checker.check_for_updates(
                    current_version=self.current_version,
                    allow_prereleases=self.allow_prereleases,
                    use_cache=not manual,
                )
            except Exception as e:
                logger.error("Error during update check: %s", e)
                res = UpdateCheckResult(
                    status=UpdateCheckStatus.ERROR,
                    is_update_available=False,
                    current_version=self.current_version,
                    error_message=str(e),
                )
            self.bridge.sig_check_finished.emit(res)

        self._active_check_thread = threading.Thread(
            target=_worker,
            name="KyaRayUpdateCheckWorker",
            daemon=True,
        )
        self._active_check_thread.start()
        return True

    def _on_check_finished_slot(self, result: UpdateCheckResult):
        """Processes update check outcome on Qt main thread."""
        self.last_check_timestamp = time.time()
        self.check_result = result

        if result.is_update_available and result.release_info:
            # Verification prerequisite: Release must have installable ZIP AND SHA-256 asset
            if result.is_verifiable:
                latest_ver_str = str(result.latest_version or result.release_info.version)
                msg = f"Version {latest_ver_str} is available."
                self.set_state(UpdateUIState.UPDATE_AVAILABLE, msg)
                self.bridge.sig_update_available_alert.emit(result)
            else:
                msg = "A newer release was found, but it lacks a verifiable SHA-256 checksum asset."
                self.set_state(UpdateUIState.ERROR, msg)
        elif result.status == UpdateCheckStatus.UP_TO_DATE:
            self.set_state(UpdateUIState.UP_TO_DATE, f"Kya-Ray is up to date (v{self.current_version}).")
        elif result.status == UpdateCheckStatus.RATE_LIMITED:
            self.set_state(UpdateUIState.ERROR, "GitHub API rate limit reached. Please try again in a few minutes.")
        elif result.status == UpdateCheckStatus.NETWORK_ERROR:
            self.set_state(UpdateUIState.ERROR, "Unable to reach GitHub. Check your internet connection.")
        elif result.status == UpdateCheckStatus.NO_COMPATIBLE_RELEASE:
            self.set_state(UpdateUIState.UP_TO_DATE, f"No newer releases available for {self.current_version}.")
        else:
            err = result.error_message or "Could not complete update check."
            self.set_state(UpdateUIState.ERROR, err)

    # -------------------------------------------------------------------------
    # Download & Verification Flow
    # -------------------------------------------------------------------------
    def start_download(self, destination_dir: Optional[Union[str, Path]] = None) -> bool:
        """
        Starts downloading and verifying the available release package in the background.
        """
        if self.current_state == UpdateUIState.DOWNLOADING:
            return False

        if not self.check_result or not self.check_result.release_info:
            self.set_state(UpdateUIState.ERROR, "No update package available to download.")
            return False

        payload_asset = self.check_result.release_info.payload_asset
        checksum_asset = self.check_result.release_info.checksum_asset

        if not payload_asset:
            self.set_state(UpdateUIState.ERROR, "Release package payload asset not found.")
            return False

        self.cancel_event.clear()
        self.download_progress = None
        self.set_state(UpdateUIState.DOWNLOADING, "Downloading update package...")
        self.bridge.sig_download_started.emit()

        def _prog_cb(prog: DownloadProgress):
            self.bridge.sig_download_progress.emit(prog)

        def _done_cb(res: DownloadResult):
            self.bridge.sig_download_finished.emit(res)

        self._active_download_thread = self.downloader.download_and_verify_async(
            payload_asset=payload_asset,
            checksum_asset=checksum_asset,
            destination_dir=destination_dir,
            progress_callback=_prog_cb,
            cancel_event=self.cancel_event,
            callback=_done_cb,
            overwrite=True,
        )
        return True

    def cancel_download(self) -> None:
        """Signals active download worker to cancel and clean up partial files."""
        if self.current_state == UpdateUIState.DOWNLOADING:
            self.cancel_event.set()

    def _on_download_progress_slot(self, prog: DownloadProgress):
        """Delivers download progress on the Qt GUI thread."""
        self.download_progress = prog
        if self.current_state == UpdateUIState.DOWNLOADING:
            mb_down = prog.downloaded_bytes / (1024 * 1024)
            if prog.total_bytes and prog.total_bytes > 0:
                mb_total = prog.total_bytes / (1024 * 1024)
                pct = prog.percent or (prog.downloaded_bytes / prog.total_bytes * 100)
                speed_mb = prog.speed_bytes_per_sec / (1024 * 1024)
                msg = f"{mb_down:.1f} MB of {mb_total:.1f} MB ({pct:.0f}%) • {speed_mb:.1f} MB/s"
            else:
                msg = f"{mb_down:.1f} MB downloaded"
            self.status_message = msg
            self.bridge.sig_state_changed.emit(self.current_state.value, msg)

    def _on_download_finished_slot(self, result: DownloadResult):
        """Delivers download completion on the Qt GUI thread."""
        self.download_result = result
        if result.status == DownloadStatus.COMPLETED and result.verified:
            self.set_state(UpdateUIState.DOWNLOAD_VERIFIED, "SHA-256 verified successfully.")
            self.set_state(UpdateUIState.READY_TO_INSTALL, "Update is ready to install.")
        elif result.status == DownloadStatus.CANCELLED:
            self.set_state(UpdateUIState.DOWNLOAD_CANCELLED, "Download was cancelled.")
        else:
            err = result.error_message or "Download failed"
            self.set_state(UpdateUIState.DOWNLOAD_FAILED, f"Download failed: {err}")

    # -------------------------------------------------------------------------
    # Installation & Detached Updater Handoff Flow
    # -------------------------------------------------------------------------
    def request_install_and_restart(
        self,
        confirmed: bool = False,
        install_dir: Optional[Union[str, Path]] = None,
        data_dir: Optional[Union[str, Path]] = None,
    ) -> bool:
        """
        Executes update handoff to the detached standalone updater.
        Crucial: Never restarts without confirmed == True.
        """
        if not self.download_result or not self.download_result.verified or not self.download_result.payload_path:
            self.set_state(UpdateUIState.ERROR, "Cannot install: update package has not been verified.")
            return False

        if not confirmed:
            self.set_state(UpdateUIState.RESTART_CONFIRMATION, "Confirm restart to apply update.")
            return False

        self.set_state(UpdateUIState.APPLYING_UPDATE, "Launching updater and preparing application restart...")

        try:
            zip_path = Path(self.download_result.payload_path).resolve()
            if not zip_path.is_file():
                raise FileNotFoundError(f"Verified release archive not found at {zip_path}")

            target_version = (
                str(self.check_result.latest_version)
                if self.check_result and self.check_result.latest_version
                else "latest"
            )

            gui_pid = os.getpid()
            backend_pid = self._get_backend_pid_fn() if self._get_backend_pid_fn else None

            # Launch detached standalone updater process outside install_dir
            proc = launch_detached_updater(
                zip_path=zip_path,
                target_version=target_version,
                gui_pid=gui_pid,
                backend_pid=backend_pid,
                install_dir=Path(install_dir) if install_dir else None,
                data_dir=Path(data_dir) if data_dir else None,
            )

            if proc is None:
                raise RuntimeError("Failed to spawn detached updater process.")

            self.bridge.sig_handoff_started.emit()
            return True

        except Exception as e:
            logger.error("Failed to launch detached updater: %s", e)
            self.set_state(UpdateUIState.ERROR, f"Could not launch updater: {e}")
            self.bridge.sig_handoff_failed.emit(str(e))
            return False

    # -------------------------------------------------------------------------
    # Lifecycle Cleanup
    # -------------------------------------------------------------------------
    def shutdown(self):
        """Cancels any in-flight download and ensures clean background thread exit."""
        self.cancel_event.set()

