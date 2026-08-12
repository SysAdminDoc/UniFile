import json

from unifile import ai_providers


def test_anthropic_messages_adapter_uses_native_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_providers, "_PROVIDER_HEALTH_FILE", str(tmp_path / "health.json"))
    calls = []

    def fake_request(url, **kwargs):
        calls.append((url, kwargs))
        return {
            "content": [{"type": "text", "text": "{\"category\": \"Notes\"}"}],
            "usage": {"input_tokens": 12, "output_tokens": 4},
        }

    monkeypatch.setattr(ai_providers, "ai_request", fake_request)
    provider = ai_providers.AIProvider(
        {
            "type": "anthropic",
            "url": "https://api.anthropic.com",
            "api_key": "sk-test",
            "model": "claude-sonnet-4-5",
        },
        provider_id="anthropic",
    )
    schema = {"type": "object", "properties": {"category": {"type": "string"}}}
    assert provider.classify("Classify this", system="Be concise", format=schema) == (
        '{"category": "Notes"}'
    )

    url, kwargs = calls[0]
    payload = json.loads(kwargs["data"])
    assert url == "https://api.anthropic.com/v1/messages"
    assert kwargs["headers"]["x-api-key"] == "sk-test"
    assert kwargs["headers"]["anthropic-version"] == "2023-06-01"
    assert payload["model"] == "claude-sonnet-4-5"
    assert payload["messages"] == [{"role": "user", "content": "Classify this"}]
    assert "Be concise" in payload["system"]
    assert "category" in payload["system"]
    assert provider.cost_stats["input_tokens"] == 12
    assert provider.cost_stats["output_tokens"] == 4


def test_gemini_generate_content_adapter_uses_native_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_providers, "_PROVIDER_HEALTH_FILE", str(tmp_path / "health.json"))
    calls = []

    def fake_request(url, **kwargs):
        calls.append((url, kwargs))
        return {
            "candidates": [{"content": {"parts": [{"text": "{\"ok\": true}"}]}}],
            "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 3},
        }

    monkeypatch.setattr(ai_providers, "ai_request", fake_request)
    provider = ai_providers.AIProvider(
        {
            "type": "gemini",
            "url": "https://generativelanguage.googleapis.com/v1beta",
            "api_key": "gem-test",
            "model": "gemini-3.6-flash",
        },
        provider_id="gemini",
    )
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    assert provider.classify("Return JSON", system="Use strict JSON", format=schema) == (
        '{"ok": true}'
    )

    url, kwargs = calls[0]
    payload = json.loads(kwargs["data"])
    assert url == (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-3.6-flash:generateContent"
    )
    assert kwargs["headers"]["x-goog-api-key"] == "gem-test"
    assert payload["systemInstruction"] == {"parts": [{"text": "Use strict JSON"}]}
    assert payload["contents"] == [{"role": "user", "parts": [{"text": "Return JSON"}]}]
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    assert payload["generationConfig"]["responseSchema"] == schema
    assert provider.cost_stats["input_tokens"] == 9
    assert provider.cost_stats["output_tokens"] == 3


def test_native_adapters_encode_vision_images_without_network(tmp_path, monkeypatch):
    image = tmp_path / "sample.jpg"
    image.write_bytes(b"jpeg-bytes")
    monkeypatch.setattr(ai_providers, "_PROVIDER_HEALTH_FILE", str(tmp_path / "health.json"))
    monkeypatch.setattr(ai_providers, "ai_request", lambda *_args, **_kwargs: {
        "content": [{"type": "text", "text": "claude image"}],
        "usage": {"input_tokens": 2, "output_tokens": 1},
    })
    anthropic = ai_providers.AIProvider({
        "type": "anthropic", "url": "https://api.anthropic.com", "api_key": "key",
        "vision_model": "claude-sonnet-4-5",
    })
    assert anthropic.classify_with_vision("Describe", str(image)) == "claude image"

    calls = []

    def gemini_request(url, **kwargs):
        calls.append((url, kwargs))
        return {
            "candidates": [{"content": {"parts": [{"text": "gemini image"}]}}],
            "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 1},
        }

    monkeypatch.setattr(ai_providers, "ai_request", gemini_request)
    gemini = ai_providers.AIProvider({
        "type": "gemini", "url": "https://generativelanguage.googleapis.com/v1beta",
        "api_key": "key", "vision_model": "gemini-3.6-flash",
    })
    assert gemini.classify_with_vision("Describe", str(image)) == "gemini image"
    payload = json.loads(calls[0][1]["data"])
    image_part = payload["contents"][0]["parts"][0]["inline_data"]
    assert image_part["mime_type"] == "image/jpeg"
    assert image_part["data"]


def test_provider_factory_exposes_named_backend_adapters():
    assert isinstance(
        ai_providers.create_provider_adapter({"type": "ollama"}),
        ai_providers.OllamaAdapter,
    )
    assert isinstance(
        ai_providers.create_provider_adapter({"type": "openai"}),
        ai_providers.OpenAICompatibleAdapter,
    )
    assert isinstance(
        ai_providers.create_provider_adapter({"type": "anthropic"}),
        ai_providers.AnthropicAdapter,
    )
    assert isinstance(
        ai_providers.create_provider_adapter({"type": "gemini"}),
        ai_providers.GeminiAdapter,
    )


def test_provider_chain_accepts_network_free_injected_adapter(monkeypatch):
    adapter = ai_providers.OfflineProvider(
        responses=['{"category": "Notes"}'],
        provider_id="offline-test",
    )

    def fail_network(*_args, **_kwargs):
        raise AssertionError("offline provider attempted network access")

    monkeypatch.setattr(ai_providers, "ai_request", fail_network)
    chain = ai_providers.ProviderChain(
        {
            "offline": {
                "type": "offline",
                "enabled": True,
                "priority": 1,
                "model": "deterministic",
                "vision_model": "deterministic-vision",
            }
        },
        adapters={"offline": adapter},
    )

    result, provider = chain.classify(
        "Classify this file",
        system="Use JSON",
        format={"type": "object"},
    )

    assert result == '{"category": "Notes"}'
    assert provider == "offline"
    assert adapter.calls == [{
        "operation": "text",
        "prompt": "Classify this file",
        "model": None,
        "system": "Use JSON",
        "format": {"type": "object"},
    }]
    assert isinstance(adapter, ai_providers.ProviderAdapter)
