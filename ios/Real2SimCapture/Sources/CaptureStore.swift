import Foundation
import RoomPlan

@MainActor
final class CaptureStore: ObservableObject {
    @Published var latestPackageURL: URL?
    @Published var latestMode: CaptureMode?
    @Published var statusMessage: String?
    @Published var lastError: String?
    @Published var isUploading = false

    private let packageBuilder = CapturePackageBuilder()
    private let uploader = BackendUploader()

    var canUpload: Bool {
        latestPackageURL != nil
    }

    func packageObjectCapture(imagesDirectory: URL, checkpointDirectory: URL) {
        do {
            latestPackageURL = try packageBuilder.packageObjectCapture(
                imagesDirectory: imagesDirectory,
                checkpointDirectory: checkpointDirectory
            )
            latestMode = .asset
            lastError = nil
            statusMessage = "Object capture package ready: \(latestPackageURL?.lastPathComponent ?? "")"
        } catch {
            lastError = error.localizedDescription
            statusMessage = error.localizedDescription
        }
    }

    func packageRoomCapture(room: CapturedRoom) {
        do {
            latestPackageURL = try packageBuilder.packageRoomCapture(room: room)
            latestMode = .room
            lastError = nil
            statusMessage = "RoomPlan package ready: \(latestPackageURL?.lastPathComponent ?? "")"
        } catch {
            lastError = error.localizedDescription
            statusMessage = error.localizedDescription
        }
    }

    func packageARSceneCapture(captureRoot: URL) {
        do {
            latestPackageURL = try packageBuilder.packageARSceneCapture(captureRoot: captureRoot)
            latestMode = .rgbdScene
            lastError = nil
            statusMessage = "AR RGB-D package ready: \(latestPackageURL?.lastPathComponent ?? "")"
        } catch {
            lastError = error.localizedDescription
            statusMessage = error.localizedDescription
        }
    }

    func uploadLatestCapture(
        serverURL: String,
        projectID: String,
        taskName: String,
        category: String,
        massKg: String,
        friction: String
    ) async {
        guard let packageURL = latestPackageURL, let mode = latestMode else {
            statusMessage = "No capture package is ready."
            return
        }

        isUploading = true
        defer { isUploading = false }

        do {
            let response = try await uploader.uploadTask(
                serverURL: serverURL,
                projectID: projectID,
                taskName: taskName,
                mode: mode.uploadValue,
                category: category,
                massKg: massKg.isEmpty ? nil : massKg,
                friction: friction.isEmpty ? nil : friction,
                packageURL: packageURL
            )
            lastError = nil
            statusMessage = "Uploaded task \(response.id) with status \(response.status). Run the backend pipeline from the web console."
        } catch {
            lastError = error.localizedDescription
            statusMessage = error.localizedDescription
        }
    }
}
