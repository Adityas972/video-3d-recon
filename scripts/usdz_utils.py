"""Shared helper for reading a mesh out of Apple's .usdz output.

PhotogrammetrySession.Request.modelFile only accepts a .usdz output path on
this OS/API version -- requesting .obj or .ply directly throws
invalidOutput (confirmed empirically; earlier drafts of this pipeline
assumed multi-format export was available). usdz has no first-class reader
in trimesh, so this uses the actual USD Python bindings (pxr, from the
usd-core package) to pull out the mesh's points/face topology and hands
back a plain trimesh.Trimesh, which is what the rest of the pipeline
(round-trip export, mesh stats, rendering) already works with.
"""
from pathlib import Path

import numpy as np
import trimesh
from pxr import Usd, UsdGeom


def load_usdz_as_trimesh(usdz_path: Path) -> trimesh.Trimesh:
    stage = Usd.Stage.Open(str(usdz_path))
    if stage is None:
        raise ValueError(f"could not open USD stage: {usdz_path}")

    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            mesh = UsdGeom.Mesh(prim)
            points = np.array(mesh.GetPointsAttr().Get(), dtype=np.float64)
            face_counts = np.array(mesh.GetFaceVertexCountsAttr().Get())
            face_indices = np.array(mesh.GetFaceVertexIndicesAttr().Get())

            if not np.all(face_counts == 3):
                # Object Capture's exports have been triangles in testing;
                # fail loudly rather than silently mis-triangulating an
                # n-gon mesh if that ever changes.
                raise ValueError(
                    f"{usdz_path} has non-triangular faces "
                    f"(counts include {sorted(set(face_counts.tolist()) - {3})}); "
                    "this loader only handles triangle meshes")

            faces = face_indices.reshape(-1, 3)
            return trimesh.Trimesh(vertices=points, faces=faces, process=False)

    raise ValueError(f"no UsdGeom.Mesh prim found in {usdz_path}")
