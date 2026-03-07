"""UniFile — Nexa SDK AI backend (alternative to Ollama).

Provides local AI inference using Nexa SDK with:
- LLaVA (vision model) for image description and classification
- Llama 3.2 (text model) for text summarization and classification

Adapted from Local-File-Organizer's inference pipeline.
"""
import json
import logging
import os
import re
from pathlib import Path

from unifile.config import _APP_DATA_DIR
from unifile.categories import get_all_category_names

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

_NEXA_SETTINGS_FILE = os.path.join(_APP_DATA_DIR, 'nexa_settings.json')

_NEXA_DEFAULTS = {
    'enabled': False,
    'vision_model': 'llava-v1.6-vicuna-7b:q4_0',
    'text_model': 'Llama3.2-3B-Instruct:q3_K_M',
    'temperature': 0.3,
    'max_new_tokens': 3000,
    'top_k': 3,
    'top_p': 0.2,
}

_NEXA_MODEL_CATALOG = [
    {
        'group': 'Vision Models',
        'name': 'llava-v1.6-vicuna-7b:q4_0',
        'label': 'LLaVA v1.6 Vicuna 7B (Q4)  -  Image understanding',
        'type': 'vision',
    },
    {
        'group': 'Vision Models',
        'name': 'llava-phi-3-mini:q4_0',
        'label': 'LLaVA Phi-3 Mini (Q4)  -  Smaller/faster vision',
        'type': 'vision',
    },
    {
        'group': 'Text Models',
        'name': 'Llama3.2-3B-Instruct:q3_K_M',
        'label': 'Llama 3.2 3B Instruct (Q3)  -  Fast text classification',
        'type': 'text',
    },
    {
        'group': 'Text Models',
        'name': 'Llama3.2-1B-Instruct:q4_0',
        'label': 'Llama 3.2 1B Instruct (Q4)  -  Ultra-fast, lower accuracy',
        'type': 'text',
    },
    {
        'group': 'Text Models',
        'name': 'gemma-2b-instruct:q4_0',
        'label': 'Gemma 2B Instruct (Q4)  -  Compact text model',
        'type': 'text',
    },
]


def load_nexa_settings() -> dict:
    try:
        with open(_NEXA_SETTINGS_FILE, 'r') as f:
            s = json.load(f)
        return {**_NEXA_DEFAULTS, **s}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return dict(_NEXA_DEFAULTS)


def save_nexa_settings(settings: dict):
    os.makedirs(_APP_DATA_DIR, exist_ok=True)
    try:
        with open(_NEXA_SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# SDK availability check
# ---------------------------------------------------------------------------

_nexa_available = None


def is_nexa_available() -> bool:
    """Check if nexa SDK is installed and importable."""
    global _nexa_available
    if _nexa_available is None:
        try:
            from nexa.gguf import NexaVLMInference, NexaTextInference
            _nexa_available = True
        except ImportError:
            _nexa_available = False
    return _nexa_available


# ---------------------------------------------------------------------------
# Inference wrappers
# ---------------------------------------------------------------------------

_vision_model = None
_text_model = None


def _init_models(settings: dict | None = None):
    """Initialize Nexa models lazily."""
    global _vision_model, _text_model
    if not is_nexa_available():
        raise RuntimeError("Nexa SDK not installed. Install with: pip install nexaai")

    from nexa.gguf import NexaVLMInference, NexaTextInference

    s = settings or load_nexa_settings()

    if _vision_model is None:
        logger.info("Initializing Nexa vision model: %s", s['vision_model'])
        _vision_model = NexaVLMInference(
            model_path=s['vision_model'],
            local_path=None,
            stop_words=[],
            temperature=s['temperature'],
            max_new_tokens=s['max_new_tokens'],
            top_k=s['top_k'],
            top_p=s['top_p'],
            profiling=False,
        )

    if _text_model is None:
        logger.info("Initializing Nexa text model: %s", s['text_model'])
        _text_model = NexaTextInference(
            model_path=s['text_model'],
            local_path=None,
            stop_words=[],
            temperature=0.5,
            max_new_tokens=s['max_new_tokens'],
            top_k=s['top_k'],
            top_p=0.3,
            profiling=False,
        )


def _text_from_generator(generator) -> str:
    """Extract text from a Nexa streaming generator response."""
    text = ""
    try:
        while True:
            response = next(generator)
            choices = response.get('choices', [])
            for choice in choices:
                delta = choice.get('delta', {})
                if 'content' in delta:
                    text += delta['content']
    except StopIteration:
        pass
    return text.strip()


def unload_models():
    """Release loaded Nexa models from memory."""
    global _vision_model, _text_model
    _vision_model = None
    _text_model = None
    logger.info("Nexa models unloaded")


# ---------------------------------------------------------------------------
# Core inference functions
# ---------------------------------------------------------------------------

def describe_image(image_path: str, settings: dict | None = None) -> str:
    """Generate a text description of an image using the vision model."""
    _init_models(settings)
    prompt = (
        "Please provide a detailed description of this image, "
        "focusing on the main subject and any important details."
    )
    generator = _vision_model._chat(prompt, image_path)
    return _text_from_generator(generator)


def summarize_text(text: str, settings: dict | None = None) -> str:
    """Summarize text content using the text model."""
    _init_models(settings)
    prompt = (
        "Provide a concise and accurate summary of the following text, "
        "focusing on the main ideas and key details. "
        "Limit your summary to a maximum of 150 words.\n\n"
        f"Text: {text[:4000]}\n\nSummary:"
    )
    response = _text_model.create_completion(prompt)
    return response['choices'][0]['text'].strip()


def generate_filename(description: str, max_words: int = 3,
                      settings: dict | None = None) -> str:
    """Generate a descriptive filename from a description using the text model."""
    _init_models(settings)
    prompt = (
        f"Based on the description below, generate a specific and descriptive "
        f"filename. Limit to {max_words} words max. Use nouns, avoid verbs. "
        f"Connect words with underscores. Output only the filename.\n\n"
        f"Description: {description}\n\nFilename:"
    )
    response = _text_model.create_completion(prompt)
    raw = response['choices'][0]['text'].strip()
    raw = re.sub(r'^Filename:\s*', '', raw, flags=re.IGNORECASE).strip()
    # Clean: remove extensions, special chars, limit words
    raw = re.sub(r'\.\w{1,4}$', '', raw)
    raw = re.sub(r'[^\w\s]', ' ', raw)
    raw = re.sub(r'\d+', '', raw).strip()
    words = [w.lower() for w in raw.split() if w.isalpha()][:max_words]
    return '_'.join(words) if words else 'untitled'


def generate_category(description: str, settings: dict | None = None) -> str:
    """Generate a category/folder name from a description using the text model."""
    _init_models(settings)
    prompt = (
        "Based on the description below, generate a general category or theme "
        "that best represents the main subject. Limit to 2 words max. "
        "Use nouns, avoid verbs. Output only the category.\n\n"
        f"Description: {description}\n\nCategory:"
    )
    response = _text_model.create_completion(prompt)
    raw = response['choices'][0]['text'].strip()
    raw = re.sub(r'^Category:\s*', '', raw, flags=re.IGNORECASE).strip()
    raw = re.sub(r'[^\w\s]', ' ', raw)
    words = [w.lower() for w in raw.split() if w.isalpha()][:2]
    return '_'.join(words) if words else 'uncategorized'


# ---------------------------------------------------------------------------
# Classification interface (matches Ollama's classify signature)
# ---------------------------------------------------------------------------

def nexa_classify_folder(folder_name: str, folder_path: str = None,
                         settings: dict | None = None,
                         log_cb=None) -> dict:
    """Classify a folder using Nexa SDK models.

    Returns dict compatible with ollama_classify_folder:
    {name, category, confidence, method, detail}
    """
    result = {
        'name': None, 'category': None, 'confidence': 0,
        'method': 'nexa', 'detail': '',
    }

    if not is_nexa_available():
        result['detail'] = 'Nexa SDK not installed'
        return result

    try:
        _init_models(settings)
    except Exception as e:
        result['detail'] = f'Model init failed: {e}'
        return result

    # Build context from folder contents
    context = f'Folder name: "{folder_name}"'
    if folder_path and os.path.isdir(folder_path):
        files = []
        try:
            for entry in os.scandir(folder_path):
                if entry.is_file():
                    files.append(entry.name)
                elif entry.is_dir():
                    try:
                        for sub in os.scandir(entry.path):
                            if sub.is_file():
                                files.append(f"{entry.name}/{sub.name}")
                    except (PermissionError, OSError):
                        pass
        except (PermissionError, OSError):
            pass
        if files:
            context += f'\nFiles inside: {", ".join(files[:40])}'

        # Check for images to use vision model
        image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
        image_files = [
            os.path.join(folder_path, f) for f in os.listdir(folder_path)
            if os.path.splitext(f)[1].lower() in image_exts
        ][:3]  # Max 3 images
        if image_files:
            descriptions = []
            for img_path in image_files:
                try:
                    desc = describe_image(img_path, settings)
                    if desc:
                        descriptions.append(desc)
                except Exception:
                    pass
            if descriptions:
                context += '\nImage descriptions: ' + ' | '.join(descriptions)

    # Use text model to classify
    categories = get_all_category_names()
    cat_list = ', '.join(categories[:200])

    prompt = (
        "You are a file organization assistant. Given the folder info below, "
        "classify it into one of the valid categories and suggest a clean name.\n\n"
        f"{context}\n\n"
        "Respond with ONLY a JSON object:\n"
        '{"name": "Clean Name", "category": "Category Name", "confidence": 85}\n\n'
        f"VALID CATEGORIES (pick exactly one):\n{cat_list}"
    )

    try:
        response = _text_model.create_completion(prompt)
        raw = response['choices'][0]['text'].strip()

        # Extract JSON from response
        json_match = re.search(r'\{[^}]+\}', raw)
        if json_match:
            data = json.loads(json_match.group())
            result['name'] = data.get('name', folder_name)
            result['category'] = data.get('category')
            result['confidence'] = float(data.get('confidence', 0))
            result['detail'] = 'nexa-text'
            if log_cb:
                log_cb(f"  Nexa: {folder_name} -> {result['category']} "
                       f"({result['confidence']:.0f}%)")
    except Exception as e:
        result['detail'] = f'Inference failed: {e}'
        logger.warning("Nexa classification failed for %s: %s", folder_name, e)

    return result


def nexa_classify_file(file_path: str, settings: dict | None = None,
                       log_cb=None) -> dict:
    """Classify a single file using Nexa SDK.

    For images, uses the vision model to describe then classify.
    For text/documents, reads content and uses text model.
    """
    result = {
        'name': None, 'category': None, 'confidence': 0,
        'method': 'nexa', 'detail': '',
    }

    if not is_nexa_available():
        result['detail'] = 'Nexa SDK not installed'
        return result

    try:
        _init_models(settings)
    except Exception as e:
        result['detail'] = f'Model init failed: {e}'
        return result

    p = Path(file_path)
    ext = p.suffix.lower()
    description = ""

    # Image files: use vision model
    image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff'}
    text_exts = {'.txt', '.md', '.py', '.js', '.html', '.css', '.json', '.xml',
                 '.csv', '.log', '.ini', '.cfg', '.yaml', '.yml', '.toml'}

    if ext in image_exts:
        try:
            description = describe_image(str(p), settings)
            result['detail'] = 'nexa-vision'
        except Exception as e:
            result['detail'] = f'Vision failed: {e}'
            return result
    elif ext in text_exts:
        try:
            with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(4000)
            description = summarize_text(content, settings)
            result['detail'] = 'nexa-text'
        except Exception as e:
            result['detail'] = f'Read failed: {e}'
            return result
    else:
        # For other files, just use the filename
        description = f"File named: {p.name}"
        result['detail'] = 'nexa-filename'

    if not description:
        return result

    # Classify based on description
    categories = get_all_category_names()
    cat_list = ', '.join(categories[:200])

    prompt = (
        "Classify this file into one of the valid categories. "
        "Also suggest a clean descriptive name.\n\n"
        f"Filename: {p.name}\n"
        f"Description: {description}\n\n"
        "Respond with ONLY a JSON object:\n"
        '{"name": "Clean Name", "category": "Category Name", "confidence": 85}\n\n'
        f"VALID CATEGORIES:\n{cat_list}"
    )

    try:
        response = _text_model.create_completion(prompt)
        raw = response['choices'][0]['text'].strip()

        json_match = re.search(r'\{[^}]+\}', raw)
        if json_match:
            data = json.loads(json_match.group())
            result['name'] = data.get('name', p.stem)
            result['category'] = data.get('category')
            result['confidence'] = float(data.get('confidence', 0))
            if log_cb:
                log_cb(f"  Nexa: {p.name} -> {result['category']} "
                       f"({result['confidence']:.0f}%)")
    except Exception as e:
        result['detail'] = f'Inference failed: {e}'
        logger.warning("Nexa file classification failed for %s: %s", p.name, e)

    # Store description for potential tag library use
    result['description'] = description

    return result
