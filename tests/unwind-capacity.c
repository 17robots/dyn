#include <assert.h>
#include <setjmp.h>
#include <stdlib.h>
#include <string.h>
#include "../runtime/reference_support.c"
static long current_tid = 1;
static jmp_buf panic_jump;
static int panicked;
long dyn_syscall6(long number, long a, long b, long c, long d, long e, long f) {
  (void)number; (void)a; (void)b; (void)c; (void)d; (void)e; (void)f;
  return current_tid;
}
void dyn_unwind_jump(DynUnwind *frame) { (void)frame; abort(); }
void dyn_panic(const unsigned char *message, uint64_t length) {
  const char expected[] = "runtime unwind thread capacity exceeded";
  assert(length == sizeof(expected) - 1 && !memcmp(message, expected, length));
  panicked = 1;
  longjmp(panic_jump, 1);
}
int main(void) {
  DynUnwind frames[65] = {0};
  for (current_tid = 1; current_tid <= 64; ++current_tid)
    dyn_unwind_link(&frames[current_tid - 1]);
  if (!setjmp(panic_jump)) dyn_unwind_link(&frames[64]);
  assert(panicked);
  current_tid = 1; dyn_unwind_unlink(&frames[0]);
  current_tid = 65; dyn_unwind_link(&frames[64]);
  assert(unwind_slots[0].tid == 65 && unwind_slots[0].top == &frames[64]);
  dyn_unwind_unlink(&frames[64]);
  return 0;
}
