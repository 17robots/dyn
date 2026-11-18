.section .text._start,"ax",%progbits
#ifndef DYN_SHARED
.global _start
.type _start,%function
_start:
    bl main
    // Returning from main ends the process: through the C library's exit()
    // when one is linked (atexit handlers, stdio), else exit_group (94), so
    // other threads end too. exit is weak: zero when nothing defines it.
    adrp x1, :got:exit
    ldr x1, [x1, :got_lo12:exit]
    cbz x1, 1f
    blr x1
1:  mov x8, #94
    svc #0
    brk #0
.weak exit
#endif

.section .text.dyn_panic,"ax",%progbits
.global dyn_panic
.type dyn_panic,%function
dyn_panic:
    stp x0, x1, [sp, #-16]!
    // The trace begins at the caller: its return address and frame pointer.
    mov x0, x30
    mov x1, x29
    bl dyn_trace_capture
    ldp x0, x1, [sp]
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
    // A panic ends every thread, without atexit handlers.
    mov x8, #94
    svc #0
    brk #0

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
#ifndef DYN_RELEASE
    // Debug programs give each thread a stack for fault reports.
    bl dyn_trace_thread
#endif
    ldp x9, x0, [sp]
    blr x9
    mov x8, #93
    svc #0
    brk #0

# libc's atexit/pthread_atfork wrappers require the CRT DSO identity.
# An external C driver may provide a strong crtbegin definition instead.
.section .data.__dso_handle,"aw",@progbits
.p2align 3
.weak __dso_handle
.hidden __dso_handle
__dso_handle:
#ifdef DYN_SHARED
    .quad __dso_handle
#else
    .quad 0
#endif
