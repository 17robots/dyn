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
    subq $40, %rsp
    callq dyn_unwind_begin
    ud2

.global dyn_unwind_set
dyn_unwind_set:
    movq %rbx, 8(%rcx)
    movq %rbp, 16(%rcx)
    movq %rdi, 24(%rcx)
    movq %rsi, 32(%rcx)
    movq %r12, 40(%rcx)
    movq %r13, 48(%rcx)
    movq %r14, 56(%rcx)
    movq %r15, 64(%rcx)
    leaq 8(%rsp), %rax
    movq %rax, 72(%rcx)
    movq (%rsp), %rax
    movq %rax, 80(%rcx)
    xorl %eax, %eax
    retq

.global dyn_unwind_jump
dyn_unwind_jump:
    movq 8(%rcx), %rbx
    movq 16(%rcx), %rbp
    movq 24(%rcx), %rdi
    movq 32(%rcx), %rsi
    movq 40(%rcx), %r12
    movq 48(%rcx), %r13
    movq 56(%rcx), %r14
    movq 64(%rcx), %r15
    movq 72(%rcx), %rsp
    movq 80(%rcx), %rdx
    movl $1, %eax
    jmpq *%rdx

.global dyn_trace_push
dyn_trace_push: retq
.global dyn_trace_pop
dyn_trace_pop: retq

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
import_jump dyn_win_yield, SwitchToThread
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
    // GNU PE linkers append the terminating descriptor. Supplying it here
    // would hide descriptors contributed by user import libraries.

.section .idata$4,"dw"
.p2align 3
kernel_lookup:
.macro thunk name
    .rva hn_\name
    .long 0
.endm
    thunk ExitProcess
    thunk CloseHandle
    thunk WaitForSingleObject
    thunk SwitchToThread
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
    thunk DuplicateHandle
    thunk InitializeProcThreadAttributeList
    thunk UpdateProcThreadAttribute
    thunk DeleteProcThreadAttributeList
    thunk GetEnvironmentVariableW
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
    thunk WSAPoll
    .quad 0

.section .idata$5,"dw"
.p2align 3
kernel_iat:
.macro iat name
__imp_\name: .rva hn_\name; .long 0
.endm
iat ExitProcess
iat CloseHandle
iat WaitForSingleObject
iat SwitchToThread
iat VirtualAlloc
iat VirtualFree
iat CreateFileA
iat ReadFile
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
iat GetStdHandle
iat GetCurrentProcess
iat DuplicateHandle
iat InitializeProcThreadAttributeList
iat UpdateProcThreadAttribute
iat DeleteProcThreadAttributeList
iat GetEnvironmentVariableW
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
iat WSAPoll
    .quad 0

.section .idata$6,"dw"
.macro hint name
hn_\name: .short 0; .asciz "\name"; .p2align 1
.endm
hint ExitProcess
hint CloseHandle
hint WaitForSingleObject
hint SwitchToThread
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
hint DuplicateHandle
hint InitializeProcThreadAttributeList
hint UpdateProcThreadAttribute
hint DeleteProcThreadAttributeList
hint GetEnvironmentVariableW
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
hint WSAPoll
kernel_name: .asciz "KERNEL32.dll"
winsock_name: .asciz "WS2_32.dll"

#include "windows_stack_probe.S"
