import SwiftUI

@main
struct LetsInferApp: App {
    @StateObject private var siteStore = SiteStore()
    @StateObject private var monitoring = SiteMonitoringController()
    @StateObject private var addSiteWindow = AddSiteWindowController()
    @StateObject private var siteInfoWindow = SiteInfoWindowController()

    var body: some Scene {
        MenuBarExtra {
            MenuBarContentView()
                .environmentObject(siteStore)
                .environmentObject(monitoring)
                .environmentObject(addSiteWindow)
                .environmentObject(siteInfoWindow)
        } label: {
            Image("MenuBarIcon")
                .renderingMode(.original)
                .resizable()
                .scaledToFit()
                .frame(width: 19, height: 17)
                .accessibilityLabel("Let's Infer")
                .task(id: monitoringKey) {
                    guard ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] == nil
                    else { return }
                    monitoring.start(sites: siteStore.sites)
                }
        }
        .menuBarExtraStyle(.window)
    }

    private var monitoringKey: String {
        siteStore.sites
            .map {
                "\($0.id.uuidString):\($0.host):\($0.port):"
                    + "\($0.controlPort ?? 0):\($0.resolvedDataSource)"
            }
            .joined(separator: "|")
    }
}
