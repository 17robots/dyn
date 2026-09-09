.section .text._start,"ax",@progbits
.global _start
.type _start,@function
_start:
#ifndef DYN_RELEASE
    # Trace slots are claimed lazily by each thread.
#endif
    call main
    mov %eax, %edi
    mov $60, %eax
    syscall
.section .text.dyn_panic,"ax",@progbits
.global dyn_panic
.type dyn_panic,@function
dyn_panic:
    push %rdi
    push %rsi
    call dyn_unwind_begin
    pop %rsi
    pop %rdi
#ifdef DYN_RELEASE
    test %rsi, %rsi
    jz .Ldyn_panic_exit
    mov %rsi, %rdx
    mov %rdi, %rsi
    mov $2, %edi
    mov $1, %eax
    syscall
    lea .Ldyn_panic_newline(%rip), %rsi
    mov $1, %edx
    mov $2, %edi
    mov $1, %eax
    syscall
    jmp .Ldyn_panic_exit
#else
    test %rsi, %rsi
    jz .Ldyn_panic_stack
    mov %rsi, %rdx
    mov %rdi, %rsi
    mov $2, %edi
    mov $1, %eax
    syscall
    lea .Ldyn_panic_newline(%rip), %rsi
    mov $1, %edx
    mov $2, %edi
    mov $1, %eax
    syscall
.Ldyn_panic_stack:
    lea .Ldyn_panic_trace(%rip), %rsi
    mov $13, %edx
    mov $2, %edi
    mov $1, %eax
    syscall
    call .Ldyn_trace_slot
    test %rax, %rax
    jz .Ldyn_panic_exit
    mov 8(%rax), %rbx
    lea 16(%rax), %r13
.Ldyn_panic_frame:
    test %rbx, %rbx
    jz .Ldyn_panic_exit
    dec %rbx
    mov %r13, %r12
    mov %rbx, %rax
    shl $4, %rax
    add %rax, %r12
    lea .Ldyn_panic_at(%rip), %rsi
    mov $5, %edx
    mov $2, %edi
    mov $1, %eax
    syscall
    mov (%r12), %rsi
    mov 8(%r12), %rdx
    mov $2, %edi
    mov $1, %eax
    syscall
    lea .Ldyn_panic_newline(%rip), %rsi
    mov $1, %edx
    mov $2, %edi
    mov $1, %eax
    syscall
    jmp .Ldyn_panic_frame
#endif
.Ldyn_panic_exit:
    mov $101, %edi
    mov $60, %eax
    syscall
    ud2
.section .text.dyn_unwind_set,"ax",@progbits
.global dyn_unwind_set
.type dyn_unwind_set,@function
dyn_unwind_set:
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
.global dyn_unwind_jump
.type dyn_unwind_jump,@function
dyn_unwind_jump:
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
.section .rodata
.Ldyn_panic_newline:
    .byte 10
#ifndef DYN_RELEASE
.Ldyn_panic_trace:
    .ascii "stack trace:\n"
.Ldyn_panic_at:
    .ascii "  at "
.section .text.dyn_trace_push,"ax",@progbits
.global dyn_trace_push
.type dyn_trace_push,@function
dyn_trace_push:
    push %rdi
    push %rsi
    call .Ldyn_trace_slot_claim
    pop %rsi
    pop %rdi
    test %rax, %rax
    jz .Ldyn_trace_push_done
    mov 8(%rax), %rcx
    cmp $64, %rcx
    jae .Ldyn_trace_push_done
    mov %rcx, %rdx
    shl $4, %rdx
    mov %rdi, 16(%rax,%rdx)
    mov %rsi, 24(%rax,%rdx)
    inc %rcx
    mov %rcx, 8(%rax)
.Ldyn_trace_push_done:
    ret
.section .text.dyn_trace_pop,"ax",@progbits
.global dyn_trace_pop
.type dyn_trace_pop,@function
dyn_trace_pop:
    call .Ldyn_trace_slot
    test %rax, %rax
    jz .Ldyn_trace_pop_done
    mov 8(%rax), %rcx
    test %rcx, %rcx
    jz .Ldyn_trace_pop_done
    dec %rcx
    mov %rcx, 8(%rax)
    jnz .Ldyn_trace_pop_done
    movq $0, (%rax)
.Ldyn_trace_pop_done:
    ret

# Return current thread's trace slot, or zero. 64 bounded slots, 64 frames each.
.Ldyn_trace_slot:
    mov $186, %eax
    syscall
    lea dyn_trace_slots(%rip), %rdx
    mov $64, %ecx
.Ldyn_trace_slot_find:
    cmp (%rdx), %rax
    je .Ldyn_trace_slot_found
    add $1040, %rdx
    loop .Ldyn_trace_slot_find
    xor %eax, %eax
    ret
.Ldyn_trace_slot_found:
    mov %rdx, %rax
    ret

# Return existing slot or atomically claim empty slot for current tid.
.Ldyn_trace_slot_claim:
    mov $186, %eax
    syscall
    mov %rax, %r8
    lea dyn_trace_slots(%rip), %rdx
    mov $64, %ecx
.Ldyn_trace_slot_claim_loop:
    cmp (%rdx), %r8
    je .Ldyn_trace_slot_claimed
    xor %eax, %eax
    lock cmpxchg %r8, (%rdx)
    je .Ldyn_trace_slot_claimed
    add $1040, %rdx
    loop .Ldyn_trace_slot_claim_loop
    xor %eax, %eax
    ret
.Ldyn_trace_slot_claimed:
    mov %rdx, %rax
    ret
.comm dyn_trace_slots,66560,16
#endif
.section .text.dyn_syscall6,"ax",@progbits
.global dyn_syscall6
.type dyn_syscall6,@function
dyn_syscall6:
    mov %rdi, %rax
    mov %rsi, %rdi
    mov %rdx, %rsi
    mov %rcx, %rdx
    mov %r8, %r10
    mov %r9, %r8
    mov 8(%rsp), %r9
    syscall
    ret

# Atomic helpers use x86's strongest practical ordering. Public std/thread API
# therefore promises sequential consistency without exposing fake weak orders.
.section .text.dyn_atomic_load_u32,"ax",@progbits
.global dyn_atomic_load_u32
.type dyn_atomic_load_u32,@function
dyn_atomic_load_u32:
    mov (%rdi), %eax
    ret
.section .text.dyn_atomic_store_u32,"ax",@progbits
.global dyn_atomic_store_u32
.type dyn_atomic_store_u32,@function
dyn_atomic_store_u32:
    xchg %esi, (%rdi)
    ret
.section .text.dyn_atomic_exchange_u32,"ax",@progbits
.global dyn_atomic_exchange_u32
.type dyn_atomic_exchange_u32,@function
dyn_atomic_exchange_u32:
    mov %esi, %eax
    xchg %eax, (%rdi)
    ret
.section .text.dyn_atomic_fetch_add_u32,"ax",@progbits
.global dyn_atomic_fetch_add_u32
.type dyn_atomic_fetch_add_u32,@function
dyn_atomic_fetch_add_u32:
    mov %esi, %eax
    lock xadd %eax, (%rdi)
    ret
.section .text.dyn_atomic_compare_exchange_u32,"ax",@progbits
.global dyn_atomic_compare_exchange_u32
.type dyn_atomic_compare_exchange_u32,@function
dyn_atomic_compare_exchange_u32:
    mov %esi, %eax
    lock cmpxchg %edx, (%rdi)
    sete %al
    movzbl %al, %eax
    ret

.section .text.dyn_atomic_load_u64,"ax",@progbits
.global dyn_atomic_load_u64
.type dyn_atomic_load_u64,@function
dyn_atomic_load_u64:
    mov (%rdi), %rax
    ret
.section .text.dyn_atomic_store_u64,"ax",@progbits
.global dyn_atomic_store_u64
.type dyn_atomic_store_u64,@function
dyn_atomic_store_u64:
    xchg %rsi, (%rdi)
    ret
.section .text.dyn_atomic_exchange_u64,"ax",@progbits
.global dyn_atomic_exchange_u64
.type dyn_atomic_exchange_u64,@function
dyn_atomic_exchange_u64:
    mov %rsi, %rax
    xchg %rax, (%rdi)
    ret
.section .text.dyn_atomic_fetch_add_u64,"ax",@progbits
.global dyn_atomic_fetch_add_u64
.type dyn_atomic_fetch_add_u64,@function
dyn_atomic_fetch_add_u64:
    mov %rsi, %rax
    lock xadd %rax, (%rdi)
    ret
.section .text.dyn_atomic_compare_exchange_u64,"ax",@progbits
.global dyn_atomic_compare_exchange_u64
.type dyn_atomic_compare_exchange_u64,@function
dyn_atomic_compare_exchange_u64:
    mov %rsi, %rax
    lock cmpxchg %rdx, (%rdi)
    sete %al
    movzbl %al, %eax
    ret

# clone-based thread. Stack storage belongs to caller and must outlive join.
# isize dyn_thread_spawn(void *base, usize size, fn, context, u32 *tid)
.section .text.dyn_thread_spawn,"ax",@progbits
.global dyn_thread_spawn
.type dyn_thread_spawn,@function
dyn_thread_spawn:
    add %rsi, %rdi
    and $-16, %rdi
    sub $16, %rdi
    mov %rdx, 0(%rdi)
    mov %rcx, 8(%rdi)
    mov %rdi, %rsi
    mov %r8, %rdx
    mov %r8, %r10
    xor %r8d, %r8d
    mov $56, %eax
    mov $0x350f00, %edi
    syscall
    test %rax, %rax
    jz .Ldyn_thread_child
    ret
.Ldyn_thread_child:
    pop %rax
    pop %rdi
    call *%rax
    mov %rax, %rdi
    mov $60, %eax
    syscall
    ud2

.section .text.dyn_sort_directory_entries,"ax",@progbits
.global dyn_sort_directory_entries
.type dyn_sort_directory_entries,@function
dyn_sort_directory_entries:
    push %rbx
    push %r12
    push %r13
    push %r14
    mov %rdi, %rbx
    mov %rsi, %r12
    mov %r12, %r13
.Lsort_outer:
    cmp $1, %r13
    jbe .Lsort_done
    mov $1, %r14
.Lsort_inner:
    cmp %r13, %r14
    jae .Lsort_next
    lea (%r14,%r14,2), %rax
    lea (,%rax,8), %rax
    lea (%rbx,%rax), %r9
    lea -24(%r9), %r8
    mov (%r8), %rdx
    mov (%r9), %rcx
    mov 8(%r8), %r10
    mov 8(%r9), %r11
    xor %eax, %eax
.Lsort_compare:
    cmp %r10, %rax
    jae .Lsort_left_end
    cmp %r11, %rax
    jae .Lsort_no_swap
    movzbl (%rdx,%rax), %edi
    movzbl (%rcx,%rax), %esi
    cmp %edi, %esi
    jb .Lsort_swap
    ja .Lsort_no_swap
    inc %rax
    jmp .Lsort_compare
.Lsort_left_end:
    cmp %r11, %r10
    ja .Lsort_swap
    jmp .Lsort_no_swap
.Lsort_swap:
    mov (%r8), %rax
    mov (%r9), %rdx
    mov %rdx, (%r8)
    mov %rax, (%r9)
    mov 8(%r8), %rax
    mov 8(%r9), %rdx
    mov %rdx, 8(%r8)
    mov %rax, 8(%r9)
    mov 16(%r8), %rax
    mov 16(%r9), %rdx
    mov %rdx, 16(%r8)
    mov %rax, 16(%r9)
.Lsort_no_swap:
    inc %r14
    jmp .Lsort_inner
.Lsort_next:
    dec %r13
    jmp .Lsort_outer
.Lsort_done:
    pop %r14
    pop %r13
    pop %r12
    pop %rbx
    ret
.section .note.GNU-stack,"",@progbits
