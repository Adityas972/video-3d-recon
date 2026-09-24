#!/usr/bin/env python3
"""Generate a synthetic orbit video for smoke-testing the pipeline.

Real footage requires an actual camera and a physical object; this renders
a textured, Lambertian-shaded low-poly shape and orbits a virtual camera
around it, writing the frames out as a video with the same shape as real
input (a single .mp4 of an object rotating/being orbited). It exists purely
to exercise scripts 01-04 end to end without waiting on a real capture --
it is NOT a substitute for testing against a real photo/video, since a
matplotlib render lacks real photographic noise, lighting falloff, and lens
characteristics that Object Capture's feature matching is tuned for.
"""
import argparse
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import trimesh
from mpl_toolkits.mplot3d.art3d import Poly3DCollection


def shaded_face_colors(mesh: trimesh.Trimesh, light_dir: np.ndarray) -> np.ndarray:
    rng = np.random.default_rng(seed=7)
    base_colors = rng.uniform(0.45, 0.95, size=(len(mesh.faces), 3))
    normals = mesh.face_normals
    # Ambient floor + one-sided diffuse term so faces facing away from the
    # single light stay clearly visible (a hard cast-shadow look actively
    # hurts feature matching, unlike a real capture's soft studio lighting).
    diffuse = np.clip(normals @ light_dir, 0.0, 1.0)
    brightness = (0.55 + 0.45 * diffuse)[:, None]
    return np.clip(base_colors * brightness, 0, 1)


def render_orbit_frames(out_dir: Path, n_frames: int, resolution: tuple[int, int]) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=1.0)
    # Irregular bumps so the surface isn't a perfectly smooth sphere -- gives
    # feature matching something less rotationally ambiguous to lock onto.
    rng = np.random.default_rng(seed=3)
    bump = 1.0 + 0.08 * rng.standard_normal(len(mesh.vertices))
    mesh.vertices *= bump[:, None]

    light_dir = np.array([0.4, -0.5, 0.8])
    light_dir /= np.linalg.norm(light_dir)
    face_colors = shaded_face_colors(mesh, light_dir)
    triangles = mesh.vertices[mesh.faces]
    radius = mesh.bounds[1].max() * 1.08

    frame_paths = []
    dpi = 120
    figsize = (resolution[0] / dpi, resolution[1] / dpi)
    for i in range(n_frames):
        azim = 360.0 * i / n_frames
        fig = plt.figure(figsize=figsize, dpi=dpi)
        ax = fig.add_subplot(111, projection="3d")
        ax.add_collection3d(Poly3DCollection(triangles, facecolors=face_colors, edgecolor="none"))
        ax.set_xlim(-radius, radius)
        ax.set_ylim(-radius, radius)
        ax.set_zlim(-radius, radius)
        ax.view_init(elev=12, azim=azim)
        ax.set_box_aspect((1, 1, 1))
        ax.set_axis_off()
        fig.patch.set_facecolor("white")

        frame_path = out_dir / f"frame_{i:05d}.png"
        fig.savefig(frame_path, facecolor="white")
        plt.close(fig)
        frame_paths.append(frame_path)

    return frame_paths


def assemble_video(frame_paths: list[Path], out_path: Path, fps: float) -> None:
    first = cv2.imread(str(frame_paths[0]))
    height, width = first.shape[:2]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    for frame_path in frame_paths:
        writer.write(cv2.imread(str(frame_path)))
    writer.release()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/raw/synthetic_orbit.mp4"))
    parser.add_argument("--n-frames", type=int, default=72, help="Distinct orbit positions rendered")
    parser.add_argument("--fps", type=float, default=12.0)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--keep-frames-dir", type=Path, default=None,
                         help="Optional: also keep the raw rendered frames here")
    args = parser.parse_args()

    render_dir = args.keep_frames_dir or (args.out.parent / f"_{args.out.stem}_render")
    print(f"rendering {args.n_frames} synthetic orbit frames to {render_dir}...")
    frame_paths = render_orbit_frames(render_dir, args.n_frames, (args.width, args.height))

    print(f"assembling {args.out} at {args.fps} fps...")
    assemble_video(frame_paths, args.out, args.fps)

    if args.keep_frames_dir is None:
        for frame_path in frame_paths:
            frame_path.unlink()
        render_dir.rmdir()

    print(f"done: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
