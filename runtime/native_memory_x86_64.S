// Freestanding memory primitives. String instructions permit arbitrary
// alignment; zero counts never dereference. Never change ABI's direction flag.
.text
#ifdef DYN_MACOS
.global _memcpy
.global _memmove
.global _memset
.global _bzero
.private_extern _memcpy
.private_extern _memmove
.private_extern _memset
.private_extern _bzero
.set _memcpy, memcpy
.set _memmove, memmove
.set _memset, memset
_bzero:
    mov %rsi, %rdx
    xor %esi, %esi
    jmp memset
#else
.global memcpy
.global memmove
.global memset
#endif
#ifndef DYN_WINDOWS
#ifndef DYN_MACOS
.hidden memcpy
.hidden memmove
.hidden memset
#endif
#endif
memcpy:
#ifdef DYN_WINDOWS
    push %rdi
    push %rsi
    mov %rcx, %rax
    mov %rcx, %rdi
    mov %rdx, %rsi
    mov %r8, %rcx
    rep movsb
    pop %rsi
    pop %rdi
#else
    mov %rdi, %rax
    mov %rdx, %rcx
    rep movsb
#endif
    ret
memmove:
#ifdef DYN_WINDOWS
    cmp %rdx, %rcx
    jbe memcpy
    mov %rcx, %rax
    add %r8, %rcx
    add %r8, %rdx
.Lmemory_backward:
    test %r8, %r8
    jz .Lmemory_return
    dec %rcx
    dec %rdx
    movzbl (%rdx), %r9d
    mov %r9b, (%rcx)
    dec %r8
#else
    cmp %rsi, %rdi
    jbe memcpy
    mov %rdi, %rax
    add %rdx, %rdi
    add %rdx, %rsi
.Lmemory_backward:
    test %rdx, %rdx
    jz .Lmemory_return
    dec %rdi
    dec %rsi
    movzbl (%rsi), %r9d
    mov %r9b, (%rdi)
    dec %rdx
#endif
    jmp .Lmemory_backward
.Lmemory_return:
    ret
memset:
#ifdef DYN_WINDOWS
    push %rdi
    mov %rcx, %rdi
    mov %rcx, %r9
    mov %edx, %eax
    mov %r8, %rcx
    rep stosb
    mov %r9, %rax
    pop %rdi
#else
    mov %rdi, %r8
    mov %esi, %eax
    mov %rdx, %rcx
    rep stosb
    mov %r8, %rax
#endif
    ret
