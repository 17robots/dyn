use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;

use crate::compiler::ast::Visibility;
use crate::compiler::ast::{Binding, Expr, ExprKind, Item, Stmt, TypeExpr};
use crate::compiler::diagnostics::SourceSpan;
use crate::compiler::module_resolver::{resolve_graph_file_path, ModuleGraph, ModuleId, ModuleKey};
use crate::compiler::pipeline::ParseSession;

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
        let Some(use_pos) = line.find("use ") else {
            continue;
        };

        let prefix = &line[..use_pos];
        if !prefix.contains(":=") && !prefix.contains("=") {
            continue;
        }

        let path_start = use_pos + 4;
        let bytes = line.as_bytes();
        if path_start >= bytes.len() || bytes[path_start] != b'"' {
            continue;
        }
        let rest = &line[path_start + 1..];
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
        Item::Destructure(d) => collect_expr_uses(&d.value, None, file_path, imports, names, members),
        Item::Extern(_) => {}
        Item::ExprStmt(expr) => collect_expr_uses(expr, None, file_path, imports, names, members),
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
        Stmt::Destructure(d) => collect_expr_uses(&d.value, None, file_path, imports, names, members),
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

#[cfg(test)]
mod tests;
