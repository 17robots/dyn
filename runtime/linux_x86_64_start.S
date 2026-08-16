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
    mov $101, %edi
    mov $60, %eax
    syscall
    ud2
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
