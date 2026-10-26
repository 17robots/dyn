#define _POSIX_C_SOURCE 200809L
#include "twin.h"
#include <dlfcn.h>
#include <inttypes.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
_Static_assert(sizeof(Value) == 16 && sizeof(Arena) == 64 &&
                   sizeof(Cursor) == 32 && sizeof(Parser) == 88 &&
                   sizeof(Result) == 48,
               "ABI layout");
void lab_reset_stats(int);
void lab_get_stats(uint64_t *);
size_t lab_get_events(uint64_t **);
typedef void (*Parse)(Arena *, const uint8_t *, size_t, Result *);
static unsigned char *file(const char *path, size_t *n) {
  FILE *f = fopen(path, "rb");
  if (!f)
    abort();
  fseek(f, 0, SEEK_END);
  long size = ftell(f);
  rewind(f);
  unsigned char *p = malloc((size_t)size + 1);
  if (!p)
    abort();
  if (fread(p, 1, (size_t)size, f) != (size_t)size)
    abort();
  fclose(f);
  *n = (size_t)size;
  return p;
}
static void hex(const uint8_t *p, size_t n) {
  for (size_t i = 0; i < n; i++)
    printf("%02x", p[i]);
}
static void show(const Result *r, const Arena *a) {
  printf("{\"ok\":%" PRIu64 ",\"detail\":%" PRIu64
         ",\"offset\":%zu,\"used\":%zu,\"retained\":%zu,\"arena\":[%zu,%zu,"
         "%" PRIu64 ",%" PRIu64 ",\"%016" PRIx64 "\"],\"nodes\":[",
         r->ok, r->detail, r->offset, r->used, r->retained, a->offset, a->peak,
         a->allocations, a->bytes, a->trace);
  if (r->ok)
    for (size_t i = 0; i < r->used; i++) {
      const Value *v = &r->root[i];
      if (i)
        putchar(',');
      printf("[\"%016" PRIx64 "\",", v->tag);
      if ((v->tag & 255) == String) {
        size_t len = (size_t)(v->tag >> 8);
        const uint8_t *p = (const uint8_t *)(uintptr_t)v->bits;
        if (len && ((uintptr_t)p < (uintptr_t)a->data || len > a->capacity ||
                    ((uintptr_t)p - (uintptr_t)a->data) > a->capacity - len))
          abort();
        putchar('"');
        hex(p, len);
        putchar('"');
      } else
        printf("\"%016" PRIx64 "\"", v->bits);
      putchar(']');
    }
  printf("],\"events\":[");
  uint64_t *events;
  size_t count = lab_get_events(&events);
  for (size_t i = 0; i < count; i++) {
    if (i)
      putchar(',');
    printf("[%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 "]", events[4 * i],
           events[4 * i + 1], events[4 * i + 2], events[4 * i + 3]);
  }
  uint64_t stats[14];
  lab_get_stats(stats);
  printf("],\"primitives\":[");
  for (unsigned i = 0; i < 14; i++)
    printf("%s%" PRIu64, i ? "," : "", stats[i]);
  printf("]}\n");
}
int main(int argc, char **argv) {
  if (argc < 5)
    return 2;
  void *h = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
  if (!h) {
    fprintf(stderr, "%s\n", dlerror());
    return 3;
  }
  Parse parse = (Parse)dlsym(h, "twin_parse");
  if (!parse)
    return 4;
  lab_set_mode(strtoull(argv[3], 0, 10));
  size_t n;
  uint8_t *data = file(argv[4], &n);
  size_t capacity = n > 65536 ? n * 20 + 4096 : 1048576;
  uint8_t *storage = malloc(capacity + 16);
  if (!storage)
    abort();
  Arena a = {.data = storage, .capacity = capacity};
  if (!strcmp(argv[2], "inspect")) {
    size_t pad = argc > 5 ? strtoull(argv[5], 0, 10) : 0;
    a.data += pad;
    a.offset = 3;
    a.peak = 3;
    a.trace = UINT64_C(1469598103934665603);
    memset(a.data, 0xa7, a.capacity);
    Result r;
    lab_reset_stats(1);
    parse(&a, data, n, &r);
    show(&r, &a);
  } else if (!strcmp(argv[2], "batch")) {
    FILE *f = fopen(argv[4], "rb");
    if (!f)
      abort();
    for (;;) {
      uint64_t len;
      if (fread(&len, 8, 1, f) != 1)
        break;
      if (len > capacity)
        abort();
      uint8_t *input = malloc((size_t)len + 1);
      if (!input)
        abort();
      if (fread(input, 1, (size_t)len, f) != (size_t)len)
        abort();
      a.offset = 3;
      a.peak = 3;
      a.allocations = a.bytes = 0;
      a.trace = UINT64_C(1469598103934665603);
      Result r;
      lab_reset_stats(1);
      parse(&a, input, (size_t)len, &r);
      show(&r, &a);
      free(input);
    }
    fclose(f);
  } else if (!strcmp(argv[2], "bench")) {
    size_t rounds = argc > 5 ? strtoull(argv[5], 0, 10) : 1;
    uint64_t checksum = 0, records = 0;
    lab_reset_stats(0);
    struct timespec start, end;
    clock_gettime(CLOCK_MONOTONIC, &start);
    for (size_t round = 0; round < rounds; round++) {
      const uint8_t *at = data, *last = data + n;
      while (at < last) {
        const uint8_t *e = memchr(at, 10, (size_t)(last - at));
        if (!e)
          e = last;
        if (e > at) {
          a.offset = 0;
          Result r;
          parse(&a, at, (size_t)(e - at), &r);
          if (!r.ok)
            return 5;
          checksum += r.root->tag >> 8;
          records++;
        }
        at = e == last ? last : e + 1;
      }
    }
    clock_gettime(CLOCK_MONOTONIC, &end);
    uint64_t stats[14];
    lab_get_stats(stats);
    printf("{\"records\":%" PRIu64 ",\"checksum\":%" PRIu64
           ",\"seconds\":%.9f,\"primitives\":[",
           records, checksum,
           (end.tv_sec - start.tv_sec) + (end.tv_nsec - start.tv_nsec) * 1e-9);
    for (unsigned i = 0; i < 14; i++)
      printf("%s%" PRIu64, i ? "," : "", stats[i]);
    printf("]}\n");
  } else
    return 2;
  free(storage);
  free(data);
  dlclose(h);
  return 0;
}
