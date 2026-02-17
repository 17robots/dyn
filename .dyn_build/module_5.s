.text
__dyn_os_alloc:
    push %rbp
    mov %rsp, %rbp
    mov 24(%rbp), %rsi
    cmp $0, %rsi
    jle .Ldyn_alloc_fail
    mov $9, %rax
    xor %rdi, %rdi
    mov $3, %rdx
    mov $34, %r10
    mov $-1, %r8
    xor %r9, %r9
    syscall
    cmp $0, %rax
    jl .Ldyn_alloc_fail
    pop %rbp
    ret
.Ldyn_alloc_fail:
    xor %rax, %rax
    pop %rbp
    ret
__dyn_os_free:
    push %rbp
    mov %rsp, %rbp
    mov 32(%rbp), %rdi
    mov 24(%rbp), %rsi
    cmp $0, %rdi
    je .Ldyn_free_ret
    cmp $0, %rsi
    jle .Ldyn_free_ret
    mov $11, %rax
    syscall
.Ldyn_free_ret:
    xor %rax, %rax
    pop %rbp
    ret
__dyn_os_realloc:
    push %rbp
    mov %rsp, %rbp
    sub $8, %rsp
    mov 48(%rbp), %rdi
    mov 40(%rbp), %r8
    mov 24(%rbp), %r9
    cmp $0, %r9
    jle .Ldyn_realloc_new_zero
    cmp $0, %rdi
    je .Ldyn_realloc_alloc_only
    mov $9, %rax
    xor %rdi, %rdi
    mov %r9, %rsi
    mov $3, %rdx
    mov $34, %r10
    mov $-1, %r8
    xor %r9, %r9
    syscall
    cmp $0, %rax
    jl .Ldyn_realloc_fail
    mov %rax, -8(%rbp)
    mov 40(%rbp), %rcx
    mov 24(%rbp), %rdx
    cmp %rdx, %rcx
    cmovg %rdx, %rcx
    cmp $0, %rcx
    jle .Ldyn_realloc_skip_copy
    mov 48(%rbp), %rsi
    mov -8(%rbp), %rdi
    cld
    rep movsb
.Ldyn_realloc_skip_copy:
    mov 40(%rbp), %rsi
    cmp $0, %rsi
    jle .Ldyn_realloc_ret_new
    mov $11, %rax
    mov 48(%rbp), %rdi
    syscall
.Ldyn_realloc_ret_new:
    mov -8(%rbp), %rax
    add $8, %rsp
    pop %rbp
    ret
.Ldyn_realloc_alloc_only:
    mov $9, %rax
    xor %rdi, %rdi
    mov 24(%rbp), %rsi
    mov $3, %rdx
    mov $34, %r10
    mov $-1, %r8
    xor %r9, %r9
    syscall
    cmp $0, %rax
    jl .Ldyn_realloc_fail
    add $8, %rsp
    pop %rbp
    ret
.Ldyn_realloc_new_zero:
    cmp $0, %rdi
    je .Ldyn_realloc_fail
    cmp $0, %r8
    jle .Ldyn_realloc_fail
    mov $11, %rax
    mov %r8, %rsi
    syscall
.Ldyn_realloc_fail:
    xor %rax, %rax
    add $8, %rsp
    pop %rbp
    ret
.global mmem_free
mmem_free:
    push %rbp
    mov %rsp, %rbp
    mov 32(%rbp), %rax
    push %rax
    mov 24(%rbp), %rax
    push %rax
    mov 16(%rbp), %rax
    push %rax
    call __dyn_os_free
    add $24, %rsp
    mov %rbp, %rsp
    pop %rbp
    ret
.global mmem_allocator_ready
mmem_allocator_ready:
    push %rbp
    mov %rsp, %rbp
fn_1_L0:
    mov $1, %rax
    push %rax
fn_1_L1:
    pop %rax
    mov %rbp, %rsp
    pop %rbp
    ret
fn_1_L2:
    mov $0, %rax
    mov %rbp, %rsp
    pop %rbp
    ret
.global mmem_alloc
mmem_alloc:
    push %rbp
    mov %rsp, %rbp
    mov 24(%rbp), %rax
    push %rax
    mov 16(%rbp), %rax
    push %rax
    call __dyn_os_alloc
    add $16, %rsp
    mov %rbp, %rsp
    pop %rbp
    ret
.global mmem_realloc
mmem_realloc:
    push %rbp
    mov %rsp, %rbp
    mov 48(%rbp), %rax
    push %rax
    mov 40(%rbp), %rax
    push %rax
    mov 32(%rbp), %rax
    push %rax
    mov 24(%rbp), %rax
    push %rax
    mov 16(%rbp), %rax
    push %rax
    call __dyn_os_realloc
    add $40, %rsp
    mov %rbp, %rsp
    pop %rbp
    ret
