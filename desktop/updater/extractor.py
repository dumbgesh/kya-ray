"""
desktop/updater/extractor.py - Safe Archive Extraction and Payload Validation.

Provides secure extraction of downloaded release archives with multi-layered defenses:
1. Path traversal rejection (parent directory segments, absolute paths, drive prefixes).
2. Symlink and device node rejection.
3. Duplicate and conflicting filename detection.
4. Pre-extraction disk space validation.
5. Structural payload verification (Kya-Ray.exe existence, PE header, runtime layout).
"""

import os
import shutil
import stat
import zipfile
from pathlib import Path
from typing import Optional, Set, Tuple


class ExtractorError(Exception):
    """Base exception for archive extraction failures."""
    pass


class UnsafeArchiveError(ExtractorError):
    """Raised when an archive contains malicious or disallowed entries."""
    pass


class InvalidPackageError(ExtractorError):
    """Raised when the extracted archive does not match the expected Kya-Ray structure."""
    pass


class InsufficientDiskSpaceError(ExtractorError):
    """Raised when available disk space is insufficient for safe extraction."""
    pass


class PackageExtractor:
    """
    Handles safe extraction and structural verification of release ZIP packages.
    """

    MIN_DISK_HEADROOM_BYTES = 50 * 1024 * 1024  # 50 MB safety buffer

    def __init__(self, min_headroom_bytes: int = MIN_DISK_HEADROOM_BYTES):
        self.min_headroom_bytes = min_headroom_bytes

    def extract_and_validate(self, zip_path: Path, staging_dir: Path) -> Path:
        """
        Extracts zip_path safely into staging_dir, validates layout, and returns
        the directory containing the payload root (the folder with Kya-Ray.exe).

        Args:
            zip_path: Path to the verified release zip file.
            staging_dir: Empty target directory for extracting staged files.

        Returns:
            Path: The root directory of the extracted application payload.

        Raises:
            FileNotFoundError: If zip_path does not exist.
            InsufficientDiskSpaceError: If target drive has inadequate free space.
            UnsafeArchiveError: If archive contains path traversal, symlinks, or duplicates.
            InvalidPackageError: If extracted contents lack Kya-Ray.exe or runtime dependencies.
        """
        zip_path = Path(zip_path).resolve()
        staging_dir = Path(staging_dir).resolve()

        if not zip_path.is_file():
            raise FileNotFoundError(f"Archive file not found: {zip_path}")

        staging_dir.mkdir(parents=True, exist_ok=True)

        if not zipfile.is_zipfile(zip_path):
            raise InvalidPackageError(f"File is not a valid zip archive: {zip_path}")

        with zipfile.ZipFile(zip_path, "r") as zf:
            self._check_disk_space(zf, staging_dir)
            self._validate_archive_entries(zf, staging_dir)
            self._perform_safe_extraction(zf, staging_dir)

        payload_root = self.validate_payload_structure(staging_dir)
        return payload_root

    def _check_disk_space(self, zf: zipfile.ZipFile, target_dir: Path) -> None:
        """Verifies that the target volume has sufficient free space for extraction."""
        total_uncompressed = sum(info.file_size for info in zf.infolist())
        required_space = total_uncompressed + self.min_headroom_bytes

        try:
            usage = shutil.disk_usage(target_dir)
            if usage.free < required_space:
                raise InsufficientDiskSpaceError(
                    f"Insufficient disk space on {target_dir}. "
                    f"Required: {required_space / (1024*1024):.1f} MB, "
                    f"Available: {usage.free / (1024*1024):.1f} MB"
                )
        except OSError:
            # If disk_usage fails on non-standard mount, continue safely
            pass

    def _validate_archive_entries(self, zf: zipfile.ZipFile, staging_dir: Path) -> None:
        """
        Scans all archive members before extracting any bytes.
        Rejects directory traversal, drive prefixes, symlinks, and duplicate filenames.
        """
        seen_paths: Set[str] = set()

        for info in zf.infolist():
            raw_name = info.filename

            # 1. Reject empty names or trailing nulls
            if not raw_name or "\0" in raw_name:
                raise UnsafeArchiveError(f"Null byte or empty name in archive entry: {raw_name!r}")

            # Standardize path separators to forward slash
            norm_name = raw_name.replace("\\", "/")

            # 2. Reject drive prefixes (e.g. C:, D:)
            if len(norm_name) > 1 and norm_name[1] == ":":
                raise UnsafeArchiveError(f"Drive letter prefix forbidden in archive entry: {raw_name!r}")

            # 3. Reject absolute paths
            if norm_name.startswith("/"):
                raise UnsafeArchiveError(f"Absolute path forbidden in archive entry: {raw_name!r}")

            # 4. Reject parent directory segments (..)
            parts = norm_name.split("/")
            if ".." in parts:
                raise UnsafeArchiveError(f"Path traversal ('..') detected in archive entry: {raw_name!r}")

            # 5. Prevent extraction outside staging_dir
            dest_path = (staging_dir / norm_name).resolve()
            try:
                dest_path.relative_to(staging_dir)
            except ValueError:
                raise UnsafeArchiveError(
                    f"Extraction destination escapes staging directory: {dest_path} not in {staging_dir}"
                )

            # 6. Check for duplicate/conflicting paths (case-insensitive for Windows filesystem safety)
            key = norm_name.rstrip("/").lower()
            if key in seen_paths:
                raise UnsafeArchiveError(f"Duplicate or colliding entry in archive: {raw_name!r}")
            if key:
                seen_paths.add(key)

            # 7. Reject symlinks, hardlinks, character devices, fifos
            mode = info.external_attr >> 16
            if mode != 0:
                if stat.S_ISLNK(mode):
                    raise UnsafeArchiveError(f"Symlinks are forbidden in update archives: {raw_name!r}")
                if stat.S_ISCHR(mode) or stat.S_ISBLK(mode) or stat.S_ISFIFO(mode):
                    raise UnsafeArchiveError(f"Special device entries forbidden in update archives: {raw_name!r}")

    def _perform_safe_extraction(self, zf: zipfile.ZipFile, staging_dir: Path) -> None:
        """Safely extracts members using streaming read/write without zipfile.extractall()."""
        for info in zf.infolist():
            norm_name = info.filename.replace("\\", "/")
            dest_path = (staging_dir / norm_name).resolve()

            if norm_name.endswith("/"):
                dest_path.mkdir(parents=True, exist_ok=True)
                continue

            dest_path.parent.mkdir(parents=True, exist_ok=True)

            with zf.open(info, "r") as src, open(dest_path, "wb") as dst:
                shutil.copyfileobj(src, dst, length=64 * 1024)

    def validate_payload_structure(self, staging_dir: Path) -> Path:
        """
        Validates the extracted application package structure.
        Detects whether Kya-Ray.exe resides at root or in a subfolder (e.g. Kya-Ray/),
        and verifies essential files and PE executable headers.

        Returns:
            Path: The directory containing Kya-Ray.exe.
        """
        staging_dir = Path(staging_dir).resolve()

        candidates = [
            staging_dir,
            staging_dir / "Kya-Ray",
            staging_dir / "dist" / "Kya-Ray",
        ]

        payload_root: Optional[Path] = None
        for cand in candidates:
            exe_file = cand / "Kya-Ray.exe"
            if exe_file.is_file():
                payload_root = cand
                break

        if payload_root is None:
            # Check any subfolder for Kya-Ray.exe
            found = list(staging_dir.glob("**/Kya-Ray.exe"))
            if found:
                payload_root = found[0].parent
            else:
                raise InvalidPackageError("Package layout invalid: Kya-Ray.exe not found in extracted archive.")

        # 1. Verify executable size and header
        exe_path = payload_root / "Kya-Ray.exe"
        try:
            exe_size = exe_path.stat().st_size
            if exe_size < 1024:
                raise InvalidPackageError(f"Kya-Ray.exe is corrupt or empty ({exe_size} bytes).")

            with open(exe_path, "rb") as f:
                header = f.read(2)
                if header != b"MZ":
                    raise InvalidPackageError("Kya-Ray.exe is not a valid Windows PE binary (missing 'MZ' magic).")
        except OSError as e:
            raise InvalidPackageError(f"Failed inspecting Kya-Ray.exe: {e}")

        # 2. Check for runtime dependencies (_internal or companion DLLs)
        has_internal = (payload_root / "_internal").is_dir()
        has_dlls = bool(list(payload_root.glob("*.dll"))) or bool(list(payload_root.glob("python*.dll")))
        if not has_internal and not has_dlls:
            raise InvalidPackageError(
                "Package layout invalid: missing runtime dependencies (_internal folder or runtime DLLs)."
            )

        return payload_root

