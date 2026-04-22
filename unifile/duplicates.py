"""UniFile — Duplicate detection: perceptual hash, BK-tree, progressive dedup,
audio fingerprinting, and similar-content detection.

Inspired by Czkawka, Duplicate Cleaner Pro, dupeGuru, and pHash."""
import os, hashlib, math, subprocess, struct
from pathlib import Path
from collections import Counter, defaultdict

from unifile.bootstrap import HAS_PILLOW, HAS_CV2
try:
    from PIL import Image as _PILImage
except ImportError:
    pass
try:
    import cv2 as _cv2
except ImportError:
    pass

from unifile.cache import hash_file

# ── Audio fingerprint support (optional: chromaprint/fpcalc) ─────────────────
_HAS_FPCALC = None  # lazy-detected

def _find_fpcalc() -> str:
    """Find the fpcalc binary (Chromaprint CLI). Returns path or empty string."""
    global _HAS_FPCALC
    if _HAS_FPCALC is not None:
        return _HAS_FPCALC

    # Try common locations
    import shutil
    fpcalc = shutil.which('fpcalc')
    if fpcalc:
        _HAS_FPCALC = fpcalc
        return fpcalc

    # Windows: check common install paths
    import sys
    if sys.platform == 'win32':
        for candidate in [
            os.path.expandvars(r'%LOCALAPPDATA%\fpcalc\fpcalc.exe'),
            os.path.expandvars(r'%PROGRAMFILES%\Chromaprint\fpcalc.exe'),
            os.path.join(os.path.dirname(sys.executable), 'fpcalc.exe'),
        ]:
            if os.path.isfile(candidate):
                _HAS_FPCALC = candidate
                return candidate

    _HAS_FPCALC = ''
    return ''


def _audio_fingerprint(filepath: str, duration: int = 120) -> tuple:
    """Compute audio fingerprint using Chromaprint/fpcalc.
    Returns (duration_secs, fingerprint_list) or (0, []) on failure."""
    fpcalc = _find_fpcalc()
    if not fpcalc:
        return (0, [])
    try:
        result = subprocess.run(
            [fpcalc, '-raw', '-length', str(duration), filepath],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        )
        if result.returncode != 0:
            return (0, [])

        dur = 0
        fp_data = []
        for line in result.stdout.strip().split('\n'):
            if line.startswith('DURATION='):
                dur = int(line.split('=', 1)[1])
            elif line.startswith('FINGERPRINT='):
                fp_data = [int(x) for x in line.split('=', 1)[1].split(',') if x.strip()]
        return (dur, fp_data)
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError, OSError):
        return (0, [])


def _fingerprint_similarity(fp1: list, fp2: list) -> float:
    """Compare two Chromaprint fingerprints. Returns similarity 0.0-1.0.
    Uses popcount of XOR to compute bit-level similarity (like Hamming distance)."""
    if not fp1 or not fp2:
        return 0.0
    # Compare overlapping portion
    length = min(len(fp1), len(fp2))
    if length == 0:
        return 0.0

    total_bits = length * 32
    diff_bits = 0
    for i in range(length):
        xor = fp1[i] ^ fp2[i]
        # Popcount
        diff_bits += bin(xor & 0xFFFFFFFF).count('1')

    return 1.0 - (diff_bits / total_bits)


AUDIO_EXTS = {'.mp3', '.flac', '.wav', '.ogg', '.m4a', '.aac', '.wma',
              '.opus', '.ape', '.aiff', '.aif'}

# ── Perceptual Hash Deduplication ────────────────────────────────────────────

def _compute_phash(filepath: str, hash_size: int = 8) -> str:
    """Compute perceptual hash of an image using average hash algorithm.
    Pure Python implementation using PIL - no heavy ML dependencies.
    Returns hex string of the hash, or empty string on failure."""
    try:
        from PIL import Image
        # `with` guarantees the underlying file handle is closed. Critical on
        # Windows where lingering handles block subsequent move/rename ops.
        with Image.open(filepath) as img:
            if img.mode == 'P' and 'transparency' in img.info:
                img = img.convert('RGBA')
            img = img.convert('L').resize((hash_size + 1, hash_size), Image.LANCZOS)
            pixels = list(img.getdata())
        # Difference hash (dHash): compare adjacent pixels
        bits = []
        for row in range(hash_size):
            for col in range(hash_size):
                bits.append(pixels[row * (hash_size + 1) + col] < pixels[row * (hash_size + 1) + col + 1])
        return ''.join('1' if b else '0' for b in bits)
    except Exception:
        return ''

def _hamming_distance(hash1: str, hash2: str) -> int:
    """Compute Hamming distance between two binary hash strings."""
    if len(hash1) != len(hash2):
        return 999
    return sum(c1 != c2 for c1, c2 in zip(hash1, hash2))

class _BKTree:
    """BK-tree for efficient nearest-neighbor search under Hamming distance.
    Reduces O(n²) all-pairs comparison to ~O(n log n) for sparse matches."""

    def __init__(self, distance_fn):
        self._dist = distance_fn
        self._root = None  # (item, {distance: child_node})

    def insert(self, item):
        if self._root is None:
            self._root = (item, {})
            return
        node = self._root
        while True:
            d = self._dist(item, node[0])
            if d in node[1]:
                node = node[1][d]
            else:
                node[1][d] = (item, {})
                return

    def query(self, item, threshold):
        """Return all items within `threshold` distance of `item`."""
        if self._root is None:
            return []
        results = []
        stack = [self._root]
        while stack:
            node = stack.pop()
            d = self._dist(item, node[0])
            if d <= threshold:
                results.append((node[0], d))
            for edge_d, child in node[1].items():
                if d - threshold <= edge_d <= d + threshold:
                    stack.append(child)
        return results


IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tif', '.tiff', '.webp'}
_PHASH_IMAGE_EXTS = IMAGE_EXTS | {'.heic', '.heif', '.avif', '.jxl'}


class ProgressiveDuplicateDetector:
    """Multi-stage duplicate detection pipeline for files.

    Stage 1: Group by file size (zero I/O — eliminates ~80-95% of candidates)
    Stage 2: Hash first 64KB of each file (prefix hash)
    Stage 3: Hash last 64KB of each file (suffix hash)
    Stage 4: Full SHA-256 content hash for final confirmation
    Stage 5 (optional): Perceptual hash for image near-duplicates

    Results:
        dup_map:  {filepath: DupInfo} where DupInfo has group_id, is_original, detail
    """

    PARTIAL_SIZE = 65536   # 64KB prefix/suffix
    PHASH_THRESHOLD = 4    # Hamming distance ≤4 = near-duplicate

    class DupInfo:
        __slots__ = ('group_id', 'is_original', 'detail', 'is_perceptual')
        def __init__(self, group_id=0, is_original=True, detail='', is_perceptual=False):
            self.group_id = group_id
            self.is_original = is_original
            self.detail = detail
            self.is_perceptual = is_perceptual

    AUDIO_SIM_THRESHOLD = 0.85  # 85% fingerprint similarity = duplicate audio

    def __init__(self, enable_perceptual=True, enable_audio=True, phash_threshold=4):
        self.enable_perceptual = enable_perceptual and HAS_PILLOW
        self.enable_audio = enable_audio
        self.phash_threshold = phash_threshold
        self.dup_map = {}        # filepath → DupInfo
        self._group_counter = 0

    def _next_group(self) -> int:
        self._group_counter += 1
        return self._group_counter

    def detect(self, file_entries: list, log_cb=None, progress_cb=None) -> dict:
        """Run the full progressive pipeline on a list of (Path, size) tuples.

        Args:
            file_entries: list of (filepath_str, file_size) for files only (no folders)
            log_cb:       optional logging callback
            progress_cb:  optional (current, total) progress callback

        Returns:
            dict mapping filepath → DupInfo for ALL duplicates found.
            Files not in the dict are unique.
        """
        self.dup_map.clear()
        self._group_counter = 0

        if len(file_entries) < 2:
            return self.dup_map

        # ── Stage 1: Group by size ───────────────────────────────────────────
        if log_cb:
            log_cb(f"  [DEDUP] Stage 1: Grouping {len(file_entries)} files by size…")
        size_groups = {}
        for fpath, fsize in file_entries:
            if fsize > 0:
                size_groups.setdefault(fsize, []).append(fpath)

        # Eliminate unique sizes
        candidates = {sz: paths for sz, paths in size_groups.items() if len(paths) > 1}
        n_candidates = sum(len(p) for p in candidates.values())
        n_eliminated = len(file_entries) - n_candidates
        if log_cb:
            log_cb(f"  [DEDUP] Stage 1: {n_eliminated} unique sizes eliminated, "
                   f"{n_candidates} candidates in {len(candidates)} size groups")
        if not candidates:
            self._run_perceptual(file_entries, log_cb)
            self._run_audio_fingerprint(file_entries, log_cb)
            return self.dup_map

        # ── Stage 2: Prefix hash (first 64KB) ───────────────────────────────
        if log_cb:
            log_cb(f"  [DEDUP] Stage 2: Prefix hash ({n_candidates} files)…")
        prefix_groups = {}
        step = 0
        for sz, paths in candidates.items():
            bucket = {}
            for fpath in paths:
                step += 1
                if progress_cb:
                    progress_cb(step, n_candidates)
                h = self._hash_partial(fpath, offset=0, size=min(self.PARTIAL_SIZE, sz))
                if h:
                    bucket.setdefault(h, []).append(fpath)
            for h, group_paths in bucket.items():
                if len(group_paths) > 1:
                    prefix_groups[(sz, h)] = group_paths

        n_prefix = sum(len(p) for p in prefix_groups.values())
        if log_cb:
            log_cb(f"  [DEDUP] Stage 2: {n_prefix} files share prefix hashes")
        if not prefix_groups:
            self._run_perceptual(file_entries, log_cb)
            self._run_audio_fingerprint(file_entries, log_cb)
            return self.dup_map

        # ── Stage 3: Suffix hash (last 64KB) ────────────────────────────────
        if log_cb:
            log_cb(f"  [DEDUP] Stage 3: Suffix hash ({n_prefix} files)…")
        suffix_groups = {}
        for (sz, ph), paths in prefix_groups.items():
            if sz <= self.PARTIAL_SIZE:
                # File is small enough that prefix covered entire file — already confirmed
                suffix_groups[(sz, ph, 'full')] = paths
                continue
            bucket = {}
            for fpath in paths:
                h = self._hash_partial(fpath, offset=max(0, sz - self.PARTIAL_SIZE),
                                       size=self.PARTIAL_SIZE)
                if h:
                    bucket.setdefault(h, []).append(fpath)
            for sh, group_paths in bucket.items():
                if len(group_paths) > 1:
                    suffix_groups[(sz, ph, sh)] = group_paths

        n_suffix = sum(len(p) for p in suffix_groups.values())
        if log_cb:
            log_cb(f"  [DEDUP] Stage 3: {n_suffix} files share prefix+suffix hashes")
        if not suffix_groups:
            self._run_perceptual(file_entries, log_cb)
            self._run_audio_fingerprint(file_entries, log_cb)
            return self.dup_map

        # ── Stage 4: Full content hash ───────────────────────────────────────
        if log_cb:
            log_cb(f"  [DEDUP] Stage 4: Full SHA-256 ({n_suffix} files)…")
        full_groups = {}
        for key, paths in suffix_groups.items():
            sz = key[0]
            if sz <= self.PARTIAL_SIZE:
                # Prefix hash already covered entire file — no need to re-hash
                full_groups[key] = paths
                continue
            bucket = {}
            for fpath in paths:
                h = self._hash_full(fpath)
                if h:
                    bucket.setdefault(h, []).append(fpath)
            for fh, group_paths in bucket.items():
                if len(group_paths) > 1:
                    full_groups[fh] = group_paths

        # ── Assign groups ────────────────────────────────────────────────────
        total_dup_files = 0
        for fh, paths in full_groups.items():
            gid = self._next_group()
            # First file is the "original" (keep), rest are duplicates
            # Sort by mtime descending — newest is "original"
            try:
                paths_sorted = sorted(paths, key=lambda p: os.path.getmtime(p), reverse=True)
            except OSError:
                paths_sorted = paths
            for i, fpath in enumerate(paths_sorted):
                is_orig = (i == 0)
                detail = (f"Group {gid}: original (newest)" if is_orig
                          else f"Group {gid}: duplicate of {os.path.basename(paths_sorted[0])}")
                self.dup_map[fpath] = self.DupInfo(
                    group_id=gid, is_original=is_orig, detail=detail)
                if not is_orig:
                    total_dup_files += 1

        if log_cb:
            n_groups = len(full_groups)
            log_cb(f"  [DEDUP] Stage 4: {n_groups} duplicate groups, "
                   f"{total_dup_files} duplicate files")

        # ── Stage 5: Perceptual image hashing ────────────────────────────────
        self._run_perceptual(file_entries, log_cb)

        # ── Stage 6: Audio fingerprinting (Chromaprint) ──────────────────────
        self._run_audio_fingerprint(file_entries, log_cb)

        return self.dup_map

    def _run_perceptual(self, file_entries: list, log_cb=None):
        """Stage 5: Find near-duplicate images via perceptual hashing."""
        if not self.enable_perceptual:
            return
        # Collect image files not already flagged as exact duplicates
        images = [(fp, sz) for fp, sz in file_entries
                  if os.path.splitext(fp)[1].lower() in _PHASH_IMAGE_EXTS
                  and fp not in self.dup_map]
        if len(images) < 2:
            return
        if log_cb:
            log_cb(f"  [DEDUP] Stage 5: Perceptual hashing {len(images)} images…")

        # Compute dHash for each image
        phashes = {}
        for fpath, _ in images:
            ph = _compute_phash(fpath)
            if ph:
                phashes[fpath] = ph

        if len(phashes) < 2:
            return

        # BK-tree for efficient nearest-neighbor search — O(n log n) vs O(n²)
        paths = list(phashes.keys())
        tree = _BKTree(lambda a, b: _hamming_distance(phashes[a], phashes[b]))
        for p in paths:
            tree.insert(p)

        perceptual_groups = {}   # group of paths that are near-duplicates
        assigned = set()

        for p in paths:
            if p in assigned:
                continue
            neighbors = tree.query(p, self.phash_threshold)
            group = [item for item, dist in neighbors if item not in assigned or item == p]
            if len(group) > 1:
                assigned.update(group)
                perceptual_groups[p] = group

        # Assign perceptual duplicate groups
        n_perceptual = 0
        for anchor, group in perceptual_groups.items():
            gid = self._next_group()
            # Keep the largest file as original
            try:
                group_sorted = sorted(group, key=lambda p: os.path.getsize(p), reverse=True)
            except OSError:
                group_sorted = group
            for i, fpath in enumerate(group_sorted):
                is_orig = (i == 0)
                detail = (f"Group {gid} (visual): original (largest)" if is_orig
                          else f"Group {gid} (visual): near-duplicate of "
                               f"{os.path.basename(group_sorted[0])}")
                self.dup_map[fpath] = self.DupInfo(
                    group_id=gid, is_original=is_orig, detail=detail,
                    is_perceptual=True)
                if not is_orig:
                    n_perceptual += 1

        if log_cb and n_perceptual > 0:
            log_cb(f"  [DEDUP] Stage 5: {n_perceptual} near-duplicate images found")

    def _run_audio_fingerprint(self, file_entries: list, log_cb=None):
        """Stage 6: Find similar audio files via Chromaprint acoustic fingerprinting."""
        if not self.enable_audio:
            return
        if not _find_fpcalc():
            if log_cb:
                log_cb("  [DEDUP] Stage 6: Skipped (fpcalc not found — install Chromaprint)")
            return

        # Collect audio files not already flagged as exact duplicates
        audio_files = [(fp, sz) for fp, sz in file_entries
                       if os.path.splitext(fp)[1].lower() in AUDIO_EXTS
                       and fp not in self.dup_map]
        if len(audio_files) < 2:
            return
        if log_cb:
            log_cb(f"  [DEDUP] Stage 6: Audio fingerprinting {len(audio_files)} files…")

        # Compute fingerprints
        fingerprints = {}
        for fpath, _ in audio_files:
            dur, fp = _audio_fingerprint(fpath)
            if fp and dur > 5:  # skip very short clips
                fingerprints[fpath] = (dur, fp)

        if len(fingerprints) < 2:
            return

        # Compare all pairs (audio collections are typically smaller than image sets)
        paths = list(fingerprints.keys())
        assigned = set()
        n_audio_dups = 0

        # Group by similar duration first to reduce comparisons
        dur_buckets = defaultdict(list)
        for fpath, (dur, fp) in fingerprints.items():
            bucket = dur // 10  # 10-second buckets
            dur_buckets[bucket].append(fpath)
            # Also add to adjacent buckets for edge cases
            dur_buckets[bucket - 1].append(fpath)
            dur_buckets[bucket + 1].append(fpath)

        compared = set()
        for bucket_paths in dur_buckets.values():
            for i in range(len(bucket_paths)):
                for j in range(i + 1, len(bucket_paths)):
                    p1, p2 = bucket_paths[i], bucket_paths[j]
                    pair_key = (min(p1, p2), max(p1, p2))
                    if pair_key in compared or p1 in assigned or p2 in assigned:
                        continue
                    compared.add(pair_key)

                    sim = _fingerprint_similarity(
                        fingerprints[p1][1], fingerprints[p2][1])
                    if sim >= self.AUDIO_SIM_THRESHOLD:
                        gid = self._next_group()
                        # Keep larger file as original
                        try:
                            sz1, sz2 = os.path.getsize(p1), os.path.getsize(p2)
                        except OSError:
                            sz1, sz2 = 0, 0
                        orig, dup = (p1, p2) if sz1 >= sz2 else (p2, p1)

                        self.dup_map[orig] = self.DupInfo(
                            group_id=gid, is_original=True,
                            detail=f"Group {gid} (audio): original (largest)",
                            is_perceptual=True)
                        self.dup_map[dup] = self.DupInfo(
                            group_id=gid, is_original=False,
                            detail=f"Group {gid} (audio {sim:.0%} match): "
                                   f"similar to {os.path.basename(orig)}",
                            is_perceptual=True)
                        assigned.update({p1, p2})
                        n_audio_dups += 1

        if log_cb and n_audio_dups > 0:
            log_cb(f"  [DEDUP] Stage 6: {n_audio_dups} similar audio pairs found")

    @staticmethod
    def _hash_partial(filepath: str, offset: int, size: int) -> str:
        """Hash a portion of a file. Returns hex digest or None."""
        try:
            h = hashlib.sha256()
            with open(filepath, 'rb') as f:
                f.seek(offset)
                remaining = size
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    h.update(chunk)
                    remaining -= len(chunk)
            return h.hexdigest()
        except (PermissionError, OSError):
            return None

    @staticmethod
    def _hash_full(filepath: str) -> str:
        """Full SHA-256 hash of a file. Returns hex digest or None."""
        try:
            h = hashlib.sha256()
            with open(filepath, 'rb') as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()
        except (PermissionError, OSError):
            return None


# ══════════════════════════════════════════════════════════════════════════════
# CONFLICT RESOLUTION ENGINE
# Detects destination path collisions and resolves them via configurable strategy.
# ══════════════════════════════════════════════════════════════════════════════

class ConflictResolver:
    """Detects and resolves destination path conflicts among FileItems."""

    STRATEGIES = ('auto_suffix', 'keep_newest', 'keep_largest', 'skip')

    @staticmethod
    def detect(items) -> dict:
        """Return {dest_path: [list of FileItems]} for paths with >1 item."""
        by_dest = {}
        for it in items:
            if not it.selected or it.status != "Pending":
                continue
            dp = it.full_dst.lower() if it.full_dst else ''
            if dp:
                by_dest.setdefault(dp, []).append(it)
        return {k: v for k, v in by_dest.items() if len(v) > 1}

    @staticmethod
    def resolve(conflicts: dict, strategy: str, items: list) -> int:
        """Resolve conflicts. Returns count of adjustments made."""
        count = 0
        for dest_path, dupes in conflicts.items():
            if strategy == 'auto_suffix':
                # Keep first, suffix the rest
                for i, it in enumerate(dupes[1:], start=1):
                    stem, ext = os.path.splitext(it.full_dst)
                    it.full_dst = f"{stem}_{i:03d}{ext}"
                    it.display_name = os.path.basename(it.full_dst)
                    count += 1
            elif strategy == 'keep_newest':
                # Sort by mtime descending, deselect all but newest
                ranked = sorted(dupes, key=lambda x: os.path.getmtime(x.full_src)
                                if os.path.exists(x.full_src) else 0, reverse=True)
                for it in ranked[1:]:
                    it.selected = False
                    it.detail = "Conflict: kept newest"
                    count += 1
            elif strategy == 'keep_largest':
                ranked = sorted(dupes, key=lambda x: x.size, reverse=True)
                for it in ranked[1:]:
                    it.selected = False
                    it.detail = "Conflict: kept largest"
                    count += 1
            elif strategy == 'skip':
                for it in dupes[1:]:
                    it.selected = False
                    it.detail = "Conflict: skipped"
                    count += 1
        return count


