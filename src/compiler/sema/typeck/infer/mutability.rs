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

pub(super) fn infer_decl_nominal_type(
    decl: &crate::compiler::sema::module_unit::DeclStub,
    methods: &BTreeSet<(String, String)>,
) -> Option<String> {
    if let ExprKind::StructLiteral(lit) = &decl.value.kind {
        if let Some(root) = &lit.root_type {
            return Some(root.text.clone());
        }
    }
    let struct_names = methods
        .iter()
        .map(|(name, _)| name)
        .collect::<BTreeSet<_>>();
    match decl.annotation.as_ref().map(|ann| &ann.kind) {
        Some(TypeExprKind::Named(ident)) if struct_names.contains(&ident.text) => {
            Some(ident.text.clone())
        }
        _ => None,
    }
}

pub(super) fn validate_mut_pointer_receiver_calls(
    expr: &Expr,
    methods: &BTreeSet<(String, String)>,
    struct_fields: &BTreeMap<(String, String), String>,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
    initial_bindings: &BTreeMap<String, NominalBinding>,
) {
    let mut scopes = vec![initial_bindings.clone()];
    validate_mut_pointer_receiver_calls_expr(
        expr,
        methods,
        struct_fields,
        diagnostics,
        file_path,
        &mut scopes,
    );
}

pub(super) fn validate_mut_pointer_receiver_calls_expr(
    expr: &Expr,
    methods: &BTreeSet<(String, String)>,
    struct_fields: &BTreeMap<(String, String), String>,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
    scopes: &mut Vec<BTreeMap<String, NominalBinding>>,
) {
    match &expr.kind {
        ExprKind::Call(call) => {
            if let ExprKind::FieldAccess { base, field } = &call.callee.kind {
                if let Some(base_nominal) =
                    infer_nominal_type_from_expr(base, scopes, struct_fields)
                {
                    if methods.contains(&(base_nominal, field.text.clone()))
                        && !can_take_mut_ref_from_expr(base, scopes)
                    {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4006,
                                "cannot call mut receiver method on immutable value",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(expr.span),
                                "mark receiver binding as mut or use a mutable receiver value",
                            ),
                        );
                    }
                }
            }
            validate_mut_pointer_receiver_calls_expr(
                &call.callee,
                methods,
                struct_fields,
                diagnostics,
                file_path,
                scopes,
            );
            for arg in &call.args {
                validate_mut_pointer_receiver_calls_expr(
                    &arg.value,
                    methods,
                    struct_fields,
                    diagnostics,
                    file_path,
                    scopes,
                );
            }
        }
        ExprKind::Block(block) => {
            scopes.push(BTreeMap::new());
            for stmt in &block.statements {
                match stmt {
                    Stmt::Binding(binding) => {
                        validate_mut_pointer_receiver_calls_expr(
                            &binding.value,
                            methods,
                            struct_fields,
                            diagnostics,
                            file_path,
                            scopes,
                        );
                        if let Some(nominal) =
                            infer_nominal_type_from_expr(&binding.value, scopes, struct_fields)
                                .or_else(|| {
                                    binding
                                        .annotation
                                        .as_ref()
                                        .and_then(|ann| nominal_name_from_type_expr(ann, methods))
                                })
                        {
                            if let Some(scope) = scopes.last_mut() {
                                scope.insert(
                                    binding.name.text.clone(),
                                    NominalBinding {
                                        nominal_type: nominal,
                                        mutable: binding.mutable,
                                    },
                                );
                            }
                        }
                    }
                    Stmt::Expr(stmt_expr) => validate_mut_pointer_receiver_calls_expr(
                        stmt_expr,
                        methods,
                        struct_fields,
                        diagnostics,
                        file_path,
                        scopes,
                    ),
                }
            }
            if let Some(tail) = &block.tail_expr {
                validate_mut_pointer_receiver_calls_expr(
                    tail,
                    methods,
                    struct_fields,
                    diagnostics,
                    file_path,
                    scopes,
                );
            }
            scopes.pop();
        }
        ExprKind::Unary { expr, .. }
        | ExprKind::Comptime { expr }
        | ExprKind::Inline { expr }
        | ExprKind::OptionalUnwrap { expr }
        | ExprKind::ErrorUnwrap { expr } => validate_mut_pointer_receiver_calls_expr(
            expr,
            methods,
            struct_fields,
            diagnostics,
            file_path,
            scopes,
        ),
        ExprKind::Binary { left, right, .. } => {
            validate_mut_pointer_receiver_calls_expr(
                left,
                methods,
                struct_fields,
                diagnostics,
                file_path,
                scopes,
            );
            validate_mut_pointer_receiver_calls_expr(
                right,
                methods,
                struct_fields,
                diagnostics,
                file_path,
                scopes,
            );
        }
        ExprKind::Assign { target, value, .. } => {
            validate_mut_pointer_receiver_calls_expr(
                target,
                methods,
                struct_fields,
                diagnostics,
                file_path,
                scopes,
            );
            validate_mut_pointer_receiver_calls_expr(
                value,
                methods,
                struct_fields,
                diagnostics,
                file_path,
                scopes,
            );
        }
        ExprKind::FieldAccess { base, .. } | ExprKind::DerefAccess { base } => {
            validate_mut_pointer_receiver_calls_expr(
                base,
                methods,
                struct_fields,
                diagnostics,
                file_path,
                scopes,
            );
        }
        ExprKind::Index { base, index } => {
            validate_mut_pointer_receiver_calls_expr(
                base,
                methods,
                struct_fields,
                diagnostics,
                file_path,
                scopes,
            );
            validate_mut_pointer_receiver_calls_expr(
                index,
                methods,
                struct_fields,
                diagnostics,
                file_path,
                scopes,
            );
        }
        ExprKind::Slice(slice) => {
            validate_mut_pointer_receiver_calls_expr(
                &slice.base,
                methods,
                struct_fields,
                diagnostics,
                file_path,
                scopes,
            );
            if let Some(start) = &slice.start {
                validate_mut_pointer_receiver_calls_expr(
                    start,
                    methods,
                    struct_fields,
                    diagnostics,
                    file_path,
                    scopes,
                );
            }
            if let Some(end) = &slice.end {
                validate_mut_pointer_receiver_calls_expr(
                    end,
                    methods,
                    struct_fields,
                    diagnostics,
                    file_path,
                    scopes,
                );
            }
        }
        ExprKind::If(if_expr) => {
            validate_mut_pointer_receiver_calls_expr(
                &if_expr.condition,
                methods,
                struct_fields,
                diagnostics,
                file_path,
                scopes,
            );
            validate_mut_pointer_receiver_calls_expr(
                &if_expr.then_branch,
                methods,
                struct_fields,
                diagnostics,
                file_path,
                scopes,
            );
            if let Some(else_expr) = &if_expr.else_branch {
                validate_mut_pointer_receiver_calls_expr(
                    else_expr,
                    methods,
                    struct_fields,
                    diagnostics,
                    file_path,
                    scopes,
                );
            }
        }
        ExprKind::Match(match_expr) => {
            validate_mut_pointer_receiver_calls_expr(
                &match_expr.scrutinee,
                methods,
                struct_fields,
                diagnostics,
                file_path,
                scopes,
            );
            for arm in &match_expr.arms {
                if let Some(guard) = &arm.guard {
                    validate_mut_pointer_receiver_calls_expr(
                        guard,
                        methods,
                        struct_fields,
                        diagnostics,
                        file_path,
                        scopes,
                    );
                }
                validate_mut_pointer_receiver_calls_expr(
                    &arm.value,
                    methods,
                    struct_fields,
                    diagnostics,
                    file_path,
                    scopes,
                );
            }
        }
        ExprKind::For(for_expr) => match for_expr {
            crate::compiler::ast::ForExpr::Range {
                start, end, body, ..
            } => {
                validate_mut_pointer_receiver_calls_expr(
                    start,
                    methods,
                    struct_fields,
                    diagnostics,
                    file_path,
                    scopes,
                );
                validate_mut_pointer_receiver_calls_expr(
                    end,
                    methods,
                    struct_fields,
                    diagnostics,
                    file_path,
                    scopes,
                );
                validate_mut_pointer_receiver_calls_expr(
                    body,
                    methods,
                    struct_fields,
                    diagnostics,
                    file_path,
                    scopes,
                );
            }
            crate::compiler::ast::ForExpr::Iterate { iterable, body, .. } => {
                validate_mut_pointer_receiver_calls_expr(
                    iterable,
                    methods,
                    struct_fields,
                    diagnostics,
                    file_path,
                    scopes,
                );
                validate_mut_pointer_receiver_calls_expr(
                    body,
                    methods,
                    struct_fields,
                    diagnostics,
                    file_path,
                    scopes,
                );
            }
            crate::compiler::ast::ForExpr::WhileLike { condition, body } => {
                validate_mut_pointer_receiver_calls_expr(
                    condition,
                    methods,
                    struct_fields,
                    diagnostics,
                    file_path,
                    scopes,
                );
                validate_mut_pointer_receiver_calls_expr(
                    body,
                    methods,
                    struct_fields,
                    diagnostics,
                    file_path,
                    scopes,
                );
            }
            crate::compiler::ast::ForExpr::Infinite { body } => {
                validate_mut_pointer_receiver_calls_expr(
                    body,
                    methods,
                    struct_fields,
                    diagnostics,
                    file_path,
                    scopes,
                );
            }
        },
        ExprKind::Break(break_expr) => {
            if let Some(value) = &break_expr.value {
                validate_mut_pointer_receiver_calls_expr(
                    value,
                    methods,
                    struct_fields,
                    diagnostics,
                    file_path,
                    scopes,
                );
            }
        }
        ExprKind::Return { value } => {
            if let Some(value) = value {
                validate_mut_pointer_receiver_calls_expr(
                    value,
                    methods,
                    struct_fields,
                    diagnostics,
                    file_path,
                    scopes,
                );
            }
        }
        ExprKind::Defer(defer_expr) => validate_mut_pointer_receiver_calls_expr(
            &defer_expr.body,
            methods,
            struct_fields,
            diagnostics,
            file_path,
            scopes,
        ),
        ExprKind::OrElse(or_else) => {
            validate_mut_pointer_receiver_calls_expr(
                &or_else.value,
                methods,
                struct_fields,
                diagnostics,
                file_path,
                scopes,
            );
            validate_mut_pointer_receiver_calls_expr(
                &or_else.fallback,
                methods,
                struct_fields,
                diagnostics,
                file_path,
                scopes,
            );
        }
        ExprKind::StructLiteral(lit) => {
            for field in &lit.fields {
                validate_mut_pointer_receiver_calls_expr(
                    &field.value,
                    methods,
                    struct_fields,
                    diagnostics,
                    file_path,
                    scopes,
                );
            }
        }
        ExprKind::ArrayLiteral(elements) => {
            for element in elements {
                validate_mut_pointer_receiver_calls_expr(
                    element,
                    methods,
                    struct_fields,
                    diagnostics,
                    file_path,
                    scopes,
                );
            }
        }
        ExprKind::TupleLiteral(elements) => {
            for element in elements {
                validate_mut_pointer_receiver_calls_expr(
                    element,
                    methods,
                    struct_fields,
                    diagnostics,
                    file_path,
                    scopes,
                );
            }
        }
        ExprKind::EnumVariantConstruct(variant) => {
            for payload in &variant.payload {
                validate_mut_pointer_receiver_calls_expr(
                    payload,
                    methods,
                    struct_fields,
                    diagnostics,
                    file_path,
                    scopes,
                );
            }
        }
        ExprKind::Fn(fn_expr) => {
            scopes.push(BTreeMap::new());
            for param in &fn_expr.params {
                if let Some(ty) = &param.ty {
                    if let Some(nominal) = nominal_name_from_type_expr(ty, methods) {
                        if let Some(scope) = scopes.last_mut() {
                            scope.insert(
                                param.name.text.clone(),
                                NominalBinding {
                                    nominal_type: nominal,
                                    mutable: false,
                                },
                            );
                        }
                    }
                }
            }
            match &fn_expr.body {
                FnBody::Block(block) => {
                    validate_mut_pointer_receiver_calls_expr(
                        &Expr {
                            kind: ExprKind::Block(block.clone()),
                            span: expr.span,
                        },
                        methods,
                        struct_fields,
                        diagnostics,
                        file_path,
                        scopes,
                    );
                }
                FnBody::ArrowExpr(body) => {
                    validate_mut_pointer_receiver_calls_expr(
                        body,
                        methods,
                        struct_fields,
                        diagnostics,
                        file_path,
                        scopes,
                    );
                }
            }
            scopes.pop();
        }
        ExprKind::Literal(_)
        | ExprKind::Ident(_)
        | ExprKind::BuiltinIdent(_)
        | ExprKind::Continue { .. }
        | ExprKind::Use { .. }
        | ExprKind::TypeLiteral(_) => {}
    }
}

pub(super) fn nominal_name_from_type_expr(
    ty: &TypeExpr,
    methods: &BTreeSet<(String, String)>,
) -> Option<String> {
    let struct_names = methods
        .iter()
        .map(|(name, _)| name)
        .collect::<BTreeSet<_>>();
    match &ty.kind {
        TypeExprKind::Named(ident) if struct_names.contains(&ident.text) => {
            Some(ident.text.clone())
        }
        _ => None,
    }
}

pub(super) fn infer_nominal_type_from_expr(
    expr: &Expr,
    scopes: &[BTreeMap<String, NominalBinding>],
    struct_fields: &BTreeMap<(String, String), String>,
) -> Option<String> {
    match &expr.kind {
        ExprKind::StructLiteral(lit) => lit.root_type.as_ref().map(|ident| ident.text.clone()),
        ExprKind::Ident(ident) => scopes
            .iter()
            .rev()
            .find_map(|scope| scope.get(&ident.text).map(|info| info.nominal_type.clone())),
        ExprKind::FieldAccess { base, field } => {
            infer_nominal_type_from_expr(base, scopes, struct_fields).and_then(|base_nominal| {
                struct_fields
                    .get(&(base_nominal, field.text.clone()))
                    .cloned()
            })
        }
        ExprKind::DerefAccess { base } => infer_nominal_type_from_expr(base, scopes, struct_fields),
        _ => None,
    }
}

pub(super) fn can_take_mut_ref_from_expr(
    expr: &Expr,
    scopes: &[BTreeMap<String, NominalBinding>],
) -> bool {
    match &expr.kind {
        ExprKind::Ident(ident) => scopes
            .iter()
            .rev()
            .find_map(|scope| scope.get(&ident.text).map(|info| info.mutable))
            .unwrap_or(false),
        ExprKind::FieldAccess { base, .. }
        | ExprKind::DerefAccess { base }
        | ExprKind::Index { base, .. } => can_take_mut_ref_from_expr(base, scopes),
        _ => false,
    }
}
