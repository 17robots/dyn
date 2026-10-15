#include <stddef.h>
#include <stdint.h>

#ifdef _WIN32
/* MSVC-target floating-point code references this CRT marker. */
int _fltused = 0;
#endif

typedef struct DynUnwind DynUnwind;
/* Keep these context sizes in sync with codegen.c and the native assembly. */
#if defined(_WIN32)
/* XMM6-XMM15 occupy bytes 96 through 255. */
struct DynUnwind { DynUnwind *previous; uintptr_t saved[31]; };
#elif defined(__aarch64__) || defined(DYN_AARCH64)
/* d8-d15 occupy bytes 112 through 175. */
struct DynUnwind { DynUnwind *previous; uintptr_t saved[21]; };
#else
struct DynUnwind { DynUnwind *previous; uintptr_t saved[15]; };
#endif
typedef struct {
  uint64_t tid;
  DynUnwind *top;
  const unsigned char *message;
  uint64_t length;
  uint64_t unwinding;
  unsigned char message_storage[4096];
} DynUnwindSlot;
static DynUnwindSlot unwind_slots[64];
long dyn_syscall6(long, long, long, long, long, long, long);
void dyn_unwind_jump(DynUnwind *);
void dyn_panic(const unsigned char *, uint64_t);
#ifdef _WIN32
__declspec(dllimport) unsigned long __stdcall GetCurrentThreadId(void);
#elif defined(__APPLE__)
extern void *pthread_self(void);
#endif

static DynUnwindSlot *unwind_slot(int claim) {
#if defined(_WIN32)
  uint64_t tid = (uint64_t)GetCurrentThreadId();
#elif defined(__APPLE__)
  uint64_t tid = (uint64_t)(uintptr_t)pthread_self();
#elif defined(DYN_AARCH64)
  uint64_t tid = (uint64_t)dyn_syscall6(178, 0, 0, 0, 0, 0, 0);
#else
  uint64_t tid = (uint64_t)dyn_syscall6(186, 0, 0, 0, 0, 0, 0);
#endif
  for (size_t i = 0; i < 64; ++i) {
    uint64_t seen = __atomic_load_n(&unwind_slots[i].tid, __ATOMIC_ACQUIRE);
    if (seen == tid) return &unwind_slots[i];
    if (claim && !seen && __atomic_compare_exchange_n(&unwind_slots[i].tid,
        &seen, tid, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return &unwind_slots[i];
  }
  return 0;
}
void dyn_unwind_link(DynUnwind *frame) {
  DynUnwindSlot *slot = unwind_slot(1);
  if (!slot) {
    static const unsigned char message[] = "runtime unwind thread capacity exceeded";
    dyn_panic(message, sizeof(message) - 1);
    return;
  }
  frame->previous = slot->top;
  slot->top = frame;
}
void dyn_unwind_unlink(DynUnwind *frame) {
  DynUnwindSlot *slot = unwind_slot(0);
  if (slot && slot->top == frame) {
    slot->top = frame->previous;
    if (!slot->top && !slot->unwinding)
      __atomic_store_n(&slot->tid, 0, __ATOMIC_RELEASE);
  }
}
void dyn_unwind_begin(const unsigned char *message, uint64_t length) {
  DynUnwindSlot *slot = unwind_slot(1);
  if (!slot || slot->unwinding || !slot->top) return;
  slot->unwinding = 1;
  /* Cleanup can release the message's arena or overwrite its stack frame.
     Own a bounded copy before jumping; panic handling must not allocate. */
  static const unsigned char truncated[] = " [truncated]";
  uint64_t copied = length;
  if (!message) copied = length = 0;
  if (copied > sizeof(slot->message_storage)) {
    copied = sizeof(slot->message_storage) - (sizeof(truncated) - 1);
    /* A valid UTF-8 diagnostic must not end with half a codepoint. */
    while (copied && (message[copied] & 0xc0) == 0x80) --copied;
  }
  for (uint64_t i = 0; i < copied; ++i)
    slot->message_storage[i] = message[i];
  if (copied < length) {
    for (size_t i = 0; i < sizeof(truncated) - 1; ++i)
      slot->message_storage[copied + i] = truncated[i];
    length = copied + sizeof(truncated) - 1;
  }
  slot->message = slot->message_storage;
  slot->length = length;
  DynUnwind *frame = slot->top;
  slot->top = frame->previous;
  dyn_unwind_jump(frame);
}
void dyn_unwind_continue(void) {
  DynUnwindSlot *slot = unwind_slot(0);
  if (slot && slot->top) {
    DynUnwind *frame = slot->top;
    slot->top = frame->previous;
    dyn_unwind_jump(frame);
  }
  if (slot) dyn_panic(slot->message, slot->length);
  dyn_panic(0, 0);
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
enum { TRACE_SLOTS = 64, TRACE_FRAMES = 64 };
typedef struct { const unsigned char *name; uint64_t length; } DynFrame;
typedef struct { uint64_t tid, count; DynFrame frames[TRACE_FRAMES]; } DynSlot;
static DynSlot trace_slots[TRACE_SLOTS];
static uint64_t trace_tid(void) {
#if defined(_WIN32)
  return (uint64_t)GetCurrentThreadId();
#elif defined(__APPLE__)
  return (uint64_t)(uintptr_t)pthread_self();
#else
  return (uint64_t)dyn_syscall6(178,0,0,0,0,0,0);
#endif
}
static void trace_write(const unsigned char *data, uint64_t length) {
#if defined(_WIN32)
  __declspec(dllimport) void *__stdcall GetStdHandle(unsigned long);
  __declspec(dllimport) int __stdcall WriteFile(void *, const void *, unsigned long, unsigned long *, void *);
  void *handle = GetStdHandle((unsigned long)-12);
  while (length) {
    unsigned long written = 0;
    unsigned long chunk = length > 0x7fffffff ? 0x7fffffff : (unsigned long)length;
    if (!WriteFile(handle, data, chunk, &written, 0) || !written) return;
    data += written; length -= written;
  }
#else
  while (length) {
#if defined(__APPLE__)
    long written = dyn_syscall6(4,2,(long)data,(long)length,0,0,0);
#else
    long written = dyn_syscall6(64,2,(long)data,(long)length,0,0,0);
#endif
    if (written <= 0) return;
    data += written; length -= (uint64_t)written;
  }
#endif
}
static DynSlot *trace_slot(uint64_t id, int claim) {
  for (size_t i = 0; i < TRACE_SLOTS; ++i) {
    uint64_t seen = __atomic_load_n(&trace_slots[i].tid, __ATOMIC_ACQUIRE);
    if (seen == id) return &trace_slots[i];
    if (claim && !seen && __atomic_compare_exchange_n(&trace_slots[i].tid,
        &seen, id, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return &trace_slots[i];
  }
  return 0;
}
void dyn_trace_push(const unsigned char *name, uint64_t length) {
  DynSlot *s = trace_slot(trace_tid(), 1);
  if (s) {
    if (s->count < TRACE_FRAMES) s->frames[s->count] = (DynFrame){name,length};
    ++s->count;
  }
}
void dyn_trace_pop(void) {
  DynSlot *s = trace_slot(trace_tid(), 0);
  if (s && s->count && !--s->count) __atomic_store_n(&s->tid,0,__ATOMIC_RELEASE);
}
void dyn_trace_dump(void) {
  static const unsigned char h[]="stack trace:\n", a[]="  at ", n[]="\n";
  DynSlot *s = trace_slot(trace_tid(), 0);
  if (!s || !s->count) return;
  trace_write(h,sizeof(h)-1);
  for (uint64_t i=s->count < TRACE_FRAMES ? s->count : TRACE_FRAMES;i;--i) {
    DynFrame *f=&s->frames[i-1];
    trace_write(a,sizeof(a)-1);
    trace_write(f->name,f->length);
    trace_write(n,1);
  }
}
#endif
