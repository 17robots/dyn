// Bare-metal RV64 for the QEMU virt board, entered in machine mode on one hart
// (qemu-system-riscv64 -machine virt -bios none -kernel program).
// RAM is 0x80000000..0x88000000 (the default 128 MiB); the stack is its last
// 1 MiB and arenas take the memory between the image end and the stack.
// Output goes to the NS16550 UART at 0x10000000. Exit writes the SiFive test
// device at 0x100000, which ends QEMU with the program's status.
.text
.global _start
_start:
    li sp, 0x88000000
    la t0, dyn_trap
    csrw mtvec, t0
    li t0, 0x2000
    csrs mstatus, t0
    la t0, __bss_start
    la t1, _end
    beq t0, zero, .Lmain
.Lzero:
    bgeu t0, t1, .Lmain
    sb zero, 0(t0)
    addi t0, t0, 1
    beq zero, zero, .Lzero
.Lmain:
    call main
    li a0, 0
    call dyn_exit
// dyn_exit(status): 0 passes; any other status fails with that exit code.
.global dyn_exit
dyn_exit:
    li t0, 0x100000
    li t1, 0x5555
    beq a0, zero, .Lfinish
    slli t1, a0, 16
    li t2, 0x3333
    or t1, t1, t2
.Lfinish:
    sw t1, 0(t0)
.Lhalt:
    wfi
    beq zero, zero, .Lhalt
// dyn_console_write(data, size) writes bytes to the UART, waiting while it is busy.
.global dyn_console_write
dyn_console_write:
    li t0, 0x10000000
    add a1, a0, a1
.Lnext:
    bgeu a0, a1, .Ldone
.Lbusy:
    lbu t1, 5(t0)
    andi t1, t1, 32
    beq t1, zero, .Lbusy
    lbu t1, 0(a0)
    sb t1, 0(t0)
    addi a0, a0, 1
    beq zero, zero, .Lnext
.Ldone:
    ret
// Arena backing: [dyn_memory_start(), dyn_memory_end()).
.global dyn_memory_start
dyn_memory_start:
    la a0, _end
    li t0, 4095
    add a0, a0, t0
    li t0, -4096
    and a0, a0, t0
    ret
.global dyn_memory_end
dyn_memory_end:
    li a0, 0x87F00000
    ret
.global dyn_panic
dyn_panic:
    addi sp, sp, -16
    sd a0, 0(sp)
    sd a1, 8(sp)
    call dyn_unwind_begin
    ld a0, 0(sp)
    ld a1, 8(sp)
    addi sp, sp, 16
    beq a1, zero, .Ltrace
    call dyn_console_write
    la a0, .Lnewline
    li a1, 1
    call dyn_console_write
.Ltrace:
#ifndef DYN_RELEASE
    call dyn_trace_dump
#endif
    li a0, 101
    call dyn_exit
// Any exception is fatal: there is no recovery on bare metal.
.p2align 2
.global dyn_stack_overflow
dyn_stack_overflow:
    li sp, 0x88000000
    la a0, .Lstack_overflow
    li a1, 15
    li a2, 0
    call dyn_console_write
    li a0, 104
    call dyn_exit
dyn_trap:
    la t0, .Ltrap_again
    csrw mtvec, t0
    li sp, 0x88000000
    la a0, .Ltrap
    li a1, 15
    call dyn_console_write
    li a0, 102
    call dyn_exit
// A trap while reporting a trap exits at once instead of looping.
.Ltrap_again:
    li sp, 0x88000000
    li a0, 103
    call dyn_exit
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
.section .rodata
.Lnewline: .byte 10
.Ltrap: .ascii "unexpected trap"
.Lstack_overflow: .ascii "stack overflow\n"
