/* Build and inspect only: this executable is not run by the PE oracle. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

int main(void) {
    return GetSystemMetrics(SM_CXSCREEN) < 0 ? 1 : 0;
}
