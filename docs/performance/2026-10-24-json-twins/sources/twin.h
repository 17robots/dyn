#ifndef JSON_TWIN_H
#define JSON_TWIN_H
#include <stddef.h>
#include <stdint.h>
typedef struct {
  uint64_t tag, bits;
} Value;
typedef struct {
  uint8_t *data;
  size_t capacity, offset, peak;
  uint64_t allocations, bytes, trace, flags;
} Arena;
typedef struct {
  const uint8_t *data;
  size_t len;
} Slice;
typedef struct {
  Slice source;
  size_t at;
  uint64_t error;
} Cursor;
typedef struct {
  Cursor cursor;
  Slice buffer;
  Value *values;
  size_t capacity, used, limit;
  Arena *arena;
} Parser;
typedef struct {
  const Value *root;
  uint64_t ok, detail;
  size_t offset, used, retained;
} Result;
enum {
  Missing = 0,
  Null = 1,
  Bool = 2,
  Number = 3,
  String = 4,
  Array = 5,
  Object = 6
};
enum {
  None = 0,
  Syntax = 1,
  TrailingData = 2,
  NumberOverflow = 3,
  Overlap = 4,
  SizeOverflow = 5
};
uint8_t *lab_push(Arena *, size_t, size_t);
void lab_rewind(Arena *, size_t);
void lab_copy(uint8_t *, const uint8_t *, size_t);
uint64_t lab_utf8(const uint8_t *, size_t);
double lab_decimal(const uint8_t *, size_t);
size_t lab_ascii(const uint8_t *, size_t);
void lab_set_mode(uint64_t);
void twin_parse(Arena *, const uint8_t *, size_t, Result *);
#endif
