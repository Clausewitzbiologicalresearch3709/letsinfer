#include "watchdog/sampler.h"

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/statvfs.h>
#include <time.h>
#include <unistd.h>

static int read_file(const char *path, char *buffer, size_t capacity, size_t *length) {
    if (capacity == 0) return -1;
    const int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    size_t used = 0;
    while (used + 1u < capacity) {
        const ssize_t count = read(fd, buffer + used, capacity - used - 1u);
        if (count == 0) break;
        if (count < 0) {
            if (errno == EINTR) continue;
            close(fd);
            return -1;
        }
        used += (size_t)count;
    }
    close(fd);
    buffer[used] = '\0';
    if (length != NULL) *length = used;
    return 0;
}

static uint64_t milliseconds(clockid_t clock) {
    struct timespec value;
    if (clock_gettime(clock, &value) != 0) return 0;
    return (uint64_t)value.tv_sec * 1000u + (uint64_t)value.tv_nsec / 1000000u;
}

static uint8_t percentage(uint64_t used, uint64_t total) {
    if (total == 0) return WATCHDOG_PERCENT_UNKNOWN;
    const uint64_t value = (used * 100u + total / 2u) / total;
    return value > 100u ? 100u : (uint8_t)value;
}

static uint32_t saturating_u32(uint64_t value) {
    return value > UINT32_MAX ? UINT32_MAX : (uint32_t)value;
}

static bool parse_cpu_counter(const char *line, watchdog_cpu_counter *counter) {
    char name[16];
    unsigned long long fields[10] = {0};
    const int count = sscanf(
        line,
        "%15s %llu %llu %llu %llu %llu %llu %llu %llu %llu %llu",
        name,
        &fields[0], &fields[1], &fields[2], &fields[3], &fields[4],
        &fields[5], &fields[6], &fields[7], &fields[8], &fields[9]
    );
    if (count < 5) return false;
    uint64_t total = 0;
    for (int index = 0; index < count - 1; ++index) total += fields[index];
    counter->total = total;
    counter->idle = fields[3] + (count > 5 ? fields[4] : 0);
    return true;
}

static uint8_t counter_usage(
    const watchdog_cpu_counter *current,
    const watchdog_cpu_counter *previous,
    bool has_baseline
) {
    if (!has_baseline || current->total <= previous->total) return WATCHDOG_PERCENT_UNKNOWN;
    const uint64_t total = current->total - previous->total;
    const uint64_t idle = current->idle >= previous->idle ? current->idle - previous->idle : 0;
    return percentage(total > idle ? total - idle : 0, total);
}

static int sample_cpu(watchdog_sampler *sampler, watchdog_sample *sample) {
    char buffer[16384];
    if (read_file("/proc/stat", buffer, sizeof(buffer), NULL) != 0) return -1;
    watchdog_cpu_counter aggregate = {0};
    watchdog_cpu_counter cores[WATCHDOG_MAX_CPU_CORES] = {{0}};
    uint8_t core_count = 0;
    char *save = NULL;
    for (char *line = strtok_r(buffer, "\n", &save); line != NULL; line = strtok_r(NULL, "\n", &save)) {
        if (strncmp(line, "cpu ", 4) == 0) {
            parse_cpu_counter(line, &aggregate);
            continue;
        }
        if (strncmp(line, "cpu", 3) != 0 || !isdigit((unsigned char)line[3])) continue;
        if (core_count < WATCHDOG_MAX_CPU_CORES && parse_cpu_counter(line, &cores[core_count])) {
            sample->cpu_core_percent[core_count] = counter_usage(
                &cores[core_count],
                &sampler->cores[core_count],
                sampler->has_baseline && core_count < sampler->core_count
            );
            ++core_count;
        }
    }
    sample->cpu_core_count = core_count;
    sample->cpu_percent = counter_usage(&aggregate, &sampler->cpu, sampler->has_baseline);
    sampler->cpu = aggregate;
    memcpy(sampler->cores, cores, sizeof(cores));
    sampler->core_count = core_count;

    DIR *frequency_root = opendir("/sys/devices/system/cpu/cpufreq");
    if (frequency_root != NULL) {
        uint64_t maximum_khz = 0;
        struct dirent *entry = NULL;
        while ((entry = readdir(frequency_root)) != NULL) {
            if (strncmp(entry->d_name, "policy", 6) != 0) continue;
            char path[PATH_MAX];
            const int length = snprintf(
                path,
                sizeof(path),
                "/sys/devices/system/cpu/cpufreq/%s/scaling_cur_freq",
                entry->d_name
            );
            if (length < 0 || (size_t)length >= sizeof(path)) continue;
            char frequency[64];
            if (read_file(path, frequency, sizeof(frequency), NULL) != 0) continue;
            const uint64_t khz = strtoull(frequency, NULL, 10);
            if (khz > maximum_khz) maximum_khz = khz;
        }
        closedir(frequency_root);
        if (maximum_khz > 0) {
            sample->cpu_clock_mhz = saturating_u32((maximum_khz + 500u) / 1000u);
        }
    }
    return 0;
}

static uint64_t meminfo_value(const char *buffer, const char *key) {
    const char *position = strstr(buffer, key);
    if (position == NULL || (position != buffer && position[-1] != '\n')) return 0;
    position += strlen(key);
    while (*position == ' ' || *position == '\t' || *position == ':') ++position;
    return strtoull(position, NULL, 10);
}

static void sample_memory(watchdog_sample *sample) {
    char buffer[8192];
    if (read_file("/proc/meminfo", buffer, sizeof(buffer), NULL) != 0) return;
    const uint64_t total_kib = meminfo_value(buffer, "MemTotal");
    const uint64_t available_kib = meminfo_value(buffer, "MemAvailable");
    const uint64_t used_kib = total_kib > available_kib ? total_kib - available_kib : 0;
    sample->memory_percent = percentage(used_kib, total_kib);
    sample->memory_used_mib = saturating_u32(used_kib / 1024u);
    sample->memory_total_mib = saturating_u32(total_kib / 1024u);
}

static void sample_load(watchdog_sample *sample) {
    char buffer[128];
    if (read_file("/proc/loadavg", buffer, sizeof(buffer), NULL) != 0) return;
    double load = 0;
    if (sscanf(buffer, "%lf", &load) == 1 && load >= 0) {
        const double centi = load * 100.0;
        sample->load1_centi = centi > UINT16_MAX ? UINT16_MAX : (uint16_t)(centi + 0.5);
    }
}

static void sample_storage(watchdog_sample *sample) {
    struct statvfs value;
    if (statvfs("/", &value) != 0 || value.f_blocks == 0) return;
    const uint64_t total = (uint64_t)value.f_blocks * value.f_frsize;
    const uint64_t available = (uint64_t)value.f_bavail * value.f_frsize;
    const uint64_t used = total > available ? total - available : 0;
    sample->disk_percent = percentage(used, total);
    sample->disk_used_mib = saturating_u32(used / (1024u * 1024u));
    sample->disk_total_mib = saturating_u32(total / (1024u * 1024u));
}

static bool physical_disk(const char *name) {
    if (strncmp(name, "nvme", 4) == 0) return strchr(name, 'p') == NULL;
    if (strncmp(name, "mmcblk", 6) == 0) return strchr(name, 'p') == NULL;
    if ((strncmp(name, "sd", 2) == 0 || strncmp(name, "vd", 2) == 0)
        && strlen(name) == 3 && isalpha((unsigned char)name[2])) return true;
    return false;
}

static void disk_counters(uint64_t *read_bytes, uint64_t *write_bytes) {
    char buffer[32768];
    *read_bytes = 0;
    *write_bytes = 0;
    if (read_file("/proc/diskstats", buffer, sizeof(buffer), NULL) != 0) return;
    char *save = NULL;
    for (char *line = strtok_r(buffer, "\n", &save); line != NULL; line = strtok_r(NULL, "\n", &save)) {
        unsigned major = 0;
        unsigned minor = 0;
        char name[64];
        unsigned long long reads = 0;
        unsigned long long sectors_read = 0;
        unsigned long long writes = 0;
        unsigned long long sectors_written = 0;
        const int count = sscanf(
            line,
            "%u %u %63s %llu %*u %llu %*u %llu %*u %llu",
            &major, &minor, name, &reads, &sectors_read, &writes, &sectors_written
        );
        (void)major;
        (void)minor;
        (void)reads;
        (void)writes;
        if (count == 7 && physical_disk(name)) {
            *read_bytes += (uint64_t)sectors_read * 512u;
            *write_bytes += (uint64_t)sectors_written * 512u;
        }
    }
}

static void network_counters(uint64_t *received, uint64_t *transmitted) {
    char buffer[16384];
    *received = 0;
    *transmitted = 0;
    if (read_file("/proc/net/dev", buffer, sizeof(buffer), NULL) != 0) return;
    char *save = NULL;
    for (char *line = strtok_r(buffer, "\n", &save); line != NULL; line = strtok_r(NULL, "\n", &save)) {
        char interface[64];
        unsigned long long rx = 0;
        unsigned long long tx = 0;
        const int count = sscanf(
            line,
            " %63[^:]: %llu %*u %*u %*u %*u %*u %*u %*u %llu",
            interface, &rx, &tx
        );
        if (count == 3 && strcmp(interface, "lo") != 0) {
            *received += (uint64_t)rx;
            *transmitted += (uint64_t)tx;
        }
    }
}

static int16_t highest_temperature(const char *root, bool require_nvme_name) {
    DIR *directory = opendir(root);
    if (directory == NULL) return WATCHDOG_TEMP_UNKNOWN;
    long highest = LONG_MIN;
    struct dirent *entry;
    while ((entry = readdir(directory)) != NULL) {
        if (entry->d_name[0] == '.') continue;
        char path[PATH_MAX];
        if (require_nvme_name) {
            snprintf(path, sizeof(path), "%s/%s/name", root, entry->d_name);
            char name[32];
            if (read_file(path, name, sizeof(name), NULL) != 0
                || strncmp(name, "nvme", 4) != 0) continue;
            snprintf(path, sizeof(path), "%s/%s/temp1_input", root, entry->d_name);
        } else {
            snprintf(path, sizeof(path), "%s/%s/temp", root, entry->d_name);
        }
        char value[32];
        if (read_file(path, value, sizeof(value), NULL) != 0) continue;
        const long millicelsius = strtol(value, NULL, 10);
        if (millicelsius > highest) highest = millicelsius;
    }
    closedir(directory);
    if (highest == LONG_MIN || highest < -100000 || highest > 250000) return WATCHDOG_TEMP_UNKNOWN;
    const long decicelsius = highest / 100;
    if (decicelsius < INT16_MIN || decicelsius > INT16_MAX) return WATCHDOG_TEMP_UNKNOWN;
    return (int16_t)decicelsius;
}

static uint32_t rate_kib(
    uint64_t current,
    uint64_t previous,
    uint64_t elapsed_ms,
    bool has_baseline
) {
    if (!has_baseline || elapsed_ms == 0 || current < previous) return 0;
    return saturating_u32(((current - previous) * 1000u) / elapsed_ms / 1024u);
}

int watchdog_sampler_open(watchdog_sampler *sampler) {
    if (sampler == NULL) return -1;
    memset(sampler, 0, sizeof(*sampler));
    return watchdog_nvml_open(&sampler->nvml);
}

void watchdog_sampler_close(watchdog_sampler *sampler) {
    if (sampler == NULL) return;
    watchdog_nvml_close(&sampler->nvml);
    memset(sampler, 0, sizeof(*sampler));
}

int watchdog_sampler_take(
    watchdog_sampler *sampler,
    uint64_t sequence,
    watchdog_sample *sample
) {
    if (sampler == NULL || sample == NULL) return -1;
    watchdog_sample_init(sample);
    sample->sequence = sequence;
    sample->unix_ms = milliseconds(CLOCK_REALTIME);
    sample->monotonic_ms = milliseconds(CLOCK_MONOTONIC);
    if (sample->unix_ms == 0 || sample->monotonic_ms == 0) return -1;

    const uint64_t elapsed = sampler->has_baseline
        ? sample->monotonic_ms - sampler->sampled_monotonic_ms
        : 0;
    if (sample_cpu(sampler, sample) != 0) return -1;
    sample_memory(sample);
    sample_load(sample);
    sample_storage(sample);

    uint64_t disk_read = 0;
    uint64_t disk_write = 0;
    uint64_t network_rx = 0;
    uint64_t network_tx = 0;
    disk_counters(&disk_read, &disk_write);
    network_counters(&network_rx, &network_tx);
    sample->disk_read_kib_s = rate_kib(disk_read, sampler->disk_read_bytes, elapsed, sampler->has_baseline);
    sample->disk_write_kib_s = rate_kib(disk_write, sampler->disk_write_bytes, elapsed, sampler->has_baseline);
    sample->network_rx_kib_s = rate_kib(network_rx, sampler->network_rx_bytes, elapsed, sampler->has_baseline);
    sample->network_tx_kib_s = rate_kib(network_tx, sampler->network_tx_bytes, elapsed, sampler->has_baseline);
    sampler->disk_read_bytes = disk_read;
    sampler->disk_write_bytes = disk_write;
    sampler->network_rx_bytes = network_rx;
    sampler->network_tx_bytes = network_tx;

    sample->system_temp_deci_c = highest_temperature("/sys/class/thermal", false);
    sample->nvme_temp_deci_c = highest_temperature("/sys/class/hwmon", true);
    watchdog_nvml_sample(&sampler->nvml, sample);
    sampler->sampled_monotonic_ms = sample->monotonic_ms;
    sampler->has_baseline = true;
    return 0;
}
