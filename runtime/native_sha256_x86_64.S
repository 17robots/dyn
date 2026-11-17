// SHA-256 blocks with the x86 SHA extensions (SHA-NI), for std/crypto/core.
//   bool dyn_sha256_blocks(u32 state[8], const u8 *data, usize count)
// Returns false, changing nothing, when the CPU lacks SHA, SSSE3 or SSE4.1;
// the first call asks CPUID and later calls read the cached answer.
// Registers: xmm0 message + K (sha256rnds2 reads it), xmm1 ABEF, xmm2 CDGH,
// xmm3-6 the rolling message schedule, xmm7 scratch, xmm8 byte-swap mask,
// xmm9-10 the state saved for the block's final additions. Win64 keeps
// xmm6-xmm15, rdi and rsi, so only volatile general registers are used and
// xmm6-xmm10 are saved there.
#ifdef DYN_MACOS
.global _dyn_sha256_blocks
.private_extern _dyn_sha256_blocks
.set _dyn_sha256_blocks, dyn_sha256_blocks
#endif
#ifdef __ELF__
.section .text.dyn_sha256_blocks,"ax",@progbits
#else
.text
#endif
.global dyn_sha256_blocks
#ifdef __ELF__
.hidden dyn_sha256_blocks
#endif
dyn_sha256_blocks:
#ifdef DYN_WINDOWS
    mov %rcx, %r9
    mov %rdx, %r10
    mov %r8, %r11
#else
    mov %rdi, %r9
    mov %rsi, %r10
    mov %rdx, %r11
#endif
    mov .Ldyn_sha256_cpu(%rip), %eax
    test %eax, %eax
    jnz .Ldyn_sha256_known
    push %rbx
    xor %eax, %eax
    xor %ecx, %ecx
    cpuid
    mov $2, %edx
    cmp $7, %eax
    jb .Ldyn_sha256_store
    mov $7, %eax
    xor %ecx, %ecx
    cpuid
    mov $2, %edx
    test $0x20000000, %ebx
    jz .Ldyn_sha256_store
    mov $1, %eax
    cpuid
    mov $2, %edx
    and $0x80200, %ecx
    cmp $0x80200, %ecx
    jne .Ldyn_sha256_store
    mov $1, %edx
.Ldyn_sha256_store:
    pop %rbx
    mov %edx, .Ldyn_sha256_cpu(%rip)
    mov %edx, %eax
.Ldyn_sha256_known:
    cmp $1, %eax
    jne .Ldyn_sha256_unsupported
#ifdef DYN_WINDOWS
    sub $88, %rsp
    movdqu %xmm6, 0(%rsp)
    movdqu %xmm7, 16(%rsp)
    movdqu %xmm8, 32(%rsp)
    movdqu %xmm9, 48(%rsp)
    movdqu %xmm10, 64(%rsp)
#endif
    lea .Ldyn_sha256_k(%rip), %rax
    movdqu .Ldyn_sha256_flip(%rip), %xmm8
    movdqu 0(%r9), %xmm1
    movdqu 16(%r9), %xmm2
    pshufd $0xb1, %xmm1, %xmm1
    pshufd $0x1b, %xmm2, %xmm2
    movdqa %xmm1, %xmm7
    palignr $8, %xmm2, %xmm1
    pblendw $0xf0, %xmm7, %xmm2
    test %r11, %r11
    jz .Ldyn_sha256_done
.Ldyn_sha256_block:
    movdqa %xmm1, %xmm9
    movdqa %xmm2, %xmm10
    movdqu 0(%r10), %xmm0
    pshufb %xmm8, %xmm0
    movdqa %xmm0, %xmm3
    paddd 0(%rax), %xmm0
    sha256rnds2 %xmm1, %xmm2
    pshufd $0x0e, %xmm0, %xmm0
    sha256rnds2 %xmm2, %xmm1
    movdqu 16(%r10), %xmm0
    pshufb %xmm8, %xmm0
    movdqa %xmm0, %xmm4
    paddd 16(%rax), %xmm0
    sha256rnds2 %xmm1, %xmm2
    pshufd $0x0e, %xmm0, %xmm0
    sha256rnds2 %xmm2, %xmm1
    sha256msg1 %xmm4, %xmm3
    movdqu 32(%r10), %xmm0
    pshufb %xmm8, %xmm0
    movdqa %xmm0, %xmm5
    paddd 32(%rax), %xmm0
    sha256rnds2 %xmm1, %xmm2
    pshufd $0x0e, %xmm0, %xmm0
    sha256rnds2 %xmm2, %xmm1
    sha256msg1 %xmm5, %xmm4
    movdqu 48(%r10), %xmm0
    pshufb %xmm8, %xmm0
    movdqa %xmm0, %xmm6
    paddd 48(%rax), %xmm0
    sha256rnds2 %xmm1, %xmm2
    movdqa %xmm6, %xmm7
    palignr $4, %xmm5, %xmm7
    paddd %xmm7, %xmm3
    sha256msg2 %xmm6, %xmm3
    pshufd $0x0e, %xmm0, %xmm0
    sha256rnds2 %xmm2, %xmm1
    sha256msg1 %xmm6, %xmm5
    movdqa %xmm3, %xmm0
    paddd 64(%rax), %xmm0
    sha256rnds2 %xmm1, %xmm2
    movdqa %xmm3, %xmm7
    palignr $4, %xmm6, %xmm7
    paddd %xmm7, %xmm4
    sha256msg2 %xmm3, %xmm4
    pshufd $0x0e, %xmm0, %xmm0
    sha256rnds2 %xmm2, %xmm1
    sha256msg1 %xmm3, %xmm6
    movdqa %xmm4, %xmm0
    paddd 80(%rax), %xmm0
    sha256rnds2 %xmm1, %xmm2
    movdqa %xmm4, %xmm7
    palignr $4, %xmm3, %xmm7
    paddd %xmm7, %xmm5
    sha256msg2 %xmm4, %xmm5
    pshufd $0x0e, %xmm0, %xmm0
    sha256rnds2 %xmm2, %xmm1
    sha256msg1 %xmm4, %xmm3
    movdqa %xmm5, %xmm0
    paddd 96(%rax), %xmm0
    sha256rnds2 %xmm1, %xmm2
    movdqa %xmm5, %xmm7
    palignr $4, %xmm4, %xmm7
    paddd %xmm7, %xmm6
    sha256msg2 %xmm5, %xmm6
    pshufd $0x0e, %xmm0, %xmm0
    sha256rnds2 %xmm2, %xmm1
    sha256msg1 %xmm5, %xmm4
    movdqa %xmm6, %xmm0
    paddd 112(%rax), %xmm0
    sha256rnds2 %xmm1, %xmm2
    movdqa %xmm6, %xmm7
    palignr $4, %xmm5, %xmm7
    paddd %xmm7, %xmm3
    sha256msg2 %xmm6, %xmm3
    pshufd $0x0e, %xmm0, %xmm0
    sha256rnds2 %xmm2, %xmm1
    sha256msg1 %xmm6, %xmm5
    movdqa %xmm3, %xmm0
    paddd 128(%rax), %xmm0
    sha256rnds2 %xmm1, %xmm2
    movdqa %xmm3, %xmm7
    palignr $4, %xmm6, %xmm7
    paddd %xmm7, %xmm4
    sha256msg2 %xmm3, %xmm4
    pshufd $0x0e, %xmm0, %xmm0
    sha256rnds2 %xmm2, %xmm1
    sha256msg1 %xmm3, %xmm6
    movdqa %xmm4, %xmm0
    paddd 144(%rax), %xmm0
    sha256rnds2 %xmm1, %xmm2
    movdqa %xmm4, %xmm7
    palignr $4, %xmm3, %xmm7
    paddd %xmm7, %xmm5
    sha256msg2 %xmm4, %xmm5
    pshufd $0x0e, %xmm0, %xmm0
    sha256rnds2 %xmm2, %xmm1
    sha256msg1 %xmm4, %xmm3
    movdqa %xmm5, %xmm0
    paddd 160(%rax), %xmm0
    sha256rnds2 %xmm1, %xmm2
    movdqa %xmm5, %xmm7
    palignr $4, %xmm4, %xmm7
    paddd %xmm7, %xmm6
    sha256msg2 %xmm5, %xmm6
    pshufd $0x0e, %xmm0, %xmm0
    sha256rnds2 %xmm2, %xmm1
    sha256msg1 %xmm5, %xmm4
    movdqa %xmm6, %xmm0
    paddd 176(%rax), %xmm0
    sha256rnds2 %xmm1, %xmm2
    movdqa %xmm6, %xmm7
    palignr $4, %xmm5, %xmm7
    paddd %xmm7, %xmm3
    sha256msg2 %xmm6, %xmm3
    pshufd $0x0e, %xmm0, %xmm0
    sha256rnds2 %xmm2, %xmm1
    sha256msg1 %xmm6, %xmm5
    movdqa %xmm3, %xmm0
    paddd 192(%rax), %xmm0
    sha256rnds2 %xmm1, %xmm2
    movdqa %xmm3, %xmm7
    palignr $4, %xmm6, %xmm7
    paddd %xmm7, %xmm4
    sha256msg2 %xmm3, %xmm4
    pshufd $0x0e, %xmm0, %xmm0
    sha256rnds2 %xmm2, %xmm1
    sha256msg1 %xmm3, %xmm6
    movdqa %xmm4, %xmm0
    paddd 208(%rax), %xmm0
    sha256rnds2 %xmm1, %xmm2
    movdqa %xmm4, %xmm7
    palignr $4, %xmm3, %xmm7
    paddd %xmm7, %xmm5
    sha256msg2 %xmm4, %xmm5
    pshufd $0x0e, %xmm0, %xmm0
    sha256rnds2 %xmm2, %xmm1
    movdqa %xmm5, %xmm0
    paddd 224(%rax), %xmm0
    sha256rnds2 %xmm1, %xmm2
    movdqa %xmm5, %xmm7
    palignr $4, %xmm4, %xmm7
    paddd %xmm7, %xmm6
    sha256msg2 %xmm5, %xmm6
    pshufd $0x0e, %xmm0, %xmm0
    sha256rnds2 %xmm2, %xmm1
    movdqa %xmm6, %xmm0
    paddd 240(%rax), %xmm0
    sha256rnds2 %xmm1, %xmm2
    pshufd $0x0e, %xmm0, %xmm0
    sha256rnds2 %xmm2, %xmm1
    paddd %xmm9, %xmm1
    paddd %xmm10, %xmm2
    add $64, %r10
    dec %r11
    jnz .Ldyn_sha256_block
.Ldyn_sha256_done:
    pshufd $0x1b, %xmm1, %xmm1
    pshufd $0xb1, %xmm2, %xmm2
    movdqa %xmm1, %xmm7
    pblendw $0xf0, %xmm2, %xmm1
    palignr $8, %xmm7, %xmm2
    movdqu %xmm1, 0(%r9)
    movdqu %xmm2, 16(%r9)
#ifdef DYN_WINDOWS
    movdqu 0(%rsp), %xmm6
    movdqu 16(%rsp), %xmm7
    movdqu 32(%rsp), %xmm8
    movdqu 48(%rsp), %xmm9
    movdqu 64(%rsp), %xmm10
    add $88, %rsp
#endif
    mov $1, %eax
    ret
.Ldyn_sha256_unsupported:
    xor %eax, %eax
    ret
.data
.p2align 2
.Ldyn_sha256_cpu:
    .long 0
.section .rodata
.p2align 4
.Ldyn_sha256_flip:
    .quad 0x0405060700010203, 0x0c0d0e0f08090a0b
.Ldyn_sha256_k:
    .long 0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5
    .long 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5
    .long 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3
    .long 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174
    .long 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc
    .long 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da
    .long 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7
    .long 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967
    .long 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13
    .long 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85
    .long 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3
    .long 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070
    .long 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5
    .long 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3
    .long 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208
    .long 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
