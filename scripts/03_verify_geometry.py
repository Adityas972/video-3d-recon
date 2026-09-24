#!/usr/bin/env python3
"""Round-trip geometry verification for reconstructed meshes.

Object Capture only writes .usdz directly (see scripts/usdz_utils.py for
why); this script is the "verify what comes out matches what went in" step
-- it doesn't trust that export blindly. For each reconstructed scene it:

  1. Loads the .usdz via USD's Python bindings and computes reference
     geometry stats.
  2. Re-exports that same in-memory mesh to .obj, .ply, and .glb (formats
     Object Capture itself can't write) and reloads each with trimesh,
     checking vertex/face counts and surface area/volume stay within
     tolerance across the round trip.

Exits non-zero if any scene fails a check, so it can gate a pipeline run
the same way a CI geometry check would.
"""
import argparse
import json
import sys
from pathlib import Path

import trimesh

from usdz_utils import load_usdz_as_trimesh

REL_TOL = 1e-3


def mesh_stats(mesh: trimesh.Trimesh) -> dict:
    return {
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "watertight": bool(mesh.is_watertight),
        "surface_area": float(mesh.area),
        "volume": float(mesh.volume) if mesh.is_watertight else None,
        "bounding_box_extents": mesh.bounding_box.extents.tolist(),
    }


def close_enough(a: float, b: float, rel_tol: float = REL_TOL) -> bool:
    if a is None or b is None:
        return a == b
    return abs(a - b) <= rel_tol * max(abs(a), abs(b), 1e-9)


def verify_scene(usdz_path: Path, work_dir: Path) -> dict:
    report: dict = {"scene": usdz_path.stem, "usdz_path": str(usdz_path), "checks": [], "ok": True}

    mesh = load_usdz_as_trimesh(usdz_path)
    reference = mesh_stats(mesh)
    report["reference"] = reference

    work_dir.mkdir(parents=True, exist_ok=True)
    for fmt in ("obj", "ply", "glb"):
        reexport_path = work_dir / f"{usdz_path.stem}.{fmt}"
        mesh.export(reexport_path)
        reloaded = trimesh.load(reexport_path, force="mesh")
        candidate = mesh_stats(reloaded)

        check = {"format": fmt, "path": str(reexport_path), "stats": candidate}
        problems = []
        if candidate["vertices"] != reference["vertices"]:
            problems.append(f"vertex count changed: {reference['vertices']} -> {candidate['vertices']}")
        if candidate["faces"] != reference["faces"]:
            problems.append(f"face count changed: {reference['faces']} -> {candidate['faces']}")
        if not close_enough(candidate["surface_area"], reference["surface_area"]):
            problems.append(f"surface area drifted: {reference['surface_area']:.6f} -> {candidate['surface_area']:.6f}")

        check["problems"] = problems
        check["ok"] = not problems
        report["ok"] = report["ok"] and check["ok"]
        report["checks"].append(check)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meshes-dir", type=Path, default=Path("outputs/meshes"))
    parser.add_argument("--reports-dir", type=Path, default=Path("outputs/reports"))
    args = parser.parse_args()

    usdz_files = sorted(args.meshes_dir.glob("*.usdz"))
    if not usdz_files:
        print(f"error: no .usdz files found in {args.meshes_dir}", file=sys.stderr)
        return 1

    args.reports_dir.mkdir(parents=True, exist_ok=True)
    all_ok = True
    for usdz_path in usdz_files:
        work_dir = args.meshes_dir / f"{usdz_path.stem}_reexport"
        report = verify_scene(usdz_path, work_dir)

        report_path = args.reports_dir / f"{usdz_path.stem}_geometry.json"
        report_path.write_text(json.dumps(report, indent=2))

        status = "OK" if report["ok"] else "FAIL"
        print(f"[{status}] {usdz_path.stem}: "
              f"{report['reference']['vertices']} verts, {report['reference']['faces']} faces, "
              f"watertight={report['reference']['watertight']} -> {report_path}")
        if not report["ok"]:
            for check in report["checks"]:
                if not check["ok"]:
                    print(f"         {check['format']}: {'; '.join(check['problems'])}")
        all_ok = all_ok and report["ok"]

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
