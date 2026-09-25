#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
int main(void) {
  uint64_t value = 1;
  for (size_t i = 0; i < 50000000; ++i)
    value = (value * UINT64_C(1664525) + UINT64_C(1013904223)) & UINT64_C(0xffffffff);
  printf("%" PRIu64 "\n", value);
}
