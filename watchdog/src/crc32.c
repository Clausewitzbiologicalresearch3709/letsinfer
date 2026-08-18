#include "watchdog/crc32.h"

uint32_t watchdog_crc32(const void *data, size_t length) {
    const unsigned char *bytes = data;
    uint32_t crc = UINT32_C(0xffffffff);

    for (size_t index = 0; index < length; ++index) {
        crc ^= bytes[index];
        for (unsigned bit = 0; bit < 8; ++bit) {
            const uint32_t mask = (uint32_t)-(int32_t)(crc & 1u);
            crc = (crc >> 1u) ^ (UINT32_C(0xedb88320) & mask);
        }
    }
    return ~crc;
}
