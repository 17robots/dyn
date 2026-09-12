.section .text._start,"ax",%progbits
#ifndef DYN_SHARED
.global _start
.type _start,%function
_start:
    bl main
    mov x8, #93
    svc #0
#endif

.section .text.dyn_panic,"ax",%progbits
.global dyn_panic
.type dyn_panic,%function
dyn_panic:
    stp x0, x1, [sp, #-16]!
    bl dyn_unwind_begin
    ldp x0, x1, [sp], #16
    cbz x1, 1f
    mov x2, x1
    mov x1, x0
    mov x0, #2
    mov x8, #64
    svc #0
    adrp x1, .Lnewline
    add x1, x1, :lo12:.Lnewline
    mov x0, #2
    mov x2, #1
    mov x8, #64
    svc #0
1:  mov x0, #101
#ifndef DYN_RELEASE
    bl dyn_trace_dump
    mov x0, #101
#endif
    mov x8, #93
    svc #0
    brk #0

.section .text.dyn_unwind_set,"ax",%progbits
.global dyn_unwind_set
.type dyn_unwind_set,%function
dyn_unwind_set:
    stp x19, x20, [x0, #8]
    stp x21, x22, [x0, #24]
    stp x23, x24, [x0, #40]
    stp x25, x26, [x0, #56]
    stp x27, x28, [x0, #72]
    stp x29, x30, [x0, #88]
    mov x1, sp
    str x1, [x0, #104]
    mov x0, #0
    ret
.global dyn_unwind_jump
.type dyn_unwind_jump,%function
dyn_unwind_jump:
    mov x9, x0
    ldp x19, x20, [x9, #8]
    ldp x21, x22, [x9, #24]
    ldp x23, x24, [x9, #40]
    ldp x25, x26, [x9, #56]
    ldp x27, x28, [x9, #72]
    ldp x29, x30, [x9, #88]
    ldr x10, [x9, #104]
    mov sp, x10
    mov x0, #1
    ret

.section .rodata
.Lnewline: .byte 10

.section .text.dyn_syscall6,"ax",%progbits
.global dyn_syscall6
.type dyn_syscall6,%function
dyn_syscall6:
    mov x8, x0
    mov x0, x1
    mov x1, x2
    mov x2, x3
    mov x3, x4
    mov x4, x5
    mov x5, x6
    svc #0
    ret

.section .text.dyn_atomic_load_u32,"ax",%progbits
.global dyn_atomic_load_u32
dyn_atomic_load_u32: ldar w0, [x0]; ret
.global dyn_atomic_store_u32
dyn_atomic_store_u32: stlr w1, [x0]; ret
.global dyn_atomic_exchange_u32
dyn_atomic_exchange_u32:
1:  ldaxr w2, [x0]; stlxr w3, w1, [x0]; cbnz w3, 1b; mov w0, w2; ret
.global dyn_atomic_fetch_add_u32
dyn_atomic_fetch_add_u32:
1:  ldaxr w2, [x0]; add w4, w2, w1; stlxr w3, w4, [x0]; cbnz w3, 1b; mov w0, w2; ret
.global dyn_atomic_compare_exchange_u32
dyn_atomic_compare_exchange_u32:
1:  ldaxr w3, [x0]; cmp w3, w1; b.ne 2f; stlxr w4, w2, [x0]; cbnz w4, 1b; mov w0, #1; ret
2:  clrex; mov w0, #0; ret

.section .text.dyn_atomic_load_u64,"ax",%progbits
.global dyn_atomic_load_u64
dyn_atomic_load_u64: ldar x0, [x0]; ret
.global dyn_atomic_store_u64
dyn_atomic_store_u64: stlr x1, [x0]; ret
.global dyn_atomic_exchange_u64
dyn_atomic_exchange_u64:
1:  ldaxr x2, [x0]; stlxr w3, x1, [x0]; cbnz w3, 1b; mov x0, x2; ret
.global dyn_atomic_fetch_add_u64
dyn_atomic_fetch_add_u64:
1:  ldaxr x2, [x0]; add x4, x2, x1; stlxr w3, x4, [x0]; cbnz w3, 1b; mov x0, x2; ret
.global dyn_atomic_compare_exchange_u64
dyn_atomic_compare_exchange_u64:
1:  ldaxr x3, [x0]; cmp x3, x1; b.ne 2f; stlxr w4, x2, [x0]; cbnz w4, 1b; mov w0, #1; ret
2:  clrex; mov w0, #0; ret

// clone-based thread. Caller owns stack until join completes.
// isize dyn_thread_spawn(void *base, usize size, fn, context, u32 *tid)
.section .text.dyn_thread_spawn,"ax",%progbits
.global dyn_thread_spawn
.type dyn_thread_spawn,%function
dyn_thread_spawn:
    add x1, x0, x1
    and x1, x1, #-16
    sub x1, x1, #16
    stp x2, x3, [x1]
    mov x2, x4
    mov x3, xzr
    mov x0, #0x0f00
    movk x0, #0x35, lsl #16
    mov x8, #220
    svc #0
    cbz x0, .Ldyn_thread_child
    ret
.Ldyn_thread_child:
    ldp x9, x0, [sp]
    blr x9
    mov x8, #93
    svc #0
    brk #0
