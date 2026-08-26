.global _start
.type _start,@function
_start:
    call main
    mov %eax, %edi
    mov $60, %eax
    syscall
.global dyn_panic
.type dyn_panic,@function
dyn_panic:
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
    mov dyn_trace_depth(%rip), %rbx
.Ldyn_panic_frame:
    test %rbx, %rbx
    jz .Ldyn_panic_exit
    dec %rbx
    lea dyn_trace_frames(%rip), %r12
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
.Ldyn_panic_exit:
    mov $101, %edi
    mov $60, %eax
    syscall
    ud2
.section .rodata
.Ldyn_panic_newline:
    .byte 10
.Ldyn_panic_trace:
    .ascii "stack trace:\n"
.Ldyn_panic_at:
    .ascii "  at "
.text
.global dyn_trace_push
.type dyn_trace_push,@function
dyn_trace_push:
    mov dyn_trace_depth(%rip), %rax
    cmp $256, %rax
    jae .Ldyn_trace_push_done
    lea dyn_trace_frames(%rip), %rdx
    mov %rax, %rcx
    shl $4, %rcx
    mov %rdi, (%rdx,%rcx)
    mov %rsi, 8(%rdx,%rcx)
    inc %rax
    mov %rax, dyn_trace_depth(%rip)
.Ldyn_trace_push_done:
    ret
.global dyn_trace_pop
.type dyn_trace_pop,@function
dyn_trace_pop:
    mov dyn_trace_depth(%rip), %rax
    test %rax, %rax
    jz .Ldyn_trace_pop_done
    dec %rax
    mov %rax, dyn_trace_depth(%rip)
.Ldyn_trace_pop_done:
    ret
.comm dyn_trace_depth,8,8
.comm dyn_trace_frames,4096,16
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
.section .note.GNU-stack,"",@progbits
