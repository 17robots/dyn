/* Literal control-flow port of original-read.dyn. No yyjson code. */
#include "twin.h"
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#ifndef CHECKED
#define CHECKED 0
#endif
static size_t add(size_t a, size_t b) {
  size_t r;
  if (CHECKED && __builtin_add_overflow(a, b, &r))
    abort();
  return a + b;
}
static size_t sub(size_t a, size_t b) {
  size_t r;
  if (CHECKED && __builtin_sub_overflow(a, b, &r))
    abort();
  return a - b;
}
static size_t mul(size_t a, size_t b) {
  size_t r;
  if (CHECKED && __builtin_mul_overflow(a, b, &r))
    abort();
  return a * b;
}
static void pointer_guard(const void *p, size_t alignment) {
  if (CHECKED && (!p || ((uintptr_t)p & (alignment - 1))))
    abort();
}
static Slice span(const uint8_t *p, size_t len) {
  if (CHECKED && len)
    pointer_guard(p, 1);
  return (Slice){p, len};
}
static Slice slice(Slice s, size_t first, size_t last) {
  if (CHECKED && (first > last || last > s.len))
    abort();
  if (CHECKED && s.len)
    pointer_guard(s.data, 1);
  return span(s.data + first, sub(last, first));
}
static uint8_t byte(Slice s, size_t i) {
  if (CHECKED && i >= s.len)
    abort();
  pointer_guard(s.data, 1);
  return s.data[i];
}
static void put(Slice s, size_t i, uint8_t v) {
  if (CHECKED && i >= s.len)
    abort();
  pointer_guard(s.data, 1);
  ((uint8_t *)s.data)[i] = v;
}
static Value *node(Parser *s, size_t i) {
  pointer_guard(s, _Alignof(Parser));
  if (CHECKED && i >= s->capacity)
    abort();
  pointer_guard(s->values, _Alignof(Value));
  return &s->values[i];
}
static const Value nil_value = {0, 0};
static size_t read_append(Parser *s, uint8_t kind, uint64_t bits) {
  if (s->used == s->capacity) {
    size_t old = s->capacity, capacity = mul(old, 2);
    if (capacity > s->limit)
      capacity = s->limit;
    if (capacity <= old)
      abort();
    uint8_t *tail = lab_push(s->arena, mul(sub(capacity, old), 16), 8);
    uintptr_t expected = add((uintptr_t)&s->values[0], mul(old, 16));
    if ((uintptr_t)tail != expected)
      abort();
    s->capacity = capacity;
  }
  size_t index = s->used;
  *node(s, index) = (Value){kind, bits};
  s->used = add(s->used, 1);
  return index;
}
static void read_skip(Cursor *c) {
  Slice source = c->source;
  size_t at = c->at;
  while (at < source.len) {
    uint8_t b = byte(source, at);
    if (b != ' ' && b != 10 && b != 13 && b != 9)
      break;
    at = add(at, 1);
  }
  c->at = at;
}
static Slice failed_string(Cursor *c) {
  if (c->error == None)
    c->error = Syntax;
  return slice(c->source, 0, 0);
}
static size_t hex_value(uint8_t b) {
  if (b >= '0' && b <= '9')
    return sub(b, '0');
  if (b >= 'a' && b <= 'f')
    return add(sub(b, 'a'), 10);
  if (b >= 'A' && b <= 'F')
    return add(sub(b, 'A'), 10);
  return 16;
}
static uint8_t utf8_byte(size_t v, uint8_t m) { return (uint8_t)v | m; }
static bool literal(Cursor *c, const char *t, size_t n) {
  if (add(c->at, n) > c->source.len)
    return false;
  for (size_t i = 0; i < n; i = add(i, 1))
    if (byte(c->source, add(c->at, i)) != (uint8_t)t[i])
      return false;
  c->at = add(c->at, n);
  return true;
}
static Slice read_decoded_string(Parser *s) {
  Cursor *c = &s->cursor;
  Slice source = c->source;
  if (c->at >= source.len || byte(source, c->at) != '"')
    return failed_string(c);
  c->at = add(c->at, 1);
  size_t start = c->at, end = start;
  end = add(end, lab_ascii(source.data + start, sub(source.len, start)));
  bool has_escape = false, ascii = true;
  while (end < source.len) {
    uint8_t b = byte(source, end);
    if (b == '"')
      break;
    if (b >= 128)
      ascii = false;
    if (b == '\\') {
      has_escape = true;
      end = add(end, 1);
      if (end >= source.len)
        return failed_string(c);
      b = byte(source, end);
      if (b >= 128)
        ascii = false;
    }
    if (b < 32)
      return failed_string(c);
    end = add(end, 1);
  }
  if (end >= source.len)
    return failed_string(c);
  if (!ascii && !lab_utf8(source.data + start, sub(end, start)))
    return failed_string(c);
  if (end == start) {
    c->at = add(end, 1);
    return slice(source, start, end);
  }
  Slice output = slice(s->buffer, start, end);
  if (!has_escape) {
    c->at = add(end, 1);
    return output;
  }
  size_t source_at = start, output_at = 0;
  while (source_at < end) {
    uint8_t b = byte(source, source_at);
    source_at = add(source_at, 1);
    if (b == '\\') {
      if (source_at >= end)
        return failed_string(c);
      uint8_t escaped = byte(source, source_at);
      source_at = add(source_at, 1);
      if (escaped == '"' || escaped == '\\' || escaped == '/')
        b = escaped;
      else if (escaped == 'b')
        b = 8;
      else if (escaped == 'f')
        b = 12;
      else if (escaped == 'n')
        b = '\n';
      else if (escaped == 'r')
        b = '\r';
      else if (escaped == 't')
        b = '\t';
      else if (escaped == 'u') {
        if (add(source_at, 4) > end)
          return failed_string(c);
        size_t code = 0;
        for (size_t digits = 0; digits < 4; digits = add(digits, 1)) {
          size_t part = hex_value(byte(source, source_at));
          if (part == 16)
            return failed_string(c);
          code = add(mul(code, 16), part);
          source_at = add(source_at, 1);
        }
        if (code >= 55296 && code <= 56319) {
          if (add(source_at, 6) > end || byte(source, source_at) != '\\' ||
              byte(source, add(source_at, 1)) != 'u')
            return failed_string(c);
          source_at = add(source_at, 2);
          size_t low = 0;
          for (size_t digits = 0; digits < 4; digits = add(digits, 1)) {
            size_t part = hex_value(byte(source, source_at));
            if (part == 16)
              return failed_string(c);
            low = add(mul(low, 16), part);
            source_at = add(source_at, 1);
          }
          if (low < 56320 || low > 57343)
            return failed_string(c);
          code = sub(add(add(65536, mul(sub(code, 55296), 1024)), low), 56320);
        } else if (code >= 56320 && code <= 57343)
          return failed_string(c);
        if (code <= 127) {
          put(output, output_at, (uint8_t)code);
          output_at = add(output_at, 1);
        } else if (code <= 2047) {
          put(output, output_at, utf8_byte(code >> 6, 192));
          put(output, add(output_at, 1), utf8_byte(code & 63, 128));
          output_at = add(output_at, 2);
        } else if (code <= 65535) {
          put(output, output_at, utf8_byte(code >> 12, 224));
          put(output, add(output_at, 1), utf8_byte((code >> 6) & 63, 128));
          put(output, add(output_at, 2), utf8_byte(code & 63, 128));
          output_at = add(output_at, 3);
        } else {
          put(output, output_at, utf8_byte(code >> 18, 240));
          put(output, add(output_at, 1), utf8_byte((code >> 12) & 63, 128));
          put(output, add(output_at, 2), utf8_byte((code >> 6) & 63, 128));
          put(output, add(output_at, 3), utf8_byte(code & 63, 128));
          output_at = add(output_at, 4);
        }
        continue;
      } else
        return failed_string(c);
    }
    put(output, output_at, b);
    output_at = add(output_at, 1);
  }
  c->at = add(end, 1);
  return slice(output, 0, output_at);
}
static bool read_number(Parser *s) {
  Slice source = s->cursor.source;
  size_t start = s->cursor.at, at = start;
  bool negative = byte(source, at) == '-';
  if (negative)
    at = add(at, 1);
  if (at == source.len)
    return false;
  uint64_t integer = 0;
  bool exact = true;
  uint8_t b = byte(source, at);
  if (b == '0')
    at = add(at, 1);
  else {
    if (b < '1' || b > '9')
      return false;
    while (at < source.len) {
      b = byte(source, at);
      if (b < '0' || b > '9')
        break;
      uint64_t n = sub(b, '0');
      if (exact) {
        if (integer > UINT64_C(1844674407370955161) ||
            (integer == UINT64_C(1844674407370955161) && n > 5))
          exact = false;
        else
          integer = integer * 10 + n;
      }
      at = add(at, 1);
    }
  }
  if (at < source.len && byte(source, at) == '.') {
    exact = false;
    at = add(at, 1);
    size_t begin = at;
    while (at < source.len) {
      b = byte(source, at);
      if (b < '0' || b > '9')
        break;
      at = add(at, 1);
    }
    if (at == begin) {
      s->cursor.at = at;
      return false;
    }
  }
  if (at < source.len && (byte(source, at) == 'e' || byte(source, at) == 'E')) {
    exact = false;
    at = add(at, 1);
    if (at < source.len && (byte(source, at) == '+' || byte(source, at) == '-'))
      at = add(at, 1);
    size_t begin = at;
    while (at < source.len) {
      b = byte(source, at);
      if (b < '0' || b > '9')
        break;
      at = add(at, 1);
    }
    if (at == begin) {
      s->cursor.at = at;
      return false;
    }
  }
  s->cursor.at = at;
  if (exact && !negative) {
    size_t i = read_append(s, Number, integer);
    node(s, i)->tag |= 256;
    return true;
  }
  if (exact && negative && integer != 0 &&
      integer <= UINT64_C(9223372036854775808)) {
    size_t i = read_append(s, Number, UINT64_C(0) - integer);
    node(s, i)->tag |= 512;
    return true;
  }
  double v = lab_decimal(source.data + start, sub(at, start));
  if (v > 1.7976931348623157e308 || v < -1.7976931348623157e308) {
    s->cursor.error = NumberOverflow;
    return false;
  }
  uint64_t bits;
  memcpy(&bits, &v, 8);
  size_t i = read_append(s, Number, bits);
  node(s, i)->tag |= 768;
  return true;
}
static bool read_value(Parser *s, size_t depth) {
  read_skip(&s->cursor);
  if (s->cursor.at == s->buffer.len)
    return false;
  uint8_t b = byte(s->buffer, s->cursor.at);
  if (b == '"') {
    Slice v = read_decoded_string(s);
    if (s->cursor.error != None)
      return false;
    uint64_t pointer = 0;
    if (v.len != 0)
      pointer = (uintptr_t)v.data;
    size_t i = read_append(s, String, pointer);
    node(s, i)->tag |= (uint64_t)v.len << 8;
    return true;
  }
  if (b == 'n') {
    if (!literal(&s->cursor, "null", 4))
      return false;
    (void)read_append(s, Null, 0);
    return true;
  }
  if (b == 't' || b == 'f') {
    bool truth = b == 't';
    if (truth) {
      if (!literal(&s->cursor, "true", 4))
        return false;
    } else {
      if (!literal(&s->cursor, "false", 5))
        return false;
    }
    uint64_t bits = 0;
    if (truth)
      bits = 1;
    (void)read_append(s, Bool, bits);
    return true;
  }
  if (b != '[' && b != '{')
    return read_number(s);
  if (depth >= 256)
    return false;
  bool object = b == '{';
  uint8_t kind = Array, close = ']';
  if (object) {
    kind = Object;
    close = '}';
  }
  size_t i = read_append(s, kind, 0);
  s->cursor.at = add(s->cursor.at, 1);
  read_skip(&s->cursor);
  size_t count = 0;
  if (s->cursor.at < s->buffer.len && byte(s->buffer, s->cursor.at) == close) {
    s->cursor.at = add(s->cursor.at, 1);
    node(s, i)->bits = sub(s->used, i);
    return true;
  }
  for (;;) {
    if (object) {
      read_skip(&s->cursor);
      if (s->cursor.at == s->buffer.len || byte(s->buffer, s->cursor.at) != '"')
        return false;
      if (!read_value(s, add(depth, 1)))
        return false;
      read_skip(&s->cursor);
      if (s->cursor.at == s->buffer.len || byte(s->buffer, s->cursor.at) != ':')
        return false;
      s->cursor.at = add(s->cursor.at, 1);
    }
    if (!read_value(s, add(depth, 1)))
      return false;
    count = add(count, 1);
    read_skip(&s->cursor);
    if (s->cursor.at == s->buffer.len)
      return false;
    b = byte(s->buffer, s->cursor.at);
    s->cursor.at = add(s->cursor.at, 1);
    if (b == close)
      break;
    if (b != ',')
      return false;
  }
  node(s, i)->tag |= (uint64_t)count << 8;
  node(s, i)->bits = sub(s->used, i);
  return true;
}
void twin_parse(Arena *a, const uint8_t *data, size_t len, Result *out) {
  pointer_guard(a, _Alignof(Arena));
  pointer_guard(out, _Alignof(Result));
  Slice source = span(data, len);
  (void)source;
  size_t mark = a->offset;
  *out = (Result){.root = &nil_value};
  if (len == 0) {
    out->detail = Syntax;
    return;
  }
  size_t limit = len;
  if (limit > SIZE_MAX / 16 || (uint64_t)len > UINT64_C(0x00ffffffffffffff)) {
    out->detail = SizeOverflow;
    return;
  }
  if (mark <= a->capacity) {
    uintptr_t x = (uintptr_t)(a->data + mark), y = (uintptr_t)data;
    size_t xn = sub(a->capacity, mark);
    if (xn && len && (x <= y ? y - x < xn : x - y < len)) {
      out->detail = Overlap;
      return;
    }
  }
  uint8_t *copy = lab_push(a, len, 1);
  Slice buffer = span(copy, len);
  lab_copy(copy, data, len);
  size_t capacity = add(len / 2, 1);
  if (capacity > 32)
    capacity = 32;
  Cursor probe = {.source = buffer};
  read_skip(&probe);
  if (probe.at < buffer.len && byte(buffer, probe.at) != '[' &&
      byte(buffer, probe.at) != '{')
    capacity = 1;
  Value *values = (Value *)lab_push(a, mul(capacity, 16), 8);
  pointer_guard(values, _Alignof(Value));
  Parser s = {.cursor = probe,
              .buffer = buffer,
              .values = values,
              .capacity = capacity,
              .limit = limit,
              .arena = a};
  bool ok = read_value(&s, 0);
  read_skip(&s.cursor);
  if (!ok || s.cursor.at != len) {
    size_t offset = s.cursor.at;
    uint64_t detail = s.cursor.error;
    if (detail == None)
      detail = Syntax;
    if (ok)
      detail = TrailingData;
    lab_rewind(a, mark);
    out->offset = offset;
    out->detail = detail;
    return;
  }
  size_t base = sub((uintptr_t)&s.values[0], (uintptr_t)&a->data[0]);
  lab_rewind(a, add(base, mul(s.used, 16)));
  out->root = &s.values[0];
  out->ok = 1;
  out->used = s.used;
  out->retained = sub(a->offset, mark);
}
