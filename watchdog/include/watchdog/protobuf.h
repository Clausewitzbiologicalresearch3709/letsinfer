#ifndef WATCHDOG_PROTOBUF_H
#define WATCHDOG_PROTOBUF_H

#include "watchdog/record.h"

#include <stddef.h>
#include <stdint.h>

#define WATCHDOG_PROTOCOL_VERSION 3u
#define WATCHDOG_MAX_FRAME_BYTES 65536u
#define WATCHDOG_MAX_BATCH_SAMPLES 128u

typedef enum watchdog_request_kind {
    WATCHDOG_REQUEST_INVALID = 0,
    WATCHDOG_REQUEST_GET_LATEST,
    WATCHDOG_REQUEST_SUBSCRIBE,
    WATCHDOG_REQUEST_QUERY_RANGE,
    WATCHDOG_REQUEST_GET_CAPABILITIES,
    WATCHDOG_REQUEST_PING,
    WATCHDOG_REQUEST_GET_SITE_STATUS
} watchdog_request_kind;

typedef enum watchdog_resolution {
    WATCHDOG_RESOLUTION_UNSPECIFIED = 0,
    WATCHDOG_RESOLUTION_RAW_1_SECOND = 1,
    WATCHDOG_RESOLUTION_1_MINUTE = 2,
    WATCHDOG_RESOLUTION_15_MINUTES = 3
} watchdog_resolution;

typedef struct watchdog_request {
    uint64_t request_id;
    watchdog_request_kind kind;
    uint32_t history_seconds;
    uint64_t start_unix_ms;
    uint64_t end_unix_ms;
    watchdog_resolution resolution;
    uint64_t nonce;
} watchdog_request;

typedef struct watchdog_site_status {
    const char *installation_id;
    const char *release;
    const char *model;
    const char *engine;
    const char *runtime_name;
    const char *runtime_version;
    const char *manifest_sha256;
    const char *cache_provider;
    uint32_t cache_persistent;
    uint32_t inference_port;
    uint32_t max_connections;
    uint32_t max_active_requests;
    uint32_t max_context_tokens;
    const char *service_state;
    const char *engine_state;
    const char *protection_phase;
    uint32_t protection_armed;
    uint32_t trip_latched;
    const char *container_name;
} watchdog_site_status;

typedef enum watchdog_sample_message_kind {
    WATCHDOG_MESSAGE_LATEST = 10,
    WATCHDOG_MESSAGE_LIVE = 13
} watchdog_sample_message_kind;

int watchdog_pb_decode_request(
    const uint8_t *payload,
    size_t payload_length,
    watchdog_request *request
);

size_t watchdog_pb_encode_sample(
    uint64_t request_id,
    watchdog_sample_message_kind kind,
    const watchdog_sample *sample,
    uint8_t *output,
    size_t capacity
);

size_t watchdog_pb_encode_history_batch(
    uint64_t request_id,
    const watchdog_sample *samples,
    size_t sample_count,
    uint8_t *output,
    size_t capacity
);

size_t watchdog_pb_encode_history_complete(
    uint64_t request_id,
    uint64_t through_sequence,
    uint8_t *output,
    size_t capacity
);

size_t watchdog_pb_encode_capabilities(
    uint64_t request_id,
    uint32_t sample_interval_ms,
    uint32_t flush_interval_ms,
    uint32_t physical_gpu_count,
    uint8_t *output,
    size_t capacity
);

size_t watchdog_pb_encode_gap(
    uint64_t request_id,
    uint64_t first_missing_sequence,
    uint64_t latest_sequence,
    uint8_t *output,
    size_t capacity
);

size_t watchdog_pb_encode_error(
    uint64_t request_id,
    uint32_t code,
    const char *message,
    uint8_t *output,
    size_t capacity
);

size_t watchdog_pb_encode_pong(
    uint64_t request_id,
    uint64_t nonce,
    uint8_t *output,
    size_t capacity
);

size_t watchdog_pb_encode_site_status(
    uint64_t request_id,
    const watchdog_site_status *status,
    uint8_t *output,
    size_t capacity
);

size_t watchdog_frame_encode(
    const uint8_t *payload,
    size_t payload_length,
    uint8_t *output,
    size_t capacity
);

int watchdog_frame_length(const uint8_t header[4], uint32_t *payload_length);

#endif
