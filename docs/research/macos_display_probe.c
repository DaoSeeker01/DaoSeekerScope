/* Independent public Core Graphics SDK probe, MIT. No names or IDs exported. */
#include <CoreGraphics/CoreGraphics.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>

_Static_assert(sizeof(CGDirectDisplayID) == 4, "display token width");
_Static_assert(sizeof(CGError) == 4, "CGError width");
_Static_assert(sizeof(size_t) == 8, "64-bit macOS SDK");
_Static_assert(kCGErrorIllegalArgument == 1001 && kCGErrorInvalidConnection == 1002 &&
    kCGErrorInvalidContext == 1003 && kCGErrorCannotComplete == 1004 &&
    kCGErrorNotImplemented == 1006 && kCGErrorRangeCheck == 1007 &&
    kCGErrorTypeCheck == 1008 && kCGErrorInvalidOperation == 1010 &&
    kCGErrorNoneAvailable == 1011, "Rust projection CGError constants");

enum { slots = 1025, limit = 128, invalid = -1, changed = -2 };
struct pixels { size_t width, height; int state; };
static int compare(const void *left, const void *right) {
    CGDirectDisplayID a = *(const CGDirectDisplayID *)left;
    CGDirectDisplayID b = *(const CGDirectDisplayID *)right;
    return (a > b) - (a < b);
}
static int active(CGDirectDisplayID ids[slots], uint32_t *count) {
    CGError code = CGGetActiveDisplayList(slots, ids, count);
    if (code != kCGErrorSuccess) return code;
    if (*count >= slots || *count > limit) return invalid;
    for (uint32_t i = 0; i < *count; i++) {
        if (ids[i] == 0) return invalid;
        for (uint32_t j = 0; j < i; j++) if (ids[j] == ids[i]) return invalid;
    }
    return 0;
}
static int collect(struct pixels result[limit], uint32_t *count) {
    for (int attempt = 0; attempt < 3; attempt++) {
        CGDirectDisplayID first[slots] = {0}, last[slots] = {0};
        uint32_t end_count = 0;
        int code = active(first, count);
        if (code != 0) return code;
        for (uint32_t i = 0; i < *count; i++) {
            CGDisplayModeRef mode = CGDisplayCopyDisplayMode(first[i]);
            result[i] = (struct pixels){0, 0, 1}; /* NULL: temporarily unavailable */
            if (mode != NULL) {
                size_t w = CGDisplayModeGetPixelWidth(mode), h = CGDisplayModeGetPixelHeight(mode);
                CGDisplayModeRelease(mode);
                if (w == 0 || h == 0 || w > UINT32_MAX || h > UINT32_MAX)
                    result[i].state = 2; /* invalid dimensions, never fabricated zero */
                else result[i] = (struct pixels){w, h, 0};
            }
        }
        code = active(last, &end_count);
        if (code != 0) return code;
        qsort(first, *count, sizeof(*first), compare);
        qsort(last, end_count, sizeof(*last), compare);
        bool same = *count == end_count;
        for (uint32_t i = 0; same && i < *count; i++) same = first[i] == last[i];
        if (same) return 0;
    }
    return changed;
}
int main(void) {
    struct pixels result[limit] = {{0}};
    uint32_t count = 0;
    int code = collect(result, &count);
    printf("{\"status\":%d,\"entries\":", code);
    if (code != 0) { puts("null,\"dimensions\":null}"); return 0; }
    printf("%" PRIu32 ",\"dimensions\":[", count);
    for (uint32_t i = 0; i < count; i++) {
        if (i != 0) putchar(',');
        if (result[i].state == 0) printf("{\"width\":%zu,\"height\":%zu,\"reason\":null}", result[i].width, result[i].height);
        else printf("{\"width\":null,\"height\":null,\"reason\":\"%s\"}", result[i].state == 1 ? "temporarily_unavailable" : "invalid_data");
    }
    puts("]}");
    return 0;
}
