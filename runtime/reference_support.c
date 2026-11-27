#include <stddef.h>
#include <stdint.h>

#ifdef _WIN32
/* MSVC-target floating-point code references this CRT marker. */
int _fltused = 0;
#endif

long dyn_syscall6(long, long, long, long, long, long, long);
void dyn_panic(const unsigned char *, uint64_t);
static void (*dyn_panic_hook)(const unsigned char *, uint64_t);
void dyn_set_panic_hook(void (*hook)(const unsigned char *, uint64_t)) { dyn_panic_hook = hook; }
static void run_panic_hook(const unsigned char *message, uint64_t length) {
  void (*hook)(const unsigned char *, uint64_t) = dyn_panic_hook;
  dyn_panic_hook = 0;
  if (hook) hook(message, length);
}
static uint64_t dyn_lifetime_checks_flag = 0;
void dyn_set_lifetime_checks(uint64_t enabled) { dyn_lifetime_checks_flag = enabled; }
uint8_t dyn_lifetime_checks_enabled(void) { return dyn_lifetime_checks_flag != 0; }
void dyn_race_sync(void) {}
void dyn_race_read(uint64_t address, uint64_t size) { (void)address; (void)size; }
void dyn_race_write(uint64_t address, uint64_t size) { (void)address; (void)size; }

void dyn_unwind_begin(const unsigned char *message, uint64_t length) {
  /* A panic does not run defers: the handler runs, then dyn_panic reports. */
  run_panic_hook(message, length);
}

/* Failed runtime checks pass the function name and kind << 24 | name length.
   No local arrays, so no stack protector is needed; a check failure never
   returns, so the static message buffer is never reused. */
static uint64_t check_append(unsigned char *out, uint64_t at, const char *text) {
  while (*text) out[at++] = (unsigned char)*text++;
  return at;
}
static uint64_t check_number(unsigned char *out, uint64_t at, uint64_t value) {
  if (value >> 63) { out[at++] = '-'; value = 0 - value; }
  static unsigned char digits[20]; unsigned count = 0; /* no stack array: no stack protector */
  do { digits[count++] = (unsigned char)('0' + value % 10); value /= 10; } while (value);
  while (count) out[at++] = digits[--count];
  return at;
}
/* Debug builds set bit 23 for an index check and pass the index and limit. */
void dyn_check_failed(const unsigned char *name, uint64_t packed, uint64_t index, uint64_t limit) {
  static const char *const kinds[] = {"overflow.ok", "divide.ok", "division.overflow.ok", "shift.count.ok",
    "function.nonnull.ok", "pointer.nonnull.ok", "pointer.aligned.ok", "index.ok", "slice.order.ok",
    "slice.bounds.ok", "enum.cast.ok", "enum.tag.ok"};
  static unsigned char message[1024];
  uint64_t kind = packed >> 24, length = packed & 0x7fffff;
  uint64_t used = check_append(message, 0, "runtime check failed (");
  used = check_append(message, used, kind < 12 ? kinds[kind] : "unknown");
  used = check_append(message, used, ") in ");
  for (uint64_t i = 0; i < length && i < 800; ++i) message[used++] = name[i];
  if (packed & 0x800000) {
    used = check_append(message, used, ": index ");
    used = check_number(message, used, index);
    used = check_append(message, used, ", length ");
    used = check_number(message, used, limit);
  }
  dyn_panic(message, used);
}

/* Freestanding programs get memset, memcpy and memmove from here.
 *
 * They are hidden: a Dyn executable that also links a C library and shared
 * libraries (SDL, FreeType, GPU drivers) must not export its own copies over
 * the C library's to every one of them. Inside the program they move eight
 * bytes at a time, and on x86-64 large blocks use the string instructions,
 * which current processors run at memory speed.
 *
 * The loops must never be compiled back into calls to these functions:
 * -fno-builtin covers Clang; GCC also needs loop-pattern distribution off. */
#if (defined(__GNUC__) || defined(__clang__)) && !defined(_WIN32)
#define DYN_RUNTIME_HIDDEN __attribute__((visibility("hidden")))
#else
#define DYN_RUNTIME_HIDDEN
#endif
#if defined(__GNUC__) && !defined(__clang__)
#define DYN_NO_LOOP_CALLS __attribute__((optimize("no-tree-loop-distribute-patterns")))
#else
#define DYN_NO_LOOP_CALLS
#endif
/* An unaligned, freely aliasing 64-bit word. */
typedef uint64_t __attribute__((may_alias, aligned(1))) DynWord;
enum { DYN_STRING_THRESHOLD = 512 };

static inline __attribute__((always_inline)) void copy_forward(unsigned char *to, const unsigned char *from, size_t count) {
#if defined(__x86_64__)
  if (count >= DYN_STRING_THRESHOLD) {
    /* Copies upward one byte at a time in effect, so it is also correct
       for an overlapping move to a lower address. */
    __asm__ volatile("rep movsb" : "+D"(to), "+S"(from), "+c"(count) : : "memory");
    return;
  }
#endif
  /* Load a block before storing it: correct when the destination overlaps
     the source from below, as memmove needs. */
  for (; count >= 32; count -= 32, to += 32, from += 32) {
    uint64_t a = *(const DynWord *)from, b = *(const DynWord *)(from + 8);
    uint64_t c = *(const DynWord *)(from + 16), d = *(const DynWord *)(from + 24);
    *(DynWord *)to = a;
    *(DynWord *)(to + 8) = b;
    *(DynWord *)(to + 16) = c;
    *(DynWord *)(to + 24) = d;
  }
  for (; count >= 8; count -= 8, to += 8, from += 8)
    *(DynWord *)to = *(const DynWord *)from;
  for (; count; --count) *to++ = *from++;
}

static inline __attribute__((always_inline)) void copy_backward(unsigned char *to, const unsigned char *from, size_t count) {
  to += count;
  from += count;
  for (; count >= 32; count -= 32) {
    to -= 32;
    from -= 32;
    uint64_t a = *(const DynWord *)from, b = *(const DynWord *)(from + 8);
    uint64_t c = *(const DynWord *)(from + 16), d = *(const DynWord *)(from + 24);
    *(DynWord *)(to + 24) = d;
    *(DynWord *)(to + 16) = c;
    *(DynWord *)(to + 8) = b;
    *(DynWord *)to = a;
  }
  for (; count >= 8; count -= 8) {
    to -= 8;
    from -= 8;
    *(DynWord *)to = *(const DynWord *)from;
  }
  for (; count; --count) *--to = *--from;
}

DYN_RUNTIME_HIDDEN DYN_NO_LOOP_CALLS
void *memset(void *destination, int value, size_t count) {
  unsigned char *bytes = destination;
#if defined(__x86_64__)
  if (count >= DYN_STRING_THRESHOLD) {
    __asm__ volatile("rep stosb" : "+D"(bytes), "+c"(count) : "a"(value) : "memory");
    return destination;
  }
#endif
  uint64_t pattern = (uint64_t)(unsigned char)value * 0x0101010101010101ull;
  for (; count >= 32; count -= 32, bytes += 32) {
    *(DynWord *)bytes = pattern;
    *(DynWord *)(bytes + 8) = pattern;
    *(DynWord *)(bytes + 16) = pattern;
    *(DynWord *)(bytes + 24) = pattern;
  }
  for (; count >= 8; count -= 8, bytes += 8) *(DynWord *)bytes = pattern;
  for (; count; --count) *bytes++ = (unsigned char)value;
  return destination;
}

#ifdef __APPLE__
/* LLVM lowers zero fills to bzero on Darwin even in freestanding programs. */
DYN_RUNTIME_HIDDEN void bzero(void *destination, size_t count) {
  (void)memset(destination, 0, count);
}
#endif

DYN_RUNTIME_HIDDEN DYN_NO_LOOP_CALLS
void *memcpy(void *destination, const void *source, size_t count) {
  copy_forward(destination, source, count);
  return destination;
}

DYN_RUNTIME_HIDDEN DYN_NO_LOOP_CALLS
void *memmove(void *destination, const void *source, size_t count) {
  uintptr_t to = (uintptr_t)destination, from = (uintptr_t)source;
  if (to > from && to - from < count)
    copy_backward(destination, source, count);
  else
    copy_forward(destination, source, count);
  return destination;
}

/* Float remainder lowers to fmod/fmodf calls in both backends. These are exact
 * (fmod has no rounding), so programs without libm still link, and a C
 * library's copy gives identical results. Algorithm after musl's fmod. */
static uint64_t dyn_f64_bits(double x) { union { double f; uint64_t i; } u = {x}; return u.i; }
static double dyn_f64_value(uint64_t i) { union { uint64_t i; double f; } u = {i}; return u.f; }
static uint32_t dyn_f32_bits(float x) { union { float f; uint32_t i; } u = {x}; return u.i; }
static float dyn_f32_value(uint32_t i) { union { uint32_t i; float f; } u = {i}; return u.f; }

DYN_RUNTIME_HIDDEN double fmod(double x, double y) {
  uint64_t ux = dyn_f64_bits(x), uy = dyn_f64_bits(y), i;
  int ex = (int)(ux >> 52 & 0x7ff), ey = (int)(uy >> 52 & 0x7ff);
  uint64_t sx = ux >> 63;
  if (uy << 1 == 0 || (uy << 1) > 0xffeull << 52 || ex == 0x7ff) return (x * y) / (x * y);
  if (ux << 1 <= uy << 1) return ux << 1 == uy << 1 ? 0 * x : x;
  if (!ex) {
    for (i = ux << 12; i >> 63 == 0; ex--, i <<= 1) {}
    ux <<= -ex + 1;
  } else {
    ux &= -1ull >> 12;
    ux |= 1ull << 52;
  }
  if (!ey) {
    for (i = uy << 12; i >> 63 == 0; ey--, i <<= 1) {}
    uy <<= -ey + 1;
  } else {
    uy &= -1ull >> 12;
    uy |= 1ull << 52;
  }
  for (; ex > ey; ex--) {
    i = ux - uy;
    if (i >> 63 == 0) {
      if (i == 0) return 0 * x;
      ux = i;
    }
    ux <<= 1;
  }
  i = ux - uy;
  if (i >> 63 == 0) {
    if (i == 0) return 0 * x;
    ux = i;
  }
  for (; ux >> 52 == 0; ux <<= 1, ex--) {}
  if (ex > 0) {
    ux -= 1ull << 52;
    ux |= (uint64_t)ex << 52;
  } else {
    ux >>= -ex + 1;
  }
  return dyn_f64_value(ux | sx << 63);
}

DYN_RUNTIME_HIDDEN float fmodf(float x, float y) {
  uint32_t ux = dyn_f32_bits(x), uy = dyn_f32_bits(y), i;
  int ex = (int)(ux >> 23 & 0xff), ey = (int)(uy >> 23 & 0xff);
  uint32_t sx = ux & 0x80000000u;
  if (uy << 1 == 0 || (uy << 1) > 0xff000000u || ex == 0xff) return (x * y) / (x * y);
  if (ux << 1 <= uy << 1) return ux << 1 == uy << 1 ? 0 * x : x;
  if (!ex) {
    for (i = ux << 9; i >> 31 == 0; ex--, i <<= 1) {}
    ux <<= -ex + 1;
  } else {
    ux &= -1u >> 9;
    ux |= 1u << 23;
  }
  if (!ey) {
    for (i = uy << 9; i >> 31 == 0; ey--, i <<= 1) {}
    uy <<= -ey + 1;
  } else {
    uy &= -1u >> 9;
    uy |= 1u << 23;
  }
  for (; ex > ey; ex--) {
    i = ux - uy;
    if (i >> 31 == 0) {
      if (i == 0) return 0 * x;
      ux = i;
    }
    ux <<= 1;
  }
  i = ux - uy;
  if (i >> 31 == 0) {
    if (i == 0) return 0 * x;
    ux = i;
  }
  for (; ux >> 23 == 0; ux <<= 1, ex--) {}
  if (ex > 0) {
    ux -= 1u << 23;
    ux |= (uint32_t)ex << 23;
  } else {
    ux >>= -ex + 1;
  }
  return dyn_f32_value(ux | sx);
}

#if defined(_WIN32) || defined(__APPLE__) || (defined(DYN_AARCH64) && !defined(DYN_RELEASE))
long dyn_syscall6(long, long, long, long, long, long, long);
/* Debug programs hand dyn_trace_start the header of their stack trace table
   (runtime/support/trace.dyn walks it). This reference runtime keeps the
   entry points and prints no trace. */
static uintptr_t trace_header;
void dyn_trace_start(uintptr_t header) { trace_header = header; }
void dyn_trace_capture(uintptr_t pc, uintptr_t fp) { (void)pc; (void)fp; }
void dyn_trace_dump(void) {}
#endif
