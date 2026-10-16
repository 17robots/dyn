.text
.global memcpy
memcpy:
.global memmove
memmove:
    mv t0, a0
    beq a2, zero, .Lcopydone
    bltu a0, a1, .Lforward
    add t0, t0, a2
    add a1, a1, a2
.Lback:
    addi t0, t0, -1
    addi a1, a1, -1
    lbu t1, 0(a1)
    sb t1, 0(t0)
    addi a2, a2, -1
    bne a2, zero, .Lback
    ret
.Lforward:
    lbu t1, 0(a1)
    sb t1, 0(t0)
    addi t0, t0, 1
    addi a1, a1, 1
    addi a2, a2, -1
    bne a2, zero, .Lforward
.Lcopydone:
    ret
.global memset
memset:
    mv t0, a0
    beq a2, zero, .Lsetdone
.Lset:
    sb a1, 0(t0)
    addi t0, t0, 1
    addi a2, a2, -1
    bne a2, zero, .Lset
.Lsetdone:
    ret
