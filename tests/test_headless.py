from datetime import datetime

import pytest

pytest.importorskip("flask")


def _client(tmp_path):
    from unifile.headless import HeadlessService, create_app

    library = tmp_path / "library"
    library.mkdir()
    (library / "photo.jpg").write_bytes(b"not-a-real-jpeg")
    service = HeadlessService(str(library))
    app = create_app({
        "API_KEY": "secret",
        "SCHEDULER_FILE": str(tmp_path / "jobs.json"),
    }, service=service)
    app.config.update(TESTING=True)
    return app.test_client(), app, library


def test_health_is_public_but_mutating_routes_require_api_key(tmp_path):
    client, _app, _library = _client(tmp_path)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.get_json()["status"] == "ok"
    health_payload = health.get_json()
    assert "library_root" not in health_payload
    assert "ollama_url" not in health_payload
    assert health.headers["X-Content-Type-Options"] == "nosniff"
    assert health.headers["Referrer-Policy"] == "no-referrer"
    assert client.post("/scan", json={}).status_code == 401
    assert client.get("/report").status_code == 401


def test_headless_request_response_and_rate_limits_are_bounded(tmp_path):
    client, app, _library = _client(tmp_path)
    headers = {"X-API-Key": "secret"}

    app.config["MAX_CONTENT_LENGTH"] = 32
    oversized = client.post(
        "/scan",
        headers=headers,
        json={"path": "x" * 128},
    )
    assert oversized.status_code == 413
    assert "configured size limit" in oversized.get_json()["error"]

    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
    app.config["MAX_RESPONSE_BYTES"] = 32
    oversized_response = client.get("/report", headers=headers)
    assert oversized_response.status_code == 413
    assert oversized_response.get_json()["error"] == "response exceeds configured size limit"

    app.config["MAX_RESPONSE_BYTES"] = 2 * 1024 * 1024
    app.config["RATE_LIMIT_REQUESTS"] = 2
    app.config["RATE_LIMIT_WINDOW_SECONDS"] = 60
    app.extensions["unifile_rate_limits"].clear()
    assert client.get("/report", headers=headers).status_code == 200
    assert client.get("/report", headers=headers).status_code == 200
    limited = client.get("/report", headers=headers)
    assert limited.status_code == 429
    assert limited.headers["Retry-After"]


def test_scan_tag_search_and_report_round_trip(tmp_path):
    client, _app, library = _client(tmp_path)
    headers = {"X-API-Key": "secret"}

    scan = client.post("/scan", headers=headers, json={"path": str(library)})
    assert scan.status_code == 200
    payload = scan.get_json()
    assert payload["version"] == "1"
    assert payload["items"][0]["name"] == "photo.jpg"
    assert payload["items"][0]["category"] == "Images"
    assert payload["action_plan"]["plan_type"] == "file-actions"
    assert payload["verification"] == {"requested": False, "status": "not-requested"}
    assert "file_health" not in payload
    assert not (library / ".unifile" / "file_health.json").exists()

    verified = client.post(
        "/scan",
        headers=headers,
        json={"path": str(library), "verify": True},
    )
    assert verified.status_code == 200
    assert verified.get_json()["verification"]["requested"] is True
    assert verified.get_json()["file_health"]["baselined"] == 1

    tagged = client.post(
        "/tag",
        headers=headers,
        json={"path": str(library / "photo.jpg"), "tag": "important"},
    )
    assert tagged.status_code == 200
    assert "important" in tagged.get_json()["entry"]["tags"]

    search = client.get("/search", headers=headers, query_string={"query": "tag:important"})
    assert search.status_code == 200
    assert search.get_json()["entries"][0]["name"] == "photo.jpg"

    report = client.get("/report", headers=headers)
    assert report.status_code == 200
    assert report.get_json()["entry_count"] == 1
    assert report.get_json()["tag_count"] >= 1


def test_headless_path_guard_rejects_outside_scan_and_tag(tmp_path):
    client, _app, library = _client(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "secret.txt"
    outside_file.write_text("secret", encoding="utf-8")
    headers = {"X-API-Key": "secret"}

    assert client.post("/scan", headers=headers, json={"path": str(outside)}).status_code == 403
    assert client.post(
        "/tag",
        headers=headers,
        json={"path": str(outside_file), "tag": "bad"},
    ).status_code == 403


def test_remote_bind_requires_explicit_acknowledgement():
    from unifile.headless import is_loopback_host, validate_bind_host

    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("::1")
    assert is_loopback_host("localhost")
    with pytest.raises(ValueError, match="allow-remote"):
        validate_bind_host("0.0.0.0")
    assert validate_bind_host("0.0.0.0", allow_remote=True) == "0.0.0.0"


def test_scheduled_job_cron_round_trip_and_execution(tmp_path):
    client, app, library = _client(tmp_path)
    headers = {"X-API-Key": "secret"}
    created = client.post(
        "/jobs",
        headers=headers,
        json={
            "name": "Nightly scan",
            "schedule": "0 2 * * *",
            "action": "scan",
            "path": str(library),
        },
    )
    assert created.status_code == 201
    job = created.get_json()
    assert job["id"]
    assert client.get("/jobs", headers=headers).get_json()["jobs"][0]["name"] == "Nightly scan"

    scheduler = app.extensions["unifile_scheduler"]
    outcomes = scheduler.run_pending(datetime(2026, 8, 3, 2, 0))
    assert outcomes[0]["status"] == "completed"
    assert scheduler.run_pending(datetime(2026, 8, 3, 2, 0)) == []

    invalid = client.post(
        "/jobs",
        headers=headers,
        json={"name": "Bad", "schedule": "not cron", "path": str(library)},
    )
    assert invalid.status_code == 400


def test_scheduler_cron_day_fields_follow_standard_or_semantics():
    from unifile.scheduler import CronExpression

    expression = CronExpression("0 0 1 * 0")
    assert expression.matches(datetime(2026, 2, 1, 0, 0))
    assert expression.matches(datetime(2026, 2, 8, 0, 0))
    assert not expression.matches(datetime(2026, 2, 2, 0, 0))
