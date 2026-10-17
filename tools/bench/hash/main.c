#include <stdio.h>
#include <stdint.h>
static uint8_t text[1048576];
static uint64_t fnv(const uint8_t *d, size_t n) {
  uint64_t h = 14695981039346656037ull;
  for (size_t i = 0; i < n; ++i) h = (h ^ d[i]) * 1099511628211ull;
  return h;
}
int main(void) {
  for (size_t i = 0; i < sizeof text; ++i) text[i] = (uint8_t)(i % 251);
  uint64_t total = 0;
  for (int round = 0; round < 100; ++round) { text[round] = (uint8_t)round; total += fnv(text, sizeof text); }
  printf("%llu\n", (unsigned long long)total);
}
