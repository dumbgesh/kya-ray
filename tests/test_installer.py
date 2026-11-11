"""
tests/test_installer.py - Unit and Integration Tests for Stage 4 Update Installation Engine.

Tests:
- Safe ZIP extraction and layout validation.
- Path traversal and symlink rejection.
- Package structure integrity checks (missing executable, corrupt PE header, missing runtime).
- Pre-extraction disk space validation.
- Process shutdown bounded waiting and non-interference with unrelated processes.
- Transactional installation, same-volume replacement, and backup creation.
- Preservation of user .env and user data.
- Registry update and rollback handling.
- Automatic rollback upon failure and failed-rollback reporting.
- Interrupted transaction crash recovery.
- Application restart and startup verification using mocked processes.
"""

import io
import json
import os
import shutil
import stat
import subprocess
import time
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from desktop.updater.extractor import (
    InsufficientDiskSpaceError,
    InvalidPackageError,
    PackageExtractor,
    UnsafeArchiveError,
)
from desktop.updater.installer import (
    InstallationResult,
    RollbackStatus,
    TransactionRecord,
    TransactionState,
    UpdateInstaller,
)
from desktop.updater.process_manager import ProcessHandoff, ProcessShutdownError
from desktop.updater.registry import RegistryError, RegistryManager


# ---------------------------------------------------------------------------
# Test Helpers: Creating Test Packages and Payloads
# ---------------------------------------------------------------------------
def create_valid_pe_bytes(size: int = 2048) -> bytes:
    """Returns dummy bytes with valid Windows PE 'MZ' magic."""
    return b"MZ" + (b"\x90" * (max(size, 1024) - 2))


def create_test_zip(
    zip_path: Path,
    nested: bool = True,
    include_env_example: bool = True,
    extra_files: dict = None,
) -> Path:
    """Creates a well-formed Kya-Ray release ZIP for testing."""
    prefix = "Kya-Ray/" if nested else ""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Essential executable
        zf.writestr(f"{prefix}Kya-Ray.exe", create_valid_pe_bytes(4096))
        # Runtime dependencies
        zf.writestr(f"{prefix}_internal/python313.dll", b"PE_DLL_DATA" * 50)
        zf.writestr(f"{prefix}_internal/app_runtime.dat", b"RUNTIME_METADATA")

        if include_env_example:
            zf.writestr(f"{prefix}.env.example", "GROQ_API_KEY=your_key_here\n")

        if extra_files:
            for name, content in extra_files.items():
                zf.writestr(f"{prefix}{name}", content)

    return zip_path


def create_mock_installation(install_dir: Path, version: str = "1.0.0-beta.1", env_content: str = None) -> None:
    """Populates install_dir with existing v1 application files."""
    install_dir.mkdir(parents=True, exist_ok=True)
    (install_dir / "Kya-Ray.exe").write_bytes(create_valid_pe_bytes(2048))
    internal = install_dir / "_internal"
    internal.mkdir(parents=True, exist_ok=True)
    (internal / "python313.dll").write_bytes(b"OLD_DLL")

    if env_content:
        (install_dir / ".env").write_text(env_content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Test Suite: Archive Extraction and Security Checks
# ---------------------------------------------------------------------------
class TestPackageExtractor:

    def test_safe_zip_extraction(self, tmp_path):
        """Verifies safe extraction of a valid nested release package."""
        zip_file = tmp_path / "valid_release.zip"
        create_test_zip(zip_file, nested=True)

        staging_dir = tmp_path / "staging"
        extractor = PackageExtractor()
        payload_root = extractor.extract_and_validate(zip_file, staging_dir)

        assert payload_root.is_dir()
        assert (payload_root / "Kya-Ray.exe").is_file()
        assert (payload_root / "_internal").is_dir()

    def test_path_traversal_rejection(self, tmp_path):
        """Rejects zip archives containing parent directory traversal (..) or leading slashes."""
        staging_dir = tmp_path / "staging"
        extractor = PackageExtractor()

        # Case 1: Parent traversal ..
        bad_zip1 = tmp_path / "traversal1.zip"
        with zipfile.ZipFile(bad_zip1, "w") as zf:
            zf.writestr("../escaped.txt", b"evil")
        with pytest.raises(UnsafeArchiveError, match="Path traversal"):
            extractor.extract_and_validate(bad_zip1, staging_dir)

        # Case 2: Leading slash /
        bad_zip2 = tmp_path / "traversal2.zip"
        with zipfile.ZipFile(bad_zip2, "w") as zf:
            zf.writestr("/root_escaped.txt", b"evil")
        with pytest.raises(UnsafeArchiveError, match="Absolute path"):
            extractor.extract_and_validate(bad_zip2, staging_dir)

        # Case 3: Windows drive prefix
        bad_zip3 = tmp_path / "traversal3.zip"
        with zipfile.ZipFile(bad_zip3, "w") as zf:
            zf.writestr("C:drive_escaped.txt", b"evil")
        with pytest.raises(UnsafeArchiveError, match="Drive letter prefix"):
            extractor.extract_and_validate(bad_zip3, staging_dir)

    def test_symlink_rejection(self, tmp_path):
        """Rejects archives containing symlink entries."""
        bad_zip = tmp_path / "symlink.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zinfo = zipfile.ZipInfo("symlink_target.txt")
            # Set Unix file mode for symlink (S_IFLNK = 0o120000)
            zinfo.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(zinfo, "target_file")

        staging_dir = tmp_path / "staging"
        extractor = PackageExtractor()
        with pytest.raises(UnsafeArchiveError, match="Symlinks are forbidden"):
            extractor.extract_and_validate(bad_zip, staging_dir)

    def test_duplicate_filename_rejection(self, tmp_path):
        """Rejects archives containing duplicate or colliding filenames."""
        bad_zip = tmp_path / "collision.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("kya-ray/file.txt", b"first")
            zf.writestr("kya-ray/FILE.TXT", b"second collision")

        staging_dir = tmp_path / "staging"
        extractor = PackageExtractor()
        with pytest.raises(UnsafeArchiveError, match="Duplicate or colliding"):
            extractor.extract_and_validate(bad_zip, staging_dir)

    def test_missing_executable(self, tmp_path):
        """Rejects packages that do not contain Kya-Ray.exe."""
        bad_zip = tmp_path / "no_exe.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("random.txt", b"some text")
            zf.writestr("_internal/some.dll", b"dll data")

        staging_dir = tmp_path / "staging"
        extractor = PackageExtractor()
        with pytest.raises(InvalidPackageError, match="Kya-Ray.exe not found"):
            extractor.extract_and_validate(bad_zip, staging_dir)

    def test_invalid_package_structure_corrupt_pe(self, tmp_path):
        """Rejects packages where Kya-Ray.exe is corrupt or lacks PE 'MZ' magic."""
        bad_zip = tmp_path / "corrupt_pe.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("Kya-Ray.exe", b"NOT_A_PE_BINARY" * 100)
            zf.writestr("_internal/some.dll", b"dll")

        staging_dir = tmp_path / "staging"
        extractor = PackageExtractor()
        with pytest.raises(InvalidPackageError, match="not a valid Windows PE binary"):
            extractor.extract_and_validate(bad_zip, staging_dir)

    def test_invalid_package_structure_missing_runtime(self, tmp_path):
        """Rejects packages where runtime folder (_internal or companion DLLs) is missing."""
        bad_zip = tmp_path / "no_runtime.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("Kya-Ray.exe", create_valid_pe_bytes(2048))

        staging_dir = tmp_path / "staging"
        extractor = PackageExtractor()
        with pytest.raises(InvalidPackageError, match="missing runtime dependencies"):
            extractor.extract_and_validate(bad_zip, staging_dir)

    def test_insufficient_disk_space(self, tmp_path):
        """Rejects extraction when target disk has inadequate free space."""
        zip_file = tmp_path / "valid.zip"
        create_test_zip(zip_file)

        staging_dir = tmp_path / "staging"
        extractor = PackageExtractor()

        # Mock disk_usage to return only 100 bytes free
        fake_usage = MagicMock(total=1000000000, used=999999900, free=100)
        with patch("shutil.disk_usage", return_value=fake_usage):
            with pytest.raises(InsufficientDiskSpaceError, match="Insufficient disk space"):
                extractor.extract_and_validate(zip_file, staging_dir)


# ---------------------------------------------------------------------------
# Test Suite: Process Handoff and Safety
# ---------------------------------------------------------------------------
class TestProcessHandoff:

    def test_process_shutdown_clean(self, tmp_path):
        """Verifies process handoff when target processes exit cleanly."""
        install_dir = tmp_path / "install"
        install_dir.mkdir()

        # Mock: PID 101 exits after 1 poll
        alive_state = {101: True}

        def mock_alive(pid):
            if alive_state.get(pid):
                alive_state[pid] = False  # exits
                return True
            return False

        handoff = ProcessHandoff(
            install_dir=install_dir,
            shutdown_timeout=2.0,
            poll_interval=0.05,
        )
        handoff._is_process_alive = mock_alive

        handoff.wait_for_shutdown(pids=[101])
        assert not alive_state[101]

    def test_process_shutdown_safety_never_kills_unrelated_process(self, tmp_path):
        """Guarantees processes outside install_dir are NEVER killed."""
        install_dir = tmp_path / "install"
        install_dir.mkdir()

        killed_pids = []

        def mock_killer(pid, force):
            killed_pids.append(pid)
            return True

        # Process 999 is located in C:/Windows/notepad.exe (outside install_dir)
        def mock_path_getter(pid):
            if pid == 999:
                return "C:/Windows/System32/notepad.exe"
            return None

        handoff = ProcessHandoff(
            install_dir=install_dir,
            shutdown_timeout=0.2,
            force_kill_timeout=0.2,
            poll_interval=0.05,
            process_path_getter=mock_path_getter,
            process_killer=mock_killer,
        )
        handoff._is_process_alive = lambda pid: True  # Process remains alive

        # Hand off process 999
        handoff.wait_for_shutdown(pids=[999])

        # Assert process 999 was NOT killed
        assert 999 not in killed_pids

    def test_process_shutdown_force_kills_verified_kya_ray_process_on_timeout(self, tmp_path):
        """Force-kills only verified processes whose executable is inside install_dir."""
        install_dir = tmp_path / "install"
        install_dir.mkdir()
        kya_exe = install_dir / "Kya-Ray.exe"
        kya_exe.write_bytes(b"EXE")

        killed_pids = []

        def mock_killer(pid, force):
            killed_pids.append(pid)
            return True

        # PID 500 is verified inside install_dir
        def mock_path_getter(pid):
            if pid == 500:
                return str(kya_exe)
            return None

        alive_map = {500: True}

        def mock_alive(pid):
            if 500 in killed_pids:
                return False  # dies after kill
            return alive_map.get(pid, False)

        handoff = ProcessHandoff(
            install_dir=install_dir,
            shutdown_timeout=0.1,
            force_kill_timeout=0.5,
            poll_interval=0.02,
            process_path_getter=mock_path_getter,
            process_killer=mock_killer,
        )
        handoff._is_process_alive = mock_alive

        handoff.wait_for_shutdown(pids=[500])
        assert 500 in killed_pids

    def test_process_shutdown_timeout_error_if_kill_fails(self, tmp_path):
        """Raises ProcessShutdownError if verified process refuses to die even after kill."""
        install_dir = tmp_path / "install"
        install_dir.mkdir()
        kya_exe = install_dir / "Kya-Ray.exe"
        kya_exe.write_bytes(b"EXE")

        handoff = ProcessHandoff(
            install_dir=install_dir,
            shutdown_timeout=0.1,
            force_kill_timeout=0.1,
            poll_interval=0.02,
            process_path_getter=lambda pid: str(kya_exe),
            process_killer=lambda pid, force: False,  # Kill fails
        )
        handoff._is_process_alive = lambda pid: True  # Never dies

        with pytest.raises(ProcessShutdownError, match="failed to terminate"):
            handoff.wait_for_shutdown(pids=[500])


# ---------------------------------------------------------------------------
# Test Suite: Transactional Installation, Backup, and Rollback
# ---------------------------------------------------------------------------
class TestUpdateInstaller:

    @pytest.fixture
    def setup_dirs(self, tmp_path):
        install_dir = tmp_path / "Programs" / "Kya-Ray"
        data_dir = tmp_path / "Kya-Ray-Data"
        mock_registry = RegistryManager(mock_store={"DisplayVersion": "1.0.0-beta.1"})

        create_mock_installation(install_dir, version="1.0.0-beta.1", env_content="GROQ_API_KEY=existing-secret-key\n")

        # Mock app launcher that returns a running process and writes readiness handshake
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None  # Process running cleanly
        mock_proc.returncode = 0

        def mock_launcher_fn(exe_path):
            handshake_file = os.environ.get("KYA_RAY_HANDSHAKE_FILE")
            if handshake_file:
                with open(handshake_file, "w", encoding="utf-8") as f:
                    json.dump({"status": "ready", "version": "1.0.0-beta.2", "pid": 12345}, f)
            return mock_proc

        app_launcher = MagicMock(side_effect=mock_launcher_fn)

        # Mock process handoff (no running processes)
        mock_handoff = MagicMock()

        installer = UpdateInstaller(
            install_dir=install_dir,
            data_dir=data_dir,
            registry_manager=mock_registry,
            process_handoff=mock_handoff,
            app_launcher=app_launcher,
            handshake_timeout=0.5,
        )

        return installer, install_dir, data_dir, mock_registry, app_launcher

    def test_successful_installation_and_replacement(self, setup_dirs, tmp_path):
        """End-to-end test of successful upgrade from v1.0.0-beta.1 to v1.0.0-beta.2."""
        installer, install_dir, data_dir, mock_registry, app_launcher = setup_dirs

        # Prepare new release package
        zip_file = tmp_path / "kya-ray-v1.0.0-beta.2.zip"
        create_test_zip(zip_file, extra_files={"new_feature.txt": b"VERSION_2_FEATURE"})

        result = installer.install(
            zip_path=zip_file,
            target_version="1.0.0-beta.2",
            restart_after=True,
        )

        assert result.success is True
        assert result.installed_version == "1.0.0-beta.2"
        assert result.previous_version == "1.0.0-beta.1"
        assert result.rollback_status == RollbackStatus.NOT_NEEDED
        assert result.restarted is True

        # Check installed files
        assert (install_dir / "Kya-Ray.exe").is_file()
        assert (install_dir / "new_feature.txt").read_bytes() == b"VERSION_2_FEATURE"

        # Check registry updated
        assert mock_registry.get_display_version() == "1.0.0-beta.2"

        # Check log file updated
        log_file = data_dir / "kya-ray.log"
        assert log_file.is_file()
        log_content = log_file.read_text(encoding="utf-8")
        assert "Update to 1.0.0-beta.2 verified and committed successfully." in log_content

    def test_preservation_of_env(self, setup_dirs, tmp_path):
        """Guarantees user .env is preserved and not overwritten by .env.example."""
        installer, install_dir, data_dir, mock_registry, _ = setup_dirs

        original_secret = "GROQ_API_KEY=my-super-secret-production-token-12345\nCUSTOM_SETTING=true\n"
        (install_dir / ".env").write_text(original_secret, encoding="utf-8")

        # Prepare update zip containing default .env.example
        zip_file = tmp_path / "update_with_example.zip"
        create_test_zip(zip_file, include_env_example=True)

        result = installer.install(
            zip_path=zip_file,
            target_version="1.0.0-beta.2",
            restart_after=False,
        )

        assert result.success is True
        # Verify user .env was preserved verbatim
        installed_env = (install_dir / ".env").read_text(encoding="utf-8")
        assert installed_env == original_secret

    def test_preservation_of_user_data(self, setup_dirs, tmp_path):
        """Ensures external user data and diagnostic logs in %LOCALAPPDATA%\\Kya-Ray survive untouched."""
        installer, install_dir, data_dir, _, _ = setup_dirs

        # Create user database or custom cache in data_dir
        user_cache = data_dir / "user_cache.json"
        user_cache.write_text('{"user_custom_data": 42}', encoding="utf-8")

        zip_file = tmp_path / "update.zip"
        create_test_zip(zip_file)

        result = installer.install(zip_path=zip_file, target_version="1.0.0-beta.2", restart_after=False)
        assert result.success is True
        assert user_cache.is_file()
        assert json.loads(user_cache.read_text(encoding="utf-8")) == {"user_custom_data": 42}

    def test_registry_update_failure_triggers_automatic_rollback(self, setup_dirs, tmp_path):
        """Triggers rollback when the Windows Registry DisplayVersion write fails."""
        installer, install_dir, data_dir, mock_registry, _ = setup_dirs

        # Cause registry write to throw RegistryError
        mock_registry.mock_store["__fail_write__"] = True

        zip_file = tmp_path / "update.zip"
        create_test_zip(zip_file, extra_files={"v2_marker.txt": b"V2"})

        result = installer.install(
            zip_path=zip_file,
            target_version="1.0.0-beta.2",
            restart_after=False,
        )

        assert result.success is False
        assert result.rollback_status == RollbackStatus.SUCCEEDED
        assert "Simulated registry write failure" in result.error_message

        # Assert v1 was restored from backup
        assert (install_dir / "Kya-Ray.exe").is_file()
        assert not (install_dir / "v2_marker.txt").exists()
        # Original .env preserved
        assert "existing-secret-key" in (install_dir / ".env").read_text()

    def test_post_install_validation_failure_triggers_rollback(self, setup_dirs, tmp_path):
        """Triggers rollback if the promoted directory fails structural verification."""
        installer, install_dir, data_dir, _, _ = setup_dirs

        zip_file = tmp_path / "update.zip"
        create_test_zip(zip_file)

        # Patch _verify_installation_integrity to raise an error
        with patch.object(installer, "_verify_installation_integrity", side_effect=InvalidPackageError("Corrupt files")):
            result = installer.install(
                zip_path=zip_file,
                target_version="1.0.0-beta.2",
                restart_after=False,
            )

        assert result.success is False
        assert result.rollback_status == RollbackStatus.SUCCEEDED
        assert "Corrupt files" in result.error_message

        # Verify old installation is restored
        assert (install_dir / "Kya-Ray.exe").is_file()
        assert "existing-secret-key" in (install_dir / ".env").read_text()

    def test_failed_rollback_reporting(self, setup_dirs, tmp_path):
        """Correctly reports RollbackStatus.FAILED if the backup cannot be restored."""
        installer, install_dir, data_dir, _, _ = setup_dirs

        zip_file = tmp_path / "update.zip"
        create_test_zip(zip_file)

        # Patch _rollback to simulate failure restoring backup
        with patch.object(installer, "_rollback", return_value=RollbackStatus.FAILED):
            with patch.object(installer, "_verify_installation_integrity", side_effect=OSError("Disk corrupted")):
                result = installer.install(
                    zip_path=zip_file,
                    target_version="1.0.0-beta.2",
                    restart_after=False,
                )

        assert result.success is False
        assert result.rollback_status == RollbackStatus.FAILED
        assert "Installation failed" in result.error_message

    def test_startup_validation_failure_triggers_rollback(self, setup_dirs, tmp_path):
        """Triggers rollback if the newly installed binary crashes immediately on launch."""
        installer, install_dir, data_dir, mock_registry, app_launcher = setup_dirs

        # Mock launcher to return a process that crashed with exit code 1
        crashed_proc = MagicMock()
        crashed_proc.poll.return_value = 1
        crashed_proc.returncode = 1
        app_launcher.side_effect = None
        app_launcher.return_value = crashed_proc

        zip_file = tmp_path / "update.zip"
        create_test_zip(zip_file, extra_files={"new_buggy_code.txt": b"CRASH"})

        result = installer.install(
            zip_path=zip_file,
            target_version="1.0.0-beta.2",
            restart_after=True,
        )

        assert result.success is False
        assert result.rollback_status == RollbackStatus.SUCCEEDED
        assert "Application failed to start after update" in result.error_message

        # Verify rollback restored previous v1 installation
        assert (install_dir / "Kya-Ray.exe").is_file()
        assert not (install_dir / "new_buggy_code.txt").exists()
        assert mock_registry.get_display_version() == "1.0.0-beta.1"

    def test_recovery_from_interrupted_transaction(self, setup_dirs, tmp_path):
        """Recovers cleanly from an interrupted transaction where power was lost mid-install."""
        installer, install_dir, data_dir, mock_registry, _ = setup_dirs

        # Simulate interrupted state:
        # 1. Existing install was moved to backup
        parent_dir = install_dir.parent
        backup_dir = parent_dir / "Kya-Ray.backup-interrupted"
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / "Kya-Ray.exe").write_bytes(create_valid_pe_bytes(2048))
        (backup_dir / ".env").write_text("GROQ_API_KEY=interrupted-key\n")

        # 2. Incomplete install_dir was left on disk
        install_dir.mkdir(parents=True, exist_ok=True)
        (install_dir / "partial.tmp").write_bytes(b"INCOMPLETE")

        # 3. Transaction state file recorded INSTALLING
        record = {
            "transaction_id": "tx-interrupted-123",
            "state": TransactionState.INSTALLING.value,
            "previous_version": "1.0.0-beta.1",
            "target_version": "1.0.0-beta.2",
            "install_dir": str(install_dir),
            "backup_dir": str(backup_dir),
            "staging_dir": str(parent_dir / ".kya-ray-staging-leftover"),
            "preserve_env": True,
            "timestamp": 123456789.0,
        }
        (data_dir / UpdateInstaller.TRANSACTION_FILE).write_text(json.dumps(record), encoding="utf-8")

        # Trigger recovery
        recovery_result = installer.recover_interrupted_transaction()

        assert recovery_result is not None
        assert recovery_result.rollback_status == RollbackStatus.SUCCEEDED
        assert "Recovered from an interrupted update transaction" in recovery_result.error_message

        # Verify backup was restored into install_dir
        assert (install_dir / "Kya-Ray.exe").is_file()
        assert not (install_dir / "partial.tmp").exists()
        assert "interrupted-key" in (install_dir / ".env").read_text()

        # Verify transaction state file was cleaned up
        assert not (data_dir / UpdateInstaller.TRANSACTION_FILE).exists()

    def test_frozen_process_handshake_timeout_triggers_rollback(self, setup_dirs, tmp_path):
        """Triggers rollback when the restarted process stays alive but is frozen/unready."""
        installer, install_dir, data_dir, mock_registry, app_launcher = setup_dirs

        # Process is alive (poll() returns None), but never writes handshake file (frozen)
        frozen_proc = MagicMock()
        frozen_proc.poll.return_value = None
        frozen_proc.terminate = MagicMock()
        frozen_proc.wait = MagicMock()
        app_launcher.side_effect = None
        app_launcher.return_value = frozen_proc

        zip_file = tmp_path / "update.zip"
        create_test_zip(zip_file, extra_files={"frozen_feature.txt": b"FROZEN"})

        result = installer.install(
            zip_path=zip_file,
            target_version="1.0.0-beta.2",
            restart_after=True,
        )

        assert result.success is False
        assert result.rollback_status == RollbackStatus.SUCCEEDED
        assert "readiness handshake" in result.error_message
        assert frozen_proc.terminate.called

        # Original installation restored
        assert (install_dir / "Kya-Ray.exe").is_file()
        assert not (install_dir / "frozen_feature.txt").exists()

    def test_nested_kya_ray_directory_auto_flattening(self, setup_dirs, tmp_path):
        """Ensures that packages with top-level Kya-Ray/ do not create nested Kya-Ray/Kya-Ray."""
        installer, install_dir, data_dir, mock_registry, _ = setup_dirs

        zip_file = tmp_path / "nested_release.zip"
        # Nested zip: Kya-Ray/Kya-Ray.exe, Kya-Ray/_internal, etc.
        create_test_zip(zip_file, nested=True, extra_files={"nested_proof.txt": b"FLATTENED"})

        result = installer.install(
            zip_path=zip_file,
            target_version="1.0.0-beta.2",
            restart_after=False,
        )

        assert result.success is True
        # Must be directly in install_dir, NOT in install_dir/Kya-Ray/
        assert (install_dir / "Kya-Ray.exe").is_file()
        assert (install_dir / "nested_proof.txt").is_file()
        assert not (install_dir / "Kya-Ray" / "Kya-Ray.exe").exists()

    def test_interrupted_transaction_staged_state(self, setup_dirs, tmp_path):
        """State STAGED was interrupted: install_dir was never touched, rollback is NOT_NEEDED."""
        installer, install_dir, data_dir, mock_registry, _ = setup_dirs

        parent_dir = install_dir.parent
        staging_dir = parent_dir / ".kya-ray-staging-leftover"
        staging_dir.mkdir(parents=True, exist_ok=True)
        (staging_dir / "leftover.dat").write_bytes(b"STAGED_GARBAGE")

        record = {
            "transaction_id": "tx-staged-123",
            "state": TransactionState.STAGED.value,
            "previous_version": "1.0.0-beta.1",
            "target_version": "1.0.0-beta.2",
            "install_dir": str(install_dir),
            "backup_dir": str(parent_dir / "Kya-Ray.backup-none"),
            "staging_dir": str(staging_dir),
            "preserve_env": True,
            "timestamp": 123456789.0,
        }
        (data_dir / UpdateInstaller.TRANSACTION_FILE).write_text(json.dumps(record), encoding="utf-8")

        res = installer.recover_interrupted_transaction()
        assert res is not None
        assert res.rollback_status == RollbackStatus.NOT_NEEDED
        assert not staging_dir.exists()
        assert (install_dir / "Kya-Ray.exe").is_file()

    def test_interrupted_transaction_never_deletes_only_installation(self, setup_dirs, tmp_path):
        """Recovery never deletes install_dir when no backup exists to restore from."""
        installer, install_dir, data_dir, mock_registry, _ = setup_dirs

        parent_dir = install_dir.parent
        record = {
            "transaction_id": "tx-lost-backup",
            "state": TransactionState.INSTALLING.value,
            "previous_version": "1.0.0-beta.1",
            "target_version": "1.0.0-beta.2",
            "install_dir": str(install_dir),
            "backup_dir": str(parent_dir / "Kya-Ray.backup-missing"),
            "staging_dir": str(parent_dir / ".kya-ray-staging-dummy"),
            "preserve_env": True,
            "timestamp": 123456789.0,
        }
        (data_dir / UpdateInstaller.TRANSACTION_FILE).write_text(json.dumps(record), encoding="utf-8")

        res = installer.recover_interrupted_transaction()
        # Install dir should be preserved, not wiped!
        assert (install_dir / "Kya-Ray.exe").is_file()
        assert "existing-secret-key" in (install_dir / ".env").read_text()



class TestUpdaterCLI:

    def test_cli_main_success(self, tmp_path):
        """Verifies CLI entrypoint exits with 0 on success."""
        from desktop.updater.cli import main

        zip_file = tmp_path / "update.zip"
        create_test_zip(zip_file)
        install_dir = tmp_path / "install"
        create_mock_installation(install_dir)
        data_dir = tmp_path / "data"

        with patch.object(UpdateInstaller, "install") as mock_install:
            mock_install.return_value = InstallationResult(
                success=True,
                installed_version="1.0.0-beta.2",
            )
            exit_code = main([
                "--zip", str(zip_file),
                "--target-version", "1.0.0-beta.2",
                "--install-dir", str(install_dir),
                "--data-dir", str(data_dir),
                "--no-restart",
            ])
            assert exit_code == 0

    def test_cli_main_failure(self, tmp_path):
        """Verifies CLI entrypoint exits with 1 on installation failure."""
        from desktop.updater.cli import main

        with patch.object(UpdateInstaller, "install") as mock_install:
            mock_install.return_value = InstallationResult(
                success=False,
                error_message="Checksum failure",
                rollback_status=RollbackStatus.SUCCEEDED,
            )
            exit_code = main([
                "--zip", str(tmp_path / "fake.zip"),
                "--target-version", "1.0.0-beta.2",
            ])
            assert exit_code == 1

    def test_launch_detached_updater_invocation(self, tmp_path):
        """Verifies detached launcher constructs command line and spawns detached process."""
        from desktop.updater.cli import launch_detached_updater

        zip_file = tmp_path / "update.zip"
        create_test_zip(zip_file)

        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_popen.return_value = mock_proc

            proc = launch_detached_updater(
                zip_path=zip_file,
                target_version="1.0.0-beta.2",
                gui_pid=1234,
                backend_pid=5678,
                no_restart=True,
            )

            assert proc is mock_proc
            assert mock_popen.called
            call_args = mock_popen.call_args[0][0]
            assert "--zip" in call_args
            assert "--target-version" in call_args
            assert "--gui-pid" in call_args
            assert "1234" in call_args
            assert "--backend-pid" in call_args
            assert "5678" in call_args
            assert "--no-restart" in call_args

    def test_cli_main_recover_flag(self, tmp_path):
        """Verifies CLI entrypoint runs recovery when invoked with --recover."""
        from desktop.updater.cli import main

        with patch.object(UpdateInstaller, "recover_interrupted_transaction") as mock_rec:
            mock_rec.return_value = None
            exit_code = main(["--recover"])
            assert exit_code == 0
            assert mock_rec.called

    def test_stale_temp_updater_cleanup(self, tmp_path, monkeypatch):
        """Verifies stale temporary updater folders are cleaned up without deleting the active one."""
        from desktop.updater.cli import cleanup_stale_temp_updaters

        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        monkeypatch.setenv("TEMP", str(temp_dir))

        stale_dir = temp_dir / "kya-ray-updater-old123"
        stale_dir.mkdir()
        (stale_dir / "old.exe").write_bytes(b"OLD")
        # Set old mtime (2 hours ago)
        old_time = time.time() - 7200
        os.utime(stale_dir, (old_time, old_time))

        active_dir = temp_dir / "kya-ray-updater-active456"
        active_dir.mkdir()
        (active_dir / "active.exe").write_bytes(b"ACTIVE")

        cleanup_stale_temp_updaters(active_dir=active_dir, max_age_seconds=3600)

        assert not stale_dir.exists()  # Cleaned up!
        assert active_dir.exists()     # Preserved!

    def test_cleanup_stale_temp_updaters_never_deletes_running_process_dir(self, tmp_path, monkeypatch):
        """Ensures temp updater directory is NEVER deleted if a running process PID or file lock is present."""
        from desktop.updater.cli import cleanup_stale_temp_updaters

        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        monkeypatch.setenv("TEMP", str(temp_dir))

        # Old directory (3 hours old) but has an active PID file
        busy_dir = temp_dir / "kya-ray-updater-busy999"
        busy_dir.mkdir()
        (busy_dir / "kya.exe").write_bytes(b"RUNNING")
        old_time = time.time() - 10800
        os.utime(busy_dir, (old_time, old_time))

        # Write current test process PID to .updater.pid (which is definitely alive!)
        (busy_dir / ".updater.pid").write_text(str(os.getpid()))

        cleanup_stale_temp_updaters(active_dir=None, max_age_seconds=3600)

        # Must NOT be deleted because PID is alive!
        assert busy_dir.exists()


class TestSafetyGuarantees:

    def test_rollback_never_deletes_installation_if_backup_missing(self, tmp_path):
        """Rollback refuses to touch or delete install_dir if backup_dir does not exist."""
        install_dir = tmp_path / "install"
        create_mock_installation(install_dir)
        missing_backup = tmp_path / "non_existent_backup"

        installer = UpdateInstaller(install_dir=install_dir, data_dir=tmp_path / "data")
        status = installer._rollback(
            backup_dir=missing_backup,
            preserved_env_path=tmp_path / "preserve",
            previous_version="1.0.0-beta.1",
        )

        assert status == RollbackStatus.FAILED
        # The only copy was NOT deleted!
        assert (install_dir / "Kya-Ray.exe").is_file()

    def test_recovery_restores_backup_even_if_state_stuck_in_staged(self, tmp_path):
        """If a crash occurred right after moving install_dir to backup_dir, recovery restores it."""
        install_dir = tmp_path / "Programs" / "Kya-Ray"
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        parent_dir = install_dir.parent
        parent_dir.mkdir(parents=True, exist_ok=True)
        backup_dir = parent_dir / "Kya-Ray.backup-stuck"
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / "Kya-Ray.exe").write_bytes(create_valid_pe_bytes(2048))

        # State recorded as STAGED (crash right before BACKUP_CREATED was written)
        record = {
            "transaction_id": "tx-staged-crash",
            "state": TransactionState.STAGED.value,
            "previous_version": "1.0.0-beta.1",
            "target_version": "1.0.0-beta.2",
            "install_dir": str(install_dir),
            "backup_dir": str(backup_dir),
            "staging_dir": str(parent_dir / ".kya-ray-staging-dummy"),
            "preserve_env": True,
            "timestamp": time.time(),
        }
        (data_dir / UpdateInstaller.TRANSACTION_FILE).write_text(json.dumps(record), encoding="utf-8")

        installer = UpdateInstaller(install_dir=install_dir, data_dir=data_dir)
        result = installer.recover_interrupted_transaction()

        assert result is not None
        assert result.rollback_status == RollbackStatus.SUCCEEDED
        assert (install_dir / "Kya-Ray.exe").is_file()

    def test_app_startup_aborts_if_recovery_fails(self, monkeypatch):
        """desktop/app.py exits with code 1 if transaction recovery fails."""
        from desktop import app

        mock_installer = MagicMock()
        mock_installer.recover_interrupted_transaction.return_value = InstallationResult(
            success=False,
            rollback_status=RollbackStatus.FAILED,
            error_message="Corrupted filesystem prevents recovery",
        )

        with patch("desktop.updater.installer.UpdateInstaller", return_value=mock_installer):
            with pytest.raises(SystemExit) as exc_info:
                app.main()
            assert exc_info.value.code == 1

    def test_handshake_version_mismatch_triggers_rollback(self, tmp_path):
        """Triggers rollback when the handshake file reports an unexpected version."""
        install_dir = tmp_path / "Programs" / "Kya-Ray"
        data_dir = tmp_path / "data"
        create_mock_installation(install_dir, version="1.0.0-beta.1")
        mock_registry = RegistryManager(mock_store={"DisplayVersion": "1.0.0-beta.1"})

        # Process starts and writes wrong version to handshake file
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345

        def launcher_wrong_version(exe_path):
            handshake = os.environ.get("KYA_RAY_HANDSHAKE_FILE")
            if handshake:
                with open(handshake, "w", encoding="utf-8") as f:
                    json.dump({"status": "ready", "version": "9.9.9-wrong", "pid": 12345}, f)
            return mock_proc

        installer = UpdateInstaller(
            install_dir=install_dir,
            data_dir=data_dir,
            registry_manager=mock_registry,
            app_launcher=launcher_wrong_version,
            handshake_timeout=0.5,
        )

        zip_file = tmp_path / "update.zip"
        create_test_zip(zip_file, extra_files={"v2_file.txt": b"NEW"})

        result = installer.install(zip_path=zip_file, target_version="1.0.0-beta.2", restart_after=True)

        assert result.success is False
        assert result.rollback_status == RollbackStatus.SUCCEEDED
        assert "Handshake version mismatch" in result.error_message
        assert mock_registry.get_display_version() == "1.0.0-beta.1"
        assert not (install_dir / "v2_file.txt").exists()

    def test_handshake_pid_mismatch_triggers_rollback(self, tmp_path):
        """Triggers rollback when the handshake file reports a mismatched process PID."""
        install_dir = tmp_path / "Programs" / "Kya-Ray"
        data_dir = tmp_path / "data"
        create_mock_installation(install_dir, version="1.0.0-beta.1")
        mock_registry = RegistryManager(mock_store={"DisplayVersion": "1.0.0-beta.1"})

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345

        def launcher_wrong_pid(exe_path):
            handshake = os.environ.get("KYA_RAY_HANDSHAKE_FILE")
            if handshake:
                with open(handshake, "w", encoding="utf-8") as f:
                    json.dump({"status": "ready", "version": "1.0.0-beta.2", "pid": 99999}, f)
            return mock_proc

        installer = UpdateInstaller(
            install_dir=install_dir,
            data_dir=data_dir,
            registry_manager=mock_registry,
            app_launcher=launcher_wrong_pid,
            handshake_timeout=0.5,
        )

        zip_file = tmp_path / "update.zip"
        create_test_zip(zip_file)

        result = installer.install(zip_path=zip_file, target_version="1.0.0-beta.2", restart_after=True)

        assert result.success is False
        assert result.rollback_status == RollbackStatus.SUCCEEDED
        assert "Handshake PID mismatch" in result.error_message
        assert mock_registry.get_display_version() == "1.0.0-beta.1"

    def test_recovery_rejects_backup_path_traversal(self, tmp_path):
        """Rejects transaction records where backup_dir escapes or violates naming conventions."""
        install_dir = tmp_path / "Programs" / "Kya-Ray"
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        create_mock_installation(install_dir)

        # Tampered record attempting to escape to C:/Windows or parent traversal
        parent_dir = install_dir.parent
        tampered_record = {
            "transaction_id": "tx-evil-backup",
            "state": TransactionState.INSTALLING.value,
            "previous_version": "1.0.0-beta.1",
            "target_version": "1.0.0-beta.2",
            "install_dir": str(install_dir),
            "backup_dir": str(parent_dir / ".." / "escaped_backup"),
            "staging_dir": str(parent_dir / ".kya-ray-staging-valid"),
            "preserve_env": True,
            "timestamp": time.time(),
        }
        (data_dir / UpdateInstaller.TRANSACTION_FILE).write_text(json.dumps(tampered_record), encoding="utf-8")

        installer = UpdateInstaller(install_dir=install_dir, data_dir=data_dir)
        result = installer.recover_interrupted_transaction()

        assert result is not None
        assert result.success is False
        assert result.rollback_status == RollbackStatus.FAILED
        assert "escapes expected parent directory" in result.error_message or "Path traversal" in result.error_message
        # Existing installation was untouched and preserved!
        assert (install_dir / "Kya-Ray.exe").is_file()
        # Invalid transaction record is preserved for diagnosis!
        assert (data_dir / UpdateInstaller.TRANSACTION_FILE).is_file()

    def test_recovery_rejects_staging_path_traversal(self, tmp_path):
        """Rejects transaction records where staging_dir escapes or violates naming conventions."""
        install_dir = tmp_path / "Programs" / "Kya-Ray"
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        create_mock_installation(install_dir)

        parent_dir = install_dir.parent
        tampered_record = {
            "transaction_id": "tx-evil-staging",
            "state": TransactionState.STAGED.value,
            "previous_version": "1.0.0-beta.1",
            "target_version": "1.0.0-beta.2",
            "install_dir": str(install_dir),
            "backup_dir": str(parent_dir / "Kya-Ray.backup-valid"),
            "staging_dir": "../../System32",
            "preserve_env": True,
            "timestamp": time.time(),
        }
        (data_dir / UpdateInstaller.TRANSACTION_FILE).write_text(json.dumps(tampered_record), encoding="utf-8")

        installer = UpdateInstaller(install_dir=install_dir, data_dir=data_dir)
        result = installer.recover_interrupted_transaction()

        assert result is not None
        assert result.success is False
        assert result.rollback_status == RollbackStatus.FAILED
        assert "Path traversal" in result.error_message or "escapes" in result.error_message
        # Existing installation was untouched and preserved!
        assert (install_dir / "Kya-Ray.exe").is_file()
        # Invalid transaction record is preserved for diagnosis!
        assert (data_dir / UpdateInstaller.TRANSACTION_FILE).is_file()

    def test_invalid_transaction_record_preserved_after_failed_recovery(self, tmp_path):
        """Invalid or corrupt transaction record is preserved (not deleted or overwritten) after failed recovery."""
        install_dir = tmp_path / "Programs" / "Kya-Ray"
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        create_mock_installation(install_dir)

        # Write invalid/malformed JSON into transaction file
        corrupt_content = '{"transaction_id": "tx-corrupt", "state": "INVALID_STATE_STRING"'
        tx_file = data_dir / UpdateInstaller.TRANSACTION_FILE
        tx_file.write_text(corrupt_content, encoding="utf-8")

        installer = UpdateInstaller(install_dir=install_dir, data_dir=data_dir)
        result = installer.recover_interrupted_transaction()

        assert result is not None
        assert result.success is False
        assert result.rollback_status == RollbackStatus.FAILED
        assert "Corrupt transaction record" in result.error_message

        # Original transaction file is preserved with exact content
        assert tx_file.is_file()
        assert tx_file.read_text(encoding="utf-8") == corrupt_content

        # Repeated recovery attempts remain non-destructive and continue to report failure
        result_retry = installer.recover_interrupted_transaction()
        assert result_retry is not None
        assert result_retry.success is False
        assert result_retry.rollback_status == RollbackStatus.FAILED
        assert tx_file.is_file()
        assert tx_file.read_text(encoding="utf-8") == corrupt_content
        assert (install_dir / "Kya-Ray.exe").is_file()

    def test_recovery_rejects_nested_backup_path(self, tmp_path):
        """Rejects transaction records where backup_dir is nested rather than a direct child."""
        install_dir = tmp_path / "Programs" / "Kya-Ray"
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        create_mock_installation(install_dir)

        parent_dir = install_dir.parent
        nested_backup = parent_dir / "nested_subfolder" / "Kya-Ray.backup-1"
        tx_record = {
            "transaction_id": "tx-nested-backup",
            "state": TransactionState.INSTALLING.value,
            "previous_version": "1.0.0-beta.1",
            "target_version": "1.0.0-beta.2",
            "install_dir": str(install_dir),
            "backup_dir": str(nested_backup),
            "staging_dir": str(parent_dir / ".kya-ray-staging-valid"),
            "preserve_env": True,
            "timestamp": time.time(),
        }
        tx_file = data_dir / UpdateInstaller.TRANSACTION_FILE
        tx_file.write_text(json.dumps(tx_record), encoding="utf-8")

        installer = UpdateInstaller(install_dir=install_dir, data_dir=data_dir)
        result = installer.recover_interrupted_transaction()

        assert result is not None
        assert result.success is False
        assert result.rollback_status == RollbackStatus.FAILED
        assert "nested" in result.error_message.lower() or "parent directory" in result.error_message.lower()

        # Record is preserved; install_dir is untouched
        assert tx_file.is_file()
        assert (install_dir / "Kya-Ray.exe").is_file()

    def test_recovery_rejects_nested_staging_path(self, tmp_path):
        """Rejects transaction records where staging_dir is nested rather than a direct child."""
        install_dir = tmp_path / "Programs" / "Kya-Ray"
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        create_mock_installation(install_dir)

        parent_dir = install_dir.parent
        nested_staging = parent_dir / "nested_subfolder" / ".kya-ray-staging-1"
        tx_record = {
            "transaction_id": "tx-nested-staging",
            "state": TransactionState.STAGED.value,
            "previous_version": "1.0.0-beta.1",
            "target_version": "1.0.0-beta.2",
            "install_dir": str(install_dir),
            "backup_dir": str(parent_dir / "Kya-Ray.backup-valid"),
            "staging_dir": str(nested_staging),
            "preserve_env": True,
            "timestamp": time.time(),
        }
        tx_file = data_dir / UpdateInstaller.TRANSACTION_FILE
        tx_file.write_text(json.dumps(tx_record), encoding="utf-8")

        installer = UpdateInstaller(install_dir=install_dir, data_dir=data_dir)
        result = installer.recover_interrupted_transaction()

        assert result is not None
        assert result.success is False
        assert result.rollback_status == RollbackStatus.FAILED
        assert "nested" in result.error_message.lower() or "parent directory" in result.error_message.lower()

        # Record is preserved; install_dir is untouched
        assert tx_file.is_file()
        assert (install_dir / "Kya-Ray.exe").is_file()

    def test_failed_recovery_prevents_normal_application_startup(self, tmp_path):
        """Failed recovery check halts application startup with exit code 1 and prevents UI initialization."""
        from desktop import app

        install_dir = tmp_path / "Programs" / "Kya-Ray"
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        create_mock_installation(install_dir)

        # Real installer with a corrupt transaction record on disk
        tx_file = data_dir / UpdateInstaller.TRANSACTION_FILE
        tx_file.write_text('{"transaction_id": "tx-corrupt", "state": "BROKEN"}', encoding="utf-8")

        real_installer = UpdateInstaller(install_dir=install_dir, data_dir=data_dir)

        with patch("desktop.updater.installer.UpdateInstaller", return_value=real_installer):
            with patch("desktop.app.KyaRayApplication") as mock_app:
                with pytest.raises(SystemExit) as exc_info:
                    app.main()
                assert exc_info.value.code == 1
                mock_app.assert_not_called()

        # The invalid transaction record is still preserved on disk
        assert tx_file.is_file()




