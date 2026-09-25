.text
// MS x64 stack-probe ABI: RAX is the requested frame size and is preserved.
// Probe every intervening page without changing the caller's stack pointer.
// ABI reference: LLVM compiler-rt/lib/builtins/x86_64/chkstk.S.
.global __chkstk
__chkstk:
    pushq %r10
    pushq %r11
    leaq 24(%rsp), %r10
    movq %r10, %r11
    subq %rax, %r11
.Ldyn_probe_next:
    cmpq %r11, %r10
    jbe .Ldyn_probe_done
    subq $4096, %r10
    cmpq %r11, %r10
    jae .Ldyn_probe_touch
    movq %r11, %r10
.Ldyn_probe_touch:
    testb $0, (%r10)
    jmp .Ldyn_probe_next
.Ldyn_probe_done:
    popq %r11
    popq %r10
    retq
#ifdef __ELF__
.section .note.GNU-stack,"",@progbits
#endif
