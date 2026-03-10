#[no_mangle]
pub unsafe extern "C" fn dynrt_io_write_i32(value: i32, newline: u32) -> u32 {
    let fmt = if newline != 0 { FMT_I32_NL } else { FMT_I32 };
    let rc = unsafe { printf(fmt.as_ptr().cast::<c_char>(), value) };
    if rc >= 0 {
        1
    } else {
        0
    }
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_io_write(ptr_value: usize, len: usize, newline: u32) -> u32 {
    if !dyn_valid_ptr_len(ptr_value, len) {
        return 0;
    }

    let bytes_ptr = ptr_value as *const u8;

    if len != 0 {
        let wrote = unsafe { write(1, bytes_ptr.cast::<c_void>(), len) };
        if wrote < 0 || wrote as usize != len {
            return 0;
        }
    }

    if newline != 0 {
        let byte = [b'\n'];
        let wrote = unsafe { write(1, byte.as_ptr().cast::<c_void>(), 1) };
        if wrote != 1 {
            return 0;
        }
    }

    1
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_bytes_len(ptr_value: usize, len: usize) -> usize {
    if !dyn_valid_ptr_len(ptr_value, len) {
        return 0;
    }
    len
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_bytes_from_ptr_len(
    src: usize,
    len: usize,
    out_len_ptr: usize,
) -> usize {
    unsafe {
        dyn_set_out_len(out_len_ptr, 0);
    }
    if !dyn_valid_ptr_len(src, len) {
        return 0;
    }
    let out = unsafe { dyn_alloc_bytes_range(src as *const u8, len) };
    if out != 0 {
        unsafe {
            dyn_set_out_len(out_len_ptr, len);
        }
    }
    out
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_bytes_eq(
    lhs_ptr: usize,
    lhs_len: usize,
    rhs_ptr: usize,
    rhs_len: usize,
) -> u32 {
    if !dyn_valid_ptr_len(lhs_ptr, lhs_len) || !dyn_valid_ptr_len(rhs_ptr, rhs_len) {
        return 0;
    }
    if lhs_len != rhs_len {
        return 0;
    }
    if lhs_len == 0 {
        return 1;
    }

    let lhs = unsafe { std::slice::from_raw_parts(lhs_ptr as *const u8, lhs_len) };
    let rhs = unsafe { std::slice::from_raw_parts(rhs_ptr as *const u8, rhs_len) };
    if lhs == rhs {
        1
    } else {
        0
    }
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_bytes_starts_with(
    value_ptr: usize,
    value_len: usize,
    prefix_ptr: usize,
    prefix_len: usize,
) -> u32 {
    if !dyn_valid_ptr_len(value_ptr, value_len) || !dyn_valid_ptr_len(prefix_ptr, prefix_len) {
        return 0;
    }

    let value_bytes = unsafe { std::slice::from_raw_parts(value_ptr as *const u8, value_len) };
    let prefix_bytes = unsafe { std::slice::from_raw_parts(prefix_ptr as *const u8, prefix_len) };
    if value_bytes.starts_with(prefix_bytes) {
        1
    } else {
        0
    }
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_bytes_ends_with(
    value_ptr: usize,
    value_len: usize,
    suffix_ptr: usize,
    suffix_len: usize,
) -> u32 {
    if !dyn_valid_ptr_len(value_ptr, value_len) || !dyn_valid_ptr_len(suffix_ptr, suffix_len) {
        return 0;
    }

    let value_bytes = unsafe { std::slice::from_raw_parts(value_ptr as *const u8, value_len) };
    let suffix_bytes = unsafe { std::slice::from_raw_parts(suffix_ptr as *const u8, suffix_len) };
    if value_bytes.ends_with(suffix_bytes) {
        1
    } else {
        0
    }
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_bytes_index_of(
    value_ptr: usize,
    value_len: usize,
    needle_ptr: usize,
    needle_len: usize,
) -> isize {
    if !dyn_valid_ptr_len(value_ptr, value_len) || !dyn_valid_ptr_len(needle_ptr, needle_len) {
        return -1;
    }

    let value_bytes = unsafe { std::slice::from_raw_parts(value_ptr as *const u8, value_len) };
    let needle_bytes = unsafe { std::slice::from_raw_parts(needle_ptr as *const u8, needle_len) };
    if needle_bytes.is_empty() {
        return 0;
    }
    if needle_bytes.len() > value_bytes.len() {
        return -1;
    }
    match value_bytes
        .windows(needle_bytes.len())
        .position(|window| window == needle_bytes)
    {
        Some(index) => index as isize,
        None => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_bytes_clone(
    ptr_value: usize,
    len: usize,
    out_len_ptr: usize,
) -> usize {
    unsafe {
        dyn_set_out_len(out_len_ptr, 0);
    }
    if !dyn_valid_ptr_len(ptr_value, len) {
        return 0;
    }
    let out = unsafe { dyn_alloc_bytes_range(ptr_value as *const u8, len) };
    if out != 0 {
        unsafe {
            dyn_set_out_len(out_len_ptr, len);
        }
    }
    out
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_bytes_slice(
    ptr_value: usize,
    len: usize,
    start: usize,
    end: usize,
    out_len_ptr: usize,
) -> usize {
    unsafe {
        dyn_set_out_len(out_len_ptr, 0);
    }
    if !dyn_valid_ptr_len(ptr_value, len) {
        return 0;
    }
    if start > end || end > len {
        return 0;
    }
    let out_len = end - start;
    let out = unsafe { dyn_alloc_bytes_range((ptr_value as *const u8).add(start), out_len) };
    if out != 0 {
        unsafe {
            dyn_set_out_len(out_len_ptr, out_len);
        }
    }
    out
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_bytes_concat2(
    lhs_ptr: usize,
    lhs_len: usize,
    rhs_ptr: usize,
    rhs_len: usize,
    out_len_ptr: usize,
) -> usize {
    unsafe {
        dyn_set_out_len(out_len_ptr, 0);
    }
    if !dyn_valid_ptr_len(lhs_ptr, lhs_len) || !dyn_valid_ptr_len(rhs_ptr, rhs_len) {
        return 0;
    }

    let Some(total) = lhs_len.checked_add(rhs_len) else {
        return 0;
    };
    let out = unsafe { dyn_alloc_bytes(total) };
    if out == 0 {
        return 0;
    }
    unsafe {
        if lhs_len != 0 {
            ptr::copy_nonoverlapping(lhs_ptr as *const u8, out as *mut u8, lhs_len);
        }
        if rhs_len != 0 {
            ptr::copy_nonoverlapping(rhs_ptr as *const u8, (out as *mut u8).add(lhs_len), rhs_len);
        }
    }
    unsafe {
        dyn_set_out_len(out_len_ptr, total);
    }
    out
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_bytes_concat3(
    a_ptr: usize,
    a_len: usize,
    b_ptr: usize,
    b_len: usize,
    c_ptr: usize,
    c_len: usize,
    out_len_ptr: usize,
) -> usize {
    unsafe {
        dyn_set_out_len(out_len_ptr, 0);
    }
    if !dyn_valid_ptr_len(a_ptr, a_len)
        || !dyn_valid_ptr_len(b_ptr, b_len)
        || !dyn_valid_ptr_len(c_ptr, c_len)
    {
        return 0;
    }

    let Some(ab) = a_len.checked_add(b_len) else {
        return 0;
    };
    let Some(total) = ab.checked_add(c_len) else {
        return 0;
    };

    let out = unsafe { dyn_alloc_bytes(total) };
    if out == 0 {
        return 0;
    }
    unsafe {
        if a_len != 0 {
            ptr::copy_nonoverlapping(a_ptr as *const u8, out as *mut u8, a_len);
        }
        if b_len != 0 {
            ptr::copy_nonoverlapping(b_ptr as *const u8, (out as *mut u8).add(a_len), b_len);
        }
        if c_len != 0 {
            ptr::copy_nonoverlapping(
                c_ptr as *const u8,
                (out as *mut u8).add(a_len + b_len),
                c_len,
            );
        }
    }
    unsafe {
        dyn_set_out_len(out_len_ptr, total);
    }
    out
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_fmt_i32(value: i32, out_len_ptr: usize) -> usize {
    unsafe {
        dyn_set_out_len(out_len_ptr, 0);
    }
    let mut buffer = [0u8; 64];
    let written = unsafe {
        snprintf(
            buffer.as_mut_ptr().cast::<c_char>(),
            buffer.len(),
            FMT_I32.as_ptr().cast::<c_char>(),
            value,
        )
    };
    if written < 0 {
        return 0;
    }
    let len = written as usize;
    if len >= buffer.len() {
        return 0;
    }
    let out = unsafe { dyn_alloc_bytes_range(buffer.as_ptr(), len) };
    if out != 0 {
        unsafe {
            dyn_set_out_len(out_len_ptr, len);
        }
    }
    out
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_fmt_u64(value: u64, out_len_ptr: usize) -> usize {
    unsafe {
        dyn_set_out_len(out_len_ptr, 0);
    }
    let mut buffer = [0u8; 64];
    let written = unsafe {
        snprintf(
            buffer.as_mut_ptr().cast::<c_char>(),
            buffer.len(),
            FMT_U64.as_ptr().cast::<c_char>(),
            value,
        )
    };
    if written < 0 {
        return 0;
    }
    let len = written as usize;
    if len >= buffer.len() {
        return 0;
    }
    let out = unsafe { dyn_alloc_bytes_range(buffer.as_ptr(), len) };
    if out != 0 {
        unsafe {
            dyn_set_out_len(out_len_ptr, len);
        }
    }
    out
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_fmt_usize(value: usize, out_len_ptr: usize) -> usize {
    unsafe {
        dyn_set_out_len(out_len_ptr, 0);
    }
    let mut buffer = [0u8; 64];
    let written = unsafe {
        snprintf(
            buffer.as_mut_ptr().cast::<c_char>(),
            buffer.len(),
            FMT_USIZE.as_ptr().cast::<c_char>(),
            value,
        )
    };
    if written < 0 {
        return 0;
    }
    let len = written as usize;
    if len >= buffer.len() {
        return 0;
    }
    let out = unsafe { dyn_alloc_bytes_range(buffer.as_ptr(), len) };
    if out != 0 {
        unsafe {
            dyn_set_out_len(out_len_ptr, len);
        }
    }
    out
}
