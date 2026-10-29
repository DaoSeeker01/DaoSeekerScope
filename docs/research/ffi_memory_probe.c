/* Bounded process memory measurements; never prints hardware snapshots. */
#if defined(__linux__)
#define _POSIX_C_SOURCE 200809L
#endif
#if defined(DSCOPE_SYNTHETIC)
#include <stdint.h>
extern uint64_t scope_probe_synthetic(uint32_t profile, uint32_t refreshes);
#else
#include "../../bindings/daoseeker_scope.h"
#endif
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
#include <errno.h>
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
#define TAIL_BUDGET (16u * 1024u * 1024u)
#if defined(DSCOPE_SYNTHETIC)
#define USAGE "choose a workload: calibrate, resident_calibrate, synthetic, over_limit, growth_synthetic"
#else
#define USAGE "choose a workload: calibrate, resident_calibrate, cached, fresh, growth_cached; or soak_cached <120..3600 seconds, multiple of 60>"
#endif
#if defined(_WIN32)
#define RESIDENT_METRIC "working_set_size"
#define RESIDENT_UNIT "bytes"
#elif defined(__linux__)
#define RESIDENT_METRIC "proc_statm_resident"
#define RESIDENT_UNIT "pages"
#elif defined(__APPLE__)
#include <mach/mach.h>
#define RESIDENT_METRIC "mach_task_basic_resident"
#define RESIDENT_UNIT "bytes"
#endif
static uint64_t launcher_pid;
static int isolated;
static int include_resident;
static uint64_t resident_multiplier = 1;

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

static int resident(uint64_t *raw) {
#if defined(_WIN32)
    PROCESS_MEMORY_COUNTERS counters = {0};
    counters.cb = sizeof(counters);
    if (!GetProcessMemoryInfo(GetCurrentProcess(), &counters, sizeof(counters))) return 0;
    *raw = (uint64_t)counters.WorkingSetSize;
#elif defined(__APPLE__)
    mach_task_basic_info_data_t info;
    mach_msg_type_number_t count = MACH_TASK_BASIC_INFO_COUNT;
    /* The self-task port is borrowed; task_info does not transfer ownership. */
    if (task_info(mach_task_self(), MACH_TASK_BASIC_INFO, (task_info_t)&info, &count) != KERN_SUCCESS
        || count != MACH_TASK_BASIC_INFO_COUNT) return 0;
    *raw = (uint64_t)info.resident_size;
#else
    char text[512], *cursor, *end;
    unsigned column;
    FILE *file = fopen("/proc/self/statm", "r");
    if (file == NULL) return 0;
    if (fgets(text, sizeof(text), file) == NULL || strchr(text, '\n') == NULL || ferror(file)) {
        fclose(file);
        return 0;
    }
    if (fclose(file) != 0) return 0;
    cursor = text;
    for (column = 0; column < 7; ++column) {
        uintmax_t value;
        while (*cursor == ' ' || *cursor == '\t') ++cursor;
        if (*cursor < '0' || *cursor > '9') return 0;
        errno = 0;
        value = strtoumax(cursor, &end, 10);
        if (errno != 0 || end == cursor) return 0;
#if UINTMAX_MAX > UINT64_MAX
        if (value > UINT64_MAX) return 0;
#endif
        if (column == 1) *raw = (uint64_t)value;
        cursor = end;
    }
    while (*cursor == ' ' || *cursor == '\t' || *cursor == '\r' || *cursor == '\n') ++cursor;
    if (*cursor != '\0') return 0;
#endif
    return *raw > 0 && *raw <= UINT64_MAX / resident_multiplier;
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
    uint64_t raw, current = 0;
    if (!peak(&raw)) return 0;
    if (include_resident && !resident(&current)) return 0;
    printf("{\"phase\":\"%s\",\"calls\":%u,\"peak_raw\":%" PRIu64
           ",\"peak_bytes\":%" PRIu64 ",\"elapsed_ns\":%" PRIu64
           ",\"max_json_bytes\":%zu",
           phase, calls, raw, raw * MULTIPLIER, elapsed, max_json);
    if (include_resident) printf(",\"resident_raw\":%" PRIu64 ",\"resident_bytes\":%" PRIu64,
                                 current, current * resident_multiplier);
    printf("}");
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

#if !defined(DSCOPE_SYNTHETIC)
static int collect_once(const dsc_options *options, size_t *max_json) {
    dsc_buffer buffer = {0};
    int32_t code = dsc_collect_json(options, &buffer);
    int valid = code == DSC_OK && buffer.data != NULL
        && buffer.len > 0 && buffer.len <= 1024u * 1024u && buffer.token != 0;
    if (buffer.len > *max_json) *max_json = buffer.len;
    if (dsc_buffer_free(&buffer) != DSC_OK) return failure("buffer_free");
    if (!valid || buffer.data != NULL || buffer.len != 0 || buffer.token != 0)
        return failure("collect_or_zeroing");
    return 0;
}

static int pause_between_calls(void) {
#if defined(_WIN32)
    Sleep(100);
#else
    struct timespec request = {0, 100000000}, remainder;
    while (nanosleep(&request, &remainder) != 0) {
        if (errno != EINTR) return 0;
        request = remainder;
    }
#endif
    return 1;
}

static int timed_sample(unsigned ordinal, unsigned calls, uint64_t elapsed, size_t max_json) {
    printf("{\"record\":\"sample\",\"ordinal\":%u,\"observation\":", ordinal);
    if (!sample(ordinal == 0 ? "baseline" : "collected", calls, elapsed, max_json))
        return 0;
    printf("}\n");
    return fflush(stdout) == 0;
}

static int soak(unsigned duration) {
    unsigned calls = 0, checkpoint = 1;
    size_t max_json = 0;
    double start, now;
    if (dsc_abi_version() != 1 || !seconds(&start)) return failure("soak_start");
    printf("{\"record\":\"header\",\"format\":1,\"mode\":\"soak_cached\",\"launch\":");
    launch_json();
    printf(",\"duration_seconds\":%u,\"checkpoint_seconds\":60,\"call_interval_ms\":100,"
           "\"warmup_seconds\":%u,\"tail_budget_bytes\":%u,"
           "\"resident_metric\":\"%s\",\"resident_raw_unit\":\"%s\",\"resident_multiplier\":%" PRIu64
           ",\"metric\":\"%s\",\"raw_unit\":\"%s\",\"multiplier\":%" PRIu64 "}\n",
           duration, duration >= 600 ? 300u : 60u, TAIL_BUDGET,
           RESIDENT_METRIC, RESIDENT_UNIT, resident_multiplier, METRIC, RAW_UNIT, MULTIPLIER);
    if (fflush(stdout) != 0 || !timed_sample(0, 0, 0, 0)) return failure("output");
    while (checkpoint <= duration / 60) {
        /* Sleep granularity varies; cap calls without claiming an exact rate. */
        if (calls >= duration * 20u + 1u) return failure("soak_call_limit");
        if (collect_once(NULL, &max_json) != 0) return 1;
        ++calls;
        if (!pause_between_calls() || !seconds(&now) || now < start
            || now - start > (double)duration + 5.0) return failure("soak_clock");
        if (now - start >= (double)checkpoint * 60.0) {
            if (!timed_sample(checkpoint, calls, (uint64_t)((now - start) * 1000000000.0), max_json))
                return failure("memory_counter_or_output");
            ++checkpoint;
        }
    }
    printf("{\"record\":\"complete\",\"calls\":%u,\"samples\":%u}\n", calls, checkpoint);
    return fflush(stdout) != 0 ? failure("output") : 0;
}
#endif

static int collect(const char *mode) {
#if defined(DSCOPE_SYNTHETIC)
    uint32_t profile = strcmp(mode, "over_limit") == 0 ? 1u : 0u;
    int growth = strcmp(mode, "growth_synthetic") == 0;
    const unsigned growth_stages[] = {1, 10, 20, 30, 40, 50, 60};
    unsigned batch, stage = 0;
    double start, end;
    uint64_t bytes;
    if (!sample("baseline", 0, 0, 0)) return failure("memory_counter");
    if (!seconds(&start)) return failure("clock");
    for (batch = 0; batch < (growth ? 60u : 2u); ++batch) {
        bytes = scope_probe_synthetic(profile, batch == 0 && !growth ? 0u : 100u);
        if (bytes == 0 || bytes > 1024u * 1024u) return failure("synthetic_workload");
        if (growth && batch + 1 != growth_stages[stage]) continue;
        if (!seconds(&end) || end < start || end - start > 600.0) return failure("clock");
        printf(",");
        if (!sample("collected", batch + 1, (uint64_t)((end - start) * 1000000000.0), (size_t)bytes))
            return failure("memory_counter");
        ++stage;
        if (!seconds(&start)) return failure("clock");
    }
    return 0;
#else
    const unsigned cached_stages[] = {1, 100, 300};
    const unsigned fresh_stages[] = {1, 10, 30};
    const unsigned growth_stages[] = {1, 100, 1000, 2000, 3000, 4000, 5000};
    int growth = strcmp(mode, "growth_cached") == 0;
    int cached = strcmp(mode, "cached") == 0 || growth;
    const unsigned *stages = growth ? growth_stages : (cached ? cached_stages : fresh_stages);
    dsc_options options = {sizeof(dsc_options), 1, 0, 2000, 128};
    unsigned calls = 0, stage;
    size_t max_json = 0;
    double start, end;
    if (dsc_abi_version() != 1) return failure("abi_version");
    if (!sample("baseline", 0, 0, 0)) return failure("memory_counter");
    for (stage = 0; stage < (growth ? 7u : 3u); ++stage) {
        if (!seconds(&start)) return failure("clock");
        while (calls < stages[stage]) {
            if (collect_once(cached ? NULL : &options, &max_json) != 0) return 1;
            ++calls;
        }
        if (!seconds(&end) || end < start || end - start > 600.0) return failure("clock");
        printf(",");
        if (!sample("collected", calls, (uint64_t)((end - start) * 1000000000.0), max_json))
            return failure("memory_counter");
    }
    return 0;
#endif
}

int main(int argc, char **argv) {
    int status;
    int lifecycle = 0;
    int calibrate;
    int timed = 0;
    unsigned duration = 0;
    launcher_pid = process_id();
#if !defined(DSCOPE_SYNTHETIC)
    if (argc == 3 && strcmp(argv[1], "soak_cached") == 0) {
        const char *digit = argv[2];
        if (*digit == '\0' || strlen(digit) > 4) return failure(USAGE);
        for (; *digit; ++digit) {
            if (*digit < '0' || *digit > '9') return failure(USAGE);
            duration = duration * 10u + (unsigned)(*digit - '0');
        }
        timed = duration >= 120 && duration <= 3600 && duration % 60 == 0;
        if (!timed) return failure(USAGE);
    }
#endif
#if defined(__linux__)
    lifecycle = argc == 2 && strcmp(argv[1], "lifecycle") == 0;
    if (argc != 2 && !timed && !(argc == 3 && strcmp(argv[2], "--direct") == 0))
        return failure(USAGE);
#else
    if (argc != 2 && !timed) return failure(USAGE);
#endif
    calibrate = strcmp(argv[1], "calibrate") == 0 || strcmp(argv[1], "resident_calibrate") == 0;
    if (!lifecycle && !timed && (!calibrate
#if defined(DSCOPE_SYNTHETIC)
        && strcmp(argv[1], "synthetic") != 0 && strcmp(argv[1], "over_limit") != 0
        && strcmp(argv[1], "growth_synthetic") != 0))
        return failure(USAGE);
#else
        && strcmp(argv[1], "cached") != 0 && strcmp(argv[1], "fresh") != 0
        && strcmp(argv[1], "growth_cached") != 0))
        return failure(USAGE);
#endif
    include_resident = strcmp(argv[1], "resident_calibrate") == 0
        || strcmp(argv[1], "growth_cached") == 0 || strcmp(argv[1], "growth_synthetic") == 0 || timed;
    if (timed && duration < 120) return failure(USAGE);
#if defined(__linux__)
    if (include_resident) {
        long page = sysconf(_SC_PAGESIZE);
        if (page < 512 || page > 65536 || (page & (page - 1)) != 0) return failure("page_size");
        resident_multiplier = (uint64_t)page;
    }
#endif
#if defined(__linux__)
    if (argc == 2 || timed) {
        pid_t child, waited;
        /* Fork before any Rust call or output. The launcher is single-threaded
         * and holds only its small C image, not Python's pre-exec heap. */
        if (signal(SIGALRM, SIG_DFL) == SIG_ERR) return failure("alarm_signal");
        child = fork();
        if (child < 0) return failure("fork");
        if (child > 0) {
            alarm(timed ? duration + 30u : 170u);
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
#if !defined(DSCOPE_SYNTHETIC)
    if (timed) return soak(duration);
#endif
    printf("{\"format\":2,\"mode\":\"%s\",\"launch\":", argv[1]);
    launch_json();
    if (include_resident) {
        printf(",\"resident_metric\":\"%s\",\"resident_raw_unit\":\"%s\",\"resident_multiplier\":%" PRIu64,
               RESIDENT_METRIC, RESIDENT_UNIT, resident_multiplier);
        if (!calibrate) printf(",\"growth_plan\":{\"warmup_calls\":%u,\"tail_budget_bytes\":%u}",
                               strcmp(argv[1], "growth_cached") == 0 ? 1000u : 10u, TAIL_BUDGET);
    }
#if defined(DSCOPE_SYNTHETIC)
    if (strcmp(argv[1], "growth_synthetic") == 0) {
        printf(",\"workload\":{\"synthetic_data\":true,\"backends\":2,\"sensors_generated\":100,"
               "\"networks_generated\":1024,\"max_entries\":1024,\"refreshes_per_batch\":100,"
               "\"batches\":60,\"json_roundtrip\":true}");
    } else if (!calibrate) {
        printf(",\"workload\":{\"synthetic_data\":true,\"backends\":2,\"sensors_generated\":100,"
               "\"networks_generated\":%u,\"max_entries\":1024,\"first_batch_refreshes\":0,"
               "\"second_batch_refreshes\":100,\"json_roundtrip\":true}",
               strcmp(argv[1], "over_limit") == 0 ? 1025u : 1024u);
    }
#endif
    printf(",\"metric\":\"%s\",\"raw_unit\":\"%s\","
           "\"multiplier\":%" PRIu64 ",\"pressure_bytes\":%u,\"samples\":[",
           METRIC, RAW_UNIT, MULTIPLIER,
           calibrate ? PRESSURE_BYTES : 0);
    status = calibrate ? calibration() : collect(argv[1]);
    if (status != 0) return status;
    printf("]}\n");
    return ferror(stdout) ? failure("output") : 0;
}
