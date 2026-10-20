/* Independent public SDK probe; no identifiers or private Mach interfaces. */
#include <mach/mach.h>
#include <mach/processor_info.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#define MAX_CPUS 1024
_Static_assert(sizeof(integer_t) == 4, "Mach wire word");
_Static_assert(sizeof(natural_t) == 4, "Mach unsigned tick");
_Static_assert(sizeof(mach_port_t) == 4, "Mach port");
_Static_assert(sizeof(vm_address_t) == 8, "64-bit desktop macOS");
_Static_assert(CPU_STATE_MAX == 4 && CPU_STATE_USER == 0 &&
               CPU_STATE_SYSTEM == 1 && CPU_STATE_IDLE == 2 &&
               CPU_STATE_NICE == 3, "CPU state order");

static int sample(unsigned calls) {
    host_t host = mach_host_self();
    if (host == MACH_PORT_NULL) return 3;
    natural_t processors = 0;
    mach_msg_type_number_t words = 0;
    processor_info_array_t raw = NULL;
    kern_return_t result = host_processor_info(host, PROCESSOR_CPU_LOAD_INFO,
                                              &processors, &raw, &words);
    if (result != KERN_SUCCESS) {
        (void)mach_port_deallocate(mach_task_self(), host);
        return 3;
    }
    uint32_t copy[MAX_CPUS][4];
    int valid = processors > 0 && processors <= MAX_CPUS &&
                words == processors * 4 && raw != NULL;
    if (valid) {
        for (natural_t cpu = 0; cpu < processors; ++cpu) {
            for (unsigned state = 0; state < 4; ++state) {
                copy[cpu][state] = (uint32_t)raw[cpu * 4 + state];
            }
        }
    }
    kern_return_t freed = KERN_SUCCESS;
    if (raw != NULL && words != 0) {
        freed = vm_deallocate(mach_task_self(), (vm_address_t)raw,
                              (vm_size_t)words * sizeof(integer_t));
    }
    kern_return_t released = mach_port_deallocate(mach_task_self(), host);
    if (!valid || freed != KERN_SUCCESS || released != KERN_SUCCESS) return 3;
    printf("{\"status\":\"passed\",\"calls\":%u,\"processors\":%u,"
           "\"word_count\":%u,\"word_size\":%zu,\"pointer_size\":%zu,"
           "\"released_array\":true,\"released_host\":true,\"ticks\":[",
           calls, (unsigned)processors, (unsigned)words,
           sizeof(integer_t), sizeof(void *));
    for (natural_t cpu = 0; cpu < processors; ++cpu) {
        if (cpu != 0) putchar(',');
        printf("[%" PRIu32 ",%" PRIu32 ",%" PRIu32 ",%" PRIu32 "]",
               copy[cpu][0], copy[cpu][1], copy[cpu][2], copy[cpu][3]);
    }
    puts("]}");
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
