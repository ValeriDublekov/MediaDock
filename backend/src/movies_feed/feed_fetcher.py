from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Protocol, Sequence
from urllib.parse import urljoin, urlsplit

import requests


DEFAULT_ALLOWED_FEED_HOSTS = frozenset({"feed.rutracker.cc"})
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 20.0
DEFAULT_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_ENTRIES = 500
DEFAULT_MAX_REDIRECTS = 3
DEFAULT_CHUNK_SIZE = 64 * 1024

ALLOWED_FEED_CONTENT_TYPES = frozenset(
    {
        "application/atom+xml",
        "application/rdf+xml",
        "application/rss+xml",
        "application/xml",
        "text/atom",
        "text/rss",
        "text/xml",
    }
)


class FeedFetcherError(Exception):
    """Base class for bounded RSS fetch and validation failures."""


class FeedUrlError(FeedFetcherError):
    """The URL or one of its resolved addresses violates the feed policy."""


class FeedDnsError(FeedUrlError):
    """DNS resolution failed or returned a non-public address."""


class FeedNetworkError(FeedFetcherError):
    """The transport could not complete the request."""


class FeedResponseError(FeedFetcherError):
    """The server response cannot be accepted as a feed response."""


class FeedStatusError(FeedResponseError):
    """The server returned a non-success HTTP status."""


class FeedContentTypeError(FeedResponseError):
    """The server returned an unsupported or missing content type."""


class FeedSizeLimitError(FeedResponseError):
    """The decompressed feed body exceeded the configured byte limit."""


class FeedEntryLimitError(FeedResponseError):
    """The parsed feed contained more entries than the configured limit."""


class FeedParseError(FeedResponseError):
    """The feed parser marked the response as malformed or incomplete."""


class FeedFixtureError(FeedFetcherError):
    """An explicitly requested local fixture could not be read safely."""


class FeedTransport(Protocol):
    def get(
        self,
        url: str,
        *,
        timeout: tuple[float, float],
        verify: bool,
        allow_redirects: bool,
        stream: bool,
    ) -> Any:
        """Return a response compatible with the requests response API."""


DnsResolver = Callable[[str, int], Iterable[str]]


def _normalize_host(hostname: str) -> str:
    if not isinstance(hostname, str) or not hostname.strip():
        raise FeedUrlError("feed host is missing")
    candidate = hostname.strip().rstrip(".").casefold()
    try:
        return candidate.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise FeedUrlError("feed host is invalid") from exc


def _is_public_address(address_text: str) -> bool:
    try:
        address = ipaddress.ip_address(address_text)
    except ValueError as exc:
        raise FeedDnsError("feed DNS returned an invalid address") from exc

    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped

    return bool(
        address.is_global
        and not address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_reserved
        and not address.is_unspecified
        and not address.is_multicast
    )


def _resolve_host(hostname: str, port: int) -> Iterable[str]:
    try:
        address_records = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except (OSError, socket.gaierror) as exc:
        raise FeedDnsError("feed host DNS resolution failed") from exc

    addresses = []
    for record in address_records:
        sockaddr = record[4]
        if sockaddr:
            addresses.append(sockaddr[0])
    if not addresses:
        raise FeedDnsError("feed host has no addresses")
    return addresses


class RequestsFeedTransport:
    """Requests-backed transport with redirects disabled for caller validation."""

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()

    def get(
        self,
        url: str,
        *,
        timeout: tuple[float, float],
        verify: bool,
        allow_redirects: bool,
        stream: bool,
    ) -> requests.Response:
        return self.session.get(
            url,
            timeout=timeout,
            verify=verify,
            allow_redirects=allow_redirects,
            stream=stream,
        )


class FeedFetcher:
    """Fetch bounded RSS/Atom bytes from a code-owned public host allowlist."""

    def __init__(
        self,
        *,
        allowed_hosts: Optional[Iterable[str]] = None,
        transport: Optional[FeedTransport] = None,
        dns_resolver: Optional[DnsResolver] = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ):
        configured_hosts = allowed_hosts if allowed_hosts is not None else DEFAULT_ALLOWED_FEED_HOSTS
        self.allowed_hosts = frozenset(_normalize_host(hostname) for hostname in configured_hosts)
        if not self.allowed_hosts:
            raise ValueError("at least one allowed feed host is required")
        if connect_timeout <= 0 or read_timeout <= 0:
            raise ValueError("feed timeouts must be positive")
        if max_response_bytes <= 0 or max_entries <= 0 or max_redirects < 0 or chunk_size <= 0:
            raise ValueError("feed bounds must be positive")

        self.connect_timeout = float(connect_timeout)
        self.read_timeout = float(read_timeout)
        self.max_response_bytes = int(max_response_bytes)
        self.max_entries = int(max_entries)
        self.max_redirects = int(max_redirects)
        self.chunk_size = int(chunk_size)
        self.transport = transport or RequestsFeedTransport()
        self.dns_resolver = dns_resolver or _resolve_host

    def _validate_url(self, url: str) -> str:
        if not isinstance(url, str) or not url.strip():
            raise FeedUrlError("feed URL must be a non-empty HTTPS URL")
        candidate = url.strip()
        if any(character.isspace() for character in candidate):
            raise FeedUrlError("feed URL contains whitespace")

        try:
            parsed = urlsplit(candidate)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError as exc:
            raise FeedUrlError("feed URL is malformed") from exc

        if parsed.scheme.casefold() != "https":
            raise FeedUrlError("feed URL must use HTTPS")
        if parsed.username is not None or parsed.password is not None:
            raise FeedUrlError("feed URL must not contain credentials")
        if hostname is None:
            raise FeedUrlError("feed URL host is missing")

        normalized_host = _normalize_host(hostname)
        if normalized_host not in self.allowed_hosts:
            raise FeedUrlError("feed host is not allowlisted")

        resolved_port = port or 443
        try:
            addresses = list(self.dns_resolver(normalized_host, resolved_port))
        except FeedFetcherError:
            raise
        except (OSError, socket.gaierror) as exc:
            raise FeedDnsError("feed host DNS resolution failed") from exc
        if not addresses:
            raise FeedDnsError("feed host has no addresses")
        if any(not _is_public_address(address) for address in addresses):
            raise FeedDnsError("feed host resolved to a non-public address")

        return candidate

    @staticmethod
    def _get_header(response: Any, name: str) -> Optional[str]:
        headers = getattr(response, "headers", None) or {}
        if hasattr(headers, "get"):
            direct_value = headers.get(name)
            if direct_value is not None:
                return str(direct_value)
        for header_name, header_value in getattr(headers, "items", lambda: ())():
            if str(header_name).casefold() == name.casefold():
                return str(header_value)
        return None

    @staticmethod
    def _close_response(response: Any) -> None:
        close = getattr(response, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def _read_body(self, response: Any) -> bytes:
        chunks: list[bytes] = []
        total_size = 0
        iter_content = getattr(response, "iter_content", None)
        try:
            if callable(iter_content):
                response_chunks = iter_content(chunk_size=self.chunk_size)
                for chunk in response_chunks:
                    if not chunk:
                        continue
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise FeedResponseError("feed response contained non-byte data")
                    byte_chunk = bytes(chunk)
                    total_size += len(byte_chunk)
                    if total_size > self.max_response_bytes:
                        raise FeedSizeLimitError("decompressed feed response exceeded the byte limit")
                    chunks.append(byte_chunk)
            else:
                content = getattr(response, "content", None)
                if not isinstance(content, (bytes, bytearray, memoryview)):
                    raise FeedResponseError("feed response body is not bytes")
                content_bytes = bytes(content)
                if len(content_bytes) > self.max_response_bytes:
                    raise FeedSizeLimitError("decompressed feed response exceeded the byte limit")
                chunks.append(content_bytes)
        except FeedFetcherError:
            raise
        except (OSError, requests.RequestException, TimeoutError) as exc:
            raise FeedNetworkError("reading the feed response failed") from exc

        body = b"".join(chunks)
        if not body:
            raise FeedResponseError("feed response body is empty")
        return body

    def fetch(self, url: str) -> bytes:
        """Fetch one configured HTTPS feed and return bounded, decompressed bytes."""
        current_url = self._validate_url(url)
        for redirect_number in range(self.max_redirects + 1):
            try:
                response = self.transport.get(
                    current_url,
                    timeout=(self.connect_timeout, self.read_timeout),
                    verify=True,
                    allow_redirects=False,
                    stream=True,
                )
            except FeedFetcherError:
                raise
            except (OSError, requests.RequestException, TimeoutError) as exc:
                raise FeedNetworkError("feed request failed") from exc

            try:
                status_code = getattr(response, "status_code", None)
                if not isinstance(status_code, int):
                    raise FeedResponseError("feed response has no valid HTTP status")

                if status_code in (301, 302, 303, 307, 308):
                    if redirect_number >= self.max_redirects:
                        raise FeedResponseError("feed redirect limit exceeded")
                    location = self._get_header(response, "Location")
                    if not location:
                        raise FeedResponseError("feed redirect has no location")
                    current_url = self._validate_url(urljoin(current_url, location))
                    continue

                if status_code < 200 or status_code >= 300:
                    raise FeedStatusError("feed server returned a non-success status")

                content_type = self._get_header(response, "Content-Type")
                media_type = content_type.split(";", 1)[0].strip().casefold() if content_type else ""
                if media_type not in ALLOWED_FEED_CONTENT_TYPES:
                    raise FeedContentTypeError("feed server returned an unsupported content type")

                return self._read_body(response)
            finally:
                self._close_response(response)

        raise FeedResponseError("feed redirect limit exceeded")

    def fetch_file(self, path: str | Path) -> bytes:
        """Read an explicitly selected local fixture without passing its path to feedparser."""
        try:
            fixture_path = Path(path)
            if not fixture_path.exists():
                for candidate in (
                    Path("backend") / fixture_path,
                    Path(__file__).parent.parent.parent / fixture_path,
                    Path(__file__).parent.parent.parent / "tests" / "fixtures" / fixture_path.name,
                ):
                    if candidate.exists():
                        fixture_path = candidate
                        break
            with fixture_path.open("rb") as fixture_stream:
                chunks: list[bytes] = []
                total_size = 0
                while True:
                    chunk = fixture_stream.read(self.chunk_size)
                    if not chunk:
                        break
                    total_size += len(chunk)
                    if total_size > self.max_response_bytes:
                        raise FeedSizeLimitError("fixture exceeded the byte limit")
                    chunks.append(chunk)
        except FeedFetcherError:
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise FeedFixtureError("fixture could not be read") from exc

        body = b"".join(chunks)
        if not body:
            raise FeedFixtureError("fixture is empty")
        return body

    def validate_parsed_feed(self, feed: Any) -> Sequence[Any]:
        """Reject bozo/partial parses and enforce the entry amplification bound."""
        if bool(getattr(feed, "bozo", False)):
            exception = getattr(feed, "bozo_exception", None)
            exception_name = type(exception).__name__ if exception is not None else "unknown"
            raise FeedParseError(f"feed parser marked response as incomplete ({exception_name})")

        entries = getattr(feed, "entries", None)
        if entries is None:
            raise FeedParseError("feed parser returned no entries collection")
        self.validate_entry_count(entries)
        return entries

    def validate_entry_count(self, entries: Sequence[Any]) -> None:
        if len(entries) > self.max_entries:
            raise FeedEntryLimitError("feed entry limit exceeded")