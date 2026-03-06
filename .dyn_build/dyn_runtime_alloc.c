#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

size_t __dyn_alloc_with(size_t alloc, size_t size, size_t align);
size_t __dyn_realloc_with(size_t alloc, size_t ptr, size_t old_size, size_t new_size, size_t align);
uint32_t __dyn_free_with(size_t alloc, size_t ptr, size_t size, size_t align);

static int dyn_is_power_of_two(size_t value) {
    return value != 0 && (value & (value - 1)) == 0;
}

size_t __dyn_alloc(size_t size, size_t align) {
    if (!dyn_is_power_of_two(align)) {
        return 0;
    }
    if (size == 0) {
        return 0;
    }

    void* ptr = NULL;
    if (align <= sizeof(void*)) {
        ptr = malloc(size);
    } else {
        if (posix_memalign(&ptr, align, size) != 0) {
            ptr = NULL;
        }
    }
    return (size_t)ptr;
}

size_t __dyn_realloc(size_t ptr, size_t old_size, size_t new_size, size_t align) {
    if (!dyn_is_power_of_two(align)) {
        return 0;
    }
    if (ptr == 0) {
        return __dyn_alloc(new_size, align);
    }
    if (new_size == 0) {
        free((void*)ptr);
        return 0;
    }

    if (align <= sizeof(void*)) {
        void* grown = realloc((void*)ptr, new_size);
        return (size_t)grown;
    }

    size_t next = __dyn_alloc(new_size, align);
    if (next == 0) {
        return 0;
    }

    size_t copy = old_size < new_size ? old_size : new_size;
    if (copy > 0) {
        memcpy((void*)next, (const void*)ptr, copy);
    }
    free((void*)ptr);
    return next;
}

uint32_t __dyn_free(size_t ptr, size_t size, size_t align) {
    (void)size;
    if (!dyn_is_power_of_two(align)) {
        return 0;
    }
    if (ptr == 0) {
        return 1;
    }
    free((void*)ptr);
    return 1;
}

size_t __dyn_c_allocator(void) {
    return 1;
}

static size_t dyn_fail_after = (size_t)-1;

size_t __dyn_test_failing_allocator(void) {
    return 2;
}

static int32_t dyn_identity_i32(int32_t value) {
    return value;
}

size_t __dyn_test_identity_i32_fn(void) {
    return (size_t)&dyn_identity_i32;
}

uint32_t __dyn_test_set_fail_after(size_t remaining_successes) {
    dyn_fail_after = remaining_successes;
    return 1;
}

static int dyn_allocator_should_fail(size_t alloc) {
    if (alloc != 2) {
        return 0;
    }
    if (dyn_fail_after == 0) {
        return 1;
    }
    if (dyn_fail_after != (size_t)-1) {
        dyn_fail_after -= 1;
    }
    return 0;
}

typedef struct DynArenaAllocator {
    size_t backing;
    uint8_t* ptr;
    size_t cap;
    size_t used;
} DynArenaAllocator;

static int dyn_is_arena_allocator(size_t alloc) {
    return alloc != 0 && alloc != 1 && alloc != 2;
}

static size_t dyn_align_up(size_t value, size_t align) {
    if (!dyn_is_power_of_two(align)) {
        return (size_t)-1;
    }
    size_t mask = align - 1;
    if (value > ((size_t)-1) - mask) {
        return (size_t)-1;
    }
    return (value + mask) & ~mask;
}

size_t __dyn_arena_allocator(size_t backing) {
    DynArenaAllocator* arena = (DynArenaAllocator*)malloc(sizeof(DynArenaAllocator));
    if (arena == NULL) {
        return 0;
    }
    arena->backing = backing;
    arena->ptr = NULL;
    arena->cap = 0;
    arena->used = 0;
    return (size_t)arena;
}

uint32_t __dyn_arena_reset(size_t arena_handle) {
    DynArenaAllocator* arena = (DynArenaAllocator*)arena_handle;
    if (arena == NULL) {
        return 0;
    }
    arena->used = 0;
    return 1;
}

uint32_t __dyn_arena_deinit(size_t arena_handle) {
    DynArenaAllocator* arena = (DynArenaAllocator*)arena_handle;
    if (arena == NULL) {
        return 1;
    }
    if (arena->ptr != NULL && arena->cap != 0) {
        if (!__dyn_free_with(arena->backing, (size_t)arena->ptr, arena->cap, 16)) {
            return 0;
        }
    }
    free(arena);
    return 1;
}

static size_t dyn_arena_alloc(DynArenaAllocator* arena, size_t size, size_t align) {
    if (!dyn_is_power_of_two(align)) {
        return 0;
    }
    if (size == 0) {
        return 0;
    }

    size_t aligned_used = dyn_align_up(arena->used, align);
    if (aligned_used == (size_t)-1) {
        return 0;
    }
    size_t required = aligned_used + size;
    if (required < aligned_used) {
        return 0;
    }

    if (required > arena->cap) {
        size_t next_cap = arena->cap == 0 ? 4096 : arena->cap;
        while (next_cap < required) {
            if (next_cap > ((size_t)-1) / 2) {
                next_cap = required;
                break;
            }
            next_cap *= 2;
        }
        size_t next_ptr = __dyn_realloc_with(arena->backing, (size_t)arena->ptr, arena->cap, next_cap, 16);
        if (next_ptr == 0) {
            return 0;
        }
        arena->ptr = (uint8_t*)next_ptr;
        arena->cap = next_cap;
    }

    size_t out = (size_t)(arena->ptr + aligned_used);
    arena->used = required;
    return out;
}

size_t __dyn_alloc_with(size_t alloc, size_t size, size_t align) {
    if (dyn_is_arena_allocator(alloc)) {
        return dyn_arena_alloc((DynArenaAllocator*)alloc, size, align);
    }
    if (dyn_allocator_should_fail(alloc)) {
        return 0;
    }
    return __dyn_alloc(size, align);
}

size_t __dyn_realloc_with(size_t alloc, size_t ptr, size_t old_size, size_t new_size, size_t align) {
    if (dyn_is_arena_allocator(alloc)) {
        DynArenaAllocator* arena = (DynArenaAllocator*)alloc;
        if (ptr == 0) {
            return dyn_arena_alloc(arena, new_size, align);
        }
        if (new_size == 0) {
            return 0;
        }
        if (new_size <= old_size) {
            return ptr;
        }
        size_t next = dyn_arena_alloc(arena, new_size, align);
        if (next == 0) {
            return 0;
        }
        memcpy((void*)next, (const void*)ptr, old_size);
        return next;
    }
    if (dyn_allocator_should_fail(alloc)) {
        return 0;
    }
    return __dyn_realloc(ptr, old_size, new_size, align);
}

uint32_t __dyn_free_with(size_t alloc, size_t ptr, size_t size, size_t align) {
    if (dyn_is_arena_allocator(alloc)) {
        (void)ptr;
        (void)size;
        (void)align;
        return 1;
    }
    (void)alloc;
    return __dyn_free(ptr, size, align);
}

uint32_t __dyn_mem_copy(size_t dst, size_t src, size_t size) {
    if (size == 0) {
        return 1;
    }
    if (dst == 0 || src == 0) {
        return 0;
    }
    memcpy((void*)dst, (const void*)src, size);
    return 1;
}

uint32_t __dyn_mem_move(size_t dst, size_t src, size_t size) {
    if (size == 0) {
        return 1;
    }
    if (dst == 0 || src == 0) {
        return 0;
    }
    memmove((void*)dst, (const void*)src, size);
    return 1;
}

uint32_t __dyn_mem_set(size_t dst, uint32_t byte_value, size_t size) {
    if (size == 0) {
        return 1;
    }
    if (dst == 0) {
        return 0;
    }
    memset((void*)dst, (int)(byte_value & 0xFFu), size);
    return 1;
}

uint32_t __dyn_mem_eq(size_t lhs, size_t rhs, size_t size) {
    if (size == 0) {
        return 1;
    }
    if (lhs == 0 || rhs == 0) {
        return 0;
    }
    return memcmp((const void*)lhs, (const void*)rhs, size) == 0 ? 1u : 0u;
}

typedef struct DynVecI32 {
    size_t alloc;
    int32_t* ptr;
    size_t len;
    size_t cap;
} DynVecI32;

size_t __dyn_vec_i32_init(size_t alloc) {
    DynVecI32* vec = (DynVecI32*)malloc(sizeof(DynVecI32));
    if (vec == NULL) {
        return 0;
    }
    vec->alloc = alloc;
    vec->ptr = NULL;
    vec->len = 0;
    vec->cap = 0;
    return (size_t)vec;
}

uint32_t __dyn_vec_i32_deinit(size_t handle) {
    DynVecI32* vec = (DynVecI32*)handle;
    if (vec == NULL) {
        return 1;
    }
    if (vec->ptr != NULL) {
        if (!__dyn_free_with(vec->alloc, (size_t)vec->ptr, vec->cap * sizeof(int32_t), sizeof(int32_t))) {
            return 0;
        }
    }
    free(vec);
    return 1;
}

size_t __dyn_vec_i32_len(size_t handle) {
    DynVecI32* vec = (DynVecI32*)handle;
    if (vec == NULL) {
        return 0;
    }
    return vec->len;
}

size_t __dyn_vec_i32_cap(size_t handle) {
    DynVecI32* vec = (DynVecI32*)handle;
    if (vec == NULL) {
        return 0;
    }
    return vec->cap;
}

static uint32_t dyn_vec_i32_reserve_exact(DynVecI32* vec, size_t new_cap) {
    if (new_cap <= vec->cap) {
        return 1;
    }
    if (new_cap > ((size_t)-1) / sizeof(int32_t)) {
        return 0;
    }
    size_t new_size = new_cap * sizeof(int32_t);
    size_t old_size = vec->cap * sizeof(int32_t);
    size_t next = __dyn_realloc_with(vec->alloc, (size_t)vec->ptr, old_size, new_size, sizeof(int32_t));
    if (next == 0) {
        return 0;
    }
    vec->ptr = (int32_t*)next;
    vec->cap = new_cap;
    return 1;
}

uint32_t __dyn_vec_i32_push(size_t handle, int32_t value) {
    DynVecI32* vec = (DynVecI32*)handle;
    if (vec == NULL) {
        return 0;
    }
    if (vec->len == vec->cap) {
        size_t next_cap = vec->cap == 0 ? 4 : vec->cap * 2;
        if (next_cap < vec->cap) {
            return 0;
        }
        if (!dyn_vec_i32_reserve_exact(vec, next_cap)) {
            return 0;
        }
    }
    vec->ptr[vec->len] = value;
    vec->len += 1;
    return 1;
}

int32_t __dyn_vec_i32_get(size_t handle, size_t index) {
    DynVecI32* vec = (DynVecI32*)handle;
    if (vec == NULL || index >= vec->len) {
        return 0;
    }
    return vec->ptr[index];
}

uint32_t __dyn_vec_i32_set(size_t handle, size_t index, int32_t value) {
    DynVecI32* vec = (DynVecI32*)handle;
    if (vec == NULL || index >= vec->len) {
        return 0;
    }
    vec->ptr[index] = value;
    return 1;
}

int32_t __dyn_vec_i32_pop(size_t handle) {
    DynVecI32* vec = (DynVecI32*)handle;
    if (vec == NULL || vec->len == 0) {
        return 0;
    }
    vec->len -= 1;
    return vec->ptr[vec->len];
}

uint32_t __dyn_vec_i32_clear(size_t handle) {
    DynVecI32* vec = (DynVecI32*)handle;
    if (vec == NULL) {
        return 0;
    }
    vec->len = 0;
    return 1;
}

uint32_t __dyn_vec_i32_reserve(size_t handle, size_t new_cap) {
    DynVecI32* vec = (DynVecI32*)handle;
    if (vec == NULL) {
        return 0;
    }
    return dyn_vec_i32_reserve_exact(vec, new_cap);
}

size_t std_vec_i32_init(size_t alloc) {
    return __dyn_vec_i32_init(alloc);
}

uint32_t std_vec_i32_deinit(size_t handle) {
    return __dyn_vec_i32_deinit(handle);
}

size_t std_vec_i32_len(size_t handle) {
    return __dyn_vec_i32_len(handle);
}

size_t std_vec_i32_cap(size_t handle) {
    return __dyn_vec_i32_cap(handle);
}

uint32_t std_vec_i32_push(size_t handle, int32_t value) {
    return __dyn_vec_i32_push(handle, value);
}

int32_t std_vec_i32_get(size_t handle, size_t index) {
    return __dyn_vec_i32_get(handle, index);
}

uint32_t std_vec_i32_set(size_t handle, size_t index, int32_t value) {
    return __dyn_vec_i32_set(handle, index, value);
}

int32_t std_vec_i32_pop(size_t handle) {
    return __dyn_vec_i32_pop(handle);
}

uint32_t std_vec_i32_clear(size_t handle) {
    return __dyn_vec_i32_clear(handle);
}

uint32_t std_vec_i32_reserve(size_t handle, size_t new_cap) {
    return __dyn_vec_i32_reserve(handle, new_cap);
}

typedef struct DynVecRaw {
    size_t alloc;
    uint8_t* ptr;
    size_t len;
    size_t cap;
    size_t elem_size;
    size_t elem_align;
} DynVecRaw;

size_t __dyn_vec_raw_init(size_t alloc, size_t elem_size, size_t elem_align) {
    if (elem_size == 0 || !dyn_is_power_of_two(elem_align)) {
        return 0;
    }
    DynVecRaw* vec = (DynVecRaw*)malloc(sizeof(DynVecRaw));
    if (vec == NULL) {
        return 0;
    }
    vec->alloc = alloc;
    vec->ptr = NULL;
    vec->len = 0;
    vec->cap = 0;
    vec->elem_size = elem_size;
    vec->elem_align = elem_align;
    return (size_t)vec;
}

uint32_t __dyn_vec_raw_deinit(size_t handle) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL) {
        return 1;
    }
    if (vec->ptr != NULL) {
        size_t size = vec->cap * vec->elem_size;
        if (!__dyn_free_with(vec->alloc, (size_t)vec->ptr, size, vec->elem_align)) {
            return 0;
        }
    }
    free(vec);
    return 1;
}

size_t __dyn_vec_raw_len(size_t handle) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL) {
        return 0;
    }
    return vec->len;
}

size_t __dyn_vec_raw_cap(size_t handle) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL) {
        return 0;
    }
    return vec->cap;
}

static uint32_t dyn_vec_raw_reserve_exact(DynVecRaw* vec, size_t new_cap) {
    if (new_cap <= vec->cap) {
        return 1;
    }
    if (vec->elem_size != 0 && new_cap > ((size_t)-1) / vec->elem_size) {
        return 0;
    }
    size_t old_size = vec->cap * vec->elem_size;
    size_t new_size = new_cap * vec->elem_size;
    size_t next = __dyn_realloc_with(vec->alloc, (size_t)vec->ptr, old_size, new_size, vec->elem_align);
    if (next == 0) {
        return 0;
    }
    vec->ptr = (uint8_t*)next;
    vec->cap = new_cap;
    return 1;
}

uint32_t __dyn_vec_raw_push_u64(size_t handle, uint64_t value) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL || vec->elem_size > sizeof(uint64_t)) {
        return 0;
    }
    if (vec->len == vec->cap) {
        size_t next_cap = vec->cap == 0 ? 4 : vec->cap * 2;
        if (next_cap < vec->cap) {
            return 0;
        }
        if (!dyn_vec_raw_reserve_exact(vec, next_cap)) {
            return 0;
        }
    }
    uint8_t* dst = vec->ptr + (vec->len * vec->elem_size);
    memcpy(dst, &value, vec->elem_size);
    vec->len += 1;
    return 1;
}

uint64_t __dyn_vec_raw_get_u64(size_t handle, size_t index) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL || index >= vec->len || vec->elem_size > sizeof(uint64_t)) {
        return 0;
    }
    uint64_t out = 0;
    const uint8_t* src = vec->ptr + (index * vec->elem_size);
    memcpy(&out, src, vec->elem_size);
    return out;
}

uint32_t __dyn_vec_raw_set_u64(size_t handle, size_t index, uint64_t value) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL || index >= vec->len || vec->elem_size > sizeof(uint64_t)) {
        return 0;
    }
    uint8_t* dst = vec->ptr + (index * vec->elem_size);
    memcpy(dst, &value, vec->elem_size);
    return 1;
}

uint64_t __dyn_vec_raw_pop_u64(size_t handle) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL || vec->len == 0 || vec->elem_size > sizeof(uint64_t)) {
        return 0;
    }
    vec->len -= 1;
    uint64_t out = 0;
    const uint8_t* src = vec->ptr + (vec->len * vec->elem_size);
    memcpy(&out, src, vec->elem_size);
    return out;
}

uint32_t __dyn_vec_raw_clear(size_t handle) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL) {
        return 0;
    }
    vec->len = 0;
    return 1;
}

uint32_t __dyn_vec_raw_reserve(size_t handle, size_t new_cap) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL) {
        return 0;
    }
    return dyn_vec_raw_reserve_exact(vec, new_cap);
}

size_t std_vec_init(size_t alloc, size_t elem_size, size_t elem_align) {
    return __dyn_vec_raw_init(alloc, elem_size, elem_align);
}

uint32_t std_vec_deinit(size_t handle) {
    return __dyn_vec_raw_deinit(handle);
}

size_t std_vec_len(size_t handle) {
    return __dyn_vec_raw_len(handle);
}

size_t std_vec_cap(size_t handle) {
    return __dyn_vec_raw_cap(handle);
}

uint32_t std_vec_push_u64(size_t handle, uint64_t value) {
    return __dyn_vec_raw_push_u64(handle, value);
}

uint64_t std_vec_get_u64(size_t handle, size_t index) {
    return __dyn_vec_raw_get_u64(handle, index);
}

uint32_t std_vec_set_u64(size_t handle, size_t index, uint64_t value) {
    return __dyn_vec_raw_set_u64(handle, index, value);
}

uint64_t std_vec_pop_u64(size_t handle) {
    return __dyn_vec_raw_pop_u64(handle);
}

uint32_t std_vec_clear(size_t handle) {
    return __dyn_vec_raw_clear(handle);
}

uint32_t std_vec_reserve(size_t handle, size_t new_cap) {
    return __dyn_vec_raw_reserve(handle, new_cap);
}

uint32_t std_io_print_i32(int32_t value) {
    return printf("%d", value) >= 0 ? 1u : 0u;
}

uint32_t std_io_println_i32(int32_t value) {
    return printf("%d\n", value) >= 0 ? 1u : 0u;
}

uint32_t std_io_print(size_t cstr) {
    if (cstr == 0) {
        return 0u;
    }
    return fputs((const char*)cstr, stdout) >= 0 ? 1u : 0u;
}

uint32_t std_io_println(size_t cstr) {
    if (cstr == 0) {
        return 0u;
    }
    return fprintf(stdout, "%s\n", (const char*)cstr) >= 0 ? 1u : 0u;
}
