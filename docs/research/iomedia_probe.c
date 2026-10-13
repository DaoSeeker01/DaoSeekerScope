/* Independent public-SDK probe, MIT. No disk contents or identifiers queried. */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/storage/IOMedia.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <unistd.h>

_Static_assert(sizeof(io_object_t) == 4, "IOKit handles are 32-bit");
_Static_assert(sizeof(SInt64) == 8, "capacity conversion is signed 64-bit");

static int probe(unsigned *scanned, unsigned *whole, unsigned *positive) {
    CFMutableDictionaryRef matching = IOServiceMatching(kIOMediaClass);
    if (matching == NULL) return 3;
    io_iterator_t iterator = 0;
    /* This call consumes the matching dictionary even on failure. */
    kern_return_t status = IOServiceGetMatchingServices(0, matching, &iterator);
    if (status != KERN_SUCCESS) {
        if (iterator != 0) IOObjectRelease(iterator);
        return 3;
    }
    int result = 0;
    *scanned = *whole = *positive = 0;
    if (iterator == 0) return 3; /* Empty is legitimate, but insufficient evidence. */
    for (;;) {
        io_object_t object = IOIteratorNext(iterator);
        if (object == 0) {
            if (!IOIteratorIsValid(iterator)) result = 3;
            break;
        }
        if (++*scanned > 4096) {
            IOObjectRelease(object);
            result = 3;
            break;
        }
        CFTypeRef flag = IORegistryEntryCreateCFProperty(object, CFSTR(kIOMediaWholeKey), NULL, 0);
        if (flag == NULL || CFGetTypeID(flag) != CFBooleanGetTypeID()) {
            if (flag != NULL) CFRelease(flag);
            IOObjectRelease(object);
            result = 3;
            break;
        }
        bool is_whole = CFBooleanGetValue((CFBooleanRef)flag);
        CFRelease(flag);
        if (is_whole) {
            if (++*whole > 128) {
                IOObjectRelease(object);
                result = 3;
                break;
            }
            CFTypeRef size = IORegistryEntryCreateCFProperty(object, CFSTR(kIOMediaSizeKey), NULL, 0);
            SInt64 capacity = -1;
            if (size != NULL && CFGetTypeID(size) == CFNumberGetTypeID()
                && !CFNumberIsFloatType((CFNumberRef)size)
                && CFNumberGetValue((CFNumberRef)size, kCFNumberSInt64Type, &capacity)
                && capacity >= 0) {
                if (capacity > 0) ++*positive;
            }
            if (size != NULL) CFRelease(size);
        }
        IOObjectRelease(object);
    }
    IOObjectRelease(iterator);
    if (*positive == 0) result = 3;
    return result;
}

int main(void) {
    /* CI executes as an ordinary account; no identity value is written. */
    if (geteuid() == 0) return 3;
    unsigned scanned = 0, whole = 0, positive = 0;
    for (unsigned cycle = 0; cycle < 110; ++cycle) {
        if (probe(&scanned, &whole, &positive) != 0) return 3;
    }
    printf("{\"overall\":\"passed\",\"source\":\"iokit\",\"effective_uid_is_root\":false,"
           "\"query_cycles\":110,\"media_scanned_last\":%u,\"whole_last\":%u,"
           "\"positive_capacities_last\":%u,\"names_queried\":false}\n", scanned, whole, positive);
    return 0;
}
