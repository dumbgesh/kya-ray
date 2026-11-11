"""
desktop/updater/cli.py - Standalone Updater CLI and Detached Process Launcher.

Enables running the update installer as an independent process outside the
main application's installation directory, ensuring zero locked files on Windows.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import List, Optional

from desktop.updater.installer import (
    UpdateInstaller,
    default_data_dir,
    default_install_dir,
)
from desktop.updater.models import InstallationResult
from desktop.updater.registry import RegistryManager


def _is_temp_updater_dir_in_use(dir_path: Path) -> bool:
    """Checks whether a temporary updater directory is currently held or executed by an active process."""
    # 1. Check PID lock file if present
    pid_file = dir_path / ".updater.pid"
    if pid_file.is_file():
        try:
            pid_str = pid_file.read_text().strip()
            if pid_str.isdigit():
                pid = int(pid_str)
                if sys.platform == "win32":
                    import ctypes
                    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                    if h:
                        exit_code = ctypes.c_ulong()
                        is_alive = False
                        if ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code)):
                            is_alive = (exit_code.value == 259)  # STILL_ACTIVE
                        ctypes.windll.kernel32.CloseHandle(h)
                        if is_alive:
                            return True
                else:
                    try:
                        os.kill(pid, 0)
                        return True
                    except OSError:
                        pass
        except Exception:
            pass

    # 2. Check file locks on binaries and libraries in the directory
    for f in list(dir_path.glob("*.exe")) + list(dir_path.glob("*.dll")):
        if not f.is_file():
            continue
        try:
            with open(f, "r+b"):
                pass
        except (PermissionError, OSError):
            return True  # File locked by another running process

    return False


def cleanup_stale_temp_updaters(active_dir: Optional[Path] = None, max_age_seconds: float = 3600.0) -> None:
    """
    Cleans up stale temporary updater directories from prior executions.
    Ensures directories belonging to an active or locked updater process are NEVER deleted.
    """
    temp_root = Path(os.environ.get("TEMP", "/tmp")).resolve()
    active_resolved = active_dir.resolve() if active_dir else None
    now = time.time()

    try:
        for p in temp_root.glob("kya-ray-updater-*"):
            if not p.is_dir():
                continue
            if active_resolved and p.resolve() == active_resolved:
                continue  # Never touch the active directory

            # Age check alone is not sufficient; confirm the directory is not in use by any process
            if _is_temp_updater_dir_in_use(p):
                continue

            try:
                mtime = p.stat().st_mtime
                if now - mtime > max_age_seconds:
                    shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass
    except Exception:
        pass


def launch_detached_updater(
    zip_path: Path,
    target_version: str,
    gui_pid: Optional[int] = None,
    backend_pid: Optional[int] = None,
    install_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    no_restart: bool = False,
) -> subprocess.Popen:
    """
    Launches the updater as a detached standalone process outside install_dir.

    In frozen PyInstaller mode:
      Copies the updater executable, companion DLLs, and complete _internal
      runtime into %TEMP%\\kya-ray-updater-<id> to guarantee zero locked files
      in the installation directory.

    In development mode:
      Executes sys.executable -m desktop.updater.cli detached.
    """
    target_install = Path(install_dir or default_install_dir()).resolve()
    target_data = Path(data_dir or default_data_dir()).resolve()
    zip_resolved = Path(zip_path).resolve()

    pids: List[str] = []
    if gui_pid:
        pids.extend(["--gui-pid", str(gui_pid)])
    if backend_pid:
        pids.extend(["--backend-pid", str(backend_pid)])

    extra_flags: List[str] = []
    if no_restart:
        extra_flags.append("--no-restart")
    reg_sub = os.environ.get("KYA_RAY_REGISTRY_SUBKEY", "").strip()
    if reg_sub:
        extra_flags.extend(["--registry-subkey", reg_sub])

    is_frozen = getattr(sys, "frozen", False)

    if is_frozen:
        # 1. Clean up old stale temporary directories from prior updater runs
        cleanup_stale_temp_updaters()

        # 2. In frozen mode, sys.executable is inside the installation directory.
        # Copy the executable and runtime dependencies to a unique temp directory outside install_dir.
        temp_updater_dir = Path(os.environ.get("TEMP", "/tmp")) / f"kya-ray-updater-{uuid.uuid4().hex[:8]}"
        temp_updater_dir.mkdir(parents=True, exist_ok=True)

        current_exe = Path(sys.executable)
        temp_exe = temp_updater_dir / current_exe.name
        shutil.copy2(current_exe, temp_exe)

        # Copy any root companion DLLs
        for dll_file in current_exe.parent.glob("*.dll"):
            try:
                shutil.copy2(dll_file, temp_updater_dir / dll_file.name)
            except Exception:
                pass

        # Copy complete _internal directory
        internal_src = current_exe.parent / "_internal"
        if internal_src.is_dir():
            internal_dst = temp_updater_dir / "_internal"
            try:
                shutil.copytree(internal_src, internal_dst, dirs_exist_ok=True)
            except Exception as e:
                shutil.rmtree(temp_updater_dir, ignore_errors=True)
                raise RuntimeError(f"Failed to prepare isolated updater runtime (_internal): {e}")

        cmd = [
            str(temp_exe),
            "--updater",
            "--zip", str(zip_resolved),
            "--target-version", str(target_version),
            "--install-dir", str(target_install),
            "--data-dir", str(target_data),
        ] + pids + extra_flags
        cwd = str(temp_updater_dir)

    else:
        # Development / test mode
        cmd = [
            sys.executable,
            "-m",
            "desktop.updater.cli",
            "--zip", str(zip_resolved),
            "--target-version", str(target_version),
            "--install-dir", str(target_install),
            "--data-dir", str(target_data),
        ] + pids + extra_flags
        cwd = str(Path.cwd())

    creationflags = 0
    if sys.platform == "win32":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )

    if is_frozen and proc and proc.pid:
        try:
            (temp_updater_dir / ".updater.pid").write_text(str(proc.pid))
        except Exception:
            pass

    return proc


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint for executing update installation or transaction recovery."""
    parser = argparse.ArgumentParser(description="Kya-Ray Standalone Update Installer")
    parser.add_argument("--updater", action="store_true", help="Internal PyInstaller dispatch flag")
    parser.add_argument("--recover", action="store_true", help="Check and recover any interrupted transaction")
    parser.add_argument("--zip", default=None, help="Path to verified release ZIP package")
    parser.add_argument("--target-version", default=None, help="Target application version string")
    parser.add_argument("--install-dir", default=None, help="Application installation directory")
    parser.add_argument("--data-dir", default=None, help="Application data/logs directory")
    parser.add_argument("--gui-pid", type=int, default=None, help="PID of running desktop GUI process")
    parser.add_argument("--backend-pid", type=int, default=None, help="PID of running backend process")
    parser.add_argument("--registry-subkey", default=None, help="Windows uninstall registry subkey override")
    parser.add_argument("--no-restart", action="store_true", help="Do not restart application after install")

    args = parser.parse_args(argv)

    if args.updater:
        try:
            (Path.cwd() / ".updater.pid").write_text(str(os.getpid()))
        except Exception:
            pass

    reg_mgr = RegistryManager(subkey=args.registry_subkey) if args.registry_subkey else None
    installer = UpdateInstaller(
        install_dir=args.install_dir,
        data_dir=args.data_dir,
        registry_manager=reg_mgr,
    )

    if args.recover:
        rec_res = installer.recover_interrupted_transaction()
        if rec_res:
            print(f"[RECOVERED] Interrupted transaction status: {rec_res.rollback_status.value}")
        else:
            print("[INFO] No interrupted transaction detected.")
        return 0

    if not args.zip or not args.target_version:
        parser.error("--zip and --target-version are required when not running with --recover")

    pids = [p for p in (args.gui_pid, args.backend_pid) if p is not None]

    result: InstallationResult = installer.install(
        zip_path=args.zip,
        target_version=args.target_version,
        pids_to_wait=pids,
        restart_after=not args.no_restart,
    )

    if result.success:
        print(f"[SUCCESS] Updated to {result.installed_version}")
        return 0
    else:
        print(f"[FAILED] Installation failed: {result.error_message}")
        print(f"Rollback status: {result.rollback_status.value}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
