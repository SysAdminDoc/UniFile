"""Release metadata and public scan contract tests."""

from pathlib import Path

from tools.release_contract import check_public_scan_contract, check_version_surfaces

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_surfaces_are_synchronized():
    assert check_version_surfaces(ROOT) == []


def test_documented_scan_contract_executes_against_live_implementations():
    assert check_public_scan_contract(ROOT) == []
