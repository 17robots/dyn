.text
#ifndef DYN_SHARED
.global _dyn_start
_dyn_start:
    bl _main
    mov x16, #1
    svc #0x80
    brk #0
#endif

.global _dyn_panic
_dyn_panic:
    stp x0, x1, [sp, #-16]!
    bl _dyn_unwind_begin
    brk #0

.global _dyn_unwind_set
_dyn_unwind_set:
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

.global _dyn_unwind_jump
_dyn_unwind_jump:
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

.global _dyn_trace_push
_dyn_trace_push: ret
.global _dyn_trace_pop
_dyn_trace_pop: ret

// Darwin arm64 syscall shim. Dyn passes Darwin's unclassed syscall number;
// x16 selects the Unix syscall class. Kernel errno is normalized to -errno.
.global _dyn_syscall6
_dyn_syscall6:
    mov x16, x0
    mov x0, x1
    mov x1, x2
    mov x2, x3
    mov x3, x4
    mov x4, x5
    mov x5, x6
    movk x16, #0x200, lsl #16
    svc #0x80
    b.cc 1f
    neg x0, x0
1:  ret

// Sequentially consistent public atomics. Acquire/release exclusives are the
// strongest portable arm64 implementation needed by std/thread.
.global _dyn_atomic_load_u32
_dyn_atomic_load_u32: ldar w0, [x0]; ret
.global _dyn_atomic_store_u32
_dyn_atomic_store_u32: stlr w1, [x0]; ret
.global _dyn_atomic_exchange_u32
_dyn_atomic_exchange_u32:
1:  ldaxr w2, [x0]; stlxr w3, w1, [x0]; cbnz w3, 1b; mov w0, w2; ret
.global _dyn_atomic_fetch_add_u32
_dyn_atomic_fetch_add_u32:
1:  ldaxr w2, [x0]; add w4, w2, w1; stlxr w3, w4, [x0]; cbnz w3, 1b; mov w0, w2; ret
.global _dyn_atomic_compare_exchange_u32
_dyn_atomic_compare_exchange_u32:
1:  ldaxr w3, [x0]; cmp w3, w1; b.ne 2f; stlxr w4, w2, [x0]; cbnz w4, 1b; mov w0, #1; ret
2:  clrex; mov w0, #0; ret
.global _dyn_atomic_load_u64
_dyn_atomic_load_u64: ldar x0, [x0]; ret
.global _dyn_atomic_store_u64
_dyn_atomic_store_u64: stlr x1, [x0]; ret
.global _dyn_atomic_exchange_u64
_dyn_atomic_exchange_u64:
1:  ldaxr x2, [x0]; stlxr w3, x1, [x0]; cbnz w3, 1b; mov x0, x2; ret
.global _dyn_atomic_fetch_add_u64
_dyn_atomic_fetch_add_u64:
1:  ldaxr x2, [x0]; add x4, x2, x1; stlxr w3, x4, [x0]; cbnz w3, 1b; mov x0, x2; ret
.global _dyn_atomic_compare_exchange_u64
_dyn_atomic_compare_exchange_u64:
1:  ldaxr x3, [x0]; cmp x3, x1; b.ne 2f; stlxr w4, x2, [x0]; cbnz w4, 1b; mov w0, #1; ret
2:  clrex; mov w0, #0; ret
