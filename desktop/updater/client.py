"""
desktop/updater/client.py - GitHub Releases API Client for Kya-Ray.

Provides robust, timeout-bounded HTTP communication with the GitHub Releases API.
Implements ETag-based conditional requests (HTTP 304), rate limit detection,
pagination across release listings, and error categorization without throwing unhandled exceptions.
"""

from dataclasses import dataclass
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx

from version import APP_VERSION

logger = logging.getLogger("kya_ray.updater.client")

DEFAULT_GITHUB_REPO = "dumbgesh/kya-ray"
DEFAULT_API_BASE_URL = "https://api.github.com"
DEFAULT_TIMEOUT_SECONDS = 10.0


def _parse_next_link(link_header: Optional[str]) -> Optional[str]:
    """Extracts next page URL from GitHub Link header if present."""
    if not link_header:
        return None
    for segment in link_header.split(","):
        segment = segment.strip()
        if 'rel="next"' in segment:
            match = re.search(r"<([^>]+)>", segment)
            if match:
                return match.group(1)
    return None


@dataclass
class GitHubApiResponse:
    """Encapsulates the response from a GitHub API call."""
    status_code: int
    data: Optional[Union[Dict[str, Any], list]] = None
    etag: Optional[str] = None
    is_cached: bool = False
    is_rate_limited: bool = False
    rate_limit_reset: Optional[int] = None
    error_message: Optional[str] = None

    @property
    def is_success(self) -> bool:
        """Returns True if the response contains valid data (either 200 or 304 cached)."""
        return (200 <= self.status_code < 300 or self.status_code == 304) and self.data is not None


class GitHubReleaseClient:
    """
    Communicates with the GitHub Releases API with caching and error handling.
    """

    def __init__(
        self,
        repo: str = DEFAULT_GITHUB_REPO,
        base_url: str = DEFAULT_API_BASE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        client: Optional[httpx.Client] = None,
    ):
        self.repo = repo.strip().strip("/")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self._custom_client = client
        # In-memory ETag and data cache: url -> (etag, data)
        self._cache: Dict[str, Tuple[str, Any]] = {}

    def _get_headers(self, etag: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": f"Kya-Ray-Updater/{APP_VERSION}",
        }
        if etag:
            headers["If-None-Match"] = etag
        return headers

    def clear_cache(self) -> None:
        """Clears the in-memory ETag response cache."""
        self._cache.clear()

    def fetch_latest_release(self, use_cache: bool = True) -> GitHubApiResponse:
        """
        Fetches the latest published stable release from:
        GET /repos/{owner}/{repo}/releases/latest
        """
        endpoint = f"/repos/{self.repo}/releases/latest"
        return self._request(endpoint, use_cache=use_cache)

    def fetch_all_releases(
        self,
        per_page: int = 100,
        max_pages: int = 3,
        use_cache: bool = True,
    ) -> GitHubApiResponse:
        """
        Fetches the list of releases (including pre-releases) from:
        GET /repos/{owner}/{repo}/releases?per_page={per_page}
        Supports pagination up to max_pages to ensure all candidate releases are considered.
        """
        initial_url = f"{self.base_url}/repos/{self.repo}/releases?per_page={max(1, min(100, per_page))}"

        # Check cache on initial endpoint
        cached_entry = self._cache.get(initial_url) if use_cache else None
        cached_etag = cached_entry[0] if cached_entry else None

        res_first = self._request_url(initial_url, cached_etag=cached_etag)
        if not res_first.is_success:
            return res_first

        if res_first.is_cached and cached_entry is not None:
            return res_first

        if not isinstance(res_first.data, list):
            return res_first

        all_releases: List[Dict[str, Any]] = list(res_first.data)
        next_url = res_first._next_url if hasattr(res_first, "_next_url") else None
        pages_fetched = 1

        while next_url and pages_fetched < max_pages:
            res_next = self._request_url(next_url, cached_etag=None)
            if res_next.is_success and isinstance(res_next.data, list):
                all_releases.extend(res_next.data)
                next_url = getattr(res_next, "_next_url", None)
                pages_fetched += 1
            else:
                break

        # Cache combined releases for initial URL
        if res_first.etag and use_cache:
            self._cache[initial_url] = (res_first.etag, all_releases)

        return GitHubApiResponse(
            status_code=200,
            data=all_releases,
            etag=res_first.etag,
            is_cached=False,
        )

    def _request(self, endpoint: str, use_cache: bool = True) -> GitHubApiResponse:
        url = f"{self.base_url}{endpoint}"
        cached_entry = self._cache.get(url) if use_cache else None
        cached_etag = cached_entry[0] if cached_entry else None
        res = self._request_url(url, cached_etag=cached_etag)

        if res.etag and res.data is not None and use_cache:
            self._cache[url] = (res.etag, res.data)

        return res

    def _request_url(self, url: str, cached_etag: Optional[str] = None) -> GitHubApiResponse:
        headers = self._get_headers(etag=cached_etag)

        try:
            if self._custom_client is not None:
                response = self._custom_client.get(
                    url,
                    headers=headers,
                    timeout=self.timeout_seconds,
                    follow_redirects=True,
                )
            else:
                with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
                    response = client.get(url, headers=headers)

            status_code = response.status_code
            etag = response.headers.get("etag") or response.headers.get("ETag")
            link_header = response.headers.get("link")
            next_url = _parse_next_link(link_header)

            # Check rate limiting
            remaining = response.headers.get("x-ratelimit-remaining")
            reset_ts = None
            try:
                raw_reset = response.headers.get("x-ratelimit-reset")
                if raw_reset:
                    reset_ts = int(raw_reset)
            except (ValueError, TypeError):
                pass

            is_rate_limited = (
                status_code == 403
                and (remaining == "0" or "rate limit" in response.text.lower())
            )

            if is_rate_limited:
                logger.warning("GitHub API rate limit encountered for %s", url)
                return GitHubApiResponse(
                    status_code=403,
                    is_rate_limited=True,
                    rate_limit_reset=reset_ts,
                    error_message="GitHub API rate limit exceeded. Please try again later.",
                )

            # 304 Not Modified: Return cached response
            if status_code == 304 and cached_etag:
                cached_entry = self._cache.get(url)
                if cached_entry:
                    return GitHubApiResponse(
                        status_code=304,
                        data=cached_entry[1],
                        etag=cached_etag,
                        is_cached=True,
                    )

            if status_code == 404:
                return GitHubApiResponse(
                    status_code=404,
                    error_message=f"Repository or release not found: {self.repo}",
                )

            if status_code >= 400:
                return GitHubApiResponse(
                    status_code=status_code,
                    error_message=f"GitHub API returned HTTP {status_code}: {response.text[:200]}",
                )

            # Parse JSON
            try:
                data = response.json()
            except Exception as e:
                logger.error("Failed to parse JSON response from %s: %s", url, e)
                return GitHubApiResponse(
                    status_code=status_code,
                    error_message=f"Invalid JSON payload returned from GitHub: {e}",
                )

            api_res = GitHubApiResponse(
                status_code=status_code,
                data=data,
                etag=etag,
                is_cached=False,
            )
            api_res._next_url = next_url  # type: ignore[attr-defined]
            return api_res

        except httpx.TimeoutException as e:
            logger.warning("Timeout connecting to GitHub API at %s: %s", url, e)
            return GitHubApiResponse(
                status_code=0,
                error_message=f"Connection timed out while contacting GitHub API: {e}",
            )
        except httpx.NetworkError as e:
            logger.warning("Network error contacting GitHub API at %s: %s", url, e)
            return GitHubApiResponse(
                status_code=0,
                error_message=f"Network error while contacting GitHub API: {e}",
            )
        except Exception as e:
            logger.error("Unexpected error contacting GitHub API at %s: %s", url, e)
            return GitHubApiResponse(
                status_code=0,
                error_message=f"Unexpected error checking updates: {e}",
            )
