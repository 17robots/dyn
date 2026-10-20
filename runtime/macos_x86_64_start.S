.text
#ifndef DYN_SHARED
.global _dyn_start
_dyn_start:
    push %rbp
    mov %rsp, %rbp
    call _main
    mov %eax, %edi
    call __exit
    ud2
#endif
.global _dyn_panic
_dyn_panic:
    push %rbp
    mov %rsp, %rbp
    push %rdi
    push %rsi
    call _dyn_unwind_begin
    pop %rdx
    pop %rsi
    mov $2, %edi
    call _write
    lea .Lpanic_newline(%rip), %rsi
    mov $1, %edx
    mov $2, %edi
    call _write
    call _dyn_trace_dump
    mov $101, %edi
    call __exit
    ud2
.global _dyn_unwind_set
_dyn_unwind_set:
    mov %rbx, 8(%rdi)
    mov %rbp, 16(%rdi)
    mov %r12, 24(%rdi)
    mov %r13, 32(%rdi)
    mov %r14, 40(%rdi)
    mov %r15, 48(%rdi)
    lea 8(%rsp), %rax
    mov %rax, 56(%rdi)
    mov (%rsp), %rax
    mov %rax, 64(%rdi)
    xor %eax, %eax
    ret
.global _dyn_unwind_jump
_dyn_unwind_jump:
    mov 8(%rdi), %rbx
    mov 16(%rdi), %rbp
    mov 24(%rdi), %r12
    mov 32(%rdi), %r13
    mov 40(%rdi), %r14
    mov 48(%rdi), %r15
    mov 56(%rdi), %rsp
    mov 64(%rdi), %rdx
    mov $1, %eax
    jmp *%rdx
.global _dyn_atomic_load_u32
_dyn_atomic_load_u32:
    mov (%rdi), %eax
    ret
.global _dyn_atomic_store_u32
_dyn_atomic_store_u32:
    xchg %esi, (%rdi)
    ret
.global _dyn_atomic_exchange_u32
_dyn_atomic_exchange_u32:
    mov %esi, %eax
    xchg %eax, (%rdi)
    ret
.global _dyn_atomic_fetch_add_u32
_dyn_atomic_fetch_add_u32:
    mov %esi, %eax
    lock xadd %eax, (%rdi)
    ret
.global _dyn_atomic_compare_exchange_u32
_dyn_atomic_compare_exchange_u32:
    mov %esi, %eax
    lock cmpxchg %edx, (%rdi)
    sete %al
    movzbl %al, %eax
    ret

.global _dyn_atomic_load_u64
_dyn_atomic_load_u64:
    mov (%rdi), %rax
    ret
.global _dyn_atomic_store_u64
_dyn_atomic_store_u64:
    xchg %rsi, (%rdi)
    ret
.global _dyn_atomic_exchange_u64
_dyn_atomic_exchange_u64:
    mov %rsi, %rax
    xchg %rax, (%rdi)
    ret
.global _dyn_atomic_fetch_add_u64
_dyn_atomic_fetch_add_u64:
    mov %rsi, %rax
    lock xadd %rax, (%rdi)
    ret
.global _dyn_atomic_compare_exchange_u64
_dyn_atomic_compare_exchange_u64:
    mov %rsi, %rax
    lock cmpxchg %rdx, (%rdi)
    sete %al
    movzbl %al, %eax
    ret

.global _dyn_syscall6
_dyn_syscall6:
    mov %rdi, %rax
    add $0x2000000, %rax
    mov %rsi, %rdi
    mov %rdx, %rsi
    mov %rcx, %rdx
    mov %r8, %r10
    mov %r9, %r8
    mov 8(%rsp), %r9
    syscall
    jae .Lsyscall_done
    neg %rax
.Lsyscall_done:
    ret
.global _dyn_time_clock
_dyn_time_clock:
    jmp _clock_gettime
.global _dyn_time_sleep
_dyn_time_sleep:
    jmp _nanosleep
.global _dyn_sync_error
_dyn_sync_error:
    jmp ___error
.global _dyn_time_error
_dyn_time_error:
    jmp ___error
.global _dyn_arguments_count
_dyn_arguments_count:
    jmp __NSGetArgc
.global _dyn_arguments_vector
_dyn_arguments_vector:
    jmp __NSGetArgv
.global _dyn_arguments_length
_dyn_arguments_length:
    jmp _strlen
.section .rodata
.Lpanic_newline:
    .byte 10
