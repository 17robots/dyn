// First occurrence of a byte, sixteen bytes at a time with SSE2, for
// std/bytes.find_byte on x86-64:
//   usize dyn_find_byte(const u8 *data, usize length, u8 byte)
// Returns the index of the first match, or length. Reads only data[0..length].
// Registers: r10 data, r11 bytes left, rcx index, xmm1 the byte in every
// lane, xmm2 the block. Only volatile registers are used on SysV and Win64.
#ifdef DYN_MACOS
.global _dyn_find_byte
.private_extern _dyn_find_byte
.set _dyn_find_byte, dyn_find_byte
#endif
#ifdef __ELF__
.section .text.dyn_find_byte,"ax",@progbits
#else
.text
#endif
.global dyn_find_byte
#ifdef __ELF__
.hidden dyn_find_byte
#endif
dyn_find_byte:
#ifdef DYN_WINDOWS
    mov %rcx, %r10
    mov %rdx, %r11
    movzbl %r8b, %eax
#else
    mov %rdi, %r10
    mov %rsi, %r11
    movzbl %dl, %eax
#endif
    imul $0x01010101, %eax, %eax
    movd %eax, %xmm1
    pshufd $0, %xmm1, %xmm1
    xor %ecx, %ecx
    cmp $16, %r11
    jb .Ldyn_find_byte_tail
.Ldyn_find_byte_loop:
    movdqu (%r10,%rcx), %xmm2
    pcmpeqb %xmm1, %xmm2
    pmovmskb %xmm2, %eax
    test %eax, %eax
    jnz .Ldyn_find_byte_lane
    add $16, %rcx
    sub $16, %r11
    cmp $16, %r11
    jae .Ldyn_find_byte_loop
.Ldyn_find_byte_tail:
    movd %xmm1, %eax
    test %r11, %r11
    jz .Ldyn_find_byte_done
.Ldyn_find_byte_scalar:
    cmp %al, (%r10,%rcx)
    je .Ldyn_find_byte_done
    inc %rcx
    dec %r11
    jnz .Ldyn_find_byte_scalar
.Ldyn_find_byte_done:
    mov %rcx, %rax
    ret
.Ldyn_find_byte_lane:
    bsf %eax, %eax
    add %rcx, %rax
    ret
