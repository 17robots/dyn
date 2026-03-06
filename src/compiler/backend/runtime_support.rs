#![allow(non_snake_case)]

use std::ffi::{c_char, c_int, c_void};
use std::mem;
use std::ptr;

unsafe extern "C" {
    fn malloc(size: usize) -> *mut c_void;
    fn realloc(ptr: *mut c_void, size: usize) -> *mut c_void;
    fn free(ptr: *mut c_void);
    fn posix_memalign(memptr: *mut *mut c_void, align: usize, size: usize) -> c_int;
    fn printf(fmt: *const c_char, ...) -> c_int;
}

const DYN_ALLOCATOR_C: usize = 1;
const DYN_ALLOCATOR_FAILING: usize = 2;

const FMT_I32: &[u8] = b"%d\0";
const FMT_I32_NL: &[u8] = b"%d\n\0";
const FMT_STR: &[u8] = b"%s\0";
const FMT_STR_NL: &[u8] = b"%s\n\0";

static mut DYN_FAIL_AFTER: usize = usize::MAX;

#[repr(C)]
struct DynArenaAllocator {
    backing: usize,
    ptr: *mut u8,
    cap: usize,
    used: usize,
}

#[repr(C)]
struct DynVecI32 {
    alloc: usize,
    ptr: *mut i32,
    len: usize,
    cap: usize,
}

#[repr(C)]
struct DynVecRaw {
    alloc: usize,
    ptr: *mut u8,
    len: usize,
    cap: usize,
    elem_size: usize,
    elem_align: usize,
}

#[inline]
fn dyn_is_power_of_two(value: usize) -> bool {
    value != 0 && (value & (value - 1)) == 0
}

#[inline]
fn dyn_is_arena_allocator(alloc: usize) -> bool {
    alloc != 0 && alloc != DYN_ALLOCATOR_C && alloc != DYN_ALLOCATOR_FAILING
}

#[inline]
fn dyn_align_up(value: usize, align: usize) -> Option<usize> {
    if !dyn_is_power_of_two(align) {
        return None;
    }
    let mask = align - 1;
    value.checked_add(mask).map(|v| v & !mask)
}

#[inline]
unsafe fn dyn_copy_bytes(dst: usize, src: usize, size: usize) {
    if size == 0 {
        return;
    }
    unsafe {
        ptr::copy_nonoverlapping(src as *const u8, dst as *mut u8, size);
    }
}

#[inline]
unsafe fn dyn_move_bytes(dst: usize, src: usize, size: usize) {
    if size == 0 {
        return;
    }
    unsafe {
        ptr::copy(src as *const u8, dst as *mut u8, size);
    }
}

#[inline]
unsafe fn dyn_set_bytes(dst: usize, byte_value: u8, size: usize) {
    if size == 0 {
        return;
    }
    unsafe {
        ptr::write_bytes(dst as *mut u8, byte_value, size);
    }
}

#[inline]
unsafe fn dyn_alloc_struct<T>() -> *mut T {
    unsafe { malloc(mem::size_of::<T>()) as *mut T }
}

unsafe extern "C" fn dyn_identity_i32(value: i32) -> i32 {
    value
}

#[inline]
fn dyn_allocator_should_fail(alloc: usize) -> bool {
    if alloc != DYN_ALLOCATOR_FAILING {
        return false;
    }
    unsafe {
        if DYN_FAIL_AFTER == 0 {
            return true;
        }
        if DYN_FAIL_AFTER != usize::MAX {
            DYN_FAIL_AFTER = DYN_FAIL_AFTER.saturating_sub(1);
        }
    }
    false
}

unsafe fn dyn_arena_alloc(arena: &mut DynArenaAllocator, size: usize, align: usize) -> usize {
    if !dyn_is_power_of_two(align) || size == 0 {
        return 0;
    }

    let Some(aligned_used) = dyn_align_up(arena.used, align) else {
        return 0;
    };
    let Some(required) = aligned_used.checked_add(size) else {
        return 0;
    };

    if required > arena.cap {
        let mut next_cap = if arena.cap == 0 { 4096 } else { arena.cap };
        while next_cap < required {
            if next_cap > usize::MAX / 2 {
                next_cap = required;
                break;
            }
            next_cap *= 2;
        }

        let next_ptr = unsafe {
            __dyn_realloc_with(arena.backing, arena.ptr as usize, arena.cap, next_cap, 16)
        };
        if next_ptr == 0 {
            return 0;
        }
        arena.ptr = next_ptr as *mut u8;
        arena.cap = next_cap;
    }

    let out = unsafe { arena.ptr.add(aligned_used) as usize };
    arena.used = required;
    out
}

unsafe fn dyn_vec_i32_reserve_exact(vec: &mut DynVecI32, new_cap: usize) -> u32 {
    if new_cap <= vec.cap {
        return 1;
    }
    if new_cap > usize::MAX / mem::size_of::<i32>() {
        return 0;
    }
    let new_size = new_cap * mem::size_of::<i32>();
    let old_size = vec.cap * mem::size_of::<i32>();
    let next = unsafe { __dyn_realloc_with(vec.alloc, vec.ptr as usize, old_size, new_size, 4) };
    if next == 0 {
        return 0;
    }
    vec.ptr = next as *mut i32;
    vec.cap = new_cap;
    1
}

unsafe fn dyn_vec_raw_reserve_exact(vec: &mut DynVecRaw, new_cap: usize) -> u32 {
    if new_cap <= vec.cap {
        return 1;
    }
    let Some(old_size) = vec.cap.checked_mul(vec.elem_size) else {
        return 0;
    };
    let Some(new_size) = new_cap.checked_mul(vec.elem_size) else {
        return 0;
    };
    let next = unsafe {
        __dyn_realloc_with(
            vec.alloc,
            vec.ptr as usize,
            old_size,
            new_size,
            vec.elem_align,
        )
    };
    if next == 0 {
        return 0;
    }
    vec.ptr = next as *mut u8;
    vec.cap = new_cap;
    1
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_alloc(size: usize, align: usize) -> usize {
    if !dyn_is_power_of_two(align) || size == 0 {
        return 0;
    }

    let mut ptr_out: *mut c_void = ptr::null_mut();
    if align <= mem::size_of::<*mut c_void>() {
        unsafe {
            ptr_out = malloc(size);
        }
    } else {
        let rc = unsafe { posix_memalign(&mut ptr_out as *mut *mut c_void, align, size) };
        if rc != 0 {
            ptr_out = ptr::null_mut();
        }
    }

    ptr_out as usize
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_realloc(
    ptr_value: usize,
    old_size: usize,
    new_size: usize,
    align: usize,
) -> usize {
    if !dyn_is_power_of_two(align) {
        return 0;
    }
    if ptr_value == 0 {
        return unsafe { __dyn_alloc(new_size, align) };
    }
    if new_size == 0 {
        unsafe {
            free(ptr_value as *mut c_void);
        }
        return 0;
    }

    if align <= mem::size_of::<*mut c_void>() {
        let grown = unsafe { realloc(ptr_value as *mut c_void, new_size) };
        return grown as usize;
    }

    let next = unsafe { __dyn_alloc(new_size, align) };
    if next == 0 {
        return 0;
    }

    let copy = old_size.min(new_size);
    if copy > 0 {
        unsafe {
            dyn_copy_bytes(next, ptr_value, copy);
        }
    }
    unsafe {
        free(ptr_value as *mut c_void);
    }
    next
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_free(ptr_value: usize, _size: usize, align: usize) -> u32 {
    if !dyn_is_power_of_two(align) {
        return 0;
    }
    if ptr_value == 0 {
        return 1;
    }
    unsafe {
        free(ptr_value as *mut c_void);
    }
    1
}

#[no_mangle]
pub extern "C" fn __dyn_c_allocator() -> usize {
    DYN_ALLOCATOR_C
}

#[no_mangle]
pub extern "C" fn __dyn_test_failing_allocator() -> usize {
    DYN_ALLOCATOR_FAILING
}

#[no_mangle]
pub extern "C" fn __dyn_test_identity_i32_fn() -> usize {
    dyn_identity_i32 as *const () as usize
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_test_set_fail_after(remaining_successes: usize) -> u32 {
    unsafe {
        DYN_FAIL_AFTER = remaining_successes;
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_arena_allocator(backing: usize) -> usize {
    let arena = unsafe { dyn_alloc_struct::<DynArenaAllocator>() };
    if arena.is_null() {
        return 0;
    }
    unsafe {
        (*arena).backing = backing;
        (*arena).ptr = ptr::null_mut();
        (*arena).cap = 0;
        (*arena).used = 0;
    }
    arena as usize
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_arena_reset(arena_handle: usize) -> u32 {
    let arena = arena_handle as *mut DynArenaAllocator;
    if arena.is_null() {
        return 0;
    }
    unsafe {
        (*arena).used = 0;
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_arena_deinit(arena_handle: usize) -> u32 {
    let arena = arena_handle as *mut DynArenaAllocator;
    if arena.is_null() {
        return 1;
    }

    let (ptr_value, cap, backing) =
        unsafe { ((*arena).ptr as usize, (*arena).cap, (*arena).backing) };
    if ptr_value != 0 && cap != 0 && unsafe { __dyn_free_with(backing, ptr_value, cap, 16) } == 0 {
        return 0;
    }

    unsafe {
        free(arena as *mut c_void);
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_alloc_with(alloc: usize, size: usize, align: usize) -> usize {
    if dyn_is_arena_allocator(alloc) {
        let arena = alloc as *mut DynArenaAllocator;
        if arena.is_null() {
            return 0;
        }
        return unsafe { dyn_arena_alloc(&mut *arena, size, align) };
    }
    if dyn_allocator_should_fail(alloc) {
        return 0;
    }
    unsafe { __dyn_alloc(size, align) }
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_realloc_with(
    alloc: usize,
    ptr_value: usize,
    old_size: usize,
    new_size: usize,
    align: usize,
) -> usize {
    if dyn_is_arena_allocator(alloc) {
        let arena = alloc as *mut DynArenaAllocator;
        if arena.is_null() {
            return 0;
        }
        if ptr_value == 0 {
            return unsafe { dyn_arena_alloc(&mut *arena, new_size, align) };
        }
        if new_size == 0 {
            return 0;
        }
        if new_size <= old_size {
            return ptr_value;
        }
        let next = unsafe { dyn_arena_alloc(&mut *arena, new_size, align) };
        if next == 0 {
            return 0;
        }
        unsafe {
            dyn_copy_bytes(next, ptr_value, old_size);
        }
        return next;
    }

    if dyn_allocator_should_fail(alloc) {
        return 0;
    }
    unsafe { __dyn_realloc(ptr_value, old_size, new_size, align) }
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_free_with(
    alloc: usize,
    ptr_value: usize,
    size: usize,
    align: usize,
) -> u32 {
    if dyn_is_arena_allocator(alloc) {
        let _ = (ptr_value, size, align);
        return 1;
    }
    unsafe { __dyn_free(ptr_value, size, align) }
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_mem_copy(dst: usize, src: usize, size: usize) -> u32 {
    if size == 0 {
        return 1;
    }
    if dst == 0 || src == 0 {
        return 0;
    }
    unsafe {
        dyn_copy_bytes(dst, src, size);
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_mem_move(dst: usize, src: usize, size: usize) -> u32 {
    if size == 0 {
        return 1;
    }
    if dst == 0 || src == 0 {
        return 0;
    }
    unsafe {
        dyn_move_bytes(dst, src, size);
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_mem_set(dst: usize, byte_value: u32, size: usize) -> u32 {
    if size == 0 {
        return 1;
    }
    if dst == 0 {
        return 0;
    }
    unsafe {
        dyn_set_bytes(dst, (byte_value & 0xFF) as u8, size);
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_mem_eq(lhs: usize, rhs: usize, size: usize) -> u32 {
    if size == 0 {
        return 1;
    }
    if lhs == 0 || rhs == 0 {
        return 0;
    }

    let equal = unsafe {
        let left = std::slice::from_raw_parts(lhs as *const u8, size);
        let right = std::slice::from_raw_parts(rhs as *const u8, size);
        left == right
    };
    if equal {
        1
    } else {
        0
    }
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_i32_init(alloc: usize) -> usize {
    let vec = unsafe { dyn_alloc_struct::<DynVecI32>() };
    if vec.is_null() {
        return 0;
    }
    unsafe {
        (*vec).alloc = alloc;
        (*vec).ptr = ptr::null_mut();
        (*vec).len = 0;
        (*vec).cap = 0;
    }
    vec as usize
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_i32_deinit(handle: usize) -> u32 {
    let vec = handle as *mut DynVecI32;
    if vec.is_null() {
        return 1;
    }
    let (ptr_value, cap, alloc) = unsafe { ((*vec).ptr as usize, (*vec).cap, (*vec).alloc) };
    if ptr_value != 0 {
        let size = cap * mem::size_of::<i32>();
        if unsafe { __dyn_free_with(alloc, ptr_value, size, mem::size_of::<i32>()) } == 0 {
            return 0;
        }
    }
    unsafe {
        free(vec as *mut c_void);
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_i32_len(handle: usize) -> usize {
    let vec = handle as *mut DynVecI32;
    if vec.is_null() {
        0
    } else {
        unsafe { (*vec).len }
    }
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_i32_cap(handle: usize) -> usize {
    let vec = handle as *mut DynVecI32;
    if vec.is_null() {
        0
    } else {
        unsafe { (*vec).cap }
    }
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_i32_push(handle: usize, value: i32) -> u32 {
    let vec = handle as *mut DynVecI32;
    if vec.is_null() {
        return 0;
    }
    let vec = unsafe { &mut *vec };
    if vec.len == vec.cap {
        let next_cap = if vec.cap == 0 {
            4
        } else {
            match vec.cap.checked_mul(2) {
                Some(v) => v,
                None => return 0,
            }
        };
        if unsafe { dyn_vec_i32_reserve_exact(vec, next_cap) } == 0 {
            return 0;
        }
    }

    unsafe {
        *vec.ptr.add(vec.len) = value;
    }
    vec.len += 1;
    1
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_i32_get(handle: usize, index: usize) -> i32 {
    let vec = handle as *mut DynVecI32;
    if vec.is_null() {
        return 0;
    }
    let vec = unsafe { &*vec };
    if index >= vec.len {
        return 0;
    }
    unsafe { *vec.ptr.add(index) }
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_i32_set(handle: usize, index: usize, value: i32) -> u32 {
    let vec = handle as *mut DynVecI32;
    if vec.is_null() {
        return 0;
    }
    let vec = unsafe { &mut *vec };
    if index >= vec.len {
        return 0;
    }
    unsafe {
        *vec.ptr.add(index) = value;
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_i32_pop(handle: usize) -> i32 {
    let vec = handle as *mut DynVecI32;
    if vec.is_null() {
        return 0;
    }
    let vec = unsafe { &mut *vec };
    if vec.len == 0 {
        return 0;
    }
    vec.len -= 1;
    unsafe { *vec.ptr.add(vec.len) }
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_i32_clear(handle: usize) -> u32 {
    let vec = handle as *mut DynVecI32;
    if vec.is_null() {
        return 0;
    }
    unsafe {
        (*vec).len = 0;
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_i32_reserve(handle: usize, new_cap: usize) -> u32 {
    let vec = handle as *mut DynVecI32;
    if vec.is_null() {
        return 0;
    }
    unsafe { dyn_vec_i32_reserve_exact(&mut *vec, new_cap) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_i32_init(alloc: usize) -> usize {
    unsafe { __dyn_vec_i32_init(alloc) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_i32_deinit(handle: usize) -> u32 {
    unsafe { __dyn_vec_i32_deinit(handle) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_i32_len(handle: usize) -> usize {
    unsafe { __dyn_vec_i32_len(handle) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_i32_cap(handle: usize) -> usize {
    unsafe { __dyn_vec_i32_cap(handle) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_i32_push(handle: usize, value: i32) -> u32 {
    unsafe { __dyn_vec_i32_push(handle, value) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_i32_get(handle: usize, index: usize) -> i32 {
    unsafe { __dyn_vec_i32_get(handle, index) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_i32_set(handle: usize, index: usize, value: i32) -> u32 {
    unsafe { __dyn_vec_i32_set(handle, index, value) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_i32_pop(handle: usize) -> i32 {
    unsafe { __dyn_vec_i32_pop(handle) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_i32_clear(handle: usize) -> u32 {
    unsafe { __dyn_vec_i32_clear(handle) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_i32_reserve(handle: usize, new_cap: usize) -> u32 {
    unsafe { __dyn_vec_i32_reserve(handle, new_cap) }
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_raw_init(
    alloc: usize,
    elem_size: usize,
    elem_align: usize,
) -> usize {
    if elem_size == 0 || !dyn_is_power_of_two(elem_align) {
        return 0;
    }
    let vec = unsafe { dyn_alloc_struct::<DynVecRaw>() };
    if vec.is_null() {
        return 0;
    }
    unsafe {
        (*vec).alloc = alloc;
        (*vec).ptr = ptr::null_mut();
        (*vec).len = 0;
        (*vec).cap = 0;
        (*vec).elem_size = elem_size;
        (*vec).elem_align = elem_align;
    }
    vec as usize
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_raw_deinit(handle: usize) -> u32 {
    let vec = handle as *mut DynVecRaw;
    if vec.is_null() {
        return 1;
    }
    let (ptr_value, cap, elem_size, alloc, elem_align) = unsafe {
        (
            (*vec).ptr as usize,
            (*vec).cap,
            (*vec).elem_size,
            (*vec).alloc,
            (*vec).elem_align,
        )
    };
    if ptr_value != 0 {
        let size = cap.saturating_mul(elem_size);
        if unsafe { __dyn_free_with(alloc, ptr_value, size, elem_align) } == 0 {
            return 0;
        }
    }
    unsafe {
        free(vec as *mut c_void);
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_raw_len(handle: usize) -> usize {
    let vec = handle as *mut DynVecRaw;
    if vec.is_null() {
        0
    } else {
        unsafe { (*vec).len }
    }
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_raw_cap(handle: usize) -> usize {
    let vec = handle as *mut DynVecRaw;
    if vec.is_null() {
        0
    } else {
        unsafe { (*vec).cap }
    }
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_raw_push_u64(handle: usize, value: u64) -> u32 {
    let vec = handle as *mut DynVecRaw;
    if vec.is_null() {
        return 0;
    }
    let vec = unsafe { &mut *vec };
    if vec.elem_size > mem::size_of::<u64>() {
        return 0;
    }
    if vec.len == vec.cap {
        let next_cap = if vec.cap == 0 {
            4
        } else {
            match vec.cap.checked_mul(2) {
                Some(v) => v,
                None => return 0,
            }
        };
        if unsafe { dyn_vec_raw_reserve_exact(vec, next_cap) } == 0 {
            return 0;
        }
    }
    let Some(offset) = vec.len.checked_mul(vec.elem_size) else {
        return 0;
    };
    let dst = unsafe { vec.ptr.add(offset) };
    unsafe {
        ptr::copy_nonoverlapping((&value as *const u64).cast::<u8>(), dst, vec.elem_size);
    }
    vec.len += 1;
    1
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_raw_get_u64(handle: usize, index: usize) -> u64 {
    let vec = handle as *mut DynVecRaw;
    if vec.is_null() {
        return 0;
    }
    let vec = unsafe { &*vec };
    if index >= vec.len || vec.elem_size > mem::size_of::<u64>() {
        return 0;
    }
    let Some(offset) = index.checked_mul(vec.elem_size) else {
        return 0;
    };
    let src = unsafe { vec.ptr.add(offset) };
    let mut out = 0u64;
    unsafe {
        ptr::copy_nonoverlapping(src, (&mut out as *mut u64).cast::<u8>(), vec.elem_size);
    }
    out
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_raw_set_u64(handle: usize, index: usize, value: u64) -> u32 {
    let vec = handle as *mut DynVecRaw;
    if vec.is_null() {
        return 0;
    }
    let vec = unsafe { &mut *vec };
    if index >= vec.len || vec.elem_size > mem::size_of::<u64>() {
        return 0;
    }
    let Some(offset) = index.checked_mul(vec.elem_size) else {
        return 0;
    };
    let dst = unsafe { vec.ptr.add(offset) };
    unsafe {
        ptr::copy_nonoverlapping((&value as *const u64).cast::<u8>(), dst, vec.elem_size);
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_raw_pop_u64(handle: usize) -> u64 {
    let vec = handle as *mut DynVecRaw;
    if vec.is_null() {
        return 0;
    }
    let vec = unsafe { &mut *vec };
    if vec.len == 0 || vec.elem_size > mem::size_of::<u64>() {
        return 0;
    }
    vec.len -= 1;
    let Some(offset) = vec.len.checked_mul(vec.elem_size) else {
        return 0;
    };
    let src = unsafe { vec.ptr.add(offset) };
    let mut out = 0u64;
    unsafe {
        ptr::copy_nonoverlapping(src, (&mut out as *mut u64).cast::<u8>(), vec.elem_size);
    }
    out
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_raw_clear(handle: usize) -> u32 {
    let vec = handle as *mut DynVecRaw;
    if vec.is_null() {
        return 0;
    }
    unsafe {
        (*vec).len = 0;
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_raw_reserve(handle: usize, new_cap: usize) -> u32 {
    let vec = handle as *mut DynVecRaw;
    if vec.is_null() {
        return 0;
    }
    unsafe { dyn_vec_raw_reserve_exact(&mut *vec, new_cap) }
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_raw_ptr(handle: usize, index: usize) -> usize {
    let vec = handle as *mut DynVecRaw;
    if vec.is_null() {
        return 0;
    }
    let vec = unsafe { &*vec };
    if index >= vec.len {
        return 0;
    }
    let Some(offset) = index.checked_mul(vec.elem_size) else {
        return 0;
    };
    unsafe { vec.ptr.add(offset) as usize }
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_raw_push_bytes(
    handle: usize,
    src: usize,
    src_size: usize,
) -> u32 {
    let vec = handle as *mut DynVecRaw;
    if vec.is_null() || src == 0 {
        return 0;
    }
    let vec = unsafe { &mut *vec };
    if src_size != vec.elem_size {
        return 0;
    }
    if vec.len == vec.cap {
        let next_cap = if vec.cap == 0 {
            4
        } else {
            match vec.cap.checked_mul(2) {
                Some(v) => v,
                None => return 0,
            }
        };
        if unsafe { dyn_vec_raw_reserve_exact(vec, next_cap) } == 0 {
            return 0;
        }
    }
    let Some(offset) = vec.len.checked_mul(vec.elem_size) else {
        return 0;
    };
    let dst = unsafe { vec.ptr.add(offset) } as usize;
    unsafe {
        dyn_copy_bytes(dst, src, vec.elem_size);
    }
    vec.len += 1;
    1
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_raw_get_bytes(
    handle: usize,
    index: usize,
    dst: usize,
    dst_size: usize,
) -> u32 {
    let vec = handle as *mut DynVecRaw;
    if vec.is_null() || dst == 0 {
        return 0;
    }
    let vec = unsafe { &*vec };
    if index >= vec.len || dst_size != vec.elem_size {
        return 0;
    }
    let Some(offset) = index.checked_mul(vec.elem_size) else {
        return 0;
    };
    let src = unsafe { vec.ptr.add(offset) as usize };
    unsafe {
        dyn_copy_bytes(dst, src, vec.elem_size);
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_raw_set_bytes(
    handle: usize,
    index: usize,
    src: usize,
    src_size: usize,
) -> u32 {
    let vec = handle as *mut DynVecRaw;
    if vec.is_null() || src == 0 {
        return 0;
    }
    let vec = unsafe { &mut *vec };
    if index >= vec.len || src_size != vec.elem_size {
        return 0;
    }
    let Some(offset) = index.checked_mul(vec.elem_size) else {
        return 0;
    };
    let dst = unsafe { vec.ptr.add(offset) as usize };
    unsafe {
        dyn_copy_bytes(dst, src, vec.elem_size);
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_vec_raw_pop_bytes(
    handle: usize,
    dst: usize,
    dst_size: usize,
) -> u32 {
    let vec = handle as *mut DynVecRaw;
    if vec.is_null() || dst == 0 {
        return 0;
    }
    let vec = unsafe { &mut *vec };
    if vec.len == 0 || dst_size != vec.elem_size {
        return 0;
    }
    vec.len -= 1;
    let Some(offset) = vec.len.checked_mul(vec.elem_size) else {
        return 0;
    };
    let src = unsafe { vec.ptr.add(offset) as usize };
    unsafe {
        dyn_copy_bytes(dst, src, vec.elem_size);
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_init(alloc: usize, elem_size: usize, elem_align: usize) -> usize {
    unsafe { __dyn_vec_raw_init(alloc, elem_size, elem_align) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_deinit(handle: usize) -> u32 {
    unsafe { __dyn_vec_raw_deinit(handle) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_len(handle: usize) -> usize {
    unsafe { __dyn_vec_raw_len(handle) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_cap(handle: usize) -> usize {
    unsafe { __dyn_vec_raw_cap(handle) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_push_u64(handle: usize, value: u64) -> u32 {
    unsafe { __dyn_vec_raw_push_u64(handle, value) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_get_u64(handle: usize, index: usize) -> u64 {
    unsafe { __dyn_vec_raw_get_u64(handle, index) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_set_u64(handle: usize, index: usize, value: u64) -> u32 {
    unsafe { __dyn_vec_raw_set_u64(handle, index, value) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_pop_u64(handle: usize) -> u64 {
    unsafe { __dyn_vec_raw_pop_u64(handle) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_clear(handle: usize) -> u32 {
    unsafe { __dyn_vec_raw_clear(handle) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_reserve(handle: usize, new_cap: usize) -> u32 {
    unsafe { __dyn_vec_raw_reserve(handle, new_cap) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_ptr(handle: usize, index: usize) -> usize {
    unsafe { __dyn_vec_raw_ptr(handle, index) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_push_bytes(handle: usize, src: usize, src_size: usize) -> u32 {
    unsafe { __dyn_vec_raw_push_bytes(handle, src, src_size) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_get_bytes(
    handle: usize,
    index: usize,
    dst: usize,
    dst_size: usize,
) -> u32 {
    unsafe { __dyn_vec_raw_get_bytes(handle, index, dst, dst_size) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_set_bytes(
    handle: usize,
    index: usize,
    src: usize,
    src_size: usize,
) -> u32 {
    unsafe { __dyn_vec_raw_set_bytes(handle, index, src, src_size) }
}

#[no_mangle]
pub unsafe extern "C" fn std_vec_pop_bytes(handle: usize, dst: usize, dst_size: usize) -> u32 {
    unsafe { __dyn_vec_raw_pop_bytes(handle, dst, dst_size) }
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_io_write_i32(value: i32, newline: u32) -> u32 {
    let fmt = if newline != 0 { FMT_I32_NL } else { FMT_I32 };
    let rc = unsafe { printf(fmt.as_ptr().cast::<c_char>(), value) };
    if rc >= 0 {
        1
    } else {
        0
    }
}

#[no_mangle]
pub unsafe extern "C" fn __dyn_io_write(cstr: usize, newline: u32) -> u32 {
    if cstr == 0 {
        return 0;
    }
    let fmt = if newline != 0 { FMT_STR_NL } else { FMT_STR };
    let rc = unsafe { printf(fmt.as_ptr().cast::<c_char>(), cstr as *const c_char) };
    if rc >= 0 {
        1
    } else {
        0
    }
}

#[no_mangle]
pub unsafe extern "C" fn std_io_print_i32(value: i32) -> u32 {
    unsafe { __dyn_io_write_i32(value, 0) }
}

#[no_mangle]
pub unsafe extern "C" fn std_io_println_i32(value: i32) -> u32 {
    unsafe { __dyn_io_write_i32(value, 1) }
}

#[no_mangle]
pub unsafe extern "C" fn std_io_print(cstr: usize) -> u32 {
    unsafe { __dyn_io_write(cstr, 0) }
}

#[no_mangle]
pub unsafe extern "C" fn std_io_println(cstr: usize) -> u32 {
    unsafe { __dyn_io_write(cstr, 1) }
}
