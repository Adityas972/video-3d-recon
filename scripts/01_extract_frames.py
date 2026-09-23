#!/usr/bin/env python3
"""Extract candidate photogrammetry frames from a turntable/orbit video.

Object Capture wants a set of sharp, well-distributed still photos, not raw
video frames -- most consecutive frames from a handheld pan are near-
duplicates or motion-blurred, and feeding all of them in just slows down
feature matching without adding coverage. This script samples at a fixed
rate with ffmpeg, then drops frames below a blur threshold (variance of the
Laplacian, a standard focus-measure) so what's left is close to what you'd
get shooting stills by hand.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2


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
    parser.add_argument("--blur-threshold", type=float, default=60.0,
                         help="Minimum variance-of-Laplacian to keep a frame; raise if too many blurry frames slip through")
    args = parser.parse_args()

    if not args.video.exists():
        print(f"error: video not found: {args.video}", file=sys.stderr)
        return 1

    raw_dir = args.out_dir / "_raw"
    frames = extract_raw_frames(args.video, raw_dir, args.fps)
    if not frames:
        print("error: ffmpeg produced no frames", file=sys.stderr)
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    kept, dropped = [], []
    for frame in frames:
        score = blur_score(frame)
        if score >= args.blur_threshold:
            dest = args.out_dir / frame.name
            dest.write_bytes(frame.read_bytes())
            kept.append({"file": frame.name, "blur_score": score})
        else:
            dropped.append({"file": frame.name, "blur_score": score})

    manifest = {
        "video": str(args.video),
        "sampled_fps": args.fps,
        "blur_threshold": args.blur_threshold,
        "total_sampled": len(frames),
        "kept": len(kept),
        "dropped": len(dropped),
        "kept_frames": kept,
        "dropped_frames": dropped,
    }
    manifest_path = args.out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"sampled {len(frames)} frames at {args.fps} fps")
    print(f"kept {len(kept)}, dropped {len(dropped)} below blur threshold {args.blur_threshold}")
    print(f"manifest: {manifest_path}")

    if len(kept) < 20:
        print("warning: fewer than 20 sharp frames -- Object Capture typically wants 20-200+ "
              "images with good angular coverage around the subject", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
