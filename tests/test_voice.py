from pathlib import Path

from unifile.search_parser import parse_query
from unifile.voice import (
    VoiceIntent,
    VoiceIntentParser,
    matches_voice_selector,
    parse_voice_command,
)


def test_parse_tag_command_with_selector_terms():
    intent = parse_voice_command("tag all 2024 Florida photos as vacation")

    assert intent.action == "tag"
    assert intent.selector == "2024 Florida photos"
    assert intent.tag == "vacation"
    assert intent.selector_terms == ("2024", "florida")
    assert intent.requires_confirmation


def test_parse_scan_resolves_known_folder(tmp_path: Path):
    intent = parse_voice_command("scan Downloads folder", home=tmp_path)

    assert intent.action == "scan"
    assert intent.path == str(tmp_path / "Downloads")


def test_parse_large_video_command_uses_existing_search_grammar():
    intent = parse_voice_command("show me large video files")
    spec = parse_query(intent.query)

    assert intent.action == "search"
    assert set(("mp4", "mkv", "mov")).issubset(spec.exts)
    assert spec.size_op == ">"
    assert spec.size_bytes == 1024 * 1024 * 1024


def test_intent_round_trip_is_json_compatible():
    intent = parse_voice_command("find screenshots")
    restored = VoiceIntent.from_dict(intent.to_dict())

    assert restored == intent


def test_llm_fallback_is_explicit_and_provider_payload_is_normalized():
    parser = VoiceIntentParser(
        llm_classifier=lambda _text: (
            '{"action":"search","query":"ext:pdf","confidence":0.82}',
            "ollama",
        )
    )

    local_unknown = parser.parse("organize my PDFs")
    fallback = parser.parse("organize my PDFs", use_llm=True)

    assert local_unknown.action == "unknown"
    assert fallback.action == "search"
    assert fallback.query == "ext:pdf"
    assert fallback.provider == "ollama"


def test_selector_match_requires_all_terms():
    assert matches_voice_selector(r"C:\Photos\2024 Florida sunset.jpg", ("2024", "florida"))
    assert not matches_voice_selector(r"C:\Photos\2024 Ohio sunset.jpg", ("2024", "florida"))
