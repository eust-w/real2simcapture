import Foundation
import RoomPlan

struct CapturePackageBuilder {
    func packageObjectCapture(imagesDirectory: URL, checkpointDirectory: URL) throws -> URL {
        let packageRoot = try freshPackageRoot(prefix: "object")
        let imagesTarget = packageRoot.appendingPathComponent("images", isDirectory: true)
        let checkpointTarget = packageRoot.appendingPathComponent("checkpoints", isDirectory: true)
        try FileManager.default.createDirectory(at: imagesTarget, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: checkpointTarget, withIntermediateDirectories: true)
        try copyDirectoryContents(from: imagesDirectory, to: imagesTarget)
        try copyDirectoryContents(from: checkpointDirectory, to: checkpointTarget)
        try writeMetadata(
            [
                "mode": "asset",
                "source": "RealityKit ObjectCaptureSession",
                "created_at": ISO8601DateFormatter().string(from: Date())
            ],
            to: packageRoot.appendingPathComponent("capture_manifest.json")
        )
        return try zip(packageRoot: packageRoot, name: "object_capture.zip")
    }

    func packageRoomCapture(room: CapturedRoom) throws -> URL {
        let packageRoot = try freshPackageRoot(prefix: "room")
        let roomUSD = packageRoot.appendingPathComponent("roomplan.usd")
        let roomJSON = packageRoot.appendingPathComponent("roomplan.json")
        try room.export(to: roomUSD, exportOptions: .mesh)
        let encodedRoom = try JSONEncoder.pretty.encode(room)
        try encodedRoom.write(to: roomJSON)
        try writeMetadata(
            [
                "mode": "scene",
                "source": "RoomPlan RoomCaptureView",
                "created_at": ISO8601DateFormatter().string(from: Date())
            ],
            to: packageRoot.appendingPathComponent("capture_manifest.json")
        )
        return try zip(packageRoot: packageRoot, name: "room_capture.zip")
    }

    func packageARSceneCapture(captureRoot: URL) throws -> URL {
        guard FileManager.default.fileExists(atPath: captureRoot.path) else {
            throw CocoaError(.fileNoSuchFile)
        }
        return try zip(packageRoot: captureRoot, name: "arkit_rgbd_scene_capture.zip")
    }

    private func freshPackageRoot(prefix: String) throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("Real2SimPackages", isDirectory: true)
            .appendingPathComponent("\(prefix)-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }

    private func copyDirectoryContents(from source: URL, to target: URL) throws {
        guard FileManager.default.fileExists(atPath: source.path) else { return }
        let contents = try FileManager.default.contentsOfDirectory(at: source, includingPropertiesForKeys: nil)
        for item in contents {
            let destination = target.appendingPathComponent(item.lastPathComponent)
            var isDirectory: ObjCBool = false
            FileManager.default.fileExists(atPath: item.path, isDirectory: &isDirectory)
            if isDirectory.boolValue {
                try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
                try copyDirectoryContents(from: item, to: destination)
            } else {
                if FileManager.default.fileExists(atPath: destination.path) {
                    try FileManager.default.removeItem(at: destination)
                }
                try FileManager.default.copyItem(at: item, to: destination)
            }
        }
    }

    private func writeMetadata(_ metadata: [String: String], to url: URL) throws {
        let data = try JSONEncoder.pretty.encode(metadata)
        try data.write(to: url)
    }

    private func zip(packageRoot: URL, name: String) throws -> URL {
        let zipURL = packageRoot.deletingLastPathComponent().appendingPathComponent(name)
        if FileManager.default.fileExists(atPath: zipURL.path) {
            try FileManager.default.removeItem(at: zipURL)
        }
        try ZipWriter.writeDirectory(packageRoot, to: zipURL)
        return zipURL
    }
}

private extension JSONEncoder {
    static var pretty: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return encoder
    }
}
