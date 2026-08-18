#ifndef WATCHDOG_NVML_H
#define WATCHDOG_NVML_H

#include "watchdog/record.h"

#include <stdbool.h>
#include <stdint.h>

#define WATCHDOG_MAX_GPUS 16u

typedef struct watchdog_nvml {
    void *library;
    void *devices[WATCHDOG_MAX_GPUS];
    void *functions[13];
    uint32_t device_count;
    bool initialized;
    bool available;
} watchdog_nvml;

int watchdog_nvml_open(watchdog_nvml *nvml);
void watchdog_nvml_close(watchdog_nvml *nvml);
void watchdog_nvml_sample(watchdog_nvml *nvml, watchdog_sample *sample);
uint32_t watchdog_nvml_device_count(const watchdog_nvml *nvml);

#endif
