"""UniFile — Dependency bootstrap and optional imports."""

#!/usr/bin/env python3
"""UniFile v9.3.33 - Context-Aware Classification + Smart Naming + Photo Library + Face Recognition + HEIC/WEBP Auto-Convert + File Type Filter"""

import base64
import csv
import gzip
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from contextlib import redirect_stdout
from functools import lru_cache
from importlib import metadata as importlib_metadata

_AUTO_INSTALL_ENV = "UNIFILE_INSTALL_DEPS"
_TRUE_VALUES = {"1", "true", "yes", "on"}


def auto_install_enabled() -> bool:
    """Return True only when dependency installation was explicitly requested."""
    return os.environ.get(_AUTO_INSTALL_ENV, "").strip().lower() in _TRUE_VALUES


def _bootstrap():
    """Optionally install dependencies before optional imports.

    Importing UniFile modules must never mutate a user's Python environment by
    default. Source users can opt in with UNIFILE_INSTALL_DEPS=1 or the
    run.py / unifile --install-deps flag.
    """
    # Skip bootstrap inside frozen PyInstaller bundles — all deps are already bundled
    if getattr(sys, 'frozen', False):
        return

    # Friendly error for source-run users on older Python (pip enforces this via
    # requires-python, but git-clone users don't hit that gate).
    if sys.version_info < (3, 10):  # noqa: UP036
        print("Python 3.10+ required"); sys.exit(1)

    if not auto_install_enabled():
        return

    # pip-name → actual import module name (only where they differ)
    _IMPORT_MAP = {
        'pyqt6': 'PyQt6',
        'pillow': 'PIL',
        'pillow-heif': 'pillow_heif',
        'psd-tools': 'psd_tools',
        'python-docx': 'docx',
        'python-pptx': 'pptx',
        'opencv-python-headless': 'cv2',
        'requests-cache': 'requests_cache',
        'pyyaml': 'yaml',
        'pyacoustid': 'acoustid',
        'pymupdf': 'fitz',
        'pdfminer.six': 'pdfminer',
        'tomli-w': 'tomli_w',
        'isbnlib2': 'isbnlib',
    }
    required = ['PyQt6>=6.5', 'SQLAlchemy>=2.0', 'keyring>=25.7.0']
    optional = [
        'Pillow>=12.2.0', 'piexif>=1.1.3', 'pillow-heif>=1.4.0', 'exifread>=3.5.1',
        'mutagen>=1.48.1', 'pypdf>=6.14.2', 'python-docx>=1.2.0',
        'python-pptx>=1.0.2', 'openpyxl>=3.1.5', 'psd-tools>=1.17.4',
        'rarfile>=4.2', 'py7zr>=1.1.3', 'rapidfuzz>=3.14.5',
        'unidecode>=1.4.0', 'reverse_geocoder>=1.5.1',
        'opencv-python-headless>=4.13.0.92', 'send2trash>=2.1.0',
        'guessit>=4.0.2', 'requests>=2.34.2', 'requests-cache>=1.3.2',
        'Flask>=3.1.0',
        'babelfish>=0.6.1', 'pydantic>=2.13.4', 'platformdirs>=4.10.0',
        'PyYAML>=6.0.3', 'tomli>=2.4.1', 'tomli-w>=1.2.0',
        'pyacoustid>=1.3.1', 'musicbrainzngs>=0.7.1', 'pytesseract>=0.3.13',
        'easyocr>=1.7.2', 'pdfminer.six>=20260107', 'pymupdf>=1.28.0',
        'pdf2image>=1.17.0', 'cmake', 'dlib', 'face_recognition', 'nexaai',
        'isbnlib2>=3.11.7',
    ]

    # Cache failed optional installs so we don't retry pip every launch (7-day TTL)
    _cache_dir = os.path.join(os.path.expanduser('~'), '.unifile')
    _fail_cache = os.path.join(_cache_dir, 'pip_failed.json')
    _FAIL_TTL = 7 * 86400  # 7 days in seconds
    failed_pkgs = {}  # {pkg_name: timestamp}
    try:
        with open(_fail_cache) as f:
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

    def _pkg_name(pkg):
        match = re.match(r"\s*([A-Za-z0-9_.-]+)", pkg)
        return (match.group(1) if match else pkg).lower().replace("_", "-")

    def _mod_name(pkg):
        name = _pkg_name(pkg)
        return _IMPORT_MAP.get(name, name.replace('-', '_').lower())

    def _min_version(pkg):
        match = re.search(r">=\s*([0-9][A-Za-z0-9_.!+-]*)", pkg)
        return match.group(1) if match else ""

    def _version_parts(version):
        parts = [int(part) for part in re.findall(r"\d+", version)]
        return tuple(parts or [0])

    def _version_at_least(installed, minimum):
        installed_parts = _version_parts(installed)
        minimum_parts = _version_parts(minimum)
        width = max(len(installed_parts), len(minimum_parts))
        return installed_parts + (0,) * (width - len(installed_parts)) >= minimum_parts + (0,) * (
            width - len(minimum_parts)
        )

    def _is_installed(pkg):
        if importlib.util.find_spec(_mod_name(pkg)) is None:
            return False
        minimum = _min_version(pkg)
        if not minimum:
            return True
        try:
            installed = importlib_metadata.version(_pkg_name(pkg))
        except importlib_metadata.PackageNotFoundError:
            return True
        return _version_at_least(installed, minimum)

    def _try_install(pkg):
        for flags in [[], ['--user']]:
            try:
                subprocess.check_call(
                    [sys.executable, '-m', 'pip', 'install', pkg, '-q'] + flags,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except subprocess.CalledProcessError:
                continue
        import logging
        logging.getLogger(__name__).warning(
            "Could not install %s. If using an externally managed Python, "
            "install it inside a virtualenv or with pipx.", pkg)
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
    from PIL.ExifTags import GPSTAGS as _GPS_TAGS
    from PIL.ExifTags import TAGS as _EXIF_TAGS
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
    # Suppress exifread's noisy "File format not recognized" / "does not have exif" warnings
    import logging as _logging

    import exifread as _exifread
    _logging.getLogger('exifread').setLevel(_logging.CRITICAL)
    HAS_EXIFREAD = True
except ImportError:
    HAS_EXIFREAD = False

try:
    import mutagen as _mutagen
    from mutagen.easyid3 import EasyID3 as _EasyID3
    from mutagen.flac import FLAC as _FLAC
    from mutagen.mp3 import MP3 as _MP3
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
    # face_recognition prints a missing-model installation hint to stdout
    # before raising SystemExit.  Keep headless JSON stdout machine-readable.
    with redirect_stdout(io.StringIO()):
        import face_recognition as _face_recognition
        import numpy as _np
    HAS_FACE_RECOGNITION = True
except (ImportError, SystemExit):
    # face_recognition calls quit() (SystemExit) when face_recognition_models is not installed
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
