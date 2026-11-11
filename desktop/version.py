"""
desktop/version.py - Compatibility Facade for Root Version Module.

Re-exports version definitions from root version.py to preserve backward
compatibility with any code referencing desktop.version.
"""

from version import (
    APP_VERSION,
    SemVer,
    __version__,
    generate_file_version_info_content,
    get_current_version,
    sync_file_version_info,
    sync_installer_version,
)

__all__ = [
    "APP_VERSION",
    "SemVer",
    "__version__",
    "generate_file_version_info_content",
    "get_current_version",
    "sync_file_version_info",
    "sync_installer_version",
]
