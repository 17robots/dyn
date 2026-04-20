use crate::compiler::ast::{Expr, ExprKind, Literal};
use crate::compiler::sema::{parse_float_type_bits, parse_int_type_bits};

use super::{Type, TypeId, TypeStore};

pub(super) fn tuple_index_literal(expr: &Expr) -> Option<usize> {
    let ExprKind::Literal(Literal::Integer(text)) = &expr.kind else {
        return None;
    };
    let value = parse_integer_literal_value(text)?;
    usize::try_from(value).ok()
}

pub(super) fn integer_literal_fits_type(text: &str, signed: bool, bits: u16) -> bool {
    if bits == 0 {
        return false;
    }
    let Some(value) = parse_integer_literal_value(text) else {
        return false;
    };

    if signed {
        if bits >= 128 {
            return true;
        }
        let shift = u32::from(bits - 1);
        let min = -(1_i128 << shift);
        let max = (1_i128 << shift) - 1;
        return (min..=max).contains(&value);
    }

    if value < 0 {
        return false;
    }
    if bits >= 128 {
        return true;
    }
    let max = (1_u128 << u32::from(bits)) - 1;
    (value as u128) <= max
}

pub(super) fn float_literal_fits_type(text: &str, bits: u16) -> bool {
    let cleaned = text.replace('_', "");
    let Ok(value) = cleaned.parse::<f64>() else {
        return false;
    };
    if bits >= 64 {
        return true;
    }
    if bits >= 32 {
        let narrowed = value as f32;
        return !(value.is_finite() && narrowed.is_infinite());
    }
    true
}

pub(super) fn parse_integer_literal_value(text: &str) -> Option<i128> {
    let cleaned = text.trim().replace('_', "");
    let (negative, unsigned_part) = if let Some(rest) = cleaned.strip_prefix('-') {
        (true, rest)
    } else {
        (false, cleaned.as_str())
    };

    let parse_radix = |digits: &str, radix: u32| -> Option<i128> {
        let magnitude = u128::from_str_radix(digits, radix).ok()?;
        if magnitude > i128::MAX as u128 {
            return None;
        }
        let as_i128 = magnitude as i128;
        if negative {
            as_i128.checked_neg()
        } else {
            Some(as_i128)
        }
    };

    if let Some(rest) = unsigned_part
        .strip_prefix("0x")
        .or_else(|| unsigned_part.strip_prefix("0X"))
    {
        return parse_radix(rest, 16);
    }
    if let Some(rest) = unsigned_part
        .strip_prefix("0b")
        .or_else(|| unsigned_part.strip_prefix("0B"))
    {
        return parse_radix(rest, 2);
    }
    if let Some(rest) = unsigned_part
        .strip_prefix("0o")
        .or_else(|| unsigned_part.strip_prefix("0O"))
    {
        return parse_radix(rest, 8);
    }

    cleaned.parse::<i128>().ok()
}

pub(super) fn numeric_result_type(left: TypeId, right: TypeId, types: &mut TypeStore) -> TypeId {
    match (types.get(left).clone(), types.get(right).clone()) {
        (Type::Float { bits: lb }, Type::Float { bits: rb }) => {
            types.intern(Type::Float { bits: lb.max(rb) })
        }
        (Type::Float { bits }, Type::Int { .. }) | (Type::Int { .. }, Type::Float { bits }) => {
            types.intern(Type::Float { bits })
        }
        (
            Type::Int {
                signed: ls,
                bits: lb,
            },
            Type::Int {
                signed: rs,
                bits: rb,
            },
        ) => {
            let signed = ls || rs;
            types.intern(Type::Int {
                signed,
                bits: lb.max(rb),
            })
        }
        _ => types.intern(Type::Unknown),
    }
}

pub(super) fn parse_int_type_name(name: &str) -> Option<Type> {
    parse_int_type_bits(name).map(|(signed, bits)| Type::Int { signed, bits })
}

pub(super) fn parse_float_type_name(name: &str) -> Option<Type> {
    parse_float_type_bits(name).map(|bits| Type::Float { bits })
}

pub(super) fn bytes_type(types: &mut TypeStore) -> TypeId {
    let u8_ty = types.intern(Type::Int {
        signed: false,
        bits: 8,
    });
    types.intern(Type::Slice {
        mutable: false,
        element: u8_ty,
    })
}

pub(super) fn type_to_string(type_id: TypeId, types: &TypeStore) -> String {
    match types.get(type_id) {
        Type::Unknown => "unknown".to_string(),
        Type::TypeType => "type".to_string(),
        Type::TypeParam(name) => name.clone(),
        Type::Bool => "u1".to_string(),
        Type::Int { signed, bits } => {
            if *signed {
                format!("i{bits}")
            } else {
                format!("u{bits}")
            }
        }
        Type::Float { bits } => format!("f{bits}"),
        Type::Any => "any".to_string(),
        Type::Opaque => "opaque".to_string(),
        Type::Void => "void".to_string(),
        Type::Null => "null".to_string(),
        Type::Optional(inner) => format!("?{}", type_to_string(*inner, types)),
        Type::Errorable { ok, errors } => {
            if errors.is_empty() {
                format!("{}!", type_to_string(*ok, types))
            } else {
                let rendered_errors = errors.iter().cloned().collect::<Vec<_>>().join(",");
                format!("{}!{}", type_to_string(*ok, types), rendered_errors)
            }
        }
        Type::Pointer { inner, mutable } => {
            if *mutable {
                format!("*mut {}", type_to_string(*inner, types))
            } else {
                format!("*{}", type_to_string(*inner, types))
            }
        }
        Type::Array(elem) => format!("[?]{}", type_to_string(*elem, types)),
        Type::Slice { element, mutable } => {
            if *mutable {
                format!("[]mut {}", type_to_string(*element, types))
            } else {
                format!("[]{}", type_to_string(*element, types))
            }
        }
        Type::Tuple(elements) => {
            let rendered = elements
                .iter()
                .map(|element| type_to_string(*element, types))
                .collect::<Vec<_>>()
                .join(", ");
            format!("{{{rendered}}}")
        }
        Type::Named(name) => name.clone(),
        Type::Applied { callee, args } => {
            let rendered = args
                .iter()
                .map(|arg| type_to_string(*arg, types))
                .collect::<Vec<_>>()
                .join(", ");
            format!("{}({})", callee, rendered)
        }
        Type::Function {
            param_types,
            return_type,
            ..
        } => format!(
            "fn/{} -> {}",
            param_types.len(),
            type_to_string(*return_type, types)
        ),
    }
}
