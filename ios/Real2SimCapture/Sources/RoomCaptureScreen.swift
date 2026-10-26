import RoomPlan
import SwiftUI

struct RoomCaptureScreen: View {
    @EnvironmentObject private var store: CaptureStore
    @State private var isScanning = false

    var body: some View {
        ZStack(alignment: .bottom) {
            if RoomCaptureSession.isSupported {
                RoomCaptureContainer(isScanning: $isScanning) { room in
                    store.packageRoomCapture(room: room)
                }
                .ignoresSafeArea(edges: .horizontal)
            } else {
                ContentUnavailableView("RoomPlan is not supported on this device", systemImage: "cube.transparent")
            }

            HStack(spacing: 10) {
                Button {
                    isScanning = true
                } label: {
                    Label("Start", systemImage: "record.circle")
                }
                .buttonStyle(.borderedProminent)

                Button {
                    isScanning = false
                } label: {
                    Label("Stop & Process", systemImage: "stop.circle")
                }
                .buttonStyle(.bordered)
            }
            .padding(12)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10))
            .padding()
        }
    }
}

struct RoomCaptureContainer: UIViewRepresentable {
    @Binding var isScanning: Bool
    let onRoomCaptured: (CapturedRoom) -> Void

    func makeUIView(context: Context) -> RoomCaptureView {
        let view = RoomCaptureView(frame: .zero)
        view.delegate = context.coordinator
        view.captureSession.delegate = context.coordinator
        return view
    }

    func updateUIView(_ uiView: RoomCaptureView, context: Context) {
        if isScanning && !context.coordinator.isRunning {
            uiView.captureSession.run(configuration: RoomCaptureSession.Configuration())
            context.coordinator.isRunning = true
        }
        if !isScanning && context.coordinator.isRunning {
            uiView.captureSession.stop()
            context.coordinator.isRunning = false
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(onRoomCaptured: onRoomCaptured)
    }

    final class Coordinator: NSObject, RoomCaptureViewDelegate, RoomCaptureSessionDelegate {
        var isRunning = false
        private let onRoomCaptured: (CapturedRoom) -> Void

        init(onRoomCaptured: @escaping (CapturedRoom) -> Void) {
            self.onRoomCaptured = onRoomCaptured
        }

        func captureView(shouldPresent roomDataForProcessing: CapturedRoomData, error: Error?) -> Bool {
            error == nil
        }

        func captureView(didPresent processedResult: CapturedRoom, error: Error?) {
            guard error == nil else { return }
            onRoomCaptured(processedResult)
        }
    }
}
