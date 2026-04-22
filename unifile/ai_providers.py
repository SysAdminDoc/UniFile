"""UniFile -- Multi-provider AI backend (Ollama, OpenAI-compatible, Groq)."""
import os
import json
import time
import base64
from datetime import datetime

from unifile.config import _APP_DATA_DIR

_PROVIDERS_FILE = os.path.join(_APP_DATA_DIR, 'ai_providers.json')

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
    },
}


def load_providers() -> dict:
    """Load provider configurations from disk."""
    providers = dict(_DEFAULT_PROVIDERS)
    if os.path.isfile(_PROVIDERS_FILE):
        try:
            with open(_PROVIDERS_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            for key, val in saved.items():
                if key in providers:
                    providers[key].update(val)
                else:
                    providers[key] = val
        except (json.JSONDecodeError, OSError):
            pass
    return providers


def save_providers(providers: dict):
    """Save provider configurations to disk."""
    try:
        with open(_PROVIDERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(providers, f, indent=2)
    except OSError:
        pass


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

    def __init__(self, config: dict):
        self.config = config
        self.type = config.get('type', 'ollama')
        self.url = config.get('url', '').rstrip('/')
        self.api_key = config.get('api_key', '')
        self.timeout = config.get('timeout', 30)
        self._cost_tracker = {'requests': 0, 'input_tokens': 0, 'output_tokens': 0}

    def classify(self, prompt: str, model: str | None = None,
                 system: str = '') -> str:
        """Send a text classification prompt and return the response."""
        model = model or self.config.get('model', '')
        if self.type == 'ollama':
            return self._ollama_generate(prompt, model, system=system)
        else:
            return self._openai_chat(prompt, model, system=system)

    def classify_with_vision(self, prompt: str, image_path: str,
                             model: str | None = None) -> str:
        """Send a vision classification prompt with an image."""
        model = model or self.config.get('vision_model', '')
        if self.type == 'ollama':
            return self._ollama_vision(prompt, image_path, model)
        else:
            return self._openai_vision(prompt, image_path, model)

    def is_available(self) -> bool:
        """Check if the provider is reachable."""
        import urllib.request
        try:
            if self.type == 'ollama':
                url = f"{self.url}/api/tags"
            else:
                url = f"{self.url}/models"
            req = urllib.request.Request(url, method='GET')
            if self.api_key:
                req.add_header('Authorization', f'Bearer {self.api_key}')
            urllib.request.urlopen(req, timeout=5)
            return True
        except Exception:
            return False

    @property
    def cost_stats(self) -> dict:
        return dict(self._cost_tracker)

    def _ollama_generate(self, prompt: str, model: str, system: str = '') -> str:
        """Call Ollama's /api/generate endpoint."""
        import urllib.request
        body = json.dumps({
            'model': model,
            'prompt': prompt,
            'system': system,
            'stream': False,
            'options': {'temperature': 0.3, 'num_predict': 200},
        }).encode()
        req = urllib.request.Request(
            f"{self.url}/api/generate",
            data=body,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read())
        self._cost_tracker['requests'] += 1
        return data.get('response', '').strip()

    def _ollama_vision(self, prompt: str, image_path: str, model: str) -> str:
        """Call Ollama with vision model (image as base64)."""
        import urllib.request
        with open(image_path, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode()
        body = json.dumps({
            'model': model,
            'prompt': prompt,
            'images': [img_b64],
            'stream': False,
            'options': {'temperature': 0.3, 'num_predict': 300},
        }).encode()
        req = urllib.request.Request(
            f"{self.url}/api/generate",
            data=body,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=self.timeout * 2) as resp:
            data = json.loads(resp.read())
        self._cost_tracker['requests'] += 1
        return data.get('response', '').strip()

    def _openai_chat(self, prompt: str, model: str, system: str = '') -> str:
        """Call OpenAI-compatible /chat/completions endpoint."""
        import urllib.request
        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': prompt})
        body = json.dumps({
            'model': model,
            'messages': messages,
            'temperature': 0.3,
            'max_tokens': 200,
        }).encode()
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        req = urllib.request.Request(
            f"{self.url}/chat/completions",
            data=body,
            headers=headers,
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read())
        self._cost_tracker['requests'] += 1
        usage = data.get('usage', {})
        self._cost_tracker['input_tokens'] += usage.get('prompt_tokens', 0)
        self._cost_tracker['output_tokens'] += usage.get('completion_tokens', 0)
        choices = data.get('choices', [])
        if choices:
            return choices[0].get('message', {}).get('content', '').strip()
        return ''

    def _openai_vision(self, prompt: str, image_path: str, model: str) -> str:
        """Call OpenAI-compatible vision endpoint."""
        import urllib.request
        with open(image_path, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode()
        ext = os.path.splitext(image_path)[1].lower().lstrip('.')
        mime = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'png': 'png',
                'gif': 'gif', 'webp': 'webp'}.get(ext, 'jpeg')
        body = json.dumps({
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
        }).encode()
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        req = urllib.request.Request(
            f"{self.url}/chat/completions",
            data=body,
            headers=headers,
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=self.timeout * 2) as resp:
            data = json.loads(resp.read())
        self._cost_tracker['requests'] += 1
        choices = data.get('choices', [])
        if choices:
            return choices[0].get('message', {}).get('content', '').strip()
        return ''


class ProviderChain:
    """Tries providers in priority order, falling back on failure."""

    def __init__(self, providers: dict | None = None):
        self._providers = providers or load_providers()
        self._instances: dict[str, AIProvider] = {}

    def _get_instance(self, key: str) -> AIProvider | None:
        if key not in self._instances:
            cfg = self._providers.get(key)
            if cfg and cfg.get('enabled'):
                self._instances[key] = AIProvider(cfg)
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

    def classify(self, prompt: str, system: str = '') -> tuple[str, str]:
        """Classify using the first available provider.

        Returns:
            (response_text, provider_key) or ("", "") on total failure.
        """
        for key, provider in self._ordered_providers("text"):
            try:
                result = provider.classify(prompt, system=system)
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
        totals = {'requests': 0, 'input_tokens': 0, 'output_tokens': 0}
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
    from unifile.ollama import (
        _build_llm_system_prompt,
        _is_id_only_folder,
        _extract_name_hints,
        _is_generic_name,
        _llm_cache_get,
        _llm_cache_set,
    )
    from unifile.categories import get_all_category_names

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

