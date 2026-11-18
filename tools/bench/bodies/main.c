#include <stdio.h>
#include <stdint.h>
typedef struct { double x, y, z, vx, vy, vz, mass, charge; } Body;
static Body bodies[1024];
static double energy(Body b, double scale) {
  return 0.5 * b.mass * (b.vx * b.vx + b.vy * b.vy + b.vz * b.vz) * scale + b.charge * (b.x + b.y + b.z);
}
int main(void) {
  for (size_t i = 0; i < 1024; ++i) {
    double v = (double)(i % 13);
    bodies[i] = (Body){v, v * 2, v * 3, v * 0.5, v * 0.25, v * 0.125, 1 + v, 0.5};
  }
  double total = 0;
  for (int round = 0; round < 20000; ++round)
    for (size_t i = 0; i < 1024; ++i) total += energy(bodies[i], 1.0 + (double)(round % 3));
  printf("%llu\n", (unsigned long long)total);
}
