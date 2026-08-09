"""Extract, compile, and validate UniFile Qt translation catalogs."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS = ROOT / 'unifile' / 'translations'
ENGLISH_CATALOG = TRANSLATIONS / 'en.ts'
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _resolve_tool(value: str | None, env_name: str, default: str, fallback: Path | None = None) -> str:
    candidate = value or os.environ.get(env_name) or default
    if Path(candidate).is_file():
        return str(Path(candidate))
    found = shutil.which(candidate)
    if found:
        return found
    if fallback is not None and fallback.is_file():
        return str(fallback)
    raise FileNotFoundError(
        f'{candidate} was not found; pass --{env_name.lower()} or set {env_name}'
    )


def _source_text(element: ET.Element | None) -> str:
    return ''.join(element.itertext()).strip() if element is not None else ''


def _normalize_english_catalog(path: Path) -> None:
    """Turn pylupdate's unfinished entries into a complete English baseline."""
    from unifile.i18n import TRANSLATION_PLURAL_SOURCES

    tree = ET.parse(path)
    root = tree.getroot()
    root.set('language', 'en')
    root.set('sourcelanguage', 'en')
    for context in root.findall('context'):
        for message in context.findall('message'):
            source = _source_text(message.find('source'))
            translation = message.find('translation')
            if translation is None:
                translation = ET.SubElement(message, 'translation')
            translation.attrib.pop('type', None)
            forms = translation.findall('numerusform')
            if message.get('numerus') == 'yes' or source in TRANSLATION_PLURAL_SOURCES:
                message.set('numerus', 'yes')
                translation.clear()
                singular = source.replace('file(s)', 'file')
                plural = source.replace('file(s)', 'files')
                ET.SubElement(translation, 'numerusform').text = singular
                ET.SubElement(translation, 'numerusform').text = plural
            else:
                for form in forms:
                    translation.remove(form)
                translation.text = source
    tree.write(path, encoding='utf-8', xml_declaration=True)


def extract(pylupdate: str | None = None) -> None:
    TRANSLATIONS.mkdir(parents=True, exist_ok=True)
    tool = _resolve_tool(pylupdate, 'PYLUPDATE6', 'pylupdate6')
    subprocess.run(
        [tool, str(ROOT / 'unifile'), '-ts', str(ENGLISH_CATALOG)],
        cwd=ROOT,
        check=True,
    )
    _normalize_english_catalog(ENGLISH_CATALOG)
    print(f'Extracted English catalog: {ENGLISH_CATALOG}')


def compile_catalogs(lrelease: str | None = None) -> None:
    tool = _resolve_tool(lrelease, 'LRELEASE', 'lrelease')
    catalogs = sorted(path for path in TRANSLATIONS.glob('*.ts') if path.stem != 'en')
    if not catalogs:
        raise RuntimeError('no non-English .ts catalogs found')
    for catalog in catalogs:
        output = catalog.with_suffix('.qm')
        subprocess.run([tool, str(catalog), '-qm', str(output)], cwd=ROOT, check=True)
        print(f'Compiled catalog: {output}')


def validate() -> None:
    from unifile.i18n import validate_translation_catalog

    catalogs = sorted(TRANSLATIONS.glob('*.ts'))
    if not catalogs:
        raise RuntimeError('no .ts catalogs found')
    errors: list[str] = []
    for catalog in catalogs:
        errors.extend(validate_translation_catalog(catalog, require_distinct_critical=catalog.stem != 'en'))
        if catalog.stem != 'en' and not catalog.with_suffix('.qm').is_file():
            errors.append(f'{catalog}: compiled .qm catalog is missing')
    if errors:
        raise RuntimeError('\n'.join(errors))
    print(f'Validated {len(catalogs)} translation catalog(s)')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('extract', 'compile', 'check', 'all'))
    parser.add_argument('--pylupdate', help='path to pylupdate6')
    parser.add_argument('--lrelease', help='path to lrelease')
    args = parser.parse_args(argv)
    try:
        if args.command in ('extract', 'all'):
            extract(args.pylupdate)
        if args.command in ('compile', 'all'):
            compile_catalogs(args.lrelease)
        if args.command in ('check', 'all'):
            validate()
    except (FileNotFoundError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'i18n catalog failure: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
