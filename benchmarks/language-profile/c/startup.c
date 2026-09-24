__attribute__((noreturn)) void _start(void) {
  __asm__ volatile("syscall" : : "a"(60), "D"(0) : "rcx", "r11", "memory");
  __builtin_unreachable();
}
