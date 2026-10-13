#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>

#define LIMIT 100000000ull

int main(void) {
  bool *composite = calloc(LIMIT + 1, sizeof(bool));
  unsigned long long count = 0;
  for (unsigned long long i = 2; i <= LIMIT; i++) {
    if (!composite[i]) {
      count++;
      for (unsigned long long j = i * i; j <= LIMIT; j += i) composite[j] = true;
    }
  }
  printf("%llu\n", count);
  free(composite);
  return 0;
}
