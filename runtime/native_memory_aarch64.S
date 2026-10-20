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
_bzero:
    mov x2, x1
    mov x1, #0
    b _memset
_memcpy:
#else
.global memcpy
.global memmove
.global memset
.hidden memcpy
.hidden memmove
.hidden memset
memcpy:
#endif
    mov x3, x0
    mov x4, x1
.Lmemory_copy:
    cmp x2, #16
    b.cc .Lmemory_copy_bytes
    ldp x5, x6, [x4]
    stp x5, x6, [x3]
    add x3, x3, #16
    add x4, x4, #16
    sub x2, x2, #16
    b .Lmemory_copy
.Lmemory_copy_bytes:
    cbz x2, .Lmemory_return
    ldrb w5, [x4]
    strb w5, [x3]
    add x3, x3, #1
    add x4, x4, #1
    sub x2, x2, #1
    b .Lmemory_copy_bytes
.Lmemory_return:
    ret
#ifdef DYN_MACOS
_memmove:
#else
memmove:
#endif
    mov x3, x0
    mov x4, x1
    cmp x0, x1
    b.ls .Lmemory_copy
    add x3, x3, x2
    add x4, x4, x2
.Lmemory_backward:
    cmp x2, #16
    b.cc .Lmemory_backward_bytes
    sub x3, x3, #16
    sub x4, x4, #16
    ldp x5, x6, [x4]
    stp x5, x6, [x3]
    sub x2, x2, #16
    b .Lmemory_backward
.Lmemory_backward_bytes:
    cbz x2, .Lmemory_return
    sub x3, x3, #1
    sub x4, x4, #1
    ldrb w5, [x4]
    strb w5, [x3]
    sub x2, x2, #1
    b .Lmemory_backward_bytes
#ifdef DYN_MACOS
_memset:
#else
memset:
#endif
    mov x3, x0
    and w1, w1, #255
    orr x1, x1, x1, lsl #8
    orr x1, x1, x1, lsl #16
    orr x1, x1, x1, lsl #32
.Lmemory_fill:
    cmp x2, #16
    b.cc .Lmemory_fill_bytes
    stp x1, x1, [x3]
    add x3, x3, #16
    sub x2, x2, #16
    b .Lmemory_fill
.Lmemory_fill_bytes:
    cbz x2, .Lmemory_return
    strb w1, [x3]
    add x3, x3, #1
    sub x2, x2, #1
    b .Lmemory_fill_bytes
