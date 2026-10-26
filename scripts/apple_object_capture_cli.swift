import Foundation
import RealityKit

enum CLIError: Error, CustomStringConvertible {
    case missingValue(String)
    case missingRequiredArgument(String)
    case unsupportedDetail(String)
    case unsupportedPlatform
    case requestFailed(String)

    var description: String {
        switch self {
        case .missingValue(let flag):
            return "missing value for \(flag)"
        case .missingRequiredArgument(let flag):
            return "missing required argument \(flag)"
        case .unsupportedDetail(let value):
            return "unsupported detail \(value)"
        case .unsupportedPlatform:
            return "PhotogrammetrySession requires macOS 12 or newer"
        case .requestFailed(let message):
            return message
        }
    }
}

struct Arguments {
    var imagesDir: String?
    var outputUsdz: String?
    var detail: String = "medium"
    var check: Bool = false
}

@main
struct AppleObjectCaptureCLI {
    static func main() async {
        do {
            let args = try parseArguments(CommandLine.arguments)
            if args.check {
                print("{\"ok\":true,\"provider\":\"apple_object_capture\",\"mode\":\"check\"}")
                return
            }
            guard #available(macOS 12.0, *) else {
                throw CLIError.unsupportedPlatform
            }
            guard let imagesDir = args.imagesDir else {
                throw CLIError.missingRequiredArgument("--images-dir")
            }
            guard let outputUsdz = args.outputUsdz else {
                throw CLIError.missingRequiredArgument("--output-usdz")
            }
            try await runPhotogrammetry(imagesDir: imagesDir, outputUsdz: outputUsdz, detail: args.detail)
        } catch {
            fputs("{\"ok\":false,\"error\":\"\(escapeJSON(String(describing: error)))\"}\n", stderr)
            Foundation.exit(1)
        }
    }
}

func parseArguments(_ argv: [String]) throws -> Arguments {
    var args = Arguments()
    var index = 1
    while index < argv.count {
        let flag = argv[index]
        switch flag {
        case "--images-dir":
            args.imagesDir = try value(after: flag, in: argv, at: &index)
        case "--output-usdz":
            args.outputUsdz = try value(after: flag, in: argv, at: &index)
        case "--detail":
            args.detail = try value(after: flag, in: argv, at: &index)
        case "--check":
            args.check = true
            index += 1
        default:
            index += 1
        }
    }
    return args
}

func value(after flag: String, in argv: [String], at index: inout Int) throws -> String {
    let valueIndex = index + 1
    guard valueIndex < argv.count else {
        throw CLIError.missingValue(flag)
    }
    index += 2
    return argv[valueIndex]
}

@available(macOS 12.0, *)
func runPhotogrammetry(imagesDir: String, outputUsdz: String, detail: String) async throws {
    let inputURL = URL(fileURLWithPath: imagesDir, isDirectory: true)
    let outputURL = URL(fileURLWithPath: outputUsdz)
    try FileManager.default.createDirectory(at: outputURL.deletingLastPathComponent(), withIntermediateDirectories: true)

    var configuration = PhotogrammetrySession.Configuration()
    configuration.isObjectMaskingEnabled = true
    let session = try PhotogrammetrySession(input: inputURL, configuration: configuration)
    let request = PhotogrammetrySession.Request.modelFile(url: outputURL, detail: try requestDetail(detail))
    try session.process(requests: [request])

    var completed = false
    for try await output in session.outputs {
        switch output {
        case .requestComplete(_, _):
            completed = true
        case .requestProgress(_, fractionComplete: let fractionComplete):
            fputs("request_progress fraction=\(fractionComplete)\n", stderr)
        case .requestProgressInfo(_, let info):
            fputs("request_progress_info \(info)\n", stderr)
        case .inputComplete:
            fputs("input_complete\n", stderr)
        case .stitchingIncomplete:
            fputs("stitching_incomplete\n", stderr)
        case .requestError(_, let error):
            throw CLIError.requestFailed("request_error: \(error)")
        case .processingComplete:
            if completed && FileManager.default.fileExists(atPath: outputURL.path) {
                print("{\"ok\":true,\"provider\":\"apple_object_capture\",\"output_usdz\":\"\(escapeJSON(outputURL.path))\"}")
                return
            }
            throw CLIError.requestFailed("processing_complete_without_output_file")
        case .processingCancelled:
            throw CLIError.requestFailed("processing_cancelled")
        case .invalidSample(let id, let reason):
            fputs("invalid_sample id=\(id) reason=\(reason)\n", stderr)
        case .skippedSample(let id):
            fputs("skipped_sample id=\(id)\n", stderr)
        case .automaticDownsampling:
            fputs("automatic_downsampling\n", stderr)
        @unknown default:
            fputs("unknown_output \(output)\n", stderr)
        }
    }
    throw CLIError.requestFailed("session_outputs_finished_without_completion")
}

@available(macOS 12.0, *)
func requestDetail(_ value: String) throws -> PhotogrammetrySession.Request.Detail {
    switch value.lowercased() {
    case "preview":
        return .preview
    case "reduced":
        return .reduced
    case "medium":
        return .medium
    case "full":
        return .full
    case "raw":
        return .raw
    default:
        throw CLIError.unsupportedDetail(value)
    }
}

func escapeJSON(_ value: String) -> String {
    value
        .replacingOccurrences(of: "\\", with: "\\\\")
        .replacingOccurrences(of: "\"", with: "\\\"")
        .replacingOccurrences(of: "\n", with: "\\n")
}
