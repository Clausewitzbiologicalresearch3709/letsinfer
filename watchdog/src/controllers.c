#include "watchdog/controllers.h"

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define WATCHDOG_CONTROLLER_FILE_MAX 12288u

static bool lowercase_hex(const char *value, size_t length) {
    if (value == NULL || strlen(value) != length) return false;
    for (size_t index = 0; index < length; ++index) {
        if (!((value[index] >= '0' && value[index] <= '9')
            || (value[index] >= 'a' && value[index] <= 'f'))) return false;
    }
    return true;
}

static bool duplicate(
    const watchdog_controller_registry *registry,
    const char *id,
    const char *fingerprint
) {
    for (size_t index = 0; index < registry->count; ++index) {
        if (strcmp(registry->controllers[index].id, id) == 0
            || strcmp(registry->controllers[index].certificate_sha256, fingerprint) == 0) {
            return true;
        }
    }
    return false;
}

int watchdog_controller_registry_load(
    const char *path,
    watchdog_controller_registry *registry
) {
    if (path == NULL || registry == NULL) return -1;
    struct stat details;
    if (lstat(path, &details) != 0 || !S_ISREG(details.st_mode)
        || details.st_uid != getuid() || (details.st_mode & 077u) != 0
        || details.st_size <= 0
        || (uintmax_t)details.st_size > WATCHDOG_CONTROLLER_FILE_MAX) return -1;
    const int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return -1;
    char text[WATCHDOG_CONTROLLER_FILE_MAX + 1u];
    size_t count = 0u;
    while (count < (size_t)details.st_size) {
        const ssize_t current = read(fd, text + count, (size_t)details.st_size - count);
        if (current <= 0) {
            count = 0u;
            break;
        }
        count += (size_t)current;
    }
    const int saved_errno = errno;
    close(fd);
    errno = saved_errno;
    if (count != (size_t)details.st_size || text[count - 1u] != '\n'
        || memchr(text, '\0', count) != NULL) return -1;
    text[count] = '\0';

    memset(registry, 0, sizeof(*registry));
    bool version_seen = false;
    bool installation_seen = false;
    char *save = NULL;
    for (char *line = strtok_r(text, "\n", &save); line != NULL;
         line = strtok_r(NULL, "\n", &save)) {
        if (strcmp(line, "version=1") == 0) {
            if (version_seen || installation_seen || registry->count != 0u) return -1;
            version_seen = true;
            continue;
        }
        if (strncmp(line, "installation_id=", 16u) == 0) {
            const char *value = line + 16u;
            if (!version_seen || installation_seen || registry->count != 0u
                || !lowercase_hex(value, 64u)) return -1;
            memcpy(registry->installation_id, value, 65u);
            installation_seen = true;
            continue;
        }
        if (strncmp(line, "controller=", 11u) != 0 || !version_seen || !installation_seen
            || registry->count >= WATCHDOG_CONTROLLER_MAX) return -1;
        char *id = line + 11u;
        char *separator = strchr(id, ',');
        if (separator == NULL || strchr(separator + 1u, ',') != NULL) return -1;
        *separator = '\0';
        const char *fingerprint = separator + 1u;
        if (!lowercase_hex(id, 32u) || !lowercase_hex(fingerprint, 64u)
            || duplicate(registry, id, fingerprint)) return -1;
        watchdog_controller *controller = &registry->controllers[registry->count++];
        memcpy(controller->id, id, 33u);
        memcpy(controller->certificate_sha256, fingerprint, 65u);
    }
    return version_seen && installation_seen && registry->count != 0u ? 0 : -1;
}

bool watchdog_controller_authorized(
    const watchdog_controller_registry *registry,
    const char *certificate_sha256
) {
    if (registry == NULL || !lowercase_hex(certificate_sha256, 64u)) return false;
    for (size_t index = 0; index < registry->count; ++index) {
        if (strcmp(registry->controllers[index].certificate_sha256,
                   certificate_sha256) == 0) return true;
    }
    return false;
}
