import ARKit
import CoreImage
import RealityKit
import SwiftUI
import UIKit

struct ARSceneCaptureScreen: View {
    @EnvironmentObject private var store: CaptureStore
    @StateObject private var controller = ARSceneCaptureController()
    @AppStorage("real2sim.serverURL") private var serverURL = "http://workstation.local:8000"
    @AppStorage("real2sim.projectID") private var projectID = ""
    @State private var taskName = "live scene scan"
    @State private var category = "scene"
    @State private var massKg = ""
    @State private var friction = ""

    var body: some View {
        ZStack(alignment: .bottom) {
            if controller.isSupported {
                ARSceneCaptureView(controller: controller)
                    .ignoresSafeArea(edges: .horizontal)
            } else {
                ContentUnavailableView("ARKit RGB-D scene capture requires LiDAR scene depth and mesh reconstruction.", systemImage: "sensor.tag.radiowaves.forward")
            }

            VStack(alignment: .leading, spacing: 10) {
                Grid(alignment: .leading, horizontalSpacing: 8, verticalSpacing: 6) {
                    GridRow {
                        Text("Server")
                        TextField("http://workstation.local:8000", text: $serverURL)
                            .textInputAutocapitalization(.never)
                            .keyboardType(.URL)
                    }
                    GridRow {
                        Text("Project")
                        TextField("Backend project UUID", text: $projectID)
                            .textInputAutocapitalization(.never)
                    }
                    GridRow {
                        Text("Task")
                        TextField("Live scan", text: $taskName)
                    }
                    GridRow {
                        Text("Category")
                        TextField("scene / workcell", text: $category)
                    }
                    GridRow {
                        Text("Mass")
                        TextField("optional", text: $massKg)
                            .keyboardType(.decimalPad)
                    }
                    GridRow {
                        Text("Friction")
                        TextField("optional", text: $friction)
                            .keyboardType(.decimalPad)
                    }
                }
                .font(.caption)

                HStack(spacing: 10) {
                    Button {
                        controller.startLive(
                            serverURL: serverURL,
                            projectID: projectID,
                            taskName: taskName,
                            category: category,
                            massKg: massKg,
                            friction: friction
                        )
                    } label: {
                        Label("Start Live", systemImage: "dot.radiowaves.left.and.right")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!controller.isSupported || controller.isRecording || controller.isLiveStreaming || controller.isStartingLive || taskName.isEmpty)

                    Button {
                        controller.stopLiveAndFinalize()
                    } label: {
                        Label("Finalize Live", systemImage: "checkmark.circle")
                    }
                    .buttonStyle(.bordered)
                    .disabled(!controller.isLiveStreaming || controller.isFinalizing)
                }

                HStack(spacing: 10) {
                    Button {
                        controller.start()
                    } label: {
                        Label("Start", systemImage: "record.circle")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!controller.isSupported || controller.isRecording || controller.isLiveStreaming)

                    Button {
                        controller.stop()
                    } label: {
                        Label("Stop", systemImage: "stop.circle")
                    }
                    .buttonStyle(.bordered)
                    .disabled(!controller.isRecording)

                    Button {
                        if let root = controller.finishForPackaging() {
                            store.packageARSceneCapture(captureRoot: root)
                        }
                    } label: {
                        Label("Package", systemImage: "shippingbox")
                    }
                    .buttonStyle(.bordered)
                    .disabled(controller.frameCount == 0 || controller.isLiveStreaming)
                }

                Text("Frames \(controller.frameCount) Depth \(controller.depthFrameCount) Mesh anchors \(controller.meshAnchorCount)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if let liveSessionID = controller.liveSessionID {
                    Text("Live \(liveSessionID.prefix(8)) uploaded \(controller.liveUploadedFrameCount) frames")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let message = controller.liveStatusMessage {
                    Text(message)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let error = controller.liveUploadError {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            }
            .padding(12)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10))
            .padding()
        }
    }
}

struct ARSceneCaptureView: UIViewRepresentable {
    @ObservedObject var controller: ARSceneCaptureController

    func makeUIView(context: Context) -> ARView {
        let view = ARView(frame: .zero)
        view.automaticallyConfigureSession = false
        view.debugOptions.insert(.showSceneUnderstanding)
        controller.attach(session: view.session)
        return view
    }

    func updateUIView(_ uiView: ARView, context: Context) {}
}

final class ARSceneCaptureController: NSObject, ObservableObject, ARSessionDelegate {
    @Published private(set) var isRecording = false
    @Published private(set) var isStartingLive = false
    @Published private(set) var isLiveStreaming = false
    @Published private(set) var isFinalizing = false
    @Published private(set) var liveSessionID: String?
    @Published private(set) var liveUploadedFrameCount = 0
    @Published private(set) var liveStatusMessage: String?
    @Published private(set) var liveUploadError: String?
    @Published private(set) var frameCount = 0
    @Published private(set) var depthFrameCount = 0
    @Published private(set) var meshAnchorCount = 0

    private let liveClient = LiveSessionClient()
    private var session: ARSession?
    private var captureRoot: URL?
    private var imagesDirectory: URL?
    private var depthDirectory: URL?
    private var poseRecords: [ARPoseRecord] = []
    private var intrinsics: ARIntrinsicsRecord?
    private var meshAnchors: [UUID: ARMeshAnchor] = [:]
    private var lastFrameTimestamp: TimeInterval = 0
    private let frameInterval: TimeInterval = 0.5
    private let ciContext = CIContext()
    private var liveServerURL: String?
    private var uploadTask: Task<Void, Never>?
    private var pendingFrames: [LiveFrameUpload] = []
    private var uploadedFrameIDs: Set<String> = []
    private var lastMeshUploadTime: TimeInterval = 0
    private var meshDirty = false

    var isSupported: Bool {
        ARWorldTrackingConfiguration.isSupported
            && ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)
            && ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh)
    }

    func attach(session: ARSession) {
        self.session = session
        session.delegate = self
        session.delegateQueue = .main
    }

    func start() {
        guard isSupported, let session else { return }
        do {
            try prepareCaptureRoot()
            poseRecords = []
            intrinsics = nil
            meshAnchors = [:]
            lastFrameTimestamp = 0
            frameCount = 0
            depthFrameCount = 0
            meshAnchorCount = 0
            isRecording = true
        } catch {
            isRecording = false
            liveUploadError = error.localizedDescription
            return
        }

        let configuration = ARWorldTrackingConfiguration()
        configuration.planeDetection = [.horizontal, .vertical]
        configuration.frameSemantics.insert(.sceneDepth)
        if ARWorldTrackingConfiguration.supportsFrameSemantics(.smoothedSceneDepth) {
            configuration.frameSemantics.insert(.smoothedSceneDepth)
        }
        if ARWorldTrackingConfiguration.supportsSceneReconstruction(.meshWithClassification) {
            configuration.sceneReconstruction = .meshWithClassification
        } else {
            configuration.sceneReconstruction = .mesh
        }
        session.run(configuration, options: [.resetTracking, .removeExistingAnchors])
    }

    func stop() {
        guard isRecording else { return }
        isRecording = false
        session?.pause()
        writeCaptureMetadata()
    }

    func finishForPackaging() -> URL? {
        if isRecording {
            stop()
        } else {
            writeCaptureMetadata()
        }
        return captureRoot
    }

    func startLive(serverURL: String, projectID: String, taskName: String, category: String, massKg: String, friction: String) {
        guard isSupported, !isRecording, !isStartingLive else { return }
        isStartingLive = true
        liveUploadError = nil
        liveStatusMessage = "Creating live session..."
        Task { @MainActor in
            do {
                let resolvedProjectID: String
                if projectID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    let project = try await liveClient.createProject(serverURL: serverURL, name: taskName)
                    resolvedProjectID = project.id
                } else {
                    resolvedProjectID = projectID
                }
                let session = try await liveClient.createSession(
                    serverURL: serverURL,
                    projectID: resolvedProjectID,
                    name: taskName,
                    category: category,
                    massKg: massKg.isEmpty ? nil : massKg,
                    friction: friction.isEmpty ? nil : friction
                )
                await MainActor.run {
                    liveSessionID = session.id
                    liveServerURL = serverURL
                    liveUploadedFrameCount = 0
                    pendingFrames = []
                    uploadedFrameIDs = []
                    lastMeshUploadTime = 0
                    isLiveStreaming = true
                    isStartingLive = false
                    liveStatusMessage = "Live session \(session.id.prefix(8)) is recording."
                    start()
                    if !isRecording {
                        isLiveStreaming = false
                    }
                }
            } catch {
                await MainActor.run {
                    isStartingLive = false
                    isLiveStreaming = false
                    liveUploadError = error.localizedDescription
                    liveStatusMessage = nil
                }
            }
        }
    }

    func stopLiveAndFinalize() {
        guard !isFinalizing, let sessionID = liveSessionID, let serverURL = liveServerURL else { return }
        isFinalizing = true
        if isRecording {
            stop()
        }
        let pendingUpload = uploadTask
        let meshURL = captureRoot?.appendingPathComponent("arkit_mesh.obj")
        liveStatusMessage = "Finalizing live session..."
        Task { @MainActor in
            defer { isFinalizing = false }
            await pendingUpload?.value
            do {
                // Frames deferred by live backpressure remain on disk and are drained here.
                if let root = captureRoot {
                    for pose in poseRecords where !uploadedFrameIDs.contains(pose.id) {
                        let frame = LiveFrameUpload(frameID: pose.id, timestamp: pose.timestamp, trackingState: pose.trackingState, transform: pose.transform, intrinsics: intrinsics, imageURL: root.appendingPathComponent(pose.image), depthURL: pose.depth.map { root.appendingPathComponent($0) })
                        let response = try await liveClient.uploadFrame(serverURL: serverURL, sessionID: sessionID, frame: frame)
                        uploadedFrameIDs.insert(pose.id)
                        liveUploadedFrameCount = response.frameCount
                    }
                }
                if meshAnchorCount > 0, let meshURL, FileManager.default.fileExists(atPath: meshURL.path) {
                    _ = try await liveClient.uploadMesh(serverURL: serverURL, sessionID: sessionID, meshURL: meshURL)
                }
                let finalized = try await liveClient.finalizeSession(serverURL: serverURL, sessionID: sessionID)
                await MainActor.run {
                    isLiveStreaming = false
                    pendingFrames = []
                    liveStatusMessage = "Finalized live task \(finalized.task.id.prefix(8)) with status \(finalized.task.status)."
                    liveUploadError = nil
                }
            } catch {
                await MainActor.run {
                    liveUploadError = error.localizedDescription
                }
            }
        }
    }

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        guard isRecording else { return }
        guard frame.timestamp - lastFrameTimestamp >= frameInterval else { return }
        guard let imagesDirectory, let depthDirectory else { return }
        lastFrameTimestamp = frame.timestamp

        let frameID = String(format: "frame_%06d", frameCount)
        let imageURL = imagesDirectory.appendingPathComponent("\(frameID).jpg")
        let depthURL = depthDirectory.appendingPathComponent("\(frameID).npy")
        do {
            try CameraFrameWriter.writeJPEG(pixelBuffer: frame.capturedImage, to: imageURL, context: ciContext)
            if let depthMap = (frame.smoothedSceneDepth ?? frame.sceneDepth)?.depthMap {
                try DepthNPYWriter.writeFloat32(pixelBuffer: depthMap, to: depthURL)
                depthFrameCount += 1
                updateIntrinsics(from: frame, depthMap: depthMap)
            }
            let pose = ARPoseRecord(
                id: frameID,
                image: "images/\(frameID).jpg",
                depth: FileManager.default.fileExists(atPath: depthURL.path) ? "depth/\(frameID).npy" : nil,
                timestamp: frame.timestamp,
                transform: frame.camera.transform.columnMajorArray,
                trackingState: frame.camera.trackingState.real2simDescription
            )
            poseRecords.append(pose)
            frameCount += 1
            enqueueLiveFrameUpload(
                frameID: frameID,
                timestamp: frame.timestamp,
                trackingState: pose.trackingState,
                transform: pose.transform,
                imageURL: imageURL,
                depthURL: FileManager.default.fileExists(atPath: depthURL.path) ? depthURL : nil,
                intrinsics: intrinsics
            )
        } catch {
            liveUploadError = error.localizedDescription
        }
    }

    func session(_ session: ARSession, didAdd anchors: [ARAnchor]) {
        updateMeshAnchors(anchors)
    }

    func session(_ session: ARSession, didUpdate anchors: [ARAnchor]) {
        updateMeshAnchors(anchors)
    }

    func session(_ session: ARSession, didRemove anchors: [ARAnchor]) {
        for anchor in anchors { meshAnchors.removeValue(forKey: anchor.identifier) }
        meshAnchorCount = meshAnchors.count
        meshDirty = true
    }

    private func prepareCaptureRoot() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("Real2SimARScene", isDirectory: true)
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let images = root.appendingPathComponent("images", isDirectory: true)
        let depth = root.appendingPathComponent("depth", isDirectory: true)
        try FileManager.default.createDirectory(at: images, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: depth, withIntermediateDirectories: true)
        captureRoot = root
        imagesDirectory = images
        depthDirectory = depth
    }

    private func updateIntrinsics(from frame: ARFrame, depthMap: CVPixelBuffer) {
        let width = CVPixelBufferGetWidth(depthMap)
        let height = CVPixelBufferGetHeight(depthMap)
        let imageResolution = frame.camera.imageResolution
        let scaleX = Float(width) / Float(imageResolution.width)
        let scaleY = Float(height) / Float(imageResolution.height)
        let matrix = frame.camera.intrinsics
        intrinsics = ARIntrinsicsRecord(
            width: width,
            height: height,
            fx: matrix.columns.0.x * scaleX,
            fy: matrix.columns.1.y * scaleY,
            cx: matrix.columns.2.x * scaleX,
            cy: matrix.columns.2.y * scaleY,
            depthScale: 1.0
        )
    }

    private func updateMeshAnchors(_ anchors: [ARAnchor]) {
        for anchor in anchors {
            if let meshAnchor = anchor as? ARMeshAnchor {
                meshAnchors[meshAnchor.identifier] = meshAnchor
                meshDirty = true
            }
        }
        meshAnchorCount = meshAnchors.count
    }

    private func enqueueLiveFrameUpload(
        frameID: String,
        timestamp: TimeInterval,
        trackingState: String,
        transform: [Float],
        imageURL: URL,
        depthURL: URL?,
        intrinsics: ARIntrinsicsRecord?
    ) {
        guard isLiveStreaming, let liveSessionID, let liveServerURL else { return }
        let upload = LiveFrameUpload(
            frameID: frameID,
            timestamp: timestamp,
            trackingState: trackingState,
            transform: transform,
            intrinsics: intrinsics,
            imageURL: imageURL,
            depthURL: depthURL
        )
        // Bound live network work; every sampled frame is still retained locally.
        if pendingFrames.count < 16 {
            pendingFrames.append(upload)
        } else {
            liveStatusMessage = "Network backlog: remaining frames are saved for finalization."
        }
        guard uploadTask == nil else { return }
        uploadTask = Task { @MainActor in
            defer { uploadTask = nil }
            while !pendingFrames.isEmpty && !isFinalizing {
                let next = pendingFrames[0]
                do {
                    let response = try await liveClient.uploadFrame(serverURL: liveServerURL, sessionID: liveSessionID, frame: next)
                    pendingFrames.removeFirst()
                    uploadedFrameIDs.insert(next.frameID)
                    liveUploadedFrameCount = response.frameCount
                    if meshDirty && meshAnchorCount > 0 && Date.timeIntervalSinceReferenceDate - lastMeshUploadTime >= 2 {
                        if let root = captureRoot {
                            let snapshot = root.appendingPathComponent("live_mesh_snapshot.obj")
                            try ARMeshOBJExporter.write(meshAnchors: Array(meshAnchors.values), to: snapshot)
                            meshDirty = false
                            do {
                                _ = try await liveClient.uploadMesh(serverURL: liveServerURL, sessionID: liveSessionID, meshURL: snapshot)
                                lastMeshUploadTime = Date.timeIntervalSinceReferenceDate
                            } catch {
                                meshDirty = true
                                throw error
                            }
                        }
                    }
                    liveStatusMessage = "Uploaded \(response.depthFrameCount) depth frames."
                    liveUploadError = nil
                } catch {
                    liveUploadError = error.localizedDescription
                    // Retain pending paths and retry on the next sampled frame.
                    break
                }
            }
        }
    }

    private func writeCaptureMetadata() {
        guard let captureRoot else { return }
        do {
            let encoder = JSONEncoder.real2simPretty
            if let intrinsics {
                try encoder.encode(intrinsics).write(to: captureRoot.appendingPathComponent("intrinsics.json"))
            }
            try encoder.encode(["frames": poseRecords]).write(to: captureRoot.appendingPathComponent("poses.json"))
            try ARMeshOBJExporter.write(meshAnchors: Array(meshAnchors.values), to: captureRoot.appendingPathComponent("arkit_mesh.obj"))
            try encoder.encode(
                ARSceneCaptureManifest(
                    mode: "scene",
                    source: "ARKit ARWorldTrackingConfiguration sceneDepth sceneReconstruction",
                    createdAt: ISO8601DateFormatter().string(from: Date()),
                    frameCount: frameCount,
                    depthFrameCount: depthFrameCount,
                    meshAnchorCount: meshAnchorCount
                )
            ).write(to: captureRoot.appendingPathComponent("capture_manifest.json"))
        } catch {
            liveUploadError = error.localizedDescription
        }
    }
}

struct ARPoseRecord: Encodable {
    let id: String
    let image: String
    let depth: String?
    let timestamp: TimeInterval
    let transform: [Float]
    let trackingState: String
}

struct ARIntrinsicsRecord: Encodable {
    let width: Int
    let height: Int
    let fx: Float
    let fy: Float
    let cx: Float
    let cy: Float
    let depthScale: Float
    let cameraConvention = "arkit"
    let worldUpAxis = "y"

    enum CodingKeys: String, CodingKey {
        case width
        case height
        case fx
        case fy
        case cx
        case cy
        case depthScale = "depth_scale"
        case cameraConvention = "camera_convention"
        case worldUpAxis = "world_up_axis"
    }
}

struct ARSceneCaptureManifest: Encodable {
    let mode: String
    let source: String
    let createdAt: String
    let frameCount: Int
    let depthFrameCount: Int
    let meshAnchorCount: Int

    enum CodingKeys: String, CodingKey {
        case mode
        case source
        case createdAt = "created_at"
        case frameCount = "frame_count"
        case depthFrameCount = "depth_frame_count"
        case meshAnchorCount = "mesh_anchor_count"
    }
}

enum CameraFrameWriter {
    static func writeJPEG(pixelBuffer: CVPixelBuffer, to url: URL, context: CIContext) throws {
        let image = CIImage(cvPixelBuffer: pixelBuffer)
        guard let cgImage = context.createCGImage(image, from: image.extent),
              let jpeg = UIImage(cgImage: cgImage).jpegData(compressionQuality: 0.9) else {
            throw CocoaError(.fileWriteUnknown)
        }
        try jpeg.write(to: url)
    }
}

enum DepthNPYWriter {
    static func writeFloat32(pixelBuffer: CVPixelBuffer, to url: URL) throws {
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }
        guard let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer) else {
            throw CocoaError(.fileReadUnknown)
        }
        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        let bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)
        var data = Data()
        data.append(contentsOf: [0x93, 0x4E, 0x55, 0x4D, 0x50, 0x59, 0x01, 0x00])
        var header = "{'descr': '<f4', 'fortran_order': False, 'shape': (\(height), \(width)), }"
        let preambleLength = 10
        let padding = 16 - ((preambleLength + header.utf8.count + 1) % 16)
        header += String(repeating: " ", count: padding == 16 ? 0 : padding)
        header += "\n"
        var headerLength = UInt16(header.utf8.count).littleEndian
        data.append(Data(bytes: &headerLength, count: MemoryLayout<UInt16>.size))
        data.append(header.data(using: .ascii)!)
        for row in 0..<height {
            let rowStart = baseAddress.advanced(by: row * bytesPerRow)
            data.append(rowStart.assumingMemoryBound(to: UInt8.self), count: width * MemoryLayout<Float>.stride)
        }
        try data.write(to: url)
    }
}

enum ARMeshOBJExporter {
    static func write(meshAnchors: [ARMeshAnchor], to url: URL) throws {
        var lines: [String] = ["# Real2Sim ARKit scene mesh"]
        var vertexOffset = 1
        for anchor in meshAnchors {
            let geometry = anchor.geometry
            for index in 0..<geometry.vertices.count {
                let vertex = geometry.vertices.vertex(at: index)
                let world = anchor.transform * SIMD4<Float>(vertex.x, vertex.y, vertex.z, 1)
                // ARKit is y-up; all exported geometry is right-handed z-up.
                lines.append(String(format: "v %.6f %.6f %.6f", world.x, -world.z, world.y))
            }
            for faceIndex in 0..<geometry.faces.count {
                let indices = geometry.faces.indices(at: faceIndex)
                if indices.count == 3 {
                    lines.append("f \(indices[0] + vertexOffset) \(indices[1] + vertexOffset) \(indices[2] + vertexOffset)")
                }
            }
            vertexOffset += geometry.vertices.count
        }
        try lines.joined(separator: "\n").write(to: url, atomically: true, encoding: .utf8)
    }
}

private extension ARGeometrySource {
    func vertex(at index: Int) -> SIMD3<Float> {
        let pointer = buffer.contents()
            .advanced(by: offset + stride * index)
            .assumingMemoryBound(to: Float.self)
        return SIMD3<Float>(pointer[0], pointer[1], pointer[2])
    }
}

private extension ARGeometryElement {
    func indices(at primitiveIndex: Int) -> [Int] {
        let start = primitiveIndex * indexCountPerPrimitive * bytesPerIndex
        let pointer = buffer.contents().advanced(by: start)
        return (0..<indexCountPerPrimitive).map { index in
            let address = pointer.advanced(by: index * bytesPerIndex)
            if bytesPerIndex == MemoryLayout<UInt16>.size {
                return Int(address.assumingMemoryBound(to: UInt16.self).pointee)
            }
            return Int(address.assumingMemoryBound(to: UInt32.self).pointee)
        }
    }
}

private extension simd_float4x4 {
    var columnMajorArray: [Float] {
        [
            columns.0.x, columns.0.y, columns.0.z, columns.0.w,
            columns.1.x, columns.1.y, columns.1.z, columns.1.w,
            columns.2.x, columns.2.y, columns.2.z, columns.2.w,
            columns.3.x, columns.3.y, columns.3.z, columns.3.w
        ]
    }
}

private extension ARCamera.TrackingState {
    var real2simDescription: String {
        switch self {
        case .normal:
            return "normal"
        case .notAvailable:
            return "not_available"
        case .limited(let reason):
            return "limited_\(reason)"
        @unknown default:
            return "unknown"
        }
    }
}

private extension JSONEncoder {
    static var real2simPretty: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return encoder
    }
}
