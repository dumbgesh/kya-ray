"""
tests/test_post_update_race_fix.py - Regression Test Suite for Post-Update Startup Race Condition.

Validates the fix for the race condition where a newly spawned application
instance executing the post-update readiness handshake attempted to roll back
its own installation while the parent installer transaction was actively running.

Test Matrix:
1. Fresh Beta.3 launch (no transaction record).
2. Beta.2 -> Beta.3 update with live handshake validation (active installer PID protection).
3. Handshake child process bypasses recovery check via KYA_RAY_HANDSHAKE_FILE.
4. Genuine interrupted transaction recovery when installer PID is dead.
5. Failed startup handshake triggers clean rollback and backup preservation.
6. Preservation of user .env and config across both success and rollback paths.
7. In-place execution safety (process executing from install_dir never partially deletes itself).
8. Repeated application launches after commit.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from desktop.updater.installer import UpdateInstaller, is_pid_running
from desktop.updater.models import (
    InstallationResult,
    RollbackStatus,
    TransactionRecord,
    TransactionState,
)
from desktop.updater.registry import RegistryManager


@pytest.fixture
def isolated_dirs(tmp_path):
    install_dir = tmp_path / "Programs" / "Kya-Ray"
    data_dir = tmp_path / "data"
    staging_dir = tmp_path / "Programs" / ".kya-ray-staging-test"
    backup_dir = tmp_path / "Programs" / "Kya-Ray.backup-tx-test"

    install_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Base Beta.2 executable and files
    exe_file = install_dir / "Kya-Ray.exe"
    exe_file.write_bytes(b"MZ" + b"\x00" * 2048)

    plugins_dir = install_dir / "_internal" / "PySide6" / "plugins" / "platforms"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    (plugins_dir / "qwindows.dll").write_bytes(b"MZ_QT_PLUGIN")

    # User .env file
    env_file = install_dir / ".env"
    env_file.write_text("GROQ_API_KEY=gsk_preserved_secret_key_12345\n", encoding="utf-8")

    return install_dir, data_dir, staging_dir, backup_dir


class TestPostUpdateRaceConditionFix:

    def test_1_fresh_launch_without_transaction(self, isolated_dirs):
        """Fresh application launch with no transaction record performs no recovery."""
        install_dir, data_dir, _, _ = isolated_dirs
        installer = UpdateInstaller(install_dir=install_dir, data_dir=data_dir)

        result = installer.recover_interrupted_transaction()
        assert result is None
        assert (install_dir / "Kya-Ray.exe").is_file()
        assert (install_dir / ".env").is_file()

    def test_2_active_installer_process_skips_recovery(self, isolated_dirs):
        """
        When update_transaction.json has an active installer_pid, any concurrent process
        (child handshake or sibling launch) skips recovery without modifying files.
        """
        install_dir, data_dir, staging_dir, backup_dir = isolated_dirs
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / "Kya-Ray.exe").write_bytes(b"MZ" + b"\x00" * 1024)

        # Mock an active running installer PID (e.g. current process or PID 88888)
        active_installer_pid = 88888
        mock_pid_checker = MagicMock(side_effect=lambda pid: pid == active_installer_pid)

        # Record an ongoing transaction in INSTALLED state
        record = {
            "transaction_id": "tx-active-123",
            "state": TransactionState.INSTALLED.value,
            "previous_version": "1.0.0-beta.2",
            "target_version": "1.0.0-beta.3",
            "install_dir": str(install_dir),
            "backup_dir": str(backup_dir),
            "staging_dir": str(staging_dir),
            "preserve_env": True,
            "timestamp": time.time(),
            "installer_pid": active_installer_pid,
        }
        tx_file = data_dir / UpdateInstaller.TRANSACTION_FILE
        tx_file.write_text(json.dumps(record), encoding="utf-8")

        # Now simulate another process (child process with different PID) calling recovery
        child_installer = UpdateInstaller(
            install_dir=install_dir,
            data_dir=data_dir,
            pid_checker=mock_pid_checker,
        )

        with patch("os.getpid", return_value=99999):  # Child PID != installer PID
            result = child_installer.recover_interrupted_transaction()

        # Recovery MUST return None (skipped) because installer is actively running
        assert result is None
        # Transaction file must NOT be cleared or modified
        assert tx_file.is_file()
        # Backup directory must remain intact outside install_dir
        assert backup_dir.is_dir()
        # Target installation files and qwindows.dll must NOT be touched
        qwin = install_dir / "_internal" / "PySide6" / "plugins" / "platforms" / "qwindows.dll"
        assert qwin.is_file(), "qwindows.dll must not be deleted while installer is active!"

    def test_3_handshake_env_var_skips_recovery_in_app_startup(self, monkeypatch):
        """desktop/app.py skips transaction recovery entirely when KYA_RAY_HANDSHAKE_FILE is set."""
        from desktop import app

        mock_installer_cls = MagicMock()
        mock_installer_instance = MagicMock()
        mock_installer_cls.return_value = mock_installer_instance

        # Simulate presence of handshake environment variable
        monkeypatch.setenv("KYA_RAY_HANDSHAKE_FILE", "C:/fake/ready.json")

        with patch("desktop.updater.installer.UpdateInstaller", mock_installer_cls):
            with patch("desktop.app.KyaRayApplication") as mock_app_cls:
                mock_app_instance = MagicMock()
                mock_app_instance.run.return_value = 0
                mock_app_cls.return_value = mock_app_instance

                # Run app.main()
                with pytest.raises(SystemExit) as exc:
                    app.main()
                assert exc.value.code == 0

        # UpdateInstaller must NOT even be instantiated when KYA_RAY_HANDSHAKE_FILE is set
        mock_installer_cls.assert_not_called()

    def test_4_genuine_interrupted_transaction_recovery_when_installer_pid_dead(self, isolated_dirs):
        """When the installer process has crashed (PID dead), recovery properly restores the backup."""
        install_dir, data_dir, staging_dir, backup_dir = isolated_dirs
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / "Kya-Ray.exe").write_bytes(b"MZ" + b"\x00" * 2048)
        (backup_dir / ".env").write_text("GROQ_API_KEY=backup_secret\n", encoding="utf-8")

        dead_installer_pid = 77777
        mock_pid_checker = MagicMock(return_value=False)  # PID is dead

        record = {
            "transaction_id": "tx-crashed-456",
            "state": TransactionState.INSTALLING.value,
            "previous_version": "1.0.0-beta.2",
            "target_version": "1.0.0-beta.3",
            "install_dir": str(install_dir),
            "backup_dir": str(backup_dir),
            "staging_dir": str(staging_dir),
            "preserve_env": True,
            "timestamp": time.time() - 300,
            "installer_pid": dead_installer_pid,
        }
        tx_file = data_dir / UpdateInstaller.TRANSACTION_FILE
        tx_file.write_text(json.dumps(record), encoding="utf-8")

        installer = UpdateInstaller(
            install_dir=install_dir,
            data_dir=data_dir,
            pid_checker=mock_pid_checker,
        )

        result = installer.recover_interrupted_transaction()

        assert result is not None
        assert result.rollback_status == RollbackStatus.SUCCEEDED
        assert not tx_file.exists()
        assert (install_dir / "Kya-Ray.exe").is_file()
        assert "backup_secret" in (install_dir / ".env").read_text(encoding="utf-8")

    def test_5_failed_startup_handshake_triggers_clean_parent_rollback(self, isolated_dirs, tmp_path):
        """
        When the spawned process fails the readiness handshake, the parent installer
        cleanly terminates the child, preserves the backup, and restores previous installation.
        """
        install_dir, data_dir, _, _ = isolated_dirs
        mock_registry = RegistryManager(mock_store={"DisplayVersion": "1.0.0-beta.2"})

        # Mock child process that hangs / never writes handshake
        hanging_child = MagicMock()
        hanging_child.poll.return_value = None
        hanging_child.terminate = MagicMock()
        hanging_child.wait = MagicMock()
        app_launcher = MagicMock(return_value=hanging_child)

        installer = UpdateInstaller(
            install_dir=install_dir,
            data_dir=data_dir,
            registry_manager=mock_registry,
            app_launcher=app_launcher,
            handshake_timeout=0.2,
        )

        # Create dummy update zip using test_installer's create_test_zip
        from tests.test_installer import create_test_zip
        update_zip = tmp_path / "test_update.zip"
        create_test_zip(update_zip, extra_files={"new_marker.txt": b"NEW"})

        result = installer.install(
            zip_path=update_zip,
            target_version="1.0.0-beta.3",
            restart_after=True,
        )

        assert result.success is False
        assert result.rollback_status == RollbackStatus.SUCCEEDED
        assert hanging_child.terminate.called
        # Original version restored
        assert (install_dir / "Kya-Ray.exe").is_file()
        assert not (install_dir / "new_marker.txt").exists()
        # Original user .env preserved
        assert "gsk_preserved_secret_key_12345" in (install_dir / ".env").read_text(encoding="utf-8")
        assert mock_registry.get_display_version() == "1.0.0-beta.2"

    def test_6_successful_update_lifecycle_commits_and_cleans_backup(self, isolated_dirs, tmp_path):
        """
        Full lifecycle test: successful update with valid handshake writes .ready file,
        commits transaction, removes backup, and preserves user configuration.
        """
        install_dir, data_dir, _, _ = isolated_dirs
        mock_registry = RegistryManager(mock_store={"DisplayVersion": "1.0.0-beta.2"})

        running_child = MagicMock()
        running_child.poll.return_value = None
        running_child.pid = 4321

        def launcher_with_handshake(exe_path):
            handshake = os.environ.get("KYA_RAY_HANDSHAKE_FILE")
            if handshake:
                with open(handshake, "w", encoding="utf-8") as f:
                    json.dump({"status": "ready", "version": "1.0.0-beta.3", "pid": 4321}, f)
            return running_child

        app_launcher = MagicMock(side_effect=launcher_with_handshake)

        installer = UpdateInstaller(
            install_dir=install_dir,
            data_dir=data_dir,
            registry_manager=mock_registry,
            app_launcher=app_launcher,
            handshake_timeout=1.0,
        )

        from tests.test_installer import create_test_zip
        update_zip = tmp_path / "beta3_update.zip"
        create_test_zip(update_zip, extra_files={"beta3_feature.txt": b"BETA3_ACTIVE"})

        result = installer.install(
            zip_path=update_zip,
            target_version="1.0.0-beta.3",
            restart_after=True,
        )

        assert result.success is True
        assert result.installed_version == "1.0.0-beta.3"
        assert result.restarted is True
        assert result.rollback_status == RollbackStatus.NOT_NEEDED

        # Verified files
        assert (install_dir / "beta3_feature.txt").is_file()
        assert (install_dir / ".env").is_file()
        assert "gsk_preserved_secret_key_12345" in (install_dir / ".env").read_text(encoding="utf-8")

        # Cleanup verified: transaction file and backup directory must NOT remain
        assert not (data_dir / UpdateInstaller.TRANSACTION_FILE).exists()
        backups = list(install_dir.parent.glob("Kya-Ray.backup-*"))
        assert len(backups) == 0, f"Expected backup to be deleted after commit, found: {backups}"

    def test_7_in_place_execution_safety_preserves_backup_without_deleting(self, isolated_dirs):
        """
        If a process starts from inside install_dir while state is uncommitted (INSTALLED or VALIDATING)
        and installer is dead, it must NEVER delete backup_dir. It must report rollback failure and
        preserve the known-good backup intact for external recovery.
        """
        install_dir, data_dir, staging_dir, backup_dir = isolated_dirs
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / "Kya-Ray.exe").write_bytes(b"MZ" + b"\x00" * 1024)

        record = {
            "transaction_id": "tx-uncommitted-preserve",
            "state": TransactionState.INSTALLED.value,
            "previous_version": "1.0.0-beta.2",
            "target_version": "1.0.0-beta.3",
            "install_dir": str(install_dir),
            "backup_dir": str(backup_dir),
            "staging_dir": str(staging_dir),
            "preserve_env": True,
            "timestamp": time.time(),
            "installer_pid": 65432,  # Dead PID
        }
        tx_file = data_dir / UpdateInstaller.TRANSACTION_FILE
        tx_file.write_text(json.dumps(record), encoding="utf-8")

        installer = UpdateInstaller(
            install_dir=install_dir,
            data_dir=data_dir,
            pid_checker=lambda pid, start_time=None: False,  # installer dead
        )

        # Mock sys.executable to be inside install_dir
        with patch.object(sys, "executable", str(install_dir / "Kya-Ray.exe")):
            result = installer.recover_interrupted_transaction()

        # Must report failure to halt startup, but backup_dir MUST remain intact!
        assert result is not None
        assert result.success is False
        assert result.rollback_status == RollbackStatus.FAILED
        assert "Cannot perform rollback" in result.error_message
        assert backup_dir.is_dir(), "CRITICAL: backup_dir must NEVER be deleted during in-place recovery!"
        assert (backup_dir / "Kya-Ray.exe").is_file()
        assert tx_file.is_file(), "Transaction record preserved for external diagnosis"

    def test_8_backward_compatibility_record_without_pid_or_start_time(self, isolated_dirs):
        """Older transaction records omitting installer_pid or installer_start_time recover safely."""
        install_dir, data_dir, staging_dir, backup_dir = isolated_dirs
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / "Kya-Ray.exe").write_bytes(b"MZ" + b"\x00" * 2048)

        # Legacy transaction format without installer_pid or installer_start_time
        record = {
            "transaction_id": "tx-legacy-record",
            "state": TransactionState.INSTALLED.value,
            "previous_version": "1.0.0-beta.2",
            "target_version": "1.0.0-beta.3",
            "install_dir": str(install_dir),
            "backup_dir": str(backup_dir),
            "staging_dir": str(staging_dir),
            "preserve_env": True,
            "timestamp": time.time(),
        }
        tx_file = data_dir / UpdateInstaller.TRANSACTION_FILE
        tx_file.write_text(json.dumps(record), encoding="utf-8")

        installer = UpdateInstaller(install_dir=install_dir, data_dir=data_dir)
        result = installer.recover_interrupted_transaction()

        assert result is not None
        assert result.rollback_status == RollbackStatus.SUCCEEDED
        assert (install_dir / "Kya-Ray.exe").is_file()
        assert not tx_file.exists()

    def test_9_real_subprocess_pid_detection_and_reuse_protection(self):
        """Integration test with real Windows subprocess verifying PID detection and start-time validation."""
        import subprocess
        from desktop.updater.installer import get_process_start_time

        # Launch genuine python subprocess sleeping for 5 seconds
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            real_pid = proc.pid
            real_start = get_process_start_time(real_pid)
            assert real_start is not None, "get_process_start_time must return int timestamp for real process"

            # 1. Matching start time -> alive
            assert is_pid_running(real_pid, expected_start_time=real_start) is True

            # 2. None expected start time -> alive
            assert is_pid_running(real_pid, expected_start_time=None) is True

            # 3. Mismatched start time (simulating PID reuse) -> MUST return False!
            fake_start = real_start + 12345678
            assert is_pid_running(real_pid, expected_start_time=fake_start) is False

        finally:
            proc.terminate()
            proc.wait(timeout=3.0)

        # 4. Terminated process -> returns False
        assert is_pid_running(real_pid, expected_start_time=real_start) is False

    def test_10_real_subprocess_child_handshake_lifecycle(self, isolated_dirs):
        """
        Integration test spawning a real Python subprocess executing the handshake protocol.
        Verifies live parent updater reading real handshake file written by real child.
        """
        install_dir, data_dir, _, _ = isolated_dirs
        installer = UpdateInstaller(
            install_dir=install_dir,
            data_dir=data_dir,
            handshake_timeout=5.0,
        )

        child_code = (
            "import os, json, sys, time\n"
            "handshake = os.environ.get('KYA_RAY_HANDSHAKE_FILE')\n"
            "if handshake:\n"
            "    with open(handshake, 'w') as f:\n"
            "        json.dump({'status': 'ready', 'version': '1.0.0-beta.3', 'pid': os.getpid()}, f)\n"
            "time.sleep(2)\n"
        )

        proc_holder = []
        base_exe = getattr(sys, "_base_executable", sys.executable)

        def real_app_launcher(exe_path):
            p = subprocess.Popen(
                [base_exe, "-c", child_code],
                env=os.environ.copy(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            proc_holder.append(p)
            return p

        installer._app_launcher = real_app_launcher
        try:
            ok, err = installer._restart_and_validate(target_version="1.0.0-beta.3")
            assert ok is True, f"Handshake failed with error: {err}"
            assert err is None
        finally:
            for p in proc_holder:
                p.terminate()
                p.wait(timeout=1.0)

    def test_11_real_subprocess_child_crash_detection(self, isolated_dirs):
        """Integration test verifying parent immediately detects a crashing child subprocess."""
        install_dir, data_dir, _, _ = isolated_dirs
        installer = UpdateInstaller(
            install_dir=install_dir,
            data_dir=data_dir,
            handshake_timeout=5.0,
        )

        base_exe = getattr(sys, "_base_executable", sys.executable)

        def crashing_launcher(exe_path):
            return subprocess.Popen(
                [base_exe, "-c", "import sys; sys.exit(42)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        installer._app_launcher = crashing_launcher
        ok, err = installer._restart_and_validate(target_version="1.0.0-beta.3")
        assert ok is False
        assert "crashed immediately (exit code: 42)" in err
