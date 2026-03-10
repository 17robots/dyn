#[allow(clippy::too_many_arguments)]
pub(super) fn infer_expr_type(
    expr: &Expr,
    env: &BTreeMap<String, TypeId>,
    mutability: &BTreeMap<String, bool>,
    signatures: &BTreeMap<String, FnSignature>,
    types: &mut TypeStore,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
    expected_return: Option<TypeId>,
) -> TypeId {
    match &expr.kind {
        ExprKind::Literal(lit) => match lit {
            Literal::Integer(_) => types.intern(Type::Int {
                signed: true,
                bits: 32,
            }),
            Literal::Float(_) => types.intern(Type::Float { bits: 64 }),
            Literal::String(_) => bytes_type(types),
            Literal::Char(_) => types.intern(Type::Int {
                signed: false,
                bits: 8,
            }),
            Literal::Bool(_) => types.intern(Type::Bool),
            Literal::Null => types.intern(Type::Null),
        },
        ExprKind::Ident(ident) => {
            if let Some(ty) = env.get(&ident.text).copied() {
                ty
            } else if resolve_builtin_type_name(&ident.text, types).is_some() {
                types.intern(Type::TypeType)
            } else {
                types.intern(Type::Unknown)
            }
        }
        ExprKind::Unary { op, expr } => {
            let inner = infer_expr_type(
                expr,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            match op {
                UnaryOp::Not => types.intern(Type::Bool),
                UnaryOp::Neg => inner,
                UnaryOp::BitNot => inner,
                UnaryOp::Ref => {
                    let mutable_ref = matches!(expr.kind, ExprKind::Ident(ref ident) if mutability.get(&ident.text).copied().unwrap_or(false));
                    types.intern(Type::Pointer {
                        inner,
                        mutable: mutable_ref,
                    })
                }
            }
        }
        ExprKind::Binary { op, left, right } => {
            let left_ty = infer_expr_type(
                left,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            let right_ty = infer_expr_type(
                right,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );

            match op {
                BinaryOp::Add
                | BinaryOp::Sub
                | BinaryOp::Mul
                | BinaryOp::Div
                | BinaryOp::Mod
                | BinaryOp::BitAnd
                | BinaryOp::BitOr
                | BinaryOp::BitXor
                | BinaryOp::Shl
                | BinaryOp::Shr => {
                    if !is_numeric(left_ty, types) || !is_numeric(right_ty, types) {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "invalid operands for numeric operator",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(expr.span),
                                "both operands must be numeric",
                            ),
                        );
                    }
                    numeric_result_type(left_ty, right_ty, types)
                }
                BinaryOp::Eq
                | BinaryOp::Ne
                | BinaryOp::Lt
                | BinaryOp::Le
                | BinaryOp::Gt
                | BinaryOp::Ge
                | BinaryOp::LogicalAnd
                | BinaryOp::LogicalOr => types.intern(Type::Bool),
                BinaryOp::Range | BinaryOp::RangeInclusive => types.intern(Type::Unknown),
            }
        }
        ExprKind::Assign { op, target, value } => {
            let value_ty = infer_expr_type(
                value,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            let target_ty = infer_expr_type(
                target,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );

            if let ExprKind::Ident(ident) = &target.kind {
                if !mutability.get(&ident.text).copied().unwrap_or(false) {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4006,
                            format!("cannot assign to immutable binding '{}'", ident.text),
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "mark binding as mut to reassign",
                        ),
                    );
                }
            }
            if let ExprKind::DerefAccess { base } = &target.kind {
                let base_ty = infer_expr_type(
                    base,
                    env,
                    mutability,
                    signatures,
                    types,
                    diagnostics,
                    file_path,
                    expected_return,
                );
                if !matches!(types.get(base_ty), Type::Pointer { mutable: true, .. }) {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4006,
                            "cannot assign through immutable pointer",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "requires *mut pointer for write access",
                        ),
                    );
                }
            }
            if let ExprKind::Index { base, .. } = &target.kind {
                let base_ty = infer_expr_type(
                    base,
                    env,
                    mutability,
                    signatures,
                    types,
                    diagnostics,
                    file_path,
                    expected_return,
                );
                let writable = match types.get(base_ty) {
                    Type::Slice { mutable, .. } | Type::Pointer { mutable, .. } => *mutable,
                    _ => false,
                };
                if !writable {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4006,
                            "cannot assign through immutable indexed view",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "requires []mut/*mut view for indexed write",
                        ),
                    );
                }
            }
            if *op != AssignOp::Assign
                && !matches!(types.get(target_ty), Type::Unknown)
                && !matches!(types.get(value_ty), Type::Unknown)
                && (!is_numeric(target_ty, types) || !is_numeric(value_ty, types))
            {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "compound assignment requires numeric target and value",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "use numeric operands for compound assignment",
                    ),
                );
            }
            target_ty
        }
        ExprKind::Call(call) => infer_call_type(
            call,
            env,
            mutability,
            signatures,
            types,
            diagnostics,
            file_path,
            expr,
            expected_return,
        ),
        ExprKind::If(if_expr) => {
            let cond_ty = infer_expr_type(
                &if_expr.condition,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            if !matches!(
                types.get(cond_ty),
                Type::Bool | Type::Unknown | Type::Optional(_)
            ) {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "if condition must evaluate to bool or optional value for unwrap form",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(if_expr.condition.span),
                        "use a boolean expression",
                    ),
                );
            }
            let mut then_env = env.clone();
            let mut then_mutability = mutability.clone();
            if let Some(capture) = &if_expr.capture {
                if !matches!(types.get(cond_ty), Type::Optional(_) | Type::Unknown) {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "if capture requires optional condition",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(if_expr.condition.span),
                            "remove capture or use optional condition",
                        ),
                    );
                }
                if let Some(binding) = &capture.binding {
                    let binding_ty = match types.get(cond_ty) {
                        Type::Optional(inner) => *inner,
                        _ => types.intern(Type::Unknown),
                    };
                    then_env.insert(binding.text.clone(), binding_ty);
                    then_mutability.insert(binding.text.clone(), false);
                }
            }
            let then_ty = infer_expr_type(
                &if_expr.then_branch,
                &then_env,
                &then_mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            let else_ty = if let Some(else_branch) = &if_expr.else_branch {
                infer_expr_type(
                    else_branch,
                    env,
                    mutability,
                    signatures,
                    types,
                    diagnostics,
                    file_path,
                    expected_return,
                )
            } else {
                types.intern(Type::Unknown)
            };

            unify_branch_types(then_ty, else_ty, types, diagnostics, file_path, expr)
        }
        ExprKind::Match(match_expr) => {
            let scrutinee_ty = infer_expr_type(
                &match_expr.scrutinee,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            let mut result = types.intern(Type::Unknown);
            let mut first = true;
            for MatchArm {
                pattern,
                guard,
                value,
                ..
            } in &match_expr.arms
            {
                let mut arm_env = env.clone();
                let mut arm_mutability = mutability.clone();
                bind_pattern_names(
                    &pattern.kind,
                    scrutinee_ty,
                    types,
                    &mut arm_env,
                    &mut arm_mutability,
                );

                if let Some(reason) =
                    pattern_compatibility_issue(&pattern.kind, scrutinee_ty, types).or_else(|| {
                        enum_literal_pattern_issue(&pattern.kind, &match_expr.scrutinee.kind)
                    })
                {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            format!(
                                "match arm pattern is incompatible with scrutinee type: {reason}"
                            ),
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(pattern.span),
                            "adjust arm pattern or scrutinee expression type",
                        ),
                    );
                }

                if let Some(guard) = guard {
                    let guard_ty = infer_expr_type(
                        guard,
                        &arm_env,
                        &arm_mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                    if !matches!(types.get(guard_ty), Type::Bool | Type::Unknown) {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "match guard must evaluate to bool",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(guard.span),
                                "use a boolean guard expression",
                            ),
                        );
                    }
                }
                let arm_ty = infer_expr_type(
                    value,
                    &arm_env,
                    &arm_mutability,
                    signatures,
                    types,
                    diagnostics,
                    file_path,
                    expected_return,
                );
                if first {
                    result = arm_ty;
                    first = false;
                } else {
                    result =
                        unify_branch_types(result, arm_ty, types, diagnostics, file_path, expr);
                }
            }
            result
        }
        ExprKind::Block(block) => {
            let mut local_env = env.clone();
            let mut local_mutability = mutability.clone();
            let mut result = types.intern(Type::Unknown);

            for stmt in &block.statements {
                match stmt {
                    crate::compiler::ast::Stmt::Binding(binding) => {
                        let mut value_ty = infer_expr_type(
                            &binding.value,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            diagnostics,
                            file_path,
                            expected_return,
                        );
                        let final_ty = if let Some(annotation) = &binding.annotation {
                            validate_any_usage(
                                annotation,
                                AnyUsageContext::Other,
                                diagnostics,
                                file_path,
                            );
                            let expected = resolve_type_expr(annotation, types)
                                .unwrap_or_else(|| types.intern(Type::Unknown));
                            value_ty = maybe_coerce_literal_to_expected(
                                &binding.value,
                                value_ty,
                                expected,
                                types,
                            );
                            if !types_compatible(expected, value_ty, types) {
                                diagnostics.push(
                                    Diagnostic::error(
                                        DiagnosticPhase::TypeChecker,
                                        DiagnosticCode::E4005,
                                        format!(
                                            "type mismatch for '{}' in block binding",
                                            binding.name.text
                                        ),
                                    )
                                    .with_primary_file_label(
                                        file_path.to_path_buf(),
                                        Some(binding.span),
                                        "annotation and initializer disagree",
                                    ),
                                );
                            }
                            expected
                        } else {
                            value_ty
                        };
                        local_env.insert(binding.name.text.clone(), final_ty);
                        local_mutability.insert(binding.name.text.clone(), binding.mutable);
                        result = final_ty;
                    }
                    crate::compiler::ast::Stmt::Expr(stmt_expr) => {
                        result = infer_expr_type(
                            stmt_expr,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            diagnostics,
                            file_path,
                            expected_return,
                        );
                    }
                }
            }

            if let Some(tail_expr) = &block.tail_expr {
                result = infer_expr_type(
                    tail_expr,
                    &local_env,
                    &local_mutability,
                    signatures,
                    types,
                    diagnostics,
                    file_path,
                    expected_return,
                );
            }

            result
        }
        ExprKind::For(for_expr) => {
            match for_expr {
                crate::compiler::ast::ForExpr::Range {
                    start,
                    end,
                    binding,
                    body,
                    ..
                } => {
                    let start_ty = infer_expr_type(
                        start,
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                    let end_ty = infer_expr_type(
                        end,
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                    let mut local_env = env.clone();
                    let mut local_mutability = mutability.clone();
                    if let Some(binding) = binding {
                        let binding_ty = if is_numeric(start_ty, types) && is_numeric(end_ty, types)
                        {
                            numeric_result_type(start_ty, end_ty, types)
                        } else {
                            types.intern(Type::Int {
                                signed: true,
                                bits: 32,
                            })
                        };
                        local_env.insert(binding.text.clone(), binding_ty);
                        local_mutability.insert(binding.text.clone(), false);
                    }
                    let _ = infer_expr_type(
                        body,
                        &local_env,
                        &local_mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                }
                crate::compiler::ast::ForExpr::Iterate {
                    iterable,
                    binding,
                    body,
                    ..
                } => {
                    let iterable_ty = infer_expr_type(
                        iterable,
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                    let mut local_env = env.clone();
                    let mut local_mutability = mutability.clone();
                    if let Some(binding) = binding {
                        let binding_ty = match types.get(iterable_ty) {
                            Type::Array(element)
                            | Type::Slice { element, .. }
                            | Type::Pointer { inner: element, .. } => *element,
                            _ => types.intern(Type::Unknown),
                        };
                        local_env.insert(binding.text.clone(), binding_ty);
                        local_mutability.insert(binding.text.clone(), false);
                    }
                    let _ = infer_expr_type(
                        body,
                        &local_env,
                        &local_mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                }
                crate::compiler::ast::ForExpr::WhileLike { condition, body } => {
                    let _ = infer_expr_type(
                        condition,
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                    let _ = infer_expr_type(
                        body,
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                }
                crate::compiler::ast::ForExpr::Infinite { body } => {
                    let _ = infer_expr_type(
                        body,
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                }
            }
            types.intern(Type::Unknown)
        }
        ExprKind::Return { value } => {
            let mut value_ty = value
                .as_ref()
                .map(|expr| {
                    infer_expr_type(
                        expr,
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    )
                })
                .unwrap_or_else(|| types.intern(Type::Unknown));

            if let Some(expected) = expected_return {
                if let Some(value_expr) = value {
                    value_ty =
                        maybe_coerce_literal_to_expected(value_expr, value_ty, expected, types);
                }
                if !types_compatible(expected, value_ty, types) {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "return type does not match function annotation",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "change returned value or function return type",
                        ),
                    );
                }
            }
            value_ty
        }
        ExprKind::Fn(fn_expr) => {
            let mut local_env = env.clone();
            let mut local_mutability = mutability.clone();
            for param in &fn_expr.params {
                let param_ty = param
                    .ty
                    .as_ref()
                    .and_then(|ty| resolve_type_expr(ty, types))
                    .unwrap_or_else(|| types.intern(Type::Unknown));
                local_env.insert(param.name.text.clone(), param_ty);
                local_mutability.insert(param.name.text.clone(), false);
            }

            let expected = fn_expr
                .return_type
                .as_ref()
                .and_then(|ty| resolve_type_expr(ty, types));

            match &fn_expr.body {
                crate::compiler::ast::FnBody::Block(block) => {
                    if strict_explicit_returns_enabled()
                        && block.tail_expr.as_ref().is_some_and(|tail| {
                            !(matches!(tail.kind, ExprKind::Return { .. })
                                || fn_expr.return_type.is_none()
                                    && is_or_else_with_return_fallback(tail))
                        })
                    {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "function must use explicit return statements in strict return mode",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(expr.span),
                                "add `return ...` statements or disable strict mode with DYN_STRICT_RETURNS=0",
                            ),
                        );
                    }
                    let _ = infer_expr_type(
                        &Expr {
                            kind: ExprKind::Block(block.clone()),
                            span: expr.span,
                        },
                        &local_env,
                        &local_mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected,
                    );
                }
                crate::compiler::ast::FnBody::ArrowExpr(arrow_expr) => {
                    let mut ret_ty = infer_expr_type(
                        arrow_expr,
                        &local_env,
                        &local_mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected,
                    );
                    if let Some(expected) = expected {
                        ret_ty =
                            maybe_coerce_literal_to_expected(arrow_expr, ret_ty, expected, types);
                        if !types_compatible(expected, ret_ty, types) {
                            diagnostics.push(
                                Diagnostic::error(
                                    DiagnosticPhase::TypeChecker,
                                    DiagnosticCode::E4005,
                                    "function arrow body type does not match return type",
                                )
                                .with_primary_file_label(
                                    file_path.to_path_buf(),
                                    Some(expr.span),
                                    "change expression or return annotation",
                                ),
                            );
                        }
                    }
                }
            }

            let return_type = expected.unwrap_or_else(|| types.intern(Type::Unknown));
            let param_types = fn_expr
                .params
                .iter()
                .map(|param| {
                    param
                        .ty
                        .as_ref()
                        .and_then(|ty| resolve_type_expr(ty, types))
                        .unwrap_or_else(|| types.intern(Type::Unknown))
                })
                .collect();
            let param_names = fn_expr
                .params
                .iter()
                .map(|param| Some(param.name.text.clone()))
                .collect();
            let has_defaults = fn_expr
                .params
                .iter()
                .map(|param| param.default_value.is_some())
                .collect();
            types.intern(Type::Function {
                param_types,
                param_names,
                has_defaults,
                return_type,
            })
        }
        ExprKind::Index { base, index } => {
            let base_ty = infer_expr_type(
                base,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            let _index_ty = infer_expr_type(
                index,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            match types.get(base_ty) {
                Type::Tuple(elements) => {
                    let Some(index_value) = tuple_index_literal(index) else {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "tuple index must be a compile-time integer literal",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(index.span),
                                "use a numeric literal like 0, 1, 2, ...",
                            ),
                        );
                        return types.intern(Type::Unknown);
                    };
                    if let Some(element_ty) = elements.get(index_value) {
                        *element_ty
                    } else {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "tuple index is out of bounds",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(index.span),
                                "index exceeds tuple element count",
                            ),
                        );
                        types.intern(Type::Unknown)
                    }
                }
                Type::Array(elem)
                | Type::Slice { element: elem, .. }
                | Type::Pointer { inner: elem, .. } => *elem,
                Type::Unknown => base_ty,
                _ => {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "indexing requires array/slice/pointer value",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "cannot index this expression",
                        ),
                    );
                    types.intern(Type::Unknown)
                }
            }
        }
        ExprKind::Slice(slice) => {
            let base_ty = infer_expr_type(
                &slice.base,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            match types.get(base_ty) {
                Type::Array(elem) => types.intern(Type::Slice {
                    element: *elem,
                    mutable: false,
                }),
                Type::Slice { element, mutable } => types.intern(Type::Slice {
                    element: *element,
                    mutable: *mutable,
                }),
                Type::Pointer { inner, mutable } => types.intern(Type::Slice {
                    element: *inner,
                    mutable: *mutable,
                }),
                Type::Unknown => base_ty,
                _ => {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "slicing requires array/slice/pointer value",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "cannot slice this expression",
                        ),
                    );
                    types.intern(Type::Unknown)
                }
            }
        }
        ExprKind::DerefAccess { base } => {
            let base_ty = infer_expr_type(
                base,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            match types.get(base_ty) {
                Type::Pointer { inner, .. } => *inner,
                Type::Unknown => base_ty,
                _ => {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "deref access requires pointer value",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "cannot dereference this expression",
                        ),
                    );
                    types.intern(Type::Unknown)
                }
            }
        }
        ExprKind::OptionalUnwrap { expr: inner } => {
            let inner_ty = infer_expr_type(
                inner,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            match types.get(inner_ty) {
                Type::Optional(base) => *base,
                Type::Unknown => inner_ty,
                _ => {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "optional unwrap requires optional value",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "cannot use .? on non-optional expression",
                        ),
                    );
                    types.intern(Type::Unknown)
                }
            }
        }
        ExprKind::ErrorUnwrap { expr: inner } => {
            let inner_ty = infer_expr_type(
                inner,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            match types.get(inner_ty) {
                Type::Errorable { ok, errors } => {
                    if let Some(expected) = expected_return {
                        if let Type::Errorable {
                            errors: expected_errors,
                            ..
                        } = types.get(expected)
                        {
                            if !expected_errors.is_empty() && !errors.is_subset(expected_errors) {
                                diagnostics.push(
                                    Diagnostic::error(
                                        DiagnosticPhase::TypeChecker,
                                        DiagnosticCode::E4005,
                                        "error unwrap may propagate undeclared errors",
                                    )
                                    .with_primary_file_label(
                                        file_path.to_path_buf(),
                                        Some(expr.span),
                                        "add missing errors to function return type or handle with `or`",
                                    ),
                                );
                            }
                        }
                    }
                    *ok
                }
                Type::Unknown => inner_ty,
                _ => {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "error unwrap requires errorable value",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "cannot use .! on non-errorable expression",
                        ),
                    );
                    types.intern(Type::Unknown)
                }
            }
        }
        ExprKind::OrElse(or_else) => {
            let value_ty = infer_expr_type(
                &or_else.value,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            let mut fallback_env = env.clone();
            let mut fallback_mutability = mutability.clone();
            if let Some(binding) = &or_else.error_binding {
                let binding_ty = types.intern(Type::Unknown);
                fallback_env.insert(binding.text.clone(), binding_ty);
                fallback_mutability.insert(binding.text.clone(), false);
            }
            let fallback_ty = infer_expr_type(
                &or_else.fallback,
                &fallback_env,
                &fallback_mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );

            match types.get(value_ty) {
                Type::Optional(inner) => {
                    if types_compatible(*inner, fallback_ty, types) {
                        *inner
                    } else {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "fallback type does not match optional inner type",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(expr.span),
                                "make `or` fallback compatible with optional type",
                            ),
                        );
                        *inner
                    }
                }
                Type::Errorable { ok: inner, .. } => {
                    if types_compatible(*inner, fallback_ty, types) {
                        *inner
                    } else {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "fallback type does not match errorable ok type",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(expr.span),
                                "make `or` fallback compatible with errorable return type",
                            ),
                        );
                        *inner
                    }
                }
                Type::Null => fallback_ty,
                Type::Unknown => fallback_ty,
                _ => value_ty,
            }
        }
        ExprKind::Comptime { expr } => infer_expr_type(
            expr,
            env,
            mutability,
            signatures,
            types,
            diagnostics,
            file_path,
            expected_return,
        ),
        ExprKind::Inline { expr } => {
            let ty = infer_expr_type(
                expr,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            validate_inline_expr(expr, signatures, diagnostics, file_path);
            ty
        }
        ExprKind::Use { .. } => types.intern(Type::Unknown),
        ExprKind::TypeLiteral(_) => types.intern(Type::TypeType),
        ExprKind::ArrayLiteral(elements) => {
            let Some(first) = elements.first() else {
                let unknown = types.intern(Type::Unknown);
                return types.intern(Type::Array(unknown));
            };
            let mut element_ty = infer_expr_type(
                first,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            for element in &elements[1..] {
                let next_ty = infer_expr_type(
                    element,
                    env,
                    mutability,
                    signatures,
                    types,
                    diagnostics,
                    file_path,
                    expected_return,
                );
                element_ty = if types_compatible(element_ty, next_ty, types) {
                    element_ty
                } else if types_compatible(next_ty, element_ty, types) {
                    next_ty
                } else if is_numeric(element_ty, types) && is_numeric(next_ty, types) {
                    numeric_result_type(element_ty, next_ty, types)
                } else {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "array literal elements must have compatible types",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(element.span),
                            "make all array elements the same type",
                        ),
                    );
                    types.intern(Type::Unknown)
                };
            }
            types.intern(Type::Array(element_ty))
        }
        ExprKind::TupleLiteral(elements) => {
            let element_types = elements
                .iter()
                .map(|element| {
                    infer_expr_type(
                        element,
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    )
                })
                .collect::<Vec<_>>();
            types.intern(Type::Tuple(element_types))
        }
        _ => types.intern(Type::Unknown),
    }
}
