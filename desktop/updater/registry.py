"""
desktop/updater/registry.py - Windows Add/Remove Programs Registry Management.

Manages DisplayVersion updates and rollback in the Windows Uninstall key:
HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Kya-Ray
"""

import os
import sys
from pathlib import Path
from typing import Optional

DEFAULT_UNINSTALL_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Kya-Ray"
UNINSTALL_SUBKEY = DEFAULT_UNINSTALL_SUBKEY


def get_default_uninstall_subkey() -> str:
    """Returns the active Windows uninstall registry subkey, supporting test overrides."""
    sub = os.environ.get("KYA_RAY_REGISTRY_SUBKEY", "").strip()
    return sub if sub else DEFAULT_UNINSTALL_SUBKEY


class RegistryError(Exception):
    """Raised when registry access or modification fails."""
    pass


class RegistryManager:
    """
    Reads and updates Kya-Ray uninstaller metadata in the Windows Registry.
    Supports in-memory mock or custom keys for automated testing.
    """

    def __init__(
        self,
        subkey: Optional[str] = None,
        mock_store: Optional[dict] = None,
    ):
        if subkey is None or subkey == DEFAULT_UNINSTALL_SUBKEY:
            self.subkey = get_default_uninstall_subkey()
        else:
            self.subkey = subkey
        self.mock_store = mock_store

    def get_display_version(self) -> Optional[str]:
        """Reads current DisplayVersion string from registry or mock store."""
        if self.mock_store is not None:
            return self.mock_store.get("DisplayVersion")

        if sys.platform != "win32":
            return None

        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.subkey, 0, winreg.KEY_READ) as key:
                val, _ = winreg.QueryValueEx(key, "DisplayVersion")
                return str(val)
        except (FileNotFoundError, OSError):
            return None

    def set_display_version(self, version_str: str) -> None:
        """Sets DisplayVersion string in registry or mock store."""
        if self.mock_store is not None:
            if self.mock_store.get("__fail_write__"):
                raise RegistryError("Simulated registry write failure")
            self.mock_store["DisplayVersion"] = str(version_str)
            return

        if sys.platform != "win32":
            return

        import winreg
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.subkey) as key:
                winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, str(version_str))
        except OSError as e:
            raise RegistryError(f"Failed setting DisplayVersion to '{version_str}': {e}")

    def update_metadata(self, version_str: str, install_dir: Optional[Path] = None) -> None:
        """Updates DisplayVersion and optionally estimated install size."""
        self.set_display_version(version_str)

        if self.mock_store is not None:
            if install_dir:
                self.mock_store["InstallLocation"] = str(install_dir)
            return

        if sys.platform != "win32" or not install_dir or not install_dir.is_dir():
            return

        import winreg
        try:
            total_bytes = sum(f.stat().st_size for f in install_dir.rglob("*") if f.is_file())
            size_kb = int(total_bytes // 1024)
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.subkey, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, size_kb)
                winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
        except OSError:
            pass  # Non-fatal metadata update

