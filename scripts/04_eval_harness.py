#!/usr/bin/env python3
"""Evaluation harness: turn a set of reconstruction runs into one readable report.

Pulls together, per detail level, three sources that are otherwise scattered
across separate files:
  - the PhotogrammetryCLI stats sidecar (wall-clock time, skipped/invalid
    input samples)
  - the frame-extraction manifest (how many input photos were offered)
  - the geometry verification report (mesh complexity, watertightness,
    round-trip integrity)

and renders a couple of fixed-angle thumbnails per mesh so a reviewer can
sanity-check quality at a glance instead of opening each file by hand.
"""
import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import trimesh
from mpl_toolkits.mplot3d.art3d import Poly3DCollection


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def render_thumbnails(mesh_path: Path, out_prefix: Path) -> list[str]:
    """Best-effort flat-shaded render from a couple of fixed angles.

    Uses matplotlib's 3D axes rather than an OpenGL-backed renderer (trimesh's
    pyglet viewer needs a real window server and is flaky headless / across
    pyglet-macOS version combinations) -- this is optional polish for the
    report, not a correctness check, so failures are logged and skipped
    rather than failing the whole harness run.
    """
    saved = []
    try:
        mesh = trimesh.load(mesh_path, force="mesh")
        triangles = mesh.vertices[mesh.faces]
        bounds = mesh.bounds
        center = bounds.mean(axis=0)
        radius = (bounds[1] - bounds[0]).max() / 2

        for name, elev, azim in [("front", 15, -60), ("three_quarter", 25, 45)]:
            fig = plt.figure(figsize=(4, 3), dpi=160)
            ax = fig.add_subplot(111, projection="3d")
            ax.add_collection3d(Poly3DCollection(
                triangles, facecolor=(0.75, 0.77, 0.82), edgecolor=(0.25, 0.25, 0.25), linewidths=0.05))
            ax.set_xlim(center[0] - radius, center[0] + radius)
            ax.set_ylim(center[1] - radius, center[1] + radius)
            ax.set_zlim(center[2] - radius, center[2] + radius)
            ax.view_init(elev=elev, azim=azim)
            ax.set_box_aspect((1, 1, 1))
            ax.set_axis_off()

            png_path = out_prefix.parent / f"{out_prefix.name}_{name}.png"
            fig.savefig(png_path, bbox_inches="tight", pad_inches=0)
            plt.close(fig)
            saved.append(str(png_path))
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"  [warn] thumbnail rendering skipped for {mesh_path.name}: {exc}")
    return saved


def build_report(scene: str, details: list[str], meshes_dir: Path, reports_dir: Path, frames_manifest: Path) -> str:
    manifest = load_json(frames_manifest)
    total_frames = manifest["kept"] if manifest else None

    rows = []
    all_thumbnails: dict[str, list[str]] = {}
    for detail in details:
        obj_path = meshes_dir / f"{scene}_{detail}.obj"
        stats_path = meshes_dir / f"{scene}_{detail}.usdz.stats.json"
        geometry_path = reports_dir / f"{scene}_{detail}_geometry.json"

        stats = load_json(stats_path)
        geometry = load_json(geometry_path)

        row = {
            "detail": detail,
            "elapsed_seconds": stats["elapsedSeconds"] if stats else None,
            "invalid_samples": stats["invalidSamples"] if stats else None,
            "skipped_samples": stats["skippedSamples"] if stats else None,
            "total_frames_offered": total_frames,
            "vertices": geometry["reference"]["vertices"] if geometry else None,
            "faces": geometry["reference"]["faces"] if geometry else None,
            "watertight": geometry["reference"]["watertight"] if geometry else None,
            "verification_ok": geometry["ok"] if geometry else None,
        }
        rows.append(row)

        if obj_path.exists():
            all_thumbnails[detail] = render_thumbnails(obj_path, reports_dir / f"{scene}_{detail}")

    lines = [f"# Reconstruction report: {scene}", ""]
    if total_frames is not None:
        lines.append(f"Input: {total_frames} sharp frames kept from `{frames_manifest.parent}` (see `manifest.json`).")
        lines.append("")

    lines.append("| Detail | Time (s) | Skipped/Invalid | Vertices | Faces | Watertight | Verified |")
    lines.append("|---|---|---|---|---|---|---|")
    for row in rows:
        elapsed = f"{row['elapsed_seconds']:.1f}" if row["elapsed_seconds"] is not None else "n/a"
        skipped_invalid = (
            f"{row['skipped_samples']}/{row['invalid_samples']}"
            if row["skipped_samples"] is not None else "n/a"
        )
        vertices = row["vertices"] if row["vertices"] is not None else "n/a"
        faces = row["faces"] if row["faces"] is not None else "n/a"
        watertight = row["watertight"] if row["watertight"] is not None else "n/a"
        verified = "yes" if row["verification_ok"] else ("no" if row["verification_ok"] is False else "n/a")
        lines.append(f"| {row['detail']} | {elapsed} | {skipped_invalid} | {vertices} | {faces} | {watertight} | {verified} |")

    lines.append("")
    for detail, thumbs in all_thumbnails.items():
        if not thumbs:
            continue
        lines.append(f"### {detail}")
        for thumb in thumbs:
            lines.append(f"![{detail}]({Path(thumb).name})")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--details", nargs="+", default=["preview", "reduced", "medium"])
    parser.add_argument("--meshes-dir", type=Path, default=Path("outputs/meshes"))
    parser.add_argument("--reports-dir", type=Path, default=Path("outputs/reports"))
    parser.add_argument("--frames-manifest", type=Path, required=True,
                         help="Path to the manifest.json written by 01_extract_frames.py")
    args = parser.parse_args()

    args.reports_dir.mkdir(parents=True, exist_ok=True)
    report_md = build_report(args.scene, args.details, args.meshes_dir, args.reports_dir, args.frames_manifest)
    report_path = args.reports_dir / f"{args.scene}_report.md"
    report_path.write_text(report_md)
    print(f"wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
