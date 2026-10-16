#ifndef DYN_NATIVE_CPU_H
#define DYN_NATIVE_CPU_H
#include <stdbool.h>
#if (defined(__x86_64__) || defined(__i386__)) &&                              \
    (defined(__GNUC__) || defined(__clang__))
#include <cpuid.h>
static inline bool dyn_native_host_bmi2(void) {
  unsigned a, b, c, d;
  return __get_cpuid_count(7, 0, &a, &b, &c, &d) && (b & (1u << 8));
}
#elif defined(_M_X64)
#include <intrin.h>
static inline bool dyn_native_host_bmi2(void) {
  int leaf[4];
  __cpuid(leaf, 0);
  if (leaf[0] < 7)
    return false;
  __cpuidex(leaf, 7, 0);
  return (leaf[1] & (1 << 8)) != 0;
}
#else
static inline bool dyn_native_host_bmi2(void) { return false; }
#endif
/* This is the complete implemented subtarget feature set, not an assertion
   that all host CPU features have optimized instruction selection. */
static inline const char *dyn_native_host_features(void) {
  return dyn_native_host_bmi2() ? "+bmi2" : "";
}
#endif
