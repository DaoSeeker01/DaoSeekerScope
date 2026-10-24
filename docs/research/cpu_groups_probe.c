/* Independent SDK group sampler. Only owned worker threads change affinity. */
#define _WIN32_WINNT 0x0601
#include <windows.h>
#include <stddef.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#define MAX_GROUPS 16
_Static_assert(sizeof(void *) == 8, "64-bit group probe");
_Static_assert(sizeof(PROCESSOR_GROUP_INFO) == 48, "group info size");
_Static_assert(offsetof(PROCESSOR_GROUP_INFO, ActiveProcessorMask) == 40, "mask offset");
_Static_assert(offsetof(GROUP_RELATIONSHIP, GroupInfo) == 24, "array offset");
_Static_assert(offsetof(SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX, Group) == 8, "union offset");
typedef union { uint64_t align; unsigned char bytes[1024]; } BUFFER;
typedef struct { uint64_t idle, kernel, user; } TIMES;
typedef struct { WORD count; KAFFINITY masks[MAX_GROUPS]; BYTE processors[MAX_GROUPS]; } TOPOLOGY;
typedef struct { int ok; TOPOLOGY topology; TIMES times[MAX_GROUPS]; } RESULT;
static uint64_t ticks(FILETIME value) { return ((uint64_t)value.dwHighDateTime << 32) | value.dwLowDateTime; }
static unsigned bits(KAFFINITY mask) { unsigned n=0; while (mask) { n+=(unsigned)(mask & 1);mask>>=1; } return n; }
static int topology(TOPOLOGY *out) {
    BUFFER buffer={0}; DWORD length=sizeof(buffer);
    if (!GetLogicalProcessorInformationEx(RelationGroup,(PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX)buffer.bytes,&length)) return 0;
    if (length<32 || length>sizeof(buffer)) return 0;
    PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX record=(PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX)buffer.bytes;
    WORD count=record->Group.ActiveGroupCount;
    if (record->Relationship!=RelationGroup || record->Size!=length || count==0 || count>MAX_GROUPS || count>record->Group.MaximumGroupCount || length!=32+48*(DWORD)count) return 0;
    out->count=count;
    for (WORD g=0;g<count;++g) {
        PROCESSOR_GROUP_INFO *info=(PROCESSOR_GROUP_INFO *)(buffer.bytes+32+48*(size_t)g);
        if (!info->MaximumProcessorCount || info->MaximumProcessorCount>64 || !info->ActiveProcessorCount || info->ActiveProcessorCount>info->MaximumProcessorCount || bits(info->ActiveProcessorMask)!=info->ActiveProcessorCount) return 0;
        if (info->MaximumProcessorCount<64 && (info->ActiveProcessorMask>>info->MaximumProcessorCount)!=0) return 0;
        out->masks[g]=info->ActiveProcessorMask;out->processors[g]=info->ActiveProcessorCount;
    }
    return 1;
}
static DWORD WINAPI worker(LPVOID context) {
    RESULT *result=context;TOPOLOGY after={0};
    if (!topology(&result->topology)) return 3;
    for (WORD g=0;g<result->topology.count;++g) {
        GROUP_AFFINITY affinity={0};affinity.Group=g;affinity.Mask=result->topology.masks[g];
        FILETIME idle={0},kernel={0},user={0};
        if (!SetThreadGroupAffinity(GetCurrentThread(),&affinity,NULL)) return 3;
        if (!GetSystemTimes(&idle,&kernel,&user)) return 3;
        result->times[g]=(TIMES){ticks(idle),ticks(kernel),ticks(user)};
        if (result->times[g].idle>result->times[g].kernel) return 3;
    }
    if (!topology(&after) || after.count!=result->topology.count) return 3;
    for (WORD g=0;g<after.count;++g)
        if (after.masks[g]!=result->topology.masks[g] || after.processors[g]!=result->topology.processors[g]) return 3;
    result->ok=1;return 0;
}
static int sample(unsigned calls) {
    RESULT result={0};GROUP_AFFINITY before={0},after={0};
    if (!GetThreadGroupAffinity(GetCurrentThread(),&before)) return 3;
    HANDLE thread=CreateThread(NULL,0,worker,&result,0,NULL);
    if (!thread) return 3;
    /* A timeout exits this owned probe process, so its worker cannot outlive result. */
    if (WaitForSingleObject(thread,4000)!=WAIT_OBJECT_0) ExitProcess(3);
    if (!CloseHandle(thread) || !result.ok || !GetThreadGroupAffinity(GetCurrentThread(),&after)) return 3;
    if (before.Group!=after.Group || before.Mask!=after.Mask) return 3;
    unsigned processors=0;for (WORD g=0;g<result.topology.count;++g) processors+=result.topology.processors[g];
    printf("{\"status\":\"passed\",\"calls\":%u,\"groups\":%u,\"processors\":%u,\"caller_affinity_unchanged\":true,\"group_info_size\":48,\"group_info_offset\":32,\"samples\":[",calls,(unsigned)result.topology.count,processors);
    for (WORD g=0;g<result.topology.count;++g) {
        TIMES t=result.times[g];
        printf("%s{\"processors\":%u,\"mask\":%" PRIu64 ",\"idle\":%" PRIu64 ",\"kernel\":%" PRIu64 ",\"user\":%" PRIu64 "}",g?",":"",(unsigned)result.topology.processors[g],(uint64_t)result.topology.masks[g],t.idle,t.kernel,t.user);
    }
    printf("]}\n");fflush(stdout);return 0;
}
int main(void) {
    char command[16];unsigned calls=1;
    if (sample(calls)!=0) return 3;
    for (unsigned i=0;i<8;++i) {
        if (!fgets(command,sizeof(command),stdin) || strcmp(command,"quit\n")==0) return 0;
        if (strcmp(command,"sample\n")!=0) return 2;
        if (sample(++calls)!=0) return 3;
    }
    return 0;
}
