pub fn parse_int_type_bits(name: &str) -> Option<(bool, u16)> {
    if name == "isize" {
        return Some((true, 64));
    }
    if name == "usize" {
        return Some((false, 64));
    }

    let (signed, rest) = if let Some(bits) = name.strip_prefix('i') {
        (true, bits)
    } else if let Some(bits) = name.strip_prefix('u') {
        (false, bits)
    } else {
        return None;
    };

    if rest.is_empty() {
        return None;
    }
    let bits = rest.parse::<u16>().ok()?;
    Some((signed, bits))
}

pub fn parse_float_type_bits(name: &str) -> Option<u16> {
    let rest = name.strip_prefix('f')?;
    if rest.is_empty() {
        return None;
    }
    rest.parse::<u16>().ok()
}

pub fn is_int_type_name(name: &str) -> bool {
    parse_int_type_bits(name).is_some()
}

pub fn is_float_type_name(name: &str) -> bool {
    parse_float_type_bits(name).is_some()
}
