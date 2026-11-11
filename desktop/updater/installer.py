"""
desktop/updater/installer.py - Transactional Installation and Rollback Engine.

Coordinates the end-to-end update transaction:
1. Validates and extracts the update package into a safe staging directory.
2. Coordinates process shutdown and file lock checks.
3. Preserves user configuration (.env) and protects external user data.
4. Backs up existing installation atomically on the same volume with retry logic for sharing violations.
5. Promotes staged application into the target installation directory, flattening any nested paths.
6. Verifies executable integrity and updates Windows Registry metadata.
7. Automatically rolls back to the known-good backup on any failure.
8. Restarts the updated application and validates with a bounded readiness handshake.
9. Detects and safely recovers from interrupted update transactions.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple, Union

from desktop.updater.extractor import (
    ExtractorError,
    InsufficientDiskSpaceError,
    InvalidPackageError,
    PackageExtractor,
    UnsafeArchiveError,
)
from desktop.updater.models import (
    InstallationResult,
    RollbackStatus,
    TransactionRecord,
    TransactionState,
)
from desktop.updater.process_manager import ProcessHandoff, ProcessShutdownError
from desktop.updater.registry import RegistryError, RegistryManager


def default_install_dir() -> Path:
    """Returns the default Windows installation directory (%LOCALAPPDATA%\\Programs\\Kya-Ray)."""
    local_app_data = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return (Path(local_app_data) / "Programs" / "Kya-Ray").resolve()


def default_data_dir() -> Path:
    """Returns the user data and diagnostic directory (%LOCALAPPDATA%\\Kya-Ray)."""
    local_app_data = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return (Path(local_app_data) / "Kya-Ray").resolve()


class UpdateInstaller:
    """
    Transactional update engine supporting safe installation, rollback,
    interrupted transaction recovery, and application restart with readiness handshake.
    """

    TRANSACTION_FILE = "update_transaction.json"
    STARTUP_HANDSHAKE_TIMEOUT = 10.0  # Bounded wait for genuine app readiness

    def __init__(
        self,
        install_dir: Optional[Union[str, Path]] = None,
        data_dir: Optional[Union[str, Path]] = None,
        registry_manager: Optional[RegistryManager] = None,
        extractor: Optional[PackageExtractor] = None,
        process_handoff: Optional[ProcessHandoff] = None,
        app_launcher: Optional[Callable[[Path], subprocess.Popen]] = None,
        handshake_timeout: float = STARTUP_HANDSHAKE_TIMEOUT,
    ):
        self.install_dir = Path(install_dir or default_install_dir()).resolve()
        self.data_dir = Path(data_dir or default_data_dir()).resolve()
        self.registry = registry_manager or RegistryManager()
        self.extractor = extractor or PackageExtractor()
        self.process_handoff = process_handoff or ProcessHandoff(self.install_dir)
        self._app_launcher = app_launcher
        self.handshake_timeout = handshake_timeout

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.transaction_file_path = self.data_dir / self.TRANSACTION_FILE

    # -------------------------------------------------------------------------
    # Logging Helper
    # -------------------------------------------------------------------------
    def _log(self, level: str, message: str) -> None:
        """Appends a structured timestamped message to kya-ray.log without logging secrets."""
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        line = f"[{now_iso}] [Updater] [{level.upper()}] {message}\n"
        log_path = self.data_dir / "kya-ray.log"
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Transaction State Persistence and Recovery
    # -------------------------------------------------------------------------
    def _record_transaction(
        self,
        transaction_id: str,
        state: TransactionState,
        previous_version: str,
        target_version: str,
        backup_dir: Path,
        staging_dir: Path,
        preserve_env: bool = True,
    ) -> TransactionRecord:
        record = TransactionRecord(
            transaction_id=transaction_id,
            state=state,
            previous_version=previous_version,
            target_version=target_version,
            install_dir=str(self.install_dir),
            backup_dir=str(backup_dir),
            staging_dir=str(staging_dir),
            preserve_env=preserve_env,
            timestamp=time.time(),
        )
        try:
            temp_tx = self.transaction_file_path.with_suffix(".tmp")
            with open(temp_tx, "w", encoding="utf-8") as f:
                json.dump(record.__dict__, f, indent=2)
            os.replace(temp_tx, self.transaction_file_path)
        except Exception as e:
            self._log("warn", f"Could not write transaction state: {e}")
        return record

    def _clear_transaction(self) -> None:
        """Removes the persistent transaction record on clean completion."""
        try:
            if self.transaction_file_path.is_file():
                self.transaction_file_path.unlink()
        except Exception:
            pass

    def recover_interrupted_transaction(self) -> Optional[InstallationResult]:
        """
        Inspects on-disk state for an incomplete transaction from a prior interrupted run.
        Handles crashes between every state transition, never deleting the only copy.
        """
        if not self.transaction_file_path.is_file():
            return None

        self._log("warn", "Interrupted transaction file detected. Initiating recovery...")

        try:
            with open(self.transaction_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Transaction file content must be a JSON dictionary")
            state_str = data.get("state")
            if not state_str:
                raise ValueError("Transaction state is missing in transaction record")
            state = TransactionState(state_str)
            backup_dir_raw = data.get("backup_dir", "")
            staging_dir_raw = data.get("staging_dir", "")
            prev_version = data.get("previous_version", "")
        except Exception as e:
            self._log("error", f"Malformed transaction file during recovery: {e}")
            # Do not delete or overwrite the invalid transaction record; preserve it for diagnosis/manual recovery
            return InstallationResult(
                success=False,
                rollback_status=RollbackStatus.FAILED,
                error_message=f"Corrupt transaction record: {e}",
                install_dir=str(self.install_dir),
            )

        if state == TransactionState.COMMITTED:
            self._clear_transaction()
            return None

        # Validate deserialized backup_dir and staging_dir paths
        expected_parent = self.install_dir.parent.resolve()

        def _validate_tx_path(p_raw: Union[str, Path], expected_prefix: str, field_name: str) -> Path:
            if not p_raw or not str(p_raw).strip():
                raise ValueError(f"{field_name} path is empty")
            raw_str = str(p_raw).replace("\\", "/")
            if ".." in raw_str.split("/"):
                raise ValueError(f"Path traversal ('..') detected in {field_name}: '{p_raw}'")

            # Validate after resolving the path
            p_resolved = Path(p_raw).resolve()

            # Require each directory's resolved parent to equal self.install_dir.parent.resolve()
            if p_resolved.parent != expected_parent:
                raise ValueError(
                    f"{field_name} resolved parent '{p_resolved.parent}' does not match "
                    f"expected parent directory '{expected_parent}' (escaped or nested paths are rejected)"
                )

            # Do not accept arbitrary nested descendants, even if they remain inside the parent
            try:
                rel = p_resolved.relative_to(expected_parent)
            except ValueError:
                raise ValueError(f"{field_name} '{p_raw}' escapes expected parent directory '{expected_parent}'")

            if len(rel.parts) != 1:
                raise ValueError(
                    f"{field_name} '{p_raw}' has unexpected nesting under '{expected_parent}' (expected direct child)"
                )

            name_lower = p_resolved.name.lower()
            pref_lower = expected_prefix.lower()
            alt_pref = f"{self.install_dir.name.lower()}.backup-"
            if not name_lower.startswith(pref_lower) and not name_lower.startswith(alt_pref):
                raise ValueError(f"{field_name} '{p_resolved.name}' does not match expected convention '{expected_prefix}*'")

            return p_resolved

        try:
            backup_dir = _validate_tx_path(backup_dir_raw, "Kya-Ray.backup-", "backup_dir")
            staging_dir = _validate_tx_path(staging_dir_raw, ".kya-ray-staging-", "staging_dir")
        except ValueError as ve:
            self._log("error", f"Unsafe or tampered path in transaction record: {ve}")
            # Do not delete or overwrite the invalid transaction record when recovery cannot safely proceed.
            # Preserve the original record for diagnosis and manual recovery.
            # Return failure result to halt normal startup. Do not touch installation or backups.
            return InstallationResult(
                success=False,
                previous_version=prev_version,
                rollback_status=RollbackStatus.FAILED,
                error_message=f"Transaction path validation rejected: {ve}",
                install_dir=str(self.install_dir),
            )

        # Clean up staging directory regardless of state
        if staging_dir.is_dir():
            self._safe_rmtree(staging_dir)

        # State 1: STAGED -> Installation was never modified unless move occurred
        if state == TransactionState.STAGED:
            if not self.install_dir.is_dir() and backup_dir.is_dir():
                self._log("warn", "Interrupted during transition from STAGED: restoring backup...")
                self._atomic_move(backup_dir, self.install_dir)
                self._clear_transaction()
                return InstallationResult(
                    success=False,
                    previous_version=prev_version,
                    rollback_status=RollbackStatus.SUCCEEDED,
                    error_message="Restored previous installation after crash following backup move.",
                    install_dir=str(self.install_dir),
                )
            self._clear_transaction()
            self._log("info", "Interrupted in STAGED phase: installation was unaffected.")
            return InstallationResult(
                success=False,
                previous_version=prev_version,
                rollback_status=RollbackStatus.NOT_NEEDED,
                error_message="Cleaned up interrupted staging phase; existing installation is intact.",
                install_dir=str(self.install_dir),
            )

        # State 2, 3, 4: BACKUP_CREATED, INSTALLING, INSTALLED, ROLLED_BACK
        # The installation directory may be missing, incomplete, or corrupted.
        rollback_ok = False
        if backup_dir.is_dir():
            try:
                # Remove incomplete install_dir if present
                if self.install_dir.is_dir():
                    self._safe_rmtree(self.install_dir)

                self._atomic_move(backup_dir, self.install_dir)
                rollback_ok = True

                if prev_version and prev_version != "unknown":
                    try:
                        self.registry.set_display_version(prev_version)
                    except Exception:
                        pass
                self._log("info", f"Successfully restored installation from backup {backup_dir}")
            except Exception as e:
                self._log("error", f"Failed restoring backup during transaction recovery: {e}")
        else:
            # Backup directory does not exist: NEVER delete the only existing installation!
            if self.install_dir.is_dir() and (self.install_dir / "Kya-Ray.exe").is_file():
                self._log("warn", "No backup directory found, but existing install_dir contains Kya-Ray.exe; preserving it.")
                rollback_ok = True
            else:
                self._log("error", "No backup directory found to restore, and install_dir is invalid.")

        if rollback_ok:
            self._clear_transaction()
        return InstallationResult(
            success=False,
            previous_version=prev_version,
            rollback_status=RollbackStatus.SUCCEEDED if rollback_ok else RollbackStatus.FAILED,
            error_message="Recovered from an interrupted update transaction." if rollback_ok else "Recovery failed: no valid backup or installation found.",
            install_dir=str(self.install_dir),
            backup_dir=str(backup_dir) if backup_dir.exists() else None,
        )

    # -------------------------------------------------------------------------
    # Core Update Installation Workflow
    # -------------------------------------------------------------------------
    def install(
        self,
        zip_path: Union[str, Path],
        target_version: str,
        pids_to_wait: Optional[Iterable[int]] = None,
        restart_after: bool = True,
    ) -> InstallationResult:
        """
        Executes a safe transactional update.

        Args:
            zip_path: Verified release ZIP archive.
            target_version: Version string of the update (e.g. '1.0.0-beta.2').
            pids_to_wait: Optional PIDs of running Kya-Ray processes to terminate.
            restart_after: Whether to launch the updated application upon success.

        Returns:
            InstallationResult describing the final outcome.
        """
        zip_path = Path(zip_path).resolve()
        tx_id = f"tx-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        self._log("info", f"Starting update transaction {tx_id} to install {target_version}")

        # First, recover any stale incomplete transaction
        recovery_result = self.recover_interrupted_transaction()
        if recovery_result and recovery_result.rollback_status == RollbackStatus.FAILED:
            return recovery_result

        # Identify previous version
        prev_version = self.registry.get_display_version() or "unknown"

        # Unique same-volume staging and backup directories
        parent_dir = self.install_dir.parent
        parent_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = parent_dir / f".kya-ray-staging-{tx_id}"
        backup_dir = parent_dir / f"Kya-Ray.backup-{tx_id}"
        preserved_env_path = self.data_dir / f".env.preserve-{tx_id}"

        # 1. Extraction and Validation Phase
        try:
            self._log("info", f"Extracting and validating archive: {zip_path.name}")
            payload_root = self.extractor.extract_and_validate(zip_path, staging_dir)
            self._record_transaction(
                tx_id, TransactionState.STAGED, prev_version, target_version, backup_dir, staging_dir
            )
        except (UnsafeArchiveError, InvalidPackageError, InsufficientDiskSpaceError, ExtractorError, Exception) as e:
            self._log("error", f"Package extraction or validation failed: {e}")
            self._safe_rmtree(staging_dir)
            return InstallationResult(
                success=False,
                previous_version=prev_version,
                rollback_status=RollbackStatus.NOT_NEEDED,
                error_message=f"Validation failed: {e}",
            )

        # 2. Application Shutdown and File Lock Verification
        try:
            self._log("info", "Waiting for existing Kya-Ray processes to shut down...")
            self.process_handoff.wait_for_shutdown(pids=pids_to_wait)
        except ProcessShutdownError as e:
            self._log("error", f"Process shutdown failed: {e}")
            self._safe_rmtree(staging_dir)
            return InstallationResult(
                success=False,
                previous_version=prev_version,
                rollback_status=RollbackStatus.NOT_NEEDED,
                error_message=f"Process shutdown failed: {e}",
            )

        # 3. Preserve User-Specific Configuration (.env)
        existing_env = self.install_dir / ".env"
        env_preserved = False
        if existing_env.is_file():
            try:
                shutil.copy2(existing_env, preserved_env_path)
                env_preserved = True
                self._log("info", "User .env configuration preserved successfully.")
            except Exception as e:
                self._log("warn", f"Could not preserve existing .env: {e}")

        # 4. Prepare Backup and Perform Atomic Replacement
        existing_installation_exists = self.install_dir.is_dir()
        try:
            if existing_installation_exists:
                self._log("info", f"Backing up current installation to {backup_dir.name}")
                self._atomic_move(self.install_dir, backup_dir)
                self._record_transaction(
                    tx_id, TransactionState.BACKUP_CREATED, prev_version, target_version, backup_dir, staging_dir
                )

            self._log("info", f"Promoting staged package to {self.install_dir.name}")
            self._record_transaction(
                tx_id, TransactionState.INSTALLING, prev_version, target_version, backup_dir, staging_dir
            )

            # Move payload_root to install_dir
            self._atomic_move(payload_root, self.install_dir)

            # Compatibility check: Prevent accidental nested directory Kya-Ray/Kya-Ray
            nested_dir = self.install_dir / "Kya-Ray"
            if nested_dir.is_dir() and (nested_dir / "Kya-Ray.exe").is_file() and not (self.install_dir / "Kya-Ray.exe").is_file():
                self._log("warn", "Flattening nested Kya-Ray directory created during promotion...")
                for item in list(nested_dir.iterdir()):
                    target = self.install_dir / item.name
                    if target.exists():
                        if target.is_dir():
                            self._safe_rmtree(target)
                        else:
                            self._safe_unlink(target)
                    shutil.move(str(item), str(target))
                self._safe_rmtree(nested_dir)

            # Preserve or restore uninstall scripts
            inst_uninstaller = self.install_dir / "installer" / "uninstall.bat"
            root_uninstaller = self.install_dir / "uninstall.bat"
            if inst_uninstaller.is_file() and not root_uninstaller.is_file():
                try:
                    shutil.copy2(inst_uninstaller, root_uninstaller)
                    ps1_src = self.install_dir / "installer" / "uninstall.ps1"
                    if ps1_src.is_file():
                        shutil.copy2(ps1_src, self.install_dir / "uninstall.ps1")
                except Exception:
                    pass

            # Restore user .env (never overwritten by .env.example)
            if env_preserved and preserved_env_path.is_file():
                shutil.copy2(preserved_env_path, self.install_dir / ".env")
                self._safe_unlink(preserved_env_path)

            # Verify the installed files
            self._verify_installation_integrity()

            # 5. Update Registry DisplayVersion
            self._log("info", f"Updating Windows Registry DisplayVersion to {target_version}")
            self.registry.set_display_version(target_version)
            self._record_transaction(
                tx_id, TransactionState.INSTALLED, prev_version, target_version, backup_dir, staging_dir
            )

        except Exception as e:
            self._log("error", f"Installation step failed: {e}. Initiating rollback...")
            rb_status = self._rollback(backup_dir, preserved_env_path, prev_version)
            self._safe_rmtree(staging_dir)
            return InstallationResult(
                success=False,
                previous_version=prev_version,
                rollback_status=rb_status,
                error_message=f"Installation failed: {e}",
                install_dir=str(self.install_dir),
                backup_dir=str(backup_dir) if backup_dir.exists() else None,
            )

        # 6. Application Restart and Genuine Startup Validation
        restarted = False
        if restart_after:
            self._log("info", "Restarting newly installed Kya-Ray application...")
            startup_ok, start_err = self._restart_and_validate(target_version=target_version)
            if not startup_ok:
                self._log("error", f"Post-update startup validation failed: {start_err}. Initiating rollback...")
                rb_status = self._rollback(backup_dir, preserved_env_path, prev_version)
                self._safe_rmtree(staging_dir)
                return InstallationResult(
                    success=False,
                    previous_version=prev_version,
                    rollback_status=rb_status,
                    error_message=f"Application failed to start after update: {start_err}",
                    install_dir=str(self.install_dir),
                    backup_dir=str(backup_dir) if backup_dir.exists() else None,
                )
            restarted = True

        # 7. Commit Transaction and Cleanup
        self._log("info", f"Update to {target_version} verified and committed successfully.")
        self._safe_rmtree(staging_dir)
        self._safe_rmtree(backup_dir)
        self._safe_unlink(preserved_env_path)
        self._clear_transaction()

        return InstallationResult(
            success=True,
            installed_version=target_version,
            previous_version=prev_version,
            rollback_status=RollbackStatus.NOT_NEEDED,
            install_dir=str(self.install_dir),
            restarted=restarted,
        )

    # -------------------------------------------------------------------------
    # Verification, Rollback, and Restart Helpers
    # -------------------------------------------------------------------------
    def _verify_installation_integrity(self) -> None:
        """Verifies that the target install directory contains a valid Kya-Ray.exe."""
        exe_path = self.install_dir / "Kya-Ray.exe"
        if not exe_path.is_file():
            raise InvalidPackageError(f"Kya-Ray.exe missing from installation target {self.install_dir}")

        if exe_path.stat().st_size < 1024:
            raise InvalidPackageError("Installed Kya-Ray.exe is corrupt or empty.")

        with open(exe_path, "rb") as f:
            if f.read(2) != b"MZ":
                raise InvalidPackageError("Installed Kya-Ray.exe missing valid PE header.")

    def _rollback(
        self,
        backup_dir: Path,
        preserved_env_path: Path,
        previous_version: str,
    ) -> RollbackStatus:
        """
        Rolls back failed installation:
        - Removes partially installed directory.
        - Restores backup to install_dir.
        - Restores previous DisplayVersion in registry.
        - Preserves user configuration.
        """
        try:
            # Safety check: Verify backup exists BEFORE removing install_dir
            if not backup_dir or not backup_dir.is_dir():
                self._log("error", f"Backup directory '{backup_dir}' not found to restore. Preserving current installation intact.")
                return RollbackStatus.FAILED

            # 1. Remove failed installation files only now that backup is confirmed present
            if self.install_dir.is_dir():
                self._safe_rmtree(self.install_dir)

            # 2. Restore previous installation from backup
            self._atomic_move(backup_dir, self.install_dir)
            self._log("info", f"Restored previous installation from backup: {backup_dir.name}")

            # 3. Restore preserved .env if needed
            if preserved_env_path.is_file() and self.install_dir.is_dir():
                shutil.copy2(preserved_env_path, self.install_dir / ".env")
                self._safe_unlink(preserved_env_path)

            # 4. Restore registry DisplayVersion
            if previous_version and previous_version != "unknown":
                try:
                    self.registry.set_display_version(previous_version)
                except Exception as reg_err:
                    self._log("warn", f"Could not restore registry version during rollback: {reg_err}")

            return RollbackStatus.SUCCEEDED

        except Exception as e:
            self._log("error", f"CRITICAL: Rollback failed: {e}")
            return RollbackStatus.FAILED

    def _restart_and_validate(self, target_version: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Launches the installed executable and validates readiness via a bounded handshake.
        Distinguishes a healthy application from a crashed, hung, or frozen one.
        """
        exe_path = self.install_dir / "Kya-Ray.exe"
        if not exe_path.is_file():
            return False, f"Executable not found at {exe_path}"

        handshake_file = self.data_dir / f".ready-{uuid.uuid4().hex[:6]}.json"
        self._safe_unlink(handshake_file)

        os.environ["KYA_RAY_HANDSHAKE_FILE"] = str(handshake_file)
        child_env = os.environ.copy()

        proc = None
        try:
            if self._app_launcher:
                proc = self._app_launcher(exe_path)
            else:
                creationflags = 0
                if sys.platform == "win32":
                    creationflags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)

                proc = subprocess.Popen(
                    [str(exe_path)],
                    cwd=str(self.install_dir),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=child_env,
                    creationflags=creationflags,
                )

            # Bounded readiness handshake polling
            deadline = time.monotonic() + self.handshake_timeout
            poll_interval = 0.25

            while time.monotonic() < deadline:
                # 1. Did the process crash immediately?
                if proc.poll() is not None and proc.returncode != 0:
                    self._safe_unlink(handshake_file)
                    return False, f"Process crashed immediately (exit code: {proc.returncode})"

                # 2. Check for readiness handshake file
                if handshake_file.is_file():
                    try:
                        with open(handshake_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        data = None  # File write may still be in progress

                    if data and isinstance(data, dict):
                        # 2a. Validate status
                        status = data.get("status")
                        if status != "ready":
                            self._safe_unlink(handshake_file)
                            self._terminate_proc(proc)
                            return False, f"Handshake status mismatch: expected 'ready', got '{status}'"

                        # 2b. Validate version
                        version = data.get("version")
                        if target_version and version != target_version:
                            self._safe_unlink(handshake_file)
                            self._terminate_proc(proc)
                            return False, f"Handshake version mismatch: expected '{target_version}', got '{version}'"

                        # 2c. Validate process PID
                        expected_pid = getattr(proc, "pid", None)
                        handshake_pid = data.get("pid")
                        if expected_pid is not None and handshake_pid != expected_pid:
                            self._safe_unlink(handshake_file)
                            self._terminate_proc(proc)
                            return False, f"Handshake PID mismatch: expected {expected_pid}, got {handshake_pid}"

                        self._safe_unlink(handshake_file)
                        return True, None

                time.sleep(poll_interval)

            # Handshake timed out: process is frozen or hung on startup
            self._terminate_proc(proc)

            self._safe_unlink(handshake_file)
            return False, (
                f"Application startup timed out after {self.handshake_timeout}s without completing "
                "readiness handshake (process frozen or failed to initialize)."
            )

        except Exception as e:
            self._safe_unlink(handshake_file)
            return False, f"Failed spawning process: {e}"
        finally:
            os.environ.pop("KYA_RAY_HANDSHAKE_FILE", None)

    def _terminate_proc(self, proc: Optional[subprocess.Popen]) -> None:
        """Gracefully terminates then force-kills a spawned process if still active."""
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    # -------------------------------------------------------------------------
    # Filesystem Helpers with Transient Lock Retries
    # -------------------------------------------------------------------------
    def _retry_fs(self, func: Callable, *args, max_retries: int = 5, base_delay: float = 0.15):
        """Executes a filesystem operation with exponential backoff on transient sharing/permission errors."""
        last_err = None
        for attempt in range(max_retries):
            try:
                return func(*args)
            except (PermissionError, OSError) as e:
                last_err = e
                time.sleep(base_delay * (2 ** attempt))
        raise last_err

    def _atomic_move(self, src: Path, dst: Path) -> None:
        """
        Moves src to dst. Prefers atomic os.replace on same volume with retry logic
        for transient Windows file sharing violations / AV locks.
        """
        src = Path(src)
        dst = Path(dst)

        if not src.exists():
            raise FileNotFoundError(f"Source path does not exist: {src}")

        # On Windows, os.replace directory-over-directory fails with Access Denied if dst exists.
        # Ensure dst is removed first (unless src and dst are the same path).
        if dst.exists():
            if dst.resolve() == src.resolve():
                return
            self._safe_rmtree(dst)

        def _do_move():
            try:
                os.replace(src, dst)
            except OSError:
                # Fallback across filesystem/mount boundaries
                if dst.exists():
                    self._safe_rmtree(dst)
                shutil.move(str(src), str(dst))

        self._retry_fs(_do_move)

    def _safe_rmtree(self, path: Path) -> None:
        if path.is_dir():
            def _rm():
                shutil.rmtree(path, ignore_errors=False)
            try:
                self._retry_fs(_rm, max_retries=3, base_delay=0.1)
            except Exception:
                # Final fallback: ignore errors
                shutil.rmtree(path, ignore_errors=True)

    def _safe_unlink(self, path: Path) -> None:
        if path.is_file():
            def _un():
                path.unlink()
            try:
                self._retry_fs(_un, max_retries=3, base_delay=0.1)
            except Exception:
                pass
