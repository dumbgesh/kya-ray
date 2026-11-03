"""
desktop/core/backend_manager.py - Lightweight lifecycle manager for the local FastAPI backend.

Responsibilities:
1. Probes if the backend is already running on the configured host/port.
2. If healthy and running, adopts it without spawning duplicate processes.
3. If offline, spawns the local backend via `uvicorn backend.main:app`.
4. Waits for health endpoint before allowing AI requests.
5. On shutdown, terminates ONLY the spawned process that this manager owns.
6. Never terminates foreign or unrelated processes using port 8000.
"""

import os
import subprocess
import sys
import time
from typing import Optional, Tuple

from desktop.ai.backend_client import BackendClient
from desktop.utils.config import BACKEND_BASE_URL, BACKEND_HOST, BACKEND_PORT


class BackendProcessManager:
    """
    Manages the lifecycle of the local FastAPI backend process:
    - Avoids duplicate processes by probing /health first.
    - Spawns a background uvicorn process without opening a console window.
    - Waits for health verification before reporting ready.
    - Tracks ownership and terminates only owned processes on shutdown.
    """

    def __init__(
        self,
        client: Optional[BackendClient] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        startup_timeout: float = 8.0,
        poll_interval: float = 0.25,
    ):
        self.client = client or BackendClient()
        self.host = host or BACKEND_HOST
        self.port = port or BACKEND_PORT
        self.startup_timeout = startup_timeout
        self.poll_interval = poll_interval

        self._process: Optional[subprocess.Popen] = None
        self._job_handle: Optional[int] = None
        self._is_owned: bool = False
        self._stopped: bool = False

    def _bind_to_job_object(self, proc: subprocess.Popen) -> None:
        """On Windows, binds child process to a Job Object so it automatically dies if parent exits."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            job = kernel32.CreateJobObjectW(None, None)
            if not job:
                return

            class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD),
                ]

            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong),
                ]

            class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryLimit", ctypes.c_size_t),
                    ("PeakJobMemoryLimit", ctypes.c_size_t),
                ]

            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            res = kernel32.SetInformationJobObject(
                job,
                9,  # JobObjectExtendedLimitInformation
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            proc_handle = getattr(proc, "_handle", None)
            if res and isinstance(proc_handle, int):
                kernel32.AssignProcessToJobObject(job, proc_handle)
                self._job_handle = job
        except Exception:
            pass

    @property
    def is_owned(self) -> bool:
        """True if the backend process was spawned by this manager instance."""
        return self._is_owned

    @property
    def process(self) -> Optional[subprocess.Popen]:
        """Underlying Popen process if owned, else None."""
        return self._process

    @property
    def is_running(self) -> bool:
        """True if the owned process is active or the target backend is healthy."""
        if self._is_owned and self._process:
            return self._process.poll() is None
        try:
            res = self.client.check_health(timeout=1.0)
            if isinstance(res, (tuple, list)) and len(res) >= 2:
                status = res[0]
                return status in ("ready", "groq_unconfigured")
            return False
        except Exception:
            return False

    def ensure_running(self) -> Tuple[bool, str]:
        """
        Ensures the backend is available.
        If already running, adopts it. If offline, starts a local instance.

        Returns:
            Tuple[bool, str]: (success, status_or_error_message)
        """
        # 1. Probe if backend is already running and healthy
        status, msg = self.client.check_health(timeout=1.5)
        if status in ("ready", "groq_unconfigured"):
            self._is_owned = False
            return True, f"Connected to existing backend: {msg}"

        # 2. Check if configured for a non-local remote host
        if self.host not in ("127.0.0.1", "localhost", "0.0.0.0"):
            return False, f"Remote backend at {self.host}:{self.port} is unreachable."

        # 3. Spawn local backend process
        print(f"[BackendManager] Starting local backend on {self.host}:{self.port}...", flush=True)
        try:
            if getattr(sys, "frozen", False):
                # In a PyInstaller-frozen application, sys.executable is Kya-Ray.exe.
                # Launch the embedded backend entrypoint via the --backend flag.
                cmd = [
                    sys.executable,
                    "--backend",
                    "--host",
                    str(self.host),
                    "--port",
                    str(self.port),
                ]
                cwd = os.path.dirname(sys.executable)
            else:
                # In development or testing mode, sys.executable is the Python interpreter.
                cmd = [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "backend.main:app",
                    "--host",
                    str(self.host),
                    "--port",
                    str(self.port),
                ]
                cwd = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

            # On Windows, suppress console window creation
            creationflags = 0
            if sys.platform == "win32":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

            self._process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            self._is_owned = True
            self._stopped = False
            self._bind_to_job_object(self._process)

        except Exception as e:
            self._is_owned = False
            self._process = None
            return False, f"Failed to spawn backend process: {e}"

        # 4. Wait for health endpoint verification
        start_time = time.perf_counter()
        while time.perf_counter() - start_time < self.startup_timeout:
            # Check if process crashed immediately (e.g. port conflict or import failure)
            if self._process.poll() is not None:
                exit_code = self._process.returncode
                self._is_owned = False
                self._process = None
                return False, f"Backend process terminated unexpectedly (exit code: {exit_code})."

            time.sleep(self.poll_interval)
            status, msg = self.client.check_health(timeout=0.6)
            if status in ("ready", "groq_unconfigured"):
                return True, f"Local backend started successfully: {msg}"

        # Startup timed out
        self.stop()
        return False, f"Backend failed to respond on {self.host}:{self.port} within {self.startup_timeout}s."

    def stop(self) -> None:
        """
        Shuts down the backend ONLY if it was spawned and is owned by this manager.
        Foreign processes (e.g. externally launched uvicorn) are never modified.
        """
        if not self._is_owned or self._process is None:
            return

        self._stopped = True
        try:
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=2.5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=1.0)
        except Exception as e:
            print(f"[BackendManager] Error terminating owned backend process: {e}", flush=True)
        finally:
            self._process = None
            self._is_owned = False
            if self._job_handle:
                try:
                    import ctypes
                    ctypes.windll.kernel32.CloseHandle(self._job_handle)
                except Exception:
                    pass
                self._job_handle = None
