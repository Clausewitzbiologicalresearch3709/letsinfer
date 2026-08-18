#ifndef WATCHDOG_SAMPLER_H
#define WATCHDOG_SAMPLER_H

#include "watchdog/nvml.h"
#include "watchdog/record.h"

#include <stdbool.h>
#include <stdint.h>

typedef struct watchdog_cpu_counter {
    uint64_t total;
    uint64_t idle;
} watchdog_cpu_counter;

typedef struct watchdog_sampler {
    watchdog_nvml nvml;
    watchdog_cpu_counter cpu;
    watchdog_cpu_counter cores[WATCHDOG_MAX_CPU_CORES];
    uint8_t core_count;
    uint64_t network_rx_bytes;
    uint64_t network_tx_bytes;
    uint64_t disk_read_bytes;
    uint64_t disk_write_bytes;
    uint64_t sampled_monotonic_ms;
    bool has_baseline;
} watchdog_sampler;

int watchdog_sampler_open(watchdog_sampler *sampler);
void watchdog_sampler_close(watchdog_sampler *sampler);
int watchdog_sampler_take(
    watchdog_sampler *sampler,
    uint64_t sequence,
    watchdog_sample *sample
);

#endif
