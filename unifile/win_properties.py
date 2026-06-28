"""Windows Property System metadata bridge.

Reads Windows Shell properties (rating, keywords/tags, title, author,
comment, subject) as read-only fields during file scan. These are the
properties visible in Explorer's Details pane and searchable via Windows
Search.

Non-Windows platforms get no-op stubs so callers don't need conditionals.
"""
import os
import sys

_IS_WINDOWS = sys.platform == 'win32'


# ── PowerShell-based property reader (no COM dependencies) ───────────────────

def read_shell_properties(filepath: str) -> dict:
    """Read Windows Shell properties for a file using PowerShell.

    Returns a dict with keys: title, author, subject, comment, keywords,
    rating. Missing or empty properties are omitted. Returns {} on non-Windows
    or on any failure.
    """
    if not _IS_WINDOWS:
        return {}
    if not os.path.isfile(filepath):
        return {}

    import subprocess

    abs_path = os.path.abspath(filepath)
    folder = os.path.dirname(abs_path)
    name = os.path.basename(abs_path)

    ps_script = f"""
$ErrorActionPreference = 'SilentlyContinue'
$shell = New-Object -ComObject Shell.Application
$folder = $shell.Namespace('{folder.replace("'", "''")}')
if (-not $folder) {{ exit }}
$item = $folder.ParseName('{name.replace("'", "''")}')
if (-not $item) {{ exit }}
$props = @{{}}
$map = @{{0='name'; 2='size'; 14='title'; 20='author'; 11='subject'; 24='comment'; 18='keywords'; 258='rating'}}
foreach ($idx in $map.Keys) {{
    $val = $folder.GetDetailsOf($item, $idx)
    if ($val) {{ $props[$map[$idx]] = $val }}
}}
$props | ConvertTo-Json -Compress
"""

    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_script],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {}
        import json
        data = json.loads(result.stdout.strip())
        if not isinstance(data, dict):
            return {}

        props = {}
        for key in ('title', 'author', 'subject', 'comment', 'keywords', 'rating'):
            val = data.get(key, '').strip()
            if val:
                props[key] = val
        return props
    except Exception:
        return {}


def merge_with_metadata(existing: dict, shell_props: dict) -> dict:
    """Merge shell properties into existing metadata without overwriting.

    Shell properties are stored with a `_shell_` prefix when they conflict
    with existing metadata fields. Non-conflicting fields are added directly.
    """
    if not shell_props:
        return existing
    result = dict(existing)
    for key, val in shell_props.items():
        if key in result and result[key]:
            result[f'_shell_{key}'] = val
        else:
            result[key] = val
    return result
