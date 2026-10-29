/* Native C measurements, independent of the Rust layout probe. */
#include "../../bindings/daoseeker_scope.h"
#include <stdio.h>
#include <string.h>

int main(void) {
    uint32_t (*version)(void) = dsc_abi_version;
    int32_t (*collect)(const dsc_options *, dsc_buffer *) = dsc_collect_json;
    int32_t (*release)(dsc_buffer *) = dsc_buffer_free;
    const char *(*error)(void) = dsc_last_error;
    dsc_buffer empty = {0};
    /* Exercise all four exported symbols without starting a collector. */
    if (collect(NULL, NULL) != DSC_INVALID_ARGUMENT ||
        strcmp(error(), "invalid argument") != 0 || release(&empty) != DSC_OK ||
        strcmp(error(), "") != 0) {
        return 2;
    }
    printf("{\"abi_version\":%u,\"pointer_bytes\":%zu,"
           "\"options\":{\"size\":%zu,\"alignment\":%zu,\"offsets\":[%zu,%zu,%zu,%zu,%zu]},"
           "\"buffer\":{\"size\":%zu,\"alignment\":%zu,\"offsets\":[%zu,%zu,%zu]},"
           "\"status_codes\":[%d,%d,%d,%d,%d,%d,%d,%d,%d,%d]}\n",
           (unsigned)version(), sizeof(void *), sizeof(dsc_options), _Alignof(dsc_options),
           offsetof(dsc_options, size), offsetof(dsc_options, version),
           offsetof(dsc_options, flags), offsetof(dsc_options, timeout_ms),
           offsetof(dsc_options, max_entries), sizeof(dsc_buffer), _Alignof(dsc_buffer),
           offsetof(dsc_buffer, data), offsetof(dsc_buffer, len), offsetof(dsc_buffer, token),
           DSC_OK, DSC_INVALID_ARGUMENT, DSC_UNSUPPORTED_PLATFORM, DSC_TIMEOUT,
           DSC_CANCELLED, DSC_BUSY, DSC_BACKEND_FAILURE, DSC_RESOURCE_LIMIT,
           DSC_PANIC, DSC_INVALID_BUFFER);
    return ferror(stdout) ? 1 : 0;
}
