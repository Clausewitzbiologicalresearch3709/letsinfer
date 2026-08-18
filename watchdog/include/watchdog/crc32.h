#ifndef WATCHDOG_CRC32_H
#define WATCHDOG_CRC32_H

#include <stddef.h>
#include <stdint.h>

uint32_t watchdog_crc32(const void *data, size_t length);

#endif
