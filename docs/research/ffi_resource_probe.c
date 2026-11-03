/* Development-only finite resource regression. Never emits device data. */
#if defined(__linux__)
#define _POSIX_C_SOURCE 200809L
#endif
#include "../../bindings/daoseeker_scope.h"
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#if defined(_WIN32)
#include <windows.h>
typedef HANDLE resource;
#define INVALID_RESOURCE NULL
#define METRIC "process_handle_count"
static resource acquire(void) { return CreateEventW(NULL, FALSE, FALSE, NULL); }
static int release(resource item) { return CloseHandle(item) != 0; }
static int count_resources(uint64_t *value) {
    DWORD count = 0;
    if (!GetProcessHandleCount(GetCurrentProcess(), &count)) return 0;
    *value = count;
    return count <= 1048576;
}
#elif defined(__linux__) || defined(__APPLE__)
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
typedef int resource;
#define INVALID_RESOURCE (-1)
static resource acquire(void) { return open("/dev/null", O_RDONLY | O_CLOEXEC); }
/* Do not retry close after EINTR: the descriptor may already have been closed. */
static int release(resource item) { return close(item) == 0; }
#if defined(__linux__)
#include <dirent.h>
#define METRIC "proc_self_fd_count"
static int count_resources(uint64_t *value) {
    DIR *directory = opendir("/proc/self/fd");
    struct dirent *entry;
    unsigned scanned = 0;
    int own, okay = 1;
    *value = 0;
    if (directory == NULL) return 0;
    own = dirfd(directory);
    if (own < 0) { (void)closedir(directory); return 0; }
    for (;;) {
        unsigned long number;
        char *end;
        errno = 0;
        entry = readdir(directory);
        if (entry == NULL) { if (errno != 0) okay = 0; break; }
        if (++scanned > 65536) { okay = 0; break; }
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        if (entry->d_name[0] < '0' || entry->d_name[0] > '9') { okay = 0; break; }
        errno = 0;
        number = strtoul(entry->d_name, &end, 10);
        if (errno || *end || number > 2147483647UL) { okay = 0; break; }
        if (number != (unsigned long)own) ++*value;
    }
    if (closedir(directory) != 0) okay = 0;
    return okay;
}
#else
#define METRIC "fcntl_fd_count_0_65535"
static int count_resources(uint64_t *value) {
    int fd;
    *value = 0;
    /* An explicit bounded view, not a total for inherited/higher descriptors. */
    for (fd = 0; fd < 65536; ++fd) {
        int result, attempt = 0;
        do { result = fcntl(fd, F_GETFD); } while (result < 0 && errno == EINTR && ++attempt < 3);
        if (result >= 0) ++*value;
        else if (errno != EBADF) return 0;
    }
    return 1;
}
#endif
#else
#error Supported development hosts: Windows, Linux, macOS
#endif

static int failure(const char *code) {
    fprintf(stderr, "ffi_resource_probe: %s\n", code);
    return 1;
}
static int acquire_many(resource *items, unsigned count) {
    unsigned index;
    for (index = 0; index < count; ++index) {
        items[index] = acquire();
        if (items[index] == INVALID_RESOURCE) {
            while (index > 0) (void)release(items[--index]);
            return 0;
        }
    }
    return 1;
}
static int release_many(resource *items, unsigned count) {
    unsigned index;
    int okay = 1;
    for (index = 0; index < count; ++index) if (!release(items[index])) okay = 0;
    return okay;
}
static int valid_buffer(const dsc_buffer *buffer) {
    return buffer->data != NULL && buffer->len > 0
        && buffer->len <= 1048576 && buffer->token != 0;
}
static int empty_buffer(const dsc_buffer *buffer) {
    return buffer->data == NULL && buffer->len == 0 && buffer->token == 0;
}
static int collect_once(size_t *largest) {
    dsc_buffer buffer = {0};
    int32_t code = dsc_collect_json(NULL, &buffer);
    int okay = code == DSC_OK && valid_buffer(&buffer);
    if (okay && buffer.len > *largest) *largest = buffer.len;
    if (dsc_buffer_free(&buffer) != DSC_OK) okay = 0;
    return okay && empty_buffer(&buffer);
}
static int buffer_limit(void) {
    enum { LIMIT = 64 };
    dsc_buffer held[LIMIT] = {0}, extra = {0}, old_token_test;
    uint8_t *copies[LIMIT] = {0};
    const char *problem = NULL;
    uint64_t retired_token;
    int32_t overflow = DSC_PANIC, recovery = DSC_PANIC, retired = DSC_PANIC;
    unsigned i, j;
    for (i = 0; i < LIMIT; ++i) {
        problem = "fill_buffers";
        if (dsc_collect_json(NULL, &held[i]) != DSC_OK || !valid_buffer(&held[i]))
            goto cleanup;
        for (j = 0; j < i; ++j) if (held[i].token == held[j].token) goto cleanup;
        copies[i] = malloc(held[i].len);
        if (copies[i] == NULL) goto cleanup;
        memcpy(copies[i], held[i].data, held[i].len);
    }
    problem = "buffer_limit";
    overflow = dsc_collect_json(NULL, &extra);
    if (overflow != DSC_RESOURCE_LIMIT || !empty_buffer(&extra)) goto cleanup;
    retired_token = held[0].token;
    if (dsc_buffer_free(&held[0]) != DSC_OK || !empty_buffer(&held[0])) goto cleanup;
    problem = "buffer_recovery";
    recovery = dsc_collect_json(NULL, &extra);
    if (recovery != DSC_OK || !valid_buffer(&extra) || extra.token == retired_token) goto cleanup;
    /* Use the live address and length so rejection depends on the retired token. */
    old_token_test = extra;
    old_token_test.token = retired_token;
    retired = dsc_buffer_free(&old_token_test);
    if (retired != DSC_INVALID_BUFFER) goto cleanup;
    problem = "retained_buffer_changed";
    for (i = 1; i < LIMIT; ++i) {
        if (extra.token == held[i].token || memcmp(copies[i], held[i].data, held[i].len))
            goto cleanup;
    }
    problem = NULL;
cleanup:
    if (dsc_buffer_free(&extra) != DSC_OK || !empty_buffer(&extra)) problem = "buffer_cleanup";
    for (i = 0; i < LIMIT; ++i) {
        if (dsc_buffer_free(&held[i]) != DSC_OK || !empty_buffer(&held[i])) problem = "buffer_cleanup";
        free(copies[i]);
    }
    if (problem != NULL) return failure(problem);
    printf("{\"format\":1,\"mode\":\"buffer_limit\",\"metric\":\"%s\","
           "\"held_buffers\":%d,\"overflow_status\":%" PRId32 ",\"recovery_status\":%" PRId32 ","
           "\"retired_token_status\":%" PRId32 ",\"verified_live_buffers\":%d,\"completed\":true}\n",
           METRIC, LIMIT, overflow, recovery, retired, LIMIT - 1);
    return fflush(stdout) != 0 ? failure("output") : 0;
}
int main(int argc, char **argv) {
    uint64_t values[10], before, opened, closed;
    resource items[32];
    size_t largest = 0;
    unsigned call, index;
    int control, okay = 1;
    if (argc != 2) return failure("invalid_mode");
    if (!strcmp(argv[1], "buffer_limit")) return buffer_limit();
    if (strcmp(argv[1], "calibrate") && strcmp(argv[1], "cached")
        && strcmp(argv[1], "control")) return failure("invalid_mode");
    if (!strcmp(argv[1], "calibrate")) {
        if (!count_resources(&before) || !acquire_many(items, 32)) return failure("calibration_open");
        okay = count_resources(&opened);
        if (!release_many(items, 32)) okay = 0;
        if (!count_resources(&closed)) okay = 0;
        if (!okay) return failure("calibration_count_or_close");
        printf("{\"format\":1,\"mode\":\"calibrate\",\"metric\":\"%s\","
               "\"opened_resources\":32,\"counts\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "]}\n",
               METRIC, before, opened, closed);
        return ferror(stdout) ? failure("output") : 0;
    }
    control = !strcmp(argv[1], "control");
    for (call = 1; call <= 1000; ++call) {
        if (!collect_once(&largest)) { okay = 0; break; }
        if (call % 100 == 0 && !count_resources(&values[call / 100 - 1])) { okay = 0; break; }
        if (control && call == 100 && !acquire_many(items, 16)) return failure("control_open");
    }
    if (control && call > 100 && !release_many(items, 16)) okay = 0;
    if (!okay) return failure("collection_or_count_or_close");
    printf("{\"format\":1,\"mode\":\"%s\",\"metric\":\"%s\",\"warmup_calls\":100,"
           "\"total_calls\":1000,\"interval_calls\":100,\"tail_budget\":8,"
           "\"control_resources\":%u,\"max_json_bytes\":%zu,\"samples\":[",
           argv[1], METRIC, control ? 16u : 0u, largest);
    for (index = 0; index < 10; ++index)
        printf("%s{\"calls\":%u,\"count\":%" PRIu64 "}", index ? "," : "", (index + 1) * 100, values[index]);
    puts("],\"completed\":true}");
    return ferror(stdout) ? failure("output") : 0;
}
