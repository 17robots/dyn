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
