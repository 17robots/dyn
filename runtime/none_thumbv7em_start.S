// Bare-metal ARMv7E-M for the QEMU mps2-an500 board: one Cortex-M7 with a
// double-precision FPU (qemu-system-arm -machine mps2-an500 -kernel program
// -semihosting-config enable=on,target=native).
// The image runs from SSRAM1 at address 0, where the vector table must be.
// SSRAM2/3 at 0x20000000 holds the arenas (3 MiB) and the stack (its last
// 1 MiB). Output goes to the CMSDK UART0 at 0x40004000; exit uses the Arm
// semihosting call SYS_EXIT_EXTENDED, which ends QEMU with the status.
//
// Code generated for Thumb keeps every 64-bit value in a pair of words: A in
// r0:r4 and C in r2:r5. The dyn_t32_* helpers below work on that model
// directly: inputs in A and C, mode in r10, result in A. They may change
// r10, r12, lr and s24-s28 and preserve every other register.
.syntax unified
.text
// Vector table: initial stack pointer, reset, then every exception.
.global _vectors
_vectors:
#ifdef DYN_NUCLEO_H753ZI
    .long 0x20020000
#else
    .long 0x20400000
#endif
    .long _start
    .long dyn_trap
    .long dyn_trap
    .long dyn_trap
    .long dyn_trap
    .long dyn_trap
    .long 0
    .long 0
    .long 0
    .long 0
    .long dyn_trap
    .long dyn_trap
    .long 0
    .long dyn_trap
    .long dyn_trap
#ifdef DYN_NUCLEO_H753ZI
    // All external interrupt vectors lead to the fatal handler (IRQs 0..149).
    .long dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap
    .long dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap
    .long dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap
    .long dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap
    .long dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap
    .long dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap
    .long dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap
    .long dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap
    .long dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap
    .long dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap
    .long dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap
    .long dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap
    .long dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap
    .long dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap
    .long dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap, dyn_trap
#endif
.global _start
_start:
#ifndef DYN_SOFT_FLOAT
    // Enable CP10 and CP11 (the FPU) in CPACR.
    movw r0, #0xED88
    movt r0, #0xE000
    ldr.w r1, [r0]
    orr.w r1, r1, #0xF00000
    str.w r1, [r0]
    dsb sy
    isb sy
#endif
#ifdef DYN_NUCLEO_H753ZI
    bl dyn_board_initialize
#else
    // Enable the UART transmitter.
    movw r0, #0x4000
    movt r0, #0x4000
    mov.w r1, #1
    str.w r1, [r0, #8]
#endif
    movw r0, #:lower16:__bss_start
    movt r0, #:upper16:__bss_start
    movw r1, #:lower16:_end
    movt r1, #:upper16:_end
    mov.w r2, #0
.Lzero:
    cmp.w r0, r1
    bhs.w .Lmain
    strb.w r2, [r0], #1
    b.w .Lzero
.Lmain:
    bl main
    mov.w r0, #0
    bl dyn_exit
#ifdef DYN_NUCLEO_H753ZI
#include "nucleo_h753zi_board.S"
#else
// dyn_exit(status): 0 passes; any other status fails with that exit code.
.global dyn_exit
dyn_exit:
    sub.w sp, sp, #8
    movw r1, #0x0026
    movt r1, #0x0002
    str.w r1, [sp]
    str.w r0, [sp, #4]
    mov r1, sp
    mov.w r0, #0x20
    bkpt #0xab
.Lhalt:
    wfi
    b.w .Lhalt
// dyn_console_write(data, size: u64) writes bytes to the UART, waiting while
// it is full. Only the low word of size (r2) is used.
.global dyn_console_write
dyn_console_write:
    movw r12, #0x4000
    movt r12, #0x4000
    add.w r2, r0, r2
.Lnext:
    cmp.w r0, r2
    bhs.w .Ldone
.Lbusy:
    ldr.w r1, [r12, #4]
    tst.w r1, #1
    bne.w .Lbusy
    ldrb.w r1, [r0], #1
    str.w r1, [r12]
    b.w .Lnext
.Ldone:
    bx lr
// Arena backing: [dyn_memory_start(), dyn_memory_end()).
.global dyn_memory_start
dyn_memory_start:
    mov.w r0, #0x20000000
    bx lr
.global dyn_memory_end
dyn_memory_end:
    movw r0, #0
    movt r0, #0x202F
    bx lr
#endif
// dyn_panic(message, length: u64): the length arrives in r2:r3.
.global dyn_panic
dyn_panic:
    mov r4, r0
    mov r5, r2
    bl dyn_unwind_begin
    cmp.w r5, #0
    beq.w .Ltrace
    mov r0, r4
    mov r2, r5
    mov.w r3, #0
    bl dyn_console_write
    movw r0, #:lower16:.Lnewline
    movt r0, #:upper16:.Lnewline
    mov.w r2, #1
    mov.w r3, #0
    bl dyn_console_write
.Ltrace:
#ifndef DYN_RELEASE
    bl dyn_trace_dump
#endif
    mov.w r0, #101
    bl dyn_exit
// Any fault is fatal: there is no recovery on bare metal. A fault while
// reporting a fault exits at once instead of looping.
.global dyn_stack_overflow
dyn_stack_overflow:
#ifdef DYN_NUCLEO_H753ZI
    movw r0, #0
    movt r0, #0x2002
#else
    mov.w r0, #0x20400000
#endif
    mov sp, r0
    movw r0, #:lower16:.Lstack_overflow
    movt r0, #:upper16:.Lstack_overflow
    mov.w r2, #15
    mov.w r3, #0
    bl dyn_console_write
    mov.w r0, #104
    bl dyn_exit
dyn_trap:
#ifdef DYN_NUCLEO_H753ZI
    movw r0, #0
    movt r0, #0x2002
#else
    mov.w r0, #0x20400000
#endif
    mov sp, r0
    movw r1, #:lower16:.Ltrapped
    movt r1, #:upper16:.Ltrapped
    ldr.w r2, [r1]
    cmp.w r2, #0
    bne.w .Ltrap_again
    mov.w r2, #1
    str.w r2, [r1]
    movw r0, #:lower16:.Ltrap
    movt r0, #:upper16:.Ltrap
    mov.w r2, #15
    mov.w r3, #0
    bl dyn_console_write
    mov.w r0, #102
    bl dyn_exit
.Ltrap_again:
    mov.w r0, #103
    bl dyn_exit
// Unwind buffers: one eight-byte slot per register from offset 8.
// Soft mode reuses bytes 88..151 for the complete private frame bank.
// r11+4028 == unbiased FP-64 (T32_BIAS=4092, T32_SAVED=64).
// Snapshot, rather than merely retaining the frame pointer: execution after
// unwind_set may overwrite logical high words and comparison/flag slots.
.global dyn_unwind_set
dyn_unwind_set:
    str.w r4, [r0, #8]
    str.w r5, [r0, #16]
    str.w r6, [r0, #24]
    str.w r7, [r0, #32]
    str.w r8, [r0, #40]
    str.w r9, [r0, #48]
    str.w r10, [r0, #56]
    str.w r11, [r0, #64]
    str.w lr, [r0, #72]
    mov r1, sp
    str.w r1, [r0, #80]
#ifdef DYN_SOFT_FLOAT
    ldr.w r2, [r11, #4028]
    str.w r2, [r0, #88]
    ldr.w r2, [r11, #4032]
    str.w r2, [r0, #92]
    ldr.w r2, [r11, #4036]
    str.w r2, [r0, #96]
    ldr.w r2, [r11, #4040]
    str.w r2, [r0, #100]
    ldr.w r2, [r11, #4044]
    str.w r2, [r0, #104]
    ldr.w r2, [r11, #4048]
    str.w r2, [r0, #108]
    ldr.w r2, [r11, #4052]
    str.w r2, [r0, #112]
    ldr.w r2, [r11, #4056]
    str.w r2, [r0, #116]
    ldr.w r2, [r11, #4060]
    str.w r2, [r0, #120]
    ldr.w r2, [r11, #4064]
    str.w r2, [r0, #124]
    ldr.w r2, [r11, #4068]
    str.w r2, [r0, #128]
    ldr.w r2, [r11, #4072]
    str.w r2, [r0, #132]
    ldr.w r2, [r11, #4076]
    str.w r2, [r0, #136]
    ldr.w r2, [r11, #4080]
    str.w r2, [r0, #140]
    ldr.w r2, [r11, #4084]
    str.w r2, [r0, #144]
    ldr.w r2, [r11, #4088]
    str.w r2, [r0, #148]
#else
    vstr d8, [r0, #88]
    vstr d9, [r0, #96]
    vstr d10, [r0, #104]
    vstr d11, [r0, #112]
    vstr d12, [r0, #120]
    vstr d13, [r0, #128]
    vstr d14, [r0, #136]
    vstr d15, [r0, #144]
#endif
    mov.w r0, #0
    bx lr
.global dyn_unwind_jump
dyn_unwind_jump:
    ldr.w r4, [r0, #8]
    ldr.w r5, [r0, #16]
    ldr.w r6, [r0, #24]
    ldr.w r7, [r0, #32]
    ldr.w r8, [r0, #40]
    ldr.w r9, [r0, #48]
    ldr.w r10, [r0, #56]
    ldr.w r11, [r0, #64]
    ldr.w lr, [r0, #72]
    ldr.w r1, [r0, #80]
    mov sp, r1
#ifdef DYN_SOFT_FLOAT
    ldr.w r2, [r0, #88]
    str.w r2, [r11, #4028]
    ldr.w r2, [r0, #92]
    str.w r2, [r11, #4032]
    ldr.w r2, [r0, #96]
    str.w r2, [r11, #4036]
    ldr.w r2, [r0, #100]
    str.w r2, [r11, #4040]
    ldr.w r2, [r0, #104]
    str.w r2, [r11, #4044]
    ldr.w r2, [r0, #108]
    str.w r2, [r11, #4048]
    ldr.w r2, [r0, #112]
    str.w r2, [r11, #4052]
    ldr.w r2, [r0, #116]
    str.w r2, [r11, #4056]
    ldr.w r2, [r0, #120]
    str.w r2, [r11, #4060]
    ldr.w r2, [r0, #124]
    str.w r2, [r11, #4064]
    ldr.w r2, [r0, #128]
    str.w r2, [r11, #4068]
    ldr.w r2, [r0, #132]
    str.w r2, [r11, #4072]
    ldr.w r2, [r0, #136]
    str.w r2, [r11, #4076]
    ldr.w r2, [r0, #140]
    str.w r2, [r11, #4080]
    ldr.w r2, [r0, #144]
    str.w r2, [r11, #4084]
    ldr.w r2, [r0, #148]
    str.w r2, [r11, #4088]
#else
    vldr d8, [r0, #88]
    vldr d9, [r0, #96]
    vldr d10, [r0, #104]
    vldr d11, [r0, #112]
    vldr d12, [r0, #120]
    vldr d13, [r0, #128]
    vldr d14, [r0, #136]
    vldr d15, [r0, #144]
#endif
    mov.w r0, #1
    bx lr
// Atomics. 32-bit operations use exclusive access; 64-bit ones run with
// interrupts masked, which suffices on a single core.
.global dyn_atomic_load_u32
dyn_atomic_load_u32:
    dmb sy
    ldr.w r0, [r0]
    dmb sy
    bx lr
.global dyn_atomic_store_u32
dyn_atomic_store_u32:
    dmb sy
    str.w r1, [r0]
    dmb sy
    bx lr
.global dyn_atomic_exchange_u32
dyn_atomic_exchange_u32:
    dmb sy
.Lexchange32:
    ldrex r2, [r0]
    strex r3, r1, [r0]
    cmp.w r3, #0
    bne.w .Lexchange32
    dmb sy
    mov r0, r2
    bx lr
.global dyn_atomic_fetch_add_u32
dyn_atomic_fetch_add_u32:
    dmb sy
.Ladd32:
    ldrex r2, [r0]
    add.w r12, r2, r1
    strex r3, r12, [r0]
    cmp.w r3, #0
    bne.w .Ladd32
    dmb sy
    mov r0, r2
    bx lr
.global dyn_atomic_compare_exchange_u32
dyn_atomic_compare_exchange_u32:
    dmb sy
.Lcas32:
    ldrex r3, [r0]
    cmp.w r3, r1
    bne.w .Lcasfail32
    strex r12, r2, [r0]
    cmp.w r12, #0
    bne.w .Lcas32
    mov.w r0, #1
    b.w .Lcasend32
.Lcasfail32:
    clrex
    mov.w r0, #0
.Lcasend32:
    dmb sy
    bx lr
.global dyn_atomic_load_u64
dyn_atomic_load_u64:
    mrs r12, primask
    cpsid i
    ldr.w r1, [r0, #4]
    ldr.w r0, [r0]
    msr primask, r12
    bx lr
// store_u64(address, value r2:r3)
.global dyn_atomic_store_u64
dyn_atomic_store_u64:
    mrs r12, primask
    cpsid i
    str.w r2, [r0]
    str.w r3, [r0, #4]
    msr primask, r12
    bx lr
.global dyn_atomic_exchange_u64
dyn_atomic_exchange_u64:
    mrs r12, primask
    cpsid i
    mov r1, r0
    ldr.w r0, [r1]
    str.w r2, [r1]
    ldr.w r2, [r1, #4]
    str.w r3, [r1, #4]
    mov r1, r2
    msr primask, r12
    bx lr
.global dyn_atomic_fetch_add_u64
dyn_atomic_fetch_add_u64:
    push.w {r4, r5, r6, lr}
    mrs r12, primask
    cpsid i
    ldr.w r4, [r0]
    ldr.w r5, [r0, #4]
    adds.w r6, r4, r2
    str.w r6, [r0]
    adc.w r6, r5, r3
    str.w r6, [r0, #4]
    msr primask, r12
    mov r0, r4
    mov r1, r5
    pop.w {r4, r5, r6, pc}
// compare_exchange_u64(address, expected r2:r3, desired on the stack) bool
.global dyn_atomic_compare_exchange_u64
dyn_atomic_compare_exchange_u64:
    push.w {r4, r5, r6, lr}
    mrs r12, primask
    cpsid i
    ldr.w r4, [r0]
    ldr.w r5, [r0, #4]
    cmp.w r4, r2
    bne.w .Lcasfail64
    cmp.w r5, r3
    bne.w .Lcasfail64
    ldr.w r6, [sp, #16]
    str.w r6, [r0]
    ldr.w r6, [sp, #20]
    str.w r6, [r0, #4]
    mov.w r0, #1
    b.w .Lcasend64
.Lcasfail64:
    mov.w r0, #0
.Lcasend64:
    msr primask, r12
    pop.w {r4, r5, r6, pc}

// 64-bit division. r10: 0 unsigned quotient, 1 unsigned remainder,
// 2 signed quotient, 3 signed remainder. The caller has excluded a zero
// divisor and the signed overflow case.
.global dyn_t32_divide
dyn_t32_divide:
    push.w {r1, r2, r3, r5, r6, r7, r8, r9, r11, lr}
    mov.w r1, #0
    mov.w r3, #0
    tst.w r10, #2
    beq.w .Ldivunsigned
    cmp.w r4, #0
    bge.w .Ldivnumerator
    rsbs.w r0, r0, #0
    sbc.w r4, r4, r4, lsl #1
    eor.w r1, r1, #1
    mov.w r3, #1
.Ldivnumerator:
    cmp.w r5, #0
    bge.w .Ldivunsigned
    rsbs.w r2, r2, #0
    sbc.w r5, r5, r5, lsl #1
    eor.w r1, r1, #1
.Ldivunsigned:
    mov.w r6, #0
    mov.w r7, #0
    mov.w r8, #0
    mov.w r9, #0
    mov.w r12, #64
.Ldivloop:
    lsl.w r9, r9, #1
    orr.w r9, r9, r8, lsr #31
    lsl.w r8, r8, #1
    orr.w r8, r8, r4, lsr #31
    lsl.w r4, r4, #1
    orr.w r4, r4, r0, lsr #31
    lsl.w r0, r0, #1
    lsl.w r7, r7, #1
    orr.w r7, r7, r6, lsr #31
    lsl.w r6, r6, #1
    subs.w r11, r8, r2
    sbcs.w lr, r9, r5
    blo.w .Ldivnext
    mov r8, r11
    mov r9, lr
    orr.w r6, r6, #1
.Ldivnext:
    subs.w r12, r12, #1
    bne.w .Ldivloop
    tst.w r10, #1
    beq.w .Ldivquotient
    mov r0, r8
    mov r4, r9
    cmp.w r3, #0
    beq.w .Ldivout
    b.w .Ldivnegate
.Ldivquotient:
    mov r0, r6
    mov r4, r7
    cmp.w r1, #0
    beq.w .Ldivout
.Ldivnegate:
    rsbs.w r0, r0, #0
    sbc.w r4, r4, r4, lsl #1
.Ldivout:
    pop.w {r1, r2, r3, r5, r6, r7, r8, r9, r11, pc}

// Checked 64-bit multiplication. r10: 0 unsigned, 1 signed. Leaves the low
// 64 bits of the product in A and r10 = 1 when the product does not fit.
.global dyn_t32_multiply
dyn_t32_multiply:
    push.w {r1, r2, r3, r5, r6, r7, r8, r9, r11, lr}
    mov.w r3, #0
    cmp.w r10, #0
    beq.w .Lmulunsigned
    cmp.w r4, #0
    bge.w .Lmulleft
    rsbs.w r0, r0, #0
    sbc.w r4, r4, r4, lsl #1
    eor.w r3, r3, #1
.Lmulleft:
    cmp.w r5, #0
    bge.w .Lmulunsigned
    rsbs.w r2, r2, #0
    sbc.w r5, r5, r5, lsl #1
    eor.w r3, r3, #1
.Lmulunsigned:
    mov.w r1, #0
    cmp.w r4, #0
    it ne
    cmpne.w r5, #0
    it ne
    movne.w r1, #1
    umull r6, r7, r0, r5
    cmp.w r7, #0
    it ne
    movne.w r1, #1
    umull r8, r9, r4, r2
    cmp.w r9, #0
    it ne
    movne.w r1, #1
    umull r0, r11, r0, r2
    adds.w r11, r11, r6
    it hs
    movhs.w r1, #1
    adds.w r4, r11, r8
    it hs
    movhs.w r1, #1
    cmp.w r10, #0
    beq.w .Lmuldone
    cmp.w r4, #0
    bge.w .Lmulsign
    // The top bit is set: only -2^63 fits.
    eor.w r6, r4, #0x80000000
    orrs.w r6, r6, r0
    it ne
    movne.w r1, #1
    cmp.w r3, #1
    it ne
    movne.w r1, #1
.Lmulsign:
    cmp.w r3, #0
    beq.w .Lmuldone
    rsbs.w r0, r0, #0
    sbc.w r4, r4, r4, lsl #1
.Lmuldone:
    mov r10, r1
    pop.w {r1, r2, r3, r5, r6, r7, r8, r9, r11, pc}

#ifndef DYN_SOFT_FLOAT
// 64-bit integer in A to floating bits in A. r10 bit 0: f32 result;
// bit 1: the integer is unsigned. Converts the magnitude with one rounding:
// hi * 2^32 + lo is exact before the final addition, and an f32 result from
// more than 53 significant bits first folds the low bits into a sticky bit.
.global dyn_t32_int_to_float
dyn_t32_int_to_float:
    push.w {r1, r2, r3, r5, r6, r7, r8, r9, r11, lr}
    vpush {d0, d1, d2}
    mov.w r3, #0
    tst.w r10, #2
    bne.w .Litfmagnitude
    cmp.w r4, #0
    bge.w .Litfmagnitude
    rsbs.w r0, r0, #0
    sbc.w r4, r4, r4, lsl #1
    mov.w r3, #1
.Litfmagnitude:
    mov.w r6, #0
    tst.w r10, #1
    beq.w .Litfconvert
    lsrs.w r7, r4, #21
    beq.w .Litfconvert
    ubfx r7, r0, #0, #11
    cmp.w r7, #0
    it ne
    movne.w r7, #1
    lsr.w r0, r0, #11
    orr.w r0, r0, r4, lsl #21
    lsr.w r4, r4, #11
    orr.w r0, r0, r7
    mov.w r6, #1
.Litfconvert:
    mov.w r7, #0
    movw r8, #0
    movt r8, #0x41F0
    vmov d2, r7, r8
    vmov s0, r4
    vcvt.f64.u32 d0, s0
    vmul.f64 d0, d0, d2
    vmov s2, r0
    vcvt.f64.u32 d1, s2
    vadd.f64 d0, d0, d1
    cmp.w r6, #0
    beq.w .Litfsign
    movt r8, #0x40A0
    vmov d1, r7, r8
    vmul.f64 d0, d0, d1
.Litfsign:
    cmp.w r3, #0
    beq.w .Litfresult
    vneg.f64 d0, d0
.Litfresult:
    tst.w r10, #1
    beq.w .Litfdouble
    vcvt.f32.f64 s0, d0
    vmov r0, s0
    mov.w r4, #0
    b.w .Litfout
.Litfdouble:
    vmov r0, r4, d0
.Litfout:
    vpop {d0, d1, d2}
    pop.w {r1, r2, r3, r5, r6, r7, r8, r9, r11, pc}

// Floating bits in A to a 64-bit integer in A, truncating toward zero.
// r10 bit 0: the input is f32; bit 1: the result is unsigned. NaN and values
// out of range give 0x8000000000000000, as x86-64 does.
.global dyn_t32_float_to_int
dyn_t32_float_to_int:
    push.w {r1, r2, r3, r5, r6, r7, r8, r9, r11, lr}
    vpush {d0, d1, d2}
    tst.w r10, #1
    beq.w .Lftidouble
    vmov s0, r0
    vcvt.f64.f32 d0, s0
    b.w .Lftiloaded
.Lftidouble:
    vmov d0, r0, r4
.Lftiloaded:
    // d2 <- 2^63
    mov.w r7, #0
    movw r8, #0
    movt r8, #0x43E0
    vmov d2, r7, r8
    // Unsigned values from 2^63 up: subtract 2^63 and set the top bit after.
    mov.w r6, #0
    tst.w r10, #2
    beq.w .Lftisign
    vcmp.f64 d0, d2
    vmrs APSR_nzcv, fpscr
    blt.w .Lftisign
    vsub.f64 d0, d0, d2
    mov.w r6, #1
.Lftisign:
    mov.w r3, #0
    vcmp.f64 d0, #0
    vmrs APSR_nzcv, fpscr
    bpl.w .Lftirange
    vneg.f64 d0, d0
    mov.w r3, #1
.Lftirange:
    // Valid when |x| < 2^63, or x == -2^63.
    vcmp.f64 d0, d2
    vmrs APSR_nzcv, fpscr
    bmi.w .Lftisplit
    bne.w .Lftiinvalid
    cmp.w r3, #0
    beq.w .Lftiinvalid
.Lftisplit:
    // hi = trunc(|x| / 2^32); lo = trunc(|x| - hi * 2^32)
    movt r8, #0x41F0
    vmov d1, r7, r8
    vdiv.f64 d2, d0, d1
    vcvt.u32.f64 s4, d2
    vmov r4, s4
    vcvt.f64.u32 d2, s4
    vmul.f64 d2, d2, d1
    vsub.f64 d2, d0, d2
    vcvt.u32.f64 s4, d2
    vmov r0, s4
    cmp.w r3, #0
    beq.w .Lftitop
    rsbs.w r0, r0, #0
    sbc.w r4, r4, r4, lsl #1
.Lftitop:
    cmp.w r6, #0
    beq.w .Lftiout
    eor.w r4, r4, #0x80000000
    b.w .Lftiout
.Lftiinvalid:
    mov.w r0, #0
    mov.w r4, #0x80000000
.Lftiout:
    vpop {d0, d1, d2}
    pop.w {r1, r2, r3, r5, r6, r7, r8, r9, r11, pc}
#endif
.section .rodata
.Lnewline: .byte 10
.Ltrap: .ascii "unexpected trap"
.Lstack_overflow: .ascii "stack overflow\n"
.data
.p2align 2
.Ltrapped: .long 0
