#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <unistd.h>
int main(void) {
  unsigned char storage[4096]; size_t total = 0, n;
  while ((n = fread(storage, 1, sizeof storage, stdin)))
    total += n;
  unsigned char output = (unsigned char)total;
  if (write(1, &output, 1) != 1) return 1;
  return ferror(stdin);
}
