#![allow(non_snake_case)]

use std::ffi::{c_char, c_int, c_long, c_void, CStr};
use std::mem;
use std::ptr;

unsafe extern "C" {
    fn malloc(size: usize) -> *mut c_void;
    fn realloc(ptr: *mut c_void, size: usize) -> *mut c_void;
    fn free(ptr: *mut c_void);
    fn posix_memalign(memptr: *mut *mut c_void, align: usize, size: usize) -> c_int;
    fn printf(fmt: *const c_char, ...) -> c_int;
    fn snprintf(buf: *mut c_char, size: usize, fmt: *const c_char, ...) -> c_int;
    fn write(fd: c_int, buf: *const c_void, count: usize) -> isize;
    fn getenv(name: *const c_char) -> *mut c_char;
    fn getcwd(buf: *mut c_char, size: usize) -> *mut c_char;
    fn access(path: *const c_char, mode: c_int) -> c_int;
    fn opendir(path: *const c_char) -> *mut c_void;
    fn readdir(dir: *mut c_void) -> *mut DynDirent;
    fn closedir(dir: *mut c_void) -> c_int;
    fn fopen(path: *const c_char, mode: *const c_char) -> *mut c_void;
    fn fclose(file: *mut c_void) -> c_int;
    fn fread(ptr: *mut c_void, size: usize, count: usize, file: *mut c_void) -> usize;
    fn fwrite(ptr: *const c_void, size: usize, count: usize, file: *mut c_void) -> usize;
    fn fseek(file: *mut c_void, offset: c_long, whence: c_int) -> c_int;
    fn ftell(file: *mut c_void) -> c_long;
    fn rewind(file: *mut c_void);
    fn mkdir(path: *const c_char, mode: u32) -> c_int;
}

const DYN_ALLOCATOR_TAG_MASK: usize = 0b11;
const DYN_ALLOCATOR_C: usize = 0b01;
const DYN_ALLOCATOR_FAILING: usize = 0b10;
const DYN_ALLOCATOR_ARENA: usize = 0b11;

const FMT_I32: &[u8] = b"%d\0";
const FMT_I32_NL: &[u8] = b"%d\n\0";
const FMT_U64: &[u8] = b"%llu\0";
const FMT_USIZE: &[u8] = b"%zu\0";
const F_OK: c_int = 0;
const SEEK_END: c_int = 2;

const FILE_MODE_READ: &[u8] = b"rb\0";
const FILE_MODE_WRITE: &[u8] = b"wb\0";

const CMDLINE_PATH: &[u8] = b"/proc/self/cmdline\0";
const DT_DIR: u8 = 4;

static mut DYN_FAIL_AFTER: usize = usize::MAX;

#[repr(C)]
struct DynArenaAllocator {
    backing: usize,
    ptr: *mut u8,
    cap: usize,
    used: usize,
}

#[repr(C)]
struct DynArenaHandleNode {
    handle: usize,
    next: *mut DynArenaHandleNode,
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

#[repr(C)]
struct DynDirent {
    d_ino: u64,
    d_off: i64,
    d_reclen: u16,
    d_type: u8,
    d_name: [c_char; 256],
}

#[repr(C)]
struct DynBytesMeta {
    ptr: usize,
    len: usize,
    next: *mut DynBytesMeta,
}

static mut DYN_BYTES_META_HEAD: *mut DynBytesMeta = ptr::null_mut();
static mut DYN_ARENA_HANDLES_HEAD: *mut DynArenaHandleNode = ptr::null_mut();

#[inline]
fn dyn_is_power_of_two(value: usize) -> bool {
    value != 0 && (value & (value - 1)) == 0
}

#[inline]
fn dyn_is_arena_allocator(alloc: usize) -> bool {
    if (alloc & DYN_ALLOCATOR_TAG_MASK) != DYN_ALLOCATOR_ARENA
        || (alloc & !DYN_ALLOCATOR_TAG_MASK) == 0
    {
        return false;
    }
    unsafe { dyn_is_registered_arena_handle(alloc) }
}

#[inline]
fn dyn_is_known_builtin_allocator(alloc: usize) -> bool {
    alloc == DYN_ALLOCATOR_C || alloc == DYN_ALLOCATOR_FAILING
}

#[inline]
fn dyn_arena_ptr_from_handle(alloc: usize) -> *mut DynArenaAllocator {
    (alloc & !DYN_ALLOCATOR_TAG_MASK) as *mut DynArenaAllocator
}

#[inline]
fn dyn_arena_handle_from_ptr(arena: *mut DynArenaAllocator) -> usize {
    (arena as usize) | DYN_ALLOCATOR_ARENA
}

#[inline]
unsafe fn dyn_is_registered_arena_handle(handle: usize) -> bool {
    let mut node = unsafe { DYN_ARENA_HANDLES_HEAD };
    while !node.is_null() {
        if unsafe { (*node).handle } == handle {
            return true;
        }
        node = unsafe { (*node).next };
    }
    false
}

#[inline]
unsafe fn dyn_register_arena_handle(handle: usize) -> bool {
    let node = unsafe { dyn_alloc_struct::<DynArenaHandleNode>() };
    if node.is_null() {
        return false;
    }
    unsafe {
        (*node).handle = handle;
        (*node).next = DYN_ARENA_HANDLES_HEAD;
        DYN_ARENA_HANDLES_HEAD = node;
    }
    true
}

#[inline]
unsafe fn dyn_unregister_arena_handle(handle: usize) -> bool {
    let mut prev: *mut DynArenaHandleNode = ptr::null_mut();
    let mut node = unsafe { DYN_ARENA_HANDLES_HEAD };
    while !node.is_null() {
        let next = unsafe { (*node).next };
        if unsafe { (*node).handle } == handle {
            unsafe {
                if prev.is_null() {
                    DYN_ARENA_HANDLES_HEAD = next;
                } else {
                    (*prev).next = next;
                }
                free(node as *mut c_void);
            }
            return true;
        }
        prev = node;
        node = next;
    }
    false
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

#[inline]
unsafe fn dyn_bytes_meta_insert(ptr_value: usize, len: usize) -> bool {
    if ptr_value == 0 {
        return false;
    }

    let mut node = unsafe { DYN_BYTES_META_HEAD };
    while !node.is_null() {
        if unsafe { (*node).ptr } == ptr_value {
            unsafe {
                (*node).len = len;
            }
            return true;
        }
        node = unsafe { (*node).next };
    }

    let size = mem::size_of::<DynBytesMeta>();
    let align = mem::align_of::<DynBytesMeta>();
    let entry = unsafe { dynrt_alloc(size.max(1), align.max(1)) } as *mut DynBytesMeta;
    if entry.is_null() {
        return false;
    }

    unsafe {
        (*entry).ptr = ptr_value;
        (*entry).len = len;
        (*entry).next = DYN_BYTES_META_HEAD;
        DYN_BYTES_META_HEAD = entry;
    }
    true
}

#[inline]
unsafe fn dyn_bytes_meta_remove(ptr_value: usize) {
    if ptr_value == 0 {
        return;
    }

    let mut prev: *mut DynBytesMeta = ptr::null_mut();
    let mut node = unsafe { DYN_BYTES_META_HEAD };
    while !node.is_null() {
        let next = unsafe { (*node).next };
        if unsafe { (*node).ptr } == ptr_value {
            unsafe {
                if prev.is_null() {
                    DYN_BYTES_META_HEAD = next;
                } else {
                    (*prev).next = next;
                }
                dynrt_free(
                    node as usize,
                    mem::size_of::<DynBytesMeta>().max(1),
                    mem::align_of::<DynBytesMeta>().max(1),
                );
            }
            return;
        }
        prev = node;
        node = next;
    }
}

#[inline]
unsafe fn dyn_free_registered_bytes(ptr_value: usize, len: usize) {
    if ptr_value == 0 {
        return;
    }
    unsafe {
        dyn_bytes_meta_remove(ptr_value);
        dynrt_free(ptr_value, len.saturating_add(1), 1);
    }
}

#[inline]
unsafe fn dyn_alloc_bytes(len: usize) -> usize {
    let Some(size) = len.checked_add(1) else {
        return 0;
    };
    let out = unsafe { dynrt_alloc(size, 1) };
    if out == 0 {
        return 0;
    }

    unsafe {
        *((out as *mut u8).add(len)) = 0;
    }
    if unsafe { !dyn_bytes_meta_insert(out, len) } {
        unsafe {
            dynrt_free(out, size, 1);
        }
        return 0;
    }
    out
}

#[inline]
unsafe fn dyn_alloc_bytes_range(ptr_value: *const u8, len: usize) -> usize {
    let out = unsafe { dyn_alloc_bytes(len) };
    if out == 0 {
        return 0;
    }

    unsafe {
        if len != 0 {
            ptr::copy_nonoverlapping(ptr_value, out as *mut u8, len);
        }
    }
    out
}

#[inline]
unsafe fn dyn_alloc_bytes_slice(bytes: &[u8]) -> usize {
    unsafe { dyn_alloc_bytes_range(bytes.as_ptr(), bytes.len()) }
}

#[inline]
fn dyn_valid_ptr_len(ptr_value: usize, len: usize) -> bool {
    !(ptr_value == 0 && len != 0)
}

#[inline]
unsafe fn dyn_set_out_len(out_len_ptr: usize, len: usize) {
    if out_len_ptr != 0 {
        unsafe {
            *(out_len_ptr as *mut usize) = len;
        }
    }
}

#[inline]
unsafe fn dyn_temp_c_string_parts(ptr_value: usize, len: usize) -> Option<(usize, usize)> {
    if !dyn_valid_ptr_len(ptr_value, len) {
        return None;
    }
    if len != 0 {
        let mut index = 0usize;
        while index < len {
            if unsafe { *((ptr_value as *const u8).add(index)) } == 0 {
                return None;
            }
            index += 1;
        }
    }

    let Some(size) = len.checked_add(1) else {
        return None;
    };
    let out = unsafe { dynrt_alloc(size, 1) };
    if out == 0 {
        return None;
    }
    unsafe {
        if len != 0 {
            ptr::copy_nonoverlapping(ptr_value as *const u8, out as *mut u8, len);
        }
        *((out as *mut u8).add(len)) = 0;
    }
    Some((out, size))
}

unsafe fn dyn_read_file_all(path_ptr: *const c_char, out_len: &mut usize) -> usize {
    *out_len = 0;
    let file = unsafe { fopen(path_ptr, FILE_MODE_READ.as_ptr().cast::<c_char>()) };
    if file.is_null() {
        return 0;
    }

    if unsafe { fseek(file, 0, SEEK_END) } != 0 {
        unsafe {
            fclose(file);
        }
        return 0;
    }

    let size = unsafe { ftell(file) };
    if size < 0 {
        unsafe {
            fclose(file);
        }
        return 0;
    }
    unsafe {
        rewind(file);
    }

    let size = size as usize;
    let out = unsafe { dyn_alloc_bytes(size) };
    if out == 0 {
        unsafe {
            fclose(file);
        }
        return 0;
    }

    let read = unsafe { fread(out as *mut c_void, 1, size, file) };
    unsafe {
        fclose(file);
    }
    if read != size {
        unsafe {
            dyn_free_registered_bytes(out, size);
        }
        return 0;
    }

    *out_len = size;
    out
}

unsafe fn dyn_write_file_all(path_ptr: *const c_char, data_ptr: *const u8, len: usize) -> u32 {
    let file = unsafe { fopen(path_ptr, FILE_MODE_WRITE.as_ptr().cast::<c_char>()) };
    if file.is_null() {
        return 0;
    }
    let written = unsafe { fwrite(data_ptr as *const c_void, 1, len, file) };
    unsafe {
        fclose(file);
    }
    if written == len {
        1
    } else {
        0
    }
}

unsafe fn dyn_trim_trailing_slashes(ptr_value: *const u8, len: usize) -> usize {
    let mut end = len;
    while end > 1 {
        if unsafe { *ptr_value.add(end - 1) } != b'/' {
            break;
        }
        end -= 1;
    }
    end
}

unsafe fn dyn_buf_grow(buf: &mut usize, cap: &mut usize, required: usize) -> bool {
    if required <= *cap {
        return true;
    }

    let mut next_cap = if *cap == 0 { 64 } else { *cap };
    while next_cap < required {
        if next_cap > usize::MAX / 2 {
            next_cap = required;
            break;
        }
        next_cap *= 2;
    }

    let next = if *buf == 0 {
        unsafe { dynrt_alloc(next_cap, 1) }
    } else {
        unsafe { dynrt_realloc(*buf, *cap, next_cap, 1) }
    };
    if next == 0 {
        return false;
    }
    *buf = next;
    *cap = next_cap;
    true
}

unsafe fn dyn_buf_push_byte(buf: &mut usize, cap: &mut usize, len: &mut usize, byte: u8) -> bool {
    let Some(required) = (*len).checked_add(1) else {
        return false;
    };
    if unsafe { !dyn_buf_grow(buf, cap, required) } {
        return false;
    }
    unsafe {
        *((*buf as *mut u8).add(*len)) = byte;
    }
    *len = required;
    true
}

unsafe fn dyn_buf_push_range(
    buf: &mut usize,
    cap: &mut usize,
    len: &mut usize,
    src: *const u8,
    src_len: usize,
) -> bool {
    let Some(required) = (*len).checked_add(src_len) else {
        return false;
    };
    if unsafe { !dyn_buf_grow(buf, cap, required) } {
        return false;
    }
    if src_len != 0 {
        unsafe {
            ptr::copy_nonoverlapping(src, (*buf as *mut u8).add(*len), src_len);
        }
    }
    *len = required;
    true
}

unsafe extern "C" fn dyn_identity_i32(value: i32) -> i32 {
    value
}

#[inline]
fn dyn_allocator_should_fail(alloc: usize) -> bool {
    if (alloc & DYN_ALLOCATOR_TAG_MASK) != DYN_ALLOCATOR_FAILING {
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
            dynrt_realloc_with(arena.backing, arena.ptr as usize, arena.cap, next_cap, 16)
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
    let next = unsafe { dynrt_realloc_with(vec.alloc, vec.ptr as usize, old_size, new_size, 4) };
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
        dynrt_realloc_with(
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
pub unsafe extern "C" fn dynrt_alloc(size: usize, align: usize) -> usize {
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
pub unsafe extern "C" fn dynrt_realloc(
    ptr_value: usize,
    old_size: usize,
    new_size: usize,
    align: usize,
) -> usize {
    if !dyn_is_power_of_two(align) {
        return 0;
    }
    if ptr_value == 0 {
        return unsafe { dynrt_alloc(new_size, align) };
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

    let next = unsafe { dynrt_alloc(new_size, align) };
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
pub unsafe extern "C" fn dynrt_free(ptr_value: usize, _size: usize, align: usize) -> u32 {
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
pub extern "C" fn dynrt_c_allocator() -> usize {
    DYN_ALLOCATOR_C
}

#[no_mangle]
pub extern "C" fn dynrt_test_failing_allocator() -> usize {
    DYN_ALLOCATOR_FAILING
}

#[no_mangle]
pub extern "C" fn dynrt_test_identity_i32_fn() -> usize {
    dyn_identity_i32 as *const () as usize
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_test_set_fail_after(remaining_successes: usize) -> u32 {
    unsafe {
        DYN_FAIL_AFTER = remaining_successes;
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_arena_allocator(backing: usize) -> usize {
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
    let handle = dyn_arena_handle_from_ptr(arena);
    if unsafe { !dyn_register_arena_handle(handle) } {
        unsafe {
            free(arena as *mut c_void);
        }
        return 0;
    }
    handle
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_arena_reset(arena_handle: usize) -> u32 {
    if !dyn_is_arena_allocator(arena_handle) {
        return 0;
    }
    let arena = dyn_arena_ptr_from_handle(arena_handle);
    if arena.is_null() {
        return 0;
    }
    unsafe {
        (*arena).used = 0;
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_arena_deinit(arena_handle: usize) -> u32 {
    if !dyn_is_arena_allocator(arena_handle) {
        return 1;
    }
    unsafe {
        dyn_unregister_arena_handle(arena_handle);
    }
    let arena = dyn_arena_ptr_from_handle(arena_handle);
    if arena.is_null() {
        return 1;
    }

    let (ptr_value, cap, backing) =
        unsafe { ((*arena).ptr as usize, (*arena).cap, (*arena).backing) };
    if ptr_value != 0 && cap != 0 && unsafe { dynrt_free_with(backing, ptr_value, cap, 16) } == 0 {
        return 0;
    }

    unsafe {
        free(arena as *mut c_void);
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_alloc_with(alloc: usize, size: usize, align: usize) -> usize {
    if dyn_is_arena_allocator(alloc) {
        let arena = dyn_arena_ptr_from_handle(alloc);
        if arena.is_null() {
            return 0;
        }
        return unsafe { dyn_arena_alloc(&mut *arena, size, align) };
    }
    if !dyn_is_known_builtin_allocator(alloc) {
        return 0;
    }
    if dyn_allocator_should_fail(alloc) {
        return 0;
    }
    unsafe { dynrt_alloc(size, align) }
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_realloc_with(
    alloc: usize,
    ptr_value: usize,
    old_size: usize,
    new_size: usize,
    align: usize,
) -> usize {
    if dyn_is_arena_allocator(alloc) {
        let arena = dyn_arena_ptr_from_handle(alloc);
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

    if !dyn_is_known_builtin_allocator(alloc) {
        return 0;
    }
    if dyn_allocator_should_fail(alloc) {
        return 0;
    }
    unsafe { dynrt_realloc(ptr_value, old_size, new_size, align) }
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_free_with(
    alloc: usize,
    ptr_value: usize,
    size: usize,
    align: usize,
) -> u32 {
    if dyn_is_arena_allocator(alloc) {
        let _ = (ptr_value, size, align);
        return 1;
    }
    if !dyn_is_known_builtin_allocator(alloc) {
        return 0;
    }
    unsafe { dynrt_free(ptr_value, size, align) }
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_mem_copy(dst: usize, src: usize, size: usize) -> u32 {
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
pub unsafe extern "C" fn dynrt_mem_move(dst: usize, src: usize, size: usize) -> u32 {
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
pub unsafe extern "C" fn dynrt_mem_set(dst: usize, byte_value: u32, size: usize) -> u32 {
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
pub unsafe extern "C" fn dynrt_mem_eq(lhs: usize, rhs: usize, size: usize) -> u32 {
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

include!("runtime_support/vec.rs");

include!("runtime_support/io.rs");

include!("runtime_support/system.rs");
