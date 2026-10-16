// RV64 LP64D: no compressed instructions or linker relaxation.
.text
#ifndef DYN_SHARED
.global _start
_start:
    call main
    lga t0, exit
    beq t0, zero, .Lexit
    jalr t0
.Lexit:
    li a7, 94
    ecall
    ebreak
.weak exit
#endif
.global dyn_panic
dyn_panic:
    addi sp, sp, -16
    sd a0, 0(sp)
    sd a1, 8(sp)
    call dyn_unwind_begin
    ld a1, 0(sp)
    ld a2, 8(sp)
    addi sp, sp, 16
    beq a2, zero, .Ltrace
    li a0, 2
    li a7, 64
    ecall
    la a1, .Lnewline
    li a0, 2
    li a2, 1
    li a7, 64
    ecall
.Ltrace:
#ifndef DYN_RELEASE
    li a0, 101
    call dyn_trace_dump
#endif
    li a0, 101
    li a7, 94
    ecall
    ebreak
.global dyn_unwind_set
dyn_unwind_set:
    sd s0, 8(a0)
    sd s1, 16(a0)
    sd s2, 24(a0)
    sd s3, 32(a0)
    sd s4, 40(a0)
    sd s5, 48(a0)
    sd s6, 56(a0)
    sd s7, 64(a0)
    sd s8, 72(a0)
    sd s9, 80(a0)
    sd s10, 88(a0)
    sd s11, 96(a0)
    sd ra, 104(a0)
    sd sp, 112(a0)
    fsd fs0, 120(a0)
    fsd fs1, 128(a0)
    fsd fs2, 136(a0)
    fsd fs3, 144(a0)
    fsd fs4, 152(a0)
    fsd fs5, 160(a0)
    fsd fs6, 168(a0)
    fsd fs7, 176(a0)
    fsd fs8, 184(a0)
    fsd fs9, 192(a0)
    fsd fs10, 200(a0)
    fsd fs11, 208(a0)
    li a0, 0
    ret
.global dyn_unwind_jump
dyn_unwind_jump:
    mv t0, a0
    ld s0, 8(t0)
    ld s1, 16(t0)
    ld s2, 24(t0)
    ld s3, 32(t0)
    ld s4, 40(t0)
    ld s5, 48(t0)
    ld s6, 56(t0)
    ld s7, 64(t0)
    ld s8, 72(t0)
    ld s9, 80(t0)
    ld s10, 88(t0)
    ld s11, 96(t0)
    ld ra, 104(t0)
    ld sp, 112(t0)
    fld fs0, 120(t0)
    fld fs1, 128(t0)
    fld fs2, 136(t0)
    fld fs3, 144(t0)
    fld fs4, 152(t0)
    fld fs5, 160(t0)
    fld fs6, 168(t0)
    fld fs7, 176(t0)
    fld fs8, 184(t0)
    fld fs9, 192(t0)
    fld fs10, 200(t0)
    fld fs11, 208(t0)
    li a0, 1
    ret
.global dyn_syscall6
dyn_syscall6:
    mv a7, a0
    mv a0, a1
    mv a1, a2
    mv a2, a3
    mv a3, a4
    mv a4, a5
    mv a5, a6
    ecall
    ret
.global dyn_atomic_load_u32
dyn_atomic_load_u32:
    fence rw, rw
    lwu a0, 0(a0)
    fence rw, rw
    ret
.global dyn_atomic_store_u32
dyn_atomic_store_u32:
    fence rw, rw
    sw a1, 0(a0)
    fence rw, rw
    ret
.global dyn_atomic_exchange_u32
dyn_atomic_exchange_u32:
    fence rw, rw
    amoswap.w.aqrl a0, a1, (a0)
    slli a0, a0, 32
    srli a0, a0, 32
    fence rw, rw
    ret
.global dyn_atomic_fetch_add_u32
dyn_atomic_fetch_add_u32:
    fence rw, rw
    amoadd.w.aqrl a0, a1, (a0)
    slli a0, a0, 32
    srli a0, a0, 32
    fence rw, rw
    ret
.global dyn_atomic_compare_exchange_u32
dyn_atomic_compare_exchange_u32:
    fence rw, rw
    slli a1, a1, 32
    srai a1, a1, 32
.Lcas32:
    lr.w.aq t0, (a0)
    bne t0, a1, .Lcasfail32
    sc.w.rl t1, a2, (a0)
    bne t1, zero, .Lcas32
    li a0, 1
    j .Lcasend32
.Lcasfail32:
    li a0, 0
.Lcasend32:
    fence rw, rw
    ret
.global dyn_atomic_load_u64
dyn_atomic_load_u64:
    fence rw, rw
    ld a0, 0(a0)
    fence rw, rw
    ret
.global dyn_atomic_store_u64
dyn_atomic_store_u64:
    fence rw, rw
    sd a1, 0(a0)
    fence rw, rw
    ret
.global dyn_atomic_exchange_u64
dyn_atomic_exchange_u64:
    fence rw, rw
    amoswap.d.aqrl a0, a1, (a0)
    fence rw, rw
    ret
.global dyn_atomic_fetch_add_u64
dyn_atomic_fetch_add_u64:
    fence rw, rw
    amoadd.d.aqrl a0, a1, (a0)
    fence rw, rw
    ret
.global dyn_atomic_compare_exchange_u64
dyn_atomic_compare_exchange_u64:
    fence rw, rw
.Lcas64:
    lr.d.aq t0, (a0)
    bne t0, a1, .Lcasfail64
    sc.d.rl t1, a2, (a0)
    bne t1, zero, .Lcas64
    li a0, 1
    j .Lcasend64
.Lcasfail64:
    li a0, 0
.Lcasend64:
    fence rw, rw
    ret
.global dyn_thread_spawn
dyn_thread_spawn:
    add a1, a0, a1
    andi a1, a1, -16
    addi a1, a1, -16
    sd a2, 0(a1)
    sd a3, 8(a1)
    mv a2, a4
    li a3, 0
    li a0, 0x350f00
    li a7, 220
    ecall
    beq a0, zero, .Lchild
    ret
.Lchild:
    ld t0, 0(sp)
    ld a0, 8(sp)
    jalr t0
    li a7, 93
    ecall
    ebreak
.section .rodata
.Lnewline: .byte 10
.section .data
.p2align 3
.weak __dso_handle
.hidden __dso_handle
__dso_handle:
#ifdef DYN_SHARED
    .quad __dso_handle
#else
    .quad 0
#endif
