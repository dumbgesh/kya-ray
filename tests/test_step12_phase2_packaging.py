"""
tests/test_step12_phase2_packaging.py - Tests for Kya-Ray Step 12 Phase 2 Packaging & Deployment.

Covers:
1. Flexible .env resolution supporting PyInstaller frozen executable directories.
2. Frozen backend lifecycle: BackendProcessManager command generation in frozen vs non-frozen mode.
3. Embedded backend CLI entrypoint (--backend flag) handling without GUI initialization.
4. Modernized PyInstaller spec structure (targets PySide6 app, collects backend, excludes legacy Tkinter).
5. START_KYA_RAY.bat verification (no Ollama references, checks port 8000 /health).
"""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.config import get_env_file_candidates, load_env_file
from desktop.core.backend_manager import BackendProcessManager


# ============================================================================
# 1. Configuration & .env Resolution in Frozen Mode
# ============================================================================

def test_get_env_file_candidates_includes_exe_dir_when_frozen(tmp_path):
    """When sys.frozen is True, candidate paths must prioritize the executable directory."""
    fake_exe = tmp_path / "bin" / "Kya-Ray.exe"
    fake_exe.parent.mkdir(parents=True, exist_ok=True)
    fake_exe.touch()

    with patch.object(sys, "frozen", True, create=True), \
         patch.object(sys, "executable", str(fake_exe)):
        candidates = get_env_file_candidates()
        assert len(candidates) > 0
        assert candidates[0] == fake_exe.parent / ".env"


def test_load_env_file_loads_from_frozen_exe_dir(tmp_path):
    """load_env_file must load variables from .env located next to frozen executable."""
    fake_exe = tmp_path / "bin" / "Kya-Ray.exe"
    fake_exe.parent.mkdir(parents=True, exist_ok=True)
    fake_exe.touch()

    env_file = fake_exe.parent / ".env"
    env_file.write_text("TEST_PACKAGED_VAR=packaged_success\n", encoding="utf-8")

    with patch.object(sys, "frozen", True, create=True), \
         patch.object(sys, "executable", str(fake_exe)), \
         patch.dict(os.environ, {}, clear=False):
        # Clear variable if present
        os.environ.pop("TEST_PACKAGED_VAR", None)
        load_env_file(override=True)
        assert os.environ.get("TEST_PACKAGED_VAR") == "packaged_success"


def test_load_env_file_does_not_override_existing_env_unless_specified(tmp_path):
    """Explicitly set environment variables must not be stomped by .env unless override=True."""
    fake_exe = tmp_path / "Kya-Ray.exe"
    fake_exe.touch()
    env_file = tmp_path / ".env"
    env_file.write_text("EXISTING_KEY=from_file\n", encoding="utf-8")

    with patch.object(sys, "frozen", True, create=True), \
         patch.object(sys, "executable", str(fake_exe)), \
         patch.dict(os.environ, {"EXISTING_KEY": "from_system_env"}, clear=False):
        load_env_file(override=False)
        assert os.environ["EXISTING_KEY"] == "from_system_env"


def test_safe_output_provides_isatty_and_stream_methods(tmp_path):
    """SafeOutput must support isatty(), readable(), writable() for uvicorn/logging compatibility."""
    from desktop.utils.logger import SafeOutput

    log_file = tmp_path / "kya-ray.log"
    out = SafeOutput(None, str(log_file))

    assert hasattr(out, "isatty")
    assert out.isatty() is False
    assert out.readable() is False
    assert out.writable() is True
    assert out.seekable() is False


# ============================================================================
# 2. Backend Process Lifecycle Command Generation
# ============================================================================

@patch("subprocess.Popen")
def test_backend_manager_spawns_embedded_backend_when_frozen(mock_popen, tmp_path):
    """In frozen mode, BackendProcessManager must invoke sys.executable --backend."""
    fake_exe = tmp_path / "Kya-Ray.exe"
    fake_exe.touch()

    mock_client = MagicMock()
    mock_client.check_health.side_effect = [
        ("offline", "Not running"),
        ("ready", "Healthy"),
    ]

    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    mock_popen.return_value = fake_proc

    with patch.object(sys, "frozen", True, create=True), \
         patch.object(sys, "executable", str(fake_exe)):
        manager = BackendProcessManager(client=mock_client, host="127.0.0.1", port=8000, startup_timeout=2.0, poll_interval=0.01)
        success, msg = manager.ensure_running()

        assert success is True
        mock_popen.assert_called_once()
        spawned_cmd = mock_popen.call_args[0][0]

        assert spawned_cmd[0] == str(fake_exe)
        assert "--backend" in spawned_cmd
        assert "--host" in spawned_cmd
        assert "--port" in spawned_cmd


@patch("subprocess.Popen")
def test_backend_manager_spawns_uvicorn_module_when_not_frozen(mock_popen):
    """In non-frozen mode (development/testing), BackendProcessManager invokes uvicorn module."""
    mock_client = MagicMock()
    mock_client.check_health.side_effect = [
        ("offline", "Not running"),
        ("ready", "Healthy"),
    ]

    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    mock_popen.return_value = fake_proc

    with patch.object(sys, "frozen", False, create=True):
        manager = BackendProcessManager(client=mock_client, host="127.0.0.1", port=8000, startup_timeout=2.0, poll_interval=0.01)
        success, msg = manager.ensure_running()

        assert success is True
        mock_popen.assert_called_once()
        spawned_cmd = mock_popen.call_args[0][0]

        assert "-m" in spawned_cmd
        assert "uvicorn" in spawned_cmd
        assert "backend.main:app" in spawned_cmd


# ============================================================================
# 3. Embedded Backend CLI Entrypoint
# ============================================================================

def test_desktop_app_handles_backend_flag_without_gui():
    """desktop.app.main() must delegate to run_embedded_backend and exit without GUI."""
    with patch("sys.argv", ["Kya-Ray.exe", "--backend", "--host", "127.0.0.1", "--port", "8888"]), \
         patch("desktop.app.run_embedded_backend") as mock_run_backend, \
         patch("desktop.app.KyaRayApplication") as mock_gui_app:
        with pytest.raises(SystemExit) as excinfo:
            from desktop.app import main
            main()

        assert excinfo.value.code == 0
        mock_run_backend.assert_called_once_with(host="127.0.0.1", port=8888)
        mock_gui_app.assert_not_called()


# ============================================================================
# 4. PyInstaller Spec Modernisation Verification
# ============================================================================

def test_spec_file_targets_pyside6_app():
    """kya-ray.spec must target desktop/app.py and exclude tkinter."""
    spec_path = Path(__file__).resolve().parent.parent / "kya-ray.spec"
    assert spec_path.is_file()

    content = spec_path.read_text(encoding="utf-8")
    assert "desktop/app.py" in content
    assert "'tkinter'" in content  # Must be in excludes
    assert "prototype/main.py" not in content
    assert "collect_submodules('uvicorn')" in content
    assert "collect_submodules('fastapi')" in content
    assert "collect_submodules('groq')" in content


# ============================================================================
# 5. START_KYA_RAY.bat Modernisation Verification
# ============================================================================

def test_start_bat_has_no_ollama_and_checks_backend():
    """START_KYA_RAY.bat must not contain Ollama or port 11434, and must check port 8000."""
    bat_path = Path(__file__).resolve().parent.parent / "START_KYA_RAY.bat"
    assert bat_path.is_file()

    content = bat_path.read_text(encoding="utf-8")
    assert "ollama" not in content.lower()
    assert "11434" not in content
    assert "8000" in content
    assert "/health" in content
    assert "tasklist" in content

