"""Tests for bounded multimodal image batching."""
import json
from pathlib import Path

from unifile import ollama


def test_vision_batch_normalization_is_bounded():
    assert ollama.DEFAULT_VISION_BATCH_SIZE == 32
    assert ollama.normalize_vision_batch_size(None) == 32
    assert ollama.normalize_vision_batch_size(0) == 1
    assert ollama.normalize_vision_batch_size(999) == 32


def test_vision_batch_sends_one_request_and_restores_index_order(monkeypatch):
    captured = {}

    def fake_generate(prompt, **kwargs):
        captured['prompt'] = prompt
        captured['kwargs'] = kwargs
        return json.dumps({
            'results': [
                {
                    'index': 2,
                    'category': 'Photos',
                    'confidence': 108,
                    'reason': 'second',
                    'description': 'a lake',
                    'suggested_name': 'lake',
                    'detected_text': '',
                },
                {
                    'index': 1,
                    'category': 'Photos',
                    'confidence': 87,
                    'reason': 'first',
                    'description': 'a mountain',
                    'suggested_name': 'mountain',
                    'detected_text': '',
                },
            ]
        })

    monkeypatch.setattr(ollama, '_ollama_generate', fake_generate)
    result = ollama.ollama_classify_vision_batch(
        [
            {'name': 'mountain.jpg', 'image': 'encoded-one'},
            {'name': 'lake.jpg', 'image': 'encoded-two'},
        ],
        model='vision-model',
        categories=['Photos'],
        system='vision system',
    )

    assert len(result) == 2
    assert result[0]['suggested_name'] == 'mountain'
    assert result[1]['suggested_name'] == 'lake'
    assert result[1]['confidence'] == 100
    assert captured['kwargs']['images'] == ['encoded-one', 'encoded-two']
    assert '[IMAGE 1] source name for context only: mountain.jpg' in captured['prompt']
    assert captured['kwargs']['format']['required'] == ['results']


def test_vision_batch_chunks_and_isolates_failed_requests(monkeypatch):
    calls = []

    def fake_chunk(images, **kwargs):
        calls.append(len(images))
        if len(calls) == 2:
            raise RuntimeError('simulated batch failure')
        return [
            {
                'category': 'Photos',
                'confidence': 80,
                'reason': 'ok',
                'description': '',
                'suggested_name': 'photo',
                'detected_text': '',
                'photo_type': '',
            }
            for _ in images
        ]

    monkeypatch.setattr(ollama, '_ollama_classify_vision_batch_chunk', fake_chunk)
    result = ollama.ollama_classify_vision_batch(
        [{'name': f'{i}.jpg', 'image': 'encoded'} for i in range(5)],
        categories=['Photos'],
        batch_size=2,
    )

    assert calls == [2, 2, 1]
    assert result[0]['category'] == 'Photos'
    assert result[1]['category'] == 'Photos'
    assert result[2] is None and result[3] is None
    assert result[4]['category'] == 'Photos'


def test_scan_worker_flushes_queued_images_in_configured_batches(tmp_path, monkeypatch):
    from unifile import workers

    for index in range(3):
        (tmp_path / f'photo-{index}.jpg').write_bytes(b'fake-image')

    settings = {
        'url': 'http://vision.test',
        'model': 'vision-model',
        'vision_enabled': True,
        'vision_max_file_mb': 20,
        'vision_max_pixels': 32,
        'vision_batch_size': 2,
        'content_extraction': False,
        'content_max_chars': 200,
    }
    calls = []
    emitted = []

    class _Cache:
        def open(self):
            pass

        def prune(self, max_age_days):
            pass

        def lookup(self, *args):
            return None

        def store(self, *args):
            pass

        def commit(self):
            pass

        def close(self):
            pass

    def fake_vision_batch(images, **kwargs):
        calls.append(len(images))
        return [
            {
                'category': 'Photos',
                'confidence': 91,
                'reason': 'batch',
                'description': 'photo',
                'suggested_name': 'photo',
                'detected_text': '',
                'photo_type': 'other',
            }
            for _ in images
        ]

    monkeypatch.setattr(workers, 'load_ollama_settings', lambda: settings)
    monkeypatch.setattr(workers.ScanFilesLLMWorker, '_ensure_ollama_ready', lambda self, s: True)
    monkeypatch.setattr(workers, 'ollama_test_connection', lambda *args: (True, 'ok', []))
    monkeypatch.setattr(workers, '_is_vision_model', lambda model: True)
    monkeypatch.setattr(workers, '_prepare_image_base64', lambda path, max_pixels: 'encoded')
    monkeypatch.setattr(workers, 'ollama_classify_vision_batch', fake_vision_batch)
    monkeypatch.setattr(workers, 'MetadataExtractor', type(
        '_Metadata', (), {'extract': staticmethod(lambda *args, **kwargs: {})}
    ))
    monkeypatch.setattr(workers, 'load_photo_settings', lambda: {'enabled': False})
    monkeypatch.setattr(workers, '_ScanCache', _Cache)

    worker = workers.ScanFilesLLMWorker(
        str(tmp_path), '', [{'name': 'Photos'}],
        scan_depth=0, include_folders=False, include_files=True,
        force_rescan=True,
    )
    worker.result_ready.connect(emitted.append)
    worker.run()

    assert calls == [2, 1]
    assert [Path(result['full_src']).name for result in emitted] == [
        'photo-0.jpg', 'photo-1.jpg', 'photo-2.jpg'
    ]
    assert all(result['method'] == 'vision' for result in emitted)
