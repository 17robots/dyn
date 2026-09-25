#include <stdint.h>
#include <stddef.h>
struct Probe { uint8_t tag; double value; uint32_t samples[3]; };
double dyn_probe_mix(int8_t a, int16_t b, int32_t c, int64_t d, float e, double f) {
  return a+b+c+d+e+f;
}
int dyn_probe_storage(const struct Probe *p, size_t size, size_t alignment) {
  return size==sizeof(*p) && alignment==_Alignof(struct Probe) && p->tag==9 &&
      p->value==2.5 && p->samples[0]==11 && p->samples[2]==33;
}
double dyn_probe_callback(double (*fn)(double, void *), void *context) {
  return fn(4.5, context);
}
