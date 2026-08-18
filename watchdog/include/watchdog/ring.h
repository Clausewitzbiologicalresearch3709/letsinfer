#ifndef WATCHDOG_RING_H
#define WATCHDOG_RING_H

#include "watchdog/record.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifndef WATCHDOG_PATH_MAX
#define WATCHDOG_PATH_MAX 4096
#endif

typedef struct watchdog_ring {
    int fd;
    uint64_t interval_ms;
    uint64_t capacity;
    char path[WATCHDOG_PATH_MAX];
} watchdog_ring;

typedef bool (*watchdog_ring_visitor)(const watchdog_sample *sample, void *context);

int watchdog_ring_open(
    watchdog_ring *ring,
    const char *path,
    uint64_t interval_ms,
    uint64_t capacity
);
void watchdog_ring_close(watchdog_ring *ring);
int watchdog_ring_write(watchdog_ring *ring, const watchdog_sample *sample);
int watchdog_ring_sync(watchdog_ring *ring);
int watchdog_ring_read_bucket(
    const watchdog_ring *ring,
    uint64_t bucket,
    watchdog_sample *sample
);
int watchdog_ring_query(
    const watchdog_ring *ring,
    uint64_t start_ms,
    uint64_t end_ms,
    size_t maximum_samples,
    watchdog_ring_visitor visitor,
    void *context,
    size_t *visited
);
int watchdog_ring_latest(const watchdog_ring *ring, watchdog_sample *sample);
int watchdog_ring_drop_cache(const watchdog_ring *ring);

#endif
