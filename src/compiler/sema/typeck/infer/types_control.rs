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
    unit: &ModuleUnit,
    decl: &DeclStub,
    types: &mut TypeStore,
) -> bool {
    if unit.key.module_name != "main" || decl.name != "main" {
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
        PatternKind::Wildcard | PatternKind::IdentBind(_) => None,
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
        PatternKind::Wildcard | PatternKind::IdentBind(_) => None,
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
        TypeExprKind::Pointer { inner, mutable } => {
            let inner = resolve_type_expr(inner, types)?;
            Some(types.intern(Type::Pointer {
                inner,
                mutable: *mutable,
            }))
        }
        TypeExprKind::Array { element, .. } => {
            let elem = resolve_type_expr(element, types)?;
            Some(types.intern(Type::Array(elem)))
        }
        TypeExprKind::Slice { element, mutable } => {
            let elem = resolve_type_expr(element, types)?;
            Some(types.intern(Type::Slice {
                element: elem,
                mutable: *mutable,
            }))
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
            for member in &struct_ty.members {
                if let Some(fn_expr) = extract_fn_expr(&member.value) {
                    for param in &fn_expr.params {
                        if let Some(param_ty) = &param.ty {
                            let _ = resolve_type_expr(param_ty, types);
                        }
                    }
                    if let Some(ret) = &fn_expr.return_type {
                        let _ = resolve_type_expr(ret, types);
                    }
                }
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
        TypeExprKind::Pointer { mutable, inner } => {
            // *mut any is not valid — mutability belongs to the concrete type after casting
            if *mutable {
                if let TypeExprKind::Named(ident) = &inner.kind {
                    if ident.text == "any" {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "'*mut any' is not allowed; use '*any' and cast to a mutable concrete pointer",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(ty.span),
                                "remove 'mut' here",
                            ),
                        );
                        return;
                    }
                }
            }
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
                mutable: expected_mut,
            },
            Type::Pointer {
                inner: actual_inner,
                mutable: actual_mut,
            },
        ) => {
            let mutable_ok = !*expected_mut || *actual_mut;
            let expected_is_opaque = matches!(types.get(*expected_inner), Type::Opaque);
            mutable_ok
                && (expected_is_opaque || types_compatible(*expected_inner, *actual_inner, types))
        }
        (
            Type::Slice {
                element: expected_elem,
                mutable: expected_mut,
            },
            Type::Slice {
                element: actual_elem,
                mutable: actual_mut,
            },
        ) => {
            let mutable_ok = !*expected_mut || *actual_mut;
            mutable_ok && types_compatible(*expected_elem, *actual_elem, types)
        }
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
