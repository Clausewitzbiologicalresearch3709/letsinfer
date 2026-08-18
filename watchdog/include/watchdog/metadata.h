#ifndef WATCHDOG_METADATA_H
#define WATCHDOG_METADATA_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define WATCHDOG_METADATA_TEXT_MAX 255u
#define WATCHDOG_METADATA_JSON_MAX 16384u

typedef struct watchdog_metadata {
    void *library;
    void *database;
    char error[256];
} watchdog_metadata;

typedef struct watchdog_workload {
    uint64_t id;
    const char *external_id;
    const char *type;
    const char *name;
    const char *model;
    const char *runtime;
    uint64_t started_unix_ms;
    uint64_t ended_unix_ms;
    const char *status;
    const char *metadata_json;
} watchdog_workload;

typedef struct watchdog_event {
    uint64_t id;
    uint64_t unix_ms;
    const char *kind;
    uint32_t severity;
    uint64_t workload_id;
    const char *payload_json;
} watchdog_event;

typedef bool (*watchdog_workload_visitor)(const watchdog_workload *workload, void *context);
typedef bool (*watchdog_event_visitor)(const watchdog_event *event, void *context);

int watchdog_metadata_open(watchdog_metadata *metadata, const char *path);
void watchdog_metadata_close(watchdog_metadata *metadata);
const char *watchdog_metadata_error(const watchdog_metadata *metadata);

int watchdog_metadata_upsert_workload(
    watchdog_metadata *metadata,
    const watchdog_workload *workload,
    uint64_t *identifier
);
int watchdog_metadata_finish_workload(
    watchdog_metadata *metadata,
    uint64_t identifier,
    uint64_t ended_unix_ms,
    const char *status
);
int watchdog_metadata_add_event(
    watchdog_metadata *metadata,
    const watchdog_event *event,
    uint64_t *identifier
);
int watchdog_metadata_query_workloads(
    watchdog_metadata *metadata,
    uint64_t start_unix_ms,
    uint64_t end_unix_ms,
    size_t limit,
    watchdog_workload_visitor visitor,
    void *context
);
int watchdog_metadata_query_events(
    watchdog_metadata *metadata,
    uint64_t start_unix_ms,
    uint64_t end_unix_ms,
    size_t limit,
    watchdog_event_visitor visitor,
    void *context
);

#endif
