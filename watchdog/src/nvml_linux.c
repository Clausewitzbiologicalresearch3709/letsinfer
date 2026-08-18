#include "watchdog/nvml.h"

#include <dlfcn.h>
#include <stdint.h>
#include <string.h>

typedef int nvml_return;
typedef void *nvml_device;

typedef struct nvml_utilization {
    unsigned gpu;
    unsigned memory;
} nvml_utilization;

typedef nvml_return (*fn_init)(void);
typedef nvml_return (*fn_shutdown)(void);
typedef nvml_return (*fn_get_count)(unsigned *);
typedef nvml_return (*fn_get_handle)(unsigned, nvml_device *);
typedef nvml_return (*fn_get_utilization)(nvml_device, nvml_utilization *);
typedef nvml_return (*fn_get_temperature)(nvml_device, unsigned, unsigned *);
typedef nvml_return (*fn_get_power)(nvml_device, unsigned *);
typedef nvml_return (*fn_get_engine)(nvml_device, unsigned *, unsigned *);
typedef nvml_return (*fn_get_throttle)(nvml_device, unsigned long long *);
typedef nvml_return (*fn_get_clock)(nvml_device, unsigned, unsigned *);

enum function_index {
    FN_SHUTDOWN,
    FN_UTILIZATION,
    FN_TEMPERATURE,
    FN_POWER,
    FN_ENCODER,
    FN_DECODER,
    FN_JPEG,
    FN_OFA,
    FN_THROTTLE,
    FN_CLOCK
};

static bool load_symbol(void *library, const char *name, void **target) {
    *target = dlsym(library, name);
    return *target != NULL;
}

static void copy_function(void *source, void *target, size_t size) {
    memcpy(target, &source, size);
}

#define FUNCTION(nvml, index, type, variable) \
    type variable = NULL; copy_function((nvml)->functions[(index)], &variable, sizeof(variable))

int watchdog_nvml_open(watchdog_nvml *nvml) {
    if (nvml == NULL) return -1;
    memset(nvml, 0, sizeof(*nvml));
    nvml->library = dlopen("libnvidia-ml.so.1", RTLD_NOW | RTLD_LOCAL);
    if (nvml->library == NULL) return 0;

    void *init_address = NULL;
    void *count_address = NULL;
    void *handle_address = NULL;
    if (!load_symbol(nvml->library, "nvmlInit_v2", &init_address)
        || !load_symbol(nvml->library, "nvmlDeviceGetCount_v2", &count_address)
        || !load_symbol(nvml->library, "nvmlDeviceGetHandleByIndex_v2", &handle_address)) {
        watchdog_nvml_close(nvml);
        return 0;
    }
    fn_init initialize = NULL;
    fn_get_count get_count = NULL;
    fn_get_handle get_handle = NULL;
    copy_function(init_address, &initialize, sizeof(initialize));
    copy_function(count_address, &get_count, sizeof(get_count));
    copy_function(handle_address, &get_handle, sizeof(get_handle));
    load_symbol(nvml->library, "nvmlShutdown", &nvml->functions[FN_SHUTDOWN]);
    if (initialize() != 0) {
        watchdog_nvml_close(nvml);
        return 0;
    }
    nvml->initialized = true;
    unsigned device_count = 0;
    if (get_count(&device_count) != 0 || device_count == 0
        || device_count > WATCHDOG_MAX_GPUS) {
        watchdog_nvml_close(nvml);
        return 0;
    }
    for (unsigned index = 0; index < device_count; ++index) {
        if (get_handle(index, (nvml_device *)&nvml->devices[index]) != 0) {
            watchdog_nvml_close(nvml);
            return 0;
        }
    }
    nvml->device_count = device_count;

    load_symbol(nvml->library, "nvmlDeviceGetUtilizationRates", &nvml->functions[FN_UTILIZATION]);
    load_symbol(nvml->library, "nvmlDeviceGetTemperature", &nvml->functions[FN_TEMPERATURE]);
    load_symbol(nvml->library, "nvmlDeviceGetPowerUsage", &nvml->functions[FN_POWER]);
    load_symbol(nvml->library, "nvmlDeviceGetEncoderUtilization", &nvml->functions[FN_ENCODER]);
    load_symbol(nvml->library, "nvmlDeviceGetDecoderUtilization", &nvml->functions[FN_DECODER]);
    load_symbol(nvml->library, "nvmlDeviceGetJpgUtilization", &nvml->functions[FN_JPEG]);
    load_symbol(nvml->library, "nvmlDeviceGetOfaUtilization", &nvml->functions[FN_OFA]);
    load_symbol(nvml->library, "nvmlDeviceGetCurrentClocksThrottleReasons", &nvml->functions[FN_THROTTLE]);
    load_symbol(nvml->library, "nvmlDeviceGetClockInfo", &nvml->functions[FN_CLOCK]);
    nvml->available = true;
    return 0;
}

void watchdog_nvml_close(watchdog_nvml *nvml) {
    if (nvml == NULL) return;
    if (nvml->initialized && nvml->functions[FN_SHUTDOWN] != NULL) {
        FUNCTION(nvml, FN_SHUTDOWN, fn_shutdown, shutdown_nvml);
        shutdown_nvml();
    }
    if (nvml->library != NULL) dlclose(nvml->library);
    memset(nvml, 0, sizeof(*nvml));
}

static uint8_t percent(unsigned value) {
    return value <= 100u ? (uint8_t)value : WATCHDOG_PERCENT_UNKNOWN;
}

static void retain_max_percent(uint8_t *current, unsigned value) {
    const uint8_t candidate = percent(value);
    if (candidate != WATCHDOG_PERCENT_UNKNOWN
        && (*current == WATCHDOG_PERCENT_UNKNOWN || candidate > *current)) {
        *current = candidate;
    }
}

static void sample_engine(
    watchdog_nvml *nvml,
    nvml_device device,
    enum function_index index,
    enum watchdog_gpu_engine engine,
    watchdog_sample *sample
) {
    if (nvml->functions[index] == NULL) return;
    FUNCTION(nvml, index, fn_get_engine, get_engine);
    unsigned utilization = 0;
    unsigned period = 0;
    if (get_engine(device, &utilization, &period) == 0) {
        retain_max_percent(&sample->gpu_engine_percent[engine], utilization);
    }
}

void watchdog_nvml_sample(watchdog_nvml *nvml, watchdog_sample *sample) {
    if (nvml == NULL || sample == NULL || !nvml->available) return;
    sample->flags |= WATCHDOG_SAMPLE_GPU_AVAILABLE;
    uint64_t total_milliwatts = 0;
    for (uint32_t index = 0; index < nvml->device_count; ++index) {
        nvml_device device = (nvml_device)nvml->devices[index];
        if (nvml->functions[FN_UTILIZATION] != NULL) {
            FUNCTION(nvml, FN_UTILIZATION, fn_get_utilization, get_utilization);
            nvml_utilization value;
            if (get_utilization(device, &value) == 0) {
                retain_max_percent(&sample->gpu_percent, value.gpu);
                retain_max_percent(&sample->gpu_memory_percent, value.memory);
                retain_max_percent(
                    &sample->gpu_engine_percent[WATCHDOG_GPU_SM], value.gpu);
                retain_max_percent(
                    &sample->gpu_engine_percent[WATCHDOG_GPU_MEMORY], value.memory);
            }
        }
        sample_engine(nvml, device, FN_ENCODER, WATCHDOG_GPU_ENCODER, sample);
        sample_engine(nvml, device, FN_DECODER, WATCHDOG_GPU_DECODER, sample);
        sample_engine(nvml, device, FN_JPEG, WATCHDOG_GPU_JPEG, sample);
        sample_engine(nvml, device, FN_OFA, WATCHDOG_GPU_OFA, sample);

        if (nvml->functions[FN_TEMPERATURE] != NULL) {
            FUNCTION(nvml, FN_TEMPERATURE, fn_get_temperature, get_temperature);
            unsigned temperature = 0;
            if (get_temperature(device, 0, &temperature) == 0
                && temperature <= 200u) {
                const int16_t candidate = (int16_t)(temperature * 10u);
                if (sample->gpu_temp_deci_c == WATCHDOG_TEMP_UNKNOWN
                    || candidate > sample->gpu_temp_deci_c) {
                    sample->gpu_temp_deci_c = candidate;
                }
            }
        }
        if (nvml->functions[FN_POWER] != NULL) {
            FUNCTION(nvml, FN_POWER, fn_get_power, get_power);
            unsigned milliwatts = 0;
            if (get_power(device, &milliwatts) == 0) {
                total_milliwatts += milliwatts;
            }
        }
        if (nvml->functions[FN_THROTTLE] != NULL) {
            FUNCTION(nvml, FN_THROTTLE, fn_get_throttle, get_throttle);
            unsigned long long reasons = 0;
            if (get_throttle(device, &reasons) == 0 && reasons != 0) {
                sample->flags |= WATCHDOG_SAMPLE_THROTTLED;
            }
        }
        if (nvml->functions[FN_CLOCK] != NULL) {
            FUNCTION(nvml, FN_CLOCK, fn_get_clock, get_clock);
            unsigned clock_mhz = 0;
            if (get_clock(device, 0, &clock_mhz) == 0
                && (sample->gpu_clock_mhz == WATCHDOG_CLOCK_UNKNOWN
                    || clock_mhz > sample->gpu_clock_mhz)) {
                sample->gpu_clock_mhz = clock_mhz;
            }
            clock_mhz = 0;
            if (get_clock(device, 2, &clock_mhz) == 0
                && (sample->vram_clock_mhz == WATCHDOG_CLOCK_UNKNOWN
                    || clock_mhz > sample->vram_clock_mhz)) {
                sample->vram_clock_mhz = clock_mhz;
            }
        }
    }
    const uint64_t deciwatts = (total_milliwatts + 50u) / 100u;
    sample->power_deci_w = deciwatts > UINT16_MAX ? UINT16_MAX : (uint16_t)deciwatts;
}

uint32_t watchdog_nvml_device_count(const watchdog_nvml *nvml) {
    return nvml != NULL && nvml->available ? nvml->device_count : 0u;
}
