import SwiftUI

@main
struct Real2SimCaptureApp: App {
    @StateObject private var captureStore = CaptureStore()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(captureStore)
        }
    }
}
