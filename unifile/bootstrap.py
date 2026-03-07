"""UniFile — Dependency bootstrap and optional imports."""

#!/usr/bin/env python3
"""UniFile v8.0.0 - Context-Aware Classification + Smart Naming + Photo Library + Face Recognition + HEIC/WEBP Auto-Convert + File Type Filter"""

import sys, os, subprocess, re, shutil, json, csv, hashlib, gzip, sqlite3, time, math, base64, io
import importlib.util
import zipfile
from collections import Counter
from functools import lru_cache
import xml.etree.ElementTree as ET

def _bootstrap():
    """Auto-install dependencies before any imports."""
    # Skip bootstrap inside frozen PyInstaller bundles — all deps are already bundled
    if getattr(sys, 'frozen', False):
        return

    if sys.version_info < (3, 8):
        print("Python 3.8+ required"); sys.exit(1)

    # pip-name → actual import module name (only where they differ)
    _IMPORT_MAP = {
        'Pillow': 'PIL', 'pillow-heif': 'pillow_heif',
        'psd-tools': 'psd_tools', 'python-docx': 'docx',
        'python-pptx': 'pptx', 'opencv-python-headless': 'cv2',
        'requests-cache': 'requests_cache',
    }
    required = ['PyQt6', 'sqlalchemy']
    optional = ['rapidfuzz', 'psd-tools', 'unidecode',
                'Pillow', 'pillow-heif', 'exifread', 'mutagen', 'pypdf', 'python-docx', 'openpyxl',
                'python-pptx', 'reverse_geocoder', 'opencv-python-headless',
                'cmake', 'dlib', 'face_recognition',
                'guessit', 'requests', 'requests-cache', 'babelfish', 'pydantic',
                'platformdirs', 'nexaai']

    # Cache failed optional installs so we don't retry pip every launch (7-day TTL)
    _cache_dir = os.path.join(os.path.expanduser('~'), '.unifile')
    _fail_cache = os.path.join(_cache_dir, 'pip_failed.json')
    _FAIL_TTL = 7 * 86400  # 7 days in seconds
    failed_pkgs = {}  # {pkg_name: timestamp}
    try:
        with open(_fail_cache, 'r') as f:
            raw = json.load(f)
            # Migrate from old list format to {pkg: timestamp} dict
            if isinstance(raw, list):
                failed_pkgs = {p: time.time() for p in raw}
            elif isinstance(raw, dict):
                failed_pkgs = raw
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    # Expire stale entries
    now = time.time()
    failed_pkgs = {p: ts for p, ts in failed_pkgs.items() if now - ts < _FAIL_TTL}

    def _mod_name(pkg):
        return _IMPORT_MAP.get(pkg, pkg.replace('-', '_').lower())

    def _is_installed(pkg):
        return importlib.util.find_spec(_mod_name(pkg)) is not None

    def _try_install(pkg):
        for flags in [[], ['--user'], ['--break-system-packages']]:
            try:
                subprocess.check_call(
                    [sys.executable, '-m', 'pip', 'install', pkg, '-q'] + flags,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except subprocess.CalledProcessError:
                continue
        return False

    for pkg in required:
        if not _is_installed(pkg):
            _try_install(pkg)

    new_failures = {}
    for pkg in optional:
        if _is_installed(pkg):
            continue
        if pkg in failed_pkgs:
            continue  # skip — failed recently
        if not _try_install(pkg):
            new_failures[pkg] = time.time()

    # Persist any new failures
    if new_failures:
        failed_pkgs.update(new_failures)
        try:
            os.makedirs(_cache_dir, exist_ok=True)
            with open(_fail_cache, 'w') as f:
                json.dump(failed_pkgs, f)
        except OSError:
            pass

# Optional imports with graceful fallback
_bootstrap()

try:
    from rapidfuzz import fuzz as _rfuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False

try:
    import psd_tools as _psd_tools
    HAS_PSD_TOOLS = True
except ImportError:
    HAS_PSD_TOOLS = False

try:
    from unidecode import unidecode as _unidecode
    HAS_UNIDECODE = True
except ImportError:
    HAS_UNIDECODE = False

# ── Optional metadata extraction libraries (Phase 1: MetadataExtractor) ──────
try:
    from PIL import Image as _PILImage
    from PIL.ExifTags import TAGS as _EXIF_TAGS, GPSTAGS as _GPS_TAGS
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HAS_PILLOW_HEIF = True
except ImportError:
    HAS_PILLOW_HEIF = False

try:
    import exifread as _exifread
    # Suppress exifread's noisy "File format not recognized" / "does not have exif" warnings
    import logging as _logging
    _logging.getLogger('exifread').setLevel(_logging.CRITICAL)
    HAS_EXIFREAD = True
except ImportError:
    HAS_EXIFREAD = False

try:
    import mutagen as _mutagen
    from mutagen.easyid3 import EasyID3 as _EasyID3
    from mutagen.mp3 import MP3 as _MP3
    from mutagen.flac import FLAC as _FLAC
    from mutagen.mp4 import MP4 as _MP4
    from mutagen.oggvorbis import OggVorbis as _OggVorbis
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False

try:
    from pypdf import PdfReader as _PdfReader
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

try:
    from docx import Document as _DocxDocument
    HAS_PYTHON_DOCX = True
except ImportError:
    HAS_PYTHON_DOCX = False

try:
    from openpyxl import load_workbook as _load_workbook
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

try:
    from pptx import Presentation as _PptxPresentation
    HAS_PYTHON_PPTX = True
except ImportError:
    HAS_PYTHON_PPTX = False

try:
    import magic as _magic
    HAS_MAGIC = True
except ImportError:
    HAS_MAGIC = False

try:
    import reverse_geocoder as _rg
    HAS_REVERSE_GEOCODER = True
except ImportError:
    HAS_REVERSE_GEOCODER = False

try:
    import cv2 as _cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    import face_recognition as _face_recognition
    import numpy as _np
    HAS_FACE_RECOGNITION = True
except ImportError:
    HAS_FACE_RECOGNITION = False

try:
    import rarfile as _rarfile
    HAS_RARFILE = True
except ImportError:
    HAS_RARFILE = False

try:
    import py7zr as _py7zr
    HAS_PY7ZR = True
except ImportError:
    HAS_PY7ZR = False


import mimetypes as _mimetypes
