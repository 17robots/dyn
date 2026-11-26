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
    // The trace begins at the caller: its return address and frame pointer.
    mv a0, ra
    mv a1, s0
    call dyn_trace_capture
    ld a0, 0(sp)
    ld a1, 8(sp)
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
#ifndef DYN_RELEASE
    // Debug programs give each thread a stack for fault reports.
    call dyn_trace_thread
#endif
    ld t0, 0(sp)
    ld a0, 8(sp)
    jalr t0
    li a7, 93
    ecall
    ebreak
# void dyn_fiber_switch(usize *save, usize load): saves ra, s0-s11 and
# fs0-fs11 on the current stack, stores its pointer in *save and resumes the
# stack at load. A new fiber's first frame returns into dyn_fiber_boot with
# s1 = entry and s2 = argument.
.section .text.dyn_fiber_switch,"ax",@progbits
.global dyn_fiber_switch
dyn_fiber_switch:
    addi sp, sp, -208
    sd ra, 0(sp)
    sd s0, 8(sp)
    sd s1, 16(sp)
    sd s2, 24(sp)
    sd s3, 32(sp)
    sd s4, 40(sp)
    sd s5, 48(sp)
    sd s6, 56(sp)
    sd s7, 64(sp)
    sd s8, 72(sp)
    sd s9, 80(sp)
    sd s10, 88(sp)
    sd s11, 96(sp)
    fsd fs0, 104(sp)
    fsd fs1, 112(sp)
    fsd fs2, 120(sp)
    fsd fs3, 128(sp)
    fsd fs4, 136(sp)
    fsd fs5, 144(sp)
    fsd fs6, 152(sp)
    fsd fs7, 160(sp)
    fsd fs8, 168(sp)
    fsd fs9, 176(sp)
    fsd fs10, 184(sp)
    fsd fs11, 192(sp)
    sd sp, 0(a0)
    mv sp, a1
    ld ra, 0(sp)
    ld s0, 8(sp)
    ld s1, 16(sp)
    ld s2, 24(sp)
    ld s3, 32(sp)
    ld s4, 40(sp)
    ld s5, 48(sp)
    ld s6, 56(sp)
    ld s7, 64(sp)
    ld s8, 72(sp)
    ld s9, 80(sp)
    ld s10, 88(sp)
    ld s11, 96(sp)
    fld fs0, 104(sp)
    fld fs1, 112(sp)
    fld fs2, 120(sp)
    fld fs3, 128(sp)
    fld fs4, 136(sp)
    fld fs5, 144(sp)
    fld fs6, 152(sp)
    fld fs7, 160(sp)
    fld fs8, 168(sp)
    fld fs9, 176(sp)
    fld fs10, 184(sp)
    fld fs11, 192(sp)
    addi sp, sp, 208
    ret

.section .text.dyn_fiber_boot,"ax",@progbits
.global dyn_fiber_boot
dyn_fiber_boot:
    mv a0, s2
    jalr s1
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
