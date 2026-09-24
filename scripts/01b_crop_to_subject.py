#!/usr/bin/env python3
"""Auto-crop frames to the one region that actually changes across them.

For a fixed-camera turntable shot where OTHER static props share the frame
with the rotating subject (e.g. the Pexels globe-on-a-stand clip this was
built against: a spinning globe next to a static cube and cylinder), SfM
sees two independently-moving rigid bodies in one scene and can't resolve
either correctly -- geometry verification still passes because it only
checks format round-trip integrity, not reconstruction accuracy (see
README "Results"). Cropping out everything that ISN'T changing removes the
confounding static geometry before it ever reaches Object Capture.

Method: stack all frames, take per-pixel variance over time, keep the
largest connected component above a variance threshold, and crop every
frame to its bounding box (with padding). This assumes exactly one region
of the frame is the moving subject and the rest is static -- it is NOT the
right tool for a genuine camera-orbit capture, where the *whole* frame
changes with viewpoint and there's nothing static to crop away from. If the
detected region covers most of the frame, this script says so and leaves
the frames untouched rather than applying a meaningless crop.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np


def find_subject_bbox(frames: list[Path], variance_quantile: float) -> tuple[int, int, int, int] | None:
    stack = np.stack([cv2.imread(str(f), cv2.IMREAD_GRAYSCALE).astype(np.float32) for f in frames])
    variance = stack.var(axis=0)

    threshold = np.quantile(variance, variance_quantile)
    mask = (variance > threshold).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))

    n_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n_labels <= 1:
        return None
    largest = max(range(1, n_labels), key=lambda i: stats[i, cv2.CC_STAT_AREA])
    x, y, w, h = stats[largest, :4]
    return int(x), int(y), int(w), int(h)


def pad_bbox(bbox: tuple[int, int, int, int], frame_shape: tuple[int, int], pad_frac: float) -> tuple[int, int, int, int]:
    x, y, w, h = bbox
    height, width = frame_shape
    pad_x, pad_y = int(w * pad_frac), int(h * pad_frac)
    x0, y0 = max(0, x - pad_x), max(0, y - pad_y)
    x1, y1 = min(width, x + w + pad_x), min(height, y + h + pad_y)
    return x0, y0, x1 - x0, y1 - y0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames-dir", required=True, type=Path)
    parser.add_argument("--variance-quantile", type=float, default=0.95,
                         help="Pixels above this variance quantile are considered part of the moving subject")
    parser.add_argument("--pad-fraction", type=float, default=0.15,
                         help="Padding added around the detected bbox, as a fraction of its size")
    parser.add_argument("--max-area-fraction", type=float, default=0.6,
                         help="Skip cropping if the detected region covers more than this fraction of the "
                              "frame -- a sign the whole frame is changing (camera motion), not one subject")
    args = parser.parse_args()

    frames = sorted(args.frames_dir.glob("*.png"))
    if len(frames) < 2:
        print(f"error: need at least 2 frames in {args.frames_dir}", file=sys.stderr)
        return 1

    first = cv2.imread(str(frames[0]), cv2.IMREAD_GRAYSCALE)
    frame_area = first.shape[0] * first.shape[1]

    bbox = find_subject_bbox(frames, args.variance_quantile)
    if bbox is None:
        print("no moving region detected -- leaving frames uncropped", file=sys.stderr)
        return 0

    x, y, w, h = pad_bbox(bbox, first.shape, args.pad_fraction)
    if (w * h) / frame_area > args.max_area_fraction:
        print(f"detected region covers {w*h/frame_area:.0%} of the frame (> {args.max_area_fraction:.0%}) -- "
              "this looks like whole-frame camera motion, not a static-clutter turntable shot; "
              "leaving frames uncropped", file=sys.stderr)
        return 0

    for frame_path in frames:
        img = cv2.imread(str(frame_path))
        cropped = img[y:y + h, x:x + w]
        cv2.imwrite(str(frame_path), cropped)

    (args.frames_dir / "crop_bbox.json").write_text(json.dumps({
        "x": x, "y": y, "w": w, "h": h,
        "original_shape": list(first.shape),
        "variance_quantile": args.variance_quantile,
        "pad_fraction": args.pad_fraction,
    }, indent=2))

    print(f"cropped {len(frames)} frames to x={x} y={y} w={w} h={h} "
          f"({w*h/frame_area:.1%} of original frame area)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
