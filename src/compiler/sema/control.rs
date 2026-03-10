use std::collections::BTreeSet;

use crate::compiler::ast::{
    BlockExpr, EnumVariantExpr, Expr, ExprKind, ForExpr, PatternKind, PatternLiteral, Stmt,
};
use crate::compiler::diagnostics::{Diagnostic, DiagnosticCode, DiagnosticPhase};
use crate::compiler::sema::module_unit::{DeclKind, ModuleUnit};

#[derive(Default)]
struct ControlContext {
    loop_depth: usize,
    labels: Vec<String>,
    or_fallback_depth: usize,
}

pub fn control_check_modules(units: &[ModuleUnit]) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();

    for unit in units {
        for decl in &unit.declarations {
            if decl.kind != DeclKind::Binding {
                continue;
            }

            let mut ctx = ControlContext::default();
            check_expr(&decl.value, &mut ctx, &decl.file_path, &mut diagnostics);
        }
    }

    diagnostics
}

fn check_expr(
    expr: &Expr,
    ctx: &mut ControlContext,
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
        ExprKind::Continue => {
            if ctx.loop_depth == 0 {
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

            if !is_match_exhaustive(match_expr) {
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

fn is_match_exhaustive(match_expr: &crate::compiler::ast::MatchExpr) -> bool {
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
        _ => enum_variant_match_assumed_exhaustive(match_expr),
    }
}

fn enum_variant_match_assumed_exhaustive(match_expr: &crate::compiler::ast::MatchExpr) -> bool {
    let mut variants = BTreeSet::new();
    for arm in &match_expr.arms {
        if arm.guard.is_some() {
            return false;
        }
        let PatternKind::EnumVariant { variant, .. } = &arm.pattern.kind else {
            return false;
        };
        variants.insert(variant.text.clone());
    }
    !variants.is_empty()
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
    ctx: &mut ControlContext,
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
            Stmt::Expr(expr) => check_expr(expr, ctx, file_path, diagnostics),
        }
    }
    if let Some(tail) = &block.tail_expr {
        check_expr(tail, ctx, file_path, diagnostics);
    }

    ctx.labels.truncate(initial_label_depth);
}

#[cfg(test)]
mod tests;
