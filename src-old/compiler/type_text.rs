pub(crate) fn parse_enum_type_descriptor(type_name: &str) -> Option<(u16, &str)> {
    let trimmed = type_name.trim();
    let mut rest = trimmed.strip_prefix("enum")?.trim_start();
    let mut repr_bits = 32u16;

    if let Some(after_open) = rest.strip_prefix('(') {
        let close = after_open.find(')')?;
        let repr_name = after_open[..close].trim();
        repr_bits = match repr_name {
            "u8" => 8,
            "u16" => 16,
            "u32" => 32,
            "u64" => 64,
            "usize" => 64,
            _ => return None,
        };
        rest = after_open[close + 1..].trim_start();
    }

    if !rest.starts_with('{') || !rest.ends_with('}') {
        return None;
    }

    Some((repr_bits, &rest[1..rest.len() - 1]))
}
