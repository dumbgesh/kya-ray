"""
desktop/updater/checker.py - Core Update Detection Logic for Kya-Ray.

Evaluates GitHub release metadata against the running application version,
enforces stable vs. beta channel rules, validates Windows x64 payload assets,
and provides both synchronous and non-blocking asynchronous execution using daemon workers.
"""

import logging
import re
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from desktop.updater.client import GitHubApiResponse, GitHubReleaseClient
from desktop.updater.models import (
    ReleaseAsset,
    ReleaseInfo,
    UpdateCheckResult,
    UpdateCheckStatus,
)
from version import SemVer, get_current_version

logger = logging.getLogger("kya_ray.updater.checker")

_ASSET_PAYLOAD_REGEX = re.compile(r"^kya[-_]ray.*win64\.zip$", re.IGNORECASE)
_ASSET_CHECKSUM_REGEX = re.compile(r"^kya[-_]ray.*win64\.zip\.sha256$", re.IGNORECASE)

# Track active daemon worker threads for optional graceful shutdown monitoring
_ACTIVE_CHECKER_THREADS: List[threading.Thread] = []
_THREADS_LOCK = threading.Lock()


def shutdown_updater(wait: bool = False) -> None:
    """
    Optional shutdown hook for background update check threads.
    Because worker threads are created as daemon threads, they will never block
    application shutdown even if wait=False.
    """
    with _THREADS_LOCK:
        threads = [t for t in _ACTIVE_CHECKER_THREADS if t.is_alive()]

    if wait:
        for t in threads:
            t.join(timeout=1.0)


def parse_release_asset(raw: Dict[str, Any]) -> Optional[ReleaseAsset]:
    """Extracts a structured ReleaseAsset from raw GitHub asset dict."""
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    url = raw.get("browser_download_url")
    size = raw.get("size")
    if not name or not url:
        return None
    try:
        size_bytes = int(size) if size is not None else 0
    except (ValueError, TypeError):
        size_bytes = 0

    return ReleaseAsset(
        name=str(name),
        download_url=str(url),
        size_bytes=size_bytes,
        content_type=str(raw.get("content_type", "application/octet-stream")),
    )


def extract_assets(raw_assets: Any) -> Tuple[Optional[ReleaseAsset], Optional[ReleaseAsset]]:
    """
    Identifies Windows x64 zip payload asset and its matching valid SHA-256 checksum asset.

    Validates that:
    - Payload matches Kya-Ray-v<ver>-win64.zip
    - Checksum asset corresponds directly to the payload and is non-empty (>0 bytes).
    """
    if not isinstance(raw_assets, list):
        return None, None

    payload_asset: Optional[ReleaseAsset] = None
    checksum_candidate: Optional[ReleaseAsset] = None

    for asset_dict in raw_assets:
        asset = parse_release_asset(asset_dict)
        if not asset:
            continue

        name_lower = asset.name.lower()
        if _ASSET_CHECKSUM_REGEX.match(name_lower) or name_lower.endswith(".sha256"):
            checksum_candidate = asset
        elif _ASSET_PAYLOAD_REGEX.match(name_lower):
            payload_asset = asset

    # Strict validation: Checksum must match payload name and have positive size
    checksum_asset: Optional[ReleaseAsset] = None
    if payload_asset and checksum_candidate:
        cand_name = checksum_candidate.name.lower()
        payload_name = payload_asset.name.lower()
        payload_prefix = payload_name.rsplit(".zip", 1)[0]

        is_matching_name = (
            cand_name == f"{payload_name}.sha256"
            or cand_name == f"{payload_prefix}.sha256"
            or cand_name.startswith(payload_prefix)
        )
        is_valid_size = checksum_candidate.size_bytes > 0

        if is_matching_name and is_valid_size:
            checksum_asset = checksum_candidate
        else:
            logger.debug(
                "Checksum asset %s does not correspond to payload %s or has size 0 (%d)",
                checksum_candidate.name, payload_asset.name, checksum_candidate.size_bytes
            )
    elif checksum_candidate and checksum_candidate.size_bytes > 0:
        checksum_asset = checksum_candidate

    return payload_asset, checksum_asset


def parse_release_item(item: Dict[str, Any]) -> Optional[ReleaseInfo]:
    """Parses a single GitHub release object into a ReleaseInfo instance."""
    if not isinstance(item, dict):
        return None

    # Exclude drafts per requirements
    if item.get("draft") is True:
        return None

    tag_name = item.get("tag_name")
    if not tag_name or not isinstance(tag_name, str):
        return None

    try:
        version = SemVer.parse(tag_name)
    except (ValueError, TypeError) as e:
        logger.debug("Skipping release with invalid SemVer tag %r: %s", tag_name, e)
        return None

    is_prerelease = bool(item.get("prerelease", False) or version.is_prerelease)
    payload_asset, checksum_asset = extract_assets(item.get("assets"))

    return ReleaseInfo(
        tag_name=tag_name,
        version=version,
        name=str(item.get("name") or tag_name),
        body=str(item.get("body") or ""),
        html_url=str(item.get("html_url") or ""),
        published_at=str(item.get("published_at") or ""),
        is_prerelease=is_prerelease,
        is_draft=False,
        payload_asset=payload_asset,
        checksum_asset=checksum_asset,
    )


class UpdateChecker:
    """
    Evaluates GitHub releases to detect available updates for Kya-Ray.
    """

    def __init__(
        self,
        client: Optional[GitHubReleaseClient] = None,
        default_current_version: Optional[Union[str, SemVer]] = None,
    ):
        self.client = client or GitHubReleaseClient()
        self._default_current_version = (
            SemVer.parse(default_current_version)
            if default_current_version
            else None
        )

    def get_current_version(self) -> SemVer:
        """Returns the current application SemVer."""
        if self._default_current_version is not None:
            return self._default_current_version
        return get_current_version()

    def check_for_updates(
        self,
        current_version: Optional[Union[str, SemVer]] = None,
        allow_prereleases: Optional[bool] = None,
        use_cache: bool = True,
    ) -> UpdateCheckResult:
        """
        Synchronously checks GitHub for updates matching channel rules.

        Channel Rules:
        - If allow_prereleases is None, channel is determined automatically:
          - Stable installations (is_prerelease == False) DO NOT receive beta updates.
          - Beta installations (is_prerelease == True) receive newer beta releases and eventual stable releases.
        """
        ver: SemVer = SemVer.parse(current_version) if current_version else self.get_current_version()

        # Automatic channel determination if not explicitly overridden
        if allow_prereleases is None:
            allow_prereleases = ver.is_prerelease

        # Channel: Prerelease (Beta) allows both betas and stable releases
        if allow_prereleases:
            return self._check_all_releases(ver, allow_prereleases=True, use_cache=use_cache)

        # Channel: Stable only allows non-prerelease stable releases
        return self._check_stable_releases(ver, use_cache=use_cache)

    def check_for_updates_async(
        self,
        callback: Callable[[UpdateCheckResult], None],
        current_version: Optional[Union[str, SemVer]] = None,
        allow_prereleases: Optional[bool] = None,
        use_cache: bool = True,
    ) -> threading.Thread:
        """
        Asynchronously checks for updates in a dedicated daemon background worker thread
        and invokes callback. Guarantees the GUI thread is never blocked, and background
        workers never prevent clean application termination.
        """
        def _worker():
            try:
                res = self.check_for_updates(
                    current_version=current_version,
                    allow_prereleases=allow_prereleases,
                    use_cache=use_cache,
                )
            except Exception as e:
                logger.error("Unexpected error in background update checker: %s", e)
                res = UpdateCheckResult(
                    status=UpdateCheckStatus.ERROR,
                    is_update_available=False,
                    current_version=SemVer.parse(current_version) if current_version else self.get_current_version(),
                    error_message=str(e),
                )
            try:
                callback(res)
            except Exception as e:
                logger.error("Error in update checker callback: %s", e)
            finally:
                with _THREADS_LOCK:
                    current_t = threading.current_thread()
                    if current_t in _ACTIVE_CHECKER_THREADS:
                        _ACTIVE_CHECKER_THREADS.remove(current_t)

        worker_thread = threading.Thread(
            target=_worker,
            name="KyaRayUpdaterWorker",
            daemon=True,
        )
        with _THREADS_LOCK:
            _ACTIVE_CHECKER_THREADS.append(worker_thread)

        worker_thread.start()
        return worker_thread

    def _check_stable_releases(self, current_version: SemVer, use_cache: bool) -> UpdateCheckResult:
        """Checks for latest stable release via /releases/latest."""
        api_res: GitHubApiResponse = self.client.fetch_latest_release(use_cache=use_cache)

        error_result = self._handle_api_errors(api_res, current_version)
        if error_result:
            return error_result

        assert api_res.data is not None
        if not isinstance(api_res.data, dict):
            return UpdateCheckResult(
                status=UpdateCheckStatus.INVALID_RESPONSE,
                is_update_available=False,
                current_version=current_version,
                error_message="Unexpected response format for latest release from GitHub",
            )

        release = parse_release_item(api_res.data)
        if not release:
            return UpdateCheckResult(
                status=UpdateCheckStatus.NO_COMPATIBLE_RELEASE,
                is_update_available=False,
                current_version=current_version,
                error_message="No valid stable release metadata available",
            )

        # Ensure stable installations do NOT receive pre-releases
        if release.is_prerelease:
            return UpdateCheckResult(
                status=UpdateCheckStatus.UP_TO_DATE,
                is_update_available=False,
                current_version=current_version,
                latest_version=current_version,
                release_info=release,
                from_cache=api_res.is_cached,
            )

        return self._evaluate_candidate(release, current_version, is_cached=api_res.is_cached)

    def _check_all_releases(
        self,
        current_version: SemVer,
        allow_prereleases: bool,
        use_cache: bool,
    ) -> UpdateCheckResult:
        """Inspects all releases across pages to find the highest valid compatible release."""
        api_res: GitHubApiResponse = self.client.fetch_all_releases(use_cache=use_cache)

        error_result = self._handle_api_errors(api_res, current_version)
        if error_result:
            return error_result

        assert api_res.data is not None
        if not isinstance(api_res.data, list):
            return UpdateCheckResult(
                status=UpdateCheckStatus.INVALID_RESPONSE,
                is_update_available=False,
                current_version=current_version,
                error_message="Expected list of releases from GitHub API",
            )

        parsed_releases: List[ReleaseInfo] = []
        for item in api_res.data:
            rel = parse_release_item(item)
            if not rel:
                continue
            if not allow_prereleases and rel.is_prerelease:
                continue
            parsed_releases.append(rel)

        if not parsed_releases:
            return UpdateCheckResult(
                status=UpdateCheckStatus.NO_COMPATIBLE_RELEASE,
                is_update_available=False,
                current_version=current_version,
                error_message="No compatible releases found in repository",
            )

        # Sort parsed releases by SemVer descending to always select the highest version
        parsed_releases.sort(key=lambda r: r.version, reverse=True)
        highest_release = parsed_releases[0]

        return self._evaluate_candidate(highest_release, current_version, is_cached=api_res.is_cached)

    def _evaluate_candidate(
        self,
        candidate: ReleaseInfo,
        current_version: SemVer,
        is_cached: bool,
    ) -> UpdateCheckResult:
        """Compares candidate version against current version and validates payload assets."""
        if candidate.version > current_version:
            # Must possess valid Windows payload asset to be installable
            if candidate.payload_asset is None:
                return UpdateCheckResult(
                    status=UpdateCheckStatus.NO_COMPATIBLE_RELEASE,
                    is_update_available=False,
                    current_version=current_version,
                    latest_version=candidate.version,
                    release_info=candidate,
                    error_message=f"Release {candidate.tag_name} found, but lacks Windows x64 zip payload asset",
                    from_cache=is_cached,
                )

            return UpdateCheckResult(
                status=UpdateCheckStatus.UPDATE_AVAILABLE,
                is_update_available=True,
                current_version=current_version,
                latest_version=candidate.version,
                release_info=candidate,
                from_cache=is_cached,
            )

        return UpdateCheckResult(
            status=UpdateCheckStatus.UP_TO_DATE,
            is_update_available=False,
            current_version=current_version,
            latest_version=candidate.version,
            release_info=candidate,
            from_cache=is_cached,
        )

    def _handle_api_errors(
        self,
        api_res: GitHubApiResponse,
        current_version: SemVer,
    ) -> Optional[UpdateCheckResult]:
        """Translates GitHub API client errors into structured UpdateCheckResult."""
        if api_res.is_rate_limited:
            return UpdateCheckResult(
                status=UpdateCheckStatus.RATE_LIMITED,
                is_update_available=False,
                current_version=current_version,
                error_message=api_res.error_message or "GitHub API rate limit exceeded",
            )

        if not api_res.is_success:
            status = (
                UpdateCheckStatus.NETWORK_ERROR
                if api_res.status_code == 0
                else UpdateCheckStatus.ERROR
            )
            return UpdateCheckResult(
                status=status,
                is_update_available=False,
                current_version=current_version,
                error_message=api_res.error_message or f"HTTP {api_res.status_code}",
            )

        return None
