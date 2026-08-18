import AppKit
import SwiftUI

struct MetricHistoryChart: View {
    let points: [MetricHistoryPoint]
    let width: CGFloat
    let compact: Bool
    @State private var hoverLocation: CGPoint?

    init(points: [MetricHistoryPoint], width: CGFloat = 404, compact: Bool = false) {
        self.points = points
        self.width = width
        self.compact = compact
    }

    private var visiblePoints: [MetricHistoryPoint] {
        guard let newest = points.max(by: { $0.timestamp < $1.timestamp })?.timestamp else {
            return []
        }
        let window: TimeInterval = compact ? 24 * 60 * 60 : 30 * 60
        let cutoff = newest.addingTimeInterval(-window)
        return points.filter { $0.timestamp >= cutoff && $0.timestamp <= newest }
    }

    var body: some View {
        MetricHistoryRepresentable(
            points: visiblePoints,
            hoverLocation: compact ? nil : hoverLocation,
            compact: compact
        )
            .frame(width: width, height: compact ? 34 : 148)
            .contentShape(Rectangle())
            .mask {
                if compact {
                    LinearGradient(
                        stops: [
                            .init(color: .clear, location: 0),
                            .init(color: .white.opacity(0.70), location: 0.06),
                            .init(color: .white, location: 0.15)
                        ],
                        startPoint: .leading,
                        endPoint: .trailing
                    )
                } else {
                    Rectangle()
                }
            }
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

private struct MetricHistoryRepresentable: NSViewRepresentable {
    let points: [MetricHistoryPoint]
    let hoverLocation: CGPoint?
    let compact: Bool

    func makeNSView(context: Context) -> MetricHistoryView {
        let view = MetricHistoryView(points: points, compact: compact)
        view.updateHover(at: hoverLocation)
        return view
    }

    func updateNSView(_ view: MetricHistoryView, context: Context) {
        view.update(points: points)
        view.updateHover(at: hoverLocation)
    }
}

final class MetricHistoryView: NSView {
    private struct Series {
        let name: String
        let color: NSColor
        let value: KeyPath<MetricHistoryPoint, Double?>
    }

    private let series = [
        Series(name: "GPU", color: .systemGreen, value: \.gpuUtilization),
        Series(name: "Memory", color: .systemBlue, value: \.memoryUtilization),
        Series(name: "CPU", color: .systemOrange, value: \.cpuUtilization),
        Series(name: "Disk", color: .systemPurple, value: \.diskUtilization)
    ]

    private var points: [MetricHistoryPoint]
    private let compact: Bool
    private let hoverDateFormatter: DateFormatter
    private var hoverTrackingArea: NSTrackingArea?
    private var hoveredPoint: MetricHistoryPoint?

    init(points: [MetricHistoryPoint], compact: Bool = false) {
        self.points = points.sorted { $0.timestamp < $1.timestamp }
        self.compact = compact
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US")
        formatter.timeZone = .current
        formatter.dateFormat = "h:mm:ss a"
        hoverDateFormatter = formatter
        super.init(frame: NSRect(x: 0, y: 0, width: compact ? 174 : 404, height: compact ? 34 : 148))
        setAccessibilityElement(true)
        setAccessibilityRole(.group)
        setAccessibilityLabel("System load history")
        setAccessibilityValue("No selected sample")
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override var intrinsicContentSize: NSSize {
        NSSize(width: compact ? 174 : 404, height: compact ? 34 : 148)
    }

    override var isFlipped: Bool { true }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        window?.acceptsMouseMovedEvents = true
    }

    func update(points: [MetricHistoryPoint]) {
        self.points = points.sorted { $0.timestamp < $1.timestamp }
        if let hoveredPoint, !points.contains(where: { $0.id == hoveredPoint.id }) {
            self.hoveredPoint = nil
        }
        needsDisplay = true
    }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let hoverTrackingArea {
            removeTrackingArea(hoverTrackingArea)
        }
        let trackingArea = NSTrackingArea(
            rect: bounds,
            options: [.mouseMoved, .mouseEnteredAndExited, .activeAlways],
            owner: self,
            userInfo: nil
        )
        addTrackingArea(trackingArea)
        hoverTrackingArea = trackingArea
    }

    override func mouseMoved(with event: NSEvent) {
        updateHover(at: convert(event.locationInWindow, from: nil))
    }

    func updateHover(at mouseLocation: CGPoint?) {
        guard !compact else {
            clearHover()
            return
        }
        guard let mouseLocation else {
            clearHover()
            return
        }
        let values = points.filter(hasAnyValue)
        guard chartRect.contains(mouseLocation), !values.isEmpty else {
            clearHover()
            return
        }

        let firstX = xLocation(for: values[0])
        let lastX = xLocation(for: values[values.count - 1])
        guard mouseLocation.x >= firstX - 6, mouseLocation.x <= lastX + 6 else {
            clearHover()
            return
        }

        let nearest = values.min {
            abs(xLocation(for: $0) - mouseLocation.x) <
                abs(xLocation(for: $1) - mouseLocation.x)
        }
        guard let nearest else {
            clearHover()
            return
        }

        if hoveredPoint?.id != nearest.id {
            hoveredPoint = nearest
            setAccessibilityValue(accessibilitySummary(for: nearest))
            needsDisplay = true
        }
    }

    override func mouseExited(with event: NSEvent) {
        clearHover()
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        if compact {
            for item in series {
                drawSeries(item)
            }
            return
        }
        drawBackground()
        drawHeader()
        drawLegend()
        drawGrid()
        for item in series {
            drawSeries(item)
        }
        drawTimeLabels()

        if points.filter(hasAnyValue).count < 2 {
            drawEmptyState()
        }
        drawHover()
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

    private func drawHeader() {
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 10, weight: .bold),
            .foregroundColor: NSColor.secondaryLabelColor
        ]
        ("SYSTEM LOAD" as NSString).draw(
            at: NSPoint(x: 18, y: 10),
            withAttributes: attributes
        )

        let detailAttributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 8, weight: .medium),
            .foregroundColor: NSColor.tertiaryLabelColor
        ]
        let detail = "30 MIN · 1 SEC"
        let size = (detail as NSString).size(withAttributes: detailAttributes)
        (detail as NSString).draw(
            at: NSPoint(x: bounds.width - size.width - 18, y: 11),
            withAttributes: detailAttributes
        )
    }

    private func drawLegend() {
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 9.5, weight: .regular),
            .foregroundColor: NSColor.secondaryLabelColor
        ]
        let latest = points.last
        var x: CGFloat = 18

        for item in series {
            let dot = NSBezierPath(ovalIn: NSRect(x: x, y: 31, width: 6, height: 6))
            item.color.setFill()
            dot.fill()
            x += 9

            let current = latest?[keyPath: item.value]
            let text = "\(item.name) \(current.map { "\(Int($0.rounded()))%" } ?? "—")"
            (text as NSString).draw(at: NSPoint(x: x, y: 27), withAttributes: attributes)
            x += (text as NSString).size(withAttributes: attributes).width + 10
        }
    }

    private func drawGrid() {
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 9),
            .foregroundColor: NSColor.tertiaryLabelColor
        ]

        for value in [100, 50, 0] {
            let y = chartRect.maxY - CGFloat(value) / 100 * chartRect.height
            let grid = NSBezierPath()
            grid.move(to: NSPoint(x: chartRect.minX, y: y))
            grid.line(to: NSPoint(x: chartRect.maxX, y: y))
            grid.lineWidth = 0.5
            NSColor.separatorColor.withAlphaComponent(0.34).setStroke()
            grid.stroke()

            let label = "\(value)"
            let size = (label as NSString).size(withAttributes: attributes)
            (label as NSString).draw(
                at: NSPoint(x: chartRect.minX - size.width - 6, y: y - size.height / 2),
                withAttributes: attributes
            )
        }
    }

    private func drawSeries(_ item: Series) {
        let values = points.compactMap { point -> (MetricHistoryPoint, Double)? in
            guard let value = point[keyPath: item.value] else { return nil }
            return (point, value)
        }
        guard !values.isEmpty else { return }

        if values.count == 1, let first = values.first {
            drawMarker(at: location(for: first.0, value: first.1), color: item.color)
            return
        }

        let line = NSBezierPath()
        let first = location(for: values[0].0, value: values[0].1)
        line.move(to: first)
        for entry in values.dropFirst() {
            line.line(to: location(for: entry.0, value: entry.1))
        }

        if let last = values.last {
            drawGradient(beneath: line, first: first, last: last.0, color: item.color)
        }

        line.lineWidth = 0.85
        line.lineJoinStyle = .round
        line.lineCapStyle = .round
        item.color.setStroke()
        line.stroke()
    }

    private func drawGradient(
        beneath line: NSBezierPath,
        first: NSPoint,
        last: MetricHistoryPoint,
        color: NSColor
    ) {
        let area = line.copy() as! NSBezierPath
        area.line(to: NSPoint(x: xLocation(for: last), y: chartRect.maxY))
        area.line(to: NSPoint(x: first.x, y: chartRect.maxY))
        area.close()

        NSGraphicsContext.saveGraphicsState()
        area.addClip()
        NSGradient(
            starting: color.withAlphaComponent(0.26),
            ending: color.withAlphaComponent(0)
        )?.draw(
            from: NSPoint(x: chartRect.midX, y: chartRect.minY),
            to: NSPoint(x: chartRect.midX, y: chartRect.maxY),
            options: []
        )
        NSGraphicsContext.restoreGraphicsState()
    }

    private func drawTimeLabels() {
        guard let first = points.first else { return }
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 9),
            .foregroundColor: NSColor.tertiaryLabelColor
        ]
        let formatter = DateFormatter()
        formatter.dateFormat = "h:mm a"

        (formatter.string(from: first.timestamp) as NSString).draw(
            at: NSPoint(x: chartRect.minX, y: chartRect.maxY + 7),
            withAttributes: attributes
        )
        let now = "Now"
        let size = (now as NSString).size(withAttributes: attributes)
        (now as NSString).draw(
            at: NSPoint(x: chartRect.maxX - size.width, y: chartRect.maxY + 7),
            withAttributes: attributes
        )
    }

    private func drawEmptyState() {
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 11),
            .foregroundColor: NSColor.secondaryLabelColor
        ]
        let text = points.isEmpty ? "Collecting history…" : "History starts now"
        let size = (text as NSString).size(withAttributes: attributes)
        (text as NSString).draw(
            at: NSPoint(x: chartRect.midX - size.width / 2, y: chartRect.midY - size.height / 2),
            withAttributes: attributes
        )
    }

    private func drawHover() {
        guard let hoveredPoint else { return }
        let x = xLocation(for: hoveredPoint)

        let guide = NSBezierPath()
        guide.move(to: NSPoint(x: x, y: chartRect.minY))
        guide.line(to: NSPoint(x: x, y: chartRect.maxY))
        guide.lineWidth = 1
        NSColor.secondaryLabelColor.withAlphaComponent(0.24).setStroke()
        guide.stroke()

        for item in series {
            guard let value = hoveredPoint[keyPath: item.value] else { continue }
            drawMarker(at: location(for: hoveredPoint, value: value), color: item.color)
        }
        drawTooltip(for: hoveredPoint, x: x)
    }

    private func drawMarker(at point: NSPoint, color: NSColor) {
        let glow = NSBezierPath(ovalIn: NSRect(x: point.x - 7, y: point.y - 7, width: 14, height: 14))
        color.withAlphaComponent(0.18).setFill()
        glow.fill()

        let ring = NSBezierPath(ovalIn: NSRect(x: point.x - 4, y: point.y - 4, width: 8, height: 8))
        NSColor.controlBackgroundColor.setFill()
        ring.fill()

        let dot = NSBezierPath(ovalIn: NSRect(x: point.x - 2.5, y: point.y - 2.5, width: 5, height: 5))
        color.setFill()
        dot.fill()
    }

    private func drawTooltip(for point: MetricHistoryPoint, x: CGFloat) {
        let bubbleSize = NSSize(width: 190, height: 67)
        let bubbleX = min(
            max(x - bubbleSize.width / 2, chartRect.minX),
            chartRect.maxX - bubbleSize.width
        )
        let bubbleY = chartRect.minY + 7
        let rect = NSRect(origin: NSPoint(x: bubbleX, y: bubbleY), size: bubbleSize)

        NSGraphicsContext.saveGraphicsState()
        let shadow = NSShadow()
        shadow.shadowColor = NSColor.black.withAlphaComponent(0.28)
        shadow.shadowBlurRadius = 8
        shadow.shadowOffset = NSSize(width: 0, height: 2)
        shadow.set()
        NSColor.windowBackgroundColor.withAlphaComponent(0.98).setFill()
        NSBezierPath(roundedRect: rect, xRadius: 9, yRadius: 9).fill()
        NSGraphicsContext.restoreGraphicsState()

        let border = NSBezierPath(roundedRect: rect.insetBy(dx: 0.5, dy: 0.5), xRadius: 8.5, yRadius: 8.5)
        border.lineWidth = 1
        NSColor.separatorColor.withAlphaComponent(0.65).setStroke()
        border.stroke()

        let labelAttributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 9, weight: .semibold),
            .foregroundColor: NSColor.labelColor
        ]
        let valueAttributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 11, weight: .bold),
            .foregroundColor: NSColor.labelColor
        ]
        let dateAttributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 8.5),
            .foregroundColor: NSColor.secondaryLabelColor
        ]

        for (index, item) in series.enumerated() {
            let column = index % 2
            let row = index / 2
            let originX = rect.minX + 10 + CGFloat(column) * 92
            let originY = rect.minY + 7 + CGFloat(row) * 19
            let dot = NSBezierPath(ovalIn: NSRect(x: originX, y: originY + 4, width: 6, height: 6))
            item.color.setFill()
            dot.fill()

            (item.name as NSString).draw(
                at: NSPoint(x: originX + 9, y: originY),
                withAttributes: labelAttributes
            )
            let value = point[keyPath: item.value].map { "\(Int($0.rounded()))%" } ?? "—"
            let size = (value as NSString).size(withAttributes: valueAttributes)
            (value as NSString).draw(
                at: NSPoint(x: originX + 83 - size.width, y: originY - 1),
                withAttributes: valueAttributes
            )
        }

        (hoverDateFormatter.string(from: point.timestamp) as NSString).draw(
            at: NSPoint(x: rect.minX + 10, y: rect.minY + 48),
            withAttributes: dateAttributes
        )
    }

    private var chartRect: NSRect {
        if compact {
            return NSRect(x: 1, y: 2, width: max(1, bounds.width - 2), height: max(1, bounds.height - 4))
        }
        return NSRect(x: 42, y: 47, width: bounds.width - 60, height: 68)
    }

    private func hasAnyValue(_ point: MetricHistoryPoint) -> Bool {
        series.contains { point[keyPath: $0.value] != nil }
    }

    private func xLocation(for point: MetricHistoryPoint) -> CGFloat {
        guard let first = points.first, let last = points.last else { return chartRect.minX }
        let span = max(1, last.timestamp.timeIntervalSince(first.timestamp))
        let progress = max(0, min(1, point.timestamp.timeIntervalSince(first.timestamp) / span))
        return chartRect.minX + CGFloat(progress) * chartRect.width
    }

    private func location(for point: MetricHistoryPoint, value: Double) -> NSPoint {
        let metric = max(0, min(100, value))
        return NSPoint(
            x: xLocation(for: point),
            y: chartRect.maxY - CGFloat(metric) / 100 * chartRect.height
        )
    }

    private func clearHover() {
        guard hoveredPoint != nil else { return }
        hoveredPoint = nil
        setAccessibilityValue("No selected sample")
        needsDisplay = true
    }

    private func accessibilitySummary(for point: MetricHistoryPoint) -> String {
        let values = series.map { item in
            let value = point[keyPath: item.value].map { "\(Int($0.rounded())) percent" } ?? "unavailable"
            return "\(item.name) \(value)"
        }
        return "\(values.joined(separator: ", ")), \(hoverDateFormatter.string(from: point.timestamp))"
    }
}
