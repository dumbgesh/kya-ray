"""
version.py - Authoritative Single Source of Truth for Kya-Ray Versioning.

Shared between desktop application, backend services, installer, and packaging scripts.
Defines authoritative application version, robust Semantic Versioning (SemVer 2.0.0)
parsing and comparison routines, and synchronizers for Windows PE metadata and installers.
"""

from dataclasses import dataclass
import functools
from pathlib import Path
import re
from typing import Any, List, Optional, Tuple, Union

# Authoritative Application Version (Single Source of Truth)
__version__ = "1.0.0-beta.2"
APP_VERSION = __version__

# Regular expression strictly following Semantic Versioning 2.0.0
# with optional leading 'v' / 'V' for user-facing tags.
_SEMVER_REGEX = re.compile(
    r"^[vV]?"
    r"(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?"
    r"(?:\+(?P<build>[0-9A-Za-z.-]+))?$"
)


@functools.total_ordering
@dataclass(frozen=True)
class SemVer:
    """
    Immutable representation of a Semantic Version (SemVer 2.0.0).

    Supports full precedence ordering, prerelease identifiers, build metadata,
    and conversions for Windows PE executable version tuples.
    """

    major: int
    minor: int
    patch: int
    prerelease: Optional[Tuple[Union[int, str], ...]] = None
    build: Optional[Tuple[str, ...]] = None
    raw: str = ""

    @classmethod
    def parse(cls, version_str: Union[str, "SemVer"]) -> "SemVer":
        """
        Parses a version string into a SemVer instance.

        Raises:
            TypeError: If version_str is not a string or SemVer.
            ValueError: If version_str is not a valid semantic version.
        """
        if isinstance(version_str, SemVer):
            return version_str

        if not isinstance(version_str, str):
            raise TypeError(f"Expected str or SemVer, got {type(version_str).__name__}")

        raw_clean = version_str.strip()
        match = _SEMVER_REGEX.match(raw_clean)
        if not match:
            raise ValueError(f"Invalid semantic version string: {version_str!r}")

        major = int(match.group("major"))
        minor = int(match.group("minor"))
        patch = int(match.group("patch"))

        prerelease_raw = match.group("prerelease")
        prerelease_parts: Optional[Tuple[Union[int, str], ...]] = None
        if prerelease_raw is not None:
            parts: List[Union[int, str]] = []
            for part in prerelease_raw.split("."):
                if not part:
                    raise ValueError(f"Empty identifier in prerelease: {prerelease_raw!r}")
                if part.isdigit():
                    if len(part) > 1 and part.startswith("0"):
                        raise ValueError(f"Leading zeroes not permitted in numeric prerelease identifier: {part!r}")
                    parts.append(int(part))
                else:
                    if not re.match(r"^[0-9A-Za-z-]+$", part):
                        raise ValueError(f"Invalid characters in prerelease identifier: {part!r}")
                    parts.append(part)
            prerelease_parts = tuple(parts)

        build_raw = match.group("build")
        build_parts: Optional[Tuple[str, ...]] = None
        if build_raw is not None:
            b_parts: List[str] = []
            for part in build_raw.split("."):
                if not part or not re.match(r"^[0-9A-Za-z-]+$", part):
                    raise ValueError(f"Invalid build metadata identifier: {part!r}")
                b_parts.append(part)
            build_parts = tuple(b_parts)

        return cls(
            major=major,
            minor=minor,
            patch=patch,
            prerelease=prerelease_parts,
            build=build_parts,
            raw=raw_clean,
        )

    @property
    def is_prerelease(self) -> bool:
        """Returns True if this version is a prerelease."""
        return self.prerelease is not None

    def as_tuple(self) -> Tuple[int, int, int]:
        """Returns (major, minor, patch) integer tuple."""
        return (self.major, self.minor, self.patch)

    def to_pe_version_tuple(self, build_number: int = 0) -> Tuple[int, int, int, int]:
        """Returns a 4-tuple of non-negative integers for Windows PE FixedFileInfo."""
        b = max(0, min(65535, int(build_number)))
        return (
            max(0, min(65535, self.major)),
            max(0, min(65535, self.minor)),
            max(0, min(65535, self.patch)),
            b,
        )

    def pe_version_str(self, build_number: int = 0) -> str:
        """Returns a 4-segment dotted string for Windows PE FileVersion."""
        pe_tuple = self.to_pe_version_tuple(build_number=build_number)
        return ".".join(str(x) for x in pe_tuple)

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            base += "-" + ".".join(str(p) for p in self.prerelease)
        if self.build:
            base += "+" + ".".join(self.build)
        return base

    def __repr__(self) -> str:
        return f"SemVer('{str(self)}')"

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            try:
                other = SemVer.parse(other)
            except (ValueError, TypeError):
                return False
        elif not isinstance(other, SemVer):
            return NotImplemented

        # SemVer 2.0.0 Section 10: Build metadata is ignored when determining version precedence
        return (
            (self.major, self.minor, self.patch, self.prerelease)
            == (other.major, other.minor, other.patch, other.prerelease)
        )

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, str):
            try:
                other = SemVer.parse(other)
            except (ValueError, TypeError):
                return NotImplemented
        elif not isinstance(other, SemVer):
            return NotImplemented

        # 1. Compare (major, minor, patch) numerically
        if self.as_tuple() != other.as_tuple():
            return self.as_tuple() < other.as_tuple()

        # 2. When major, minor, patch are equal:
        # A normal version has greater precedence than a pre-release version.
        if self.prerelease is None and other.prerelease is None:
            return False
        if self.prerelease is not None and other.prerelease is None:
            # Self is prerelease, other is release -> self < other
            return True
        if self.prerelease is None and other.prerelease is not None:
            # Self is release, other is prerelease -> not (self < other)
            return False

        # Both have pre-releases: compare identifier by identifier from left to right
        assert self.prerelease is not None and other.prerelease is not None
        for a_id, b_id in zip(self.prerelease, other.prerelease):
            if a_id == b_id:
                continue

            # Numeric identifiers always have lower precedence than non-numeric identifiers
            a_is_int = isinstance(a_id, int)
            b_is_int = isinstance(b_id, int)

            if a_is_int and b_is_int:
                return a_id < b_id
            if a_is_int and not b_is_int:
                return True
            if not a_is_int and b_is_int:
                return False

            return str(a_id) < str(b_id)

        # Larger set of pre-release fields has higher precedence
        return len(self.prerelease) < len(other.prerelease)


def get_current_version() -> SemVer:
    """Returns the parsed SemVer representation of the current application version."""
    return SemVer.parse(APP_VERSION)


def generate_file_version_info_content(
    version: Optional[Union[str, SemVer]] = None,
    company_name: str = "Kya-Ray Contributors",
    product_name: str = "Kya-Ray",
    file_description: str = "Kya-Ray Desktop AI Companion",
    original_filename: str = "Kya-Ray.exe",
    copyright_notice: str = "Copyright (C) 2026 Kya-Ray Contributors",
) -> str:
    """Generates valid Windows PE VSVersionInfo configuration content."""
    ver = SemVer.parse(version or APP_VERSION)
    pe_tuple = ver.to_pe_version_tuple()
    file_version_str = ver.pe_version_str()
    product_version_str = str(ver)

    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={pe_tuple},
    prodvers={pe_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [
            StringStruct('CompanyName', '{company_name}'),
            StringStruct('FileDescription', '{file_description}'),
            StringStruct('FileVersion', '{file_version_str}'),
            StringStruct('InternalName', '{product_name}'),
            StringStruct('LegalCopyright', '{copyright_notice}'),
            StringStruct('OriginalFilename', '{original_filename}'),
            StringStruct('ProductName', '{product_name}'),
            StringStruct('ProductVersion', '{product_version_str}')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def sync_file_version_info(target_path: Optional[Union[str, Path]] = None) -> bool:
    """
    Synchronizes file_version_info.txt with the authoritative APP_VERSION.
    Returns True if the file was updated or verified matching.
    """
    if target_path is None:
        target_path = Path(__file__).resolve().parent / "file_version_info.txt"
    else:
        target_path = Path(target_path)

    expected_content = generate_file_version_info_content()
    if target_path.exists():
        try:
            current_content = target_path.read_text(encoding="utf-8")
            if current_content.strip() == expected_content.strip():
                return True
        except Exception:
            pass

    target_path.write_text(expected_content, encoding="utf-8")
    return True


def sync_installer_version(script_path: Optional[Union[str, Path]] = None) -> bool:
    """
    Ensures installer/install.ps1 DisplayVersion matches the authoritative APP_VERSION.
    """
    if script_path is None:
        script_path = Path(__file__).resolve().parent / "installer" / "install.ps1"
    else:
        script_path = Path(script_path)

    if not script_path.exists():
        return False

    content = script_path.read_text(encoding="utf-8")
    new_content = re.sub(
        r'Set-ItemProperty -Path \$regPath -Name "DisplayVersion" -Value "[^"]+"',
        f'Set-ItemProperty -Path $regPath -Name "DisplayVersion" -Value "{APP_VERSION}"',
        content,
    )
    new_content = re.sub(
        r"Kya-Ray v[0-9A-Za-z.-]+ - Windows Application Installer",
        f"Kya-Ray v{APP_VERSION} - Windows Application Installer",
        new_content,
    )

    if new_content != content:
        script_path.write_text(new_content, encoding="utf-8")
    return True

