#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <assert.h>
#include <signal.h>
#include <stdint.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>

extern int run_probe(void *stack, size_t bytes);
static unsigned char *mapping;
static volatile sig_atomic_t touched;
static unsigned char signal_stack[65536];
static void fault(int number, siginfo_t *info, void *context) {
  (void)number; (void)context;
  uintptr_t address = (uintptr_t)info->si_addr;
  uintptr_t base = (uintptr_t)mapping;
  if (address < base || address >= base + 4 * 4096) _exit(2);
  unsigned page = (unsigned)((address - base) / 4096);
  touched |= 1 << page;
  if (mprotect(mapping + page * 4096, 4096, PROT_READ | PROT_WRITE)) _exit(3);
}
int main(void) {
  assert(sysconf(_SC_PAGESIZE) == 4096);
  stack_t alternate = {.ss_sp = signal_stack, .ss_size = sizeof(signal_stack)};
  assert(!sigaltstack(&alternate, NULL));
  struct sigaction action = {.sa_sigaction = fault, .sa_flags = SA_SIGINFO | SA_ONSTACK};
  sigemptyset(&action.sa_mask);
  assert(!sigaction(SIGSEGV, &action, NULL));
  mapping = mmap(NULL, 5 * 4096, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
  assert(mapping != MAP_FAILED);
  assert(!mprotect(mapping + 4 * 4096, 4096, PROT_READ | PROT_WRITE));
  void *stack = mapping + 5 * 4096 - 256;
  assert(run_probe(stack, 0));
  assert(touched == 0);
  assert(run_probe(stack, 4 * 4096));
  assert(touched == 15); /* Every intervening page was touched, not only the last. */
  assert(run_probe(stack, 1));
  assert(!munmap(mapping, 5 * 4096));
  return 0;
}
