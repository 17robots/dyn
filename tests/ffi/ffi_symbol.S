.global dyn_test_add
.type dyn_test_add,@function
dyn_test_add:
    lea (%rdi,%rsi), %rax
    ret
.section .note.GNU-stack,"",@progbits
