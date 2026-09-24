#include <windows.h>
#include <stddef.h>
/* Values used by the Dyn Win64 adapter, checked against the target SDK. */
_Static_assert(sizeof(STARTUPINFOEXW) == 112, "STARTUPINFOEXW size");
_Static_assert(offsetof(STARTUPINFOEXW, lpAttributeList) == 104, "attribute offset");
_Static_assert(offsetof(STARTUPINFOW, dwFlags) == 60, "flags offset");
_Static_assert(offsetof(STARTUPINFOW, hStdInput) == 80, "stdin offset");
_Static_assert(sizeof(PROCESS_INFORMATION) == 24, "process information size");
_Static_assert(PROC_THREAD_ATTRIBUTE_HANDLE_LIST == 131074, "handle list attribute");
_Static_assert(CREATE_UNICODE_ENVIRONMENT + EXTENDED_STARTUPINFO_PRESENT == 525312, "creation flags");
