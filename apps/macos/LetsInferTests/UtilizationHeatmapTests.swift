import AppKit
import Testing
@testable import LetsInfer

struct UtilizationHeatmapTests {
    @Test @MainActor
    func hoverExposesTheSelectedUnit() {
        let view = UtilizationHeatmapView(
            title: "CPU cores",
            units: [
                UtilizationUnit(id: "cpu0", name: "Core 0", utilizationPercent: 87),
                UtilizationUnit(id: "cpu1", name: "Core 1", utilizationPercent: 12)
            ]
        )
        view.frame = NSRect(x: 0, y: 0, width: 340, height: 76)

        view.updateHover(at: CGPoint(x: 20, y: 40))

        #expect(view.accessibilityValue() as? String == "Core 0 · 87%")
    }
}
