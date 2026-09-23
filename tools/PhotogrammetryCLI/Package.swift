// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "PhotogrammetryCLI",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(name: "PhotogrammetryCLI")
    ]
)
