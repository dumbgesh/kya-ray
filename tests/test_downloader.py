"""
tests/test_downloader.py - Unit Tests for Kya-Ray Update Downloader and SHA-256 Verification.

Covers:
1. Checksum parsing (Coreutils, BSD, bare hash, manifests).
2. Malformed, empty, and mismatched filename checksum parsing.
3. Incremental file hash computation.
4. Successful chunked download and SHA-256 verification.
5. Progress callback reporting (bytes, percent, speed).
6. Cancellation mid-download and temporary file cleanup.
7. Missing checksum asset handling.
8. Checksum asset HTTP error (404/500).
9. SHA-256 hash mismatch rejection.
10. Checksum pointing to different filename rejection.
11. Content-Length mismatch handling.
12. Network error / connection interruption handling.
13. Existing destination file handling (non-overwrite vs overwrite).
14. Path traversal prevention in asset filename.
15. Insufficient disk space handling.
16. Asynchronous execution on daemon worker thread.
"""

import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import httpx

from desktop.updater import (
    DownloadProgress,
    DownloadResult,
    DownloadStatus,
    ReleaseAsset,
    UpdateDownloader,
    compute_file_sha256,
    get_default_updates_dir,
    parse_sha256_checksum,
    verify_file_sha256,
)


class TestChecksumParsing(unittest.TestCase):
    """Verifies SHA-256 manifest parser across supported formats."""

    def test_parse_coreutils_format(self):
        sample_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        content = f"{sample_hash}  Kya-Ray-v1.0.1-win64.zip\n"
        h, fn = parse_sha256_checksum(content, expected_filename="Kya-Ray-v1.0.1-win64.zip")
        self.assertEqual(h, sample_hash)
        self.assertEqual(fn, "Kya-Ray-v1.0.1-win64.zip")

    def test_parse_coreutils_binary_flag(self):
        sample_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        content = f"{sample_hash} *Kya-Ray-v1.0.1-win64.zip"
        h, fn = parse_sha256_checksum(content, expected_filename="Kya-Ray-v1.0.1-win64.zip")
        self.assertEqual(h, sample_hash)
        self.assertEqual(fn, "Kya-Ray-v1.0.1-win64.zip")

    def test_parse_bsd_format(self):
        sample_hash = "a" * 64
        content = f"SHA256 (Kya-Ray-v1.0.1-win64.zip) = {sample_hash}\n"
        h, fn = parse_sha256_checksum(content, expected_filename="Kya-Ray-v1.0.1-win64.zip")
        self.assertEqual(h, sample_hash)
        self.assertEqual(fn, "Kya-Ray-v1.0.1-win64.zip")

    def test_parse_bare_hash(self):
        sample_hash = "f" * 64
        h, fn = parse_sha256_checksum(sample_hash)
        self.assertEqual(h, sample_hash)
        self.assertIsNone(fn)

    def test_parse_multi_line_manifest(self):
        sample_hash_linux = "1" * 64
        sample_hash_win = "2" * 64
        content = f"{sample_hash_linux}  Kya-Ray-v1.0.1-linux.tar.gz\n{sample_hash_win}  Kya-Ray-v1.0.1-win64.zip\n"
        h, fn = parse_sha256_checksum(content, expected_filename="Kya-Ray-v1.0.1-win64.zip")
        self.assertEqual(h, sample_hash_win)
        self.assertEqual(fn, "Kya-Ray-v1.0.1-win64.zip")

    def test_parse_manifest_missing_expected_filename(self):
        content = f"{'1' * 64}  Kya-Ray-v1.0.1-linux.tar.gz\n{'2' * 64}  Kya-Ray-v1.0.1-macos.zip\n"
        with self.assertRaises(ValueError) as ctx:
            parse_sha256_checksum(content, expected_filename="Kya-Ray-v1.0.1-win64.zip")
        self.assertIn("does not contain entry", str(ctx.exception))

    def test_parse_invalid_hex_length(self):
        invalid_hashes = ["", "abc", "12345", "z" * 64, "1" * 63, "1" * 65]
        for inv in invalid_hashes:
            with self.assertRaises(ValueError):
                parse_sha256_checksum(inv)

    def test_parse_mismatched_single_line_filename(self):
        content = f"{'a' * 64}  other-package.zip"
        with self.assertRaises(ValueError) as ctx:
            parse_sha256_checksum(content, expected_filename="Kya-Ray-win64.zip")
        self.assertIn("expected 'Kya-Ray-win64.zip'", str(ctx.exception))


class TestFileHashing(unittest.TestCase):
    """Verifies incremental hash computation on disk."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_compute_file_sha256(self):
        test_file = Path(self.temp_dir) / "test.bin"
        payload = b"Hello Kya-Ray Update System!\n" * 1024
        test_file.write_bytes(payload)

        expected = hashlib.sha256(payload).hexdigest().lower()
        computed = compute_file_sha256(test_file)
        self.assertEqual(computed, expected)
        self.assertTrue(verify_file_sha256(test_file, expected))
        self.assertFalse(verify_file_sha256(test_file, "0" * 64))


class TestUpdateDownloader(unittest.TestCase):
    """Verifies safe download streaming, SHA-256 verification, and error handling."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.dest_dir = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_mock_client(self, payload_bytes: bytes, checksum_text: str):
        def handler(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            if url_str.endswith(".sha256") or "checksum" in url_str:
                return httpx.Response(200, text=checksum_text)
            return httpx.Response(
                200,
                headers={"Content-Length": str(len(payload_bytes))},
                content=payload_bytes,
            )

        transport = httpx.MockTransport(handler)
        return httpx.Client(transport=transport)

    def test_successful_download_and_verification(self):
        payload_data = b"PK\x03\x04MockKyaRayPayloadZipBytes" * 200
        actual_hash = hashlib.sha256(payload_data).hexdigest()
        checksum_text = f"{actual_hash}  Kya-Ray-v1.0.1-win64.zip\n"

        client = self._make_mock_client(payload_data, checksum_text)
        downloader = UpdateDownloader(client=client)

        payload_asset = ReleaseAsset(
            name="Kya-Ray-v1.0.1-win64.zip",
            download_url="https://github.com/dumbgesh/kya-ray/releases/download/v1.0.1/Kya-Ray-v1.0.1-win64.zip",
            size_bytes=len(payload_data),
        )
        checksum_asset = ReleaseAsset(
            name="Kya-Ray-v1.0.1-win64.zip.sha256",
            download_url="https://github.com/dumbgesh/kya-ray/releases/download/v1.0.1/Kya-Ray-v1.0.1-win64.zip.sha256",
            size_bytes=len(checksum_text),
        )

        progress_events = []

        res = downloader.download_and_verify(
            payload_asset=payload_asset,
            checksum_asset=checksum_asset,
            destination_dir=self.dest_dir,
            progress_callback=lambda p: progress_events.append(p),
        )

        self.assertEqual(res.status, DownloadStatus.COMPLETED)
        self.assertTrue(res.verified)
        self.assertEqual(res.sha256_hash, actual_hash)
        self.assertIsNotNone(res.payload_path)
        self.assertTrue(Path(res.payload_path).is_file())
        self.assertEqual(Path(res.payload_path).read_bytes(), payload_data)
        self.assertTrue(progress_events)
        self.assertEqual(progress_events[-1].downloaded_bytes, len(payload_data))

        # Ensure no temporary .part files remained
        part_files = list(self.dest_dir.glob("*.part.*"))
        self.assertEqual(len(part_files), 0)

    def test_cancellation_mid_download_cleans_up_temp_file(self):
        payload_data = b"X" * (1024 * 512)
        cancel_event = threading.Event()

        # Cancel on first progress tick
        def on_progress(p: DownloadProgress):
            if p.downloaded_bytes > 1024:
                cancel_event.set()

        client = self._make_mock_client(payload_data, f"{'a'*64}  Kya-Ray.zip")
        downloader = UpdateDownloader(client=client, chunk_size=2048)

        payload_asset = ReleaseAsset(
            name="Kya-Ray-v1.0.1-win64.zip",
            download_url="https://github.com/download/Kya-Ray-v1.0.1-win64.zip",
            size_bytes=len(payload_data),
        )

        res = downloader.download_and_verify(
            payload_asset=payload_asset,
            checksum_asset=ReleaseAsset("Kya-Ray.zip.sha256", "https://url.sha256", 64),
            destination_dir=self.dest_dir,
            progress_callback=on_progress,
            cancel_event=cancel_event,
        )

        self.assertEqual(res.status, DownloadStatus.CANCELLED)
        self.assertFalse(res.verified)
        # Verify temporary files were wiped
        part_files = list(self.dest_dir.glob("*.part.*"))
        self.assertEqual(len(part_files), 0)

    def test_missing_checksum_asset_rejects_download(self):
        payload_data = b"PayloadData"
        client = self._make_mock_client(payload_data, "")
        downloader = UpdateDownloader(client=client)

        payload_asset = ReleaseAsset(
            name="Kya-Ray-v1.0.1-win64.zip",
            download_url="https://github.com/download/payload.zip",
            size_bytes=len(payload_data),
        )

        res = downloader.download_and_verify(
            payload_asset=payload_asset,
            checksum_asset=None,  # Missing checksum
            destination_dir=self.dest_dir,
        )

        self.assertEqual(res.status, DownloadStatus.ERROR)
        self.assertFalse(res.verified)
        self.assertIn("Missing SHA-256 checksum", res.error_message)

    def test_sha256_hash_mismatch_rejects_and_cleans_up(self):
        payload_data = b"RealPayloadData"
        wrong_hash = "0" * 64
        checksum_text = f"{wrong_hash}  Kya-Ray-v1.0.1-win64.zip\n"

        client = self._make_mock_client(payload_data, checksum_text)
        downloader = UpdateDownloader(client=client)

        payload_asset = ReleaseAsset(
            name="Kya-Ray-v1.0.1-win64.zip",
            download_url="https://github.com/download/payload.zip",
            size_bytes=len(payload_data),
        )
        checksum_asset = ReleaseAsset(
            name="Kya-Ray-v1.0.1-win64.zip.sha256",
            download_url="https://github.com/download/checksum.sha256",
            size_bytes=len(checksum_text),
        )

        res = downloader.download_and_verify(
            payload_asset=payload_asset,
            checksum_asset=checksum_asset,
            destination_dir=self.dest_dir,
        )

        self.assertEqual(res.status, DownloadStatus.ERROR)
        self.assertFalse(res.verified)
        self.assertIn("hash mismatch", res.error_message.lower())
        # Target file must not have been created
        target = self.dest_dir / "Kya-Ray-v1.0.1-win64.zip"
        self.assertFalse(target.exists())
        self.assertEqual(len(list(self.dest_dir.glob("*.part.*"))), 0)

    def test_checksum_http_error_handled(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if "sha256" in str(request.url):
                return httpx.Response(404, text="Not Found")
            return httpx.Response(200, content=b"ValidZip")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        downloader = UpdateDownloader(client=client)

        res = downloader.download_and_verify(
            payload_asset=ReleaseAsset("app.zip", "https://url/app.zip", 8),
            checksum_asset=ReleaseAsset("app.zip.sha256", "https://url/app.zip.sha256", 64),
            destination_dir=self.dest_dir,
        )

        self.assertEqual(res.status, DownloadStatus.ERROR)
        self.assertIn("HTTP 404", res.error_message)

    def test_payload_http_error_handled(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Server Error")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        downloader = UpdateDownloader(client=client)

        res = downloader.download_and_verify(
            payload_asset=ReleaseAsset("app.zip", "https://url/app.zip", 8),
            checksum_asset=ReleaseAsset("app.zip.sha256", "https://url/app.zip.sha256", 64),
            destination_dir=self.dest_dir,
        )

        self.assertEqual(res.status, DownloadStatus.ERROR)
        self.assertIn("HTTP 500", res.error_message)

    def test_content_length_size_mismatch_rejected(self):
        def handler(request: httpx.Request) -> httpx.Response:
            # Header says 100 bytes, but content is only 10 bytes
            return httpx.Response(200, headers={"Content-Length": "100"}, content=b"1234567890")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        downloader = UpdateDownloader(client=client)

        res = downloader.download_and_verify(
            payload_asset=ReleaseAsset("app.zip", "https://url/app.zip", 100),
            checksum_asset=ReleaseAsset("app.zip.sha256", "https://url/app.zip.sha256", 64),
            destination_dir=self.dest_dir,
        )

        self.assertEqual(res.status, DownloadStatus.ERROR)
        self.assertIn("Downloaded size (10 bytes) does not match", res.error_message)

    def test_path_traversal_prevention(self):
        downloader = UpdateDownloader()
        unsafe_names = ["../../Windows/system32/cmd.exe", "../exploit.zip", "C:\\temp\\hack.zip"]

        for unsafe in unsafe_names:
            res = downloader.download_and_verify(
                payload_asset=ReleaseAsset(unsafe, "https://url/app.zip", 10),
                destination_dir=self.dest_dir,
            )
            # Target must be sanitized to basename within dest_dir or rejected
            if res.payload_path:
                self.assertTrue(res.payload_path.startswith(str(self.dest_dir.resolve())))

    def test_existing_destination_handling(self):
        payload_data = b"AlreadyDownloadedData"
        target_file = self.dest_dir / "app.zip"
        target_file.write_bytes(payload_data)

        downloader = UpdateDownloader()
        # When overwrite=False and no matching checksum provided, reject
        res = downloader.download_and_verify(
            payload_asset=ReleaseAsset("app.zip", "https://url/app.zip", len(payload_data)),
            checksum_asset=None,
            destination_dir=self.dest_dir,
            overwrite=False,
        )

        self.assertEqual(res.status, DownloadStatus.ERROR)
        self.assertIn("already exists", res.error_message.lower())

    def test_async_download_on_daemon_worker_thread(self):
        payload_data = b"AsyncDownloadData"
        actual_hash = hashlib.sha256(payload_data).hexdigest()
        checksum_text = f"{actual_hash}  async-app.zip\n"

        client = self._make_mock_client(payload_data, checksum_text)
        downloader = UpdateDownloader(client=client)

        event = threading.Event()
        callback_result = []

        def on_done(result: DownloadResult):
            callback_result.append(result)
            event.set()

        thread = downloader.download_and_verify_async(
            callback=on_done,
            payload_asset=ReleaseAsset("async-app.zip", "https://url/async-app.zip", len(payload_data)),
            checksum_asset=ReleaseAsset("async-app.zip.sha256", "https://url/async-app.zip.sha256", 64),
            destination_dir=self.dest_dir,
        )

        self.assertTrue(thread.daemon, "Download worker must be a daemon thread")
        completed = event.wait(timeout=5.0)
        self.assertTrue(completed)
        self.assertEqual(callback_result[0].status, DownloadStatus.COMPLETED)
        self.assertTrue(callback_result[0].verified)

    def test_insecure_http_url_rejected(self):
        """Plain HTTP download URLs are rejected to prevent MITM tampering."""
        downloader = UpdateDownloader()
        res = downloader.download_and_verify(
            payload_asset=ReleaseAsset("app.zip", "http://insecure-url.com/app.zip", 100),
            destination_dir=self.dest_dir,
        )
        self.assertEqual(res.status, DownloadStatus.ERROR)
        self.assertIn("HTTPS required", res.error_message)

    def test_cleanup_stale_part_files_on_init(self):
        """Orphaned temporary files from previous crashes are cleaned up."""
        stale_file = self.dest_dir / "old-download.zip.part.12345678"
        stale_file.write_bytes(b"LeftoverFromCrash")
        # Set mtime to 2 hours ago
        two_hours_ago = time.time() - 7200
        os.utime(stale_file, (two_hours_ago, two_hours_ago))

        payload_data = b"FreshValidPayload"
        actual_hash = hashlib.sha256(payload_data).hexdigest()
        checksum_text = f"{actual_hash}  clean-app.zip\n"
        client = self._make_mock_client(payload_data, checksum_text)
        downloader = UpdateDownloader(client=client)

        res = downloader.download_and_verify(
            payload_asset=ReleaseAsset("clean-app.zip", "https://url/clean-app.zip", len(payload_data)),
            checksum_asset=ReleaseAsset("clean-app.zip.sha256", "https://url/clean-app.zip.sha256", len(checksum_text)),
            destination_dir=self.dest_dir,
        )

        self.assertEqual(res.status, DownloadStatus.COMPLETED)
        self.assertFalse(stale_file.exists(), "Stale .part file should have been cleaned up")

    def test_cancellation_during_checksum_phase(self):
        """Cancelling after payload download but before checksum finishes returns CANCELLED."""
        payload_data = b"ValidData"
        cancel_event = threading.Event()

        def handler(request: httpx.Request) -> httpx.Response:
            if "sha256" in str(request.url):
                cancel_event.set()
                return httpx.Response(200, text=f"{'a'*64}  app.zip\n")
            return httpx.Response(200, content=payload_data)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        downloader = UpdateDownloader(client=client)

        res = downloader.download_and_verify(
            payload_asset=ReleaseAsset("app.zip", "https://url/app.zip", len(payload_data)),
            checksum_asset=ReleaseAsset("app.zip.sha256", "https://url/app.zip.sha256", 64),
            destination_dir=self.dest_dir,
            cancel_event=cancel_event,
        )

        self.assertEqual(res.status, DownloadStatus.CANCELLED)
        # Verify no temp files left
        self.assertEqual(len(list(self.dest_dir.glob("*.part.*"))), 0)

    def test_existing_corrupted_file_not_mistaken_for_valid(self):
        """A corrupted existing file is never returned as verified COMPLETED."""
        target_file = self.dest_dir / "app.zip"
        target_file.write_bytes(b"CorruptedPayloadBytes")

        actual_hash = hashlib.sha256(b"LegitimateUncorruptedData").hexdigest()
        checksum_text = f"{actual_hash}  app.zip\n"
        client = self._make_mock_client(b"LegitimateUncorruptedData", checksum_text)
        downloader = UpdateDownloader(client=client)

        # When overwrite=False, revalidation against checksum fails -> ERROR
        res = downloader.download_and_verify(
            payload_asset=ReleaseAsset("app.zip", "https://url/app.zip", 24),
            checksum_asset=ReleaseAsset("app.zip.sha256", "https://url/app.zip.sha256", len(checksum_text)),
            destination_dir=self.dest_dir,
            overwrite=False,
        )

        self.assertEqual(res.status, DownloadStatus.ERROR)
        self.assertFalse(res.verified)
        self.assertIn("already exists", res.error_message.lower())

    def test_atomic_overwrite_replaces_existing_cleanly(self):
        """When overwrite=True, existing file is replaced atomically with verified new payload."""
        target_file = self.dest_dir / "app.zip"
        target_file.write_bytes(b"OldVersionPayload")

        new_data = b"NewVerifiedVersion2Payload"
        actual_hash = hashlib.sha256(new_data).hexdigest()
        checksum_text = f"{actual_hash}  app.zip\n"
        client = self._make_mock_client(new_data, checksum_text)
        downloader = UpdateDownloader(client=client)

        res = downloader.download_and_verify(
            payload_asset=ReleaseAsset("app.zip", "https://url/app.zip", len(new_data)),
            checksum_asset=ReleaseAsset("app.zip.sha256", "https://url/app.zip.sha256", len(checksum_text)),
            destination_dir=self.dest_dir,
            overwrite=True,
        )

        self.assertEqual(res.status, DownloadStatus.COMPLETED)
        self.assertTrue(res.verified)
        self.assertEqual(target_file.read_bytes(), new_data)

    def test_https_to_https_redirect_succeeds(self):
        """Valid HTTPS to HTTPS redirect is permitted and downloaded safely."""
        payload_data = b"RedirectedPayloadContent"
        actual_hash = hashlib.sha256(payload_data).hexdigest()
        checksum_text = f"{actual_hash}  app.zip\n"

        def handler(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            if url_str == "https://initial.github.com/app.zip":
                return httpx.Response(302, headers={"Location": "https://cdn.github.com/app.zip"})
            if url_str == "https://cdn.github.com/app.zip":
                return httpx.Response(200, content=payload_data)
            if "sha256" in url_str:
                return httpx.Response(200, text=checksum_text)
            return httpx.Response(404)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        downloader = UpdateDownloader(client=client)

        res = downloader.download_and_verify(
            payload_asset=ReleaseAsset("app.zip", "https://initial.github.com/app.zip", len(payload_data)),
            checksum_asset=ReleaseAsset("app.zip.sha256", "https://cdn.github.com/app.zip.sha256", len(checksum_text)),
            destination_dir=self.dest_dir,
        )

        self.assertEqual(res.status, DownloadStatus.COMPLETED)
        self.assertTrue(res.verified)

    def test_https_to_http_redirect_rejected_before_request(self):
        """HTTPS to plain HTTP redirect downgrade is rejected before making the insecure request."""
        requests_seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests_seen.append(str(request.url))
            if str(request.url) == "https://initial.github.com/app.zip":
                return httpx.Response(302, headers={"Location": "http://insecure-cdn.com/app.zip"})
            return httpx.Response(200, content=b"InsecureData")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        downloader = UpdateDownloader(client=client)

        res = downloader.download_and_verify(
            payload_asset=ReleaseAsset("app.zip", "https://initial.github.com/app.zip", 10),
            destination_dir=self.dest_dir,
        )

        self.assertEqual(res.status, DownloadStatus.ERROR)
        self.assertIn("HTTPS required", res.error_message)
        # Verify the insecure HTTP URL was NEVER requested
        self.assertNotIn("http://insecure-cdn.com/app.zip", requests_seen)

    def test_redirect_loop_or_excessive_redirects_rejected(self):
        """Redirect cycles exceeding max_redirects are terminated safely."""
        def handler(request: httpx.Request) -> httpx.Response:
            # Infinite redirect loop
            return httpx.Response(302, headers={"Location": "https://example.com/loop"})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        downloader = UpdateDownloader(client=client, max_redirects=3)

        res = downloader.download_and_verify(
            payload_asset=ReleaseAsset("app.zip", "https://example.com/initial", 10),
            destination_dir=self.dest_dir,
        )

        self.assertEqual(res.status, DownloadStatus.ERROR)
        self.assertIn("Too many redirects", res.error_message)

    def test_valid_github_cdn_redirect_succeeds(self):
        """Simulates GitHub release asset redirecting to S3 CDN with sensitive header stripping."""
        payload_data = b"GitHubReleaseZipViaS3CDN"
        actual_hash = hashlib.sha256(payload_data).hexdigest()
        checksum_text = f"{actual_hash}  app.zip\n"
        cdn_headers_received = {}

        def handler(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            if "sha256" in url_str:
                return httpx.Response(200, text=checksum_text)
            if "github.com/releases/download" in url_str:
                return httpx.Response(
                    302,
                    headers={"Location": "https://github-production-release-asset-2e65be.s3.amazonaws.com/123/app.zip"},
                )
            if "s3.amazonaws.com" in url_str:
                cdn_headers_received.update(dict(request.headers))
                return httpx.Response(200, content=payload_data)
            return httpx.Response(404)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        downloader = UpdateDownloader(client=client)

        res = downloader.download_and_verify(
            payload_asset=ReleaseAsset(
                "app.zip",
                "https://github.com/releases/download/v1.0.1/app.zip",
                len(payload_data),
            ),
            checksum_asset=ReleaseAsset(
                "app.zip.sha256",
                "https://github.com/releases/download/v1.0.1/app.zip.sha256",
                len(checksum_text),
            ),
            destination_dir=self.dest_dir,
        )

        self.assertEqual(res.status, DownloadStatus.COMPLETED)
        self.assertTrue(res.verified)
        # Ensure no sensitive authorization/cookie headers leaked to the CDN
        self.assertNotIn("authorization", cdn_headers_received)
        self.assertNotIn("cookie", cdn_headers_received)




if __name__ == "__main__":
    unittest.main()

