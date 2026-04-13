use std::collections::BTreeMap;

use crate::compiler::ast::BinaryOp;
use crate::compiler::hir::{HirExpr, HirExprKind, HirLiteral};
use crate::compiler::mir::MirValueType;
use crate::compiler::type_text::parse_enum_type_descriptor;

use super::ComptimeValue;

pub(super) fn substitute_type_locals(
    type_name: &str,
    locals: &BTreeMap<String, ComptimeValue>,
) -> String {
    let mut out = String::with_capacity(type_name.len());
    let mut iter = type_name.char_indices().peekable();
    while let Some((start, ch)) = iter.next() {
        if is_type_ident_start(ch) {
            let mut end = start + ch.len_utf8();
            while let Some((idx, next)) = iter.peek().copied() {
                if is_type_ident_continue(next) {
                    end = idx + next.len_utf8();
                    let _ = iter.next();
                } else {
                    break;
                }
            }
            let ident = &type_name[start..end];
            if let Some(ComptimeValue::Type(replacement)) = locals.get(ident) {
                out.push_str(replacement);
            } else {
                out.push_str(ident);
            }
        } else {
            out.push(ch);
        }
    }
    out
}

fn is_type_ident_start(ch: char) -> bool {
    ch == '_' || ch.is_ascii_alphabetic()
}

fn is_type_ident_continue(ch: char) -> bool {
    ch == '_' || ch.is_ascii_alphanumeric()
}

pub(super) fn layout_for_builtin_type_name(name: &str) -> (u64, u64) {
    let name = name.trim();
    if let Some(fields) = parse_struct_fields(name) {
        return layout_for_struct_fields(&fields);
    }
    match name {
        "u1" | "i8" | "u8" => (1, 1),
        "i16" | "u16" => (2, 2),
        "i32" | "u32" | "f32" => (4, 4),
        "i64" | "u64" | "isize" | "usize" | "f64" | "type" => (8, 8),
        "opaque" | "any" => (8, 8),
        n if n.starts_with('*') => (8, 8),
        n if n.starts_with("[]") => (16, 8),
        _ => (8, 8),
    }
}

pub(super) fn builtin_offsetof_for_type_name(type_name: &str, field_arg: &HirExpr) -> Option<u64> {
    let fields = parse_struct_fields(type_name)?;
    let offsets = struct_field_offsets(&fields);
    match &field_arg.kind {
        HirExprKind::Ident(field) => offsets
            .iter()
            .find(|(name, _)| name == field)
            .map(|(_, o)| *o),
        HirExprKind::Literal(HirLiteral::Integer(index)) => {
            let idx = index.parse::<usize>().ok()?;
            offsets.get(idx).map(|(_, offset)| *offset)
        }
        _ => None,
    }
}

pub(super) fn has_struct_field(type_descriptor: &str, field: &str) -> bool {
    parse_struct_fields(type_descriptor)
        .map(|fields| fields.iter().any(|(name, _)| name == field))
        .unwrap_or(false)
}

/// Returns `(field_name, field_type_string)` pairs for a struct descriptor.
pub(super) fn struct_field_names_with_types(type_descriptor: &str) -> Vec<(String, String)> {
    parse_struct_fields(type_descriptor).unwrap_or_default()
}

fn parse_struct_fields(type_name: &str) -> Option<Vec<(String, String)>> {
    if !type_name.starts_with("struct{") || !type_name.ends_with('}') {
        return None;
    }
    let inner = &type_name[7..type_name.len() - 1];
    if inner.trim().is_empty() {
        return Some(Vec::new());
    }
    let mut fields = Vec::new();
    for part in split_top_level(inner, ',') {
        let mut pieces = part.splitn(2, ':');
        let name = pieces.next()?.trim();
        let ty = pieces.next()?.trim();
        if name.is_empty() || ty.is_empty() {
            return None;
        }
        fields.push((name.to_string(), ty.to_string()));
    }
    Some(fields)
}

pub(super) fn enum_type_repr_bits(type_name: &str) -> Option<u16> {
    parse_enum_type_descriptor(type_name).map(|(bits, _)| bits)
}

pub(super) fn enum_type_variants(type_name: &str) -> Option<Vec<String>> {
    let (_, inner) = parse_enum_type_descriptor(type_name)?;
    if inner.trim().is_empty() {
        return Some(Vec::new());
    }

    let mut variants = Vec::new();
    for part in split_top_level(inner, ',') {
        if part.trim().is_empty() {
            continue;
        }
        let mut pieces = part.splitn(2, ':');
        let name = pieces.next()?.trim();
        if name.is_empty() {
            return None;
        }
        variants.push(name.to_string());
    }
    Some(variants)
}

pub(super) fn enum_type_has_payload(type_name: &str) -> Option<bool> {
    let (_, inner) = parse_enum_type_descriptor(type_name)?;
    if inner.trim().is_empty() {
        return Some(false);
    }
    for part in split_top_level(inner, ',') {
        if part.trim().is_empty() {
            continue;
        }
        let mut depth_paren = 0i32;
        let mut depth_brace = 0i32;
        let mut depth_bracket = 0i32;
        for ch in part.chars() {
            match ch {
                '(' => depth_paren += 1,
                ')' => depth_paren -= 1,
                '{' => depth_brace += 1,
                '}' => depth_brace -= 1,
                '[' => depth_bracket += 1,
                ']' => depth_bracket -= 1,
                ':' if depth_paren == 0 && depth_brace == 0 && depth_bracket == 0 => {
                    return Some(true);
                }
                _ => {}
            }
        }
    }
    Some(false)
}

fn split_top_level(input: &str, sep: char) -> Vec<String> {
    let mut out = Vec::new();
    let mut depth_paren = 0i32;
    let mut depth_brace = 0i32;
    let mut depth_bracket = 0i32;
    let mut start = 0usize;
    for (idx, ch) in input.char_indices() {
        match ch {
            '(' => depth_paren += 1,
            ')' => depth_paren -= 1,
            '{' => depth_brace += 1,
            '}' => depth_brace -= 1,
            '[' => depth_bracket += 1,
            ']' => depth_bracket -= 1,
            _ => {}
        }
        if ch == sep && depth_paren == 0 && depth_brace == 0 && depth_bracket == 0 {
            out.push(input[start..idx].trim().to_string());
            start = idx + ch.len_utf8();
        }
    }
    out.push(input[start..].trim().to_string());
    out
}

fn layout_for_struct_fields(fields: &[(String, String)]) -> (u64, u64) {
    let mut size = 0u64;
    let mut max_align = 1u64;
    for (_, ty_name) in fields {
        let (field_size, field_align) = layout_for_builtin_type_name(ty_name);
        max_align = max_align.max(field_align);
        size = align_to_u64(size, field_align);
        size += field_size;
    }
    (align_to_u64(size, max_align), max_align)
}

fn struct_field_offsets(fields: &[(String, String)]) -> Vec<(String, u64)> {
    let mut offsets = Vec::with_capacity(fields.len());
    let mut size = 0u64;
    for (name, ty_name) in fields {
        let (field_size, field_align) = layout_for_builtin_type_name(ty_name);
        size = align_to_u64(size, field_align);
        offsets.push((name.clone(), size));
        size += field_size;
    }
    offsets
}

fn align_to_u64(value: u64, align: u64) -> u64 {
    if align <= 1 {
        return value;
    }
    let mask = align - 1;
    if value & mask == 0 {
        value
    } else {
        (value + mask) & !mask
    }
}

pub(super) fn parse_i64_literal(text: &str) -> Option<i64> {
    text.replace('_', "").parse::<i64>().ok()
}

pub(super) fn comptime_truthy(value: &ComptimeValue) -> bool {
    match value {
        ComptimeValue::Literal(HirLiteral::Bool(v)) => *v,
        ComptimeValue::Literal(HirLiteral::Null) => false,
        ComptimeValue::Literal(HirLiteral::Integer(v)) => {
            parse_i64_literal(v).map(|n| n != 0).unwrap_or(false)
        }
        ComptimeValue::Literal(HirLiteral::Float(v)) => v
            .replace('_', "")
            .parse::<f64>()
            .map(|n| n != 0.0)
            .unwrap_or(false),
        ComptimeValue::Literal(HirLiteral::Char(v)) => *v != '\0',
        ComptimeValue::Literal(HirLiteral::String(v)) => !v.is_empty(),
        ComptimeValue::Type(_) | ComptimeValue::Function(_) => true,
    }
}

pub(super) fn eval_comptime_binary(
    op: BinaryOp,
    left: ComptimeValue,
    right: ComptimeValue,
) -> Option<ComptimeValue> {
    match (left, right) {
        (
            ComptimeValue::Literal(HirLiteral::Integer(l)),
            ComptimeValue::Literal(HirLiteral::Integer(r)),
        ) => {
            let l = parse_i64_literal(&l)?;
            let r = parse_i64_literal(&r)?;
            let out = match op {
                BinaryOp::Add => ComptimeValue::Literal(HirLiteral::Integer((l + r).to_string())),
                BinaryOp::Sub => ComptimeValue::Literal(HirLiteral::Integer((l - r).to_string())),
                BinaryOp::Mul => ComptimeValue::Literal(HirLiteral::Integer((l * r).to_string())),
                BinaryOp::Div => {
                    if r == 0 {
                        return None;
                    }
                    ComptimeValue::Literal(HirLiteral::Integer((l / r).to_string()))
                }
                BinaryOp::Mod => {
                    if r == 0 {
                        return None;
                    }
                    ComptimeValue::Literal(HirLiteral::Integer((l % r).to_string()))
                }
                BinaryOp::Eq => ComptimeValue::Literal(HirLiteral::Bool(l == r)),
                BinaryOp::Ne => ComptimeValue::Literal(HirLiteral::Bool(l != r)),
                BinaryOp::Lt => ComptimeValue::Literal(HirLiteral::Bool(l < r)),
                BinaryOp::Le => ComptimeValue::Literal(HirLiteral::Bool(l <= r)),
                BinaryOp::Gt => ComptimeValue::Literal(HirLiteral::Bool(l > r)),
                BinaryOp::Ge => ComptimeValue::Literal(HirLiteral::Bool(l >= r)),
                BinaryOp::BitAnd => {
                    ComptimeValue::Literal(HirLiteral::Integer((l & r).to_string()))
                }
                BinaryOp::BitOr => ComptimeValue::Literal(HirLiteral::Integer((l | r).to_string())),
                BinaryOp::BitXor => {
                    ComptimeValue::Literal(HirLiteral::Integer((l ^ r).to_string()))
                }
                BinaryOp::Shl => {
                    if r < 0 {
                        return None;
                    }
                    ComptimeValue::Literal(HirLiteral::Integer((l << (r as u32)).to_string()))
                }
                BinaryOp::Shr => {
                    if r < 0 {
                        return None;
                    }
                    ComptimeValue::Literal(HirLiteral::Integer((l >> (r as u32)).to_string()))
                }
                _ => return None,
            };
            Some(out)
        }
        (
            ComptimeValue::Literal(HirLiteral::Bool(l)),
            ComptimeValue::Literal(HirLiteral::Bool(r)),
        ) => {
            let out = match op {
                BinaryOp::LogicalAnd => ComptimeValue::Literal(HirLiteral::Bool(l && r)),
                BinaryOp::LogicalOr => ComptimeValue::Literal(HirLiteral::Bool(l || r)),
                BinaryOp::Eq => ComptimeValue::Literal(HirLiteral::Bool(l == r)),
                BinaryOp::Ne => ComptimeValue::Literal(HirLiteral::Bool(l != r)),
                _ => return None,
            };
            Some(out)
        }
        (ComptimeValue::Type(l), ComptimeValue::Type(r)) => {
            let out = match op {
                BinaryOp::Eq => ComptimeValue::Literal(HirLiteral::Bool(l == r)),
                BinaryOp::Ne => ComptimeValue::Literal(HirLiteral::Bool(l != r)),
                _ => return None,
            };
            Some(out)
        }
        (ComptimeValue::Function(l), ComptimeValue::Function(r)) => {
            let out = match op {
                BinaryOp::Eq => ComptimeValue::Literal(HirLiteral::Bool(l == r)),
                BinaryOp::Ne => ComptimeValue::Literal(HirLiteral::Bool(l != r)),
                _ => return None,
            };
            Some(out)
        }
        _ => None,
    }
}

pub(super) fn eval_comptime_cast(target: &str, value: ComptimeValue) -> Option<ComptimeValue> {
    match (target, value) {
        ("i32" | "i64" | "isize", ComptimeValue::Literal(HirLiteral::Integer(v))) => Some(
            ComptimeValue::Literal(HirLiteral::Integer(parse_i64_literal(&v)?.to_string())),
        ),
        ("u32" | "u64" | "usize", ComptimeValue::Literal(HirLiteral::Integer(v))) => {
            let parsed = parse_i64_literal(&v)?;
            Some(ComptimeValue::Literal(HirLiteral::Integer(
                (parsed as u64).to_string(),
            )))
        }
        ("u1", ComptimeValue::Literal(HirLiteral::Bool(v))) => {
            Some(ComptimeValue::Literal(HirLiteral::Bool(v)))
        }
        (_, other) => Some(other),
    }
}

pub(super) fn literal_type(literal: &HirLiteral) -> MirValueType {
    match literal {
        HirLiteral::Integer(_) => MirValueType::Int {
            signed: true,
            bits: 32,
        },
        HirLiteral::Float(_) => MirValueType::Float { bits: 64 },
        HirLiteral::Bool(_) => MirValueType::Bool,
        HirLiteral::Char(_) => MirValueType::Int {
            signed: false,
            bits: 8,
        },
        HirLiteral::String(_) => MirValueType::BytesSlice,
        HirLiteral::Null => MirValueType::Int {
            signed: false,
            bits: 64,
        },
    }
}

pub(super) fn parse_type_hint(text: &str) -> MirValueType {
    let trimmed = text.trim();
    if trimmed.starts_with("fn/")
        || trimmed.starts_with("fn(")
        || (trimmed.starts_with('(') && trimmed.contains(")->"))
    {
        return MirValueType::FunctionPointer;
    }
    let mut normalized = trimmed;
    if let Some(inner) = normalized.strip_prefix('?') {
        normalized = inner.trim();
    }
    if let Some((ok, _)) = normalized.split_once('!') {
        normalized = ok.trim();
    } else if let Some(ok) = normalized.strip_suffix('!') {
        normalized = ok.trim();
    }

    match normalized {
        "u1" => return MirValueType::Bool,
        "[]u8" => return MirValueType::BytesSlice,
        "type" => return MirValueType::Type,
        "isize" => {
            return MirValueType::Int {
                signed: true,
                bits: 64,
            };
        }
        "usize" | "opaque" | "any" => {
            return MirValueType::Int {
                signed: false,
                bits: 64,
            };
        }
        _ => {}
    }

    if normalized.starts_with('*') || normalized.starts_with("[]") {
        return MirValueType::Int {
            signed: false,
            bits: 64,
        };
    }

    if normalized.starts_with("enum") {
        if matches!(enum_type_has_payload(normalized), Some(false)) {
            if let Some(bits) = enum_type_repr_bits(normalized) {
                return MirValueType::Int {
                    signed: false,
                    bits,
                };
            }
        }
        return MirValueType::Unknown;
    }

    if let Some(rest) = normalized.strip_prefix('i') {
        if let Ok(bits) = rest.parse::<u16>() {
            return MirValueType::Int { signed: true, bits };
        }
    }
    if let Some(rest) = normalized.strip_prefix('u') {
        if let Ok(bits) = rest.parse::<u16>() {
            return MirValueType::Int {
                signed: false,
                bits,
            };
        }
    }
    if let Some(rest) = normalized.strip_prefix('f') {
        if let Ok(bits) = rest.parse::<u16>() {
            if matches!(bits, 32 | 64) {
                return MirValueType::Float { bits };
            }
        }
    }

    MirValueType::Unknown
}

pub(super) fn parse_function_return_hint(text: &str) -> Option<MirValueType> {
    let trimmed = text.trim();
    let arrow = trimmed.rfind("->")?;
    let ret = &trimmed[arrow + 2..];
    let parsed = parse_type_hint(ret.trim());
    if matches!(parsed, MirValueType::Unknown) {
        None
    } else {
        Some(parsed)
    }
}

pub(super) fn self_type_literal_from_param_hint(text: &str) -> String {
    let mut hint = text.trim();
    if let Some(stripped) = hint.strip_prefix("*mut ") {
        hint = stripped.trim();
    } else if let Some(stripped) = hint.strip_prefix('*') {
        hint = stripped.trim();
    }
    hint.to_string()
}

pub(super) fn type_literal_name_for_ident(
    name: &str,
    named_type_literals: &BTreeMap<String, String>,
) -> Option<String> {
    if let Some(lit) = named_type_literals.get(name) {
        return Some(lit.clone());
    }
    if parse_type_hint(name) != MirValueType::Unknown || matches!(name, "type" | "opaque" | "any") {
        return Some(name.to_string());
    }
    None
}

pub(super) fn merge_types(left: &MirValueType, right: &MirValueType) -> MirValueType {
    if left == right {
        return left.clone();
    }
    match (left, right) {
        (MirValueType::Unknown, other) | (other, MirValueType::Unknown) => other.clone(),
        (
            MirValueType::Int {
                signed: ls,
                bits: lb,
            },
            MirValueType::Int {
                signed: rs,
                bits: rb,
            },
        ) => MirValueType::Int {
            signed: *ls || *rs,
            bits: (*lb).max(*rb),
        },
        (MirValueType::Float { bits: lb }, MirValueType::Float { bits: rb }) => {
            MirValueType::Float {
                bits: (*lb).max(*rb),
            }
        }
        (MirValueType::BytesSlice, MirValueType::BytesSlice) => MirValueType::BytesSlice,
        _ => MirValueType::Unknown,
    }
}

/// Map a concrete type name to its broad type class, as returned by `$typeclass`.
///
/// - `u8 / u16 / u32 / u64 / usize` → `"uint"`
/// - `i8 / i16 / i32 / i64`         → `"sint"`
/// - `f32 / f64`                     → `"float"`
/// - `u1`                            → `"bool-class"`
/// - `[]u8`                          → `"bytes"`
/// - anything else                   → `"struct"`
pub(super) fn type_name_to_class(type_name: &str) -> &'static str {
    match type_name {
        "u8" | "u16" | "u32" | "u64" | "usize" => "uint",
        "i8" | "i16" | "i32" | "i64" => "sint",
        "f32" | "f64" => "float",
        "u1" => "bool",
        "[]u8" => "bytes",
        _ => "struct",
    }
}
