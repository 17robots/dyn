#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <unistd.h>
int main(void) {
  unsigned char storage[4096]; size_t total = 0; ssize_t n;
  while ((n = read(0, storage, sizeof storage)) > 0)
    total += (size_t)n;
  unsigned char output = (unsigned char)total;
  if (write(1, &output, 1) != 1) return 1;
  return n < 0;
}
