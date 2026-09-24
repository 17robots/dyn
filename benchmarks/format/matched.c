#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
static size_t decimal(unsigned char *out, uint64_t value) {
  size_t digits = 1;
  for (uint64_t n = value; n >= 10; n /= 10) ++digits;
  size_t i = digits;
  do { out[--i] = (unsigned char)('0' + value % 10); value /= 10; } while (i);
  return digits;
}
int main(void) {
  unsigned char storage[32]; uint64_t checksum = 0;
  for (uint64_t i = 0; i < 5000000; ++i) {
    size_t n = decimal(storage, i * 1000003); checksum += n + storage[0];
  }
  printf("%" PRIu64 "\n", checksum);
}
