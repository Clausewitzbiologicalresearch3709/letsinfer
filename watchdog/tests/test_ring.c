#include "test.h"

#include "watchdog/ring.h"

#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef struct query_result {
    uint64_t sequences[8];
    size_t count;
} query_result;

static bool collect(const watchdog_sample *sample, void *context) {
    query_result *result = context;
    result->sequences[result->count++] = sample->sequence;
    return true;
}

void test_ring_wrap_and_query(void) {
    char directory[] = "/tmp/watchdog-test-XXXXXX";
    TEST_ASSERT(mkdtemp(directory) != NULL);
    char path[512];
    TEST_ASSERT(snprintf(path, sizeof(path), "%s/raw.ring", directory) > 0);

    watchdog_ring ring;
    TEST_ASSERT(watchdog_ring_open(&ring, path, 1000, 4) == 0);
    for (uint64_t sequence = 1; sequence <= 6; ++sequence) {
        watchdog_sample sample;
        watchdog_sample_init(&sample);
        sample.sequence = sequence;
        sample.unix_ms = sequence * 1000;
        TEST_ASSERT(watchdog_ring_write(&ring, &sample) == 0);
    }
    TEST_ASSERT(watchdog_ring_sync(&ring) == 0);

    watchdog_sample missing;
    TEST_ASSERT(watchdog_ring_read_bucket(&ring, 1, &missing) == 1);
    query_result result = {0};
    size_t visited = 0;
    TEST_ASSERT(watchdog_ring_query(&ring, 2000, 6000, 8, collect, &result, &visited) == 0);
    TEST_ASSERT(visited == 4);
    TEST_ASSERT(result.count == 4);
    TEST_ASSERT(result.sequences[0] == 3);
    TEST_ASSERT(result.sequences[3] == 6);

    watchdog_sample latest;
    TEST_ASSERT(watchdog_ring_latest(&ring, &latest) == 0);
    TEST_ASSERT(latest.sequence == 6);
    watchdog_ring_close(&ring);
    TEST_ASSERT(unlink(path) == 0);
    TEST_ASSERT(rmdir(directory) == 0);
}
