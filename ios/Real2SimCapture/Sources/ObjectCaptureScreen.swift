import RealityKit
import SwiftUI

struct ObjectCaptureScreen: View {
    @EnvironmentObject private var store: CaptureStore
    @StateObject private var controller = ObjectCaptureController()

    var body: some View {
        ZStack(alignment: .bottom) {
            if controller.isSupported, let session = controller.session {
                ObjectCaptureView(session: session)
                    .ignoresSafeArea(edges: .horizontal)
            } else {
                ContentUnavailableView("Object Capture is not supported on this device", systemImage: "iphone.slash")
            }

            HStack(spacing: 10) {
                Button {
                    controller.startDetecting()
                } label: {
                    Label("Detect", systemImage: "viewfinder")
                }
                .buttonStyle(.bordered)

                Button {
                    controller.startCapturing()
                } label: {
                    Label("Capture", systemImage: "camera")
                }
                .buttonStyle(.borderedProminent)

                Button {
                    controller.finish()
                    store.packageObjectCapture(
                        imagesDirectory: controller.imagesDirectory,
                        checkpointDirectory: controller.checkpointDirectory
                    )
                } label: {
                    Label("Package", systemImage: "shippingbox")
                }
                .buttonStyle(.bordered)
            }
            .padding(12)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10))
            .padding()
        }
        .task {
            controller.startSessionIfNeeded()
        }
    }
}

@MainActor
final class ObjectCaptureController: ObservableObject {
    @Published private(set) var session: ObjectCaptureSession?
    let imagesDirectory: URL
    let checkpointDirectory: URL

    var isSupported: Bool {
        ObjectCaptureSession.isSupported
    }

    init() {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("Real2SimObjectCapture", isDirectory: true)
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        imagesDirectory = root.appendingPathComponent("Images", isDirectory: true)
        checkpointDirectory = root.appendingPathComponent("Snapshots", isDirectory: true)
        try? FileManager.default.createDirectory(at: imagesDirectory, withIntermediateDirectories: true)
        try? FileManager.default.createDirectory(at: checkpointDirectory, withIntermediateDirectories: true)
        if ObjectCaptureSession.isSupported {
            session = ObjectCaptureSession()
        }
    }

    func startSessionIfNeeded() {
        guard let session else { return }
        var configuration = ObjectCaptureSession.Configuration()
        configuration.checkpointDirectory = checkpointDirectory
        session.start(imagesDirectory: imagesDirectory, configuration: configuration)
    }

    func startDetecting() {
        session?.startDetecting()
    }

    func startCapturing() {
        session?.startCapturing()
    }

    func finish() {
        session?.finish()
    }
}
