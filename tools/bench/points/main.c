#include <stdio.h>
#include <stdint.h>
typedef struct { int64_t x, y; } Point;
static Point points[4096];
static Point step(Point p, Point d) { return (Point){(p.x + d.x) % 1000003, (p.y * 3 + d.y) % 1000003}; }
int main(void) {
  for (size_t i = 0; i < 4096; ++i) points[i] = (Point){(int64_t)i, (int64_t)(i * 7)};
  Point delta = {5, 11};
  for (int round = 0; round < 2000; ++round)
    for (size_t i = 0; i < 4096; ++i) points[i] = step(points[i], delta);
  int64_t total = 0;
  for (size_t i = 0; i < 4096; ++i) total += points[i].x + points[i].y;
  printf("%lld\n", (long long)total);
}
