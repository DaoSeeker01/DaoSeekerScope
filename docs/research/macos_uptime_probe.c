/* Independent public SDK reads. No raw boot epoch, identifiers or clock writes. */
#include <sys/types.h>
#include <sys/time.h>
#include <sys/sysctl.h>
#include <time.h>
#include <inttypes.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

_Static_assert(sizeof(time_t) == 8, "LP64 time_t");
_Static_assert(sizeof(struct timeval) == 16, "LP64 timeval");
_Static_assert(offsetof(struct timeval, tv_sec) == 0, "timeval seconds offset");
_Static_assert(offsetof(struct timeval, tv_usec) == 8, "timeval microseconds offset");

static int failure(const char *stage) {
    printf("{\"status\":\"failed\",\"stage\":\"%s\"}\n", stage);
    fflush(stdout);
    return 3;
}
static int boot(struct timeval *value) {
    int mib[2] = {CTL_KERN, KERN_BOOTTIME};
    size_t length = sizeof(*value);
    if (sysctl(mib, 2, value, &length, NULL, 0) != 0) return 0;
    return length == sizeof(*value) && value->tv_sec >= 0 &&
           value->tv_usec >= 0 && value->tv_usec < 1000000;
}
static int sample(unsigned calls) {
    struct timeval before = {0}, after = {0};
    if (!boot(&before)) return failure("boot_before");
    time_t now = time(NULL);
    if (now == (time_t)-1) return failure("time");
    if (!boot(&after)) return failure("boot_after");
    if (before.tv_sec != after.tv_sec || before.tv_usec != after.tv_usec)
        return failure("changed_boot");
    if (now < 0 || now < before.tv_sec) return failure("invalid_data");
    uint64_t seconds = (uint64_t)(now - before.tv_sec);
    printf("{\"status\":\"passed\",\"calls\":%u,\"uptime_seconds\":%" PRIu64
           ",\"timeval_size\":%zu,\"time_t_size\":%zu,\"boot_stable\":true}\n",
           calls, seconds, sizeof(struct timeval), sizeof(time_t));
    fflush(stdout);
    return 0;
}
int main(void) {
    char command[16];
    unsigned calls = 1;
    if (sample(calls) != 0) return 3;
    for (unsigned i = 0; i < 16; ++i) {
        if (fgets(command, sizeof(command), stdin) == NULL) return 0;
        if (strcmp(command, "quit\n") == 0) return 0;
        if (strcmp(command, "sample\n") != 0) return 2;
        if (sample(++calls) != 0) return 3;
    }
    return 0;
}
