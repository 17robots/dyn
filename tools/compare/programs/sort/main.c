#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define COUNT 10000000u

static void quicksort(uint64_t *values, size_t length) {
  if (length < 2) return;
  uint64_t pivot = values[(length - 1) / 2];
  size_t i = 0, j = length - 1;
  for (;;) {
    while (values[i] < pivot) i++;
    while (values[j] > pivot) j--;
    if (i >= j) break;
    uint64_t swap = values[i];
    values[i] = values[j];
    values[j] = swap;
    i++;
    j--;
  }
  quicksort(values, j + 1);
  quicksort(values + j + 1, length - j - 1);
}

int main(void) {
  uint64_t *values = malloc(COUNT * sizeof(uint64_t));
  uint64_t state = 42;
  for (size_t i = 0; i < COUNT; i++) {
    state = state * 6364136223846793005ull + 1442695040888963407ull;
    values[i] = state >> 1;
  }
  quicksort(values, COUNT);
  printf("%llu %llu %llu\n", (unsigned long long)values[0], (unsigned long long)values[COUNT / 2],
         (unsigned long long)values[COUNT - 1]);
  free(values);
  return 0;
}
