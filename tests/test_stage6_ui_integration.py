"""
tests/test_stage6_ui_integration.py - Automated Stage 6 UI & Update Controller Integration Tests.

Validates all 18 requirements:
1. Up-to-date result
2. Update available result
3. Stable channel filtering
4. Beta channel filtering
5. GitHub API timeout / offline failure
6. GitHub rate-limit response
7. Download progress updates via signals
8. Download cancellation via UI
9. Download failure handling
10. Checksum verification handling
11. Restart confirmation flow (never restart unconfirmed)
12. Detached updater handoff invocation
13. Handoff failure handling
14. Closing application during update check
15. Closing application during download
16. No duplicate concurrent checks or downloads
17. Thread safety: no UI widget updates from worker threads
18. No unexpected application restart
"""

import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from desktop.app import KyaRayApplication
from desktop.ui.bubble import AssistantBubbleWindow
from desktop.ui.update_controller import (
    DownloadProgress,
    DownloadResult,
    DownloadStatus,
    UpdateCheckResult,
    UpdateCheckStatus,
    UpdateController,
    UpdateUIState,
)
from desktop.ui.update_window import UpdateWindow
from desktop.updater.models import ReleaseAsset, ReleaseInfo
from version import SemVer


@pytest.fixture(scope="session")
def qapp():
    """Session-scoped QApplication instance for UI testing."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def process_qt_events():
    """Processes pending events on Qt main loop."""
    QCoreApplication.processEvents()


# =============================================================================
# Helper Fixtures & Objects
# =============================================================================

def make_dummy_release(version_str: str = "1.0.0-beta.2", is_prerelease: bool = True) -> ReleaseInfo:
    payload = ReleaseAsset(
        name=f"Kya-Ray-{version_str}-windows-x86_64.zip",
        download_url="https://github.com/test/download.zip",
        size_bytes=15_000_000,
        content_type="application/zip",
    )
    checksum = ReleaseAsset(
        name=f"Kya-Ray-{version_str}-windows-x86_64.zip.sha256",
        download_url="https://github.com/test/download.zip.sha256",
        size_bytes=64,
        content_type="text/plain",
    )
    return ReleaseInfo(
        tag_name=f"v{version_str}",
        version=SemVer.parse(version_str),
        name=f"Kya-Ray v{version_str}",
        body=f"Release notes for v{version_str}.\n- Feature Alpha\n- Bugfix Beta",
        html_url=f"https://github.com/test/releases/tag/v{version_str}",
        published_at="2026-11-11T00:00:00Z",
        is_prerelease=is_prerelease,
        is_draft=False,
        payload_asset=payload,
        checksum_asset=checksum,
    )


# =============================================================================
# Test Suite
# =============================================================================

class TestStage6UIIntegration:
    """Complete Stage 6 UI and UpdateController test suite."""

    def test_req01_up_to_date_result(self, qapp):
        """1. Up-to-date result: displays up-to-date message, shows current version, sets UP_TO_DATE."""
        mock_checker = MagicMock()
        mock_checker.get_current_version.return_value = SemVer.parse("1.0.0-beta.1")
        mock_checker.check_for_updates.return_value = UpdateCheckResult(
            status=UpdateCheckStatus.UP_TO_DATE,
            is_update_available=False,
            current_version=SemVer.parse("1.0.0-beta.1"),
        )

        controller = UpdateController(checker=mock_checker)
        window = UpdateWindow(controller=controller)
        window.show()
        process_qt_events()

        assert controller.check_for_updates(manual=True) is True
        controller._active_check_thread.join(timeout=2.0)
        process_qt_events()

        assert controller.current_state == UpdateUIState.UP_TO_DATE
        assert "up to date" in window.headline_label.text().lower()
        assert "v1.0.0-beta.1" in window.version_badge.text()
        assert window.primary_btn.text() == "Check Again"
        assert not window.notes_browser.isVisible()
        window.close()

    def test_req02_update_available_result(self, qapp):
        """2. Update available result: displays new version, release notes, changes button to Download."""
        rel = make_dummy_release("1.0.0-beta.2")
        mock_checker = MagicMock()
        mock_checker.get_current_version.return_value = SemVer.parse("1.0.0-beta.1")
        mock_checker.check_for_updates.return_value = UpdateCheckResult(
            status=UpdateCheckStatus.UPDATE_AVAILABLE,
            is_update_available=True,
            current_version=SemVer.parse("1.0.0-beta.1"),
            latest_version=SemVer.parse("1.0.0-beta.2"),
            release_info=rel,
        )

        controller = UpdateController(checker=mock_checker)
        window = UpdateWindow(controller=controller)
        window.show()
        process_qt_events()

        controller.check_for_updates(manual=True)
        controller._active_check_thread.join(timeout=2.0)
        process_qt_events()

        assert controller.current_state == UpdateUIState.UPDATE_AVAILABLE
        assert "v1.0.0-beta.2" in window.headline_label.text()
        assert window.notes_browser.isVisible()
        assert "Feature Alpha" in window.notes_browser.toPlainText()
        assert window.primary_btn.text() == "Download Update"
        assert window.secondary_btn.text() == "Later"
        window.close()

    def test_req03_stable_channel_filtering(self, qapp):
        """3. Stable channel filtering: when allow_prereleases=False, checker filters out prereleases."""
        mock_checker = MagicMock()
        mock_checker.get_current_version.return_value = SemVer.parse("1.0.0")
        mock_checker.check_for_updates.return_value = UpdateCheckResult(
            status=UpdateCheckStatus.NO_COMPATIBLE_RELEASE,
            is_update_available=False,
            current_version=SemVer.parse("1.0.0"),
        )

        controller = UpdateController(checker=mock_checker)
        controller.allow_prereleases = False
        controller.check_for_updates(manual=True)
        controller._active_check_thread.join(timeout=2.0)
        process_qt_events()

        mock_checker.check_for_updates.assert_called_once_with(
            current_version=SemVer.parse("1.0.0"),
            allow_prereleases=False,
            use_cache=False,
        )
        assert controller.current_state == UpdateUIState.UP_TO_DATE

    def test_req04_beta_channel_filtering(self, qapp):
        """4. Beta channel filtering: when allow_prereleases=True, checker queries with allow_prereleases=True."""
        rel = make_dummy_release("1.1.0-beta.1", is_prerelease=True)
        mock_checker = MagicMock()
        mock_checker.get_current_version.return_value = SemVer.parse("1.0.0")
        mock_checker.check_for_updates.return_value = UpdateCheckResult(
            status=UpdateCheckStatus.UPDATE_AVAILABLE,
            is_update_available=True,
            current_version=SemVer.parse("1.0.0"),
            latest_version=SemVer.parse("1.1.0-beta.1"),
            release_info=rel,
        )

        controller = UpdateController(checker=mock_checker)
        controller.allow_prereleases = True
        controller.check_for_updates(manual=True)
        controller._active_check_thread.join(timeout=2.0)
        process_qt_events()

        mock_checker.check_for_updates.assert_called_once_with(
            current_version=SemVer.parse("1.0.0"),
            allow_prereleases=True,
            use_cache=False,
        )
        assert controller.current_state == UpdateUIState.UPDATE_AVAILABLE

    def test_req05_github_api_timeout_offline_failure(self, qapp):
        """5. GitHub API timeout or offline failure: displays error and provides retry button."""
        mock_checker = MagicMock()
        mock_checker.get_current_version.return_value = SemVer.parse("1.0.0-beta.1")
        mock_checker.check_for_updates.return_value = UpdateCheckResult(
            status=UpdateCheckStatus.NETWORK_ERROR,
            is_update_available=False,
            current_version=SemVer.parse("1.0.0-beta.1"),
            error_message="Network unreachable",
        )

        controller = UpdateController(checker=mock_checker)
        window = UpdateWindow(controller=controller)
        window.show()
        process_qt_events()

        controller.check_for_updates(manual=True)
        controller._active_check_thread.join(timeout=2.0)
        process_qt_events()

        assert controller.current_state == UpdateUIState.ERROR
        assert window.error_card.isVisible()
        assert "internet connection" in window.error_detail.text().lower()
        assert window.primary_btn.text() == "Retry Check"
        window.close()

    def test_req06_github_rate_limit_response(self, qapp):
        """6. GitHub rate-limit response: sets ERROR state with helpful rate limit explanation."""
        mock_checker = MagicMock()
        mock_checker.get_current_version.return_value = SemVer.parse("1.0.0-beta.1")
        mock_checker.check_for_updates.return_value = UpdateCheckResult(
            status=UpdateCheckStatus.RATE_LIMITED,
            is_update_available=False,
            current_version=SemVer.parse("1.0.0-beta.1"),
            error_message="API rate limit exceeded",
        )

        controller = UpdateController(checker=mock_checker)
        window = UpdateWindow(controller=controller)
        window.show()
        process_qt_events()

        controller.check_for_updates(manual=True)
        controller._active_check_thread.join(timeout=2.0)
        process_qt_events()

        assert controller.current_state == UpdateUIState.ERROR
        assert "rate limit" in window.error_detail.text().lower()
        window.close()

    def test_req07_download_progress_updates(self, qapp):
        """7. Download progress updates: Qt signals safely deliver progress and update widgets."""
        controller = UpdateController()
        window = UpdateWindow(controller=controller)
        window.show()
        process_qt_events()

        controller.set_state(UpdateUIState.DOWNLOADING, "Downloading...")
        process_qt_events()
        assert window.progress_container.isVisible()

        # Emit DownloadProgress signal
        prog = DownloadProgress(
            downloaded_bytes=20 * 1024 * 1024,
            total_bytes=40 * 1024 * 1024,
            percent=50.0,
            speed_bytes_per_sec=4 * 1024 * 1024,
        )
        controller.bridge.sig_download_progress.emit(prog)
        process_qt_events()

        assert window.progress_bar.value() == 50
        assert "20.0 MB of 40.0 MB (50%) • 4.0 MB/s" in window.progress_stats_label.text()
        window.close()

    def test_req08_download_cancellation(self, qapp):
        """8. Download cancellation: cancel_download() sets cancel_event and transitions to DOWNLOAD_CANCELLED."""
        mock_downloader = MagicMock()
        controller = UpdateController(downloader=mock_downloader)
        controller.check_result = UpdateCheckResult(
            status=UpdateCheckStatus.UPDATE_AVAILABLE,
            is_update_available=True,
            current_version=SemVer.parse("1.0.0-beta.1"),
            latest_version=SemVer.parse("1.0.0-beta.2"),
            release_info=make_dummy_release("1.0.0-beta.2"),
        )
        window = UpdateWindow(controller=controller)
        window.show()
        process_qt_events()

        # Start download
        controller.start_download()
        process_qt_events()
        assert controller.current_state == UpdateUIState.DOWNLOADING
        assert window.primary_btn.text() == "Cancel Download"

        # User clicks cancel
        window._handle_primary_action()
        assert controller.cancel_event.is_set()

        # Simulate cancellation callback from downloader
        controller.bridge.sig_download_finished.emit(
            DownloadResult(status=DownloadStatus.CANCELLED, error_message="Cancelled by user")
        )
        process_qt_events()

        assert controller.current_state == UpdateUIState.DOWNLOAD_CANCELLED
        assert "Cancelled" in window.headline_label.text()
        assert window.primary_btn.text() == "Try Again"
        window.close()

    def test_req09_download_failure(self, qapp):
        """9. Download failure: sets DOWNLOAD_FAILED, shows error card, offers Retry Download."""
        controller = UpdateController()
        window = UpdateWindow(controller=controller)
        window.show()
        process_qt_events()

        controller.bridge.sig_download_finished.emit(
            DownloadResult(status=DownloadStatus.ERROR, error_message="Connection aborted by remote host")
        )
        process_qt_events()

        assert controller.current_state == UpdateUIState.DOWNLOAD_FAILED
        assert window.error_card.isVisible()
        assert "Connection aborted" in window.error_detail.text()
        assert window.primary_btn.text() == "Retry Download"
        window.close()

    def test_req10_checksum_verification_handling(self, qapp, tmp_path):
        """10. Checksum verification: verified=True advances to READY_TO_INSTALL; mismatch fails."""
        dummy_zip = tmp_path / "kya-ray.zip"
        dummy_zip.write_bytes(b"dummy_zip_content")

        controller = UpdateController()
        window = UpdateWindow(controller=controller)
        window.show()
        process_qt_events()

        # Test verified=True
        controller.bridge.sig_download_finished.emit(
            DownloadResult(
                status=DownloadStatus.COMPLETED,
                verified=True,
                payload_path=dummy_zip,
                sha256_hash="abc123",
            )
        )
        process_qt_events()

        assert controller.current_state == UpdateUIState.READY_TO_INSTALL
        assert window.headline_label.text() == "Ready to Install"
        assert window.primary_btn.text() == "Restart & Install"

        # Test verified=False (checksum failure)
        controller.bridge.sig_download_finished.emit(
            DownloadResult(
                status=DownloadStatus.ERROR,
                verified=False,
                error_message="Checksum mismatch: expected a but got b",
            )
        )
        process_qt_events()

        assert controller.current_state == UpdateUIState.DOWNLOAD_FAILED
        assert "Checksum mismatch" in window.error_detail.text()
        window.close()

    def test_req11_restart_confirmation_flow(self, qapp, tmp_path):
        """11. Restart confirmation: NEVER restarts without explicit user confirmation."""
        dummy_zip = tmp_path / "kya-ray.zip"
        dummy_zip.write_bytes(b"dummy_zip_content")

        controller = UpdateController()
        controller.download_result = DownloadResult(
            status=DownloadStatus.COMPLETED,
            verified=True,
            payload_path=dummy_zip,
        )
        controller.set_state(UpdateUIState.READY_TO_INSTALL)

        window = UpdateWindow(controller=controller)
        window.show()
        process_qt_events()

        # 1. User clicks "Restart & Install"
        window._handle_primary_action()
        process_qt_events()

        # Verify state is RESTART_CONFIRMATION (NOT applying update yet!)
        assert controller.current_state == UpdateUIState.RESTART_CONFIRMATION
        assert window.restart_card.isVisible()
        assert window.primary_btn.text() == "Confirm Restart"
        assert window.secondary_btn.text() == "Cancel"

        # 2. User clicks "Cancel": cancels restart confirmation and returns to READY_TO_INSTALL
        window._handle_secondary_action()
        process_qt_events()

        assert controller.current_state == UpdateUIState.READY_TO_INSTALL
        assert not window.restart_card.isVisible()
        window.close()

    def test_req12_detached_updater_handoff_invocation(self, qapp, tmp_path):
        """12. Detached updater handoff: confirmed=True calls launch_detached_updater with correct args."""
        dummy_zip = tmp_path / "kya-ray.zip"
        dummy_zip.write_bytes(b"dummy_zip_content")

        mock_backend_pid_fn = MagicMock(return_value=9999)
        controller = UpdateController(get_backend_pid_fn=mock_backend_pid_fn)
        controller.download_result = DownloadResult(
            status=DownloadStatus.COMPLETED,
            verified=True,
            payload_path=dummy_zip,
        )
        controller.check_result = UpdateCheckResult(
            status=UpdateCheckStatus.UPDATE_AVAILABLE,
            is_update_available=True,
            current_version=SemVer.parse("1.0.0-beta.1"),
            latest_version=SemVer.parse("1.0.0-beta.2"),
        )
        controller.set_state(UpdateUIState.RESTART_CONFIRMATION)

        window = UpdateWindow(controller=controller)
        window.show()
        process_qt_events()

        with patch("desktop.ui.update_controller.launch_detached_updater") as mock_launch:
            mock_launch.return_value = MagicMock()  # mock popen
            handoff_signal_received = []
            controller.bridge.sig_handoff_started.connect(lambda: handoff_signal_received.append(True))

            # Confirm restart
            window._handle_primary_action()
            process_qt_events()

            assert len(handoff_signal_received) == 1
            assert controller.current_state == UpdateUIState.APPLYING_UPDATE
            mock_launch.assert_called_once()
            call_kwargs = mock_launch.call_args[1]
            assert call_kwargs["zip_path"] == dummy_zip.resolve()
            assert call_kwargs["target_version"] == "1.0.0-beta.2"
            assert call_kwargs["gui_pid"] == os.getpid()
            assert call_kwargs["backend_pid"] == 9999
        window.close()

    def test_req13_handoff_failure_handling(self, qapp, tmp_path):
        """13. Handoff failure handling: if launcher fails, shows error and application stays alive."""
        dummy_zip = tmp_path / "kya-ray.zip"
        dummy_zip.write_bytes(b"dummy_zip_content")

        controller = UpdateController()
        controller.download_result = DownloadResult(
            status=DownloadStatus.COMPLETED,
            verified=True,
            payload_path=dummy_zip,
        )
        controller.set_state(UpdateUIState.RESTART_CONFIRMATION)

        window = UpdateWindow(controller=controller)
        window.show()
        process_qt_events()

        with patch("desktop.ui.update_controller.launch_detached_updater") as mock_launch:
            mock_launch.side_effect = PermissionError("Cannot execute detached updater binary")
            failed_signals = []
            controller.bridge.sig_handoff_failed.connect(lambda err: failed_signals.append(err))

            res = controller.request_install_and_restart(confirmed=True)
            process_qt_events()

            assert res is False
            assert len(failed_signals) == 1
            assert "Cannot execute" in failed_signals[0]
            assert controller.current_state == UpdateUIState.ERROR
            assert window.error_card.isVisible()
        window.close()

    def test_req14_closing_app_during_check(self, qapp):
        """14. Closing app during check: controller.shutdown() stops gracefully."""
        mock_checker = MagicMock()
        mock_checker.get_current_version.return_value = SemVer.parse("1.0.0-beta.1")
        def _slow_check(*args, **kwargs):
            time.sleep(0.5)
            return UpdateCheckResult(
                status=UpdateCheckStatus.UP_TO_DATE,
                is_update_available=False,
                current_version=SemVer.parse("1.0.0-beta.1"),
            )
        mock_checker.check_for_updates.side_effect = _slow_check

        controller = UpdateController(checker=mock_checker)
        controller.check_for_updates(manual=True)
        assert controller.current_state == UpdateUIState.CHECKING

        # Shutdown while check is in flight
        controller.shutdown()
        assert controller.cancel_event.is_set()

    def test_req15_closing_app_during_download(self, qapp):
        """15. Closing app during download: controller.shutdown() sets cancel_event to abort download."""
        controller = UpdateController()
        controller.set_state(UpdateUIState.DOWNLOADING)

        controller.shutdown()
        assert controller.cancel_event.is_set()

    def test_req16_no_duplicate_concurrent_checks_or_downloads(self, qapp):
        """16. No duplicate operations: skips checks/downloads if already in progress or within cooldown."""
        controller = UpdateController()
        controller.current_state = UpdateUIState.CHECKING
        assert controller.check_for_updates() is False

        controller.current_state = UpdateUIState.DOWNLOADING
        assert controller.check_for_updates() is False
        assert controller.start_download() is False

        # Background cooldown test
        controller.current_state = UpdateUIState.IDLE
        controller.last_check_timestamp = time.time()
        # Non-manual check within 4h cooldown should return False
        assert controller.check_for_updates(manual=False) is False
        # Force or manual check bypasses cooldown
        assert controller.check_for_updates(manual=True) is True

    def test_req17_thread_safety_no_direct_widget_updates_from_worker(self, qapp):
        """17. Thread safety: worker threads emit Qt signals; no cross-thread widget mutation."""
        controller = UpdateController()
        window = UpdateWindow(controller=controller)
        window.show()
        process_qt_events()

        worker_thread_id = None
        main_thread_id = threading.get_ident()

        def _worker():
            nonlocal worker_thread_id
            worker_thread_id = threading.get_ident()
            # Worker emits signal instead of calling widget directly
            controller.bridge.sig_state_changed.emit("idle", "Worker thread safe message")

        th = threading.Thread(target=_worker)
        th.start()
        th.join()

        process_qt_events()
        assert worker_thread_id != main_thread_id
        assert window.desc_label.text() == "Worker thread safe message"
        window.close()

    def test_req18_no_unexpected_application_restart(self, qapp, tmp_path):
        """18. No unexpected restart: application shutdown is only called upon confirmed handoff."""
        dummy_zip = tmp_path / "kya-ray.zip"
        dummy_zip.write_bytes(b"dummy_zip_content")

        with patch("desktop.app.AppOrchestrator"):
            app_instance = KyaRayApplication(qapp=qapp)
            app_instance.shutdown = MagicMock()

            # Simulate download finished and ready to install
            app_instance.update_controller.download_result = DownloadResult(
                status=DownloadStatus.COMPLETED,
                verified=True,
                payload_path=dummy_zip,
            )
            app_instance.update_controller.set_state(UpdateUIState.READY_TO_INSTALL)
            process_qt_events()

            # At READY_TO_INSTALL, app must NOT shut down
            assert not app_instance.shutdown.called

            # Request install without confirmation
            app_instance.update_controller.request_install_and_restart(confirmed=False)
            process_qt_events()
            assert not app_instance.shutdown.called

            # Now confirm install with mock launch
            with patch("desktop.ui.update_controller.launch_detached_updater") as mock_launch:
                mock_launch.return_value = MagicMock()
                app_instance.update_controller.request_install_and_restart(confirmed=True)
                process_qt_events()

                # ONLY now should shutdown be invoked
                assert app_instance.shutdown.called

    def test_req19_dialog_reopening_sync(self, qapp):
        """19. Reopening synchronization: reopening window after error or state change synchronizes UI."""
        controller = UpdateController()
        window = UpdateWindow(controller=controller)
        window.show()
        process_qt_events()

        # Simulate update check error while window is open
        controller.set_state(UpdateUIState.ERROR, "GitHub API timeout during check")
        process_qt_events()
        assert window.error_card.isVisible()
        assert window.primary_btn.text() == "Retry Check"

        # User closes window
        window.close()
        process_qt_events()

        # Controller state advances while window is closed
        controller.set_state(UpdateUIState.UP_TO_DATE, "Kya-Ray is up to date.")

        # User reopens window: showEvent must synchronize UI
        window.show()
        process_qt_events()

        assert not window.error_card.isVisible()
        assert "up to date" in window.headline_label.text().lower()
        assert window.primary_btn.text() == "Check Again"
        window.close()

    def test_req20_close_event_cancels_restart_confirmation(self, qapp, tmp_path):
        """20. Close event handling: closing window during RESTART_CONFIRMATION cancels confirmation safely."""
        dummy_zip = tmp_path / "kya-ray.zip"
        dummy_zip.write_bytes(b"dummy_zip_content")

        controller = UpdateController()
        controller.download_result = DownloadResult(
            status=DownloadStatus.COMPLETED,
            verified=True,
            payload_path=dummy_zip,
        )
        controller.set_state(UpdateUIState.RESTART_CONFIRMATION)

        window = UpdateWindow(controller=controller)
        window.show()
        process_qt_events()
        assert window.restart_card.isVisible()

        # User closes window (e.g. clicking [X] or pressing Escape)
        window.close()
        process_qt_events()

        # State safely reverts to READY_TO_INSTALL
        assert controller.current_state == UpdateUIState.READY_TO_INSTALL
        window.close()
