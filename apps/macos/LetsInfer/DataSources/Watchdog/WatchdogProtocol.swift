import Foundation

struct WatchdogTelemetrySample: Equatable, Sendable {
    var sequence: UInt64 = 0
    var unixMilliseconds: UInt64 = 0
    var flags: UInt32 = 0
    var cpuPercent: UInt32 = 255
    var cpuCorePercent: [UInt32] = []
    var memoryPercent: UInt32 = 255
    var diskPercent: UInt32 = 255
    var gpuPercent: UInt32 = 255
    var gpuMemoryPercent: UInt32 = 255
    var gpuEnginePercent: [UInt32] = []
    var gpuTemperatureDeciCelsius: Int32 = .min
    var powerDeciwatts: UInt32 = 0
    var systemTemperatureDeciCelsius: Int32 = .min
    var nvmeTemperatureDeciCelsius: Int32 = .min
    var load1Centi: UInt32 = 0
    var memoryUsedMiB: UInt32 = 0
    var memoryTotalMiB: UInt32 = 0
    var diskUsedMiB: UInt32 = 0
    var diskTotalMiB: UInt32 = 0
    var networkReceiveKiBPerSecond: UInt32 = 0
    var networkTransmitKiBPerSecond: UInt32 = 0
    var diskReadKiBPerSecond: UInt32 = 0
    var diskWriteKiBPerSecond: UInt32 = 0
    var workloadID: UInt32 = 0
    var workloadType: UInt32 = 0
    var cpuClockMHz: UInt32 = .max
    var systemRAMClockMHz: UInt32 = .max
    var gpuClockMHz: UInt32 = .max
    var vramClockMHz: UInt32 = .max
    var activeRequests: UInt32 = 0
    var queuedRequests: UInt32 = 0
    var requestsReceived: UInt64 = 0
    var requestsAdmitted: UInt64 = 0
    var requestsCompleted: UInt64 = 0
    var requestsFailed: UInt64 = 0
    var requestsCancelled: UInt64 = 0
    var requestsRetried: UInt64 = 0
    var inputTokens: UInt64 = 0
    var outputTokens: UInt64 = 0
    var cachedTokens: UInt64 = 0
    var queueMilliseconds: UInt64 = 0
    var ttftMilliseconds: UInt64 = 0
    var decodeMilliseconds: UInt64 = 0
    var exactTokenRequests: UInt64 = 0
    var prefixCacheHits: UInt64 = 0
    var usageRecordsDropped: UInt64 = 0
    var usageWriteErrors: UInt64 = 0
}

struct WatchdogCapabilities: Equatable, Sendable {
    var protocolVersion: UInt32 = 0
    var sampleIntervalMilliseconds: UInt32 = 0
    var durableFlushIntervalMilliseconds: UInt32 = 0
    var maxCPUCores: UInt32 = 0
    var resolutions: [UInt32] = []
    var mutualTLSRequired = false
    var physicalGPUCount: UInt32 = 0
}

enum WatchdogServerMessage: Equatable, Sendable {
    case latest(requestID: UInt64, sample: WatchdogTelemetrySample)
    case history(requestID: UInt64, samples: [WatchdogTelemetrySample])
    case historyComplete(requestID: UInt64, throughSequence: UInt64)
    case live(requestID: UInt64, sample: WatchdogTelemetrySample)
    case capabilities(requestID: UInt64, capabilities: WatchdogCapabilities)
    case gap(requestID: UInt64, firstMissingSequence: UInt64, latestSequence: UInt64)
    case error(requestID: UInt64, code: UInt32, message: String)
    case pong(requestID: UInt64, nonce: UInt64)
    case letsinferStatus(requestID: UInt64, status: SiteStatus)
    case other(requestID: UInt64)

    var requestID: UInt64 {
        switch self {
        case .latest(let id, _), .history(let id, _), .historyComplete(let id, _),
             .live(let id, _), .capabilities(let id, _), .gap(let id, _, _),
             .error(let id, _, _), .pong(let id, _), .letsinferStatus(let id, _),
             .other(let id):
            id
        }
    }
}

enum WatchdogProtocolError: LocalizedError, Equatable {
    case malformedMessage
    case frameTooLarge
    case unexpectedResponse
    case incompatibleProtocol(UInt32)
    case sequenceGap(first: UInt64, latest: UInt64)
    case server(code: UInt32, message: String)

    var errorDescription: String? {
        switch self {
        case .malformedMessage:
            "watchdog returned malformed telemetry."
        case .frameTooLarge:
            "watchdog returned an oversized telemetry frame."
        case .unexpectedResponse:
            "watchdog returned an unexpected response."
        case .incompatibleProtocol(let version):
            "This Let's Infer Watchdog protocol is unsupported (version \(version))."
        case .sequenceGap(let first, let latest):
            "Watchdog history has a sequence gap from \(first) through \(latest)."
        case .server(_, let message):
            message
        }
    }
}

enum WatchdogProtobuf {
    static let maximumFrameBytes = 65_536

    static func getLatest(requestID: UInt64) -> Data {
        envelope(requestID: requestID, payloadField: 10, body: Data())
    }

    static func subscribe(requestID: UInt64, historySeconds: UInt32) -> Data {
        var body = Data()
        writeUInt(field: 1, value: UInt64(historySeconds), to: &body)
        return envelope(requestID: requestID, payloadField: 11, body: body)
    }

    static func getCapabilities(requestID: UInt64) -> Data {
        envelope(requestID: requestID, payloadField: 13, body: Data())
    }

    static func getSiteStatus(requestID: UInt64) -> Data {
        envelope(requestID: requestID, payloadField: 15, body: Data())
    }

    static func queryHistory(
        requestID: UInt64,
        startMilliseconds: UInt64,
        endMilliseconds: UInt64,
        resolution: UInt32
    ) -> Data {
        var body = Data()
        writeUInt(field: 1, value: startMilliseconds, to: &body)
        writeUInt(field: 2, value: endMilliseconds, to: &body)
        writeUInt(field: 3, value: UInt64(resolution), to: &body)
        return envelope(requestID: requestID, payloadField: 12, body: body)
    }

    static func framed(_ payload: Data) throws -> Data {
        guard !payload.isEmpty, payload.count <= maximumFrameBytes else {
            throw WatchdogProtocolError.frameTooLarge
        }
        let length = UInt32(payload.count)
        var frame = Data([
            UInt8(truncatingIfNeeded: length >> 24),
            UInt8(truncatingIfNeeded: length >> 16),
            UInt8(truncatingIfNeeded: length >> 8),
            UInt8(truncatingIfNeeded: length)
        ])
        frame.append(payload)
        return frame
    }

    static func frameLength(_ header: Data) throws -> Int {
        guard header.count == 4 else { throw WatchdogProtocolError.malformedMessage }
        let bytes = [UInt8](header)
        let length = Int(UInt32(bytes[0]) << 24
            | UInt32(bytes[1]) << 16
            | UInt32(bytes[2]) << 8
            | UInt32(bytes[3]))
        guard length > 0, length <= maximumFrameBytes else {
            throw WatchdogProtocolError.frameTooLarge
        }
        return length
    }

    static func decodeServerEnvelope(_ payload: Data) throws -> WatchdogServerMessage {
        var reader = Reader(payload)
        var requestID: UInt64 = 0
        var payloadField: Int?
        var payloadBytes: [UInt8]?

        while !reader.isAtEnd {
            let field = try reader.readField()
            if field.number == 1, field.wireType == 0 {
                requestID = try reader.readVarint()
            } else if (10...18).contains(field.number), field.wireType == 2 {
                payloadField = field.number
                payloadBytes = try reader.readBytes()
            } else {
                try reader.skip(wireType: field.wireType)
            }
        }

        guard let payloadField, let payloadBytes else {
            throw WatchdogProtocolError.malformedMessage
        }
        switch payloadField {
        case 10:
            return .latest(requestID: requestID, sample: try decodeTelemetry(payloadBytes))
        case 11:
            return .history(requestID: requestID, samples: try decodeBatch(payloadBytes))
        case 12:
            return .historyComplete(
                requestID: requestID,
                throughSequence: try decodeSingleUInt(payloadBytes, fieldNumber: 1)
            )
        case 13:
            return .live(requestID: requestID, sample: try decodeTelemetry(payloadBytes))
        case 14:
            return .capabilities(
                requestID: requestID,
                capabilities: try decodeCapabilities(payloadBytes)
            )
        case 15:
            let gap = try decodeGap(payloadBytes)
            return .gap(
                requestID: requestID,
                firstMissingSequence: gap.first,
                latestSequence: gap.latest
            )
        case 16:
            let value = try decodeError(payloadBytes)
            return .error(requestID: requestID, code: value.code, message: value.message)
        case 17:
            return .pong(
                requestID: requestID,
                nonce: try decodeSingleUInt(payloadBytes, fieldNumber: 1)
            )
        case 18:
            return .letsinferStatus(
                requestID: requestID,
                status: try decodeSiteStatus(payloadBytes)
            )
        default:
            return .other(requestID: requestID)
        }
    }

    private static func envelope(requestID: UInt64, payloadField: Int, body: Data) -> Data {
        var envelope = Data()
        writeUInt(field: 1, value: requestID, to: &envelope)
        writeMessage(field: payloadField, body: body, to: &envelope)
        return envelope
    }

    private static func decodeBatch(_ bytes: [UInt8]) throws -> [WatchdogTelemetrySample] {
        var reader = Reader(bytes)
        var samples: [WatchdogTelemetrySample] = []
        while !reader.isAtEnd {
            let field = try reader.readField()
            if field.number == 1, field.wireType == 2 {
                samples.append(try decodeTelemetry(reader.readBytes()))
            } else {
                try reader.skip(wireType: field.wireType)
            }
        }
        return samples
    }

    private static func decodeTelemetry(_ bytes: [UInt8]) throws -> WatchdogTelemetrySample {
        var reader = Reader(bytes)
        var sample = WatchdogTelemetrySample()
        while !reader.isAtEnd {
            let field = try reader.readField()
            switch (field.number, field.wireType) {
            case (1, 0): sample.sequence = try reader.readVarint()
            case (2, 0): sample.unixMilliseconds = try reader.readVarint()
            case (4, 0): sample.flags = try reader.readUInt32()
            case (5, 0): sample.cpuPercent = try reader.readUInt32()
            case (6, 2): sample.cpuCorePercent = try decodePackedUInt32(reader.readBytes())
            case (6, 0): sample.cpuCorePercent.append(try reader.readUInt32())
            case (7, 0): sample.memoryPercent = try reader.readUInt32()
            case (8, 0): sample.diskPercent = try reader.readUInt32()
            case (9, 2): try decodeGPU(reader.readBytes(), into: &sample)
            case (10, 0): sample.systemTemperatureDeciCelsius = try reader.readSInt32()
            case (11, 0): sample.nvmeTemperatureDeciCelsius = try reader.readSInt32()
            case (12, 0): sample.load1Centi = try reader.readUInt32()
            case (13, 0): sample.memoryUsedMiB = try reader.readUInt32()
            case (14, 0): sample.memoryTotalMiB = try reader.readUInt32()
            case (15, 0): sample.diskUsedMiB = try reader.readUInt32()
            case (16, 0): sample.diskTotalMiB = try reader.readUInt32()
            case (17, 0): sample.networkReceiveKiBPerSecond = try reader.readUInt32()
            case (18, 0): sample.networkTransmitKiBPerSecond = try reader.readUInt32()
            case (19, 0): sample.diskReadKiBPerSecond = try reader.readUInt32()
            case (20, 0): sample.diskWriteKiBPerSecond = try reader.readUInt32()
            case (21, 0): sample.workloadID = try reader.readUInt32()
            case (22, 0): sample.workloadType = try reader.readUInt32()
            case (23, 0): sample.cpuClockMHz = try reader.readUInt32()
            case (24, 0): sample.systemRAMClockMHz = try reader.readUInt32()
            case (25, 0): sample.activeRequests = try reader.readUInt32()
            case (26, 0): sample.queuedRequests = try reader.readUInt32()
            case (27, 0): sample.requestsReceived = try reader.readVarint()
            case (28, 0): sample.requestsAdmitted = try reader.readVarint()
            case (29, 0): sample.requestsCompleted = try reader.readVarint()
            case (30, 0): sample.requestsFailed = try reader.readVarint()
            case (31, 0): sample.requestsCancelled = try reader.readVarint()
            case (32, 0): sample.requestsRetried = try reader.readVarint()
            case (33, 0): sample.inputTokens = try reader.readVarint()
            case (34, 0): sample.outputTokens = try reader.readVarint()
            case (35, 0): sample.cachedTokens = try reader.readVarint()
            case (36, 0): sample.queueMilliseconds = try reader.readVarint()
            case (37, 0): sample.ttftMilliseconds = try reader.readVarint()
            case (38, 0): sample.decodeMilliseconds = try reader.readVarint()
            case (39, 0): sample.exactTokenRequests = try reader.readVarint()
            case (40, 0): sample.prefixCacheHits = try reader.readVarint()
            case (41, 0): sample.usageRecordsDropped = try reader.readVarint()
            case (42, 0): sample.usageWriteErrors = try reader.readVarint()
            default: try reader.skip(wireType: field.wireType)
            }
        }
        return sample
    }

    private static func decodeGPU(_ bytes: [UInt8], into sample: inout WatchdogTelemetrySample) throws {
        var reader = Reader(bytes)
        while !reader.isAtEnd {
            let field = try reader.readField()
            switch (field.number, field.wireType) {
            case (1, 0): sample.gpuPercent = try reader.readUInt32()
            case (2, 0): sample.gpuMemoryPercent = try reader.readUInt32()
            case (3, 2): sample.gpuEnginePercent = try decodePackedUInt32(reader.readBytes())
            case (3, 0): sample.gpuEnginePercent.append(try reader.readUInt32())
            case (4, 0): sample.gpuTemperatureDeciCelsius = try reader.readSInt32()
            case (5, 0): sample.powerDeciwatts = try reader.readUInt32()
            case (6, 0): sample.gpuClockMHz = try reader.readUInt32()
            case (7, 0): sample.vramClockMHz = try reader.readUInt32()
            default: try reader.skip(wireType: field.wireType)
            }
        }
    }

    private static func decodePackedUInt32(_ bytes: [UInt8]) throws -> [UInt32] {
        var reader = Reader(bytes)
        var values: [UInt32] = []
        while !reader.isAtEnd {
            values.append(try reader.readUInt32())
        }
        return values
    }

    private static func decodeSingleUInt(_ bytes: [UInt8], fieldNumber: Int) throws -> UInt64 {
        var reader = Reader(bytes)
        while !reader.isAtEnd {
            let field = try reader.readField()
            if field.number == fieldNumber, field.wireType == 0 {
                return try reader.readVarint()
            }
            try reader.skip(wireType: field.wireType)
        }
        return 0
    }

    private static func decodeCapabilities(_ bytes: [UInt8]) throws -> WatchdogCapabilities {
        var reader = Reader(bytes)
        var value = WatchdogCapabilities()
        while !reader.isAtEnd {
            let field = try reader.readField()
            switch (field.number, field.wireType) {
            case (1, 0): value.protocolVersion = try reader.readUInt32()
            case (2, 0): value.sampleIntervalMilliseconds = try reader.readUInt32()
            case (3, 0): value.durableFlushIntervalMilliseconds = try reader.readUInt32()
            case (4, 0): value.maxCPUCores = try reader.readUInt32()
            case (5, 0): value.resolutions.append(try reader.readUInt32())
            case (5, 2): value.resolutions.append(contentsOf: try decodePackedUInt32(reader.readBytes()))
            case (6, 0): value.mutualTLSRequired = try reader.readUInt32() != 0
            case (7, 0): value.physicalGPUCount = try reader.readUInt32()
            default: try reader.skip(wireType: field.wireType)
            }
        }
        guard value.protocolVersion > 0, value.sampleIntervalMilliseconds > 0 else {
            throw WatchdogProtocolError.malformedMessage
        }
        return value
    }

    private static func decodeGap(_ bytes: [UInt8]) throws -> (first: UInt64, latest: UInt64) {
        var reader = Reader(bytes)
        var first: UInt64 = 0
        var latest: UInt64 = 0
        while !reader.isAtEnd {
            let field = try reader.readField()
            if field.number == 1, field.wireType == 0 {
                first = try reader.readVarint()
            } else if field.number == 2, field.wireType == 0 {
                latest = try reader.readVarint()
            } else {
                try reader.skip(wireType: field.wireType)
            }
        }
        guard first > 0, latest >= first else { throw WatchdogProtocolError.malformedMessage }
        return (first, latest)
    }

    private static func decodeSiteStatus(_ bytes: [UInt8]) throws -> SiteStatus {
        var reader = Reader(bytes)
        var strings: [Int: String] = [:]
        var integers: [Int: UInt32] = [:]
        while !reader.isAtEnd {
            let field = try reader.readField()
            if [1, 2, 3, 4, 5, 6, 7, 13, 14, 15, 18, 19].contains(field.number),
               field.wireType == 2 {
                strings[field.number] = try reader.readString()
            } else if (8...12).contains(field.number) || (16...17).contains(field.number),
                      field.wireType == 0 {
                integers[field.number] = try reader.readUInt32()
            } else {
                try reader.skip(wireType: field.wireType)
            }
        }
        guard
            let release = strings[1], portableText(release),
            let installationID = strings[19], lowercaseSHA256(installationID),
            let model = strings[2], portableText(model),
            let engine = strings[3], portableText(engine),
            let manifest = strings[6], lowercaseSHA256(manifest),
            let cache = strings[7], portableText(cache),
            let service = strings[13], service == "running",
            let engineState = strings[14],
            ["absent", "pending", "starting", "running", "degraded", "stopped", "tripped"]
                .contains(engineState),
            let protection = strings[15],
            ["none", "pending", "starting", "armed", "disarmed"].contains(protection),
            strings[4].map(portableText) ?? true,
            strings[5].map(portableText) ?? true,
            strings[18].map({ $0.isEmpty || portableText($0) }) ?? true,
            let port = integers[9], port > 0, port <= 65_535,
            let maxConnections = integers[10], maxConnections > 0,
            let maxActive = integers[11], maxActive > 0,
            let maxContext = integers[12], maxContext > 0
        else {
            throw WatchdogProtocolError.malformedMessage
        }
        return SiteStatus(
            installationID: installationID,
            release: release,
            model: model,
            engine: engine,
            runtimeName: strings[4].flatMap { $0 == "-" ? nil : $0 },
            runtimeVersion: strings[5].flatMap { $0 == "-" ? nil : $0 },
            manifestSHA256: manifest,
            cacheProvider: cache,
            cachePersistent: integers[8] == 1,
            inferencePort: Int(port),
            maxConnections: Int(maxConnections),
            maxActiveRequests: Int(maxActive),
            maxContextTokens: Int(maxContext),
            serviceState: service,
            engineState: engineState,
            protectionPhase: protection,
            protectionArmed: integers[16] == 1,
            tripLatched: integers[17] == 1,
            containerName: strings[18].flatMap { $0.isEmpty ? nil : $0 }
        )
    }

    private static func portableText(_ value: String) -> Bool {
        guard !value.isEmpty, value.utf8.count <= 127 else { return false }
        return value.utf8.allSatisfy { byte in
            (byte >= 48 && byte <= 57)
                || (byte >= 65 && byte <= 90)
                || (byte >= 97 && byte <= 122)
                || "._:/@+-".utf8.contains(byte)
        }
    }

    private static func lowercaseSHA256(_ value: String) -> Bool {
        value.utf8.count == 64 && value.utf8.allSatisfy { byte in
            (byte >= 48 && byte <= 57) || (byte >= 97 && byte <= 102)
        }
    }

    private static func decodeError(_ bytes: [UInt8]) throws -> (code: UInt32, message: String) {
        var reader = Reader(bytes)
        var code: UInt32 = 0
        var message = "watchdog rejected the request."
        while !reader.isAtEnd {
            let field = try reader.readField()
            if field.number == 1, field.wireType == 0 {
                code = try reader.readUInt32()
            } else if field.number == 2, field.wireType == 2 {
                message = String(decoding: try reader.readBytes(), as: UTF8.self)
            } else {
                try reader.skip(wireType: field.wireType)
            }
        }
        return (code, message)
    }

    private static func writeUInt(field: Int, value: UInt64, to output: inout Data) {
        writeVarint(UInt64(field << 3), to: &output)
        writeVarint(value, to: &output)
    }

    private static func writeMessage(field: Int, body: Data, to output: inout Data) {
        writeVarint(UInt64(field << 3 | 2), to: &output)
        writeVarint(UInt64(body.count), to: &output)
        output.append(body)
    }

    private static func writeVarint(_ input: UInt64, to output: inout Data) {
        var value = input
        while value >= 0x80 {
            output.append(UInt8(truncatingIfNeeded: value) | 0x80)
            value >>= 7
        }
        output.append(UInt8(value))
    }

    private struct Reader {
        private let bytes: [UInt8]
        private var offset = 0

        init(_ data: Data) { bytes = [UInt8](data) }
        init(_ bytes: [UInt8]) { self.bytes = bytes }

        var isAtEnd: Bool { offset == bytes.count }

        mutating func readField() throws -> (number: Int, wireType: Int) {
            let key = try readVarint()
            let number = Int(key >> 3)
            let wireType = Int(key & 7)
            guard number > 0 else { throw WatchdogProtocolError.malformedMessage }
            return (number, wireType)
        }

        mutating func readVarint() throws -> UInt64 {
            var value: UInt64 = 0
            for shift in stride(from: 0, to: 64, by: 7) {
                guard offset < bytes.count else { throw WatchdogProtocolError.malformedMessage }
                let byte = bytes[offset]
                offset += 1
                value |= UInt64(byte & 0x7f) << UInt64(shift)
                if byte & 0x80 == 0 { return value }
            }
            throw WatchdogProtocolError.malformedMessage
        }

        mutating func readUInt32() throws -> UInt32 {
            let value = try readVarint()
            guard value <= UInt64(UInt32.max) else { throw WatchdogProtocolError.malformedMessage }
            return UInt32(value)
        }

        mutating func readSInt32() throws -> Int32 {
            let value = try readUInt32()
            return Int32(bitPattern: (value >> 1) ^ (0 &- (value & 1)))
        }

        mutating func readBytes() throws -> [UInt8] {
            let length = try readVarint()
            guard length <= UInt64(bytes.count - offset) else {
                throw WatchdogProtocolError.malformedMessage
            }
            let end = offset + Int(length)
            let result = Array(bytes[offset..<end])
            offset = end
            return result
        }

        mutating func readString() throws -> String {
            guard let value = String(bytes: try readBytes(), encoding: .utf8) else {
                throw WatchdogProtocolError.malformedMessage
            }
            return value
        }

        mutating func skip(wireType: Int) throws {
            switch wireType {
            case 0:
                _ = try readVarint()
            case 1:
                try advance(8)
            case 2:
                _ = try readBytes()
            case 5:
                try advance(4)
            default:
                throw WatchdogProtocolError.malformedMessage
            }
        }

        private mutating func advance(_ count: Int) throws {
            guard count <= bytes.count - offset else {
                throw WatchdogProtocolError.malformedMessage
            }
            offset += count
        }
    }
}
