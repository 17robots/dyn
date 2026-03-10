#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

extern __float128 strtoflt128(const char *nptr, char **endptr);

static __float128 dynrt_f128_load(uintptr_t value_ptr) {
    if (value_ptr == 0) {
        return 0.0Q;
    }
    return *((const __float128 *)(uintptr_t)value_ptr);
}

static uintptr_t dynrt_f128_box(__float128 value) {
    __float128 *out = (__float128 *)malloc(sizeof(__float128));
    if (out == NULL) {
        return 0;
    }
    *out = value;
    return (uintptr_t)out;
}

uintptr_t dynrt_f128_zero(void) {
    return dynrt_f128_box(0.0Q);
}

uintptr_t dynrt_f128_from_literal(const uint8_t *text_ptr, uintptr_t len) {
    if (text_ptr == NULL && len != 0) {
        return 0;
    }

    size_t size = (size_t)len + 1u;
    char *buffer = (char *)malloc(size);
    if (buffer == NULL) {
        return 0;
    }
    if (len != 0) {
        memcpy(buffer, text_ptr, (size_t)len);
    }
    buffer[len] = '\0';

    char *end_ptr = NULL;
    __float128 value = strtoflt128(buffer, &end_ptr);
    if (end_ptr == buffer) {
        value = 0.0Q;
    }
    free(buffer);
    return dynrt_f128_box(value);
}

uintptr_t dynrt_f128_from_f64(double value) {
    return dynrt_f128_box((__float128)value);
}

uintptr_t dynrt_f128_from_i64(int64_t value) {
    return dynrt_f128_box((__float128)value);
}

uintptr_t dynrt_f128_from_u64(uint64_t value) {
    return dynrt_f128_box((__float128)value);
}

double dynrt_f128_to_f64(uintptr_t value_ptr) {
    return (double)dynrt_f128_load(value_ptr);
}

int64_t dynrt_f128_to_i64(uintptr_t value_ptr) {
    __float128 value = dynrt_f128_load(value_ptr);
    if (value != value) {
        return 0;
    }
    if (value >= (__float128)INT64_MAX) {
        return INT64_MAX;
    }
    if (value <= (__float128)INT64_MIN) {
        return INT64_MIN;
    }
    return (int64_t)value;
}

uint64_t dynrt_f128_to_u64(uintptr_t value_ptr) {
    __float128 value = dynrt_f128_load(value_ptr);
    if (value != value || value <= 0.0Q) {
        return 0;
    }
    if (value >= (__float128)UINT64_MAX) {
        return UINT64_MAX;
    }
    return (uint64_t)value;
}

uintptr_t dynrt_f128_neg(uintptr_t value_ptr) {
    return dynrt_f128_box(-dynrt_f128_load(value_ptr));
}

uintptr_t dynrt_f128_add(uintptr_t lhs_ptr, uintptr_t rhs_ptr) {
    return dynrt_f128_box(dynrt_f128_load(lhs_ptr) + dynrt_f128_load(rhs_ptr));
}

uintptr_t dynrt_f128_sub(uintptr_t lhs_ptr, uintptr_t rhs_ptr) {
    return dynrt_f128_box(dynrt_f128_load(lhs_ptr) - dynrt_f128_load(rhs_ptr));
}

uintptr_t dynrt_f128_mul(uintptr_t lhs_ptr, uintptr_t rhs_ptr) {
    return dynrt_f128_box(dynrt_f128_load(lhs_ptr) * dynrt_f128_load(rhs_ptr));
}

uintptr_t dynrt_f128_div(uintptr_t lhs_ptr, uintptr_t rhs_ptr) {
    return dynrt_f128_box(dynrt_f128_load(lhs_ptr) / dynrt_f128_load(rhs_ptr));
}

int32_t dynrt_f128_eq(uintptr_t lhs_ptr, uintptr_t rhs_ptr) {
    return dynrt_f128_load(lhs_ptr) == dynrt_f128_load(rhs_ptr) ? 1 : 0;
}

int32_t dynrt_f128_ne(uintptr_t lhs_ptr, uintptr_t rhs_ptr) {
    return dynrt_f128_load(lhs_ptr) != dynrt_f128_load(rhs_ptr) ? 1 : 0;
}

int32_t dynrt_f128_lt(uintptr_t lhs_ptr, uintptr_t rhs_ptr) {
    return dynrt_f128_load(lhs_ptr) < dynrt_f128_load(rhs_ptr) ? 1 : 0;
}

int32_t dynrt_f128_le(uintptr_t lhs_ptr, uintptr_t rhs_ptr) {
    return dynrt_f128_load(lhs_ptr) <= dynrt_f128_load(rhs_ptr) ? 1 : 0;
}

int32_t dynrt_f128_gt(uintptr_t lhs_ptr, uintptr_t rhs_ptr) {
    return dynrt_f128_load(lhs_ptr) > dynrt_f128_load(rhs_ptr) ? 1 : 0;
}

int32_t dynrt_f128_ge(uintptr_t lhs_ptr, uintptr_t rhs_ptr) {
    return dynrt_f128_load(lhs_ptr) >= dynrt_f128_load(rhs_ptr) ? 1 : 0;
}

int32_t dynrt_f128_release(uintptr_t value_ptr) {
    if (value_ptr != 0) {
        free((void *)(uintptr_t)value_ptr);
    }
    return 1;
}
