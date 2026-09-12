#include <stddef.h>
#include <stdint.h>

typedef struct DynUnwind DynUnwind;
struct DynUnwind { DynUnwind *previous; uintptr_t saved[15]; };
typedef struct {
  uint64_t tid;
  DynUnwind *top;
  const unsigned char *message;
  uint64_t length;
  uint64_t unwinding;
} DynUnwindSlot;
static DynUnwindSlot unwind_slots[64];
long dyn_syscall6(long, long, long, long, long, long, long);
void dyn_unwind_jump(DynUnwind *);
void dyn_panic(const unsigned char *, uint64_t);

static DynUnwindSlot *unwind_slot(int claim) {
#if defined(DYN_SINGLE_THREAD)
  uint64_t tid = 1;
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
  if (!slot) return;
  frame->previous = slot->top;
  slot->top = frame;
}
void dyn_unwind_unlink(DynUnwind *frame) {
  DynUnwindSlot *slot = unwind_slot(0);
  if (slot && slot->top == frame) {
    slot->top = frame->previous;
    if (!slot->top) __atomic_store_n(&slot->tid, 0, __ATOMIC_RELEASE);
  }
}
void dyn_unwind_begin(const unsigned char *message, uint64_t length) {
  DynUnwindSlot *slot = unwind_slot(1);
  if (!slot || slot->unwinding || !slot->top) return;
  slot->unwinding = 1;
  slot->message = message;
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

void *memset(void *destination, int value, size_t count) {
  unsigned char *bytes = destination;
  for (size_t i = 0; i < count; ++i)
    bytes[i] = (unsigned char)value;
  return destination;
}

void *memcpy(void *destination, const void *source, size_t count) {
  unsigned char *to = destination;
  const unsigned char *from = source;
  for (size_t i = 0; i < count; ++i) to[i] = from[i];
  return destination;
}

void *memmove(void *destination, const void *source, size_t count) {
  unsigned char *to = destination;
  const unsigned char *from = source;
  uintptr_t to_address = (uintptr_t)to, from_address = (uintptr_t)from;
  if (to_address > from_address && to_address - from_address < count) {
    for (size_t i = count; i; --i) to[i - 1] = from[i - 1];
  } else {
    for (size_t i = 0; i < count; ++i) to[i] = from[i];
  }
  return destination;
}

#if defined(DYN_AARCH64) && !defined(DYN_RELEASE)
long dyn_syscall6(long, long, long, long, long, long, long);
enum { TRACE_SLOTS = 64, TRACE_FRAMES = 64 };
typedef struct { const unsigned char *name; uint64_t length; } DynFrame;
typedef struct { uint64_t tid, count; DynFrame frames[TRACE_FRAMES]; } DynSlot;
static DynSlot trace_slots[TRACE_SLOTS];
static uint64_t trace_tid(void) { return (uint64_t)dyn_syscall6(178,0,0,0,0,0,0); }
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
  if (s && s->count != TRACE_FRAMES) s->frames[s->count++] = (DynFrame){name,length};
}
void dyn_trace_pop(void) {
  DynSlot *s = trace_slot(trace_tid(), 0);
  if (s && s->count && !--s->count) __atomic_store_n(&s->tid,0,__ATOMIC_RELEASE);
}
void dyn_trace_dump(void) {
  static const unsigned char h[]="stack trace:\n", a[]="  at ", n[]="\n";
  DynSlot *s = trace_slot(trace_tid(), 0);
  dyn_syscall6(64,2,(long)h,sizeof(h)-1,0,0,0);
  if (!s) return;
  for (uint64_t i=s->count;i;--i) {
    DynFrame *f=&s->frames[i-1];
    dyn_syscall6(64,2,(long)a,sizeof(a)-1,0,0,0);
    dyn_syscall6(64,2,(long)f->name,f->length,0,0,0);
    dyn_syscall6(64,2,(long)n,1,0,0,0);
  }
}
#endif
