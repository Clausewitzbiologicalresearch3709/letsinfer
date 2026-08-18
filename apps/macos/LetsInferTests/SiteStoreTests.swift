import Foundation
import Testing
@testable import LetsInfer

@MainActor
struct SiteStoreTests {
    @Test
    func missingStoreStartsAtWelcomeState() throws {
        let directory = temporaryDirectory()
        let store = SiteStore(directoryURL: directory)

        #expect(store.sites.isEmpty)
        #expect(store.loadError == nil)
    }

    @Test
    func addedSitePersistsAcrossLaunches() throws {
        let directory = temporaryDirectory()
        let store = SiteStore(directoryURL: directory)
        let site = SavedSite(
            name: "Desk Spark",
            host: "site-abcd.local",
            username: "developer",
            authentication: .sshConfig
        )

        try store.add(site)
        let reloaded = SiteStore(directoryURL: directory)

        #expect(reloaded.sites == [site])
    }

    @Test
    func duplicateHostAndPortIsRejected() throws {
        let store = SiteStore(directoryURL: temporaryDirectory())
        let first = SavedSite(
            name: "First",
            host: "site-abcd.local",
            username: "developer",
            authentication: .sshConfig
        )
        let duplicate = SavedSite(
            name: "Second",
            host: "SITE-ABCD.LOCAL.",
            username: "another-user",
            authentication: .sshConfig
        )

        try store.add(first)

        #expect(throws: SiteStore.StoreError.duplicate) {
            try store.add(duplicate)
        }
    }

    @Test
    func privateKeyModeRequiresBookmarkData() throws {
        let store = SiteStore(directoryURL: temporaryDirectory())
        let site = SavedSite(
            name: "Desk Spark",
            host: "site-abcd.local",
            username: "developer",
            authentication: .privateKey
        )

        #expect(throws: SiteStore.StoreError.privateKeyRequired) {
            try store.add(site)
        }
    }

    @Test
    func stableHardwareIdentityRejectsSameSiteAtAnotherAddress() throws {
        let store = SiteStore(directoryURL: temporaryDirectory())
        let identity = SavedHardwareIdentity(
            manufacturer: "ASUS",
            product: "GX10",
            productVersion: nil,
            serialNumber: nil,
            systemUUID: nil,
            machineIDHash: "stable-machine"
        )
        let first = SavedSite(
            name: "First",
            host: "site.local",
            username: "developer",
            authentication: .sshConfig,
            hardwareIdentity: identity
        )
        let moved = SavedSite(
            name: "Moved",
            host: "100.64.0.20",
            username: "developer",
            authentication: .sshConfig,
            hardwareIdentity: identity
        )

        try store.add(first)

        #expect(throws: SiteStore.StoreError.duplicate) {
            try store.add(moved)
        }
    }

    @Test
    func logicalSiteIdentityRejectsDuplicateCoordinatorRoute() throws {
        let store = SiteStore(directoryURL: temporaryDirectory())
        let first = SavedSite(
            name: "Home",
            host: "home.local",
            username: "developer",
            authentication: .sshConfig,
            siteID: "11111111111111111111111111111111"
        )
        let duplicate = SavedSite(
            name: "Home alternate",
            host: "100.64.0.2",
            username: "developer",
            authentication: .sshConfig,
            siteID: "11111111111111111111111111111111"
        )
        try store.add(first)
        #expect(throws: SiteStore.StoreError.duplicate) {
            try store.add(duplicate)
        }
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
    }
}
