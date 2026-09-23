# Video → 3D Mesh Reconstruction Pipeline

Turns a short handheld orbit video of an object into a verified, evaluated
3D mesh, built to run entirely on a MacBook with Apple Silicon and no CUDA:

- **Frame selection**: `scripts/01_extract_frames.py` samples a video with
  `ffmpeg` and drops blurry frames (variance-of-Laplacian focus measure),
  since Object Capture wants a curated set of sharp stills, not raw video.
- **Reconstruction**: `tools/PhotogrammetryCLI` is a small Swift CLI around
  RealityKit's `PhotogrammetrySession` — Apple's on-device structure-from-
  motion + multi-view-stereo engine, Metal-accelerated. Used instead of
  COLMAP+dense-MVS or 3D Gaussian Splatting because both of those require a
  CUDA GPU for the dense/rasterization step, which this Mac doesn't have.
- **Geometry pipeline**: `scripts/03_verify_geometry.py` doesn't trust
  Apple's exporter blindly — it independently re-exports each reconstructed
  mesh to `.ply` and `.glb`, reloads them, and checks vertex/face counts and
  surface area survive the round trip. It also confirms the `.usdz` output
  is at least a well-formed zip container. Exits non-zero on any mismatch,
  so it can gate a pipeline run the way a CI check would.
- **Eval harness**: `scripts/04_eval_harness.py` runs reconstruction at
  multiple detail levels (`preview`/`reduced`/`medium`) and produces one
  Markdown report comparing processing time, mesh complexity, watertightness,
  and verification status per level, with rendered thumbnails per mesh.
- **Orchestration**: `run_pipeline.py` chains all four stages with fail-fast
  behavior and per-stage timing.

## Setup

```bash
brew install ffmpeg
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# builds tools/PhotogrammetryCLI/.build/release/PhotogrammetryCLI on first run
```

Requires macOS 13+ on Apple Silicon (`PhotogrammetrySession.isSupported`
checks this at runtime) and Xcode Command Line Tools for the Swift build.

## Usage

1. Shoot a ~30-45s video orbiting a small, textured, matte object (avoid
   glossy/transparent/featureless surfaces — Object Capture needs visual
   texture to match features across views). Save it to `data/raw/`.
2. Run the pipeline:

```bash
python run_pipeline.py --video data/raw/mug.mov --scene mug
```

3. Read `outputs/reports/mug_report.md`.

Each stage can also be run standalone (`scripts/01_extract_frames.py`,
`scripts/02_run_photogrammetry.sh`, etc.) — useful when only the last stage
needs rerunning after tweaking a threshold.

## Results

*(Fill in after a real capture — this scaffold has been smoke-tested with
synthetic meshes and a placeholder image set to verify the pipeline
plumbing, but not yet run on a real object capture.)*

| Detail | Time (s) | Vertices | Faces | Watertight | Verified |
|---|---|---|---|---|---|
| preview | — | — | — | — | — |
| reduced | — | — | — | — | — |
| medium | — | — | — | — | — |

## Why this design

- **Apple Object Capture over COLMAP+MVS or Gaussian Splatting.** Dense
  multi-view stereo (COLMAP's `patch_match_stereo`) and Gaussian Splatting
  rasterizers are CUDA-only — there's no CPU or Metal fallback in the
  standard toolchains. `PhotogrammetrySession` is the one reconstruction
  engine on this hardware that does full SfM + dense MVS + meshing +
  texturing with GPU acceleration that isn't CUDA. The tradeoff: it's a
  black box for the SfM/MVS math itself, so the engineering surface area
  here is deliberately everything *around* it — format verification, an
  eval harness, and pipeline tooling — rather than the reconstruction
  algorithm.
- **Blur-based frame filtering before reconstruction, not after.** Feature
  matching on blurry frames wastes time and can introduce bad matches;
  filtering at ingest is cheaper than debugging a bad reconstruction later.
- **Independent re-export in the verification step**, rather than trusting
  Apple's own multi-format export. If `PhotogrammetrySession` ever silently
  degraded one export format relative to another, checking Apple's `.obj`
  against Apple's `.usdz` wouldn't catch it — round-tripping through a
  separate library (`trimesh`) is a genuinely independent check.
- **Matplotlib thumbnails over an OpenGL/pyglet renderer.** trimesh's
  built-in viewer needs a real windowing context and was flaky in testing
  on this pyglet/macOS combination; a flat-shaded matplotlib render has no
  such dependency and degrades gracefully (logs a warning, doesn't fail the
  run) if it ever can't render.

## Stretch / future work

- Bootstrap camera poses from a monocular depth model (e.g. Depth Anything)
  for scenes with too little texture for Object Capture's feature matching
  to converge — this is the natural bridge to prior video-perception work
  (VideoMAE/V-JEPA-style backbones) rather than relying purely on classical
  feature matching.
- Run 3D Gaussian Splatting on a rented CUDA instance as a quality/speed
  comparison against Object Capture's MVS mesh, using the same eval harness.
- Extend the eval harness with held-out-view rendering + PSNR/SSIM against
  the actual photo at that camera pose, once camera poses are exposed from
  the reconstruction (currently only the final mesh is available from
  `PhotogrammetrySession`'s public API, not the intermediate camera graph).
