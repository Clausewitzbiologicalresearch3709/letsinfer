import Foundation

/// The only monitoring contract consumed by the app.
///
/// Every transport translates its native response into `SiteSnapshot`. UI,
/// monitoring, history, and charts remain transport-independent.
protocol SiteDataSource: Sendable {
    func fetchSnapshot(for site: SavedSite) async throws -> SiteSnapshot
    func fetchHistory(for site: SavedSite, since: Date) async throws -> [SiteSnapshot]
    func updates(for site: SavedSite) async -> AsyncThrowingStream<SiteSnapshot, Error>?
}

extension SiteDataSource {
    func fetchHistory(for site: SavedSite, since: Date) async throws -> [SiteSnapshot] {
        []
    }

    func updates(for site: SavedSite) async -> AsyncThrowingStream<SiteSnapshot, Error>? {
        nil
    }
}

struct RoutingSiteDataSource: SiteDataSource {
    private let ssh: any SiteDataSource
    private let watchdog: any SiteDataSource

    init(
        ssh: any SiteDataSource = SSHSiteDataSource(),
        watchdog: (any SiteDataSource)? = nil
    ) {
        self.ssh = ssh
        self.watchdog = watchdog ?? WatchdogDataSource()
    }

    func fetchSnapshot(for site: SavedSite) async throws -> SiteSnapshot {
        switch site.dataSource {
        case nil:
            do {
                return try await watchdog.fetchSnapshot(for: site)
            } catch {
                guard site.installationID == nil else { throw error }
                return try await ssh.fetchSnapshot(for: site)
            }
        case .ssh:
            return try await ssh.fetchSnapshot(for: site)
        case .watchdog:
            do {
                return try await watchdog.fetchSnapshot(for: site)
            } catch {
                guard site.installationID == nil else { throw error }
                return try await ssh.fetchSnapshot(for: site)
            }
        }
    }

    func fetchHistory(for site: SavedSite, since: Date) async throws -> [SiteSnapshot] {
        switch site.dataSource {
        case nil, .watchdog:
            do {
                return try await watchdog.fetchHistory(for: site, since: since)
            } catch {
                return []
            }
        case .ssh:
            return []
        }
    }

    func updates(for site: SavedSite) async -> AsyncThrowingStream<SiteSnapshot, Error>? {
        switch site.dataSource {
        case nil, .watchdog:
            return await watchdog.updates(for: site)
        case .ssh:
            return nil
        }
    }
}
