#include <stdio.h>
#include <stdint.h>
static double a[65536], b[65536], c[65536];
int main(void) {
  size_t n = 256;
  for (size_t i = 0; i < n * n; ++i) { a[i] = (double)(i % 7) * 0.5; b[i] = (double)(i % 5) * 0.25; }
  for (int round = 0; round < 8; ++round)
    for (size_t i = 0; i < n; ++i)
      for (size_t j = 0; j < n; ++j) {
        double sum = 0.0;
        for (size_t k = 0; k < n; ++k) sum += a[i * n + k] * b[k * n + j];
        c[i * n + j] = sum + round;
      }
  double total = 0.0;
  for (size_t i = 0; i < n * n; ++i) total += c[i];
  printf("%llu\n", (unsigned long long)total);
}
