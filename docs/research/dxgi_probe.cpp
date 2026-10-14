// SPDX-License-Identifier: MIT
#include <windows.h>
#include <dxgi.h>
#include <memory>
#include <cstdio>
struct ReleaseCom { template<class T> void operator()(T* pointer) const { if (pointer) pointer->Release(); } };
int main() {
    IDXGIFactory1* raw_factory = nullptr;
    HRESULT factory_result = CreateDXGIFactory1(IID_PPV_ARGS(&raw_factory));
    std::unique_ptr<IDXGIFactory1, ReleaseCom> factory(raw_factory);
    if (FAILED(factory_result) || !factory) return 1;
    unsigned total = 0, hardware = 0, software = 0, named = 0;
    unsigned long long capacities[128] = {};
    bool completed = false;
    for (unsigned index = 0; index <= 128; ++index) {
        IDXGIAdapter1* raw_adapter = nullptr;
        HRESULT result = factory->EnumAdapters1(index, &raw_adapter);
        std::unique_ptr<IDXGIAdapter1, ReleaseCom> adapter(raw_adapter);
        if (result == DXGI_ERROR_NOT_FOUND) { completed = true; break; }
        if (FAILED(result) || !adapter) return 2;
        if (index == 128) return 3;
        ++total;
        DXGI_ADAPTER_DESC1 desc = {};
        if (FAILED(adapter->GetDesc1(&desc))) return 4;
        if ((desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) != 0) { ++software; continue; }
        bool terminated = false;
        for (unsigned j = 0; j < 128; ++j) if (desc.Description[j] == 0) { terminated = true; break; }
        if (terminated && desc.Description[0] != 0) ++named;
        capacities[hardware++] = static_cast<unsigned long long>(desc.DedicatedVideoMemory);
        // Vendor/device/subsystem IDs and AdapterLuid are not inspected or retained.
    }
    if (!completed) return 5;
    HANDLE token = nullptr;
    TOKEN_ELEVATION elevation = {};
    DWORD bytes = 0;
    bool token_known = false;
    if (OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) {
        token_known = GetTokenInformation(token, TokenElevation, &elevation, sizeof(elevation), &bytes) != 0;
        CloseHandle(token);
    }
    std::printf("{\"source\":\"dxgi\",\"enumeration_complete\":true,\"adapters_seen\":%u,\"non_software_adapters\":%u,\"software_skipped\":%u,\"description_present_count\":%u,\"identifiers_retained\":false,\"token_elevated\":%s,\"dedicated_video_memory_bytes\":[", total, hardware, software, named, token_known ? (elevation.TokenIsElevated ? "true" : "false") : "null");
    for (unsigned i = 0; i < hardware; ++i) std::printf("%s%llu", i ? "," : "", capacities[i]);
    std::puts("]}");
    return 0;
}
