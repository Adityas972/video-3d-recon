#!/usr/bin/env python3
"""Extract candidate photogrammetry frames from a turntable/orbit video.

Object Capture wants a set of sharp, well-distributed still photos, not raw
video frames -- most consecutive frames from a handheld pan are near-
duplicates or motion-blurred, and feeding all of them in just slows down
feature matching without adding coverage. This script samples at a fixed
rate with ffmpeg, then drops the blurriest fraction of frames by variance
of the Laplacian (a standard focus-measure).

Blur is filtered by PERCENTILE within the sampled set, not an absolute
threshold: variance-of-Laplacian scales with scene contrast, not just
actual sharpness -- a flat, moody studio-lit shot can score 5-10x lower
than a high-contrast outdoor one while being just as in-focus (confirmed
against a real low-key product-photography clip, where every frame scored
8-16 against an absolute default of 60 that was tuned on brighter test
footage and silently dropped all of them). Dropping the bottom N% of the
set's own distribution self-calibrates to each video's lighting instead.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np


def extract_raw_frames(video_path: Path, raw_dir: Path, fps: float) -> list[Path]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    pattern = raw_dir / "frame_%05d.png"
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", f"fps={fps}",
        "-qscale:v", "2",
        str(pattern),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr}")
    return sorted(raw_dir.glob("frame_*.png"))


def blur_score(image_path: Path) -> float:
    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    return cv2.Laplacian(img, cv2.CV_64F).var()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path, help="Input turntable/orbit video")
    parser.add_argument("--out-dir", required=True, type=Path, help="Directory to write kept frames into")
    parser.add_argument("--fps", type=float, default=3.0, help="Sampling rate before blur filtering")
    parser.add_argument("--drop-fraction", type=float, default=0.15,
                         help="Fraction of sampled frames to drop as blurriest-of-the-set (0 disables filtering)")
    args = parser.parse_args()

    if not args.video.exists():
        print(f"error: video not found: {args.video}", file=sys.stderr)
        return 1

    raw_dir = args.out_dir / "_raw"
    frames = extract_raw_frames(args.video, raw_dir, args.fps)
    if not frames:
        print("error: ffmpeg produced no frames", file=sys.stderr)
        return 1

    scores = {frame: blur_score(frame) for frame in frames}
    threshold = np.quantile(list(scores.values()), args.drop_fraction) if args.drop_fraction > 0 else -1.0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    kept, dropped = [], []
    for frame, score in scores.items():
        if score >= threshold:
            dest = args.out_dir / frame.name
            dest.write_bytes(frame.read_bytes())
            kept.append({"file": frame.name, "blur_score": score})
        else:
            dropped.append({"file": frame.name, "blur_score": score})

    manifest = {
        "video": str(args.video),
        "sampled_fps": args.fps,
        "drop_fraction": args.drop_fraction,
        "derived_blur_threshold": float(threshold),
        "total_sampled": len(frames),
        "kept": len(kept),
        "dropped": len(dropped),
        "kept_frames": kept,
        "dropped_frames": dropped,
    }
    manifest_path = args.out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"sampled {len(frames)} frames at {args.fps} fps")
    print(f"kept {len(kept)}, dropped {len(dropped)} "
          f"(bottom {args.drop_fraction:.0%} by blur score, threshold={threshold:.1f})")
    print(f"manifest: {manifest_path}")

    if len(kept) < 20:
        print("warning: fewer than 20 sharp frames -- Object Capture typically wants 20-200+ "
              "images with good angular coverage around the subject", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
