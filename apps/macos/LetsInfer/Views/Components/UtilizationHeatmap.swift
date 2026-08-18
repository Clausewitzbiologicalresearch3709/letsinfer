import AppKit
import SwiftUI

struct UtilizationHeatmap: View {
    let title: String
    let units: [UtilizationUnit]
    let width: CGFloat
    @State private var hoverLocation: CGPoint?

    init(title: String, units: [UtilizationUnit], width: CGFloat = 404) {
        self.title = title
        self.units = units
        self.width = width
    }

    private var height: CGFloat {
        units.count > 10 ? 84 : 68
    }

    var body: some View {
        UtilizationHeatmapRepresentable(
            title: title,
            units: units,
            hoverLocation: hoverLocation
        )
        .frame(width: width, height: height)
        .contentShape(Rectangle())
        .onContinuousHover(coordinateSpace: .local) { phase in
            switch phase {
            case .active(let location):
                hoverLocation = location
            case .ended:
                hoverLocation = nil
            }
        }
    }
}

private struct UtilizationHeatmapRepresentable: NSViewRepresentable {
    let title: String
    let units: [UtilizationUnit]
    let hoverLocation: CGPoint?

    func makeNSView(context: Context) -> UtilizationHeatmapView {
        let view = UtilizationHeatmapView(title: title, units: units)
        view.updateHover(at: hoverLocation)
        return view
    }

    func updateNSView(_ view: UtilizationHeatmapView, context: Context) {
        view.update(title: title, units: units)
        view.updateHover(at: hoverLocation)
    }
}

final class UtilizationHeatmapView: NSView {
    private let cellSize: CGFloat = 12
    private let cellGap: CGFloat = 4
    private let gridOrigin = NSPoint(x: 14, y: 30)
    private var title: String
    private var units: [UtilizationUnit]
    private var hoveredUnitID: String?
    private var hoverTrackingArea: NSTrackingArea?

    init(title: String, units: [UtilizationUnit]) {
        self.title = title
        self.units = units
        super.init(frame: NSRect(x: 0, y: 0, width: 340, height: units.count > 10 ? 84 : 68))
        setAccessibilityElement(true)
        setAccessibilityRole(.group)
        setAccessibilityLabel(title)
        setAccessibilityValue("No selected unit")
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override var isFlipped: Bool { true }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        window?.acceptsMouseMovedEvents = true
    }

    func update(title: String, units: [UtilizationUnit]) {
        self.title = title
        self.units = units
        if let hoveredUnitID, !units.contains(where: { $0.id == hoveredUnitID }) {
            self.hoveredUnitID = nil
        }
        setAccessibilityLabel(title)
        needsDisplay = true
    }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let hoverTrackingArea {
            removeTrackingArea(hoverTrackingArea)
        }
        let area = NSTrackingArea(
            rect: bounds,
            options: [.mouseMoved, .mouseEnteredAndExited, .activeAlways],
            owner: self,
            userInfo: nil
        )
        addTrackingArea(area)
        hoverTrackingArea = area
    }

    override func mouseMoved(with event: NSEvent) {
        updateHover(at: convert(event.locationInWindow, from: nil))
    }

    override func mouseExited(with event: NSEvent) {
        updateHover(at: nil)
    }

    func updateHover(at location: CGPoint?) {
        let next = location.flatMap { point in
            units.indices.first { unitRect(at: $0).contains(point) }
        }.map { units[$0] }

        guard next?.id != hoveredUnitID else { return }
        hoveredUnitID = next?.id
        if let next {
            setAccessibilityValue(detail(for: next))
        } else {
            setAccessibilityValue("No selected unit")
        }
        needsDisplay = true
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        drawBackground()

        let titleAttributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 12, weight: .semibold),
            .foregroundColor: NSColor.labelColor
        ]
        let detailAttributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 9.5, weight: .regular),
            .foregroundColor: NSColor.secondaryLabelColor
        ]

        (title as NSString).draw(at: NSPoint(x: 14, y: 8), withAttributes: titleAttributes)
        drawHeaderDetail(attributes: detailAttributes)

        if units.isEmpty {
            ("Unavailable" as NSString).draw(
                at: gridOrigin,
                withAttributes: detailAttributes
            )
            return
        }

        for index in units.indices {
            let unit = units[index]
            let rect = unitRect(at: index)
            color(for: unit.utilizationPercent).setFill()
            NSBezierPath(roundedRect: rect, xRadius: 2, yRadius: 2).fill()

            if hoveredUnitID == unit.id {
                let outline = NSBezierPath(
                    roundedRect: rect.insetBy(dx: -1.5, dy: -1.5),
                    xRadius: 2.5,
                    yRadius: 2.5
                )
                outline.lineWidth = 1
                NSColor.labelColor.setStroke()
                outline.stroke()
            }
        }

        drawLegend(attributes: detailAttributes)
    }

    private func drawBackground() {
        let appearance = effectiveAppearance.bestMatch(from: [.darkAqua, .aqua])
        let tint = appearance == .darkAqua
            ? NSColor(calibratedWhite: 0.075, alpha: 1)
            : NSColor(calibratedWhite: 0.92, alpha: 1)
        tint.setFill()
        NSBezierPath(rect: bounds).fill()

        NSColor.separatorColor.withAlphaComponent(0.28).setStroke()
        for y in [CGFloat(0.5), bounds.maxY - 0.5] {
            let divider = NSBezierPath()
            divider.move(to: NSPoint(x: bounds.minX, y: y))
            divider.line(to: NSPoint(x: bounds.maxX, y: y))
            divider.lineWidth = 0.5
            divider.stroke()
        }
    }

    private var rowCount: Int {
        units.count > 10 ? 2 : 1
    }

    private var columnCount: Int {
        max(1, Int(ceil(Double(units.count) / Double(rowCount))))
    }

    private func unitRect(at index: Int) -> NSRect {
        let row = index / columnCount
        let column = index % columnCount
        return NSRect(
            x: gridOrigin.x + CGFloat(column) * (cellSize + cellGap),
            y: gridOrigin.y + CGFloat(row) * (cellSize + cellGap),
            width: cellSize,
            height: cellSize
        )
    }

    private func drawHeaderDetail(attributes: [NSAttributedString.Key: Any]) {
        let text: String
        if let hovered = units.first(where: { $0.id == hoveredUnitID }) {
            text = detail(for: hovered)
        } else {
            let reporting = units.filter { $0.utilizationPercent != nil }.count
            text = "\(reporting)/\(units.count) reporting"
        }
        let size = (text as NSString).size(withAttributes: attributes)
        (text as NSString).draw(
            at: NSPoint(x: bounds.width - size.width - 14, y: 10),
            withAttributes: attributes
        )
    }

    private func drawLegend(attributes: [NSAttributedString.Key: Any]) {
        let legendCell: CGFloat = 7
        let legendGap: CGFloat = 3
        let less = "Less"
        let more = "More"
        let lessSize = (less as NSString).size(withAttributes: attributes)
        let moreSize = (more as NSString).size(withAttributes: attributes)
        let cellsWidth = 5 * legendCell + 4 * legendGap
        let startX = bounds.width - 14 - moreSize.width - 5 - cellsWidth - 5 - lessSize.width
        let y = gridOrigin.y + CGFloat(rowCount) * (cellSize + cellGap) + 7

        (less as NSString).draw(at: NSPoint(x: startX, y: y - 2), withAttributes: attributes)
        let cellsX = startX + lessSize.width + 5
        for level in 0...4 {
            let rect = NSRect(
                x: cellsX + CGFloat(level) * (legendCell + legendGap),
                y: y,
                width: legendCell,
                height: legendCell
            )
            color(forLevel: level).setFill()
            NSBezierPath(roundedRect: rect, xRadius: 1.5, yRadius: 1.5).fill()
        }
        (more as NSString).draw(
            at: NSPoint(x: cellsX + cellsWidth + 5, y: y - 2),
            withAttributes: attributes
        )
    }

    private func detail(for unit: UtilizationUnit) -> String {
        let value = unit.utilizationPercent.map { "\(Int($0.rounded()))%" } ?? "unavailable"
        return "\(unit.name) · \(value)"
    }

    private func color(for utilization: Double?) -> NSColor {
        guard let utilization else { return color(forLevel: 0) }
        switch utilization {
        case ...0: return color(forLevel: 0)
        case ...25: return color(forLevel: 1)
        case ...50: return color(forLevel: 2)
        case ...75: return color(forLevel: 3)
        default: return color(forLevel: 4)
        }
    }

    private func color(forLevel level: Int) -> NSColor {
        switch level {
        case 1: return NSColor.systemGreen.withAlphaComponent(0.38)
        case 2: return NSColor.systemGreen.withAlphaComponent(0.58)
        case 3: return NSColor.systemGreen.withAlphaComponent(0.78)
        case 4: return NSColor.systemGreen
        default: return NSColor.systemGreen.withAlphaComponent(0.20)
        }
    }
}
