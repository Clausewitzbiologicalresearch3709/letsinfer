#include "watchdog/metadata.h"

#include <dlfcn.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>

typedef struct sqlite3 sqlite3;
typedef struct sqlite3_stmt sqlite3_stmt;
typedef int64_t sqlite3_int64;

enum {
    SQLITE_OK = 0,
    SQLITE_ROW = 100,
    SQLITE_DONE = 101,
    SQLITE_OPEN_READWRITE = 0x00000002,
    SQLITE_OPEN_CREATE = 0x00000004,
    SQLITE_OPEN_NOMUTEX = 0x00008000
};

typedef struct sqlite_api {
    int (*open_v2)(const char *, sqlite3 **, int, const char *);
    int (*close_v2)(sqlite3 *);
    int (*exec)(sqlite3 *, const char *, int (*)(void *, int, char **, char **), void *, char **);
    void (*free_memory)(void *);
    const char *(*errmsg)(sqlite3 *);
    int (*busy_timeout)(sqlite3 *, int);
    int (*prepare_v2)(sqlite3 *, const char *, int, sqlite3_stmt **, const char **);
    int (*finalize)(sqlite3_stmt *);
    int (*step)(sqlite3_stmt *);
    int (*reset)(sqlite3_stmt *);
    int (*clear_bindings)(sqlite3_stmt *);
    int (*bind_int)(sqlite3_stmt *, int, int);
    int (*bind_int64)(sqlite3_stmt *, int, sqlite3_int64);
    int (*bind_text)(sqlite3_stmt *, int, const char *, int, void (*)(void *));
    sqlite3_int64 (*last_insert_rowid)(sqlite3 *);
    sqlite3_int64 (*column_int64)(sqlite3_stmt *, int);
    int (*column_int)(sqlite3_stmt *, int);
    const unsigned char *(*column_text)(sqlite3_stmt *, int);
    sqlite3_int64 (*soft_heap_limit64)(sqlite3_int64);
} sqlite_api;

static sqlite_api api;
static unsigned api_users;

static void set_error(watchdog_metadata *metadata, const char *message) {
    if (metadata == NULL) return;
    snprintf(metadata->error, sizeof(metadata->error), "%s", message == NULL ? "unknown error" : message);
}

static void *load_library(void) {
    const char *candidates[] = {
        "libsqlite3.so.0",
        "libsqlite3.so",
        "libsqlite3.dylib",
        "/usr/lib/libsqlite3.dylib"
    };
    for (size_t index = 0; index < sizeof(candidates) / sizeof(candidates[0]); ++index) {
        void *library = dlopen(candidates[index], RTLD_NOW | RTLD_LOCAL);
        if (library != NULL) return library;
    }
    return NULL;
}

static bool symbol(void *library, const char *name, void *target, size_t target_size) {
    void *address = dlsym(library, name);
    if (address == NULL || target_size != sizeof(address)) return false;
    memcpy(target, &address, sizeof(address));
    return true;
}

#define LOAD_REQUIRED(library, member, name) \
    do { if (!symbol((library), (name), &api.member, sizeof(api.member))) return false; } while (0)

static bool load_api(void *library) {
    memset(&api, 0, sizeof(api));
    LOAD_REQUIRED(library, open_v2, "sqlite3_open_v2");
    LOAD_REQUIRED(library, close_v2, "sqlite3_close_v2");
    LOAD_REQUIRED(library, exec, "sqlite3_exec");
    LOAD_REQUIRED(library, free_memory, "sqlite3_free");
    LOAD_REQUIRED(library, errmsg, "sqlite3_errmsg");
    LOAD_REQUIRED(library, busy_timeout, "sqlite3_busy_timeout");
    LOAD_REQUIRED(library, prepare_v2, "sqlite3_prepare_v2");
    LOAD_REQUIRED(library, finalize, "sqlite3_finalize");
    LOAD_REQUIRED(library, step, "sqlite3_step");
    LOAD_REQUIRED(library, reset, "sqlite3_reset");
    LOAD_REQUIRED(library, clear_bindings, "sqlite3_clear_bindings");
    LOAD_REQUIRED(library, bind_int, "sqlite3_bind_int");
    LOAD_REQUIRED(library, bind_int64, "sqlite3_bind_int64");
    LOAD_REQUIRED(library, bind_text, "sqlite3_bind_text");
    LOAD_REQUIRED(library, last_insert_rowid, "sqlite3_last_insert_rowid");
    LOAD_REQUIRED(library, column_int64, "sqlite3_column_int64");
    LOAD_REQUIRED(library, column_int, "sqlite3_column_int");
    LOAD_REQUIRED(library, column_text, "sqlite3_column_text");
    symbol(library, "sqlite3_soft_heap_limit64", &api.soft_heap_limit64, sizeof(api.soft_heap_limit64));
    return true;
}

static int execute(watchdog_metadata *metadata, const char *sql) {
    char *error = NULL;
    const int result = api.exec((sqlite3 *)metadata->database, sql, NULL, NULL, &error);
    if (result != SQLITE_OK) {
        set_error(metadata, error != NULL ? error : api.errmsg((sqlite3 *)metadata->database));
        if (error != NULL) api.free_memory(error);
        return -1;
    }
    return 0;
}

static bool valid_text(const char *value, size_t maximum, bool required) {
    if (value == NULL) return !required;
    size_t length = 0;
    while (length <= maximum && value[length] != '\0') ++length;
    return length <= maximum && (!required || length > 0);
}

static int bind_text(sqlite3_stmt *statement, int index, const char *value, size_t maximum) {
    if (!valid_text(value, maximum, false)) return -1;
    if (value == NULL) value = "";
    return api.bind_text(statement, index, value, -1, NULL);
}

static int prepare(watchdog_metadata *metadata, const char *sql, sqlite3_stmt **statement) {
    if (api.prepare_v2((sqlite3 *)metadata->database, sql, -1, statement, NULL) != SQLITE_OK) {
        set_error(metadata, api.errmsg((sqlite3 *)metadata->database));
        return -1;
    }
    return 0;
}

static const char *column_text(sqlite3_stmt *statement, int column) {
    const unsigned char *value = api.column_text(statement, column);
    return value == NULL ? "" : (const char *)value;
}

int watchdog_metadata_open(watchdog_metadata *metadata, const char *path) {
    if (metadata == NULL || path == NULL) return -1;
    memset(metadata, 0, sizeof(*metadata));
    metadata->library = load_library();
    if (metadata->library == NULL) {
        set_error(metadata, "libsqlite3 is unavailable");
        return -1;
    }
    if (api_users == 0 && !load_api(metadata->library)) {
        set_error(metadata, "libsqlite3 is missing a required symbol");
        dlclose(metadata->library);
        metadata->library = NULL;
        return -1;
    }
    ++api_users;
    sqlite3 *database = NULL;
    const int flags = SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_NOMUTEX;
    if (api.open_v2(path, &database, flags, NULL) != SQLITE_OK) {
        set_error(metadata, database == NULL ? "could not open metadata database" : api.errmsg(database));
        if (database != NULL) api.close_v2(database);
        watchdog_metadata_close(metadata);
        return -1;
    }
    metadata->database = database;
    if (api.soft_heap_limit64 != NULL) api.soft_heap_limit64(1024 * 1024);
    api.busy_timeout(database, 1000);

    const char *schema =
        "PRAGMA journal_mode=WAL;"
        "PRAGMA synchronous=NORMAL;"
        "PRAGMA cache_size=-256;"
        "PRAGMA mmap_size=0;"
        "PRAGMA temp_store=FILE;"
        "PRAGMA wal_autocheckpoint=64;"
        "PRAGMA journal_size_limit=262144;"
        "PRAGMA foreign_keys=ON;"
        "CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL);"
        "INSERT INTO schema_version(version) SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM schema_version);"
        "CREATE TABLE IF NOT EXISTS workloads("
        "id INTEGER PRIMARY KEY, external_id TEXT NOT NULL UNIQUE, type TEXT NOT NULL,"
        "name TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '', runtime TEXT NOT NULL DEFAULT '',"
        "started_unix_ms INTEGER NOT NULL, ended_unix_ms INTEGER NOT NULL DEFAULT 0,"
        "status TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '');"
        "CREATE INDEX IF NOT EXISTS workloads_time ON workloads(started_unix_ms, ended_unix_ms);"
        "CREATE INDEX IF NOT EXISTS workloads_type ON workloads(type, started_unix_ms);"
        "CREATE TABLE IF NOT EXISTS events("
        "id INTEGER PRIMARY KEY, unix_ms INTEGER NOT NULL, kind TEXT NOT NULL, severity INTEGER NOT NULL,"
        "workload_id INTEGER NOT NULL DEFAULT 0, payload_json TEXT NOT NULL DEFAULT '');"
        "CREATE INDEX IF NOT EXISTS events_time ON events(unix_ms);"
        "CREATE INDEX IF NOT EXISTS events_kind ON events(kind, unix_ms);";
    if (execute(metadata, schema) != 0) {
        watchdog_metadata_close(metadata);
        return -1;
    }
    return 0;
}

void watchdog_metadata_close(watchdog_metadata *metadata) {
    if (metadata == NULL) return;
    if (metadata->database != NULL) {
        api.close_v2((sqlite3 *)metadata->database);
        metadata->database = NULL;
    }
    if (metadata->library != NULL) {
        dlclose(metadata->library);
        metadata->library = NULL;
        if (api_users > 0) --api_users;
        if (api_users == 0) memset(&api, 0, sizeof(api));
    }
}

const char *watchdog_metadata_error(const watchdog_metadata *metadata) {
    return metadata == NULL ? "invalid metadata handle" : metadata->error;
}

int watchdog_metadata_upsert_workload(
    watchdog_metadata *metadata,
    const watchdog_workload *workload,
    uint64_t *identifier
) {
    if (metadata == NULL || metadata->database == NULL || workload == NULL
        || !valid_text(workload->external_id, WATCHDOG_METADATA_TEXT_MAX, true)
        || !valid_text(workload->type, WATCHDOG_METADATA_TEXT_MAX, true)
        || !valid_text(workload->status, WATCHDOG_METADATA_TEXT_MAX, true)
        || !valid_text(workload->metadata_json, WATCHDOG_METADATA_JSON_MAX, false)) return -1;
    const char *sql =
        "INSERT INTO workloads(external_id,type,name,model,runtime,started_unix_ms,ended_unix_ms,status,metadata_json)"
        "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(external_id) DO UPDATE SET "
        "type=excluded.type,name=excluded.name,model=excluded.model,runtime=excluded.runtime,"
        "started_unix_ms=excluded.started_unix_ms,ended_unix_ms=excluded.ended_unix_ms,"
        "status=excluded.status,metadata_json=excluded.metadata_json;";
    sqlite3_stmt *statement = NULL;
    if (prepare(metadata, sql, &statement) != 0) return -1;
    int result = 0;
    result |= bind_text(statement, 1, workload->external_id, WATCHDOG_METADATA_TEXT_MAX);
    result |= bind_text(statement, 2, workload->type, WATCHDOG_METADATA_TEXT_MAX);
    result |= bind_text(statement, 3, workload->name, WATCHDOG_METADATA_TEXT_MAX);
    result |= bind_text(statement, 4, workload->model, WATCHDOG_METADATA_TEXT_MAX);
    result |= bind_text(statement, 5, workload->runtime, WATCHDOG_METADATA_TEXT_MAX);
    result |= api.bind_int64(statement, 6, (sqlite3_int64)workload->started_unix_ms);
    result |= api.bind_int64(statement, 7, (sqlite3_int64)workload->ended_unix_ms);
    result |= bind_text(statement, 8, workload->status, WATCHDOG_METADATA_TEXT_MAX);
    result |= bind_text(statement, 9, workload->metadata_json, WATCHDOG_METADATA_JSON_MAX);
    if (result != SQLITE_OK || api.step(statement) != SQLITE_DONE) {
        set_error(metadata, api.errmsg((sqlite3 *)metadata->database));
        api.finalize(statement);
        return -1;
    }
    api.finalize(statement);

    if (identifier != NULL) {
        if (prepare(metadata, "SELECT id FROM workloads WHERE external_id=?;", &statement) != 0) {
            return -1;
        }
        if (bind_text(statement, 1, workload->external_id, WATCHDOG_METADATA_TEXT_MAX) != SQLITE_OK
            || api.step(statement) != SQLITE_ROW) {
            set_error(metadata, api.errmsg((sqlite3 *)metadata->database));
            api.finalize(statement);
            return -1;
        }
        *identifier = (uint64_t)api.column_int64(statement, 0);
        api.finalize(statement);
    }
    return 0;
}

int watchdog_metadata_finish_workload(
    watchdog_metadata *metadata,
    uint64_t identifier,
    uint64_t ended_unix_ms,
    const char *status
) {
    if (metadata == NULL || metadata->database == NULL
        || !valid_text(status, WATCHDOG_METADATA_TEXT_MAX, true)) return -1;
    sqlite3_stmt *statement = NULL;
    if (prepare(metadata, "UPDATE workloads SET ended_unix_ms=?,status=? WHERE id=?;", &statement) != 0) return -1;
    int result = api.bind_int64(statement, 1, (sqlite3_int64)ended_unix_ms);
    result |= bind_text(statement, 2, status, WATCHDOG_METADATA_TEXT_MAX);
    result |= api.bind_int64(statement, 3, (sqlite3_int64)identifier);
    const int step = result == SQLITE_OK ? api.step(statement) : result;
    api.finalize(statement);
    return step == SQLITE_DONE ? 0 : -1;
}

int watchdog_metadata_add_event(
    watchdog_metadata *metadata,
    const watchdog_event *event,
    uint64_t *identifier
) {
    if (metadata == NULL || metadata->database == NULL || event == NULL
        || !valid_text(event->kind, WATCHDOG_METADATA_TEXT_MAX, true)
        || !valid_text(event->payload_json, WATCHDOG_METADATA_JSON_MAX, false)) return -1;
    sqlite3_stmt *statement = NULL;
    if (prepare(metadata, "INSERT INTO events(unix_ms,kind,severity,workload_id,payload_json) VALUES(?,?,?,?,?);", &statement) != 0) return -1;
    int result = api.bind_int64(statement, 1, (sqlite3_int64)event->unix_ms);
    result |= bind_text(statement, 2, event->kind, WATCHDOG_METADATA_TEXT_MAX);
    result |= api.bind_int(statement, 3, (int)event->severity);
    result |= api.bind_int64(statement, 4, (sqlite3_int64)event->workload_id);
    result |= bind_text(statement, 5, event->payload_json, WATCHDOG_METADATA_JSON_MAX);
    const int step = result == SQLITE_OK ? api.step(statement) : result;
    if (step == SQLITE_DONE && identifier != NULL) {
        *identifier = (uint64_t)api.last_insert_rowid((sqlite3 *)metadata->database);
    }
    if (step != SQLITE_DONE) set_error(metadata, api.errmsg((sqlite3 *)metadata->database));
    api.finalize(statement);
    return step == SQLITE_DONE ? 0 : -1;
}

int watchdog_metadata_query_workloads(
    watchdog_metadata *metadata,
    uint64_t start_unix_ms,
    uint64_t end_unix_ms,
    size_t limit,
    watchdog_workload_visitor visitor,
    void *context
) {
    if (metadata == NULL || metadata->database == NULL || visitor == NULL
        || end_unix_ms < start_unix_ms || limit == 0 || limit > INT_MAX) return -1;
    const char *sql =
        "SELECT id,external_id,type,name,model,runtime,started_unix_ms,ended_unix_ms,status,metadata_json "
        "FROM workloads WHERE started_unix_ms<=? AND (ended_unix_ms=0 OR ended_unix_ms>=?) "
        "ORDER BY started_unix_ms LIMIT ?;";
    sqlite3_stmt *statement = NULL;
    if (prepare(metadata, sql, &statement) != 0) return -1;
    api.bind_int64(statement, 1, (sqlite3_int64)end_unix_ms);
    api.bind_int64(statement, 2, (sqlite3_int64)start_unix_ms);
    api.bind_int(statement, 3, (int)limit);
    int step;
    while ((step = api.step(statement)) == SQLITE_ROW) {
        const watchdog_workload item = {
            .id = (uint64_t)api.column_int64(statement, 0),
            .external_id = column_text(statement, 1),
            .type = column_text(statement, 2),
            .name = column_text(statement, 3),
            .model = column_text(statement, 4),
            .runtime = column_text(statement, 5),
            .started_unix_ms = (uint64_t)api.column_int64(statement, 6),
            .ended_unix_ms = (uint64_t)api.column_int64(statement, 7),
            .status = column_text(statement, 8),
            .metadata_json = column_text(statement, 9)
        };
        if (!visitor(&item, context)) break;
    }
    api.finalize(statement);
    return step == SQLITE_DONE || step == SQLITE_ROW ? 0 : -1;
}

int watchdog_metadata_query_events(
    watchdog_metadata *metadata,
    uint64_t start_unix_ms,
    uint64_t end_unix_ms,
    size_t limit,
    watchdog_event_visitor visitor,
    void *context
) {
    if (metadata == NULL || metadata->database == NULL || visitor == NULL
        || end_unix_ms < start_unix_ms || limit == 0 || limit > INT_MAX) return -1;
    const char *sql =
        "SELECT id,unix_ms,kind,severity,workload_id,payload_json FROM events "
        "WHERE unix_ms BETWEEN ? AND ? ORDER BY unix_ms LIMIT ?;";
    sqlite3_stmt *statement = NULL;
    if (prepare(metadata, sql, &statement) != 0) return -1;
    api.bind_int64(statement, 1, (sqlite3_int64)start_unix_ms);
    api.bind_int64(statement, 2, (sqlite3_int64)end_unix_ms);
    api.bind_int(statement, 3, (int)limit);
    int step;
    while ((step = api.step(statement)) == SQLITE_ROW) {
        const watchdog_event item = {
            .id = (uint64_t)api.column_int64(statement, 0),
            .unix_ms = (uint64_t)api.column_int64(statement, 1),
            .kind = column_text(statement, 2),
            .severity = (uint32_t)api.column_int(statement, 3),
            .workload_id = (uint64_t)api.column_int64(statement, 4),
            .payload_json = column_text(statement, 5)
        };
        if (!visitor(&item, context)) break;
    }
    api.finalize(statement);
    return step == SQLITE_DONE || step == SQLITE_ROW ? 0 : -1;
}
