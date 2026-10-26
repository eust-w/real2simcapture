import Foundation

struct BackendTaskResponse: Decodable {
    let id: String
    let status: String
}

struct BackendUploader {
    func uploadTask(
        serverURL: String,
        projectID: String,
        taskName: String,
        mode: String,
        category: String,
        massKg: String?,
        friction: String?,
        packageURL: URL
    ) async throws -> BackendTaskResponse {
        guard let base = URL(string: serverURL.trimmingCharacters(in: .whitespacesAndNewlines)) else {
            throw UploadError.invalidServerURL
        }
        let url = base.appendingPathComponent("/api/tasks")
        let boundary = "Boundary-\(UUID().uuidString)"
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        body.appendMultipartField(name: "project_id", value: projectID, boundary: boundary)
        body.appendMultipartField(name: "name", value: taskName, boundary: boundary)
        body.appendMultipartField(name: "mode", value: mode, boundary: boundary)
        body.appendMultipartField(name: "category", value: category, boundary: boundary)
        if let massKg { body.appendMultipartField(name: "mass_kg", value: massKg, boundary: boundary) }
        if let friction { body.appendMultipartField(name: "friction", value: friction, boundary: boundary) }
        try body.appendMultipartFile(name: "capture", fileURL: packageURL, mimeType: "application/zip", boundary: boundary)
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)

        let (data, response) = try await URLSession.shared.upload(for: request, from: body)
        guard let http = response as? HTTPURLResponse else {
            throw UploadError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "HTTP \(http.statusCode)"
            throw UploadError.serverRejected(message)
        }
        return try JSONDecoder().decode(BackendTaskResponse.self, from: data)
    }
}

enum UploadError: LocalizedError {
    case invalidServerURL
    case invalidResponse
    case serverRejected(String)

    var errorDescription: String? {
        switch self {
        case .invalidServerURL:
            "Invalid backend server URL."
        case .invalidResponse:
            "Backend returned an invalid response."
        case .serverRejected(let message):
            "Backend rejected upload: \(message)"
        }
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
