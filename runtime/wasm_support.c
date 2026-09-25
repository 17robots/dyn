/* Freestanding browser support. Traps terminate the invocation; no unwinding. */
typedef __SIZE_TYPE__ size_t;
void *memset(void *destination, int value, size_t count) {
  unsigned char *out = destination;
  for (size_t i = 0; i < count; ++i) out[i] = (unsigned char)value;
  return destination;
}
void *memcpy(void *destination, const void *source, size_t count) {
  unsigned char *out = destination;
  const unsigned char *in = source;
  for (size_t i = 0; i < count; ++i) out[i] = in[i];
  return destination;
}
void *memmove(void *destination, const void *source, size_t count) {
  unsigned char *out = destination;
  const unsigned char *in = source;
  if ((__UINTPTR_TYPE__)out < (__UINTPTR_TYPE__)in) return memcpy(destination, source, count);
  while (count) { --count; out[count] = in[count]; }
  return destination;
}
__attribute__((noreturn)) void dyn_panic(const char *message, size_t count) {
  (void)message; (void)count;
  __builtin_trap();
}

// Raw mechanism only. Arena allocation/reuse policy is implemented in std/mem.
size_t dyn_wasm_grow_pages(size_t pages) {
  return __builtin_wasm_memory_grow(0, pages);
}

// LLVM expands checked 64-bit multiplication through this 128-bit libcall.
// Only 32x32 -> 64 multiplies are used for the low-half product.
typedef unsigned long long u64;
typedef unsigned __int128 u128;
u128 __multi3(u128 left, u128 right) {
  union Wide { u128 value; struct { u64 low, high; } words; } a = {left}, b = {right}, out;
  const u64 mask = 0xffffffffULL;
  u64 p0 = (a.words.low & mask) * (b.words.low & mask);
  u64 p1 = (a.words.low & mask) * (b.words.low >> 32);
  u64 p2 = (a.words.low >> 32) * (b.words.low & mask);
  u64 carry = (p0 >> 32) + (p1 & mask) + (p2 & mask);
  out.words.low = (p0 & mask) | (carry << 32);
  out.words.high = (a.words.low >> 32) * (b.words.low >> 32) +
    (p1 >> 32) + (p2 >> 32) + (carry >> 32) +
    a.words.high * b.words.low + a.words.low * b.words.high;
  return out.value;
}
