"""UniFile -- Audio transcription via Whisper for content-based classification."""
import os
import json
import hashlib
from pathlib import Path

from unifile.config import _APP_DATA_DIR

_TRANSCRIPTION_CACHE_DIR = os.path.join(_APP_DATA_DIR, 'transcriptions')
os.makedirs(_TRANSCRIPTION_CACHE_DIR, exist_ok=True)

_AUDIO_EXTENSIONS = {
    '.mp3', '.wav', '.flac', '.m4a', '.ogg', '.opus', '.wma', '.aac',
    '.mp4', '.mkv', '.avi', '.mov', '.webm',  # video files (audio track)
}

# Whisper model sizes ordered by speed/quality tradeoff
WHISPER_MODELS = {
    'tiny': 'Tiny (~39M params, fastest, least accurate)',
    'base': 'Base (~74M params, fast, decent accuracy)',
    'small': 'Small (~244M params, balanced)',
    'medium': 'Medium (~769M params, good accuracy)',
    'large-v3': 'Large v3 (~1.5B params, best accuracy)',
}


def _file_hash(filepath: str) -> str:
    """Quick hash for cache key based on filename + size + mtime."""
    try:
        stat = os.stat(filepath)
        raw = f"{filepath}|{stat.st_size}|{stat.st_mtime}"
        return hashlib.md5(raw.encode()).hexdigest()
    except OSError:
        return hashlib.md5(filepath.encode()).hexdigest()


def _get_cached_transcription(filepath: str) -> str | None:
    """Check if we have a cached transcription."""
    cache_key = _file_hash(filepath)
    cache_file = os.path.join(_TRANSCRIPTION_CACHE_DIR, f"{cache_key}.json")
    if os.path.isfile(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('text', '')
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _save_transcription(filepath: str, text: str, language: str = "",
                        duration: float = 0):
    """Save transcription to cache."""
    cache_key = _file_hash(filepath)
    cache_file = os.path.join(_TRANSCRIPTION_CACHE_DIR, f"{cache_key}.json")
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump({
                'file': os.path.basename(filepath),
                'text': text,
                'language': language,
                'duration': duration,
            }, f, indent=2)
    except OSError:
        pass


def is_audio_file(filepath: str) -> bool:
    """Check if a file is an audio/video file we can transcribe."""
    return os.path.splitext(filepath)[1].lower() in _AUDIO_EXTENSIONS


class WhisperTranscriber:
    """Audio/video transcription using OpenAI's Whisper model."""

    def __init__(self, model_size: str = "base"):
        self._model_size = model_size
        self._model = None
        self._available = None

    @property
    def is_available(self) -> bool:
        """Check if Whisper is installed."""
        if self._available is None:
            try:
                import whisper
                self._available = True
            except ImportError:
                self._available = False
        return self._available

    def _ensure_model(self):
        """Load Whisper model on first use."""
        if self._model is None and self.is_available:
            import whisper
            self._model = whisper.load_model(self._model_size)

    def transcribe(self, filepath: str, language: str | None = None,
                   max_duration: int = 600) -> dict:
        """Transcribe an audio/video file.

        Args:
            filepath: Path to audio/video file.
            language: Language hint (e.g., 'en'). None for auto-detect.
            max_duration: Skip files longer than this (seconds).

        Returns:
            dict with 'text', 'language', 'duration', 'segments', 'cached'
        """
        # Check cache first
        cached = _get_cached_transcription(filepath)
        if cached is not None:
            return {'text': cached, 'language': '', 'duration': 0,
                    'segments': [], 'cached': True}

        if not self.is_available:
            return {'text': '', 'language': '', 'duration': 0,
                    'segments': [], 'error': 'whisper not installed'}

        self._ensure_model()

        try:
            opts = {'fp16': False}
            if language:
                opts['language'] = language

            result = self._model.transcribe(filepath, **opts)
            text = result.get('text', '').strip()
            lang = result.get('language', '')
            segments = result.get('segments', [])
            duration = segments[-1]['end'] if segments else 0

            # Cache the transcription
            _save_transcription(filepath, text, lang, duration)

            return {
                'text': text,
                'language': lang,
                'duration': duration,
                'segments': segments[:20],  # keep first 20 segments for display
                'cached': False,
            }
        except Exception as e:
            return {'text': '', 'language': '', 'duration': 0,
                    'segments': [], 'error': str(e)}

    def transcribe_for_classification(self, filepath: str) -> str:
        """Get a short text excerpt from audio for classification purposes.

        Returns just the first ~500 chars of transcription,
        suitable for passing to a classification LLM.
        """
        result = self.transcribe(filepath)
        text = result.get('text', '')
        return text[:500] if text else ''

    def clear_cache(self):
        """Clear all cached transcriptions."""
        for f in Path(_TRANSCRIPTION_CACHE_DIR).glob('*.json'):
            try:
                f.unlink()
            except OSError:
                pass


# Module-level singleton
_transcriber: WhisperTranscriber | None = None


def get_transcriber(model_size: str = "base") -> WhisperTranscriber:
    """Get the singleton WhisperTranscriber instance."""
    global _transcriber
    if _transcriber is None or _transcriber._model_size != model_size:
        _transcriber = WhisperTranscriber(model_size)
    return _transcriber
