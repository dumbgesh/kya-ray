"""
tests/test_updater.py - Comprehensive Unit Tests for Kya-Ray GitHub Update Detection.

Tests all requirements using mock responses with zero live network dependencies:
1. Newer stable release detection.
2. Newer beta release detection.
3. Stable installation ignoring beta releases.
4. Beta installation detecting stable releases.
5. No update available (current >= latest).
6. Invalid release tags skipped gracefully.
7. Missing Windows x64 zip payload asset handling.
8. GitHub API errors (404, 500).
9. Network timeouts (httpx.TimeoutException).
10. GitHub rate limit handling (HTTP 403 / X-RateLimit-Remaining: 0).
11. ETag conditional requests and cached response handling (HTTP 304).
12. Malformed API responses.
13. Asynchronous non-blocking background check execution.
"""

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import httpx

from desktop.updater import (
    GitHubApiResponse,
    GitHubReleaseClient,
    ReleaseAsset,
    ReleaseInfo,
    UpdateCheckResult,
    UpdateCheckStatus,
    UpdateChecker,
)
from desktop.version import SemVer


def make_release_dict(
    tag_name: str = "v1.0.1",
    name: str = "Kya-Ray v1.0.1",
    body: str = "Bug fixes and improvements",
    prerelease: bool = False,
    draft: bool = False,
    include_zip: bool = True,
    include_sha256: bool = True,
    zip_name: str = None,
    sha256_name: str = None,
) -> dict:
    assets = []
    if include_zip:
        assets.append({
            "name": zip_name or f"Kya-Ray-{tag_name}-win64.zip",
            "browser_download_url": f"https://github.com/dumbgesh/kya-ray/releases/download/{tag_name}/Kya-Ray-{tag_name}-win64.zip",
            "size": 45000000,
            "content_type": "application/zip",
        })
    if include_sha256:
        assets.append({
            "name": sha256_name or f"Kya-Ray-{tag_name}-win64.zip.sha256",
            "browser_download_url": f"https://github.com/dumbgesh/kya-ray/releases/download/{tag_name}/Kya-Ray-{tag_name}-win64.zip.sha256",
            "size": 64,
            "content_type": "text/plain",
        })
    return {
        "tag_name": tag_name,
        "name": name,
        "body": body,
        "html_url": f"https://github.com/dumbgesh/kya-ray/releases/tag/{tag_name}",
        "published_at": "2026-11-08T12:00:00Z",
        "prerelease": prerelease,
        "draft": draft,
        "assets": assets,
    }


class TestUpdateDetection(unittest.TestCase):
    """Verifies update detection logic, channel rules, and release asset validation."""

    def setUp(self):
        self.mock_client = MagicMock(spec=GitHubReleaseClient)
        self.checker = UpdateChecker(client=self.mock_client)

    def test_newer_stable_release_detected(self):
        """Current 1.0.0 detects newer 1.0.1 stable release."""
        rel = make_release_dict(tag_name="v1.0.1", prerelease=False)
        self.mock_client.fetch_latest_release.return_value = GitHubApiResponse(
            status_code=200,
            data=rel,
        )

        res = self.checker.check_for_updates(current_version="1.0.0", allow_prereleases=False)

        self.assertTrue(res.is_update_available)
        self.assertEqual(res.status, UpdateCheckStatus.UPDATE_AVAILABLE)
        self.assertEqual(res.current_version, SemVer.parse("1.0.0"))
        self.assertEqual(res.latest_version, SemVer.parse("1.0.1"))
        self.assertIsNotNone(res.payload_asset)
        self.assertIsNotNone(res.checksum_asset)
        self.assertIn("Kya-Ray-v1.0.1-win64.zip", res.payload_asset.name)
        self.assertEqual(res.release_notes, "Bug fixes and improvements")

    def test_newer_beta_release_detected(self):
        """Current 1.0.0-beta.1 detects 1.0.0-beta.2 on beta channel."""
        releases = [
            make_release_dict(tag_name="v1.0.0-beta.2", prerelease=True),
            make_release_dict(tag_name="v1.0.0-beta.1", prerelease=True),
        ]
        self.mock_client.fetch_all_releases.return_value = GitHubApiResponse(
            status_code=200,
            data=releases,
        )

        res = self.checker.check_for_updates(current_version="1.0.0-beta.1")

        self.assertTrue(res.is_update_available)
        self.assertEqual(res.status, UpdateCheckStatus.UPDATE_AVAILABLE)
        self.assertEqual(res.latest_version, SemVer.parse("1.0.0-beta.2"))

    def test_stable_installation_ignores_beta_releases(self):
        """Stable 1.0.0 installation must not receive beta updates even if newer than current."""
        # When allow_prereleases=False, checker queries latest stable release
        rel = make_release_dict(tag_name="v1.0.0", prerelease=False)
        self.mock_client.fetch_latest_release.return_value = GitHubApiResponse(
            status_code=200,
            data=rel,
        )

        res = self.checker.check_for_updates(current_version="1.0.0", allow_prereleases=False)

        self.assertFalse(res.is_update_available)
        self.assertEqual(res.status, UpdateCheckStatus.UP_TO_DATE)
        self.assertEqual(res.latest_version, SemVer.parse("1.0.0"))

    def test_beta_installation_detects_eventual_stable_release(self):
        """Beta 1.0.0-beta.1 installation detects 1.0.0 final stable release."""
        releases = [
            make_release_dict(tag_name="v1.0.0", prerelease=False),
            make_release_dict(tag_name="v1.0.0-beta.2", prerelease=True),
            make_release_dict(tag_name="v1.0.0-beta.1", prerelease=True),
        ]
        self.mock_client.fetch_all_releases.return_value = GitHubApiResponse(
            status_code=200,
            data=releases,
        )

        res = self.checker.check_for_updates(current_version="1.0.0-beta.1")

        self.assertTrue(res.is_update_available)
        self.assertEqual(res.latest_version, SemVer.parse("1.0.0"))

    def test_no_update_available_when_already_latest(self):
        """Already running the newest release."""
        rel = make_release_dict(tag_name="v1.0.0", prerelease=False)
        self.mock_client.fetch_latest_release.return_value = GitHubApiResponse(
            status_code=200,
            data=rel,
        )

        res = self.checker.check_for_updates(current_version="1.0.0")

        self.assertFalse(res.is_update_available)
        self.assertEqual(res.status, UpdateCheckStatus.UP_TO_DATE)

    def test_no_update_available_when_running_newer_than_remote(self):
        """Local build is ahead of remote published releases."""
        rel = make_release_dict(tag_name="v0.9.0", prerelease=False)
        self.mock_client.fetch_latest_release.return_value = GitHubApiResponse(
            status_code=200,
            data=rel,
        )

        res = self.checker.check_for_updates(current_version="1.0.0-beta.1", allow_prereleases=False)

        self.assertFalse(res.is_update_available)
        self.assertEqual(res.status, UpdateCheckStatus.UP_TO_DATE)

    def test_invalid_release_tags_and_drafts_ignored(self):
        """Drafts and unparseable tags are filtered out."""
        releases = [
            make_release_dict(tag_name="v2.0.0", draft=True),  # Draft ignored
            make_release_dict(tag_name="nightly-build"),       # Invalid SemVer ignored
            make_release_dict(tag_name="v1.0.0-beta.2", prerelease=True),  # Valid
        ]
        self.mock_client.fetch_all_releases.return_value = GitHubApiResponse(
            status_code=200,
            data=releases,
        )

        res = self.checker.check_for_updates(current_version="1.0.0-beta.1")

        self.assertTrue(res.is_update_available)
        self.assertEqual(res.latest_version, SemVer.parse("1.0.0-beta.2"))

    def test_missing_windows_zip_asset_results_in_no_compatible_release(self):
        """Release exists with higher version but no Windows x64 zip payload."""
        rel = make_release_dict(tag_name="v1.0.1", include_zip=False)
        self.mock_client.fetch_latest_release.return_value = GitHubApiResponse(
            status_code=200,
            data=rel,
        )

        res = self.checker.check_for_updates(current_version="1.0.0", allow_prereleases=False)

        self.assertFalse(res.is_update_available)
        self.assertEqual(res.status, UpdateCheckStatus.NO_COMPATIBLE_RELEASE)
        self.assertIn("lacks Windows x64 zip", res.error_message)

    def test_checksum_missing_distinguishes_zip_from_verifiable_package(self):
        """When zip payload exists but .sha256 is missing, package is not marked verifiable."""
        rel = make_release_dict(tag_name="v1.0.1", include_zip=True, include_sha256=False)
        self.mock_client.fetch_latest_release.return_value = GitHubApiResponse(
            status_code=200,
            data=rel,
        )

        res = self.checker.check_for_updates(current_version="1.0.0", allow_prereleases=False)

        self.assertTrue(res.is_update_available)
        self.assertIsNotNone(res.payload_asset)
        self.assertIsNone(res.checksum_asset)
        self.assertFalse(res.has_checksum)
        self.assertFalse(res.is_verifiable)

    def test_checksum_malformed_or_empty_rejected(self):
        """When .sha256 asset has size 0 or is mismatched, it is rejected as non-verifiable."""
        rel = make_release_dict(
            tag_name="v1.0.1",
            include_zip=True,
            include_sha256=True,
            sha256_name="unrelated_checksum.sha256",
        )
        # Force size 0
        rel["assets"][1]["size"] = 0

        self.mock_client.fetch_latest_release.return_value = GitHubApiResponse(
            status_code=200,
            data=rel,
        )

        res = self.checker.check_for_updates(current_version="1.0.0", allow_prereleases=False)

        self.assertTrue(res.is_update_available)
        self.assertFalse(res.has_checksum)
        self.assertFalse(res.is_verifiable)

    def test_checksum_valid_marks_package_verifiable(self):
        """When both matching zip and non-empty .sha256 exist, package is fully verifiable."""
        rel = make_release_dict(tag_name="v1.0.1", include_zip=True, include_sha256=True)
        self.mock_client.fetch_latest_release.return_value = GitHubApiResponse(
            status_code=200,
            data=rel,
        )

        res = self.checker.check_for_updates(current_version="1.0.0", allow_prereleases=False)

        self.assertTrue(res.is_update_available)
        self.assertTrue(res.has_checksum)
        self.assertTrue(res.is_verifiable)



class TestUpdateClientReliability(unittest.TestCase):
    """Verifies timeouts, HTTP errors, rate-limiting, ETags, and JSON parsing."""

    def test_network_timeout_handling(self):
        """TimeoutException is caught and structured NETWORK_ERROR returned."""
        client = GitHubReleaseClient()
        checker = UpdateChecker(client=client)

        with patch.object(httpx.Client, "get", side_effect=httpx.TimeoutException("Read timed out")):
            res = checker.check_for_updates(current_version="1.0.0")

        self.assertFalse(res.is_update_available)
        self.assertEqual(res.status, UpdateCheckStatus.NETWORK_ERROR)
        self.assertIn("timed out", res.error_message.lower())

    def test_http_404_error_handling(self):
        """HTTP 404 is caught and structured ERROR returned."""
        mock_resp = httpx.Response(status_code=404, text="Not Found")
        with patch.object(httpx.Client, "get", return_value=mock_resp):
            client = GitHubReleaseClient()
            checker = UpdateChecker(client=client)
            res = checker.check_for_updates(current_version="1.0.0")

        self.assertFalse(res.is_update_available)
        self.assertEqual(res.status, UpdateCheckStatus.ERROR)
        self.assertIn("not found", res.error_message.lower())

    def test_http_500_error_handling(self):
        """HTTP 500 server error handling."""
        mock_resp = httpx.Response(status_code=500, text="Internal Server Error")
        with patch.object(httpx.Client, "get", return_value=mock_resp):
            client = GitHubReleaseClient()
            checker = UpdateChecker(client=client)
            res = checker.check_for_updates(current_version="1.0.0")

        self.assertFalse(res.is_update_available)
        self.assertEqual(res.status, UpdateCheckStatus.ERROR)
        self.assertIn("500", res.error_message)

    def test_github_rate_limit_exceeded(self):
        """HTTP 403 with x-ratelimit-remaining: 0 maps to RATE_LIMITED status."""
        headers = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1731000000"}
        mock_resp = httpx.Response(
            status_code=403,
            headers=headers,
            text='{"message": "API rate limit exceeded"}',
        )
        with patch.object(httpx.Client, "get", return_value=mock_resp):
            client = GitHubReleaseClient()
            checker = UpdateChecker(client=client)
            res = checker.check_for_updates(current_version="1.0.0")

        self.assertFalse(res.is_update_available)
        self.assertEqual(res.status, UpdateCheckStatus.RATE_LIMITED)
        self.assertIn("rate limit", res.error_message.lower())

    def test_etag_conditional_request_304_cache_hit(self):
        """ETag is cached and HTTP 304 reuses cached release payload."""
        rel = make_release_dict(tag_name="v1.0.1")
        resp_200 = httpx.Response(
            status_code=200,
            headers={"etag": '"etag-abc-123"'},
            json=rel,
        )
        resp_304 = httpx.Response(
            status_code=304,
            headers={"etag": '"etag-abc-123"'},
        )

        with patch.object(httpx.Client, "get", side_effect=[resp_200, resp_304]) as mock_get:
            client = GitHubReleaseClient()
            checker = UpdateChecker(client=client)

            # First request: 200 OK -> caches ETag
            res1 = checker.check_for_updates(current_version="1.0.0", allow_prereleases=False)
            self.assertTrue(res1.is_update_available)
            self.assertFalse(res1.from_cache)

            # Second request: 304 Not Modified -> reuses cached payload
            res2 = checker.check_for_updates(current_version="1.0.0", allow_prereleases=False)
            self.assertTrue(res2.is_update_available)
            self.assertTrue(res2.from_cache)
            self.assertEqual(res2.latest_version, SemVer.parse("1.0.1"))

            # Verify 'If-None-Match' was sent in 2nd request
            second_call_headers = mock_get.call_args_list[1][1]["headers"]
            self.assertEqual(second_call_headers.get("If-None-Match"), '"etag-abc-123"')

    def test_malformed_json_response(self):
        """Corrupted JSON response from API is handled safely."""
        mock_resp = httpx.Response(
            status_code=200,
            text="<!DOCTYPE html><html><body>Error</body></html>",
        )
        with patch.object(httpx.Client, "get", return_value=mock_resp):
            client = GitHubReleaseClient()
            checker = UpdateChecker(client=client)
            res = checker.check_for_updates(current_version="1.0.0")

        self.assertFalse(res.is_update_available)
        self.assertIn(res.status, (UpdateCheckStatus.INVALID_RESPONSE, UpdateCheckStatus.ERROR))


class TestAsyncUpdateChecker(unittest.TestCase):
    """Verifies that the checker executes asynchronously on a background worker thread."""

    def test_async_checker_invokes_callback_on_worker_thread(self):
        """check_for_updates_async runs in separate thread and invokes callback with result."""
        rel = make_release_dict(tag_name="v1.0.1")
        mock_client = MagicMock(spec=GitHubReleaseClient)
        mock_client.fetch_latest_release.return_value = GitHubApiResponse(status_code=200, data=rel)

        checker = UpdateChecker(client=mock_client)

        event = threading.Event()
        callback_result = []
        callback_thread_name = []

        def on_complete(result: UpdateCheckResult):
            callback_result.append(result)
            callback_thread_name.append(threading.current_thread().name)
            event.set()

        main_thread_name = threading.current_thread().name

        checker.check_for_updates_async(
            callback=on_complete,
            current_version="1.0.0",
            allow_prereleases=False,
        )

        completed = event.wait(timeout=5.0)
        self.assertTrue(completed, "Async update check timed out")
        self.assertEqual(len(callback_result), 1)
        self.assertTrue(callback_result[0].is_update_available)
        self.assertNotEqual(callback_thread_name[0], main_thread_name)
        self.assertIn("KyaRayUpdater", callback_thread_name[0])

    def test_async_checker_thread_is_daemon(self):
        """Worker thread must be daemon so it never blocks application termination."""
        mock_client = MagicMock(spec=GitHubReleaseClient)
        mock_client.fetch_latest_release.return_value = GitHubApiResponse(
            status_code=200,
            data=make_release_dict(tag_name="v1.0.1"),
        )
        checker = UpdateChecker(client=mock_client)
        event = threading.Event()

        thread = checker.check_for_updates_async(
            callback=lambda res: event.set(),
            current_version="1.0.0",
        )

        self.assertTrue(thread.daemon, "Worker thread must have daemon=True")
        event.wait(timeout=5.0)


class TestPaginationAndSharedArchitecture(unittest.TestCase):
    """Verifies multi-page release traversal and shared version module decoupling."""

    def test_github_pagination_traversal(self):
        """Client traverses pages via Link header and selects highest SemVer release."""
        page1_data = [
            make_release_dict(tag_name="v1.0.0-beta.1", prerelease=True),
            make_release_dict(tag_name="v1.0.0-beta.2", prerelease=True),
        ]
        page2_data = [
            make_release_dict(tag_name="v1.0.0-beta.3", prerelease=True),
            make_release_dict(tag_name="v1.0.0-beta.4", prerelease=True),
        ]

        resp_p1 = httpx.Response(
            status_code=200,
            headers={
                "link": '<https://api.github.com/repos/dumbgesh/kya-ray/releases?page=2>; rel="next"',
                "etag": '"page1-etag"',
            },
            json=page1_data,
        )
        resp_p2 = httpx.Response(
            status_code=200,
            json=page2_data,
        )
        resp_p1_304 = httpx.Response(
            status_code=304,
            headers={"etag": '"page1-etag"'},
        )

        with patch.object(httpx.Client, "get", side_effect=[resp_p1, resp_p2, resp_p1_304]):
            client = GitHubReleaseClient()
            api_res = client.fetch_all_releases(max_pages=3)

            self.assertTrue(api_res.is_success)
            self.assertEqual(len(api_res.data), 4)

            checker = UpdateChecker(client=client)
            # Should detect v1.0.0-beta.4 from page 2 as highest candidate
            res = checker.check_for_updates(current_version="1.0.0-beta.1")
            self.assertTrue(res.is_update_available)
            self.assertEqual(res.latest_version, SemVer.parse("1.0.0-beta.4"))

    def test_shared_version_module_decoupled(self):
        """Verifies root version.py is authoritative and directly importable without desktop package."""
        import version
        import desktop.version

        self.assertEqual(version.APP_VERSION, "1.0.0-beta.1")
        self.assertEqual(desktop.version.APP_VERSION, version.APP_VERSION)
        self.assertEqual(desktop.version.SemVer, version.SemVer)



if __name__ == "__main__":
    unittest.main()

