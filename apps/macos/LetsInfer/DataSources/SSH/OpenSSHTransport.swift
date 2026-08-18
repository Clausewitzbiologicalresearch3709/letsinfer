import Darwin
import Foundation

struct OpenSSHTransport: SSHTransport {
    private let stateDirectory: URL
    private let timeout: TimeInterval

    init(stateDirectory: URL? = nil, timeout: TimeInterval = 10) {
        let support = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        )[0]
        self.stateDirectory = stateDirectory
            ?? support.appendingPathComponent("letsinfer/ssh", isDirectory: true)
        self.timeout = timeout
    }

    func run(_ command: String, on site: SavedSite) async throws -> String {
        let stateDirectory = stateDirectory
        let timeout = timeout

        return try await Task.detached(priority: .utility) {
            try Self.runSynchronously(
                command,
                on: site,
                stateDirectory: stateDirectory,
                timeout: timeout
            )
        }.value
    }

    private static func runSynchronously(
        _ command: String,
        on site: SavedSite,
        stateDirectory: URL,
        timeout: TimeInterval
    ) throws -> String {
        let fileManager = FileManager.default
        try fileManager.createDirectory(at: stateDirectory, withIntermediateDirectories: true)
        try? fileManager.setAttributes(
            [.posixPermissions: 0o700],
            ofItemAtPath: stateDirectory.path
        )

        let knownHosts = stateDirectory.appendingPathComponent("known_hosts")
        // Unix-domain socket paths are short on macOS; the normal temporary
        // directory path can exceed the limit before OpenSSH adds its hash.
        let controlPath = "/tmp/letsinfer-\(getuid())-%C"

        var keyURL: URL?
        if site.authentication == .privateKey {
            guard let bookmark = site.privateKeyBookmark else {
                throw SSHTransportError.keyUnavailable
            }
            var isStale = false
            do {
                let resolved = try URL(
                    resolvingBookmarkData: bookmark,
                    options: [.withoutUI],
                    relativeTo: nil,
                    bookmarkDataIsStale: &isStale
                )
                guard !isStale else { throw SSHTransportError.keyUnavailable }
                keyURL = resolved
            } catch let error as SSHTransportError {
                throw error
            } catch {
                throw SSHTransportError.keyUnavailable
            }
        }

        var arguments = [
            "-T",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=6",
            "-o", "ServerAliveInterval=5",
            "-o", "ServerAliveCountMax=1",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "UserKnownHostsFile=\(knownHosts.path)",
            "-o", "ControlMaster=auto",
            "-o", "ControlPersist=60",
            "-o", "ControlPath=\(controlPath)",
            "-o", "LogLevel=ERROR",
            "-p", String(site.port)
        ]

        if let keyURL {
            arguments += ["-o", "IdentitiesOnly=yes", "-i", keyURL.path]
        }

        arguments += ["--", "\(site.username)@\(site.host)", command]

        let process = Process()
        let standardOutput = Pipe()
        let standardError = Pipe()
        let finished = DispatchSemaphore(value: 0)

        process.executableURL = URL(fileURLWithPath: "/usr/bin/ssh")
        process.arguments = arguments
        process.standardOutput = standardOutput
        process.standardError = standardError
        process.environment = environment()
        process.terminationHandler = { _ in finished.signal() }

        do {
            try process.run()
        } catch {
            throw SSHTransportError.launchFailed(error.localizedDescription)
        }

        if finished.wait(timeout: .now() + timeout) == .timedOut {
            process.terminate()
            if finished.wait(timeout: .now() + 1) == .timedOut {
                kill(process.processIdentifier, SIGKILL)
            }
            throw SSHTransportError.timedOut
        }

        let output = standardOutput.fileHandleForReading.readDataToEndOfFile()
        let error = standardError.fileHandleForReading.readDataToEndOfFile()
        let outputText = String(decoding: output, as: UTF8.self)
            .trimmingCharacters(in: .whitespacesAndNewlines)

        guard process.terminationStatus == 0 else {
            let errorText = String(decoding: error, as: UTF8.self)
                .trimmingCharacters(in: .whitespacesAndNewlines)
            throw SSHTransportError.commandFailed(errorText)
        }

        return outputText
    }

    private static func environment() -> [String: String] {
        let source = ProcessInfo.processInfo.environment
        var result = [
            "HOME": FileManager.default.homeDirectoryForCurrentUser.path,
            "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": "en_US.UTF-8"
        ]
        if let socket = source["SSH_AUTH_SOCK"] {
            result["SSH_AUTH_SOCK"] = socket
        }
        return result
    }
}
