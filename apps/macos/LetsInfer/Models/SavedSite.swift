import Foundation

struct SavedSite: Codable, Equatable, Identifiable, Sendable {
    let id: UUID
    var name: String
    var host: String
    var port: Int
    var username: String
    var authentication: SSHAuthenticationMethod
    var privateKeyBookmark: Data?
    var privateKeyName: String?
    var dataSource: SiteDataSourceConfiguration?
    var installationID: String?
    var controllerID: String?
    var controlPort: Int?
    var siteID: String?
    var coordinatorMemberID: String?
    var memberPublicKeySHA256: String?
    var controllerRole: String?
    var hardwareIdentity: SavedHardwareIdentity?
    let createdAt: Date

    init(
        id: UUID = UUID(),
        name: String,
        host: String,
        port: Int = 22,
        username: String,
        authentication: SSHAuthenticationMethod,
        privateKeyBookmark: Data? = nil,
        privateKeyName: String? = nil,
        dataSource: SiteDataSourceConfiguration? = nil,
        installationID: String? = nil,
        controllerID: String? = nil,
        controlPort: Int? = nil,
        siteID: String? = nil,
        coordinatorMemberID: String? = nil,
        memberPublicKeySHA256: String? = nil,
        controllerRole: String? = nil,
        hardwareIdentity: SavedHardwareIdentity? = nil,
        createdAt: Date = Date()
    ) {
        self.id = id
        self.name = name
        self.host = host
        self.port = port
        self.username = username
        self.authentication = authentication
        self.privateKeyBookmark = privateKeyBookmark
        self.privateKeyName = privateKeyName
        self.dataSource = dataSource
        self.installationID = installationID
        self.controllerID = controllerID
        self.controlPort = controlPort
        self.siteID = siteID
        self.coordinatorMemberID = coordinatorMemberID
        self.memberPublicKeySHA256 = memberPublicKeySHA256
        self.controllerRole = controllerRole
        self.hardwareIdentity = hardwareIdentity
        self.createdAt = Date(
            timeIntervalSince1970: floor(createdAt.timeIntervalSince1970 * 1_000) / 1_000
        )
    }

    var resolvedDataSource: SiteDataSourceConfiguration {
        dataSource ?? .watchdog(port: 9_768)
    }
}

struct SavedHardwareIdentity: Codable, Equatable, Sendable {
    let manufacturer: String?
    let product: String?
    let productVersion: String?
    let serialNumber: String?
    let systemUUID: String?
    let machineIDHash: String?

    init(
        manufacturer: String?,
        product: String?,
        productVersion: String?,
        serialNumber: String?,
        systemUUID: String?,
        machineIDHash: String?
    ) {
        self.manufacturer = manufacturer
        self.product = product
        self.productVersion = productVersion
        self.serialNumber = serialNumber
        self.systemUUID = systemUUID
        self.machineIDHash = machineIDHash
    }

    init(snapshot: SiteSnapshot) {
        manufacturer = snapshot.identity?.manufacturerName
        product = snapshot.identity?.product
        productVersion = snapshot.system?.productVersion
        serialNumber = snapshot.system?.serialNumber
        systemUUID = snapshot.system?.systemUUID
        machineIDHash = snapshot.system?.machineIDHash
    }

    var stableIdentifier: String? {
        serialNumber ?? systemUUID ?? machineIDHash
    }
}

enum SiteDataSourceConfiguration: Codable, Equatable, Sendable {
    case ssh
    case watchdog(port: Int)
}

enum SSHAuthenticationMethod: String, Codable, CaseIterable, Identifiable, Sendable {
    case sshConfig
    case privateKey

    var id: Self { self }

    var title: String {
        switch self {
        case .sshConfig:
            "SSH Agent or Config"
        case .privateKey:
            "Private Key"
        }
    }
}
