"""Read-only mobile companion route coverage."""

import base64

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
        "SCHEDULER_FILE": str(tmp_path / "jobs.json"),
    }, service=service)
    app.config.update(TESTING=True)
    return app.test_client(), image


def test_mobile_shell_requires_token_and_exposes_pwa_assets(tmp_path):
    client, _image = _client(tmp_path)

    assert client.get("/mobile").status_code == 401
    page = client.get("/mobile?token=mobile-token")
    assert page.status_code == 200
    assert b"read-only" in page.data
    assert b"manifest.json" in page.data

    manifest = client.get("/mobile/manifest.json?token=mobile-token")
    assert manifest.status_code == 200
    assert manifest.get_json()["display"] == "standalone"
    assert "token=mobile-token" in manifest.get_json()["start_url"]
    assert client.get("/mobile/sw.js?token=mobile-token").status_code == 200
    assert client.get("/mobile/icon.svg?token=mobile-token").status_code == 200


def test_mobile_catalog_search_detail_and_preview_are_read_only(tmp_path):
    client, _image = _client(tmp_path)
    query = {"token": "mobile-token"}

    library = client.get("/mobile/api/library", query_string=query)
    assert library.status_code == 200
    assert library.get_json()["entry_count"] == 1
    assert any(tag["name"] == "favorite" for tag in library.get_json()["tags"])

    entries = client.get("/mobile/api/entries", query_string=query)
    assert entries.status_code == 200
    payload = entries.get_json()["entries"]
    assert payload[0]["name"] == "photo.png"
    assert payload[0]["path"] == "photo.png"
    assert payload[0]["preview_url"].endswith("/preview")
    assert "absolute_path" not in payload[0]

    entry_id = payload[0]["id"]
    detail = client.get(f"/mobile/api/entries/{entry_id}", query_string=query)
    assert detail.status_code == 200
    assert "absolute_path" not in detail.get_json()
    preview = client.get(f"/mobile/api/entries/{entry_id}/preview", query_string=query)
    assert preview.status_code == 200
    assert preview.content_type.startswith("image/")

    filtered = client.get("/mobile/api/entries", query_string={**query, "tag": "favorite"})
    assert len(filtered.get_json()["entries"]) == 1


def test_mobile_mode_rejects_write_routes(tmp_path):
    client, image = _client(tmp_path)
    headers = {"X-API-Key": "mobile-token"}

    assert client.post("/scan", headers=headers, json={}).status_code == 405
    assert client.post(
        "/tag", headers=headers, json={"path": str(image), "tag": "new"}
    ).status_code == 405
    assert client.post("/jobs", headers=headers, json={}).status_code == 405
    assert client.delete("/jobs/missing", headers=headers).status_code == 405
