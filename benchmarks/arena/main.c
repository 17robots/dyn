#define _GNU_SOURCE
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>

typedef struct {
  unsigned char *data;
  size_t capacity;
  size_t at;
} Arena;

static unsigned char *arena_try_push(Arena *arena, size_t size,
                                     size_t alignment) {
  if (alignment == 0 || (alignment & (alignment - 1)) != 0) return 0;
  if (size == 0) return 0;
  if (!arena->data || arena->at >= arena->capacity) return 0;
  unsigned char *current = arena->data + arena->at;
  size_t remainder = (uintptr_t)current & (alignment - 1);
  size_t padding = remainder == 0 ? 0 : alignment - remainder;
  size_t remaining = arena->capacity - arena->at;
  if (padding > remaining || size > remaining - padding) return 0;
  if (size > SIZE_MAX - padding || padding + size > SIZE_MAX - arena->at)
    return 0;
  current += padding;
  arena->at += padding + size;
  memset(current, 0, size);
  return current;
}

int main(void) {
  size_t capacity = 64 * 1024;
  Arena arena = {mmap(0, capacity, PROT_READ | PROT_WRITE,
                      MAP_PRIVATE | MAP_ANONYMOUS, -1, 0), capacity, 0};
  if (arena.data == MAP_FAILED) return 1;
  uint64_t checksum = 0;
  for (size_t i = 0; i < 2000000; ++i) {
    if (capacity - arena.at < 32) arena.at = 0;
    unsigned char *bytes = arena_try_push(&arena, 32, 8);
    if (!bytes) return 2;
    bytes[0] = (unsigned char)i;
    checksum += bytes[0];
  }
  printf("%" PRIu64 "\n", checksum);
  return munmap(arena.data, capacity) != 0;
}
