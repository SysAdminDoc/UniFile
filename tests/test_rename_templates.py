"""Regression coverage for move-time rename templates."""

from unifile.engine import RenameTemplateEngine
from unifile.models import FileItem
from unifile.workers import ApplyFilesWorker


def test_media_template_renders_episode_numbers_and_extension(tmp_path):
    source = tmp_path / 'Example.Show.S01E02.mkv'
    source.write_bytes(b'video')
    template = '{title} ({year}) - S{season:02d}E{episode:02d}{ext}'
    metadata = {
        '_type': 'video', 'title': 'Pilot', 'series': 'Example Show',
        'year': '2024', 'season': 1, 'episode': 2,
    }

    assert RenameTemplateEngine.resolve_filename(
        template, str(source), metadata, 'Videos', counter=1
    ) == 'Pilot (2024) - S01E02.mkv'
    assert RenameTemplateEngine.preview(
        template, str(source), metadata, 'Videos', counter=1
    ) == 'Pilot (2024) - S01E02.mkv'


def test_episode_numbers_fall_back_to_common_filename_syntax(tmp_path):
    source = tmp_path / 'The.Show.S03E07.mp4'
    source.write_bytes(b'video')
    metadata = {'_type': 'video', 'title': 'Episode 7', 'year': '2025'}

    assert RenameTemplateEngine.resolve_filename(
        '{title} ({year}) - S{season:02d}E{episode:02d}{ext}',
        str(source), metadata, 'Videos'
    ) == 'Episode 7 (2025) - S03E07.mp4'


def test_templates_without_explicit_extension_keep_source_extension(tmp_path):
    source = tmp_path / 'photo.jpg'
    source.write_bytes(b'image')

    assert RenameTemplateEngine.resolve_filename(
        '{name}-{counter:03d}', str(source), {}, 'Images', counter=4
    ) == 'photo-004.jpg'


def test_move_worker_re_resolves_template_before_move(tmp_path, monkeypatch):
    monkeypatch.setattr('unifile.workers.is_protected', lambda _path: False)
    source = tmp_path / 'Example.Show.S01E02.mkv'
    destination = tmp_path / 'organized' / 'stale-name.mkv'
    source.write_bytes(b'video')
    item = FileItem()
    item.name = source.name
    item.full_src = str(source)
    item.full_dst = str(destination)
    item.category = 'Videos'
    item.display_name = 'stale-name.mkv'
    item.metadata = {
        '_type': 'video', 'title': 'Pilot', 'year': '2024',
        'season': 1, 'episode': 2,
    }
    item.rename_template = '{title} ({year}) - S{season:02d}E{episode:02d}{ext}'
    item.rename_counter = 1
    item.rename_source = 'template'

    worker = ApplyFilesWorker([(0, item)], dry_run=False)
    worker.run()

    expected = destination.parent / 'Pilot (2024) - S01E02.mkv'
    assert not source.exists()
    assert expected.read_bytes() == b'video'
    assert item.display_name == expected.name
    assert item.full_dst == str(expected)
