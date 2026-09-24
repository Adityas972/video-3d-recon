#!/usr/bin/env python3
"""Orchestrates the full video -> mesh -> verified + evaluated report pipeline.

    python run_pipeline.py --video data/raw/mug.mov --scene mug

Each stage is a separate script under scripts/ and can be run standalone;
this just chains them with consistent paths, timing, and fail-fast behavior
so a broken stage doesn't waste time running the ones after it on bad input.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run_step(name: str, cmd: list[str]) -> None:
    print(f"\n=== {name} ===")
    print(" ".join(str(c) for c in cmd))
    started = time.time()
    result = subprocess.run(cmd, cwd=ROOT)
    elapsed = time.time() - started
    if result.returncode != 0:
        print(f"[FAILED] {name} exited {result.returncode} after {elapsed:.1f}s", file=sys.stderr)
        sys.exit(result.returncode)
    print(f"[OK] {name} finished in {elapsed:.1f}s")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--scene", required=True, help="Short name for this capture, e.g. 'mug'")
    parser.add_argument("--fps", type=float, default=3.0)
    parser.add_argument("--drop-fraction", type=float, default=0.15,
                         help="Fraction of sampled frames to drop as blurriest-of-the-set")
    parser.add_argument("--details", nargs="+", default=["preview", "reduced", "medium"])
    args = parser.parse_args()

    frames_dir = ROOT / "data" / "frames" / args.scene
    venv_python = ROOT / ".venv" / "bin" / "python3"
    python = str(venv_python) if venv_python.exists() else sys.executable

    run_step("1/4 extract frames", [
        python, "scripts/01_extract_frames.py",
        "--video", str(args.video),
        "--out-dir", str(frames_dir),
        "--fps", str(args.fps),
        "--drop-fraction", str(args.drop_fraction),
    ])

    run_step("2/4 photogrammetry reconstruction", [
        "bash", "scripts/02_run_photogrammetry.sh", str(frames_dir), args.scene, *args.details,
    ])

    run_step("3/4 verify geometry", [
        python, "scripts/03_verify_geometry.py",
    ])

    run_step("4/4 build eval report", [
        python, "scripts/04_eval_harness.py",
        "--scene", args.scene,
        "--details", *args.details,
        "--frames-manifest", str(frames_dir / "manifest.json"),
    ])

    print(f"\nDone. See outputs/reports/{args.scene}_report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
