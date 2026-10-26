import Foundation

enum ZipWriter {
    static func writeDirectory(_ directory: URL, to destination: URL) throws {
        let files = try FileManager.default.enumerator(
            at: directory,
            includingPropertiesForKeys: [.isRegularFileKey],
            options: [.skipsHiddenFiles]
        )?.compactMap { $0 as? URL } ?? []

        var archive = Data()
        var centralDirectory = Data()
        var entries: [CentralDirectoryEntry] = []

        for file in files where try file.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile == true {
            let relativePath = file.path.replacingOccurrences(of: directory.path + "/", with: "")
            let fileData = try Data(contentsOf: file)
            let crc = CRC32.checksum(fileData)
            let offset = UInt32(archive.count)
            let nameData = Data(relativePath.utf8)

            archive.appendUInt32(0x04034b50)
            archive.appendUInt16(20)
            archive.appendUInt16(0)
            archive.appendUInt16(0)
            archive.appendUInt16(0)
            archive.appendUInt16(0)
            archive.appendUInt32(crc)
            archive.appendUInt32(UInt32(fileData.count))
            archive.appendUInt32(UInt32(fileData.count))
            archive.appendUInt16(UInt16(nameData.count))
            archive.appendUInt16(0)
            archive.append(nameData)
            archive.append(fileData)

            entries.append(
                CentralDirectoryEntry(
                    nameData: nameData,
                    crc: crc,
                    compressedSize: UInt32(fileData.count),
                    uncompressedSize: UInt32(fileData.count),
                    localHeaderOffset: offset
                )
            )
        }

        let centralDirectoryOffset = UInt32(archive.count)
        for entry in entries {
            centralDirectory.appendUInt32(0x02014b50)
            centralDirectory.appendUInt16(20)
            centralDirectory.appendUInt16(20)
            centralDirectory.appendUInt16(0)
            centralDirectory.appendUInt16(0)
            centralDirectory.appendUInt16(0)
            centralDirectory.appendUInt16(0)
            centralDirectory.appendUInt32(entry.crc)
            centralDirectory.appendUInt32(entry.compressedSize)
            centralDirectory.appendUInt32(entry.uncompressedSize)
            centralDirectory.appendUInt16(UInt16(entry.nameData.count))
            centralDirectory.appendUInt16(0)
            centralDirectory.appendUInt16(0)
            centralDirectory.appendUInt16(0)
            centralDirectory.appendUInt16(0)
            centralDirectory.appendUInt32(0)
            centralDirectory.appendUInt32(entry.localHeaderOffset)
            centralDirectory.append(entry.nameData)
        }
        archive.append(centralDirectory)
        archive.appendUInt32(0x06054b50)
        archive.appendUInt16(0)
        archive.appendUInt16(0)
        archive.appendUInt16(UInt16(entries.count))
        archive.appendUInt16(UInt16(entries.count))
        archive.appendUInt32(UInt32(centralDirectory.count))
        archive.appendUInt32(centralDirectoryOffset)
        archive.appendUInt16(0)
        try archive.write(to: destination)
    }
}

private struct CentralDirectoryEntry {
    let nameData: Data
    let crc: UInt32
    let compressedSize: UInt32
    let uncompressedSize: UInt32
    let localHeaderOffset: UInt32
}

private enum CRC32 {
    private static let table: [UInt32] = (0..<256).map { index in
        var value = UInt32(index)
        for _ in 0..<8 {
            if value & 1 == 1 {
                value = 0xedb88320 ^ (value >> 1)
            } else {
                value >>= 1
            }
        }
        return value
    }

    static func checksum(_ data: Data) -> UInt32 {
        var crc: UInt32 = 0xffffffff
        for byte in data {
            crc = table[Int((crc ^ UInt32(byte)) & 0xff)] ^ (crc >> 8)
        }
        return crc ^ 0xffffffff
    }
}

private extension Data {
    mutating func appendUInt16(_ value: UInt16) {
        var littleEndian = value.littleEndian
        append(Data(bytes: &littleEndian, count: MemoryLayout<UInt16>.size))
    }

    mutating func appendUInt32(_ value: UInt32) {
        var littleEndian = value.littleEndian
        append(Data(bytes: &littleEndian, count: MemoryLayout<UInt32>.size))
    }
}
