import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var store: CaptureStore
    @State private var mode: CaptureMode = .asset

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                Picker("Mode", selection: $mode) {
                    ForEach(CaptureMode.allCases) { mode in
                        Text(mode.title).tag(mode)
                    }
                }
                .pickerStyle(.segmented)
                .padding()

                if mode == .asset {
                    ObjectCaptureScreen()
                } else if mode == .rgbdScene {
                    ARSceneCaptureScreen()
                } else {
                    RoomCaptureScreen()
                }

                UploadPanel()
                    .padding()
                    .background(.regularMaterial)
            }
            .navigationTitle("Real2Sim Capture")
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}

enum CaptureMode: String, CaseIterable, Identifiable {
    case asset
    case room
    case rgbdScene

    var id: String { rawValue }

    var title: String {
        switch self {
        case .asset: "Asset"
        case .room: "Room"
        case .rgbdScene: "RGB-D"
        }
    }

    var uploadValue: String {
        switch self {
        case .asset:
            "asset"
        case .room, .rgbdScene:
            "scene"
        }
    }
}

private struct UploadPanel: View {
    @EnvironmentObject private var store: CaptureStore
    @AppStorage("real2sim.serverURL") private var serverURL = "http://workstation.local:8000"
    @AppStorage("real2sim.projectID") private var projectID = ""
    @State private var taskName = ""
    @State private var category = "object"
    @State private var massKg = ""
    @State private var friction = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 8) {
                GridRow {
                    Text("Server")
                    TextField("http://workstation.local:8000", text: $serverURL)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                }
                GridRow {
                    Text("Project ID")
                    TextField("Backend project UUID", text: $projectID)
                        .textInputAutocapitalization(.never)
                }
                GridRow {
                    Text("Task")
                    TextField("Scan task name", text: $taskName)
                }
                GridRow {
                    Text("Category")
                    TextField("bottle / table / part", text: $category)
                }
                GridRow {
                    Text("Mass kg")
                    TextField("optional", text: $massKg)
                        .keyboardType(.decimalPad)
                }
                GridRow {
                    Text("Friction")
                    TextField("optional", text: $friction)
                        .keyboardType(.decimalPad)
                }
            }
            .font(.footnote)

            HStack {
                Button {
                    Task {
                        await store.uploadLatestCapture(
                            serverURL: serverURL,
                            projectID: projectID,
                            taskName: taskName,
                            category: category,
                            massKg: massKg,
                            friction: friction
                        )
                    }
                } label: {
                    Label("Upload Package", systemImage: "square.and.arrow.up")
                }
                .buttonStyle(.borderedProminent)
                .disabled(!store.canUpload || projectID.isEmpty || taskName.isEmpty || store.isUploading)

                if store.isUploading {
                    ProgressView()
                }
            }

            if let message = store.statusMessage {
                Text(message)
                    .font(.caption)
                    .foregroundStyle(store.lastError == nil ? .secondary : .red)
            }
        }
    }
}
