"""Build the PyQt-free UniFile SDK wheel from the isolated SDK project."""
from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = ROOT / "sdk"
DEFAULT_OUTPUT = ROOT / "dist" / "sdk"


def build(output_dir: Path = DEFAULT_OUTPUT) -> Path:
    """Build one SDK wheel and return its path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "build",
        "--wheel",
        "--no-isolation",
        "--outdir",
        str(output_dir),
        str(SDK_ROOT),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    wheels = sorted(output_dir.glob("unifile_sdk-*.whl"))
    if not wheels:
        raise RuntimeError(f"SDK build produced no wheel under {output_dir}")
    wheel = wheels[-1]
    verify_wheel(wheel)
    return wheel


def verify_wheel(wheel: Path) -> None:
    """Verify the wheel exposes only the SDK dependency contract."""
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        metadata_name = next(
            name for name in names if name.endswith(".dist-info/METADATA")
        )
        metadata = archive.read(metadata_name).decode("utf-8")
    if "Requires-Dist: PyQt6" in metadata:
        raise RuntimeError("SDK wheel must not require PyQt6")
    if "unifile_sdk/__init__.py" not in names:
        raise RuntimeError("SDK wheel is missing unifile_sdk/__init__.py")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    wheel = build(args.output_dir)
    print(f"SDK wheel build passed: {wheel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
