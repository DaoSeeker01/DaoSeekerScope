/* Independent public Windows SDK memory observation, test process only. */
#include <windows.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

_Static_assert(sizeof(MEMORYSTATUSEX) == 64, "MEMORYSTATUSEX size");
_Static_assert(offsetof(MEMORYSTATUSEX, ullTotalPhys) == 8, "total offset");
_Static_assert(offsetof(MEMORYSTATUSEX, ullAvailPhys) == 16, "available offset");
#define PRESSURE ((size_t)64 * 1024 * 1024)
int main(void) {
    unsigned char *held = NULL;
    char command[16];
    int result = 0;
    unsigned int count = 0;
    setvbuf(stdout, NULL, _IONBF, 0);
    for (unsigned int step = 0; step < 16 && fgets(command, sizeof(command), stdin); ++step) {
        if (strcmp(command, "quit\n") == 0) break;
        if (strcmp(command, "hold\n") == 0 && !held) {
            held = malloc(PRESSURE);
            if (!held) { result = 3; break; }
            for (size_t offset = 0; offset < PRESSURE; offset += 4096)
                ((volatile unsigned char *)held)[offset] = 1;
        } else if (strcmp(command, "release\n") == 0 && held) {
            free(held);
            held = NULL;
        } else if (strcmp(command, "sample\n") != 0) {
            result = 2;
            break;
        }
        MEMORYSTATUSEX memory = {0};
        memory.dwLength = (DWORD)sizeof(memory);
        BOOL ok = GlobalMemoryStatusEx(&memory);
        DWORD error = ok ? 0 : GetLastError();
        ++count;
        if (ok) {
            printf("{\"status\":0,\"struct_size\":%lu,\"calls\":%u,\"held_bytes\":%llu,\"total\":%llu,\"available\":%llu}\n",
                   (unsigned long)sizeof(memory), count,
                   (unsigned long long)(held ? PRESSURE : 0),
                   (unsigned long long)memory.ullTotalPhys,
                   (unsigned long long)memory.ullAvailPhys);
        } else {
            printf("{\"status\":%lu,\"struct_size\":%lu,\"calls\":%u,\"total\":null,\"available\":null}\n",
                   (unsigned long)error, (unsigned long)sizeof(memory), count);
            result = 3;
            break;
        }
    }
    free(held);
    return result;
}
