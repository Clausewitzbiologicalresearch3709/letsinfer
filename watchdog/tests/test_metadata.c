#include "test.h"

#include "watchdog/metadata.h"

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

typedef struct counts {
    size_t workloads;
    size_t events;
    bool valid;
} counts;

static bool count_workload(const watchdog_workload *workload, void *context) {
    counts *value = context;
    if (workload->id == 0 || workload->type[0] == '\0') value->valid = false;
    ++value->workloads;
    return true;
}

static bool count_event(const watchdog_event *event, void *context) {
    counts *value = context;
    if (event->id == 0 || event->kind[0] == '\0') value->valid = false;
    ++value->events;
    return true;
}

void test_metadata_workloads_and_events(void) {
    char directory[] = "/tmp/watchdog-metadata-XXXXXX";
    TEST_ASSERT(mkdtemp(directory) != NULL);
    char path[512];
    TEST_ASSERT(snprintf(path, sizeof(path), "%s/metadata.sqlite", directory) > 0);

    watchdog_metadata metadata;
    TEST_ASSERT(watchdog_metadata_open(&metadata, path) == 0);
    const watchdog_workload workload = {
        .external_id = "container-1",
        .type = "llm-inference",
        .name = "Fixture workload",
        .model = "fixture-model",
        .runtime = "vllm",
        .started_unix_ms = 1000,
        .status = "running",
        .metadata_json = "{\"port\":8000}"
    };
    uint64_t workload_id = 0;
    TEST_ASSERT(watchdog_metadata_upsert_workload(&metadata, &workload, &workload_id) == 0);
    TEST_ASSERT(workload_id != 0);
    const watchdog_event event = {
        .unix_ms = 1500,
        .kind = "workload.started",
        .severity = 1,
        .workload_id = workload_id,
        .payload_json = "{}"
    };
    TEST_ASSERT(watchdog_metadata_add_event(&metadata, &event, NULL) == 0);
    TEST_ASSERT(watchdog_metadata_finish_workload(&metadata, workload_id, 2000, "stopped") == 0);
    counts result = {.valid = true};
    TEST_ASSERT(watchdog_metadata_query_workloads(&metadata, 0, 3000, 10, count_workload, &result) == 0);
    TEST_ASSERT(watchdog_metadata_query_events(&metadata, 0, 3000, 10, count_event, &result) == 0);
    TEST_ASSERT(result.workloads == 1);
    TEST_ASSERT(result.events == 1);
    TEST_ASSERT(result.valid);
    watchdog_metadata_close(&metadata);

    char wal[520];
    char shm[520];
    TEST_ASSERT(snprintf(wal, sizeof(wal), "%s-wal", path) > 0);
    TEST_ASSERT(snprintf(shm, sizeof(shm), "%s-shm", path) > 0);
    unlink(wal);
    unlink(shm);
    TEST_ASSERT(unlink(path) == 0);
    TEST_ASSERT(rmdir(directory) == 0);
}
