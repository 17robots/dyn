#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define BITS 23
#define CAPACITY (1ull << 23)
#define INSERTS 4000000u

static size_t slot(uint64_t key) { return (size_t)((key * 11400714819323198485ull) >> (64 - BITS)); }

int main(void) {
  uint64_t *keys = calloc(CAPACITY, sizeof(uint64_t));
  uint64_t *counts = calloc(CAPACITY, sizeof(uint64_t));
  uint64_t state = 7;
  for (size_t n = 0; n < INSERTS; n++) {
    state = state * 6364136223846793005ull + 1442695040888963407ull;
    uint64_t key = (state >> 40) | 1;
    size_t at = slot(key);
    while (keys[at] != 0 && keys[at] != key) at = (at + 1) & (CAPACITY - 1);
    keys[at] = key;
    counts[at]++;
  }
  uint64_t found = 0;
  state = 7;
  for (size_t n = 0; n < 2 * INSERTS; n++) {
    state = state * 6364136223846793005ull + 1442695040888963407ull;
    uint64_t key = (state >> 40) | 1;
    size_t at = slot(key);
    while (keys[at] != 0 && keys[at] != key) at = (at + 1) & (CAPACITY - 1);
    if (keys[at] == key) found += counts[at];
  }
  printf("%llu\n", (unsigned long long)found);
  free(keys);
  free(counts);
  return 0;
}
