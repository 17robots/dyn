.text
#ifndef DYN_SHARED
.global dyn_start
dyn_start:
    bl main
    b ExitProcess
#endif
.global dyn_panic
dyn_panic:
    stp x0, x1, [sp, #-16]!
    bl dyn_unwind_begin
    ldp x0, x1, [sp]
    bl dyn_panic_write
    bl dyn_trace_dump
    mov x0, #101
    b ExitProcess
.global dyn_unwind_set
dyn_unwind_set:
    stp x19, x20, [x0, #8]
    stp x21, x22, [x0, #24]
    stp x23, x24, [x0, #40]
    stp x25, x26, [x0, #56]
    stp x27, x28, [x0, #72]
    stp x29, x30, [x0, #88]
    mov x1, sp
    str x1, [x0, #104]
    // The Apple arm64 ABI preserves the low 64 bits of v8-v15.
    stp d8, d9, [x0, #112]
    stp d10, d11, [x0, #128]
    stp d12, d13, [x0, #144]
    stp d14, d15, [x0, #160]
    mov x0, #0
    ret

.global dyn_unwind_jump
dyn_unwind_jump:
    mov x9, x0
    ldp x19, x20, [x9, #8]
    ldp x21, x22, [x9, #24]
    ldp x23, x24, [x9, #40]
    ldp x25, x26, [x9, #56]
    ldp x27, x28, [x9, #72]
    ldp x29, x30, [x9, #88]
    ldr x10, [x9, #104]
    ldp d8, d9, [x9, #112]
    ldp d10, d11, [x9, #128]
    ldp d12, d13, [x9, #144]
    ldp d14, d15, [x9, #160]
    mov sp, x10
    mov x0, #1
    ret


// Darwin arm64 syscall shim. Dyn passes Darwin's unclassed syscall number;
.global dyn_atomic_load_u32
dyn_atomic_load_u32:
    ldar w0, [x0]
    ret
.global dyn_atomic_store_u32
dyn_atomic_store_u32:
    stlr w1, [x0]
    ret
.global dyn_atomic_exchange_u32
dyn_atomic_exchange_u32:
1:  ldaxr w2, [x0]
    stlxr w3, w1, [x0]
    cbnz w3, 1b
    mov w0, w2
    ret
.global dyn_atomic_fetch_add_u32
dyn_atomic_fetch_add_u32:
1:  ldaxr w2, [x0]
    add w4, w2, w1
    stlxr w3, w4, [x0]
    cbnz w3, 1b
    mov w0, w2
    ret
.global dyn_atomic_compare_exchange_u32
dyn_atomic_compare_exchange_u32:
1:  ldaxr w3, [x0]
    cmp w3, w1
    b.ne 2f
    stlxr w4, w2, [x0]
    cbnz w4, 1b
    mov w0, #1
    ret
2:  clrex
    mov w0, #0
    ret
.global dyn_atomic_load_u64
dyn_atomic_load_u64:
    ldar x0, [x0]
    ret
.global dyn_atomic_store_u64
dyn_atomic_store_u64:
    stlr x1, [x0]
    ret
.global dyn_atomic_exchange_u64
dyn_atomic_exchange_u64:
1:  ldaxr x2, [x0]
    stlxr w3, x1, [x0]
    cbnz w3, 1b
    mov x0, x2
    ret
.global dyn_atomic_fetch_add_u64
dyn_atomic_fetch_add_u64:
1:  ldaxr x2, [x0]
    add x4, x2, x1
    stlxr w3, x4, [x0]
    cbnz w3, 1b
    mov x0, x2
    ret
.global dyn_atomic_compare_exchange_u64
dyn_atomic_compare_exchange_u64:
1:  ldaxr x3, [x0]
    cmp x3, x1
    b.ne 2f
    stlxr w4, x2, [x0]
    cbnz w4, 1b
    mov w0, #1
    ret
2:  clrex
    mov w0, #0
    ret

.global dyn_win_thread_spawn
dyn_win_thread_spawn:
    mov x5, x3
    mov x3, x2
    mov x2, x1
    mov x1, x0
    mov x0, #0
    mov x4, #0
    b CreateThread
.global dyn_win_close_handle
dyn_win_close_handle:
    adrp x16, __imp_CloseHandle
    ldr x16, [x16, :lo12:__imp_CloseHandle]
    br x16
.global dyn_win_wait
dyn_win_wait:
    adrp x16, __imp_WaitForSingleObject
    ldr x16, [x16, :lo12:__imp_WaitForSingleObject]
    br x16
.global dyn_crypto_random
dyn_crypto_random:
    adrp x16, __imp_BCryptGenRandom
    ldr x16, [x16, :lo12:__imp_BCryptGenRandom]
    br x16
.global dyn_sync_wait
dyn_sync_wait:
    adrp x16, __imp_WaitOnAddress
    ldr x16, [x16, :lo12:__imp_WaitOnAddress]
    br x16
.global dyn_sync_single
dyn_sync_single:
    adrp x16, __imp_WakeByAddressSingle
    ldr x16, [x16, :lo12:__imp_WakeByAddressSingle]
    br x16
.global dyn_sync_all
dyn_sync_all:
    adrp x16, __imp_WakeByAddressAll
    ldr x16, [x16, :lo12:__imp_WakeByAddressAll]
    br x16
.global dyn_sync_error
dyn_sync_error:
    adrp x16, __imp_GetLastError
    ldr x16, [x16, :lo12:__imp_GetLastError]
    br x16
.global dyn_win_yield
dyn_win_yield:
    adrp x16, __imp_SwitchToThread
    ldr x16, [x16, :lo12:__imp_SwitchToThread]
    br x16
.global dyn_net_idle
dyn_net_idle:
    adrp x16, __imp_Sleep
    ldr x16, [x16, :lo12:__imp_Sleep]
    br x16
.global dyn_win_virtual_alloc
dyn_win_virtual_alloc:
    adrp x16, __imp_VirtualAlloc
    ldr x16, [x16, :lo12:__imp_VirtualAlloc]
    br x16
.global dyn_win_virtual_free
dyn_win_virtual_free:
    adrp x16, __imp_VirtualFree
    ldr x16, [x16, :lo12:__imp_VirtualFree]
    br x16
.global dyn_win_create_file
dyn_win_create_file:
    adrp x16, __imp_CreateFileA
    ldr x16, [x16, :lo12:__imp_CreateFileA]
    br x16
.global dyn_win_read_file
dyn_win_read_file:
    adrp x16, __imp_ReadFile
    ldr x16, [x16, :lo12:__imp_ReadFile]
    br x16
.global dyn_win_write_file
dyn_win_write_file:
    adrp x16, __imp_WriteFile
    ldr x16, [x16, :lo12:__imp_WriteFile]
    br x16
.global dyn_terminal_get_mode
dyn_terminal_get_mode:
    adrp x16, __imp_GetConsoleMode
    ldr x16, [x16, :lo12:__imp_GetConsoleMode]
    br x16
.global dyn_terminal_set_mode
dyn_terminal_set_mode:
    adrp x16, __imp_SetConsoleMode
    ldr x16, [x16, :lo12:__imp_SetConsoleMode]
    br x16
.global dyn_terminal_buffer_info
dyn_terminal_buffer_info:
    adrp x16, __imp_GetConsoleScreenBufferInfo
    ldr x16, [x16, :lo12:__imp_GetConsoleScreenBufferInfo]
    br x16
.global dyn_fs_map_create
dyn_fs_map_create:
    adrp x16, __imp_CreateFileMappingW
    ldr x16, [x16, :lo12:__imp_CreateFileMappingW]
    br x16
.global dyn_fs_map_view
dyn_fs_map_view:
    adrp x16, __imp_MapViewOfFile
    ldr x16, [x16, :lo12:__imp_MapViewOfFile]
    br x16
.global dyn_fs_map_release
dyn_fs_map_release:
    adrp x16, __imp_UnmapViewOfFile
    ldr x16, [x16, :lo12:__imp_UnmapViewOfFile]
    br x16
.global dyn_signal_console_handler
dyn_signal_console_handler:
    adrp x16, __imp_SetConsoleCtrlHandler
    ldr x16, [x16, :lo12:__imp_SetConsoleCtrlHandler]
    br x16
.global dyn_signal_create_event
dyn_signal_create_event:
    adrp x16, __imp_CreateEventW
    ldr x16, [x16, :lo12:__imp_CreateEventW]
    br x16
.global dyn_signal_set_event
dyn_signal_set_event:
    adrp x16, __imp_SetEvent
    ldr x16, [x16, :lo12:__imp_SetEvent]
    br x16
.global dyn_time_zone_information
dyn_time_zone_information:
    adrp x16, __imp_GetDynamicTimeZoneInformation
    ldr x16, [x16, :lo12:__imp_GetDynamicTimeZoneInformation]
    br x16
.global dyn_win_load_library
dyn_win_load_library:
    adrp x16, __imp_LoadLibraryA
    ldr x16, [x16, :lo12:__imp_LoadLibraryA]
    br x16
.global dyn_win_get_symbol
dyn_win_get_symbol:
    adrp x16, __imp_GetProcAddress
    ldr x16, [x16, :lo12:__imp_GetProcAddress]
    br x16
.global dyn_win_free_library
dyn_win_free_library:
    adrp x16, __imp_FreeLibrary
    ldr x16, [x16, :lo12:__imp_FreeLibrary]
    br x16
.global dyn_win_last_error
dyn_win_last_error:
    adrp x16, __imp_GetLastError
    ldr x16, [x16, :lo12:__imp_GetLastError]
    br x16
.global dyn_win_socket_startup
dyn_win_socket_startup:
    adrp x16, __imp_WSAStartup
    ldr x16, [x16, :lo12:__imp_WSAStartup]
    br x16
.global dyn_win_socket
dyn_win_socket:
    adrp x16, __imp_socket
    ldr x16, [x16, :lo12:__imp_socket]
    br x16
.global dyn_win_close_socket
dyn_win_close_socket:
    adrp x16, __imp_closesocket
    ldr x16, [x16, :lo12:__imp_closesocket]
    br x16
.global dyn_win_connect
dyn_win_connect:
    adrp x16, __imp_connect
    ldr x16, [x16, :lo12:__imp_connect]
    br x16
.global dyn_win_bind
dyn_win_bind:
    adrp x16, __imp_bind
    ldr x16, [x16, :lo12:__imp_bind]
    br x16
.global dyn_win_listen
dyn_win_listen:
    adrp x16, __imp_listen
    ldr x16, [x16, :lo12:__imp_listen]
    br x16
.global dyn_win_accept
dyn_win_accept:
    adrp x16, __imp_accept
    ldr x16, [x16, :lo12:__imp_accept]
    br x16
.global dyn_win_send
dyn_win_send:
    adrp x16, __imp_send
    ldr x16, [x16, :lo12:__imp_send]
    br x16
.global dyn_win_receive
dyn_win_receive:
    adrp x16, __imp_recv
    ldr x16, [x16, :lo12:__imp_recv]
    br x16
.global dyn_win_shutdown
dyn_win_shutdown:
    adrp x16, __imp_shutdown
    ldr x16, [x16, :lo12:__imp_shutdown]
    br x16
.global dyn_win_ioctlsocket
dyn_win_ioctlsocket:
    adrp x16, __imp_ioctlsocket
    ldr x16, [x16, :lo12:__imp_ioctlsocket]
    br x16
.global dyn_win_socket_error
dyn_win_socket_error:
    adrp x16, __imp_WSAGetLastError
    ldr x16, [x16, :lo12:__imp_WSAGetLastError]
    br x16
.global dyn_net_send_to
dyn_net_send_to:
    adrp x16, __imp_sendto
    ldr x16, [x16, :lo12:__imp_sendto]
    br x16
.global dyn_net_receive_from
dyn_net_receive_from:
    adrp x16, __imp_recvfrom
    ldr x16, [x16, :lo12:__imp_recvfrom]
    br x16
.global dyn_net_local
dyn_net_local:
    adrp x16, __imp_getsockname
    ldr x16, [x16, :lo12:__imp_getsockname]
    br x16
.global dyn_net_peer
dyn_net_peer:
    adrp x16, __imp_getpeername
    ldr x16, [x16, :lo12:__imp_getpeername]
    br x16
.global dyn_net_set_option
dyn_net_set_option:
    adrp x16, __imp_setsockopt
    ldr x16, [x16, :lo12:__imp_setsockopt]
    br x16
.global dyn_net_get_option
dyn_net_get_option:
    adrp x16, __imp_getsockopt
    ldr x16, [x16, :lo12:__imp_getsockopt]
    br x16
.global dyn_win_socket_poll
dyn_win_socket_poll:
    adrp x16, __imp_WSAPoll
    ldr x16, [x16, :lo12:__imp_WSAPoll]
    br x16
.global dyn_process_compare
dyn_process_compare:
    adrp x16, __imp_CompareStringOrdinal
    ldr x16, [x16, :lo12:__imp_CompareStringOrdinal]
    br x16
.global dyn_process_create
dyn_process_create:
    adrp x16, __imp_CreateProcessW
    ldr x16, [x16, :lo12:__imp_CreateProcessW]
    br x16
.global dyn_process_exit_code
dyn_process_exit_code:
    adrp x16, __imp_GetExitCodeProcess
    ldr x16, [x16, :lo12:__imp_GetExitCodeProcess]
    br x16
.global dyn_process_terminate
dyn_process_terminate:
    adrp x16, __imp_TerminateProcess
    ldr x16, [x16, :lo12:__imp_TerminateProcess]
    br x16
.global dyn_process_pipe
dyn_process_pipe:
    adrp x16, __imp_CreatePipe
    ldr x16, [x16, :lo12:__imp_CreatePipe]
    br x16
.global dyn_process_peek
dyn_process_peek:
    adrp x16, __imp_PeekNamedPipe
    ldr x16, [x16, :lo12:__imp_PeekNamedPipe]
    br x16
.global dyn_process_ticks
dyn_process_ticks:
    adrp x16, __imp_GetTickCount64
    ldr x16, [x16, :lo12:__imp_GetTickCount64]
    br x16
.global dyn_process_sleep
dyn_process_sleep:
    adrp x16, __imp_Sleep
    ldr x16, [x16, :lo12:__imp_Sleep]
    br x16
.global dyn_process_std
dyn_process_std:
    adrp x16, __imp_GetStdHandle
    ldr x16, [x16, :lo12:__imp_GetStdHandle]
    br x16
.global dyn_process_current
dyn_process_current:
    adrp x16, __imp_GetCurrentProcess
    ldr x16, [x16, :lo12:__imp_GetCurrentProcess]
    br x16
.global dyn_process_duplicate
dyn_process_duplicate:
    adrp x16, __imp_DuplicateHandle
    ldr x16, [x16, :lo12:__imp_DuplicateHandle]
    br x16
.global dyn_process_init_attributes
dyn_process_init_attributes:
    adrp x16, __imp_InitializeProcThreadAttributeList
    ldr x16, [x16, :lo12:__imp_InitializeProcThreadAttributeList]
    br x16
.global dyn_process_update_attributes
dyn_process_update_attributes:
    adrp x16, __imp_UpdateProcThreadAttribute
    ldr x16, [x16, :lo12:__imp_UpdateProcThreadAttribute]
    br x16
.global dyn_process_delete_attributes
dyn_process_delete_attributes:
    adrp x16, __imp_DeleteProcThreadAttributeList
    ldr x16, [x16, :lo12:__imp_DeleteProcThreadAttributeList]
    br x16
.global dyn_process_environment
dyn_process_environment:
    adrp x16, __imp_GetEnvironmentVariableW
    ldr x16, [x16, :lo12:__imp_GetEnvironmentVariableW]
    br x16
.global dyn_process_set_error
dyn_process_set_error:
    adrp x16, __imp_SetLastError
    ldr x16, [x16, :lo12:__imp_SetLastError]
    br x16
.global dyn_process_close
dyn_process_close:
    adrp x16, __imp_CloseHandle
    ldr x16, [x16, :lo12:__imp_CloseHandle]
    br x16
.global dyn_process_wait
dyn_process_wait:
    adrp x16, __imp_WaitForSingleObject
    ldr x16, [x16, :lo12:__imp_WaitForSingleObject]
    br x16
.global dyn_process_error
dyn_process_error:
    adrp x16, __imp_GetLastError
    ldr x16, [x16, :lo12:__imp_GetLastError]
    br x16
.global dyn_process_read
dyn_process_read:
    adrp x16, __imp_ReadFile
    ldr x16, [x16, :lo12:__imp_ReadFile]
    br x16
.global dyn_watch_open
dyn_watch_open:
    adrp x16, __imp_CreateFileW
    ldr x16, [x16, :lo12:__imp_CreateFileW]
    br x16
.global dyn_watch_close
dyn_watch_close:
    adrp x16, __imp_CloseHandle
    ldr x16, [x16, :lo12:__imp_CloseHandle]
    br x16
.global dyn_watch_error
dyn_watch_error:
    adrp x16, __imp_GetLastError
    ldr x16, [x16, :lo12:__imp_GetLastError]
    br x16
.global dyn_watch_create_event
dyn_watch_create_event:
    adrp x16, __imp_CreateEventW
    ldr x16, [x16, :lo12:__imp_CreateEventW]
    br x16
.global dyn_watch_reset_event
dyn_watch_reset_event:
    adrp x16, __imp_ResetEvent
    ldr x16, [x16, :lo12:__imp_ResetEvent]
    br x16
.global dyn_watch_read
dyn_watch_read:
    adrp x16, __imp_ReadDirectoryChangesW
    ldr x16, [x16, :lo12:__imp_ReadDirectoryChangesW]
    br x16
.global dyn_watch_result
dyn_watch_result:
    adrp x16, __imp_GetOverlappedResult
    ldr x16, [x16, :lo12:__imp_GetOverlappedResult]
    br x16
.global dyn_watch_cancel
dyn_watch_cancel:
    adrp x16, __imp_CancelIoEx
    ldr x16, [x16, :lo12:__imp_CancelIoEx]
    br x16
.global dyn_fs_open
dyn_fs_open:
    adrp x16, __imp_CreateFileW
    ldr x16, [x16, :lo12:__imp_CreateFileW]
    br x16
.global dyn_fs_seek
dyn_fs_seek:
    adrp x16, __imp_SetFilePointerEx
    ldr x16, [x16, :lo12:__imp_SetFilePointerEx]
    br x16
.global dyn_fs_sync
dyn_fs_sync:
    adrp x16, __imp_FlushFileBuffers
    ldr x16, [x16, :lo12:__imp_FlushFileBuffers]
    br x16
.global dyn_time_sleep
dyn_time_sleep:
    adrp x16, __imp_Sleep
    ldr x16, [x16, :lo12:__imp_Sleep]
    br x16
.global dyn_time_counter
dyn_time_counter:
    adrp x16, __imp_QueryPerformanceCounter
    ldr x16, [x16, :lo12:__imp_QueryPerformanceCounter]
    br x16
.global dyn_time_frequency
dyn_time_frequency:
    adrp x16, __imp_QueryPerformanceFrequency
    ldr x16, [x16, :lo12:__imp_QueryPerformanceFrequency]
    br x16
.global dyn_time_realtime
dyn_time_realtime:
    adrp x16, __imp_GetSystemTimePreciseAsFileTime
    ldr x16, [x16, :lo12:__imp_GetSystemTimePreciseAsFileTime]
    br x16
.global dyn_arguments_command
dyn_arguments_command:
    adrp x16, __imp_GetCommandLineW
    ldr x16, [x16, :lo12:__imp_GetCommandLineW]
    br x16
.global dyn_fs_close
dyn_fs_close:
    adrp x16, __imp_CloseHandle
    ldr x16, [x16, :lo12:__imp_CloseHandle]
    br x16
.global dyn_fs_read
dyn_fs_read:
    adrp x16, __imp_ReadFile
    ldr x16, [x16, :lo12:__imp_ReadFile]
    br x16
.global dyn_fs_write
dyn_fs_write:
    adrp x16, __imp_WriteFile
    ldr x16, [x16, :lo12:__imp_WriteFile]
    br x16
.global dyn_fs_error
dyn_fs_error:
    adrp x16, __imp_GetLastError
    ldr x16, [x16, :lo12:__imp_GetLastError]
    br x16
.global dyn_stdio_handle
dyn_stdio_handle:
    adrp x16, __imp_GetStdHandle
    ldr x16, [x16, :lo12:__imp_GetStdHandle]
    br x16
.global dyn_stdio_read
dyn_stdio_read:
    adrp x16, __imp_ReadFile
    ldr x16, [x16, :lo12:__imp_ReadFile]
    br x16
.global dyn_stdio_write
dyn_stdio_write:
    adrp x16, __imp_WriteFile
    ldr x16, [x16, :lo12:__imp_WriteFile]
    br x16
.global dyn_stdio_error
dyn_stdio_error:
    adrp x16, __imp_GetLastError
    ldr x16, [x16, :lo12:__imp_GetLastError]
    br x16
.global CreateThread
CreateThread:
    adrp x16, __imp_CreateThread
    ldr x16, [x16, :lo12:__imp_CreateThread]
    br x16
.global ExitProcess
ExitProcess:
    adrp x16, __imp_ExitProcess
    ldr x16, [x16, :lo12:__imp_ExitProcess]
    br x16
.global GetCurrentThreadId
GetCurrentThreadId:
    adrp x16, __imp_GetCurrentThreadId
    ldr x16, [x16, :lo12:__imp_GetCurrentThreadId]
    br x16
.global GetStdHandle
GetStdHandle:
    adrp x16, __imp_GetStdHandle
    ldr x16, [x16, :lo12:__imp_GetStdHandle]
    br x16
.global WriteFile
WriteFile:
    adrp x16, __imp_WriteFile
    ldr x16, [x16, :lo12:__imp_WriteFile]
    br x16
.global dyn_win_arena_last_error
.set dyn_win_arena_last_error, dyn_win_last_error
.section .idata$2,"dw"
.p2align 2
    .rva kernel_lookup
    .long 0
    .long 0
    .rva kernel_name
    .rva kernel_iat
    .rva winsock_lookup
    .long 0
    .long 0
    .rva winsock_name
    .rva winsock_iat
    .rva sync_lookup
    .long 0
    .long 0
    .rva sync_name
    .rva sync_iat
    .rva crypto_lookup
    .long 0
    .long 0
    .rva crypto_name
    .rva crypto_iat
    // GNU PE linkers append the terminating descriptor. Supplying it here
    // would hide descriptors contributed by user import libraries.

.section .idata$4,"dw"
.p2align 3
kernel_lookup:
.macro thunk name
    .rva hn_\name
    .long 0
.endm
    thunk CreateFileW
    thunk SetFilePointerEx
    thunk FlushFileBuffers
    thunk QueryPerformanceCounter
    thunk QueryPerformanceFrequency
    thunk GetSystemTimePreciseAsFileTime
    thunk GetCommandLineW
    thunk ExitProcess
    thunk CloseHandle
    thunk WaitForSingleObject
    thunk SwitchToThread
    thunk GetDynamicTimeZoneInformation
    thunk SetConsoleCtrlHandler
    thunk CreateEventW
    thunk SetEvent
    thunk CreateFileMappingW
    thunk MapViewOfFile
    thunk UnmapViewOfFile
    thunk GetConsoleMode
    thunk SetConsoleMode
    thunk GetConsoleScreenBufferInfo
    thunk VirtualAlloc
    thunk VirtualFree
    thunk CreateFileA
    thunk ReadFile
    thunk WriteFile
    thunk LoadLibraryA
    thunk GetProcAddress
    thunk FreeLibrary
    thunk GetLastError
    thunk CreateThread
    thunk CompareStringOrdinal
    thunk CreateProcessW
    thunk GetExitCodeProcess
    thunk TerminateProcess
    thunk CreatePipe
    thunk PeekNamedPipe
    thunk GetTickCount64
    thunk Sleep
    thunk GetStdHandle
    thunk GetCurrentProcess
    thunk GetCurrentThreadId
    thunk DuplicateHandle
    thunk InitializeProcThreadAttributeList
    thunk UpdateProcThreadAttribute
    thunk DeleteProcThreadAttributeList
    thunk GetEnvironmentVariableW
    thunk CreateEventW
    thunk ResetEvent
    thunk ReadDirectoryChangesW
    thunk GetOverlappedResult
    thunk CancelIoEx
    thunk SetLastError
    .quad 0
winsock_lookup:
    thunk WSAStartup
    thunk socket
    thunk closesocket
    thunk connect
    thunk bind
    thunk listen
    thunk accept
    thunk send
    thunk recv
    thunk shutdown
    thunk ioctlsocket
    thunk WSAGetLastError
    thunk sendto
    thunk recvfrom
    thunk getsockname
    thunk getpeername
    thunk setsockopt
    thunk getsockopt
    thunk WSAPoll
    .quad 0

sync_lookup:
    thunk WaitOnAddress
    thunk WakeByAddressSingle
    thunk WakeByAddressAll
    .quad 0

crypto_lookup:
    thunk BCryptGenRandom
    .quad 0

.section .idata$5,"dw"
.p2align 3
kernel_iat:
.macro iat name
__imp_\name: .rva hn_\name; .long 0
.endm
iat CreateFileW
iat SetFilePointerEx
iat FlushFileBuffers
iat QueryPerformanceCounter
iat QueryPerformanceFrequency
iat GetSystemTimePreciseAsFileTime
iat GetCommandLineW
iat ExitProcess
iat CloseHandle
iat WaitForSingleObject
iat SwitchToThread
iat GetDynamicTimeZoneInformation
iat SetConsoleCtrlHandler
iat CreateEventW
iat SetEvent
iat CreateFileMappingW
iat MapViewOfFile
iat UnmapViewOfFile
iat GetConsoleMode
iat SetConsoleMode
iat GetConsoleScreenBufferInfo
iat VirtualAlloc
iat VirtualFree
iat CreateFileA
iat ReadFile
.global __imp_WriteFile
iat WriteFile
iat LoadLibraryA
iat GetProcAddress
iat FreeLibrary
iat GetLastError
iat CreateThread
iat CompareStringOrdinal
iat CreateProcessW
iat GetExitCodeProcess
iat TerminateProcess
iat CreatePipe
iat PeekNamedPipe
iat GetTickCount64
iat Sleep
.global __imp_GetStdHandle
iat GetStdHandle
iat GetCurrentProcess
.global __imp_GetCurrentThreadId
iat GetCurrentThreadId
iat DuplicateHandle
iat InitializeProcThreadAttributeList
iat UpdateProcThreadAttribute
iat DeleteProcThreadAttributeList
iat GetEnvironmentVariableW
iat CreateEventW
iat ResetEvent
iat ReadDirectoryChangesW
iat GetOverlappedResult
iat CancelIoEx
iat SetLastError
    .quad 0
winsock_iat:
iat WSAStartup
iat socket
iat closesocket
iat connect
iat bind
iat listen
iat accept
iat send
iat recv
iat shutdown
iat ioctlsocket
iat WSAGetLastError
iat sendto
iat recvfrom
iat getsockname
iat getpeername
iat setsockopt
iat getsockopt
iat WSAPoll
    .quad 0

sync_iat:
iat WaitOnAddress
iat WakeByAddressSingle
iat WakeByAddressAll
    .quad 0

crypto_iat:
iat BCryptGenRandom
    .quad 0

.section .idata$6,"dw"
.macro hint name
hn_\name: .short 0; .asciz "\name"; .p2align 1
.endm
hint CreateFileW
hint SetFilePointerEx
hint FlushFileBuffers
hint QueryPerformanceCounter
hint QueryPerformanceFrequency
hint GetSystemTimePreciseAsFileTime
hint GetCommandLineW
hint ExitProcess
hint CloseHandle
hint WaitForSingleObject
hint SwitchToThread
hint GetDynamicTimeZoneInformation
hint SetConsoleCtrlHandler
hint CreateEventW
hint SetEvent
hint CreateFileMappingW
hint MapViewOfFile
hint UnmapViewOfFile
hint GetConsoleMode
hint SetConsoleMode
hint GetConsoleScreenBufferInfo
hint VirtualAlloc
hint VirtualFree
hint CreateFileA
hint ReadFile
hint WriteFile
hint LoadLibraryA
hint GetProcAddress
hint FreeLibrary
hint GetLastError
hint CreateThread
hint CompareStringOrdinal
hint CreateProcessW
hint GetExitCodeProcess
hint TerminateProcess
hint CreatePipe
hint PeekNamedPipe
hint GetTickCount64
hint Sleep
hint GetStdHandle
hint GetCurrentProcess
hint GetCurrentThreadId
hint DuplicateHandle
hint InitializeProcThreadAttributeList
hint UpdateProcThreadAttribute
hint DeleteProcThreadAttributeList
hint GetEnvironmentVariableW
hint CreateEventW
hint ResetEvent
hint ReadDirectoryChangesW
hint GetOverlappedResult
hint CancelIoEx
hint SetLastError
hint WSAStartup
hint socket
hint closesocket
hint connect
hint bind
hint listen
hint accept
hint send
hint recv
hint shutdown
hint ioctlsocket
hint WSAGetLastError
hint sendto
hint recvfrom
hint getsockname
hint getpeername
hint setsockopt
hint getsockopt
hint WSAPoll
hint WaitOnAddress
hint WakeByAddressSingle
hint WakeByAddressAll
sync_name: .asciz "api-ms-win-core-synch-l1-2-0.dll"
hint BCryptGenRandom
crypto_name: .asciz "bcrypt.dll"
kernel_name: .asciz "KERNEL32.dll"
winsock_name: .asciz "WS2_32.dll"

// Windows ARM64 stack probe ABI: x15 holds allocation / 16; only x16/x17
// may change. Keep SP and x15 intact; touch every page before allocation.
.text
.global __chkstk
__chkstk:
    mov x16, x15
    mov x17, sp
.Lchkstk_page:
    cmp x16, #256
    b.cc .Lchkstk_tail
    sub x17, x17, #2048
    sub x17, x17, #2048
    ldr xzr, [x17]
    sub x16, x16, #256
    b .Lchkstk_page
.Lchkstk_tail:
    cbz x16, .Lchkstk_done
    orr x16, xzr, x16, lsl #4
    sub x17, x17, x16
    ldr xzr, [x17]
.Lchkstk_done:
    ret
