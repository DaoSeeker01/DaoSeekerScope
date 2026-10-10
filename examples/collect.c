#include "../bindings/daoseeker_scope.h"
#include <stdio.h>
int main(void) {
    dsc_buffer buffer = {0};
    if (dsc_abi_version() != 1) return 1;
    int32_t code = dsc_collect_json(NULL, &buffer);
    if (code != DSC_OK) { fprintf(stderr,"%s\n",dsc_last_error()); return 2; }
    if (!buffer.data || !buffer.len || !buffer.token) {
        (void)dsc_buffer_free(&buffer);
        return 3;
    }
    if (fwrite(buffer.data,1,buffer.len,stdout) != buffer.len) {
        (void)dsc_buffer_free(&buffer);
        return 4;
    }
    dsc_buffer stale = buffer;
    if (dsc_buffer_free(&buffer) != DSC_OK) return 5;
    if (buffer.data || buffer.len || buffer.token) return 6;
    if (dsc_buffer_free(&buffer) != DSC_OK) return 7;
    if (dsc_buffer_free(&stale) != DSC_INVALID_BUFFER) return 8;
    return 0;
}
