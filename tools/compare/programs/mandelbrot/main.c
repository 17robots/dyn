#include <stdio.h>

#define SIZE 3000
#define ITERATIONS 50

int main(void) {
  long inside = 0;
  for (int py = 0; py < SIZE; py++) {
    double y0 = (double)py / SIZE * 2.0 - 1.0;
    for (int px = 0; px < SIZE; px++) {
      double x0 = (double)px / SIZE * 3.0 - 2.0;
      double x = 0.0, y = 0.0;
      int n = 0;
      while (n < ITERATIONS && x * x + y * y <= 4.0) {
        double next = x * x - y * y + x0;
        y = 2.0 * x * y + y0;
        x = next;
        n++;
      }
      if (n == ITERATIONS) inside++;
    }
  }
  printf("%ld\n", inside);
  return 0;
}
