#include "test.h"

#include "watchdog/controllers.h"

#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

void test_controller_registry(void) {
    char path[] = "/tmp/letsinfer-controllers-XXXXXX";
    const int fd = mkstemp(path);
    TEST_ASSERT(fd >= 0);
    const char *installation =
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    const char *fingerprint =
        "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789";
    char value[512];
    const int length = snprintf(
        value, sizeof(value),
        "version=1\ninstallation_id=%s\ncontroller=0123456789abcdef0123456789abcdef,%s\n",
        installation, fingerprint);
    TEST_ASSERT(length > 0 && (size_t)length < sizeof(value));
    TEST_ASSERT(write(fd, value, (size_t)length) == length);
    TEST_ASSERT(close(fd) == 0);
    TEST_ASSERT(chmod(path, 0600) == 0);

    watchdog_controller_registry registry;
    TEST_ASSERT(watchdog_controller_registry_load(path, &registry) == 0);
    TEST_ASSERT(strcmp(registry.installation_id, installation) == 0);
    TEST_ASSERT(registry.count == 1u);
    TEST_ASSERT(watchdog_controller_authorized(&registry, fingerprint));
    TEST_ASSERT(!watchdog_controller_authorized(
        &registry,
        "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"));

    TEST_ASSERT(chmod(path, 0644) == 0);
    TEST_ASSERT(watchdog_controller_registry_load(path, &registry) != 0);

    int rewrite = open(path, O_WRONLY | O_TRUNC);
    TEST_ASSERT(rewrite >= 0);
    TEST_ASSERT(write(rewrite, value, (size_t)length - 1u) == length - 1);
    TEST_ASSERT(close(rewrite) == 0);
    TEST_ASSERT(chmod(path, 0600) == 0);
    TEST_ASSERT(watchdog_controller_registry_load(path, &registry) != 0);

    rewrite = open(path, O_WRONLY | O_TRUNC);
    TEST_ASSERT(rewrite >= 0);
    value[20] = '\0';
    TEST_ASSERT(write(rewrite, value, (size_t)length) == length);
    TEST_ASSERT(close(rewrite) == 0);
    TEST_ASSERT(watchdog_controller_registry_load(path, &registry) != 0);
    unlink(path);
}
