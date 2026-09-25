.text
.global run_probe
.type run_probe,@function
run_probe:
    movq %rsp, %rdx
    movq %rdi, %rsp
    movq %rsi, %rax
    movq $123, %r10
    movq $456, %r11
    call __chkstk
    cmpq %rdi, %rsp
    jne .Lfailed
    cmpq %rsi, %rax
    jne .Lfailed
    cmpq $123, %r10
    jne .Lfailed
    cmpq $456, %r11
    jne .Lfailed
    movq %rdx, %rsp
    movl $1, %eax
    ret
.Lfailed:
    movq %rdx, %rsp
    xorl %eax, %eax
    ret
.section .note.GNU-stack,"",@progbits
