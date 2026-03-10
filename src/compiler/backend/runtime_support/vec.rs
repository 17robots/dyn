#[no_mangle]
pub unsafe extern "C" fn dynrt_vec_i32_init(alloc: usize) -> usize {
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
pub unsafe extern "C" fn dynrt_vec_i32_deinit(handle: usize) -> u32 {
    let vec = handle as *mut DynVecI32;
    if vec.is_null() {
        return 1;
    }
    let (ptr_value, cap, alloc) = unsafe { ((*vec).ptr as usize, (*vec).cap, (*vec).alloc) };
    if ptr_value != 0 {
        let size = cap * mem::size_of::<i32>();
        if unsafe { dynrt_free_with(alloc, ptr_value, size, mem::size_of::<i32>()) } == 0 {
            return 0;
        }
    }
    unsafe {
        free(vec as *mut c_void);
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_vec_i32_len(handle: usize) -> usize {
    let vec = handle as *mut DynVecI32;
    if vec.is_null() {
        0
    } else {
        unsafe { (*vec).len }
    }
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_vec_i32_cap(handle: usize) -> usize {
    let vec = handle as *mut DynVecI32;
    if vec.is_null() {
        0
    } else {
        unsafe { (*vec).cap }
    }
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_vec_i32_push(handle: usize, value: i32) -> u32 {
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
pub unsafe extern "C" fn dynrt_vec_i32_get(handle: usize, index: usize) -> i32 {
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
pub unsafe extern "C" fn dynrt_vec_i32_set(handle: usize, index: usize, value: i32) -> u32 {
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
pub unsafe extern "C" fn dynrt_vec_i32_pop(handle: usize) -> i32 {
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
pub unsafe extern "C" fn dynrt_vec_i32_clear(handle: usize) -> u32 {
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
pub unsafe extern "C" fn dynrt_vec_i32_reserve(handle: usize, new_cap: usize) -> u32 {
    let vec = handle as *mut DynVecI32;
    if vec.is_null() {
        return 0;
    }
    unsafe { dyn_vec_i32_reserve_exact(&mut *vec, new_cap) }
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_vec_raw_init(
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
pub unsafe extern "C" fn dynrt_vec_raw_deinit(handle: usize) -> u32 {
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
        if unsafe { dynrt_free_with(alloc, ptr_value, size, elem_align) } == 0 {
            return 0;
        }
    }
    unsafe {
        free(vec as *mut c_void);
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_vec_raw_len(handle: usize) -> usize {
    let vec = handle as *mut DynVecRaw;
    if vec.is_null() {
        0
    } else {
        unsafe { (*vec).len }
    }
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_vec_raw_cap(handle: usize) -> usize {
    let vec = handle as *mut DynVecRaw;
    if vec.is_null() {
        0
    } else {
        unsafe { (*vec).cap }
    }
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_vec_raw_push_u64(handle: usize, value: u64) -> u32 {
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
pub unsafe extern "C" fn dynrt_vec_raw_get_u64(handle: usize, index: usize) -> u64 {
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
pub unsafe extern "C" fn dynrt_vec_raw_set_u64(handle: usize, index: usize, value: u64) -> u32 {
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
pub unsafe extern "C" fn dynrt_vec_raw_pop_u64(handle: usize) -> u64 {
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
pub unsafe extern "C" fn dynrt_vec_raw_clear(handle: usize) -> u32 {
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
pub unsafe extern "C" fn dynrt_vec_raw_reserve(handle: usize, new_cap: usize) -> u32 {
    let vec = handle as *mut DynVecRaw;
    if vec.is_null() {
        return 0;
    }
    unsafe { dyn_vec_raw_reserve_exact(&mut *vec, new_cap) }
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_vec_raw_ptr(handle: usize, index: usize) -> usize {
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
pub unsafe extern "C" fn dynrt_vec_raw_push_bytes(
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
pub unsafe extern "C" fn dynrt_vec_raw_get_bytes(
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
pub unsafe extern "C" fn dynrt_vec_raw_set_bytes(
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
pub unsafe extern "C" fn dynrt_vec_raw_pop_bytes(
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
