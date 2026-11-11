"""
desktop/updater/models.py - Data Models for Kya-Ray Automatic Update System.

Defines structured immutable types for release assets, parsed GitHub releases,
and update check results.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from desktop.version import SemVer


class UpdateCheckStatus(str, Enum):
    """Categorized outcome of an update check."""
    UPDATE_AVAILABLE = "update_available"
    UP_TO_DATE = "up_to_date"
    NO_COMPATIBLE_RELEASE = "no_compatible_release"
    RATE_LIMITED = "rate_limited"
    NETWORK_ERROR = "network_error"
    INVALID_RESPONSE = "invalid_response"
    ERROR = "error"


@dataclass(frozen=True)
class ReleaseAsset:
    """Represents a downloadable binary or checksum asset in a GitHub release."""
    name: str
    download_url: str
    size_bytes: int
    content_type: str = "application/octet-stream"


@dataclass(frozen=True)
class ReleaseInfo:
    """Parsed and validated GitHub release metadata."""
    tag_name: str
    version: SemVer
    name: str
    body: str
    html_url: str
    published_at: str
    is_prerelease: bool
    is_draft: bool
    payload_asset: Optional[ReleaseAsset] = None
    checksum_asset: Optional[ReleaseAsset] = None


@dataclass(frozen=True)
class UpdateCheckResult:
    """Structured result returned by the update checker."""
    status: UpdateCheckStatus
    is_update_available: bool
    current_version: SemVer
    latest_version: Optional[SemVer] = None
    release_info: Optional[ReleaseInfo] = None
    error_message: Optional[str] = None
    from_cache: bool = False

    @property
    def release_notes(self) -> str:
        """Convenience accessor for release notes body."""
        return self.release_info.body if self.release_info else ""

    @property
    def release_url(self) -> str:
        """Convenience accessor for release web page URL."""
        return self.release_info.html_url if self.release_info else ""

    @property
    def payload_asset(self) -> Optional[ReleaseAsset]:
        """Convenience accessor for the Windows x64 zip payload asset."""
        return self.release_info.payload_asset if self.release_info else None

    @property
    def checksum_asset(self) -> Optional[ReleaseAsset]:
        """Convenience accessor for the SHA-256 checksum asset."""
        return self.release_info.checksum_asset if self.release_info else None

    @property
    def has_checksum(self) -> bool:
        """Returns True if a non-empty SHA-256 checksum asset is available for this release."""
        return bool(self.checksum_asset and self.checksum_asset.size_bytes > 0)

    @property
    def is_verifiable(self) -> bool:
        """
        Returns True if both the installable ZIP payload AND a valid SHA-256
        checksum asset are present, ensuring the update package can be fully verified.
        """
        return bool(self.payload_asset and self.has_checksum)


class DownloadStatus(str, Enum):
    """Lifecycle status of an update download operation."""
    IDLE = "idle"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass(frozen=True)
class DownloadProgress:
    """Real-time progress reporting structure emitted during streaming downloads."""
    downloaded_bytes: int
    total_bytes: Optional[int] = None
    percent: Optional[float] = None
    speed_bytes_per_sec: float = 0.0
    is_indeterminate: bool = False


@dataclass(frozen=True)
class DownloadResult:
    """Structured immutable outcome of an update package download and SHA-256 verification."""
    status: DownloadStatus
    payload_path: Optional[str] = None
    checksum_path: Optional[str] = None
    verified: bool = False
    sha256_hash: Optional[str] = None
    error_message: Optional[str] = None


class TransactionState(str, Enum):
    """Lifecycle states of an update installation transaction."""
    IDLE = "idle"
    STAGED = "staged"
    BACKUP_CREATED = "backup_created"
    INSTALLING = "installing"
    INSTALLED = "installed"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class RollbackStatus(str, Enum):
    """Outcome of an installation rollback."""
    NOT_NEEDED = "not_needed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class InstallationResult:
    """Outcome of an update installation operation."""
    success: bool
    installed_version: Optional[str] = None
    previous_version: Optional[str] = None
    rollback_status: RollbackStatus = RollbackStatus.NOT_NEEDED
    error_message: Optional[str] = None
    install_dir: Optional[str] = None
    backup_dir: Optional[str] = None
    restarted: bool = False


@dataclass(frozen=True)
class TransactionRecord:
    """Persistent on-disk record of an ongoing or interrupted update transaction."""
    transaction_id: str
    state: TransactionState
    previous_version: str
    target_version: str
    install_dir: str
    backup_dir: str
    staging_dir: str
    preserve_env: bool = True
    timestamp: float = 0.0




