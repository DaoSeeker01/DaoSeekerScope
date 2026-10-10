#ifndef DAOSEEKER_SCOPE_H
#define DAOSEEKER_SCOPE_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* ABI v1, JSON Schema v1. Build library with panic=unwind.
 * All pointers must be live, aligned and valid for the call; invalid pointers
 * and concurrent mutation are caller UB and cannot be guarded by this API.
 * Thread safe across distinct structs. Calls can return BUSY.
 * Error text is redacted and thread-local, valid until next ABI call on thread.
 */
typedef struct {
    uint32_t size;       /* sizeof(dsc_options), exactly 20 in ABI v1 */
    uint32_t version;    /* 1 */
    uint32_t flags;      /* bit0 sensitive request, bit1 caller authorized */
    uint32_t timeout_ms; /* 1..60000 */
    uint32_t max_entries;/* 1..1024 */
} dsc_options;
typedef struct {
    const uint8_t *data; /* library-owned UTF-8; NOT NUL terminated; read len */
    size_t len;
    uint64_t token;      /* never reuse or modify; stale copies rejected */
} dsc_buffer;
enum dsc_status {
    DSC_OK=0, DSC_INVALID_ARGUMENT=1, DSC_UNSUPPORTED_PLATFORM=2,
    DSC_TIMEOUT=3, DSC_CANCELLED=4, DSC_BUSY=5, DSC_BACKEND_FAILURE=6,
    DSC_RESOURCE_LIMIT=7, DSC_PANIC=8, DSC_INVALID_BUFFER=9
};
uint32_t dsc_abi_version(void);
/* Zero initialize output. NULL options selects defaults.
 * NULL options shares a cached default collector between calls. Non-NULL options
 * creates a fresh collector per call: static data is reread and CPU sampling
 * has no prior baseline, so usage can be temporarily unavailable.
 * Success transfers no ownership to caller: call free once when done.
 * Failure leaves output unchanged. Max 64 live allocations, each <=1MiB.
 * Do not memcpy ownership, access after free, or free concurrently with reads.
 * Timeout bounds caller wait; a blocking OS call can keep a bounded worker alive.
 */
int32_t dsc_collect_json(const dsc_options *options, dsc_buffer *buffer);
/* Empty zero buffer is idempotent; stale nonzero copies return INVALID_BUFFER.
 * Success zeros the original struct. Input data pointer is never dereferenced. */
int32_t dsc_buffer_free(dsc_buffer *buffer);
const char *dsc_last_error(void);
#ifdef __cplusplus
}
#endif
#endif
