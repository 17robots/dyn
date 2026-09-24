#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
int main(void) {
  char storage[32]; uint64_t checksum = 0;
  for (uint64_t i = 0; i < 5000000; ++i) {
    int n = snprintf(storage, sizeof storage, "%" PRIu64, i * 1000003);
    checksum += (uint64_t)n + (unsigned char)storage[0];
  }
  printf("%" PRIu64 "\n", checksum);
}
