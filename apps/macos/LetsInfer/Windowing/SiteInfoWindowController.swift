import AppKit
import SwiftUI

@MainActor
final class SiteInfoWindowController: NSObject, ObservableObject, NSWindowDelegate {
    private var window: NSWindow?
    private var siteID: SavedSite.ID?

    func show(site: SavedSite, monitoring: SiteMonitoringController) {
        if let window, siteID == site.id {
            present(window)
            return
        }

        window?.close()

        let content = SiteInfoView(site: site)
            .environmentObject(monitoring)
        let contentSize = NSSize(width: 620, height: 680)
        let window = NSWindow(
            contentRect: NSRect(origin: .zero, size: contentSize),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "\(site.name) — System Information"
        let hostingController = NSHostingController(rootView: content)
        hostingController.view.frame = NSRect(origin: .zero, size: contentSize)
        window.contentViewController = hostingController
        window.contentMinSize = NSSize(width: 520, height: 480)
        window.setContentSize(contentSize)
        window.isReleasedWhenClosed = false
        window.level = .floating
        window.collectionBehavior = [.moveToActiveSpace, .fullScreenAuxiliary]
        window.tabbingMode = .disallowed
        window.delegate = self
        window.center()

        self.window = window
        siteID = site.id
        present(window)
    }

    private func present(_ window: NSWindow) {
        // A MenuBarExtra closes its panel after dispatching the button action.
        // Present on the next event-loop turn so that close cannot steal focus.
        window.orderFrontRegardless()
        DispatchQueue.main.async { [weak window] in
            guard let window else { return }
            NSApplication.shared.activate(ignoringOtherApps: true)
            window.orderFrontRegardless()
            window.makeKey()
        }
    }

    func windowWillClose(_ notification: Notification) {
        window = nil
        siteID = nil
    }
}
