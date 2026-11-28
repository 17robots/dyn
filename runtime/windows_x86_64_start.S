.text
#ifndef DYN_SHARED
.global dyn_start
dyn_start:
    subq $40, %rsp
    callq main
    movl %eax, %ecx
    callq *__imp_ExitProcess(%rip)
    ud2
#endif

.global dyn_panic
dyn_panic:
    subq $88, %rsp
    movq %rcx, 48(%rsp)
    movq %rdx, 56(%rsp)
    // The trace begins at the caller: its return address and frame pointer.
    movq 88(%rsp), %rcx
    movq %rbp, %rdx
    callq dyn_trace_capture
    movq 48(%rsp), %rcx
    movq 56(%rsp), %rdx
    callq dyn_unwind_begin
    movl $-12, %ecx
    callq *__imp_GetStdHandle(%rip)
    movq %rax, 64(%rsp)
    cmpq $0, 48(%rsp)
    je .Lpanic_exit
.Lpanic_write:
    cmpq $0, 56(%rsp)
    je .Lpanic_newline
    movq 64(%rsp), %rcx
    movq 48(%rsp), %rdx
    movq 56(%rsp), %r8
    movl $0x7fffffff, %eax
    cmpq %rax, %r8
    cmovaq %rax, %r8
    leaq 72(%rsp), %r9
    movq $0, 32(%rsp)
    callq *__imp_WriteFile(%rip)
    testl %eax, %eax
    jz .Lpanic_exit
    movl 72(%rsp), %eax
    testl %eax, %eax
    jz .Lpanic_exit
    addq %rax, 48(%rsp)
    subq %rax, 56(%rsp)
    jmp .Lpanic_write
.Lpanic_newline:
    movb $10, 80(%rsp)
    movq 64(%rsp), %rcx
    leaq 80(%rsp), %rdx
    movl $1, %r8d
    leaq 72(%rsp), %r9
    movq $0, 32(%rsp)
    callq *__imp_WriteFile(%rip)
.Lpanic_exit:
    callq dyn_trace_dump
    movl $101, %ecx
    callq *__imp_ExitProcess(%rip)
    ud2

// Sequentially consistent atomics. x86 loads/stores already preserve acquire/release;
// locked read/modify/write instructions provide total ordering.
.global dyn_atomic_load_u32
dyn_atomic_load_u32: movl (%rcx), %eax; retq
.global dyn_atomic_store_u32
dyn_atomic_store_u32: xchgl %edx, (%rcx); retq
.global dyn_atomic_exchange_u32
dyn_atomic_exchange_u32: movl %edx, %eax; xchgl %eax, (%rcx); retq
.global dyn_atomic_fetch_add_u32
dyn_atomic_fetch_add_u32: movl %edx, %eax; lock xaddl %eax, (%rcx); retq
.global dyn_atomic_compare_exchange_u32
dyn_atomic_compare_exchange_u32:
    movl %edx, %eax
    lock cmpxchgl %r8d, (%rcx)
    sete %al
    movzbl %al, %eax
    retq
.global dyn_atomic_load_u64
dyn_atomic_load_u64: movq (%rcx), %rax; retq
.global dyn_atomic_store_u64
dyn_atomic_store_u64: xchgq %rdx, (%rcx); retq
.global dyn_atomic_exchange_u64
dyn_atomic_exchange_u64: movq %rdx, %rax; xchgq %rax, (%rcx); retq
.global dyn_atomic_fetch_add_u64
dyn_atomic_fetch_add_u64: movq %rdx, %rax; lock xaddq %rax, (%rcx); retq
.global dyn_atomic_compare_exchange_u64
dyn_atomic_compare_exchange_u64:
    movq %rdx, %rax
    lock cmpxchgq %r8, (%rcx)
    sete %al
    movzbl %al, %eax
    retq

// Caller supplies stack size, not storage: Win32 owns actual thread stack.
// rawptr dyn_win_thread_spawn(size, entry, context, tid_out)
.global dyn_win_thread_spawn
dyn_win_thread_spawn:
    subq $56, %rsp
    movq %r9, 40(%rsp)
    movq %r8, %r9
    movq %rdx, %r8
    movq %rcx, %rdx
    xorl %ecx, %ecx
    movq $0, 32(%rsp)
    callq *__imp_CreateThread(%rip)
    addq $56, %rsp
    retq

.macro import_jump public, native
.global \public
\public: jmp *__imp_\native(%rip)
.endm
import_jump dyn_win_close_handle, CloseHandle
import_jump dyn_win_wait, WaitForSingleObject
import_jump dyn_crypto_random, BCryptGenRandom
import_jump dyn_sync_wait, WaitOnAddress
import_jump dyn_sync_single, WakeByAddressSingle
import_jump dyn_sync_all, WakeByAddressAll
import_jump dyn_sync_error, GetLastError
import_jump dyn_win_yield, SwitchToThread
import_jump dyn_win_system_info, GetSystemInfo
import_jump dyn_fs_make_directory, CreateDirectoryW
import_jump dyn_fs_delete, DeleteFileW
import_jump dyn_fs_remove_directory, RemoveDirectoryW
import_jump dyn_fs_move, MoveFileExW
import_jump dyn_fs_attributes, GetFileAttributesExW
import_jump dyn_fs_information, GetFileInformationByHandle
import_jump dyn_fs_find_first, FindFirstFileW
import_jump dyn_fs_find_next, FindNextFileW
import_jump dyn_fs_find_close, FindClose
import_jump dyn_time_zone_information, GetDynamicTimeZoneInformation
import_jump dyn_signal_console_handler, SetConsoleCtrlHandler
import_jump dyn_signal_create_event, CreateEventW
import_jump dyn_signal_set_event, SetEvent
import_jump dyn_fs_map_create, CreateFileMappingW
import_jump dyn_fs_map_view, MapViewOfFile
import_jump dyn_fs_map_release, UnmapViewOfFile
import_jump dyn_terminal_get_mode, GetConsoleMode
import_jump dyn_terminal_set_mode, SetConsoleMode
import_jump dyn_terminal_buffer_info, GetConsoleScreenBufferInfo
import_jump dyn_net_idle, Sleep
import_jump dyn_win_virtual_alloc, VirtualAlloc
import_jump dyn_win_virtual_free, VirtualFree
import_jump dyn_win_create_file, CreateFileA
import_jump dyn_win_read_file, ReadFile
import_jump dyn_win_write_file, WriteFile
import_jump dyn_win_load_library, LoadLibraryA
import_jump dyn_win_get_symbol, GetProcAddress
import_jump dyn_win_free_library, FreeLibrary
import_jump dyn_win_last_error, GetLastError
.global dyn_win_arena_last_error
.set dyn_win_arena_last_error, dyn_win_last_error
// std/fs: permissions, links, locks, block cloning and environment.
import_jump dyn_fs_information_ex, GetFileInformationByHandleEx
import_jump dyn_fs_set_information, SetFileInformationByHandle
import_jump dyn_fs_lock, LockFileEx
import_jump dyn_fs_unlock, UnlockFileEx
import_jump dyn_fs_symbolic_link, CreateSymbolicLinkW
import_jump dyn_fs_control, DeviceIoControl
import_jump dyn_fs_volume, GetVolumeInformationByHandleW
import_jump dyn_fs_reopen, ReOpenFile
import_jump dyn_fs_local_free, LocalFree
import_jump dyn_fs_environment, GetEnvironmentVariableW
import_jump dyn_fs_set_error, SetLastError
import_jump dyn_fs_get_security, GetSecurityInfo
import_jump dyn_fs_set_security, SetSecurityInfo
import_jump dyn_win_socket_startup, WSAStartup
import_jump dyn_win_socket, socket
import_jump dyn_win_close_socket, closesocket
import_jump dyn_win_connect, connect
import_jump dyn_win_bind, bind
import_jump dyn_win_listen, listen
import_jump dyn_win_accept, accept
import_jump dyn_win_send, send
import_jump dyn_win_receive, recv
import_jump dyn_win_shutdown, shutdown
import_jump dyn_win_ioctlsocket, ioctlsocket
import_jump dyn_win_socket_error, WSAGetLastError
import_jump dyn_net_send_to, sendto
import_jump dyn_net_receive_from, recvfrom
import_jump dyn_net_local, getsockname
import_jump dyn_net_peer, getpeername
import_jump dyn_net_set_option, setsockopt
import_jump dyn_net_get_option, getsockopt
import_jump dyn_win_socket_poll, WSAPoll

import_jump dyn_process_compare, CompareStringOrdinal
import_jump dyn_process_create, CreateProcessW
import_jump dyn_process_exit_code, GetExitCodeProcess
import_jump dyn_process_terminate, TerminateProcess
import_jump dyn_process_pipe, CreatePipe
import_jump dyn_process_peek, PeekNamedPipe
import_jump dyn_process_ticks, GetTickCount64
import_jump dyn_process_sleep, Sleep
import_jump dyn_process_std, GetStdHandle
import_jump dyn_process_current, GetCurrentProcess
import_jump dyn_process_duplicate, DuplicateHandle
import_jump dyn_process_init_attributes, InitializeProcThreadAttributeList
import_jump dyn_process_update_attributes, UpdateProcThreadAttribute
import_jump dyn_process_delete_attributes, DeleteProcThreadAttributeList
import_jump dyn_process_environment, GetEnvironmentVariableW
import_jump dyn_process_set_error, SetLastError
import_jump dyn_process_close, CloseHandle
import_jump dyn_process_wait, WaitForSingleObject
import_jump dyn_process_error, GetLastError
import_jump dyn_process_read, ReadFile
// std/process: process trees, nonblocking pipe writes.
import_jump dyn_process_write, WriteFile
import_jump dyn_process_job_create, CreateJobObjectW
import_jump dyn_process_job_limit, SetInformationJobObject
import_jump dyn_process_job_assign, AssignProcessToJobObject
import_jump dyn_process_job_terminate, TerminateJobObject
import_jump dyn_process_resume, ResumeThread
import_jump dyn_process_pipe_mode, SetNamedPipeHandleState

import_jump dyn_watch_open, CreateFileW
import_jump dyn_watch_close, CloseHandle
import_jump dyn_watch_error, GetLastError
import_jump dyn_watch_create_event, CreateEventW
import_jump dyn_watch_reset_event, ResetEvent
import_jump dyn_watch_read, ReadDirectoryChangesW
import_jump dyn_watch_result, GetOverlappedResult
import_jump dyn_watch_cancel, CancelIoEx
import_jump dyn_fs_open, CreateFileW
import_jump dyn_fs_seek, SetFilePointerEx
import_jump dyn_fs_sync, FlushFileBuffers
import_jump dyn_time_sleep, Sleep
import_jump dyn_time_counter, QueryPerformanceCounter
import_jump dyn_time_frequency, QueryPerformanceFrequency
import_jump dyn_time_realtime, GetSystemTimePreciseAsFileTime
import_jump dyn_arguments_command, GetCommandLineW

import_jump dyn_fs_close, CloseHandle
import_jump dyn_fs_read, ReadFile
import_jump dyn_fs_write, WriteFile
import_jump dyn_fs_error, GetLastError
import_jump dyn_stdio_handle, GetStdHandle
import_jump dyn_stdio_read, ReadFile
import_jump dyn_stdio_write, WriteFile
import_jump dyn_stdio_error, GetLastError
// std/process/pty: pseudoconsole pipes, job objects and the lazy ConPTY lookup.
import_jump dyn_pty_pipe, CreatePipe
import_jump dyn_pty_pipe_state, SetNamedPipeHandleState
import_jump dyn_pty_peek, PeekNamedPipe
import_jump dyn_pty_read, ReadFile
import_jump dyn_pty_write, WriteFile
import_jump dyn_pty_close, CloseHandle
import_jump dyn_pty_error, GetLastError
import_jump dyn_pty_wait, WaitForSingleObject
import_jump dyn_pty_exit_code, GetExitCodeProcess
import_jump dyn_pty_terminate_process, TerminateProcess
import_jump dyn_pty_create_process, CreateProcessW
import_jump dyn_pty_init_attributes, InitializeProcThreadAttributeList
import_jump dyn_pty_update_attributes, UpdateProcThreadAttribute
import_jump dyn_pty_delete_attributes, DeleteProcThreadAttributeList
import_jump dyn_pty_compare, CompareStringOrdinal
import_jump dyn_pty_job_create, CreateJobObjectW
import_jump dyn_pty_job_limits, SetInformationJobObject
import_jump dyn_pty_job_assign, AssignProcessToJobObject
import_jump dyn_pty_job_terminate, TerminateJobObject
import_jump dyn_pty_resume, ResumeThread
import_jump dyn_pty_ticks, GetTickCount64
import_jump dyn_pty_sleep, Sleep
import_jump dyn_pty_library, LoadLibraryA
import_jump dyn_pty_symbol, GetProcAddress

// Minimal PE import directory, avoiding SDK/import-library dependency while
// retaining stable documented Win32 and Winsock entry points.
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
    // std/fs: access control lists.
    .rva advapi_lookup
    .long 0
    .long 0
    .rva advapi_name
    .rva advapi_iat
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
    thunk GetSystemInfo
    thunk CreateDirectoryW
    thunk DeleteFileW
    thunk RemoveDirectoryW
    thunk MoveFileExW
    thunk GetFileAttributesExW
    thunk GetFileInformationByHandle
    thunk FindFirstFileW
    thunk FindNextFileW
    thunk FindClose
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
    // std/process/pty
    thunk SetNamedPipeHandleState
    thunk CreateJobObjectW
    thunk SetInformationJobObject
    thunk AssignProcessToJobObject
    thunk TerminateJobObject
    thunk ResumeThread
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
    thunk SetUnhandledExceptionFilter
    thunk AddVectoredExceptionHandler
    thunk DuplicateHandle
    thunk InitializeProcThreadAttributeList
    thunk UpdateProcThreadAttribute
    thunk DeleteProcThreadAttributeList
    thunk GetEnvironmentVariableW
    thunk ResetEvent
    thunk ReadDirectoryChangesW
    thunk GetOverlappedResult
    thunk CancelIoEx
    thunk SetLastError
    // std/process: process trees and nonblocking pipes.
    // std/fs
    thunk GetFileInformationByHandleEx
    thunk SetFileInformationByHandle
    thunk LockFileEx
    thunk UnlockFileEx
    thunk CreateSymbolicLinkW
    thunk DeviceIoControl
    thunk GetVolumeInformationByHandleW
    thunk ReOpenFile
    thunk LocalFree
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

// std/fs
advapi_lookup:
    thunk GetSecurityInfo
    thunk SetSecurityInfo
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
iat GetSystemInfo
iat CreateDirectoryW
iat DeleteFileW
iat RemoveDirectoryW
iat MoveFileExW
iat GetFileAttributesExW
iat GetFileInformationByHandle
iat FindFirstFileW
iat FindNextFileW
iat FindClose
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
// std/process/pty
iat SetNamedPipeHandleState
iat CreateJobObjectW
iat SetInformationJobObject
iat AssignProcessToJobObject
iat TerminateJobObject
iat ResumeThread
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
.global __imp_SetUnhandledExceptionFilter
iat SetUnhandledExceptionFilter
.global __imp_AddVectoredExceptionHandler
iat AddVectoredExceptionHandler
iat DuplicateHandle
iat InitializeProcThreadAttributeList
iat UpdateProcThreadAttribute
iat DeleteProcThreadAttributeList
iat GetEnvironmentVariableW
iat ResetEvent
iat ReadDirectoryChangesW
iat GetOverlappedResult
iat CancelIoEx
iat SetLastError
// std/process: process trees and nonblocking pipes.
// std/fs
iat GetFileInformationByHandleEx
iat SetFileInformationByHandle
iat LockFileEx
iat UnlockFileEx
iat CreateSymbolicLinkW
iat DeviceIoControl
iat GetVolumeInformationByHandleW
iat ReOpenFile
iat LocalFree
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

// std/fs
advapi_iat:
iat GetSecurityInfo
iat SetSecurityInfo
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
hint GetSystemInfo
hint CreateDirectoryW
hint DeleteFileW
hint RemoveDirectoryW
hint MoveFileExW
hint GetFileAttributesExW
hint GetFileInformationByHandle
hint FindFirstFileW
hint FindNextFileW
hint FindClose
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
// std/process/pty
hint SetNamedPipeHandleState
hint CreateJobObjectW
hint SetInformationJobObject
hint AssignProcessToJobObject
hint TerminateJobObject
hint ResumeThread
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
hint SetUnhandledExceptionFilter
hint AddVectoredExceptionHandler
hint DuplicateHandle
hint InitializeProcThreadAttributeList
hint UpdateProcThreadAttribute
hint DeleteProcThreadAttributeList
hint GetEnvironmentVariableW
hint ResetEvent
hint ReadDirectoryChangesW
hint GetOverlappedResult
hint CancelIoEx
hint SetLastError
// std/process: process trees and nonblocking pipes.
// std/fs
hint GetFileInformationByHandleEx
hint SetFileInformationByHandle
hint LockFileEx
hint UnlockFileEx
hint CreateSymbolicLinkW
hint DeviceIoControl
hint GetVolumeInformationByHandleW
hint ReOpenFile
hint LocalFree
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
// std/fs
hint GetSecurityInfo
hint SetSecurityInfo
advapi_name: .asciz "ADVAPI32.dll"
kernel_name: .asciz "KERNEL32.dll"
winsock_name: .asciz "WS2_32.dll"

#include "windows_stack_probe.S"
