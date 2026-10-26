#define _GNU_SOURCE
#include "twin.h"
#include <emmintrin.h>
#include <locale.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifndef LAB_TRACE
#define LAB_TRACE 1
#endif
static uint64_t mode;
static locale_t locale_c;
static uint64_t calls[7], sizes[7];
static uint64_t event_data[65536][4];
static size_t event_count;
static int recording;
static uint64_t mix(uint64_t h, uint64_t v) {
  return (h ^ v) * UINT64_C(1099511628211);
}
static void event(Arena *a, uint64_t type, uint64_t size, uint64_t alignment,
                  uint64_t offset) {
  if (!LAB_TRACE)
    return;
  a->trace = mix(mix(mix(mix(a->trace, type), size), alignment), offset);
  if (recording) {
    if (event_count >= 65536)
      abort();
    event_data[event_count][0] = type;
    event_data[event_count][1] = size;
    event_data[event_count][2] = alignment;
    event_data[event_count++][3] = offset;
  }
}
void lab_set_mode(uint64_t v) {
  mode = v;
  if (!locale_c)
    locale_c = newlocale(LC_NUMERIC_MASK, "C", (locale_t)0);
  if (!locale_c)
    abort();
}
void lab_reset_stats(int record) {
  memset(calls, 0, sizeof calls);
  memset(sizes, 0, sizeof sizes);
  event_count = 0;
  recording = record;
}
void lab_get_stats(uint64_t *out) {
  memcpy(out, calls, sizeof calls);
  memcpy(out + 7, sizes, sizeof sizes);
}
size_t lab_get_events(uint64_t **out) {
  *out = &event_data[0][0];
  return event_count;
}
__attribute__((noinline)) uint8_t *lab_push(Arena *a, size_t n,
                                            size_t alignment) {
  if (LAB_TRACE) {
    calls[0]++;
    sizes[0] += n;
  }
  uintptr_t address = (uintptr_t)a->data + a->offset;
  size_t padding = (0 - address) & (alignment - 1);
  if (padding > a->capacity - a->offset ||
      n > a->capacity - a->offset - padding)
    abort();
  size_t at = a->offset + padding;
  a->offset = at + n;
  if (a->offset > a->peak)
    a->peak = a->offset;
  if (LAB_TRACE) {
    a->allocations++;
    a->bytes += n;
  }
  event(a, 1, n, alignment, at);
  return a->data + at;
}
__attribute__((noinline)) void lab_rewind(Arena *a, size_t n) {
  if (LAB_TRACE)
    calls[1]++;
  if (n > a->offset)
    abort();
  event(a, 2, 0, 0, n);
  a->offset = n;
}
__attribute__((noinline)) void lab_copy(uint8_t *d, const uint8_t *s,
                                        size_t n) {
  if (LAB_TRACE) {
    calls[2]++;
    sizes[2] += n;
  }
  memcpy(d, s, n);
}
__attribute__((noinline)) uint64_t lab_utf8(const uint8_t *s, size_t n) {
  if (LAB_TRACE) {
    calls[3]++;
    sizes[3] += n;
  }
  size_t at = 0;
  while (at < n) {
    unsigned first = s[at];
    if (first < 128) {
      at++;
      continue;
    }
    unsigned width = 0, value = 0, minimum = 0;
    if (first >= 194 && first <= 223) {
      width = 2;
      value = first & 31;
      minimum = 128;
    } else if (first >= 224 && first <= 239) {
      width = 3;
      value = first & 15;
      minimum = 2048;
    } else if (first >= 240 && first <= 244) {
      width = 4;
      value = first & 7;
      minimum = 65536;
    } else
      return 0;
    if (width > n - at)
      return 0;
    for (unsigned i = 1; i < width; i++) {
      unsigned b = s[at + i];
      if (b < 128 || b > 191)
        return 0;
      value = (value << 6) | (b & 63);
    }
    if (value < minimum || value > 1114111 ||
        (value >= 55296 && value <= 57343))
      return 0;
    at += width;
  }
  return 1;
}
__attribute__((noinline)) double lab_decimal(const uint8_t *s, size_t n) {
  if (LAB_TRACE) {
    calls[4]++;
    sizes[4] += n;
  }
  char local[512];
  char *text = n < sizeof local ? local : malloc(n + 1);
  if (!text)
    abort();
  memcpy(text, s, n);
  text[n] = 0;
  char *end;
  double v = strtod_l(text, &end, locale_c);
  if (end != text + n)
    abort();
  if (text != local)
    free(text);
  return v;
}
static size_t ascii_scalar(const uint8_t *s, size_t n) {
  for (size_t i = 0; i < n; i++)
    if (s[i] < 32 || s[i] >= 128 || s[i] == 34 || s[i] == 92)
      return i;
  return n;
}
__attribute__((noinline)) size_t lab_ascii(const uint8_t *s, size_t n) {
  if (LAB_TRACE) {
    calls[5]++;
    sizes[5] += n;
  }
  if (!(mode & 1))
    return ascii_scalar(s, n);
  size_t at = 0;
  const __m128i low = _mm_set1_epi8(32), quote = _mm_set1_epi8(34),
                slash = _mm_set1_epi8(92);
  for (; n - at >= 16; at += 16) {
    __m128i v = _mm_loadu_si128((const __m128i *)(s + at));
    __m128i m = _mm_or_si128(
        _mm_cmpgt_epi8(low, v),
        _mm_or_si128(_mm_cmpeq_epi8(v, quote), _mm_cmpeq_epi8(v, slash)));
    unsigned bits = (unsigned)_mm_movemask_epi8(m);
    if (bits)
      return at + (unsigned)__builtin_ctz(bits);
  }
  return at + ascii_scalar(s + at, n - at);
}
