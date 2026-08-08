"""Read-only mobile companion route coverage."""

import base64
import inspect
import time

import pytest

from unifile.headless import HeadlessService, create_app

_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _client(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    image = library / "photo.png"
    image.write_bytes(_ONE_PIXEL_PNG)
    service = HeadlessService(str(library))
    service.tag(str(image), "favorite")
    app = create_app({
        "MOBILE_ONLY": True,
        "MOBILE_TOKEN": "mobile-token",
        "MOBILE_BOOTSTRAP_TTL": 300,
        "SCHEDULER_FILE": str(tmp_path / "jobs.json"),
    }, service=service)
    app.config.update(TESTING=True)
    return app.test_client(), image, app


def _session(client):
    response = client.post(
        "/mobile/api/session",
        headers={"X-Mobile-Bootstrap": "mobile-token"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["token"]
    assert payload["expires_at"] > int(time.time())
    return payload["token"]


def test_mobile_shell_exposes_no_credential_bearing_urls(tmp_path):
    client, _image, _app = _client(tmp_path)

    page = client.get("/mobile")
    assert page.status_code == 200
    assert b"read-only" in page.data
    assert b"manifest.json" in page.data
    assert b"mobile-token" not in page.data
    assert b"?token=" not in page.data

    manifest = client.get("/mobile/manifest.json")
    assert manifest.status_code == 200
    assert manifest.get_json()["display"] == "standalone"
    assert manifest.get_json()["start_url"] == "/mobile"
    assert "token" not in manifest.get_json()["start_url"]
    assert client.get("/mobile/sw.js").status_code == 200
    assert client.get("/mobile/icon.svg").status_code == 200
    assert client.get("/mobile?token=mobile-token").status_code == 400


def test_mobile_catalog_search_detail_and_preview_are_read_only(tmp_path):
    client, _image, _app = _client(tmp_path)
    headers = {"X-API-Key": _session(client)}

    library = client.get("/mobile/api/library", headers=headers)
    assert library.status_code == 200
    assert library.get_json()["entry_count"] == 1
    assert any(tag["name"] == "favorite" for tag in library.get_json()["tags"])

    entries = client.get("/mobile/api/entries", headers=headers)
    assert entries.status_code == 200
    payload = entries.get_json()["entries"]
    assert payload[0]["name"] == "photo.png"
    assert payload[0]["path"] == "photo.png"
    assert payload[0]["preview_url"].endswith("/preview")
    assert "absolute_path" not in payload[0]

    entry_id = payload[0]["id"]
    detail = client.get(f"/mobile/api/entries/{entry_id}", headers=headers)
    assert detail.status_code == 200
    assert "absolute_path" not in detail.get_json()
    preview = client.get(f"/mobile/api/entries/{entry_id}/preview", headers=headers)
    assert preview.status_code == 200
    assert preview.content_type.startswith("image/")

    filtered = client.get(
        "/mobile/api/entries",
        headers=headers,
        query_string={"tag": "favorite"},
    )
    assert len(filtered.get_json()["entries"]) == 1


def test_mobile_mode_rejects_write_routes(tmp_path):
    client, image, _app = _client(tmp_path)
    headers = {"X-API-Key": "mobile-token"}

    assert client.post("/scan", headers=headers, json={}).status_code == 405
    assert client.post(
        "/tag", headers=headers, json={"path": str(image), "tag": "new"}
    ).status_code == 405
    assert client.post("/jobs", headers=headers, json={}).status_code == 405
    assert client.delete("/jobs/missing", headers=headers).status_code == 405


def test_mobile_session_rotation_and_revocation(tmp_path):
    client, _image, _app = _client(tmp_path)
    first = _session(client)
    first_headers = {"X-API-Key": first}

    rotated = client.post("/mobile/api/session/rotate", headers=first_headers)
    assert rotated.status_code == 200
    second = rotated.get_json()["token"]
    assert second != first
    assert client.get("/mobile/api/library", headers=first_headers).status_code == 401
    second_headers = {"X-API-Key": second}
    assert client.get("/mobile/api/library", headers=second_headers).status_code == 200

    revoked = client.delete("/mobile/api/session", headers=second_headers)
    assert revoked.status_code == 200
    assert revoked.get_json() == {"revoked": True}
    assert client.get("/mobile/api/library", headers=second_headers).status_code == 401


def test_mobile_bootstrap_and_session_expiry_are_fail_safe(tmp_path):
    client, _image, app = _client(tmp_path)
    app.config["MOBILE_BOOTSTRAP_EXPIRES_AT"] = time.time() - 1
    assert client.post(
        "/mobile/api/session",
        headers={"X-Mobile-Bootstrap": "mobile-token"},
    ).status_code == 401

    app.config["MOBILE_BOOTSTRAP_EXPIRES_AT"] = time.time() + 300
    session = _session(client)
    sessions = app.extensions["unifile_mobile_sessions"]
    sessions[session] = time.time() - 1
    assert client.get(
        "/mobile/api/library",
        headers={"X-API-Key": session},
    ).status_code == 401


def test_mobile_server_defaults_to_loopback_and_rejects_remote_without_ack(tmp_path):
    from unifile.mobile import run_mobile_server

    assert inspect.signature(run_mobile_server).parameters["host"].default == "127.0.0.1"
    with pytest.raises(ValueError, match="allow-remote"):
        run_mobile_server(tmp_path, host="0.0.0.0")
