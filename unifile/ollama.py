"""UniFile — Ollama LLM integration, model catalog, and AI classification."""
import os, re, json, subprocess, sys, time, math, base64, io
from pathlib import Path

from unifile.bootstrap import HAS_PILLOW, HAS_MAGIC
try:
    from PIL import Image as _PILImage
except ImportError:
    pass
try:
    import magic as _magic
except ImportError:
    pass

from unifile.config import _APP_DATA_DIR
from unifile.categories import get_all_categories, get_all_category_names, CATEGORIES
from unifile.bootstrap import HAS_RAPIDFUZZ
try:
    from rapidfuzz import fuzz as _rfuzz
except ImportError:
    _rfuzz = None
from unifile.naming import (
    _is_id_only_folder, _extract_name_hints, _smart_name,
    _is_generic_name, _normalize, _beautify_name, _ASSET_FOLDER_NAMES
)

_OLLAMA_SETTINGS_FILE = os.path.join(_APP_DATA_DIR, 'ollama_settings.json')

_OLLAMA_DEFAULTS = {
    'url': 'http://localhost:11434',
    'model': 'qwen3.5:9b',
    'enabled': True,
    'timeout': 120,
    'temperature': 0.1,
    'num_predict': 4096,
    'think': False,
    'batch_size': 3,
    'vision_enabled': True,
    'vision_max_file_mb': 20,
    'vision_max_pixels': 1024,
    'content_extraction': True,
    'content_max_chars': 800,
    'convert_heic_to_jpg': True,
    'convert_webp_to_jpg': True,
}

def _normalize_ollama_url(url: str) -> str:
    """Strip trailing slashes — all API paths assume no trailing slash on the base URL."""
    if not url:
        return 'http://localhost:11434'
    return url.rstrip('/').strip() or 'http://localhost:11434'


def load_ollama_settings() -> dict:
    try:
        with open(_OLLAMA_SETTINGS_FILE, 'r') as f:
            s = json.load(f)
        merged = {**_OLLAMA_DEFAULTS, **s}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        merged = dict(_OLLAMA_DEFAULTS)
    merged['url'] = _normalize_ollama_url(merged.get('url', ''))
    return merged

def save_ollama_settings(settings: dict):
    try:
        with open(_OLLAMA_SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass

_MODEL_CATALOG = [
    # ── Qwen3.5 (latest, recommended) ─────────────────────────────────────────
    {
        'group': 'Qwen3.5 (Recommended)',
        'name': 'qwen3.5:9b',
        'label': 'Qwen3.5 9B  ·  Best balance  ·  ~6.6 GB',
        'description': 'Best accuracy/speed balance. Default choice for most GPUs.',
        'temperature': 0.1, 'num_predict': 4096, 'think': False, 'batch_size': 3,
    },
    {
        'group': 'Qwen3.5 (Recommended)',
        'name': 'qwen3.5:4b',
        'label': 'Qwen3.5 4B  ·  Fastest  ·  ~3.4 GB',
        'description': 'Best for large libraries (5000+ folders). Slightly less accurate.',
        'temperature': 0.1, 'num_predict': 4096, 'think': False, 'batch_size': 5,
    },
    {
        'group': 'Qwen3.5 (Recommended)',
        'name': 'qwen3.5:27b',
        'label': 'Qwen3.5 27B  ·  High accuracy  ·  ~17 GB',
        'description': 'Higher accuracy on ambiguous names. Requires 20GB+ VRAM.',
        'temperature': 0.1, 'num_predict': 4096, 'think': False, 'batch_size': 2,
    },
    {
        'group': 'Qwen3.5 (Recommended)',
        'name': 'qwen3.5:35b',
        'label': 'Qwen3.5 35B  ·  Max local quality  ·  ~24 GB',
        'description': 'Best local model. Requires 24GB VRAM (RTX 3090/4090).',
        'temperature': 0.1, 'num_predict': 4096, 'think': False, 'batch_size': 1,
    },
    # ── Qwen3 ─────────────────────────────────────────────────────────────────
    {
        'group': 'Qwen3',
        'name': 'qwen3:8b',
        'label': 'Qwen3 8B  ·  Solid  ·  ~5.2 GB',
        'description': 'Previous Qwen generation. Good JSON reliability.',
        'temperature': 0.1, 'num_predict': 4096, 'think': False, 'batch_size': 3,
    },
    {
        'group': 'Qwen3',
        'name': 'qwen3:14b',
        'label': 'Qwen3 14B  ·  Strong  ·  ~9.3 GB',
        'description': 'Strong instruction following for large category lists.',
        'temperature': 0.1, 'num_predict': 4096, 'think': False, 'batch_size': 2,
    },
    {
        'group': 'Qwen3',
        'name': 'qwen3:30b',
        'label': 'Qwen3 30B MoE  ·  Efficient large  ·  ~19 GB',
        'description': 'MoE architecture — fast for its size. Good accuracy.',
        'temperature': 0.1, 'num_predict': 4096, 'think': False, 'batch_size': 1,
    },
    # ── Gemma3 ────────────────────────────────────────────────────────────────
    {
        'group': 'Gemma3',
        'name': 'gemma3:27b',
        'label': 'Gemma3 27B  ·  High accuracy  ·  ~17 GB  [VISION]',
        'description': 'Top-tier accuracy with vision support. Requires 20GB+ VRAM.',
        'temperature': 0.1, 'num_predict': 4096, 'think': False, 'batch_size': 1, 'vision': True,
    },
    # ── Mistral ───────────────────────────────────────────────────────────────
    {
        'group': 'Mistral',
        'name': 'mistral:7b',
        'label': 'Mistral 7B  ·  Fast & reliable  ·  ~4.1 GB',
        'description': 'Strong reasoning. Consistent JSON output.',
        'temperature': 0.1, 'num_predict': 2048, 'think': False, 'batch_size': 3,
    },
    {
        'group': 'Mistral',
        'name': 'mistral-nemo:12b',
        'label': 'Mistral Nemo 12B  ·  Multilingual  ·  ~7 GB',
        'description': 'Best for libraries with non-Latin filenames (CJK, Cyrillic, Arabic).',
        'temperature': 0.1, 'num_predict': 2048, 'think': False, 'batch_size': 3,
    },
    # ── Llama3 ────────────────────────────────────────────────────────────────
    {
        'group': 'Llama3',
        'name': 'llama3.2:3b',
        'label': 'Llama3.2 3B  ·  Ultra-fast  ·  ~2 GB',
        'description': 'Fastest option. Good for quick passes on well-named folders.',
        'temperature': 0.1, 'num_predict': 2048, 'think': False, 'batch_size': 5,
    },
    {
        'group': 'Llama3',
        'name': 'llama3.1:8b',
        'label': 'Llama3.1 8B  ·  Balanced  ·  ~4.7 GB',
        'description': 'Solid all-rounder with good category accuracy.',
        'temperature': 0.1, 'num_predict': 2048, 'think': False, 'batch_size': 3,
    },
    {
        'group': 'Llama3',
        'name': 'llama3.3:70b',
        'label': 'Llama3.3 70B  ·  Max accuracy  ·  ~40 GB',
        'description': 'Highest accuracy available locally. Multi-GPU or high-RAM required.',
        'temperature': 0.1, 'num_predict': 4096, 'think': False, 'batch_size': 1,
    },
    # ── Phi4 ──────────────────────────────────────────────────────────────────
    {
        'group': 'Phi4',
        'name': 'phi4-mini:3.8b',
        'label': 'Phi4 Mini 3.8B  ·  Efficient  ·  ~2.5 GB',
        'description': 'Microsoft model. Surprisingly accurate for its size. Clean JSON.',
        'temperature': 0.1, 'num_predict': 2048, 'think': False, 'batch_size': 5,
    },
    {
        'group': 'Phi4',
        'name': 'phi4:14b',
        'label': 'Phi4 14B  ·  Strong reasoning  ·  ~8.5 GB',
        'description': 'Excellent at understanding what noise to strip vs preserve.',
        'temperature': 0.1, 'num_predict': 4096, 'think': False, 'batch_size': 2,
    },
    # ── DeepSeek ──────────────────────────────────────────────────────────────
    {
        'group': 'DeepSeek',
        'name': 'deepseek-r1:8b',
        'label': 'DeepSeek R1 8B  ·  Reasoning  ·  ~4.9 GB',
        'description': 'Reasoning model — slower but very precise classification.',
        'temperature': 0.1, 'num_predict': 2048, 'think': False, 'batch_size': 1,
    },
    {
        'group': 'DeepSeek',
        'name': 'deepseek-v3:7b',
        'label': 'DeepSeek V3 7B  ·  Fast inference  ·  ~4.4 GB',
        'description': 'Efficient MoE model. Strong at following structured output rules.',
        'temperature': 0.1, 'num_predict': 2048, 'think': False, 'batch_size': 3,
    },
    # ── Vision Models (image understanding) ────────────────────────────────
    {
        'group': 'Vision Models (Recommended)',
        'name': 'qwen2.5vl:7b',
        'label': 'Qwen2.5-VL 7B  ·  Best vision  ·  ~5.5 GB  [VISION]',
        'description': 'Top accuracy across OCR, captioning, landmark & image classification. Default vision model.',
        'temperature': 0.1, 'num_predict': 4096, 'think': False, 'batch_size': 1, 'vision': True,
    },
    {
        'group': 'Vision Models (Recommended)',
        'name': 'qwen2.5vl:3b',
        'label': 'Qwen2.5-VL 3B  ·  Fast vision  ·  ~2.4 GB  [VISION]',
        'description': 'Lightweight Qwen vision. Great speed/accuracy tradeoff for quick scans.',
        'temperature': 0.1, 'num_predict': 4096, 'think': False, 'batch_size': 1, 'vision': True,
    },
    {
        'group': 'Vision Models (Recommended)',
        'name': 'gemma3:4b',
        'label': 'Gemma3 4B  ·  Fast multimodal  ·  ~3.3 GB  [VISION]',
        'description': 'Google multimodal model. Fast text+image combo, strong on common formats.',
        'temperature': 0.1, 'num_predict': 4096, 'think': False, 'batch_size': 1, 'vision': True,
    },
    {
        'group': 'Vision Models (Recommended)',
        'name': 'gemma3:12b',
        'label': 'Gemma3 12B  ·  Strong multimodal  ·  ~8.1 GB  [VISION]',
        'description': 'Larger Gemma with excellent vision accuracy and reliable JSON output.',
        'temperature': 0.1, 'num_predict': 4096, 'think': False, 'batch_size': 1, 'vision': True,
    },
    {
        'group': 'Vision Models',
        'name': 'minicpm-v:8b',
        'label': 'MiniCPM-V 8B  ·  OCR specialist  ·  ~5.5 GB  [VISION]',
        'description': 'Best-in-class OCR, surpasses GPT-4o on OCRBench. Great for documents and memes.',
        'temperature': 0.1, 'num_predict': 4096, 'think': False, 'batch_size': 1, 'vision': True,
    },
    {
        'group': 'Vision Models',
        'name': 'llama3.2-vision:11b',
        'label': 'Llama3.2 Vision 11B  ·  Strong vision  ·  ~7.9 GB  [VISION]',
        'description': 'Meta multimodal model. Strong image classification and OCR.',
        'temperature': 0.1, 'num_predict': 4096, 'think': False, 'batch_size': 1, 'vision': True,
    },
    {
        'group': 'Vision Models',
        'name': 'llava:7b',
        'label': 'LLaVA 7B  ·  Solid vision  ·  ~4.7 GB  [VISION]',
        'description': 'Visual instruction tuning model. Good image descriptions and OCR.',
        'temperature': 0.1, 'num_predict': 4096, 'think': False, 'batch_size': 1, 'vision': True,
    },
    {
        'group': 'Vision Models',
        'name': 'llava:13b',
        'label': 'LLaVA 13B  ·  Better detail  ·  ~8.0 GB  [VISION]',
        'description': 'Larger LLaVA model. More detailed descriptions, better at reading small text.',
        'temperature': 0.1, 'num_predict': 4096, 'think': False, 'batch_size': 1, 'vision': True,
    },
    {
        'group': 'Vision Models',
        'name': 'bakllava:7b',
        'label': 'BakLLaVA 7B  ·  Mistral vision  ·  ~4.7 GB  [VISION]',
        'description': 'Mistral-based LLaVA variant. Efficient vision with strong Mistral backbone.',
        'temperature': 0.1, 'num_predict': 4096, 'think': False, 'batch_size': 1, 'vision': True,
    },
    {
        'group': 'Vision Models',
        'name': 'moondream:1.8b',
        'label': 'Moondream 1.8B  ·  Lightweight  ·  ~1.7 GB  [VISION]',
        'description': 'Tiny but capable vision model. Fast inference on low-end hardware.',
        'temperature': 0.1, 'num_predict': 2048, 'think': False, 'batch_size': 1, 'vision': True,
    },
]

# Fast lookup: model name → catalog entry
_MODEL_CATALOG_MAP = {m['name']: m for m in _MODEL_CATALOG}



# ── ModelRouter: centralized model selector for multi-model routing ──────────
_EVIDENCE_CONFIDENCE_THRESHOLD = 65

class ModelRouter:
    """Picks the best installed model for each task type, with caching."""
    _cache = None          # list of installed model names
    _cache_ts = 0          # timestamp of last cache refresh
    _CACHE_TTL = 60        # seconds

    _TASK_PREFS = {
        'text_classify':  ['qwen3.5:4b', 'qwen3:8b', 'llama3.2:3b'],
        'vision_classify': ['moondream:1.8b', 'llava:7b', 'minicpm-v:8b', 'llama3.2-vision:11b'],
        'ocr_heavy':      ['minicpm-v:8b', 'llava:13b', 'llava:7b'],
        'deep_reasoning': ['qwen3.5:9b', 'qwen3:14b', 'gemma3:12b'],
    }

    @classmethod
    def _installed(cls, url: str = None) -> list:
        now = time.time()
        if cls._cache is not None and (now - cls._cache_ts) < cls._CACHE_TTL:
            return cls._cache
        cls._cache = _ollama_list_models(url)
        cls._cache_ts = now
        return cls._cache

    @classmethod
    def invalidate_cache(cls):
        cls._cache = None
        cls._cache_ts = 0

    @classmethod
    def get_model(cls, task: str, url: str = None, log_cb=None, auto_pull: bool = True) -> str:
        """Return the best available model for the given task.
        Prepends the user's selected model for text/reasoning tasks.
        Auto-pulls first preference if nothing installed for that task."""
        prefs = list(cls._TASK_PREFS.get(task, []))
        # For text/reasoning tasks, user's selected model goes first
        if task in ('text_classify', 'deep_reasoning'):
            user_model = load_ollama_settings().get('model', '')
            if user_model and user_model not in prefs:
                prefs.insert(0, user_model)

        installed = cls._installed(url)
        # Find first installed model matching preference list
        for m in prefs:
            if m in installed or any(im.startswith(m.split(':')[0] + ':') for im in installed if ':' in m):
                # Exact match or base-name match
                if m in installed:
                    return m
                # Base name match — return the installed variant
                base = m.split(':')[0]
                for im in installed:
                    if im.startswith(base + ':') or im == base:
                        return im

        # Nothing installed for this task — auto-pull first preference
        if auto_pull and prefs:
            target = prefs[0]
            if log_cb:
                log_cb(f"  [ModelRouter] No model for '{task}' — auto-pulling {target}...")
            success = _ollama_pull_model_streaming(target, url=url, log_cb=log_cb)
            if success:
                cls.invalidate_cache()
                return target
            if log_cb:
                log_cb(f"  [ModelRouter] Pull failed for {target}")

        # Last resort: return user's model (may not be ideal but better than nothing)
        return load_ollama_settings().get('model', '')


def ollama_test_connection(url: str = None, model: str = None) -> tuple:
    """Test Ollama connection and model availability.
    Returns (success: bool, message: str, models: list)."""
    import urllib.request, urllib.error
    s = load_ollama_settings()
    url = url or s['url']
    model = model or s['model']

    # Test server is running
    try:
        req = urllib.request.Request(f"{url}/api/tags", method='GET')
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        models = [m['name'] for m in data.get('models', [])]
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        return (False, f"Cannot reach Ollama at {url}\n{e}", [])

    if not models:
        return (False, f"Ollama is running but no models installed.\nRun: ollama pull {model}", models)

    # Check if requested model is available (exact match, or base name matches an installed variant)
    found_exact = model in models or any(m.startswith(model + ':') or m == model for m in models)
    if not found_exact:
        # Try prefix match to suggest the correct model
        model_base = model.split(':')[0]
        suggestions = [m for m in models if m.startswith(model_base)]
        hint = f"\nDid you mean: {', '.join(suggestions)}" if suggestions else ""
        return (True, f"Connected but model '{model}' not found.\n"
                      f"Available: {', '.join(models[:8])}{hint}\n"
                      f"Run: ollama pull {model}", models)

    return (True, f"Connected to Ollama\nModel: {model}\n{len(models)} models available", models)


def _ollama_generate(prompt: str, system: str = '', url: str = None,
                     model: str = None, timeout: int = None,
                     log_cb=None, images: list = None) -> str:
    """Send a prompt to Ollama via /api/chat and return the response text.
    Uses the chat endpoint so that 'think: false' is honored via the chat
    template (the /api/generate endpoint ignores this option for Qwen3.x).
    Raises on connection/timeout errors.
    """
    import urllib.request, urllib.error
    s = load_ollama_settings()
    url = url or s['url']
    model = model or s['model']
    # Use a generous timeout — Qwen3.5:9b can take 60-120s on first inference
    timeout = timeout or max(s.get('timeout', 30), 120)

    think = s.get('think', False)
    messages = []
    if system:
        messages.append({'role': 'system', 'content': system})
    user_msg = {'role': 'user', 'content': prompt}
    if images:
        user_msg['images'] = images
    messages.append(user_msg)

    payload = {
        'model': model,
        'messages': messages,
        'stream': False,
        'think': think,   # top-level for /api/chat — actually suppresses Qwen3.x CoT
        'options': {
            'temperature': s.get('temperature', 0.1),
            'num_predict': s.get('num_predict', 4096),
        },
    }

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        f"{url}/api/chat",
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    # Use a thread to enforce a hard total deadline (urlopen timeout only covers
    # socket-level idle, not total transfer time — a slow model can block forever)
    import threading
    _result_box = [None, None]  # [result_dict, exception]

    def _do_request():
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                _result_box[0] = json.loads(resp.read().decode())
        except Exception as exc:
            _result_box[1] = exc

    t = threading.Thread(target=_do_request, daemon=True)
    t.start()
    t.join(timeout=timeout + 30)  # hard deadline = socket timeout + 30s grace
    if t.is_alive():
        raise TimeoutError(f"Ollama request exceeded hard deadline of {timeout + 30}s")
    if _result_box[1]:
        raise _result_box[1]
    result = _result_box[0]

    raw = result.get('message', {}).get('content', '')

    # Log diagnostics
    if log_cb:
        done_reason = result.get('done_reason', '?')
        eval_count = result.get('eval_count', '?')
        prompt_tokens = result.get('prompt_eval_count', '?')
        log_cb(f"    [dbg] done_reason={done_reason} prompt_tokens={prompt_tokens} gen_tokens={eval_count} raw={repr(raw[:120])}")

    # Safety strip — remove any thinking blocks that slipped through
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL)
    raw = re.sub(r'<think>.*$', '', raw, flags=re.DOTALL)
    return raw.strip()



# ── Vision Helpers ────────────────────────────────────────────────────────────

_VISION_MODEL_PREFIXES = ('qwen2.5vl', 'qwen2.5-vl', 'gemma3', 'minicpm-v',
                          'llava', 'llama3.2-vision', 'moondream',
                          'bakllava', 'cogvlm', 'yi-vl', 'internvl')

def _is_vision_model(model_name: str) -> bool:
    """Check if a model supports vision/image input."""
    if not model_name:
        return False
    name_lower = model_name.lower().split(':')[0]
    # Check catalog flag first
    entry = _MODEL_CATALOG_MAP.get(model_name)
    if entry and entry.get('vision'):
        return True
    # Heuristic prefix matching for models not in catalog
    return any(name_lower.startswith(p) for p in _VISION_MODEL_PREFIXES)


def _find_vision_model(url: str = None, auto_upgrade: bool = True) -> str:
    """Find the best available vision model. Always returns the top-ranked
    model (for auto-pull) unless auto_upgrade is False, in which case it
    returns the best already-installed model.
    Returns model name or empty string if none available."""
    # Ranked best-to-worst — the #1 entry is the default auto-pull target
    _VISION_RANK = ['qwen2.5vl:7b', 'gemma3:12b', 'minicpm-v:8b',
                    'llama3.2-vision:11b', 'qwen2.5vl:3b', 'gemma3:4b',
                    'llava:13b', 'llava:7b', 'bakllava:7b', 'moondream:1.8b']
    installed = _ollama_list_models(url)
    # Find the best installed vision model by rank
    best_installed = ''
    best_installed_rank = len(_VISION_RANK) + 1
    for idx, m in enumerate(_VISION_RANK):
        base = m.split(':')[0]
        if m in installed:
            best_installed = m
            best_installed_rank = idx
            break
        # Check for variant tags (e.g., minicpm-v:latest matches minicpm-v)
        for i in installed:
            if i.startswith(base + ':') and _is_vision_model(i):
                if idx < best_installed_rank:
                    best_installed = i
                    best_installed_rank = idx
                break
    # Also check any installed vision models not in our rank list
    if not best_installed:
        for m in installed:
            if _is_vision_model(m):
                best_installed = m
                break
    # If auto_upgrade, always return the top-ranked model so the caller
    # will auto-pull it if not already installed
    if auto_upgrade:
        return _VISION_RANK[0]
    return best_installed


def _prepare_image_base64(file_path: str, max_pixels: int = 1024) -> str:
    """Open an image, resize if needed, JPEG-encode, and return base64 string.
    Returns empty string on failure."""
    if not HAS_PILLOW:
        return ''
    try:
        img = _PILImage.open(file_path)
        if img.mode == 'P' and 'transparency' in img.info:
            img = img.convert('RGBA')
        img = img.convert('RGB')  # ensure no alpha channel for JPEG
        # Resize preserving aspect ratio if either dimension exceeds max_pixels
        w, h = img.size
        if w > max_pixels or h > max_pixels:
            ratio = min(max_pixels / w, max_pixels / h)
            img = img.resize((int(w * ratio), int(h * ratio)), _PILImage.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85)
        return base64.b64encode(buf.getvalue()).decode('ascii')
    except Exception:
        return ''



# ── Evidence gathering for low-confidence escalation ─────────────────────────
_EVIDENCE_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tif', '.tiff', '.webp'}
_EVIDENCE_TEXT_EXTS = {'.txt', '.md', '.readme', '.nfo', '.text'}

def _gather_evidence(folder_path, url=None, log_cb=None) -> dict:
    """Dig into a folder to gather classification clues when confidence is low.
    Samples images (vision), reads text files, collects PDF filenames."""
    evidence = {'context': '', 'image_descriptions': [], 'text_snippets': [], 'pdf_hints': []}
    folder = Path(folder_path)
    if not folder.is_dir():
        return evidence

    # ── Collect candidate files (walk depth 2) ──
    images, texts, pdfs = [], [], []
    try:
        for root, dirs, files in os.walk(str(folder)):
            depth = str(root).replace(str(folder), '').count(os.sep)
            if depth > 2:
                dirs.clear(); continue
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                fp = os.path.join(root, f)
                if ext in _EVIDENCE_IMAGE_EXTS and len(images) < 5:
                    try:
                        sz = os.path.getsize(fp)
                        if 10_000 < sz < 20_000_000:  # 10KB - 20MB
                            images.append(fp)
                    except OSError:
                        pass
                elif ext in _EVIDENCE_TEXT_EXTS and len(texts) < 2:
                    texts.append(fp)
                elif ext == '.pdf' and len(pdfs) < 5:
                    pdfs.append(f)
    except PermissionError:
        pass

    # ── Image sampling with vision model ──
    if images and HAS_PILLOW:
        # Pick up to 3 representative images (first, middle, last)
        picks = [images[0]]
        if len(images) >= 3:
            picks.append(images[len(images) // 2])
        if len(images) >= 2:
            picks.append(images[-1])
        vision_model = ModelRouter.get_model('vision_classify', url=url, log_cb=log_cb)
        if vision_model:
            for img_path in picks:
                try:
                    b64 = _prepare_image_base64(img_path, max_pixels=512)
                    if not b64:
                        continue
                    desc = _ollama_generate(
                        prompt="Describe this image in 1-2 sentences. What is the subject and style?",
                        model=vision_model, url=url, images=[b64], timeout=30
                    )
                    if desc and len(desc.strip()) > 5:
                        evidence['image_descriptions'].append(desc.strip()[:200])
                        if log_cb:
                            log_cb(f"    [Evidence] Image: {os.path.basename(img_path)} -> {desc.strip()[:80]}")
                except Exception:
                    pass

    # ── Text peeking ──
    for tp in texts[:2]:
        try:
            with open(tp, 'r', encoding='utf-8', errors='ignore') as f:
                snippet = f.read(500).strip()
            if snippet:
                evidence['text_snippets'].append(snippet[:300])
                if log_cb:
                    log_cb(f"    [Evidence] Text: {os.path.basename(tp)} ({len(snippet)} chars)")
        except Exception:
            pass

    # ── PDF filename hints ──
    for pf in pdfs[:5]:
        cleaned = os.path.splitext(pf)[0].replace('-', ' ').replace('_', ' ').strip()
        if cleaned:
            evidence['pdf_hints'].append(cleaned)

    # Build combined context string
    parts = []
    if evidence['image_descriptions']:
        parts.append("Images found: " + '; '.join(evidence['image_descriptions']))
    if evidence['text_snippets']:
        parts.append("Text content: " + ' | '.join(evidence['text_snippets']))
    if evidence['pdf_hints']:
        parts.append("PDF files: " + ', '.join(evidence['pdf_hints']))
    evidence['context'] = '\n'.join(parts)
    return evidence


def _escalate_classification(folder_name, folder_path, initial_result,
                             url=None, log_cb=None, category_list=None) -> dict:
    """Re-classify a low-confidence item using evidence gathering + smarter model.
    Only upgrades confidence, never downgrades."""
    if log_cb:
        log_cb(f"    [Escalate] Gathering evidence for: {folder_name}")

    evidence = _gather_evidence(folder_path, url=url, log_cb=log_cb)
    if not evidence['context']:
        if log_cb:
            log_cb(f"    [Escalate] No evidence found -- keeping original result")
        return initial_result

    # Get category list
    if not category_list:
        category_list = get_all_category_names()
    cat_list_str = ', '.join(category_list)

    # Get a smarter model for re-classification
    reasoning_model = ModelRouter.get_model('deep_reasoning', url=url, log_cb=log_cb)

    orig_cat = initial_result.get('category', 'Unknown')
    orig_conf = initial_result.get('confidence', 0)
    orig_method = initial_result.get('method', '')

    prompt = (
        f"Classify this folder into EXACTLY ONE category from the list below.\n\n"
        f"Folder name: {folder_name}\n"
        f"Initial guess: {orig_cat} ({orig_conf}% confidence)\n\n"
        f"Additional evidence gathered from inside the folder:\n{evidence['context']}\n\n"
        f"Available categories:\n{cat_list_str}\n\n"
        f"Respond with JSON only: {{\"category\": \"<exact category name>\", "
        f"\"confidence\": <50-99>, \"name\": \"<cleaned display name>\"}}"
    )

    try:
        resp = _ollama_generate(
            prompt=prompt,
            system="You are a file classification expert. Use all evidence to pick the best category. "
                   "Be precise. Return only valid JSON.",
            model=reasoning_model, url=url, timeout=60
        )
        # Parse JSON from response
        resp_clean = resp.strip()
        # Extract JSON from markdown code blocks if present
        if '```' in resp_clean:
            import re as _re_esc
            m = _re_esc.search(r'```(?:json)?\s*(\{.*?\})\s*```', resp_clean, _re_esc.DOTALL)
            if m:
                resp_clean = m.group(1)
        # Try to find JSON object
        start = resp_clean.find('{')
        end = resp_clean.rfind('}')
        if start >= 0 and end > start:
            parsed = json.loads(resp_clean[start:end + 1])
        else:
            if log_cb:
                log_cb(f"    [Escalate] Could not parse LLM response")
            return initial_result

        new_cat = parsed.get('category', '')
        new_conf = int(parsed.get('confidence', 0))
        new_name = parsed.get('name', initial_result.get('cleaned_name', folder_name))

        # Validate category exists
        if new_cat not in category_list:
            if log_cb:
                log_cb(f"    [Escalate] LLM returned unknown category '{new_cat}' -- keeping original")
            return initial_result

        # Only accept if confidence improved
        if new_conf > orig_conf:
            if log_cb:
                log_cb(f"    [Escalate] Upgraded: {orig_cat}({orig_conf}%) -> {new_cat}({new_conf}%)")
            return {
                'category': new_cat,
                'confidence': new_conf,
                'cleaned_name': new_name,
                'method': f"escalated:{orig_method}",
                'detail': f"Evidence: {len(evidence['image_descriptions'])} images, "
                          f"{len(evidence['text_snippets'])} texts, {len(evidence['pdf_hints'])} PDFs",
                'topic': initial_result.get('topic'),
            }
        else:
            if log_cb:
                log_cb(f"    [Escalate] No improvement ({new_conf}% vs {orig_conf}%) -- keeping original")
            return initial_result

    except Exception as e:
        if log_cb:
            log_cb(f"    [Escalate] Error: {e}")
        return initial_result


def _build_llm_system_prompt() -> str:
    """Build the system prompt with all category names for LLM classification.
    Uses profile-specific persona when a non-design profile is active."""
    from unifile.profiles import get_llm_system_prompt_prefix, get_profile_categories

    # Check if we have a profile-specific prompt
    prefix = get_llm_system_prompt_prefix()
    if prefix is not None:
        # Profile-specific prompt: use profile categories
        profile_cats = get_profile_categories()
        cat_names = [c[0] for c in profile_cats]
        cat_list = '\n'.join(cat_names)
        return prefix + cat_list

    # Default: Design Assets prompt (original behavior)
    cats = get_all_category_names()
    cat_list = '\n'.join(cats)
    return (
        "You are a design asset file organizer specializing in creative marketplace content "
        "(Envato, Creative Market, Freepik, etc).\n\n"
        "Your job:\n"
        "1. CLEAN the folder name: remove ONLY true noise — marketplace IDs, item codes "
        "(numeric strings like 553035, 22832058), version numbers (v1, v2.1), "
        "site names (GraphicRiver, CreativeMarket, CM_, Envato, VideoHive, VH-, etc), "
        "and replace dashes/underscores with spaces. Convert to clean Title Case.\n\n"
        "CRITICAL NAME CLEANING RULES:\n"
        "- PRESERVE the subject, topic, and descriptive words. These describe WHAT the design "
        "is about and are the most important part of the name.\n"
        "- The category already tells the user what TYPE of asset it is, so the cleaned name "
        "should focus on the SUBJECT/THEME. For example:\n"
        "  '553035-Advertisement-Company-Flyer-Template' → 'Advertisement Company Flyer Template'\n"
        "  'VH-22832058-Christmas-Slideshow' → 'Christmas Slideshow'\n"
        "  'Night-Club-Party-Flyer-PSD' → 'Night Club Party Flyer'\n"
        "  'CM_Jetstyle_Corporate-Business-Card' → 'Corporate Business Card'\n"
        "- NEVER return just a generic asset type like 'Flyer Template', 'Business Card', "
        "'Slideshow', 'Logo' etc. The name MUST include the specific subject/theme.\n"
        "- If the original name IS only a generic type after removing noise, keep it as-is.\n\n"
        "NAMING FROM PROJECT FILES (IMPORTANT):\n"
        "- If the folder name is mostly numeric IDs or marketplace noise, look at the .aep, "
        ".prproj, .psd, and .mogrt filenames inside the folder. These often contain the REAL "
        "project name.\n"
        "- Example: folder '22832058-VH' contains 'Epic_Corporate_Slideshow.aep' → name should "
        "be 'Epic Corporate Slideshow', NOT a guess based on the folder name.\n"
        "- .aep and .prproj filenames are the strongest signal for the true project name.\n"
        "- Ignore generic project filenames like 'main.aep', 'project.aep', 'comp.aep', "
        "'final.aep', 'preview.aep'.\n"
        "- Ignore subfolder names that are just asset containers: Footage, (Footage), Audio, "
        "Media, Elements, Preview, etc.\n\n"
        "NON-ENGLISH CONTENT:\n"
        "- Folder names, subfolders, and project files may be in Chinese, Russian, Korean, "
        "Arabic, Japanese, Thai, or other languages.\n"
        "- You MUST translate the name to English. The cleaned name in your response must "
        "ALWAYS be in English.\n"
        "- Translate the MEANING, not just transliterate. "
        "For example: '圣诞节幻灯片' → 'Christmas Slideshow', "
        "'Рождественское слайдшоу' → 'Christmas Slideshow', "
        "'企业宣传片' → 'Corporate Promo'.\n"
        "- If the name mixes languages (e.g. '22832058-圣诞节-Template'), extract the meaning "
        "from all parts and produce a clean English name.\n"
        "- Category assignment should still be based on the content type regardless of language.\n\n"
        "2. CATEGORIZE the folder into the single best category from the list below, "
        "based on the folder name AND the actual files inside it.\n\n"
        "IMPORTANT: Look at the filenames to determine what TYPE of design this is. "
        "For example, if files contain 'flyer' it's a flyer template. If files contain "
        "'business-card' it's a business card. If there are .aep files, it's an After Effects template. "
        "If there are .psd files with topic names like 'Night Club', it's likely a flyer.\n\n"
        "Respond ONLY with valid JSON, no other text:\n"
        '{\"name\": \"Clean Project Name\", \"category\": \"Exact Category Name\", \"confidence\": 85}\n\n'
        "VALID CATEGORIES (pick exactly one):\n"
        f"{cat_list}"
    )


def ollama_classify_folder(folder_name: str, folder_path: str = None,
                           url: str = None, model: str = None,
                           log_cb=None) -> dict:
    """Use Ollama LLM to classify and rename a folder.
    Returns dict: {name, category, confidence, method, detail} or empty on failure."""
    result = {'name': None, 'category': None, 'confidence': 0,
              'method': 'llm', 'detail': ''}

    # Collect file/subfolder context from the folder
    context_lines = [f"Folder name: \"{folder_name}\""]

    # ── Smart ID-only enrichment ──────────────────────────────────────────────
    # If the folder name is just a marketplace ID (e.g. "VH-12345678"), scan
    # inside for project files (.aep, .prproj, .psd…) to extract a real name.
    if folder_path and os.path.isdir(folder_path) and _is_id_only_folder(folder_name):
        hints = _extract_name_hints(folder_path)
        if hints:
            context_lines.append("")
            context_lines.append("⚠ FOLDER NAME IS ID-ONLY — use the project file name below instead:")
            for name, source, priority in hints[:5]:
                context_lines.append(f"  ★ {name}  [from {source}, score {priority}]")
            context_lines.append("Use the project file name as the cleaned 'name' field.")
    if folder_path and os.path.isdir(folder_path):
        files = []
        subdirs = []
        try:
            for entry in os.scandir(folder_path):
                if entry.is_file():
                    files.append(entry.name)
                elif entry.is_dir():
                    subdirs.append(entry.name)
                    # Also list files one level deeper
                    try:
                        for sub_entry in os.scandir(entry.path):
                            if sub_entry.is_file():
                                files.append(f"{entry.name}/{sub_entry.name}")
                    except (PermissionError, OSError):
                        pass
        except (PermissionError, OSError):
            pass

        if files:
            # Separate project files (strong naming signals) from other files
            project_exts = {'.aep', '.aet', '.prproj', '.psd', '.psb', '.mogrt', '.ai', '.indd'}
            project_files = []
            other_files = []
            for f in files[:80]:
                if f.lower().startswith('__macosx'):
                    continue
                ext = os.path.splitext(f)[1].lower()
                if ext in project_exts:
                    project_files.append(f)
                else:
                    other_files.append(f)

            # Show project files first with a clear label (these are the naming signals)
            if project_files:
                context_lines.append(f"PROJECT FILES (use these names for the project title):")
                for f in project_files[:15]:
                    context_lines.append(f"  ** {f}")
            if other_files:
                shown = other_files[:max(25, 40 - len(project_files))]
                context_lines.append(f"Other files ({len(files)} total, showing {len(shown) + len(project_files)}):")
                for f in shown:
                    context_lines.append(f"  {f}")
        if subdirs:
            # Filter out asset/utility folders — they're never the project name
            meaningful = []
            for d in subdirs[:20]:
                d_lower = d.lower().strip()
                d_stripped = re.sub(r'^[\(\[\{]|[\)\]\}]$', '', d_lower).strip()
                if d_stripped not in _ASSET_FOLDER_NAMES and d_lower not in _ASSET_FOLDER_NAMES:
                    meaningful.append(d)
            if meaningful:
                context_lines.append(f"Subfolders: {', '.join(meaningful)}")
            # Note asset folders separately so the LLM knows they exist but ignores them for naming
            asset_dirs = [d for d in subdirs[:20] if d not in meaningful]
            if asset_dirs:
                context_lines.append(f"Asset folders (ignore for naming): {', '.join(asset_dirs)}")

    prompt = '\n'.join(context_lines)

    try:
        system = _build_llm_system_prompt()
        raw = _ollama_generate(prompt, system=system, url=url, model=model, log_cb=log_cb)

        raw = raw.strip()
        if not raw:
            result['detail'] = 'llm:empty_response'
            return result

        # Robust JSON extraction — works whether model wraps in markdown or not
        parsed = None
        # Try direct parse first
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # Try to find a JSON object anywhere in the response
            match = re.search(r'\{[^{}]*"name"[^{}]*"category"[^{}]*\}', raw, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            if parsed is None:
                # Last resort: any JSON object
                match = re.search(r'\{.*?\}', raw, re.DOTALL)
                if match:
                    try:
                        parsed = json.loads(match.group())
                    except json.JSONDecodeError:
                        pass

        if parsed is None:
            result['detail'] = f'llm:json_parse_failed raw={repr(raw[:80])}'
            return result
        clean_name = parsed.get('name', '').strip()
        category = parsed.get('category', '').strip()
        confidence = int(parsed.get('confidence', 0))

        # Validate category exists
        valid_cats = get_all_category_names()
        if category not in valid_cats:
            # Try fuzzy match on category name
            if HAS_RAPIDFUZZ:
                best_match = None
                best_score = 0
                for vc in valid_cats:
                    score = _rfuzz.ratio(category.lower(), vc.lower())
                    if score > best_score:
                        best_score = score
                        best_match = vc
                if best_match and best_score >= 75:
                    category = best_match
                    confidence = max(confidence - 10, 30)
                else:
                    category = None
            else:
                category = None

        if category:
            result['name'] = clean_name or folder_name
            result['category'] = category
            result['confidence'] = min(max(confidence, 30), 95)
            result['detail'] = f"llm:{load_ollama_settings().get('model', '?')}→{category}"

            # ── Post-validation: reject over-stripped names ──
            # If the LLM returned a name that's just the category or a generic asset type,
            # fall back to rule-based cleaning which preserves subject/topic words
            if clean_name:
                _rejected = _is_generic_name(clean_name, category)
                if _rejected:
                    # LLM stripped too aggressively — use smart naming (AEP/project hints)
                    fallback_name = _smart_name(folder_name, folder_path, category)
                    result['name'] = fallback_name
                    result['detail'] += f" (name_override:{clean_name}→{fallback_name})"
        else:
            result['detail'] = f"llm:invalid_category:\"{parsed.get('category', '')}\" not found"

    except json.JSONDecodeError as e:
        result['detail'] = f"llm:json_parse_error:{e}"
    except Exception as e:
        result['detail'] = f"llm:error:{e}"

    return result


# ── LLM Name Cache (in-memory, keyed by folder name string) ──────────────────
# Separate from the fingerprint-based SQLite cache. Avoids re-hitting Ollama
# for folders with identical names seen during the same scan session.
_llm_name_cache: dict = {}

def _llm_cache_get(folder_name: str):
    return _llm_name_cache.get(folder_name)

def _llm_cache_set(folder_name: str, result: dict):
    _llm_name_cache[folder_name] = result

def _llm_cache_clear():
    _llm_name_cache.clear()


def ollama_classify_batch(folders: list, url: str = None, model: str = None) -> list:
    """Classify multiple folders in a single Ollama request (batching).

    Args:
        folders: list of dicts with keys 'folder_name', 'folder_path', 'context' (str)
        url, model: Ollama connection params

    Returns:
        list of result dicts (same structure as ollama_classify_folder), one per input folder.
        Failed entries have category=None.
    """
    import urllib.request, urllib.error
    s = load_ollama_settings()
    url = url or s['url']
    model = model or s['model']
    timeout = max(s.get('timeout', 30), 120) + 30 * len(folders)  # generous per-folder budget
    valid_cats = get_all_category_names()

    # Build multi-folder prompt
    prompt_parts = []
    for i, f in enumerate(folders):
        prompt_parts.append(f"--- FOLDER {i+1} ---\n{f['context']}")
    prompt = '\n\n'.join(prompt_parts)

    # Batch-specific system prompt
    batch_system = (
        _build_llm_system_prompt().rstrip() +
        f"\n\nYou are processing {len(folders)} folders in a batch. "
        "Respond ONLY with a JSON object in this exact format:\n"
        f'{{"results": [{{"name":"...", "category":"...", "confidence":85}}, ...]}}\n'
        f"The 'results' array must have exactly {len(folders)} entries, one per folder, IN ORDER.\n"
        "No other text, no markdown, no explanation."
    )

    think = s.get('think', False)
    messages = [
        {'role': 'system', 'content': batch_system},
        {'role': 'user', 'content': prompt},
    ]

    payload = {
        'model': model,
        'messages': messages,
        'stream': False,
        'think': think,   # top-level /api/chat flag — suppresses Qwen3.x CoT
        'options': {
            'temperature': s.get('temperature', 0.1),
            'num_predict': s.get('num_predict', 4096) * len(folders),
        },
    }

    empty = [{'name': None, 'category': None, 'confidence': 0,
               'method': 'llm', 'detail': 'batch:not_run'} for _ in folders]

    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            f"{url}/api/chat",
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode())
        raw = result.get('message', {}).get('content', '').strip()
        raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL)
        raw = re.sub(r'<think>.*$', '', raw, flags=re.DOTALL)
        raw = raw.strip()
        if not raw:
            for r in empty: r['detail'] = 'batch:empty_response'
            return empty

        parsed = json.loads(raw)
        # Unwrap {"results": [...]} — the expected format
        if isinstance(parsed, dict):
            parsed = parsed.get('results', parsed.get('items', parsed.get('folders', [])))
        if not isinstance(parsed, list):
            for r in empty: r['detail'] = f'batch:not_a_list:{type(parsed).__name__}'
            return empty

        out = []
        for i, f in enumerate(folders):
            if i >= len(parsed):
                out.append({'name': None, 'category': None, 'confidence': 0,
                             'method': 'llm', 'detail': 'batch:missing_result'})
                continue
            p = parsed[i]
            clean_name = str(p.get('name', '') or '').strip()
            category = str(p.get('category', '') or '').strip()
            confidence = int(p.get('confidence', 0))

            if category not in valid_cats:
                if HAS_RAPIDFUZZ:
                    best, best_s = None, 0
                    for vc in valid_cats:
                        s_score = _rfuzz.ratio(category.lower(), vc.lower())
                        if s_score > best_s:
                            best_s = s_score; best = vc
                    if best and best_s >= 75:
                        category = best; confidence = max(confidence - 10, 30)
                    else:
                        category = None
                else:
                    category = None

            if category:
                folder_name = f['folder_name']
                res = {
                    'name': clean_name or folder_name,
                    'category': category,
                    'confidence': min(max(confidence, 30), 95),
                    'method': 'llm_batch',
                    'detail': f"llm_batch:{model}→{category}",
                }
                # Reject over-stripped names (same logic as single classify)
                if clean_name and _is_generic_name(clean_name, category):
                    fallback = _smart_name(folder_name, f.get('folder_path'), category)
                    res['name'] = fallback
                    res['detail'] += f" (name_override:{clean_name}→{fallback})"
                out.append(res)
            else:
                out.append({'name': None, 'category': None, 'confidence': 0,
                             'method': 'llm_batch', 'detail': f"batch:invalid_category:{p.get('category','')}"})

        return out

    except json.JSONDecodeError as e:
        for r in empty: r['detail'] = f"batch:json_error:{e}"
        return empty
    except Exception as e:
        for r in empty: r['detail'] = f"batch:error:{e}"
        return empty


def _ollama_list_models(url: str = None) -> list:
    """Fetch list of locally installed Ollama models. Returns list of name strings."""
    import urllib.request, urllib.error
    url = url or load_ollama_settings()['url']
    try:
        req = urllib.request.Request(f"{url}/api/tags", method='GET')
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        return sorted(m['name'] for m in data.get('models', []))
    except Exception:
        return []


def _ollama_pull_model(model: str, url: str = None, log_cb=None) -> bool:
    """Pull a model via Ollama CLI. Returns True on success."""
    import subprocess
    binary = _find_ollama_binary()
    if not binary:
        if log_cb: log_cb("ollama binary not found — run: ollama pull " + model)
        return False
    _ansi_re = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]|\x1b\].*?(?:\x07|\x1b\\)|\r')
    try:
        proc = subprocess.Popen(
            [binary, 'pull', model],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        last_pct = ''
        for raw_line in proc.stdout:
            line = _ansi_re.sub('', raw_line.decode('utf-8', errors='replace')).strip()
            if not line:
                continue
            # Deduplicate progress lines — only log when percentage changes
            pct_m = re.search(r'(\d+)%', line)
            if pct_m:
                pct = pct_m.group(1)
                if pct == last_pct:
                    continue
                last_pct = pct
            if log_cb: log_cb(f"  [pull] {line}")
        try:
            proc.wait(timeout=600)  # 10 minute max for model pull
        except subprocess.TimeoutExpired:
            proc.kill()
            if log_cb: log_cb(f"Model pull timed out after 10 minutes")
            return False
        return proc.returncode == 0
    except Exception as e:
        if log_cb: log_cb(f"Pull failed: {e}")
        return False


def _find_ollama_binary() -> str:
    """Find ollama executable. Returns path or empty string."""
    # Check PATH first
    ollama_cmd = 'ollama.exe' if sys.platform == 'win32' else 'ollama'
    for p in os.environ.get('PATH', '').split(os.pathsep):
        candidate = os.path.join(p, ollama_cmd)
        if os.path.isfile(candidate):
            return candidate

    # Windows common install locations
    if sys.platform == 'win32':
        for loc in [
            os.path.expandvars(r'%LOCALAPPDATA%\Programs\Ollama\ollama.exe'),
            os.path.expandvars(r'%PROGRAMFILES%\Ollama\ollama.exe'),
            os.path.expandvars(r'%USERPROFILE%\AppData\Local\Programs\Ollama\ollama.exe'),
        ]:
            if os.path.isfile(loc):
                return loc

    # Linux/macOS common locations
    for loc in ['/usr/local/bin/ollama', '/usr/bin/ollama', os.path.expanduser('~/.local/bin/ollama')]:
        if os.path.isfile(loc):
            return loc

    return ''


def _is_ollama_server_running(url: str = None) -> bool:
    """Check if Ollama server is responding."""
    import urllib.request, urllib.error
    url = url or load_ollama_settings()['url']
    try:
        req = urllib.request.Request(f"{url}/api/tags", method='GET')
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _ollama_has_model(model: str, url: str = None) -> bool:
    """Check if a specific model is already pulled (exact match)."""
    import urllib.request, urllib.error
    url = url or load_ollama_settings()['url']
    try:
        req = urllib.request.Request(f"{url}/api/tags", method='GET')
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        models = [m['name'] for m in data.get('models', [])]
        # Exact match: "qwen3.5:9b" in models, or untagged "qwen3.5" matches "qwen3.5:latest"
        return model in models or any(m.startswith(model + ':') or m == model for m in models)
    except Exception:
        return False


def _ollama_list_models_detailed(url: str = None) -> list:
    """Fetch installed models with full metadata (name, size, modified_at, details)."""
    import urllib.request, urllib.error
    url = url or load_ollama_settings()['url']
    try:
        req = urllib.request.Request(f"{url}/api/tags", method='GET')
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        return data.get('models', [])
    except Exception:
        return []


def _ollama_delete_model(model: str, url: str = None) -> bool:
    """Delete a model via Ollama API. Returns True on success."""
    import urllib.request, urllib.error
    url = url or load_ollama_settings()['url']
    try:
        body = json.dumps({"name": model}).encode()
        req = urllib.request.Request(f"{url}/api/delete", data=body, method='DELETE',
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        return e.code == 200
    except Exception:
        return False


def _ollama_pull_model_streaming(model: str, url: str = None, progress_cb=None, log_cb=None) -> bool:
    """Pull a model via Ollama API with streaming progress. Falls back to CLI on failure."""
    import urllib.request, urllib.error
    url = url or load_ollama_settings()['url']
    try:
        body = json.dumps({"name": model, "stream": True}).encode()
        req = urllib.request.Request(f"{url}/api/pull", data=body, method='POST',
                                     headers={'Content-Type': 'application/json'})
        resp = urllib.request.urlopen(req, timeout=600)
        buf = b''
        while True:
            chunk = resp.read(1)
            if not chunk:
                break
            buf += chunk
            if chunk == b'\n':
                line = buf.strip()
                buf = b''
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                status = obj.get('status', '')
                if log_cb:
                    log_cb(status)
                if progress_cb:
                    completed = obj.get('completed', 0)
                    total = obj.get('total', 0)
                    progress_cb(completed, total, status)
                if obj.get('error'):
                    if log_cb:
                        log_cb(f"Error: {obj['error']}")
                    resp.close()
                    return False
        resp.close()
        return True
    except Exception as e:
        if log_cb:
            log_cb(f"API pull failed ({e}), falling back to CLI...")
        return _ollama_pull_model(model, url=url, log_cb=log_cb)
