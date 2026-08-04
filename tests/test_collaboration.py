"""Role, ACL, conflict, audit, and LAN API coverage."""

import json

import pytest

from unifile.collaboration import CollaborationConflict, CollaborationStore
from unifile.headless import HeadlessService, create_app


def _users(library):
    store = CollaborationStore(library)
    admin = store.create_user("admin", "Library Admin", "admin", token="admin-token-123456")
    editor = store.create_user("editor", "Library Editor", "editor", token="editor-token-123456")
    viewer = store.create_user("viewer", "Library Viewer", "viewer", token="viewer-token-123456")
    return store, admin, editor, viewer


def _headers(user):
    return {"X-UniFile-User": user["user_id"], "X-UniFile-Token": user["token"]}


def test_store_hashes_tokens_and_rejects_stale_fields(tmp_path):
    store, admin, editor, _viewer = _users(tmp_path / "library")

    state = json.loads(store.state_path.read_text(encoding="utf-8"))
    assert admin["token"] not in store.state_path.read_text(encoding="utf-8")
    assert state["users"][0]["token_hash"]
    assert store.authenticate("admin", admin["token"]).role == "admin"
    assert store.authenticate("admin", "wrong-token") is None

    first = store.accept_field("entry:1:tag:2", store.authenticate("editor", editor["token"]),
                               "2026-08-03T00:00:00Z")
    assert first["timestamp"].startswith("2026-08-03T00:00:00")
    with pytest.raises(CollaborationConflict) as conflict:
        store.accept_field("entry:1:tag:2", store.authenticate("admin", admin["token"]),
                           "2025-01-01T00:00:00Z")
    assert conflict.value.field == "entry:1:tag:2"
    assert conflict.value.current["user_id"] == "editor"

    store.record_audit(store.authenticate("admin", admin["token"]), "test.change", "entry:1")
    assert store.audit_events(1)[0]["action"] == "test.change"


def test_collaborative_roles_acl_conflicts_and_admin_surfaces(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    public_file = library / "public.txt"
    secret_file = library / "secret.txt"
    public_file.write_text("public", encoding="utf-8")
    secret_file.write_text("secret", encoding="utf-8")

    service = HeadlessService(library)
    service.tag(str(public_file), "public")
    service.tag(str(secret_file), "tag:confidential")
    service.tag(str(public_file), "shared")
    store, admin, editor, viewer = _users(library)
    app = create_app({
        "COLLABORATIVE_MODE": True,
        "SCHEDULER_FILE": str(tmp_path / "jobs.json"),
    }, service=service)
    app.config.update(TESTING=True)
    client = app.test_client()

    assert client.get("/collab/search").status_code == 401
    assert client.get("/collab/me", headers=_headers(viewer)).get_json()["role"] == "viewer"

    viewer_search = client.get("/search", headers=_headers(viewer))
    assert viewer_search.status_code == 200
    viewer_entries = viewer_search.get_json()["entries"]
    assert [entry["name"] for entry in viewer_entries] == ["public.txt"]
    assert client.get("/collab/tags", headers=_headers(viewer)).status_code == 403
    assert client.post(
        "/tag", headers=_headers(viewer), json={"entry_id": 1, "tag": "shared"}
    ).status_code == 403

    admin_search = client.get("/collab/search", headers=_headers(admin))
    assert admin_search.status_code == 200
    assert {entry["name"] for entry in admin_search.get_json()["entries"]} == {
        "public.txt", "secret.txt"
    }
    secret = next(entry for entry in admin_search.get_json()["entries"] if entry["name"] == "secret.txt")
    public = next(entry for entry in admin_search.get_json()["entries"] if entry["name"] == "public.txt")

    tagged = client.post(
        "/collab/tag",
        headers=_headers(editor),
        json={
            "entry_id": public["id"],
            "tag": "shared",
            "field_timestamp": "2026-08-03T00:00:00Z",
        },
    )
    assert tagged.status_code == 200
    version = tagged.get_json()["field_version"]["timestamp"]
    stale = client.post(
        "/collab/tag",
        headers=_headers(admin),
        json={"entry_id": public["id"], "tag": "shared", "field_timestamp": "2025-01-01T00:00:00Z"},
    )
    assert stale.status_code == 409
    assert stale.get_json()["current"]["timestamp"] == version

    assert client.post(
        "/collab/tags", headers=_headers(editor), json={"action": "add", "name": "blocked"}
    ).status_code == 403
    created = client.post(
        "/collab/tags",
        headers=_headers(admin),
        json={"action": "add", "name": "approved", "namespace": "workflow"},
    )
    assert created.status_code == 200
    assert created.get_json()["tag"]["name"] == "approved"
    approved_id = created.get_json()["tag"]["id"]

    acl = client.post(
        "/collab/tags",
        headers=_headers(admin),
        json={"action": "acl", "id": approved_id, "roles": ["admin", "editor"]},
    )
    assert acl.status_code == 200
    assert acl.get_json()["allowed_roles"] == ["admin", "editor"]
    rules = client.post(
        "/collab/rules", headers=_headers(admin), json={"rules": [{"name": "Images", "priority": 1}]}
    )
    assert rules.status_code == 200
    assert client.get("/collab/rules", headers=_headers(admin)).get_json()["rules"][0]["name"] == "Images"
    assert client.get("/collab/rules", headers=_headers(editor)).status_code == 403

    users = client.post(
        "/collab/users",
        headers=_headers(admin),
        json={"user_id": "newviewer", "display_name": "New Viewer", "role": "viewer"},
    )
    assert users.status_code == 201
    assert len(users.get_json()["token"]) >= 16
    assert any(
        user["user_id"] == "newviewer"
        for user in client.get("/collab/users", headers=_headers(admin)).get_json()["users"]
    )

    audit = client.get("/collab/audit", headers=_headers(admin))
    assert audit.status_code == 200
    actions = {event["action"] for event in audit.get_json()["events"]}
    assert {"tag.add", "tag.create", "tag.acl", "rules.update", "user.create"} <= actions
    assert "tag:confidential" in secret["tags"]
