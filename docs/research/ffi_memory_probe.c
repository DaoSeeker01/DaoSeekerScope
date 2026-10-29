/* Development-only process high-water measurement; never prints snapshots. */
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
#include <psapi.h>
#define METRIC "peak_working_set"
#define RAW_UNIT "bytes"
#define MULTIPLIER UINT64_C(1)
#elif defined(__linux__) || defined(__APPLE__)
#include <sys/resource.h>
#include <time.h>
#include <unistd.h>
#define METRIC "ru_maxrss"
#if defined(__APPLE__)
#define RAW_UNIT "bytes"
#define MULTIPLIER UINT64_C(1)
#else
#define RAW_UNIT "kibibytes"
#define MULTIPLIER UINT64_C(1024)
#endif
#else
#error This development probe supports only desktop Windows, Linux and macOS
#endif

#if defined(__linux__)
#include <errno.h>
#include <signal.h>
#include <sys/prctl.h>
#include <sys/wait.h>
#endif

#define PRESSURE_BYTES (64u * 1024u * 1024u)
static uint64_t launcher_pid;
static int isolated;

static uint64_t process_id(void) {
#if defined(_WIN32)
    return (uint64_t)GetCurrentProcessId();
#else
    return (uint64_t)getpid();
#endif
}

static void launch_json(void) {
    printf("{\"strategy\":\"%s\",\"launcher_pid\":%" PRIu64
           ",\"measurement_pid\":%" PRIu64 ",\"parent_death_signal\":%d}",
           isolated ? "linux_fork" : "direct", launcher_pid, process_id(),
           isolated ? 9 : 0);
}

static int failure(const char *message) {
    fprintf(stderr, "ffi_memory_probe: %s\n", message);
    return 1;
}

static int peak(uint64_t *raw) {
#if defined(_WIN32)
    PROCESS_MEMORY_COUNTERS counters = {0};
    counters.cb = sizeof(counters);
    if (!GetProcessMemoryInfo(GetCurrentProcess(), &counters, sizeof(counters))) return 0;
    *raw = (uint64_t)counters.PeakWorkingSetSize;
#else
    struct rusage usage;
    if (getrusage(RUSAGE_SELF, &usage) != 0 || usage.ru_maxrss < 0) return 0;
    *raw = (uint64_t)usage.ru_maxrss;
#endif
    return *raw > 0 && *raw <= UINT64_MAX / MULTIPLIER;
}

static int seconds(double *value) {
#if defined(_WIN32)
    LARGE_INTEGER count, frequency;
    if (!QueryPerformanceCounter(&count) || !QueryPerformanceFrequency(&frequency)
        || count.QuadPart < 0 || frequency.QuadPart <= 0) return 0;
    *value = (double)count.QuadPart / (double)frequency.QuadPart;
#else
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) return 0;
    *value = (double)now.tv_sec + (double)now.tv_nsec / 1000000000.0;
#endif
    return 1;
}

static int sample(const char *phase, unsigned calls, uint64_t elapsed, size_t max_json) {
    uint64_t raw;
    if (!peak(&raw)) return 0;
    printf("{\"phase\":\"%s\",\"calls\":%u,\"peak_raw\":%" PRIu64
           ",\"peak_bytes\":%" PRIu64 ",\"elapsed_ns\":%" PRIu64
           ",\"max_json_bytes\":%zu}",
           phase, calls, raw, raw * MULTIPLIER, elapsed, max_json);
    return 1;
}

static int calibration(void) {
    volatile unsigned char *memory;
    size_t i;
    if (!sample("baseline", 0, 0, 0)) return failure("memory_counter");
    memory = (volatile unsigned char *)malloc(PRESSURE_BYTES);
    if (memory == NULL) return failure("allocation");
    for (i = 0; i < PRESSURE_BYTES; i += 4096) memory[i] = (unsigned char)(i / 4096);
    memory[PRESSURE_BYTES - 1] = 1;
    printf(",");
    if (!sample("touched", 0, 0, 0)) {
        free((void *)memory);
        return failure("memory_counter");
    }
    free((void *)memory);
    printf(",");
    if (!sample("freed", 0, 0, 0)) return failure("memory_counter");
    return 0;
}

static int collect(const char *mode) {
    const unsigned cached_stages[] = {1, 100, 300};
    const unsigned fresh_stages[] = {1, 10, 30};
    int cached = strcmp(mode, "cached") == 0;
    const unsigned *stages = cached ? cached_stages : fresh_stages;
    dsc_options options = {sizeof(dsc_options), 1, 0, 2000, 128};
    unsigned calls = 0, stage;
    size_t max_json = 0;
    double start, end;
    if (dsc_abi_version() != 1) return failure("abi_version");
    if (!sample("baseline", 0, 0, 0)) return failure("memory_counter");
    for (stage = 0; stage < 3; ++stage) {
        if (!seconds(&start)) return failure("clock");
        while (calls < stages[stage]) {
            dsc_buffer buffer = {0};
            int32_t code = dsc_collect_json(cached ? NULL : &options, &buffer);
            int valid = code == DSC_OK && buffer.data != NULL
                && buffer.len > 0 && buffer.len <= 1024u * 1024u && buffer.token != 0;
            if (buffer.len > max_json) max_json = buffer.len;
            /* Also attempt cleanup on a malformed success or error output. */
            if (dsc_buffer_free(&buffer) != DSC_OK) return failure("buffer_free");
            if (!valid || buffer.data != NULL || buffer.len != 0 || buffer.token != 0)
                return failure("collect_or_zeroing");
            ++calls;
        }
        if (!seconds(&end) || end < start || end - start > 600.0) return failure("clock");
        printf(",");
        if (!sample("collected", calls, (uint64_t)((end - start) * 1000000000.0), max_json))
            return failure("memory_counter");
    }
    return 0;
}

int main(int argc, char **argv) {
    int status;
    int lifecycle = 0;
    launcher_pid = process_id();
#if defined(__linux__)
    lifecycle = argc == 2 && strcmp(argv[1], "lifecycle") == 0;
    if (argc != 2 && !(argc == 3 && strcmp(argv[2], "--direct") == 0))
        return failure("usage_calibrate_cached_or_fresh");
#else
    if (argc != 2) return failure("usage_calibrate_cached_or_fresh");
#endif
    if (!lifecycle && (strcmp(argv[1], "calibrate") != 0
        && strcmp(argv[1], "cached") != 0 && strcmp(argv[1], "fresh") != 0))
        return failure("usage_calibrate_cached_or_fresh");
#if defined(__linux__)
    if (argc == 2) {
        pid_t child, waited;
        /* Fork before any Rust call or output. The launcher is single-threaded
         * and holds only its small C image, not Python's pre-exec heap. */
        if (signal(SIGALRM, SIG_DFL) == SIG_ERR) return failure("alarm_signal");
        child = fork();
        if (child < 0) return failure("fork");
        if (child > 0) {
            alarm(170);
            do { waited = waitpid(child, &status, 0); } while (waited < 0 && errno == EINTR);
            alarm(0);
            if (waited != child) return failure("waitpid");
            if (!WIFEXITED(status)) return failure("worker_signaled");
            return WEXITSTATUS(status);
        }
        if (prctl(PR_SET_PDEATHSIG, (long)SIGKILL, 0L, 0L, 0L) != 0
            || (uint64_t)getppid() != launcher_pid) return failure("parent_death_signal");
        isolated = 1;
    }
    if (lifecycle) {
        printf("{\"format\":2,\"lifecycle\":true,\"launch\":");
        launch_json();
        printf("}\n");
        if (fflush(stdout) != 0) return failure("output");
        alarm(15); /* Safety fallback for the parent-death regression only. */
        for (;;) pause();
    }
#endif
    printf("{\"format\":2,\"mode\":\"%s\",\"launch\":", argv[1]);
    launch_json();
    printf(",\"metric\":\"%s\",\"raw_unit\":\"%s\","
           "\"multiplier\":%" PRIu64 ",\"pressure_bytes\":%u,\"samples\":[",
           METRIC, RAW_UNIT, MULTIPLIER,
           strcmp(argv[1], "calibrate") == 0 ? PRESSURE_BYTES : 0);
    status = strcmp(argv[1], "calibrate") == 0 ? calibration() : collect(argv[1]);
    if (status != 0) return status;
    printf("]}\n");
    return ferror(stdout) ? failure("output") : 0;
}
