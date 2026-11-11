"""
tests/test_version.py - Comprehensive Unit Tests for Kya-Ray Versioning and SemVer.

Verifies:
1. Single authoritative source of truth across desktop, backend, and build scripts.
2. FastAPI /health endpoint reports the exact authoritative version.
3. Windows PE metadata (file_version_info.txt) and installer (install.ps1) synchronization.
4. SemVer 2.0.0 parsing, precedence ordering, and prerelease comparisons.
5. All required comparison cases:
   - 1.0.1 > 1.0.0
   - 1.0.0-beta.2 > 1.0.0-beta.1
   - 1.0.0 > 1.0.0-beta.1
   - 1.0.0-beta.1 < 1.0.0
"""

from pathlib import Path
import re
import unittest

from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import app
import desktop
from desktop.utils.config import APP_NAME, APP_TARGET_VERSION, APP_VERSION as CONFIG_APP_VERSION
from desktop.version import (
    APP_VERSION,
    SemVer,
    __version__,
    generate_file_version_info_content,
    get_current_version,
    sync_file_version_info,
    sync_installer_version,
)


class TestVersionSingleSourceOfTruth(unittest.TestCase):
    """Verifies that all components derive their version from the authoritative definition."""

    def test_version_constants_match(self):
        """Authoritative version constants must match across modules."""
        self.assertEqual(APP_VERSION, "1.0.0-beta.2")
        self.assertEqual(__version__, "1.0.0-beta.2")
        self.assertEqual(desktop.__version__, "1.0.0-beta.2")
        self.assertEqual(desktop.APP_VERSION, "1.0.0-beta.2")
        self.assertEqual(CONFIG_APP_VERSION, "1.0.0-beta.2")
        self.assertEqual(APP_TARGET_VERSION, "1.0.0-beta.2")

    def test_backend_settings_version(self):
        """Backend Settings must report the authoritative version."""
        settings = get_settings()
        self.assertEqual(settings.APP_VERSION, APP_VERSION)

    def test_fastapi_app_version(self):
        """FastAPI OpenAPI metadata version must match the authoritative version."""
        self.assertEqual(app.version, APP_VERSION)

    def test_backend_health_endpoint_reports_authoritative_version(self):
        """GET /health must return status 200 with the exact authoritative version."""
        client = TestClient(app)
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("service"), "kya-ray-backend")
        self.assertEqual(data.get("version"), APP_VERSION)
        self.assertEqual(data.get("status"), "healthy")

    def test_file_version_info_on_disk_is_synchronized(self):
        """file_version_info.txt must match the generated metadata for APP_VERSION."""
        repo_root = Path(__file__).resolve().parent.parent
        info_file = repo_root / "file_version_info.txt"
        self.assertTrue(info_file.exists(), "file_version_info.txt missing")

        content = info_file.read_text(encoding="utf-8")
        current_semver = get_current_version()
        expected_pe_tuple = str(current_semver.to_pe_version_tuple())

        self.assertIn(f"filevers={expected_pe_tuple}", content)
        self.assertIn(f"prodvers={expected_pe_tuple}", content)
        self.assertIn(f"StringStruct('FileVersion', '{current_semver.pe_version_str()}')", content)
        self.assertIn(f"StringStruct('ProductVersion', '{APP_VERSION}')", content)

    def test_installer_display_version_is_synchronized(self):
        """installer/install.ps1 must specify DisplayVersion matching APP_VERSION."""
        repo_root = Path(__file__).resolve().parent.parent
        installer_file = repo_root / "installer" / "install.ps1"
        self.assertTrue(installer_file.exists(), "installer/install.ps1 missing")

        content = installer_file.read_text(encoding="utf-8")
        expected_pattern = rf'Set-ItemProperty -Path \$regPath -Name "DisplayVersion" -Value "{re.escape(APP_VERSION)}"'
        self.assertRegex(content, expected_pattern)

    def test_sync_functions_execute_cleanly(self):
        """sync_file_version_info and sync_installer_version must execute without error."""
        self.assertTrue(sync_file_version_info())
        self.assertTrue(sync_installer_version())


class TestSemVerParsing(unittest.TestCase):
    """Verifies parsing of standard, prefixed, prerelease, and build metadata versions."""

    def test_parse_standard_release(self):
        v = SemVer.parse("1.2.3")
        self.assertEqual(v.major, 1)
        self.assertEqual(v.minor, 2)
        self.assertEqual(v.patch, 3)
        self.assertIsNone(v.prerelease)
        self.assertIsNone(v.build)
        self.assertFalse(v.is_prerelease)
        self.assertEqual(str(v), "1.2.3")
        self.assertEqual(v.as_tuple(), (1, 2, 3))
        self.assertEqual(v.to_pe_version_tuple(), (1, 2, 3, 0))
        self.assertEqual(v.pe_version_str(), "1.2.3.0")

    def test_parse_with_v_prefix(self):
        v1 = SemVer.parse("v1.0.0")
        v2 = SemVer.parse("V1.0.0")
        self.assertEqual(v1, v2)
        self.assertEqual(v1, "1.0.0")
        self.assertEqual(v1.as_tuple(), (1, 0, 0))

    def test_parse_prerelease(self):
        v = SemVer.parse("1.0.0-beta.2")
        self.assertEqual(v.major, 1)
        self.assertEqual(v.minor, 0)
        self.assertEqual(v.patch, 0)
        self.assertEqual(v.prerelease, ("beta", 2))
        self.assertTrue(v.is_prerelease)
        self.assertEqual(str(v), "1.0.0-beta.2")

    def test_parse_complex_prerelease_and_build(self):
        v = SemVer.parse("1.0.0-alpha.1+build.123")
        self.assertEqual(v.prerelease, ("alpha", 1))
        self.assertEqual(v.build, ("build", "123"))
        self.assertEqual(str(v), "1.0.0-alpha.1+build.123")

    def test_parse_idempotence(self):
        v1 = SemVer.parse("1.0.0")
        v2 = SemVer.parse(v1)
        self.assertIs(v1, v2)

    def test_parse_invalid_types_and_formats(self):
        invalid_types = [None, 123, ["1", "0", "0"]]
        for item in invalid_types:
            with self.assertRaises(TypeError):
                SemVer.parse(item)  # type: ignore

        invalid_strings = [
            "",
            "   ",
            "1",
            "1.0",
            "1.0.0.0",
            "-1.0.0",
            "1.a.0",
            "v",
            "1.0.0-",
            "1.0.0+",
            "1.0.0-beta..1",
            "1.0.0-01",  # Leading zeroes prohibited in numeric prerelease
            "1.0.0-beta$",
        ]
        for string in invalid_strings:
            with self.assertRaises(ValueError, msg=f"Should raise ValueError for {string!r}"):
                SemVer.parse(string)


class TestSemVerComparison(unittest.TestCase):
    """Verifies comprehensive semantic version comparisons and precedence rules."""

    def test_required_comparison_cases(self):
        """Explicitly tests the 4 comparison cases required by specification."""
        v_1_0_0 = SemVer.parse("1.0.0")
        v_1_0_1 = SemVer.parse("1.0.1")
        v_beta_1 = SemVer.parse("1.0.0-beta.1")
        v_beta_2 = SemVer.parse("1.0.0-beta.2")

        # 1. 1.0.1 > 1.0.0
        self.assertGreater(v_1_0_1, v_1_0_0)
        self.assertTrue(v_1_0_1 > "1.0.0")

        # 2. 1.0.0-beta.2 > 1.0.0-beta.1
        self.assertGreater(v_beta_2, v_beta_1)
        self.assertTrue(v_beta_2 > "1.0.0-beta.1")

        # 3. 1.0.0 > 1.0.0-beta.1
        self.assertGreater(v_1_0_0, v_beta_1)
        self.assertTrue(v_1_0_0 > "1.0.0-beta.1")

        # 4. 1.0.0-beta.1 < 1.0.0
        self.assertLess(v_beta_1, v_1_0_0)
        self.assertTrue(v_beta_1 < "1.0.0")

    def test_semver_precedence_chain(self):
        """Verifies strict SemVer 2.0.0 precedence ordering chain."""
        versions = [
            "1.0.0-alpha",
            "1.0.0-alpha.1",
            "1.0.0-alpha.beta",
            "1.0.0-beta",
            "1.0.0-beta.2",
            "1.0.0-beta.11",
            "1.0.0-rc.1",
            "1.0.0",
            "1.0.1",
            "1.1.0",
            "2.0.0",
        ]
        parsed = [SemVer.parse(v) for v in versions]

        for i in range(len(parsed) - 1):
            a, b = parsed[i], parsed[i + 1]
            self.assertLess(a, b, f"Expected {a} < {b}")
            self.assertGreater(b, a, f"Expected {b} > {a}")
            self.assertNotEqual(a, b)

    def test_build_metadata_ignored_in_precedence(self):
        """Build metadata must not affect version equality or precedence."""
        v1 = SemVer.parse("1.0.0+20130313144700")
        v2 = SemVer.parse("1.0.0+exp.sha.5114f85")
        v3 = SemVer.parse("1.0.0")

        self.assertEqual(v1, v2)
        self.assertEqual(v1, v3)
        self.assertFalse(v1 < v2)
        self.assertFalse(v2 < v1)

    def test_mixed_type_comparisons(self):
        """Comparing SemVer with strings directly."""
        v = SemVer.parse("1.0.0")
        self.assertEqual(v, "1.0.0")
        self.assertEqual(v, "v1.0.0")
        self.assertNotEqual(v, "1.0.1")
        self.assertFalse(v == 100)  # non-string type returns False or NotImplemented

    def test_get_current_version(self):
        """get_current_version returns SemVer matching APP_VERSION."""
        curr = get_current_version()
        self.assertEqual(str(curr), APP_VERSION)
        self.assertEqual(curr.major, 1)
        self.assertEqual(curr.minor, 0)
        self.assertEqual(curr.patch, 0)
        self.assertEqual(curr.prerelease, ("beta", 2))
        self.assertTrue(curr.is_prerelease)


if __name__ == "__main__":
    unittest.main()

