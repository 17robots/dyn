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

// The length of the prefix of data[0..length] that the JSON string scanner
// can copy as it is: no byte below 32, at or above 128, '"' or '\\'.
//   usize dyn_json_text_prefix(const u8 *data, usize length)
// Sixteen bytes at a time: a signed compare against 32 catches both the
// control bytes and those at or above 128. Reads only data[0..length].
#ifdef DYN_MACOS
.global _dyn_json_text_prefix
.private_extern _dyn_json_text_prefix
.set _dyn_json_text_prefix, dyn_json_text_prefix
#endif
#ifdef __ELF__
.section .text.dyn_json_text_prefix,"ax",@progbits
#else
.text
#endif
.global dyn_json_text_prefix
#ifdef __ELF__
.hidden dyn_json_text_prefix
#endif
dyn_json_text_prefix:
#ifdef DYN_WINDOWS
    mov %rcx, %r10
    mov %rdx, %r11
#else
    mov %rdi, %r10
    mov %rsi, %r11
#endif
    mov $0x20202020, %eax
    movd %eax, %xmm1
    pshufd $0, %xmm1, %xmm1
    mov $0x22222222, %eax
    movd %eax, %xmm3
    pshufd $0, %xmm3, %xmm3
    mov $0x5c5c5c5c, %eax
    movd %eax, %xmm4
    pshufd $0, %xmm4, %xmm4
    xor %ecx, %ecx
    cmp $16, %r11
    jb .Ldyn_json_text_tail
.Ldyn_json_text_loop:
    movdqu (%r10,%rcx), %xmm2
    movdqa %xmm1, %xmm5
    pcmpgtb %xmm2, %xmm5
    movdqa %xmm2, %xmm6
    pcmpeqb %xmm3, %xmm6
    por %xmm6, %xmm5
    pcmpeqb %xmm4, %xmm2
    por %xmm2, %xmm5
    pmovmskb %xmm5, %eax
    test %eax, %eax
    jnz .Ldyn_json_text_lane
    add $16, %rcx
    sub $16, %r11
    cmp $16, %r11
    jae .Ldyn_json_text_loop
.Ldyn_json_text_tail:
    test %r11, %r11
    jz .Ldyn_json_text_done
.Ldyn_json_text_scalar:
    movzbl (%r10,%rcx), %eax
    cmp $32, %eax
    jb .Ldyn_json_text_done
    cmp $128, %eax
    jae .Ldyn_json_text_done
    cmp $0x22, %eax
    je .Ldyn_json_text_done
    cmp $0x5c, %eax
    je .Ldyn_json_text_done
    inc %rcx
    dec %r11
    jnz .Ldyn_json_text_scalar
.Ldyn_json_text_done:
    mov %rcx, %rax
    ret
.Ldyn_json_text_lane:
    bsf %eax, %eax
    add %rcx, %rax
    ret
