// C ABI names used by the portable Dyn runtime support. The import-address
// slots are supplied by windows_x86_64_start.S without an external SDK.
.text
.global GetCurrentThreadId
GetCurrentThreadId:
    jmp *__imp_GetCurrentThreadId(%rip)
.global GetStdHandle
.set GetStdHandle, dyn_stdio_handle
.global WriteFile
.set WriteFile, dyn_stdio_write

