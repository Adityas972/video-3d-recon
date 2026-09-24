// Minimal CLI wrapper around RealityKit's PhotogrammetrySession (Apple's
// on-device structure-from-motion + multi-view-stereo engine). Runs Metal-
// accelerated dense reconstruction with no CUDA dependency, which is why
// this project uses it instead of COLMAP+dense-MVS or a Gaussian Splatting
// stack on Apple Silicon.
//
// Usage:
//   PhotogrammetryCLI <input-frames-dir> <preview|reduced|medium|full|raw> <output.usdz> [output2.usdz ...]
//
// .usdz is the only extension Request.modelFile accepts on this OS/API
// version -- .obj/.ply requests throw invalidOutput (confirmed empirically).
// Multiple output paths are still supported (e.g. writing several detail
// levels' worth of .usdz from one input set), sharing a single feature-
// matching + pose-estimation pass.
//
// On success, writes a JSON stats sidecar next to the FIRST output model
// (same path with .stats.json appended) recording sample counts, detail
// level, and wall-clock time, which scripts/04_eval_harness.py consumes.

import Foundation
import RealityKit

struct CLIError: Error, CustomStringConvertible {
    let description: String
}

func parseDetail(_ raw: String) throws -> PhotogrammetrySession.Request.Detail {
    switch raw.lowercased() {
    case "preview": return .preview
    case "reduced": return .reduced
    case "medium": return .medium
    case "full": return .full
    case "raw": return .raw
    default:
        throw CLIError(description: "Unknown detail level '\(raw)'. Use preview|reduced|medium|full|raw.")
    }
}

@main
struct PhotogrammetryCLI {
    static func main() async {
        let args = CommandLine.arguments
        guard args.count >= 4 else {
            FileHandle.standardError.write(
                "Usage: PhotogrammetryCLI <input-frames-dir> <preview|reduced|medium|full|raw> <output1> [output2 ...]\n"
                    .data(using: .utf8)!)
            exit(64)
        }

        let inputPath = args[1]
        let detailArg = args[2]
        let outputPaths = Array(args[3...])

        do {
            guard PhotogrammetrySession.isSupported else {
                throw CLIError(description: "PhotogrammetrySession is not supported on this Mac (needs Apple Silicon).")
            }

            let detail = try parseDetail(detailArg)
            let inputURL = URL(fileURLWithPath: inputPath, isDirectory: true)
            let outputURLs = outputPaths.map { URL(fileURLWithPath: $0) }

            var configuration = PhotogrammetrySession.Configuration()
            configuration.sampleOrdering = .unordered
            configuration.featureSensitivity = .normal

            let session = try PhotogrammetrySession(input: inputURL, configuration: configuration)
            let requests = outputURLs.map { PhotogrammetrySession.Request.modelFile(url: $0, detail: detail) }

            var invalidSamples = 0
            var skippedSamples = 0
            var requestIssues: [String] = []
            var completedOutputs: [String] = []
            let startedAt = Date()

            try session.process(requests: requests)

            for try await output in session.outputs {
                switch output {
                case .inputComplete:
                    FileHandle.standardError.write("[input] all frames enumerated\n".data(using: .utf8)!)
                case .invalidSample(let id, let reason):
                    invalidSamples += 1
                    FileHandle.standardError.write("[invalid] sample \(id): \(reason)\n".data(using: .utf8)!)
                case .skippedSample(let id):
                    skippedSamples += 1
                    FileHandle.standardError.write("[skipped] sample \(id)\n".data(using: .utf8)!)
                case .requestProgress(_, let fraction):
                    FileHandle.standardError.write(
                        String(format: "[progress] %.1f%%\r", fraction * 100).data(using: .utf8)!)
                case .requestComplete(_, let result):
                    if case .modelFile(let url) = result {
                        completedOutputs.append(url.path)
                        FileHandle.standardError.write("\n[complete] model written to \(url.path)\n".data(using: .utf8)!)
                    }
                case .requestError(_, let error):
                    requestIssues.append(String(describing: error))
                    FileHandle.standardError.write("[error] request failed: \(error)\n".data(using: .utf8)!)
                case .processingComplete:
                    let elapsed = Date().timeIntervalSince(startedAt)
                    let stats: [String: Any] = [
                        "detail": detailArg,
                        "elapsedSeconds": elapsed,
                        "invalidSamples": invalidSamples,
                        "skippedSamples": skippedSamples,
                        "requestIssues": requestIssues,
                        "outputPaths": outputURLs.map(\.path),
                        "completedOutputs": completedOutputs,
                        "succeeded": requestIssues.isEmpty && completedOutputs.count == outputURLs.count,
                    ]
                    guard let firstOutput = outputPaths.first else {
                        exit(requestIssues.isEmpty ? 0 : 1)
                    }
                    let statsURL = URL(fileURLWithPath: firstOutput + ".stats.json")
                    let data = try JSONSerialization.data(withJSONObject: stats, options: [.prettyPrinted])
                    try data.write(to: statsURL)
                    exit(requestIssues.isEmpty ? 0 : 1)
                case .processingCancelled:
                    throw CLIError(description: "Processing was cancelled.")
                case .automaticDownsampling:
                    FileHandle.standardError.write("[warn] automatic downsampling triggered (input too large for memory)\n".data(using: .utf8)!)
                case .stitchingIncomplete:
                    FileHandle.standardError.write("[warn] stitching incomplete\n".data(using: .utf8)!)
                case .requestProgressInfo:
                    continue
                @unknown default:
                    continue
                }
            }
        } catch {
            FileHandle.standardError.write("PhotogrammetryCLI failed: \(error)\n".data(using: .utf8)!)
            exit(1)
        }
    }
}
