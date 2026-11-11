"""
desktop/updater/process_manager.py - Safe Process Shutdown and Lock Verification.

Ensures controlled application shutdown before update installation:
1. Identifies running Kya-Ray processes using verified executable image paths.
2. Never terminates unrelated system or user processes.
3. Bounded waiting for graceful termination.
4. Force terminates only verified Kya-Ray-owned processes after timeout.
5. Verifies all installation files and DLLs are unlocked.
"""

import ctypes
import os
import sys
import time
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Set


class ProcessShutdownError(Exception):
    """Raised when application processes fail to shut down or files remain locked."""
    pass


class ProcessHandoff:
    """
    Coordinates safe shutdown of the running Kya-Ray desktop and backend instances.
    """

    def __init__(
        self,
        install_dir: Path,
        shutdown_timeout: float = 10.0,
        force_kill_timeout: float = 3.0,
        poll_interval: float = 0.25,
        process_path_getter: Optional[Callable[[int], Optional[str]]] = None,
        process_killer: Optional[Callable[[int, bool], bool]] = None,
        running_pid_enumerator: Optional[Callable[[], List[int]]] = None,
    ):
        self.install_dir = Path(install_dir).resolve()
        self.shutdown_timeout = shutdown_timeout
        self.force_kill_timeout = force_kill_timeout
        self.poll_interval = poll_interval
        self._custom_process_path_getter = process_path_getter
        self._custom_process_killer = process_killer
        self._custom_running_pid_enumerator = running_pid_enumerator

    def wait_for_shutdown(self, pids: Optional[Iterable[int]] = None) -> None:
        """
        Waits for target Kya-Ray processes to exit.
        If processes remain alive after shutdown_timeout, verifies they reside within
        install_dir before issuing a forced termination.
        Finally, verifies all files in install_dir are unlocked.

        Args:
            pids: Optional list of known process IDs (e.g. GUI and backend PIDs).
                  If None or empty, scans running processes for binaries inside install_dir.

        Raises:
            ProcessShutdownError: If processes cannot be terminated or files stay locked.
        """
        candidate_pids: Set[int] = set(pids) if pids else set()

        # If no explicit PIDs, discover processes running from install_dir
        if not candidate_pids:
            candidate_pids.update(self.find_processes_in_install_dir())

        if not candidate_pids:
            self.verify_files_unlocked()
            return

        # 1. Bounded wait for graceful exit
        deadline = time.monotonic() + self.shutdown_timeout
        active_pids: Set[int] = set()

        while time.monotonic() < deadline:
            active_pids = {pid for pid in candidate_pids if self._is_process_alive(pid)}
            if not active_pids:
                break
            time.sleep(self.poll_interval)

        # 2. Force termination only for verified Kya-Ray processes
        if active_pids:
            for pid in list(active_pids):
                # Critical safety check: verify the process executable is actually in install_dir
                if self._is_process_owned_by_install_dir(pid):
                    self._terminate_process(pid, force=True)
                else:
                    # Not in install_dir: do not touch!
                    active_pids.discard(pid)

            # Wait for forced kill to take effect
            kill_deadline = time.monotonic() + self.force_kill_timeout
            while time.monotonic() < kill_deadline:
                active_pids = {pid for pid in active_pids if self._is_process_alive(pid)}
                if not active_pids:
                    break
                time.sleep(self.poll_interval)

            if active_pids:
                raise ProcessShutdownError(
                    f"Kya-Ray processes {list(active_pids)} failed to terminate within timeout."
                )

        # 3. Verify file handles are released
        self.verify_files_unlocked()

    def find_processes_in_install_dir(self) -> List[int]:
        """Discovers running processes whose executable image path resides in install_dir."""
        owned_pids: List[int] = []
        all_pids = self._enumerate_pids()
        for pid in all_pids:
            if pid <= 4:
                continue  # Skip System Idle / System
            if self._is_process_owned_by_install_dir(pid):
                owned_pids.append(pid)
        return owned_pids

    def verify_files_unlocked(self, timeout: float = 3.0) -> None:
        """
        Confirms that key executable and binary files in install_dir are not locked.
        Attempts exclusive read-write open on critical binaries.
        """
        if not self.install_dir.is_dir():
            return

        critical_files = list(self.install_dir.glob("*.exe")) + list(self.install_dir.glob("*.dll"))
        if not critical_files:
            return

        deadline = time.monotonic() + timeout
        last_locked: Optional[Path] = None

        while time.monotonic() < deadline:
            locked: Optional[Path] = None
            for p in critical_files:
                if not p.is_file():
                    continue
                try:
                    with open(p, "r+b"):
                        pass
                except (PermissionError, OSError):
                    locked = p
                    break

            if locked is None:
                return  # All files unlocked
            last_locked = locked
            time.sleep(0.2)

        raise ProcessShutdownError(
            f"Installation file '{last_locked.name}' is currently locked by a running process."
        )

    # -------------------------------------------------------------------------
    # Process Inspection and Safety Helpers
    # -------------------------------------------------------------------------
    def _is_process_owned_by_install_dir(self, pid: int) -> bool:
        """
        Verifies that the executable running under PID is strictly located inside install_dir.
        Returns False if the process does not exist, cannot be queried, or is unrelated.
        """
        exe_path_str = self._get_process_executable_path(pid)
        if not exe_path_str:
            return False

        try:
            exe_path = Path(exe_path_str).resolve()
            return exe_path.is_relative_to(self.install_dir)
        except Exception:
            return False

    def _get_process_executable_path(self, pid: int) -> Optional[str]:
        """Retrieves full image path for a given process ID."""
        if self._custom_process_path_getter:
            return self._custom_process_path_getter(pid)

        if sys.platform != "win32":
            # POSIX / procfs fallback
            try:
                proc_exe = Path(f"/proc/{pid}/exe")
                if proc_exe.exists():
                    return str(proc_exe.resolve())
            except Exception:
                pass
            return None

        # Windows native QueryFullProcessImageNameW via kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32

        h_process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h_process:
            return None

        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = ctypes.c_ulong(1024)
            if kernel32.QueryFullProcessImageNameW(h_process, 0, buf, ctypes.byref(size)):
                return buf.value
            return None
        finally:
            kernel32.CloseHandle(h_process)

    def _is_process_alive(self, pid: int) -> bool:
        """Checks whether process pid is currently active."""
        if sys.platform == "win32":
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            kernel32 = ctypes.windll.kernel32
            h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False
            exit_code = ctypes.c_ulong()
            still_active = 259
            if kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code)):
                is_alive = exit_code.value == still_active
            else:
                is_alive = False
            kernel32.CloseHandle(h)
            return is_alive
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False

    def _terminate_process(self, pid: int, force: bool = True) -> bool:
        """Terminates process safely."""
        if self._custom_process_killer:
            return self._custom_process_killer(pid, force)

        if sys.platform == "win32":
            PROCESS_TERMINATE = 0x0001
            kernel32 = ctypes.windll.kernel32
            h = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
            if not h:
                return False
            try:
                res = kernel32.TerminateProcess(h, 1)
                return bool(res)
            finally:
                kernel32.CloseHandle(h)
        else:
            import signal
            sig = signal.SIGKILL if force else signal.SIGTERM
            try:
                os.kill(pid, sig)
                return True
            except OSError:
                return False

    def _enumerate_pids(self) -> List[int]:
        """Enumerates running process IDs."""
        if self._custom_running_pid_enumerator:
            return self._custom_running_pid_enumerator()

        pids: List[int] = []
        if sys.platform == "win32":
            # Use EnumProcesses from psapi
            try:
                psapi = ctypes.windll.psapi
                count = 2048
                arr = (ctypes.c_ulong * count)()
                bytes_returned = ctypes.c_ulong()
                if psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(bytes_returned)):
                    num_pids = bytes_returned.value // ctypes.sizeof(ctypes.c_ulong)
                    pids = [int(arr[i]) for i in range(num_pids)]
            except Exception:
                pass
        return pids

