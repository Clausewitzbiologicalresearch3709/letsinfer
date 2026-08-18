#ifndef WATCHDOG_CONTROLLERS_H
#define WATCHDOG_CONTROLLERS_H

#include <stdbool.h>
#include <stddef.h>

#define WATCHDOG_CONTROLLER_MAX 64u

typedef struct watchdog_controller {
    char id[33u];
    char certificate_sha256[65u];
} watchdog_controller;

typedef struct watchdog_controller_registry {
    char installation_id[65u];
    watchdog_controller controllers[WATCHDOG_CONTROLLER_MAX];
    size_t count;
} watchdog_controller_registry;

int watchdog_controller_registry_load(
    const char *path,
    watchdog_controller_registry *registry
);
bool watchdog_controller_authorized(
    const watchdog_controller_registry *registry,
    const char *certificate_sha256
);

#endif
