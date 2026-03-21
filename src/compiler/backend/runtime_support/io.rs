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
    if prefix_len > value_len {
        return 0;
    }
    if prefix_len == 0 {
        return 1;
    }

    let value = value_ptr as *const u8;
    let prefix = prefix_ptr as *const u8;
    let mut idx = 0usize;
    while idx < prefix_len {
        let lhs = unsafe { *value.add(idx) };
        let rhs = unsafe { *prefix.add(idx) };
        if lhs != rhs {
            return 0;
        }
        idx += 1;
    }
    1
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
    if suffix_len > value_len {
        return 0;
    }
    if suffix_len == 0 {
        return 1;
    }

    let start = value_len - suffix_len;
    let value = value_ptr as *const u8;
    let suffix = suffix_ptr as *const u8;
    let mut idx = 0usize;
    while idx < suffix_len {
        let lhs = unsafe { *value.add(start + idx) };
        let rhs = unsafe { *suffix.add(idx) };
        if lhs != rhs {
            return 0;
        }
        idx += 1;
    }
    1
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

const DYN_PARSE_OK: u32 = 1;
const DYN_PARSE_EMPTY: u32 = 2;
const DYN_PARSE_INVALID: u32 = 3;
const DYN_PARSE_OVERFLOW: u32 = 4;

#[inline]
fn dyn_is_ascii_space(byte: u8) -> bool {
    matches!(byte, b' ' | b'\t' | b'\n' | b'\r' | 0x0b | 0x0c)
}

#[inline]
unsafe fn dyn_trim_ascii_whitespace_bounds(ptr_value: usize, len: usize) -> (usize, usize) {
    let mut start = 0usize;
    let mut end = len;
    let ptr = ptr_value as *const u8;
    while start < end && dyn_is_ascii_space(unsafe { *ptr.add(start) }) {
        start += 1;
    }
    while end > start && dyn_is_ascii_space(unsafe { *ptr.add(end - 1) }) {
        end -= 1;
    }
    (start, end)
}

#[inline]
fn dyn_is_ascii_digit(byte: u8) -> bool {
    byte >= b'0' && byte <= b'9'
}

#[inline]
fn dyn_is_utf8_cont(byte: u8) -> bool {
    (byte & 0b1100_0000) == 0b1000_0000
}

#[inline]
unsafe fn dyn_utf8_scalar_len_at(ptr_value: usize, len: usize, index: usize) -> usize {
    if index >= len {
        return 0;
    }
    let ptr = ptr_value as *const u8;

    let b0 = unsafe { *ptr.add(index) };
    if b0 <= 0x7f {
        return 1;
    }

    let remaining = len - index;
    if b0 >= 0xc2 && b0 <= 0xdf {
        if remaining < 2 {
            return 0;
        }
        return if dyn_is_utf8_cont(unsafe { *ptr.add(index + 1) }) {
            2
        } else {
            0
        };
    }

    if b0 >= 0xe0 && b0 <= 0xef {
        if remaining < 3 {
            return 0;
        }
        let b1 = unsafe { *ptr.add(index + 1) };
        let b2 = unsafe { *ptr.add(index + 2) };
        let valid = if b0 == 0xe0 {
            b1 >= 0xa0 && b1 <= 0xbf && dyn_is_utf8_cont(b2)
        } else if b0 == 0xed {
            b1 >= 0x80 && b1 <= 0x9f && dyn_is_utf8_cont(b2)
        } else {
            dyn_is_utf8_cont(b1) && dyn_is_utf8_cont(b2)
        };
        return if valid { 3 } else { 0 };
    }

    if b0 >= 0xf0 && b0 <= 0xf4 {
        if remaining < 4 {
            return 0;
        }
        let b1 = unsafe { *ptr.add(index + 1) };
        let b2 = unsafe { *ptr.add(index + 2) };
        let b3 = unsafe { *ptr.add(index + 3) };
        let valid = if b0 == 0xf0 {
            b1 >= 0x90 && b1 <= 0xbf && dyn_is_utf8_cont(b2) && dyn_is_utf8_cont(b3)
        } else if b0 == 0xf4 {
            b1 >= 0x80 && b1 <= 0x8f && dyn_is_utf8_cont(b2) && dyn_is_utf8_cont(b3)
        } else {
            dyn_is_utf8_cont(b1) && dyn_is_utf8_cont(b2) && dyn_is_utf8_cont(b3)
        };
        return if valid { 4 } else { 0 };
    }

    0
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_strconv_parse_i32(
    ptr_value: usize,
    len: usize,
    out_value_ptr: usize,
) -> u32 {
    if out_value_ptr == 0 || !dyn_valid_ptr_len(ptr_value, len) {
        return DYN_PARSE_INVALID;
    }

    let (start, end) = unsafe { dyn_trim_ascii_whitespace_bounds(ptr_value, len) };
    if start == end {
        return DYN_PARSE_EMPTY;
    }
    let ptr = ptr_value as *const u8;

    let mut index = start;
    let mut negative = false;
    let first = unsafe { *ptr.add(index) };
    if first == b'+' {
        index += 1;
    } else if first == b'-' {
        negative = true;
        index += 1;
    }
    if index >= end {
        return DYN_PARSE_INVALID;
    }

    let mut acc: i64 = 0;
    let limit: i64 = if negative {
        2_147_483_648
    } else {
        2_147_483_647
    };
    while index < end {
        let byte = unsafe { *ptr.add(index) };
        if !dyn_is_ascii_digit(byte) {
            return DYN_PARSE_INVALID;
        }
        let digit = (byte - b'0') as i64;
        let next = match acc.checked_mul(10).and_then(|v| v.checked_add(digit)) {
            Some(v) => v,
            None => return DYN_PARSE_OVERFLOW,
        };
        if next > limit {
            return DYN_PARSE_OVERFLOW;
        }
        acc = next;
        index += 1;
    }

    let out = if negative {
        if acc == 2_147_483_648 {
            i32::MIN
        } else {
            -(acc as i32)
        }
    } else {
        acc as i32
    };
    unsafe {
        *(out_value_ptr as *mut i32) = out;
    }
    DYN_PARSE_OK
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_strconv_parse_u64(
    ptr_value: usize,
    len: usize,
    out_value_ptr: usize,
) -> u32 {
    if out_value_ptr == 0 || !dyn_valid_ptr_len(ptr_value, len) {
        return DYN_PARSE_INVALID;
    }

    let (start, end) = unsafe { dyn_trim_ascii_whitespace_bounds(ptr_value, len) };
    if start == end {
        return DYN_PARSE_EMPTY;
    }
    let ptr = ptr_value as *const u8;

    let mut index = start;
    if unsafe { *ptr.add(index) } == b'+' {
        index += 1;
    }
    if index >= end {
        return DYN_PARSE_INVALID;
    }

    let mut acc: u64 = 0;
    while index < end {
        let byte = unsafe { *ptr.add(index) };
        if !dyn_is_ascii_digit(byte) {
            return DYN_PARSE_INVALID;
        }
        let digit = (byte - b'0') as u64;
        let next = match acc.checked_mul(10).and_then(|v| v.checked_add(digit)) {
            Some(v) => v,
            None => return DYN_PARSE_OVERFLOW,
        };
        acc = next;
        index += 1;
    }

    unsafe {
        *(out_value_ptr as *mut u64) = acc;
    }
    DYN_PARSE_OK
}

#[inline]
unsafe fn dyn_ascii_eq_ignore_case(ptr_value: usize, start: usize, end: usize, rhs: &[u8]) -> bool {
    let lhs_len = end - start;
    if lhs_len != rhs.len() {
        return false;
    }
    let ptr = ptr_value as *const u8;
    let rhs_ptr = rhs.as_ptr();
    let mut index = 0usize;
    while index < lhs_len {
        let lhs_byte = unsafe { *ptr.add(start + index) };
        let rhs_byte = unsafe { *rhs_ptr.add(index) };
        if !lhs_byte.eq_ignore_ascii_case(&rhs_byte) {
            return false;
        }
        index += 1;
    }
    true
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_strconv_parse_bool(
    ptr_value: usize,
    len: usize,
    out_value_ptr: usize,
) -> u32 {
    if out_value_ptr == 0 || !dyn_valid_ptr_len(ptr_value, len) {
        return DYN_PARSE_INVALID;
    }

    let (start, end) = unsafe { dyn_trim_ascii_whitespace_bounds(ptr_value, len) };
    if start == end {
        return DYN_PARSE_EMPTY;
    }

    let value = if end - start == 1 && unsafe { *((ptr_value as *const u8).add(start)) } == b'1' {
        1u32
    } else if end - start == 1 && unsafe { *((ptr_value as *const u8).add(start)) } == b'0' {
        0u32
    } else if unsafe { dyn_ascii_eq_ignore_case(ptr_value, start, end, b"true") } {
        1u32
    } else if unsafe { dyn_ascii_eq_ignore_case(ptr_value, start, end, b"false") } {
        0u32
    } else {
        return DYN_PARSE_INVALID;
    };

    unsafe {
        *(out_value_ptr as *mut u32) = value;
    }
    DYN_PARSE_OK
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_unicode_utf8_valid(ptr_value: usize, len: usize) -> u32 {
    if !dyn_valid_ptr_len(ptr_value, len) {
        return 0;
    }
    let mut index = 0usize;
    while index < len {
        let width = unsafe { dyn_utf8_scalar_len_at(ptr_value, len, index) };
        if width == 0 {
            return 0;
        }
        index += width;
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_unicode_utf8_count_scalars(
    ptr_value: usize,
    len: usize,
    out_count_ptr: usize,
) -> u32 {
    if out_count_ptr != 0 {
        unsafe {
            *(out_count_ptr as *mut usize) = 0;
        }
    }
    if out_count_ptr == 0 || !dyn_valid_ptr_len(ptr_value, len) {
        return 0;
    }

    let mut index = 0usize;
    let mut count = 0usize;
    while index < len {
        let width = unsafe { dyn_utf8_scalar_len_at(ptr_value, len, index) };
        if width == 0 {
            return 0;
        }
        index += width;
        count += 1;
    }

    unsafe {
        *(out_count_ptr as *mut usize) = count;
    }
    1
}

#[no_mangle]
pub unsafe extern "C" fn dynrt_unicode_utf8_next_len(
    ptr_value: usize,
    len: usize,
    offset: usize,
) -> usize {
    if !dyn_valid_ptr_len(ptr_value, len) {
        return 0;
    }
    if offset >= len {
        return 0;
    }
    unsafe { dyn_utf8_scalar_len_at(ptr_value, len, offset) }
}
