#include <stdio.h>
#include <stdint.h>
static uint8_t flags[8000000];
int main(void) {
  uint64_t total = 0;
  for (uint64_t round = 0; round < 10; ++round) {
    for (size_t i = 0; i < sizeof flags; ++i) flags[i] = 1;
    uint64_t count = 0;
    for (size_t i = 2; i < sizeof flags; ++i)
      if (flags[i] == 1) { ++count; for (size_t j = i * 2; j < sizeof flags; j += i) flags[j] = 0; }
    total += count + round;
  }
  printf("%llu\n", (unsigned long long)total);
}
