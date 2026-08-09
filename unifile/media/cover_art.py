"""Safe cover-art download, validation, embedding, and restore helpers."""
from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
import posixpath
import shutil
import tempfile
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from unifile import __version__
from unifile.config import _APP_DATA_DIR
from unifile.network import NetworkSession

MAX_COVER_BYTES = 10 * 1024 * 1024
SUPPORTED_COVER_ART_EXTENSIONS = frozenset({
    '.mp3', '.flac', '.ogg', '.oga', '.opus', '.m4a', '.m4b', '.mp4', '.m4v',
    '.epub',
})
_BACKUP_DIR = os.path.join(_APP_DATA_DIR, 'cover_art_backups')
_CACHE_DIR = os.path.join(_APP_DATA_DIR, 'cover_art_cache')


class CoverArtError(RuntimeError):
    """Raised when a cover response or media container is unsafe to process."""


@dataclass(frozen=True)
class CoverArtStatus:
    filepath: str
    supported: bool
    has_artwork: bool
    format: str = ''
    message: str = ''


@dataclass(frozen=True)
class CoverArtAsset:
    data: bytes
    mime_type: str
    source_url: str
    cache_path: str = ''


@dataclass(frozen=True)
class CoverArtResult:
    success: bool
    filepath: str
    source_url: str = ''
    skipped: bool = False
    backup_path: str = ''
    cache_path: str = ''
    message: str = ''

    def as_dict(self) -> dict:
        return {
            'success': self.success,
            'filepath': self.filepath,
            'source_url': self.source_url,
            'skipped': self.skipped,
            'backup_path': self.backup_path,
            'cache_path': self.cache_path,
            'message': self.message,
        }


def _normalise_mime(mime_type: str) -> str:
    value = str(mime_type or '').split(';', 1)[0].strip().lower()
    return value if value.startswith('image/') else ''


def _normalise_image(data: bytes, mime_type: str = '') -> tuple[bytes, str]:
    if not data or len(data) > MAX_COVER_BYTES:
        raise CoverArtError('cover response is empty or exceeds the 10 MiB safety limit')
    try:
        from PIL import Image
        with Image.open(BytesIO(data)) as image:
            image.verify()
            detected_format = str(image.format or '').upper()
        with Image.open(BytesIO(data)) as image:
            image.load()
            if detected_format == 'JPEG':
                return data, 'image/jpeg'
            if detected_format == 'PNG':
                return data, 'image/png'
            # Normalize GIF, WebP, and other image formats to a bounded,
            # widely-supported JPEG before handing bytes to mutagen.
            if image.mode in ('RGBA', 'LA'):
                background = Image.new('RGB', image.size, 'white')
                background.paste(image, mask=image.getchannel('A'))
                image = background
            else:
                image = image.convert('RGB')
            output = BytesIO()
            image.save(output, format='JPEG', quality=92, optimize=True)
            normalized = output.getvalue()
            if len(normalized) > MAX_COVER_BYTES:
                raise CoverArtError('normalized cover exceeds the 10 MiB safety limit')
            return normalized, 'image/jpeg'
    except CoverArtError:
        raise
    except Exception as exc:
        raise CoverArtError(f'cover response is not a readable image: {exc}') from exc


def _default_cache_dir() -> str:
    try:
        from platformdirs import user_cache_dir
        return os.path.join(user_cache_dir('unifile', ensure_exists=True), 'cover_art')
    except ImportError:
        return _CACHE_DIR


def _cache_candidate(cache_dir: str, url: str) -> str:
    digest = hashlib.sha256(url.encode('utf-8')).hexdigest()
    for extension in ('.jpg', '.png'):
        candidate = os.path.join(cache_dir, digest + extension)
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(cache_dir, digest + '.jpg')


def _write_atomic(path: str, data: bytes) -> None:
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix='.unifile-cover-', dir=directory)
    os.close(fd)
    try:
        with open(temp_path, 'wb') as stream:
            stream.write(data)
        os.replace(temp_path, path)
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def _response_bytes(response) -> bytes:
    status = int(getattr(response, 'status_code', 0) or 0)
    if status != 200:
        raise CoverArtError(f'cover provider returned HTTP {status}')
    headers = getattr(response, 'headers', {}) or {}
    try:
        declared = int(headers.get('Content-Length', 0) or 0)
    except (TypeError, ValueError):
        declared = 0
    if declared > MAX_COVER_BYTES:
        raise CoverArtError('cover provider response exceeds the 10 MiB safety limit')
    chunks: list[bytes] = []
    total = 0
    iterator = getattr(response, 'iter_content', None)
    if callable(iterator):
        for chunk in iterator(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_COVER_BYTES:
                raise CoverArtError('cover provider response exceeds the 10 MiB safety limit')
            chunks.append(bytes(chunk))
    else:
        payload = bytes(getattr(response, 'content', b'') or b'')
        if len(payload) > MAX_COVER_BYTES:
            raise CoverArtError('cover provider response exceeds the 10 MiB safety limit')
        return payload
    return b''.join(chunks)


def download_cover_art(url: str, *, cache_dir: str | os.PathLike[str] | None = None,
                       session=None) -> CoverArtAsset:
    """Download and validate an HTTP(S) cover, reusing a content-addressed cache."""
    source_url = str(url or '').strip()
    parsed = urllib.parse.urlparse(source_url)
    if parsed.scheme.lower() not in {'http', 'https'} or not parsed.netloc:
        raise CoverArtError('cover URL must use HTTP or HTTPS')
    target_dir = os.fspath(cache_dir) if cache_dir is not None else _default_cache_dir()
    os.makedirs(target_dir, exist_ok=True)
    candidate = _cache_candidate(target_dir, source_url)
    if os.path.isfile(candidate):
        try:
            data = Path(candidate).read_bytes()
            normalized, mime_type = _normalise_image(data, mimetypes.guess_type(candidate)[0] or '')
            return CoverArtAsset(normalized, mime_type, source_url, candidate)
        except (OSError, CoverArtError):
            try:
                os.remove(candidate)
            except OSError:
                pass

    if session is None:
        session = NetworkSession(provider="cover-art", cache_ttl=518_400)
    response = session.get(
        source_url,
        headers={'User-Agent': f'UniFile/{__version__} (cover art)', 'Accept': 'image/*'},
        timeout=15,
        stream=True,
    )
    try:
        payload = _response_bytes(response)
        normalized, mime_type = _normalise_image(
            payload, _normalise_mime((getattr(response, 'headers', {}) or {}).get('Content-Type', ''))
        )
    finally:
        close = getattr(response, 'close', None)
        if callable(close):
            close()
    extension = '.png' if mime_type == 'image/png' else '.jpg'
    candidate = os.path.join(
        target_dir, hashlib.sha256(source_url.encode('utf-8')).hexdigest() + extension)
    _write_atomic(candidate, normalized)
    return CoverArtAsset(normalized, mime_type, source_url, candidate)


def _status_for_audio(filepath: str, extension: str) -> bool:
    try:
        if extension == '.mp3':
            from mutagen.id3 import ID3
            return bool(ID3(filepath).getall('APIC'))
        if extension == '.flac':
            from mutagen.flac import FLAC
            return bool(FLAC(filepath).pictures)
        if extension in {'.ogg', '.oga', '.opus'}:
            import mutagen
            audio = mutagen.File(filepath, easy=False)
            tags = getattr(audio, 'tags', None) if audio else None
            return bool(tags and (tags.get('metadata_block_picture') or tags.get('coverart')))
        if extension in {'.m4a', '.m4b', '.mp4', '.m4v'}:
            from mutagen.mp4 import MP4
            tags = MP4(filepath).tags
            return bool(tags and tags.get('covr'))
        if extension == '.epub':
            return _epub_has_cover(filepath)
    except (ImportError, OSError, ValueError):
        return False
    return False


def _epub_opf_path(archive: zipfile.ZipFile) -> str:
    container = ET.fromstring(archive.read('META-INF/container.xml'))
    for element in container.iter():
        if element.tag.rsplit('}', 1)[-1] == 'rootfile':
            full_path = str(element.attrib.get('full-path', '')).strip()
            if full_path:
                return full_path
    raise CoverArtError('EPUB does not declare an OPF package')


def _epub_manifest_and_metadata(root: ET.Element):
    namespace = root.tag[1:].split('}', 1)[0] if root.tag.startswith('{') else ''
    prefix = f'{{{namespace}}}' if namespace else ''
    manifest = root.find(f'.//{prefix}manifest')
    metadata = root.find(f'.//{prefix}metadata')
    if manifest is None or metadata is None:
        raise CoverArtError('EPUB OPF has no manifest or metadata section')
    return prefix, manifest, metadata


def _epub_has_cover(filepath: str) -> bool:
    with zipfile.ZipFile(filepath) as archive:
        opf_path = _epub_opf_path(archive)
        root = ET.fromstring(archive.read(opf_path))
        prefix, manifest, metadata = _epub_manifest_and_metadata(root)
        cover_ids = {
            str(element.attrib.get('content', '')).strip()
            for element in metadata
            if element.tag.rsplit('}', 1)[-1] == 'meta'
            and str(element.attrib.get('name', '')).strip().casefold() == 'cover'
        }
        for item in manifest:
            properties = str(item.attrib.get('properties', '')).split()
            if 'cover-image' in properties or item.attrib.get('id') in cover_ids:
                return str(item.attrib.get('media-type', '')).startswith('image/')
    return False


def _embed_epub_cover(filepath: str, data: bytes, mime_type: str) -> None:
    with zipfile.ZipFile(filepath, 'r') as source:
        opf_path = _epub_opf_path(source)
        root = ET.fromstring(source.read(opf_path))
        prefix, manifest, metadata = _epub_manifest_and_metadata(root)
        existing_names = set(source.namelist())
        entries = [(info, source.read(info.filename)) for info in source.infolist()]
        image_extension = '.png' if mime_type == 'image/png' else '.jpg'
        cover_href = f'images/unifile-cover{image_extension}'
        cover_path = posixpath.normpath(
            posixpath.join(posixpath.dirname(opf_path), cover_href)
        )
        counter = 1
        while cover_path in existing_names:
            cover_href = f'images/unifile-cover-{counter}{image_extension}'
            cover_path = posixpath.normpath(
                posixpath.join(posixpath.dirname(opf_path), cover_href)
            )
            counter += 1
        item_id = 'unifile-cover-art'
        used_ids = {str(item.attrib.get('id', '')) for item in manifest}
        while item_id in used_ids:
            item_id += '-copy'
        ET.SubElement(manifest, f'{prefix}item', {
            'id': item_id,
            'href': cover_href,
            'media-type': mime_type,
            'properties': 'cover-image',
        })
        ET.SubElement(metadata, f'{prefix}meta', {
            'name': 'cover',
            'content': item_id,
        })
        opf_bytes = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    # Windows keeps the original archive locked until the ZipFile context is
    # closed, so rebuild after the source handle has been released.
    directory = os.path.dirname(filepath) or '.'
    fd, rebuilt_path = tempfile.mkstemp(prefix='.unifile-epub-', suffix='.epub', dir=directory)
    os.close(fd)
    try:
        with zipfile.ZipFile(rebuilt_path, 'w') as target:
            for info, payload in entries:
                target.writestr(info, opf_bytes if info.filename == opf_path else payload)
            target.writestr(cover_path, data, compress_type=zipfile.ZIP_DEFLATED)
        os.replace(rebuilt_path, filepath)
    finally:
        try:
            os.remove(rebuilt_path)
        except OSError:
            pass


def cover_art_status(filepath: str) -> CoverArtStatus:
    """Inspect whether *filepath* supports cover art and already contains it."""
    path = os.path.abspath(str(filepath or '').strip())
    extension = os.path.splitext(path)[1].lower()
    if extension not in SUPPORTED_COVER_ART_EXTENSIONS:
        return CoverArtStatus(path, False, False, message='container does not support embedded cover art')
    if not os.path.isfile(path):
        return CoverArtStatus(path, True, False, message='media file is missing')
    try:
        has_artwork = _status_for_audio(path, extension)
        return CoverArtStatus(
            path, True, has_artwork, extension[1:].upper(),
            'embedded artwork present' if has_artwork else 'no embedded artwork',
        )
    except Exception as exc:
        return CoverArtStatus(path, True, False, extension[1:].upper(), str(exc))


def _add_flac_picture(audio, data: bytes, mime_type: str) -> None:
    from mutagen.flac import Picture
    picture = Picture()
    picture.type = 3  # front cover
    picture.mime = mime_type
    picture.desc = 'UniFile cover art'
    picture.data = data
    audio.add_picture(picture)


def _embed_on_temp(filepath: str, data: bytes, mime_type: str, replace: bool) -> None:
    extension = os.path.splitext(filepath)[1].lower()
    if extension == '.mp3':
        from mutagen.id3 import APIC, ID3, ID3NoHeaderError
        try:
            audio = ID3(filepath)
        except ID3NoHeaderError:
            audio = ID3()
        if replace:
            audio.delall('APIC')
        audio.add(APIC(
            encoding=3, mime=mime_type, type=3, desc='UniFile cover art', data=data,
        ))
        audio.save(filepath)
        return
    if extension == '.flac':
        from mutagen.flac import FLAC
        audio = FLAC(filepath)
        if replace:
            audio.clear_pictures()
        _add_flac_picture(audio, data, mime_type)
        audio.save()
        return
    if extension in {'.ogg', '.oga', '.opus'}:
        import mutagen
        from mutagen.flac import Picture
        audio = mutagen.File(filepath, easy=False)
        if audio is None:
            raise CoverArtError('mutagen could not open the Ogg container')
        if getattr(audio, 'tags', None) is None:
            audio.add_tags()
        picture = Picture()
        picture.type = 3
        picture.mime = mime_type
        picture.desc = 'UniFile cover art'
        picture.data = data
        if replace:
            for key in ('metadata_block_picture', 'coverart'):
                audio.tags.pop(key, None)
        encoded = base64.b64encode(picture.write()).decode('ascii')
        audio.tags['metadata_block_picture'] = [encoded]
        audio.save()
        return
    if extension in {'.m4a', '.m4b', '.mp4', '.m4v'}:
        from mutagen.mp4 import MP4, MP4Cover
        audio = MP4(filepath)
        if audio.tags is None:
            audio.add_tags()
        image_format = MP4Cover.FORMAT_PNG if mime_type == 'image/png' else MP4Cover.FORMAT_JPEG
        audio['covr'] = [MP4Cover(data, imageformat=image_format)]
        audio.save()
        return
    if extension == '.epub':
        _embed_epub_cover(filepath, data, mime_type)
        return
    raise CoverArtError('container does not support embedded cover art')


def embed_cover_art(filepath: str, data: bytes, mime_type: str = '', *,
                    source_url: str = '', replace: bool = False,
                    backup_dir: str | os.PathLike[str] | None = None) -> CoverArtResult:
    """Embed validated artwork atomically, backing up the original first."""
    path = os.path.abspath(str(filepath or '').strip())
    status = cover_art_status(path)
    if not status.supported:
        return CoverArtResult(False, path, source_url, message=status.message)
    if status.has_artwork and not replace:
        return CoverArtResult(
            False, path, source_url, skipped=True, message='embedded artwork already present',
        )
    try:
        normalized, detected_mime = _normalise_image(data, mime_type)
        backup_root = os.fspath(backup_dir) if backup_dir is not None else _BACKUP_DIR
        os.makedirs(backup_root, exist_ok=True)
        backup_path = os.path.join(
            backup_root, f'{uuid.uuid4()}-{os.path.basename(path)}.bak')
        shutil.copy2(path, backup_path)
        directory = os.path.dirname(path) or '.'
        suffix = os.path.splitext(path)[1].lower()
        fd, temp_path = tempfile.mkstemp(prefix='.unifile-cover-', suffix=suffix, dir=directory)
        os.close(fd)
        try:
            shutil.copy2(path, temp_path)
            _embed_on_temp(temp_path, normalized, detected_mime, replace)
            os.replace(temp_path, path)
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return CoverArtResult(
            True, path, source_url, backup_path=backup_path,
            message='cover art embedded successfully',
        )
    except Exception as exc:
        return CoverArtResult(False, path, source_url, message=str(exc))


def fetch_and_embed_cover_art(filepath: str, url: str, *,
                              cache_dir: str | os.PathLike[str] | None = None,
                              backup_dir: str | os.PathLike[str] | None = None,
                              session=None, replace: bool = False) -> CoverArtResult:
    """Fetch provider artwork, cache it, then embed it into a local container."""
    asset = download_cover_art(url, cache_dir=cache_dir, session=session)
    result = embed_cover_art(
        filepath, asset.data, asset.mime_type, source_url=asset.source_url,
        replace=replace, backup_dir=backup_dir,
    )
    return CoverArtResult(
        result.success, result.filepath, result.source_url, result.skipped,
        result.backup_path, asset.cache_path, result.message,
    )


def undo_cover_art_write(filepath: str, backup_path: str) -> bool:
    """Restore a cover-art backup using an atomic replacement."""
    path = os.path.abspath(str(filepath or '').strip())
    backup = os.path.abspath(str(backup_path or '').strip())
    if not os.path.isfile(path) or not os.path.isfile(backup):
        return False
    directory = os.path.dirname(path) or '.'
    fd, temp_path = tempfile.mkstemp(prefix='.unifile-cover-restore-', dir=directory)
    os.close(fd)
    try:
        shutil.copy2(backup, temp_path)
        os.replace(temp_path, path)
        return True
    except OSError:
        return False
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass
