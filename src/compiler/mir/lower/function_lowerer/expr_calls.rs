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
            inline_call_depth: 0,
            inline_call_stack: Vec::new(),
            loop_stack: Vec::new(),
            or_break_stack: Vec::new(),
            deferred: Vec::new(),
            diagnostics: Vec::new(),
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
                if let Some(runtime_symbol) = runtime_symbol_for_builtin(name) {
                    return (
                        block,
                        Some(self.push_eval(
                            block,
                            MirValue::Ident(runtime_symbol.to_string()),
                            MirValueType::FunctionPointer,
                        )),
                    );
                }
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
                    let ty = if self.function_return_types.contains_key(name) {
                        MirValueType::FunctionPointer
                    } else {
                        MirValueType::Unknown
                    };
                    (
                        block,
                        Some(self.push_eval(block, MirValue::Ident(name.clone()), ty)),
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
                        if let Some(import_path) = self.top_level_import_path(base_name) {
                            if let Some(qualified) =
                                self.resolve_import_member_ident(import_path, field)
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
            HirExprKind::Function { .. } => (
                block,
                Some(self.push_eval(block, MirValue::Unknown, MirValueType::Unknown)),
            ),
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
                    let old = self.locals.get(name).copied();
                    self.locals.insert(name.to_string(), iter_value);
                    old
                } else {
                    None
                };

                let (next, _) = self.lower_expr(at, body);
                at = next;

                if let Some(name) = binding {
                    if let Some(old) = previous {
                        self.locals.insert(name.to_string(), old);
                    } else {
                        self.locals.remove(name);
                    }
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

    pub(super) fn is_format_print_call(
        &self,
        callee: &HirExpr,
        resolved_name: Option<&str>,
    ) -> bool {
        let is_known_name = |name: &str| {
            name == "print"
                || name == "println"
                || name.ends_with("::print")
                || name.ends_with("::println")
        };

        if let Some(name) = resolved_name {
            if is_known_name(name) {
                return true;
            }
        }

        match &callee.kind {
            HirExprKind::Ident(name) => is_known_name(name),
            HirExprKind::FieldAccess { field, .. } => is_known_name(field),
            _ => false,
        }
    }

    pub(super) fn tuple_like_aggregate_values(&self, value: MirValueId) -> Option<Vec<MirValueId>> {
        let sequence = self.aggregate_sequences.get(&value)?;
        let fields = self.struct_fields.get(&value)?;
        if fields.len() != sequence.len() {
            return None;
        }
        for (index, element) in sequence.iter().enumerate() {
            let key = format!("__{index}");
            if fields.get(&key).copied() != Some(*element) {
                return None;
            }
        }
        Some(sequence.clone())
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

        if lowered_named.len() == 2
            && lowered_named.iter().all(|(name, _)| name.is_none())
            && self.is_format_print_call(callee, callee_name.as_deref())
        {
            if let Some(tuple_values) = self.tuple_like_aggregate_values(lowered_named[1].1) {
                let mut expanded = Vec::with_capacity(1 + tuple_values.len());
                expanded.push(lowered_named[0].clone());
                expanded.extend(tuple_values.into_iter().map(|value| (None, value)));
                lowered_named = expanded;
                lowered_args = lowered_named.iter().map(|(_, value)| *value).collect();
            }
        }

        if let Some(name) = &callee_name {
            if let Some(param_names) = self.function_param_names.get(name) {
                let mut ordered = vec![None; param_names.len()];
                for (arg_name, value) in &lowered_named {
                    if let Some(arg_name) = arg_name {
                        if let Some(index) = param_names.iter().position(|param| param == arg_name)
                        {
                            ordered[index] = Some(*value);
                        }
                    }
                }
                let mut positional_iter = lowered_named.iter().filter_map(|(arg_name, value)| {
                    if arg_name.is_none() {
                        Some(*value)
                    } else {
                        None
                    }
                });
                for slot in &mut ordered {
                    if slot.is_none() {
                        *slot = positional_iter.next();
                    }
                }

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
            let old = self.locals.get(param).copied();
            self.locals.insert(param.clone(), *value);
            previous.push((param.clone(), old));
        }

        self.inline_call_depth += 1;
        self.inline_call_stack.push(callee_name.to_string());
        let (end, value) = self.lower_expr(block, &inline_body);
        self.inline_call_stack.pop();
        self.inline_call_depth -= 1;

        for (name, old) in previous.into_iter().rev() {
            if let Some(old) = old {
                self.locals.insert(name, old);
            } else {
                self.locals.remove(&name);
            }
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
                    let prev = self.locals.insert(binding.clone(), value);
                    let (end, _) = self.lower_expr(at, &deferred_expr.body);
                    at = end;
                    if let Some(prev) = prev {
                        self.locals.insert(binding.clone(), prev);
                    } else {
                        self.locals.remove(binding);
                    }
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
