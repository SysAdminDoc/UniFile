"""UniFile — Photo library: face detection, geocoding, blur analysis, HEIC conversion."""
import base64
import io
import json
import os
from functools import lru_cache

from unifile.bootstrap import HAS_CV2, HAS_FACE_RECOGNITION, HAS_PILLOW, HAS_PILLOW_HEIF, HAS_REVERSE_GEOCODER

try:
    from PIL import Image as _PILImage
except ImportError:
    pass
try:
    import cv2 as _cv2
except ImportError:
    pass
try:
    import face_recognition as _face_recognition
    import numpy as _np
except (ImportError, SystemExit):
    # face_recognition calls quit() (SystemExit) at import time when
    # face_recognition_models is missing. Keep the app running.
    _face_recognition = None
try:
    import reverse_geocoder as _rg
except ImportError:
    pass

from unifile.config import _APP_DATA_DIR, _FACE_DB_FILE

_PHOTO_SETTINGS_FILE = os.path.join(_APP_DATA_DIR, 'photo_settings.json')

_PHOTO_DEFAULTS = {
    'enabled': False,
    'folder_preset': 'year_month',
    'geocoding_enabled': True,
    'blur_detection_enabled': True,
    'scene_tagging_enabled': True,
    'enhanced_descriptions': True,
    'blur_threshold': 100.0,
    'face_recognition_enabled': False,
}

_PHOTO_FOLDER_PRESETS = {
    'flat':           {'label': 'Flat (no subfolders)',       'template': ''},
    'year':           {'label': 'Year',                       'template': '{year}/'},
    'year_month':     {'label': 'Year / Month',               'template': '{year}/{month_name}/'},
    'year_month_day': {'label': 'Year / Month / Day',         'template': '{year}/{month_name}/{day}/'},
    'year_city':      {'label': 'Year / City',                'template': '{year}/{city}/'},
    'city_year':      {'label': 'City / Year',                'template': '{city}/{year}/'},
    'scene':          {'label': 'Scene Type',                 'template': '{scene}/'},
    'year_scene':     {'label': 'Year / Scene',               'template': '{year}/{scene}/'},
    'person':         {'label': 'Person',                     'template': '{person}/'},
    'year_person':    {'label': 'Year / Person',              'template': '{year}/{person}/'},
    'person_year':    {'label': 'Person / Year',              'template': '{person}/{year}/'},
}

def load_photo_settings() -> dict:
    try:
        with open(_PHOTO_SETTINGS_FILE) as f:
            s = json.load(f)
        return {**_PHOTO_DEFAULTS, **s}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return dict(_PHOTO_DEFAULTS)

def save_photo_settings(settings: dict):
    try:
        with open(_PHOTO_SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass

# ═══ FACE RECOGNITION DATABASE ═══════════════════════════════════════════════


def load_face_db() -> dict:
    """Load face database from JSON file."""
    try:
        with open(_FACE_DB_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {'faces': {}, 'tolerance': 0.6, 'next_id': 1}


def save_face_db(db: dict):
    """Save face database to JSON file."""
    try:
        with open(_FACE_DB_FILE, 'w') as f:
            json.dump(db, f, indent=2)
    except OSError:
        pass


class FaceDB:
    """Persistent face encoding database with clustering and matching."""

    def __init__(self):
        self._db = load_face_db()
        self._enc_cache = {}  # face_id -> numpy array list

    @property
    def tolerance(self):
        return self._db.get('tolerance', 0.6)

    def set_tolerance(self, val: float):
        self._db['tolerance'] = max(0.3, min(0.9, val))

    def face_count(self) -> int:
        return len(self._db.get('faces', {}))

    def _get_np_encodings(self, face_id: str):
        """Lazy-convert stored lists to numpy arrays."""
        if face_id not in self._enc_cache:
            face = self._db['faces'].get(face_id, {})
            encs = face.get('encodings', [])
            if HAS_FACE_RECOGNITION:
                self._enc_cache[face_id] = [_np.array(e) for e in encs]
            else:
                self._enc_cache[face_id] = []
        return self._enc_cache[face_id]

    def match(self, encoding) -> str:
        """Match a 128-dim encoding against known faces. Returns face_id or ''."""
        if not HAS_FACE_RECOGNITION:
            return ''
        enc_np = _np.array(encoding) if not isinstance(encoding, _np.ndarray) else encoding
        best_id = ''
        best_dist = self.tolerance
        for face_id in self._db.get('faces', {}):
            known = self._get_np_encodings(face_id)
            if not known:
                continue
            distances = _face_recognition.face_distance(known, enc_np)
            min_dist = float(_np.min(distances))
            if min_dist < best_dist:
                best_dist = min_dist
                best_id = face_id
        return best_id

    def add_or_update(self, encoding, thumbnail_b64: str = '') -> str:
        """Match encoding or create new cluster. Returns label string."""
        face_id = self.match(encoding)
        enc_list = encoding.tolist() if hasattr(encoding, 'tolist') else list(encoding)
        if face_id:
            # Add encoding to existing face (cap at 20)
            face = self._db['faces'][face_id]
            if len(face.get('encodings', [])) < 20:
                face['encodings'].append(enc_list)
                if face_id in self._enc_cache:
                    del self._enc_cache[face_id]
            face['sample_count'] = face.get('sample_count', 0) + 1
            if thumbnail_b64 and not face.get('thumbnail'):
                face['thumbnail'] = thumbnail_b64
            return face.get('label', face_id)
        else:
            # Create new face cluster
            nid = self._db.get('next_id', 1)
            face_id = f"face_{nid:04d}"
            self._db['next_id'] = nid + 1
            label = f"Person_{nid}"
            self._db.setdefault('faces', {})[face_id] = {
                'label': label,
                'encodings': [enc_list],
                'thumbnail': thumbnail_b64,
                'sample_count': 1,
            }
            return label

    def rename(self, face_id: str, new_label: str):
        """Rename a face cluster."""
        if face_id in self._db.get('faces', {}):
            self._db['faces'][face_id]['label'] = new_label.strip()

    def delete(self, face_id: str):
        """Delete a face cluster."""
        self._db.get('faces', {}).pop(face_id, None)
        self._enc_cache.pop(face_id, None)

    def get_all_summaries(self) -> list:
        """Return list of dicts: {id, label, sample_count, thumbnail}."""
        result = []
        for fid, data in self._db.get('faces', {}).items():
            result.append({
                'id': fid,
                'label': data.get('label', fid),
                'sample_count': data.get('sample_count', 0),
                'thumbnail': data.get('thumbnail', ''),
            })
        return result

    def save(self):
        save_face_db(self._db)


# ═══ FACE DETECTION HELPERS ═════════════════════════════════════════════════

@lru_cache(maxsize=1)
def _get_haar_face_cascade():
    """LRU-cached Haar cascade loader for face detection fallback."""
    if not HAS_CV2:
        return None
    cascade_path = _cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    cascade = _cv2.CascadeClassifier(cascade_path)
    if cascade.empty():
        return None
    return cascade


def _detect_faces_full(filepath: str, face_db: 'FaceDB') -> dict:
    """Full face recognition via face_recognition library.
    Returns {'face_count': int, 'persons': [str], 'primary_person': str}."""
    try:
        from PIL import Image as _PILImage
        img = _face_recognition.load_image_file(filepath)
        h, w = img.shape[:2]
        max_dim = 1600
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            new_w, new_h = int(w * scale), int(h * scale)
            pil_img = _PILImage.fromarray(img).resize((new_w, new_h), _PILImage.LANCZOS)
            img = _np.array(pil_img)
            h, w = new_h, new_w

        locations = _face_recognition.face_locations(img, model='hog')
        if not locations:
            return {'face_count': 0, 'persons': [], 'primary_person': ''}

        encodings = _face_recognition.face_encodings(img, locations)
        persons = []
        pil_full = _PILImage.fromarray(img)

        for loc, enc in zip(locations, encodings, strict=True):
            # Crop face thumbnail (96x96 JPEG, base64)
            top, right, bottom, left = loc
            pad = int((bottom - top) * 0.2)
            crop_box = (max(0, left - pad), max(0, top - pad),
                        min(w, right + pad), min(h, bottom + pad))
            thumb = pil_full.crop(crop_box).resize((96, 96), _PILImage.LANCZOS)
            buf = io.BytesIO()
            thumb.save(buf, format='JPEG', quality=75)
            thumb_b64 = base64.b64encode(buf.getvalue()).decode('ascii')

            label = face_db.add_or_update(enc, thumb_b64)
            persons.append(label)

        # Primary person = most frequent across scan, fallback to first
        primary = persons[0] if persons else ''
        return {'face_count': len(locations), 'persons': persons, 'primary_person': primary}
    except Exception:
        return {'face_count': 0, 'persons': [], 'primary_person': ''}


def _detect_faces_count_only(filepath: str) -> int:
    """Haar cascade fallback for face count only. Returns count, -1 on error."""
    cascade = _get_haar_face_cascade()
    if cascade is None:
        return -1
    try:
        img = _cv2.imread(filepath)
        if img is None:
            return -1
        h, w = img.shape[:2]
        max_dim = 1024
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            img = _cv2.resize(img, (int(w * scale), int(h * scale)))
        gray = _cv2.cvtColor(img, _cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        return len(faces)
    except Exception:
        return -1


_PHOTO_SCENES = [
    'portrait', 'group_photo', 'selfie', 'landscape', 'cityscape',
    'architecture', 'food', 'pet', 'wildlife', 'macro', 'night',
    'beach', 'mountain', 'sunset', 'event', 'wedding', 'sports',
    'street', 'travel', 'screenshot', 'document', 'art', 'other',
]

@lru_cache(maxsize=2048)
def _reverse_geocode(lat: float, lon: float) -> dict:
    """Reverse geocode GPS coords -> {city, country}. Cached."""
    if not HAS_REVERSE_GEOCODER:
        return {}
    try:
        results = _rg.search(((lat, lon),))
        if results:
            r = results[0]
            return {
                'city': r.get('name', ''),
                'country': r.get('cc', ''),
            }
    except Exception:
        pass
    return {}

def _compute_blur_score(filepath: str) -> float:
    """Compute blur score via Laplacian variance. Lower = blurrier. Returns -1 on error."""
    if not HAS_CV2:
        return -1.0
    try:
        img = _cv2.imread(filepath, _cv2.IMREAD_GRAYSCALE)
        if img is None:
            return -1.0
        h, w = img.shape[:2]
        if max(h, w) > 1024:
            scale = 1024 / max(h, w)
            img = _cv2.resize(img, (int(w * scale), int(h * scale)))
        return float(_cv2.Laplacian(img, _cv2.CV_64F).var())
    except Exception:
        return -1.0


# ── HEIC/WEBP → JPG auto-conversion ─────────────────────────────────────────
def _convert_image_to_jpg(filepath, quality=95, log_cb=None):
    """Convert a HEIC/HEIF/WEBP file to JPG in-place. Returns new path or None."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext in ('.heic', '.heif'):
        if not (HAS_PILLOW and HAS_PILLOW_HEIF):
            return None
    elif ext == '.webp':
        if not HAS_PILLOW:
            return None
    else:
        return None

    stem = os.path.splitext(filepath)[0]
    jpg_path = stem + '.jpg'
    try:
        with _PILImage.open(filepath) as img:
            # Preserve EXIF if present
            exif_data = img.info.get('exif')
            rgb = img.convert('RGB')
            save_kwargs = {'quality': quality}
            if exif_data:
                save_kwargs['exif'] = exif_data
            rgb.save(jpg_path, 'JPEG', **save_kwargs)
        # Remove original after successful conversion
        os.remove(filepath)
        orig_name = os.path.basename(filepath)
        new_name = os.path.basename(jpg_path)
        if log_cb:
            log_cb(f"  [CONVERT] {orig_name} -> {new_name}")
        return jpg_path
    except Exception as exc:
        if log_cb:
            log_cb(f"  [CONVERT-ERR] {os.path.basename(filepath)}: {exc}")
        # Clean up partial jpg if it was created
        if os.path.exists(jpg_path) and os.path.exists(filepath):
            try:
                os.remove(jpg_path)
            except OSError:
                pass
        return None


