"""Resilient asynchronous HTTP client with backoff, retry, and content hashing."""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING, Any, Self

import httpx

if TYPE_CHECKING:
    from types import TracebackType

DEFAULT_USER_AGENT = (
    "ECUHockeyCalendarCrawler/1.0 (+https://github.com/bdperkin/ecu-hockey-calendar)"
)
DEFAULT_TIMEOUT = 15.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 0.5
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def compute_content_hash(data: bytes | str) -> str:
    """Compute SHA-256 hexadecimal digest for payload content.

    Args:
        data: Raw string or byte content.

    Returns:
        Hexadecimal SHA-256 digest string.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")

    return hashlib.sha256(data).hexdigest()


class ResilientHttpClient:
    """Asynchronous HTTP client with retry, backoff, and content hashing."""

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
        user_agent: str = DEFAULT_USER_AGENT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Initialize HTTP client configuration.

        Args:
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retry attempts for transient failures.
            backoff_factor: Multiplier for exponential backoff sleep intervals.
            user_agent: Custom User-Agent header value.
            transport: Optional custom httpx AsyncBaseTransport (useful for testing).
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "application/json, text/html, */*",
        }
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            headers=self.headers,
            transport=transport,
            follow_redirects=True,
        )

    async def close(self) -> None:
        """Explicitly close the underlying HTTP client session."""
        await self._client.aclose()

    def _merge_headers(self, headers: dict[str, str] | None) -> dict[str, str]:
        """Merge custom headers with default client headers."""
        merged = dict(self.headers)
        if headers:
            merged.update(headers)

        return merged

    async def _sleep_backoff(self, attempt: int) -> None:
        """Sleep for exponential backoff duration if retry limit not reached."""
        if attempt < self.max_retries:
            await asyncio.sleep(self.backoff_factor * (2**attempt))

    async def _single_request(
        self,
        method: str,
        url: str,
        json_data: object,
        headers: dict[str, str],
    ) -> httpx.Response:
        """Execute a single HTTP request and validate retryable status."""
        response = await self._client.request(
            method=method,
            url=url,
            json=json_data,
            headers=headers,
        )
        if response.status_code in RETRYABLE_STATUS_CODES:
            response.raise_for_status()

        return response

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        json_data: object = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Execute HTTP request with exponential backoff on transient errors.

        Args:
            method: HTTP method string (e.g., 'GET', 'POST').
            url: Target URL.
            json_data: Optional JSON body payload.
            headers: Optional extra headers to merge.

        Returns:
            Successful httpx.Response instance.

        Raises:
            httpx.HTTPStatusError: If request fails after all retries.
            httpx.RequestError: If network connection fails after all retries.
        """
        merged_headers = self._merge_headers(headers)
        last_exception: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return await self._single_request(
                    method,
                    url,
                    json_data,
                    merged_headers,
                )
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                last_exception = exc
                await self._sleep_backoff(attempt)

        if last_exception:
            raise last_exception

        msg = "Unexpected request failure state"
        raise RuntimeError(msg)

    async def fetch_text(
        self,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> tuple[str, str]:
        """Fetch raw HTML or text content and compute SHA-256 content digest.

        Args:
            url: Target web page URL.
            headers: Optional request headers.

        Returns:
            Tuple of (text_content, content_hash).
        """
        response = await self._request_with_retry("GET", url, headers=headers)
        text = response.text
        content_hash = compute_content_hash(response.content)
        return text, content_hash

    async def fetch_json(
        self,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> tuple[Any, str]:
        """Fetch JSON data and compute SHA-256 content digest.

        Args:
            url: Target API endpoint URL.
            headers: Optional request headers.

        Returns:
            Tuple of (parsed_json_data, content_hash).
        """
        response = await self._request_with_retry("GET", url, headers=headers)
        content_hash = compute_content_hash(response.content)
        return response.json(), content_hash

    async def post_json(
        self,
        url: str,
        json_data: object,
        headers: dict[str, str] | None = None,
    ) -> tuple[Any, str]:
        """Execute HTTP POST with JSON body and compute response SHA-256 digest.

        Args:
            url: Target API endpoint URL.
            json_data: Request body payload to serialize as JSON.
            headers: Optional request headers.

        Returns:
            Tuple of (parsed_json_data, content_hash).
        """
        response = await self._request_with_retry(
            "POST",
            url,
            json_data=json_data,
            headers=headers,
        )
        content_hash = compute_content_hash(response.content)
        return response.json(), content_hash

    async def __aenter__(self) -> Self:
        """Enter asynchronous context manager."""
        await self._client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit asynchronous context manager and close underlying transport."""
        await self._client.__aexit__(exc_type, exc_val, exc_tb)


__all__ = [
    "DEFAULT_BACKOFF_FACTOR",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_TIMEOUT",
    "DEFAULT_USER_AGENT",
    "RETRYABLE_STATUS_CODES",
    "ResilientHttpClient",
    "compute_content_hash",
]
