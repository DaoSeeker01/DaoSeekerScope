/* Independent public Windows SDK counter probe, no identifiers or OS hooks. */
#define _WIN32_WINNT 0x0601
#include <windows.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>

_Static_assert(sizeof(FILETIME) == 8, "SDK FILETIME layout");
static uint64_t ticks(FILETIME time) {
    return ((uint64_t)time.dwHighDateTime << 32) | time.dwLowDateTime;
}
static int sample(unsigned calls) {
    WORD groups = GetActiveProcessorGroupCount();
    DWORD count = GetActiveProcessorCount(ALL_PROCESSOR_GROUPS);
    FILETIME idle = {0}, kernel = {0}, user = {0};
    if (groups == 0 || count == 0) return 3;
    if (groups != 1) {
        printf("{\"status\":\"unsupported\",\"groups\":%u,\"processors\":%lu}\n",
               (unsigned)groups, (unsigned long)count);
        fflush(stdout);
        return 0;
    }
    if (!GetSystemTimes(&idle, &kernel, &user)) return 3;
    if (GetActiveProcessorGroupCount() != groups ||
        GetActiveProcessorCount(ALL_PROCESSOR_GROUPS) != count) return 3;
    printf("{\"status\":\"passed\",\"groups\":%u,\"processors\":%lu,"
           "\"calls\":%u,\"struct_size\":%zu,\"idle\":%" PRIu64 ","
           "\"kernel\":%" PRIu64 ",\"user\":%" PRIu64 "}\n",
           (unsigned)groups, (unsigned long)count, calls, sizeof(FILETIME),
           ticks(idle), ticks(kernel), ticks(user));
    fflush(stdout);
    return 0;
}
int main(void) {
    char command[16];
    unsigned calls = 1;
    int code = sample(calls);
    if (code != 0) return code;
    for (unsigned i = 0; i < 8; ++i) {
        if (fgets(command, sizeof(command), stdin) == NULL) return 0;
        if (strcmp(command, "quit\n") == 0) return 0;
        if (strcmp(command, "sample\n") != 0) return 2;
        code = sample(++calls);
        if (code != 0) return code;
    }
    return 0;
}
