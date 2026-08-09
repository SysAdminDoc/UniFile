"""UniFile -- Multi-provider AI backend (Ollama, OpenAI-compatible, Groq)."""
import base64
import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from urllib.parse import quote as _url_quote

from unifile.config import _APP_DATA_DIR, save_json_safe
from unifile.credentials import (
    delete_credential,
    get_credential,
    keyring_available,
    set_credential,
)
from unifile.network import NetworkError, redact_text, request_json

_log = logging.getLogger(__name__)


class AIRequestError(Exception):
    """Normalized error from an AI provider HTTP call."""


def _redact(text: str) -> str:
    """Scrub API keys, bearer tokens, and long base64 blobs from diagnostics."""
    return redact_text(text)


def ai_request(url: str, *, method: str = 'POST', data: bytes | None = None,
               headers: dict | None = None, timeout: int = 30,
               retries: int = 1, backoff: float = 1.0) -> dict:
    """Unified HTTP helper for AI provider calls.

    Returns parsed JSON response dict on success.
    Raises ``AIRequestError`` with redacted diagnostics on failure.
    Retries on 5xx and connection errors; does NOT retry 4xx (client bugs).
    """
    request_headers = dict(headers or {})
    request_headers.setdefault('Content-Type', 'application/json')
    try:
        return request_json(
            url,
            method=method,
            data=data,
            headers=request_headers,
            timeout=timeout,
            retries=retries,
            backoff=backoff,
            provider='ai',
            allow_local=True,
        )
    except NetworkError as exc:
        msg = _redact(str(exc))
        _log.debug("AI request failed: %s", msg)
        raise AIRequestError(msg) from exc

_PROVIDERS_FILE = os.path.join(_APP_DATA_DIR, 'ai_providers.json')
_PROVIDER_HEALTH_FILE = os.path.join(_APP_DATA_DIR, 'ai_provider_health.json')
_PROVIDER_HEALTH_LIMIT = 60
_PROVIDER_HEALTH_LOCK = threading.RLock()


def _nonnegative_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _nonnegative_float(value) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _health_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _empty_provider_health() -> dict:
    return {'version': 1, 'providers': {}}


def _read_provider_health(path: str) -> dict:
    """Read and lightly validate the local provider health ledger."""
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return _empty_provider_health()
    if not isinstance(raw, dict) or not isinstance(raw.get('providers'), dict):
        return _empty_provider_health()

    providers = {}
    for provider_id, payload in raw['providers'].items():
        if not isinstance(payload, dict):
            continue
        samples = []
        raw_samples = payload.get('samples', [])
        if isinstance(raw_samples, list):
            for raw_sample in raw_samples[-_PROVIDER_HEALTH_LIMIT:]:
                if not isinstance(raw_sample, dict):
                    continue
                sample = {
                    'timestamp': str(raw_sample.get('timestamp', '')),
                    'ok': bool(raw_sample.get('ok', False)),
                    'latency_ms': round(_nonnegative_float(raw_sample.get('latency_ms')), 2),
                    'input_tokens': _nonnegative_int(raw_sample.get('input_tokens')),
                    'output_tokens': _nonnegative_int(raw_sample.get('output_tokens')),
                    'estimated_cost': round(_nonnegative_float(raw_sample.get('estimated_cost')), 8),
                    'operation': str(raw_sample.get('operation', 'inference'))[:32],
                }
                if raw_sample.get('error'):
                    sample['error'] = _redact(str(raw_sample.get('error')))[:500]
                samples.append(sample)
        providers[str(provider_id)] = {
            'samples': samples,
            'last_checked': str(payload.get('last_checked', '')),
            'last_success': str(payload.get('last_success', '')),
            'last_error': _redact(str(payload.get('last_error', '')))[:500],
        }
    return {'version': 1, 'providers': providers}


def _write_provider_health(data: dict, path: str) -> bool:
    """Atomically write the local health ledger, best effort."""
    directory = os.path.dirname(os.path.abspath(path))
    temp_path = ''
    try:
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix='.ai-provider-health-', suffix='.tmp',
                                         dir=directory)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, path)
        return True
    except OSError:
        return False
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def load_provider_health(path: str | None = None) -> dict:
    """Load the redacted, local-only provider health history."""
    target = path or _PROVIDER_HEALTH_FILE
    with _PROVIDER_HEALTH_LOCK:
        return _read_provider_health(target)


def record_provider_health(provider_id: str, *, success: bool, latency_ms: float,
                           input_tokens: int = 0, output_tokens: int = 0,
                           estimated_cost: float = 0.0, error: str = '',
                           operation: str = 'inference', timestamp: str | None = None,
                           path: str | None = None) -> dict:
    """Append one provider request sample to the bounded local health ledger."""
    provider_id = str(provider_id or 'provider').strip() or 'provider'
    timestamp = timestamp or _health_timestamp()
    sample = {
        'timestamp': str(timestamp),
        'ok': bool(success),
        'latency_ms': round(_nonnegative_float(latency_ms), 2),
        'input_tokens': _nonnegative_int(input_tokens),
        'output_tokens': _nonnegative_int(output_tokens),
        'estimated_cost': round(_nonnegative_float(estimated_cost), 8),
        'operation': str(operation or 'inference')[:32],
    }
    if error:
        sample['error'] = _redact(str(error))[:500]

    target = path or _PROVIDER_HEALTH_FILE
    with _PROVIDER_HEALTH_LOCK:
        data = _read_provider_health(target)
        entry = data['providers'].setdefault(provider_id, {
            'samples': [], 'last_checked': '', 'last_success': '', 'last_error': '',
        })
        entry['samples'] = (entry.get('samples', []) + [sample])[-_PROVIDER_HEALTH_LIMIT:]
        entry['last_checked'] = sample['timestamp']
        if success:
            entry['last_success'] = sample['timestamp']
        elif error:
            entry['last_error'] = sample['error']
        _write_provider_health(data, target)
    return sample


def clear_provider_health(path: str | None = None, provider_id: str | None = None) -> bool:
    """Clear all health history or one provider's history."""
    target = path or _PROVIDER_HEALTH_FILE
    with _PROVIDER_HEALTH_LOCK:
        if provider_id:
            data = _read_provider_health(target)
            data['providers'].pop(str(provider_id), None)
        else:
            data = _empty_provider_health()
        return _write_provider_health(data, target)


def provider_health_snapshot(providers: dict | None = None,
                             path: str | None = None) -> dict:
    """Return dashboard-ready health metrics for configured providers."""
    providers = providers if providers is not None else load_providers()
    ledger = load_provider_health(path)
    snapshot = {}
    for provider_id, config in providers.items():
        config = config if isinstance(config, dict) else {}
        entry = ledger['providers'].get(str(provider_id), {})
        samples = list(entry.get('samples', []))
        success_count = sum(1 for sample in samples if sample.get('ok'))
        error_count = len(samples) - success_count
        latency_values = [
            _nonnegative_float(sample.get('latency_ms'))
            for sample in samples
            if _nonnegative_float(sample.get('latency_ms')) > 0
        ]
        input_tokens = sum(_nonnegative_int(sample.get('input_tokens')) for sample in samples)
        output_tokens = sum(_nonnegative_int(sample.get('output_tokens')) for sample in samples)
        estimated_cost = sum(_nonnegative_float(sample.get('estimated_cost')) for sample in samples)
        latest = samples[-1] if samples else {}
        snapshot[str(provider_id)] = {
            'id': str(provider_id),
            'name': str(config.get('name', provider_id)),
            'type': str(config.get('type', 'provider')),
            'enabled': bool(config.get('enabled', False)),
            'request_count': len(samples),
            'success_count': success_count,
            'error_count': error_count,
            'error_rate': round((error_count / len(samples)) * 100, 1) if samples else 0.0,
            'avg_latency_ms': round(sum(latency_values) / len(latency_values), 1) if latency_values else 0.0,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'total_tokens': input_tokens + output_tokens,
            'estimated_cost': round(estimated_cost, 8),
            'last_checked': entry.get('last_checked', ''),
            'last_success': entry.get('last_success', ''),
            'last_error': entry.get('last_error', ''),
            'last_ok': latest.get('ok') if latest else None,
            'samples': samples,
        }
    return snapshot

# Default provider configurations
_DEFAULT_PROVIDERS = {
    'ollama': {
        'name': 'Ollama (Local)',
        'type': 'ollama',
        'enabled': True,
        'priority': 1,
        'url': 'http://localhost:11434',
        'model': 'qwen3.5:9b',
        'vision_model': 'gemma3:27b',
        'timeout': 30,
        'api_key': '',
        'input_cost_per_1k': 0.0,
        'output_cost_per_1k': 0.0,
    },
    'openai_compat': {
        'name': 'OpenAI-Compatible (LM Studio / vLLM)',
        'type': 'openai',
        'enabled': False,
        'priority': 2,
        'url': 'http://localhost:1234/v1',
        'model': 'default',
        'vision_model': '',
        'timeout': 30,
        'api_key': 'not-needed',
        'input_cost_per_1k': 0.0,
        'output_cost_per_1k': 0.0,
    },
    'groq': {
        'name': 'Groq Cloud',
        'type': 'openai',
        'enabled': False,
        'priority': 3,
        'url': 'https://api.groq.com/openai/v1',
        'model': 'llama-3.3-70b-versatile',
        'vision_model': 'llama-3.2-90b-vision-preview',
        'timeout': 30,
        'api_key': '',
        'input_cost_per_1k': 0.0,
        'output_cost_per_1k': 0.0,
    },
    'openai': {
        'name': 'OpenAI',
        'type': 'openai',
        'enabled': False,
        'priority': 4,
        'url': 'https://api.openai.com/v1',
        'model': 'gpt-4o-mini',
        'vision_model': 'gpt-4o',
        'timeout': 30,
        'api_key': '',
        'input_cost_per_1k': 0.0,
        'output_cost_per_1k': 0.0,
    },
    'anthropic': {
        'name': 'Anthropic Claude',
        'type': 'anthropic',
        'enabled': False,
        'priority': 5,
        'url': 'https://api.anthropic.com',
        'model': 'claude-sonnet-4-5',
        'vision_model': 'claude-sonnet-4-5',
        'timeout': 30,
        'api_key': '',
        'input_cost_per_1k': 0.0,
        'output_cost_per_1k': 0.0,
    },
    'gemini': {
        'name': 'Google Gemini',
        'type': 'gemini',
        'enabled': False,
        'priority': 6,
        'url': 'https://generativelanguage.googleapis.com/v1beta',
        'model': 'gemini-3.6-flash',
        'vision_model': 'gemini-3.6-flash',
        'timeout': 30,
        'api_key': '',
        'input_cost_per_1k': 0.0,
        'output_cost_per_1k': 0.0,
    },
}


_AI_KEY_ENV_VARS = {
    'openai_compat': 'OPENAI_API_KEY',
    'groq': 'GROQ_API_KEY',
    'openai': 'OPENAI_API_KEY',
    'anthropic': 'ANTHROPIC_API_KEY',
    'gemini': 'GEMINI_API_KEY',
}


def _load_key_from_keyring(provider_id: str) -> str:
    return get_credential(f'ai:{provider_id}')


def _save_key_to_keyring(provider_id: str, key: str) -> bool:
    return set_credential(f'ai:{provider_id}', key) if key else delete_credential(
        f'ai:{provider_id}'
    )


def load_providers() -> dict:
    """Load provider configurations from disk.
    API keys are loaded from the environment-independent OS keyring.

    Legacy JSON API-key fields are migrated when a keyring backend is
    available. They are never returned to callers when migration is not
    possible.
    """
    providers = dict(_DEFAULT_PROVIDERS)
    migrated_legacy = False
    if os.path.isfile(_PROVIDERS_FILE):
        try:
            with open(_PROVIDERS_FILE, encoding='utf-8') as f:
                saved = json.load(f)
            for key, val in saved.items():
                if isinstance(val, dict) and val.get('api_key'):
                    legacy_key = str(val.get('api_key', ''))
                    if keyring_available() and _save_key_to_keyring(str(key), legacy_key):
                        migrated_legacy = True
                    else:
                        _log.warning(
                            "Ignoring legacy plaintext AI credential for provider %s; "
                            "an OS keyring is required.",
                            key,
                        )
                    val = dict(val)
                    val['api_key'] = ''
                    migrated_legacy = True
                if key in providers:
                    providers[key].update(val)
                else:
                    providers[key] = val
        except (json.JSONDecodeError, OSError):
            pass
    if migrated_legacy:
        save_json_safe(
            _PROVIDERS_FILE,
            {str(key): {**dict(value), 'api_key': ''} for key, value in providers.items()},
        )
    for pid, cfg in providers.items():
        env_var = _AI_KEY_ENV_VARS.get(str(pid), '')
        env_key = os.environ.get(env_var, '').strip() if env_var else ''
        if env_key:
            cfg['api_key'] = env_key
        else:
            kr_key = _load_key_from_keyring(str(pid))
            if kr_key:
                cfg['api_key'] = kr_key
    return providers


def save_providers(providers: dict) -> bool:
    """Save provider configurations to disk.
    API keys are stored in the OS keyring and stripped from the JSON file.
    The settings file is not written when a non-empty key cannot be secured.
    """
    save_copy = {}
    for pid, cfg in providers.items():
        entry = dict(cfg)
        api_key = entry.get('api_key', '')
        env_var = _AI_KEY_ENV_VARS.get(str(pid), '')
        if env_var and os.environ.get(env_var, '').strip():
            pass
        elif api_key and str(api_key) != 'not-needed':
            if not _save_key_to_keyring(str(pid), str(api_key)):
                return False
        elif keyring_available() and not _save_key_to_keyring(str(pid), ''):
            return False
        entry['api_key'] = ''
        save_copy[pid] = entry
    return save_json_safe(_PROVIDERS_FILE, save_copy)


def get_active_provider(providers: dict | None = None,
                        task: str = "text") -> dict | None:
    """Get the highest-priority enabled provider.

    Args:
        providers: Provider config dict. If None, loads from disk.
        task: "text" or "vision" to check for model availability.

    Returns:
        Provider config dict, or None if none available.
    """
    if providers is None:
        providers = load_providers()
    candidates = []
    for key, cfg in providers.items():
        if not cfg.get('enabled', False):
            continue
        if task == 'vision' and not cfg.get('vision_model'):
            continue
        candidates.append((cfg.get('priority', 99), key, cfg))
    candidates.sort(key=lambda x: x[0])
    return candidates[0][2] if candidates else None


class AIProvider:
    """Unified interface for AI text/vision inference."""

    def __init__(self, config: dict, provider_id: str | None = None):
        self.config = config
        self.provider_id = str(
            provider_id or config.get('id') or config.get('name') or config.get('type') or 'provider'
        )
        self.type = config.get('type', 'ollama')
        self.url = config.get('url', '').rstrip('/')
        self.api_key = config.get('api_key', '')
        self.timeout = config.get('timeout', 30)
        self._cost_tracker = {
            'requests': 0, 'errors': 0, 'input_tokens': 0, 'output_tokens': 0,
            'latency_ms_total': 0.0,
        }

    def _estimated_token_cost(self, input_tokens: int, output_tokens: int) -> float:
        input_rate = _nonnegative_float(self.config.get('input_cost_per_1k'))
        output_rate = _nonnegative_float(self.config.get('output_cost_per_1k'))
        return (input_tokens / 1000.0) * input_rate + (output_tokens / 1000.0) * output_rate

    def _record_request(self, started: float, *, success: bool, response: dict | None = None,
                        error: Exception | str = '', operation: str = 'inference') -> None:
        """Update in-process counters and persist one redacted health sample."""
        response = response if isinstance(response, dict) else {}
        usage = response.get('usage') if isinstance(response.get('usage'), dict) else {}
        if self.type == 'ollama':
            input_tokens = _nonnegative_int(response.get('prompt_eval_count'))
            output_tokens = _nonnegative_int(response.get('eval_count'))
        elif self.type == 'anthropic':
            input_tokens = _nonnegative_int(usage.get('input_tokens'))
            output_tokens = _nonnegative_int(usage.get('output_tokens'))
        elif self.type == 'gemini':
            gemini_usage = response.get('usageMetadata')
            if not isinstance(gemini_usage, dict):
                gemini_usage = {}
            input_tokens = _nonnegative_int(gemini_usage.get('promptTokenCount'))
            output_tokens = _nonnegative_int(gemini_usage.get('candidatesTokenCount'))
        else:
            input_tokens = _nonnegative_int(usage.get('prompt_tokens'))
            output_tokens = _nonnegative_int(usage.get('completion_tokens'))
        latency_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        estimated_cost = self._estimated_token_cost(input_tokens, output_tokens)
        self._cost_tracker['requests'] += 1
        self._cost_tracker['errors'] += 0 if success else 1
        self._cost_tracker['input_tokens'] += input_tokens
        self._cost_tracker['output_tokens'] += output_tokens
        self._cost_tracker['latency_ms_total'] += latency_ms
        record_provider_health(
            self.provider_id,
            success=success,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=estimated_cost,
            error=str(error) if error else '',
            operation=operation,
        )

    def _openai_headers(self) -> dict:
        headers = {}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        return headers

    def _anthropic_base_url(self) -> str:
        return self.url if self.url.endswith('/v1') else f"{self.url}/v1"

    def _anthropic_headers(self) -> dict:
        headers = {
            'anthropic-version': str(self.config.get('anthropic_version', '2023-06-01')),
        }
        if self.api_key:
            headers['x-api-key'] = self.api_key
        return headers

    def _gemini_base_url(self) -> str:
        return self.url or 'https://generativelanguage.googleapis.com/v1beta'

    def _gemini_headers(self) -> dict:
        headers = {}
        if self.api_key:
            headers['x-goog-api-key'] = self.api_key
        return headers

    def _max_output_tokens(self, default: int = 1024) -> int:
        return max(1, _nonnegative_int(self.config.get('max_tokens', default)) or default)

    @staticmethod
    def _image_payload(image_path: str) -> tuple[str, str]:
        with open(image_path, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode()
        ext = os.path.splitext(image_path)[1].lower().lstrip('.')
        mime = {
            'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
            'gif': 'image/gif', 'webp': 'image/webp',
        }.get(ext, 'image/jpeg')
        return img_b64, mime

    def classify(self, prompt: str, model: str | None = None,
                 system: str = '', format: dict | None = None) -> str:
        """Send a text classification prompt and return the response.

        When *format* is a JSON Schema dict, providers that support
        structured output will constrain the model to return valid JSON
        matching the schema.
        """
        model = model or self.config.get('model', '')
        if self.type == 'ollama':
            return self._ollama_generate(prompt, model, system=system,
                                         format=format)
        elif self.type == 'anthropic':
            return self._anthropic_messages(prompt, model, system=system,
                                            format=format)
        elif self.type == 'gemini':
            return self._gemini_generate_content(prompt, model, system=system,
                                                 format=format)
        else:
            return self._openai_chat(prompt, model, system=system,
                                     format=format)

    def classify_with_vision(self, prompt: str, image_path: str,
                             model: str | None = None) -> str:
        """Send a vision classification prompt with an image."""
        model = model or self.config.get('vision_model', '')
        if self.type == 'ollama':
            return self._ollama_vision(prompt, image_path, model)
        elif self.type == 'anthropic':
            return self._anthropic_vision(prompt, image_path, model)
        elif self.type == 'gemini':
            return self._gemini_vision(prompt, image_path, model)
        else:
            return self._openai_vision(prompt, image_path, model)

    def is_available(self) -> bool:
        """Check if the provider is reachable."""
        started = time.perf_counter()
        try:
            if self.type == 'ollama':
                url = f"{self.url}/api/tags"
                headers = {}
            elif self.type == 'anthropic':
                url = f"{self._anthropic_base_url()}/models"
                headers = self._anthropic_headers()
            elif self.type == 'gemini':
                url = f"{self._gemini_base_url()}/models"
                headers = self._gemini_headers()
            else:
                url = f"{self.url}/models"
                headers = self._openai_headers()
            response = ai_request(url, method='GET', data=None, headers=headers,
                                  timeout=5, retries=0)
            self._record_request(started, success=True, response=response,
                                 operation='availability')
            return True
        except Exception as exc:
            self._record_request(started, success=False, error=exc,
                                 operation='availability')
            return False

    @property
    def cost_stats(self) -> dict:
        return dict(self._cost_tracker)

    def _anthropic_messages(self, prompt: str, model: str, system: str = '',
                            format: dict | None = None) -> str:
        """Call Anthropic's native Messages API without an SDK dependency."""
        started = time.perf_counter()
        system_text = (system or '').strip()
        if format is not None:
            schema_hint = (
                "Return only valid JSON matching this schema; do not include markdown fences:\n"
                f"{json.dumps(format, separators=(',', ':'))}"
            )
            system_text = f"{system_text}\n\n{schema_hint}".strip()
        payload = {
            'model': model,
            'max_tokens': self._max_output_tokens(),
            'messages': [{'role': 'user', 'content': prompt}],
        }
        if system_text:
            payload['system'] = system_text
        try:
            data = ai_request(
                f"{self._anthropic_base_url()}/messages",
                data=json.dumps(payload).encode(),
                headers=self._anthropic_headers(),
                timeout=self.timeout,
            )
            self._record_request(started, success=True, response=data, operation='text')
            content = data.get('content', [])
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                return ''.join(
                    str(block.get('text', ''))
                    for block in content
                    if isinstance(block, dict) and block.get('type') == 'text'
                ).strip()
            return ''
        except Exception as exc:
            self._record_request(started, success=False, error=exc, operation='text')
            raise

    def _anthropic_vision(self, prompt: str, image_path: str, model: str) -> str:
        """Call Anthropic Messages with an inline base64 image block."""
        started = time.perf_counter()
        try:
            image_data, mime = self._image_payload(image_path)
            payload = {
                'model': model,
                'max_tokens': self._max_output_tokens(1024),
                'messages': [{
                    'role': 'user',
                    'content': [
                        {
                            'type': 'image',
                            'source': {
                                'type': 'base64',
                                'media_type': mime,
                                'data': image_data,
                            },
                        },
                        {'type': 'text', 'text': prompt},
                    ],
                }],
            }
            data = ai_request(
                f"{self._anthropic_base_url()}/messages",
                data=json.dumps(payload).encode(),
                headers=self._anthropic_headers(),
                timeout=self.timeout * 2,
            )
            self._record_request(started, success=True, response=data, operation='vision')
            content = data.get('content', [])
            return ''.join(
                str(block.get('text', ''))
                for block in content
                if isinstance(block, dict) and block.get('type') == 'text'
            ).strip()
        except Exception as exc:
            self._record_request(started, success=False, error=exc, operation='vision')
            raise

    def _gemini_generate_content(self, prompt: str, model: str, system: str = '',
                                 format: dict | None = None) -> str:
        """Call Gemini's REST generateContent endpoint."""
        started = time.perf_counter()
        generation_config = {
            'temperature': 0.3,
            'maxOutputTokens': self._max_output_tokens(),
        }
        if format is not None:
            generation_config['responseMimeType'] = 'application/json'
            generation_config['responseSchema'] = format
        payload = {
            'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
            'generationConfig': generation_config,
        }
        if system:
            payload['systemInstruction'] = {'parts': [{'text': system}]}
        try:
            data = ai_request(
                f"{self._gemini_base_url()}/models/{_url_quote(model, safe=':@-._')}:generateContent",
                data=json.dumps(payload).encode(),
                headers=self._gemini_headers(),
                timeout=self.timeout,
            )
            self._record_request(started, success=True, response=data, operation='text')
            candidates = data.get('candidates', [])
            if not candidates:
                return ''
            parts = candidates[0].get('content', {}).get('parts', [])
            return ''.join(
                str(part.get('text', ''))
                for part in parts
                if isinstance(part, dict) and part.get('text') is not None
            ).strip()
        except Exception as exc:
            self._record_request(started, success=False, error=exc, operation='text')
            raise

    def _gemini_vision(self, prompt: str, image_path: str, model: str) -> str:
        """Call Gemini generateContent with an inline image part."""
        started = time.perf_counter()
        try:
            image_data, mime = self._image_payload(image_path)
            payload = {
                'contents': [{
                    'role': 'user',
                    'parts': [
                        {'inline_data': {'mime_type': mime, 'data': image_data}},
                        {'text': prompt},
                    ],
                }],
                'generationConfig': {
                    'temperature': 0.3,
                    'maxOutputTokens': self._max_output_tokens(1024),
                },
            }
            data = ai_request(
                f"{self._gemini_base_url()}/models/{_url_quote(model, safe=':@-._')}:generateContent",
                data=json.dumps(payload).encode(),
                headers=self._gemini_headers(),
                timeout=self.timeout * 2,
            )
            self._record_request(started, success=True, response=data, operation='vision')
            candidates = data.get('candidates', [])
            if not candidates:
                return ''
            parts = candidates[0].get('content', {}).get('parts', [])
            return ''.join(
                str(part.get('text', ''))
                for part in parts
                if isinstance(part, dict) and part.get('text') is not None
            ).strip()
        except Exception as exc:
            self._record_request(started, success=False, error=exc, operation='vision')
            raise

    def _ollama_generate(self, prompt: str, model: str, system: str = '',
                         format: dict | None = None) -> str:
        """Call Ollama's /api/generate endpoint."""
        started = time.perf_counter()
        payload = {
            'model': model,
            'prompt': prompt,
            'system': system,
            'stream': False,
            'options': {'temperature': 0.3, 'num_predict': 200},
        }
        if format is not None:
            payload['format'] = format
        try:
            data = ai_request(f"{self.url}/api/generate",
                              data=json.dumps(payload).encode(),
                              timeout=self.timeout)
            self._record_request(started, success=True, response=data, operation='text')
            return data.get('response', '').strip()
        except Exception as exc:
            self._record_request(started, success=False, error=exc, operation='text')
            raise

    def _ollama_vision(self, prompt: str, image_path: str, model: str) -> str:
        """Call Ollama with vision model (image as base64)."""
        started = time.perf_counter()
        try:
            with open(image_path, 'rb') as f:
                img_b64 = base64.b64encode(f.read()).decode()
            payload = {
                'model': model,
                'prompt': prompt,
                'images': [img_b64],
                'stream': False,
                'options': {'temperature': 0.3, 'num_predict': 300},
            }
            data = ai_request(f"{self.url}/api/generate",
                              data=json.dumps(payload).encode(),
                              timeout=self.timeout * 2)
            self._record_request(started, success=True, response=data, operation='vision')
            return data.get('response', '').strip()
        except Exception as exc:
            self._record_request(started, success=False, error=exc, operation='vision')
            raise

    def _openai_chat(self, prompt: str, model: str, system: str = '',
                     format: dict | None = None) -> str:
        """Call OpenAI-compatible /chat/completions endpoint."""
        started = time.perf_counter()
        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': prompt})
        payload = {
            'model': model,
            'messages': messages,
            'temperature': 0.3,
            'max_tokens': 200,
        }
        if format is not None:
            payload['response_format'] = {
                'type': 'json_schema',
                'json_schema': {'name': 'response', 'schema': format},
            }
        headers = {}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        try:
            data = ai_request(f"{self.url}/chat/completions",
                              data=json.dumps(payload).encode(),
                              headers=headers, timeout=self.timeout)
            self._record_request(started, success=True, response=data, operation='text')
            choices = data.get('choices', [])
            if choices:
                return choices[0].get('message', {}).get('content', '').strip()
            return ''
        except Exception as exc:
            self._record_request(started, success=False, error=exc, operation='text')
            raise

    def _openai_vision(self, prompt: str, image_path: str, model: str) -> str:
        """Call OpenAI-compatible vision endpoint."""
        started = time.perf_counter()
        try:
            with open(image_path, 'rb') as f:
                img_b64 = base64.b64encode(f.read()).decode()
            ext = os.path.splitext(image_path)[1].lower().lstrip('.')
            mime = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'png': 'png',
                    'gif': 'gif', 'webp': 'webp'}.get(ext, 'jpeg')
            payload = {
                'model': model,
                'messages': [{
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': prompt},
                        {'type': 'image_url', 'image_url': {
                            'url': f'data:image/{mime};base64,{img_b64}'
                        }},
                    ],
                }],
                'temperature': 0.3,
                'max_tokens': 300,
            }
            headers = {}
            if self.api_key:
                headers['Authorization'] = f'Bearer {self.api_key}'
            data = ai_request(f"{self.url}/chat/completions",
                              data=json.dumps(payload).encode(),
                              headers=headers, timeout=self.timeout * 2)
            self._record_request(started, success=True, response=data, operation='vision')
            choices = data.get('choices', [])
            if choices:
                return choices[0].get('message', {}).get('content', '').strip()
            return ''
        except Exception as exc:
            self._record_request(started, success=False, error=exc, operation='vision')
            raise


class ProviderChain:
    """Tries providers in priority order, falling back on failure."""

    def __init__(self, providers: dict | None = None):
        self._providers = providers or load_providers()
        self._instances: dict[str, AIProvider] = {}

    def _get_instance(self, key: str) -> AIProvider | None:
        if key not in self._instances:
            cfg = self._providers.get(key)
            if cfg and cfg.get('enabled'):
                self._instances[key] = AIProvider(cfg, provider_id=key)
        return self._instances.get(key)

    def _ordered_providers(self, task: str = "text") -> list[tuple[str, AIProvider]]:
        """Return enabled providers sorted by priority."""
        items = []
        for key, cfg in self._providers.items():
            if not cfg.get('enabled'):
                continue
            if task == 'vision' and not cfg.get('vision_model'):
                continue
            inst = self._get_instance(key)
            if inst:
                items.append((cfg.get('priority', 99), key, inst))
        items.sort(key=lambda x: x[0])
        return [(k, p) for _, k, p in items]

    def classify(self, prompt: str, system: str = '',
                 format: dict | None = None) -> tuple[str, str]:
        """Classify using the first available provider.

        Returns:
            (response_text, provider_key) or ("", "") on total failure.
        """
        for key, provider in self._ordered_providers("text"):
            try:
                result = provider.classify(prompt, system=system, format=format)
                if result:
                    return result, key
            except Exception:
                continue
        return "", ""

    def classify_with_vision(self, prompt: str,
                             image_path: str) -> tuple[str, str]:
        """Vision classify using the first available provider with vision support."""
        for key, provider in self._ordered_providers("vision"):
            try:
                result = provider.classify_with_vision(prompt, image_path)
                if result:
                    return result, key
            except Exception:
                continue
        return "", ""

    def check_availability(self) -> dict[str, bool]:
        """Check which providers are reachable."""
        results = {}
        for key, cfg in self._providers.items():
            if not cfg.get('enabled'):
                results[key] = False
                continue
            inst = self._get_instance(key)
            results[key] = inst.is_available() if inst else False
        return results

    def get_cost_summary(self) -> dict:
        """Aggregate cost tracking across all providers."""
        totals = {'requests': 0, 'errors': 0, 'input_tokens': 0,
                  'output_tokens': 0, 'latency_ms_total': 0.0}
        for inst in self._instances.values():
            for k, v in inst.cost_stats.items():
                totals[k] = totals.get(k, 0) + v
        return totals


# ── Provider-chain folder classifier ──────────────────────────────────────────

def classify_folder_via_chain(folder_name: str, folder_path: str | None,
                              log_cb=None) -> dict:
    """Classify a folder using the configured ProviderChain (paid/remote AI).

    Replicates the same context-building, prompt, and JSON-parsing logic as
    ``ollama_classify_folder`` but routes through ProviderChain instead of
    calling the Ollama API directly.

    Returns the same dict shape as ``ollama_classify_folder``:
      {name, category, confidence, method, detail}
    or an empty dict on failure.
    """
    import json as _json
    import os as _os

    from unifile.categories import get_all_category_names
    from unifile.ollama import (
        _build_llm_system_prompt,
        _extract_name_hints,
        _is_generic_name,
        _is_id_only_folder,
        _llm_cache_get,
        _llm_cache_set,
    )

    def _log(msg: str):
        if log_cb:
            try:
                log_cb(msg)
            except Exception:
                pass

    # ── Cache check ────────────────────────────────────────────────────────────
    cached = _llm_cache_get(folder_name)
    if cached:
        return cached

    result = {'name': None, 'category': None, 'confidence': 0,
              'method': 'llm_provider', 'detail': ''}

    # ── Build context lines ────────────────────────────────────────────────────
    context_lines = [f'Folder name: "{folder_name}"']

    # ID-only enrichment
    if folder_path and _os.path.isdir(folder_path) and _is_id_only_folder(folder_name):
        hints = _extract_name_hints(folder_path)
        if hints:
            context_lines.append('')
            context_lines.append(
                '\u26a0 FOLDER NAME IS ID-ONLY \u2014 use the project file name below instead:'
            )
            for name, source, priority in hints[:5]:
                context_lines.append(f'  \u2605 {name}  [from {source}, score {priority}]')
            context_lines.append('Use the project file name as the cleaned \'name\' field.')

    if folder_path and _os.path.isdir(folder_path):
        files, subdirs = [], []
        try:
            for entry in _os.scandir(folder_path):
                if entry.is_file():
                    files.append(entry.name)
                elif entry.is_dir():
                    subdirs.append(entry.name)
        except OSError:
            pass
        if files:
            shown = files[:20]
            context_lines.append(f'Files ({len(files)} total): {", ".join(shown)}'
                                  + (' …' if len(files) > 20 else ''))
        if subdirs:
            shown = subdirs[:10]
            context_lines.append(f'Subfolders ({len(subdirs)} total): {", ".join(shown)}'
                                  + (' …' if len(subdirs) > 10 else ''))

    # Generic-name enrichment: scan parent for sibling context
    if _is_generic_name(folder_name) and folder_path:
        parent = _os.path.dirname(folder_path)
        if parent and _os.path.isdir(parent):
            try:
                siblings = [e.name for e in _os.scandir(parent)
                            if e.is_dir() and e.name != folder_name][:8]
                if siblings:
                    context_lines.append(
                        f'Sibling folders (for context): {", ".join(siblings)}'
                    )
            except OSError:
                pass

    user_prompt = '\n'.join(context_lines)

    # ── Build system prompt and call chain ─────────────────────────────────────
    system_prompt = _build_llm_system_prompt(get_all_category_names())

    chain = ProviderChain()
    try:
        raw, provider_key = chain.classify(user_prompt, system=system_prompt)
    except Exception as exc:
        _log(f'Provider chain error: {exc}')
        return {}

    if not raw:
        _log('Provider chain returned empty response')
        return {}

    # ── Parse JSON response ────────────────────────────────────────────────────
    try:
        # Strip markdown fences if present
        text = raw.strip()
        if text.startswith('```'):
            text = '\n'.join(text.split('\n')[1:])
            if text.endswith('```'):
                text = text[:-3].strip()
        data = _json.loads(text)
    except _json.JSONDecodeError:
        # Try extracting a JSON block from mixed output
        import re as _re
        m = _re.search(r'\{[^{}]+\}', raw, _re.DOTALL)
        if m:
            try:
                data = _json.loads(m.group())
            except _json.JSONDecodeError:
                _log(f'Could not parse provider response: {raw[:120]}')
                return {}
        else:
            _log(f'No JSON in provider response: {raw[:120]}')
            return {}

    # ── Validate category ──────────────────────────────────────────────────────
    categories = get_all_category_names()
    category = data.get('category', '').strip()
    if category not in categories:
        _log(f'Provider returned unknown category "{category}" for "{folder_name}"')
        return {}

    name = data.get('name', folder_name).strip() or folder_name
    confidence = float(data.get('confidence', 0))
    result.update({
        'name': name,
        'category': category,
        'confidence': confidence,
        'method': 'llm_provider',
        'detail': f'provider:{provider_key}\u2192{category}',
    })

    _llm_cache_set(folder_name, result)
    return result
