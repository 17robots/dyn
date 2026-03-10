#[allow(clippy::too_many_arguments)]
pub(super) fn infer_function_value_call_type(
    call: &crate::compiler::ast::CallExpr,
    callee_ty: TypeId,
    env: &BTreeMap<String, TypeId>,
    mutability: &BTreeMap<String, bool>,
    signatures: &BTreeMap<String, FnSignature>,
    types: &mut TypeStore,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
    expected_return: Option<TypeId>,
) -> Option<TypeId> {
    let Type::Function {
        param_types,
        param_names,
        has_defaults,
        return_type,
    } = types.get(callee_ty).clone()
    else {
        return None;
    };

    let required = has_defaults.iter().filter(|d| !**d).count();
    let mut ordered_args = vec![None; param_types.len()];
    for arg in &call.args {
        if let Some(name) = &arg.name {
            let Some(index) = param_names.iter().position(|param| {
                param
                    .as_ref()
                    .map(|text| text == &name.text)
                    .unwrap_or(false)
            }) else {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "unknown named argument for function value call",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(arg.value.span),
                        "named argument does not match any parameter",
                    ),
                );
                continue;
            };
            if ordered_args[index].is_some() {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "duplicate named argument for function value call",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(arg.value.span),
                        "parameter already has an argument",
                    ),
                );
                continue;
            }
            ordered_args[index] = Some(arg);
        }
    }
    let mut positional_iter = call.args.iter().filter(|arg| arg.name.is_none());
    for slot in &mut ordered_args {
        if slot.is_none() {
            *slot = positional_iter.next();
        }
    }
    let provided = ordered_args.iter().filter(|slot| slot.is_some()).count();
    if provided < required || provided > param_types.len() {
        diagnostics.push(
            Diagnostic::error(
                DiagnosticPhase::TypeChecker,
                DiagnosticCode::E4005,
                format!(
                    "function value call arity mismatch: expected {}..={}, got {}",
                    required,
                    param_types.len(),
                    call.args.len()
                ),
            )
            .with_primary_file_label(
                file_path.to_path_buf(),
                Some(call.callee.span),
                "adjust argument count to match function value signature",
            ),
        );
    }
    let mut type_param_bindings = BTreeMap::<String, TypeId>::new();
    let mut pending_type_designators = VecDeque::<TypeId>::new();
    for (idx, arg) in ordered_args.into_iter().enumerate() {
        if let (Some(expected_ty), Some(arg)) = (param_types.get(idx), arg) {
            if matches!(types.get(*expected_ty), Type::TypeType)
                && !is_type_designator_expr(&arg.value)
            {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "function value argument must be a type designator",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(arg.value.span),
                        "pass a type name or type literal",
                    ),
                );
            }
            let mut actual_ty = infer_expr_type(
                &arg.value,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            if matches!(types.get(*expected_ty), Type::TypeType) {
                if let Some(designated) = resolve_type_designator_arg(&arg.value, types) {
                    pending_type_designators.push_back(designated);
                }
            }
            let resolved_expected = match types.get(*expected_ty) {
                Type::TypeParam(name) => {
                    if let Some(bound) = type_param_bindings.get(name).copied() {
                        bound
                    } else if let Some(pending) = pending_type_designators.pop_front() {
                        type_param_bindings.insert(name.clone(), pending);
                        pending
                    } else {
                        type_param_bindings.insert(name.clone(), actual_ty);
                        actual_ty
                    }
                }
                _ => *expected_ty,
            };
            actual_ty =
                maybe_coerce_literal_to_expected(&arg.value, actual_ty, resolved_expected, types);
            if !types_compatible(resolved_expected, actual_ty, types) {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "function value argument type mismatch",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(arg.value.span),
                        "argument type does not match function value parameter",
                    ),
                );
            }
        }
    }
    if let Type::TypeParam(name) = types.get(return_type) {
        if let Some(bound) = type_param_bindings.get(name).copied() {
            return Some(bound);
        }
    }
    Some(return_type)
}

#[allow(clippy::too_many_arguments)]
pub(super) fn infer_call_type(
    call: &crate::compiler::ast::CallExpr,
    env: &BTreeMap<String, TypeId>,
    mutability: &BTreeMap<String, bool>,
    signatures: &BTreeMap<String, FnSignature>,
    types: &mut TypeStore,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
    expr: &Expr,
    expected_return: Option<TypeId>,
) -> TypeId {
    let callee_ty = infer_expr_type(
        &call.callee,
        env,
        mutability,
        signatures,
        types,
        diagnostics,
        file_path,
        expected_return,
    );

    let Some(callee_name) = extract_callee_name(&call.callee) else {
        if let Some(return_ty) = infer_function_value_call_type(
            call,
            callee_ty,
            env,
            mutability,
            signatures,
            types,
            diagnostics,
            file_path,
            expected_return,
        ) {
            return return_ty;
        }

        if !matches!(
            types.get(callee_ty),
            Type::Unknown
                | Type::Function { .. }
                | Type::Pointer { .. }
                | Type::TypeParam(_)
                | Type::Any
        ) {
            diagnostics.push(
                Diagnostic::error(
                    DiagnosticPhase::TypeChecker,
                    DiagnosticCode::E4005,
                    "called value is not a function",
                )
                .with_primary_file_label(
                    file_path.to_path_buf(),
                    Some(call.callee.span),
                    "call target must be a function or function value",
                ),
            );
        }
        return types.intern(Type::Unknown);
    };

    if let Some(builtin_ty) = infer_builtin_call_type(
        &callee_name,
        call,
        env,
        mutability,
        signatures,
        types,
        diagnostics,
        file_path,
        expr,
        expected_return,
    ) {
        return builtin_ty;
    }

    let signature_name = runtime_builtin_symbol_name(&callee_name)
        .map(str::to_string)
        .unwrap_or_else(|| callee_name.clone());

    let Some(sig) = signatures.get(&signature_name) else {
        if let Some(return_ty) = infer_function_value_call_type(
            call,
            callee_ty,
            env,
            mutability,
            signatures,
            types,
            diagnostics,
            file_path,
            expected_return,
        ) {
            return return_ty;
        }

        if !matches!(
            types.get(callee_ty),
            Type::Unknown
                | Type::Function { .. }
                | Type::Pointer { .. }
                | Type::TypeParam(_)
                | Type::Any
        ) {
            diagnostics.push(
                Diagnostic::error(
                    DiagnosticPhase::TypeChecker,
                    DiagnosticCode::E4005,
                    "called value is not a function",
                )
                .with_primary_file_label(
                    file_path.to_path_buf(),
                    Some(call.callee.span),
                    "call target must be a function or function value",
                ),
            );
        }
        return types.intern(Type::Unknown);
    };

    let mut named_seen = BTreeSet::<String>::new();
    let mut positional_count = 0usize;
    let mut used_params = BTreeSet::<usize>::new();
    let mut specialized_return = None;
    let mut type_param_bindings = BTreeMap::<String, TypeId>::new();

    let direct_param_types = env
        .get(&callee_name)
        .or_else(|| {
            if signature_name != callee_name {
                env.get(&signature_name)
            } else {
                None
            }
        })
        .and_then(|type_id| match types.get(*type_id) {
            Type::Function { param_types, .. } => Some(param_types.clone()),
            _ => None,
        });
    let return_from_type_param_idx = match types.get(sig.return_type) {
        Type::TypeParam(param_name) => sig
            .params
            .iter()
            .position(|param| param.name.as_deref() == Some(param_name.as_str())),
        Type::Unknown => direct_param_types.as_ref().and_then(|params| {
            params
                .iter()
                .position(|param| matches!(types.get(*param), Type::TypeType))
        }),
        _ => None,
    };

    for arg in &call.args {
        if let Some(name) = &arg.name {
            let Some(param_index) = sig
                .params
                .iter()
                .position(|param| param.name.as_deref() == Some(name.text.as_str()))
            else {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        format!("unknown named argument '{}'", name.text),
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "named argument does not match any parameter",
                    ),
                );
                continue;
            };

            if let Some(param_types) = &direct_param_types {
                if let Some(expected_ty) = param_types.get(param_index) {
                    let resolved_expected = match types.get(*expected_ty) {
                        Type::TypeParam(name) => type_param_bindings
                            .get(name)
                            .copied()
                            .unwrap_or(*expected_ty),
                        _ => *expected_ty,
                    };
                    if matches!(types.get(*expected_ty), Type::TypeType)
                        && !is_type_designator_expr(&arg.value)
                    {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "call argument must be a type designator",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(arg.value.span),
                                "pass a type name or type literal",
                            ),
                        );
                    }
                    let mut actual_ty = infer_expr_type(
                        &arg.value,
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                    actual_ty = maybe_coerce_literal_to_expected(
                        &arg.value,
                        actual_ty,
                        resolved_expected,
                        types,
                    );
                    if let Some(param_name) = sig.params[param_index].name.as_ref() {
                        if matches!(types.get(*expected_ty), Type::TypeType) {
                            if let Some(designated) = resolve_type_designator_arg(&arg.value, types)
                            {
                                if let Some(bound) = type_param_bindings.get(param_name).copied() {
                                    if bound != designated {
                                        diagnostics.push(
                                            Diagnostic::error(
                                                DiagnosticPhase::TypeChecker,
                                                DiagnosticCode::E4005,
                                                "call argument type mismatch",
                                            )
                                            .with_primary_file_label(
                                                file_path.to_path_buf(),
                                                Some(arg.value.span),
                                                "argument type does not match parameter type",
                                            ),
                                        );
                                    }
                                } else {
                                    type_param_bindings.insert(param_name.clone(), designated);
                                }
                            }
                        }
                    }
                    if let Type::TypeParam(name) = types.get(*expected_ty) {
                        if let Some(bound) = type_param_bindings.get(name).copied() {
                            if !types_compatible(bound, actual_ty, types) {
                                diagnostics.push(
                                    Diagnostic::error(
                                        DiagnosticPhase::TypeChecker,
                                        DiagnosticCode::E4005,
                                        "call argument type mismatch",
                                    )
                                    .with_primary_file_label(
                                        file_path.to_path_buf(),
                                        Some(arg.value.span),
                                        "argument type does not match parameter type",
                                    ),
                                );
                            }
                        } else {
                            type_param_bindings.insert(name.clone(), actual_ty);
                        }
                    }
                    if !types_compatible(resolved_expected, actual_ty, types) {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "call argument type mismatch",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(arg.value.span),
                                "argument type does not match parameter type",
                            ),
                        );
                    }
                }
            }

            if !named_seen.insert(name.text.clone()) {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        format!("duplicate named argument '{}'", name.text),
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "remove duplicate argument",
                    ),
                );
            }
            used_params.insert(param_index);
            if return_from_type_param_idx == Some(param_index) {
                specialized_return =
                    resolve_type_designator_arg(&arg.value, types).or(specialized_return);
            }
        } else {
            if positional_count >= sig.params.len() {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "too many positional arguments",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "call exceeds function arity",
                    ),
                );
                continue;
            }

            if let Some(param_types) = &direct_param_types {
                if let Some(expected_ty) = param_types.get(positional_count) {
                    let resolved_expected = match types.get(*expected_ty) {
                        Type::TypeParam(name) => type_param_bindings
                            .get(name)
                            .copied()
                            .unwrap_or(*expected_ty),
                        _ => *expected_ty,
                    };
                    if matches!(types.get(*expected_ty), Type::TypeType)
                        && !is_type_designator_expr(&arg.value)
                    {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "call argument must be a type designator",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(arg.value.span),
                                "pass a type name or type literal",
                            ),
                        );
                    }
                    let mut actual_ty = infer_expr_type(
                        &arg.value,
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                    actual_ty = maybe_coerce_literal_to_expected(
                        &arg.value,
                        actual_ty,
                        resolved_expected,
                        types,
                    );
                    if let Some(param_name) = sig.params[positional_count].name.as_ref() {
                        if matches!(types.get(*expected_ty), Type::TypeType) {
                            if let Some(designated) = resolve_type_designator_arg(&arg.value, types)
                            {
                                if let Some(bound) = type_param_bindings.get(param_name).copied() {
                                    if bound != designated {
                                        diagnostics.push(
                                            Diagnostic::error(
                                                DiagnosticPhase::TypeChecker,
                                                DiagnosticCode::E4005,
                                                "call argument type mismatch",
                                            )
                                            .with_primary_file_label(
                                                file_path.to_path_buf(),
                                                Some(arg.value.span),
                                                "argument type does not match parameter type",
                                            ),
                                        );
                                    }
                                } else {
                                    type_param_bindings.insert(param_name.clone(), designated);
                                }
                            }
                        }
                    }
                    if let Type::TypeParam(name) = types.get(*expected_ty) {
                        if let Some(bound) = type_param_bindings.get(name).copied() {
                            if !types_compatible(bound, actual_ty, types) {
                                diagnostics.push(
                                    Diagnostic::error(
                                        DiagnosticPhase::TypeChecker,
                                        DiagnosticCode::E4005,
                                        "call argument type mismatch",
                                    )
                                    .with_primary_file_label(
                                        file_path.to_path_buf(),
                                        Some(arg.value.span),
                                        "argument type does not match parameter type",
                                    ),
                                );
                            }
                        } else {
                            type_param_bindings.insert(name.clone(), actual_ty);
                        }
                    }
                    if !types_compatible(resolved_expected, actual_ty, types) {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "call argument type mismatch",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(arg.value.span),
                                "argument type does not match parameter type",
                            ),
                        );
                    }
                }
            }

            used_params.insert(positional_count);
            if return_from_type_param_idx == Some(positional_count) {
                specialized_return =
                    resolve_type_designator_arg(&arg.value, types).or(specialized_return);
            }
            positional_count += 1;
        }
    }

    for (idx, param) in sig.params.iter().enumerate() {
        if !used_params.contains(&idx) && !param.has_default {
            diagnostics.push(
                Diagnostic::error(
                    DiagnosticPhase::TypeChecker,
                    DiagnosticCode::E4005,
                    "missing required argument",
                )
                .with_primary_file_label(
                    file_path.to_path_buf(),
                    Some(expr.span),
                    "provide all non-default parameters",
                ),
            );
        }
    }

    if let Type::TypeParam(name) = types.get(sig.return_type) {
        if let Some(bound) = type_param_bindings.get(name).copied() {
            return bound;
        }
    }

    specialized_return.unwrap_or(sig.return_type)
}

pub(super) fn bind_pattern_names(
    pattern: &PatternKind,
    scrutinee_ty: TypeId,
    types: &mut TypeStore,
    env: &mut BTreeMap<String, TypeId>,
    mutability: &mut BTreeMap<String, bool>,
) {
    match pattern {
        PatternKind::IdentBind(ident) => {
            env.insert(ident.text.clone(), scrutinee_ty);
            mutability.insert(ident.text.clone(), false);
        }
        PatternKind::Range { start, end, .. } => {
            bind_pattern_names(&start.kind, scrutinee_ty, types, env, mutability);
            bind_pattern_names(&end.kind, scrutinee_ty, types, env, mutability);
        }
        PatternKind::EnumVariant { bindings, .. } => {
            let unknown = types.intern(Type::Unknown);
            for ident in bindings {
                env.insert(ident.text.clone(), unknown);
                mutability.insert(ident.text.clone(), false);
            }
        }
        PatternKind::Typed { pattern, ty } => {
            let bound_ty = resolve_type_expr(ty, types).unwrap_or(scrutinee_ty);
            bind_pattern_names(&pattern.kind, bound_ty, types, env, mutability);
        }
        PatternKind::Wildcard | PatternKind::Literal(_) => {}
    }
}

#[allow(clippy::too_many_arguments)]
pub(super) fn infer_builtin_call_type(
    name: &str,
    call: &crate::compiler::ast::CallExpr,
    env: &BTreeMap<String, TypeId>,
    mutability: &BTreeMap<String, bool>,
    signatures: &BTreeMap<String, FnSignature>,
    types: &mut TypeStore,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
    expr: &Expr,
    expected_return: Option<TypeId>,
) -> Option<TypeId> {
    match name {
        "$Self" => {
            if !call.args.is_empty() {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$Self expects no arguments",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "use $Self()",
                    ),
                );
            }
            if env.get("self").is_none() {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$Self is only available in self method context",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "use inside an instance method with self parameter",
                    ),
                );
            }
            return Some(types.intern(Type::TypeType));
        }
        "$sizeof" | "$alignof" => {
            if call.args.len() != 1 {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        format!("{} expects exactly one argument", name),
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "pass one type argument",
                    ),
                );
            }
            return Some(types.intern(Type::Int {
                signed: false,
                bits: 64,
            }));
        }
        "$offsetof" => {
            if call.args.len() != 2 {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$offsetof expects two arguments: type and field name",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "use $offsetof(Type, field)",
                    ),
                );
            } else {
                let type_arg = &call.args[0].value;
                let field_arg = &call.args[1].value;
                if !valid_offsetof_designator(type_arg, field_arg) {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "$offsetof field designator is invalid for the target type",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(field_arg.span),
                            "use an existing field name or in-range field index",
                        ),
                    );
                }
            }
            return Some(types.intern(Type::Int {
                signed: false,
                bits: 64,
            }));
        }
        "$typeof" => {
            if call.args.len() != 1 {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$typeof expects exactly one argument",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "pass one expression argument",
                    ),
                );
            }
            if let Some(arg) = call.args.first() {
                let _ = infer_expr_type(
                    &arg.value,
                    env,
                    mutability,
                    signatures,
                    types,
                    diagnostics,
                    file_path,
                    expected_return,
                );
            }
            return Some(types.intern(Type::TypeType));
        }
        "$as" => {
            if call.args.len() != 2 {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$as expects two arguments: target type and value",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "use $as(Type, value)",
                    ),
                );
                return Some(types.intern(Type::Unknown));
            }

            let target_ty = resolve_builtin_type_arg(&call.args[0].value, types)
                .unwrap_or_else(|| types.intern(Type::Unknown));
            let value_ty = infer_expr_type(
                &call.args[1].value,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            let numeric_cast =
                matches!(types.get(target_ty), Type::Int { .. } | Type::Float { .. })
                    && matches!(types.get(value_ty), Type::Int { .. } | Type::Float { .. });
            let pointer_cast = matches!(types.get(target_ty), Type::Pointer { .. })
                && matches!(types.get(value_ty), Type::Pointer { .. });
            let int_to_pointer_cast = matches!(types.get(target_ty), Type::Pointer { .. })
                && matches!(
                    types.get(value_ty),
                    Type::Int {
                        signed: false,
                        bits: 64
                    }
                );
            let slice_to_pointer_cast = matches!(types.get(target_ty), Type::Pointer { .. })
                && matches!(types.get(value_ty), Type::Slice { .. });
            let pointer_to_usize_cast = matches!(
                (types.get(target_ty), types.get(value_ty)),
                (
                    Type::Int {
                        signed: false,
                        bits: 64
                    },
                    Type::Pointer { .. }
                )
            );
            let slice_to_usize_cast = matches!(
                (types.get(target_ty), types.get(value_ty)),
                (
                    Type::Int {
                        signed: false,
                        bits: 64
                    },
                    Type::Slice { .. }
                )
            );
            if !numeric_cast
                && !pointer_cast
                && !int_to_pointer_cast
                && !slice_to_pointer_cast
                && !pointer_to_usize_cast
                && !slice_to_usize_cast
                && !types_compatible(target_ty, value_ty, types)
                && !types_compatible(value_ty, target_ty, types)
            {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$as value is incompatible with requested target type",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(call.args[1].value.span),
                        "adjust source value or target type",
                    ),
                );
            }
            return Some(target_ty);
        }
        "$compile_error" => {
            diagnostics.push(
                Diagnostic::error(
                    DiagnosticPhase::TypeChecker,
                    DiagnosticCode::E4005,
                    "$compile_error invoked",
                )
                .with_primary_file_label(
                    file_path.to_path_buf(),
                    Some(expr.span),
                    "remove compile error or gate it behind compile-time condition",
                ),
            );
            return Some(types.intern(Type::Unknown));
        }
        "$panic" => {
            if call.args.len() != 1 {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$panic expects one argument",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "use $panic(message)",
                    ),
                );
            } else {
                let message_ty = infer_expr_type(
                    &call.args[0].value,
                    env,
                    mutability,
                    signatures,
                    types,
                    diagnostics,
                    file_path,
                    expected_return,
                );
                let bytes_ty = bytes_type(types);
                if !types_compatible(bytes_ty, message_ty, types) {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "$panic message must be []u8/string compatible",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(call.args[0].value.span),
                            "pass a string literal or []u8 value",
                        ),
                    );
                }
            }
            return Some(types.intern(Type::Unknown));
        }
        "$unreachable" => {
            if !call.args.is_empty() {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$unreachable expects zero arguments",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "remove arguments from $unreachable",
                    ),
                );
            }
            return Some(types.intern(Type::Unknown));
        }
        _ => {}
    }

    None
}

pub(super) fn resolve_builtin_type_arg(expr: &Expr, types: &mut TypeStore) -> Option<TypeId> {
    resolve_type_designator_arg(expr, types)
}

pub(super) fn resolve_type_designator_arg(expr: &Expr, types: &mut TypeStore) -> Option<TypeId> {
    match &expr.kind {
        ExprKind::TypeLiteral(ty) => resolve_type_expr(ty, types),
        ExprKind::Ident(ident) | ExprKind::BuiltinIdent(ident) => {
            if let Some(ty) = resolve_builtin_type_name(&ident.text, types) {
                Some(ty)
            } else {
                Some(types.intern(Type::Applied {
                    callee: ident.text.clone(),
                    args: Vec::new(),
                }))
            }
        }
        ExprKind::Call(call) => {
            let callee_name = match &call.callee.kind {
                ExprKind::Ident(ident) | ExprKind::BuiltinIdent(ident) => ident.text.clone(),
                _ => return None,
            };
            let mut args = Vec::with_capacity(call.args.len());
            for arg in &call.args {
                args.push(resolve_type_designator_arg(&arg.value, types)?);
            }
            Some(types.intern(Type::Applied {
                callee: callee_name,
                args,
            }))
        }
        _ => None,
    }
}

pub(super) fn resolve_builtin_type_name(name: &str, types: &mut TypeStore) -> Option<TypeId> {
    if name == "u1" {
        return Some(types.intern(Type::Bool));
    }
    if let Some(int_ty) = parse_int_type_name(name) {
        return Some(types.intern(int_ty));
    }
    if let Some(float_ty) = parse_float_type_name(name) {
        return Some(types.intern(float_ty));
    }
    match name {
        "type" => Some(types.intern(Type::TypeType)),
        "opaque" => Some(types.intern(Type::Opaque)),
        "any" => Some(types.intern(Type::Any)),
        "void" => Some(types.intern(Type::Void)),
        _ => None,
    }
}

pub(super) fn extract_fn_expr(expr: &Expr) -> Option<&crate::compiler::ast::FnExpr> {
    match &expr.kind {
        ExprKind::Fn(fn_expr) => Some(fn_expr),
        ExprKind::Inline { expr } => extract_fn_expr(expr),
        _ => None,
    }
}

pub(super) fn is_function_expr(expr: &Expr) -> bool {
    extract_fn_expr(expr).is_some()
}

pub(super) fn validate_inline_expr(
    expr: &Expr,
    _signatures: &BTreeMap<String, FnSignature>,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
) {
    match &expr.kind {
        ExprKind::For(for_expr) => match for_expr {
            crate::compiler::ast::ForExpr::Range {
                start, end, body, ..
            } => {
                if !is_compile_time_expr(start) || !is_compile_time_expr(end) {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4011,
                            "inline for requires compile-time range bounds",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "use literals or comptime-evaluable bound expressions",
                        ),
                    );
                }
                if contains_disallowed_inline_flow(body) {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "inline for body uses unsupported control flow",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(body.span),
                            "avoid return/defer/break/continue inside inline for bodies",
                        ),
                    );
                }
            }
            _ => diagnostics.push(
                Diagnostic::error(
                    DiagnosticPhase::TypeChecker,
                    DiagnosticCode::E4005,
                    "inline for only supports range loops",
                )
                .with_primary_file_label(
                    file_path.to_path_buf(),
                    Some(expr.span),
                    "use `inline for start..end` with compile-time bounds",
                ),
            ),
        },
        ExprKind::Call(call) => {
            let supported = match &call.callee.kind {
                ExprKind::Ident(_) => true,
                _ => false,
            };
            if !supported {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4010,
                        "inline call requires a direct function identifier",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(call.callee.span),
                        "inline calls must target a named function",
                    ),
                );
            }
        }
        ExprKind::Fn(fn_expr) => {
            if !inline_function_body_supported(&fn_expr.body) {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "inline function body uses unsupported control flow",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "avoid return/defer/break/continue inside inline function bodies",
                    ),
                );
            }
        }
        _ => diagnostics.push(
            Diagnostic::error(
                DiagnosticPhase::TypeChecker,
                DiagnosticCode::E4012,
                "unsupported inline expression",
            )
            .with_primary_file_label(
                file_path.to_path_buf(),
                Some(expr.span),
                "inline currently supports range loops, direct calls, and function literals",
            ),
        ),
    }
}

pub(super) fn inline_function_body_supported(body: &FnBody) -> bool {
    match body {
        FnBody::ArrowExpr(expr) => !contains_disallowed_inline_flow(expr),
        FnBody::Block(block) => {
            !block.statements.iter().any(|stmt| match stmt {
                Stmt::Binding(binding) => contains_disallowed_inline_flow(&binding.value),
                Stmt::Expr(expr) => contains_disallowed_inline_flow(expr),
            }) && block
                .tail_expr
                .as_ref()
                .map(|expr| !contains_disallowed_inline_flow(expr))
                .unwrap_or(true)
        }
    }
}

pub(super) fn contains_disallowed_inline_flow(expr: &Expr) -> bool {
    match &expr.kind {
        ExprKind::Break(_) | ExprKind::Continue | ExprKind::Return { .. } | ExprKind::Defer(_) => {
            true
        }
        ExprKind::Unary { expr, .. }
        | ExprKind::Comptime { expr }
        | ExprKind::Inline { expr }
        | ExprKind::OptionalUnwrap { expr }
        | ExprKind::ErrorUnwrap { expr }
        | ExprKind::DerefAccess { base: expr } => contains_disallowed_inline_flow(expr),
        ExprKind::Binary { left, right, .. }
        | ExprKind::Assign {
            target: left,
            value: right,
            ..
        }
        | ExprKind::Index {
            base: left,
            index: right,
        } => contains_disallowed_inline_flow(left) || contains_disallowed_inline_flow(right),
        ExprKind::Call(call) => {
            contains_disallowed_inline_flow(&call.callee)
                || call
                    .args
                    .iter()
                    .any(|arg| contains_disallowed_inline_flow(&arg.value))
        }
        ExprKind::FieldAccess { base, .. } => contains_disallowed_inline_flow(base),
        ExprKind::Slice(slice) => {
            contains_disallowed_inline_flow(&slice.base)
                || slice
                    .start
                    .as_ref()
                    .map(|expr| contains_disallowed_inline_flow(expr))
                    .unwrap_or(false)
                || slice
                    .end
                    .as_ref()
                    .map(|expr| contains_disallowed_inline_flow(expr))
                    .unwrap_or(false)
        }
        ExprKind::Block(block) => {
            block.statements.iter().any(|stmt| match stmt {
                Stmt::Binding(binding) => contains_disallowed_inline_flow(&binding.value),
                Stmt::Expr(expr) => contains_disallowed_inline_flow(expr),
            }) || block
                .tail_expr
                .as_ref()
                .map(|expr| contains_disallowed_inline_flow(expr))
                .unwrap_or(false)
        }
        ExprKind::If(if_expr) => {
            contains_disallowed_inline_flow(&if_expr.condition)
                || contains_disallowed_inline_flow(&if_expr.then_branch)
                || if_expr
                    .else_branch
                    .as_ref()
                    .map(|expr| contains_disallowed_inline_flow(expr))
                    .unwrap_or(false)
        }
        ExprKind::Match(match_expr) => {
            contains_disallowed_inline_flow(&match_expr.scrutinee)
                || match_expr.arms.iter().any(|arm| {
                    arm.guard
                        .as_ref()
                        .map(contains_disallowed_inline_flow)
                        .unwrap_or(false)
                        || contains_disallowed_inline_flow(&arm.value)
                })
        }
        ExprKind::For(for_expr) => match for_expr {
            crate::compiler::ast::ForExpr::Range {
                start, end, body, ..
            } => {
                contains_disallowed_inline_flow(start)
                    || contains_disallowed_inline_flow(end)
                    || contains_disallowed_inline_flow(body)
            }
            crate::compiler::ast::ForExpr::Iterate { iterable, body, .. } => {
                contains_disallowed_inline_flow(iterable) || contains_disallowed_inline_flow(body)
            }
            crate::compiler::ast::ForExpr::WhileLike { condition, body } => {
                contains_disallowed_inline_flow(condition) || contains_disallowed_inline_flow(body)
            }
            crate::compiler::ast::ForExpr::Infinite { body } => {
                contains_disallowed_inline_flow(body)
            }
        },
        ExprKind::OrElse(or_else) => {
            contains_disallowed_inline_flow(&or_else.value)
                || contains_disallowed_inline_flow(&or_else.fallback)
        }
        ExprKind::StructLiteral(struct_lit) => struct_lit
            .fields
            .iter()
            .any(|field| contains_disallowed_inline_flow(&field.value)),
        ExprKind::ArrayLiteral(elements) | ExprKind::TupleLiteral(elements) => {
            elements.iter().any(contains_disallowed_inline_flow)
        }
        ExprKind::EnumVariantConstruct(variant) => {
            variant.payload.iter().any(contains_disallowed_inline_flow)
        }
        ExprKind::Fn(fn_expr) => !inline_function_body_supported(&fn_expr.body),
        ExprKind::Use { .. }
        | ExprKind::TypeLiteral(_)
        | ExprKind::Literal(_)
        | ExprKind::Ident(_)
        | ExprKind::BuiltinIdent(_) => false,
    }
}
