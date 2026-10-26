#ifndef DYN_NATIVE_CPU_H
#define DYN_NATIVE_CPU_H
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

/* Match complete comma-separated tokens, including the leading + or -. */
static inline bool dyn_cpu_has_feature(const char *features, const char *token) {
  size_t length = strlen(token);
  if (!features || !length) return false;
  while (*features) {
    const char *end = strchr(features, ',');
    size_t n = end ? (size_t)(end - features) : strlen(features);
    if (n == length && !memcmp(features, token, n)) return true;
    if (!end) break;
    features = end + 1;
  }
  return false;
}

/* Pure predicates also allow synthetic CPU/OS combinations to be checked. */
static inline bool dyn_native_fma_cpu(unsigned leaf1_ecx) {
  const unsigned required = (1u << 12) | (1u << 26) | (1u << 27) | (1u << 28);
  return (leaf1_ecx & required) == required;
}
static inline bool dyn_native_fma_usable(unsigned leaf1_ecx, uint64_t xcr0) {
  return dyn_native_fma_cpu(leaf1_ecx) && (xcr0 & 6) == 6;
}
static inline const char *dyn_native_features_from_bits(unsigned leaf1_ecx,
                                                       unsigned leaf7_ebx, uint64_t xcr0) {
  unsigned index = ((leaf7_ebx >> 8) & 1) |
                   (((leaf1_ecx >> 19) & 1) << 1) |
                   (dyn_native_fma_usable(leaf1_ecx, xcr0) ? 4u : 0u);
  static const char *const features[] = {
    "", "+bmi2", "+sse4.1", "+bmi2,+sse4.1", "+fma", "+bmi2,+fma",
    "+sse4.1,+fma", "+bmi2,+sse4.1,+fma"
  };
  return features[index];
}
#if (defined(__x86_64__) || defined(__i386__)) && \
    (defined(__GNUC__) || defined(__clang__))
#include <cpuid.h>
static inline const char *dyn_native_host_features(void) {
  unsigned a, b, c, d, leaf1 = 0, leaf7 = 0;
  uint64_t xcr0 = 0;
  if (__get_cpuid(1, &a, &b, &c, &d)) leaf1 = c;
  if (__get_cpuid_count(7, 0, &a, &b, &c, &d)) leaf7 = b;
  /* In particular, never execute XGETBV without CPUID.OSXSAVE. */
  if (dyn_native_fma_cpu(leaf1)) {
    unsigned lo, hi;
    __asm__ volatile ("xgetbv" : "=a" (lo), "=d" (hi) : "c" (0));
    xcr0 = ((uint64_t)hi << 32) | lo;
  }
  return dyn_native_features_from_bits(leaf1, leaf7, xcr0);
}
#elif defined(_M_X64) || defined(_M_IX86)
#include <intrin.h>
static inline const char *dyn_native_host_features(void) {
  int leaf[4];
  unsigned leaf1 = 0, leaf7 = 0;
  uint64_t xcr0 = 0;
  __cpuid(leaf, 0);
  int maximum = leaf[0];
  if (maximum >= 1) { __cpuid(leaf, 1); leaf1 = (unsigned)leaf[2]; }
  if (maximum >= 7) { __cpuidex(leaf, 7, 0); leaf7 = (unsigned)leaf[1]; }
  if (dyn_native_fma_cpu(leaf1)) xcr0 = _xgetbv(0);
  return dyn_native_features_from_bits(leaf1, leaf7, xcr0);
}
#else
static inline const char *dyn_native_host_features(void) { return ""; }
#endif
static inline bool dyn_native_host_bmi2(void) {
  return dyn_cpu_has_feature(dyn_native_host_features(), "+bmi2");
}
#endif
