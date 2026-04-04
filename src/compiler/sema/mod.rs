use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::fs;
use std::path::PathBuf;

use crate::compiler::ast::{
    AssignOp, BinaryOp, Binding, BlockExpr, EnumVariantExpr, Expr, ExprKind, FnBody, ForExpr, Item,
    Literal, MatchArm, Pattern, PatternKind, PatternLiteral, Stmt, TypeExpr, TypeExprKind, UnaryOp,
    Visibility,
};
use crate::compiler::diagnostics::{
    sort_diagnostics_by_primary_path, Diagnostic, DiagnosticCode, DiagnosticLabel, DiagnosticPhase,
    SourceSpan,
};
use crate::compiler::module_resolver::{resolve_graph_file_path, ModuleGraph, ModuleId, ModuleKey};
use crate::compiler::pipeline::ParseSession;

mod helpers;
mod infer;

use self::helpers::{
    bytes_type, float_literal_fits_type, integer_literal_fits_type, numeric_result_type,
    parse_float_type_name, parse_int_type_name, tuple_index_literal, type_to_string,
};
use self::infer::*;

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

        for extern_decl in &unit.extern_declarations {
            let def_id = DefId(next_def_id);
            next_def_id += 1;

            if seen.contains_key(&extern_decl.name) {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::Semantic,
                        DiagnosticCode::E4002,
                        format!("duplicate declaration '{}'", extern_decl.name),
                    )
                    .with_primary_file_label(
                        extern_decl.file_path.clone(),
                        Some(extern_decl.span),
                        "name already declared in this module",
                    ),
                );
            } else {
                seen.insert(extern_decl.name.clone(), def_id);
                declared_spans.insert(extern_decl.name.clone(), extern_decl.span);
            }

            declarations.push(ResolvedDecl {
                def_id,
                name: extern_decl.name.clone(),
                file_path: extern_decl.file_path.clone(),
            });

            collect_type_names(&extern_decl.ty, &mut type_names);
        }

        for import in &unit.imports {
            let target_key =
                crate::compiler::module_resolver::module_key_for_import(&unit.key, &import.path);
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
            | "type"
            | "any"
            | "opaque"
            | "void"
            | "usize"
            | "isize"
            | "_"
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
        }
        TypeExprKind::Enum(enum_ty) => {
            if let Some(repr) = &enum_ty.repr {
                collect_type_names(repr, out);
            }
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
                    Stmt::Destructure(d) => {
                        check_expr_resolution(
                            &d.value,
                            scopes,
                            out_of_scope,
                            module_defs,
                            import_aliases,
                            type_names,
                            module_by_id,
                            file_path,
                            diagnostics,
                        );
                        for dn in &d.names {
                            bind_name(scopes, &dn.name.text, dn.name.span);
                        }
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
                for binding_opt in &capture.bindings {
                    if let Some(binding) = binding_opt {
                        bind_name(scopes, &binding.text, binding.span);
                    }
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
        ExprKind::TypeConstruct { ty_expr, fields } => {
            check_expr_resolution(
                ty_expr,
                scopes,
                out_of_scope,
                module_defs,
                import_aliases,
                type_names,
                module_by_id,
                file_path,
                diagnostics,
            );
            for field in fields {
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
        | ExprKind::Continue { .. } => {}
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
        PatternKind::Wildcard | PatternKind::Literal(_) | PatternKind::TypeLiteral(_) => {}
    }
}
pub fn is_type_designator_expr(expr: &Expr) -> bool {
    match &expr.kind {
        ExprKind::TypeLiteral(_) => true,
        ExprKind::Ident(ident) | ExprKind::BuiltinIdent(ident) => {
            is_int_type_name(&ident.text)
                || is_float_type_name(&ident.text)
                || matches!(
                    ident.text.as_str(),
                    "u1" | "type" | "opaque" | "any" | "void"
                )
                || ident
                    .text
                    .chars()
                    .next()
                    .map(|ch| ch.is_ascii_uppercase())
                    .unwrap_or(false)
        }
        ExprKind::Call(call) => {
            matches!(
                call.callee.kind,
                ExprKind::Ident(_) | ExprKind::BuiltinIdent(_)
            ) && call
                .args
                .iter()
                .all(|arg| is_type_designator_expr(&arg.value))
        }
        _ => false,
    }
}

pub fn is_compile_time_expr(expr: &Expr) -> bool {
    let mut locals = BTreeSet::new();
    is_compile_time_expr_with_locals(expr, &mut locals)
}

fn is_compile_time_expr_with_locals(expr: &Expr, locals: &mut BTreeSet<String>) -> bool {
    match &expr.kind {
        ExprKind::Literal(_) | ExprKind::TypeLiteral(_) => true,
        ExprKind::Ident(ident) => locals.contains(&ident.text) || is_type_designator_expr(expr),
        ExprKind::BuiltinIdent(_) => is_type_designator_expr(expr),
        ExprKind::Unary { expr, .. } => is_compile_time_expr_with_locals(expr, locals),
        ExprKind::Binary { left, right, .. } => {
            is_compile_time_expr_with_locals(left, locals)
                && is_compile_time_expr_with_locals(right, locals)
        }
        ExprKind::Assign { target, value, .. } => {
            let ExprKind::Ident(ident) = &target.kind else {
                return false;
            };
            if !is_compile_time_expr_with_locals(value, locals) {
                return false;
            }
            locals.insert(ident.text.clone());
            true
        }
        ExprKind::Block(block) => {
            let mut scope = locals.clone();
            for stmt in &block.statements {
                match stmt {
                    Stmt::Binding(binding) => {
                        if !is_compile_time_expr_with_locals(&binding.value, &mut scope) {
                            return false;
                        }
                        scope.insert(binding.name.text.clone());
                    }
                    Stmt::Destructure(d) => {
                        if !is_compile_time_expr_with_locals(&d.value, &mut scope) {
                            return false;
                        }
                        for dn in &d.names {
                            scope.insert(dn.name.text.clone());
                        }
                    }
                    Stmt::Expr(expr) => {
                        if !is_compile_time_expr_with_locals(expr, &mut scope) {
                            return false;
                        }
                    }
                }
            }
            if let Some(tail) = &block.tail_expr {
                is_compile_time_expr_with_locals(tail, &mut scope)
            } else {
                true
            }
        }
        ExprKind::If(if_expr) => {
            if !is_compile_time_expr_with_locals(&if_expr.condition, locals) {
                return false;
            }
            let mut then_scope = locals.clone();
            if let Some(capture) = &if_expr.capture {
                for binding_opt in &capture.bindings {
                    if let Some(binding) = binding_opt {
                        if binding.text != "_" {
                            then_scope.insert(binding.text.clone());
                        }
                    }
                }
            }
            if !is_compile_time_expr_with_locals(&if_expr.then_branch, &mut then_scope) {
                return false;
            }
            if let Some(else_branch) = &if_expr.else_branch {
                let mut else_scope = locals.clone();
                is_compile_time_expr_with_locals(else_branch, &mut else_scope)
            } else {
                true
            }
        }
        ExprKind::Return { value } => value
            .as_ref()
            .map(|value| is_compile_time_expr_with_locals(value, locals))
            .unwrap_or(false),
        ExprKind::ArrayLiteral(elements) | ExprKind::TupleLiteral(elements) => elements
            .iter()
            .all(|element| is_compile_time_expr_with_locals(element, locals)),
        ExprKind::Call(call) => match &call.callee.kind {
            ExprKind::BuiltinIdent(ident) => match ident.text.as_str() {
                "$as" => {
                    call.args.len() == 2
                        && is_type_designator_expr(&call.args[0].value)
                        && is_compile_time_expr_with_locals(&call.args[1].value, locals)
                }
                "$sizeof" | "$alignof" => {
                    call.args.len() == 1 && is_type_designator_expr(&call.args[0].value)
                }
                "$offsetof" => {
                    call.args.len() == 2
                        && is_type_designator_expr(&call.args[0].value)
                        && matches!(
                            call.args[1].value.kind,
                            ExprKind::Ident(_) | ExprKind::Literal(Literal::Integer(_))
                        )
                }
                "$typeof" => {
                    call.args.len() == 1
                        && is_compile_time_expr_with_locals(&call.args[0].value, locals)
                }
                "$self" => call.args.is_empty(),
                _ => false,
            },
            ExprKind::Ident(_) => call
                .args
                .iter()
                .all(|arg| is_compile_time_expr_with_locals(&arg.value, locals)),
            _ => false,
        },
        ExprKind::Comptime { expr } | ExprKind::Inline { expr } => {
            is_compile_time_expr_with_locals(expr, locals)
        }
        _ => false,
    }
}
struct ControlContext<'a> {
    loop_depth: usize,
    labels: Vec<String>,
    or_fallback_depth: usize,
    units: &'a [ModuleUnit],
}

pub fn control_check_modules(units: &[ModuleUnit]) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();

    for unit in units {
        for decl in &unit.declarations {
            if decl.kind != DeclKind::Binding {
                continue;
            }

            let mut ctx = ControlContext {
                loop_depth: 0,
                labels: Vec::new(),
                or_fallback_depth: 0,
                units,
            };
            check_expr(&decl.value, &mut ctx, &decl.file_path, &mut diagnostics);
        }
    }

    diagnostics
}

fn check_expr(
    expr: &Expr,
    ctx: &mut ControlContext<'_>,
    file_path: &std::path::Path,
    diagnostics: &mut Vec<Diagnostic>,
) {
    match &expr.kind {
        ExprKind::For(for_expr) => {
            ctx.loop_depth += 1;
            match for_expr {
                ForExpr::Range {
                    start, end, body, ..
                } => {
                    check_expr(start, ctx, file_path, diagnostics);
                    check_expr(end, ctx, file_path, diagnostics);
                    check_expr(body, ctx, file_path, diagnostics);
                }
                ForExpr::Iterate { iterable, body, .. } => {
                    check_expr(iterable, ctx, file_path, diagnostics);
                    check_expr(body, ctx, file_path, diagnostics);
                }
                ForExpr::WhileLike { condition, body } => {
                    check_expr(condition, ctx, file_path, diagnostics);
                    check_expr(body, ctx, file_path, diagnostics);
                }
                ForExpr::Infinite { body } => check_expr(body, ctx, file_path, diagnostics),
            }
            ctx.loop_depth -= 1;
        }
        ExprKind::Break(break_expr) => {
            let in_or_fallback = ctx.or_fallback_depth > 0;

            if break_expr.value.is_some() && break_expr.label.is_none() && !in_or_fallback {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::Semantic,
                        DiagnosticCode::E4007,
                        "break with value requires labeled block target",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "add a label target like `break :lbl value`",
                    ),
                );
            }

            if let Some(label) = &break_expr.label {
                if !ctx
                    .labels
                    .iter()
                    .any(|existing| existing == &label.name.text)
                {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::Semantic,
                            DiagnosticCode::E4007,
                            format!("unknown break label '{}'", label.name.text),
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "label is not in scope",
                        ),
                    );
                }
            } else if ctx.loop_depth == 0 && !in_or_fallback {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::Semantic,
                        DiagnosticCode::E4007,
                        "break used outside loop or labeled block",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "break requires loop or label context",
                    ),
                );
            }

            if let Some(value) = &break_expr.value {
                check_expr(value, ctx, file_path, diagnostics);
            }
        }
        ExprKind::Continue { label } => {
            if let Some(label) = label {
                if !ctx
                    .labels
                    .iter()
                    .any(|existing| existing == &label.name.text)
                {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::Semantic,
                            DiagnosticCode::E4007,
                            format!("unknown continue label '{}'", label.name.text),
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "label is not in scope",
                        ),
                    );
                }
            } else if ctx.loop_depth == 0 {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::Semantic,
                        DiagnosticCode::E4007,
                        "continue used outside loop",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "continue requires loop context",
                    ),
                );
            }
        }
        ExprKind::Block(block) => check_block(block, ctx, file_path, diagnostics),
        ExprKind::If(if_expr) => {
            check_expr(&if_expr.condition, ctx, file_path, diagnostics);
            check_expr(&if_expr.then_branch, ctx, file_path, diagnostics);
            if let Some(else_branch) = &if_expr.else_branch {
                check_expr(else_branch, ctx, file_path, diagnostics);
            }
        }
        ExprKind::Match(match_expr) => {
            check_expr(&match_expr.scrutinee, ctx, file_path, diagnostics);
            for arm in &match_expr.arms {
                if let Some(guard) = &arm.guard {
                    check_expr(guard, ctx, file_path, diagnostics);
                }
                check_expr(&arm.value, ctx, file_path, diagnostics);
            }

            if !is_match_exhaustive(match_expr, ctx.units) {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::Semantic,
                        DiagnosticCode::E4008,
                        "match expression is not exhaustive",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "add wildcard arm `_: ...` or cover all cases",
                    ),
                );
            }
        }
        ExprKind::Unary { expr, .. }
        | ExprKind::OptionalUnwrap { expr }
        | ExprKind::ErrorUnwrap { expr }
        | ExprKind::Comptime { expr }
        | ExprKind::Inline { expr } => check_expr(expr, ctx, file_path, diagnostics),
        ExprKind::Binary { left, right, .. } => {
            check_expr(left, ctx, file_path, diagnostics);
            check_expr(right, ctx, file_path, diagnostics);
        }
        ExprKind::Assign { target, value, .. } => {
            check_expr(target, ctx, file_path, diagnostics);
            check_expr(value, ctx, file_path, diagnostics);
        }
        ExprKind::Call(call) => {
            check_expr(&call.callee, ctx, file_path, diagnostics);
            for arg in &call.args {
                check_expr(&arg.value, ctx, file_path, diagnostics);
            }
        }
        ExprKind::FieldAccess { base, .. } | ExprKind::DerefAccess { base } => {
            check_expr(base, ctx, file_path, diagnostics)
        }
        ExprKind::Index { base, index } => {
            check_expr(base, ctx, file_path, diagnostics);
            check_expr(index, ctx, file_path, diagnostics);
        }
        ExprKind::Slice(slice) => {
            check_expr(&slice.base, ctx, file_path, diagnostics);
            if let Some(start) = &slice.start {
                check_expr(start, ctx, file_path, diagnostics);
            }
            if let Some(end) = &slice.end {
                check_expr(end, ctx, file_path, diagnostics);
            }
        }
        ExprKind::Defer(defer_expr) => check_expr(&defer_expr.body, ctx, file_path, diagnostics),
        ExprKind::OrElse(or_else) => {
            check_expr(&or_else.value, ctx, file_path, diagnostics);
            ctx.or_fallback_depth += 1;
            check_expr(&or_else.fallback, ctx, file_path, diagnostics);
            ctx.or_fallback_depth -= 1;
        }
        ExprKind::StructLiteral(struct_lit) => {
            for field in &struct_lit.fields {
                check_expr(&field.value, ctx, file_path, diagnostics);
            }
        }
        ExprKind::TypeConstruct { ty_expr, fields } => {
            check_expr(ty_expr, ctx, file_path, diagnostics);
            for field in fields {
                check_expr(&field.value, ctx, file_path, diagnostics);
            }
        }
        ExprKind::ArrayLiteral(elements) => {
            for element in elements {
                check_expr(element, ctx, file_path, diagnostics);
            }
        }
        ExprKind::TupleLiteral(elements) => {
            for element in elements {
                check_expr(element, ctx, file_path, diagnostics);
            }
        }
        ExprKind::EnumVariantConstruct(enum_variant) => {
            for payload in &enum_variant.payload {
                check_expr(payload, ctx, file_path, diagnostics);
            }
        }
        ExprKind::Fn(fn_expr) => match &fn_expr.body {
            crate::compiler::ast::FnBody::Block(block) => {
                check_block(block, ctx, file_path, diagnostics)
            }
            crate::compiler::ast::FnBody::ArrowExpr(expr) => {
                check_expr(expr, ctx, file_path, diagnostics)
            }
        },
        ExprKind::Return { value } => {
            if let Some(value) = value {
                check_expr(value, ctx, file_path, diagnostics);
            }
        }
        ExprKind::Use { .. }
        | ExprKind::TypeLiteral(_)
        | ExprKind::Literal(_)
        | ExprKind::Ident(_)
        | ExprKind::BuiltinIdent(_) => {}
    }
}

fn is_match_exhaustive(match_expr: &crate::compiler::ast::MatchExpr, units: &[ModuleUnit]) -> bool {
    if match_expr.arms.is_empty() {
        return false;
    }

    if match_expr.arms.iter().any(|arm| {
        arm.guard.is_none()
            && matches!(
                arm.pattern.kind,
                PatternKind::Wildcard | PatternKind::IdentBind(_)
            )
    }) {
        return true;
    }

    let mut has_true = false;
    let mut has_false = false;
    for arm in &match_expr.arms {
        if arm.guard.is_some() {
            continue;
        }
        if let PatternKind::Literal(PatternLiteral::Bool(value)) = &arm.pattern.kind {
            if *value {
                has_true = true;
            } else {
                has_false = true;
            }
        }
    }

    if has_true && has_false {
        return true;
    }

    match &match_expr.scrutinee.kind {
        ExprKind::Literal(crate::compiler::ast::Literal::Bool(value)) => match_expr
            .arms
            .iter()
            .any(|arm| arm.guard.is_none() && pattern_matches_bool(&arm.pattern.kind, *value)),
        ExprKind::Literal(crate::compiler::ast::Literal::Integer(value)) => {
            let Some(value) = parse_int_literal(value) else {
                return false;
            };
            match_expr
                .arms
                .iter()
                .any(|arm| arm.guard.is_none() && pattern_matches_int(&arm.pattern.kind, value))
        }
        ExprKind::EnumVariantConstruct(enum_variant) => match_expr.arms.iter().any(|arm| {
            arm.guard.is_none() && pattern_matches_enum_variant(&arm.pattern.kind, enum_variant)
        }),
        _ => enum_variant_match_exhaustive(match_expr, units),
    }
}

/// Checks exhaustiveness for enum-typed scrutinees (non-literal).
///
/// Two strategies are used depending on whether the match arms carry explicit
/// root type names:
///
/// **Explicit root** (e.g. `MyEnum.Variant`): the compiler looks up the full
/// variant list for that type in the module declarations and verifies every
/// variant is covered.  Mixed root type names, guarded arms, or a root type
/// that can't be found all cause this check to return `false`.
///
/// **Shorthand / no root** (e.g. `.Variant`): without type information the
/// compiler cannot enumerate all variants, so it falls back to the conservative
/// heuristic — assume exhaustive if every arm is an unguarded enum variant
/// pattern.  This matches the old behaviour and avoids breaking existing code
/// that correctly covers all variants in shorthand style.
fn enum_variant_match_exhaustive(
    match_expr: &crate::compiler::ast::MatchExpr,
    units: &[ModuleUnit],
) -> bool {
    let mut matched_variants: BTreeSet<String> = BTreeSet::new();
    let mut root_name: Option<String> = None;
    let mut has_any_root = false;

    for arm in &match_expr.arms {
        // Guarded arms don't guarantee coverage of a case.
        if arm.guard.is_some() {
            return false;
        }
        let PatternKind::EnumVariant { root, variant, .. } = &arm.pattern.kind else {
            return false;
        };
        matched_variants.insert(variant.text.clone());
        if let Some(r) = root {
            has_any_root = true;
            match &root_name {
                None => root_name = Some(r.text.clone()),
                Some(existing) if existing != &r.text => return false, // mixed root types
                Some(_) => {}
            }
        }
    }

    if matched_variants.is_empty() {
        return false;
    }

    // If no arm used an explicit root type name, fall back to the heuristic:
    // assume exhaustive when all arms are unguarded enum variant patterns.
    // We cannot look up the full variant list without type information, so
    // this is a best-effort check.  Users who want guaranteed exhaustiveness
    // should use explicit root names (e.g. `MyEnum.Variant`) or add a `_` arm.
    if !has_any_root {
        return true;
    }

    // At least one explicit root type name is present.
    let Some(type_name) = root_name else {
        return false;
    };

    // Look up the enum declaration in any visible module unit.
    let Some(all_variants) = find_enum_variants(&type_name, units) else {
        // Declaration not found (e.g. imported type) — fall back to heuristic.
        return true;
    };

    // Every declared variant must appear in the match arms.
    all_variants.iter().all(|v| matched_variants.contains(v))
}

/// Searches module declarations for an enum type named `type_name` and returns
/// its variant names, or `None` if no such declaration is found.
fn find_enum_variants(type_name: &str, units: &[ModuleUnit]) -> Option<Vec<String>> {
    for unit in units {
        for decl in &unit.declarations {
            if decl.name != type_name {
                continue;
            }
            if let ExprKind::TypeLiteral(type_expr) = &decl.value.kind {
                if let TypeExprKind::Enum(enum_type) = &type_expr.kind {
                    return Some(
                        enum_type
                            .variants
                            .iter()
                            .map(|v| v.name.text.clone())
                            .collect(),
                    );
                }
            }
        }
    }
    None
}

fn pattern_matches_bool(pattern: &PatternKind, scrutinee: bool) -> bool {
    match pattern {
        PatternKind::Literal(crate::compiler::ast::PatternLiteral::Bool(value)) => {
            *value == scrutinee
        }
        PatternKind::Wildcard => true,
        _ => false,
    }
}

fn pattern_matches_enum_variant(pattern: &PatternKind, scrutinee: &EnumVariantExpr) -> bool {
    match pattern {
        PatternKind::EnumVariant { root, variant, .. } => {
            let root_matches = match (root.as_ref(), scrutinee.root.as_ref()) {
                (None, _) => true,
                (Some(pattern_root), Some(scrutinee_root)) => {
                    pattern_root.text == scrutinee_root.text
                }
                (Some(_), None) => false,
            };
            root_matches && variant.text == scrutinee.variant.text
        }
        PatternKind::Typed { pattern, .. } => {
            pattern_matches_enum_variant(&pattern.kind, scrutinee)
        }
        PatternKind::Wildcard | PatternKind::IdentBind(_) => true,
        _ => false,
    }
}

fn pattern_matches_int(pattern: &PatternKind, scrutinee: i64) -> bool {
    match pattern {
        PatternKind::Literal(crate::compiler::ast::PatternLiteral::Integer(value)) => {
            parse_int_literal(value)
                .map(|v| v == scrutinee)
                .unwrap_or(false)
        }
        PatternKind::Range {
            start,
            end,
            inclusive,
        } => {
            let Some(start) = (match &start.kind {
                PatternKind::Literal(crate::compiler::ast::PatternLiteral::Integer(v)) => {
                    parse_int_literal(v)
                }
                _ => None,
            }) else {
                return false;
            };
            let Some(end) = (match &end.kind {
                PatternKind::Literal(crate::compiler::ast::PatternLiteral::Integer(v)) => {
                    parse_int_literal(v)
                }
                _ => None,
            }) else {
                return false;
            };
            if *inclusive {
                scrutinee >= start && scrutinee <= end
            } else {
                scrutinee >= start && scrutinee < end
            }
        }
        PatternKind::Wildcard => true,
        _ => false,
    }
}

fn parse_int_literal(value: &str) -> Option<i64> {
    let normalized = value.replace('_', "");
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

fn check_block(
    block: &BlockExpr,
    ctx: &mut ControlContext<'_>,
    file_path: &std::path::Path,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let initial_label_depth = ctx.labels.len();
    if let Some(label) = &block.label {
        ctx.labels.push(label.name.text.clone());
    }

    for stmt in &block.statements {
        match stmt {
            Stmt::Binding(binding) => check_expr(&binding.value, ctx, file_path, diagnostics),
            Stmt::Destructure(d) => check_expr(&d.value, ctx, file_path, diagnostics),
            Stmt::Expr(expr) => check_expr(expr, ctx, file_path, diagnostics),
        }
    }
    if let Some(tail) = &block.tail_expr {
        check_expr(tail, ctx, file_path, diagnostics);
    }

    ctx.labels.truncate(initial_label_depth);
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ModuleUnit {
    pub module_id: ModuleId,
    pub key: ModuleKey,
    pub files: Vec<PathBuf>,
    pub declarations: Vec<DeclStub>,
    pub extern_declarations: Vec<ExternDeclStub>,
    pub imports: Vec<ImportStub>,
    pub name_uses: Vec<NameUseStub>,
    pub member_uses: Vec<MemberUseStub>,
    pub type_associations: Vec<TypeAssociation>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeclStub {
    pub name: String,
    pub visibility: Visibility,
    pub mutable: bool,
    pub kind: DeclKind,
    pub initializer: DeclInitializer,
    pub annotation: Option<TypeExpr>,
    pub value: Expr,
    pub file_path: PathBuf,
    pub span: SourceSpan,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExternDeclStub {
    pub name: String,
    pub visibility: Visibility,
    pub ty: TypeExpr,
    pub link_name: Option<String>,
    pub file_path: PathBuf,
    pub span: SourceSpan,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ImportStub {
    pub alias: Option<String>,
    pub path: String,
    pub file_path: PathBuf,
    pub span: SourceSpan,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NameUseStub {
    pub name: String,
    pub file_path: PathBuf,
    pub span: SourceSpan,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MemberUseStub {
    pub base_name: String,
    pub member_name: String,
    pub file_path: PathBuf,
    pub span: SourceSpan,
}

/// Lightweight record that a type has a named member in its scope, whose binding lives in
/// `declarations` under the synthetic name `format!("{type_name}__{member_name}")`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TypeAssociation {
    pub type_name: String,
    pub member_name: String,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum DeclKind {
    Binding,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DeclInitializer {
    Expr,
}

pub fn build_module_units(graph: &ModuleGraph, parsed: &ParseSession) -> Vec<ModuleUnit> {
    let mut units = graph
        .modules
        .iter()
        .map(|module| {
            (
                module.id,
                ModuleUnit {
                    module_id: module.id,
                    key: module.key.clone(),
                    files: module.files.clone(),
                    declarations: Vec::new(),
                    extern_declarations: Vec::new(),
                    imports: Vec::new(),
                    name_uses: Vec::new(),
                    member_uses: Vec::new(),
                    type_associations: Vec::new(),
                },
            )
        })
        .collect::<BTreeMap<_, _>>();

    for parsed_file in &parsed.files {
        let Some(ast) = &parsed_file.ast else {
            continue;
        };

        let Some(unit) = units.get_mut(&parsed_file.module_id) else {
            continue;
        };

        for item in &ast.items {
            match item {
                Item::Binding(binding) => {
                    unit.declarations.push(DeclStub {
                        name: binding.name.text.clone(),
                        visibility: binding.visibility,
                        mutable: binding.mutable,
                        kind: DeclKind::Binding,
                        initializer: DeclInitializer::Expr,
                        annotation: binding.annotation.clone(),
                        value: binding.value.clone(),
                        file_path: parsed_file.file_path.clone(),
                        span: binding.span,
                    });
                }
                Item::Destructure(d) => {
                    for dn in &d.names {
                        unit.declarations.push(DeclStub {
                            name: dn.name.text.clone(),
                            visibility: d.visibility,
                            mutable: dn.mutable,
                            kind: DeclKind::Binding,
                            initializer: DeclInitializer::Expr,
                            annotation: None,
                            value: d.value.clone(),
                            file_path: parsed_file.file_path.clone(),
                            span: d.span,
                        });
                    }
                }
                Item::Extern(extern_decl) => {
                    unit.extern_declarations.push(ExternDeclStub {
                        name: extern_decl.name.text.clone(),
                        visibility: extern_decl.visibility,
                        ty: extern_decl.ty.clone(),
                        link_name: extern_decl.link_name.clone(),
                        file_path: parsed_file.file_path.clone(),
                        span: extern_decl.span,
                    });
                }
                Item::TypeBinding(tb) => {
                    let synthetic = format!("{}__{}", tb.type_name.text, tb.member_name.text);
                    unit.declarations.push(DeclStub {
                        name: synthetic,
                        visibility: tb.visibility,
                        mutable: false,
                        kind: DeclKind::Binding,
                        initializer: DeclInitializer::Expr,
                        annotation: tb.annotation.clone(),
                        value: tb.value.clone(),
                        file_path: parsed_file.file_path.clone(),
                        span: tb.span,
                    });
                    unit.type_associations.push(TypeAssociation {
                        type_name: tb.type_name.text.clone(),
                        member_name: tb.member_name.text.clone(),
                    });
                }
                Item::ExprStmt(_) => {}
            }
        }

        for item in &ast.items {
            collect_item_uses(
                item,
                &parsed_file.file_path,
                &mut unit.imports,
                &mut unit.name_uses,
                &mut unit.member_uses,
            );
        }

        let absolute_path = resolve_graph_file_path(graph, &parsed_file.file_path);
        if let Ok(source) = fs::read_to_string(&absolute_path) {
            collect_source_level_use_imports(&source, &parsed_file.file_path, &mut unit.imports);
        }
    }

    units.into_values().collect()
}

fn collect_source_level_use_imports(source: &str, file_path: &PathBuf, out: &mut Vec<ImportStub>) {
    for (line_index, line) in source.lines().enumerate() {
        let code = if let Some(comment_start) = line.find("//") {
            &line[..comment_start]
        } else {
            line
        };

        let Some(use_pos) = code.find("use ") else {
            continue;
        };

        let prefix = &code[..use_pos];
        if !prefix.contains(":=") && !prefix.contains("=") {
            continue;
        }

        let path_start = use_pos + 4;
        let bytes = code.as_bytes();
        if path_start >= bytes.len() || bytes[path_start] != b'"' {
            continue;
        }
        let rest = &code[path_start + 1..];
        let Some(end_quote) = rest.find('"') else {
            continue;
        };
        let path = rest[..end_quote].to_string();
        if path.is_empty() {
            continue;
        }

        if out.iter().any(|existing| {
            existing.file_path == *file_path
                && existing.path == path
                && existing.span.start_line == line_index + 1
        }) {
            continue;
        }

        out.push(ImportStub {
            alias: None,
            path,
            file_path: file_path.clone(),
            span: SourceSpan {
                start_byte: 0,
                end_byte: 0,
                start_line: line_index + 1,
                start_col: 1,
                end_line: line_index + 1,
                end_col: 1,
            },
        });
    }
}

fn collect_item_uses(
    item: &Item,
    file_path: &PathBuf,
    imports: &mut Vec<ImportStub>,
    names: &mut Vec<NameUseStub>,
    members: &mut Vec<MemberUseStub>,
) {
    match item {
        Item::Binding(binding) => collect_binding_uses(binding, file_path, imports, names, members),
        Item::Destructure(d) => {
            collect_expr_uses(&d.value, None, file_path, imports, names, members)
        }
        Item::Extern(_) => {}
        Item::ExprStmt(expr) => collect_expr_uses(expr, None, file_path, imports, names, members),
        Item::TypeBinding(tb) => {
            let synthetic = format!("{}__{}", tb.type_name.text, tb.member_name.text);
            collect_expr_uses(&tb.value, Some(synthetic), file_path, imports, names, members);
        }
    }
}

fn collect_binding_uses(
    binding: &Binding,
    file_path: &PathBuf,
    imports: &mut Vec<ImportStub>,
    names: &mut Vec<NameUseStub>,
    members: &mut Vec<MemberUseStub>,
) {
    let alias = Some(binding.name.text.clone());
    collect_expr_uses(&binding.value, alias, file_path, imports, names, members);
}

fn collect_stmt_uses(
    stmt: &Stmt,
    file_path: &PathBuf,
    imports: &mut Vec<ImportStub>,
    names: &mut Vec<NameUseStub>,
    members: &mut Vec<MemberUseStub>,
) {
    match stmt {
        Stmt::Binding(binding) => collect_binding_uses(binding, file_path, imports, names, members),
        Stmt::Destructure(d) => {
            collect_expr_uses(&d.value, None, file_path, imports, names, members)
        }
        Stmt::Expr(expr) => collect_expr_uses(expr, None, file_path, imports, names, members),
    }
}

fn collect_expr_uses(
    expr: &Expr,
    alias_hint: Option<String>,
    file_path: &PathBuf,
    imports: &mut Vec<ImportStub>,
    names: &mut Vec<NameUseStub>,
    members: &mut Vec<MemberUseStub>,
) {
    match &expr.kind {
        ExprKind::Use { path } => imports.push(ImportStub {
            alias: alias_hint,
            path: path.trim_matches('"').to_string(),
            file_path: file_path.clone(),
            span: expr.span,
        }),
        ExprKind::Ident(ident) => names.push(NameUseStub {
            name: ident.text.clone(),
            file_path: file_path.clone(),
            span: expr.span,
        }),
        ExprKind::Unary { expr, .. } => {
            collect_expr_uses(expr, None, file_path, imports, names, members)
        }
        ExprKind::Binary { left, right, .. } => {
            collect_expr_uses(left, None, file_path, imports, names, members);
            collect_expr_uses(right, None, file_path, imports, names, members);
        }
        ExprKind::Assign { target, value, .. } => {
            collect_expr_uses(target, None, file_path, imports, names, members);
            collect_expr_uses(value, None, file_path, imports, names, members);
        }
        ExprKind::Call(call) => {
            collect_expr_uses(&call.callee, None, file_path, imports, names, members);
            for arg in &call.args {
                collect_expr_uses(&arg.value, None, file_path, imports, names, members);
            }
        }
        ExprKind::FieldAccess { base, field } => {
            if let ExprKind::Ident(ident) = &base.kind {
                members.push(MemberUseStub {
                    base_name: ident.text.clone(),
                    member_name: field.text.clone(),
                    file_path: file_path.clone(),
                    span: expr.span,
                });
            }
            collect_expr_uses(base, None, file_path, imports, names, members);
        }
        ExprKind::DerefAccess { base }
        | ExprKind::OptionalUnwrap { expr: base }
        | ExprKind::ErrorUnwrap { expr: base }
        | ExprKind::Comptime { expr: base }
        | ExprKind::Inline { expr: base } => {
            collect_expr_uses(base, None, file_path, imports, names, members)
        }
        ExprKind::Index { base, index } => {
            collect_expr_uses(base, None, file_path, imports, names, members);
            collect_expr_uses(index, None, file_path, imports, names, members);
        }
        ExprKind::Slice(slice) => {
            collect_expr_uses(&slice.base, None, file_path, imports, names, members);
            if let Some(start) = &slice.start {
                collect_expr_uses(start, None, file_path, imports, names, members);
            }
            if let Some(end) = &slice.end {
                collect_expr_uses(end, None, file_path, imports, names, members);
            }
        }
        ExprKind::Block(block) => {
            for stmt in &block.statements {
                collect_stmt_uses(stmt, file_path, imports, names, members);
            }
            if let Some(tail) = &block.tail_expr {
                collect_expr_uses(tail, None, file_path, imports, names, members);
            }
        }
        ExprKind::If(if_expr) => {
            collect_expr_uses(&if_expr.condition, None, file_path, imports, names, members);
            collect_expr_uses(
                &if_expr.then_branch,
                None,
                file_path,
                imports,
                names,
                members,
            );
            if let Some(else_branch) = &if_expr.else_branch {
                collect_expr_uses(else_branch, None, file_path, imports, names, members);
            }
        }
        ExprKind::Match(match_expr) => {
            collect_expr_uses(
                &match_expr.scrutinee,
                None,
                file_path,
                imports,
                names,
                members,
            );
            for arm in &match_expr.arms {
                collect_expr_uses(&arm.value, None, file_path, imports, names, members);
            }
        }
        ExprKind::For(for_expr) => match for_expr {
            crate::compiler::ast::ForExpr::Range {
                start, end, body, ..
            } => {
                collect_expr_uses(start, None, file_path, imports, names, members);
                collect_expr_uses(end, None, file_path, imports, names, members);
                collect_expr_uses(body, None, file_path, imports, names, members);
            }
            crate::compiler::ast::ForExpr::Iterate { iterable, body, .. } => {
                collect_expr_uses(iterable, None, file_path, imports, names, members);
                collect_expr_uses(body, None, file_path, imports, names, members);
            }
            crate::compiler::ast::ForExpr::WhileLike { condition, body } => {
                collect_expr_uses(condition, None, file_path, imports, names, members);
                collect_expr_uses(body, None, file_path, imports, names, members);
            }
            crate::compiler::ast::ForExpr::Infinite { body } => {
                collect_expr_uses(body, None, file_path, imports, names, members);
            }
        },
        ExprKind::Break(break_expr) => {
            if let Some(value) = &break_expr.value {
                collect_expr_uses(value, None, file_path, imports, names, members);
            }
        }
        ExprKind::Return { value } => {
            if let Some(value) = value {
                collect_expr_uses(value, None, file_path, imports, names, members);
            }
        }
        ExprKind::Defer(defer_expr) => {
            collect_expr_uses(&defer_expr.body, None, file_path, imports, names, members)
        }
        ExprKind::OrElse(or_else) => {
            collect_expr_uses(&or_else.value, None, file_path, imports, names, members);
            collect_expr_uses(&or_else.fallback, None, file_path, imports, names, members);
        }
        ExprKind::StructLiteral(struct_lit) => {
            for field in &struct_lit.fields {
                collect_expr_uses(&field.value, None, file_path, imports, names, members);
            }
        }
        ExprKind::TypeConstruct { ty_expr, fields } => {
            collect_expr_uses(ty_expr, None, file_path, imports, names, members);
            for field in fields {
                collect_expr_uses(&field.value, None, file_path, imports, names, members);
            }
        }
        ExprKind::ArrayLiteral(elements) => {
            for element in elements {
                collect_expr_uses(element, None, file_path, imports, names, members);
            }
        }
        ExprKind::TupleLiteral(elements) => {
            for element in elements {
                collect_expr_uses(element, None, file_path, imports, names, members);
            }
        }
        ExprKind::EnumVariantConstruct(enum_variant) => {
            for payload in &enum_variant.payload {
                collect_expr_uses(payload, None, file_path, imports, names, members);
            }
        }
        ExprKind::Fn(_fn_expr) => {}
        ExprKind::Literal(_)
        | ExprKind::BuiltinIdent(_)
        | ExprKind::Continue { .. }
        | ExprKind::TypeLiteral(_) => {}
    }
}
pub fn parse_int_type_bits(name: &str) -> Option<(bool, u16)> {
    if name == "isize" {
        return Some((true, 64));
    }
    if name == "usize" {
        return Some((false, 64));
    }

    let (signed, rest) = if let Some(bits) = name.strip_prefix('i') {
        (true, bits)
    } else if let Some(bits) = name.strip_prefix('u') {
        (false, bits)
    } else {
        return None;
    };

    if rest.is_empty() {
        return None;
    }
    let bits = rest.parse::<u16>().ok()?;
    Some((signed, bits))
}

pub fn parse_float_type_bits(name: &str) -> Option<u16> {
    let rest = name.strip_prefix('f')?;
    if rest.is_empty() {
        return None;
    }
    rest.parse::<u16>().ok()
}

pub fn is_int_type_name(name: &str) -> bool {
    parse_int_type_bits(name).is_some()
}

pub fn is_float_type_name(name: &str) -> bool {
    parse_float_type_bits(name).is_some()
}

#[derive(Debug, Copy, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct TypeId(pub usize);

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Type {
    Unknown,
    TypeType,
    TypeParam(String),
    Bool,
    Int {
        signed: bool,
        bits: u16,
    },
    Float {
        bits: u16,
    },
    Any,
    Opaque,
    Void,
    Null,
    Optional(TypeId),
    Errorable {
        ok: TypeId,
        errors: BTreeSet<String>,
    },
    Pointer {
        inner: TypeId,
    },
    Array(TypeId),
    Slice {
        element: TypeId,
    },
    Tuple(Vec<TypeId>),
    Applied {
        callee: String,
        args: Vec<TypeId>,
    },
    Function {
        param_types: Vec<TypeId>,
        param_names: Vec<Option<String>>,
        has_defaults: Vec<bool>,
        return_type: TypeId,
    },
}

#[derive(Default)]
struct TypeStore {
    types: Vec<Type>,
}

impl TypeStore {
    fn intern(&mut self, ty: Type) -> TypeId {
        if let Some((index, _)) = self.types.iter().enumerate().find(|(_, t)| **t == ty) {
            return TypeId(index);
        }
        self.types.push(ty);
        TypeId(self.types.len() - 1)
    }

    fn get(&self, id: TypeId) -> &Type {
        &self.types[id.0]
    }
}

#[derive(Debug, Clone)]
struct FnParamSpec {
    name: Option<String>,
    has_default: bool,
    comp: bool,
}

#[derive(Debug, Clone)]
struct FnSignature {
    params: Vec<FnParamSpec>,
    return_type: TypeId,
}

#[derive(Copy, Clone)]
enum AnyUsageContext {
    FunctionParam,
    /// Direct inner type of a `*` pointer — `*any` is the erased pointer type.
    PointerInner,
    Other,
}

pub fn type_check_modules(units: &[ModuleUnit]) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();

    for unit in units {
        let mut types = TypeStore::default();
        let unknown = types.intern(Type::Unknown);
        let mut env = BTreeMap::<String, TypeId>::new();
        let mut mutability = BTreeMap::<String, bool>::new();
        let mut signatures = BTreeMap::<String, FnSignature>::new();
        let named_struct_fields = collect_named_struct_fields(unit);
        let enum_variants = collect_enum_variants(unit);

        for extern_decl in &unit.extern_declarations {
            let TypeExprKind::Function(fn_ty) = &extern_decl.ty.kind else {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        format!(
                            "extern declaration '{}' must use a function type",
                            extern_decl.name
                        ),
                    )
                    .with_primary_file_label(
                        extern_decl.file_path.clone(),
                        Some(extern_decl.span),
                        "use `fn(...) ...` for extern declarations",
                    ),
                );
                continue;
            };

            for param in &fn_ty.params {
                validate_any_usage(
                    &param.ty,
                    AnyUsageContext::FunctionParam,
                    &mut diagnostics,
                    &extern_decl.file_path,
                );
            }
            validate_any_usage(
                &fn_ty.return_type,
                AnyUsageContext::Other,
                &mut diagnostics,
                &extern_decl.file_path,
            );

            let param_types = fn_ty
                .params
                .iter()
                .map(|param| resolve_type_expr(&param.ty, &mut types).unwrap_or(unknown))
                .collect::<Vec<_>>();
            let param_names = fn_ty
                .params
                .iter()
                .map(|param| param.name.as_ref().map(|ident| ident.text.clone()))
                .collect::<Vec<_>>();
            let return_type = resolve_type_expr(&fn_ty.return_type, &mut types).unwrap_or(unknown);

            signatures.insert(
                extern_decl.name.clone(),
                FnSignature {
                    params: param_names
                        .iter()
                        .cloned()
                        .map(|name| FnParamSpec {
                            name,
                            has_default: false,
                            comp: false,
                        })
                        .collect(),
                    return_type,
                },
            );
            env.insert(
                extern_decl.name.clone(),
                types.intern(Type::Function {
                    param_types,
                    param_names,
                    has_defaults: vec![false; fn_ty.params.len()],
                    return_type,
                }),
            );
        }

        for decl in &unit.declarations {
            if decl.kind != DeclKind::Binding {
                continue;
            }
            if let Some(fn_expr) = extract_fn_expr(&decl.value) {
                for param in &fn_expr.params {
                    if let Some(param_ty) = &param.ty {
                        validate_any_usage(
                            param_ty,
                            AnyUsageContext::FunctionParam,
                            &mut diagnostics,
                            &decl.file_path,
                        );
                    }
                }
                if let Some(return_ty) = &fn_expr.return_type {
                    validate_any_usage(
                        return_ty,
                        AnyUsageContext::Other,
                        &mut diagnostics,
                        &decl.file_path,
                    );
                }
                let return_type = fn_expr
                    .return_type
                    .as_ref()
                    .and_then(|ty| resolve_type_expr(ty, &mut types))
                    .unwrap_or(unknown);
                let params = fn_expr
                    .params
                    .iter()
                    .map(|param| FnParamSpec {
                        name: Some(param.name.text.clone()),
                        has_default: param.default_value.is_some(),
                        comp: param.comp || matches!(param.ty.as_ref(), Some(ty) if matches!(&ty.kind, crate::compiler::ast::TypeExprKind::Named(n) if n.text == "any")),
                    })
                    .collect::<Vec<_>>();
                signatures.insert(
                    decl.name.clone(),
                    FnSignature {
                        params,
                        return_type,
                    },
                );
                let param_types = fn_expr
                    .params
                    .iter()
                    .map(|param| {
                        param
                            .ty
                            .as_ref()
                            .and_then(|ty| resolve_type_expr(ty, &mut types))
                            .unwrap_or(unknown)
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
                env.insert(
                    decl.name.clone(),
                    types.intern(Type::Function {
                        param_types,
                        param_names,
                        has_defaults,
                        return_type,
                    }),
                );
            }
        }

        for decl in &unit.declarations {
            if decl.kind != DeclKind::Binding {
                continue;
            }
            let Some(fn_expr) = extract_fn_expr(&decl.value) else {
                continue;
            };
            let Some(ok_ty_expr) = implicit_error_union_ok_type(fn_expr) else {
                continue;
            };

            let inferred_errors = infer_implicit_error_union_set(
                fn_expr,
                &env,
                &mutability,
                &signatures,
                &mut types,
                &enum_variants,
                &decl.file_path,
            );
            if inferred_errors.is_empty() {
                continue;
            }
            let Some(ok_ty) = resolve_type_expr(ok_ty_expr, &mut types) else {
                continue;
            };
            let inferred_return = types.intern(Type::Errorable {
                ok: ok_ty,
                errors: inferred_errors,
            });

            if let Some(signature) = signatures.get_mut(&decl.name) {
                signature.return_type = inferred_return;
            }

            if let Some(function_ty) = env.get(&decl.name).copied() {
                if let Type::Function {
                    param_types,
                    param_names,
                    has_defaults,
                    ..
                } = types.get(function_ty).clone()
                {
                    env.insert(
                        decl.name.clone(),
                        types.intern(Type::Function {
                            param_types,
                            param_names,
                            has_defaults,
                            return_type: inferred_return,
                        }),
                    );
                }
            }
        }

        for decl in &unit.declarations {
            if decl.kind != DeclKind::Binding {
                continue;
            }

            if let Some(fn_expr) = extract_fn_expr(&decl.value) {
                validate_function_error_set_coverage(
                    fn_expr,
                    &enum_variants,
                    &decl.file_path,
                    &mut diagnostics,
                );
            }

            let allow_main_implicit_tail =
                should_allow_implicit_tail_for_main(unit, decl, &mut types);
            let diagnostics_before_infer = diagnostics.len();
            let mut actual = infer_expr_type(
                &decl.value,
                &env,
                &mutability,
                &signatures,
                &mut types,
                &mut diagnostics,
                &decl.file_path,
                None,
            );
            if allow_main_implicit_tail {
                let mut new_diagnostics = diagnostics.split_off(diagnostics_before_infer);
                new_diagnostics.retain(|diagnostic| {
                    !is_strict_return_mode_tail_diagnostic_for_span(diagnostic, decl.value.span)
                });
                diagnostics.extend(new_diagnostics);
            }
            if let ExprKind::TypeLiteral(ty) = &decl.value.kind {
                validate_struct_type_members(ty, &decl.name, &mut diagnostics, &decl.file_path);
            }
            validate_named_struct_offsetof_calls(
                &decl.value,
                &named_struct_fields,
                &mut diagnostics,
                &decl.file_path,
            );
            let expected = decl.annotation.as_ref().and_then(|ty| {
                validate_any_usage(
                    ty,
                    AnyUsageContext::Other,
                    &mut diagnostics,
                    &decl.file_path,
                );
                resolve_type_expr(ty, &mut types)
            });

            if matches!(types.get(actual), Type::Null) {
                if !decl.mutable {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4006,
                            format!("'{}' is assigned null but is not mutable", decl.name),
                        )
                        .with_primary_file_label(
                            decl.file_path.clone(),
                            Some(decl.span),
                            "null assignment requires mutable binding",
                        ),
                    );
                }
                if decl.annotation.is_none() {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4006,
                            format!(
                                "'{}' is assigned null but has no explicit type annotation",
                                decl.name
                            ),
                        )
                        .with_primary_file_label(
                            decl.file_path.clone(),
                            Some(decl.span),
                            "add an explicit type annotation, e.g. `mut x: ?i32 = null`",
                        ),
                    );
                }
            }

            let mut final_type = if let Some(expected) = expected {
                actual = maybe_coerce_literal_to_expected(&decl.value, actual, expected, &types);
                if !types_compatible(expected, actual, &types) {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            format!(
                                "type mismatch for '{}': annotation and value disagree",
                                decl.name
                            ),
                        )
                        .with_primary_file_label(
                            decl.file_path.clone(),
                            Some(decl.span),
                            "change annotation or initializer expression",
                        ),
                    );
                }
                expected
            } else {
                actual
            };

            if let Some(fn_expr) = extract_fn_expr(&decl.value) {
                if implicit_error_union_ok_type(fn_expr).is_some() {
                    if let Some(signature) = signatures.get(&decl.name) {
                        if let Type::Function {
                            param_types,
                            param_names,
                            has_defaults,
                            ..
                        } = types.get(final_type).clone()
                        {
                            final_type = types.intern(Type::Function {
                                param_types,
                                param_names,
                                has_defaults,
                                return_type: signature.return_type,
                            });
                        }
                    }
                }
            }

            env.insert(decl.name.clone(), final_type);
            mutability.insert(decl.name.clone(), decl.mutable);
        }
    }

    diagnostics
}

pub fn infer_binding_type_strings(
    units: &[ModuleUnit],
) -> BTreeMap<(crate::compiler::module_resolver::ModuleId, String), String> {
    let mut out = BTreeMap::new();

    for unit in units {
        let mut types = TypeStore::default();
        let unknown = types.intern(Type::Unknown);
        let mut env = BTreeMap::<String, TypeId>::new();
        let mut mutability = BTreeMap::<String, bool>::new();
        let mut signatures = BTreeMap::<String, FnSignature>::new();

        for extern_decl in &unit.extern_declarations {
            let TypeExprKind::Function(fn_ty) = &extern_decl.ty.kind else {
                continue;
            };

            let param_types = fn_ty
                .params
                .iter()
                .map(|param| resolve_type_expr(&param.ty, &mut types).unwrap_or(unknown))
                .collect::<Vec<_>>();
            let param_names = fn_ty
                .params
                .iter()
                .map(|param| param.name.as_ref().map(|ident| ident.text.clone()))
                .collect::<Vec<_>>();
            let return_type = resolve_type_expr(&fn_ty.return_type, &mut types).unwrap_or(unknown);

            signatures.insert(
                extern_decl.name.clone(),
                FnSignature {
                    params: param_names
                        .iter()
                        .cloned()
                        .map(|name| FnParamSpec {
                            name,
                            has_default: false,
                            comp: false,
                        })
                        .collect(),
                    return_type,
                },
            );
            env.insert(
                extern_decl.name.clone(),
                types.intern(Type::Function {
                    param_types,
                    param_names,
                    has_defaults: vec![false; fn_ty.params.len()],
                    return_type,
                }),
            );
        }

        for decl in &unit.declarations {
            if decl.kind != DeclKind::Binding {
                continue;
            }
            if let Some(fn_expr) = extract_fn_expr(&decl.value) {
                let return_type = fn_expr
                    .return_type
                    .as_ref()
                    .and_then(|ty| resolve_type_expr(ty, &mut types))
                    .unwrap_or(unknown);
                let params = fn_expr
                    .params
                    .iter()
                    .map(|param| FnParamSpec {
                        name: Some(param.name.text.clone()),
                        has_default: param.default_value.is_some(),
                        comp: param.comp || matches!(param.ty.as_ref(), Some(ty) if matches!(&ty.kind, crate::compiler::ast::TypeExprKind::Named(n) if n.text == "any")),
                    })
                    .collect::<Vec<_>>();
                signatures.insert(
                    decl.name.clone(),
                    FnSignature {
                        params,
                        return_type,
                    },
                );
                let param_types = fn_expr
                    .params
                    .iter()
                    .map(|param| {
                        param
                            .ty
                            .as_ref()
                            .and_then(|ty| resolve_type_expr(ty, &mut types))
                            .unwrap_or(unknown)
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
                env.insert(
                    decl.name.clone(),
                    types.intern(Type::Function {
                        param_types,
                        param_names,
                        has_defaults,
                        return_type,
                    }),
                );
            }
        }

        let enum_variants = collect_enum_variants(unit);
        for decl in &unit.declarations {
            if decl.kind != DeclKind::Binding {
                continue;
            }
            let Some(fn_expr) = extract_fn_expr(&decl.value) else {
                continue;
            };
            let Some(ok_ty_expr) = implicit_error_union_ok_type(fn_expr) else {
                continue;
            };

            let inferred_errors = infer_implicit_error_union_set(
                fn_expr,
                &env,
                &mutability,
                &signatures,
                &mut types,
                &enum_variants,
                &decl.file_path,
            );
            if inferred_errors.is_empty() {
                continue;
            }
            let Some(ok_ty) = resolve_type_expr(ok_ty_expr, &mut types) else {
                continue;
            };
            let inferred_return = types.intern(Type::Errorable {
                ok: ok_ty,
                errors: inferred_errors,
            });

            if let Some(signature) = signatures.get_mut(&decl.name) {
                signature.return_type = inferred_return;
            }

            if let Some(function_ty) = env.get(&decl.name).copied() {
                if let Type::Function {
                    param_types,
                    param_names,
                    has_defaults,
                    ..
                } = types.get(function_ty).clone()
                {
                    env.insert(
                        decl.name.clone(),
                        types.intern(Type::Function {
                            param_types,
                            param_names,
                            has_defaults,
                            return_type: inferred_return,
                        }),
                    );
                }
            }
        }

        for decl in &unit.declarations {
            if decl.kind != DeclKind::Binding {
                continue;
            }
            let actual = infer_expr_type(
                &decl.value,
                &env,
                &mutability,
                &signatures,
                &mut types,
                &mut Vec::new(),
                &decl.file_path,
                None,
            );
            let mut final_ty = decl
                .annotation
                .as_ref()
                .and_then(|ty| resolve_type_expr(ty, &mut types))
                .unwrap_or(actual);

            if let Some(fn_expr) = extract_fn_expr(&decl.value) {
                if implicit_error_union_ok_type(fn_expr).is_some() {
                    if let Some(signature) = signatures.get(&decl.name) {
                        if let Type::Function {
                            param_types,
                            param_names,
                            has_defaults,
                            ..
                        } = types.get(final_ty).clone()
                        {
                            final_ty = types.intern(Type::Function {
                                param_types,
                                param_names,
                                has_defaults,
                                return_type: signature.return_type,
                            });
                        }
                    }
                }
            }

            env.insert(decl.name.clone(), final_ty);
            mutability.insert(decl.name.clone(), decl.mutable);
            out.insert(
                (unit.module_id, decl.name.clone()),
                type_to_string(final_ty, &types),
            );
        }
    }

    out
}
