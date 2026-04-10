use crate::compiler::mir::lower::helpers::*;

use super::*;

use std::collections::BTreeSet;

fn find_comptime_match_arm<'a>(
    value: &ComptimeValue,
    arms: &'a [HirMatchArm],
) -> Option<&'a HirMatchArm> {
    arms.iter()
        .find(|arm| comptime_pattern_matches(value, &arm.pattern))
}

fn comptime_pattern_matches(value: &ComptimeValue, pattern: &HirPattern) -> bool {
    match (value, pattern) {
        (_, HirPattern::Wildcard) => true,
        (ComptimeValue::Type(type_name), HirPattern::TypeLiteral(pat)) => type_name == pat,
        // In a comp match on a type, IdentBind is treated as a type name pattern
        (ComptimeValue::Type(type_name), HirPattern::IdentBind(ident)) => type_name == ident,
        (ComptimeValue::Literal(HirLiteral::Bool(v)), HirPattern::Literal(HirLiteral::Bool(p))) => {
            v == p
        }
        (
            ComptimeValue::Literal(HirLiteral::Integer(v)),
            HirPattern::Literal(HirLiteral::Integer(p)),
        ) => v == p,
        (
            ComptimeValue::Literal(HirLiteral::Float(v)),
            HirPattern::Literal(HirLiteral::Float(p)),
        ) => v == p,
        (
            ComptimeValue::Literal(HirLiteral::String(v)),
            HirPattern::Literal(HirLiteral::String(p)),
        ) => v == p,
        (ComptimeValue::Literal(HirLiteral::Null), HirPattern::Literal(HirLiteral::Null)) => true,
        _ => false,
    }
}

fn collect_free_vars(expr: &HirExpr, bound: &BTreeSet<String>) -> BTreeSet<String> {
    match &expr.kind {
        HirExprKind::Ident(name) => {
            if !bound.contains(name) {
                std::iter::once(name.clone()).collect()
            } else {
                BTreeSet::new()
            }
        }
        HirExprKind::Literal(_) => BTreeSet::new(),
        HirExprKind::Block { body } => {
            let mut all = BTreeSet::new();
            let mut cur = bound.clone();
            for e in body {
                all.extend(collect_free_vars(e, &cur));
                if let HirExprKind::Let { name, .. } = &e.kind {
                    cur.insert(name.clone());
                }
            }
            all
        }
        HirExprKind::Let { value, .. } => collect_free_vars(value, bound),
        HirExprKind::Function { params, body, .. } => {
            let mut inner = bound.clone();
            for p in params {
                inner.insert(p.clone());
            }
            collect_free_vars(body, &inner)
        }
        HirExprKind::Unary { expr, .. } => collect_free_vars(expr, bound),
        HirExprKind::Binary { left, right, .. } => {
            let mut f = collect_free_vars(left, bound);
            f.extend(collect_free_vars(right, bound));
            f
        }
        HirExprKind::Assign { target, value, .. } => {
            let mut f = collect_free_vars(target, bound);
            f.extend(collect_free_vars(value, bound));
            f
        }
        HirExprKind::Call { callee, args } => {
            let mut f = collect_free_vars(callee, bound);
            for a in args {
                f.extend(collect_free_vars(&a.value, bound));
            }
            f
        }
        HirExprKind::FieldAccess { base, .. } | HirExprKind::DerefAccess { base } => {
            collect_free_vars(base, bound)
        }
        HirExprKind::Index { base, index } => {
            let mut f = collect_free_vars(base, bound);
            f.extend(collect_free_vars(index, bound));
            f
        }
        HirExprKind::Slice {
            base, start, end, ..
        } => {
            let mut f = collect_free_vars(base, bound);
            if let Some(s) = start {
                f.extend(collect_free_vars(s, bound));
            }
            if let Some(e) = end {
                f.extend(collect_free_vars(e, bound));
            }
            f
        }
        HirExprKind::StructLiteral { fields, .. } => {
            let mut f = BTreeSet::new();
            for (_, v) in fields {
                f.extend(collect_free_vars(v, bound));
            }
            f
        }
        HirExprKind::EnumVariant { payload, .. } => {
            let mut f = BTreeSet::new();
            for p in payload {
                f.extend(collect_free_vars(p, bound));
            }
            f
        }
        HirExprKind::If {
            condition,
            capture,
            then_branch,
            else_branch,
        } => {
            let mut f = collect_free_vars(condition, bound);
            let mut then_bound = bound.clone();
            if let Some(cap) = capture {
                if let Some(b) = &cap.binding {
                    then_bound.insert(b.clone());
                }
            }
            f.extend(collect_free_vars(then_branch, &then_bound));
            if let Some(eb) = else_branch {
                f.extend(collect_free_vars(eb, bound));
            }
            f
        }
        HirExprKind::Match { value, arms } => {
            let mut f = collect_free_vars(value, bound);
            for arm in arms {
                let mut arm_bound = bound.clone();
                match &arm.pattern {
                    HirPattern::IdentBind(n) => {
                        arm_bound.insert(n.clone());
                    }
                    HirPattern::EnumVariant { bindings, .. } => {
                        for b in bindings {
                            arm_bound.insert(b.clone());
                        }
                    }
                    _ => {}
                }
                if let Some(g) = &arm.guard {
                    f.extend(collect_free_vars(g, &arm_bound));
                }
                f.extend(collect_free_vars(&arm.value, &arm_bound));
            }
            f
        }
        HirExprKind::For(for_expr) => match for_expr {
            HirForExpr::Infinite { body } => collect_free_vars(body, bound),
            HirForExpr::WhileLike { condition, body } => {
                let mut f = collect_free_vars(condition, bound);
                f.extend(collect_free_vars(body, bound));
                f
            }
            HirForExpr::Range {
                start,
                end,
                binding,
                body,
                ..
            } => {
                let mut f = collect_free_vars(start, bound);
                f.extend(collect_free_vars(end, bound));
                let mut bb = bound.clone();
                if let Some(b) = binding {
                    bb.insert(b.clone());
                }
                f.extend(collect_free_vars(body, &bb));
                f
            }
            HirForExpr::Iterate {
                iterable,
                binding,
                body,
            } => {
                let mut f = collect_free_vars(iterable, bound);
                let mut bb = bound.clone();
                if let Some(b) = binding {
                    bb.insert(b.clone());
                }
                f.extend(collect_free_vars(body, &bb));
                f
            }
        },
        HirExprKind::Break { value } | HirExprKind::Return { value } => value
            .as_deref()
            .map(|v| collect_free_vars(v, bound))
            .unwrap_or_default(),
        HirExprKind::Continue => BTreeSet::new(),
        HirExprKind::Defer { body, .. } => collect_free_vars(body, bound),
        HirExprKind::OrElse {
            value,
            fallback,
            error_binding,
            ..
        } => {
            let mut f = collect_free_vars(value, bound);
            let mut fb = bound.clone();
            if let Some(b) = error_binding {
                fb.insert(b.clone());
            }
            f.extend(collect_free_vars(fallback, &fb));
            f
        }
        HirExprKind::OptionalUnwrap { value } | HirExprKind::ErrorUnwrap { value } => {
            collect_free_vars(value, bound)
        }
        HirExprKind::Use { .. } | HirExprKind::TypeLiteral(_) => BTreeSet::new(),
        HirExprKind::Comptime { expr } | HirExprKind::Inline { expr } => {
            collect_free_vars(expr, bound)
        }
        HirExprKind::Unknown => BTreeSet::new(),
    }
}

impl FunctionLowerer {
    pub(super) fn new(
        module_key: ModuleKey,
        source_file_path: std::path::PathBuf,
        name: String,
        shared: FunctionLowererShared,
    ) -> Self {
        Self {
            module_key,
            source_file_path,
            function: MirFunction {
                name,
                def_id: None,
                return_type: None,
                param_type_hints: Vec::new(),
                param_types: Vec::new(),
                blocks: vec![MirBasicBlock {
                    id: MirBlockId(0),
                    instructions: Vec::new(),
                    terminator: None,
                }],
                entry: MirBlockId(0),
            },
            next_value: 0,
            locals: BTreeMap::new(),
            address_taken_values: BTreeMap::new(),
            comptime_known_locals: BTreeMap::new(),
            comptime_local_function_exprs: BTreeMap::new(),
            value_types: BTreeMap::new(),
            value_defs: BTreeMap::new(),
            struct_fields: BTreeMap::new(),
            aggregate_sequences: BTreeMap::new(),
            function_return_types: shared.function_return_types,
            function_return_hints: shared.function_return_hints,
            errorable_aggregate_values: BTreeSet::new(),
            errorable_scalar_values: BTreeSet::new(),
            named_type_literals: shared.named_type_literals,
            enum_repr_bits_by_name: shared.enum_repr_bits_by_name,
            enum_variant_tags_by_name: shared.enum_variant_tags_by_name,
            function_param_names: shared.function_param_names,
            function_param_defaults: shared.function_param_defaults,
            function_param_type_hints: shared.function_param_type_hints,
            function_exprs: shared.function_exprs,
            inline_function_names: shared.inline_function_names,
            module_ids_by_key: shared.module_ids_by_key,
            module_exports_by_id: shared.module_exports_by_id,
            current_param_type_hints: Vec::new(),
            current_self_type_hint: None,
            inline_call_depth: 0,
            inline_call_stack: Vec::new(),
            current_inline_module: None,
            loop_stack: Vec::new(),
            or_break_stack: Vec::new(),
            deferred: Vec::new(),
            diagnostics: Vec::new(),
            hoisted_lambdas: Vec::new(),
            global_names: shared.global_names,
            local_type_hints: BTreeMap::new(),
            build_config: shared.build_config,
        }
    }

    pub(super) fn lower_expr(
        &mut self,
        block: MirBlockId,
        expr: &HirExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        match &expr.kind {
            HirExprKind::Literal(literal) => {
                let ty = literal_type(literal);
                (
                    block,
                    Some(self.push_eval(block, MirValue::Literal(literal.clone()), ty)),
                )
            }
            HirExprKind::Ident(name) => {
                if let Some(value) = self.locals.get(name).copied() {
                    if let Some(addr) = self.address_taken_values.get(name).copied() {
                        let ty = self
                            .value_types
                            .get(&value)
                            .cloned()
                            .unwrap_or(MirValueType::Unknown);
                        (
                            block,
                            Some(self.push_eval(block, MirValue::DerefAccess { base: addr }, ty)),
                        )
                    } else {
                        (block, Some(value))
                    }
                } else if self.global_names.contains(name) {
                    let ty = self
                        .function_return_types
                        .get(name)
                        .cloned()
                        .unwrap_or(MirValueType::Unknown);
                    (
                        block,
                        Some(self.push_eval(
                            block,
                            MirValue::GlobalLoad { name: name.clone() },
                            ty,
                        )),
                    )
                } else if let Some(type_name) =
                    type_literal_name_for_ident(name, &self.named_type_literals)
                {
                    (
                        block,
                        Some(self.push_eval(
                            block,
                            MirValue::TypeLiteral(type_name),
                            MirValueType::Type,
                        )),
                    )
                } else {
                    // When inlining a cross-module function, bare function calls in its body
                    // (e.g. `render_value` inside `substitute_next` from the io module) must
                    // be resolved to their qualified form (e.g. `#8::render_value`) so they
                    // can be found in the caller module's inline_function_names.
                    // Only qualify names that are actually inline functions — module import
                    // variables (e.g. `bytes_mod`) are left unqualified and handled separately
                    // in the FieldAccess path.
                    let effective_name = if let Some(module_id) = &self.current_inline_module {
                        let qualified = format!("{module_id}::{name}");
                        if self.inline_function_names.contains(&qualified) {
                            qualified
                        } else {
                            name.clone()
                        }
                    } else {
                        name.clone()
                    };
                    let ty = if self.function_return_types.contains_key(&effective_name) {
                        MirValueType::FunctionPointer
                    } else {
                        MirValueType::Unknown
                    };
                    (
                        block,
                        Some(self.push_eval(block, MirValue::Ident(effective_name), ty)),
                    )
                }
            }
            HirExprKind::Unary { expr, op } => {
                if matches!(op, UnaryOp::Ref) {
                    if let HirExprKind::Ident(name) = &expr.kind {
                        if let Some(local_value) = self.locals.get(name).copied() {
                            let ty = self
                                .value_types
                                .get(&local_value)
                                .cloned()
                                .unwrap_or(MirValueType::Unknown);
                            let addr = self.push_eval(
                                block,
                                MirValue::Unary {
                                    op: *op,
                                    operand: local_value,
                                },
                                ty,
                            );
                            if self.should_track_address_taken_local(local_value) {
                                self.address_taken_values.insert(name.clone(), addr);
                            } else {
                                self.invalidate_address_taken_aggregate_view(local_value, 0);
                            }
                            return (block, Some(addr));
                        }
                    }
                }
                let (end, operand) = self.lower_expr(block, expr);
                let Some(operand) = operand else {
                    return (end, None);
                };
                let ty = self
                    .value_types
                    .get(&operand)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown);
                (
                    end,
                    Some(self.push_eval(end, MirValue::Unary { op: *op, operand }, ty)),
                )
            }
            HirExprKind::Binary { left, right, op } => {
                let (left_end, left_value) = self.lower_expr(block, left);
                let (right_end, right_value) = self.lower_expr(left_end, right);
                let (Some(left_value), Some(right_value)) = (left_value, right_value) else {
                    return (right_end, None);
                };
                let left_ty = self
                    .value_types
                    .get(&left_value)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown);
                let right_ty = self
                    .value_types
                    .get(&right_value)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown);
                let result_ty = match op {
                    crate::compiler::ast::BinaryOp::Eq
                    | crate::compiler::ast::BinaryOp::Ne
                    | crate::compiler::ast::BinaryOp::Lt
                    | crate::compiler::ast::BinaryOp::Le
                    | crate::compiler::ast::BinaryOp::Gt
                    | crate::compiler::ast::BinaryOp::Ge
                    | crate::compiler::ast::BinaryOp::LogicalAnd
                    | crate::compiler::ast::BinaryOp::LogicalOr => MirValueType::Bool,
                    _ => merge_types(&left_ty, &right_ty),
                };
                (
                    right_end,
                    Some(self.push_eval(
                        right_end,
                        MirValue::Binary {
                            op: *op,
                            left: left_value,
                            right: right_value,
                        },
                        result_ty,
                    )),
                )
            }
            HirExprKind::Assign { target, value, op } => {
                let (target_end, target_value) = self.lower_expr(block, target);
                let (value_end, value_value) = self.lower_expr(target_end, value);
                let (Some(target_value), Some(value_value)) = (target_value, value_value) else {
                    return (value_end, None);
                };
                let target_ty = self
                    .value_types
                    .get(&target_value)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown);
                let value_ty = self
                    .value_types
                    .get(&value_value)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown);
                if let HirExprKind::Ident(name) = &target.kind {
                    if name == "_" {
                        return (value_end, Some(value_value));
                    }
                    let assigned_value = if let Some(binary_op) = assign_to_binary_op(*op) {
                        let result_ty = merge_types(&target_ty, &value_ty);
                        self.push_eval(
                            value_end,
                            MirValue::Binary {
                                op: binary_op,
                                left: target_value,
                                right: value_value,
                            },
                            result_ty,
                        )
                    } else {
                        value_value
                    };

                    let assigned_value = if matches!(
                        target_ty,
                        MirValueType::Int { .. } | MirValueType::Float { .. } | MirValueType::Bool
                    ) {
                        self.push_eval(
                            value_end,
                            MirValue::Cast {
                                value: assigned_value,
                                target: target_ty.clone(),
                            },
                            target_ty.clone(),
                        )
                    } else {
                        assigned_value
                    };

                    let assigned_ty = self
                        .value_types
                        .get(&assigned_value)
                        .cloned()
                        .unwrap_or(value_ty.clone());
                    if self.global_names.contains(name) {
                        let store = self.push_eval(
                            value_end,
                            MirValue::GlobalStore {
                                name: name.clone(),
                                value: assigned_value,
                            },
                            assigned_ty,
                        );
                        return (value_end, Some(store));
                    }
                    self.locals.insert(name.clone(), assigned_value);
                    if matches!(op, AssignOp::Assign) {
                        self.refresh_comptime_local_from_expr(name, value);
                    } else {
                        self.comptime_known_locals.remove(name);
                        self.comptime_local_function_exprs.remove(name);
                    }
                    let local_set = self.push_eval(
                        value_end,
                        MirValue::LocalSet {
                            name: name.clone(),
                            value: assigned_value,
                        },
                        assigned_ty,
                    );
                    if self.errorable_aggregate_values.contains(&assigned_value) {
                        self.errorable_aggregate_values.insert(local_set);
                    }
                    if self.errorable_scalar_values.contains(&assigned_value) {
                        self.errorable_scalar_values.insert(local_set);
                    }
                    return (value_end, Some(local_set));
                }
                (
                    value_end,
                    Some(self.push_eval(
                        value_end,
                        MirValue::Assign {
                            op: *op,
                            target: target_value,
                            value: value_value,
                        },
                        value_ty,
                    )),
                )
            }
            HirExprKind::Let {
                name,
                type_hint,
                value,
                ..
            } => {
                let (end, init_value) = self.lower_expr(block, value);
                let Some(init_value) = init_value else {
                    return (end, None);
                };

                let hint_ty = type_hint
                    .as_deref()
                    .map(parse_type_hint)
                    .filter(|ty| !matches!(ty, MirValueType::Unknown));
                let stored_value = if hint_ty.as_ref().is_some_and(|hint_ty| {
                    matches!(
                        hint_ty,
                        MirValueType::Int { .. } | MirValueType::Float { .. } | MirValueType::Bool
                    )
                }) {
                    let hint_ty = hint_ty.as_ref().expect("checked above");
                    let init_ty = self
                        .value_types
                        .get(&init_value)
                        .cloned()
                        .unwrap_or(MirValueType::Unknown);
                    if init_ty == *hint_ty {
                        init_value
                    } else {
                        self.push_eval(
                            end,
                            MirValue::Cast {
                                value: init_value,
                                target: hint_ty.clone(),
                            },
                            hint_ty.clone(),
                        )
                    }
                } else {
                    init_value
                };

                self.locals.insert(name.clone(), stored_value);
                // Track the raw type hint for named locals so $fields(v) can resolve the struct.
                if let Some(hint) = type_hint {
                    self.local_type_hints.insert(name.clone(), hint.clone());
                }
                self.refresh_comptime_local_from_expr(name, value);
                let value_ty = self
                    .value_types
                    .get(&stored_value)
                    .cloned()
                    .or(hint_ty)
                    .unwrap_or(MirValueType::Unknown);
                let local_set = self.push_eval(
                    end,
                    MirValue::LocalSet {
                        name: name.clone(),
                        value: stored_value,
                    },
                    value_ty,
                );
                if self.errorable_aggregate_values.contains(&init_value)
                    || self.errorable_aggregate_values.contains(&stored_value)
                {
                    self.errorable_aggregate_values.insert(local_set);
                }
                if self.errorable_scalar_values.contains(&init_value)
                    || self.errorable_scalar_values.contains(&stored_value)
                {
                    self.errorable_scalar_values.insert(local_set);
                }
                (end, Some(local_set))
            }
            HirExprKind::Call { callee, args } => self.lower_call_expr(block, callee, args, false),
            HirExprKind::FieldAccess { base, field } => {
                if let HirExprKind::Ident(base_name) = &base.kind {
                    if !self.locals.contains_key(base_name) {
                        // Try to find the import path for the module variable. When inlining a
                        // cross-module function, the module variable (e.g. `bytes_mod`) lives in
                        // the source module's namespace. Try the unqualified name first, then the
                        // qualified name (e.g. `#8::bytes_mod`) using the current inline module.
                        let import_path = self
                            .top_level_import_path(base_name)
                            .map(|s| s.to_string())
                            .or_else(|| {
                                self.current_inline_module.as_ref().and_then(|module_id| {
                                    let qualified = format!("{module_id}::{base_name}");
                                    self.top_level_import_path(&qualified)
                                        .map(|s| s.to_string())
                                })
                            });
                        if let Some(import_path) = import_path {
                            if let Some(qualified) =
                                self.resolve_import_member_ident(&import_path, field)
                            {
                                return (
                                    block,
                                    Some(self.push_eval(
                                        block,
                                        MirValue::Ident(qualified),
                                        MirValueType::FunctionPointer,
                                    )),
                                );
                            }
                        }
                    }
                }

                let (end, base_value) = self.lower_expr(block, base);
                let Some(base_value) = base_value else {
                    return (end, None);
                };
                if let Some(fields) = self.struct_fields.get(&base_value) {
                    if let Some(value) = fields.get(field).copied() {
                        return (end, Some(value));
                    }
                }
                (
                    end,
                    Some(self.push_eval(
                        end,
                        MirValue::FieldAccess {
                            base: base_value,
                            field: field.clone(),
                        },
                        self.infer_field_access_result_type(base_value, field, 0),
                    )),
                )
            }
            HirExprKind::DerefAccess { base } => {
                let (end, base_value) = self.lower_expr(block, base);
                let Some(base_value) = base_value else {
                    return (end, None);
                };
                (
                    end,
                    Some(
                        self.push_eval(
                            end,
                            MirValue::DerefAccess { base: base_value },
                            self.value_types
                                .get(&base_value)
                                .cloned()
                                .unwrap_or(MirValueType::Unknown),
                        ),
                    ),
                )
            }
            HirExprKind::Index { base, index } => {
                if let HirExprKind::Binary { op, left, right } = &index.kind {
                    if matches!(
                        op,
                        crate::compiler::ast::BinaryOp::Range
                            | crate::compiler::ast::BinaryOp::RangeInclusive
                    ) {
                        let (base_end, base_value) = self.lower_expr(block, base);
                        let Some(base_value) = base_value else {
                            return (base_end, None);
                        };
                        let (after_start, start_value) = self.lower_expr(base_end, left);
                        let (after_end, end_value) = self.lower_expr(after_start, right);
                        let (Some(start_value), Some(end_value)) = (start_value, end_value) else {
                            return (after_end, None);
                        };

                        let inclusive =
                            matches!(op, crate::compiler::ast::BinaryOp::RangeInclusive);
                        let dest = self.push_eval(
                            after_end,
                            MirValue::Slice {
                                base: base_value,
                                start: Some(start_value),
                                end: Some(end_value),
                                inclusive,
                            },
                            MirValueType::Unknown,
                        );
                        self.track_aggregate_slice_view(
                            dest,
                            base_value,
                            Some(start_value),
                            Some(end_value),
                            inclusive,
                        );
                        return (after_end, Some(dest));
                    }
                }

                let (base_end, base_value) = self.lower_expr(block, base);
                let (idx_end, index_value) = self.lower_expr(base_end, index);
                let (Some(base_value), Some(index_value)) = (base_value, index_value) else {
                    return (idx_end, None);
                };
                if let Some(values) = self.aggregate_sequences.get(&base_value) {
                    if let Some(idx) = self.literal_int_value(index_value) {
                        if let Some(target) = values.get(idx as usize).copied() {
                            return (idx_end, Some(target));
                        }
                    }
                }
                (
                    idx_end,
                    Some(self.push_eval(
                        idx_end,
                        MirValue::Index {
                            base: base_value,
                            index: index_value,
                        },
                        self.infer_index_result_type(base_value, 0),
                    )),
                )
            }
            HirExprKind::Slice {
                base,
                start,
                end,
                inclusive,
            } => {
                let (base_end, base_value) = self.lower_expr(block, base);
                let Some(base_value) = base_value else {
                    return (base_end, None);
                };
                let (after_start, start_value) = if let Some(start) = start {
                    let (end, value) = self.lower_expr(base_end, start);
                    (end, value)
                } else {
                    (base_end, None)
                };
                let (after_end, end_value) = if let Some(end_expr) = end {
                    let (end, value) = self.lower_expr(after_start, end_expr);
                    (end, value)
                } else {
                    (after_start, None)
                };
                let dest = self.push_eval(
                    after_end,
                    MirValue::Slice {
                        base: base_value,
                        start: start_value,
                        end: end_value,
                        inclusive: *inclusive,
                    },
                    self.infer_slice_result_type(base_value, 0),
                );
                self.track_aggregate_slice_view(
                    dest,
                    base_value,
                    start_value,
                    end_value,
                    *inclusive,
                );

                (after_end, Some(dest))
            }
            HirExprKind::StructLiteral { fields, .. } => {
                let mut end = block;
                let mut lowered_fields = Vec::with_capacity(fields.len());
                let mut field_map = BTreeMap::new();
                let mut seq = Vec::with_capacity(fields.len());
                for (name, expr) in fields {
                    let (field_end, field_value) = self.lower_expr(end, expr);
                    end = field_end;
                    let Some(field_value) = field_value else {
                        return (end, None);
                    };
                    lowered_fields.push((name.clone(), field_value));
                    field_map.insert(name.clone(), field_value);
                    seq.push(field_value);
                }
                let dest = self.push_eval(
                    end,
                    MirValue::StructLiteral {
                        fields: lowered_fields,
                    },
                    MirValueType::Unknown,
                );
                self.struct_fields.insert(dest, field_map);
                self.aggregate_sequences.insert(dest, seq);
                (end, Some(dest))
            }
            HirExprKind::EnumVariant {
                root,
                variant,
                payload,
            } => {
                let mut end = block;
                let mut lowered_payload = Vec::with_capacity(payload.len());
                for expr in payload {
                    let (payload_end, payload_value) = self.lower_expr(end, expr);
                    end = payload_end;
                    let Some(payload_value) = payload_value else {
                        return (end, None);
                    };
                    lowered_payload.push(payload_value);
                }
                let (tag, tag_bits) = if let Some((tag, bits)) =
                    self.enum_tag_and_bits_for_variant(root.as_deref(), variant)
                {
                    (tag, bits)
                } else if root.is_none() {
                    self.anonymous_variant_tag_for(variant)
                } else {
                    self.diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::Mir,
                            DiagnosticCode::E4005,
                            format!(
                                "cannot resolve enum variant '{}'; use an explicit enum root",
                                variant
                            ),
                        )
                        .with_primary_file_label(
                            self.source_file_path.clone(),
                            Some(expr.span),
                            "qualify the enum variant (for example `MyEnum.Variant`)",
                        ),
                    );
                    (0, 32)
                };
                let tag_value = self.push_eval(
                    end,
                    MirValue::Literal(HirLiteral::Integer(tag.to_string())),
                    MirValueType::Int {
                        signed: false,
                        bits: tag_bits,
                    },
                );
                (
                    end,
                    Some({
                        let enum_value_ty = if lowered_payload.is_empty() {
                            MirValueType::Int {
                                signed: false,
                                bits: tag_bits,
                            }
                        } else {
                            MirValueType::Unknown
                        };
                        let dest = self.push_eval(
                            end,
                            MirValue::EnumVariant {
                                root: root.clone(),
                                variant: variant.clone(),
                                tag,
                                tag_bits,
                                payload: lowered_payload.clone(),
                            },
                            enum_value_ty,
                        );
                        let mut aggregate = Vec::with_capacity(lowered_payload.len() + 1);
                        aggregate.push(tag_value);
                        aggregate.extend(lowered_payload);
                        self.aggregate_sequences.insert(dest, aggregate);
                        dest
                    }),
                )
            }
            HirExprKind::Block { body } => {
                let defer_scope_start = self.deferred.len();
                let mut end = block;
                let mut last = None;
                for value in body {
                    if self.is_terminated(end) {
                        break;
                    }
                    let lowered = self.lower_expr(end, value);
                    end = lowered.0;
                    last = lowered.1;
                }
                if !self.is_terminated(end) {
                    end = self.emit_deferred_since(end, defer_scope_start, None);
                }
                self.deferred.truncate(defer_scope_start);
                (end, last)
            }
            HirExprKind::If {
                condition,
                capture,
                then_branch,
                else_branch,
            } => self.lower_if(
                block,
                condition,
                capture.as_ref(),
                then_branch,
                else_branch.as_deref(),
            ),
            HirExprKind::Return { value } => {
                let return_value = if let Some(value) = value {
                    let (end, lowered) = self.lower_expr(block, value);
                    let deferred_error_value = if self.function_returns_errorable() {
                        lowered.filter(|value_id| self.return_value_is_error_variant(*value_id, 0))
                    } else {
                        None
                    };
                    let end = self.emit_deferred(end, deferred_error_value);
                    self.set_terminator(end, MirTerminator::Return(lowered));
                    return (end, None);
                } else {
                    None
                };
                let block = self.emit_deferred(block, None);
                self.set_terminator(block, MirTerminator::Return(return_value));
                (block, None)
            }
            HirExprKind::Use { path } => {
                let value = self.push_eval(
                    block,
                    MirValue::Use { path: path.clone() },
                    MirValueType::Unknown,
                );

                let target_key =
                    crate::compiler::module_resolver::module_key_for_import(&self.module_key, path);
                if let Some(target_module_id) = self.module_ids_by_key.get(&target_key).copied() {
                    if let Some(exports) = self.module_exports_by_id.get(&target_module_id).cloned()
                    {
                        let mut fields = BTreeMap::new();
                        for export_name in &exports {
                            let qualified = qualified_function_name(target_module_id, export_name);
                            let export_value = self.push_eval(
                                block,
                                MirValue::Ident(qualified),
                                MirValueType::FunctionPointer,
                            );
                            fields.insert(export_name.clone(), export_value);
                        }
                        if !fields.is_empty() {
                            self.struct_fields.insert(value, fields);
                        }
                    }
                }

                (block, Some(value))
            }
            HirExprKind::TypeLiteral(name) => (
                block,
                Some(self.push_eval(
                    block,
                    MirValue::TypeLiteral(name.clone()),
                    MirValueType::Type,
                )),
            ),
            HirExprKind::Comptime { expr } => {
                // Special case: `comp match expr { ... }` — evaluate discriminant at
                // comptime, select the matching arm, then lower that arm's body as
                // regular runtime MIR (only the selected arm is emitted).
                if let HirExprKind::Match { value, arms } = &expr.kind {
                    // First try pure comptime evaluation of the discriminant.
                    let ct_val = self
                        .try_eval_comptime_expr(value, 0)
                        // Fallback: if the discriminant is `$typeof(expr)`, lower `expr`
                        // as MIR and use its inferred type. This handles `comp match
                        // $typeof(v)` when `v` is a runtime parameter whose type is still
                        // statically known (e.g. `v: comp T`).
                        .or_else(|| self.try_eval_typeof_discriminant(block, value));
                    if let Some(ct_val) = ct_val {
                        if let Some(arm) = find_comptime_match_arm(&ct_val, arms) {
                            return self.lower_expr(block, &arm.value);
                        }
                    }
                }
                // Special case: `comp if cond { ... } else { ... }` — evaluate the
                // condition at comptime, then lower only the selected branch as regular
                // runtime MIR (the other branch is never emitted).
                if let HirExprKind::If {
                    condition,
                    then_branch,
                    else_branch,
                    ..
                } = &expr.kind
                {
                    if let Some(ct_cond) = self.try_eval_comptime_expr(condition, 0) {
                        if comptime_truthy(&ct_cond) {
                            return self.lower_expr(block, then_branch);
                        } else if let Some(eb) = else_branch {
                            return self.lower_expr(block, eb);
                        } else {
                            return (block, None);
                        }
                    }
                }
                if let Some(constant) = self.try_eval_comptime_expr(expr, 0) {
                    (block, Some(self.emit_comptime_value(block, constant)))
                } else {
                    self.report_comptime_eval_failure(expr.span);
                    (
                        block,
                        Some(self.push_eval(block, MirValue::Unknown, MirValueType::Unknown)),
                    )
                }
            }
            HirExprKind::Inline { expr } => self.lower_inline_expr(block, expr),
            HirExprKind::Match { value, arms } => self.lower_match(block, value, arms),
            HirExprKind::Unknown => (
                block,
                Some(self.push_eval(block, MirValue::Unknown, MirValueType::Unknown)),
            ),
            HirExprKind::For(for_expr) => self.lower_for(block, for_expr),
            HirExprKind::Break { value } => {
                let mut at = block;
                let mut break_value = None;
                if let Some(value) = value {
                    let (end, lowered) = self.lower_expr(at, value);
                    at = end;
                    break_value = lowered;
                }
                if let Some(ctx) = self.loop_stack.last_mut() {
                    let break_target = ctx.break_target;
                    if let Some(value) = break_value {
                        ctx.break_values.push((at, value));
                    }
                    self.set_terminator(at, MirTerminator::Goto(break_target));
                    (at, None)
                } else if let Some(ctx) = self.or_break_stack.last_mut() {
                    let target = ctx.target;
                    if let Some(value) = break_value {
                        ctx.values.push((at, value));
                    }
                    self.set_terminator(at, MirTerminator::Goto(target));
                    (at, None)
                } else {
                    (
                        at,
                        Some(self.push_eval(at, MirValue::Unknown, MirValueType::Unknown)),
                    )
                }
            }
            HirExprKind::Continue => {
                if let Some(ctx) = self.loop_stack.last().cloned() {
                    self.set_terminator(block, MirTerminator::Goto(ctx.continue_target));
                    (block, None)
                } else {
                    (
                        block,
                        Some(self.push_eval(block, MirValue::Unknown, MirValueType::Unknown)),
                    )
                }
            }
            HirExprKind::Defer {
                error_binding,
                body,
            } => {
                self.deferred.push(DeferredExpr {
                    error_binding: error_binding.clone(),
                    body: (**body).clone(),
                });
                (
                    block,
                    Some(self.push_eval(block, MirValue::Unknown, MirValueType::Unknown)),
                )
            }
            HirExprKind::OptionalUnwrap { value } => self.lower_force_unwrap(block, value, false),
            HirExprKind::ErrorUnwrap { value } => self.lower_force_unwrap(block, value, true),
            HirExprKind::OrElse {
                value,
                error_binding,
                fallback,
            } => self.lower_or_else(block, value, error_binding.as_deref(), fallback),
            HirExprKind::Function {
                params,
                param_types,
                body,
                ..
            } => {
                use std::sync::atomic::{AtomicUsize, Ordering};
                static LAMBDA_COUNTER: AtomicUsize = AtomicUsize::new(0);
                let lambda_id = LAMBDA_COUNTER.fetch_add(1, Ordering::Relaxed);
                let lambda_name = format!("__lambda_{lambda_id}");

                // Compute captures: free vars in body (minus params) that exist in outer scope
                let param_set: BTreeSet<String> = params.iter().cloned().collect();
                let free_vars = collect_free_vars(body, &param_set);
                // Only capture variables that are actually in the current function's locals
                let captures: Vec<(String, MirValueId)> = free_vars
                    .into_iter()
                    .filter_map(|name| self.locals.get(&name).map(|&val| (name, val)))
                    .collect();

                let capture_val_ids: Vec<MirValueId> = captures.iter().map(|(_, v)| *v).collect();
                let capture_names: Vec<String> = captures.iter().map(|(n, _)| n.clone()).collect();

                // Build the hoisted lambda function
                let lambda_fn = MirFunction {
                    name: lambda_name.clone(),
                    def_id: None,
                    return_type: None,
                    // env_ptr as first param, then declared params
                    param_type_hints: std::iter::once(None)
                        .chain(param_types.iter().cloned())
                        .collect(),
                    param_types: std::iter::once(MirValueType::Unknown)
                        .chain(param_types.iter().map(|pt| {
                            pt.as_deref()
                                .map(parse_type_hint)
                                .unwrap_or(MirValueType::Unknown)
                        }))
                        .collect(),
                    blocks: vec![MirBasicBlock {
                        id: MirBlockId(0),
                        instructions: Vec::new(),
                        terminator: None,
                    }],
                    entry: MirBlockId(0),
                };

                // We will build the sub-lowerer manually.
                // First set up env_ptr param (index 0) in the lambda's block.
                // We do this by creating a new FunctionLowerer and pushing params.
                let shared = FunctionLowererShared {
                    function_return_types: self.function_return_types.clone(),
                    function_return_hints: self.function_return_hints.clone(),
                    named_type_literals: self.named_type_literals.clone(),
                    enum_repr_bits_by_name: self.enum_repr_bits_by_name.clone(),
                    enum_variant_tags_by_name: self.enum_variant_tags_by_name.clone(),
                    function_param_names: self.function_param_names.clone(),
                    function_param_defaults: self.function_param_defaults.clone(),
                    function_param_type_hints: self.function_param_type_hints.clone(),
                    function_exprs: self.function_exprs.clone(),
                    inline_function_names: self.inline_function_names.clone(),
                    module_ids_by_key: self.module_ids_by_key.clone(),
                    module_exports_by_id: self.module_exports_by_id.clone(),
                    global_names: self.global_names.clone(),
                    build_config: self.build_config.clone(),
                };
                let mut sub_lowerer = FunctionLowerer {
                    module_key: self.module_key.clone(),
                    source_file_path: self.source_file_path.clone(),
                    function: lambda_fn,
                    next_value: 0,
                    locals: BTreeMap::new(),
                    address_taken_values: BTreeMap::new(),
                    comptime_known_locals: BTreeMap::new(),
                    comptime_local_function_exprs: BTreeMap::new(),
                    value_types: BTreeMap::new(),
                    value_defs: BTreeMap::new(),
                    struct_fields: BTreeMap::new(),
                    aggregate_sequences: BTreeMap::new(),
                    function_return_types: shared.function_return_types,
                    function_return_hints: shared.function_return_hints,
                    errorable_aggregate_values: BTreeSet::new(),
                    errorable_scalar_values: BTreeSet::new(),
                    named_type_literals: shared.named_type_literals,
                    enum_repr_bits_by_name: shared.enum_repr_bits_by_name,
                    enum_variant_tags_by_name: shared.enum_variant_tags_by_name,
                    function_param_names: shared.function_param_names,
                    function_param_defaults: shared.function_param_defaults,
                    function_param_type_hints: shared.function_param_type_hints,
                    function_exprs: shared.function_exprs,
                    inline_function_names: shared.inline_function_names,
                    module_ids_by_key: shared.module_ids_by_key,
                    module_exports_by_id: shared.module_exports_by_id,
                    current_param_type_hints: Vec::new(),
                    current_self_type_hint: None,
                    inline_call_depth: 0,
                    inline_call_stack: Vec::new(),
                    current_inline_module: None,
                    loop_stack: Vec::new(),
                    or_break_stack: Vec::new(),
                    deferred: Vec::new(),
                    diagnostics: Vec::new(),
                    hoisted_lambdas: Vec::new(),
                    global_names: shared.global_names,
                    local_type_hints: BTreeMap::new(),
                    build_config: shared.build_config,
                };

                let lambda_entry = sub_lowerer.function.entry;

                // Push env_ptr as param 0
                let env_ptr_vid = sub_lowerer.push_eval(
                    lambda_entry,
                    MirValue::Param { index: 0 },
                    MirValueType::Unknown,
                );

                // Push capture load instructions for each capture
                for (i, cap_name) in capture_names.iter().enumerate() {
                    let cap_vid = sub_lowerer.push_eval(
                        lambda_entry,
                        MirValue::ClosureEnvField {
                            env_ptr: env_ptr_vid,
                            index: i,
                        },
                        MirValueType::Unknown,
                    );
                    sub_lowerer.locals.insert(cap_name.clone(), cap_vid);
                }

                // Push declared params (index 1..N in the actual function, skipping env_ptr)
                for (idx, param_name) in params.iter().enumerate() {
                    let param_idx = idx + 1; // +1 for env_ptr
                    let ty = param_types
                        .get(idx)
                        .and_then(|s| s.as_deref())
                        .map(parse_type_hint)
                        .unwrap_or(MirValueType::Unknown);
                    let vid = sub_lowerer.push_eval(
                        lambda_entry,
                        MirValue::Param { index: param_idx },
                        ty,
                    );
                    sub_lowerer.locals.insert(param_name.clone(), vid);
                }

                // Lower the body
                let (end_block, ret_val) = sub_lowerer.lower_expr(lambda_entry, body);
                if !sub_lowerer.is_terminated(end_block) {
                    let end_block = sub_lowerer.emit_deferred(end_block, None);
                    sub_lowerer.set_terminator(end_block, MirTerminator::Return(ret_val));
                }

                // Collect hoisted lambdas from the sub-lowerer (for nested closures)
                self.hoisted_lambdas.extend(sub_lowerer.hoisted_lambdas);
                self.hoisted_lambdas.push(sub_lowerer.function);

                // Emit ClosureCreate in the current function
                let closure_val = self.push_eval(
                    block,
                    MirValue::ClosureCreate {
                        fn_symbol: lambda_name,
                        captures: capture_val_ids,
                    },
                    MirValueType::Closure,
                );
                (block, Some(closure_val))
            }
        }
    }

    pub(super) fn lower_or_else(
        &mut self,
        block: MirBlockId,
        value: &HirExpr,
        error_binding: Option<&str>,
        fallback: &HirExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        let (start, value_id) = self.lower_expr(block, value);
        let Some(value_id) = value_id else {
            return (start, None);
        };
        let value_ty = self
            .value_types
            .get(&value_id)
            .cloned()
            .unwrap_or(MirValueType::Unknown);

        let then_block = self.new_block();
        let else_block = self.new_block();
        let join = self.new_block();
        let mut success_value = value_id;
        let mut error_value = value_id;
        let cond = if self.errorable_scalar_values.contains(&value_id) {
            let status_value = self.push_eval(
                start,
                MirValue::ErrorStatus { value: value_id },
                value_ty.clone(),
            );
            let payload_value = self.push_eval(
                start,
                MirValue::ErrorPayload { value: value_id },
                value_ty.clone(),
            );
            success_value = payload_value;
            error_value = status_value;
            self.emit_int_equality_check(start, status_value, 0)
        } else if self.errorable_aggregate_values.contains(&value_id) {
            self.emit_int_equality_check(start, value_id, 0)
        } else {
            self.emit_nonzero_check(start, value_id, &value_ty)
        };
        if !self.is_terminated(start) {
            self.set_terminator(
                start,
                MirTerminator::Branch {
                    condition: cond,
                    then_block,
                    else_block,
                },
            );
        }

        if !self.is_terminated(then_block) {
            self.set_terminator(then_block, MirTerminator::Goto(join));
        }

        self.or_break_stack.push(OrBreakContext {
            target: join,
            values: Vec::new(),
        });
        let prev_error_binding = error_binding.and_then(|binding| {
            self.locals
                .insert(binding.to_string(), error_value)
                .map(|prev| (binding.to_string(), prev))
        });
        let (else_end, else_value) = self.lower_expr(else_block, fallback);
        if let Some(binding) = error_binding {
            if let Some((name, prev)) = prev_error_binding {
                self.locals.insert(name, prev);
            } else {
                self.locals.remove(binding);
            }
        }
        let mut break_ctx = self
            .or_break_stack
            .pop()
            .expect("or-break context should exist");

        let mut fallback_sources = Vec::new();
        if !self.is_terminated(else_end) {
            self.set_terminator(else_end, MirTerminator::Goto(join));
            if let Some(value) = else_value {
                fallback_sources.push((else_end, value));
            }
        }
        fallback_sources.append(&mut break_ctx.values);

        if fallback_sources.is_empty() {
            return (join, Some(success_value));
        }

        let sources = std::iter::once((then_block, success_value))
            .chain(fallback_sources.iter().copied())
            .collect::<Vec<_>>();

        let dest = self.fresh_value();
        let phi_ty = fallback_sources
            .iter()
            .filter_map(|(_, value)| self.value_types.get(value))
            .fold(value_ty.clone(), |left, right| merge_types(&left, right));
        self.function.blocks[join.0]
            .instructions
            .push(MirInstr::Phi {
                dest,
                sources,
                ty: phi_ty.clone(),
            });
        self.value_types.insert(dest, phi_ty);
        (join, Some(dest))
    }

    pub(super) fn lower_inline_expr(
        &mut self,
        block: MirBlockId,
        expr: &HirExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        match &expr.kind {
            HirExprKind::For(HirForExpr::Range {
                start,
                end,
                inclusive,
                binding,
                body,
            }) => {
                self.lower_inline_range_for(block, start, end, *inclusive, binding.as_deref(), body)
            }
            // inline for $fields(v): |f| — unroll over each struct field of v at comptime.
            // For each field, f.name is the field name string and f.value is the field value.
            HirExprKind::For(HirForExpr::Iterate {
                iterable,
                binding,
                body,
            }) if matches!(&iterable.kind, HirExprKind::Call { callee, .. } if matches!(&callee.kind, HirExprKind::Ident(n) if n == "$fields")) =>
            {
                let HirExprKind::Call { args, .. } = &iterable.kind else {
                    unreachable!()
                };
                let arg_expr = args.first().map(|a| a.value.clone());
                let (v_end, v_value) = if let Some(ref e) = arg_expr {
                    self.lower_expr(block, e)
                } else {
                    return (block, None);
                };
                let Some(v_value) = v_value else {
                    return (v_end, None);
                };

                // Resolve the struct type descriptor.
                // First try struct_fields map (when v came from a literal).
                // Then try local_type_hints → named_type_literals lookup.
                let field_pairs: Vec<(String, String)> = {
                    let from_struct_fields: Option<Vec<(String, String)>> = self
                        .struct_fields
                        .get(&v_value)
                        .map(|map| map.keys().map(|k| (k.clone(), String::new())).collect());
                    if let Some(pairs) = from_struct_fields {
                        pairs
                    } else {
                        // Try to get type name from the HIR ident and local_type_hints.
                        let type_name = arg_expr.as_ref().and_then(|e| {
                            if let HirExprKind::Ident(n) = &e.kind {
                                self.local_type_hints
                                    .get(n)
                                    .cloned()
                                    .or_else(|| Some(n.clone()))
                            } else {
                                None
                            }
                        });
                        if let Some(raw_name) = type_name {
                            // Resolve through named_type_literals to get the struct descriptor.
                            let descriptor = self
                                .named_type_literals
                                .get(&raw_name)
                                .cloned()
                                .unwrap_or_else(|| raw_name.clone());
                            struct_field_names_with_types(&descriptor)
                        } else {
                            Vec::new()
                        }
                    }
                };

                let mut at = v_end;
                for (field_name, _field_type) in &field_pairs {
                    if self.is_terminated(at) {
                        break;
                    }
                    // Emit f.name = string literal of the field name.
                    let name_value = self.push_eval(
                        at,
                        MirValue::Literal(HirLiteral::String(field_name.clone())),
                        MirValueType::BytesSlice,
                    );
                    // Emit f.value = v.field_name (runtime field access).
                    let val_value = self.push_eval(
                        at,
                        MirValue::FieldAccess {
                            base: v_value,
                            field: field_name.clone(),
                        },
                        self.infer_field_access_result_type(v_value, field_name, 0),
                    );
                    // Build a synthetic struct value for `f` with fields `name` and `value`.
                    let f_value = self.push_eval(
                        at,
                        MirValue::StructLiteral {
                            fields: vec![
                                ("name".to_string(), name_value),
                                ("value".to_string(), val_value),
                            ],
                        },
                        MirValueType::Unknown,
                    );
                    let mut field_map = BTreeMap::new();
                    field_map.insert("name".to_string(), name_value);
                    field_map.insert("value".to_string(), val_value);
                    self.struct_fields.insert(f_value, field_map);

                    let previous = binding
                        .as_deref()
                        .map(|bind_name| self.save_local_binding(bind_name, f_value));

                    let (body_end, _) = self.lower_expr(at, body);
                    at = body_end;

                    if let Some(saved) = previous {
                        self.restore_saved_local_binding(saved);
                    }
                }
                if !self.is_terminated(at) {
                    let unit = self.push_eval(
                        at,
                        MirValue::Literal(HirLiteral::Integer("0".to_string())),
                        MirValueType::Int {
                            signed: false,
                            bits: 64,
                        },
                    );
                    return (at, Some(unit));
                }
                (at, None)
            }
            // inline for tuple: |v| — unroll each element of a tuple/anonymous-struct literal
            HirExprKind::For(HirForExpr::Iterate {
                iterable,
                binding,
                body,
            }) if matches!(
                &iterable.kind,
                HirExprKind::StructLiteral {
                    root_type: None,
                    ..
                }
            ) =>
            {
                let HirExprKind::StructLiteral { fields, .. } = &iterable.kind else {
                    unreachable!()
                };
                let fields = fields.clone();
                let mut at = block;
                for (_, element_expr) in &fields {
                    if self.is_terminated(at) {
                        break;
                    }
                    let (elem_end, elem_value) = self.lower_expr(at, element_expr);
                    at = elem_end;

                    let previous = if let Some(name) = binding {
                        let Some(elem_value) = elem_value else {
                            continue;
                        };
                        Some(self.save_local_binding(name, elem_value))
                    } else {
                        None
                    };

                    let (body_end, _) = self.lower_expr(at, body);
                    at = body_end;

                    if let Some(saved) = previous {
                        self.restore_saved_local_binding(saved);
                    }
                }
                if !self.is_terminated(at) {
                    let unit = self.push_eval(
                        at,
                        MirValue::Literal(HirLiteral::Integer("0".to_string())),
                        MirValueType::Int {
                            signed: false,
                            bits: 64,
                        },
                    );
                    return (at, Some(unit));
                }
                (at, None)
            }
            // inline for ident: |v| — when the ident is a comp param bound to a MIR tuple,
            // unroll over its indexed fields (__0, __1, …) at comptime.
            HirExprKind::For(HirForExpr::Iterate {
                iterable,
                binding,
                body,
            }) if matches!(&iterable.kind, HirExprKind::Ident(_)) => {
                let HirExprKind::Ident(ident_name) = &iterable.kind else {
                    unreachable!()
                };
                let maybe_fields: Option<Vec<MirValueId>> =
                    self.locals.get(ident_name.as_str()).copied().and_then(|v| {
                        self.struct_fields.get(&v).map(|fields| {
                            // Collect __0, __1, … fields in numeric order.
                            let mut indexed: Vec<(usize, MirValueId)> = fields
                                .iter()
                                .filter_map(|(k, &vid)| {
                                    k.strip_prefix("__")
                                        .and_then(|n| n.parse::<usize>().ok())
                                        .map(|idx| (idx, vid))
                                })
                                .collect();
                            indexed.sort_by_key(|(idx, _)| *idx);
                            indexed.into_iter().map(|(_, vid)| vid).collect()
                        })
                    });
                if let Some(element_values) = maybe_fields {
                    let mut at = block;
                    for elem_value in element_values {
                        if self.is_terminated(at) {
                            break;
                        }
                        let previous = binding
                            .as_deref()
                            .map(|name| self.save_local_binding(name, elem_value));
                        let (body_end, _) = self.lower_expr(at, body);
                        at = body_end;
                        if let Some(saved) = previous {
                            self.restore_saved_local_binding(saved);
                        }
                    }
                    if !self.is_terminated(at) {
                        let unit = self.push_eval(
                            at,
                            MirValue::Literal(HirLiteral::Integer("0".to_string())),
                            MirValueType::Int {
                                signed: false,
                                bits: 64,
                            },
                        );
                        return (at, Some(unit));
                    }
                    (at, None)
                } else {
                    // Fall back to a regular runtime for loop.
                    self.lower_expr(block, expr)
                }
            }
            HirExprKind::Call { callee, args } => self.lower_call_expr(block, callee, args, true),
            _ => self.lower_expr(block, expr),
        }
    }

    pub(super) fn lower_inline_range_for(
        &mut self,
        block: MirBlockId,
        start: &HirExpr,
        end: &HirExpr,
        inclusive: bool,
        binding: Option<&str>,
        body: &HirExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        let Some(start_value) = self.comptime_i64(start) else {
            return self.lower_range_loop(block, start, end, inclusive, binding, body);
        };
        let Some(end_value_raw) = self.comptime_i64(end) else {
            return self.lower_range_loop(block, start, end, inclusive, binding, body);
        };
        let end_value = if inclusive {
            match end_value_raw.checked_add(1) {
                Some(next) => next,
                None => end_value_raw,
            }
        } else {
            end_value_raw
        };

        let mut at = block;
        if start_value < end_value {
            for idx in start_value..end_value {
                if self.is_terminated(at) {
                    break;
                }
                let previous = if let Some(name) = binding {
                    let iter_value = self.push_eval(
                        at,
                        MirValue::Literal(HirLiteral::Integer(idx.to_string())),
                        MirValueType::Int {
                            signed: true,
                            bits: 64,
                        },
                    );
                    Some(self.save_local_binding(name, iter_value))
                } else {
                    None
                };

                let (next, _) = self.lower_expr(at, body);
                at = next;

                if let Some(saved) = previous {
                    self.restore_saved_local_binding(saved);
                }
            }
        }

        if self.is_terminated(at) {
            (at, None)
        } else {
            (
                at,
                Some(self.push_eval(at, MirValue::Unknown, MirValueType::Unknown)),
            )
        }
    }

    pub(super) fn lower_call_expr(
        &mut self,
        block: MirBlockId,
        callee: &HirExpr,
        args: &[HirCallArg],
        force_inline: bool,
    ) -> (MirBlockId, Option<MirValueId>) {
        if let HirExprKind::Ident(name) = &callee.kind {
            if self.should_force_comptime_call(name) {
                let call_expr = HirExpr {
                    kind: HirExprKind::Call {
                        callee: Box::new(callee.clone()),
                        args: args.to_vec(),
                    },
                    span: callee.span,
                };
                if let Some(constant) = self.try_eval_comptime_expr(&call_expr, 0) {
                    let value = self.emit_comptime_value(block, constant);
                    return (block, Some(value));
                }
            }
            if let Some((end, value)) = self.try_lower_builtin_call(block, name, args) {
                return (end, value);
            }
        }

        let (mut end, callee_value) = self.lower_expr(block, callee);
        let Some(callee_value) = callee_value else {
            return (end, None);
        };
        let mut lowered_args = Vec::with_capacity(args.len());
        let mut lowered_named = Vec::with_capacity(args.len());
        for arg in args {
            let (arg_end, arg_value) = self.lower_expr(end, &arg.value);
            end = arg_end;
            let Some(arg_value) = arg_value else {
                return (end, None);
            };
            lowered_args.push(arg_value);
            lowered_named.push((arg.name.clone(), arg_value));
        }
        let callee_name = if let Some(name) = self.resolve_callee_function_name(callee_value, 0) {
            Some(name)
        } else if let HirExprKind::Ident(name) = &callee.kind {
            Some(name.clone())
        } else {
            None
        };

        if let Some(name) = &callee_name {
            if let Some(param_names) = self.function_param_names.get(name) {
                let mut ordered = self.order_named_call_items(param_names, &lowered_named);

                if let Some(defaults) = self.function_param_defaults.get(name).cloned() {
                    for (idx, slot) in ordered.iter_mut().enumerate() {
                        if slot.is_none() {
                            if let Some(Some(default_expr)) = defaults.get(idx) {
                                let (default_end, default_value) =
                                    self.lower_expr(end, default_expr);
                                end = default_end;
                                if let Some(default_value) = default_value {
                                    *slot = Some(default_value);
                                }
                            }
                        }
                    }
                }

                if ordered.iter().all(|slot| slot.is_some()) {
                    lowered_args = ordered.into_iter().flatten().collect();
                }
            }
        }

        let should_inline = force_inline
            || callee_name
                .as_ref()
                .map(|name| self.inline_function_names.contains(name))
                .unwrap_or(false);
        if should_inline {
            if let Some(name) = &callee_name {
                if let Some((inline_end, inline_value)) =
                    self.try_inline_named_call(end, name, &lowered_args)
                {
                    return (inline_end, inline_value);
                }
            }
        }

        let result_ty = self.infer_call_result_type(callee_value, 0);
        let call_id = self.push_eval(
            end,
            MirValue::Call {
                callee: callee_value,
                args: lowered_args,
            },
            result_ty,
        );
        if let Some(name) = callee_name {
            if self.function_returns_errorable_aggregate(&name) {
                self.errorable_aggregate_values.insert(call_id);
            } else if self.function_returns_errorable_scalar(&name) {
                self.errorable_scalar_values.insert(call_id);
            }
        }
        (end, Some(call_id))
    }

    pub(super) fn try_inline_named_call(
        &mut self,
        block: MirBlockId,
        callee_name: &str,
        args: &[MirValueId],
    ) -> Option<(MirBlockId, Option<MirValueId>)> {
        if self.inline_call_depth >= 32 {
            return None;
        }
        if self
            .inline_call_stack
            .iter()
            .any(|active| active == callee_name)
        {
            return None;
        }

        let function_expr = self
            .function_exprs
            .get(callee_name)
            .cloned()
            .or_else(|| self.comptime_local_function_exprs.get(callee_name).cloned())?;
        let (params, body) = extract_inline_function_body(&function_expr)?;
        if params.len() != args.len() {
            return None;
        }
        let inline_body = normalize_inline_hir_body(body);
        if !inline_hir_body_supported(&inline_body) {
            return None;
        }

        let mut previous = Vec::with_capacity(params.len());
        for (param, value) in params.iter().zip(args.iter()) {
            previous.push(self.save_local_binding(param, *value));
        }

        // Track the module of the function being inlined so that unqualified ident
        // references in its body (e.g. `print_impl` inside `println`) can be resolved
        // to their qualified names (e.g. `#8::print_impl`) in the caller's context.
        let inline_module = callee_name.find("::").map(|i| callee_name[..i].to_string());
        let prev_inline_module = self.current_inline_module.clone();
        if inline_module.is_some() {
            self.current_inline_module = inline_module;
        }
        self.inline_call_depth += 1;
        self.inline_call_stack.push(callee_name.to_string());
        let (end, value) = self.lower_expr(block, &inline_body);
        self.inline_call_stack.pop();
        self.inline_call_depth -= 1;
        self.current_inline_module = prev_inline_module;

        for saved in previous.into_iter().rev() {
            self.restore_saved_local_binding(saved);
        }

        Some((end, value))
    }

    pub(super) fn comptime_i64(&mut self, expr: &HirExpr) -> Option<i64> {
        let value = self.try_eval_comptime_expr(expr, 0)?;
        match value {
            ComptimeValue::Literal(HirLiteral::Integer(text)) => text.parse::<i64>().ok(),
            ComptimeValue::Literal(HirLiteral::Char(ch)) => Some(ch as i64),
            _ => None,
        }
    }

    pub(super) fn emit_nonzero_check(
        &mut self,
        block: MirBlockId,
        value: MirValueId,
        value_ty: &MirValueType,
    ) -> MirValueId {
        let zero_literal = match value_ty {
            MirValueType::Float { .. } => HirLiteral::Float("0.0".to_string()),
            MirValueType::Bool => HirLiteral::Bool(false),
            _ => HirLiteral::Integer("0".to_string()),
        };
        let zero = self.push_eval(block, MirValue::Literal(zero_literal), value_ty.clone());
        self.push_eval(
            block,
            MirValue::Binary {
                op: crate::compiler::ast::BinaryOp::Ne,
                left: value,
                right: zero,
            },
            MirValueType::Bool,
        )
    }

    pub(super) fn emit_int_equality_check(
        &mut self,
        block: MirBlockId,
        value: MirValueId,
        rhs: i64,
    ) -> MirValueId {
        let rhs_value = self.push_eval(
            block,
            MirValue::Literal(HirLiteral::Integer(rhs.to_string())),
            MirValueType::Int {
                signed: true,
                bits: 32,
            },
        );
        self.push_eval(
            block,
            MirValue::Binary {
                op: crate::compiler::ast::BinaryOp::Eq,
                left: value,
                right: rhs_value,
            },
            MirValueType::Bool,
        )
    }

    pub(super) fn lower_force_unwrap(
        &mut self,
        block: MirBlockId,
        value_expr: &HirExpr,
        is_error_unwrap: bool,
    ) -> (MirBlockId, Option<MirValueId>) {
        let (start, value_id) = self.lower_expr(block, value_expr);
        let Some(value_id) = value_id else {
            return (start, None);
        };
        let value_ty = self
            .value_types
            .get(&value_id)
            .cloned()
            .unwrap_or(MirValueType::Unknown);
        let mut success_value = value_id;
        let mut error_value = value_id;
        let cond = if self.errorable_scalar_values.contains(&value_id) {
            let status_value = self.push_eval(
                start,
                MirValue::ErrorStatus { value: value_id },
                value_ty.clone(),
            );
            let payload_value = self.push_eval(
                start,
                MirValue::ErrorPayload { value: value_id },
                value_ty.clone(),
            );
            success_value = payload_value;
            error_value = status_value;
            self.emit_int_equality_check(start, status_value, 0)
        } else if self.errorable_aggregate_values.contains(&value_id) {
            self.emit_int_equality_check(start, value_id, 0)
        } else {
            self.emit_nonzero_check(start, value_id, &value_ty)
        };

        let ok_block = self.new_block();
        let fail_block = self.new_block();
        if !self.is_terminated(start) {
            self.set_terminator(
                start,
                MirTerminator::Branch {
                    condition: cond,
                    then_block: ok_block,
                    else_block: fail_block,
                },
            );
        }

        let fail_end = self.emit_deferred(
            fail_block,
            if is_error_unwrap {
                Some(error_value)
            } else {
                None
            },
        );
        if !self.is_terminated(fail_end) {
            if is_error_unwrap && self.function_returns_errorable() {
                let return_value = if self.errorable_aggregate_values.contains(&value_id) {
                    value_id
                } else if self.errorable_scalar_values.contains(&value_id) {
                    error_value
                } else {
                    let zero_literal = match value_ty {
                        MirValueType::Float { .. } => HirLiteral::Float("0.0".to_string()),
                        MirValueType::Bool => HirLiteral::Bool(false),
                        _ => HirLiteral::Integer("0".to_string()),
                    };
                    self.push_eval(fail_end, MirValue::Literal(zero_literal), value_ty.clone())
                };
                self.set_terminator(fail_end, MirTerminator::Return(Some(return_value)));
            } else {
                self.set_terminator(fail_end, MirTerminator::Unreachable);
            }
        }

        (ok_block, Some(success_value))
    }

    pub(super) fn function_returns_errorable(&self) -> bool {
        self.function
            .return_type
            .as_ref()
            .is_some_and(|hint| hint.contains('!'))
    }

    pub(super) fn return_value_is_error_variant(&self, value_id: MirValueId, depth: usize) -> bool {
        if depth > 16 {
            return false;
        }

        match self.value_defs.get(&value_id) {
            Some(MirValue::EnumVariant { payload, .. }) => payload.is_empty(),
            Some(MirValue::Cast { value, .. })
            | Some(MirValue::Assign { value, .. })
            | Some(MirValue::LocalSet { value, .. }) => {
                self.return_value_is_error_variant(*value, depth + 1)
            }
            _ => false,
        }
    }

    fn should_track_address_taken_local(&self, value_id: MirValueId) -> bool {
        !self.value_is_aggregate_like(value_id, 0)
    }

    fn track_aggregate_slice_view(
        &mut self,
        dest: MirValueId,
        base_value: MirValueId,
        start: Option<MirValueId>,
        end: Option<MirValueId>,
        inclusive: bool,
    ) {
        let Some(sequence) = self.aggregate_sequences.get(&base_value).cloned() else {
            return;
        };
        let Some((start_idx, end_idx)) =
            self.aggregate_slice_bounds(sequence.len(), start, end, inclusive)
        else {
            return;
        };
        self.aggregate_sequences
            .insert(dest, sequence[start_idx..end_idx].to_vec());
    }

    fn aggregate_slice_bounds(
        &self,
        sequence_len: usize,
        start: Option<MirValueId>,
        end: Option<MirValueId>,
        inclusive: bool,
    ) -> Option<(usize, usize)> {
        let start_idx = start
            .and_then(|value| self.literal_int_value(value))
            .unwrap_or(0)
            .max(0) as usize;
        let mut end_idx = end
            .and_then(|value| self.literal_int_value(value))
            .map(|value| value.max(0) as usize)
            .unwrap_or(sequence_len);
        if inclusive {
            end_idx = end_idx.saturating_add(1);
        }

        let clamped_start = start_idx.min(sequence_len);
        let clamped_end = end_idx.min(sequence_len);
        (clamped_start <= clamped_end).then_some((clamped_start, clamped_end))
    }

    fn next_passthrough_access_base(&self, base_value: MirValueId) -> Option<MirValueId> {
        match self.value_defs.get(&base_value) {
            Some(MirValue::Cast { value, .. })
            | Some(MirValue::Assign { value, .. })
            | Some(MirValue::LocalSet { value, .. })
            | Some(MirValue::DerefAccess { base: value }) => Some(*value),
            _ => None,
        }
    }

    fn value_type_is_bytes_slice(&self, value_id: MirValueId) -> bool {
        self.value_types
            .get(&value_id)
            .is_some_and(|ty| matches!(ty, MirValueType::BytesSlice))
    }

    fn infer_field_access_result_type(
        &self,
        base_value: MirValueId,
        field: &str,
        depth: usize,
    ) -> MirValueType {
        if depth > 16 {
            return MirValueType::Unknown;
        }
        if field == "len" && self.value_type_is_bytes_slice(base_value) {
            return MirValueType::Int {
                signed: false,
                bits: 64,
            };
        }
        if let Some(fields) = self.struct_fields.get(&base_value) {
            if let Some(value) = fields.get(field) {
                return self
                    .value_types
                    .get(value)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown);
            }
        }
        if let Some(next_value) = self.next_passthrough_access_base(base_value) {
            return self.infer_field_access_result_type(next_value, field, depth + 1);
        }
        MirValueType::Unknown
    }

    fn infer_index_result_type(&self, base_value: MirValueId, depth: usize) -> MirValueType {
        if depth > 16 {
            return MirValueType::Unknown;
        }
        if let Some(sequence) = self.aggregate_sequences.get(&base_value) {
            if let Some(first) = sequence.first() {
                return self
                    .value_types
                    .get(first)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown);
            }
        }
        if self.value_type_is_bytes_slice(base_value) {
            return MirValueType::Int {
                signed: false,
                bits: 8,
            };
        }
        if let Some(next_value) = self.next_passthrough_access_base(base_value) {
            return self.infer_index_result_type(next_value, depth + 1);
        }
        MirValueType::Unknown
    }

    fn infer_slice_result_type(&self, base_value: MirValueId, depth: usize) -> MirValueType {
        if depth > 16 {
            return MirValueType::Unknown;
        }
        if self.value_type_is_bytes_slice(base_value) {
            return MirValueType::BytesSlice;
        }
        if let Some(next_value) = self.next_passthrough_access_base(base_value) {
            return self.infer_slice_result_type(next_value, depth + 1);
        }
        MirValueType::Unknown
    }

    fn value_is_aggregate_like(&self, value_id: MirValueId, depth: usize) -> bool {
        if depth > 16 {
            return false;
        }
        if self.aggregate_sequences.contains_key(&value_id)
            || self.struct_fields.contains_key(&value_id)
        {
            return true;
        }
        match self.value_defs.get(&value_id) {
            Some(MirValue::StructLiteral { .. }) => true,
            Some(MirValue::EnumVariant { payload, .. }) => !payload.is_empty(),
            Some(MirValue::Cast { value, .. })
            | Some(MirValue::Assign { value, .. })
            | Some(MirValue::LocalSet { value, .. }) => {
                self.value_is_aggregate_like(*value, depth + 1)
            }
            _ => false,
        }
    }

    fn invalidate_address_taken_aggregate_view(&mut self, value_id: MirValueId, depth: usize) {
        if depth > 16 {
            return;
        }
        self.aggregate_sequences.remove(&value_id);
        self.struct_fields.remove(&value_id);
        match self.value_defs.get(&value_id) {
            Some(MirValue::Cast { value, .. })
            | Some(MirValue::Assign { value, .. })
            | Some(MirValue::LocalSet { value, .. }) => {
                self.invalidate_address_taken_aggregate_view(*value, depth + 1)
            }
            _ => {}
        }
    }

    pub(super) fn emit_deferred(
        &mut self,
        block: MirBlockId,
        error_value: Option<MirValueId>,
    ) -> MirBlockId {
        self.emit_deferred_since(block, 0, error_value)
    }

    pub(super) fn emit_deferred_since(
        &mut self,
        block: MirBlockId,
        start: usize,
        error_value: Option<MirValueId>,
    ) -> MirBlockId {
        let mut at = block;
        let deferred = self.deferred[start.min(self.deferred.len())..].to_vec();
        for deferred_expr in deferred.iter().rev() {
            if self.is_terminated(at) {
                break;
            }
            match (&deferred_expr.error_binding, error_value) {
                (Some(binding), Some(value)) => {
                    let prev = self.save_local_binding(binding, value);
                    let (end, _) = self.lower_expr(at, &deferred_expr.body);
                    at = end;
                    self.restore_saved_local_binding(prev);
                }
                (Some(_), None) => {}
                (None, _) => {
                    let (end, _) = self.lower_expr(at, &deferred_expr.body);
                    at = end;
                }
            }
        }
        at
    }
}

impl FunctionLowerer {
    pub(super) fn lower_for(
        &mut self,
        block: MirBlockId,
        for_expr: &HirForExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        match for_expr {
            HirForExpr::Infinite { body } => self.lower_infinite_loop(block, body),
            HirForExpr::WhileLike { condition, body } => {
                self.lower_while_like_loop(block, condition, body)
            }
            HirForExpr::Range {
                start,
                end,
                inclusive,
                binding,
                body,
            } => self.lower_range_loop(block, start, end, *inclusive, binding.as_deref(), body),
            HirForExpr::Iterate {
                iterable,
                binding,
                body,
            } => self.lower_iterate_loop(block, iterable, binding.as_deref(), body),
        }
    }

    pub(super) fn set_goto_if_not_terminated(&mut self, from: MirBlockId, to: MirBlockId) {
        if !self.is_terminated(from) {
            self.set_terminator(from, MirTerminator::Goto(to));
        }
    }

    pub(super) fn push_loop_context(
        &mut self,
        continue_target: MirBlockId,
        break_target: MirBlockId,
    ) {
        self.loop_stack.push(LoopContext {
            continue_target,
            break_target,
            break_values: Vec::new(),
        });
    }

    pub(super) fn finish_loop(&mut self, exit: MirBlockId) -> (MirBlockId, Option<MirValueId>) {
        let ctx = self.loop_stack.pop().expect("loop context should exist");
        (exit, self.build_loop_break_value(exit, ctx.break_values))
    }

    pub(super) fn append_loop_phi_source(
        &mut self,
        header: MirBlockId,
        backedge_block: MirBlockId,
        next_value: MirValueId,
    ) {
        if let Some(MirInstr::Phi { sources, .. }) =
            self.function.blocks[header.0].instructions.first_mut()
        {
            sources.push((backedge_block, next_value));
        }
    }

    pub(super) fn prepare_loop_carried_locals(
        &mut self,
        header: MirBlockId,
        incoming_block: MirBlockId,
        body: &HirExpr,
    ) -> Vec<(String, MirValueId)> {
        let mut carried = Vec::new();
        for name in assigned_local_names(body) {
            let Some(current) = self.locals.get(&name).copied() else {
                continue;
            };
            let ty = self
                .value_types
                .get(&current)
                .cloned()
                .unwrap_or(MirValueType::Unknown);
            let phi = self.fresh_value();
            self.function.blocks[header.0]
                .instructions
                .push(MirInstr::Phi {
                    dest: phi,
                    sources: vec![(incoming_block, current)],
                    ty,
                });
            self.value_types.insert(
                phi,
                self.value_types
                    .get(&current)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown),
            );
            self.locals.insert(name.clone(), phi);
            carried.push((name, phi));
        }
        carried
    }

    pub(super) fn finalize_loop_carried_locals(
        &mut self,
        header: MirBlockId,
        backedge_block: MirBlockId,
        carried: &[(String, MirValueId)],
    ) {
        for (name, phi) in carried {
            let source = self.locals.get(name).copied().unwrap_or(*phi);
            for instr in &mut self.function.blocks[header.0].instructions {
                if let MirInstr::Phi { dest, sources, .. } = instr {
                    if *dest == *phi {
                        sources.push((backedge_block, source));
                        break;
                    }
                }
            }
            self.locals.insert(name.clone(), *phi);
        }
    }

    fn inferred_sequence_element_type(&self, value_id: MirValueId) -> MirValueType {
        self.aggregate_sequences
            .get(&value_id)
            .and_then(|sequence| sequence.first())
            .and_then(|first| self.value_types.get(first))
            .cloned()
            .unwrap_or(MirValueType::Unknown)
    }

    fn value_from_sequence_or_index(
        &mut self,
        block: MirBlockId,
        base: MirValueId,
        sequence_value: Option<MirValueId>,
        position: usize,
        result_ty: MirValueType,
    ) -> MirValueId {
        sequence_value.unwrap_or_else(|| {
            let index_value = self.push_eval(
                block,
                MirValue::Literal(HirLiteral::Integer(position.to_string())),
                MirValueType::Int {
                    signed: false,
                    bits: 32,
                },
            );
            self.push_eval(
                block,
                MirValue::Index {
                    base,
                    index: index_value,
                },
                result_ty,
            )
        })
    }

    pub(super) fn lower_range_loop(
        &mut self,
        block: MirBlockId,
        start: &HirExpr,
        end: &HirExpr,
        inclusive: bool,
        binding: Option<&str>,
        body: &HirExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        let (after_start, start_value) = self.lower_expr(block, start);
        let Some(start_value) = start_value else {
            return (after_start, None);
        };
        let (after_end, end_value) = self.lower_expr(after_start, end);
        let Some(end_value) = end_value else {
            return (after_end, None);
        };

        let iter_ty = self
            .value_types
            .get(&start_value)
            .cloned()
            .zip(self.value_types.get(&end_value).cloned())
            .map(|(left, right)| merge_types(&left, &right))
            .unwrap_or_else(|| {
                self.value_types
                    .get(&start_value)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown)
            });

        let header = self.new_block();
        let body_block = self.new_block();
        let step_block = self.new_block();
        let exit = self.new_block();

        self.set_goto_if_not_terminated(after_end, header);

        let iter_value = self.fresh_value();
        self.function.blocks[header.0]
            .instructions
            .push(MirInstr::Phi {
                dest: iter_value,
                sources: vec![(after_end, start_value)],
                ty: iter_ty.clone(),
            });
        self.value_types.insert(iter_value, iter_ty.clone());

        let carried = self.prepare_loop_carried_locals(header, after_end, body);

        let cond_op = if inclusive {
            crate::compiler::ast::BinaryOp::Le
        } else {
            crate::compiler::ast::BinaryOp::Lt
        };
        let cond = self.push_eval(
            header,
            MirValue::Binary {
                op: cond_op,
                left: iter_value,
                right: end_value,
            },
            MirValueType::Bool,
        );
        if !self.is_terminated(header) {
            self.set_terminator(
                header,
                MirTerminator::Branch {
                    condition: cond,
                    then_block: body_block,
                    else_block: exit,
                },
            );
        }

        self.push_loop_context(step_block, exit);

        let prev_binding = binding.map(|name| self.save_local_binding(name, iter_value));
        let (body_end, _) = self.lower_expr(body_block, body);
        if let Some(saved) = prev_binding {
            self.restore_saved_local_binding(saved);
        }
        self.set_goto_if_not_terminated(body_end, step_block);

        let one_literal = match iter_ty {
            MirValueType::Float { .. } => HirLiteral::Float("1.0".to_string()),
            _ => HirLiteral::Integer("1".to_string()),
        };
        let one = self.push_eval(step_block, MirValue::Literal(one_literal), iter_ty.clone());
        let next_iter = self.push_eval(
            step_block,
            MirValue::Binary {
                op: crate::compiler::ast::BinaryOp::Add,
                left: iter_value,
                right: one,
            },
            iter_ty,
        );
        self.append_loop_phi_source(header, step_block, next_iter);
        self.finalize_loop_carried_locals(header, step_block, &carried);
        self.set_goto_if_not_terminated(step_block, header);

        self.finish_loop(exit)
    }

    pub(super) fn lower_iterate_loop(
        &mut self,
        block: MirBlockId,
        iterable: &HirExpr,
        binding: Option<&str>,
        body: &HirExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        let (after_iterable, iterable_value) = self.lower_expr(block, iterable);
        let Some(iterable_value) = iterable_value else {
            return (after_iterable, None);
        };

        let len = self
            .aggregate_sequences
            .get(&iterable_value)
            .map(|values| values.len())
            .unwrap_or(0);

        let index_ty = MirValueType::Int {
            signed: false,
            bits: 64,
        };
        let index_start = self.push_eval(
            after_iterable,
            MirValue::Literal(HirLiteral::Integer("0".to_string())),
            index_ty.clone(),
        );
        let len_value = self.push_eval(
            after_iterable,
            MirValue::Literal(HirLiteral::Integer(len.to_string())),
            index_ty.clone(),
        );

        let header = self.new_block();
        let body_block = self.new_block();
        let step_block = self.new_block();
        let exit = self.new_block();

        self.set_goto_if_not_terminated(after_iterable, header);

        let index_value = self.fresh_value();
        self.function.blocks[header.0]
            .instructions
            .push(MirInstr::Phi {
                dest: index_value,
                sources: vec![(after_iterable, index_start)],
                ty: index_ty.clone(),
            });
        self.value_types.insert(index_value, index_ty.clone());

        let carried = self.prepare_loop_carried_locals(header, after_iterable, body);

        let cond = self.push_eval(
            header,
            MirValue::Binary {
                op: crate::compiler::ast::BinaryOp::Lt,
                left: index_value,
                right: len_value,
            },
            MirValueType::Bool,
        );
        if !self.is_terminated(header) {
            self.set_terminator(
                header,
                MirTerminator::Branch {
                    condition: cond,
                    then_block: body_block,
                    else_block: exit,
                },
            );
        }

        self.push_loop_context(step_block, exit);

        let (body_start, prev_binding) = if let Some(name) = binding {
            let element_value = if self
                .aggregate_sequences
                .get(&iterable_value)
                .is_some_and(Vec::is_empty)
            {
                self.push_eval(body_block, MirValue::Unknown, MirValueType::Unknown)
            } else {
                self.push_eval(
                    body_block,
                    MirValue::Index {
                        base: iterable_value,
                        index: index_value,
                    },
                    self.inferred_sequence_element_type(iterable_value),
                )
            };
            let prev = self.save_local_binding(name, element_value);
            (body_block, Some(prev))
        } else {
            (body_block, None)
        };

        let (body_end, _) = self.lower_expr(body_start, body);
        if let Some(saved) = prev_binding {
            self.restore_saved_local_binding(saved);
        }
        self.set_goto_if_not_terminated(body_end, step_block);

        let one = self.push_eval(
            step_block,
            MirValue::Literal(HirLiteral::Integer("1".to_string())),
            index_ty.clone(),
        );
        let next_index = self.push_eval(
            step_block,
            MirValue::Binary {
                op: crate::compiler::ast::BinaryOp::Add,
                left: index_value,
                right: one,
            },
            index_ty,
        );
        self.append_loop_phi_source(header, step_block, next_index);
        self.finalize_loop_carried_locals(header, step_block, &carried);
        self.set_goto_if_not_terminated(step_block, header);

        self.finish_loop(exit)
    }

    pub(super) fn lower_infinite_loop(
        &mut self,
        block: MirBlockId,
        body: &HirExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        let header = self.new_block();
        let body_block = self.new_block();
        let exit = self.new_block();

        self.set_goto_if_not_terminated(block, header);
        self.set_goto_if_not_terminated(header, body_block);

        self.push_loop_context(header, exit);

        let (body_end, _) = self.lower_expr(body_block, body);
        self.set_goto_if_not_terminated(body_end, header);

        self.finish_loop(exit)
    }

    pub(super) fn lower_while_like_loop(
        &mut self,
        block: MirBlockId,
        condition: &HirExpr,
        body: &HirExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        let header = self.new_block();
        let body_block = self.new_block();
        let step_block = self.new_block();
        let exit = self.new_block();

        self.set_goto_if_not_terminated(block, header);

        let carried = self.prepare_loop_carried_locals(header, block, body);

        let (cond_end, cond_value) = self.lower_expr(header, condition);
        let cond_value = cond_value.unwrap_or_else(|| {
            self.push_eval(
                cond_end,
                MirValue::Literal(HirLiteral::Bool(false)),
                MirValueType::Bool,
            )
        });
        if !self.is_terminated(cond_end) {
            self.set_terminator(
                cond_end,
                MirTerminator::Branch {
                    condition: cond_value,
                    then_block: body_block,
                    else_block: exit,
                },
            );
        }

        self.push_loop_context(step_block, exit);
        let (body_end, _) = self.lower_expr(body_block, body);
        self.set_goto_if_not_terminated(body_end, step_block);
        self.finalize_loop_carried_locals(header, step_block, &carried);
        self.set_goto_if_not_terminated(step_block, header);

        self.finish_loop(exit)
    }

    pub(super) fn build_loop_break_value(
        &mut self,
        exit: MirBlockId,
        break_values: Vec<(MirBlockId, MirValueId)>,
    ) -> Option<MirValueId> {
        if break_values.is_empty() {
            return None;
        }
        if break_values.len() == 1 {
            return Some(break_values[0].1);
        }

        let dest = self.fresh_value();
        let phi_ty = break_values
            .iter()
            .filter_map(|(_, value)| self.value_types.get(value))
            .cloned()
            .reduce(|left, right| merge_types(&left, &right))
            .unwrap_or(MirValueType::Unknown);
        self.function.blocks[exit.0]
            .instructions
            .push(MirInstr::Phi {
                dest,
                sources: break_values,
                ty: phi_ty.clone(),
            });
        self.value_types.insert(dest, phi_ty);
        Some(dest)
    }

    fn order_named_call_items<T: Copy>(
        &self,
        param_names: &[String],
        args: &[(Option<String>, T)],
    ) -> Vec<Option<T>> {
        let mut ordered = vec![None; param_names.len()];
        let mut positional_cursor = 0usize;

        for (arg_name, value) in args {
            if let Some(arg_name) = arg_name {
                if let Some(index) = param_names.iter().position(|param| param == arg_name) {
                    ordered[index] = Some(*value);
                }
                continue;
            }

            while positional_cursor < ordered.len() && ordered[positional_cursor].is_some() {
                positional_cursor += 1;
            }
            if positional_cursor < ordered.len() {
                ordered[positional_cursor] = Some(*value);
                positional_cursor += 1;
            }
        }

        ordered
    }

    pub(super) fn lower_match(
        &mut self,
        block: MirBlockId,
        scrutinee: &HirExpr,
        arms: &[crate::compiler::hir::HirMatchArm],
    ) -> (MirBlockId, Option<MirValueId>) {
        let (start_test, scrutinee_value) = self.lower_expr(block, scrutinee);
        let Some(scrutinee_value) = scrutinee_value else {
            return (start_test, None);
        };

        let join = self.new_block();
        let mut test_block = start_test;
        let mut join_sources: Vec<(MirBlockId, MirValueId)> = Vec::new();

        for (idx, arm) in arms.iter().enumerate() {
            let arm_block = self.new_block();
            let fallback_block = if idx + 1 == arms.len() {
                join
            } else {
                self.new_block()
            };

            let guard_block = if arm.guard.is_some() {
                Some(self.new_block())
            } else {
                None
            };

            let pattern_pass_block = guard_block.unwrap_or(arm_block);
            self.lower_match_pattern(
                test_block,
                scrutinee_value,
                &arm.pattern,
                pattern_pass_block,
                fallback_block,
            );

            if let Some(guard_expr) = &arm.guard {
                let guard_block = guard_block.expect("guard block should exist");
                let (guard_start, guard_saved) =
                    self.bind_match_pattern_values(guard_block, scrutinee_value, &arm.pattern);
                let (guard_end, guard_value) = self.lower_expr(guard_start, guard_expr);
                self.restore_local_bindings(guard_saved);
                let guard_cond = guard_value.unwrap_or_else(|| {
                    self.push_eval(
                        guard_end,
                        MirValue::Literal(HirLiteral::Bool(false)),
                        MirValueType::Bool,
                    )
                });
                if !self.is_terminated(guard_end) {
                    self.set_terminator(
                        guard_end,
                        MirTerminator::Branch {
                            condition: guard_cond,
                            then_block: arm_block,
                            else_block: fallback_block,
                        },
                    );
                }
            }

            let (arm_start, arm_saved) =
                self.bind_match_pattern_values(arm_block, scrutinee_value, &arm.pattern);
            let (arm_end, arm_value) = self.lower_expr(arm_start, &arm.value);
            self.restore_local_bindings(arm_saved);
            if !self.is_terminated(arm_end) {
                self.set_terminator(arm_end, MirTerminator::Goto(join));
                if let Some(arm_value) = arm_value {
                    join_sources.push((arm_end, arm_value));
                }
            }

            test_block = fallback_block;
        }

        if test_block != join && !self.is_terminated(test_block) {
            self.set_terminator(test_block, MirTerminator::Goto(join));
        }

        if join_sources.is_empty() {
            (join, None)
        } else if join_sources.len() == 1 {
            (join, Some(join_sources[0].1))
        } else {
            let dest = self.fresh_value();
            let phi_ty = join_sources
                .iter()
                .filter_map(|(_, value)| self.value_types.get(value))
                .cloned()
                .reduce(|left, right| merge_types(&left, &right))
                .unwrap_or(MirValueType::Unknown);
            self.function.blocks[join.0]
                .instructions
                .push(MirInstr::Phi {
                    dest,
                    sources: join_sources,
                    ty: phi_ty.clone(),
                });
            self.value_types.insert(dest, phi_ty);
            (join, Some(dest))
        }
    }

    pub(super) fn lower_match_pattern(
        &mut self,
        test_block: MirBlockId,
        scrutinee_value: MirValueId,
        pattern: &HirPattern,
        then_block: MirBlockId,
        else_block: MirBlockId,
    ) {
        match pattern {
            HirPattern::Wildcard
            | HirPattern::IdentBind(_)
            | HirPattern::TypeLiteral(_)
            | HirPattern::Other => {
                if !self.is_terminated(test_block) {
                    self.set_terminator(test_block, MirTerminator::Goto(then_block));
                }
            }
            HirPattern::EnumVariant { root, variant, .. } => {
                let (variant_tag, tag_bits) = if let Some((tag, bits)) =
                    self.enum_tag_and_bits_for_variant(root.as_deref(), variant)
                {
                    (tag, bits)
                } else if root.is_none() {
                    self.anonymous_variant_tag_for(variant)
                } else {
                    self.diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::Mir,
                            DiagnosticCode::E4005,
                            format!(
                                "cannot resolve enum match pattern '{}'; use an explicit enum root",
                                variant
                            ),
                        )
                        .with_primary_file_label(
                            self.source_file_path.clone(),
                            None,
                            "qualify the enum pattern (for example `MyEnum.Variant`)",
                        ),
                    );
                    if !self.is_terminated(test_block) {
                        self.set_terminator(test_block, MirTerminator::Goto(else_block));
                    }
                    return;
                };
                let scrutinee_tag = self
                    .aggregate_sequences
                    .get(&scrutinee_value)
                    .and_then(|sequence| sequence.first().copied());
                let scrutinee_tag = self.value_from_sequence_or_index(
                    test_block,
                    scrutinee_value,
                    scrutinee_tag,
                    0,
                    MirValueType::Int {
                        signed: false,
                        bits: tag_bits,
                    },
                );
                let expected_tag = self.push_eval(
                    test_block,
                    MirValue::Literal(HirLiteral::Integer(variant_tag.to_string())),
                    MirValueType::Int {
                        signed: false,
                        bits: tag_bits,
                    },
                );
                let cond = self.push_eval(
                    test_block,
                    MirValue::Binary {
                        op: crate::compiler::ast::BinaryOp::Eq,
                        left: scrutinee_tag,
                        right: expected_tag,
                    },
                    MirValueType::Bool,
                );
                if !self.is_terminated(test_block) {
                    self.set_terminator(
                        test_block,
                        MirTerminator::Branch {
                            condition: cond,
                            then_block,
                            else_block,
                        },
                    );
                }
            }
            HirPattern::Literal(literal) => {
                let lit_ty = literal_type(literal);
                let literal_value =
                    self.push_eval(test_block, MirValue::Literal(literal.clone()), lit_ty);
                let cond = self.push_eval(
                    test_block,
                    MirValue::Binary {
                        op: crate::compiler::ast::BinaryOp::Eq,
                        left: scrutinee_value,
                        right: literal_value,
                    },
                    MirValueType::Bool,
                );
                if !self.is_terminated(test_block) {
                    self.set_terminator(
                        test_block,
                        MirTerminator::Branch {
                            condition: cond,
                            then_block,
                            else_block,
                        },
                    );
                }
            }
            HirPattern::RangeLiteral {
                start,
                end,
                inclusive,
            } => {
                let start_value = self.push_eval(
                    test_block,
                    MirValue::Literal(start.clone()),
                    literal_type(start),
                );
                let end_value = self.push_eval(
                    test_block,
                    MirValue::Literal(end.clone()),
                    literal_type(end),
                );
                let lower_ok = self.push_eval(
                    test_block,
                    MirValue::Binary {
                        op: crate::compiler::ast::BinaryOp::Ge,
                        left: scrutinee_value,
                        right: start_value,
                    },
                    MirValueType::Bool,
                );
                let upper_op = if *inclusive {
                    crate::compiler::ast::BinaryOp::Le
                } else {
                    crate::compiler::ast::BinaryOp::Lt
                };
                let upper_ok = self.push_eval(
                    test_block,
                    MirValue::Binary {
                        op: upper_op,
                        left: scrutinee_value,
                        right: end_value,
                    },
                    MirValueType::Bool,
                );
                let cond = self.push_eval(
                    test_block,
                    MirValue::Binary {
                        op: crate::compiler::ast::BinaryOp::LogicalAnd,
                        left: lower_ok,
                        right: upper_ok,
                    },
                    MirValueType::Bool,
                );
                if !self.is_terminated(test_block) {
                    self.set_terminator(
                        test_block,
                        MirTerminator::Branch {
                            condition: cond,
                            then_block,
                            else_block,
                        },
                    );
                }
            }
        }
    }

    pub(super) fn bind_match_pattern_values(
        &mut self,
        block: MirBlockId,
        scrutinee_value: MirValueId,
        pattern: &HirPattern,
    ) -> (MirBlockId, Vec<(String, Option<MirValueId>)>) {
        let (end, bindings) = self.pattern_binding_values(block, scrutinee_value, pattern);
        let mut saved = Vec::with_capacity(bindings.len());
        for (name, value) in bindings {
            saved.push(self.save_local_binding(&name, value));
        }
        (end, saved)
    }

    pub(super) fn save_local_binding(
        &mut self,
        name: &str,
        value: MirValueId,
    ) -> (String, Option<MirValueId>) {
        let name = name.to_string();
        let previous = self.locals.insert(name.clone(), value);
        (name, previous)
    }

    pub(super) fn restore_saved_local_binding(&mut self, saved: (String, Option<MirValueId>)) {
        let (name, previous) = saved;
        if let Some(previous) = previous {
            self.locals.insert(name, previous);
        } else {
            self.locals.remove(&name);
        }
    }

    pub(super) fn restore_local_bindings(&mut self, saved: Vec<(String, Option<MirValueId>)>) {
        for saved_binding in saved {
            self.restore_saved_local_binding(saved_binding);
        }
    }

    pub(super) fn pattern_binding_values(
        &mut self,
        block: MirBlockId,
        scrutinee_value: MirValueId,
        pattern: &HirPattern,
    ) -> (MirBlockId, Vec<(String, MirValueId)>) {
        match pattern {
            HirPattern::IdentBind(name) if name != "_" => {
                (block, vec![(name.clone(), scrutinee_value)])
            }
            HirPattern::EnumVariant { bindings, .. } => {
                let at = block;
                let sequence = self.aggregate_sequences.get(&scrutinee_value).cloned();
                let mut out = Vec::new();
                for (idx, name) in bindings.iter().enumerate() {
                    if name == "_" {
                        continue;
                    }
                    let payload_index = idx + 1;
                    let payload_value = self.value_from_sequence_or_index(
                        at,
                        scrutinee_value,
                        sequence
                            .as_ref()
                            .and_then(|values| values.get(payload_index).copied()),
                        payload_index,
                        MirValueType::Unknown,
                    );
                    out.push((name.clone(), payload_value));
                }
                (at, out)
            }
            _ => (block, Vec::new()),
        }
    }

    pub(super) fn lower_if(
        &mut self,
        block: MirBlockId,
        condition: &HirExpr,
        capture: Option<&crate::compiler::hir::HirIfCapture>,
        then_branch: &HirExpr,
        else_branch: Option<&HirExpr>,
    ) -> (MirBlockId, Option<MirValueId>) {
        let (cond_end, cond_value) = self.lower_expr(block, condition);
        let Some(cond_value) = cond_value else {
            return (cond_end, None);
        };
        let branch_condition = if capture.is_some() {
            let cond_ty = self
                .value_types
                .get(&cond_value)
                .cloned()
                .unwrap_or(MirValueType::Unknown);
            self.emit_nonzero_check(cond_end, cond_value, &cond_ty)
        } else {
            cond_value
        };

        let then_block = self.new_block();
        let else_block = self.new_block();
        let join_block = self.new_block();

        self.set_terminator(
            cond_end,
            MirTerminator::Branch {
                condition: branch_condition,
                then_block,
                else_block,
            },
        );

        // Snapshot locals before any branch lowering so we can properly merge
        // at the join block. Without this, assignments inside if-branches produce
        // SSA values that don't dominate the join block, causing Cranelift errors.
        let pre_locals = self.locals.clone();

        let capture_binding = capture.and_then(|capture| capture.binding.as_deref());
        let prev_capture_binding =
            capture_binding.map(|name| self.save_local_binding(name, cond_value));
        let (then_end, then_value) = self.lower_expr(then_block, then_branch);
        if let Some(saved) = prev_capture_binding {
            self.restore_saved_local_binding(saved);
        }
        let then_locals = self.locals.clone();
        let then_pred = if self.is_terminated(then_end) {
            None
        } else {
            self.set_terminator(then_end, MirTerminator::Goto(join_block));
            Some((then_end, then_value))
        };

        // Restore pre-branch locals before lowering the else branch so that
        // the else branch sees the correct incoming state, not the then-branch's
        // modifications.
        self.locals = pre_locals.clone();

        let else_pred = if let Some(else_branch) = else_branch {
            let (else_end, else_value) = self.lower_expr(else_block, else_branch);
            if self.is_terminated(else_end) {
                None
            } else {
                self.set_terminator(else_end, MirTerminator::Goto(join_block));
                Some((else_end, else_value))
            }
        } else {
            self.set_terminator(else_block, MirTerminator::Goto(join_block));
            Some((else_block, None))
        };
        let else_locals = self.locals.clone();

        // Merge locals at the join block.
        match (&then_pred, &else_pred) {
            (Some((then_end_blk, _)), Some((else_end_blk, _))) => {
                // Both paths reach the join block — create phi nodes for any
                // local that was modified in either branch.
                self.locals = pre_locals.clone();
                for name in pre_locals.keys() {
                    let pre_val = pre_locals[name];
                    let tv = then_locals.get(name).copied().unwrap_or(pre_val);
                    let ev = else_locals.get(name).copied().unwrap_or(pre_val);
                    if tv == ev {
                        // Same value from both paths — use it directly.
                        self.locals.insert(name.clone(), tv);
                    } else {
                        // Different values — create a phi.
                        let phi = self.fresh_value();
                        let phi_ty = [tv, ev]
                            .iter()
                            .filter_map(|v| self.value_types.get(v))
                            .cloned()
                            .reduce(|a, b| merge_types(&a, &b))
                            .unwrap_or(MirValueType::Unknown);
                        self.function.blocks[join_block.0]
                            .instructions
                            .push(MirInstr::Phi {
                                dest: phi,
                                sources: vec![(*then_end_blk, tv), (*else_end_blk, ev)],
                                ty: phi_ty.clone(),
                            });
                        self.value_types.insert(phi, phi_ty);
                        self.locals.insert(name.clone(), phi);
                    }
                }
            }
            (Some(_), None) => {
                // Only the then path reaches join.
                self.locals = then_locals;
            }
            (None, Some(_)) => {
                // Only the else path reaches join.
                self.locals = else_locals;
            }
            (None, None) => {
                // Neither path reaches join (both terminate).
                self.locals = pre_locals;
            }
        }

        let mut sources = Vec::new();
        if let Some((pred, Some(value))) = then_pred {
            sources.push((pred, value));
        }
        if let Some((pred, Some(value))) = else_pred {
            sources.push((pred, value));
        }

        if sources.is_empty() {
            (join_block, None)
        } else if sources.len() == 1 {
            (join_block, Some(sources[0].1))
        } else {
            let dest = self.fresh_value();
            let phi_ty = sources
                .iter()
                .filter_map(|(_, value)| self.value_types.get(value))
                .cloned()
                .reduce(|left, right| merge_types(&left, &right))
                .unwrap_or(MirValueType::Unknown);
            self.function.blocks[join_block.0]
                .instructions
                .push(MirInstr::Phi {
                    dest,
                    sources,
                    ty: phi_ty.clone(),
                });
            self.value_types.insert(dest, phi_ty);
            (join_block, Some(dest))
        }
    }
}

impl FunctionLowerer {
    pub(super) fn new_block(&mut self) -> MirBlockId {
        let id = MirBlockId(self.function.blocks.len());
        self.function.blocks.push(MirBasicBlock {
            id,
            instructions: Vec::new(),
            terminator: None,
        });
        id
    }

    pub(super) fn push_eval(
        &mut self,
        block: MirBlockId,
        value: MirValue,
        ty: MirValueType,
    ) -> MirValueId {
        let dest = self.fresh_value();
        self.function.blocks[block.0]
            .instructions
            .push(MirInstr::Eval {
                dest,
                value: value.clone(),
                ty: ty.clone(),
            });
        self.value_types.insert(dest, ty);
        self.value_defs.insert(dest, value);
        dest
    }

    pub(super) fn literal_int_value(&self, value_id: MirValueId) -> Option<i64> {
        match self.value_defs.get(&value_id) {
            Some(MirValue::Literal(HirLiteral::Integer(v))) => {
                let normalized = v.replace('_', "");
                if let Some(bits) = normalized.strip_prefix("0x") {
                    i64::from_str_radix(bits, 16).ok()
                } else if let Some(bits) = normalized.strip_prefix("0b") {
                    i64::from_str_radix(bits, 2).ok()
                } else if let Some(bits) = normalized.strip_prefix("0o") {
                    i64::from_str_radix(bits, 8).ok()
                } else {
                    normalized.parse::<i64>().ok()
                }
            }
            _ => None,
        }
    }

    pub(super) fn enum_tag_and_bits_for_variant(
        &self,
        root: Option<&str>,
        variant: &str,
    ) -> Option<(i64, u16)> {
        let root = root?;
        let tags = self.enum_variant_tags_by_name.get(root)?;
        let tag = tags.get(variant).copied()?;
        let bits = self.enum_repr_bits_by_name.get(root).copied().unwrap_or(32);
        Some((tag, bits))
    }

    pub(super) fn anonymous_variant_tag_for(&self, variant: &str) -> (i64, u16) {
        let mut hash = 2166136261u32;
        for byte in variant.as_bytes() {
            hash ^= u32::from(*byte);
            hash = hash.wrapping_mul(16777619);
        }
        let tag = if hash == 0 { 1 } else { i64::from(hash) };
        (tag, 32)
    }

    pub(super) fn fresh_value(&mut self) -> MirValueId {
        let id = MirValueId(self.next_value);
        self.next_value += 1;
        id
    }

    pub(super) fn is_terminated(&self, block: MirBlockId) -> bool {
        self.function.blocks[block.0].terminator.is_some()
    }

    pub(super) fn set_terminator(&mut self, block: MirBlockId, term: MirTerminator) {
        self.function.blocks[block.0].terminator = Some(term);
    }
}

impl FunctionLowerer {
    pub(super) fn emit_comptime_value(
        &mut self,
        block: MirBlockId,
        value: ComptimeValue,
    ) -> MirValueId {
        let (value, ty) = match value {
            ComptimeValue::Literal(lit) => {
                let ty = literal_type(&lit);
                (MirValue::Literal(lit), ty)
            }
            ComptimeValue::Type(name) => (MirValue::TypeLiteral(name), MirValueType::Type),
            ComptimeValue::Function(name) => (MirValue::Ident(name), MirValueType::FunctionPointer),
        };
        self.push_eval(block, value, ty)
    }

    pub(super) fn refresh_comptime_local_from_expr(&mut self, name: &str, expr: &HirExpr) {
        self.comptime_local_function_exprs.remove(name);
        let mut locals = self.current_comptime_locals();
        locals.remove(name);

        let local_function_expr = match &expr.kind {
            HirExprKind::Function { .. } => Some(expr.clone()),
            HirExprKind::Inline { expr } if matches!(expr.kind, HirExprKind::Function { .. }) => {
                Some((**expr).clone())
            }
            _ => None,
        };

        if let Some(function_expr) = local_function_expr {
            self.comptime_known_locals
                .insert(name.to_string(), ComptimeValue::Function(name.to_string()));
            self.comptime_local_function_exprs
                .insert(name.to_string(), function_expr);
            return;
        }

        if let Some(value) = self.try_eval_comptime_expr_with_locals(expr, 0, &mut locals) {
            self.comptime_known_locals.insert(name.to_string(), value);
        } else {
            self.comptime_known_locals.remove(name);
        }
    }

    pub(super) fn current_comptime_locals(&self) -> BTreeMap<String, ComptimeValue> {
        let mut locals = self.comptime_known_locals.clone();
        locals.retain(|name, _| self.locals.contains_key(name));

        let mut cache = BTreeMap::new();
        let mut visiting = BTreeSet::new();
        for (name, value_id) in &self.locals {
            if let Some(value) =
                self.try_eval_comptime_value_id(*value_id, 0, &mut cache, &mut visiting)
            {
                locals.insert(name.clone(), value);
            } else if !self.comptime_known_locals.contains_key(name) {
                locals.remove(name);
            }
        }
        locals
    }

    pub(super) fn try_eval_comptime_value_id(
        &self,
        value_id: MirValueId,
        depth: usize,
        cache: &mut BTreeMap<MirValueId, Option<ComptimeValue>>,
        visiting: &mut BTreeSet<MirValueId>,
    ) -> Option<ComptimeValue> {
        if depth > 64 {
            return None;
        }
        if let Some(cached) = cache.get(&value_id) {
            return cached.clone();
        }
        if !visiting.insert(value_id) {
            return None;
        }

        let evaluated = match self.value_defs.get(&value_id) {
            Some(MirValue::Literal(lit)) => Some(ComptimeValue::Literal(lit.clone())),
            Some(MirValue::TypeLiteral(name)) => Some(ComptimeValue::Type(name.clone())),
            Some(MirValue::Ident(name)) => {
                if self.function_return_types.contains_key(name)
                    || self
                        .function_exprs
                        .get(name)
                        .is_some_and(|expr| matches!(&expr.kind, HirExprKind::Function { .. }))
                {
                    Some(ComptimeValue::Function(name.clone()))
                } else {
                    None
                }
            }
            Some(MirValue::Unary { op, operand }) => {
                let operand =
                    self.try_eval_comptime_value_id(*operand, depth + 1, cache, visiting)?;
                match (op, operand) {
                    (UnaryOp::Neg, ComptimeValue::Literal(HirLiteral::Integer(v))) => {
                        let parsed = parse_i64_literal(&v)?;
                        Some(ComptimeValue::Literal(HirLiteral::Integer(
                            (-parsed).to_string(),
                        )))
                    }
                    (UnaryOp::Not, ComptimeValue::Literal(HirLiteral::Bool(v))) => {
                        Some(ComptimeValue::Literal(HirLiteral::Bool(!v)))
                    }
                    (UnaryOp::BitNot, ComptimeValue::Literal(HirLiteral::Integer(v))) => {
                        let parsed = parse_i64_literal(&v)?;
                        Some(ComptimeValue::Literal(HirLiteral::Integer(
                            (!parsed).to_string(),
                        )))
                    }
                    _ => None,
                }
            }
            Some(MirValue::Binary { op, left, right }) => {
                let left = self.try_eval_comptime_value_id(*left, depth + 1, cache, visiting)?;
                let right = self.try_eval_comptime_value_id(*right, depth + 1, cache, visiting)?;
                eval_comptime_binary(*op, left, right)
            }
            Some(MirValue::Assign { value, .. }) | Some(MirValue::LocalSet { value, .. }) => {
                self.try_eval_comptime_value_id(*value, depth + 1, cache, visiting)
            }
            Some(MirValue::Cast { value, .. }) => {
                self.try_eval_comptime_value_id(*value, depth + 1, cache, visiting)
            }
            _ => None,
        };

        visiting.remove(&value_id);
        cache.insert(value_id, evaluated.clone());
        evaluated
    }

    pub(super) fn report_comptime_eval_failure(
        &mut self,
        span: crate::compiler::diagnostics::SourceSpan,
    ) {
        self.diagnostics.push(
            Diagnostic::error(
                DiagnosticPhase::Mir,
                DiagnosticCode::E4009,
                "comptime expression must be compile-time evaluable",
            )
            .with_primary_file_label(
                self.source_file_path.clone(),
                Some(span),
                "this `comp` expression could not be evaluated at compile time",
            ),
        );
    }

    pub(super) fn should_force_comptime_call(&self, callee_name: &str) -> bool {
        if matches!(
            self.function_return_types.get(callee_name),
            Some(MirValueType::Type)
        ) {
            return true;
        }
        self.function_param_type_hints
            .get(callee_name)
            .map(|params| {
                params.iter().flatten().any(|hint| {
                    matches!(parse_type_hint(hint), MirValueType::Type)
                        || hint.trim() == "comp type"
                })
            })
            .unwrap_or(false)
    }

    pub(super) fn function_returns_errorable_aggregate(&self, callee_name: &str) -> bool {
        if let Some(Some(hint)) = self.function_return_hints.get(callee_name) {
            return return_hint_is_errorable_aggregate(hint);
        }
        let suffix = format!("::{callee_name}");
        self.function_return_hints
            .iter()
            .filter_map(|(name, hint)| {
                if name.ends_with(&suffix) {
                    hint.as_deref()
                } else {
                    None
                }
            })
            .any(return_hint_is_errorable_aggregate)
    }

    pub(super) fn function_returns_errorable_scalar(&self, callee_name: &str) -> bool {
        let is_errorable_scalar_hint = |hint: &str| {
            if !hint.contains('!') || return_hint_is_errorable_aggregate(hint) {
                return false;
            }
            let candidate = if let Some((_, ret)) = hint.rsplit_once("->") {
                ret.trim()
            } else {
                hint.trim()
            };
            let ok = return_hint_ok_type_text(candidate);
            !matches!(parse_type_hint(ok), MirValueType::BytesSlice)
        };

        if let Some(Some(hint)) = self.function_return_hints.get(callee_name) {
            return is_errorable_scalar_hint(hint);
        }
        let suffix = format!("::{callee_name}");
        self.function_return_hints
            .iter()
            .filter_map(|(name, hint)| {
                if name.ends_with(&suffix) {
                    hint.as_deref()
                } else {
                    None
                }
            })
            .any(is_errorable_scalar_hint)
    }

    pub(super) fn eval_type_designator_name(
        &self,
        expr: &HirExpr,
        locals: &BTreeMap<String, ComptimeValue>,
    ) -> Option<String> {
        match self.try_eval_comptime_expr_with_locals(expr, 0, &mut locals.clone()) {
            Some(ComptimeValue::Type(name)) => Some(name),
            Some(ComptimeValue::Function(_)) => Some("fn".to_string()),
            _ => None,
        }
    }

    pub(super) fn try_lower_builtin_call(
        &mut self,
        block: MirBlockId,
        name: &str,
        args: &[HirCallArg],
    ) -> Option<(MirBlockId, Option<MirValueId>)> {
        match name {
            "$as" => {
                if args.len() != 2 {
                    return Some((block, None));
                }
                let empty_locals = BTreeMap::new();
                let target_name = self
                    .eval_type_designator_name(&args[0].value, &empty_locals)
                    .unwrap_or_else(|| "unknown".to_string());
                let target_ty = parse_type_hint(&target_name);
                let (arg_end, value) = self.lower_expr(block, &args[1].value);
                let Some(value) = value else {
                    return Some((arg_end, None));
                };
                if matches!(target_ty, MirValueType::Unknown) {
                    return Some((arg_end, Some(value)));
                }
                let casted = self.push_eval(
                    arg_end,
                    MirValue::Cast {
                        value,
                        target: target_ty.clone(),
                    },
                    target_ty,
                );
                Some((arg_end, Some(casted)))
            }
            "$sizeof" | "$alignof" | "$offsetof" => {
                let expected = if name == "$offsetof" { 2 } else { 1 };
                if args.len() != expected {
                    return Some((block, None));
                }
                let empty_locals = BTreeMap::new();
                let type_name = self
                    .eval_type_designator_name(&args[0].value, &empty_locals)
                    .unwrap_or_else(|| "unknown".to_string());
                let (size, align) = layout_for_builtin_type_name(&type_name);
                let raw = if name == "$sizeof" {
                    size
                } else if name == "$alignof" {
                    align
                } else {
                    builtin_offsetof_for_type_name(&type_name, &args[1].value).unwrap_or(0)
                };
                let value = self.push_eval(
                    block,
                    MirValue::Literal(HirLiteral::Integer(raw.to_string())),
                    MirValueType::Int {
                        signed: false,
                        bits: 64,
                    },
                );
                Some((block, Some(value)))
            }
            "$unreachable" => {
                self.set_terminator(block, MirTerminator::Unreachable);
                Some((block, None))
            }
            "$memcpy" | "$memset" => {
                if args.len() != 3 {
                    return Some((block, None));
                }
                let ptr_ty = MirValueType::Int {
                    signed: false,
                    bits: 64,
                };
                let mut end = block;
                let mut lowered_args = Vec::with_capacity(3);
                for arg in args {
                    let (arg_end, value) = self.lower_expr(end, &arg.value);
                    end = arg_end;
                    let zero = self.push_eval(
                        end,
                        MirValue::Literal(crate::compiler::hir::HirLiteral::Integer(
                            "0".to_string(),
                        )),
                        ptr_ty.clone(),
                    );
                    lowered_args.push(value.unwrap_or(zero));
                }
                let sym = if name == "$memcpy" {
                    "memcpy"
                } else {
                    "memset"
                };
                let callee = self.push_eval(
                    end,
                    MirValue::Ident(sym.to_string()),
                    MirValueType::FunctionPointer,
                );
                let result = self.push_eval(
                    end,
                    MirValue::Call {
                        callee,
                        args: lowered_args,
                    },
                    ptr_ty,
                );
                Some((end, Some(result)))
            }
            "$syscall" => {
                if args.is_empty() || args.len() > 7 {
                    return Some((block, None));
                }
                let isize_ty = MirValueType::Int {
                    signed: true,
                    bits: 64,
                };
                let zero = self.push_eval(
                    block,
                    MirValue::Literal(crate::compiler::hir::HirLiteral::Integer("0".to_string())),
                    isize_ty.clone(),
                );
                // Lower all provided args, then pad remaining slots to 7 with zero.
                let mut end = block;
                let mut lowered_args = Vec::with_capacity(7);
                for arg in args {
                    let (arg_end, value) = self.lower_expr(end, &arg.value);
                    end = arg_end;
                    lowered_args.push(value.unwrap_or(zero));
                }
                while lowered_args.len() < 7 {
                    lowered_args.push(zero);
                }
                let callee = self.push_eval(
                    end,
                    MirValue::Ident("dyn_syscall".to_string()),
                    MirValueType::FunctionPointer,
                );
                let result = self.push_eval(
                    end,
                    MirValue::Call {
                        callee,
                        args: lowered_args,
                    },
                    isize_ty,
                );
                Some((end, Some(result)))
            }
            "$panic" => {
                if args.len() != 1 {
                    self.set_terminator(block, MirTerminator::Unreachable);
                    return Some((block, None));
                }
                let (arg_end, _) = self.lower_expr(block, &args[0].value);
                self.set_terminator(arg_end, MirTerminator::Unreachable);
                Some((arg_end, None))
            }
            "$self" => {
                if !args.is_empty() {
                    return Some((block, None));
                }
                // First try the first parameter's type hint (e.g. `self: *Thing` → "Thing").
                // Fall back to the enclosing struct name for members with no self parameter.
                let self_name = self
                    .current_param_type_hints
                    .first()
                    .and_then(|hint| hint.as_ref())
                    .map(|hint| self_type_literal_from_param_hint(hint))
                    .or_else(|| self.current_self_type_hint.clone())
                    .unwrap_or_else(|| "unknown".to_string());
                let value =
                    self.push_eval(block, MirValue::TypeLiteral(self_name), MirValueType::Type);
                Some((block, Some(value)))
            }
            "$typeof" => {
                if args.len() != 1 {
                    return Some((block, None));
                }
                let (arg_end, arg_value) = self.lower_expr(block, &args[0].value);
                let Some(arg_value) = arg_value else {
                    return Some((arg_end, None));
                };
                let resolved_ty = self
                    .value_types
                    .get(&arg_value)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown);
                let ty_name = match resolved_ty {
                    MirValueType::Bool => "u1".to_string(),
                    MirValueType::BytesSlice => "[]u8".to_string(),
                    MirValueType::Int { signed: true, bits } => format!("i{bits}"),
                    MirValueType::Int {
                        signed: false,
                        bits,
                    } => format!("u{bits}"),
                    MirValueType::Float { bits } => format!("f{bits}"),
                    MirValueType::Type => "type".to_string(),
                    MirValueType::Function
                    | MirValueType::FunctionPointer
                    | MirValueType::Closure => "fn".to_string(),
                    MirValueType::Unknown => "unknown".to_string(),
                };
                let value =
                    self.push_eval(arg_end, MirValue::TypeLiteral(ty_name), MirValueType::Type);
                Some((arg_end, Some(value)))
            }
            "$is_uint" | "$is_sint" | "$is_float" => {
                if args.len() != 1 {
                    return Some((block, None));
                }
                let ct_locals = self.current_comptime_locals();
                let type_name = self
                    .eval_type_designator_name(&args[0].value, &ct_locals)
                    .unwrap_or_default();
                let result = match name {
                    "$is_uint" => {
                        matches!(type_name.as_str(), "u8" | "u16" | "u32" | "u64" | "usize")
                    }
                    "$is_sint" => matches!(type_name.as_str(), "i8" | "i16" | "i32" | "i64"),
                    "$is_float" => matches!(type_name.as_str(), "f32" | "f64"),
                    _ => false,
                };
                let value = self.push_eval(
                    block,
                    MirValue::Literal(HirLiteral::Bool(result)),
                    MirValueType::Bool,
                );
                Some((block, Some(value)))
            }
            "$typeclass" => {
                if args.len() != 1 {
                    return Some((block, None));
                }
                let ct_locals = self.current_comptime_locals();
                let type_name = self
                    .eval_type_designator_name(&args[0].value, &ct_locals)
                    .unwrap_or_default();
                let class = type_name_to_class(&type_name);
                let value = self.push_eval(
                    block,
                    MirValue::TypeLiteral(class.to_string()),
                    MirValueType::Type,
                );
                Some((block, Some(value)))
            }
            "$has_method" | "$has_field" => {
                if args.len() != 2 {
                    return Some((block, None));
                }
                // Get the type name as the raw ident (don't resolve to struct descriptor,
                // since method keys use the short name like "Channel__send").
                let type_name = {
                    let locals = self.current_comptime_locals();
                    match &args[0].value.kind {
                        HirExprKind::Ident(n) => {
                            if let Some(ComptimeValue::Type(t)) = locals.get(n.as_str()) {
                                t.clone()
                            } else {
                                n.clone()
                            }
                        }
                        _ => {
                            // Try evaluating the first arg as a comptime expression (e.g. `$typeof(v)`).
                            match self.try_eval_comptime_expr(&args[0].value, 0) {
                                Some(ComptimeValue::Type(t)) => t,
                                _ => return Some((block, None)),
                            }
                        }
                    }
                };
                let member_name = match &args[1].value.kind {
                    HirExprKind::Literal(HirLiteral::String(s)) => s.clone(),
                    _ => return Some((block, None)),
                };
                let exists = if name == "$has_method" {
                    let key = format!("{}__{}", type_name, member_name);
                    self.function_exprs.contains_key(&key)
                } else {
                    // $has_field: resolve the struct descriptor from named_type_literals
                    let descriptor = self
                        .named_type_literals
                        .get(&type_name)
                        .cloned()
                        .unwrap_or_else(|| type_name.clone());
                    has_struct_field(&descriptor, &member_name)
                };
                let value = self.push_eval(
                    block,
                    MirValue::Literal(HirLiteral::Bool(exists)),
                    MirValueType::Bool,
                );
                Some((block, Some(value)))
            }
            "$typename" => {
                if args.len() != 1 {
                    return Some((block, None));
                }
                let ct_locals = self.current_comptime_locals();
                // Try to resolve as a type designator; fall back to the raw ident name.
                let type_name = self
                    .eval_type_designator_name(&args[0].value, &ct_locals)
                    .unwrap_or_else(|| {
                        if let HirExprKind::Ident(n) = &args[0].value.kind {
                            n.clone()
                        } else {
                            "unknown".to_string()
                        }
                    });
                let value = self.push_eval(
                    block,
                    MirValue::Literal(HirLiteral::String(type_name)),
                    MirValueType::BytesSlice,
                );
                Some((block, Some(value)))
            }
            "$target" => {
                if !args.is_empty() {
                    return Some((block, None));
                }
                let enum_u8 = MirValueType::Int {
                    signed: false,
                    bits: 8,
                };
                let (mode_variant, mode_tag) = match self.build_config.opt_level {
                    crate::compiler::backend::BuildOptLevel::Default
                    | crate::compiler::backend::BuildOptLevel::O0 => ("debug", 0i64),
                    crate::compiler::backend::BuildOptLevel::O1 => ("release_safe", 1),
                    crate::compiler::backend::BuildOptLevel::O2
                    | crate::compiler::backend::BuildOptLevel::O3 => ("release_fast", 2),
                    crate::compiler::backend::BuildOptLevel::Os
                    | crate::compiler::backend::BuildOptLevel::Oz => ("release_small", 3),
                };
                let mode = self.push_eval(
                    block,
                    MirValue::EnumVariant {
                        root: Some("BuildMode".to_string()),
                        variant: mode_variant.to_string(),
                        tag: mode_tag,
                        tag_bits: 8,
                        payload: Vec::new(),
                    },
                    enum_u8.clone(),
                );
                #[cfg(target_arch = "x86_64")]
                let (arch_variant, arch_tag) = ("x86_64", 0i64);
                #[cfg(target_arch = "aarch64")]
                let (arch_variant, arch_tag) = ("aarch64", 1i64);
                #[cfg(not(any(target_arch = "x86_64", target_arch = "aarch64")))]
                let (arch_variant, arch_tag) = ("x86_64", 0i64);
                let arch = self.push_eval(
                    block,
                    MirValue::EnumVariant {
                        root: Some("Arch".to_string()),
                        variant: arch_variant.to_string(),
                        tag: arch_tag,
                        tag_bits: 8,
                        payload: Vec::new(),
                    },
                    enum_u8.clone(),
                );
                #[cfg(target_os = "linux")]
                let (os_variant, os_tag) = ("linux", 0i64);
                #[cfg(target_os = "macos")]
                let (os_variant, os_tag) = ("macos", 1i64);
                #[cfg(target_os = "windows")]
                let (os_variant, os_tag) = ("windows", 2i64);
                #[cfg(not(any(target_os = "linux", target_os = "macos", target_os = "windows")))]
                let (os_variant, os_tag) = ("freestanding", 3i64);
                let os = self.push_eval(
                    block,
                    MirValue::EnumVariant {
                        root: Some("Os".to_string()),
                        variant: os_variant.to_string(),
                        tag: os_tag,
                        tag_bits: 8,
                        payload: Vec::new(),
                    },
                    enum_u8,
                );
                let sanitize = self.push_eval(
                    block,
                    MirValue::Literal(HirLiteral::Bool(self.build_config.sanitize)),
                    MirValueType::Bool,
                );
                let fields: Vec<(String, MirValueId)> = vec![
                    ("mode".to_string(), mode),
                    ("arch".to_string(), arch),
                    ("os".to_string(), os),
                    ("sanitize".to_string(), sanitize),
                ];
                let field_map: BTreeMap<String, MirValueId> = fields.iter().cloned().collect();
                let target_val = self.push_eval(
                    block,
                    MirValue::StructLiteral { fields },
                    MirValueType::Unknown,
                );
                self.struct_fields.insert(target_val, field_map);
                Some((block, Some(target_val)))
            }
            _ => None,
        }
    }

    pub(super) fn try_eval_comptime_expr(
        &self,
        expr: &HirExpr,
        depth: usize,
    ) -> Option<ComptimeValue> {
        let mut locals = self.current_comptime_locals();
        self.try_eval_comptime_expr_with_locals(expr, depth, &mut locals)
    }

    pub(super) fn try_eval_comptime_expr_with_locals(
        &self,
        expr: &HirExpr,
        depth: usize,
        locals: &mut BTreeMap<String, ComptimeValue>,
    ) -> Option<ComptimeValue> {
        if depth > 64 {
            return None;
        }
        match &expr.kind {
            HirExprKind::Literal(lit) => Some(ComptimeValue::Literal(lit.clone())),
            HirExprKind::TypeLiteral(name) => {
                Some(ComptimeValue::Type(substitute_type_locals(name, locals)))
            }
            HirExprKind::Ident(name) => {
                if let Some(value) = locals.get(name).cloned() {
                    return Some(value);
                }
                if let Some(type_name) =
                    type_literal_name_for_ident(name, &self.named_type_literals)
                {
                    return Some(ComptimeValue::Type(type_name));
                }
                if let Some(target) = self.function_exprs.get(name) {
                    if matches!(&target.kind, HirExprKind::Function { .. }) {
                        return Some(ComptimeValue::Function(name.clone()));
                    }
                    return self.try_eval_comptime_expr_with_locals(
                        target,
                        depth + 1,
                        &mut locals.clone(),
                    );
                }
                None
            }
            HirExprKind::Comptime { expr } | HirExprKind::Inline { expr } => {
                self.try_eval_comptime_expr_with_locals(expr, depth + 1, locals)
            }
            HirExprKind::Unary { op, expr } => {
                let value = self.try_eval_comptime_expr_with_locals(expr, depth + 1, locals)?;
                match (op, value) {
                    (UnaryOp::Neg, ComptimeValue::Literal(HirLiteral::Integer(v))) => {
                        let parsed = parse_i64_literal(&v)?;
                        Some(ComptimeValue::Literal(HirLiteral::Integer(
                            (-parsed).to_string(),
                        )))
                    }
                    (UnaryOp::Not, ComptimeValue::Literal(HirLiteral::Bool(v))) => {
                        Some(ComptimeValue::Literal(HirLiteral::Bool(!v)))
                    }
                    (UnaryOp::BitNot, ComptimeValue::Literal(HirLiteral::Integer(v))) => {
                        let parsed = parse_i64_literal(&v)?;
                        Some(ComptimeValue::Literal(HirLiteral::Integer(
                            (!parsed).to_string(),
                        )))
                    }
                    _ => None,
                }
            }
            HirExprKind::Binary { op, left, right } => {
                let left = self.try_eval_comptime_expr_with_locals(left, depth + 1, locals)?;
                let right = self.try_eval_comptime_expr_with_locals(right, depth + 1, locals)?;
                eval_comptime_binary(*op, left, right)
            }
            HirExprKind::Let { name, value, .. } => {
                let value = self.try_eval_comptime_expr_with_locals(value, depth + 1, locals)?;
                locals.insert(name.clone(), value.clone());
                Some(value)
            }
            HirExprKind::Assign { target, value, .. } => {
                let HirExprKind::Ident(name) = &target.kind else {
                    return None;
                };
                let value = self.try_eval_comptime_expr_with_locals(value, depth + 1, locals)?;
                locals.insert(name.clone(), value.clone());
                Some(value)
            }
            HirExprKind::Block { body } => {
                let mut scope = locals.clone();
                let mut last = None;
                for value in body {
                    if let HirExprKind::Return { value } = &value.kind {
                        if let Some(value) = value {
                            return self.try_eval_comptime_expr_with_locals(
                                value,
                                depth + 1,
                                &mut scope,
                            );
                        }
                        return None;
                    }
                    last = self.try_eval_comptime_expr_with_locals(value, depth + 1, &mut scope);
                }
                last
            }
            HirExprKind::If {
                condition,
                capture,
                then_branch,
                else_branch,
            } => {
                let condition_value =
                    self.try_eval_comptime_expr_with_locals(condition, depth + 1, locals)?;
                if comptime_truthy(&condition_value) {
                    let mut scope = locals.clone();
                    if let Some(capture) = capture {
                        if let Some(binding) = &capture.binding {
                            if binding != "_" {
                                scope.insert(binding.clone(), condition_value.clone());
                            }
                        }
                    }
                    self.try_eval_comptime_expr_with_locals(then_branch, depth + 1, &mut scope)
                } else if let Some(else_branch) = else_branch {
                    let mut scope = locals.clone();
                    self.try_eval_comptime_expr_with_locals(else_branch, depth + 1, &mut scope)
                } else {
                    None
                }
            }
            HirExprKind::Return { value } => value.as_ref().and_then(|value| {
                self.try_eval_comptime_expr_with_locals(value, depth + 1, locals)
            }),
            HirExprKind::Call { callee, args } => {
                let HirExprKind::Ident(name) = &callee.kind else {
                    return None;
                };
                match name.as_str() {
                    "$sizeof" | "$alignof" => {
                        if args.len() != 1 {
                            return None;
                        }
                        let type_name = self.comptime_type_name_from_expr_with_locals(
                            &args[0].value,
                            depth + 1,
                            locals,
                        )?;
                        let (size, align) = layout_for_builtin_type_name(&type_name);
                        let out = if name == "$sizeof" { size } else { align };
                        Some(ComptimeValue::Literal(HirLiteral::Integer(out.to_string())))
                    }
                    "$offsetof" => {
                        if args.len() != 2 {
                            return None;
                        }
                        let type_name = self.comptime_type_name_from_expr_with_locals(
                            &args[0].value,
                            depth + 1,
                            locals,
                        )?;
                        let off = builtin_offsetof_for_type_name(&type_name, &args[1].value)?;
                        Some(ComptimeValue::Literal(HirLiteral::Integer(off.to_string())))
                    }
                    "$typeof" => {
                        if args.len() != 1 {
                            return None;
                        }
                        // For ident arguments, prefer the MIR value type (from value_types)
                        // over the comptime-inferred type, because casts (e.g. `a: u64 = 99`)
                        // preserve the correct MIR type but lose it when unwrapped to a
                        // ComptimeValue literal.
                        if let HirExprKind::Ident(ident_name) = &args[0].value.kind {
                            if let Some(&mir_id) = self.locals.get(ident_name.as_str()) {
                                let mir_ty_name =
                                    self.value_types
                                        .get(&mir_id)
                                        .and_then(|mir_ty| match mir_ty {
                                            MirValueType::Bool => Some("u1".to_string()),
                                            MirValueType::BytesSlice => Some("[]u8".to_string()),
                                            MirValueType::Int { signed: true, bits } => {
                                                Some(format!("i{bits}"))
                                            }
                                            MirValueType::Int {
                                                signed: false,
                                                bits,
                                            } => Some(format!("u{bits}")),
                                            MirValueType::Float { bits } => {
                                                Some(format!("f{bits}"))
                                            }
                                            MirValueType::Type => Some("type".to_string()),
                                            MirValueType::Function
                                            | MirValueType::FunctionPointer
                                            | MirValueType::Closure => Some("fn".to_string()),
                                            MirValueType::Unknown => None,
                                        });
                                if let Some(ty_name) = mir_ty_name {
                                    return Some(ComptimeValue::Type(ty_name));
                                }
                            }
                        }
                        let inner = self.try_eval_comptime_expr_with_locals(
                            &args[0].value,
                            depth + 1,
                            locals,
                        )?;
                        let ty_name = match inner {
                            ComptimeValue::Literal(HirLiteral::Integer(_)) => "i32".to_string(),
                            ComptimeValue::Literal(HirLiteral::Float(_)) => "f64".to_string(),
                            ComptimeValue::Literal(HirLiteral::Bool(_)) => "u1".to_string(),
                            ComptimeValue::Literal(HirLiteral::Char(_)) => "u8".to_string(),
                            ComptimeValue::Literal(HirLiteral::String(_)) => "[]u8".to_string(),
                            ComptimeValue::Literal(HirLiteral::Null) => "unknown".to_string(),
                            ComptimeValue::Type(_) => "type".to_string(),
                            ComptimeValue::Function(_) => "fn".to_string(),
                        };
                        Some(ComptimeValue::Type(ty_name))
                    }
                    "$as" => {
                        if args.len() != 2 {
                            return None;
                        }
                        let target = self.comptime_type_name_from_expr_with_locals(
                            &args[0].value,
                            depth + 1,
                            locals,
                        )?;
                        let value = self.try_eval_comptime_expr_with_locals(
                            &args[1].value,
                            depth + 1,
                            locals,
                        )?;
                        eval_comptime_cast(&target, value)
                    }
                    "$self" => {
                        if !args.is_empty() {
                            return None;
                        }
                        let self_name = self
                            .current_param_type_hints
                            .first()
                            .and_then(|hint| hint.as_ref())
                            .map(|hint| self_type_literal_from_param_hint(hint))
                            .or_else(|| self.current_self_type_hint.clone())
                            .unwrap_or_else(|| "unknown".to_string());
                        Some(ComptimeValue::Type(self_name))
                    }
                    "$is_uint" | "$is_sint" | "$is_float" => {
                        if args.len() != 1 {
                            return None;
                        }
                        let type_name = self
                            .eval_type_designator_name(&args[0].value, locals)
                            .unwrap_or_default();
                        let result = match name.as_str() {
                            "$is_uint" => {
                                matches!(type_name.as_str(), "u8" | "u16" | "u32" | "u64" | "usize")
                            }
                            "$is_sint" => {
                                matches!(type_name.as_str(), "i8" | "i16" | "i32" | "i64")
                            }
                            "$is_float" => matches!(type_name.as_str(), "f32" | "f64"),
                            _ => false,
                        };
                        Some(ComptimeValue::Literal(HirLiteral::Bool(result)))
                    }
                    "$typeclass" => {
                        if args.len() != 1 {
                            return None;
                        }
                        let type_name = self
                            .eval_type_designator_name(&args[0].value, locals)
                            .unwrap_or_default();
                        let class = type_name_to_class(&type_name);
                        Some(ComptimeValue::Type(class.to_string()))
                    }
                    "$has_method" | "$has_field" => {
                        if args.len() != 2 {
                            return None;
                        }
                        let type_name = match &args[0].value.kind {
                            HirExprKind::Ident(n) => {
                                if let Some(ComptimeValue::Type(t)) = locals.get(n.as_str()) {
                                    t.clone()
                                } else {
                                    n.clone()
                                }
                            }
                            _ => {
                                // Try evaluating the first arg as a comptime expression (e.g. `$typeof(v)`).
                                match self.try_eval_comptime_expr_with_locals(
                                    &args[0].value,
                                    depth + 1,
                                    locals,
                                ) {
                                    Some(ComptimeValue::Type(t)) => t,
                                    _ => return None,
                                }
                            }
                        };
                        let member_name = match &args[1].value.kind {
                            HirExprKind::Literal(HirLiteral::String(s)) => s.clone(),
                            _ => return None,
                        };
                        let exists = if name == "$has_method" {
                            let key = format!("{}__{}", type_name, member_name);
                            self.function_exprs.contains_key(&key)
                        } else {
                            let descriptor = self
                                .named_type_literals
                                .get(&type_name)
                                .cloned()
                                .unwrap_or_else(|| type_name.clone());
                            has_struct_field(&descriptor, &member_name)
                        };
                        Some(ComptimeValue::Literal(HirLiteral::Bool(exists)))
                    }
                    "$typename" => {
                        if args.len() != 1 {
                            return None;
                        }
                        let type_name = self.comptime_type_name_from_expr_with_locals(
                            &args[0].value,
                            depth + 1,
                            locals,
                        )?;
                        Some(ComptimeValue::Literal(HirLiteral::String(type_name)))
                    }
                    _ => self.try_eval_named_comptime_call(name, args, depth + 1, locals),
                }
            }
            HirExprKind::FieldAccess { base, field } => {
                // Comptime field access: only $target().field is supported.
                if let HirExprKind::Call {
                    callee,
                    args: call_args,
                } = &base.kind
                {
                    let callee_name = match &callee.kind {
                        HirExprKind::Ident(n) => n.as_str(),
                        _ => return None,
                    };
                    if callee_name == "$target" && call_args.is_empty() {
                        return match field.as_str() {
                            "sanitize" => Some(ComptimeValue::Literal(HirLiteral::Bool(
                                self.build_config.sanitize,
                            ))),
                            "mode" => {
                                let tag = match self.build_config.opt_level {
                                    crate::compiler::backend::BuildOptLevel::Default
                                    | crate::compiler::backend::BuildOptLevel::O0 => 0i64,
                                    crate::compiler::backend::BuildOptLevel::O1 => 1,
                                    crate::compiler::backend::BuildOptLevel::O2
                                    | crate::compiler::backend::BuildOptLevel::O3 => 2,
                                    crate::compiler::backend::BuildOptLevel::Os
                                    | crate::compiler::backend::BuildOptLevel::Oz => 3,
                                };
                                Some(ComptimeValue::Literal(HirLiteral::Integer(tag.to_string())))
                            }
                            "arch" => {
                                #[cfg(target_arch = "x86_64")]
                                let tag = 0i64;
                                #[cfg(target_arch = "aarch64")]
                                let tag = 1i64;
                                #[cfg(not(any(target_arch = "x86_64", target_arch = "aarch64")))]
                                let tag = 0i64;
                                Some(ComptimeValue::Literal(HirLiteral::Integer(tag.to_string())))
                            }
                            "os" => {
                                #[cfg(target_os = "linux")]
                                let tag = 0i64;
                                #[cfg(target_os = "macos")]
                                let tag = 1i64;
                                #[cfg(target_os = "windows")]
                                let tag = 2i64;
                                #[cfg(not(any(
                                    target_os = "linux",
                                    target_os = "macos",
                                    target_os = "windows"
                                )))]
                                let tag = 3i64;
                                Some(ComptimeValue::Literal(HirLiteral::Integer(tag.to_string())))
                            }
                            _ => None,
                        };
                    }
                }
                None
            }
            _ => None,
        }
    }

    pub(super) fn try_eval_named_comptime_call(
        &self,
        name: &str,
        args: &[HirCallArg],
        depth: usize,
        caller_locals: &mut BTreeMap<String, ComptimeValue>,
    ) -> Option<ComptimeValue> {
        let (resolved_name, came_from_local_binding) =
            if let Some(ComptimeValue::Function(function_name)) = caller_locals.get(name) {
                (function_name.clone(), true)
            } else {
                (name.to_string(), false)
            };
        let (target, captures_caller_locals) = if came_from_local_binding {
            if let Some(local_target) = self.comptime_local_function_exprs.get(&resolved_name) {
                (local_target, true)
            } else {
                (self.function_exprs.get(&resolved_name)?, false)
            }
        } else {
            (self.function_exprs.get(&resolved_name)?, false)
        };
        match &target.kind {
            HirExprKind::Function {
                params,
                param_defaults,
                body,
                ..
            } => {
                if args.len() > params.len() {
                    return None;
                }

                let lowered_args = args
                    .iter()
                    .map(|arg| (arg.name.clone(), &arg.value))
                    .collect::<Vec<_>>();
                let ordered = self.order_named_call_items(params, &lowered_args);

                let mut locals = if captures_caller_locals {
                    caller_locals.clone()
                } else {
                    BTreeMap::new()
                };
                for (idx, param_name) in params.iter().enumerate() {
                    let value = if let Some(expr) = ordered[idx] {
                        self.try_eval_comptime_expr_with_locals(expr, depth + 1, caller_locals)?
                    } else if let Some(Some(default_expr)) = param_defaults.get(idx) {
                        self.try_eval_comptime_expr_with_locals(
                            default_expr,
                            depth + 1,
                            &mut locals,
                        )?
                    } else {
                        return None;
                    };
                    locals.insert(param_name.clone(), value);
                }

                self.try_eval_comptime_expr_with_locals(body, depth + 1, &mut locals)
            }
            _ => {
                if !args.is_empty() {
                    return None;
                }
                let mut locals = BTreeMap::new();
                self.try_eval_comptime_expr_with_locals(target, depth + 1, &mut locals)
            }
        }
    }

    pub(super) fn comptime_type_name_from_expr_with_locals(
        &self,
        expr: &HirExpr,
        depth: usize,
        locals: &BTreeMap<String, ComptimeValue>,
    ) -> Option<String> {
        match &expr.kind {
            HirExprKind::TypeLiteral(name) => Some(substitute_type_locals(name, locals)),
            HirExprKind::Ident(name) => {
                if let Some(ComptimeValue::Type(type_name)) = locals.get(name) {
                    return Some(type_name.clone());
                }
                if let Some(resolved) = type_literal_name_for_ident(name, &self.named_type_literals)
                {
                    return Some(resolved);
                }
                if let Some(target) = self.function_exprs.get(name) {
                    if let Some(ComptimeValue::Type(type_name)) = self
                        .try_eval_comptime_expr_with_locals(target, depth + 1, &mut locals.clone())
                    {
                        return Some(type_name);
                    }
                }
                Some(name.clone())
            }
            _ => self
                .try_eval_comptime_expr_with_locals(expr, depth + 1, &mut locals.clone())
                .and_then(|value| match value {
                    ComptimeValue::Type(name) => Some(name),
                    ComptimeValue::Function(_) | ComptimeValue::Literal(_) => None,
                }),
        }
    }

    /// Try to evaluate a `$typeof(expr)` call as a comptime type by lowering
    /// `expr` as MIR and reading its inferred `MirValueType`. Used as a fallback
    /// in `comp match $typeof(v)` when `v` is a runtime parameter.
    pub(super) fn try_eval_typeof_discriminant(
        &mut self,
        block: MirBlockId,
        expr: &HirExpr,
    ) -> Option<ComptimeValue> {
        let HirExprKind::Call { callee, args } = &expr.kind else {
            return None;
        };
        let HirExprKind::Ident(name) = &callee.kind else {
            return None;
        };
        if name != "$typeof" || args.len() != 1 {
            return None;
        }
        let (_end, arg_val) = self.lower_expr(block, &args[0].value);
        let arg_val = arg_val?;
        let resolved_ty = self
            .value_types
            .get(&arg_val)
            .cloned()
            .unwrap_or(MirValueType::Unknown);
        let ty_name = match resolved_ty {
            MirValueType::Bool => "u1".to_string(),
            MirValueType::BytesSlice => "[]u8".to_string(),
            MirValueType::Int { signed: true, bits } => format!("i{bits}"),
            MirValueType::Int {
                signed: false,
                bits,
            } => format!("u{bits}"),
            MirValueType::Float { bits } => format!("f{bits}"),
            MirValueType::Type => "type".to_string(),
            MirValueType::Function | MirValueType::FunctionPointer | MirValueType::Closure => {
                "fn".to_string()
            }
            MirValueType::Unknown => return None,
        };
        Some(ComptimeValue::Type(ty_name))
    }
}

impl FunctionLowerer {
    pub(super) fn top_level_import_path(&self, name: &str) -> Option<&str> {
        self.function_exprs.get(name).and_then(|expr| {
            if let HirExprKind::Use { path } = &expr.kind {
                Some(path.as_str())
            } else {
                None
            }
        })
    }

    pub(super) fn resolve_import_member_ident(
        &self,
        import_path: &str,
        field: &str,
    ) -> Option<String> {
        let target_key =
            crate::compiler::module_resolver::module_key_for_import(&self.module_key, import_path);
        let target_module_id = self.module_ids_by_key.get(&target_key).copied()?;
        let exports = self.module_exports_by_id.get(&target_module_id)?;
        if exports.iter().any(|name| name == field) {
            Some(qualified_function_name(target_module_id, field))
        } else {
            None
        }
    }

    pub(super) fn infer_call_result_type(&self, callee: MirValueId, depth: usize) -> MirValueType {
        if depth > 8 {
            return MirValueType::Unknown;
        }
        if let Some(name) = self.resolve_callee_function_name(callee, depth) {
            let inferred = self
                .function_return_types
                .get(&name)
                .cloned()
                .unwrap_or(MirValueType::Unknown);
            if !matches!(inferred, MirValueType::Unknown) {
                return inferred;
            }
            return MirValueType::Unknown;
        }
        match self.value_defs.get(&callee) {
            Some(MirValue::Param { index }) => {
                if let Some(Some(hint)) = self.current_param_type_hints.get(*index) {
                    if let Some(ret) = parse_function_return_hint(hint) {
                        return ret;
                    }
                }
                self.value_types
                    .get(&callee)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown)
            }
            _ => MirValueType::Unknown,
        }
    }

    pub(super) fn resolve_callee_function_name(
        &self,
        value: MirValueId,
        depth: usize,
    ) -> Option<String> {
        if depth > 8 {
            return None;
        }
        match self.value_defs.get(&value) {
            Some(MirValue::Ident(name)) => Some(name.clone()),
            Some(MirValue::LocalSet { value, .. }) | Some(MirValue::Assign { value, .. }) => {
                self.resolve_callee_function_name(*value, depth + 1)
            }
            _ => None,
        }
    }
}
