import sys

import pytest

from unifile import ai_providers


def test_provider_health_ledger_is_bounded_and_redacts(tmp_path):
    path = tmp_path / "provider-health.json"
    for index in range(65):
        ai_providers.record_provider_health(
            "demo",
            success=index != 64,
            latency_ms=index + 1,
            input_tokens=2,
            output_tokens=3,
            estimated_cost=0.01,
            error="Bearer super-secret-token" if index == 64 else "",
            timestamp=f"2026-08-03T00:{index:02d}:00+00:00",
            path=str(path),
        )

    ledger = ai_providers.load_provider_health(str(path))
    samples = ledger["providers"]["demo"]["samples"]
    assert len(samples) == ai_providers._PROVIDER_HEALTH_LIMIT
    assert samples[0]["latency_ms"] == 6.0
    assert samples[-1]["error"] == "Bearer <REDACTED>"
    assert ledger["providers"]["demo"]["last_error"] == "Bearer <REDACTED>"


def test_ai_provider_records_usage_cost_and_failures(tmp_path, monkeypatch):
    path = tmp_path / "provider-health.json"
    monkeypatch.setattr(ai_providers, "_PROVIDER_HEALTH_FILE", str(path))

    def successful_request(*_args, **_kwargs):
        return {
            "choices": [{"message": {"content": "{\"category\": \"Notes\"}"}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30},
        }

    monkeypatch.setattr(ai_providers, "ai_request", successful_request)
    provider = ai_providers.AIProvider(
        {
            "type": "openai",
            "url": "http://provider.test/v1",
            "model": "demo",
            "input_cost_per_1k": 0.02,
            "output_cost_per_1k": 0.04,
        },
        provider_id="demo",
    )
    assert provider.classify("classify this") == '{"category": "Notes"}'
    assert provider.cost_stats["requests"] == 1
    assert provider.cost_stats["input_tokens"] == 120
    assert provider.cost_stats["output_tokens"] == 30

    def failed_request(*_args, **_kwargs):
        raise ai_providers.AIRequestError("api_key=super-secret-token")

    monkeypatch.setattr(ai_providers, "ai_request", failed_request)
    with pytest.raises(ai_providers.AIRequestError):
        provider.classify("fail this")

    snapshot = ai_providers.provider_health_snapshot(
        {"demo": {"name": "Demo", "type": "openai", "enabled": True}},
        path=str(path),
    )["demo"]
    assert snapshot["request_count"] == 2
    assert snapshot["success_count"] == 1
    assert snapshot["error_count"] == 1
    assert snapshot["error_rate"] == 50.0
    assert snapshot["total_tokens"] == 150
    assert snapshot["estimated_cost"] == pytest.approx(0.0036)
    assert "<REDACTED>" in snapshot["last_error"]


def test_provider_health_snapshot_includes_untested_and_disabled_providers(tmp_path):
    path = tmp_path / "provider-health.json"
    providers = {
        "local": {"name": "Local", "type": "ollama", "enabled": True},
        "cloud": {"name": "Cloud", "type": "openai", "enabled": False},
    }
    snapshot = ai_providers.provider_health_snapshot(providers, path=str(path))
    assert snapshot["local"]["request_count"] == 0
    assert snapshot["local"]["last_ok"] is None
    assert snapshot["cloud"]["enabled"] is False


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0], "-platform", "offscreen"])
    yield app


def test_provider_health_dialog_builds_rows(qapp, tmp_path, monkeypatch):
    path = tmp_path / "provider-health.json"
    monkeypatch.setattr(ai_providers, "_PROVIDER_HEALTH_FILE", str(path))
    providers = {
        "demo": {
            "name": "Demo Provider",
            "type": "openai",
            "enabled": True,
            "priority": 1,
        },
    }
    monkeypatch.setattr(ai_providers, "load_providers", lambda: providers)
    ai_providers.record_provider_health(
        "demo", success=True, latency_ms=42, input_tokens=10,
        output_tokens=5, timestamp="2026-08-03T00:00:00+00:00",
    )

    from unifile.dialogs.provider_health import ProviderHealthDialog

    dialog = ProviderHealthDialog()
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 0).text() == "Demo Provider"
    assert dialog.table.item(0, 1).text() == "Healthy"
    assert dialog.table.cellWidget(0, 6) is not None
    dialog.close()
