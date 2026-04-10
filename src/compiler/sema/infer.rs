use super::*;

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
                UnaryOp::Ref => types.intern(Type::Pointer { inner }),
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
                | BinaryOp::BitXor => {
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
                BinaryOp::Shl | BinaryOp::Shr => {
                    let left_is_int = matches!(types.get(left_ty), Type::Int { .. });
                    let right_is_int = matches!(types.get(right_ty), Type::Int { .. });
                    if !left_is_int || !right_is_int {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "shift operators require integer operands",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(expr.span),
                                "both operands must be integers, not floats",
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
                BinaryOp::Range | BinaryOp::RangeInclusive => {
                    if !is_numeric(left_ty, types) || !is_numeric(right_ty, types) {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "range bounds must be numeric",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(expr.span),
                                "both range bounds must be numeric",
                            ),
                        );
                    }
                    types.intern(Type::Unknown)
                }
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
                if ident.text != "_" && !mutability.get(&ident.text).copied().unwrap_or(false) {
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
                let n = capture.bindings.len();
                let uses_and_chain = matches!(
                    &if_expr.condition.kind,
                    ExprKind::Binary {
                        op: BinaryOp::LogicalAnd,
                        ..
                    }
                );
                if uses_and_chain || n > 1 {
                    // && chain capture: identify capturable operands in order,
                    // validate slot count, bind each named slot to its type.
                    let operands = collect_and_operands(&if_expr.condition);

                    // Determine which operands are capturable and what type each produces.
                    let capturable: Vec<TypeId> = operands
                        .iter()
                        .filter_map(|op| {
                            let op_ty = infer_expr_type(
                                op,
                                env,
                                mutability,
                                signatures,
                                types,
                                diagnostics,
                                file_path,
                                expected_return,
                            );
                            if matches!(types.get(op_ty), Type::Optional(_))
                                || is_enum_variant_check(op)
                            {
                                Some(op_ty)
                            } else {
                                None
                            }
                        })
                        .collect();

                    // Validate: slot count must match capturable operand count.
                    if n != capturable.len() {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                format!(
                                    "if condition has {} capturable sub-condition(s) but {} capture slot(s) were provided",
                                    capturable.len(),
                                    n,
                                ),
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(if_expr.condition.span),
                                format!(
                                    "provide exactly {} slot(s) in the capture list (use _ to discard)",
                                    capturable.len()
                                ),
                            ),
                        );
                    }

                    // Bind each named slot to its capturable type.
                    for (binding_opt, op_ty) in capture.bindings.iter().zip(capturable.iter()) {
                        if let Some(binding) = binding_opt {
                            let binding_ty = match types.get(*op_ty) {
                                Type::Optional(inner) => *inner,
                                // Enum variant check — payload type (Unknown until full enum
                                // type system maps variant → payload type).
                                _ => types.intern(Type::Unknown),
                            };
                            then_env.insert(binding.text.clone(), binding_ty);
                            then_mutability.insert(binding.text.clone(), false);
                        }
                    }
                } else {
                    // Single capture: allow optionals OR enum variant checks.
                    let cond_is_enum_check = is_enum_variant_check(&if_expr.condition);
                    if !matches!(types.get(cond_ty), Type::Optional(_) | Type::Unknown)
                        && !cond_is_enum_check
                    {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "if capture requires optional condition or enum variant check (expr == .Variant)",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(if_expr.condition.span),
                                "remove capture or use optional/enum-variant condition",
                            ),
                        );
                    }
                    if let Some(binding) = capture.bindings.first().and_then(|b| b.as_ref()) {
                        let binding_ty = match types.get(cond_ty) {
                            Type::Optional(inner) => *inner,
                            // Enum variant check — payload type is Unknown until full
                            // enum type resolution is implemented.
                            _ => types.intern(Type::Unknown),
                        };
                        then_env.insert(binding.text.clone(), binding_ty);
                        then_mutability.insert(binding.text.clone(), false);
                    }
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
                    crate::compiler::ast::Stmt::Destructure(d) => {
                        infer_expr_type(
                            &d.value,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            diagnostics,
                            file_path,
                            expected_return,
                        );
                        let unknown = types.intern(Type::Unknown);
                        for dn in &d.names {
                            local_env.insert(dn.name.text.clone(), unknown);
                            local_mutability.insert(dn.name.text.clone(), dn.mutable);
                        }
                        result = unknown;
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
                    let return_is_void = fn_expr.return_type.as_ref().is_some_and(|ty| {
                        matches!(&ty.kind, crate::compiler::ast::TypeExprKind::Named(n) if n.text == "void")
                    });
                    if strict_explicit_returns_enabled()
                        && !return_is_void
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
                Type::Array(elem) => types.intern(Type::Slice { element: *elem }),
                Type::Slice { element } => types.intern(Type::Slice { element: *element }),
                Type::Pointer { inner } => types.intern(Type::Slice { element: *inner }),
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
            let pre_len = diagnostics.len();
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
            // Inline functions must be expression-oriented (no explicit `return`) to be
            // inlinable at call sites. Suppress the strict-returns diagnostic for the
            // function body so that expression-style inline functions compile cleanly.
            let added: Vec<_> = diagnostics.drain(pre_len..).collect();
            diagnostics.extend(
                added
                    .into_iter()
                    .filter(|d| !is_strict_return_mode_tail_diagnostic_for_span(d, expr.span)),
            );
            validate_inline_expr(expr, signatures, diagnostics, file_path);
            ty
        }
        ExprKind::Use { .. } => types.intern(Type::Unknown),
        ExprKind::TypeLiteral(_) => types.intern(Type::TypeType),
        ExprKind::TypeConstruct { ty_expr, fields } => {
            // Walk the type expression and all field values for side-effects (diagnostics).
            let _ = infer_expr_type(
                ty_expr,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            for field in fields {
                let _ = infer_expr_type(
                    &field.value,
                    env,
                    mutability,
                    signatures,
                    types,
                    diagnostics,
                    file_path,
                    expected_return,
                );
            }
            // The concrete struct type is resolved by the backend from the ty_expr's runtime value.
            types.intern(Type::Unknown)
        }
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

fn collect_and_operands(expr: &Expr) -> Vec<&Expr> {
    match &expr.kind {
        ExprKind::Binary {
            op: BinaryOp::LogicalAnd,
            left,
            right,
        } => {
            let mut ops = collect_and_operands(left);
            ops.push(right);
            ops
        }
        _ => vec![expr],
    }
}

/// Returns true if this expression is an enum-variant tag check of the form
/// `expr == .Variant` or `expr != .Variant`. These can produce a capture binding
/// (the variant's payload) in an if condition.
fn is_enum_variant_check(op: &Expr) -> bool {
    matches!(
        &op.kind,
        ExprKind::Binary {
            op: BinaryOp::Eq | BinaryOp::Ne,
            right,
            ..
        } if matches!(&right.kind, ExprKind::EnumVariantConstruct(_))
    )
}

pub(super) fn validate_struct_type_members(
    _ty: &TypeExpr,
    _struct_name: &str,
    _diagnostics: &mut Vec<Diagnostic>,
    _file_path: &std::path::Path,
) {
    // Methods are no longer defined inside struct bodies; this validation is handled
    // per-method-binding in analyze_modules.
}

#[allow(dead_code)]
pub(super) fn matches_receiver_type(param_ty: &TypeExpr, struct_name: &str) -> bool {
    matches!(&param_ty.kind, TypeExprKind::Named(ident) if ident.text == struct_name)
        || matches!(&param_ty.kind, TypeExprKind::Pointer { inner, .. }
            if matches!(inner.kind, TypeExprKind::Named(ref ident) if ident.text == struct_name))
}

pub(super) fn collect_named_struct_fields(unit: &ModuleUnit) -> BTreeMap<String, Vec<String>> {
    let mut out = BTreeMap::new();
    for decl in &unit.declarations {
        let ExprKind::TypeLiteral(type_lit) = &decl.value.kind else {
            continue;
        };
        let TypeExprKind::Struct(struct_ty) = &type_lit.kind else {
            continue;
        };
        let names = struct_ty
            .fields
            .iter()
            .map(|field| field.name.text.clone())
            .collect::<Vec<_>>();
        out.insert(decl.name.clone(), names);
    }
    out
}

#[derive(Debug, Clone)]
pub(super) struct StructLiteralSpec {
    pub fields: BTreeMap<String, bool>,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(super) enum NominalValueKind {
    Struct,
    PlainEnum,
    PayloadEnum,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(super) enum EqualityValueKind {
    Unknown,
    Scalar,
    Pointer,
    Array,
    Slice,
    Tuple,
    Struct,
    PlainEnum,
    PayloadEnum,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
enum BorrowKind {
    Shared,
    Mutable,
}

#[derive(Debug, Clone, Default)]
pub(super) struct BorrowState {
    mutability: BTreeMap<String, bool>,
    binding_borrows: BTreeMap<String, (String, BorrowKind)>,
    active_by_origin: BTreeMap<String, Vec<(String, BorrowKind)>>,
}

impl BorrowState {
    fn with_params(params: &[crate::compiler::ast::FnParam]) -> Self {
        let mut state = Self::default();
        for param in params {
            state.mutability.insert(param.name.text.clone(), false);
        }
        state
    }

    fn bind_local(&mut self, name: &str, mutable: bool) {
        self.mutability.insert(name.to_string(), mutable);
    }

    fn release_binding_borrow(&mut self, name: &str) {
        let Some((origin, _)) = self.binding_borrows.remove(name) else {
            return;
        };
        let Some(active) = self.active_by_origin.get_mut(&origin) else {
            return;
        };
        active.retain(|(binding, _)| binding != name);
        if active.is_empty() {
            self.active_by_origin.remove(&origin);
        }
    }

    fn record_binding_borrow(&mut self, binding: &str, origin: &str, kind: BorrowKind) {
        self.release_binding_borrow(binding);
        self.binding_borrows
            .insert(binding.to_string(), (origin.to_string(), kind));
        self.active_by_origin
            .entry(origin.to_string())
            .or_default()
            .push((binding.to_string(), kind));
    }
}

pub(super) fn collect_struct_literal_specs(
    unit: &ModuleUnit,
) -> BTreeMap<String, StructLiteralSpec> {
    let mut out = BTreeMap::new();
    for decl in &unit.declarations {
        let ExprKind::TypeLiteral(type_lit) = &decl.value.kind else {
            continue;
        };
        let TypeExprKind::Struct(struct_ty) = &type_lit.kind else {
            continue;
        };
        let fields = struct_ty
            .fields
            .iter()
            .map(|field| (field.name.text.clone(), field.default_value.is_some()))
            .collect::<BTreeMap<_, _>>();
        out.insert(decl.name.clone(), StructLiteralSpec { fields });
    }
    out
}

pub(super) fn collect_nominal_value_kinds(unit: &ModuleUnit) -> BTreeMap<String, NominalValueKind> {
    let mut out = BTreeMap::new();
    for decl in &unit.declarations {
        let ExprKind::TypeLiteral(type_lit) = &decl.value.kind else {
            continue;
        };
        match &type_lit.kind {
            TypeExprKind::Struct(_) => {
                out.insert(decl.name.clone(), NominalValueKind::Struct);
            }
            TypeExprKind::Enum(enum_ty) => {
                let has_payload = enum_ty
                    .variants
                    .iter()
                    .any(|variant| variant.payload.is_some());
                out.insert(
                    decl.name.clone(),
                    if has_payload {
                        NominalValueKind::PayloadEnum
                    } else {
                        NominalValueKind::PlainEnum
                    },
                );
            }
            _ => {}
        }
    }
    out
}

pub(super) fn visit_expr_children(expr: &Expr, mut visit: impl FnMut(&Expr)) {
    match &expr.kind {
        ExprKind::Literal(_)
        | ExprKind::Ident(_)
        | ExprKind::BuiltinIdent(_)
        | ExprKind::Continue { .. }
        | ExprKind::Use { .. }
        | ExprKind::TypeLiteral(_) => {}
        ExprKind::Unary { expr, .. }
        | ExprKind::Comptime { expr }
        | ExprKind::Inline { expr }
        | ExprKind::OptionalUnwrap { expr }
        | ExprKind::ErrorUnwrap { expr }
        | ExprKind::DerefAccess { base: expr } => visit(expr),
        ExprKind::Binary { left, right, .. }
        | ExprKind::Assign {
            target: left,
            value: right,
            ..
        }
        | ExprKind::Index {
            base: left,
            index: right,
        } => {
            visit(left);
            visit(right);
        }
        ExprKind::Call(call) => {
            visit(&call.callee);
            for arg in &call.args {
                visit(&arg.value);
            }
        }
        ExprKind::FieldAccess { base, .. } => visit(base),
        ExprKind::Slice(slice) => {
            visit(&slice.base);
            if let Some(start) = &slice.start {
                visit(start);
            }
            if let Some(end) = &slice.end {
                visit(end);
            }
        }
        ExprKind::Block(block) => {
            for stmt in &block.statements {
                match stmt {
                    Stmt::Binding(binding) => visit(&binding.value),
                    Stmt::Destructure(destructure) => visit(&destructure.value),
                    Stmt::Expr(stmt_expr) => visit(stmt_expr),
                }
            }
            if let Some(tail_expr) = &block.tail_expr {
                visit(tail_expr);
            }
        }
        ExprKind::If(if_expr) => {
            visit(&if_expr.condition);
            visit(&if_expr.then_branch);
            if let Some(else_branch) = &if_expr.else_branch {
                visit(else_branch);
            }
        }
        ExprKind::Match(match_expr) => {
            visit(&match_expr.scrutinee);
            for arm in &match_expr.arms {
                if let Some(guard) = &arm.guard {
                    visit(guard);
                }
                visit(&arm.value);
            }
        }
        ExprKind::For(for_expr) => match for_expr {
            crate::compiler::ast::ForExpr::Range {
                start, end, body, ..
            } => {
                visit(start);
                visit(end);
                visit(body);
            }
            crate::compiler::ast::ForExpr::Iterate { iterable, body, .. } => {
                visit(iterable);
                visit(body);
            }
            crate::compiler::ast::ForExpr::WhileLike { condition, body } => {
                visit(condition);
                visit(body);
            }
            crate::compiler::ast::ForExpr::Infinite { body } => visit(body),
        },
        ExprKind::Break(break_expr) => {
            if let Some(value) = &break_expr.value {
                visit(value);
            }
        }
        ExprKind::Return { value } => {
            if let Some(value) = value {
                visit(value);
            }
        }
        ExprKind::Defer(defer_expr) => visit(&defer_expr.body),
        ExprKind::OrElse(or_else) => {
            visit(&or_else.value);
            visit(&or_else.fallback);
        }
        ExprKind::StructLiteral(struct_lit) => {
            for field in &struct_lit.fields {
                visit(&field.value);
            }
        }
        ExprKind::TypeConstruct { ty_expr, fields } => {
            visit(ty_expr);
            for field in fields {
                visit(&field.value);
            }
        }
        ExprKind::ArrayLiteral(elements) | ExprKind::TupleLiteral(elements) => {
            for element in elements {
                visit(element);
            }
        }
        ExprKind::EnumVariantConstruct(variant) => {
            for payload in &variant.payload {
                visit(payload);
            }
        }
        ExprKind::Fn(fn_expr) => match &fn_expr.body {
            FnBody::Block(block) => visit(&Expr {
                kind: ExprKind::Block(block.clone()),
                span: expr.span,
            }),
            FnBody::ArrowExpr(body) => visit(body),
        },
    }
}

pub(super) fn validate_typed_struct_literals(
    expr: &Expr,
    struct_specs: &BTreeMap<String, StructLiteralSpec>,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
) {
    if let ExprKind::StructLiteral(struct_lit) = &expr.kind {
        if let Some(root_type) = &struct_lit.root_type {
            if let Some(spec) = struct_specs.get(&root_type.text) {
                let mut provided = BTreeSet::new();
                for field in &struct_lit.fields {
                    if !spec.fields.contains_key(&field.name.text) {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                format!(
                                    "unknown field '{}' in typed struct literal '{}'",
                                    field.name.text, root_type.text
                                ),
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(field.name.span),
                                "field is not declared on this struct type",
                            ),
                        );
                        continue;
                    }
                    if !provided.insert(field.name.text.clone()) {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                format!(
                                    "duplicate field '{}' in typed struct literal '{}'",
                                    field.name.text, root_type.text
                                ),
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(field.name.span),
                                "each struct field may be provided at most once",
                            ),
                        );
                    }
                }
                for (field_name, has_default) in &spec.fields {
                    if !has_default && !provided.contains(field_name) {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                format!(
                                    "missing required field '{}' in typed struct literal '{}'",
                                    field_name, root_type.text
                                ),
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(expr.span),
                                "provide all non-default struct fields",
                            ),
                        );
                    }
                }
            }
        }
    }

    visit_expr_children(expr, |child| {
        validate_typed_struct_literals(child, struct_specs, diagnostics, file_path)
    });
}

pub(super) fn validate_supported_builtin_type_expr(
    ty: &TypeExpr,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
) {
    match &ty.kind {
        TypeExprKind::Named(name)
            if name
                .text
                .strip_prefix('i')
                .or_else(|| name.text.strip_prefix('u'))
                .is_some_and(|rest| {
                    !rest.is_empty() && rest.chars().all(|c| c.is_ascii_digit())
                })
                && name.text != "u1"
                && parse_int_type_bits(&name.text).is_none() =>
        {
            diagnostics.push(
                Diagnostic::error(
                    DiagnosticPhase::TypeChecker,
                    DiagnosticCode::E4005,
                    format!("unsupported integer type '{}'", name.text),
                )
                .with_primary_file_label(
                    file_path.to_path_buf(),
                    Some(name.span),
                    "use integer widths from 1 to 128 bits",
                ),
            );
        }
        TypeExprKind::Named(name)
            if name.text.starts_with('f') && parse_float_type_bits(&name.text).is_none() =>
        {
            diagnostics.push(
                Diagnostic::error(
                    DiagnosticPhase::TypeChecker,
                    DiagnosticCode::E4005,
                    format!("unsupported float type '{}'", name.text),
                )
                .with_primary_file_label(
                    file_path.to_path_buf(),
                    Some(name.span),
                    "use f32 or f64",
                ),
            );
        }
        TypeExprKind::Applied { args, .. } => {
            for arg in args {
                validate_supported_builtin_type_expr(arg, diagnostics, file_path);
            }
        }
        TypeExprKind::Pointer { inner, .. }
        | TypeExprKind::Optional { inner }
        | TypeExprKind::Errorable { ok: inner, .. } => {
            validate_supported_builtin_type_expr(inner, diagnostics, file_path);
        }
        TypeExprKind::Array { element, .. } | TypeExprKind::Slice { element } => {
            validate_supported_builtin_type_expr(element, diagnostics, file_path);
        }
        TypeExprKind::Function(fn_ty) => {
            for param in &fn_ty.params {
                validate_supported_builtin_type_expr(&param.ty, diagnostics, file_path);
            }
            validate_supported_builtin_type_expr(&fn_ty.return_type, diagnostics, file_path);
        }
        TypeExprKind::Struct(struct_ty) => {
            for field in &struct_ty.fields {
                validate_supported_builtin_type_expr(&field.ty, diagnostics, file_path);
            }
        }
        TypeExprKind::Enum(enum_ty) => {
            if let Some(repr) = &enum_ty.repr {
                validate_supported_builtin_type_expr(repr, diagnostics, file_path);
            }
            for variant in &enum_ty.variants {
                if let Some(payload) = &variant.payload {
                    validate_supported_builtin_type_expr(payload, diagnostics, file_path);
                }
            }
        }
        TypeExprKind::Named(_) => {}
    }
}

pub(super) fn validate_supported_builtin_types_in_expr(
    expr: &Expr,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
) {
    match &expr.kind {
        ExprKind::Block(block) => {
            for stmt in &block.statements {
                match stmt {
                    Stmt::Binding(binding) => {
                        if let Some(annotation) = &binding.annotation {
                            validate_supported_builtin_type_expr(
                                annotation,
                                diagnostics,
                                file_path,
                            );
                        }
                        validate_supported_builtin_types_in_expr(
                            &binding.value,
                            diagnostics,
                            file_path,
                        );
                    }
                    Stmt::Destructure(destructure) => validate_supported_builtin_types_in_expr(
                        &destructure.value,
                        diagnostics,
                        file_path,
                    ),
                    Stmt::Expr(stmt_expr) => {
                        validate_supported_builtin_types_in_expr(stmt_expr, diagnostics, file_path);
                    }
                }
            }
            if let Some(tail_expr) = &block.tail_expr {
                validate_supported_builtin_types_in_expr(tail_expr, diagnostics, file_path);
            }
        }
        ExprKind::Fn(fn_expr) => {
            for param in &fn_expr.params {
                if let Some(ty) = &param.ty {
                    validate_supported_builtin_type_expr(ty, diagnostics, file_path);
                }
            }
            if let Some(ret) = &fn_expr.return_type {
                validate_supported_builtin_type_expr(ret, diagnostics, file_path);
            }
            match &fn_expr.body {
                FnBody::Block(block) => validate_supported_builtin_types_in_expr(
                    &Expr {
                        kind: ExprKind::Block(block.clone()),
                        span: expr.span,
                    },
                    diagnostics,
                    file_path,
                ),
                FnBody::ArrowExpr(body) => {
                    validate_supported_builtin_types_in_expr(body, diagnostics, file_path)
                }
            }
        }
        ExprKind::TypeLiteral(ty) => {
            validate_supported_builtin_type_expr(ty, diagnostics, file_path);
        }
        _ => visit_expr_children(expr, |child| {
            validate_supported_builtin_types_in_expr(child, diagnostics, file_path)
        }),
    }
}

fn classify_type_for_equality(
    ty: TypeId,
    types: &TypeStore,
    nominal_kinds: &BTreeMap<String, NominalValueKind>,
) -> EqualityValueKind {
    match types.get(ty) {
        Type::Unknown
        | Type::TypeType
        | Type::Any
        | Type::Opaque
        | Type::Void
        | Type::Null
        | Type::Optional(_)
        | Type::Errorable { .. }
        | Type::Function { .. } => EqualityValueKind::Unknown,
        Type::Bool | Type::Int { .. } | Type::Float { .. } => EqualityValueKind::Scalar,
        Type::Pointer { .. } => EqualityValueKind::Pointer,
        Type::Array(_) => EqualityValueKind::Array,
        Type::Slice { .. } => EqualityValueKind::Slice,
        Type::Tuple(_) => EqualityValueKind::Tuple,
        Type::TypeParam(name) | Type::Applied { callee: name, .. } => {
            match nominal_kinds.get(name) {
                Some(NominalValueKind::Struct) => EqualityValueKind::Struct,
                Some(NominalValueKind::PlainEnum) => EqualityValueKind::PlainEnum,
                Some(NominalValueKind::PayloadEnum) => EqualityValueKind::PayloadEnum,
                None => EqualityValueKind::Unknown,
            }
        }
    }
}

fn infer_expr_type_silently(
    expr: &Expr,
    env: &BTreeMap<String, TypeId>,
    mutability: &BTreeMap<String, bool>,
    signatures: &BTreeMap<String, FnSignature>,
    types: &mut TypeStore,
    file_path: &std::path::Path,
    expected_return: Option<TypeId>,
) -> TypeId {
    let mut scratch = Vec::new();
    infer_expr_type(
        expr,
        env,
        mutability,
        signatures,
        types,
        &mut scratch,
        file_path,
        expected_return,
    )
}

fn classify_expr_for_equality(
    expr: &Expr,
    env_shapes: &BTreeMap<String, EqualityValueKind>,
    env_types: &BTreeMap<String, TypeId>,
    mutability: &BTreeMap<String, bool>,
    signatures: &BTreeMap<String, FnSignature>,
    types: &mut TypeStore,
    nominal_kinds: &BTreeMap<String, NominalValueKind>,
    file_path: &std::path::Path,
    expected_return: Option<TypeId>,
) -> EqualityValueKind {
    match &expr.kind {
        ExprKind::Literal(Literal::String(_)) => EqualityValueKind::Slice,
        ExprKind::Literal(_) => EqualityValueKind::Scalar,
        ExprKind::Unary {
            op: UnaryOp::Ref, ..
        } => EqualityValueKind::Pointer,
        ExprKind::StructLiteral(_) => EqualityValueKind::Struct,
        ExprKind::ArrayLiteral(_) => EqualityValueKind::Array,
        ExprKind::TupleLiteral(_) => EqualityValueKind::Tuple,
        ExprKind::EnumVariantConstruct(variant) => {
            if let Some(root) = &variant.root {
                match nominal_kinds.get(&root.text) {
                    Some(NominalValueKind::PlainEnum) => EqualityValueKind::PlainEnum,
                    Some(NominalValueKind::PayloadEnum) => EqualityValueKind::PayloadEnum,
                    Some(NominalValueKind::Struct) | None => {
                        if variant.payload.is_empty() {
                            EqualityValueKind::PlainEnum
                        } else {
                            EqualityValueKind::PayloadEnum
                        }
                    }
                }
            } else if variant.payload.is_empty() {
                EqualityValueKind::PlainEnum
            } else {
                EqualityValueKind::PayloadEnum
            }
        }
        ExprKind::Ident(ident) => env_shapes.get(&ident.text).copied().unwrap_or_else(|| {
            env_types
                .get(&ident.text)
                .map(|ty| classify_type_for_equality(*ty, types, nominal_kinds))
                .unwrap_or(EqualityValueKind::Unknown)
        }),
        ExprKind::Call(call) => {
            if let Some(name) = extract_callee_name(&call.callee) {
                if let Some(signature) = signatures.get(&name) {
                    return classify_type_for_equality(signature.return_type, types, nominal_kinds);
                }
            }
            let inferred = infer_expr_type_silently(
                expr,
                env_types,
                mutability,
                signatures,
                types,
                file_path,
                expected_return,
            );
            classify_type_for_equality(inferred, types, nominal_kinds)
        }
        _ => {
            let inferred = infer_expr_type_silently(
                expr,
                env_types,
                mutability,
                signatures,
                types,
                file_path,
                expected_return,
            );
            classify_type_for_equality(inferred, types, nominal_kinds)
        }
    }
}

pub(super) fn validate_unsupported_equality(
    expr: &Expr,
    env_shapes: &BTreeMap<String, EqualityValueKind>,
    env: &BTreeMap<String, TypeId>,
    mutability: &BTreeMap<String, bool>,
    signatures: &BTreeMap<String, FnSignature>,
    types: &mut TypeStore,
    nominal_kinds: &BTreeMap<String, NominalValueKind>,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
    expected_return: Option<TypeId>,
) {
    match &expr.kind {
        ExprKind::Binary {
            op: BinaryOp::Eq | BinaryOp::Ne,
            left,
            right,
        } => {
            validate_unsupported_equality(
                left,
                env_shapes,
                env,
                mutability,
                signatures,
                types,
                nominal_kinds,
                diagnostics,
                file_path,
                expected_return,
            );
            validate_unsupported_equality(
                right,
                env_shapes,
                env,
                mutability,
                signatures,
                types,
                nominal_kinds,
                diagnostics,
                file_path,
                expected_return,
            );

            let left_kind = classify_expr_for_equality(
                left,
                env_shapes,
                env,
                mutability,
                signatures,
                types,
                nominal_kinds,
                file_path,
                expected_return,
            );
            let right_kind = classify_expr_for_equality(
                right,
                env_shapes,
                env,
                mutability,
                signatures,
                types,
                nominal_kinds,
                file_path,
                expected_return,
            );
            if let Some(kind) = unsupported_equality_kind(left_kind, right_kind) {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        format!(
                            "unsupported equality on {} values",
                            equality_kind_name(kind)
                        ),
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "use == and != only with scalars, pointers, and plain enums",
                    ),
                );
            }
        }
        ExprKind::Block(block) => {
            let mut local_env = env.clone();
            let mut local_shapes = env_shapes.clone();
            let mut local_mutability = mutability.clone();
            for stmt in &block.statements {
                match stmt {
                    Stmt::Binding(binding) => {
                        validate_unsupported_equality(
                            &binding.value,
                            &local_shapes,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            nominal_kinds,
                            diagnostics,
                            file_path,
                            expected_return,
                        );
                        let mut value_ty = infer_expr_type_silently(
                            &binding.value,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            file_path,
                            expected_return,
                        );
                        let final_ty = if let Some(annotation) = &binding.annotation {
                            let expected = resolve_type_expr(annotation, types)
                                .unwrap_or_else(|| types.intern(Type::Unknown));
                            value_ty = maybe_coerce_literal_to_expected(
                                &binding.value,
                                value_ty,
                                expected,
                                types,
                            );
                            expected
                        } else {
                            value_ty
                        };
                        let final_shape = if binding.annotation.is_some() {
                            classify_type_for_equality(final_ty, types, nominal_kinds)
                        } else {
                            classify_expr_for_equality(
                                &binding.value,
                                &local_shapes,
                                &local_env,
                                &local_mutability,
                                signatures,
                                types,
                                nominal_kinds,
                                file_path,
                                expected_return,
                            )
                        };
                        local_env.insert(binding.name.text.clone(), final_ty);
                        local_shapes.insert(binding.name.text.clone(), final_shape);
                        local_mutability.insert(binding.name.text.clone(), binding.mutable);
                    }
                    Stmt::Destructure(destructure) => {
                        validate_unsupported_equality(
                            &destructure.value,
                            &local_shapes,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            nominal_kinds,
                            diagnostics,
                            file_path,
                            expected_return,
                        );
                        let unknown = types.intern(Type::Unknown);
                        for name in &destructure.names {
                            local_env.insert(name.name.text.clone(), unknown);
                            local_shapes.insert(name.name.text.clone(), EqualityValueKind::Unknown);
                            local_mutability.insert(name.name.text.clone(), name.mutable);
                        }
                    }
                    Stmt::Expr(stmt_expr) => validate_unsupported_equality(
                        stmt_expr,
                        &local_shapes,
                        &local_env,
                        &local_mutability,
                        signatures,
                        types,
                        nominal_kinds,
                        diagnostics,
                        file_path,
                        expected_return,
                    ),
                }
            }
            if let Some(tail_expr) = &block.tail_expr {
                validate_unsupported_equality(
                    tail_expr,
                    &local_shapes,
                    &local_env,
                    &local_mutability,
                    signatures,
                    types,
                    nominal_kinds,
                    diagnostics,
                    file_path,
                    expected_return,
                );
            }
        }
        ExprKind::Fn(fn_expr) => {
            let mut local_env = env.clone();
            let mut local_shapes = env_shapes.clone();
            let mut local_mutability = mutability.clone();
            for param in &fn_expr.params {
                let param_ty = param
                    .ty
                    .as_ref()
                    .and_then(|ty| resolve_type_expr(ty, types))
                    .unwrap_or_else(|| types.intern(Type::Unknown));
                local_env.insert(param.name.text.clone(), param_ty);
                local_shapes.insert(
                    param.name.text.clone(),
                    classify_type_for_equality(param_ty, types, nominal_kinds),
                );
                local_mutability.insert(param.name.text.clone(), false);
            }
            let nested_expected = fn_expr
                .return_type
                .as_ref()
                .and_then(|ty| resolve_type_expr(ty, types));
            match &fn_expr.body {
                FnBody::Block(block) => validate_unsupported_equality(
                    &Expr {
                        kind: ExprKind::Block(block.clone()),
                        span: expr.span,
                    },
                    &local_shapes,
                    &local_env,
                    &local_mutability,
                    signatures,
                    types,
                    nominal_kinds,
                    diagnostics,
                    file_path,
                    nested_expected,
                ),
                FnBody::ArrowExpr(body) => validate_unsupported_equality(
                    body,
                    &local_shapes,
                    &local_env,
                    &local_mutability,
                    signatures,
                    types,
                    nominal_kinds,
                    diagnostics,
                    file_path,
                    nested_expected,
                ),
            }
        }
        ExprKind::If(if_expr) => {
            validate_unsupported_equality(
                &if_expr.condition,
                env_shapes,
                env,
                mutability,
                signatures,
                types,
                nominal_kinds,
                diagnostics,
                file_path,
                expected_return,
            );
            let mut then_env = env.clone();
            let mut then_shapes = env_shapes.clone();
            let mut then_mutability = mutability.clone();
            if let Some(capture) = &if_expr.capture {
                for binding in &capture.bindings {
                    if let Some(binding) = binding {
                        then_env.insert(binding.text.clone(), types.intern(Type::Unknown));
                        then_shapes.insert(binding.text.clone(), EqualityValueKind::Unknown);
                        then_mutability.insert(binding.text.clone(), false);
                    }
                }
            }
            validate_unsupported_equality(
                &if_expr.then_branch,
                &then_shapes,
                &then_env,
                &then_mutability,
                signatures,
                types,
                nominal_kinds,
                diagnostics,
                file_path,
                expected_return,
            );
            if let Some(else_branch) = &if_expr.else_branch {
                validate_unsupported_equality(
                    else_branch,
                    env_shapes,
                    env,
                    mutability,
                    signatures,
                    types,
                    nominal_kinds,
                    diagnostics,
                    file_path,
                    expected_return,
                );
            }
        }
        ExprKind::Match(match_expr) => {
            validate_unsupported_equality(
                &match_expr.scrutinee,
                env_shapes,
                env,
                mutability,
                signatures,
                types,
                nominal_kinds,
                diagnostics,
                file_path,
                expected_return,
            );
            let scrutinee_ty = infer_expr_type_silently(
                &match_expr.scrutinee,
                env,
                mutability,
                signatures,
                types,
                file_path,
                expected_return,
            );
            for arm in &match_expr.arms {
                let mut arm_env = env.clone();
                let mut arm_shapes = env_shapes.clone();
                let mut arm_mutability = mutability.clone();
                bind_pattern_names(
                    &arm.pattern.kind,
                    scrutinee_ty,
                    types,
                    &mut arm_env,
                    &mut arm_mutability,
                );
                match &arm.pattern.kind {
                    PatternKind::IdentBind(ident) => {
                        arm_shapes.insert(
                            ident.text.clone(),
                            classify_type_for_equality(scrutinee_ty, types, nominal_kinds),
                        );
                    }
                    PatternKind::EnumVariant { bindings, .. } => {
                        for ident in bindings {
                            arm_shapes.insert(ident.text.clone(), EqualityValueKind::Unknown);
                        }
                    }
                    PatternKind::Range { start, end, .. } => {
                        if let PatternKind::IdentBind(ident) = &start.kind {
                            arm_shapes.insert(ident.text.clone(), EqualityValueKind::Unknown);
                        }
                        if let PatternKind::IdentBind(ident) = &end.kind {
                            arm_shapes.insert(ident.text.clone(), EqualityValueKind::Unknown);
                        }
                    }
                    PatternKind::Typed { pattern, .. } => {
                        if let PatternKind::IdentBind(ident) = &pattern.kind {
                            arm_shapes.insert(
                                ident.text.clone(),
                                classify_type_for_equality(scrutinee_ty, types, nominal_kinds),
                            );
                        }
                    }
                    PatternKind::Wildcard
                    | PatternKind::Literal(_)
                    | PatternKind::TypeLiteral(_) => {}
                }
                if let Some(guard) = &arm.guard {
                    validate_unsupported_equality(
                        guard,
                        &arm_shapes,
                        &arm_env,
                        &arm_mutability,
                        signatures,
                        types,
                        nominal_kinds,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                }
                validate_unsupported_equality(
                    &arm.value,
                    &arm_shapes,
                    &arm_env,
                    &arm_mutability,
                    signatures,
                    types,
                    nominal_kinds,
                    diagnostics,
                    file_path,
                    expected_return,
                );
            }
        }
        ExprKind::For(for_expr) => match for_expr {
            ForExpr::Range {
                start,
                end,
                binding,
                body,
                ..
            } => {
                validate_unsupported_equality(
                    start,
                    env_shapes,
                    env,
                    mutability,
                    signatures,
                    types,
                    nominal_kinds,
                    diagnostics,
                    file_path,
                    expected_return,
                );
                validate_unsupported_equality(
                    end,
                    env_shapes,
                    env,
                    mutability,
                    signatures,
                    types,
                    nominal_kinds,
                    diagnostics,
                    file_path,
                    expected_return,
                );
                let mut body_env = env.clone();
                let mut body_shapes = env_shapes.clone();
                let mut body_mutability = mutability.clone();
                if let Some(binding) = binding {
                    let start_ty = infer_expr_type_silently(
                        start,
                        env,
                        mutability,
                        signatures,
                        types,
                        file_path,
                        expected_return,
                    );
                    let end_ty = infer_expr_type_silently(
                        end,
                        env,
                        mutability,
                        signatures,
                        types,
                        file_path,
                        expected_return,
                    );
                    let binding_ty = if is_numeric(start_ty, types) && is_numeric(end_ty, types) {
                        numeric_result_type(start_ty, end_ty, types)
                    } else {
                        types.intern(Type::Unknown)
                    };
                    body_env.insert(binding.text.clone(), binding_ty);
                    body_shapes.insert(
                        binding.text.clone(),
                        classify_type_for_equality(binding_ty, types, nominal_kinds),
                    );
                    body_mutability.insert(binding.text.clone(), false);
                }
                validate_unsupported_equality(
                    body,
                    &body_shapes,
                    &body_env,
                    &body_mutability,
                    signatures,
                    types,
                    nominal_kinds,
                    diagnostics,
                    file_path,
                    expected_return,
                );
            }
            ForExpr::Iterate {
                iterable,
                binding,
                body,
            } => {
                validate_unsupported_equality(
                    iterable,
                    env_shapes,
                    env,
                    mutability,
                    signatures,
                    types,
                    nominal_kinds,
                    diagnostics,
                    file_path,
                    expected_return,
                );
                let mut body_env = env.clone();
                let mut body_shapes = env_shapes.clone();
                let mut body_mutability = mutability.clone();
                if let Some(binding) = binding {
                    let iterable_ty = infer_expr_type_silently(
                        iterable,
                        env,
                        mutability,
                        signatures,
                        types,
                        file_path,
                        expected_return,
                    );
                    let binding_ty = match types.get(iterable_ty) {
                        Type::Array(element)
                        | Type::Slice { element }
                        | Type::Pointer { inner: element } => *element,
                        _ => types.intern(Type::Unknown),
                    };
                    body_env.insert(binding.text.clone(), binding_ty);
                    body_shapes.insert(
                        binding.text.clone(),
                        classify_type_for_equality(binding_ty, types, nominal_kinds),
                    );
                    body_mutability.insert(binding.text.clone(), false);
                }
                validate_unsupported_equality(
                    body,
                    &body_shapes,
                    &body_env,
                    &body_mutability,
                    signatures,
                    types,
                    nominal_kinds,
                    diagnostics,
                    file_path,
                    expected_return,
                );
            }
            ForExpr::WhileLike { condition, body } => {
                validate_unsupported_equality(
                    condition,
                    env_shapes,
                    env,
                    mutability,
                    signatures,
                    types,
                    nominal_kinds,
                    diagnostics,
                    file_path,
                    expected_return,
                );
                validate_unsupported_equality(
                    body,
                    env_shapes,
                    env,
                    mutability,
                    signatures,
                    types,
                    nominal_kinds,
                    diagnostics,
                    file_path,
                    expected_return,
                );
            }
            ForExpr::Infinite { body } => validate_unsupported_equality(
                body,
                env_shapes,
                env,
                mutability,
                signatures,
                types,
                nominal_kinds,
                diagnostics,
                file_path,
                expected_return,
            ),
        },
        ExprKind::OrElse(or_else) => {
            validate_unsupported_equality(
                &or_else.value,
                env_shapes,
                env,
                mutability,
                signatures,
                types,
                nominal_kinds,
                diagnostics,
                file_path,
                expected_return,
            );
            let mut fallback_env = env.clone();
            let mut fallback_shapes = env_shapes.clone();
            let mut fallback_mutability = mutability.clone();
            if let Some(binding) = &or_else.error_binding {
                fallback_env.insert(binding.text.clone(), types.intern(Type::Unknown));
                fallback_shapes.insert(binding.text.clone(), EqualityValueKind::Unknown);
                fallback_mutability.insert(binding.text.clone(), false);
            }
            validate_unsupported_equality(
                &or_else.fallback,
                &fallback_shapes,
                &fallback_env,
                &fallback_mutability,
                signatures,
                types,
                nominal_kinds,
                diagnostics,
                file_path,
                expected_return,
            );
        }
        _ => visit_expr_children(expr, |child| {
            validate_unsupported_equality(
                child,
                env_shapes,
                env,
                mutability,
                signatures,
                types,
                nominal_kinds,
                diagnostics,
                file_path,
                expected_return,
            )
        }),
    }
}

fn borrow_origin(expr: &Expr) -> Option<String> {
    match &expr.kind {
        ExprKind::Ident(ident) => Some(ident.text.clone()),
        ExprKind::FieldAccess { base, .. } | ExprKind::Index { base, .. } => borrow_origin(base),
        ExprKind::DerefAccess { .. } => None,
        _ => None,
    }
}

fn borrow_kind_for_origin(state: &BorrowState, origin: &str) -> Option<BorrowKind> {
    state.mutability.get(origin).map(|mutable| {
        if *mutable {
            BorrowKind::Mutable
        } else {
            BorrowKind::Shared
        }
    })
}

fn borrowed_binding(expr: &Expr, state: &BorrowState) -> Option<(String, BorrowKind, String)> {
    let ExprKind::Ident(ident) = &expr.kind else {
        return None;
    };
    state
        .binding_borrows
        .get(&ident.text)
        .map(|(origin, kind)| (origin.clone(), *kind, ident.text.clone()))
}

fn first_borrow_conflict<'a>(
    state: &'a BorrowState,
    origin: &str,
    kind: BorrowKind,
    ignore_binding: Option<&str>,
) -> Option<(&'a str, BorrowKind)> {
    let active = state.active_by_origin.get(origin)?;
    match kind {
        BorrowKind::Mutable => active
            .iter()
            .find(|(binding, _)| ignore_binding != Some(binding.as_str()))
            .map(|(binding, active_kind)| (binding.as_str(), *active_kind)),
        BorrowKind::Shared => active
            .iter()
            .find(|(binding, active_kind)| {
                ignore_binding != Some(binding.as_str()) && *active_kind == BorrowKind::Mutable
            })
            .map(|(binding, active_kind)| (binding.as_str(), *active_kind)),
    }
}

fn validate_borrow_binding_initializer(
    expr: &Expr,
    state: &BorrowState,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
) -> Option<(String, BorrowKind)> {
    let ExprKind::Unary {
        op: UnaryOp::Ref,
        expr: inner,
    } = &expr.kind
    else {
        return None;
    };
    let origin = borrow_origin(inner)?;
    let kind = borrow_kind_for_origin(state, &origin)?;
    if let Some((binding, active_kind)) = first_borrow_conflict(state, &origin, kind, None) {
        let active_kind = match active_kind {
            BorrowKind::Shared => "shared",
            BorrowKind::Mutable => "mutable",
        };
        diagnostics.push(
            Diagnostic::error(
                DiagnosticPhase::TypeChecker,
                DiagnosticCode::E4005,
                format!("conflicting borrow of '{}'", origin),
            )
            .with_primary_file_label(
                file_path.to_path_buf(),
                Some(expr.span),
                format!(
                    "conflicts with existing {active_kind} borrow held by '{}'",
                    binding
                ),
            ),
        );
    }
    Some((origin, kind))
}

fn validate_borrow_stmt(
    stmt: &Stmt,
    state: &mut BorrowState,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
) {
    match stmt {
        Stmt::Binding(binding) => {
            validate_borrow_rules(&binding.value, state, diagnostics, file_path);
            state.bind_local(&binding.name.text, binding.mutable);
            if let Some((origin, kind)) =
                validate_borrow_binding_initializer(&binding.value, state, diagnostics, file_path)
            {
                state.record_binding_borrow(&binding.name.text, &origin, kind);
            }
        }
        Stmt::Destructure(destructure) => {
            validate_borrow_rules(&destructure.value, state, diagnostics, file_path);
            for name in &destructure.names {
                state.bind_local(&name.name.text, name.mutable);
            }
        }
        Stmt::Expr(expr) => validate_borrow_rules(expr, state, diagnostics, file_path),
    }
}

pub(super) fn validate_borrow_rules(
    expr: &Expr,
    state: &mut BorrowState,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
) {
    match &expr.kind {
        ExprKind::Block(block) => {
            let mut local_state = state.clone();
            for stmt in &block.statements {
                validate_borrow_stmt(stmt, &mut local_state, diagnostics, file_path);
            }
            if let Some(tail_expr) = &block.tail_expr {
                validate_borrow_rules(tail_expr, &mut local_state, diagnostics, file_path);
            }
        }
        ExprKind::Fn(fn_expr) => {
            let mut local_state = BorrowState::with_params(&fn_expr.params);
            match &fn_expr.body {
                FnBody::Block(block) => validate_borrow_rules(
                    &Expr {
                        kind: ExprKind::Block(block.clone()),
                        span: expr.span,
                    },
                    &mut local_state,
                    diagnostics,
                    file_path,
                ),
                FnBody::ArrowExpr(body) => {
                    validate_borrow_rules(body, &mut local_state, diagnostics, file_path)
                }
            }
        }
        ExprKind::Call(call) => {
            validate_borrow_rules(&call.callee, state, diagnostics, file_path);
            let mut arg_state = state.clone();
            for arg in &call.args {
                validate_borrow_rules(&arg.value, &mut arg_state, diagnostics, file_path);
                if let Some((origin, kind)) = validate_borrow_binding_initializer(
                    &arg.value,
                    &arg_state,
                    diagnostics,
                    file_path,
                ) {
                    arg_state.record_binding_borrow(
                        &format!(
                            "$call_arg:{}:{}",
                            expr.span.start_line, arg.value.span.start_col
                        ),
                        &origin,
                        kind,
                    );
                }
            }
        }
        ExprKind::Assign { target, value, .. } => {
            validate_borrow_rules(value, state, diagnostics, file_path);
            validate_borrow_rules(target, state, diagnostics, file_path);

            if let Some(origin) = borrow_origin(target) {
                if state.active_by_origin.contains_key(&origin) {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            format!("cannot assign to '{}' while it is borrowed", origin),
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "assignment conflicts with a live borrow of this storage",
                        ),
                    );
                }
            }

            if let ExprKind::DerefAccess { base } = &target.kind {
                if let Some((origin, kind, binding)) = borrowed_binding(base, state) {
                    if kind == BorrowKind::Shared {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                format!("cannot write through shared borrow '{}'", binding),
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(expr.span),
                                "shared borrows are read-only",
                            ),
                        );
                    }
                    if let Some((conflict_binding, _)) =
                        first_borrow_conflict(state, &origin, BorrowKind::Mutable, Some(&binding))
                    {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                format!(
                                    "mutable dereference of '{}' conflicts with another live borrow",
                                    origin
                                ),
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(expr.span),
                                format!(
                                    "mutable access must be exclusive; '{}' is also live",
                                    conflict_binding
                                ),
                            ),
                        );
                    }
                }
            }

            if let ExprKind::Ident(ident) = &target.kind {
                state.release_binding_borrow(&ident.text);
            }
        }
        ExprKind::If(if_expr) => {
            validate_borrow_rules(&if_expr.condition, state, diagnostics, file_path);
            let mut then_state = state.clone();
            validate_borrow_rules(
                &if_expr.then_branch,
                &mut then_state,
                diagnostics,
                file_path,
            );
            if let Some(else_branch) = &if_expr.else_branch {
                let mut else_state = state.clone();
                validate_borrow_rules(else_branch, &mut else_state, diagnostics, file_path);
            }
        }
        ExprKind::Match(match_expr) => {
            validate_borrow_rules(&match_expr.scrutinee, state, diagnostics, file_path);
            for arm in &match_expr.arms {
                let mut arm_state = state.clone();
                if let Some(guard) = &arm.guard {
                    validate_borrow_rules(guard, &mut arm_state, diagnostics, file_path);
                }
                validate_borrow_rules(&arm.value, &mut arm_state, diagnostics, file_path);
            }
        }
        ExprKind::For(for_expr) => match for_expr {
            ForExpr::Range {
                start, end, body, ..
            } => {
                validate_borrow_rules(start, state, diagnostics, file_path);
                validate_borrow_rules(end, state, diagnostics, file_path);
                let mut body_state = state.clone();
                validate_borrow_rules(body, &mut body_state, diagnostics, file_path);
            }
            ForExpr::Iterate { iterable, body, .. } => {
                validate_borrow_rules(iterable, state, diagnostics, file_path);
                let mut body_state = state.clone();
                validate_borrow_rules(body, &mut body_state, diagnostics, file_path);
            }
            ForExpr::WhileLike { condition, body } => {
                validate_borrow_rules(condition, state, diagnostics, file_path);
                let mut body_state = state.clone();
                validate_borrow_rules(body, &mut body_state, diagnostics, file_path);
            }
            ForExpr::Infinite { body } => {
                let mut body_state = state.clone();
                validate_borrow_rules(body, &mut body_state, diagnostics, file_path);
            }
        },
        ExprKind::OrElse(or_else) => {
            validate_borrow_rules(&or_else.value, state, diagnostics, file_path);
            let mut fallback_state = state.clone();
            validate_borrow_rules(
                &or_else.fallback,
                &mut fallback_state,
                diagnostics,
                file_path,
            );
        }
        ExprKind::Unary {
            op: UnaryOp::Ref,
            expr: inner,
        } => {
            validate_borrow_rules(inner, state, diagnostics, file_path);
            let _ = validate_borrow_binding_initializer(expr, state, diagnostics, file_path);
        }
        _ => visit_expr_children(expr, |child| {
            validate_borrow_rules(child, state, diagnostics, file_path)
        }),
    }
}

pub(super) fn collect_enum_variants(unit: &ModuleUnit) -> BTreeMap<String, BTreeSet<String>> {
    let mut out = BTreeMap::new();
    for decl in &unit.declarations {
        let ExprKind::TypeLiteral(type_lit) = &decl.value.kind else {
            continue;
        };
        let TypeExprKind::Enum(enum_ty) = &type_lit.kind else {
            continue;
        };
        out.insert(
            decl.name.clone(),
            enum_ty
                .variants
                .iter()
                .map(|variant| variant.name.text.clone())
                .collect::<BTreeSet<_>>(),
        );
    }
    out
}

pub(super) fn implicit_error_union_ok_type(
    fn_expr: &crate::compiler::ast::FnExpr,
) -> Option<&TypeExpr> {
    let return_ty = fn_expr.return_type.as_ref()?;
    let TypeExprKind::Errorable { ok, errors } = &return_ty.kind else {
        return None;
    };
    if errors.is_empty() {
        Some(ok)
    } else {
        None
    }
}

#[allow(clippy::too_many_arguments)]
pub(super) fn infer_implicit_error_union_set(
    fn_expr: &crate::compiler::ast::FnExpr,
    env: &BTreeMap<String, TypeId>,
    mutability: &BTreeMap<String, bool>,
    signatures: &BTreeMap<String, FnSignature>,
    types: &mut TypeStore,
    enum_variants: &BTreeMap<String, BTreeSet<String>>,
    file_path: &std::path::Path,
) -> BTreeSet<String> {
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

    let mut inferred = BTreeSet::new();
    match &fn_expr.body {
        FnBody::ArrowExpr(body) => {
            collect_inferred_error_set_from_return_expr(
                body,
                &local_env,
                &local_mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                &mut inferred,
            );
            collect_inferred_error_set_from_unwraps_expr(
                body,
                &local_env,
                &local_mutability,
                signatures,
                types,
                file_path,
                &mut inferred,
            );
        }
        FnBody::Block(block) => {
            for stmt in &block.statements {
                match stmt {
                    Stmt::Expr(expr) => {
                        collect_inferred_error_set_from_return_sites(
                            expr,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            enum_variants,
                            file_path,
                            &mut inferred,
                        );
                        collect_inferred_error_set_from_unwraps_expr(
                            expr,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            file_path,
                            &mut inferred,
                        );
                    }
                    Stmt::Destructure(d) => {
                        collect_inferred_error_set_from_return_sites(
                            &d.value,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            enum_variants,
                            file_path,
                            &mut inferred,
                        );
                        collect_inferred_error_set_from_unwraps_expr(
                            &d.value,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            file_path,
                            &mut inferred,
                        );
                        let unknown = types.intern(Type::Unknown);
                        for dn in &d.names {
                            local_env.insert(dn.name.text.clone(), unknown);
                            local_mutability.insert(dn.name.text.clone(), dn.mutable);
                        }
                    }
                    Stmt::Binding(binding) => {
                        if !is_function_expr(&binding.value) {
                            collect_inferred_error_set_from_return_sites(
                                &binding.value,
                                &local_env,
                                &local_mutability,
                                signatures,
                                types,
                                enum_variants,
                                file_path,
                                &mut inferred,
                            );
                            collect_inferred_error_set_from_unwraps_expr(
                                &binding.value,
                                &local_env,
                                &local_mutability,
                                signatures,
                                types,
                                file_path,
                                &mut inferred,
                            );

                            let mut value_ty = infer_expr_type(
                                &binding.value,
                                &local_env,
                                &local_mutability,
                                signatures,
                                types,
                                &mut Vec::new(),
                                file_path,
                                None,
                            );
                            let final_ty = if let Some(annotation) = &binding.annotation {
                                let expected = resolve_type_expr(annotation, types)
                                    .unwrap_or_else(|| types.intern(Type::Unknown));
                                value_ty = maybe_coerce_literal_to_expected(
                                    &binding.value,
                                    value_ty,
                                    expected,
                                    types,
                                );
                                let _ = value_ty;
                                expected
                            } else {
                                value_ty
                            };
                            local_env.insert(binding.name.text.clone(), final_ty);
                            local_mutability.insert(binding.name.text.clone(), binding.mutable);
                        }
                    }
                }
            }
            if let Some(tail) = &block.tail_expr {
                collect_inferred_error_set_from_return_expr(
                    tail,
                    &local_env,
                    &local_mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    &mut inferred,
                );
                collect_inferred_error_set_from_unwraps_expr(
                    tail,
                    &local_env,
                    &local_mutability,
                    signatures,
                    types,
                    file_path,
                    &mut inferred,
                );
            }
        }
    }

    inferred
}

#[allow(clippy::too_many_arguments)]
pub(super) fn collect_inferred_error_set_from_return_sites(
    expr: &Expr,
    env: &BTreeMap<String, TypeId>,
    mutability: &BTreeMap<String, bool>,
    signatures: &BTreeMap<String, FnSignature>,
    types: &mut TypeStore,
    enum_variants: &BTreeMap<String, BTreeSet<String>>,
    file_path: &std::path::Path,
    inferred: &mut BTreeSet<String>,
) {
    match &expr.kind {
        ExprKind::Return { value } => {
            if let Some(value) = value {
                collect_inferred_error_set_from_return_expr(
                    value,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::Block(block) => {
            let mut local_env = env.clone();
            let mut local_mutability = mutability.clone();
            for stmt in &block.statements {
                match stmt {
                    Stmt::Expr(inner) => collect_inferred_error_set_from_return_sites(
                        inner,
                        &local_env,
                        &local_mutability,
                        signatures,
                        types,
                        enum_variants,
                        file_path,
                        inferred,
                    ),
                    Stmt::Destructure(d) => {
                        collect_inferred_error_set_from_return_sites(
                            &d.value,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            enum_variants,
                            file_path,
                            inferred,
                        );
                        let unknown = types.intern(Type::Unknown);
                        for dn in &d.names {
                            local_env.insert(dn.name.text.clone(), unknown);
                            local_mutability.insert(dn.name.text.clone(), dn.mutable);
                        }
                    }
                    Stmt::Binding(binding) if !is_function_expr(&binding.value) => {
                        collect_inferred_error_set_from_return_sites(
                            &binding.value,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            enum_variants,
                            file_path,
                            inferred,
                        );
                        let mut value_ty = infer_expr_type(
                            &binding.value,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            &mut Vec::new(),
                            file_path,
                            None,
                        );
                        let final_ty = if let Some(annotation) = &binding.annotation {
                            let expected = resolve_type_expr(annotation, types)
                                .unwrap_or_else(|| types.intern(Type::Unknown));
                            value_ty = maybe_coerce_literal_to_expected(
                                &binding.value,
                                value_ty,
                                expected,
                                types,
                            );
                            let _ = value_ty;
                            expected
                        } else {
                            value_ty
                        };
                        local_env.insert(binding.name.text.clone(), final_ty);
                        local_mutability.insert(binding.name.text.clone(), binding.mutable);
                    }
                    Stmt::Binding(_) => {}
                }
            }
            if let Some(tail) = &block.tail_expr {
                collect_inferred_error_set_from_return_sites(
                    tail,
                    &local_env,
                    &local_mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::If(if_expr) => {
            collect_inferred_error_set_from_return_sites(
                &if_expr.then_branch,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            );
            if let Some(else_branch) = &if_expr.else_branch {
                collect_inferred_error_set_from_return_sites(
                    else_branch,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::Match(match_expr) => {
            for arm in &match_expr.arms {
                collect_inferred_error_set_from_return_sites(
                    &arm.value,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::For(for_expr) => match for_expr {
            crate::compiler::ast::ForExpr::Range { body, .. }
            | crate::compiler::ast::ForExpr::Iterate { body, .. }
            | crate::compiler::ast::ForExpr::WhileLike { body, .. }
            | crate::compiler::ast::ForExpr::Infinite { body } => {
                collect_inferred_error_set_from_return_sites(
                    body,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
        },
        ExprKind::Fn(_) => {}
        ExprKind::Unary { expr, .. }
        | ExprKind::Comptime { expr }
        | ExprKind::Inline { expr }
        | ExprKind::OptionalUnwrap { expr }
        | ExprKind::ErrorUnwrap { expr }
        | ExprKind::DerefAccess { base: expr }
        | ExprKind::Defer(crate::compiler::ast::DeferExpr { body: expr, .. }) => {
            collect_inferred_error_set_from_return_sites(
                expr,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            )
        }
        ExprKind::Binary { left, right, .. }
        | ExprKind::Assign {
            target: left,
            value: right,
            ..
        }
        | ExprKind::Index {
            base: left,
            index: right,
        } => {
            collect_inferred_error_set_from_return_sites(
                left,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            );
            collect_inferred_error_set_from_return_sites(
                right,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            );
        }
        ExprKind::Call(call) => {
            collect_inferred_error_set_from_return_sites(
                &call.callee,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            );
            for arg in &call.args {
                collect_inferred_error_set_from_return_sites(
                    &arg.value,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::FieldAccess { base, .. } => collect_inferred_error_set_from_return_sites(
            base,
            env,
            mutability,
            signatures,
            types,
            enum_variants,
            file_path,
            inferred,
        ),
        ExprKind::Slice(slice_expr) => {
            collect_inferred_error_set_from_return_sites(
                &slice_expr.base,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            );
            if let Some(start) = &slice_expr.start {
                collect_inferred_error_set_from_return_sites(
                    start,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
            if let Some(end) = &slice_expr.end {
                collect_inferred_error_set_from_return_sites(
                    end,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::OrElse(or_else) => {
            collect_inferred_error_set_from_return_sites(
                &or_else.value,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            );
            collect_inferred_error_set_from_return_sites(
                &or_else.fallback,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            );
        }
        ExprKind::StructLiteral(lit) => {
            for field in &lit.fields {
                collect_inferred_error_set_from_return_sites(
                    &field.value,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::TypeConstruct { ty_expr, fields } => {
            collect_inferred_error_set_from_return_sites(
                ty_expr,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            );
            for field in fields {
                collect_inferred_error_set_from_return_sites(
                    &field.value,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::ArrayLiteral(elements) | ExprKind::TupleLiteral(elements) => {
            for element in elements {
                collect_inferred_error_set_from_return_sites(
                    element,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::Literal(_)
        | ExprKind::Ident(_)
        | ExprKind::BuiltinIdent(_)
        | ExprKind::Continue { .. }
        | ExprKind::Break(_)
        | ExprKind::Use { .. }
        | ExprKind::TypeLiteral(_)
        | ExprKind::EnumVariantConstruct(_) => {}
    }
}

#[allow(clippy::too_many_arguments)]
pub(super) fn collect_inferred_error_set_from_return_expr(
    expr: &Expr,
    env: &BTreeMap<String, TypeId>,
    mutability: &BTreeMap<String, bool>,
    signatures: &BTreeMap<String, FnSignature>,
    types: &mut TypeStore,
    enum_variants: &BTreeMap<String, BTreeSet<String>>,
    file_path: &std::path::Path,
    inferred: &mut BTreeSet<String>,
) {
    match &expr.kind {
        ExprKind::EnumVariantConstruct(variant) => {
            inferred.extend(candidate_error_enums_for_variant(variant, enum_variants));
            for payload in &variant.payload {
                collect_inferred_error_set_from_return_expr(
                    payload,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::ErrorUnwrap { expr: inner } => {
            let inner_ty = infer_expr_type(
                inner,
                env,
                mutability,
                signatures,
                types,
                &mut Vec::new(),
                file_path,
                None,
            );
            if let Type::Errorable { errors, .. } = types.get(inner_ty) {
                inferred.extend(errors.iter().cloned());
            }
            collect_inferred_error_set_from_return_expr(
                inner,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            );
        }
        ExprKind::If(if_expr) => {
            collect_inferred_error_set_from_return_expr(
                &if_expr.then_branch,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            );
            if let Some(else_branch) = &if_expr.else_branch {
                collect_inferred_error_set_from_return_expr(
                    else_branch,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::Match(match_expr) => {
            for arm in &match_expr.arms {
                collect_inferred_error_set_from_return_expr(
                    &arm.value,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::Block(block) => {
            let mut local_env = env.clone();
            let mut local_mutability = mutability.clone();
            for stmt in &block.statements {
                match stmt {
                    Stmt::Expr(inner) => collect_inferred_error_set_from_return_expr(
                        inner,
                        &local_env,
                        &local_mutability,
                        signatures,
                        types,
                        enum_variants,
                        file_path,
                        inferred,
                    ),
                    Stmt::Destructure(d) => {
                        collect_inferred_error_set_from_return_expr(
                            &d.value,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            enum_variants,
                            file_path,
                            inferred,
                        );
                        let unknown = types.intern(Type::Unknown);
                        for dn in &d.names {
                            local_env.insert(dn.name.text.clone(), unknown);
                            local_mutability.insert(dn.name.text.clone(), dn.mutable);
                        }
                    }
                    Stmt::Binding(binding) if !is_function_expr(&binding.value) => {
                        collect_inferred_error_set_from_return_expr(
                            &binding.value,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            enum_variants,
                            file_path,
                            inferred,
                        );
                        let mut value_ty = infer_expr_type(
                            &binding.value,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            &mut Vec::new(),
                            file_path,
                            None,
                        );
                        let final_ty = if let Some(annotation) = &binding.annotation {
                            let expected = resolve_type_expr(annotation, types)
                                .unwrap_or_else(|| types.intern(Type::Unknown));
                            value_ty = maybe_coerce_literal_to_expected(
                                &binding.value,
                                value_ty,
                                expected,
                                types,
                            );
                            let _ = value_ty;
                            expected
                        } else {
                            value_ty
                        };
                        local_env.insert(binding.name.text.clone(), final_ty);
                        local_mutability.insert(binding.name.text.clone(), binding.mutable);
                    }
                    Stmt::Binding(_) => {}
                }
            }
            if let Some(tail) = &block.tail_expr {
                collect_inferred_error_set_from_return_expr(
                    tail,
                    &local_env,
                    &local_mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::For(for_expr) => match for_expr {
            crate::compiler::ast::ForExpr::Range {
                start, end, body, ..
            } => {
                collect_inferred_error_set_from_return_expr(
                    start,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
                collect_inferred_error_set_from_return_expr(
                    end,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
                collect_inferred_error_set_from_return_expr(
                    body,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
            crate::compiler::ast::ForExpr::Iterate { iterable, body, .. } => {
                collect_inferred_error_set_from_return_expr(
                    iterable,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
                collect_inferred_error_set_from_return_expr(
                    body,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
            crate::compiler::ast::ForExpr::WhileLike { condition, body } => {
                collect_inferred_error_set_from_return_expr(
                    condition,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
                collect_inferred_error_set_from_return_expr(
                    body,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
            crate::compiler::ast::ForExpr::Infinite { body } => {
                collect_inferred_error_set_from_return_expr(
                    body,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
        },
        ExprKind::Call(call) => {
            collect_inferred_error_set_from_return_expr(
                &call.callee,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            );
            for arg in &call.args {
                collect_inferred_error_set_from_return_expr(
                    &arg.value,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::Assign { target, value, .. } => {
            collect_inferred_error_set_from_return_expr(
                target,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            );
            collect_inferred_error_set_from_return_expr(
                value,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            );
        }
        ExprKind::Binary { left, right, .. }
        | ExprKind::Index {
            base: left,
            index: right,
        } => {
            collect_inferred_error_set_from_return_expr(
                left,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            );
            collect_inferred_error_set_from_return_expr(
                right,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            );
        }
        ExprKind::Unary { expr, .. }
        | ExprKind::Comptime { expr }
        | ExprKind::Inline { expr }
        | ExprKind::OptionalUnwrap { expr }
        | ExprKind::DerefAccess { base: expr }
        | ExprKind::FieldAccess { base: expr, .. }
        | ExprKind::Defer(crate::compiler::ast::DeferExpr { body: expr, .. }) => {
            collect_inferred_error_set_from_return_expr(
                expr,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            );
        }
        ExprKind::Slice(slice_expr) => {
            collect_inferred_error_set_from_return_expr(
                &slice_expr.base,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            );
            if let Some(start) = &slice_expr.start {
                collect_inferred_error_set_from_return_expr(
                    start,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
            if let Some(end) = &slice_expr.end {
                collect_inferred_error_set_from_return_expr(
                    end,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::OrElse(or_else) => {
            collect_inferred_error_set_from_return_expr(
                &or_else.value,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            );
            collect_inferred_error_set_from_return_expr(
                &or_else.fallback,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            );
        }
        ExprKind::StructLiteral(lit) => {
            for field in &lit.fields {
                collect_inferred_error_set_from_return_expr(
                    &field.value,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::TypeConstruct { ty_expr, fields } => {
            collect_inferred_error_set_from_return_expr(
                ty_expr,
                env,
                mutability,
                signatures,
                types,
                enum_variants,
                file_path,
                inferred,
            );
            for field in fields {
                collect_inferred_error_set_from_return_expr(
                    &field.value,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::ArrayLiteral(elements) | ExprKind::TupleLiteral(elements) => {
            for element in elements {
                collect_inferred_error_set_from_return_expr(
                    element,
                    env,
                    mutability,
                    signatures,
                    types,
                    enum_variants,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::Fn(_)
        | ExprKind::Literal(_)
        | ExprKind::Ident(_)
        | ExprKind::BuiltinIdent(_)
        | ExprKind::Continue { .. }
        | ExprKind::Break(_)
        | ExprKind::Use { .. }
        | ExprKind::TypeLiteral(_)
        | ExprKind::Return { .. } => {}
    }
}

#[allow(clippy::too_many_arguments)]
pub(super) fn collect_inferred_error_set_from_unwraps_expr(
    expr: &Expr,
    env: &BTreeMap<String, TypeId>,
    mutability: &BTreeMap<String, bool>,
    signatures: &BTreeMap<String, FnSignature>,
    types: &mut TypeStore,
    file_path: &std::path::Path,
    inferred: &mut BTreeSet<String>,
) {
    match &expr.kind {
        ExprKind::ErrorUnwrap { expr: inner } => {
            let inner_ty = infer_expr_type(
                inner,
                env,
                mutability,
                signatures,
                types,
                &mut Vec::new(),
                file_path,
                None,
            );
            if let Type::Errorable { errors, .. } = types.get(inner_ty) {
                inferred.extend(errors.iter().cloned());
            }
            collect_inferred_error_set_from_unwraps_expr(
                inner, env, mutability, signatures, types, file_path, inferred,
            );
        }
        ExprKind::Fn(_) => {}
        ExprKind::Block(block) => {
            let mut local_env = env.clone();
            let mut local_mutability = mutability.clone();
            for stmt in &block.statements {
                match stmt {
                    Stmt::Expr(inner) => collect_inferred_error_set_from_unwraps_expr(
                        inner,
                        &local_env,
                        &local_mutability,
                        signatures,
                        types,
                        file_path,
                        inferred,
                    ),
                    Stmt::Destructure(d) => {
                        collect_inferred_error_set_from_unwraps_expr(
                            &d.value,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            file_path,
                            inferred,
                        );
                        let unknown = types.intern(Type::Unknown);
                        for dn in &d.names {
                            local_env.insert(dn.name.text.clone(), unknown);
                            local_mutability.insert(dn.name.text.clone(), dn.mutable);
                        }
                    }
                    Stmt::Binding(binding) if !is_function_expr(&binding.value) => {
                        collect_inferred_error_set_from_unwraps_expr(
                            &binding.value,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            file_path,
                            inferred,
                        );
                        let mut value_ty = infer_expr_type(
                            &binding.value,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            &mut Vec::new(),
                            file_path,
                            None,
                        );
                        let final_ty = if let Some(annotation) = &binding.annotation {
                            let expected = resolve_type_expr(annotation, types)
                                .unwrap_or_else(|| types.intern(Type::Unknown));
                            value_ty = maybe_coerce_literal_to_expected(
                                &binding.value,
                                value_ty,
                                expected,
                                types,
                            );
                            let _ = value_ty;
                            expected
                        } else {
                            value_ty
                        };
                        local_env.insert(binding.name.text.clone(), final_ty);
                        local_mutability.insert(binding.name.text.clone(), binding.mutable);
                    }
                    Stmt::Binding(_) => {}
                }
            }
            if let Some(tail) = &block.tail_expr {
                collect_inferred_error_set_from_unwraps_expr(
                    tail,
                    &local_env,
                    &local_mutability,
                    signatures,
                    types,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::If(if_expr) => {
            collect_inferred_error_set_from_unwraps_expr(
                &if_expr.condition,
                env,
                mutability,
                signatures,
                types,
                file_path,
                inferred,
            );
            collect_inferred_error_set_from_unwraps_expr(
                &if_expr.then_branch,
                env,
                mutability,
                signatures,
                types,
                file_path,
                inferred,
            );
            if let Some(else_branch) = &if_expr.else_branch {
                collect_inferred_error_set_from_unwraps_expr(
                    else_branch,
                    env,
                    mutability,
                    signatures,
                    types,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::Match(match_expr) => {
            collect_inferred_error_set_from_unwraps_expr(
                &match_expr.scrutinee,
                env,
                mutability,
                signatures,
                types,
                file_path,
                inferred,
            );
            for arm in &match_expr.arms {
                if let Some(guard) = &arm.guard {
                    collect_inferred_error_set_from_unwraps_expr(
                        guard, env, mutability, signatures, types, file_path, inferred,
                    );
                }
                collect_inferred_error_set_from_unwraps_expr(
                    &arm.value, env, mutability, signatures, types, file_path, inferred,
                );
            }
        }
        ExprKind::For(for_expr) => match for_expr {
            crate::compiler::ast::ForExpr::Range {
                start, end, body, ..
            } => {
                collect_inferred_error_set_from_unwraps_expr(
                    start, env, mutability, signatures, types, file_path, inferred,
                );
                collect_inferred_error_set_from_unwraps_expr(
                    end, env, mutability, signatures, types, file_path, inferred,
                );
                collect_inferred_error_set_from_unwraps_expr(
                    body, env, mutability, signatures, types, file_path, inferred,
                );
            }
            crate::compiler::ast::ForExpr::Iterate { iterable, body, .. } => {
                collect_inferred_error_set_from_unwraps_expr(
                    iterable, env, mutability, signatures, types, file_path, inferred,
                );
                collect_inferred_error_set_from_unwraps_expr(
                    body, env, mutability, signatures, types, file_path, inferred,
                );
            }
            crate::compiler::ast::ForExpr::WhileLike { condition, body } => {
                collect_inferred_error_set_from_unwraps_expr(
                    condition, env, mutability, signatures, types, file_path, inferred,
                );
                collect_inferred_error_set_from_unwraps_expr(
                    body, env, mutability, signatures, types, file_path, inferred,
                );
            }
            crate::compiler::ast::ForExpr::Infinite { body } => {
                collect_inferred_error_set_from_unwraps_expr(
                    body, env, mutability, signatures, types, file_path, inferred,
                );
            }
        },
        ExprKind::Call(call) => {
            collect_inferred_error_set_from_unwraps_expr(
                &call.callee,
                env,
                mutability,
                signatures,
                types,
                file_path,
                inferred,
            );
            for arg in &call.args {
                collect_inferred_error_set_from_unwraps_expr(
                    &arg.value, env, mutability, signatures, types, file_path, inferred,
                );
            }
        }
        ExprKind::Assign { target, value, .. } => {
            collect_inferred_error_set_from_unwraps_expr(
                target, env, mutability, signatures, types, file_path, inferred,
            );
            collect_inferred_error_set_from_unwraps_expr(
                value, env, mutability, signatures, types, file_path, inferred,
            );
        }
        ExprKind::Binary { left, right, .. }
        | ExprKind::Index {
            base: left,
            index: right,
        } => {
            collect_inferred_error_set_from_unwraps_expr(
                left, env, mutability, signatures, types, file_path, inferred,
            );
            collect_inferred_error_set_from_unwraps_expr(
                right, env, mutability, signatures, types, file_path, inferred,
            );
        }
        ExprKind::Unary { expr, .. }
        | ExprKind::Comptime { expr }
        | ExprKind::Inline { expr }
        | ExprKind::OptionalUnwrap { expr }
        | ExprKind::DerefAccess { base: expr }
        | ExprKind::FieldAccess { base: expr, .. }
        | ExprKind::Return { value: Some(expr) }
        | ExprKind::Defer(crate::compiler::ast::DeferExpr { body: expr, .. }) => {
            collect_inferred_error_set_from_unwraps_expr(
                expr, env, mutability, signatures, types, file_path, inferred,
            );
        }
        ExprKind::Slice(slice_expr) => {
            collect_inferred_error_set_from_unwraps_expr(
                &slice_expr.base,
                env,
                mutability,
                signatures,
                types,
                file_path,
                inferred,
            );
            if let Some(start) = &slice_expr.start {
                collect_inferred_error_set_from_unwraps_expr(
                    start, env, mutability, signatures, types, file_path, inferred,
                );
            }
            if let Some(end) = &slice_expr.end {
                collect_inferred_error_set_from_unwraps_expr(
                    end, env, mutability, signatures, types, file_path, inferred,
                );
            }
        }
        ExprKind::OrElse(or_else) => {
            collect_inferred_error_set_from_unwraps_expr(
                &or_else.value,
                env,
                mutability,
                signatures,
                types,
                file_path,
                inferred,
            );
            collect_inferred_error_set_from_unwraps_expr(
                &or_else.fallback,
                env,
                mutability,
                signatures,
                types,
                file_path,
                inferred,
            );
        }
        ExprKind::StructLiteral(lit) => {
            for field in &lit.fields {
                collect_inferred_error_set_from_unwraps_expr(
                    &field.value,
                    env,
                    mutability,
                    signatures,
                    types,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::TypeConstruct { ty_expr, fields } => {
            collect_inferred_error_set_from_unwraps_expr(
                ty_expr, env, mutability, signatures, types, file_path, inferred,
            );
            for field in fields {
                collect_inferred_error_set_from_unwraps_expr(
                    &field.value,
                    env,
                    mutability,
                    signatures,
                    types,
                    file_path,
                    inferred,
                );
            }
        }
        ExprKind::EnumVariantConstruct(variant) => {
            for payload in &variant.payload {
                collect_inferred_error_set_from_unwraps_expr(
                    payload, env, mutability, signatures, types, file_path, inferred,
                );
            }
        }
        ExprKind::ArrayLiteral(elements) | ExprKind::TupleLiteral(elements) => {
            for element in elements {
                collect_inferred_error_set_from_unwraps_expr(
                    element, env, mutability, signatures, types, file_path, inferred,
                );
            }
        }
        ExprKind::Literal(_)
        | ExprKind::Ident(_)
        | ExprKind::BuiltinIdent(_)
        | ExprKind::Continue { .. }
        | ExprKind::Break(_)
        | ExprKind::Return { value: None }
        | ExprKind::Use { .. }
        | ExprKind::TypeLiteral(_) => {}
    }
}

pub(super) fn candidate_error_enums_for_variant(
    variant: &crate::compiler::ast::EnumVariantExpr,
    enum_variants: &BTreeMap<String, BTreeSet<String>>,
) -> BTreeSet<String> {
    if let Some(root) = &variant.root {
        if enum_variants.contains_key(&root.text) {
            return [root.text.clone()].into_iter().collect();
        }
        return BTreeSet::new();
    }

    enum_variants
        .iter()
        .filter_map(|(enum_name, variants)| {
            if variants.contains(&variant.variant.text) {
                Some(enum_name.clone())
            } else {
                None
            }
        })
        .collect()
}

pub(super) fn validate_function_error_set_coverage(
    fn_expr: &crate::compiler::ast::FnExpr,
    enum_variants: &BTreeMap<String, BTreeSet<String>>,
    file_path: &std::path::Path,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let Some(return_ty) = &fn_expr.return_type else {
        return;
    };
    let TypeExprKind::Errorable { errors, .. } = &return_ty.kind else {
        return;
    };
    if errors.is_empty() {
        return;
    }

    let declared_errors = errors
        .iter()
        .map(|error| error.text.clone())
        .collect::<BTreeSet<_>>();

    match &fn_expr.body {
        FnBody::ArrowExpr(body) => {
            validate_error_return_value_expr(
                body,
                &declared_errors,
                enum_variants,
                file_path,
                diagnostics,
            );
        }
        FnBody::Block(block) => {
            for stmt in &block.statements {
                match stmt {
                    Stmt::Expr(expr) => validate_error_set_returns_expr(
                        expr,
                        &declared_errors,
                        enum_variants,
                        file_path,
                        diagnostics,
                    ),
                    Stmt::Destructure(d) => validate_error_set_returns_expr(
                        &d.value,
                        &declared_errors,
                        enum_variants,
                        file_path,
                        diagnostics,
                    ),
                    Stmt::Binding(binding) if !is_function_expr(&binding.value) => {
                        validate_error_set_returns_expr(
                            &binding.value,
                            &declared_errors,
                            enum_variants,
                            file_path,
                            diagnostics,
                        )
                    }
                    Stmt::Binding(_) => {}
                }
            }
            if let Some(tail) = &block.tail_expr {
                validate_error_set_returns_expr(
                    tail,
                    &declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
            }
        }
    }
}

pub(super) fn validate_value_required_exprs(
    expr: &Expr,
    value_required: bool,
    file_path: &std::path::Path,
    diagnostics: &mut Vec<Diagnostic>,
) {
    match &expr.kind {
        ExprKind::If(if_expr) => {
            if value_required && if_expr.else_branch.is_none() {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "if expression requires an else branch",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "add an `else` branch or use the `if` in statement position",
                    ),
                );
            }
            validate_value_required_exprs(&if_expr.condition, true, file_path, diagnostics);
            validate_value_required_exprs(
                &if_expr.then_branch,
                value_required,
                file_path,
                diagnostics,
            );
            if let Some(else_branch) = &if_expr.else_branch {
                validate_value_required_exprs(else_branch, value_required, file_path, diagnostics);
            }
        }
        ExprKind::Match(match_expr) => {
            validate_value_required_exprs(&match_expr.scrutinee, true, file_path, diagnostics);
            for arm in &match_expr.arms {
                if let Some(guard) = &arm.guard {
                    validate_value_required_exprs(guard, true, file_path, diagnostics);
                }
                validate_value_required_exprs(&arm.value, value_required, file_path, diagnostics);
            }
        }
        ExprKind::Block(block) => {
            for stmt in &block.statements {
                match stmt {
                    Stmt::Binding(binding) => {
                        validate_value_required_exprs(&binding.value, true, file_path, diagnostics)
                    }
                    Stmt::Destructure(d) => {
                        validate_value_required_exprs(&d.value, true, file_path, diagnostics)
                    }
                    Stmt::Expr(stmt_expr) => {
                        validate_value_required_exprs(stmt_expr, false, file_path, diagnostics)
                    }
                }
            }
            if let Some(tail_expr) = &block.tail_expr {
                validate_value_required_exprs(tail_expr, value_required, file_path, diagnostics);
            }
        }
        ExprKind::Fn(fn_expr) => match &fn_expr.body {
            FnBody::Block(block) => {
                for stmt in &block.statements {
                    match stmt {
                        Stmt::Binding(binding) => validate_value_required_exprs(
                            &binding.value,
                            true,
                            file_path,
                            diagnostics,
                        ),
                        Stmt::Destructure(d) => {
                            validate_value_required_exprs(&d.value, true, file_path, diagnostics)
                        }
                        Stmt::Expr(stmt_expr) => {
                            validate_value_required_exprs(stmt_expr, false, file_path, diagnostics)
                        }
                    }
                }
                if let Some(tail_expr) = &block.tail_expr {
                    validate_value_required_exprs(tail_expr, false, file_path, diagnostics);
                }
            }
            FnBody::ArrowExpr(body) => {
                validate_value_required_exprs(body, true, file_path, diagnostics)
            }
        },
        ExprKind::Unary { expr, .. }
        | ExprKind::OptionalUnwrap { expr }
        | ExprKind::ErrorUnwrap { expr }
        | ExprKind::Comptime { expr }
        | ExprKind::Inline { expr }
        | ExprKind::DerefAccess { base: expr } => {
            validate_value_required_exprs(expr, true, file_path, diagnostics)
        }
        ExprKind::Binary { left, right, .. }
        | ExprKind::Assign {
            target: left,
            value: right,
            ..
        }
        | ExprKind::Index {
            base: left,
            index: right,
        } => {
            validate_value_required_exprs(left, true, file_path, diagnostics);
            validate_value_required_exprs(right, true, file_path, diagnostics);
        }
        ExprKind::Call(call) => {
            validate_value_required_exprs(&call.callee, true, file_path, diagnostics);
            for arg in &call.args {
                validate_value_required_exprs(&arg.value, true, file_path, diagnostics);
            }
        }
        ExprKind::FieldAccess { base, .. } => {
            validate_value_required_exprs(base, true, file_path, diagnostics)
        }
        ExprKind::Slice(slice) => {
            validate_value_required_exprs(&slice.base, true, file_path, diagnostics);
            if let Some(start) = &slice.start {
                validate_value_required_exprs(start, true, file_path, diagnostics);
            }
            if let Some(end) = &slice.end {
                validate_value_required_exprs(end, true, file_path, diagnostics);
            }
        }
        ExprKind::For(for_expr) => match for_expr {
            ForExpr::Range {
                start, end, body, ..
            } => {
                validate_value_required_exprs(start, true, file_path, diagnostics);
                validate_value_required_exprs(end, true, file_path, diagnostics);
                validate_value_required_exprs(body, false, file_path, diagnostics);
            }
            ForExpr::Iterate { iterable, body, .. } => {
                validate_value_required_exprs(iterable, true, file_path, diagnostics);
                validate_value_required_exprs(body, false, file_path, diagnostics);
            }
            ForExpr::WhileLike { condition, body } => {
                validate_value_required_exprs(condition, true, file_path, diagnostics);
                validate_value_required_exprs(body, false, file_path, diagnostics);
            }
            ForExpr::Infinite { body } => {
                validate_value_required_exprs(body, false, file_path, diagnostics)
            }
        },
        ExprKind::Return { value } => {
            if let Some(value) = value {
                validate_value_required_exprs(value, true, file_path, diagnostics);
            }
        }
        ExprKind::Break(break_expr) => {
            if let Some(value) = &break_expr.value {
                validate_value_required_exprs(value, true, file_path, diagnostics);
            }
        }
        ExprKind::Defer(defer_expr) => {
            validate_value_required_exprs(&defer_expr.body, false, file_path, diagnostics)
        }
        ExprKind::OrElse(or_else) => {
            validate_value_required_exprs(&or_else.value, true, file_path, diagnostics);
            validate_value_required_exprs(
                &or_else.fallback,
                value_required,
                file_path,
                diagnostics,
            );
        }
        ExprKind::StructLiteral(struct_lit) => {
            for field in &struct_lit.fields {
                validate_value_required_exprs(&field.value, true, file_path, diagnostics);
            }
        }
        ExprKind::TypeConstruct { ty_expr, fields } => {
            validate_value_required_exprs(ty_expr, true, file_path, diagnostics);
            for field in fields {
                validate_value_required_exprs(&field.value, true, file_path, diagnostics);
            }
        }
        ExprKind::ArrayLiteral(elements) | ExprKind::TupleLiteral(elements) => {
            for element in elements {
                validate_value_required_exprs(element, true, file_path, diagnostics);
            }
        }
        ExprKind::EnumVariantConstruct(enum_variant) => {
            for payload in &enum_variant.payload {
                validate_value_required_exprs(payload, true, file_path, diagnostics);
            }
        }
        ExprKind::Literal(_)
        | ExprKind::Ident(_)
        | ExprKind::BuiltinIdent(_)
        | ExprKind::Continue { .. }
        | ExprKind::Use { .. }
        | ExprKind::TypeLiteral(_) => {}
    }
}

pub(super) fn validate_error_set_returns_expr(
    expr: &Expr,
    declared_errors: &BTreeSet<String>,
    enum_variants: &BTreeMap<String, BTreeSet<String>>,
    file_path: &std::path::Path,
    diagnostics: &mut Vec<Diagnostic>,
) {
    match &expr.kind {
        ExprKind::Return { value } => {
            if let Some(value) = value {
                validate_error_return_value_expr(
                    value,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
                validate_error_set_returns_expr(
                    value,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::Block(block) => {
            for stmt in &block.statements {
                match stmt {
                    Stmt::Expr(inner) => validate_error_set_returns_expr(
                        inner,
                        declared_errors,
                        enum_variants,
                        file_path,
                        diagnostics,
                    ),
                    Stmt::Destructure(d) => validate_error_set_returns_expr(
                        &d.value,
                        declared_errors,
                        enum_variants,
                        file_path,
                        diagnostics,
                    ),
                    Stmt::Binding(binding) if !is_function_expr(&binding.value) => {
                        validate_error_set_returns_expr(
                            &binding.value,
                            declared_errors,
                            enum_variants,
                            file_path,
                            diagnostics,
                        )
                    }
                    Stmt::Binding(_) => {}
                }
            }
            if let Some(tail) = &block.tail_expr {
                validate_error_set_returns_expr(
                    tail,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::If(if_expr) => {
            validate_error_set_returns_expr(
                &if_expr.condition,
                declared_errors,
                enum_variants,
                file_path,
                diagnostics,
            );
            validate_error_set_returns_expr(
                &if_expr.then_branch,
                declared_errors,
                enum_variants,
                file_path,
                diagnostics,
            );
            if let Some(else_branch) = &if_expr.else_branch {
                validate_error_set_returns_expr(
                    else_branch,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::Match(match_expr) => {
            validate_error_set_returns_expr(
                &match_expr.scrutinee,
                declared_errors,
                enum_variants,
                file_path,
                diagnostics,
            );
            for arm in &match_expr.arms {
                if let Some(guard) = &arm.guard {
                    validate_error_set_returns_expr(
                        guard,
                        declared_errors,
                        enum_variants,
                        file_path,
                        diagnostics,
                    );
                }
                validate_error_set_returns_expr(
                    &arm.value,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::For(for_expr) => match for_expr {
            crate::compiler::ast::ForExpr::Range {
                start, end, body, ..
            } => {
                validate_error_set_returns_expr(
                    start,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
                validate_error_set_returns_expr(
                    end,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
                validate_error_set_returns_expr(
                    body,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
            }
            crate::compiler::ast::ForExpr::Iterate { iterable, body, .. } => {
                validate_error_set_returns_expr(
                    iterable,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
                validate_error_set_returns_expr(
                    body,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
            }
            crate::compiler::ast::ForExpr::WhileLike { condition, body } => {
                validate_error_set_returns_expr(
                    condition,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
                validate_error_set_returns_expr(
                    body,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
            }
            crate::compiler::ast::ForExpr::Infinite { body } => {
                validate_error_set_returns_expr(
                    body,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
            }
        },
        ExprKind::Call(call) => {
            validate_error_set_returns_expr(
                &call.callee,
                declared_errors,
                enum_variants,
                file_path,
                diagnostics,
            );
            for arg in &call.args {
                validate_error_set_returns_expr(
                    &arg.value,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::Assign { target, value, .. } => {
            validate_error_set_returns_expr(
                target,
                declared_errors,
                enum_variants,
                file_path,
                diagnostics,
            );
            validate_error_set_returns_expr(
                value,
                declared_errors,
                enum_variants,
                file_path,
                diagnostics,
            );
        }
        ExprKind::Binary { left, right, .. } => {
            validate_error_set_returns_expr(
                left,
                declared_errors,
                enum_variants,
                file_path,
                diagnostics,
            );
            validate_error_set_returns_expr(
                right,
                declared_errors,
                enum_variants,
                file_path,
                diagnostics,
            );
        }
        ExprKind::Unary { expr, .. }
        | ExprKind::FieldAccess { base: expr, .. }
        | ExprKind::DerefAccess { base: expr }
        | ExprKind::OptionalUnwrap { expr }
        | ExprKind::ErrorUnwrap { expr }
        | ExprKind::Comptime { expr }
        | ExprKind::Inline { expr }
        | ExprKind::Defer(crate::compiler::ast::DeferExpr { body: expr, .. }) => {
            validate_error_set_returns_expr(
                expr,
                declared_errors,
                enum_variants,
                file_path,
                diagnostics,
            );
        }
        ExprKind::Index { base, index } => {
            validate_error_set_returns_expr(
                base,
                declared_errors,
                enum_variants,
                file_path,
                diagnostics,
            );
            validate_error_set_returns_expr(
                index,
                declared_errors,
                enum_variants,
                file_path,
                diagnostics,
            );
        }
        ExprKind::Slice(slice_expr) => {
            validate_error_set_returns_expr(
                &slice_expr.base,
                declared_errors,
                enum_variants,
                file_path,
                diagnostics,
            );
            if let Some(start) = &slice_expr.start {
                validate_error_set_returns_expr(
                    start,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
            }
            if let Some(end) = &slice_expr.end {
                validate_error_set_returns_expr(
                    end,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::OrElse(or_else) => {
            validate_error_set_returns_expr(
                &or_else.value,
                declared_errors,
                enum_variants,
                file_path,
                diagnostics,
            );
            validate_error_set_returns_expr(
                &or_else.fallback,
                declared_errors,
                enum_variants,
                file_path,
                diagnostics,
            );
        }
        ExprKind::StructLiteral(lit) => {
            for field in &lit.fields {
                validate_error_set_returns_expr(
                    &field.value,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::TypeConstruct { ty_expr, fields } => {
            validate_error_set_returns_expr(
                ty_expr,
                declared_errors,
                enum_variants,
                file_path,
                diagnostics,
            );
            for field in fields {
                validate_error_set_returns_expr(
                    &field.value,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::ArrayLiteral(elements) | ExprKind::TupleLiteral(elements) => {
            for element in elements {
                validate_error_set_returns_expr(
                    element,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::EnumVariantConstruct(variant) => {
            for payload in &variant.payload {
                validate_error_set_returns_expr(
                    payload,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::Fn(_)
        | ExprKind::Literal(_)
        | ExprKind::Ident(_)
        | ExprKind::BuiltinIdent(_)
        | ExprKind::Continue { .. }
        | ExprKind::Break(_)
        | ExprKind::Use { .. }
        | ExprKind::TypeLiteral(_) => {}
    }
}

pub(super) fn validate_error_return_value_expr(
    expr: &Expr,
    declared_errors: &BTreeSet<String>,
    enum_variants: &BTreeMap<String, BTreeSet<String>>,
    file_path: &std::path::Path,
    diagnostics: &mut Vec<Diagnostic>,
) {
    match &expr.kind {
        ExprKind::EnumVariantConstruct(variant) => validate_error_variant_against_declared_set(
            variant,
            expr.span,
            declared_errors,
            enum_variants,
            file_path,
            diagnostics,
        ),
        ExprKind::If(if_expr) => {
            validate_error_return_value_expr(
                &if_expr.then_branch,
                declared_errors,
                enum_variants,
                file_path,
                diagnostics,
            );
            if let Some(else_branch) = &if_expr.else_branch {
                validate_error_return_value_expr(
                    else_branch,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::Match(match_expr) => {
            for arm in &match_expr.arms {
                validate_error_return_value_expr(
                    &arm.value,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::Block(block) => {
            if let Some(tail) = &block.tail_expr {
                validate_error_return_value_expr(
                    tail,
                    declared_errors,
                    enum_variants,
                    file_path,
                    diagnostics,
                );
            }
        }
        _ => {}
    }
}

pub(super) fn validate_error_variant_against_declared_set(
    variant: &crate::compiler::ast::EnumVariantExpr,
    span: crate::compiler::diagnostics::SourceSpan,
    declared_errors: &BTreeSet<String>,
    enum_variants: &BTreeMap<String, BTreeSet<String>>,
    file_path: &std::path::Path,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let variant_name = variant.variant.text.clone();

    if let Some(root) = &variant.root {
        if !declared_errors.contains(&root.text) {
            diagnostics.push(
                Diagnostic::error(
                    DiagnosticPhase::TypeChecker,
                    DiagnosticCode::E4005,
                    "returned error is not in function error set",
                )
                .with_primary_file_label(
                    file_path.to_path_buf(),
                    Some(span),
                    "add this error enum to the function return type",
                ),
            );
            return;
        }
        if let Some(variants) = enum_variants.get(&root.text) {
            if !variants.contains(&variant_name) {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "returned error variant is not defined on enum",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(span),
                        "use a variant that exists on the declared error enum",
                    ),
                );
            }
        }
        return;
    }

    if declared_errors.is_empty() {
        diagnostics.push(
            Diagnostic::error(
                DiagnosticPhase::TypeChecker,
                DiagnosticCode::E4005,
                "returned error is not in function error set",
            )
            .with_primary_file_label(
                file_path.to_path_buf(),
                Some(span),
                "declare an error enum in the function return type",
            ),
        );
        return;
    }

    if declared_errors.len() == 1 {
        let expected_enum = declared_errors
            .iter()
            .next()
            .expect("single-element set should have a value");
        if let Some(variants) = enum_variants.get(expected_enum) {
            if !variants.contains(&variant_name) {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "returned error variant is not defined on enum",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(span),
                        "use a variant that exists on the declared error enum",
                    ),
                );
            }
        }
        return;
    }

    let all_declared_known = declared_errors
        .iter()
        .all(|error_enum| enum_variants.contains_key(error_enum));
    if !all_declared_known {
        diagnostics.push(
            Diagnostic::error(
                DiagnosticPhase::TypeChecker,
                DiagnosticCode::E4005,
                "cannot infer unqualified returned error across multiple error enums",
            )
            .with_primary_file_label(
                file_path.to_path_buf(),
                Some(span),
                "qualify error with enum name (for example `ErrType.Variant`)",
            ),
        );
        return;
    }

    let matching = declared_errors
        .iter()
        .filter(|error_enum| {
            enum_variants
                .get(*error_enum)
                .is_some_and(|variants| variants.contains(&variant_name))
        })
        .cloned()
        .collect::<Vec<_>>();

    if matching.is_empty() {
        diagnostics.push(
            Diagnostic::error(
                DiagnosticPhase::TypeChecker,
                DiagnosticCode::E4005,
                "returned error is not in function error set",
            )
            .with_primary_file_label(
                file_path.to_path_buf(),
                Some(span),
                "return an error variant from a declared error enum",
            ),
        );
    } else if matching.len() > 1 {
        diagnostics.push(
            Diagnostic::error(
                DiagnosticPhase::TypeChecker,
                DiagnosticCode::E4005,
                "unqualified returned error variant is ambiguous",
            )
            .with_primary_file_label(
                file_path.to_path_buf(),
                Some(span),
                "qualify error with enum name (for example `ErrType.Variant`)",
            ),
        );
    }
}

pub(super) fn validate_named_struct_offsetof_calls(
    expr: &Expr,
    named_struct_fields: &BTreeMap<String, Vec<String>>,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
) {
    match &expr.kind {
        ExprKind::Call(call) => {
            if matches!(&call.callee.kind, ExprKind::BuiltinIdent(ident) if ident.text == "$offsetof")
                && call.args.len() == 2
            {
                if let ExprKind::Ident(type_name) = &call.args[0].value.kind {
                    if let Some(fields) = named_struct_fields.get(&type_name.text) {
                        let valid = match &call.args[1].value.kind {
                            ExprKind::Ident(field) => fields.iter().any(|name| name == &field.text),
                            ExprKind::Literal(Literal::Integer(index)) => index
                                .parse::<usize>()
                                .map(|idx| idx < fields.len())
                                .unwrap_or(false),
                            _ => false,
                        };
                        if !valid {
                            diagnostics.push(
                                Diagnostic::error(
                                    DiagnosticPhase::TypeChecker,
                                    DiagnosticCode::E4005,
                                    "$offsetof field designator is invalid for named struct type",
                                )
                                .with_primary_file_label(
                                    file_path.to_path_buf(),
                                    Some(call.args[1].value.span),
                                    "use an existing field name or in-range field index",
                                ),
                            );
                        }
                    }
                }
            }

            validate_named_struct_offsetof_calls(
                &call.callee,
                named_struct_fields,
                diagnostics,
                file_path,
            );
            for arg in &call.args {
                validate_named_struct_offsetof_calls(
                    &arg.value,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
            }
        }
        ExprKind::Block(block) => {
            for stmt in &block.statements {
                match stmt {
                    Stmt::Binding(binding) => validate_named_struct_offsetof_calls(
                        &binding.value,
                        named_struct_fields,
                        diagnostics,
                        file_path,
                    ),
                    Stmt::Destructure(d) => validate_named_struct_offsetof_calls(
                        &d.value,
                        named_struct_fields,
                        diagnostics,
                        file_path,
                    ),
                    Stmt::Expr(stmt_expr) => validate_named_struct_offsetof_calls(
                        stmt_expr,
                        named_struct_fields,
                        diagnostics,
                        file_path,
                    ),
                }
            }
            if let Some(tail) = &block.tail_expr {
                validate_named_struct_offsetof_calls(
                    tail,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
            }
        }
        ExprKind::Unary { expr, .. }
        | ExprKind::Comptime { expr }
        | ExprKind::Inline { expr }
        | ExprKind::OptionalUnwrap { expr }
        | ExprKind::ErrorUnwrap { expr } => {
            validate_named_struct_offsetof_calls(expr, named_struct_fields, diagnostics, file_path)
        }
        ExprKind::Binary { left, right, .. }
        | ExprKind::Assign {
            target: left,
            value: right,
            ..
        }
        | ExprKind::Index {
            base: left,
            index: right,
        } => {
            validate_named_struct_offsetof_calls(left, named_struct_fields, diagnostics, file_path);
            validate_named_struct_offsetof_calls(
                right,
                named_struct_fields,
                diagnostics,
                file_path,
            );
        }
        ExprKind::FieldAccess { base, .. } | ExprKind::DerefAccess { base } => {
            validate_named_struct_offsetof_calls(base, named_struct_fields, diagnostics, file_path);
        }
        ExprKind::Slice(slice) => {
            validate_named_struct_offsetof_calls(
                &slice.base,
                named_struct_fields,
                diagnostics,
                file_path,
            );
            if let Some(start) = &slice.start {
                validate_named_struct_offsetof_calls(
                    start,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
            }
            if let Some(end) = &slice.end {
                validate_named_struct_offsetof_calls(
                    end,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
            }
        }
        ExprKind::If(if_expr) => {
            validate_named_struct_offsetof_calls(
                &if_expr.condition,
                named_struct_fields,
                diagnostics,
                file_path,
            );
            validate_named_struct_offsetof_calls(
                &if_expr.then_branch,
                named_struct_fields,
                diagnostics,
                file_path,
            );
            if let Some(else_expr) = &if_expr.else_branch {
                validate_named_struct_offsetof_calls(
                    else_expr,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
            }
        }
        ExprKind::Match(match_expr) => {
            validate_named_struct_offsetof_calls(
                &match_expr.scrutinee,
                named_struct_fields,
                diagnostics,
                file_path,
            );
            for arm in &match_expr.arms {
                if let Some(guard) = &arm.guard {
                    validate_named_struct_offsetof_calls(
                        guard,
                        named_struct_fields,
                        diagnostics,
                        file_path,
                    );
                }
                validate_named_struct_offsetof_calls(
                    &arm.value,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
            }
        }
        ExprKind::For(for_expr) => match for_expr {
            crate::compiler::ast::ForExpr::Range {
                start, end, body, ..
            } => {
                validate_named_struct_offsetof_calls(
                    start,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
                validate_named_struct_offsetof_calls(
                    end,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
                validate_named_struct_offsetof_calls(
                    body,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
            }
            crate::compiler::ast::ForExpr::Iterate { iterable, body, .. } => {
                validate_named_struct_offsetof_calls(
                    iterable,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
                validate_named_struct_offsetof_calls(
                    body,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
            }
            crate::compiler::ast::ForExpr::WhileLike { condition, body } => {
                validate_named_struct_offsetof_calls(
                    condition,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
                validate_named_struct_offsetof_calls(
                    body,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
            }
            crate::compiler::ast::ForExpr::Infinite { body } => {
                validate_named_struct_offsetof_calls(
                    body,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
            }
        },
        ExprKind::Break(break_expr) => {
            if let Some(value) = &break_expr.value {
                validate_named_struct_offsetof_calls(
                    value,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
            }
        }
        ExprKind::Return { value } => {
            if let Some(value) = value {
                validate_named_struct_offsetof_calls(
                    value,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
            }
        }
        ExprKind::Defer(defer_expr) => validate_named_struct_offsetof_calls(
            &defer_expr.body,
            named_struct_fields,
            diagnostics,
            file_path,
        ),
        ExprKind::OrElse(or_else) => {
            validate_named_struct_offsetof_calls(
                &or_else.value,
                named_struct_fields,
                diagnostics,
                file_path,
            );
            validate_named_struct_offsetof_calls(
                &or_else.fallback,
                named_struct_fields,
                diagnostics,
                file_path,
            );
        }
        ExprKind::StructLiteral(lit) => {
            for field in &lit.fields {
                validate_named_struct_offsetof_calls(
                    &field.value,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
            }
        }
        ExprKind::TypeConstruct { ty_expr, fields } => {
            validate_named_struct_offsetof_calls(
                ty_expr,
                named_struct_fields,
                diagnostics,
                file_path,
            );
            for field in fields {
                validate_named_struct_offsetof_calls(
                    &field.value,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
            }
        }
        ExprKind::ArrayLiteral(elements) => {
            for element in elements {
                validate_named_struct_offsetof_calls(
                    element,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
            }
        }
        ExprKind::TupleLiteral(elements) => {
            for element in elements {
                validate_named_struct_offsetof_calls(
                    element,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
            }
        }
        ExprKind::EnumVariantConstruct(variant) => {
            for payload in &variant.payload {
                validate_named_struct_offsetof_calls(
                    payload,
                    named_struct_fields,
                    diagnostics,
                    file_path,
                );
            }
        }
        ExprKind::Fn(fn_expr) => match &fn_expr.body {
            FnBody::Block(block) => validate_named_struct_offsetof_calls(
                &Expr {
                    kind: ExprKind::Block(block.clone()),
                    span: expr.span,
                },
                named_struct_fields,
                diagnostics,
                file_path,
            ),
            FnBody::ArrowExpr(body) => validate_named_struct_offsetof_calls(
                body,
                named_struct_fields,
                diagnostics,
                file_path,
            ),
        },
        ExprKind::Literal(_)
        | ExprKind::Ident(_)
        | ExprKind::BuiltinIdent(_)
        | ExprKind::Continue { .. }
        | ExprKind::Use { .. }
        | ExprKind::TypeLiteral(_) => {}
    }
}

fn report_called_value_not_function(
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
    span: SourceSpan,
) {
    diagnostics.push(
        Diagnostic::error(
            DiagnosticPhase::TypeChecker,
            DiagnosticCode::E4005,
            "called value is not a function",
        )
        .with_primary_file_label(
            file_path.to_path_buf(),
            Some(span),
            "call target must be a function or function value",
        ),
    );
}

fn report_call_arg_must_be_type_designator(
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
    span: SourceSpan,
) {
    diagnostics.push(
        Diagnostic::error(
            DiagnosticPhase::TypeChecker,
            DiagnosticCode::E4005,
            "call argument must be a type designator",
        )
        .with_primary_file_label(
            file_path.to_path_buf(),
            Some(span),
            "pass a type name or type literal",
        ),
    );
}

fn report_call_arg_type_mismatch(
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
    span: SourceSpan,
) {
    diagnostics.push(
        Diagnostic::error(
            DiagnosticPhase::TypeChecker,
            DiagnosticCode::E4005,
            "call argument type mismatch",
        )
        .with_primary_file_label(
            file_path.to_path_buf(),
            Some(span),
            "argument type does not match parameter type",
        ),
    );
}

#[allow(clippy::too_many_arguments)]
fn validate_direct_call_arg(
    arg: &crate::compiler::ast::CallArg,
    expected_ty: TypeId,
    param_name: Option<&String>,
    env: &BTreeMap<String, TypeId>,
    mutability: &BTreeMap<String, bool>,
    signatures: &BTreeMap<String, FnSignature>,
    types: &mut TypeStore,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
    expected_return: Option<TypeId>,
    type_param_bindings: &mut BTreeMap<String, TypeId>,
) {
    let resolved_expected = match types.get(expected_ty) {
        Type::TypeParam(name) => type_param_bindings
            .get(name)
            .copied()
            .unwrap_or(expected_ty),
        _ => expected_ty,
    };

    if matches!(types.get(expected_ty), Type::TypeType) && !is_type_designator_expr(&arg.value) {
        report_call_arg_must_be_type_designator(diagnostics, file_path, arg.value.span);
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
    actual_ty = maybe_coerce_literal_to_expected(&arg.value, actual_ty, resolved_expected, types);

    if let Some(param_name) = param_name {
        if matches!(types.get(expected_ty), Type::TypeType) {
            if let Some(designated) = resolve_type_designator_arg(&arg.value, types) {
                if let Some(bound) = type_param_bindings.get(param_name).copied() {
                    if bound != designated {
                        report_call_arg_type_mismatch(diagnostics, file_path, arg.value.span);
                    }
                } else {
                    type_param_bindings.insert(param_name.clone(), designated);
                }
            }
        }
    }

    if let Type::TypeParam(name) = types.get(expected_ty) {
        if let Some(bound) = type_param_bindings.get(name).copied() {
            if !types_compatible(bound, actual_ty, types) {
                report_call_arg_type_mismatch(diagnostics, file_path, arg.value.span);
            }
        } else {
            type_param_bindings.insert(name.clone(), actual_ty);
        }
    }

    if !types_compatible(resolved_expected, actual_ty, types) {
        report_call_arg_type_mismatch(diagnostics, file_path, arg.value.span);
    }
}

fn param_is_generic_type_var(param_ty: Option<&TypeId>, types: &TypeStore) -> bool {
    param_ty
        .map(|pt| {
            matches!(
                types.get(*pt),
                Type::TypeParam(_) | Type::Unknown | Type::Any
            )
        })
        .unwrap_or(false)
}

fn equality_kind_name(kind: EqualityValueKind) -> &'static str {
    match kind {
        EqualityValueKind::Scalar => "scalar",
        EqualityValueKind::Pointer => "pointer",
        EqualityValueKind::PlainEnum => "plain enum",
        EqualityValueKind::PayloadEnum => "payload enum",
        EqualityValueKind::Struct => "struct",
        EqualityValueKind::Array => "array",
        EqualityValueKind::Slice => "slice",
        EqualityValueKind::Tuple => "tuple",
        EqualityValueKind::Unknown => "value",
    }
}

fn unsupported_equality_kind(
    left: EqualityValueKind,
    right: EqualityValueKind,
) -> Option<EqualityValueKind> {
    [left, right].into_iter().find(|kind| {
        matches!(
            kind,
            EqualityValueKind::Struct
                | EqualityValueKind::PayloadEnum
                | EqualityValueKind::Array
                | EqualityValueKind::Slice
                | EqualityValueKind::Tuple
        )
    })
}

fn report_named_arg_order_error(
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
    span: SourceSpan,
) {
    diagnostics.push(
        Diagnostic::error(
            DiagnosticPhase::TypeChecker,
            DiagnosticCode::E4005,
            "positional arguments cannot follow named arguments",
        )
        .with_primary_file_label(
            file_path.to_path_buf(),
            Some(span),
            "move positional arguments before the first named argument",
        ),
    );
}

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
    let mut named_seen = false;
    let mut positional_cursor = 0usize;
    for arg in &call.args {
        if let Some(name) = &arg.name {
            named_seen = true;
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
            continue;
        }

        if named_seen {
            report_named_arg_order_error(diagnostics, file_path, arg.value.span);
            continue;
        }

        while positional_cursor < ordered_args.len() && ordered_args[positional_cursor].is_some() {
            positional_cursor += 1;
        }
        if positional_cursor < ordered_args.len() {
            ordered_args[positional_cursor] = Some(arg);
            positional_cursor += 1;
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
            report_called_value_not_function(diagnostics, file_path, call.callee.span);
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

    let Some(sig) = signatures.get(&callee_name) else {
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
            report_called_value_not_function(diagnostics, file_path, call.callee.span);
        }
        return types.intern(Type::Unknown);
    };

    let mut named_seen = BTreeSet::<String>::new();
    let mut saw_named_arg = false;
    let mut positional_count = 0usize;
    let mut used_params = BTreeSet::<usize>::new();
    let mut specialized_return = None;
    let mut type_param_bindings = BTreeMap::<String, TypeId>::new();

    let direct_param_types = env
        .get(&callee_name)
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
            saw_named_arg = true;
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
                    validate_direct_call_arg(
                        arg,
                        *expected_ty,
                        sig.params[param_index].name.as_ref(),
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                        &mut type_param_bindings,
                    );
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
            let param_is_generic_type_var = param_is_generic_type_var(
                direct_param_types
                    .as_ref()
                    .and_then(|pts| pts.get(param_index)),
                types,
            );
            if sig.params[param_index].comp
                && !param_is_generic_type_var
                && !is_compile_time_expr(&arg.value)
            {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        format!(
                            "argument '{}' is a 'comp' parameter and requires a compile-time-known value",
                            name.text
                        ),
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(arg.value.span),
                        "wrap in 'comp' or use a literal value",
                    ),
                );
            }
            used_params.insert(param_index);
            if return_from_type_param_idx == Some(param_index) {
                specialized_return =
                    resolve_type_designator_arg(&arg.value, types).or(specialized_return);
            }
        } else {
            if saw_named_arg {
                report_named_arg_order_error(diagnostics, file_path, arg.value.span);
                continue;
            }
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
                    validate_direct_call_arg(
                        arg,
                        *expected_ty,
                        sig.params[positional_count].name.as_ref(),
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                        &mut type_param_bindings,
                    );
                }
            }

            let param_is_generic_type_var = param_is_generic_type_var(
                direct_param_types
                    .as_ref()
                    .and_then(|pts| pts.get(positional_count)),
                types,
            );
            if sig.params[positional_count].comp
                && !param_is_generic_type_var
                && !is_compile_time_expr(&arg.value)
            {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        format!(
                            "argument {} is a 'comp' parameter and requires a compile-time-known value",
                            positional_count + 1
                        ),
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(arg.value.span),
                        "wrap in 'comp' or use a literal value",
                    ),
                );
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
        PatternKind::Wildcard | PatternKind::Literal(_) | PatternKind::TypeLiteral(_) => {}
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
        "$self" => {
            if !call.args.is_empty() {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$self expects no arguments",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "use $self()",
                    ),
                );
            }
            if env.get("self").is_none() {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$self is only available in self method context",
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
        "$memcpy" | "$memset" => {
            if call.args.len() != 3 {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        if name == "$memcpy" {
                            "$memcpy expects 3 arguments: dst, src, len"
                        } else {
                            "$memset expects 3 arguments: dst, val, len"
                        },
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        if name == "$memcpy" {
                            "use $memcpy(dst, src, len)"
                        } else {
                            "use $memset(dst, val, len)"
                        },
                    ),
                );
            } else {
                for arg in &call.args {
                    infer_expr_type(
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
            }
            // Returns the destination pointer as a raw integer (cast as needed).
            return Some(types.intern(Type::Int {
                signed: false,
                bits: 64,
            }));
        }
        "$syscall" => {
            if call.args.is_empty() || call.args.len() > 7 {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$syscall expects 1 to 7 arguments (syscall number plus up to 6 args)",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "use $syscall(number, arg1, arg2, ...)",
                    ),
                );
            } else {
                for arg in &call.args {
                    infer_expr_type(
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
            }
            return Some(types.intern(Type::Int {
                signed: true,
                bits: 64,
            }));
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
        "$fields" => {
            if call.args.len() != 1 {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$fields expects one argument: a struct value or type",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "use $fields(v) inside an inline for loop",
                    ),
                );
            }
            // $fields is only valid as the iterable of an inline for; return Unknown so
            // it doesn't cause spurious type errors when used in that context.
            return Some(types.intern(Type::Unknown));
        }
        "$has_method" | "$has_field" => {
            if call.args.len() != 2 {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        format!(
                            "{} expects two arguments: type and member name string",
                            name
                        ),
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        if name == "$has_method" {
                            "use $has_method(Type, \"method_name\")"
                        } else {
                            "use $has_field(Type, \"field_name\")"
                        },
                    ),
                );
            }
            return Some(types.intern(Type::Bool));
        }
        "$typename" => {
            if call.args.len() != 1 {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$typename expects one type argument",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "use $typename(Type)",
                    ),
                );
            }
            return Some(bytes_type(types));
        }
        "$target" => {
            if !call.args.is_empty() {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$target expects no arguments",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "use $target()",
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
    // If this is an inline function, validate the body has no disallowed flow.
    if let ExprKind::Fn(fn_expr) = &expr.kind {
        if !inline_function_body_supported(&fn_expr.body) {
            diagnostics.push(
                Diagnostic::error(
                    DiagnosticPhase::TypeChecker,
                    DiagnosticCode::E4005,
                    "inline function body contains unsupported control flow",
                )
                .with_primary_file_label(
                    file_path.to_path_buf(),
                    Some(expr.span),
                    "inline functions cannot use 'break', 'continue', 'return', or 'defer'",
                ),
            );
        }
    }
    // If this is an inline for loop, it is already validated by the MIR unroller.
    // Other inline forms (calls) have no additional restrictions here.
}

fn inline_function_body_supported(body: &FnBody) -> bool {
    match body {
        FnBody::ArrowExpr(expr) => !contains_disallowed_inline_flow(expr),
        FnBody::Block(block) => {
            !block.statements.iter().any(|stmt| match stmt {
                Stmt::Binding(binding) => contains_disallowed_inline_flow(&binding.value),
                Stmt::Destructure(d) => contains_disallowed_inline_flow(&d.value),
                Stmt::Expr(expr) => contains_disallowed_inline_flow(expr),
            }) && block
                .tail_expr
                .as_ref()
                .map(|expr| !contains_disallowed_inline_flow(expr))
                .unwrap_or(true)
        }
    }
}

fn contains_disallowed_inline_flow(expr: &Expr) -> bool {
    match &expr.kind {
        ExprKind::Break(_)
        | ExprKind::Continue { .. }
        | ExprKind::Return { .. }
        | ExprKind::Defer(_) => true,
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
                Stmt::Destructure(d) => contains_disallowed_inline_flow(&d.value),
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
        ExprKind::TypeConstruct { ty_expr, fields } => {
            contains_disallowed_inline_flow(ty_expr)
                || fields
                    .iter()
                    .any(|field| contains_disallowed_inline_flow(&field.value))
        }
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

pub(super) fn strict_explicit_returns_enabled() -> bool {
    let env = std::env::var("DYN_STRICT_RETURNS").ok();
    let parse = |v: &str| matches!(v, "1" | "true" | "TRUE" | "on" | "ON");
    match env.as_deref() {
        Some("0") | Some("false") | Some("FALSE") | Some("off") | Some("OFF") => false,
        Some(v) => parse(v),
        None => true,
    }
}

pub(super) fn return_ok_type_is_i32(ty: TypeId, types: &TypeStore) -> bool {
    match types.get(ty) {
        Type::Int {
            signed: true,
            bits: 32,
        } => true,
        Type::Errorable { ok, .. } => return_ok_type_is_i32(*ok, types),
        _ => false,
    }
}

pub(super) fn should_allow_implicit_tail_for_main(
    _unit: &ModuleUnit,
    decl: &DeclStub,
    types: &mut TypeStore,
) -> bool {
    if decl.name != "main" {
        return false;
    }

    let Some(fn_expr) = extract_fn_expr(&decl.value) else {
        return false;
    };

    let Some(return_ty_expr) = fn_expr.return_type.as_ref() else {
        return true;
    };

    let Some(return_ty) = resolve_type_expr(return_ty_expr, types) else {
        return true;
    };

    !return_ok_type_is_i32(return_ty, types)
}

pub(super) fn is_strict_return_mode_tail_diagnostic_for_span(
    diagnostic: &Diagnostic,
    span: SourceSpan,
) -> bool {
    diagnostic.code == DiagnosticCode::E4005
        && diagnostic.message
            == "function must use explicit return statements in strict return mode"
        && diagnostic.labels.iter().any(|label| {
            label.is_primary
                && label.span.is_some_and(|label_span| {
                    label_span.start_byte == span.start_byte && label_span.end_byte == span.end_byte
                })
        })
}

pub(super) fn is_or_else_with_return_fallback(expr: &Expr) -> bool {
    match &expr.kind {
        ExprKind::OrElse(or_else) => matches!(or_else.fallback.kind, ExprKind::Return { .. }),
        _ => false,
    }
}

pub(super) fn valid_offsetof_designator(type_arg: &Expr, field_arg: &Expr) -> bool {
    if !matches!(
        field_arg.kind,
        ExprKind::Ident(_) | ExprKind::Literal(Literal::Integer(_))
    ) {
        return false;
    }

    let ExprKind::TypeLiteral(ty) = &type_arg.kind else {
        return true;
    };
    let TypeExprKind::Struct(struct_ty) = &ty.kind else {
        return true;
    };
    match &field_arg.kind {
        ExprKind::Ident(field) => struct_ty.fields.iter().any(|f| f.name.text == field.text),
        ExprKind::Literal(Literal::Integer(index)) => index
            .parse::<usize>()
            .map(|idx| idx < struct_ty.fields.len())
            .unwrap_or(false),
        _ => false,
    }
}

pub(super) fn pattern_compatibility_issue(
    pattern: &PatternKind,
    scrutinee: TypeId,
    types: &mut TypeStore,
) -> Option<String> {
    match pattern {
        PatternKind::Wildcard | PatternKind::IdentBind(_) | PatternKind::TypeLiteral(_) => None,
        PatternKind::Literal(lit) => {
            if literal_pattern_compatible(lit, scrutinee, types) {
                None
            } else {
                Some("literal pattern does not match scrutinee type".to_string())
            }
        }
        PatternKind::Range { start, end, .. } => {
            if !matches!(
                types.get(scrutinee),
                Type::Int { .. } | Type::Float { .. } | Type::Unknown
            ) {
                return Some("range patterns require numeric scrutinee type".to_string());
            }

            let start_lit = match &start.kind {
                PatternKind::Literal(lit) => lit,
                _ => return Some("range pattern start must be a literal".to_string()),
            };
            let end_lit = match &end.kind {
                PatternKind::Literal(lit) => lit,
                _ => return Some("range pattern end must be a literal".to_string()),
            };

            if !literal_pattern_compatible(start_lit, scrutinee, types)
                || !literal_pattern_compatible(end_lit, scrutinee, types)
            {
                return Some(
                    "range endpoint literal is incompatible with scrutinee type".to_string(),
                );
            }

            match (
                literal_numeric_class(start_lit),
                literal_numeric_class(end_lit),
            ) {
                (Some(start_class), Some(end_class)) if start_class == end_class => {
                    match types.get(scrutinee) {
                        Type::Int { .. } if start_class != NumericLiteralClass::Integer => Some(
                            "range endpoints must be integer literals for integer scrutinee"
                                .to_string(),
                        ),
                        Type::Float { .. } if start_class != NumericLiteralClass::Float => Some(
                            "range endpoints must be float literals for float scrutinee"
                                .to_string(),
                        ),
                        _ => None,
                    }
                }
                (Some(_), Some(_)) => {
                    Some("range endpoints must use the same numeric literal kind".to_string())
                }
                _ => Some("range endpoints must be numeric literals".to_string()),
            }
        }
        PatternKind::EnumVariant { .. } => match types.get(scrutinee) {
            Type::Unknown => None,
            _ => Some("enum pattern requires enum-typed scrutinee".to_string()),
        },
        PatternKind::Typed { pattern, ty } => {
            let typed_id = resolve_type_expr(ty, types)?;
            if !types_compatible(typed_id, scrutinee, types) {
                return Some(
                    "typed pattern annotation is incompatible with scrutinee type".to_string(),
                );
            }
            pattern_compatibility_issue(&pattern.kind, typed_id, types)
        }
    }
}

pub(super) fn enum_literal_pattern_issue(
    pattern: &PatternKind,
    scrutinee: &ExprKind,
) -> Option<String> {
    let ExprKind::EnumVariantConstruct(scrutinee_enum) = scrutinee else {
        return None;
    };

    match pattern {
        PatternKind::Wildcard | PatternKind::IdentBind(_) | PatternKind::TypeLiteral(_) => None,
        PatternKind::EnumVariant {
            root,
            variant,
            bindings,
        } => {
            if let Some(pattern_root) = root {
                match &scrutinee_enum.root {
                    Some(scrutinee_root) if scrutinee_root.text == pattern_root.text => {}
                    Some(_) => {
                        return Some(
                            "enum pattern root does not match scrutinee variant root".to_string(),
                        );
                    }
                    None => {
                        return Some(
                            "enum pattern root does not match rootless scrutinee variant"
                                .to_string(),
                        );
                    }
                }
            }

            if variant.text != scrutinee_enum.variant.text {
                return Some("enum pattern variant does not match scrutinee variant".to_string());
            }

            if bindings.len() != scrutinee_enum.payload.len() {
                return Some(
                    "enum pattern binding count does not match scrutinee payload arity".to_string(),
                );
            }

            None
        }
        PatternKind::Typed { pattern, .. } => enum_literal_pattern_issue(&pattern.kind, scrutinee),
        PatternKind::Literal(_) | PatternKind::Range { .. } => {
            Some("enum variant scrutinee requires enum/wildcard/binding pattern".to_string())
        }
    }
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(super) enum NumericLiteralClass {
    Integer,
    Float,
}

pub(super) fn literal_numeric_class(lit: &PatternLiteral) -> Option<NumericLiteralClass> {
    match lit {
        PatternLiteral::Integer(_) => Some(NumericLiteralClass::Integer),
        PatternLiteral::Float(_) => Some(NumericLiteralClass::Float),
        _ => None,
    }
}

pub(super) fn literal_pattern_compatible(
    lit: &PatternLiteral,
    scrutinee: TypeId,
    types: &TypeStore,
) -> bool {
    match lit {
        PatternLiteral::Integer(_) => matches!(
            types.get(scrutinee),
            Type::Int { .. } | Type::Float { .. } | Type::Unknown
        ),
        PatternLiteral::Float(_) => {
            matches!(types.get(scrutinee), Type::Float { .. } | Type::Unknown)
        }
        PatternLiteral::String(_) => {
            is_u8_slice_type(scrutinee, types) || matches!(types.get(scrutinee), Type::Unknown)
        }
        PatternLiteral::Char(_) => matches!(
            types.get(scrutinee),
            Type::Int {
                signed: false,
                bits: 8
            } | Type::Unknown
        ),
        PatternLiteral::Bool(_) => {
            matches!(types.get(scrutinee), Type::Bool | Type::Unknown)
        }
        PatternLiteral::Null => matches!(
            types.get(scrutinee),
            Type::Null | Type::Optional(_) | Type::Unknown
        ),
    }
}

pub(super) fn extract_callee_name(callee: &Expr) -> Option<String> {
    match &callee.kind {
        ExprKind::Ident(ident) | ExprKind::BuiltinIdent(ident) => Some(ident.text.clone()),
        _ => None,
    }
}

pub(super) fn unify_branch_types(
    left: TypeId,
    right: TypeId,
    types: &mut TypeStore,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
    expr: &Expr,
) -> TypeId {
    if left == right {
        return left;
    }

    match (types.get(left).clone(), types.get(right).clone()) {
        (Type::Optional(l_inner), Type::Optional(r_inner)) => {
            let inner = unify_branch_types(l_inner, r_inner, types, diagnostics, file_path, expr);
            types.intern(Type::Optional(inner))
        }
        (
            Type::Errorable {
                ok: l_inner,
                errors: l_errors,
            },
            Type::Errorable {
                ok: r_inner,
                errors: r_errors,
            },
        ) => {
            let inner = unify_branch_types(l_inner, r_inner, types, diagnostics, file_path, expr);
            let mut merged_errors = l_errors;
            merged_errors.extend(r_errors);
            types.intern(Type::Errorable {
                ok: inner,
                errors: merged_errors,
            })
        }
        (Type::Tuple(l_elems), Type::Tuple(r_elems)) if l_elems.len() == r_elems.len() => {
            let merged = l_elems
                .iter()
                .zip(r_elems.iter())
                .map(|(left_elem, right_elem)| {
                    unify_branch_types(*left_elem, *right_elem, types, diagnostics, file_path, expr)
                })
                .collect::<Vec<_>>();
            types.intern(Type::Tuple(merged))
        }
        (Type::Null, Type::Unknown) | (Type::Unknown, Type::Null) => types.intern(Type::Unknown),
        (Type::Null, Type::Optional(inner)) | (Type::Optional(inner), Type::Null) => {
            types.intern(Type::Optional(inner))
        }
        (Type::Null, other) => {
            let inner = types.intern(other);
            types.intern(Type::Optional(inner))
        }
        (other, Type::Null) => {
            let inner = types.intern(other);
            types.intern(Type::Optional(inner))
        }
        (Type::Unknown, _) => right,
        (_, Type::Unknown) => left,
        _ => {
            diagnostics.push(
                Diagnostic::error(
                    DiagnosticPhase::TypeChecker,
                    DiagnosticCode::E4005,
                    "branch type mismatch",
                )
                .with_primary_file_label(
                    file_path.to_path_buf(),
                    Some(expr.span),
                    "if/match branches must produce compatible types",
                ),
            );
            types.intern(Type::Unknown)
        }
    }
}

pub(super) fn resolve_type_expr(ty: &TypeExpr, types: &mut TypeStore) -> Option<TypeId> {
    match &ty.kind {
        TypeExprKind::Named(name) => {
            if name.text == "u1" {
                return Some(types.intern(Type::Bool));
            }
            if let Some(int_ty) = parse_int_type_name(&name.text) {
                return Some(types.intern(int_ty));
            }
            if let Some(float_ty) = parse_float_type_name(&name.text) {
                return Some(types.intern(float_ty));
            }
            if name.text == "type" {
                return Some(types.intern(Type::TypeType));
            }
            if name.text == "opaque" {
                return Some(types.intern(Type::Opaque));
            }
            if name.text == "any" {
                return Some(types.intern(Type::Any));
            }
            if name.text == "void" {
                return Some(types.intern(Type::Void));
            }
            if name
                .text
                .chars()
                .next()
                .map(|ch| ch.is_ascii_uppercase())
                .unwrap_or(false)
            {
                return Some(types.intern(Type::TypeParam(name.text.clone())));
            }
            Some(types.intern(Type::Unknown))
        }
        TypeExprKind::Applied { callee, args } => {
            let resolved_args = args
                .iter()
                .map(|arg| {
                    resolve_type_expr(arg, types).unwrap_or_else(|| types.intern(Type::Unknown))
                })
                .collect::<Vec<_>>();
            Some(types.intern(Type::Applied {
                callee: callee.text.clone(),
                args: resolved_args,
            }))
        }
        TypeExprKind::Optional { inner } => {
            let inner = resolve_type_expr(inner, types)?;
            Some(types.intern(Type::Optional(inner)))
        }
        TypeExprKind::Errorable { ok, errors } => {
            let ok = resolve_type_expr(ok, types)?;
            Some(
                types.intern(Type::Errorable {
                    ok,
                    errors: errors
                        .iter()
                        .map(|error| error.text.clone())
                        .collect::<BTreeSet<_>>(),
                }),
            )
        }
        TypeExprKind::Pointer { inner } => {
            let inner = resolve_type_expr(inner, types)?;
            Some(types.intern(Type::Pointer { inner }))
        }
        TypeExprKind::Array { element, .. } => {
            let elem = resolve_type_expr(element, types)?;
            Some(types.intern(Type::Array(elem)))
        }
        TypeExprKind::Slice { element } => {
            let elem = resolve_type_expr(element, types)?;
            Some(types.intern(Type::Slice { element: elem }))
        }
        TypeExprKind::Function(fn_ty) => {
            let param_types = fn_ty
                .params
                .iter()
                .map(|param| {
                    resolve_type_expr(&param.ty, types)
                        .unwrap_or_else(|| types.intern(Type::Unknown))
                })
                .collect::<Vec<_>>();
            let param_names = fn_ty
                .params
                .iter()
                .map(|param| param.name.as_ref().map(|name| name.text.clone()))
                .collect::<Vec<_>>();
            let has_defaults = vec![false; fn_ty.params.len()];
            let return_type = resolve_type_expr(&fn_ty.return_type, types)
                .unwrap_or_else(|| types.intern(Type::Unknown));
            Some(types.intern(Type::Function {
                param_types,
                param_names,
                has_defaults,
                return_type,
            }))
        }
        TypeExprKind::Struct(struct_ty) => {
            for field in &struct_ty.fields {
                let _ = resolve_type_expr(&field.ty, types);
            }
            Some(types.intern(Type::Unknown))
        }
        _ => Some(types.intern(Type::Unknown)),
    }
}

pub(super) fn is_numeric(ty: TypeId, types: &TypeStore) -> bool {
    matches!(types.get(ty), Type::Int { .. } | Type::Float { .. })
}

pub(super) fn validate_any_usage(
    ty: &TypeExpr,
    context: AnyUsageContext,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
) {
    match &ty.kind {
        TypeExprKind::Named(ident) if ident.text == "any" => {
            if !matches!(
                context,
                AnyUsageContext::FunctionParam | AnyUsageContext::PointerInner
            ) {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "'any' is only allowed as '*any' (erased pointer) or a function parameter type",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(ty.span),
                        "use '*any' for a type-erased pointer, or a concrete type here",
                    ),
                );
            }
        }
        TypeExprKind::Named(ident) if ident.text == "bytes" => {
            diagnostics.push(
                Diagnostic::error(
                    DiagnosticPhase::TypeChecker,
                    DiagnosticCode::E4005,
                    "'bytes' is not a language type; use []u8",
                )
                .with_primary_file_label(
                    file_path.to_path_buf(),
                    Some(ty.span),
                    "replace `bytes` with `[]u8`",
                ),
            );
        }
        TypeExprKind::Pointer { inner } => {
            validate_any_usage(inner, AnyUsageContext::PointerInner, diagnostics, file_path)
        }
        TypeExprKind::Optional { inner } => {
            validate_any_usage(inner, context, diagnostics, file_path)
        }
        TypeExprKind::Slice { element, .. } | TypeExprKind::Array { element, .. } => {
            validate_any_usage(element, context, diagnostics, file_path)
        }
        TypeExprKind::Errorable { ok, .. } => {
            validate_any_usage(ok, context, diagnostics, file_path)
        }
        TypeExprKind::Applied { args, .. } => {
            for arg in args {
                validate_any_usage(arg, context, diagnostics, file_path);
            }
        }
        TypeExprKind::Function(fn_ty) => {
            for param in &fn_ty.params {
                validate_any_usage(
                    &param.ty,
                    AnyUsageContext::FunctionParam,
                    diagnostics,
                    file_path,
                );
            }
            validate_any_usage(
                &fn_ty.return_type,
                AnyUsageContext::Other,
                diagnostics,
                file_path,
            );
        }
        TypeExprKind::Struct(struct_ty) => {
            for field in &struct_ty.fields {
                validate_any_usage(&field.ty, AnyUsageContext::Other, diagnostics, file_path);
            }
        }
        _ => {}
    }
}

pub(super) fn types_compatible(expected: TypeId, actual: TypeId, types: &TypeStore) -> bool {
    if expected == actual {
        return true;
    }

    match (types.get(expected), types.get(actual)) {
        (Type::Optional(_), Type::Null) => true,
        (Type::Optional(expected_inner), Type::Optional(actual_inner)) => {
            types_compatible(*expected_inner, *actual_inner, types)
        }
        (Type::Errorable { ok: inner, .. }, _) if *inner == actual => true,
        (
            Type::Errorable {
                ok: expected_inner,
                errors: expected_errors,
            },
            Type::Errorable {
                ok: actual_inner,
                errors: actual_errors,
            },
        ) => {
            types_compatible(*expected_inner, *actual_inner, types)
                && (expected_errors.is_empty() || actual_errors.is_subset(expected_errors))
        }
        (Type::Unknown, _) | (_, Type::Unknown) => true,
        (Type::TypeParam(_), _) | (_, Type::TypeParam(_)) => true,
        (Type::Any, _) => true,
        (
            Type::Int {
                bits: eb,
                signed: es,
            },
            Type::Int {
                bits: ab,
                signed: as_,
            },
        ) => {
            if es == as_ {
                eb >= ab
            } else if *es && !*as_ {
                eb > ab
            } else {
                false
            }
        }
        (
            Type::Int {
                signed: false,
                bits: 64,
            },
            Type::Any,
        ) => true,
        (Type::Float { bits: eb }, Type::Float { bits: ab }) => eb >= ab,
        (Type::Float { .. }, Type::Int { .. }) => true,
        (
            Type::Pointer {
                inner: expected_inner,
            },
            Type::Pointer {
                inner: actual_inner,
            },
        ) => {
            let expected_is_opaque = matches!(types.get(*expected_inner), Type::Opaque);
            expected_is_opaque || types_compatible(*expected_inner, *actual_inner, types)
        }
        (
            Type::Slice {
                element: expected_elem,
            },
            Type::Slice {
                element: actual_elem,
            },
        ) => types_compatible(*expected_elem, *actual_elem, types),
        (Type::Array(expected_elem), Type::Array(actual_elem)) => {
            types_compatible(*expected_elem, *actual_elem, types)
        }
        (Type::Slice { element, .. }, Type::Array(actual_elem)) => {
            types_compatible(*element, *actual_elem, types)
        }
        (Type::Tuple(expected_elements), Type::Tuple(actual_elements)) => {
            expected_elements.len() == actual_elements.len()
                && expected_elements
                    .iter()
                    .zip(actual_elements.iter())
                    .all(|(expected, actual)| types_compatible(*expected, *actual, types))
        }
        (
            Type::Applied {
                callee: expected_callee,
                args: expected_args,
            },
            Type::Applied {
                callee: actual_callee,
                args: actual_args,
            },
        ) => {
            expected_callee == actual_callee
                && expected_args.len() == actual_args.len()
                && expected_args
                    .iter()
                    .zip(actual_args.iter())
                    .all(|(e, a)| types_compatible(*e, *a, types))
        }
        (
            Type::Function {
                param_types: expected_params,
                return_type: expected_return,
                ..
            },
            Type::Function {
                param_types: actual_params,
                return_type: actual_return,
                ..
            },
        ) => {
            expected_params.len() == actual_params.len()
                && expected_params
                    .iter()
                    .zip(actual_params.iter())
                    .all(|(e, a)| types_compatible(*e, *a, types))
                && types_compatible(*expected_return, *actual_return, types)
        }
        (Type::Optional(inner), _) if *inner == actual => true,
        (Type::Optional(inner), _) => types_compatible(*inner, actual, types),
        _ => false,
    }
}

pub(super) fn is_u8_type(type_id: TypeId, types: &TypeStore) -> bool {
    matches!(
        types.get(type_id),
        Type::Int {
            signed: false,
            bits: 8,
        }
    )
}

pub(super) fn is_u8_slice_type(type_id: TypeId, types: &TypeStore) -> bool {
    matches!(types.get(type_id), Type::Slice { element, .. } if is_u8_type(*element, types))
}

pub(super) fn maybe_coerce_literal_to_expected(
    expr: &Expr,
    inferred: TypeId,
    expected: TypeId,
    types: &TypeStore,
) -> TypeId {
    match (&expr.kind, types.get(expected)) {
        (ExprKind::Literal(Literal::Integer(text)), Type::Int { signed, bits })
            if integer_literal_fits_type(text, *signed, *bits) =>
        {
            expected
        }
        (ExprKind::Literal(Literal::Float(text)), Type::Float { bits })
            if float_literal_fits_type(text, *bits) =>
        {
            expected
        }
        (ExprKind::ArrayLiteral(elements), Type::Array(expected_elem))
            if array_literal_elements_fit_type(elements, *expected_elem, types) =>
        {
            expected
        }
        (ExprKind::ArrayLiteral(elements), Type::Slice { element, .. })
            if array_literal_elements_fit_type(elements, *element, types) =>
        {
            expected
        }
        _ => inferred,
    }
}

pub(super) fn array_literal_elements_fit_type(
    elements: &[Expr],
    expected_elem: TypeId,
    types: &TypeStore,
) -> bool {
    elements
        .iter()
        .all(|element| match (&element.kind, types.get(expected_elem)) {
            (ExprKind::Literal(Literal::Integer(text)), Type::Int { signed, bits }) => {
                integer_literal_fits_type(text, *signed, *bits)
            }
            (ExprKind::Literal(Literal::Float(text)), Type::Float { bits }) => {
                float_literal_fits_type(text, *bits)
            }
            (ExprKind::Literal(Literal::String(_)), _) => is_u8_slice_type(expected_elem, types),
            (
                ExprKind::Literal(Literal::Char(_)),
                Type::Int {
                    signed: false,
                    bits: 8,
                },
            ) => true,
            (ExprKind::Literal(Literal::Bool(_)), Type::Bool) => true,
            (ExprKind::Literal(Literal::Null), Type::Optional(_)) => true,
            _ => false,
        })
}
