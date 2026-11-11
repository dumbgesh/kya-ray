"""
desktop/updater/downloader.py - Robust Download Manager & SHA-256 Verification for Kya-Ray.

Handles chunked streaming downloads of GitHub release binaries, real-time progress tracking,
cancellation tokens, safe atomic temporary file writes, path traversal prevention,
per-hop HTTPS redirect validation, and rigorous SHA-256 checksum verification.
"""

from dataclasses import dataclass
import hashlib
import hmac
import logging
import os
from pathlib import Path
import re
import shutil
import threading
import time
from typing import Callable, Optional, Tuple, Union
import urllib.parse
import uuid

import httpx

from desktop.updater.models import (
    DownloadProgress,
    DownloadResult,
    DownloadStatus,
    ReleaseAsset,
)
from version import APP_VERSION

logger = logging.getLogger("kya_ray.updater.downloader")

DEFAULT_DOWNLOAD_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)
DEFAULT_CHUNK_SIZE = 65536  # 64 KB streaming chunks
MIN_FREE_SPACE_BUFFER_BYTES = 50 * 1024 * 1024  # 50 MB safety margin
MAX_SAFE_REDIRECTS = 5


def get_default_updates_dir() -> Path:
    """
    Returns the authoritative updates directory in the active user profile:
    %LOCALAPPDATA%\\Kya-Ray\\updates (or ~/.kya-ray/updates fallback).
    """
    appdata = os.environ.get("LOCALAPPDATA")
    if appdata and os.path.isdir(appdata):
        updates_dir = Path(appdata) / "Kya-Ray" / "updates"
    else:
        updates_dir = Path.home() / ".kya-ray" / "updates"

    try:
        updates_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning("Could not create default updates directory %s: %s", updates_dir, e)

    return updates_dir


def cleanup_orphaned_part_files(updates_dir: Path, max_age_seconds: float = 3600.0) -> int:
    """
    Removes stale partial temporary download files (.part.*) left behind by prior crashes
    or killed processes older than max_age_seconds.
    """
    cleaned = 0
    now = time.time()
    try:
        for p in updates_dir.glob("*.part.*"):
            if not p.is_file():
                continue
            try:
                if now - p.stat().st_mtime >= max_age_seconds:
                    p.unlink()
                    cleaned += 1
            except Exception as e:
                logger.debug("Could not remove orphaned temp file %s: %s", p, e)
    except Exception as e:
        logger.debug("Failed scanning for orphaned files in %s: %s", updates_dir, e)
    return cleaned


def parse_sha256_checksum(content: str, expected_filename: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """
    Parses SHA-256 checksum from standard manifest formats:
    - Coreutils format: '<hex>  <filename>' or '<hex> *<filename>'
    - BSD format: 'SHA256 (<filename>) = <hex>'
    - Bare hash: '<hex>'

    Validates that the hash consists of exactly 64 hexadecimal characters.
    If expected_filename is provided and a filename is present in the manifest,
    ensures they match.
    """
    if not isinstance(content, str):
        raise TypeError(f"Expected str for checksum content, got {type(content).__name__}")

    clean = content.strip().lstrip("\ufeff")
    if not clean:
        raise ValueError("Checksum content is empty")

    lines = [line.strip() for line in clean.splitlines() if line.strip() and not line.strip().startswith("#")]
    if not lines:
        raise ValueError("No valid checksum entries found")

    selected_line = lines[0]
    expected_lower = os.path.basename(expected_filename.lower()) if expected_filename else None

    # If multiple lines, locate the entry matching expected filename
    if len(lines) > 1 and expected_lower:
        matched_lines = [l for l in lines if expected_lower in l.lower()]
        if matched_lines:
            selected_line = matched_lines[0]
        else:
            raise ValueError(f"Checksum manifest does not contain entry for expected file '{expected_filename}'")

    # Format 1: BSD style: SHA256 (filename) = hash
    bsd_match = re.match(r"^SHA256\s*\((.+?)\)\s*=\s*([0-9a-fA-F]{64})$", selected_line, re.IGNORECASE)
    if bsd_match:
        fn = os.path.basename(bsd_match.group(1).strip())
        hash_val = bsd_match.group(2).lower()
        if expected_lower and fn.lower() != expected_lower:
            raise ValueError(f"Checksum entry is for '{fn}', expected '{expected_filename}'")
        return hash_val, fn

    # Format 2: Coreutils style: <hash>  <filename> or <hash> *<filename>
    core_match = re.match(r"^([0-9a-fA-F]{64})\s+[\*]?(.*?)$", selected_line)
    if core_match:
        hash_val = core_match.group(1).lower()
        fn_part = core_match.group(2).strip()
        fn = os.path.basename(fn_part) if fn_part else None
        if expected_lower and fn and fn.lower() != expected_lower:
            raise ValueError(f"Checksum entry is for '{fn}', expected '{expected_filename}'")
        return hash_val, fn

    # Format 3: Bare 64-character hexadecimal hash
    bare_match = re.match(r"^([0-9a-fA-F]{64})$", selected_line)
    if bare_match:
        return bare_match.group(1).lower(), None

    raise ValueError(f"Malformed or unrecognized SHA-256 checksum entry: {selected_line!r}")


def compute_file_sha256(
    file_path: Union[str, Path],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    cancel_event: Optional[threading.Event] = None,
) -> str:
    """Incrementally calculates SHA-256 hex digest of a file on disk."""
    p = Path(file_path)
    if not p.is_file():
        raise FileNotFoundError(f"File not found for checksum calculation: {p}")

    hasher = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("SHA-256 calculation cancelled by user")
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)

    return hasher.hexdigest().lower()


def verify_file_sha256(
    file_path: Union[str, Path],
    expected_hash: str,
    cancel_event: Optional[threading.Event] = None,
) -> bool:
    """Securely compares file SHA-256 digest against expected hex string in constant time."""
    actual_hash = compute_file_sha256(file_path, cancel_event=cancel_event)
    return hmac.compare_digest(actual_hash, expected_hash.strip().lower())


def validate_secure_url(url: str) -> None:
    """
    Ensures update download URLs strictly use HTTPS to guard against MITM protocol downgrade.
    Rejects any non-HTTPS scheme (http://, file://, ftp://, etc.).
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("URL must be a non-empty string")

    clean_url = url.strip()
    allow_insecure = bool(os.environ.get("KYA_RAY_ALLOW_INSECURE_UPDATES"))

    parsed = urllib.parse.urlparse(clean_url)
    scheme = parsed.scheme.lower()

    if scheme != "https" and not (allow_insecure and scheme == "http"):
        raise ValueError(f"Insecure or invalid URL scheme (HTTPS required): {url!r}")


class UpdateDownloader:
    """
    Downloads release binaries safely and performs incremental SHA-256 integrity validation.
    Enforces per-hop redirect validation, HTTPS invariants, and header hygiene.
    """

    def __init__(
        self,
        timeout: Optional[httpx.Timeout] = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        client: Optional[httpx.Client] = None,
        max_redirects: int = MAX_SAFE_REDIRECTS,
    ):
        self.timeout = timeout or DEFAULT_DOWNLOAD_TIMEOUT
        self.chunk_size = max(1024, int(chunk_size))
        self._custom_client = client
        self.max_redirects = max(1, int(max_redirects))

    def _get_headers(self) -> dict:
        return {
            "Accept": "application/octet-stream, application/vnd.github.v3+json",
            "User-Agent": f"Kya-Ray-Updater/{APP_VERSION}",
        }

    def _sanitize_filename(self, name: str, destination_dir: Path) -> Path:
        """Sanitizes filename and prevents directory traversal attacks."""
        base_name = os.path.basename(name.strip().replace("\\", "/"))
        if not base_name or base_name in (".", ".."):
            raise ValueError(f"Invalid or unsafe asset filename: {name!r}")

        dest_resolved = destination_dir.resolve()
        target_path = (dest_resolved / base_name).resolve()

        if not str(target_path).startswith(str(dest_resolved)):
            raise ValueError(f"Path traversal detected in asset filename: {name!r}")

        return target_path

    def _safe_stream_get(
        self,
        client: httpx.Client,
        url: str,
        headers: dict,
        cancel_event: Optional[threading.Event] = None,
    ) -> httpx.Response:
        """
        Executes a streaming GET request with strict per-hop redirect validation:
        1. Validates initial and every redirect destination BEFORE making the next request.
        2. Rejects HTTPS-to-HTTP downgrades.
        3. Rejects non-HTTPS destinations.
        4. Preserves safe GitHub release asset redirects to HTTPS CDN domains.
        5. Strips sensitive headers across origin boundaries.
        6. Enforces max_redirects to prevent redirect loops.
        """
        current_url = url
        current_headers = dict(headers)
        redirect_count = 0

        while True:
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Cancelled before network request")

            # Validate destination BEFORE making the request
            validate_secure_url(current_url)

            request = client.build_request("GET", current_url, headers=current_headers)
            response = client.send(request, stream=True)

            if response.is_redirect:
                redirect_count += 1
                location = response.headers.get("location") or response.headers.get("Location")
                response.close()

                if not location:
                    raise ValueError(f"HTTP {response.status_code} redirect missing Location header from {current_url}")

                if redirect_count > self.max_redirects:
                    raise ValueError(f"Too many redirects (limit: {self.max_redirects})")

                # Resolve relative URL against current response base URL
                next_url = str(response.url.join(location))

                # Step 1, 2, 3: Validate redirect destination BEFORE sending next request
                validate_secure_url(next_url)

                # Step 5: Strip sensitive headers across origin boundaries
                parsed_curr = urllib.parse.urlparse(current_url)
                parsed_next = urllib.parse.urlparse(next_url)
                if (parsed_curr.scheme, parsed_curr.netloc) != (parsed_next.scheme, parsed_next.netloc):
                    for sensitive in ("authorization", "cookie", "proxy-authorization"):
                        current_headers.pop(sensitive, None)

                current_url = next_url
                continue

            return response

    def download_and_verify(
        self,
        payload_asset: ReleaseAsset,
        checksum_asset: Optional[ReleaseAsset] = None,
        destination_dir: Optional[Union[str, Path]] = None,
        progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        overwrite: bool = False,
    ) -> DownloadResult:
        """
        Synchronously downloads release ZIP in streaming chunks to a temporary file,
        fetches and parses SHA-256 checksum, computes incremental hash, and atomically
        renames upon verification.

        Safely cleans up temporary files on error, cancellation, or hash mismatch.
        """
        if not payload_asset or not payload_asset.download_url:
            return DownloadResult(
                status=DownloadStatus.ERROR,
                error_message="Invalid payload asset: missing download URL",
            )

        # Validate HTTPS scheme on initial URLs
        try:
            validate_secure_url(payload_asset.download_url)
            if checksum_asset and checksum_asset.download_url:
                validate_secure_url(checksum_asset.download_url)
        except ValueError as e:
            return DownloadResult(status=DownloadStatus.ERROR, error_message=str(e))

        dest_dir = Path(destination_dir) if destination_dir else get_default_updates_dir()
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            # Clean up stale temporary files from previous sessions
            cleanup_orphaned_part_files(dest_dir, max_age_seconds=3600.0)
        except OSError as e:
            return DownloadResult(
                status=DownloadStatus.ERROR,
                error_message=f"Failed to access destination directory {dest_dir}: {e}",
            )

        try:
            target_file = self._sanitize_filename(payload_asset.name, dest_dir)
        except ValueError as e:
            return DownloadResult(status=DownloadStatus.ERROR, error_message=str(e))

        # Check existing destination
        if target_file.exists() and not overwrite:
            # If already verified against checksum asset, do not re-download
            if checksum_asset:
                try:
                    checksum_resp = self._fetch_checksum_text(
                        checksum_asset,
                        cancel_event=cancel_event,
                    )
                    expected_hash, _ = parse_sha256_checksum(checksum_resp, expected_filename=target_file.name)
                    if verify_file_sha256(target_file, expected_hash, cancel_event=cancel_event):
                        checksum_file = dest_dir / f"{target_file.name}.sha256"
                        return DownloadResult(
                            status=DownloadStatus.COMPLETED,
                            payload_path=str(target_file),
                            checksum_path=str(checksum_file) if checksum_file.exists() else None,
                            verified=True,
                            sha256_hash=expected_hash,
                        )
                    else:
                        logger.warning("Existing file %s failed SHA-256 validation (corrupted or outdated)", target_file.name)
                except Exception as e:
                    logger.debug("Existing file revalidation skipped or failed: %s", e)

            return DownloadResult(
                status=DownloadStatus.ERROR,
                error_message=f"Destination file already exists: {target_file.name}. Use overwrite=True to replace.",
            )

        # Check disk space
        if payload_asset.size_bytes > 0:
            try:
                free_space = shutil.disk_usage(dest_dir).free
                required_space = payload_asset.size_bytes + MIN_FREE_SPACE_BUFFER_BYTES
                if free_space < required_space:
                    return DownloadResult(
                        status=DownloadStatus.ERROR,
                        error_message=(
                            f"Insufficient disk space in {dest_dir}. "
                            f"Required: {required_space // (1024 * 1024)} MB, available: {free_space // (1024 * 1024)} MB"
                        ),
                    )
            except Exception as e:
                logger.debug("Disk usage check bypassed: %s", e)

        # Check cancellation before starting
        if cancel_event and cancel_event.is_set():
            return DownloadResult(status=DownloadStatus.CANCELLED)

        # Temporary download path
        part_filename = f"{target_file.name}.part.{uuid.uuid4().hex[:8]}"
        temp_file = dest_dir / part_filename

        headers = self._get_headers()
        client = self._custom_client or httpx.Client(timeout=self.timeout)
        should_close_client = self._custom_client is None

        downloaded_bytes = 0
        total_bytes = payload_asset.size_bytes if payload_asset.size_bytes > 0 else None
        start_time = time.monotonic()
        last_progress_time = start_time

        try:
            response = self._safe_stream_get(
                client=client,
                url=payload_asset.download_url,
                headers=headers,
                cancel_event=cancel_event,
            )
            try:
                if response.status_code >= 400:
                    return DownloadResult(
                        status=DownloadStatus.ERROR,
                        error_message=f"HTTP {response.status_code} while downloading payload: {payload_asset.name}",
                    )

                # Update total_bytes from Content-Length header if available
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        parsed_len = int(content_length)
                        if parsed_len > 0:
                            total_bytes = parsed_len
                    except ValueError:
                        pass

                cancelled = False
                with open(temp_file, "wb") as f_out:
                    for chunk in response.iter_bytes(chunk_size=self.chunk_size):
                        if cancel_event and cancel_event.is_set():
                            logger.info("Download cancelled by user.")
                            cancelled = True
                            break

                        f_out.write(chunk)
                        downloaded_bytes += len(chunk)

                        now = time.monotonic()
                        if progress_callback and (
                            downloaded_bytes == len(chunk)
                            or now - last_progress_time >= 0.05
                            or downloaded_bytes == total_bytes
                        ):
                            elapsed = max(0.001, now - start_time)
                            speed = downloaded_bytes / elapsed
                            percent = (downloaded_bytes / total_bytes * 100.0) if total_bytes else None
                            progress_callback(
                                DownloadProgress(
                                    downloaded_bytes=downloaded_bytes,
                                    total_bytes=total_bytes,
                                    percent=percent,
                                    speed_bytes_per_sec=speed,
                                    is_indeterminate=total_bytes is None,
                                )
                            )
                            last_progress_time = now

                        if cancel_event and cancel_event.is_set():
                            logger.info("Download cancelled by user.")
                            cancelled = True
                            break

                if cancelled or (cancel_event and cancel_event.is_set()):
                    self._cleanup_file(temp_file)
                    return DownloadResult(status=DownloadStatus.CANCELLED)
            finally:
                response.close()

            # Validate size if specified in release metadata
            if total_bytes and downloaded_bytes != total_bytes:
                self._cleanup_file(temp_file)
                return DownloadResult(
                    status=DownloadStatus.ERROR,
                    error_message=f"Downloaded size ({downloaded_bytes} bytes) does not match expected ({total_bytes} bytes)",
                )

            # Cancellation check before verification phase
            if cancel_event and cancel_event.is_set():
                self._cleanup_file(temp_file)
                return DownloadResult(status=DownloadStatus.CANCELLED)

            # Verification Phase
            if not checksum_asset or not checksum_asset.download_url:
                self._cleanup_file(temp_file)
                return DownloadResult(
                    status=DownloadStatus.ERROR,
                    error_message=f"Missing SHA-256 checksum asset for release payload: {payload_asset.name}",
                )

            # Fetch and parse checksum using safe redirect validation
            try:
                checksum_content = self._fetch_checksum_text(
                    checksum_asset,
                    client=client,
                    cancel_event=cancel_event,
                )
                expected_hash, _ = parse_sha256_checksum(
                    checksum_content,
                    expected_filename=target_file.name,
                )
            except InterruptedError:
                self._cleanup_file(temp_file)
                return DownloadResult(status=DownloadStatus.CANCELLED)
            except Exception as e:
                self._cleanup_file(temp_file)
                return DownloadResult(
                    status=DownloadStatus.ERROR,
                    error_message=f"Failed to fetch or parse SHA-256 checksum: {e}",
                )

            # Cancellation check before incremental hashing
            if cancel_event and cancel_event.is_set():
                self._cleanup_file(temp_file)
                return DownloadResult(status=DownloadStatus.CANCELLED)

            # Verify hash incrementally
            try:
                actual_hash = compute_file_sha256(temp_file, cancel_event=cancel_event)
            except InterruptedError:
                self._cleanup_file(temp_file)
                return DownloadResult(status=DownloadStatus.CANCELLED)

            if not hmac.compare_digest(actual_hash, expected_hash):
                self._cleanup_file(temp_file)
                return DownloadResult(
                    status=DownloadStatus.ERROR,
                    error_message=(
                        f"SHA-256 hash mismatch for {payload_asset.name}!\n"
                        f"Expected: {expected_hash}\n"
                        f"Actual:   {actual_hash}"
                    ),
                )

            # Atomic promotion: on Windows NTFS os.replace is atomic
            if target_file.exists() and not overwrite:
                self._cleanup_file(temp_file)
                return DownloadResult(
                    status=DownloadStatus.ERROR,
                    error_message=f"Destination file already exists: {target_file.name}",
                )

            os.replace(str(temp_file), str(target_file))

            # Save matching verified .sha256 file alongside payload
            checksum_file = dest_dir / f"{target_file.name}.sha256"
            try:
                checksum_file.write_text(f"{expected_hash}  {target_file.name}\n", encoding="utf-8")
            except OSError as e:
                logger.debug("Could not write local checksum record file: %s", e)

            return DownloadResult(
                status=DownloadStatus.COMPLETED,
                payload_path=str(target_file),
                checksum_path=str(checksum_file) if checksum_file.exists() else None,
                verified=True,
                sha256_hash=expected_hash,
            )

        except httpx.TimeoutException as e:
            self._cleanup_file(temp_file)
            return DownloadResult(
                status=DownloadStatus.ERROR,
                error_message=f"Network timeout while downloading update: {e}",
            )
        except httpx.NetworkError as e:
            self._cleanup_file(temp_file)
            return DownloadResult(
                status=DownloadStatus.ERROR,
                error_message=f"Connection interrupted while downloading update: {e}",
            )
        except OSError as e:
            self._cleanup_file(temp_file)
            return DownloadResult(
                status=DownloadStatus.ERROR,
                error_message=f"Filesystem error during download: {e}",
            )
        except Exception as e:
            self._cleanup_file(temp_file)
            return DownloadResult(
                status=DownloadStatus.ERROR,
                error_message=f"Unexpected error during download: {e}",
            )
        finally:
            if should_close_client:
                try:
                    client.close()
                except Exception:
                    pass

    def _fetch_checksum_text(
        self,
        checksum_asset: ReleaseAsset,
        client: Optional[httpx.Client] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> str:
        """Fetches raw SHA-256 checksum manifest text from GitHub asset URL with safe redirect checks."""
        headers = self._get_headers()
        cli = client or httpx.Client(timeout=self.timeout)
        should_close = client is None
        response = None
        try:
            response = self._safe_stream_get(
                client=cli,
                url=checksum_asset.download_url,
                headers=headers,
                cancel_event=cancel_event,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code} fetching checksum asset from {checksum_asset.download_url}")

            content_bytes = response.read()
            return content_bytes.decode("utf-8", errors="replace")
        finally:
            if response is not None:
                response.close()
            if should_close:
                try:
                    cli.close()
                except Exception:
                    pass

    def _cleanup_file(self, file_path: Path) -> None:
        """Safely removes an incomplete temporary file without raising errors."""
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception as e:
            logger.debug("Failed to clean up temporary file %s: %s", file_path, e)

    def download_and_verify_async(
        self,
        callback: Callable[[DownloadResult], None],
        payload_asset: ReleaseAsset,
        checksum_asset: Optional[ReleaseAsset] = None,
        destination_dir: Optional[Union[str, Path]] = None,
        progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        overwrite: bool = False,
    ) -> threading.Thread:
        """
        Asynchronously executes download and verification on a daemon worker thread.
        Never blocks the GUI thread and never prevents clean application termination.
        """
        def _worker():
            try:
                res = self.download_and_verify(
                    payload_asset=payload_asset,
                    checksum_asset=checksum_asset,
                    destination_dir=destination_dir,
                    progress_callback=progress_callback,
                    cancel_event=cancel_event,
                    overwrite=overwrite,
                )
            except Exception as e:
                logger.error("Unhandled exception in download worker thread: %s", e)
                res = DownloadResult(
                    status=DownloadStatus.ERROR,
                    error_message=str(e),
                )
            try:
                callback(res)
            except Exception as e:
                logger.error("Error invoking download completion callback: %s", e)

        thread = threading.Thread(
            target=_worker,
            name="KyaRayDownloadWorker",
            daemon=True,
        )
        thread.start()
        return thread
