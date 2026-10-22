/* Independent public SDK tick counter. No failure sentinel, IDs or OS hooks. */
#define _WIN32_WINNT 0x0600
#include <windows.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>

static void sample(unsigned calls) {
    uint64_t milliseconds = GetTickCount64();
    printf("{\"milliseconds\":%" PRIu64 ",\"calls\":%u}\n", milliseconds, calls);
    fflush(stdout);
}
int main(void) {
    char command[16];
    unsigned calls = 1;
    sample(calls);
    for (unsigned i = 0; i < 16; ++i) {
        if (fgets(command, sizeof(command), stdin) == NULL) return 0;
        if (strcmp(command, "quit\n") == 0) return 0;
        if (strcmp(command, "sample\n") != 0) return 2;
        sample(++calls);
    }
    return 0;
}
