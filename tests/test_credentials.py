import json

from unifile import credentials


class _MemoryKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def delete_password(self, service, username):
        self.values.pop((service, username), None)


def test_environment_precedes_keyring(monkeypatch):
    backend = _MemoryKeyring()
    monkeypatch.setattr(credentials, "_KEYRING_OVERRIDE", backend)
    assert credentials.set_credential("media:tmdb", "keyring-value")

    monkeypatch.setenv("TMDB_TEST_KEY", "environment-value")
    assert credentials.get_credential("media:tmdb", env_var="TMDB_TEST_KEY") == "environment-value"
    monkeypatch.delenv("TMDB_TEST_KEY")
    assert credentials.get_credential("media:tmdb", env_var="TMDB_TEST_KEY") == "keyring-value"


def test_legacy_text_migrates_without_plaintext_backup(monkeypatch, tmp_path):
    backend = _MemoryKeyring()
    monkeypatch.setattr(credentials, "_KEYRING_OVERRIDE", backend)
    legacy = tmp_path / "legacy-key.txt"
    legacy.write_text("legacy-secret", encoding="utf-8")

    assert credentials.get_credential("metadata:envato", legacy_path=legacy) == "legacy-secret"
    assert not legacy.exists()
    assert not (tmp_path / "legacy-key.txt.bak").exists()
    assert backend.values[("UniFile", "metadata:envato")] == "legacy-secret"


def test_legacy_json_migrates_every_mapped_field(monkeypatch, tmp_path):
    backend = _MemoryKeyring()
    monkeypatch.setattr(credentials, "_KEYRING_OVERRIDE", backend)
    legacy = tmp_path / "media_api_keys.json"
    legacy.write_text(
        json.dumps({"tmdb": "tmdb-secret", "opensubtitles_password": "sub-secret"}),
        encoding="utf-8",
    )

    result = credentials.migrate_legacy_json(
        legacy,
        {
            "tmdb": "media:tmdb",
            "opensubtitles_password": "media:opensubtitles_password",
        },
    )

    assert result.status == "migrated"
    assert set(result.migrated) == {"media:tmdb", "media:opensubtitles_password"}
    assert not legacy.exists()
    assert backend.values[("UniFile", "media:tmdb")] == "tmdb-secret"
    assert backend.values[("UniFile", "media:opensubtitles_password")] == "sub-secret"


def test_missing_keyring_never_reads_or_writes_plaintext(monkeypatch, tmp_path):
    monkeypatch.setattr(credentials, "_KEYRING_OVERRIDE", None)
    legacy = tmp_path / "legacy-key.txt"
    legacy.write_text("must-not-be-read", encoding="utf-8")

    assert credentials.get_credential("metadata:envato", legacy_path=legacy) == ""
    assert credentials.migrate_legacy_text("metadata:envato", legacy).status == "keyring-unavailable"
    assert credentials.set_credential("metadata:envato", "new-secret") is False
    assert legacy.read_text(encoding="utf-8") == "must-not-be-read"
    status = credentials.credential_status("metadata:envato", legacy_path=legacy)
    assert status["configured"] is False
    assert status["migration"] == "keyring-unavailable"
    assert "must-not-be-read" not in json.dumps(status)


def test_ai_provider_keys_are_stripped_from_settings(monkeypatch, tmp_path):
    backend = _MemoryKeyring()
    monkeypatch.setattr(credentials, "_KEYRING_OVERRIDE", backend)
    from unifile import ai_providers

    path = tmp_path / "ai_providers.json"
    monkeypatch.setattr(ai_providers, "_PROVIDERS_FILE", str(path))
    assert ai_providers.save_providers(
        {"demo": {"name": "Demo", "type": "openai", "api_key": "ai-secret"}}
    )
    saved = path.read_text(encoding="utf-8")
    assert "ai-secret" not in saved
    assert ai_providers.load_providers()["demo"]["api_key"] == "ai-secret"


def test_scheduler_passwords_are_keyring_only(monkeypatch, tmp_path):
    backend = _MemoryKeyring()
    monkeypatch.setattr(credentials, "_KEYRING_OVERRIDE", backend)
    from unifile.scheduler import load_jobs, save_jobs, validate_job

    job = validate_job({
        "id": "smtp-job",
        "name": "Digest",
        "schedule": "0 3 * * 0",
        "action": "scan",
        "path": str(tmp_path),
        "email": {
            "host": "smtp.example.test",
            "from": "from@example.test",
            "to": "to@example.test",
            "username": "user",
            "password": "smtp-secret",
        },
    })
    assert "password" not in job["email"]
    assert credentials.get_credential("scheduler:smtp:smtp-job") == "smtp-secret"

    path = tmp_path / "jobs.json"
    assert save_jobs([job], str(path))
    saved = path.read_text(encoding="utf-8")
    assert "smtp-secret" not in saved
    persisted = json.loads(saved)
    assert "password" not in persisted[0]["email"]
    assert "password_ref" not in persisted[0]["email"]
    loaded = load_jobs(str(path))
    assert "password" not in loaded[0]["email"]
