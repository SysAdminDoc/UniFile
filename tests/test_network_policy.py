"""Central outbound network policy and observability coverage."""
from __future__ import annotations

import urllib.error

import pytest

from unifile import network


class _Response:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, payload=b'{"ok": true}'):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=None):
        return self.payload


def test_validate_url_blocks_private_hosts_unless_explicitly_local():
    with pytest.raises(network.NetworkPolicyError, match="private"):
        network.validate_url("http://127.0.0.1:11434")
    assert network.validate_url("http://127.0.0.1:11434", allow_local=True).startswith("http://")


def test_get_retries_transient_failures_and_records_redacted_health(monkeypatch):
    network.clear_provider_health()
    monkeypatch.setattr(network.socket, "getaddrinfo", lambda *_args, **_kwargs: [])
    calls = []

    def opener(request, timeout):
        calls.append((request.full_url, timeout))
        if len(calls) < 3:
            raise urllib.error.URLError("Bearer super-secret-token")
        return _Response()

    result = network.request_json(
        "https://example.test/api?token=super-secret-token",
        retries=2,
        backoff=0,
        opener=opener,
        provider="demo",
        sleep=lambda _delay: None,
    )

    assert result == {"ok": True}
    assert len(calls) == 3
    snapshot = network.provider_health_snapshot()["demo"]
    assert snapshot["request_count"] == 1
    assert snapshot["success_count"] == 1
    assert "super-secret-token" not in network.redact_url(calls[0][0])


def test_post_is_not_retried_and_malformed_json_is_normalized(monkeypatch):
    monkeypatch.setattr(network.socket, "getaddrinfo", lambda *_args, **_kwargs: [])
    calls = []

    def opener(*_args, **_kwargs):
        calls.append(True)
        raise urllib.error.URLError("connection refused")

    with pytest.raises(network.NetworkError) as error:
        network.request_bytes(
            "https://example.test/write",
            method="POST",
            data=b"{}",
            retries=3,
            opener=opener,
        )
    assert error.value.code == "connection_error"
    assert len(calls) == 1

    with pytest.raises(network.NetworkError) as malformed:
        network.request_json("https://example.test/bad", opener=lambda *_args, **_kwargs: _Response(b"nope"))
    assert malformed.value.code == "invalid_json"


def test_cancellation_happens_before_transport(monkeypatch):
    monkeypatch.setattr(network.socket, "getaddrinfo", lambda *_args, **_kwargs: [])
    called = []

    with pytest.raises(network.NetworkCancelled) as error:
        network.request_bytes(
            "https://example.test/cancel",
            opener=lambda *_args, **_kwargs: called.append(True),
            cancel=lambda: True,
        )
    assert error.value.code == "cancelled"
    assert called == []
