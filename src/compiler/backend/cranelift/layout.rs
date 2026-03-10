use std::collections::{BTreeMap, BTreeSet};

use cranelift_codegen::ir::types::{F32, F64, I16, I32, I64, I8};
use cranelift_codegen::ir::Type;

use crate::compiler::mir::{
    MirFunction, MirInstr, MirProgram, MirTerminator, MirValue, MirValueId,
};

use super::{align_to, AggregateLayout};

pub(super) fn build_nominal_aggregate_layouts(
    mir: &MirProgram,
    pointer_ty: Type,
) -> BTreeMap<String, AggregateLayout> {
    let nominal_type_literals = collect_nominal_type_literals(mir);
    let mut layouts = BTreeMap::new();
    let mut visiting = BTreeSet::new();
    let names = nominal_type_literals.keys().cloned().collect::<Vec<_>>();
    for name in names {
        let _ = resolve_nominal_aggregate_layout(
            &name,
            &nominal_type_literals,
            pointer_ty,
            &mut layouts,
            &mut visiting,
        );
    }
    layouts
}

fn collect_nominal_type_literals(mir: &MirProgram) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    for module in &mir.modules {
        for function in &module.functions {
            if let Some(type_literal) = returned_type_literal(function) {
                out.entry(function.name.clone()).or_insert(type_literal);
            }
        }
    }
    out
}

fn returned_type_literal(function: &MirFunction) -> Option<String> {
    let mut value_defs = BTreeMap::<MirValueId, MirValue>::new();
    for block in &function.blocks {
        for instruction in &block.instructions {
            if let MirInstr::Eval { dest, value, .. } = instruction {
                value_defs.insert(*dest, value.clone());
            }
        }
    }

    let mut returned = None::<String>;
    for block in &function.blocks {
        let Some(MirTerminator::Return(Some(value_id))) = &block.terminator else {
            continue;
        };
        let type_name = resolve_type_literal_value(*value_id, &value_defs, 0)?;
        match &returned {
            Some(existing) if existing != &type_name => return None,
            Some(_) => {}
            None => returned = Some(type_name),
        }
    }
    returned
}

fn resolve_type_literal_value(
    value_id: MirValueId,
    value_defs: &BTreeMap<MirValueId, MirValue>,
    depth: usize,
) -> Option<String> {
    if depth > 16 {
        return None;
    }
    match value_defs.get(&value_id) {
        Some(MirValue::TypeLiteral(name)) => Some(name.clone()),
        Some(MirValue::LocalSet { value, .. }) | Some(MirValue::Assign { value, .. }) => {
            resolve_type_literal_value(*value, value_defs, depth + 1)
        }
        _ => None,
    }
}

pub(super) fn parse_aggregate_layout(
    type_hint: Option<&str>,
    nominal_aggregate_layouts: &BTreeMap<String, AggregateLayout>,
    pointer_ty: Type,
) -> Option<AggregateLayout> {
    let ty = normalize_runtime_type_text(type_hint?);
    if ty.is_empty() {
        return None;
    }
    if ty.starts_with("struct{") {
        return parse_struct_layout(&ty, nominal_aggregate_layouts, pointer_ty);
    }
    let nominal = nominal_base_name(&ty)?;
    nominal_aggregate_layouts
        .get(&nominal)
        .cloned()
        .or_else(|| parse_struct_layout(&ty, nominal_aggregate_layouts, pointer_ty))
}

fn resolve_nominal_aggregate_layout(
    name: &str,
    nominal_type_literals: &BTreeMap<String, String>,
    pointer_ty: Type,
    cache: &mut BTreeMap<String, AggregateLayout>,
    visiting: &mut BTreeSet<String>,
) -> Option<AggregateLayout> {
    if let Some(layout) = cache.get(name) {
        return Some(layout.clone());
    }
    if !visiting.insert(name.to_string()) {
        return None;
    }
    let Some(type_text) = nominal_type_literals.get(name) else {
        visiting.remove(name);
        return None;
    };
    let layout = resolve_layout_for_type_text(
        type_text,
        nominal_type_literals,
        pointer_ty,
        cache,
        visiting,
    );
    visiting.remove(name);
    if let Some(layout) = layout.clone() {
        cache.insert(name.to_string(), layout);
    }
    layout
}

fn resolve_layout_for_type_text(
    type_text: &str,
    nominal_type_literals: &BTreeMap<String, String>,
    pointer_ty: Type,
    cache: &mut BTreeMap<String, AggregateLayout>,
    visiting: &mut BTreeSet<String>,
) -> Option<AggregateLayout> {
    let normalized = normalize_runtime_type_text(type_text);
    if normalized.starts_with("struct{") {
        return parse_struct_layout_with_nominals(
            &normalized,
            nominal_type_literals,
            pointer_ty,
            cache,
            visiting,
        );
    }
    let nominal = nominal_base_name(&normalized)?;
    resolve_nominal_aggregate_layout(&nominal, nominal_type_literals, pointer_ty, cache, visiting)
}

fn parse_struct_layout(
    type_text: &str,
    nominal_aggregate_layouts: &BTreeMap<String, AggregateLayout>,
    pointer_ty: Type,
) -> Option<AggregateLayout> {
    if !type_text.starts_with("struct{") || !type_text.ends_with('}') {
        return None;
    }
    let inner = &type_text["struct{".len()..type_text.len() - 1];
    let mut fields = BTreeMap::new();
    let mut aggregate_fields = BTreeMap::new();
    let mut ordered = Vec::new();
    let mut scalar_leaves = Vec::new();
    let mut size = 0u32;
    let mut max_align = 1u32;

    for field in split_top_level(inner, ',') {
        let field = field.trim();
        if field.is_empty() {
            continue;
        }
        let Some(colon_idx) = top_level_separator(field, ':') else {
            continue;
        };
        let name = field[..colon_idx].trim().to_string();
        let ty_text = field[colon_idx + 1..].trim();
        let nested = parse_aggregate_layout(Some(ty_text), nominal_aggregate_layouts, pointer_ty);
        if let Some(nested) = nested {
            let field_align = nested.align.max(1);
            max_align = max_align.max(field_align);
            size = align_to(size, field_align);
            let offset = size as i32;
            size = size.saturating_add(nested.size.max(1));
            for (leaf_ty, leaf_offset) in &nested.scalar_leaves {
                scalar_leaves.push((*leaf_ty, offset + *leaf_offset));
            }
            aggregate_fields.insert(name, (offset, Box::new(nested)));
        } else {
            let field_ty = scalar_type_for_layout(ty_text, pointer_ty);
            let field_align = ((field_ty.bits() / 8).max(1)) as u32;
            max_align = max_align.max(field_align);
            size = align_to(size, field_align);
            let offset = size as i32;
            size = size.saturating_add(field_align);
            fields.insert(name, (field_ty, offset));
            ordered.push((field_ty, offset));
            scalar_leaves.push((field_ty, offset));
        }
    }

    size = align_to(size, max_align).max(1);
    Some(AggregateLayout {
        fields,
        aggregate_fields,
        ordered,
        scalar_leaves,
        size,
        align: max_align,
    })
}

fn parse_struct_layout_with_nominals(
    type_text: &str,
    nominal_type_literals: &BTreeMap<String, String>,
    pointer_ty: Type,
    cache: &mut BTreeMap<String, AggregateLayout>,
    visiting: &mut BTreeSet<String>,
) -> Option<AggregateLayout> {
    if !type_text.starts_with("struct{") || !type_text.ends_with('}') {
        return None;
    }
    let inner = &type_text["struct{".len()..type_text.len() - 1];
    let mut fields = BTreeMap::new();
    let mut aggregate_fields = BTreeMap::new();
    let mut ordered = Vec::new();
    let mut scalar_leaves = Vec::new();
    let mut size = 0u32;
    let mut max_align = 1u32;

    for field in split_top_level(inner, ',') {
        let field = field.trim();
        if field.is_empty() {
            continue;
        }
        let Some(colon_idx) = top_level_separator(field, ':') else {
            continue;
        };
        let name = field[..colon_idx].trim().to_string();
        let ty_text = field[colon_idx + 1..].trim();
        let nested = resolve_layout_for_type_text(
            ty_text,
            nominal_type_literals,
            pointer_ty,
            cache,
            visiting,
        );
        if let Some(nested) = nested {
            let field_align = nested.align.max(1);
            max_align = max_align.max(field_align);
            size = align_to(size, field_align);
            let offset = size as i32;
            size = size.saturating_add(nested.size.max(1));
            for (leaf_ty, leaf_offset) in &nested.scalar_leaves {
                scalar_leaves.push((*leaf_ty, offset + *leaf_offset));
            }
            aggregate_fields.insert(name, (offset, Box::new(nested)));
        } else {
            let field_ty = scalar_type_for_layout(ty_text, pointer_ty);
            let field_align = ((field_ty.bits() / 8).max(1)) as u32;
            max_align = max_align.max(field_align);
            size = align_to(size, field_align);
            let offset = size as i32;
            size = size.saturating_add(field_align);
            fields.insert(name, (field_ty, offset));
            ordered.push((field_ty, offset));
            scalar_leaves.push((field_ty, offset));
        }
    }

    size = align_to(size, max_align).max(1);
    Some(AggregateLayout {
        fields,
        aggregate_fields,
        ordered,
        scalar_leaves,
        size,
        align: max_align,
    })
}

fn split_top_level(input: &str, delimiter: char) -> Vec<String> {
    let mut out = Vec::new();
    let mut start = 0usize;
    let mut paren = 0i32;
    let mut brace = 0i32;
    let mut bracket = 0i32;
    for (idx, ch) in input.char_indices() {
        match ch {
            '(' => paren += 1,
            ')' => paren -= 1,
            '{' => brace += 1,
            '}' => brace -= 1,
            '[' => bracket += 1,
            ']' => bracket -= 1,
            _ => {}
        }
        if ch == delimiter && paren == 0 && brace == 0 && bracket == 0 {
            out.push(input[start..idx].to_string());
            start = idx + ch.len_utf8();
        }
    }
    out.push(input[start..].to_string());
    out
}

fn top_level_separator(input: &str, separator: char) -> Option<usize> {
    let mut paren = 0i32;
    let mut brace = 0i32;
    let mut bracket = 0i32;
    for (idx, ch) in input.char_indices() {
        match ch {
            '(' => paren += 1,
            ')' => paren -= 1,
            '{' => brace += 1,
            '}' => brace -= 1,
            '[' => bracket += 1,
            ']' => bracket -= 1,
            _ => {}
        }
        if ch == separator && paren == 0 && brace == 0 && bracket == 0 {
            return Some(idx);
        }
    }
    None
}

fn normalize_runtime_type_text(text: &str) -> String {
    let mut ty = text.trim().to_string();
    if let Some(stripped) = ty.strip_prefix('?') {
        ty = stripped.trim().to_string();
    }
    if let Some((ok, _errs)) = ty.split_once('!') {
        ty = ok.trim().to_string();
    }
    ty
}

fn nominal_base_name(type_text: &str) -> Option<String> {
    let trimmed = type_text.trim();
    if trimmed.is_empty() {
        return None;
    }
    let mut end = 0usize;
    for (idx, ch) in trimmed.char_indices() {
        if ch.is_ascii_alphanumeric() || ch == '_' {
            end = idx + ch.len_utf8();
        } else {
            break;
        }
    }
    if end == 0 {
        return None;
    }
    let head = &trimmed[..end];
    let tail = trimmed[end..].trim_start();
    if tail.is_empty() || tail.starts_with('(') {
        Some(head.to_string())
    } else {
        None
    }
}

fn scalar_type_for_layout(type_text: &str, pointer_ty: Type) -> Type {
    let ty = normalize_runtime_type_text(type_text);
    if ty.starts_with('*')
        || ty.starts_with("[]")
        || ty.starts_with("[?")
        || ty.starts_with("fn/")
        || ty.starts_with("fn(")
    {
        return pointer_ty;
    }

    if let Some((_, bits)) = parse_int_type_bits(&ty) {
        return int_carrier_type_for_bits(bits);
    }
    if let Some(bits) = parse_float_type_bits(&ty) {
        return float_carrier_type_for_bits(bits);
    }

    match ty.as_str() {
        "bool" => I8,
        "type" | "any" | "opaque" => I64,
        _ => pointer_ty,
    }
}

fn parse_int_type_bits(type_name: &str) -> Option<(bool, u16)> {
    if type_name == "isize" {
        return Some((true, 64));
    }
    if type_name == "usize" {
        return Some((false, 64));
    }

    let (signed, rest) = if let Some(bits) = type_name.strip_prefix('i') {
        (true, bits)
    } else if let Some(bits) = type_name.strip_prefix('u') {
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

fn parse_float_type_bits(type_name: &str) -> Option<u16> {
    let bits = type_name.strip_prefix('f')?;
    if bits.is_empty() {
        return None;
    }
    bits.parse::<u16>().ok()
}

fn int_carrier_type_for_bits(bits: u16) -> Type {
    match bits {
        0..=8 => I8,
        9..=16 => I16,
        17..=32 => I32,
        _ => I64,
    }
}

fn float_carrier_type_for_bits(bits: u16) -> Type {
    if bits <= 32 {
        F32
    } else if bits <= 64 {
        F64
    } else if bits <= 128 {
        I64
    } else {
        F64
    }
}
