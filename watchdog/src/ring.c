#include "watchdog/ring.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

static int preallocate(int fd, uint64_t bytes) {
    if (bytes > (uint64_t)INT64_MAX) {
        errno = EFBIG;
        return -1;
    }
#if defined(__linux__)
    const int result = posix_fallocate(fd, 0, (off_t)bytes);
    if (result != 0) {
        errno = result;
        return -1;
    }
    return 0;
#else
    return ftruncate(fd, (off_t)bytes);
#endif
}

static int read_exact(int fd, uint8_t *buffer, size_t length, off_t offset) {
    size_t consumed = 0;
    while (consumed < length) {
        const ssize_t count = pread(fd, buffer + consumed, length - consumed, offset + (off_t)consumed);
        if (count == 0) {
            memset(buffer + consumed, 0, length - consumed);
            return 0;
        }
        if (count < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        consumed += (size_t)count;
    }
    return 0;
}

static int write_exact(int fd, const uint8_t *buffer, size_t length, off_t offset) {
    size_t consumed = 0;
    while (consumed < length) {
        const ssize_t count = pwrite(fd, buffer + consumed, length - consumed, offset + (off_t)consumed);
        if (count < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        consumed += (size_t)count;
    }
    return 0;
}

static off_t bucket_offset(const watchdog_ring *ring, uint64_t bucket) {
    const uint64_t slot = bucket % ring->capacity;
    return (off_t)(slot * WATCHDOG_RECORD_BYTES);
}

int watchdog_ring_open(
    watchdog_ring *ring,
    const char *path,
    uint64_t interval_ms,
    uint64_t capacity
) {
    if (ring == NULL || path == NULL || interval_ms == 0 || capacity == 0
        || strlen(path) >= sizeof(ring->path)
        || capacity > UINT64_MAX / WATCHDOG_RECORD_BYTES) {
        errno = EINVAL;
        return -1;
    }

    memset(ring, 0, sizeof(*ring));
    ring->fd = -1;
    ring->interval_ms = interval_ms;
    ring->capacity = capacity;
    memcpy(ring->path, path, strlen(path) + 1);
    ring->fd = open(path, O_RDWR | O_CREAT | O_CLOEXEC, 0640);
    if (ring->fd < 0) {
        return -1;
    }
    if (preallocate(ring->fd, capacity * WATCHDOG_RECORD_BYTES) != 0) {
        const int saved = errno;
        close(ring->fd);
        ring->fd = -1;
        errno = saved;
        return -1;
    }
    return 0;
}

void watchdog_ring_close(watchdog_ring *ring) {
    if (ring != NULL && ring->fd >= 0) {
        close(ring->fd);
        ring->fd = -1;
    }
}

int watchdog_ring_write(watchdog_ring *ring, const watchdog_sample *sample) {
    uint8_t record[WATCHDOG_RECORD_BYTES];
    if (ring == NULL || ring->fd < 0 || sample == NULL
        || !watchdog_record_encode(sample, record)) {
        errno = EINVAL;
        return -1;
    }
    const uint64_t bucket = sample->unix_ms / ring->interval_ms;
    return write_exact(ring->fd, record, sizeof(record), bucket_offset(ring, bucket));
}

int watchdog_ring_sync(watchdog_ring *ring) {
    if (ring == NULL || ring->fd < 0) {
        errno = EINVAL;
        return -1;
    }
    return fdatasync(ring->fd);
}

int watchdog_ring_read_bucket(
    const watchdog_ring *ring,
    uint64_t bucket,
    watchdog_sample *sample
) {
    uint8_t record[WATCHDOG_RECORD_BYTES];
    if (ring == NULL || ring->fd < 0 || sample == NULL) {
        errno = EINVAL;
        return -1;
    }
    if (read_exact(ring->fd, record, sizeof(record), bucket_offset(ring, bucket)) != 0) {
        return -1;
    }
    if (!watchdog_record_decode(record, sample)
        || sample->unix_ms / ring->interval_ms != bucket) {
        errno = ENOENT;
        return 1;
    }
    return 0;
}

int watchdog_ring_query(
    const watchdog_ring *ring,
    uint64_t start_ms,
    uint64_t end_ms,
    size_t maximum_samples,
    watchdog_ring_visitor visitor,
    void *context,
    size_t *visited
) {
    if (ring == NULL || visitor == NULL || end_ms < start_ms) {
        errno = EINVAL;
        return -1;
    }
    size_t count = 0;
    const uint64_t first_bucket = start_ms / ring->interval_ms;
    const uint64_t final_bucket = end_ms / ring->interval_ms;
    for (uint64_t bucket = first_bucket;
         bucket <= final_bucket && count < maximum_samples;
         ++bucket) {
        watchdog_sample sample;
        const int result = watchdog_ring_read_bucket(ring, bucket, &sample);
        if (result < 0) {
            return -1;
        }
        if (result == 0 && sample.unix_ms >= start_ms && sample.unix_ms <= end_ms) {
            ++count;
            if (!visitor(&sample, context)) {
                break;
            }
        }
        if (bucket == UINT64_MAX) {
            break;
        }
    }
    if (visited != NULL) {
        *visited = count;
    }
    return 0;
}

int watchdog_ring_latest(const watchdog_ring *ring, watchdog_sample *sample) {
    if (ring == NULL || sample == NULL) {
        errno = EINVAL;
        return -1;
    }
    bool found = false;
    watchdog_sample latest;
    enum { BLOCK_RECORDS = 32 };
    uint8_t records[BLOCK_RECORDS * WATCHDOG_RECORD_BYTES];
#if defined(POSIX_FADV_RANDOM)
    (void)posix_fadvise(ring->fd, 0, 0, POSIX_FADV_RANDOM);
#endif
    for (uint64_t first_slot = 0; first_slot < ring->capacity; first_slot += BLOCK_RECORDS) {
        const uint64_t remaining = ring->capacity - first_slot;
        const size_t record_count = remaining < BLOCK_RECORDS ? (size_t)remaining : BLOCK_RECORDS;
        const size_t byte_count = record_count * WATCHDOG_RECORD_BYTES;
        const off_t offset = (off_t)(first_slot * WATCHDOG_RECORD_BYTES);
        if (read_exact(
                ring->fd,
                records,
                byte_count,
                offset
            ) != 0) {
            return -1;
        }
        for (size_t index = 0; index < record_count; ++index) {
            watchdog_sample candidate;
            if (watchdog_record_decode(records + index * WATCHDOG_RECORD_BYTES, &candidate)
                && (!found || candidate.sequence > latest.sequence)) {
                latest = candidate;
                found = true;
            }
        }
#if defined(POSIX_FADV_DONTNEED)
        (void)posix_fadvise(ring->fd, offset, (off_t)byte_count, POSIX_FADV_DONTNEED);
#endif
    }
    if (!found) {
        errno = ENOENT;
        return 1;
    }
    *sample = latest;
    return 0;
}

int watchdog_ring_drop_cache(const watchdog_ring *ring) {
    if (ring == NULL || ring->fd < 0) {
        errno = EINVAL;
        return -1;
    }
#if defined(POSIX_FADV_DONTNEED)
    const int result = posix_fadvise(ring->fd, 0, 0, POSIX_FADV_DONTNEED);
    if (result != 0) {
        errno = result;
        return -1;
    }
#endif
    return 0;
}
