#include <stddef.h>
#include <stdint.h>

static long syscall6(long number, long a, long b, long c, long d, long e,
                     long f) {
  register long r10 __asm__("r10") = d;
  register long r8 __asm__("r8") = e;
  register long r9 __asm__("r9") = f;
  long result;
  __asm__ volatile("syscall"
                   : "=a"(result)
                   : "a"(number), "D"(a), "S"(b), "d"(c), "r"(r10), "r"(r8),
                     "r"(r9)
                   : "rcx", "r11", "memory");
  return result;
}

static int run(void) {
  const size_t capacity = 67108864;
  uint8_t *bytes = (uint8_t *)syscall6(9, 0, (long)capacity, 3, 34, -1, 0);
  if ((long)bytes < 0)
    return 101;

  uint64_t checksum = 0;
  for (size_t i = 0; i < capacity; ++i) {
    uint8_t value = (uint8_t)(i & 255);
    bytes[i] = value;
  }
  for (size_t i = 0; i < capacity; ++i) {
    uint8_t value = bytes[i];
    checksum += value;
  }

  if (checksum != UINT64_C(8556380160))
    return 101;
  if (syscall6(11, (long)bytes, (long)capacity, 0, 0, 0, 0) != 0)
    return 101;
  return 0;
}

__attribute__((noreturn, force_align_arg_pointer)) void _start(void) {
  int status = run();
  syscall6(60, status, 0, 0, 0, 0, 0);
  __builtin_unreachable();
}
