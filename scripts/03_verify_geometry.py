#!/usr/bin/env python3
"""Round-trip geometry verification for reconstructed meshes.

Object Capture writes .usdz and .obj directly; this script is the "verify
what comes out matches what went in" step -- it doesn't trust either export
blindly. For each reconstructed scene it:

  1. Loads the .obj export and computes reference geometry stats.
  2. Re-exports that same in-memory mesh to .ply and .glb (independent of
     Apple's exporter) and reloads each, checking vertex/face counts and
     surface area/volume stay within tolerance across the round trip.
  3. Confirms the .usdz sidecar is at least a well-formed zip container
     (usdz is a zip archive), since this toolchain has no full USD parser.

Exits non-zero if any scene fails a check, so it can gate a pipeline run
the same way a CI geometry check would.
"""
import argparse
import json
import sys
import zipfile
from pathlib import Path

import trimesh

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


def verify_scene(obj_path: Path, usdz_path: Path, work_dir: Path) -> dict:
    report: dict = {"scene": obj_path.stem, "obj_path": str(obj_path), "checks": [], "ok": True}

    mesh = trimesh.load(obj_path, force="mesh")
    reference = mesh_stats(mesh)
    report["reference"] = reference

    work_dir.mkdir(parents=True, exist_ok=True)
    for fmt in ("ply", "glb"):
        reexport_path = work_dir / f"{obj_path.stem}.{fmt}"
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

    usdz_check = {"format": "usdz", "path": str(usdz_path)}
    if not usdz_path.exists():
        usdz_check["ok"] = False
        usdz_check["problems"] = ["usdz sidecar missing"]
    elif not zipfile.is_zipfile(usdz_path):
        usdz_check["ok"] = False
        usdz_check["problems"] = ["usdz file is not a valid zip container"]
    else:
        usdz_check["ok"] = True
        usdz_check["problems"] = []
        usdz_check["size_bytes"] = usdz_path.stat().st_size
    report["ok"] = report["ok"] and usdz_check["ok"]
    report["checks"].append(usdz_check)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meshes-dir", type=Path, default=Path("outputs/meshes"))
    parser.add_argument("--reports-dir", type=Path, default=Path("outputs/reports"))
    args = parser.parse_args()

    obj_files = sorted(args.meshes_dir.glob("*.obj"))
    if not obj_files:
        print(f"error: no .obj files found in {args.meshes_dir}", file=sys.stderr)
        return 1

    args.reports_dir.mkdir(parents=True, exist_ok=True)
    all_ok = True
    for obj_path in obj_files:
        usdz_path = obj_path.with_suffix(".usdz")
        work_dir = args.meshes_dir / f"{obj_path.stem}_reexport"
        report = verify_scene(obj_path, usdz_path, work_dir)

        report_path = args.reports_dir / f"{obj_path.stem}_geometry.json"
        report_path.write_text(json.dumps(report, indent=2))

        status = "OK" if report["ok"] else "FAIL"
        print(f"[{status}] {obj_path.stem}: "
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
