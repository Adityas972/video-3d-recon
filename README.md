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
  `.usdz` is the only output extension the API accepts for a `modelFile`
  request (confirmed empirically — `.obj`/`.ply` both throw `invalidOutput`
  on this OS/API version), so it's the only format requested from Apple's
  side; every other format comes from this pipeline's own export code.
- **Geometry pipeline**: `scripts/usdz_utils.py` reads the mesh back out of
  the `.usdz` via USD's own Python bindings (`pxr`, from `usd-core`) — no
  format-conversion trust in Apple's exporter is assumed. From there,
  `scripts/03_verify_geometry.py` independently re-exports the mesh to
  `.obj`, `.ply`, and `.glb`, reloads each with `trimesh`, and checks
  vertex/face counts and surface area survive the round trip. Exits
  non-zero on any mismatch, so it can gate a pipeline run the way a CI
  check would.
- **Auto-crop to subject** (opt-in, `--auto-crop-subject`): for a fixed-camera
  shot where a rotating subject shares the frame with other static clutter,
  `scripts/01b_crop_to_subject.py` stacks all frames, takes per-pixel
  variance over time, and crops to the bounding box of the one region that
  actually changes — the static parts vanish identically across frames, so
  they contribute zero variance. Refuses to crop (leaves frames untouched)
  if the detected region covers most of the frame, since that means the
  *whole* frame is changing — i.e. this is a real camera-orbit capture,
  where there's nothing static to crop away from and this technique doesn't
  apply.
- **Self-test fixture**: `scripts/00_generate_synthetic_test_video.py`
  renders a textured, Lambertian-shaded low-poly shape orbited by a virtual
  camera and encodes it to an `.mp4`, so the full pipeline can be exercised
  end-to-end without waiting on a real capture. It is not a substitute for
  testing against real footage (see Results).
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

To try the pipeline immediately without a real capture:

```bash
python scripts/00_generate_synthetic_test_video.py
python run_pipeline.py --video data/raw/synthetic_orbit.mp4 --scene synth --fps 12
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

Add `--auto-crop-subject` if the shot has other static objects/props
sharing the frame with the subject (see "Auto-crop to subject" above and
the real-footage case in Results) — omit it for a genuine camera-orbit
capture, where it has nothing valid to do.

3. Read `outputs/reports/mug_report.md`.

Each stage can also be run standalone (`scripts/01_extract_frames.py`,
`scripts/02_run_photogrammetry.sh`, etc.) — useful when only the last stage
needs rerunning after tweaking a threshold.

## Results

**Synthetic smoke test** (72-frame rendered orbit, `scripts/00_generate_synthetic_test_video.py`
— confirms the pipeline is mechanically correct end-to-end, *not* a stand-in
for real-world reconstruction quality: a matplotlib render has none of the
lighting falloff, sensor noise, or lens distortion real photos do):

| Detail | Time (s) | Vertices | Faces | Watertight | Verified |
|---|---|---|---|---|---|
| preview | 3.8 | 1314 | 2619 | False | yes |
| reduced | 5.7 | 1381 | 2758 | True | yes |

61 of 72 sampled frames survived blur filtering (0 skipped/invalid by
Object Capture itself) and every geometry round-trip check (`.usdz` →
`.obj`/`.ply`/`.glb` → reload) passed at both detail levels. `preview`
came out non-watertight (a small hole in the low-poly approximation) while
`reduced` didn't — expected run-to-run/detail-level variance in the mesh
simplification, not a bug.

**Real footage (Pexels stock video, a globe/cylinder/cube studio still-life,
camera fixed, globe motorized to spin in place)**: ran end-to-end and
surfaced two real issues, both now fixed in code.

How this was run: the clip is Pexels video 7601710 by Marina Leonova
(13s, 1080p, [Pexels License](https://www.pexels.com/license/)), fetched
through the official Pexels API with a free key — scraping Pexels/Pixabay
directly is blocked by Cloudflare. It is not committed to this repo
(`data/raw/` is gitignored). Final run:

```bash
python run_pipeline.py --video data/raw/pexels_globe.mp4 --scene globe \
    --fps 6 --auto-crop-subject --details preview
```

81 frames sampled at 6 fps, 69 kept after dropping the blurriest 15%,
cropped to a 445×451 region (9.7% of the frame), then reconstructed by
Object Capture at `preview` detail in ~4s with 0 skipped/invalid frames.
There is no ground-truth mesh for this clip, so "coherent" below is a
visual judgment of the rendered thumbnails, not a measured accuracy.

1. **The blur filter dropped every single frame.** Variance-of-Laplacian
   scales with scene contrast, not just focus — this clip's moody, low-key
   studio lighting scored 8-16 across the board against a threshold (60)
   tuned on brighter test frames. Fixed by switching `01_extract_frames.py`
   to drop the blurriest *percentile* of the sampled set instead of an
   absolute cutoff, which self-calibrates to each video's lighting.
2. **The reconstruction was geometrically wrong, and verification didn't
   catch it.** First attempt (no crop):

   | Detail | Vertices | Faces | Watertight | Verified |
   |---|---|---|---|---|
   | preview | 1558 | 3022 | False | yes |

   — a single fused blob, part sphere, part flattened slab, because the
   shot has a fixed camera with only the globe rotating while the cube and
   cylinder behind it stay static. SfM assumes one rigid scene across all
   views; two independently-moving things sharing a frame breaks that no
   matter how clean the feature matching is. Verification still said "yes"
   because it only checks format round-trip integrity, not reconstruction
   accuracy — a real gap between the two worth knowing about, not papering
   over.

   Fixed with `scripts/01b_crop_to_subject.py` (`--auto-crop-subject`):
   crop to the one region with temporal variance (the spinning globe),
   which removes the confounding static geometry entirely before it
   reaches Object Capture:

   | Detail | Vertices | Faces | Watertight | Verified |
   |---|---|---|---|---|
   | preview | 929 | 1840 | False | yes |

   Now a single round, blob-like shape — not a perfect sphere (a fixed
   camera watching an object spin in place still has no true stereo
   parallax on that object, only texture and silhouette cues), but a
   coherent single-object reconstruction instead of a fused mess.

**Real capture with genuine camera motion**: still not run. A second stock
clip (Pexels 7317794, a static-tripod push-in on a statue) was checked and rejected for the
same underlying reason — no angular parallax, just a zoom. Stock b-roll is
shot for visual storytelling, not photogrammetry, and in practice almost
none of it has the camera path Object Capture needs. Filming a real
~30-45s phone orbit around a small object by hand — genuine lateral motion
around a single static subject, camera actually moving — is the one case
neither the synthetic fixture nor either stock clip has tested yet, and
the remaining way to see this pipeline's true reconstruction quality.

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
- **Reading `.usdz` back out via `pxr` instead of trusting a second Apple
  export.** Apple's API doesn't offer a second format to cross-check against
  anyway (`.obj`/`.ply` requests are rejected outright), so the independent
  check has to start from parsing the actual USD mesh data, then round-trip
  through a wholly separate library (`trimesh`) for the format conversions.
- **Temporal-variance cropping, opt-in rather than automatic.** It's a
  correct fix only for the "fixed camera, rotating subject plus other
  static clutter" case it was built for; on a genuine camera-orbit capture
  the entire frame legitimately changes with viewpoint, and blindly
  applying this crop would remove real structure instead of confounding
  clutter. It self-guards for that case (skips cropping when the detected
  region covers most of the frame) but stays behind a flag rather than
  running by default.
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
