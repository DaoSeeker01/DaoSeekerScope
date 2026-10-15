// Independent public SDK projection. Output contains no product names or IDs.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    @autoreleasepool {
        NSArray<id<MTLDevice>> *devices = MTLCopyAllDevices();
        if (devices == nil || devices.count > 128) return 1;
        NSUInteger names = 0, unified = 0;
        for (id<MTLDevice> device in devices) {
            NSString *name = device.name;
            char bytes[4097] = {0};
            if (name.length > 0 && name.length <= 1024 &&
                [name getCString:bytes maxLength:sizeof(bytes) encoding:NSUTF8StringEncoding]) {
                NSString *decoded = [[NSString alloc] initWithBytes:bytes
                    length:strlen(bytes) encoding:NSUTF8StringEncoding];
                // Match Rust's C0/C1 controls.
                NSMutableCharacterSet *c0c1 = [NSMutableCharacterSet characterSetWithRange:NSMakeRange(0, 32)];
                [c0c1 addCharactersInRange:NSMakeRange(127, 33)];
                if (decoded != nil && decoded.length == name.length &&
                    [decoded stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet].length > 0 &&
                    [decoded rangeOfCharacterFromSet:c0c1].location == NSNotFound) names++;
            }
            if (@available(macOS 10.15, *)) {
                if (device.hasUnifiedMemory) unified++;
            }
        }
        printf("{\"entries\":%lu,\"names_available\":%lu,\"unified_memory\":%lu,\"dedicated_memory_unsupported\":%lu}\n",
            (unsigned long)devices.count, (unsigned long)names,
            (unsigned long)unified, (unsigned long)(devices.count - unified));
    }
    return 0;
}
