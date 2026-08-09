"""Central outbound network policy and provider observability."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import smtplib
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from email.message import Message
from threading import RLock
from typing import Any

from unifile import __version__

DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_RETRIES = 3
SAFE_RETRY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
RETRY_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
_LOCAL_HOSTNAMES = frozenset({"localhost", "localhost.localdomain"})
_SENSITIVE_QUERY_KEYS = frozenset({
    "api_key", "apikey", "authorization", "key", "password", "secret", "token",
})
_SENSITIVE_HEADER_RE = re.compile(r"(?:authorization|api[-_]?key|password|secret|token)", re.I)
_BASE64_RE = re.compile(r"[A-Za-z0-9+/]{80,}={0,2}")


class NetworkError(OSError):
    """Normalized, redacted outbound request failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "network_error",
        provider: str = "network",
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        self.code = code
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(redact_text(message))


class NetworkPolicyError(NetworkError):
    """URL or host rejected by the outbound policy."""


class NetworkHTTPError(NetworkError):
    """HTTP response rejected by the outbound policy."""


class NetworkTimeout(NetworkError):
    """Connect/read timeout or hard request deadline."""


class NetworkCancelled(NetworkError):
    """Caller cancelled an outbound request before another attempt."""


@dataclass(frozen=True)
class NetworkResponse:
    """Small requests-like response object shared by optional providers."""

    status_code: int
    headers: dict[str, str]
    content: bytes
    url: str

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8"))

    def iter_content(self, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
        for start in range(0, len(self.content), max(1, int(chunk_size))):
            yield self.content[start:start + max(1, int(chunk_size))]

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise NetworkHTTPError(
                f"HTTP {self.status_code} from {redact_url(self.url)}",
                code="http_error",
                status_code=self.status_code,
                retryable=self.status_code in RETRY_STATUS_CODES,
            )

    def close(self) -> None:
        """Match the requests response lifecycle; content is already buffered."""


@dataclass
class _HealthEntry:
    request_count: int = 0
    success_count: int = 0
    error_count: int = 0
    timeout_count: int = 0
    cancelled_count: int = 0
    latency_ms_total: float = 0.0
    last_error: str = ""
    last_code: str = ""


_HEALTH_LOCK = RLock()
_HEALTH: dict[str, _HealthEntry] = {}


def redact_text(value: Any) -> str:
    """Redact credentials, bearer values, and large encoded payloads."""
    text = str(value)
    text = re.sub(r"(Bearer\s+)\S+", r"\1<REDACTED>", text, flags=re.I)
    text = re.sub(
        r"((?:api[_-]?key|password|secret|token|authorization)[\s:=]+)\S+",
        r"\1<REDACTED>",
        text,
        flags=re.I,
    )
    return _BASE64_RE.sub("<BASE64_REDACTED>", text)


def redact_url(url: str) -> str:
    """Return a URL safe for logs and provider-health diagnostics."""
    try:
        parsed = urllib.parse.urlsplit(str(url))
        query = urllib.parse.urlencode(
            [
                (key, "<REDACTED>" if key.lower() in _SENSITIVE_QUERY_KEYS else value)
                for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            ],
            doseq=True,
        )
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))
    except ValueError:
        return "<INVALID_URL>"


def _record_health(
    provider: str,
    *,
    success: bool,
    latency_ms: float,
    code: str = "",
    error: str = "",
) -> None:
    provider = str(provider or "network").strip()[:80] or "network"
    with _HEALTH_LOCK:
        entry = _HEALTH.setdefault(provider, _HealthEntry())
        entry.request_count += 1
        entry.success_count += int(success)
        entry.error_count += int(not success)
        entry.timeout_count += int(code == "timeout")
        entry.cancelled_count += int(code == "cancelled")
        entry.latency_ms_total += max(0.0, float(latency_ms))
        if not success:
            entry.last_code = code or "network_error"
            entry.last_error = redact_text(error)[:500]


def provider_health_snapshot() -> dict[str, dict[str, Any]]:
    """Return bounded provider metrics without URLs, request bodies, or secrets."""
    with _HEALTH_LOCK:
        return {
            provider: {
                "provider": provider,
                "request_count": entry.request_count,
                "success_count": entry.success_count,
                "error_count": entry.error_count,
                "timeout_count": entry.timeout_count,
                "cancelled_count": entry.cancelled_count,
                "error_rate": round(entry.error_count / entry.request_count * 100, 1)
                if entry.request_count
                else 0.0,
                "avg_latency_ms": round(entry.latency_ms_total / entry.request_count, 1)
                if entry.request_count
                else 0.0,
                "last_code": entry.last_code,
                "last_error": entry.last_error,
            }
            for provider, entry in sorted(_HEALTH.items())
        }


def clear_provider_health() -> None:
    with _HEALTH_LOCK:
        _HEALTH.clear()


def _host_is_local(host: str) -> bool:
    normalized = host.strip("[]").lower().rstrip(".")
    if normalized in _LOCAL_HOSTNAMES or normalized.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def validate_url(
    url: str,
    *,
    allow_local: bool = False,
    allowed_hosts: set[str] | frozenset[str] | None = None,
) -> str:
    """Validate an HTTP(S) URL and reject obvious SSRF destinations."""
    value = str(url or "").strip()
    try:
        parsed = urllib.parse.urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise NetworkPolicyError("invalid network URL", code="invalid_url") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise NetworkPolicyError(
            f"outbound URL must be HTTP(S) without embedded credentials: {redact_url(value)}",
            code="invalid_url",
        )
    if port is not None and not 1 <= port <= 65535:
        raise NetworkPolicyError("outbound URL has an invalid port", code="invalid_url")
    normalized_host = host.lower().rstrip(".")
    if allowed_hosts and normalized_host not in {item.lower().rstrip(".") for item in allowed_hosts}:
        raise NetworkPolicyError(
            f"outbound host is not allowed: {normalized_host}",
            code="host_not_allowed",
        )
    if not allow_local and _host_is_local(host):
        raise NetworkPolicyError(
            f"local or private outbound host rejected: {normalized_host}",
            code="ssrf_blocked",
        )
    if not allow_local and not _host_is_local(host):
        try:
            addresses = socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
        except socket.gaierror:
            addresses = []
        for address in addresses:
            resolved = address[4][0]
            if _host_is_local(resolved):
                raise NetworkPolicyError(
                    f"outbound hostname resolves to a private host: {normalized_host}",
                    code="ssrf_blocked",
                )
    return value


def _headers(headers: dict[str, str] | None, *, method: str, user_agent: str | None) -> dict[str, str]:
    result = {str(key): str(value) for key, value in (headers or {}).items()}
    result.setdefault("User-Agent", user_agent or f"UniFile/{__version__}")
    result.setdefault("Accept", "application/json")
    if method not in SAFE_RETRY_METHODS or any(_SENSITIVE_HEADER_RE.search(key) for key in result):
        result.setdefault("Cache-Control", "no-store")
    else:
        result.setdefault("Cache-Control", "no-cache")
    return result


def _read_limited(response: Any, max_bytes: int) -> bytes:
    maximum = max(1, min(int(max_bytes), MAX_RESPONSE_BYTES))
    reader = getattr(response, "read", None)
    if not callable(reader):
        raise NetworkError("network response has no readable body", code="invalid_response")
    try:
        payload = reader(maximum + 1)
    except TypeError:
        payload = reader()
    payload = bytes(payload or b"")
    if len(payload) > maximum:
        raise NetworkError(
            f"network response exceeds {maximum} bytes",
            code="response_too_large",
        )
    return payload


def _response_headers(response: Any) -> dict[str, str]:
    raw = getattr(response, "headers", {}) or {}
    try:
        return {str(key): str(value) for key, value in raw.items()}
    except AttributeError:
        return {}


def request_bytes(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    retries: int = 0,
    backoff: float = 0.25,
    max_bytes: int = MAX_RESPONSE_BYTES,
    allow_local: bool = False,
    allowed_hosts: set[str] | frozenset[str] | None = None,
    provider: str = "network",
    opener: Callable[..., Any] | None = None,
    cancel: Callable[[], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> NetworkResponse:
    """Make one bounded request with safe retries and redacted health metrics."""
    method = str(method or "GET").upper()
    bounded_timeout = max(0.1, min(float(timeout), 600.0))
    retry_count = max(0, min(int(retries), MAX_RETRIES)) if method in SAFE_RETRY_METHODS else 0
    validated_url = validate_url(url, allow_local=allow_local, allowed_hosts=allowed_hosts)
    request_headers = _headers(headers, method=method, user_agent=None)
    last_error: NetworkError | None = None
    started = time.perf_counter()
    for attempt in range(retry_count + 1):
        if cancel and cancel():
            error = NetworkCancelled("outbound request cancelled", code="cancelled", provider=provider)
            _record_health(provider, success=False, latency_ms=_elapsed_ms(started), code=error.code, error=error)
            raise error
        try:
            request = urllib.request.Request(
                validated_url,
                data=data,
                headers=request_headers,
                method=method,
            )
            open_url = opener or urllib.request.urlopen
            with open_url(request, timeout=bounded_timeout) as response:
                status = int(getattr(response, "status", getattr(response, "code", 200)) or 200)
                payload = _read_limited(response, max_bytes)
                if status >= 400:
                    raise NetworkHTTPError(
                        f"HTTP {status} from {redact_url(validated_url)}",
                        code="http_error",
                        provider=provider,
                        status_code=status,
                        retryable=status in RETRY_STATUS_CODES,
                    )
                result = NetworkResponse(status, _response_headers(response), payload, validated_url)
            _record_health(provider, success=True, latency_ms=_elapsed_ms(started))
            return result
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = _read_limited(exc, min(max_bytes, 4096)).decode("utf-8", errors="replace")
            except Exception:
                pass
            last_error = NetworkHTTPError(
                f"HTTP {exc.code} from {redact_url(validated_url)}: {body}",
                code="http_error",
                provider=provider,
                status_code=exc.code,
                retryable=exc.code in RETRY_STATUS_CODES,
            )
        except NetworkError as exc:
            last_error = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            is_timeout = isinstance(exc, TimeoutError) or "timed out" in str(exc).lower()
            last_error = NetworkTimeout(
                f"network request failed for {redact_url(validated_url)}: {exc}",
                code="timeout" if is_timeout else "connection_error",
                provider=provider,
                retryable=True,
            ) if is_timeout else NetworkError(
                f"network request failed for {redact_url(validated_url)}: {exc}",
                code="connection_error",
                provider=provider,
                retryable=True,
            )
        if last_error is None or not last_error.retryable or attempt >= retry_count:
            break
        if cancel and cancel():
            last_error = NetworkCancelled("outbound request cancelled", code="cancelled", provider=provider)
            break
        sleep(max(0.0, float(backoff)) * (2 ** attempt))
    error = last_error or NetworkError("network request failed", provider=provider)
    _record_health(
        provider,
        success=False,
        latency_ms=_elapsed_ms(started),
        code=error.code,
        error=error,
    )
    raise error


def _elapsed_ms(started: float) -> float:
    return max(0.0, (time.perf_counter() - started) * 1000.0)


def request_json(url: str, **kwargs: Any) -> Any:
    """Request and decode a bounded JSON response."""
    response = request_bytes(url, **kwargs)
    try:
        return response.json()
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NetworkError(
            f"network response was not valid JSON from {redact_url(response.url)}",
            code="invalid_json",
            provider=str(kwargs.get("provider", "network")),
        ) from exc


@contextmanager
def stream_request(url: str, **kwargs: Any) -> Iterator[Any]:
    """Open a bounded socket for a caller that must consume a live stream."""
    method = str(kwargs.pop("method", "GET")).upper()
    timeout = max(0.1, min(float(kwargs.pop("timeout", DEFAULT_TIMEOUT_SECONDS)), 600.0))
    provider = str(kwargs.pop("provider", "network"))
    allow_local = bool(kwargs.pop("allow_local", False))
    allowed_hosts = kwargs.pop("allowed_hosts", None)
    headers = _headers(kwargs.pop("headers", None), method=method, user_agent=None)
    data = kwargs.pop("data", None)
    if kwargs:
        raise TypeError(f"unsupported stream request options: {', '.join(sorted(kwargs))}")
    validated_url = validate_url(url, allow_local=allow_local, allowed_hosts=allowed_hosts)
    request = urllib.request.Request(validated_url, data=data, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", getattr(response, "code", 200)) or 200)
            if status >= 400:
                raise NetworkHTTPError(
                    f"HTTP {status} from {redact_url(validated_url)}",
                    code="http_error",
                    provider=provider,
                    status_code=status,
                )
            yield response
        _record_health(provider, success=True, latency_ms=_elapsed_ms(started))
    except NetworkError as exc:
        _record_health(provider, success=False, latency_ms=_elapsed_ms(started), code=exc.code, error=exc)
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        error = NetworkTimeout(
            f"network stream failed for {redact_url(validated_url)}: {exc}",
            code="timeout",
            provider=provider,
            retryable=False,
        ) if isinstance(exc, TimeoutError) else NetworkError(
            f"network stream failed for {redact_url(validated_url)}: {exc}",
            code="connection_error",
            provider=provider,
        )
        _record_health(provider, success=False, latency_ms=_elapsed_ms(started), code=error.code, error=error)
        raise error from exc


class NetworkSession:
    """Small requests-compatible facade using the central policy."""

    def __init__(self, *, provider: str = "network", cache_ttl: float = 0.0, allow_local: bool = False):
        self.provider = provider
        self.cache_ttl = max(0.0, float(cache_ttl))
        self.allow_local = allow_local
        self._cache: dict[str, tuple[float, NetworkResponse]] = {}

    def _request(self, method: str, url: str, **kwargs: Any) -> NetworkResponse:
        params = kwargs.pop("params", None)
        if params:
            query = urllib.parse.urlencode(
                [(key, value) for key, value in params.items() if value is not None],
                doseq=True,
            )
            url = f"{url}{'&' if '?' in url else '?'}{query}" if query else url
        json_body = kwargs.pop("json", None)
        data = kwargs.pop("data", None)
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            kwargs.setdefault("headers", {})["Content-Type"] = "application/json"
        headers = kwargs.pop("headers", None)
        timeout = kwargs.pop("timeout", DEFAULT_TIMEOUT_SECONDS)
        stream = bool(kwargs.pop("stream", False))
        if kwargs:
            raise TypeError(f"unsupported session options: {', '.join(sorted(kwargs))}")
        cache_key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        cacheable = (
            method == "GET"
            and self.cache_ttl > 0
            and not any(_SENSITIVE_HEADER_RE.search(key) for key in (headers or {}))
        )
        if cacheable:
            cached = self._cache.get(cache_key)
            if cached and cached[0] > time.monotonic():
                return cached[1]
        if stream:
            raise ValueError("NetworkSession streaming responses must use request_bytes")
        response = request_bytes(
            url,
            method=method,
            data=data,
            headers=headers,
            timeout=timeout,
            provider=self.provider,
            allow_local=self.allow_local,
        )
        if cacheable:
            if len(self._cache) >= 256:
                self._cache.pop(next(iter(self._cache)))
            self._cache[cache_key] = (time.monotonic() + self.cache_ttl, response)
        return response

    def get(self, url: str, **kwargs: Any) -> NetworkResponse:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> NetworkResponse:
        return self._request("POST", url, **kwargs)

    def mount(self, *_args: Any, **_kwargs: Any) -> None:
        """Compatibility no-op for callers that used requests adapters."""

    def close(self) -> None:
        self._cache.clear()


def send_smtp(
    host: str,
    port: int,
    message: Message,
    *,
    username: str = "",
    password: str = "",
    starttls: bool = True,
    timeout: float = 15.0,
    provider: str = "smtp",
    smtp_factory: Callable[..., Any] = smtplib.SMTP,
) -> None:
    """Send one email with bounded SMTP setup and redacted health diagnostics."""
    host = str(host or "").strip()
    if not host or len(host) > 253 or any(char.isspace() for char in host):
        raise NetworkPolicyError("invalid SMTP host", code="invalid_host", provider=provider)
    started = time.perf_counter()
    try:
        with smtp_factory(host, int(port), timeout=max(0.1, min(float(timeout), 120.0))) as smtp:
            if starttls:
                smtp.starttls()
            if username or password:
                smtp.login(username, password)
            smtp.send_message(message)
    except Exception as exc:
        error = NetworkError(
            f"SMTP delivery failed for {host}: {type(exc).__name__}: {exc}",
            code="smtp_error",
            provider=provider,
        )
        _record_health(provider, success=False, latency_ms=_elapsed_ms(started), code=error.code, error=error)
        raise error from exc
    _record_health(provider, success=True, latency_ms=_elapsed_ms(started))


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_RESPONSE_BYTES",
    "NetworkCancelled",
    "NetworkError",
    "NetworkHTTPError",
    "NetworkPolicyError",
    "NetworkResponse",
    "NetworkSession",
    "NetworkTimeout",
    "clear_provider_health",
    "provider_health_snapshot",
    "redact_text",
    "redact_url",
    "request_bytes",
    "request_json",
    "send_smtp",
    "stream_request",
    "validate_url",
]
