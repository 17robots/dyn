#include <stdio.h>
#include <stdint.h>
static uint64_t fib(uint64_t n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }
int main(void) { printf("%llu\n", (unsigned long long)fib(40)); }
