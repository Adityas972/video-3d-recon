#!/usr/bin/env bash
# Reconstruct a mesh from a directory of frames at one or more detail levels,
# via the PhotogrammetryCLI wrapper around RealityKit's PhotogrammetrySession.
#
# Usage: scripts/02_run_photogrammetry.sh <frames-dir> <scene-name> [detail-levels...]
# Example: scripts/02_run_photogrammetry.sh data/frames/mug mug preview reduced medium
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI_DIR="$ROOT_DIR/tools/PhotogrammetryCLI"
CLI_BIN="$CLI_DIR/.build/release/PhotogrammetryCLI"

FRAMES_DIR="${1:?usage: $0 <frames-dir> <scene-name> [detail-levels...]}"
SCENE="${2:?usage: $0 <frames-dir> <scene-name> [detail-levels...]}"
shift 2
DETAILS=("${@:-medium}")

if [[ ! -x "$CLI_BIN" ]]; then
    echo "[build] PhotogrammetryCLI binary not found, building release build..."
    (cd "$CLI_DIR" && swift build -c release)
fi

OUT_DIR="$ROOT_DIR/outputs/meshes"
mkdir -p "$OUT_DIR"

for DETAIL in "${DETAILS[@]}"; do
    echo "[run] scene=$SCENE detail=$DETAIL"
    # .usdz is the only output extension PhotogrammetrySession.Request.modelFile
    # accepts on this OS/API version -- .obj/.ply requests throw invalidOutput
    # (confirmed empirically). scripts/usdz_utils.py reads the mesh back out
    # of the .usdz for the verification/eval steps.
    "$CLI_BIN" "$FRAMES_DIR" "$DETAIL" \
        "$OUT_DIR/${SCENE}_${DETAIL}.usdz"
done
