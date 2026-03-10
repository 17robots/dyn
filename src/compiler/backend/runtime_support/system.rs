#[no_mangle]
pub unsafe extern "C" fn dynrt_env_argc() -> usize {
    let mut len = 0usize;
    let buffer = unsafe { dyn_read_file_all(CMDLINE_PATH.as_ptr().cast::<c_char>(), &mut len) };
    if buffer == 0 {
        return 0;
    }

    let mut count = 0usize;
    let mut index = 0usize;
    let bytes_ptr = buffer as *const u8;
    while index < len {
        let current = unsafe { *bytes_ptr.add(index) };
        let previous = if index == 0 {
            0
        } else {
            unsafe { *bytes_ptr.add(index - 1) }
        };
        if current != 0 && (index == 0 || previous == 0) {
            count += 1;
        }
        index += 1;
    }

    unsafe {
        dyn_free_registered_bytes(buffer, len);
    }

    count
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_env_argv(index: usize, out_len_ptr: usize) -> usize {
    unsafe {
        dyn_set_out_len(out_len_ptr, 0);
    }
    let mut len = 0usize;
    let buffer = unsafe { dyn_read_file_all(CMDLINE_PATH.as_ptr().cast::<c_char>(), &mut len) };
    if buffer == 0 {
        return 0;
    }

    let mut arg_index = 0usize;
    let mut start = 0usize;
    let mut cursor = 0usize;
    let mut out = 0usize;
    let bytes_ptr = buffer as *const u8;
    while cursor <= len {
        let boundary = if cursor == len {
            true
        } else {
            unsafe { *bytes_ptr.add(cursor) == 0 }
        };
        if boundary {
            if cursor > start {
                if arg_index == index {
                    let arg_len = cursor - start;
                    out = unsafe { dyn_alloc_bytes_range(bytes_ptr.add(start), arg_len) };
                    if out != 0 {
                        unsafe {
                            dyn_set_out_len(out_len_ptr, arg_len);
                        }
                    }
                    break;
                }
                arg_index += 1;
            }
            start = cursor + 1;
        }
        cursor += 1;
    }

    unsafe {
        dyn_free_registered_bytes(buffer, len);
    }

    out
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_env_get(
    name_ptr: usize,
    name_len: usize,
    out_len_ptr: usize,
) -> usize {
    unsafe {
        dyn_set_out_len(out_len_ptr, 0);
    }
    let Some((name_cstr, name_size)) = (unsafe { dyn_temp_c_string_parts(name_ptr, name_len) })
    else {
        return 0;
    };

    let value = unsafe { getenv(name_cstr as *const c_char) };
    unsafe {
        dynrt_free(name_cstr, name_size, 1);
    }
    if value.is_null() {
        return 0;
    }
    let bytes = unsafe { CStr::from_ptr(value).to_bytes() };
    let out = unsafe { dyn_alloc_bytes_slice(bytes) };
    if out != 0 {
        unsafe {
            dyn_set_out_len(out_len_ptr, bytes.len());
        }
    }
    out
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_env_cwd(out_len_ptr: usize) -> usize {
    unsafe {
        dyn_set_out_len(out_len_ptr, 0);
    }
    let mut buffer = [0u8; 4096];
    let cwd = unsafe { getcwd(buffer.as_mut_ptr().cast::<c_char>(), buffer.len()) };
    if cwd.is_null() {
        return 0;
    }
    let bytes = unsafe { CStr::from_ptr(cwd).to_bytes() };
    let out = unsafe { dyn_alloc_bytes_slice(bytes) };
    if out != 0 {
        unsafe {
            dyn_set_out_len(out_len_ptr, bytes.len());
        }
    }
    out
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_fs_exists(path_ptr: usize, path_len: usize) -> u32 {
    let Some((path_cstr, path_size)) = (unsafe { dyn_temp_c_string_parts(path_ptr, path_len) })
    else {
        return 0;
    };
    let ok = if unsafe { access(path_cstr as *const c_char, F_OK) } == 0 {
        1
    } else {
        0
    };
    unsafe {
        dynrt_free(path_cstr, path_size, 1);
    }
    ok
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_fs_is_dir(path_ptr: usize, path_len: usize) -> u32 {
    let Some((path_cstr, path_size)) = (unsafe { dyn_temp_c_string_parts(path_ptr, path_len) })
    else {
        return 0;
    };
    let dir = unsafe { opendir(path_cstr as *const c_char) };
    unsafe {
        dynrt_free(path_cstr, path_size, 1);
    }
    if dir.is_null() {
        return 0;
    }
    unsafe {
        closedir(dir);
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_fs_read_all(
    path_ptr: usize,
    path_len: usize,
    out_len_ptr: usize,
) -> usize {
    unsafe {
        dyn_set_out_len(out_len_ptr, 0);
    }
    let Some((path_cstr, path_size)) = (unsafe { dyn_temp_c_string_parts(path_ptr, path_len) })
    else {
        return 0;
    };
    let mut len = 0usize;
    let out = unsafe { dyn_read_file_all(path_cstr as *const c_char, &mut len) };
    unsafe {
        dynrt_free(path_cstr, path_size, 1);
    }
    if out != 0 {
        unsafe {
            dyn_set_out_len(out_len_ptr, len);
        }
    }
    out
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_fs_write_all(
    path_ptr: usize,
    path_len: usize,
    data_ptr: usize,
    data_len: usize,
) -> u32 {
    let Some((path_cstr, path_size)) = (unsafe { dyn_temp_c_string_parts(path_ptr, path_len) })
    else {
        return 0;
    };
    if !dyn_valid_ptr_len(data_ptr, data_len) {
        unsafe {
            dynrt_free(path_cstr, path_size, 1);
        }
        return 0;
    }
    let ok =
        unsafe { dyn_write_file_all(path_cstr as *const c_char, data_ptr as *const u8, data_len) };
    unsafe {
        dynrt_free(path_cstr, path_size, 1);
    }
    ok
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_fs_mkdir_all(path_ptr: usize, path_len: usize) -> u32 {
    if !dyn_valid_ptr_len(path_ptr, path_len) {
        return 0;
    }
    if path_len == 0 {
        return 0;
    }

    let Some((tmp, tmp_size)) = (unsafe { dyn_temp_c_string_parts(path_ptr, path_len) }) else {
        return 0;
    };

    let mut ok = 1u32;
    let len = path_len;
    let buf = tmp as *mut u8;
    let mut index = if unsafe { *buf } == b'/' { 1 } else { 0 };

    while index <= len {
        let current = unsafe { *buf.add(index) };
        if current == b'/' || current == 0 {
            unsafe {
                *buf.add(index) = 0;
            }
            if unsafe { *buf } != 0 && unsafe { access(tmp as *const c_char, F_OK) } != 0 {
                if unsafe { mkdir(tmp as *const c_char, 0o755) } != 0 {
                    ok = 0;
                    unsafe {
                        *buf.add(index) = current;
                    }
                    break;
                }
            }
            unsafe {
                *buf.add(index) = current;
            }
        }
        index += 1;
    }

    unsafe {
        dynrt_free(tmp, tmp_size, 1);
    }
    ok
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_fs_list_dir(
    path_ptr: usize,
    path_len: usize,
    out_len_ptr: usize,
) -> usize {
    unsafe {
        dyn_set_out_len(out_len_ptr, 0);
    }
    let Some((path_cstr, path_size)) = (unsafe { dyn_temp_c_string_parts(path_ptr, path_len) })
    else {
        return 0;
    };

    let dir = unsafe { opendir(path_cstr as *const c_char) };
    unsafe {
        dynrt_free(path_cstr, path_size, 1);
    }
    if dir.is_null() {
        return 0;
    }

    let mut out = 0usize;
    let mut cap = 0usize;
    let mut len = 0usize;
    let mut ok = true;

    loop {
        let entry = unsafe { readdir(dir) };
        if entry.is_null() {
            break;
        }

        let name_ptr = unsafe { (*entry).d_name.as_ptr() };
        if name_ptr.is_null() {
            continue;
        }
        let name_bytes = unsafe { CStr::from_ptr(name_ptr).to_bytes() };
        if name_bytes.is_empty() {
            continue;
        }

        if unsafe { *name_bytes.as_ptr() } == b'.' {
            if name_bytes.len() == 1 {
                continue;
            }
            if name_bytes.len() == 2 && unsafe { *name_bytes.as_ptr().add(1) } == b'.' {
                continue;
            }
        }

        if len != 0 && unsafe { !dyn_buf_push_byte(&mut out, &mut cap, &mut len, b'\n') } {
            ok = false;
            break;
        }

        if unsafe {
            !dyn_buf_push_range(
                &mut out,
                &mut cap,
                &mut len,
                name_bytes.as_ptr(),
                name_bytes.len(),
            )
        } {
            ok = false;
            break;
        }

        if unsafe { (*entry).d_type } == DT_DIR
            && unsafe { !dyn_buf_push_byte(&mut out, &mut cap, &mut len, b'/') }
        {
            ok = false;
            break;
        }
    }

    unsafe {
        closedir(dir);
    }

    if !ok {
        if out != 0 {
            unsafe {
                dynrt_free(out, cap, 1);
            }
        }
        return 0;
    }

    if out == 0 {
        return unsafe { dyn_alloc_bytes_slice(b"") };
    }

    let result = unsafe { dyn_alloc_bytes_range(out as *const u8, len) };
    unsafe {
        dynrt_free(out, cap, 1);
    }
    if result == 0 {
        return 0;
    }

    unsafe {
        dyn_set_out_len(out_len_ptr, len);
    }

    result
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_path_join(
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

    let lhs_bytes = unsafe { std::slice::from_raw_parts(lhs_ptr as *const u8, lhs_len) };
    let rhs_bytes = unsafe { std::slice::from_raw_parts(rhs_ptr as *const u8, rhs_len) };

    if rhs_bytes.first().copied() == Some(b'/') {
        let out = unsafe { dyn_alloc_bytes_range(rhs_ptr as *const u8, rhs_len) };
        if out != 0 {
            unsafe {
                dyn_set_out_len(out_len_ptr, rhs_len);
            }
        }
        return out;
    }
    if lhs_bytes.is_empty() {
        let out = unsafe { dyn_alloc_bytes_range(rhs_ptr as *const u8, rhs_len) };
        if out != 0 {
            unsafe {
                dyn_set_out_len(out_len_ptr, rhs_len);
            }
        }
        return out;
    }
    if rhs_bytes.is_empty() {
        let out = unsafe { dyn_alloc_bytes_range(lhs_ptr as *const u8, lhs_len) };
        if out != 0 {
            unsafe {
                dyn_set_out_len(out_len_ptr, lhs_len);
            }
        }
        return out;
    }

    let needs_sep = lhs_bytes.last().copied() != Some(b'/');
    let mut total = lhs_len;
    if needs_sep {
        let Some(next) = total.checked_add(1) else {
            return 0;
        };
        total = next;
    }
    let Some(total_with_rhs) = total.checked_add(rhs_len) else {
        return 0;
    };
    total = total_with_rhs;

    let out = unsafe { dyn_alloc_bytes(total) };
    if out == 0 {
        return 0;
    }

    unsafe {
        ptr::copy_nonoverlapping(lhs_ptr as *const u8, out as *mut u8, lhs_len);
        let mut offset = lhs_len;
        if needs_sep {
            *((out as *mut u8).add(offset)) = b'/';
            offset += 1;
        }
        ptr::copy_nonoverlapping(rhs_ptr as *const u8, (out as *mut u8).add(offset), rhs_len);
    }
    unsafe {
        dyn_set_out_len(out_len_ptr, total);
    }
    out
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_path_normalize(
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
    let ptr_value = ptr_value as *const u8;

    let absolute = len > 0 && unsafe { *ptr_value } == b'/';

    let Some(out_cap) = len.checked_add(3) else {
        return 0;
    };
    let out = unsafe { dynrt_alloc(out_cap, 1) };
    if out == 0 {
        return 0;
    }

    let Some(stack_cap) = len.checked_add(1) else {
        unsafe {
            dynrt_free(out, out_cap, 1);
        }
        return 0;
    };
    let Some(stack_bytes) = stack_cap.checked_mul(mem::size_of::<usize>()) else {
        unsafe {
            dynrt_free(out, out_cap, 1);
        }
        return 0;
    };
    let stack = unsafe { dynrt_alloc(stack_bytes.max(1), mem::align_of::<usize>()) };
    if stack == 0 {
        unsafe {
            dynrt_free(out, out_cap, 1);
        }
        return 0;
    }

    let out_ptr = out as *mut u8;
    let stack_ptr = stack as *mut usize;
    let mut out_len = 0usize;
    let mut seg_count = 0usize;

    if absolute {
        unsafe {
            *out_ptr = b'/';
        }
        out_len = 1;
    }

    let mut index = 0usize;
    while index < len {
        while index < len && unsafe { *ptr_value.add(index) } == b'/' {
            index += 1;
        }
        if index >= len {
            break;
        }

        let seg_start = index;
        while index < len && unsafe { *ptr_value.add(index) } != b'/' {
            index += 1;
        }
        let seg_len = index - seg_start;

        let is_dot = seg_len == 1 && unsafe { *ptr_value.add(seg_start) } == b'.';
        if is_dot {
            continue;
        }

        let is_dot_dot = seg_len == 2
            && unsafe { *ptr_value.add(seg_start) } == b'.'
            && unsafe { *ptr_value.add(seg_start + 1) } == b'.';
        if is_dot_dot {
            if seg_count > 0 {
                seg_count -= 1;
                let prior_start = unsafe { *stack_ptr.add(seg_count) };
                if prior_start == 0 {
                    out_len = 0;
                } else if absolute && prior_start == 1 {
                    out_len = 1;
                } else {
                    out_len = prior_start - 1;
                }
                continue;
            }

            if absolute {
                continue;
            }

            if out_len != 0 {
                unsafe {
                    *out_ptr.add(out_len) = b'/';
                }
                out_len += 1;
            }
            unsafe {
                *out_ptr.add(out_len) = b'.';
                *out_ptr.add(out_len + 1) = b'.';
            }
            out_len += 2;
            continue;
        }

        if out_len != 0 && unsafe { *out_ptr.add(out_len - 1) } != b'/' {
            unsafe {
                *out_ptr.add(out_len) = b'/';
            }
            out_len += 1;
        }

        let segment_output_start = out_len;
        if seg_count < stack_cap {
            unsafe {
                *stack_ptr.add(seg_count) = segment_output_start;
            }
            seg_count += 1;
        }

        unsafe {
            ptr::copy_nonoverlapping(ptr_value.add(seg_start), out_ptr.add(out_len), seg_len);
        }
        out_len += seg_len;
    }

    if out_len == 0 {
        unsafe {
            *out_ptr = if absolute { b'/' } else { b'.' };
        }
        out_len = 1;
    }

    if out_len > 1 && unsafe { *out_ptr.add(out_len - 1) } == b'/' {
        out_len -= 1;
    }

    unsafe {
        *out_ptr.add(out_len) = 0;
        dynrt_free(stack, stack_bytes.max(1), mem::align_of::<usize>());
    }

    unsafe {
        dyn_set_out_len(out_len_ptr, out_len);
    }

    out
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_path_dirname(
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
    let ptr_value = ptr_value as *const u8;
    if len == 0 {
        let out = unsafe { dyn_alloc_bytes_slice(b".") };
        if out != 0 {
            unsafe {
                dyn_set_out_len(out_len_ptr, 1);
            }
        }
        return out;
    }
    if len == 1 && unsafe { *ptr_value } == b'/' {
        let out = unsafe { dyn_alloc_bytes_slice(b"/") };
        if out != 0 {
            unsafe {
                dyn_set_out_len(out_len_ptr, 1);
            }
        }
        return out;
    }

    let end = unsafe { dyn_trim_trailing_slashes(ptr_value, len) };

    let mut slash = end;
    while slash > 0 {
        if unsafe { *ptr_value.add(slash - 1) } == b'/' {
            break;
        }
        slash -= 1;
    }

    if slash == 0 {
        let out = unsafe { dyn_alloc_bytes_slice(b".") };
        if out != 0 {
            unsafe {
                dyn_set_out_len(out_len_ptr, 1);
            }
        }
        return out;
    }
    if slash == 1 {
        let out = unsafe { dyn_alloc_bytes_slice(b"/") };
        if out != 0 {
            unsafe {
                dyn_set_out_len(out_len_ptr, 1);
            }
        }
        return out;
    }

    let out_len = slash - 1;
    let out = unsafe { dyn_alloc_bytes_range(ptr_value, out_len) };
    if out != 0 {
        unsafe {
            dyn_set_out_len(out_len_ptr, out_len);
        }
    }
    out
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_path_basename(
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
    let ptr_value = ptr_value as *const u8;
    if len == 0 {
        return unsafe { dyn_alloc_bytes_slice(b"") };
    }
    if len == 1 && unsafe { *ptr_value } == b'/' {
        let out = unsafe { dyn_alloc_bytes_slice(b"/") };
        if out != 0 {
            unsafe {
                dyn_set_out_len(out_len_ptr, 1);
            }
        }
        return out;
    }

    let end = unsafe { dyn_trim_trailing_slashes(ptr_value, len) };
    let mut start = end;
    while start > 0 {
        if unsafe { *ptr_value.add(start - 1) } == b'/' {
            break;
        }
        start -= 1;
    }
    if start >= end {
        return unsafe { dyn_alloc_bytes_slice(b"") };
    }
    let out_len = end - start;
    let out = unsafe { dyn_alloc_bytes_range(ptr_value.add(start), out_len) };
    if out != 0 {
        unsafe {
            dyn_set_out_len(out_len_ptr, out_len);
        }
    }
    out
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_path_extension(
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
    let ptr_value = ptr_value as *const u8;
    let end = unsafe { dyn_trim_trailing_slashes(ptr_value, len) };
    let mut start = end;
    while start > 0 {
        if unsafe { *ptr_value.add(start - 1) } == b'/' {
            break;
        }
        start -= 1;
    }
    if start >= end {
        return unsafe { dyn_alloc_bytes_slice(b"") };
    }

    let mut dot = end;
    let mut found = false;
    while dot > start {
        if unsafe { *ptr_value.add(dot - 1) } == b'.' {
            dot -= 1;
            found = true;
            break;
        }
        dot -= 1;
    }
    if !found || dot == start || dot + 1 >= end {
        return unsafe { dyn_alloc_bytes_slice(b"") };
    }

    let ext_start = dot + 1;
    let out_len = end - ext_start;
    let out = unsafe { dyn_alloc_bytes_range(ptr_value.add(ext_start), out_len) };
    if out != 0 {
        unsafe {
            dyn_set_out_len(out_len_ptr, out_len);
        }
    }
    out
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_path_is_abs(ptr_value: usize, len: usize) -> u32 {
    if !dyn_valid_ptr_len(ptr_value, len) {
        return 0;
    }
    let ptr_value = ptr_value as *const u8;
    if len != 0 && unsafe { *ptr_value } == b'/' {
        1
    } else {
        0
    }
}
