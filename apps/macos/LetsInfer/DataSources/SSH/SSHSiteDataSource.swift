import Foundation

actor SSHSiteDataSource: SiteDataSource {
    private struct CPUCoreCounter {
        let id: String
        let total: Double
        let idle: Double
    }

    private struct Baseline {
        let cpuTotal: Double
        let cpuIdle: Double
        let cpuCores: [CPUCoreCounter]
        let receivedBytes: Double
        let transmittedBytes: Double
        let diskReadBytes: Double
        let diskWriteBytes: Double
        let sampledAt: Date
    }

    private let transport: any SSHTransport
    private var baselines: [SavedSite.ID: Baseline] = [:]

    init(transport: any SSHTransport = OpenSSHTransport()) {
        self.transport = transport
    }

    func fetchSnapshot(for site: SavedSite) async throws -> SiteSnapshot {
        let output = try await transport.run(Self.probeCommand, on: site)
        let values = Self.parse(output)
        guard values["timestamp"] != nil else {
            throw SSHTransportError.commandFailed("The Spark returned an unexpected telemetry response.")
        }

        let sampledAt = values.double("timestamp").map(Date.init(timeIntervalSince1970:)) ?? Date()
        let cpuTotal = values.double("cpu_total") ?? 0
        let cpuIdle = values.double("cpu_idle") ?? 0
        let cpuCoreCounters = Self.parseCPUCoreCounters(values["cpu_cores"])
        let receivedBytes = values.double("net_rx") ?? 0
        let transmittedBytes = values.double("net_tx") ?? 0
        let diskReadBytes = values.double("disk_read_bytes") ?? 0
        let diskWriteBytes = values.double("disk_write_bytes") ?? 0
        let previous = baselines[site.id]
        baselines[site.id] = Baseline(
            cpuTotal: cpuTotal,
            cpuIdle: cpuIdle,
            cpuCores: cpuCoreCounters,
            receivedBytes: receivedBytes,
            transmittedBytes: transmittedBytes,
            diskReadBytes: diskReadBytes,
            diskWriteBytes: diskWriteBytes,
            sampledAt: sampledAt
        )

        let gpuFields = (values["gpu"] ?? "")
            .split(separator: ",", omittingEmptySubsequences: false)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        let gpuName = gpuFields[safe: 0]?.nilIfUnavailable
        let gpuUnits = Self.parseGPUUnits(values["gpu_engines"])
        let gpu = gpuFields.count > 3 ? GPUMetrics(
            utilizationPercent: gpuFields.double(at: 4),
            temperatureCelsius: gpuFields.double(at: 3),
            powerWatts: gpuFields.double(at: 6),
            powerLimitWatts: gpuFields.double(at: 7),
            smClockMHz: gpuFields.double(at: 9),
            maxSMClockMHz: gpuFields.double(at: 11),
            isThrottled: Self.throttleActive(Array(gpuFields.dropFirst(17))),
            memoryUtilizationPercent: gpuFields.double(at: 5),
            graphicsClockMHz: gpuFields.double(at: 8),
            memoryClockMHz: gpuFields.double(at: 10),
            performanceState: gpuFields[safe: 12]?.nilIfUnavailable,
            computeMode: gpuFields[safe: 13]?.nilIfUnavailable,
            displayActive: Self.enabled(gpuFields[safe: 14]),
            pcieGeneration: gpuFields.int(at: 15),
            pcieWidth: gpuFields.int(at: 16),
            units: gpuUnits
        ) : nil

        let memoryTotal = values.double("mem_total_kb").map { $0 * 1_024 }
        let memoryAvailable = values.double("mem_available_kb").map { $0 * 1_024 }
        let memoryUsed = Self.subtract(memoryTotal, memoryAvailable)
        let memoryPercent = Self.percentage(used: memoryUsed, total: memoryTotal)
        let swapTotal = values.double("swap_total_kb").map { $0 * 1_024 }
        let swapFree = values.double("swap_free_kb").map { $0 * 1_024 }

        let storageFields = (values["root_disk_kb"] ?? "")
            .split(separator: " ")
            .map(String.init)
        let storageTotal = storageFields.double(at: 0).map { $0 * 1_024 }
        let storageUsed = storageFields.double(at: 1).map { $0 * 1_024 }
        let storageAvailable = storageFields.double(at: 2).map { $0 * 1_024 }

        let loadFields = (values["load_average"] ?? "")
            .split(separator: " ")
            .map(String.init)
        let elapsed = previous.map { max(0, sampledAt.timeIntervalSince($0.sampledAt)) }
        let cpuUsage: Double? = previous.flatMap {
            let totalDelta = cpuTotal - $0.cpuTotal
            let idleDelta = cpuIdle - $0.cpuIdle
            guard totalDelta > 0 else { return nil }
            return max(0, min(100, (totalDelta - idleDelta) / totalDelta * 100))
        }
        let cpuUnits = Self.cpuUnits(
            current: cpuCoreCounters,
            previous: previous?.cpuCores
        )

        return SiteSnapshot(
            siteID: site.id,
            source: .ssh,
            sampledAt: sampledAt,
            availability: .online,
            uptimeSeconds: values.double("uptime"),
            identity: MemberIdentity(
                vendor: values["vendor"]?.nilIfUnavailable,
                product: values["product"]?.nilIfUnavailable,
                architecture: values["architecture"]?.nilIfUnavailable,
                gpuName: gpuName
            ),
            system: MemberSystemInfo(
                hostname: values["hostname"]?.nilIfUnavailable,
                operatingSystem: values["operating_system"]?.nilIfUnavailable,
                kernelVersion: values["kernel"]?.nilIfUnavailable,
                productVersion: values["product_version"]?.nilIfUnavailable,
                serialNumber: values["dgx_serial"]?.nilIfUnavailable
                    ?? values["product_serial"]?.nilIfUnavailable,
                serialSource: values["dgx_serial"]?.nilIfUnavailable != nil
                    ? "NVIDIA DGX release"
                    : (values["product_serial"]?.nilIfUnavailable != nil ? "DMI" : nil),
                systemUUID: values["product_uuid"]?.nilIfUnavailable,
                machineIDHash: values["machine_id_hash"]?.nilIfUnavailable,
                dmiSerialRequiresPrivilege: values["dmi_serial_access"] == "restricted",
                boardVendor: values["board_vendor"]?.nilIfUnavailable,
                boardName: values["board_name"]?.nilIfUnavailable,
                boardVersion: values["board_version"]?.nilIfUnavailable,
                boardSerial: values["board_serial"]?.nilIfUnavailable,
                chassisVendor: values["chassis_vendor"]?.nilIfUnavailable,
                chassisType: values["chassis_type"]?.nilIfUnavailable,
                chassisSerial: values["chassis_serial"]?.nilIfUnavailable,
                biosVendor: values["bios_vendor"]?.nilIfUnavailable,
                biosVersion: values["bios_version"]?.nilIfUnavailable,
                biosDate: values["bios_date"]?.nilIfUnavailable,
                cpuModel: values["cpu_model"]?.nilIfUnavailable,
                cpuCoreCount: values.int("cpu_count"),
                gpuUUID: gpuFields[safe: 1]?.nilIfUnavailable,
                nvidiaDriverVersion: gpuFields[safe: 2]?.nilIfUnavailable,
                dgxName: values["dgx_name"]?.nilIfUnavailable,
                dgxSoftwareVersion: values["dgx_ota_version"]?.nilIfUnavailable,
                dgxBaseBuildVersion: values["dgx_build_version"]?.nilIfUnavailable,
                dgxBuildDate: values["dgx_build_date"]?.nilIfUnavailable,
                dgxCommitID: values["dgx_commit_id"]?.nilIfUnavailable,
                dgxPlatform: values["dgx_platform"]?.nilIfUnavailable,
                dgxUpdateDate: values["dgx_ota_date"]?.nilIfUnavailable,
                nvmeModel: values["nvme_model"]?.nilIfUnavailable,
                nvmeSerial: values["nvme_serial"]?.nilIfUnavailable,
                nvmeFirmware: values["nvme_firmware"]?.nilIfUnavailable,
                networkAddresses: Self.parseNetworkAddresses(values["network_addresses"]),
                defaultNetworkInterface: values["default_interface"]?.nilIfUnavailable,
                processCount: values.int("process_count"),
                activeUsers: (values["active_users"] ?? "")
                    .split(whereSeparator: \.isWhitespace)
                    .map(String.init),
                loginSessionCount: values.int("login_sessions"),
                lastLogin: values["last_login"]?.nilIfUnavailable,
                firmwareUpdateCount: values.int("firmware_update_count"),
                containers: Self.parseContainers(values["containers"])
            ),
            metrics: MemberMetrics(
                gpu: gpu,
                cpu: CPUMetrics(
                    utilizationPercent: cpuUsage,
                    temperatureCelsius: values.double("cpu_temp_millic").map { $0 / 1_000 },
                    averageFrequencyMHz: values.double("cpu_frequency_khz").map { $0 / 1_000 },
                    loadAverage1Minute: loadFields.double(at: 0),
                    loadAverage5Minutes: loadFields.double(at: 1),
                    loadAverage15Minutes: loadFields.double(at: 2),
                    pressureAverage10Seconds: values.pressureAverage10("psi_cpu"),
                    units: cpuUnits
                ),
                memory: MemoryMetrics(
                    usedBytes: memoryUsed,
                    totalBytes: memoryTotal,
                    availableBytes: memoryAvailable,
                    utilizationPercent: memoryPercent,
                    cachedBytes: values.double("mem_cached_kb").map { $0 * 1_024 },
                    swapUsedBytes: Self.subtract(swapTotal, swapFree),
                    swapTotalBytes: swapTotal,
                    pressureAverage10Seconds: values.pressureAverage10("psi_memory")
                ),
                storage: StorageMetrics(
                    usedBytes: storageUsed,
                    totalBytes: storageTotal,
                    availableBytes: storageAvailable,
                    utilizationPercent: Self.percentage(used: storageUsed, total: storageTotal),
                    temperatureCelsius: values.double("nvme_temp_millic").map { $0 / 1_000 },
                    readBytesPerSecond: Self.rate(
                        current: diskReadBytes,
                        previous: previous?.diskReadBytes,
                        elapsed: elapsed
                    ),
                    writeBytesPerSecond: Self.rate(
                        current: diskWriteBytes,
                        previous: previous?.diskWriteBytes,
                        elapsed: elapsed
                    ),
                    pressureAverage10Seconds: values.pressureAverage10("psi_io")
                ),
                network: NetworkMetrics(
                    receiveBytesPerSecond: Self.rate(
                        current: receivedBytes,
                        previous: previous?.receivedBytes,
                        elapsed: elapsed
                    ),
                    transmitBytesPerSecond: Self.rate(
                        current: transmittedBytes,
                        previous: previous?.transmittedBytes,
                        elapsed: elapsed
                    ),
                    receivedPackets: values.double("net_rx_packets"),
                    transmittedPackets: values.double("net_tx_packets"),
                    receiveErrors: values.double("net_rx_errors"),
                    transmitErrors: values.double("net_tx_errors"),
                    receiveDrops: values.double("net_rx_drops"),
                    transmitDrops: values.double("net_tx_drops")
                )
            )
        )
    }

    private static func parse(_ output: String) -> [String: String] {
        output.split(separator: "\n").reduce(into: [:]) { result, line in
            let fields = line.split(separator: "\t", maxSplits: 1, omittingEmptySubsequences: false)
            guard fields.count == 2 else { return }
            result[String(fields[0])] = String(fields[1])
        }
    }

    private static func parseContainers(_ value: String?) -> [ContainerInfo] {
        guard let value, !value.isEmpty else { return [] }
        return value.components(separatedBy: ";;").compactMap { record in
            let fields = record.split(separator: "|", maxSplits: 2, omittingEmptySubsequences: false)
            guard let name = fields[safe: 0].map(String.init), !name.isEmpty else { return nil }
            return ContainerInfo(
                name: name,
                image: fields[safe: 1].map(String.init)?.nilIfUnavailable,
                status: fields[safe: 2].map(String.init)?.nilIfUnavailable
            )
        }
    }

    private static func parseNetworkAddresses(_ value: String?) -> [NetworkAddress] {
        guard let value, !value.isEmpty else { return [] }
        return value.components(separatedBy: ";;").compactMap { record in
            let fields = record.split(separator: "|", maxSplits: 2, omittingEmptySubsequences: false)
            guard
                let interface = fields[safe: 0].map(String.init),
                let family = fields[safe: 1].map(String.init),
                let address = fields[safe: 2].map(String.init),
                !interface.isEmpty,
                !address.isEmpty
            else { return nil }
            return NetworkAddress(interface: interface, family: family, address: address)
        }
    }

    private static func parseCPUCoreCounters(_ value: String?) -> [CPUCoreCounter] {
        guard let value, !value.isEmpty else { return [] }
        return value.components(separatedBy: ";;").compactMap { record in
            let fields = record.split(separator: "|", maxSplits: 2, omittingEmptySubsequences: false)
            guard
                let id = fields[safe: 0].map(String.init),
                let total = fields[safe: 1].flatMap({ Double($0) }),
                let idle = fields[safe: 2].flatMap({ Double($0) })
            else { return nil }
            return CPUCoreCounter(id: id, total: total, idle: idle)
        }
    }

    private static func cpuUnits(
        current: [CPUCoreCounter],
        previous: [CPUCoreCounter]?
    ) -> [UtilizationUnit] {
        let previousByID = Dictionary(uniqueKeysWithValues: (previous ?? []).map { ($0.id, $0) })
        return current.map { core in
            let utilization = previousByID[core.id].flatMap { old -> Double? in
                let totalDelta = core.total - old.total
                let idleDelta = core.idle - old.idle
                guard totalDelta > 0 else { return nil }
                return max(0, min(100, (totalDelta - idleDelta) / totalDelta * 100))
            }
            let number = core.id.drop(while: { !$0.isNumber })
            return UtilizationUnit(
                id: core.id,
                name: number.isEmpty ? core.id : "Core \(number)",
                utilizationPercent: utilization
            )
        }
    }

    private static func parseGPUUnits(_ value: String?) -> [UtilizationUnit] {
        let definitions = [
            ("sm", "SM"),
            ("memory", "Memory"),
            ("encoder", "Encoder"),
            ("decoder", "Decoder"),
            ("jpeg", "JPEG"),
            ("ofa", "OFA")
        ]
        let fields = (value ?? "")
            .split(separator: "|", omittingEmptySubsequences: false)
            .map(String.init)
        return definitions.enumerated().map { index, definition in
            UtilizationUnit(
                id: definition.0,
                name: definition.1,
                utilizationPercent: fields[safe: index]?.nilIfUnavailable.flatMap(Double.init)
            )
        }
    }

    private static func throttleActive(_ values: [String]) -> Bool? {
        guard !values.isEmpty else { return nil }
        return values.contains { $0.caseInsensitiveCompare("Active") == .orderedSame }
    }

    private static func enabled(_ value: String?) -> Bool? {
        guard let value = value?.nilIfUnavailable else { return nil }
        if value.caseInsensitiveCompare("Enabled") == .orderedSame { return true }
        if value.caseInsensitiveCompare("Disabled") == .orderedSame { return false }
        return nil
    }

    private static func subtract(_ lhs: Double?, _ rhs: Double?) -> Double? {
        guard let lhs, let rhs else { return nil }
        return max(0, lhs - rhs)
    }

    private static func percentage(used: Double?, total: Double?) -> Double? {
        guard let used, let total, total > 0 else { return nil }
        return max(0, min(100, used / total * 100))
    }

    private static func rate(current: Double, previous: Double?, elapsed: Double?) -> Double? {
        guard let previous, let elapsed, elapsed > 0 else { return nil }
        return max(0, (current - previous) / elapsed)
    }

    private static let probeCommand = #"""
set +e
emit() { printf '%s\t%s\n' "$1" "$2"; }
read_dmi() { cat "/sys/class/dmi/id/$1" 2>/dev/null; }
[ -r /etc/dgx-release ] && . /etc/dgx-release
emit timestamp "$(date +%s)"
emit hostname "$(hostname 2>/dev/null)"
emit architecture "$(uname -m 2>/dev/null)"
emit kernel "$(uname -r 2>/dev/null)"
emit operating_system "$(. /etc/os-release 2>/dev/null; printf '%s' "$PRETTY_NAME")"
emit vendor "$(read_dmi sys_vendor)"
emit product "$(read_dmi product_name)"
emit product_version "$(read_dmi product_version)"
emit product_serial "$(read_dmi product_serial)"
emit product_uuid "$(read_dmi product_uuid)"
emit dgx_name "$DGX_PRETTY_NAME"
emit dgx_serial "$DGX_SERIAL_NUMBER"
emit dgx_ota_version "$DGX_OTA_VERSION"
emit dgx_ota_date "$DGX_OTA_DATE"
emit dgx_build_version "$DGX_SWBUILD_VERSION"
emit dgx_build_date "$DGX_SWBUILD_DATE"
emit dgx_commit_id "$DGX_COMMIT_ID"
emit dgx_platform "$DGX_PLATFORM"
if [ -r /sys/class/dmi/id/product_serial ]; then emit dmi_serial_access readable; elif [ -e /sys/class/dmi/id/product_serial ]; then emit dmi_serial_access restricted; else emit dmi_serial_access unavailable; fi
emit machine_id_hash "$(sha256sum /etc/machine-id 2>/dev/null | awk '{print $1}')"
emit board_vendor "$(read_dmi board_vendor)"
emit board_name "$(read_dmi board_name)"
emit board_version "$(read_dmi board_version)"
emit board_serial "$(read_dmi board_serial)"
emit chassis_vendor "$(read_dmi chassis_vendor)"
emit chassis_type "$(read_dmi chassis_type)"
emit chassis_serial "$(read_dmi chassis_serial)"
emit bios_vendor "$(read_dmi bios_vendor)"
emit bios_version "$(read_dmi bios_version)"
emit bios_date "$(read_dmi bios_date)"
emit cpu_model "$(lscpu 2>/dev/null | awk -F: '/^Model name:/ {sub(/^ +/,"",$2); if(!seen[$2]++){if(n++) printf " / "; printf "%s",$2}}')"
emit cpu_count "$(nproc 2>/dev/null)"
emit cpu_frequency_khz "$(awk '{s+=$1;n++} END {if(n) printf "%.0f",s/n}' /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq 2>/dev/null)"
emit uptime "$(awk '{print $1}' /proc/uptime 2>/dev/null)"
emit load_average "$(awk '{print $1, $2, $3}' /proc/loadavg 2>/dev/null)"
emit mem_total_kb "$(awk '/^MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null)"
emit mem_available_kb "$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo 2>/dev/null)"
emit mem_cached_kb "$(awk '/^Cached:/ {print $2}' /proc/meminfo 2>/dev/null)"
emit swap_total_kb "$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo 2>/dev/null)"
emit swap_free_kb "$(awk '/^SwapFree:/ {print $2}' /proc/meminfo 2>/dev/null)"
emit psi_cpu "$(head -n1 /proc/pressure/cpu 2>/dev/null)"
emit psi_memory "$(head -n1 /proc/pressure/memory 2>/dev/null)"
emit psi_io "$(head -n1 /proc/pressure/io 2>/dev/null)"
emit cpu_total "$(awk '/^cpu / {t=0; for(i=2;i<=NF;i++) t+=$i; print t; exit}' /proc/stat 2>/dev/null)"
emit cpu_idle "$(awk '/^cpu / {print $5+$6; exit}' /proc/stat 2>/dev/null)"
emit cpu_cores "$(awk '/^cpu[0-9]+ / {t=0; for(i=2;i<=NF;i++) t+=$i; if(n++) printf ";;"; printf "%s|%.0f|%.0f",$1,t,$5+$6}' /proc/stat 2>/dev/null)"
emit cpu_temp_millic "$(for f in /sys/class/thermal/thermal_zone*/temp; do cat "$f" 2>/dev/null; done | sort -nr | head -n1)"
controller="$(find /sys/class/nvme -maxdepth 1 -type l -name 'nvme[0-9]*' 2>/dev/null | sort | head -n1)"
emit nvme_model "$(cat "$controller/model" 2>/dev/null)"
emit nvme_serial "$(cat "$controller/serial" 2>/dev/null)"
emit nvme_firmware "$(cat "$controller/firmware_rev" 2>/dev/null)"
emit nvme_temp_millic "$(for h in /sys/class/hwmon/hwmon*; do [ "$(cat "$h/name" 2>/dev/null)" = nvme ] && cat "$h/temp1_input" 2>/dev/null; done | sort -nr | head -n1)"
emit root_disk_kb "$(df -Pk / 2>/dev/null | awk 'NR==2 {print $2, $3, $4}')"
emit disk_read_bytes "$(awk '$3 ~ /^nvme[0-9]+n[0-9]+$|^sd[a-z]+$|^vd[a-z]+$|^mmcblk[0-9]+$/ {n+=$6} END{printf "%.0f",n*512}' /proc/diskstats 2>/dev/null)"
emit disk_write_bytes "$(awk '$3 ~ /^nvme[0-9]+n[0-9]+$|^sd[a-z]+$|^vd[a-z]+$|^mmcblk[0-9]+$/ {n+=$10} END{printf "%.0f",n*512}' /proc/diskstats 2>/dev/null)"
emit net_rx "$(awk -F: 'NR>2 {i=$1; gsub(/ /,"",i); if(i!="lo"){gsub(/^ +/,"",$2); split($2,a,/ +/); n+=a[1]}} END{print n+0}' /proc/net/dev 2>/dev/null)"
emit net_rx_packets "$(awk -F: 'NR>2 {i=$1; gsub(/ /,"",i); if(i!="lo"){gsub(/^ +/,"",$2); split($2,a,/ +/); n+=a[2]}} END{print n+0}' /proc/net/dev 2>/dev/null)"
emit net_rx_errors "$(awk -F: 'NR>2 {i=$1; gsub(/ /,"",i); if(i!="lo"){gsub(/^ +/,"",$2); split($2,a,/ +/); n+=a[3]}} END{print n+0}' /proc/net/dev 2>/dev/null)"
emit net_rx_drops "$(awk -F: 'NR>2 {i=$1; gsub(/ /,"",i); if(i!="lo"){gsub(/^ +/,"",$2); split($2,a,/ +/); n+=a[4]}} END{print n+0}' /proc/net/dev 2>/dev/null)"
emit net_tx "$(awk -F: 'NR>2 {i=$1; gsub(/ /,"",i); if(i!="lo"){gsub(/^ +/,"",$2); split($2,a,/ +/); n+=a[9]}} END{print n+0}' /proc/net/dev 2>/dev/null)"
emit net_tx_packets "$(awk -F: 'NR>2 {i=$1; gsub(/ /,"",i); if(i!="lo"){gsub(/^ +/,"",$2); split($2,a,/ +/); n+=a[10]}} END{print n+0}' /proc/net/dev 2>/dev/null)"
emit net_tx_errors "$(awk -F: 'NR>2 {i=$1; gsub(/ /,"",i); if(i!="lo"){gsub(/^ +/,"",$2); split($2,a,/ +/); n+=a[11]}} END{print n+0}' /proc/net/dev 2>/dev/null)"
emit net_tx_drops "$(awk -F: 'NR>2 {i=$1; gsub(/ /,"",i); if(i!="lo"){gsub(/^ +/,"",$2); split($2,a,/ +/); n+=a[12]}} END{print n+0}' /proc/net/dev 2>/dev/null)"
emit default_interface "$(ip route show default 2>/dev/null | awk 'NR==1 {print $5}')"
emit network_addresses "$(ip -o addr show scope global 2>/dev/null | awk '{if(n++) printf ";;"; printf "%s|%s|%s",$2,$3,$4}')"
emit process_count "$(find /proc -maxdepth 1 -type d -name '[0-9]*' 2>/dev/null | wc -l)"
emit active_users "$(who 2>/dev/null | awk '{print $1}' | sort -u | paste -sd ' ' -)"
emit login_sessions "$(who 2>/dev/null | wc -l)"
emit last_login "$(last -n 1 -w 2>/dev/null | head -n1 | tr '\t' ' ')"
emit firmware_update_count "$(awk '$1 ~ /^[0-9]+$/ {print $1; exit}' /run/motd.d/85-fwupd 2>/dev/null)"
emit containers "$(docker ps -a --format '{{.Names}}|{{.Image}}|{{.Status}}' 2>/dev/null | awk 'BEGIN{first=1} {gsub(/\t/," "); if(!first) printf ";;"; printf "%s",$0; first=0}')"
emit gpu "$(nvidia-smi --query-gpu=name,uuid,driver_version,temperature.gpu,utilization.gpu,utilization.memory,power.draw,power.limit,clocks.current.graphics,clocks.current.sm,clocks.current.memory,clocks.max.sm,pstate,compute_mode,display_active,pcie.link.gen.current,pcie.link.width.current,clocks_throttle_reasons.hw_thermal_slowdown,clocks_throttle_reasons.sw_thermal_slowdown,clocks_throttle_reasons.hw_slowdown,clocks_throttle_reasons.sw_power_cap --format=csv,noheader,nounits 2>/dev/null | head -n1)"
emit gpu_engines "$(nvidia-smi dmon -s u -c 1 2>/dev/null | awk '$1 ~ /^[0-9]+$/ {printf "%s|%s|%s|%s|%s|%s",$2,$3,$4,$5,$6,$7; exit}')"
"""#
}

private extension Dictionary where Key == String, Value == String {
    func double(_ key: String) -> Double? {
        self[key]?.nilIfUnavailable.flatMap(Double.init)
    }

    func int(_ key: String) -> Int? {
        self[key]?.nilIfUnavailable.flatMap(Int.init)
    }

    func pressureAverage10(_ key: String) -> Double? {
        guard let value = self[key] else { return nil }
        return value.split(separator: " ")
            .first { $0.hasPrefix("avg10=") }
            .flatMap { Double($0.dropFirst("avg10=".count)) }
    }
}

private extension Collection where Element == String, Index == Int {
    func double(at index: Int) -> Double? {
        self[safe: index]?.nilIfUnavailable.flatMap(Double.init)
    }

    func int(at index: Int) -> Int? {
        self[safe: index]?.nilIfUnavailable.flatMap(Int.init)
    }
}

private extension Collection {
    subscript(safe index: Index) -> Element? {
        indices.contains(index) ? self[index] : nil
    }
}

private extension String {
    var nilIfUnavailable: String? {
        let value = trimmingCharacters(in: .whitespacesAndNewlines)
        guard
            !value.isEmpty,
            value != "[N/A]",
            value.lowercased() != "n/a",
            value.lowercased() != "default string",
            value.lowercased() != "to be filled by o.e.m."
        else { return nil }
        return value
    }
}
