/* Independent Windows SDK CCD probe. No names, IDs, paths or EDID are printed. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>

static DISPLAYCONFIG_PATH_INFO paths[1024];
static DISPLAYCONFIG_MODE_INFO modes[4096];
static int whitespace(WCHAR c) {
    return (c >= 9 && c <= 13) || c == 32 || c == 0x85 || c == 0xa0 ||
        c == 0x1680 || (c >= 0x2000 && c <= 0x200a) || c == 0x2028 ||
        c == 0x2029 || c == 0x202f || c == 0x205f || c == 0x3000;
}
static int valid_name(const DISPLAYCONFIG_TARGET_DEVICE_NAME *name) {
    size_t n = 0;
    int nonblank = 0;
    if (!name->flags.friendlyNameFromEdid) return 0;
    while (n < 64 && name->monitorFriendlyDeviceName[n] != 0) {
        WCHAR c = name->monitorFriendlyDeviceName[n++];
        if (c < 32 || (c >= 127 && c <= 159)) return 0;
        if (!whitespace(c)) nonblank = 1;
    }
    return n > 0 && n < 64 && nonblank &&
        WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS,
            name->monitorFriendlyDeviceName, (int)n, NULL, 0, NULL, NULL) > 0;
}
static int dimensions(const DISPLAYCONFIG_PATH_INFO *path, UINT32 count, UINT32 *w, UINT32 *h) {
    UINT32 index, absent;
    const DISPLAYCONFIG_MODE_INFO *mode;
    if (path->flags & DISPLAYCONFIG_PATH_SUPPORT_VIRTUAL_MODE) {
        index = path->targetInfo.targetModeInfoIdx;
        absent = 0xffff;
    } else {
        index = path->targetInfo.modeInfoIdx;
        absent = 0xffffffff;
    }
    if (index == absent || index >= count) return 0;
    mode = &modes[index];
    if (mode->infoType != DISPLAYCONFIG_MODE_INFO_TYPE_TARGET ||
        mode->id != path->targetInfo.id ||
        mode->adapterId.LowPart != path->targetInfo.adapterId.LowPart ||
        mode->adapterId.HighPart != path->targetInfo.adapterId.HighPart) return 0;
    *w = mode->targetMode.targetVideoSignalInfo.activeSize.cx;
    *h = mode->targetMode.targetVideoSignalInfo.activeSize.cy;
    return *w > 0 && *h > 0;
}
int main(void) {
    const UINT32 flags = QDC_ONLY_ACTIVE_PATHS | QDC_VIRTUAL_MODE_AWARE;
    UINT32 p = 0, m = 0, i, names = 0, sizes = 0, attempt;
    LONG status = ERROR_INSUFFICIENT_BUFFER;
    for (attempt = 0; attempt < 3; attempt++) {
        status = GetDisplayConfigBufferSizes(flags, &p, &m);
        if (status != ERROR_SUCCESS) break;
        if (p > 1024 || m > 4096) { status = ERROR_INVALID_DATA; break; }
        if (p == 0) p = 1;
        if (m == 0) m = 1;
        {
            UINT32 capacity_p = p, capacity_m = m;
            status = QueryDisplayConfig(flags, &p, paths, &m, modes, NULL);
            if (status == ERROR_SUCCESS && (p > capacity_p || m > capacity_m))
                status = ERROR_INVALID_DATA;
        }
        if (status != ERROR_INSUFFICIENT_BUFFER) break;
    }
    if (status != ERROR_SUCCESS) {
        printf("{\"status\":%ld,\"entries\":null,\"names_available\":null,\"dimensions_available\":null,\"dimensions\":null}\n", status);
        return 0; /* Report actual access/driver state; never call it an empty display view. */
    }
    for (i = 0; i < p; i++) {
        DISPLAYCONFIG_TARGET_DEVICE_NAME name;
        UINT32 w = 0, h = 0;
        memset(&name, 0, sizeof(name));
        name.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME;
        name.header.size = sizeof(name);
        name.header.adapterId = paths[i].targetInfo.adapterId;
        name.header.id = paths[i].targetInfo.id;
        if (DisplayConfigGetDeviceInfo(&name.header) == ERROR_SUCCESS && valid_name(&name)) names++;
        if (dimensions(&paths[i], m, &w, &h)) sizes++;
    }
    printf("{\"status\":0,\"entries\":%u,\"names_available\":%u,\"dimensions_available\":%u,\"dimensions\":[", p, names, sizes);
    for (i = 0; i < p; i++) {
        UINT32 w = 0, h = 0;
        if (i != 0) putchar(',');
        if (dimensions(&paths[i], m, &w, &h)) printf("[%u,%u]", w, h);
        else fputs("null", stdout);
    }
    puts("]}");
    return 0;
}
