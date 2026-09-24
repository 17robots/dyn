#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>

int32_t dyn_test_variadic_sum(uint32_t count, ...) {
  va_list arguments;
  va_start(arguments, count);
  int32_t sum = 0;
  for (uint32_t i = 0; i < count; ++i)
    sum += va_arg(arguments, int);
  va_end(arguments);
  return sum;
}

double dyn_test_variadic_double(uint32_t count, ...) {
  va_list arguments;
  va_start(arguments, count);
  double sum = 0.0;
  for (uint32_t i = 0; i < count; ++i)
    sum += va_arg(arguments, double);
  va_end(arguments);
  return sum;
}

typedef struct { int64_t integer; double real; } DynTestPair;
typedef struct { DynTestPair pair; uint32_t values[3]; } DynTestNested;

void dyn_test_pair(DynTestPair *value) {
  value->integer += 2;
  value->real += 0.5;
}

int64_t dyn_test_nested(const DynTestNested *value) {
  return value->pair.integer + (int64_t)value->pair.real +
    value->values[0] + value->values[1] + value->values[2];
}

uint64_t dyn_test_pair_size(void) { return sizeof(DynTestPair); }
uint64_t dyn_test_pair_align(void) { return _Alignof(DynTestPair); }
uint64_t dyn_test_nested_size(void) { return sizeof(DynTestNested); }
uint64_t dyn_test_nested_align(void) { return _Alignof(DynTestNested); }
uint64_t dyn_test_nested_values_offset(void) {
  return offsetof(DynTestNested, values);
}

int64_t dyn_test_callback(int64_t (*callback)(int64_t, void *), void *context) {
  return callback ? callback(40, context) : -1;
}

int32_t dyn_test_nullable(const void *pointer) { return pointer == 0; }

int64_t dyn_test_foreign_global = 41;
int64_t *dyn_test_global_address(void) { return &dyn_test_foreign_global; }
