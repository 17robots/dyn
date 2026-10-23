// Bare-metal RV32 for the QEMU virt board, entered in machine mode on one hart
// (qemu-system-riscv32 -machine virt -bios none -kernel program).
// RAM is 0x80000000..0x88000000 (the default 128 MiB); the stack is its last
// 1 MiB and arenas take the memory between the image end and the stack.
// Output goes to the NS16550 UART at 0x10000000. Exit writes the SiFive test
// device at 0x100000, which ends QEMU with the program's status.
//
// Code generated for RV32 keeps every 64-bit value in a register pair: the
// low word where RV64 keeps the whole value (a0 for A, t0 for C) and the
// high word in s2 (A) or s3 (C). The dyn_rv32_* helpers below work on that
// model directly: inputs in A and C, mode in t1, result in A. They may change
// t1, t2, a7, t3-t6, s10 and s11 and preserve every other register.
.text
.global _start
_start:
    li sp, 0x88000000
    la t0, dyn_trap
    csrw mtvec, t0
#ifndef DYN_SOFT_FLOAT
    li t0, 0x2000
    csrs mstatus, t0
#endif
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
// dyn_console_write(data, size: u64) writes bytes to the UART, waiting while
// it is busy. Only the low word of size is used.
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
// dyn_panic(message, length: u64): the length's high word arrives in a2.
.global dyn_panic
dyn_panic:
    addi sp, sp, -16
    sw a0, 0(sp)
    sw a1, 4(sp)
    sw a2, 8(sp)
    call dyn_unwind_begin
    lw a0, 0(sp)
    lw a1, 4(sp)
    addi sp, sp, 16
    beq a1, zero, .Ltrace
    li a2, 0
    call dyn_console_write
    la a0, .Lnewline
    li a1, 1
    li a2, 0
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
    li a2, 0
    call dyn_console_write
    li a0, 102
    call dyn_exit
// A trap while reporting a trap exits at once instead of looping.
.Ltrap_again:
    li sp, 0x88000000
    li a0, 103
    call dyn_exit
// Unwind buffers keep the RV64 layout: one eight-byte slot per register.
.global dyn_unwind_set
dyn_unwind_set:
    sw s0, 8(a0)
    sw s1, 16(a0)
    sw s2, 24(a0)
    sw s3, 32(a0)
    sw s4, 40(a0)
    sw s5, 48(a0)
    sw s6, 56(a0)
    sw s7, 64(a0)
    sw s8, 72(a0)
    sw s9, 80(a0)
    sw s10, 88(a0)
    sw s11, 96(a0)
    sw ra, 104(a0)
    sw sp, 112(a0)
#ifndef DYN_SOFT_FLOAT
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
#endif
    li a0, 0
    ret
.global dyn_unwind_jump
dyn_unwind_jump:
    mv t0, a0
    lw s0, 8(t0)
    lw s1, 16(t0)
    lw s2, 24(t0)
    lw s3, 32(t0)
    lw s4, 40(t0)
    lw s5, 48(t0)
    lw s6, 56(t0)
    lw s7, 64(t0)
    lw s8, 72(t0)
    lw s9, 80(t0)
    lw s10, 88(t0)
    lw s11, 96(t0)
    lw ra, 104(t0)
    lw sp, 112(t0)
#ifndef DYN_SOFT_FLOAT
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
#endif
    li a0, 1
    ret
// Atomics. One hart with interrupts off: 64-bit operations need no locking.
.global dyn_atomic_load_u32
dyn_atomic_load_u32:
    fence rw, rw
    lw a0, 0(a0)
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
    fence rw, rw
    ret
.global dyn_atomic_fetch_add_u32
dyn_atomic_fetch_add_u32:
    fence rw, rw
    amoadd.w.aqrl a0, a1, (a0)
    fence rw, rw
    ret
.global dyn_atomic_compare_exchange_u32
dyn_atomic_compare_exchange_u32:
    fence rw, rw
.Lcas32:
    lr.w.aq t0, (a0)
    bne t0, a1, .Lcasfail32
    sc.w.rl t1, a2, (a0)
    bne t1, zero, .Lcas32
    li a0, 1
    beq zero, zero, .Lcasend32
.Lcasfail32:
    li a0, 0
.Lcasend32:
    fence rw, rw
    ret
.global dyn_atomic_load_u64
dyn_atomic_load_u64:
    fence rw, rw
    lw a1, 4(a0)
    lw a0, 0(a0)
    fence rw, rw
    ret
.global dyn_atomic_store_u64
dyn_atomic_store_u64:
    fence rw, rw
    sw a1, 0(a0)
    sw a2, 4(a0)
    fence rw, rw
    ret
.global dyn_atomic_exchange_u64
dyn_atomic_exchange_u64:
    fence rw, rw
    lw t0, 0(a0)
    lw t1, 4(a0)
    sw a1, 0(a0)
    sw a2, 4(a0)
    mv a0, t0
    mv a1, t1
    fence rw, rw
    ret
.global dyn_atomic_fetch_add_u64
dyn_atomic_fetch_add_u64:
    fence rw, rw
    lw t0, 0(a0)
    lw t1, 4(a0)
    add t2, t0, a1
    sltu a3, t2, t0
    add a2, t1, a2
    add a2, a2, a3
    sw t2, 0(a0)
    sw a2, 4(a0)
    mv a0, t0
    mv a1, t1
    fence rw, rw
    ret
// compare_exchange_u64(address, expected a1:a2, desired a3:a4) bool
.global dyn_atomic_compare_exchange_u64
dyn_atomic_compare_exchange_u64:
    fence rw, rw
    lw t0, 0(a0)
    lw t1, 4(a0)
    bne t0, a1, .Lcasfail64
    bne t1, a2, .Lcasfail64
    sw a3, 0(a0)
    sw a4, 4(a0)
    li a0, 1
    beq zero, zero, .Lcasend64
.Lcasfail64:
    li a0, 0
.Lcasend64:
    fence rw, rw
    ret

// 64-bit division. t1: 0 unsigned quotient, 1 unsigned remainder,
// 2 signed quotient, 3 signed remainder. The caller has excluded a zero
// divisor and the signed overflow case.
.global dyn_rv32_divide
dyn_rv32_divide:
    addi sp, sp, -32
    sw t0, 0(sp)
    sw s3, 4(sp)
    sw a1, 8(sp)
    sw a2, 12(sp)
    sw a3, 16(sp)
    li t2, 0
    li a3, 0
    andi a7, t1, 2
    beq a7, zero, .Ldivunsigned
    bge s2, zero, .Ldivnumerator
    sltu t5, zero, a0
    sub a0, zero, a0
    sub s2, zero, s2
    sub s2, s2, t5
    xori t2, t2, 1
    li a3, 1
.Ldivnumerator:
    bge s3, zero, .Ldivunsigned
    sltu t5, zero, t0
    sub t0, zero, t0
    sub s3, zero, s3
    sub s3, s3, t5
    xori t2, t2, 1
.Ldivunsigned:
    li a1, 0
    li a2, 0
    li t3, 0
    li t4, 0
    li a7, 64
.Ldivloop:
    slli t4, t4, 1
    srli t5, t3, 31
    or t4, t4, t5
    slli t3, t3, 1
    srli t5, s2, 31
    or t3, t3, t5
    slli s2, s2, 1
    srli t5, a0, 31
    or s2, s2, t5
    slli a0, a0, 1
    slli a2, a2, 1
    srli t5, a1, 31
    or a2, a2, t5
    slli a1, a1, 1
    bltu t4, s3, .Ldivnext
    bne t4, s3, .Ldivsubtract
    bltu t3, t0, .Ldivnext
.Ldivsubtract:
    sltu t5, t3, t0
    sub t3, t3, t0
    sub t4, t4, s3
    sub t4, t4, t5
    addi a1, a1, 1
.Ldivnext:
    addi a7, a7, -1
    bne a7, zero, .Ldivloop
    andi t5, t1, 1
    beq t5, zero, .Ldivquotient
    mv a0, t3
    mv s2, t4
    beq a3, zero, .Ldivout
    beq zero, zero, .Ldivnegate
.Ldivquotient:
    mv a0, a1
    mv s2, a2
    beq t2, zero, .Ldivout
.Ldivnegate:
    sltu t5, zero, a0
    sub a0, zero, a0
    sub s2, zero, s2
    sub s2, s2, t5
.Ldivout:
    lw t0, 0(sp)
    lw s3, 4(sp)
    lw a1, 8(sp)
    lw a2, 12(sp)
    lw a3, 16(sp)
    addi sp, sp, 32
    ret

// Checked 64-bit multiplication. t1: 0 unsigned, 1 signed. Leaves the low
// 64 bits of the product in A and t1 = 1 when the product does not fit.
.global dyn_rv32_multiply
dyn_rv32_multiply:
    addi sp, sp, -32
    sw t0, 0(sp)
    sw s3, 4(sp)
    sw a1, 8(sp)
    sw a2, 12(sp)
    sw a3, 16(sp)
    sw a4, 20(sp)
    li a3, 0
    beq t1, zero, .Lmulunsigned
    bge s2, zero, .Lmulleft
    sltu t5, zero, a0
    sub a0, zero, a0
    sub s2, zero, s2
    sub s2, s2, t5
    xori a3, a3, 1
.Lmulleft:
    bge s3, zero, .Lmulunsigned
    sltu t5, zero, t0
    sub t0, zero, t0
    sub s3, zero, s3
    sub s3, s3, t5
    xori a3, a3, 1
.Lmulunsigned:
    sltu t2, zero, s2
    sltu t5, zero, s3
    and a4, t2, t5
    mulhu t2, a0, s3
    sltu t2, zero, t2
    or a4, a4, t2
    mul a1, a0, s3
    mulhu t2, s2, t0
    sltu t2, zero, t2
    or a4, a4, t2
    mul a2, s2, t0
    mulhu t2, a0, t0
    mul a0, a0, t0
    add t5, t2, a1
    sltu t6, t5, t2
    or a4, a4, t6
    add s2, t5, a2
    sltu t6, s2, t5
    or a4, a4, t6
    beq t1, zero, .Lmuldone
    srli t2, s2, 31
    beq t2, zero, .Lmulsign
    li t5, 0x80000000
    xor t5, s2, t5
    or t5, t5, a0
    sltu t5, zero, t5
    xori t6, a3, 1
    or t5, t5, t6
    or a4, a4, t5
.Lmulsign:
    beq a3, zero, .Lmuldone
    sltu t5, zero, a0
    sub a0, zero, a0
    sub s2, zero, s2
    sub s2, s2, t5
.Lmuldone:
    mv t1, a4
    lw t0, 0(sp)
    lw s3, 4(sp)
    lw a1, 8(sp)
    lw a2, 12(sp)
    lw a3, 16(sp)
    lw a4, 20(sp)
    addi sp, sp, 32
    ret

#ifndef DYN_SOFT_FLOAT
// 64-bit integer in A to floating bits in A. t1 bit 0: f32 result;
// bit 1: the integer is unsigned. Converts the magnitude with one rounding:
// hi * 2^32 + lo is exact before the final addition, and an f32 result from
// more than 53 significant bits first folds the low bits into a sticky bit.
.global dyn_rv32_int_to_float
dyn_rv32_int_to_float:
    addi sp, sp, -48
    sw a3, 0(sp)
    fsd f0, 8(sp)
    fsd f1, 16(sp)
    fsd f2, 24(sp)
    li a3, 0
    andi t2, t1, 2
    bne t2, zero, .Litfmagnitude
    bge s2, zero, .Litfmagnitude
    sltu t5, zero, a0
    sub a0, zero, a0
    sub s2, zero, s2
    sub s2, s2, t5
    li a3, 1
.Litfmagnitude:
    andi t2, t1, 1
    beq t2, zero, .Litfconvert
    srli t2, s2, 21
    beq t2, zero, .Litfconvert
    andi t5, a0, 2047
    sltu t5, zero, t5
    srli a0, a0, 11
    slli t6, s2, 21
    or a0, a0, t6
    srli s2, s2, 11
    or a0, a0, t5
    li t2, 1
    beq zero, zero, .Litfscaled
.Litfconvert:
    li t2, 0
.Litfscaled:
    li t5, 65536
    fcvt.d.wu f2, t5
    fmul.d f2, f2, f2
    fcvt.d.wu f0, s2
    fmul.d f0, f0, f2
    fcvt.d.wu f1, a0
    fadd.d f0, f0, f1
    beq t2, zero, .Litfsign
    li t5, 2048
    fcvt.d.wu f1, t5
    fmul.d f0, f0, f1
.Litfsign:
    beq a3, zero, .Litfresult
    fsgnjn.d f0, f0, f0
.Litfresult:
    andi t2, t1, 1
    beq t2, zero, .Litfdouble
    fcvt.s.d f0, f0
    fmv.x.w a0, f0
    li s2, 0
    beq zero, zero, .Litfout
.Litfdouble:
    fsd f0, 32(sp)
    lw a0, 32(sp)
    lw s2, 36(sp)
.Litfout:
    lw a3, 0(sp)
    fld f0, 8(sp)
    fld f1, 16(sp)
    fld f2, 24(sp)
    addi sp, sp, 48
    ret

// Floating bits in A to a 64-bit integer in A, truncating toward zero.
// t1 bit 0: the input is f32; bit 1: the result is unsigned. NaN and values
// out of range give 0x8000000000000000, as x86-64 does.
.global dyn_rv32_float_to_int
dyn_rv32_float_to_int:
    addi sp, sp, -48
    sw a3, 0(sp)
    sw a4, 4(sp)
    fsd f0, 8(sp)
    fsd f1, 16(sp)
    fsd f2, 24(sp)
    andi t2, t1, 1
    beq t2, zero, .Lftidouble
    fmv.w.x f0, a0
    fcvt.d.s f0, f0
    beq zero, zero, .Lftiloaded
.Lftidouble:
    sw a0, 32(sp)
    sw s2, 36(sp)
    fld f0, 32(sp)
.Lftiloaded:
    // f2 <- 2^63
    li t5, 65536
    fcvt.d.wu f2, t5
    fmul.d f2, f2, f2
    fmul.d f2, f2, f2
    li t5, 32768
    fcvt.d.wu f1, t5
    fmul.d f2, f2, f1
    // Unsigned values from 2^63 up: subtract 2^63 and set the top bit after.
    li a4, 0
    andi t2, t1, 2
    beq t2, zero, .Lftisign
    fle.d t2, f2, f0
    beq t2, zero, .Lftisign
    fsub.d f0, f0, f2
    li a4, 1
.Lftisign:
    li a3, 0
    fcvt.d.wu f1, zero
    flt.d t2, f0, f1
    beq t2, zero, .Lftirange
    fsgnjn.d f0, f0, f0
    li a3, 1
.Lftirange:
    // Valid when |x| < 2^63, or x == -2^63.
    flt.d t2, f0, f2
    bne t2, zero, .Lftisplit
    feq.d t2, f0, f2
    and t2, t2, a3
    beq t2, zero, .Lftiinvalid
.Lftisplit:
    // hi = trunc(|x| / 2^32); lo = trunc(|x| - hi * 2^32)
    li t5, 65536
    fcvt.d.wu f1, t5
    fmul.d f1, f1, f1
    fdiv.d f2, f0, f1, rtz
    fcvt.wu.d s2, f2, rtz
    fcvt.d.wu f2, s2
    fmul.d f2, f2, f1
    fsub.d f2, f0, f2
    fcvt.wu.d a0, f2, rtz
    beq a3, zero, .Lftitop
    sltu t5, zero, a0
    sub a0, zero, a0
    sub s2, zero, s2
    sub s2, s2, t5
.Lftitop:
    beq a4, zero, .Lftiout
    li t5, 0x80000000
    xor s2, s2, t5
    beq zero, zero, .Lftiout
.Lftiinvalid:
    li a0, 0
    li s2, 0x80000000
.Lftiout:
    lw a3, 0(sp)
    lw a4, 4(sp)
    fld f0, 8(sp)
    fld f1, 16(sp)
    fld f2, 24(sp)
    addi sp, sp, 48
    ret
#endif
.section .rodata
.Lnewline: .byte 10
.Ltrap: .ascii "unexpected trap"
.Lstack_overflow: .ascii "stack overflow\n"
