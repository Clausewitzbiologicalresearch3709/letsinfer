#include "test.h"

#include "watchdog/protobuf.h"

#include <string.h>

void test_protobuf_request_and_response(void) {
    const uint8_t query[] = {
        0x08, 0x07,
        0x62, 0x08,
        0x08, 0xe8, 0x07,
        0x10, 0xd0, 0x0f,
        0x18, 0x01
    };
    watchdog_request request;
    TEST_ASSERT(watchdog_pb_decode_request(query, sizeof(query), &request) == 0);
    TEST_ASSERT(request.request_id == 7);
    TEST_ASSERT(request.kind == WATCHDOG_REQUEST_QUERY_RANGE);
    TEST_ASSERT(request.start_unix_ms == 1000);
    TEST_ASSERT(request.end_unix_ms == 2000);
    TEST_ASSERT(request.resolution == WATCHDOG_RESOLUTION_RAW_1_SECOND);

    watchdog_sample sample;
    watchdog_sample_init(&sample);
    sample.sequence = 9;
    sample.unix_ms = 2000;
    sample.cpu_core_count = 2;
    sample.cpu_core_percent[0] = 10;
    sample.cpu_core_percent[1] = 20;
    uint8_t payload[1024];
    const size_t payload_length = watchdog_pb_encode_sample(
        7,
        WATCHDOG_MESSAGE_LATEST,
        &sample,
        payload,
        sizeof(payload)
    );
    TEST_ASSERT(payload_length > 0);
    uint8_t frame[1030];
    const size_t frame_length = watchdog_frame_encode(
        payload,
        payload_length,
        frame,
        sizeof(frame)
    );
    TEST_ASSERT(frame_length == payload_length + 4);
    uint32_t decoded_length = 0;
    TEST_ASSERT(watchdog_frame_length(frame, &decoded_length) == 0);
    TEST_ASSERT(decoded_length == payload_length);
    TEST_ASSERT(memcmp(frame + 4, payload, payload_length) == 0);

    const size_t capabilities_length = watchdog_pb_encode_capabilities(
        11, 1000, 10000, 8, payload, sizeof(payload));
    TEST_ASSERT(capabilities_length > 0);
    TEST_ASSERT(WATCHDOG_PROTOCOL_VERSION == 3u);
    int found_gpu_count = 0;
    int found_protocol_version = 0;
    for (size_t index = 0; index + 1 < capabilities_length; ++index) {
        if (payload[index] == 0x38 && payload[index + 1] == 0x08) {
            found_gpu_count = 1;
        }
        if (payload[index] == 0x08 && payload[index + 1] == WATCHDOG_PROTOCOL_VERSION) {
            found_protocol_version = 1;
        }
    }
    TEST_ASSERT(found_gpu_count == 1);
    TEST_ASSERT(found_protocol_version == 1);

    const uint8_t status_request[] = {0x08, 0x0d, 0x7a, 0x00};
    TEST_ASSERT(watchdog_pb_decode_request(
        status_request, sizeof(status_request), &request) == 0);
    TEST_ASSERT(request.request_id == 13);
    TEST_ASSERT(request.kind == WATCHDOG_REQUEST_GET_SITE_STATUS);

    const watchdog_site_status status = {
        .installation_id = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
        .release = "fixture-release",
        .model = "fixture-model",
        .engine = "dwarfstar",
        .runtime_name = "fixture-runtime",
        .runtime_version = "0.11.0-rc.2",
        .manifest_sha256 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        .cache_provider = "dwarfstar-native",
        .cache_persistent = 1,
        .inference_port = 8000,
        .max_connections = 64,
        .max_active_requests = 16,
        .max_context_tokens = 557056,
        .service_state = "running",
        .engine_state = "running",
        .protection_phase = "armed",
        .protection_armed = 1,
        .trip_latched = 0,
        .container_name = "letsinfer-dwarfstar"
    };
    const size_t status_length = watchdog_pb_encode_site_status(
        13, &status, payload, sizeof(payload));
    TEST_ASSERT(status_length > 0);
    TEST_ASSERT(payload[status_length - 1] != 0);
}
