use std::collections::BTreeSet;

use crate::compiler::ast::{Expr, ExprKind, Literal, Stmt};
use crate::compiler::sema::type_names::{is_float_type_name, is_int_type_name};

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
                if let Some(binding) = &capture.binding {
                    if binding.text != "_" {
                        then_scope.insert(binding.text.clone());
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
