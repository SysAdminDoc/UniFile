"""UniFile — Rule engine, event grouping, scheduling, rename templates."""
import os, re, json, math, subprocess, sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from unifile.config import _APP_DATA_DIR

_RULES_FILE = os.path.join(_APP_DATA_DIR, 'rules.json')


def _parse_naive_dt(s: str) -> datetime:
    """Parse an ISO-format datetime string, stripping any timezone offset."""
    s = s.strip()
    s = re.sub(r'[Zz]$', '', s)
    s = re.sub(r'[+-]\d{2}:?\d{2}$', '', s).strip()
    return datetime.fromisoformat(s)


def _safe_regex_match(pattern: str, value: str) -> bool:
    """Match a regex pattern against value, returning False on invalid patterns."""
    try:
        return bool(re.search(pattern, value, re.IGNORECASE))
    except re.error:
        return False

class RuleEngine:
    """User-defined classification rules with priority ordering."""

    _OPS = {
        'eq': lambda a, b: str(a).lower() == str(b).lower(),
        'neq': lambda a, b: str(a).lower() != str(b).lower(),
        'gt': lambda a, b: float(a) > float(b),
        'lt': lambda a, b: float(a) < float(b),
        'gte': lambda a, b: float(a) >= float(b),
        'lte': lambda a, b: float(a) <= float(b),
        'contains': lambda a, b: str(b).lower() in str(a).lower(),
        'not_contains': lambda a, b: str(b).lower() not in str(a).lower(),
        'matches': lambda a, b: _safe_regex_match(b, str(a)),
        'startswith': lambda a, b: str(a).lower().startswith(str(b).lower()),
        'endswith': lambda a, b: str(a).lower().endswith(str(b).lower()),
        'older_than_days': lambda a, b: (
            datetime.now() - _parse_naive_dt(str(a)) > timedelta(days=int(b))
            if a else False
        ),
        'newer_than_days': lambda a, b: (
            datetime.now() - _parse_naive_dt(str(a)) < timedelta(days=int(b))
            if a else False
        ),
        'size_gt_mb': lambda a, b: float(a) > float(b) * 1024 * 1024,
        'size_lt_mb': lambda a, b: float(a) < float(b) * 1024 * 1024,
        'in_list': lambda a, b: str(a).lower() in [x.strip().lower() for x in str(b).split(',')],
        'not_in_list': lambda a, b: str(a).lower() not in [x.strip().lower() for x in str(b).split(',')],
    }

    @staticmethod
    def load_rules() -> list:
        if os.path.isfile(_RULES_FILE):
            try:
                with open(_RULES_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    @staticmethod
    def save_rules(rules: list):
        with open(_RULES_FILE, 'w', encoding='utf-8') as f:
            json.dump(rules, f, indent=2)

    @staticmethod
    def _get_field_value(item, field: str, metadata: dict):
        """Extract field value from FileItem or metadata."""
        if field == 'name':
            return getattr(item, 'name', '')
        elif field == 'extension':
            return os.path.splitext(getattr(item, 'name', ''))[1].lower()
        elif field == 'size':
            return getattr(item, 'size', 0)
        elif field == 'modified_date':
            try:
                return datetime.fromtimestamp(os.path.getmtime(item.full_src)).isoformat()
            except Exception:
                return ''
        elif field == 'created_date':
            try:
                return datetime.fromtimestamp(os.path.getctime(item.full_src)).isoformat()
            except Exception:
                return ''
        elif field == 'path_contains':
            return getattr(item, 'full_src', '')
        elif field == 'name_regex':
            return getattr(item, 'name', '')
        else:
            return metadata.get(field, '')

    @classmethod
    def evaluate(cls, item, rules: list, metadata: dict = None) -> tuple:
        """Returns (category, rename_template, confidence) or None if no match."""
        if metadata is None:
            metadata = getattr(item, 'metadata', {})
        for rule in sorted(rules, key=lambda r: r.get('priority', 99)):
            if not rule.get('enabled', True):
                continue
            conditions = rule.get('conditions', [])
            if not conditions:
                continue
            logic = rule.get('logic', 'all')
            results = []
            for cond in conditions:
                field = cond.get('field', '')
                op = cond.get('op', 'eq')
                value = cond.get('value', '')
                actual = cls._get_field_value(item, field, metadata)
                op_fn = cls._OPS.get(op, cls._OPS['eq'])
                try:
                    results.append(op_fn(actual, value))
                except (ValueError, TypeError):
                    results.append(False)
            matched = all(results) if logic == 'all' else any(results)
            if matched:
                return (rule.get('action_category', ''),
                        rule.get('action_rename', ''),
                        rule.get('confidence', 90))
        return None

    @staticmethod
    def export_rules_yaml(rules: list, output_path: str) -> bool:
        """Export rules to YAML. Falls back to JSON if PyYAML not available."""
        try:
            import yaml
            with open(output_path, 'w', encoding='utf-8') as f:
                yaml.dump({'rules': rules}, f, default_flow_style=False, allow_unicode=True)
            return True
        except ImportError:
            import json
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump({'rules': rules}, f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False

    @staticmethod
    def import_rules_yaml(input_path: str) -> list:
        """Import rules from YAML or JSON. Returns list of rule dicts."""
        try:
            if input_path.lower().endswith(('.yaml', '.yml')):
                try:
                    import yaml
                    with open(input_path, 'r', encoding='utf-8') as f:
                        data = yaml.safe_load(f)
                except ImportError:
                    import json
                    with open(input_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
            else:
                import json
                with open(input_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            if isinstance(data, list):
                return data
            return data.get('rules', [])
        except Exception:
            return []

    @staticmethod
    def natural_language_to_rule(prompt: str, ollama_url: str = 'http://localhost:11434',
                                  model: str = 'llama3') -> dict | None:
        """Convert natural language to a rule dict using Ollama LLM.

        Example prompt: "Move PDF files larger than 5MB to Documents"
        Returns a rule dict compatible with evaluate() or None on failure.
        """
        import json as _json
        system = (
            'You are a JSON rule generator for a file organizer. '
            'Convert the user description into a single JSON rule object with these exact keys: '
            '"name" (string), "enabled" (true), "priority" (int 1-99), "logic" ("all" or "any"), '
            '"conditions" (array of {"field": string, "op": string, "value": string}), '
            '"action_category" (string), "action_rename" (string, can be empty), "confidence" (int 1-100). '
            'Valid field values: name, extension, size, modified_date, created_date, path_contains. '
            'Valid op values: eq, neq, contains, not_contains, matches, startswith, endswith, '
            'gt, lt, gte, lte, older_than_days, newer_than_days, size_gt_mb, size_lt_mb, in_list, not_in_list. '
            'Respond with ONLY the JSON object, no explanation.'
        )
        payload = {
            'model': model,
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': prompt},
            ],
            'stream': False,
        }
        try:
            import urllib.request
            data = _json.dumps(payload).encode()
            req = urllib.request.Request(
                f'{ollama_url.rstrip("/")}/api/chat',
                data=data,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = _json.loads(resp.read())
            content = result.get('message', {}).get('content', '').strip()
            # Strip code fences (```json ... ``` or ``` ... ```)
            fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
            if fence_match:
                content = fence_match.group(1).strip()
            return _json.loads(content)
        except Exception:
            return None

    @staticmethod
    def find_conflicts(rules: list) -> list[tuple[int, int]]:
        """Return list of (rule_index_a, rule_index_b) pairs that have identical conditions."""
        conflicts = []
        for i, ra in enumerate(rules):
            for j, rb in enumerate(rules):
                if j <= i:
                    continue
                ca = sorted(ra.get('conditions', []), key=lambda c: c.get('field', ''))
                cb = sorted(rb.get('conditions', []), key=lambda c: c.get('field', ''))
                if ca == cb and ra.get('action_category') != rb.get('action_category'):
                    conflicts.append((i, j))
        return conflicts


# ══════════════════════════════════════════════════════════════════════════════
# EVENT GROUPER — AI-powered photo event clustering
# ══════════════════════════════════════════════════════════════════════════════

_EVENT_CACHE_FILE = os.path.join(_APP_DATA_DIR, 'event_groups.json')


class EventGrouper:
    """Groups photos by event/scene using vision descriptions and timestamps."""

    @staticmethod
    def group_by_time(items, gap_hours=3) -> list:
        """Group items by time proximity. Returns list of (event_id, [items])."""
        # Filter items with timestamps
        timed = []
        for it in items:
            ts = 0
            try:
                ts = os.path.getmtime(it.full_src)
            except Exception:
                pass
            if ts > 0:
                timed.append((ts, it))
        timed.sort(key=lambda x: x[0])
        groups = []
        current_group = []
        last_ts = 0
        for ts, it in timed:
            if current_group and (ts - last_ts) > gap_hours * 3600:
                groups.append(current_group)
                current_group = []
            current_group.append(it)
            last_ts = ts
        if current_group:
            groups.append(current_group)
        return [(i + 1, g) for i, g in enumerate(groups)]

    @staticmethod
    def suggest_event_name(descriptions: list) -> str:
        """Suggest an event name from a list of vision descriptions (offline heuristic)."""
        if not descriptions:
            return "Unknown Event"
        # Count common words (excluding stopwords)
        stopwords = {'a', 'an', 'the', 'is', 'are', 'was', 'were', 'in', 'on', 'at',
                     'to', 'for', 'of', 'with', 'and', 'or', 'this', 'that', 'it'}
        word_counts = Counter()
        for desc in descriptions:
            words = [w.lower() for w in re.findall(r'\b[a-zA-Z]{3,}\b', desc) if w.lower() not in stopwords]
            word_counts.update(words)
        top_words = [w for w, _ in word_counts.most_common(3)]
        return ' '.join(w.title() for w in top_words) if top_words else "Photo Group"

    @staticmethod
    def load_cache() -> dict:
        if os.path.isfile(_EVENT_CACHE_FILE):
            try:
                with open(_EVENT_CACHE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    @staticmethod
    def save_cache(data: dict):
        with open(_EVENT_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# SCHEDULE MANAGER — Windows Task Scheduler integration
# ══════════════════════════════════════════════════════════════════════════════

_SCHED_FILE = os.path.join(_APP_DATA_DIR, 'scheduled_tasks.json')


class ScheduleManager:
    """Windows Task Scheduler integration for periodic organization."""

    @staticmethod
    def create_task(name, profile_name, schedule_type='daily', time_str='09:00',
                    days='', auto_apply=False):
        """Create a Windows scheduled task."""
        if sys.platform != 'win32':
            return False
        args = f'--profile "{profile_name}"'
        if auto_apply:
            args += ' --auto-apply'
        # Run as an installed package to avoid script-path fragility
        tr = f'"{sys.executable}" -m unifile {args}'
        tn = f"UniFile\\{name}"
        cmd = ['schtasks', '/create', '/tn', tn, '/tr', tr, '/f']
        if schedule_type == 'daily':
            cmd += ['/sc', 'daily', '/st', time_str]
        elif schedule_type == 'weekly':
            cmd += ['/sc', 'weekly', '/st', time_str]
            if days:
                cmd += ['/d', days]
        elif schedule_type == 'on_logon':
            cmd += ['/sc', 'onlogon']
        try:
            subprocess.run(cmd, capture_output=True, check=True)
            return True
        except Exception:
            return False

    @staticmethod
    def delete_task(name):
        if sys.platform != 'win32':
            return False
        try:
            subprocess.run(['schtasks', '/delete', '/tn', f'UniFile\\{name}', '/f'],
                          capture_output=True, check=True)
            return True
        except Exception:
            return False

    @staticmethod
    def list_tasks() -> list:
        if sys.platform != 'win32':
            return []
        try:
            result = subprocess.run(
                ['schtasks', '/query', '/tn', 'UniFile\\', '/fo', 'CSV', '/nh'],
                capture_output=True, text=True, timeout=10)
            tasks = []
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    parts = line.strip('"').split('","')
                    if len(parts) >= 3:
                        tasks.append({
                            'name': parts[0].replace('UniFile\\', ''),
                            'next_run': parts[1] if len(parts) > 1 else '',
                            'status': parts[2] if len(parts) > 2 else '',
                        })
            return tasks
        except Exception:
            return []


# ══════════════════════════════════════════════════════════════════════════════
# RENAME TEMPLATE ENGINE — Phase 2 (PC File Organizer)
# Resolves {token} syntax against file metadata + filesystem properties.
# Supports: {name}, {ext}, {year}, {month}, {day}, {hour}, {minute}, {second},
#   {artist}, {album}, {title}, {genre}, {track}, {camera}, {camera_make},
#   {camera_model}, {width}, {height}, {duration}, {bitrate}, {pages},
#   {author}, {counter}, {counter:03d}, {parent}, {size}, {category},
#   {vision_name}, {vision_ocr}
# ══════════════════════════════════════════════════════════════════════════════

class RenameTemplateEngine:
    """Resolves rename templates for PC File Organizer items.

    Usage:
        engine = RenameTemplateEngine()
        new_name = engine.resolve("{year}-{month}-{day}_{name}", filepath, metadata, category)
    """

    # Tokens that come from file modification date
    _DATE_TOKENS = {'year', 'month', 'day', 'hour', 'minute', 'second'}

    @staticmethod
    def resolve(template: str, filepath: str, metadata: dict,
                category: str = '', counter: int = 1) -> str:
        """Resolve a template string into a concrete filename.

        Args:
            template:  e.g. "{year}-{month}-{day}_{name}"
            filepath:  absolute path to the original file
            metadata:  dict from MetadataExtractor.extract()
            category:  the assigned category name
            counter:   sequential counter (for {counter} token)

        Returns:
            Resolved filename (stem only, no extension) — or original stem if
            template is empty or resolution fails completely.
        """
        if not template or not template.strip():
            return os.path.splitext(os.path.basename(filepath))[0]

        basename = os.path.basename(filepath)
        stem, ext = os.path.splitext(basename)
        ext_clean = ext.lstrip('.')

        # Build context dict with all available tokens
        ctx = RenameTemplateEngine._build_context(filepath, stem, ext_clean,
                                                   metadata, category, counter)

        # Resolve conditional blocks before token substitution
        template = RenameTemplateEngine._resolve_conditionals(template, ctx)

        # Resolve tokens using regex
        def _replacer(match):
            raw = match.group(1)
            # Handle format specifiers: {counter:03d}, {track:02d}
            if ':' in raw:
                key, fmt = raw.split(':', 1)
                key = key.strip().lower()
                val = ctx.get(key)
                if val is not None:
                    try:
                        return format(int(val) if fmt.endswith('d') else val, fmt)
                    except (ValueError, TypeError):
                        return str(val)
                return ''
            else:
                key = raw.strip().lower()
                val = ctx.get(key)
                if val is not None and val != '':
                    return str(val)
                return ''

        try:
            result = re.sub(r'\{([^}]+)\}', _replacer, template)
        except Exception:
            return stem

        # Clean up result: collapse multiple separators, strip edges
        result = re.sub(r'[_\-\s]{2,}', '_', result)  # collapse repeated separators
        result = result.strip(' _-.')
        if not result:
            return stem

        # Fall back to stem if result is degenerate (no letters, or too short to be useful)
        if not any(c.isalpha() for c in result) or len(result) < 3:
            # Append original stem to give context: "03_recording" instead of "03"
            result = f"{result}_{stem}" if result else stem
            result = re.sub(r'[_\-\s]{2,}', '_', result).strip(' _-.')

        # Sanitise for filesystem safety
        result = re.sub(r'[<>:"/\\|?*]', '_', result)
        return result

    @staticmethod
    def preview(template: str, filepath: str, metadata: dict,
                category: str = '', counter: int = 1) -> str:
        """Like resolve(), but returns stem + extension for display."""
        if not template or not template.strip():
            return os.path.basename(filepath)
        stem = RenameTemplateEngine.resolve(template, filepath, metadata, category, counter)
        ext = os.path.splitext(filepath)[1]
        return stem + ext

    @staticmethod
    def available_tokens() -> list:
        """Return list of all supported token names (for UI help text)."""
        return [
            'name', 'ext', 'parent', 'category', 'size',
            'year', 'month', 'day', 'hour', 'minute', 'second',
            'artist', 'album', 'title', 'genre', 'track', 'year_tag',
            'camera', 'camera_make', 'camera_model', 'width', 'height',
            'duration', 'bitrate', 'pages', 'author',
            'counter', 'counter:03d',
            'vision_name', 'vision_ocr',
            'city', 'country', 'scene', 'month_name', 'blur',
            'person', 'face_count',
        ]

    @staticmethod
    def _build_context(filepath: str, stem: str, ext_clean: str,
                       metadata: dict, category: str, counter: int) -> dict:
        """Build the full token→value context dict."""
        ctx = {}

        # ── File properties ──────────────────────────────────────────────────
        ctx['original_name'] = stem
        ctx['ext'] = ext_clean
        ctx['category'] = category
        ctx['parent'] = os.path.basename(os.path.dirname(filepath))
        try:
            ctx['size'] = os.path.getsize(filepath)
        except OSError:
            ctx['size'] = 0

        # ── Date tokens — prefer EXIF date_taken, fallback to file mtime ────
        dt = None
        date_taken = metadata.get('date_taken', '')
        if date_taken:
            # Try common EXIF date formats with known output lengths
            _DATE_FMTS = [
                ('%Y:%m:%d %H:%M:%S', 19),   # standard EXIF: "2024:03:15 14:30:00"
                ('%Y-%m-%d %H:%M:%S', 19),   # ISO-ish:       "2024-03-15 14:30:00"
                ('%Y:%m:%d',          10),   # date only:     "2024:03:15"
                ('%Y-%m-%d',          10),   # ISO date:      "2024-03-15"
            ]
            for fmt, expected_len in _DATE_FMTS:
                try:
                    dt = datetime.strptime(date_taken[:expected_len], fmt)
                    break
                except (ValueError, IndexError):
                    continue
        # PDF/Office creation date
        if dt is None:
            for key in ('creation_date', 'created'):
                val = metadata.get(key, '')
                if val:
                    try:
                        dt = datetime.fromisoformat(str(val).replace('Z', '+00:00'))
                        break
                    except (ValueError, TypeError):
                        continue
        # Filename-extracted date (e.g. IMG_20240315_142300.jpg)
        if dt is None and metadata.get('fname_year'):
            try:
                y = int(metadata['fname_year'])
                m = int(metadata.get('fname_month', '1'))
                d = int(metadata.get('fname_day', '1'))
                dt = datetime(y, m, d)
            except (ValueError, TypeError):
                pass
        # Fallback to file modification time
        if dt is None:
            try:
                dt = datetime.fromtimestamp(os.path.getmtime(filepath))
            except OSError:
                dt = datetime.now()

        ctx['year'] = dt.strftime('%Y')
        ctx['month'] = dt.strftime('%m')
        ctx['day'] = dt.strftime('%d')
        ctx['hour'] = dt.strftime('%H')
        ctx['minute'] = dt.strftime('%M')
        ctx['second'] = dt.strftime('%S')

        # ── Photo organization tokens ────────────────────────────────────────
        ctx['month_name'] = dt.strftime('%B')
        ctx['city'] = metadata.get('_photo_city', '') or 'Unknown_Location'
        ctx['country'] = metadata.get('_photo_country', '')
        ctx['scene'] = metadata.get('_photo_scene', '') or 'Other'
        blur_val = metadata.get('_photo_blur', -1.0)
        ctx['blur'] = 'sharp' if blur_val < 0 else ('blurry' if blur_val < metadata.get('_photo_blur_threshold', 100) else 'sharp')
        ctx['person'] = metadata.get('_photo_face_primary', '') or 'Unknown_Person'
        fc = metadata.get('_photo_face_count', -1)
        ctx['face_count'] = str(fc) if fc >= 0 else '0'

        # ── Audio metadata ───────────────────────────────────────────────────
        ctx['artist'] = metadata.get('artist', '')
        ctx['album'] = metadata.get('album', '')
        ctx['title'] = metadata.get('title', '')
        ctx['genre'] = metadata.get('genre', '')
        ctx['track'] = metadata.get('track', '')
        ctx['year_tag'] = metadata.get('year', '')  # from ID3 tag

        # ── Image metadata ───────────────────────────────────────────────────
        make = metadata.get('camera_make', '')
        model = metadata.get('camera_model', '')
        ctx['camera_make'] = make
        ctx['camera_model'] = model
        # {camera} = combined make+model (deduplicated)
        if make and model and model.lower().startswith(make.lower()):
            ctx['camera'] = model
        elif make or model:
            ctx['camera'] = f"{make} {model}".strip()
        else:
            ctx['camera'] = ''
        ctx['width'] = metadata.get('width', '')
        ctx['height'] = metadata.get('height', '')

        # ── Media metadata ───────────────────────────────────────────────────
        ctx['duration'] = metadata.get('duration', '')
        ctx['bitrate'] = metadata.get('bitrate', '')
        ctx['codec'] = metadata.get('codec', '')
        ctx['fps'] = metadata.get('fps', '')

        # ── Document metadata ────────────────────────────────────────────────
        ctx['pages'] = metadata.get('pages', '')
        ctx['author'] = metadata.get('author', '')

        # ── Counter ──────────────────────────────────────────────────────────
        ctx['counter'] = counter

        # ── Vision AI tokens ─────────────────────────────────────────────────
        vname = metadata.get('_vision_name', '')
        # Validate vision name — reject JSON key leakage or garbage
        if vname:
            vl = vname.lower().replace('-', '_').replace(' ', '_')
            _poison = ('category', 'confidence', 'reason', 'suggested_name',
                       'detected_text', 'description', 'the_image_is',
                       'this_image', 'image_is', 'no_ext', 'json', 'null',
                       'undefined', 'true', 'false',
                       'according_to', 'here_is', 'classified', 'classification',
                       'given_input', 'provided_image', 'based_on')
            if any(p in vl for p in _poison):
                vname = ''
        ctx['vision_name'] = vname
        ctx['vision_ocr'] = metadata.get('_vision_ocr', '')
        # {name} — prefer vision-derived name when available, else original stem
        # {original_name} always has the raw filename stem
        ctx['name'] = vname if vname else stem
        ctx['smart_name'] = ctx['name']  # alias

        return ctx

    @staticmethod
    def _resolve_conditionals(template: str, ctx: dict) -> str:
        """Resolve {if:cond}...{else}...{endif} blocks in template.

        Supports:
          - Existence: {if:city}...{endif}  (true if city is non-empty)
          - Comparison: {if:face_count>0}...{endif}
          - Equality: {if:scene=portrait}...{endif}
        No nesting supported.
        """
        def _eval_condition(cond: str) -> bool:
            cond = cond.strip()
            # Comparison operators
            for op_str, op_fn in [('>=', lambda a, b: a >= b), ('<=', lambda a, b: a <= b),
                                   ('>', lambda a, b: a > b), ('<', lambda a, b: a < b),
                                   ('!=', lambda a, b: str(a) != str(b)),
                                   ('=', lambda a, b: str(a).lower() == str(b).lower())]:
                if op_str in cond:
                    parts = cond.split(op_str, 1)
                    if len(parts) == 2:
                        key = parts[0].strip().lower()
                        val = parts[1].strip()
                        ctx_val = ctx.get(key, '')
                        try:
                            return op_fn(float(ctx_val), float(val))
                        except (ValueError, TypeError):
                            return op_fn(str(ctx_val), val)
            # Existence check
            key = cond.lower()
            val = ctx.get(key, '')
            return bool(val) and str(val) not in ('', '0', 'Unknown_Person', 'Unknown_Location')

        pattern = re.compile(r'\{if:([^}]+)\}(.*?)(?:\{else\}(.*?))?\{endif\}', re.DOTALL)
        def _replacer(m):
            cond = m.group(1)
            if_body = m.group(2) or ''
            else_body = m.group(3) or ''
            return if_body if _eval_condition(cond) else else_body
        try:
            return pattern.sub(_replacer, template)
        except Exception:
            return template

    @staticmethod
    def get_default_template(category_name: str) -> str:
        """Return a sensible default template for a given category."""
        defaults = {
            'Images':     '{year}-{month}-{day}_{name}',
            'Audio':      '{artist} - {album} - {track:02d} - {title}',
            'Videos':     '{year}-{month}-{day}_{name}',
            'Documents':  '',
            'Archives':   '',
            'Code':       '',
            'Executables': '',
            'Fonts':      '',
            'Data':       '',
            'Design':     '',
            'Shortcuts':  '',
            'Other':      '',
        }
        return defaults.get(category_name, '')


# ══════════════════════════════════════════════════════════════════════════════
# ITERATIVE CATEGORY BALANCER
# Merges tiny categories and splits oversized ones for cleaner organization.
# ══════════════════════════════════════════════════════════════════════════════

class CategoryBalancer:
    """Iteratively rebalances category assignments after classification.

    Rules:
    - Categories with <= min_merge files get merged into nearest parent/sibling.
    - Categories with > split_threshold% of total files get split into subcategories.
    - Runs up to max_passes iterations until stable.
    """

    def __init__(self, min_merge: int = 3, split_pct: float = 0.20,
                 max_passes: int = 5):
        self.min_merge = min_merge
        self.split_pct = split_pct
        self.max_passes = max_passes

    def balance(self, items: list, category_attr: str = 'category',
                all_categories: list[str] | None = None) -> dict:
        """Rebalance category assignments on a list of items.

        Args:
            items: List of objects with a category attribute.
            category_attr: Name of the category attribute.
            all_categories: Available category names for merging targets.

        Returns:
            dict with 'merges', 'splits', 'passes', 'changes' counts.
        """
        stats = {'merges': 0, 'splits': 0, 'passes': 0, 'changes': 0}
        if not items:
            return stats

        for pass_num in range(self.max_passes):
            changed = False
            distribution = {}
            for it in items:
                cat = getattr(it, category_attr, '')
                if cat:
                    distribution.setdefault(cat, []).append(it)

            total = len(items)

            # Phase 1: Merge small categories
            for cat, cat_items in list(distribution.items()):
                if len(cat_items) <= self.min_merge and len(distribution) > 1:
                    # Find best merge target (most similar category name)
                    best_target = self._find_merge_target(
                        cat, [c for c in distribution if c != cat])
                    if best_target:
                        for it in cat_items:
                            setattr(it, category_attr, best_target)
                            stats['changes'] += 1
                        stats['merges'] += 1
                        changed = True

            # Phase 2: Split large categories
            distribution = {}
            for it in items:
                cat = getattr(it, category_attr, '')
                if cat:
                    distribution.setdefault(cat, []).append(it)

            for cat, cat_items in list(distribution.items()):
                if len(cat_items) > total * self.split_pct and len(cat_items) > 10:
                    # Split by extension or name pattern
                    subcats = self._suggest_splits(cat, cat_items)
                    if subcats:
                        for it, new_cat in subcats:
                            setattr(it, category_attr, new_cat)
                            stats['changes'] += 1
                        stats['splits'] += 1
                        changed = True

            stats['passes'] += 1
            if not changed:
                break

        return stats

    @staticmethod
    def _find_merge_target(cat_name: str, candidates: list[str]) -> str | None:
        """Find the most similar category to merge into."""
        if not candidates:
            return None
        # Simple word overlap scoring
        cat_words = set(cat_name.lower().split())
        best = None
        best_score = -1
        for c in candidates:
            c_words = set(c.lower().split())
            overlap = len(cat_words & c_words)
            if overlap > best_score:
                best_score = overlap
                best = c
        # If no word overlap, merge into "Other" if it exists, else first candidate
        if best_score == 0:
            return 'Other' if 'Other' in candidates else candidates[0]
        return best

    @staticmethod
    def _suggest_splits(cat_name: str, items: list) -> list[tuple] | None:
        """Try to split a large category into subcategories by extension."""
        from collections import Counter
        ext_counts = Counter()
        for it in items:
            name = getattr(it, 'name', '') or getattr(it, 'filename', '')
            ext = os.path.splitext(name)[1].lower() if name else ''
            ext_counts[ext] += 1

        # Only split if we have at least 2 major extension groups
        major_exts = [(ext, cnt) for ext, cnt in ext_counts.most_common()
                      if cnt >= 3 and ext]
        if len(major_exts) < 2:
            return None

        reassignments = []
        for it in items:
            name = getattr(it, 'name', '') or getattr(it, 'filename', '')
            ext = os.path.splitext(name)[1].lower() if name else ''
            if ext and any(ext == me[0] for me in major_exts[1:]):
                # Assign to subcategory
                ext_label = ext.lstrip('.').upper()
                new_cat = f"{cat_name} ({ext_label})"
                reassignments.append((it, new_cat))

        return reassignments if reassignments else None


# ══════════════════════════════════════════════════════════════════════════════
# PROGRESSIVE DUPLICATE DETECTOR — Phase 3 (PC File Organizer)
# 4-stage pipeline: size grouping → prefix hash → suffix hash → full hash
# Plus optional perceptual image hashing for near-duplicate images.
# ══════════════════════════════════════════════════════════════════════════════

_PHASH_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tif', '.tiff',
                     '.webp', '.heic', '.heif', '.avif'}

