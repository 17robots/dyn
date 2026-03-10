use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::PathBuf;

use crate::compiler::ast::{
    Expr, ExprKind, FnBody, Pattern, PatternKind, Stmt, TypeExpr, TypeExprKind,
};
use crate::compiler::diagnostic_utils::sort_diagnostics_by_primary_path;
use crate::compiler::diagnostics::{
    Diagnostic, DiagnosticCode, DiagnosticLabel, DiagnosticPhase, SourceSpan,
};
use crate::compiler::module_resolver::{ModuleId, ModuleKey};
use crate::compiler::sema::module_unit::ModuleUnit;

#[derive(Debug, Copy, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct DefId(pub usize);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SemanticSession {
    pub modules: Vec<ModuleSema>,
    pub diagnostics: Vec<Diagnostic>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ModuleSema {
    pub module_id: ModuleId,
    pub key: ModuleKey,
    pub declarations: Vec<ResolvedDecl>,
    pub imports: Vec<ResolvedImport>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResolvedDecl {
    pub def_id: DefId,
    pub name: String,
    pub file_path: PathBuf,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResolvedImport {
    pub alias_def: Option<DefId>,
    pub alias_name: String,
    pub target: Option<ModuleId>,
    pub path: String,
}

pub fn analyze_modules(units: &[ModuleUnit]) -> SemanticSession {
    let mut diagnostics = Vec::new();
    let module_index = units
        .iter()
        .map(|unit| (unit.key.clone(), unit.module_id))
        .collect::<BTreeMap<_, _>>();
    let module_by_id = units
        .iter()
        .map(|unit| (unit.module_id, unit))
        .collect::<BTreeMap<_, _>>();

    let mut next_def_id = 0usize;
    let mut modules = Vec::new();

    for unit in units {
        let mut seen = BTreeMap::<String, DefId>::new();
        let mut declared_spans = BTreeMap::<String, SourceSpan>::new();
        let mut declarations = Vec::new();
        let mut imports = Vec::new();
        let mut import_alias_spans = BTreeMap::<String, SourceSpan>::new();
        let mut type_names = BTreeSet::<String>::new();

        for decl in &unit.declarations {
            let def_id = DefId(next_def_id);
            next_def_id += 1;

            if seen.contains_key(&decl.name) {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::Semantic,
                        DiagnosticCode::E4002,
                        format!("duplicate declaration '{}'", decl.name),
                    )
                    .with_primary_file_label(
                        decl.file_path.clone(),
                        Some(decl.span),
                        "name already declared in this module",
                    ),
                );
            } else {
                seen.insert(decl.name.clone(), def_id);
                declared_spans.insert(decl.name.clone(), decl.span);
            }

            declarations.push(ResolvedDecl {
                def_id,
                name: decl.name.clone(),
                file_path: decl.file_path.clone(),
            });

            if let Some(annotation) = &decl.annotation {
                collect_type_names(annotation, &mut type_names);
            }
            if let ExprKind::Fn(fn_expr) = &decl.value.kind {
                for param in &fn_expr.params {
                    if let Some(ty) = &param.ty {
                        collect_type_names(ty, &mut type_names);
                    }
                }
                if let Some(ret) = &fn_expr.return_type {
                    collect_type_names(ret, &mut type_names);
                }
                if let FnBody::ArrowExpr(expr) = &fn_expr.body {
                    if let ExprKind::TypeLiteral(ty) = &expr.kind {
                        collect_type_names(ty, &mut type_names);
                    }
                }
            }
        }

        for import in &unit.imports {
            let target_key = import_path_to_module_key(&unit.key, &import.path);
            let target = module_index.get(&target_key).copied();
            if target.is_none() {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::Semantic,
                        DiagnosticCode::E4003,
                        format!("unresolved module import '{}'", import.path),
                    )
                    .with_primary_file_label(
                        import.file_path.clone(),
                        Some(import.span),
                        "import target module does not exist",
                    ),
                );
            }

            let alias_name = import.alias.clone().unwrap_or_else(|| "_".to_string());
            let alias_def = seen.get(&alias_name).copied();
            import_alias_spans
                .entry(alias_name.clone())
                .or_insert(import.span);
            imports.push(ResolvedImport {
                alias_def,
                alias_name,
                target,
                path: import.path.clone(),
            });
        }

        let import_aliases = imports
            .iter()
            .map(|import| (import.alias_name.clone(), import.target))
            .collect::<BTreeMap<_, _>>();

        for decl in &unit.declarations {
            let mut scopes = vec![BTreeMap::<String, SourceSpan>::new()];
            if let Some(scope) = scopes.last_mut() {
                for (name, span) in &declared_spans {
                    scope.insert(name.clone(), *span);
                }
                for (name, span) in &import_alias_spans {
                    scope.insert(name.clone(), *span);
                }
            }
            let mut out_of_scope = BTreeMap::<String, SourceSpan>::new();
            check_expr_resolution(
                &decl.value,
                &mut scopes,
                &mut out_of_scope,
                &seen,
                &import_aliases,
                &type_names,
                &module_by_id,
                &decl.file_path,
                &mut diagnostics,
            );
        }

        modules.push(ModuleSema {
            module_id: unit.module_id,
            key: unit.key.clone(),
            declarations,
            imports,
        });
    }

    sort_diagnostics_by_primary_path(&mut diagnostics);

    SemanticSession {
        modules,
        diagnostics,
    }
}

fn is_predeclared_name(name: &str) -> bool {
    matches!(
        name,
        "u1" | "u8"
            | "u16"
            | "u32"
            | "u64"
            | "i8"
            | "i16"
            | "i31"
            | "i32"
            | "i64"
            | "f32"
            | "f64"
            | "f128"
            | "type"
            | "any"
            | "opaque"
            | "void"
            | "usize"
            | "isize"
    )
}

fn looks_like_type_parameter(name: &str) -> bool {
    name.chars()
        .next()
        .map(|ch| ch.is_ascii_uppercase())
        .unwrap_or(false)
}

fn collect_type_names(ty: &TypeExpr, out: &mut BTreeSet<String>) {
    match &ty.kind {
        TypeExprKind::Named(ident) => {
            out.insert(ident.text.clone());
        }
        TypeExprKind::Applied { callee, args } => {
            out.insert(callee.text.clone());
            for arg in args {
                collect_type_names(arg, out);
            }
        }
        TypeExprKind::Pointer { inner, .. }
        | TypeExprKind::Optional { inner }
        | TypeExprKind::Errorable { ok: inner, .. } => collect_type_names(inner, out),
        TypeExprKind::Array { element, .. } | TypeExprKind::Slice { element, .. } => {
            collect_type_names(element, out)
        }
        TypeExprKind::Function(fn_type) => {
            for param in &fn_type.params {
                collect_type_names(&param.ty, out);
            }
            collect_type_names(&fn_type.return_type, out);
        }
        TypeExprKind::Struct(struct_ty) => {
            for field in &struct_ty.fields {
                collect_type_names(&field.ty, out);
            }
            for member in &struct_ty.members {
                if let ExprKind::Fn(fn_expr) = &member.value.kind {
                    for param in &fn_expr.params {
                        if let Some(param_ty) = &param.ty {
                            collect_type_names(param_ty, out);
                        }
                    }
                    if let Some(return_ty) = &fn_expr.return_type {
                        collect_type_names(return_ty, out);
                    }
                }
            }
        }
        TypeExprKind::Enum(enum_ty) => {
            for variant in &enum_ty.variants {
                if let Some(payload) = &variant.payload {
                    collect_type_names(payload, out);
                }
            }
        }
    }
}

fn pop_scope(
    scopes: &mut Vec<BTreeMap<String, SourceSpan>>,
    out_of_scope: &mut BTreeMap<String, SourceSpan>,
) {
    if let Some(scope) = scopes.pop() {
        for (name, span) in scope {
            if !scopes.iter().rev().any(|active| active.contains_key(&name)) {
                out_of_scope.insert(name, span);
            }
        }
    }
}

fn bind_name(scopes: &mut [BTreeMap<String, SourceSpan>], name: &str, span: SourceSpan) {
    if let Some(scope) = scopes.last_mut() {
        scope.insert(name.to_string(), span);
    }
}

#[allow(clippy::too_many_arguments)]
fn check_expr_resolution(
    expr: &Expr,
    scopes: &mut Vec<BTreeMap<String, SourceSpan>>,
    out_of_scope: &mut BTreeMap<String, SourceSpan>,
    module_defs: &BTreeMap<String, DefId>,
    import_aliases: &BTreeMap<String, Option<ModuleId>>,
    type_names: &BTreeSet<String>,
    module_by_id: &BTreeMap<ModuleId, &ModuleUnit>,
    file_path: &PathBuf,
    diagnostics: &mut Vec<Diagnostic>,
) {
    match &expr.kind {
        ExprKind::Ident(ident) => {
            let known = scopes
                .iter()
                .rev()
                .any(|scope| scope.contains_key(&ident.text))
                || module_defs.contains_key(&ident.text)
                || import_aliases.contains_key(&ident.text)
                || type_names.contains(&ident.text)
                || is_predeclared_name(&ident.text)
                || looks_like_type_parameter(&ident.text);

            if !known {
                if let Some(declared_span) = out_of_scope.get(&ident.text) {
                    let mut diagnostic = Diagnostic::error(
                        DiagnosticPhase::Semantic,
                        DiagnosticCode::E4001,
                        format!("name '{}' is out of scope", ident.text),
                    )
                    .with_primary_file_label(
                        file_path.clone(),
                        Some(expr.span),
                        "name was declared in an inner scope and is not visible here",
                    );
                    diagnostic.labels.push(DiagnosticLabel {
                        file_path: file_path.clone(),
                        span: Some(*declared_span),
                        message: "declared here".to_string(),
                        is_primary: false,
                    });
                    diagnostics.push(diagnostic);
                } else {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::Semantic,
                            DiagnosticCode::E4001,
                            format!("cannot resolve name '{}'", ident.text),
                        )
                        .with_primary_file_label(
                            file_path.clone(),
                            Some(expr.span),
                            "declare it before use or check for a typo",
                        ),
                    );
                }
            }
        }
        ExprKind::FieldAccess { base, field } => {
            if let ExprKind::Ident(base_ident) = &base.kind {
                if let Some(Some(target_module_id)) = import_aliases.get(&base_ident.text) {
                    if let Some(target_unit) = module_by_id.get(target_module_id) {
                        if let Some(target_decl) = target_unit
                            .declarations
                            .iter()
                            .find(|decl| decl.name == field.text)
                        {
                            if target_decl.visibility != crate::compiler::ast::Visibility::Public {
                                diagnostics.push(
                                    Diagnostic::error(
                                        DiagnosticPhase::Semantic,
                                        DiagnosticCode::E4004,
                                        format!(
                                            "member '{}' is private in module '{}'",
                                            field.text, target_unit.key.module_name
                                        ),
                                    )
                                    .with_primary_file_label(
                                        file_path.clone(),
                                        Some(expr.span),
                                        "cannot access private member from another module",
                                    ),
                                );
                            }
                        } else {
                            diagnostics.push(
                                Diagnostic::error(
                                    DiagnosticPhase::Semantic,
                                    DiagnosticCode::E4001,
                                    format!(
                                        "module '{}' has no member '{}'",
                                        target_unit.key.module_name, field.text
                                    ),
                                )
                                .with_primary_file_label(
                                    file_path.clone(),
                                    Some(expr.span),
                                    "member does not exist on imported module",
                                ),
                            );
                        }
                    }
                }
            }
            check_expr_resolution(
                base,
                scopes,
                out_of_scope,
                module_defs,
                import_aliases,
                type_names,
                module_by_id,
                file_path,
                diagnostics,
            );
        }
        ExprKind::Block(block) => {
            scopes.push(BTreeMap::new());
            for stmt in &block.statements {
                match stmt {
                    Stmt::Binding(binding) => {
                        check_expr_resolution(
                            &binding.value,
                            scopes,
                            out_of_scope,
                            module_defs,
                            import_aliases,
                            type_names,
                            module_by_id,
                            file_path,
                            diagnostics,
                        );
                        bind_name(scopes, &binding.name.text, binding.name.span);
                    }
                    Stmt::Expr(stmt_expr) => check_expr_resolution(
                        stmt_expr,
                        scopes,
                        out_of_scope,
                        module_defs,
                        import_aliases,
                        type_names,
                        module_by_id,
                        file_path,
                        diagnostics,
                    ),
                }
            }
            if let Some(tail) = &block.tail_expr {
                check_expr_resolution(
                    tail,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
            }
            pop_scope(scopes, out_of_scope);
        }
        ExprKind::Fn(fn_expr) => {
            scopes.push(BTreeMap::new());
            for param in &fn_expr.params {
                bind_name(scopes, &param.name.text, param.name.span);
            }
            match &fn_expr.body {
                FnBody::Block(block) => {
                    check_expr_resolution(
                        &Expr {
                            kind: ExprKind::Block(block.clone()),
                            span: expr.span,
                        },
                        scopes,
                        out_of_scope,
                        module_defs,
                        import_aliases,
                        type_names,
                        module_by_id,
                        file_path,
                        diagnostics,
                    );
                }
                FnBody::ArrowExpr(arrow) => check_expr_resolution(
                    arrow,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                ),
            }
            pop_scope(scopes, out_of_scope);
        }
        ExprKind::For(for_expr) => match for_expr {
            crate::compiler::ast::ForExpr::Range {
                start,
                end,
                binding,
                body,
                ..
            } => {
                check_expr_resolution(
                    start,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
                check_expr_resolution(
                    end,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
                scopes.push(BTreeMap::new());
                if let Some(binding) = binding {
                    bind_name(scopes, &binding.text, binding.span);
                }
                check_expr_resolution(
                    body,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
                pop_scope(scopes, out_of_scope);
            }
            crate::compiler::ast::ForExpr::Iterate {
                iterable,
                binding,
                body,
                ..
            } => {
                check_expr_resolution(
                    iterable,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
                scopes.push(BTreeMap::new());
                if let Some(binding) = binding {
                    bind_name(scopes, &binding.text, binding.span);
                }
                check_expr_resolution(
                    body,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
                pop_scope(scopes, out_of_scope);
            }
            crate::compiler::ast::ForExpr::WhileLike { condition, body } => {
                check_expr_resolution(
                    condition,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
                check_expr_resolution(
                    body,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
            }
            crate::compiler::ast::ForExpr::Infinite { body } => check_expr_resolution(
                body,
                scopes,
                out_of_scope,
                module_defs,
                import_aliases,
                type_names,
                module_by_id,
                file_path,
                diagnostics,
            ),
        },
        ExprKind::Match(match_expr) => {
            check_expr_resolution(
                &match_expr.scrutinee,
                scopes,
                out_of_scope,
                module_defs,
                import_aliases,
                type_names,
                module_by_id,
                file_path,
                diagnostics,
            );
            for arm in &match_expr.arms {
                scopes.push(BTreeMap::new());
                collect_pattern_bindings_checked(
                    &arm.pattern,
                    scopes.last_mut().expect("scope exists"),
                    file_path,
                    diagnostics,
                );
                if let Some(guard) = &arm.guard {
                    check_expr_resolution(
                        guard,
                        scopes,
                        out_of_scope,
                        module_defs,
                        import_aliases,
                        type_names,
                        module_by_id,
                        file_path,
                        diagnostics,
                    );
                }
                check_expr_resolution(
                    &arm.value,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
                pop_scope(scopes, out_of_scope);
            }
        }
        ExprKind::Unary { expr, .. }
        | ExprKind::OptionalUnwrap { expr }
        | ExprKind::ErrorUnwrap { expr }
        | ExprKind::Comptime { expr }
        | ExprKind::Inline { expr }
        | ExprKind::DerefAccess { base: expr } => check_expr_resolution(
            expr,
            scopes,
            out_of_scope,
            module_defs,
            import_aliases,
            type_names,
            module_by_id,
            file_path,
            diagnostics,
        ),
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
            check_expr_resolution(
                left,
                scopes,
                out_of_scope,
                module_defs,
                import_aliases,
                type_names,
                module_by_id,
                file_path,
                diagnostics,
            );
            check_expr_resolution(
                right,
                scopes,
                out_of_scope,
                module_defs,
                import_aliases,
                type_names,
                module_by_id,
                file_path,
                diagnostics,
            );
        }
        ExprKind::Call(call) => {
            check_expr_resolution(
                &call.callee,
                scopes,
                out_of_scope,
                module_defs,
                import_aliases,
                type_names,
                module_by_id,
                file_path,
                diagnostics,
            );
            let skip_offsetof_field_designator = matches!(
                &call.callee.kind,
                ExprKind::BuiltinIdent(ident) if ident.text == "$offsetof"
            );
            for (index, arg) in call.args.iter().enumerate() {
                if skip_offsetof_field_designator
                    && index == 1
                    && matches!(arg.value.kind, ExprKind::Ident(_))
                {
                    continue;
                }
                check_expr_resolution(
                    &arg.value,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::Slice(slice) => {
            check_expr_resolution(
                &slice.base,
                scopes,
                out_of_scope,
                module_defs,
                import_aliases,
                type_names,
                module_by_id,
                file_path,
                diagnostics,
            );
            if let Some(start) = &slice.start {
                check_expr_resolution(
                    start,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
            }
            if let Some(end) = &slice.end {
                check_expr_resolution(
                    end,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::If(if_expr) => {
            check_expr_resolution(
                &if_expr.condition,
                scopes,
                out_of_scope,
                module_defs,
                import_aliases,
                type_names,
                module_by_id,
                file_path,
                diagnostics,
            );
            if let Some(capture) = &if_expr.capture {
                scopes.push(BTreeMap::new());
                if let Some(binding) = &capture.binding {
                    bind_name(scopes, &binding.text, binding.span);
                }
                check_expr_resolution(
                    &if_expr.then_branch,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
                pop_scope(scopes, out_of_scope);
            } else {
                check_expr_resolution(
                    &if_expr.then_branch,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
            }
            if let Some(else_branch) = &if_expr.else_branch {
                check_expr_resolution(
                    else_branch,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::Break(break_expr) => {
            if let Some(value) = &break_expr.value {
                check_expr_resolution(
                    value,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::Return { value } => {
            if let Some(value) = value {
                check_expr_resolution(
                    value,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::Defer(defer_expr) => check_expr_resolution(
            &defer_expr.body,
            scopes,
            out_of_scope,
            module_defs,
            import_aliases,
            type_names,
            module_by_id,
            file_path,
            diagnostics,
        ),
        ExprKind::OrElse(or_else) => {
            check_expr_resolution(
                &or_else.value,
                scopes,
                out_of_scope,
                module_defs,
                import_aliases,
                type_names,
                module_by_id,
                file_path,
                diagnostics,
            );
            if let Some(binding) = &or_else.error_binding {
                scopes.push(BTreeMap::new());
                bind_name(scopes, &binding.text, binding.span);
                check_expr_resolution(
                    &or_else.fallback,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
                pop_scope(scopes, out_of_scope);
            } else {
                check_expr_resolution(
                    &or_else.fallback,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::StructLiteral(struct_lit) => {
            for field in &struct_lit.fields {
                check_expr_resolution(
                    &field.value,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::ArrayLiteral(elements) => {
            for element in elements {
                check_expr_resolution(
                    element,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::TupleLiteral(elements) => {
            for element in elements {
                check_expr_resolution(
                    element,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::EnumVariantConstruct(enum_variant) => {
            for payload in &enum_variant.payload {
                check_expr_resolution(
                    payload,
                    scopes,
                    out_of_scope,
                    module_defs,
                    import_aliases,
                    type_names,
                    module_by_id,
                    file_path,
                    diagnostics,
                );
            }
        }
        ExprKind::Use { .. }
        | ExprKind::TypeLiteral(_)
        | ExprKind::Literal(_)
        | ExprKind::BuiltinIdent(_)
        | ExprKind::Continue => {}
    }
}

fn collect_pattern_bindings_checked(
    pattern: &Pattern,
    out: &mut BTreeMap<String, SourceSpan>,
    file_path: &PathBuf,
    diagnostics: &mut Vec<Diagnostic>,
) {
    match &pattern.kind {
        PatternKind::IdentBind(ident) => {
            if out.insert(ident.text.clone(), ident.span).is_some() {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::Semantic,
                        DiagnosticCode::E4002,
                        format!("duplicate binding '{}' in match pattern", ident.text),
                    )
                    .with_primary_file_label(
                        file_path.clone(),
                        Some(ident.span),
                        "binding name appears more than once in this pattern",
                    ),
                );
            }
        }
        PatternKind::Range { start, end, .. } => {
            collect_pattern_bindings_checked(start, out, file_path, diagnostics);
            collect_pattern_bindings_checked(end, out, file_path, diagnostics);
        }
        PatternKind::EnumVariant { bindings, .. } => {
            for binding in bindings {
                if out.insert(binding.text.clone(), binding.span).is_some() {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::Semantic,
                            DiagnosticCode::E4002,
                            format!(
                                "duplicate binding '{}' in enum variant pattern",
                                binding.text
                            ),
                        )
                        .with_primary_file_label(
                            file_path.clone(),
                            Some(binding.span),
                            "binding name appears more than once in this pattern",
                        ),
                    );
                }
            }
        }
        PatternKind::Typed { pattern, .. } => {
            collect_pattern_bindings_checked(pattern, out, file_path, diagnostics)
        }
        PatternKind::Wildcard | PatternKind::Literal(_) => {}
    }
}

fn import_path_to_module_key(current: &ModuleKey, import_path: &str) -> ModuleKey {
    let normalized = import_path.trim_matches('"');
    let mut parts = normalized
        .split('/')
        .filter(|segment| !segment.is_empty())
        .collect::<Vec<_>>();

    if parts.is_empty() {
        return current.clone();
    }

    let module_name = parts.pop().unwrap_or_default().to_string();
    let is_std_absolute = normalized.starts_with("std/");
    let mut directory = if is_std_absolute || current.directory == std::path::Path::new(".") {
        PathBuf::new()
    } else {
        current.directory.clone()
    };
    for segment in parts {
        directory.push(segment);
    }
    if directory.as_os_str().is_empty() {
        directory = PathBuf::from(".");
    }

    ModuleKey {
        directory,
        module_name,
    }
}

#[cfg(test)]
mod tests;
