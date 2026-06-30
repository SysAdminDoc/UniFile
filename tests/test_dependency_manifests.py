from importlib import util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = util.spec_from_file_location(
    "check_dependency_manifests",
    ROOT / "tools" / "check_dependency_manifests.py",
)
manifests = util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(manifests)


def test_dependency_manifest_check_passes():
    assert manifests.main() == 0


def test_parser_minimums_are_declared_in_relevant_extras():
    _base, extras = manifests._pyproject_packages()

    full = set(extras["full"])
    assert manifests.REQUIRED_EXTRA_PACKAGES["full"] <= full
    assert "pyacoustid" in full
    assert "acoustid" not in full

    for extra, packages in manifests.REQUIRED_EXTRA_PACKAGES.items():
        declared = extras[extra]
        for package in packages:
            assert manifests._has_required_floor(declared[package], manifests.PARSER_MINIMUMS[package])


def test_parser_floor_validation_rejects_unbounded_or_old_specs():
    assert manifests._has_required_floor("Pillow>=12.2.0", "12.2.0")
    assert manifests._has_required_floor("Pillow==12.2.0", "12.2.0")
    assert not manifests._has_required_floor("Pillow", "12.2.0")
    assert not manifests._has_required_floor("Pillow>=11.3.0", "12.2.0")
