"""
desktop/updater - Automatic Update System for Kya-Ray.
"""

from desktop.updater.checker import UpdateChecker, shutdown_updater
from desktop.updater.client import GitHubApiResponse, GitHubReleaseClient
from desktop.updater.cli import launch_detached_updater
from desktop.updater.downloader import (
    UpdateDownloader,
    compute_file_sha256,
    get_default_updates_dir,
    parse_sha256_checksum,
    verify_file_sha256,
)
from desktop.updater.extractor import (
    ExtractorError,
    InsufficientDiskSpaceError,
    InvalidPackageError,
    PackageExtractor,
    UnsafeArchiveError,
)
from desktop.updater.installer import UpdateInstaller
from desktop.updater.models import (
    DownloadProgress,
    DownloadResult,
    DownloadStatus,
    InstallationResult,
    ReleaseAsset,
    ReleaseInfo,
    RollbackStatus,
    TransactionRecord,
    TransactionState,
    UpdateCheckResult,
    UpdateCheckStatus,
)
from desktop.updater.process_manager import ProcessHandoff, ProcessShutdownError
from desktop.updater.registry import RegistryError, RegistryManager

__all__ = [
    "DownloadProgress",
    "DownloadResult",
    "DownloadStatus",
    "ExtractorError",
    "GitHubApiResponse",
    "GitHubReleaseClient",
    "InstallationResult",
    "InsufficientDiskSpaceError",
    "InvalidPackageError",
    "PackageExtractor",
    "ProcessHandoff",
    "ProcessShutdownError",
    "RegistryError",
    "RegistryManager",
    "ReleaseAsset",
    "ReleaseInfo",
    "RollbackStatus",
    "TransactionRecord",
    "TransactionState",
    "UnsafeArchiveError",
    "UpdateCheckResult",
    "UpdateCheckStatus",
    "UpdateChecker",
    "UpdateDownloader",
    "UpdateInstaller",
    "compute_file_sha256",
    "get_default_updates_dir",
    "launch_detached_updater",
    "parse_sha256_checksum",
    "shutdown_updater",
    "verify_file_sha256",
]
