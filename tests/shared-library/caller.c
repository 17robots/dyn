#include <stdint.h>

extern int64_t dyn_test_add(int64_t left, int64_t right);

int main(void) { return dyn_test_add(20, 22) == 42 ? 0 : 1; }
