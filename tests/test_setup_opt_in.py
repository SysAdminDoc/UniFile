import sys


def test_bootstrap_does_not_install_without_opt_in(monkeypatch):
    import unifile.bootstrap as bootstrap

    calls = []
    monkeypatch.delenv("UNIFILE_INSTALL_DEPS", raising=False)
    monkeypatch.setattr(bootstrap.importlib.util, "find_spec", lambda _name: None)
    monkeypatch.setattr(bootstrap.subprocess, "check_call", lambda *a, **k: calls.append((a, k)))

    bootstrap._bootstrap()

    assert calls == []


def test_bootstrap_installs_only_when_opted_in(monkeypatch):
    import unifile.bootstrap as bootstrap

    calls = []
    monkeypatch.setenv("UNIFILE_INSTALL_DEPS", "1")
    monkeypatch.setattr(
        bootstrap.importlib.util,
        "find_spec",
        lambda name: None if name == "pyqt6" else object(),
    )
    monkeypatch.setattr(bootstrap.subprocess, "check_call", lambda cmd, **_kwargs: calls.append(cmd) or 0)

    bootstrap._bootstrap()

    assert calls == [[sys.executable, "-m", "pip", "install", "PyQt6", "-q"]]


def test_ollama_setup_worker_does_not_install_by_default(monkeypatch):
    import unifile.workers as workers

    calls = []
    worker = workers.OllamaSetupWorker(model="qwen2.5:7b", url="http://localhost:11434")
    monkeypatch.setattr(workers, "_find_ollama_binary", lambda: "")
    monkeypatch.setattr(worker, "_install_ollama", lambda: calls.append("install") or True)

    worker._setup()

    assert calls == []


def test_ollama_setup_worker_does_not_pull_by_default(monkeypatch):
    import unifile.workers as workers

    calls = []
    worker = workers.OllamaSetupWorker(model="qwen2.5:7b", url="http://localhost:11434")
    monkeypatch.setattr(workers, "_find_ollama_binary", lambda: "ollama")
    monkeypatch.setattr(workers, "_is_ollama_server_running", lambda _url: True)
    monkeypatch.setattr(workers, "_ollama_has_model", lambda _model, _url: False)
    monkeypatch.setattr(worker, "_pull_model", lambda _binary: calls.append("pull") or True)

    worker._setup()

    assert calls == []


def test_scan_files_llm_worker_does_not_auto_pull_missing_model(monkeypatch, tmp_path):
    import unifile.workers as workers

    calls = []
    worker = workers.ScanFilesLLMWorker(str(tmp_path), str(tmp_path), categories=[])
    monkeypatch.setattr(workers, "_is_ollama_server_running", lambda _url: True)
    monkeypatch.setattr(workers, "_ollama_has_model", lambda _model, _url: False)
    monkeypatch.setattr(
        workers,
        "_ollama_pull_model_streaming",
        lambda *a, **k: calls.append((a, k)) or True,
    )

    ok = worker._ensure_ollama_ready({"url": "http://localhost:11434", "model": "missing:model"})

    assert ok is False
    assert calls == []
