/* Independent public SDK success-path probe; no private API or pressure load. */
#include <mach/mach.h>
#include <mach/host_info.h>
#include <mach/vm_statistics.h>
#include <sys/sysctl.h>
#include <inttypes.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

_Static_assert(sizeof(integer_t) == 4 && sizeof(vm_size_t) == 8,
               "64-bit desktop Mach ABI");
_Static_assert(HOST_VM_INFO64_REV1_COUNT == 38, "Rust libc rev1 count");
_Static_assert(offsetof(vm_statistics64_data_t, speculative_count) == 92,
               "rev1 speculative offset");
_Static_assert(offsetof(vm_statistics64_data_t,
                       total_uncompressed_pages_in_compressor) == 144,
               "rev1 prefix end");
_Static_assert(sizeof(vm_statistics64_data_t) >= 152, "SDK contains rev1");

static int sample(unsigned calls) {
    uint64_t total = 0;
    size_t length = sizeof(total);
    if (sysctlbyname("hw.memsize", &total, &length, NULL, 0) != 0 ||
        length != sizeof(total) || total == 0) return 3;
    host_t host = mach_host_self();
    if (host == MACH_PORT_NULL) return 3;
    vm_size_t page_size = 0;
    kern_return_t page_result = host_page_size(host, &page_size);
    vm_statistics64_data_t stats = {0};
    mach_msg_type_number_t count = HOST_VM_INFO64_REV1_COUNT;
    kern_return_t vm_result = KERN_FAILURE;
    if (page_result == KERN_SUCCESS) {
        vm_result = host_statistics64(host, HOST_VM_INFO64,
                                     (host_info64_t)&stats, &count);
    }
    kern_return_t released = mach_port_deallocate(mach_task_self(), host);
    if (page_result != KERN_SUCCESS || vm_result != KERN_SUCCESS || released != KERN_SUCCESS) {
        printf("{\"status\":\"failed\",\"stage\":\"api\",\"page_status\":%d,\"vm_status\":%d,\"release_status\":%d}\n",
               page_result, vm_result, released);
        return 3;
    }
    if (count != HOST_VM_INFO64_REV1_COUNT) {
        printf("{\"status\":\"failed\",\"stage\":\"shape\",\"received_words\":%u,\"requested_words\":%u}\n",
               (unsigned)count, (unsigned)HOST_VM_INFO64_REV1_COUNT);
        return 3;
    }
    if (page_size == 0 || (page_size & (page_size - 1)) != 0 || stats.speculative_count > stats.free_count) {
        printf("{\"status\":\"failed\",\"stage\":\"units\",\"page_size\":%" PRIu64 ",\"free\":%u,\"speculative\":%u}\n",
               (uint64_t)page_size, (unsigned)stats.free_count, (unsigned)stats.speculative_count);
        return 3;
    }
    uint64_t pages = (uint64_t)stats.active_count + stats.inactive_count + stats.free_count;
    if (pages > UINT64_MAX / page_size || pages * page_size > total) {
        printf("{\"status\":\"failed\",\"stage\":\"bounds\",\"total\":%" PRIu64 ",\"pages\":%" PRIu64 ",\"page_size\":%" PRIu64 "}\n", total, pages, (uint64_t)page_size);
        return 3;
    }
    printf("{\"status\":\"passed\",\"calls\":%u,\"total\":%" PRIu64
           ",\"page_size\":%" PRIu64 ",\"active\":%u,\"inactive\":%u,"
           "\"free\":%u,\"speculative\":%u,\"available\":%" PRIu64
           ",\"requested_words\":%u,\"returned_words\":%u,"
           "\"sdk_struct_size\":%zu,\"rev1_prefix_bytes\":152,\"released_host\":true}\n",
           calls, total, (uint64_t)page_size, (unsigned)stats.active_count,
           (unsigned)stats.inactive_count, (unsigned)stats.free_count,
           (unsigned)stats.speculative_count, pages * page_size,
           (unsigned)HOST_VM_INFO64_REV1_COUNT, (unsigned)count, sizeof(stats));
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
