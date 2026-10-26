import Foundation

struct LiveSessionResponse: Decodable {
    let id: String
    let status: String
    let frameCount: Int
    let depthFrameCount: Int
    let latestFrameID: String?
    let taskID: String?

    enum CodingKeys: String, CodingKey {
        case id
        case status
        case frameCount = "frame_count"
        case depthFrameCount = "depth_frame_count"
        case latestFrameID = "latest_frame_id"
        case taskID = "task_id"
    }
}

struct LiveFinalizeResponse: Decodable {
    let session: LiveSessionResponse
    let task: BackendTaskResponse
}

struct BackendProjectResponse: Decodable {
    let id: String
    let name: String
}

struct LiveFrameUpload {
    let frameID: String
    let timestamp: TimeInterval
    let trackingState: String
    let transform: [Float]
    let intrinsics: ARIntrinsicsRecord?
    let imageURL: URL
    let depthURL: URL?
}

struct LiveSessionClient {
    func createProject(serverURL: String, name: String) async throws -> BackendProjectResponse {
        let url = try endpoint(serverURL: serverURL, components: ["api", "projects"])
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["name": name])
        return try await decode(request: request, as: BackendProjectResponse.self)
    }

    func createSession(
        serverURL: String,
        projectID: String,
        name: String,
        category: String,
        massKg: String?,
        friction: String?
    ) async throws -> LiveSessionResponse {
        let url = try endpoint(serverURL: serverURL, components: ["api", "live-sessions"])
        var payload: [String: Any] = [
            "project_id": projectID,
            "name": name,
            "category": category
        ]
        if let value = Double((massKg ?? "").trimmingCharacters(in: .whitespacesAndNewlines)) {
            payload["mass_kg"] = value
        }
        if let value = Double((friction ?? "").trimmingCharacters(in: .whitespacesAndNewlines)) {
            payload["friction"] = value
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        return try await decode(request: request, as: LiveSessionResponse.self)
    }

    func uploadFrame(serverURL: String, sessionID: String, frame: LiveFrameUpload) async throws -> LiveSessionResponse {
        let url = try endpoint(serverURL: serverURL, components: ["api", "live-sessions", sessionID, "frames"])
        let boundary = "Boundary-\(UUID().uuidString)"
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        body.appendMultipartField(name: "frame_id", value: frame.frameID, boundary: boundary)
        body.appendMultipartField(name: "timestamp", value: String(frame.timestamp), boundary: boundary)
        body.appendMultipartField(name: "tracking_state", value: frame.trackingState, boundary: boundary)
        body.appendMultipartField(name: "transform", value: try jsonString(frame.transform), boundary: boundary)
        if let intrinsics = frame.intrinsics {
            body.appendMultipartField(name: "intrinsics", value: try jsonString(intrinsics), boundary: boundary)
        }
        try body.appendMultipartFile(name: "image", fileURL: frame.imageURL, mimeType: "image/jpeg", boundary: boundary)
        if let depthURL = frame.depthURL {
            try body.appendMultipartFile(name: "depth", fileURL: depthURL, mimeType: "application/octet-stream", boundary: boundary)
        }
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)
        return try await upload(request: request, body: body, as: LiveSessionResponse.self)
    }

    func uploadMesh(serverURL: String, sessionID: String, meshURL: URL) async throws -> LiveSessionResponse {
        let url = try endpoint(serverURL: serverURL, components: ["api", "live-sessions", sessionID, "mesh"])
        let boundary = "Boundary-\(UUID().uuidString)"
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        try body.appendMultipartFile(name: "mesh", fileURL: meshURL, mimeType: "text/plain", boundary: boundary)
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)
        return try await upload(request: request, body: body, as: LiveSessionResponse.self)
    }

    func finalizeSession(serverURL: String, sessionID: String) async throws -> LiveFinalizeResponse {
        let url = try endpoint(serverURL: serverURL, components: ["api", "live-sessions", sessionID, "finalize"])
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        return try await decode(request: request, as: LiveFinalizeResponse.self)
    }

    private func endpoint(serverURL: String, components: [String]) throws -> URL {
        guard var url = URL(string: serverURL.trimmingCharacters(in: .whitespacesAndNewlines)),
              ["http", "https"].contains(url.scheme?.lowercased() ?? ""), url.host != nil else {
            throw UploadError.invalidServerURL
        }
        for component in components {
            url.appendPathComponent(component)
        }
        return url
    }

    private func decode<T: Decodable>(request: URLRequest, as type: T.Type) async throws -> T {
        let (data, response) = try await URLSession.shared.data(for: request)
        return try decodeHTTP(data: data, response: response, as: type)
    }

    private func upload<T: Decodable>(request: URLRequest, body: Data, as type: T.Type) async throws -> T {
        var boundedRequest = request
        boundedRequest.timeoutInterval = 30
        let (data, response) = try await URLSession.shared.upload(for: boundedRequest, from: body)
        return try decodeHTTP(data: data, response: response, as: type)
    }

    private func decodeHTTP<T: Decodable>(data: Data, response: URLResponse, as type: T.Type) throws -> T {
        guard let http = response as? HTTPURLResponse else {
            throw UploadError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "HTTP \(http.statusCode)"
            throw UploadError.serverRejected(message)
        }
        return try JSONDecoder().decode(type, from: data)
    }

    private func jsonString<T: Encodable>(_ value: T) throws -> String {
        let data = try JSONEncoder().encode(value)
        return String(data: data, encoding: .utf8) ?? "null"
    }
}

private extension Data {
    mutating func appendMultipartField(name: String, value: String, boundary: String) {
        append("--\(boundary)\r\n".data(using: .utf8)!)
        append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n".data(using: .utf8)!)
        append("\(value)\r\n".data(using: .utf8)!)
    }

    mutating func appendMultipartFile(name: String, fileURL: URL, mimeType: String, boundary: String) throws {
        append("--\(boundary)\r\n".data(using: .utf8)!)
        append("Content-Disposition: form-data; name=\"\(name)\"; filename=\"\(fileURL.lastPathComponent)\"\r\n".data(using: .utf8)!)
        append("Content-Type: \(mimeType)\r\n\r\n".data(using: .utf8)!)
        append(try Data(contentsOf: fileURL))
        append("\r\n".data(using: .utf8)!)
    }
}
