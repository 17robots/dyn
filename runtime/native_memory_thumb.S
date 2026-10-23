.syntax unified
.text
.global memcpy
memcpy:
.global memmove
memmove:
    mov r12, r0
    cmp.w r2, #0
    beq.w .Lcopydone
    cmp.w r0, r1
    blo.w .Lforward
    add.w r12, r12, r2
    add.w r1, r1, r2
.Lback:
    ldrb.w r3, [r1, #-1]!
    strb.w r3, [r12, #-1]!
    subs.w r2, r2, #1
    bne.w .Lback
    bx lr
.Lforward:
    ldrb.w r3, [r1], #1
    strb.w r3, [r12], #1
    subs.w r2, r2, #1
    bne.w .Lforward
.Lcopydone:
    bx lr
.global memset
memset:
    mov r12, r0
    cmp.w r2, #0
    beq.w .Lsetdone
.Lset:
    strb.w r1, [r12], #1
    subs.w r2, r2, #1
    bne.w .Lset
.Lsetdone:
    bx lr
