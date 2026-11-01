/* Read only documented power-source keys; never print names or identifiers. */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/ps/IOPSKeys.h>
#include <IOKit/ps/IOPowerSources.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>

static CFTypeRef value(CFDictionaryRef object, CFStringRef key) {
    return CFDictionaryGetValue(object, key);
}
static int equal(CFTypeRef object, CFStringRef text) {
    return object && CFGetTypeID(object) == CFStringGetTypeID() && CFEqual(object, text);
}
static int number(CFDictionaryRef object, CFStringRef key, int64_t *out) {
    CFTypeRef item = value(object, key);
    if (!item) return 0;
    if (CFGetTypeID(item) != CFNumberGetTypeID() || CFNumberIsFloatType((CFNumberRef)item)) return 2;
    return CFNumberGetValue((CFNumberRef)item, kCFNumberSInt64Type, out) ? 1 : 2;
}
int main(void) {
    CFTypeRef blob = IOPSCopyPowerSourcesInfo();
    CFArrayRef list = blob ? IOPSCopyPowerSourcesList(blob) : NULL;
    if (!list) {
        puts("{\"status\":\"unavailable\",\"source_count\":0,\"records\":[]}");
        if (blob) CFRelease(blob);
        return 0;
    }
    CFIndex count = CFArrayGetCount(list);
    if (count < 0 || count > 256) {
        printf("{\"status\":\"invalid_count\",\"source_count\":%ld,\"records\":[]}\n", (long)count);
        CFRelease(list);
        CFRelease(blob);
        return 0;
    }
    printf("{\"status\":\"ok\",\"source_count\":%ld,\"records\":[", (long)count);
    for (CFIndex i = 0; i < count; i++) {
        CFTypeRef handle = CFArrayGetValueAtIndex(list, i);
        CFDictionaryRef description = IOPSGetPowerSourceDescription(blob, handle);
        int type = -2, present = -1, current_kind = 0, maximum_kind = 0, power = 0;
        int64_t current = 0, maximum = 0;
        if (description) {
            CFTypeRef kind = value(description, CFSTR(kIOPSTypeKey));
            type = !kind || CFGetTypeID(kind) != CFStringGetTypeID() ? -1
                : equal(kind, CFSTR(kIOPSInternalBatteryType)) ? 1
                : equal(kind, CFSTR(kIOPSUPSType)) ? 0 : 2;
            if (type == 1) {
                CFTypeRef found = value(description, CFSTR(kIOPSIsPresentKey));
                present = !found ? -1 : CFGetTypeID(found) != CFBooleanGetTypeID() ? -2
                    : CFBooleanGetValue((CFBooleanRef)found) ? 1 : 0;
                if (present == 1) {
                    current_kind = number(description, CFSTR(kIOPSCurrentCapacityKey), &current);
                    maximum_kind = number(description, CFSTR(kIOPSMaxCapacityKey), &maximum);
                    CFTypeRef state = value(description, CFSTR(kIOPSPowerSourceStateKey));
                    power = !state ? 0 : equal(state, CFSTR(kIOPSACPowerValue)) ? 1
                        : equal(state, CFSTR(kIOPSBatteryPowerValue)) ? 2
                        : equal(state, CFSTR(kIOPSOffLineValue)) ? 3 : 4;
                }
            }
        }
        printf("%s{\"type\":%d,\"present\":%d,\"current_kind\":%d,\"current\":%" PRId64
               ",\"maximum_kind\":%d,\"maximum\":%" PRId64 ",\"power\":%d}",
               i ? "," : "", type, present, current_kind, current, maximum_kind, maximum, power);
    }
    puts("]}");
    CFRelease(list);
    CFRelease(blob);
    return 0;
}
