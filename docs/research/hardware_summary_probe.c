/* Independent read-only SDK probe: exactly six non-identifier value names. */
#define _WIN32_WINNT 0x0600
#include <windows.h>
#include <stdio.h>
#include <string.h>
_Static_assert(sizeof(WCHAR)==2,"UTF-16 SDK units");
_Static_assert(sizeof(WCHAR[2048])==4096,"fixed SDK buffer");

static const WCHAR *names[]={L"SystemManufacturer",L"SystemProductName",L"BaseBoardManufacturer",L"BaseBoardProduct",L"BIOSVendor",L"BIOSVersion"};
static const char *fields[]={"system.device.vendor","system.device.model","system.motherboard.vendor","system.motherboard.model","system.firmware.vendor","system.firmware.version"};
static const WCHAR key[]=L"HARDWARE\\DESCRIPTION\\System\\BIOS";
static void quoted(const char *data, int length) {
    putchar('"');
    for (int i=0;i<length;++i) {
        unsigned char ch=(unsigned char)data[i];
        if (ch=='"' || ch=='\\') { putchar('\\');putchar(ch); }
        else if (ch<32) printf("\\u%04x",(unsigned)ch);
        else putchar(ch);
    }
    putchar('"');
}
static int elevation(void) {
    HANDLE token=NULL;TOKEN_ELEVATION info={0};DWORD bytes=0;
    if (!OpenProcessToken(GetCurrentProcess(),TOKEN_QUERY,&token)) return -1;
    BOOL ok=GetTokenInformation(token,TokenElevation,&info,sizeof(info),&bytes);
    BOOL closed=CloseHandle(token);
    if (!ok || !closed || bytes!=sizeof(info)) return -1;
    return info.TokenIsElevated?1:0;
}
static void sample(unsigned calls,int elevated) {
    printf("{\"status\":\"passed\",\"calls\":%u,\"queries\":%u,\"buffer_bytes\":4096,\"token_elevated\":",calls,calls*6);
    printf("%s,\"fields\":{",elevated<0?"null":(elevated?"true":"false"));
    for (unsigned i=0;i<6;++i) {
        WCHAR buffer[2048]={0};DWORD kind=0,bytes=sizeof(buffer);
        LSTATUS status=RegGetValueW(HKEY_LOCAL_MACHINE,key,names[i],RRF_RT_REG_SZ|RRF_NOEXPAND|RRF_ZEROONFAILURE,&kind,buffer,&bytes);
        printf("%s\"%s\":{\"code\":%lu,\"kind\":",i?",":"",fields[i],(unsigned long)status);
        if (status!=ERROR_SUCCESS) { printf("null,\"bytes\":null,\"value\":null}");continue; }
        printf("%lu,\"bytes\":%lu,\"value\":",(unsigned long)kind,(unsigned long)bytes);
        if (kind!=REG_SZ || bytes<2 || bytes>sizeof(buffer) || bytes%2 || buffer[bytes/2-1]!=0) { printf("null}");continue; }
        int units=(int)(bytes/2-1);char utf8[8192];int length=0;
        if (units>0) length=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,buffer,units,utf8,sizeof(utf8),NULL,NULL);
        if (units>0 && length==0) printf("null");else quoted(utf8,length);
        putchar('}');
    }
    printf("}}\n");fflush(stdout);
}
int main(void) {
    int elevated=elevation();unsigned calls=1;char command[16];sample(calls,elevated);
    for (unsigned i=0;i<8;++i) {
        if (!fgets(command,sizeof(command),stdin) || strcmp(command,"quit\n")==0) return 0;
        if (strcmp(command,"sample\n")!=0) return 2;
        sample(++calls,elevated);
    }
    return 0;
}
