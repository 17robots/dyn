pub(super) fn validate_struct_type_members(
    ty: &TypeExpr,
    struct_name: &str,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
) {
    let TypeExprKind::Struct(struct_ty) = &ty.kind else {
        return;
    };

    for member in &struct_ty.members {
        let Some(fn_expr) = extract_fn_expr(&member.value) else {
            continue;
        };
        if fn_expr.params.is_empty() {
            continue;
        }
        let Some(first_ty) = fn_expr.params[0].ty.as_ref() else {
            continue;
        };
        let is_method = matches_receiver_type(first_ty, struct_name);
        if is_method && fn_expr.params[0].name.text != "self" {
            diagnostics.push(
                Diagnostic::error(
                    DiagnosticPhase::TypeChecker,
                    DiagnosticCode::E4005,
                    format!(
                        "member function '{}' uses receiver type but first parameter is not named self",
                        member.name.text
                    ),
                )
                .with_primary_file_label(
                    file_path.to_path_buf(),
                    Some(member.value.span),
                    "rename first parameter to self for instance methods",
                ),
            );
        }
    }
}

pub(super) fn matches_receiver_type(param_ty: &TypeExpr, struct_name: &str) -> bool {
    matches!(&param_ty.kind, TypeExprKind::Named(ident) if ident.text == struct_name)
        || matches!(&param_ty.kind, TypeExprKind::Pointer { inner, .. }
            if matches!(inner.kind, TypeExprKind::Named(ref ident) if ident.text == struct_name))
}

pub(super) fn collect_mut_pointer_receiver_methods(
    unit: &ModuleUnit,
) -> BTreeSet<(String, String)> {
    let mut methods = BTreeSet::new();
    for decl in &unit.declarations {
        let ExprKind::TypeLiteral(type_lit) = &decl.value.kind else {
            continue;
        };
        let TypeExprKind::Struct(struct_ty) = &type_lit.kind else {
            continue;
        };
        for member in &struct_ty.members {
            let Some(fn_expr) = extract_fn_expr(&member.value) else {
                continue;
            };
            let Some(first) = fn_expr.params.first() else {
                continue;
            };
            let Some(first_ty) = &first.ty else {
                continue;
            };
            let TypeExprKind::Pointer {
                mutable: true,
                inner,
            } = &first_ty.kind
            else {
                continue;
            };
            if matches!(inner.kind, TypeExprKind::Named(ref ident) if ident.text == decl.name) {
                methods.insert((decl.name.clone(), member.name.text.clone()));
            }
        }
    }
    methods
}

pub(super) fn collect_struct_field_nominal_types(
    unit: &ModuleUnit,
) -> BTreeMap<(String, String), String> {
    let mut fields = BTreeMap::new();
    for decl in &unit.declarations {
        let ExprKind::TypeLiteral(type_lit) = &decl.value.kind else {
            continue;
        };
        let TypeExprKind::Struct(struct_ty) = &type_lit.kind else {
            continue;
        };
        for field in &struct_ty.fields {
            if let TypeExprKind::Named(named) = &field.ty.kind {
                fields.insert(
                    (decl.name.clone(), field.name.text.clone()),
                    named.text.clone(),
                );
            }
        }
    }
    fields
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
