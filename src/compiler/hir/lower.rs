use std::collections::{BTreeMap, BTreeSet};

use crate::compiler::ast::{
    Expr, ExprKind, Literal, PatternKind, PatternLiteral, TypeExprKind, UnaryOp,
};
use crate::compiler::hir::{
    HirCallArg, HirExpr, HirExprKind, HirIfCapture, HirItem, HirLiteral, HirMatchArm, HirModule,
    HirPattern, HirProgram,
};
use crate::compiler::sema::analyze::SemanticSession;
use crate::compiler::sema::module_unit::ModuleUnit;

#[derive(Default)]
struct MethodIndex {
    type_names: BTreeSet<String>,
    static_methods: BTreeMap<(String, String), String>,
    instance_methods: BTreeMap<(String, String), MethodTarget>,
    struct_field_nominals: BTreeMap<(String, String), String>,
}

#[derive(Copy, Clone)]
enum ReceiverStyle {
    Value,
    Ptr,
    MutPtr,
}

#[derive(Clone)]
struct MethodTarget {
    name: String,
    receiver: ReceiverStyle,
}

#[derive(Clone)]
struct BindingInfo {
    nominal_type: String,
    mutable: bool,
}

pub fn lower_module_units(units: &[ModuleUnit]) -> HirProgram {
    lower_module_units_with_metadata(units, None, &BTreeMap::new())
}

pub fn lower_module_units_with_metadata(
    units: &[ModuleUnit],
    sema: Option<&SemanticSession>,
    inferred_types: &BTreeMap<(crate::compiler::module_resolver::ModuleId, String), String>,
) -> HirProgram {
    let def_map = sema
        .map(|session| {
            let mut map = BTreeMap::new();
            for module in &session.modules {
                for decl in &module.declarations {
                    map.insert((module.module_id, decl.name.clone()), decl.def_id.0);
                }
            }
            map
        })
        .unwrap_or_default();

    let modules = units
        .iter()
        .map(|unit| {
            let method_index = build_method_index(unit);
            let mut items = unit
                .declarations
                .iter()
                .map(|decl| HirItem {
                    name: decl.name.clone(),
                    def_id: def_map.get(&(unit.module_id, decl.name.clone())).copied(),
                    visibility: decl.visibility,
                    mutable: decl.mutable,
                    type_hint: decl.annotation.as_ref().map(type_expr_to_string),
                    inferred_type: inferred_types
                        .get(&(unit.module_id, decl.name.clone()))
                        .cloned(),
                    value: rewrite_method_calls(lower_expr(&decl.value), &method_index),
                    span: decl.span,
                })
                .collect::<Vec<_>>();

            for decl in &unit.declarations {
                append_member_function_items(&mut items, decl, &method_index);
            }

            HirModule {
                module_id: unit.module_id,
                key: unit.key.clone(),
                items,
            }
        })
        .collect::<Vec<_>>();

    HirProgram { modules }
}

fn build_method_index(unit: &ModuleUnit) -> MethodIndex {
    let mut index = MethodIndex::default();
    for decl in &unit.declarations {
        let Some(struct_ty) = decl_struct_type(decl) else {
            continue;
        };
        index.type_names.insert(decl.name.clone());
        for member in &struct_ty.members {
            let ExprKind::Fn(fn_expr) = &member.value.kind else {
                continue;
            };
            let synthetic = format!("{}__{}", decl.name, member.name.text);
            index.static_methods.insert(
                (decl.name.clone(), member.name.text.clone()),
                synthetic.clone(),
            );
            if let Some(receiver) = instance_receiver_style(fn_expr, &decl.name) {
                index.instance_methods.insert(
                    (decl.name.clone(), member.name.text.clone()),
                    MethodTarget {
                        name: synthetic,
                        receiver,
                    },
                );
            }
        }
        for field in &struct_ty.fields {
            if let TypeExprKind::Named(named) = &field.ty.kind {
                index.struct_field_nominals.insert(
                    (decl.name.clone(), field.name.text.clone()),
                    named.text.clone(),
                );
            }
        }
    }
    index
}

fn instance_receiver_style(
    fn_expr: &crate::compiler::ast::FnExpr,
    type_name: &str,
) -> Option<ReceiverStyle> {
    let Some(first) = fn_expr.params.first() else {
        return None;
    };
    let Some(first_ty) = &first.ty else {
        return None;
    };
    if matches!(&first_ty.kind, TypeExprKind::Named(ident) if ident.text == type_name) {
        return Some(ReceiverStyle::Value);
    }
    if let TypeExprKind::Pointer { mutable, inner } = &first_ty.kind {
        if matches!(inner.kind, TypeExprKind::Named(ref ident) if ident.text == type_name) {
            return Some(if *mutable {
                ReceiverStyle::MutPtr
            } else {
                ReceiverStyle::Ptr
            });
        }
    }
    None
}

fn append_member_function_items(
    items: &mut Vec<HirItem>,
    decl: &crate::compiler::sema::module_unit::DeclStub,
    method_index: &MethodIndex,
) {
    let Some(struct_ty) = decl_struct_type(decl) else {
        return;
    };
    for member in &struct_ty.members {
        let ExprKind::Fn(fn_expr) = &member.value.kind else {
            continue;
        };
        let Some(name) = method_index
            .static_methods
            .get(&(decl.name.clone(), member.name.text.clone()))
        else {
            continue;
        };
        items.push(HirItem {
            name: name.clone(),
            def_id: None,
            visibility: decl.visibility,
            mutable: false,
            type_hint: None,
            inferred_type: fn_expr.return_type.as_ref().map(type_expr_to_string),
            value: rewrite_method_calls(lower_expr(&member.value), method_index),
            span: member.value.span,
        });
    }
}

fn decl_struct_type(
    decl: &crate::compiler::sema::module_unit::DeclStub,
) -> Option<&crate::compiler::ast::StructType> {
    match &decl.value.kind {
        ExprKind::TypeLiteral(type_lit) => {
            if let TypeExprKind::Struct(struct_ty) = &type_lit.kind {
                Some(struct_ty)
            } else {
                None
            }
        }
        ExprKind::Fn(fn_expr) => match &fn_expr.body {
            crate::compiler::ast::FnBody::ArrowExpr(expr) => expr_type_literal_struct(expr),
            crate::compiler::ast::FnBody::Block(block) => {
                if let Some(tail) = &block.tail_expr {
                    expr_type_literal_struct(tail)
                } else {
                    None
                }
            }
        },
        _ => None,
    }
}

fn expr_type_literal_struct(expr: &Expr) -> Option<&crate::compiler::ast::StructType> {
    let ExprKind::TypeLiteral(type_lit) = &expr.kind else {
        return None;
    };
    let TypeExprKind::Struct(struct_ty) = &type_lit.kind else {
        return None;
    };
    Some(struct_ty)
}

fn rewrite_method_calls(expr: HirExpr, method_index: &MethodIndex) -> HirExpr {
    let mut scopes = vec![BTreeMap::<String, BindingInfo>::new()];
    rewrite_method_calls_with_scopes(expr, method_index, &mut scopes)
}

fn rewrite_method_calls_with_scopes(
    expr: HirExpr,
    method_index: &MethodIndex,
    scopes: &mut Vec<BTreeMap<String, BindingInfo>>,
) -> HirExpr {
    let span = expr.span;
    let kind = match expr.kind {
        HirExprKind::Call { callee, args } => {
            let callee = rewrite_method_calls_with_scopes(*callee, method_index, scopes);
            let mut args = args
                .into_iter()
                .map(|arg| HirCallArg {
                    name: arg.name,
                    value: rewrite_method_calls_with_scopes(arg.value, method_index, scopes),
                })
                .collect::<Vec<_>>();
            if let HirExprKind::FieldAccess { base, field } = callee.kind {
                if is_type_receiver_expr(&base, scopes, method_index) {
                    if let Some(base_nominal) = infer_nominal_type(&base, scopes, method_index) {
                        if let Some(synth) = method_index
                            .static_methods
                            .get(&(base_nominal, field.clone()))
                        {
                            return HirExpr {
                                kind: HirExprKind::Call {
                                    callee: Box::new(HirExpr {
                                        kind: HirExprKind::Ident(synth.clone()),
                                        span,
                                    }),
                                    args,
                                },
                                span,
                            };
                        }
                    }
                }

                if let Some(base_nominal) = infer_nominal_type(&base, scopes, method_index) {
                    if let Some(target) = method_index
                        .instance_methods
                        .get(&(base_nominal, field.clone()))
                    {
                        if matches!(target.receiver, ReceiverStyle::MutPtr)
                            && !can_take_mut_ref(&base, scopes)
                        {
                            return HirExpr {
                                kind: HirExprKind::Call {
                                    callee: Box::new(HirExpr {
                                        kind: HirExprKind::FieldAccess {
                                            base: Box::new(rewrite_method_calls_with_scopes(
                                                *base,
                                                method_index,
                                                scopes,
                                            )),
                                            field,
                                        },
                                        span,
                                    }),
                                    args,
                                },
                                span,
                            };
                        }

                        let mut method_args = Vec::with_capacity(args.len() + 1);
                        let base_value =
                            rewrite_method_calls_with_scopes(*base, method_index, scopes);
                        let receiver_expr = match target.receiver {
                            ReceiverStyle::Value => base_value,
                            ReceiverStyle::Ptr => HirExpr {
                                kind: HirExprKind::Unary {
                                    op: UnaryOp::Ref,
                                    expr: Box::new(base_value),
                                },
                                span,
                            },
                            ReceiverStyle::MutPtr => HirExpr {
                                kind: HirExprKind::Unary {
                                    op: UnaryOp::Ref,
                                    expr: Box::new(base_value),
                                },
                                span,
                            },
                        };
                        method_args.push(HirCallArg {
                            name: None,
                            value: receiver_expr,
                        });
                        method_args.append(&mut args);
                        return HirExpr {
                            kind: HirExprKind::Call {
                                callee: Box::new(HirExpr {
                                    kind: HirExprKind::Ident(target.name.clone()),
                                    span,
                                }),
                                args: method_args,
                            },
                            span,
                        };
                    }
                }

                HirExprKind::Call {
                    callee: Box::new(HirExpr {
                        kind: HirExprKind::FieldAccess {
                            base: Box::new(rewrite_method_calls_with_scopes(
                                *base,
                                method_index,
                                scopes,
                            )),
                            field,
                        },
                        span,
                    }),
                    args,
                }
            } else {
                HirExprKind::Call {
                    callee: Box::new(callee),
                    args,
                }
            }
        }
        HirExprKind::Unary { op, expr } => HirExprKind::Unary {
            op,
            expr: Box::new(rewrite_method_calls_with_scopes(
                *expr,
                method_index,
                scopes,
            )),
        },
        HirExprKind::Binary { op, left, right } => HirExprKind::Binary {
            op,
            left: Box::new(rewrite_method_calls_with_scopes(
                *left,
                method_index,
                scopes,
            )),
            right: Box::new(rewrite_method_calls_with_scopes(
                *right,
                method_index,
                scopes,
            )),
        },
        HirExprKind::Assign { op, target, value } => HirExprKind::Assign {
            op,
            target: Box::new(rewrite_method_calls_with_scopes(
                *target,
                method_index,
                scopes,
            )),
            value: Box::new(rewrite_method_calls_with_scopes(
                *value,
                method_index,
                scopes,
            )),
        },
        HirExprKind::FieldAccess { base, field } => HirExprKind::FieldAccess {
            base: Box::new(rewrite_method_calls_with_scopes(
                *base,
                method_index,
                scopes,
            )),
            field,
        },
        HirExprKind::DerefAccess { base } => HirExprKind::DerefAccess {
            base: Box::new(rewrite_method_calls_with_scopes(
                *base,
                method_index,
                scopes,
            )),
        },
        HirExprKind::Index { base, index } => HirExprKind::Index {
            base: Box::new(rewrite_method_calls_with_scopes(
                *base,
                method_index,
                scopes,
            )),
            index: Box::new(rewrite_method_calls_with_scopes(
                *index,
                method_index,
                scopes,
            )),
        },
        HirExprKind::Slice {
            base,
            start,
            end,
            inclusive,
        } => HirExprKind::Slice {
            base: Box::new(rewrite_method_calls_with_scopes(
                *base,
                method_index,
                scopes,
            )),
            start: start.map(|expr| {
                Box::new(rewrite_method_calls_with_scopes(
                    *expr,
                    method_index,
                    scopes,
                ))
            }),
            end: end.map(|expr| {
                Box::new(rewrite_method_calls_with_scopes(
                    *expr,
                    method_index,
                    scopes,
                ))
            }),
            inclusive,
        },
        HirExprKind::StructLiteral { root_type, fields } => HirExprKind::StructLiteral {
            root_type,
            fields: fields
                .into_iter()
                .map(|(name, expr)| {
                    (
                        name,
                        rewrite_method_calls_with_scopes(expr, method_index, scopes),
                    )
                })
                .collect(),
        },
        HirExprKind::EnumVariant { variant, payload } => HirExprKind::EnumVariant {
            variant,
            payload: payload
                .into_iter()
                .map(|expr| rewrite_method_calls_with_scopes(expr, method_index, scopes))
                .collect(),
        },
        HirExprKind::Block { body } => {
            scopes.push(BTreeMap::new());
            let mut out = Vec::with_capacity(body.len());
            for expr in body {
                let rewritten = rewrite_method_calls_with_scopes(expr, method_index, scopes);
                if let HirExprKind::Let { name, value, .. } = &rewritten.kind {
                    if let Some(nominal) = infer_nominal_type(value, scopes, method_index) {
                        if let Some(scope) = scopes.last_mut() {
                            let mutable = matches!(&rewritten.kind, HirExprKind::Let { mutable, .. } if *mutable);
                            scope.insert(
                                name.clone(),
                                BindingInfo {
                                    nominal_type: nominal,
                                    mutable,
                                },
                            );
                        }
                    }
                }
                out.push(rewritten);
            }
            scopes.pop();
            HirExprKind::Block { body: out }
        }
        HirExprKind::Let {
            name,
            mutable,
            value,
        } => HirExprKind::Let {
            name,
            mutable,
            value: Box::new(rewrite_method_calls_with_scopes(
                *value,
                method_index,
                scopes,
            )),
        },
        HirExprKind::If {
            condition,
            capture,
            then_branch,
            else_branch,
        } => HirExprKind::If {
            condition: Box::new(rewrite_method_calls_with_scopes(
                *condition,
                method_index,
                scopes,
            )),
            capture,
            then_branch: Box::new(rewrite_method_calls_with_scopes(
                *then_branch,
                method_index,
                scopes,
            )),
            else_branch: else_branch.map(|expr| {
                Box::new(rewrite_method_calls_with_scopes(
                    *expr,
                    method_index,
                    scopes,
                ))
            }),
        },
        HirExprKind::Match { value, arms } => HirExprKind::Match {
            value: Box::new(rewrite_method_calls_with_scopes(
                *value,
                method_index,
                scopes,
            )),
            arms: arms
                .into_iter()
                .map(|arm| HirMatchArm {
                    pattern: arm.pattern,
                    guard: arm
                        .guard
                        .map(|expr| rewrite_method_calls_with_scopes(expr, method_index, scopes)),
                    value: rewrite_method_calls_with_scopes(arm.value, method_index, scopes),
                })
                .collect(),
        },
        HirExprKind::For(for_expr) => HirExprKind::For(for_expr),
        HirExprKind::Break { value } => HirExprKind::Break {
            value: value.map(|expr| {
                Box::new(rewrite_method_calls_with_scopes(
                    *expr,
                    method_index,
                    scopes,
                ))
            }),
        },
        HirExprKind::Return { value } => HirExprKind::Return {
            value: value.map(|expr| {
                Box::new(rewrite_method_calls_with_scopes(
                    *expr,
                    method_index,
                    scopes,
                ))
            }),
        },
        HirExprKind::Defer {
            error_binding,
            body,
        } => HirExprKind::Defer {
            error_binding,
            body: Box::new(rewrite_method_calls_with_scopes(
                *body,
                method_index,
                scopes,
            )),
        },
        HirExprKind::OptionalUnwrap { value } => HirExprKind::OptionalUnwrap {
            value: Box::new(rewrite_method_calls_with_scopes(
                *value,
                method_index,
                scopes,
            )),
        },
        HirExprKind::ErrorUnwrap { value } => HirExprKind::ErrorUnwrap {
            value: Box::new(rewrite_method_calls_with_scopes(
                *value,
                method_index,
                scopes,
            )),
        },
        HirExprKind::OrElse {
            value,
            error_binding,
            fallback,
        } => HirExprKind::OrElse {
            value: Box::new(rewrite_method_calls_with_scopes(
                *value,
                method_index,
                scopes,
            )),
            error_binding,
            fallback: Box::new(rewrite_method_calls_with_scopes(
                *fallback,
                method_index,
                scopes,
            )),
        },
        HirExprKind::Comptime { expr } => HirExprKind::Comptime {
            expr: Box::new(rewrite_method_calls_with_scopes(
                *expr,
                method_index,
                scopes,
            )),
        },
        HirExprKind::Inline { expr } => HirExprKind::Inline {
            expr: Box::new(rewrite_method_calls_with_scopes(
                *expr,
                method_index,
                scopes,
            )),
        },
        HirExprKind::Function {
            params,
            param_types,
            param_defaults,
            body,
        } => HirExprKind::Function {
            params,
            param_types,
            param_defaults: param_defaults
                .into_iter()
                .map(|default| {
                    default.map(|expr| rewrite_method_calls_with_scopes(expr, method_index, scopes))
                })
                .collect(),
            body: Box::new(rewrite_method_calls_with_scopes(
                *body,
                method_index,
                scopes,
            )),
        },
        other => other,
    };
    HirExpr { kind, span }
}

fn infer_nominal_type(
    expr: &HirExpr,
    scopes: &[BTreeMap<String, BindingInfo>],
    method_index: &MethodIndex,
) -> Option<String> {
    match &expr.kind {
        HirExprKind::StructLiteral {
            root_type: Some(root),
            ..
        } => Some(root.clone()),
        HirExprKind::Ident(name) => scopes
            .iter()
            .rev()
            .find_map(|scope| scope.get(name).map(|info| info.nominal_type.clone()))
            .or_else(|| {
                method_index
                    .type_names
                    .contains(name)
                    .then_some(name.clone())
            }),
        HirExprKind::FieldAccess { base, field } => infer_nominal_type(base, scopes, method_index)
            .and_then(|base_nominal| {
                method_index
                    .struct_field_nominals
                    .get(&(base_nominal, field.clone()))
                    .cloned()
            }),
        HirExprKind::DerefAccess { base } => infer_nominal_type(base, scopes, method_index),
        HirExprKind::Call { callee, .. } => match &callee.kind {
            HirExprKind::Ident(name) if method_index.type_names.contains(name) => {
                Some(name.clone())
            }
            HirExprKind::FieldAccess { base, field } => {
                let base_nominal = infer_nominal_type(base, scopes, method_index)?;
                if method_index
                    .instance_methods
                    .contains_key(&(base_nominal.clone(), field.clone()))
                {
                    Some(base_nominal)
                } else {
                    None
                }
            }
            _ => None,
        },
        _ => None,
    }
}

fn is_type_receiver_expr(
    expr: &HirExpr,
    scopes: &[BTreeMap<String, BindingInfo>],
    method_index: &MethodIndex,
) -> bool {
    match &expr.kind {
        HirExprKind::Ident(name) => {
            method_index.type_names.contains(name)
                && !scopes.iter().rev().any(|scope| scope.contains_key(name))
        }
        HirExprKind::Call { callee, .. } => {
            matches!(&callee.kind, HirExprKind::Ident(name) if method_index.type_names.contains(name))
        }
        _ => false,
    }
}

fn can_take_mut_ref(expr: &HirExpr, scopes: &[BTreeMap<String, BindingInfo>]) -> bool {
    match &expr.kind {
        HirExprKind::Ident(name) => scopes
            .iter()
            .rev()
            .find_map(|scope| scope.get(name).map(|info| info.mutable))
            .unwrap_or(false),
        HirExprKind::FieldAccess { base, .. }
        | HirExprKind::DerefAccess { base }
        | HirExprKind::Index { base, .. } => can_take_mut_ref(base, scopes),
        _ => false,
    }
}

fn lower_expr(expr: &Expr) -> HirExpr {
    let kind = match &expr.kind {
        ExprKind::Literal(literal) => HirExprKind::Literal(match literal {
            Literal::Integer(value) => HirLiteral::Integer(value.clone()),
            Literal::Float(value) => HirLiteral::Float(value.clone()),
            Literal::String(value) => HirLiteral::String(value.clone()),
            Literal::Char(value) => HirLiteral::Char(*value),
            Literal::Bool(value) => HirLiteral::Bool(*value),
            Literal::Null => HirLiteral::Null,
        }),
        ExprKind::Ident(ident) | ExprKind::BuiltinIdent(ident) => {
            HirExprKind::Ident(ident.text.clone())
        }
        ExprKind::Unary { expr, op } => HirExprKind::Unary {
            op: *op,
            expr: Box::new(lower_expr(expr)),
        },
        ExprKind::Binary { left, right, op } => HirExprKind::Binary {
            op: *op,
            left: Box::new(lower_expr(left)),
            right: Box::new(lower_expr(right)),
        },
        ExprKind::Assign { target, value, op } => HirExprKind::Assign {
            op: *op,
            target: Box::new(lower_expr(target)),
            value: Box::new(lower_expr(value)),
        },
        ExprKind::Call(call) => HirExprKind::Call {
            callee: Box::new(lower_expr(&call.callee)),
            args: call
                .args
                .iter()
                .map(|arg| HirCallArg {
                    name: arg.name.as_ref().map(|ident| ident.text.clone()),
                    value: lower_expr(&arg.value),
                })
                .collect(),
        },
        ExprKind::FieldAccess { base, field } => HirExprKind::FieldAccess {
            base: Box::new(lower_expr(base)),
            field: field.text.clone(),
        },
        ExprKind::DerefAccess { base } => HirExprKind::DerefAccess {
            base: Box::new(lower_expr(base)),
        },
        ExprKind::Index { base, index } => HirExprKind::Index {
            base: Box::new(lower_expr(base)),
            index: Box::new(lower_expr(index)),
        },
        ExprKind::Slice(slice) => HirExprKind::Slice {
            base: Box::new(lower_expr(&slice.base)),
            start: slice.start.as_ref().map(|expr| Box::new(lower_expr(expr))),
            end: slice.end.as_ref().map(|expr| Box::new(lower_expr(expr))),
            inclusive: slice.inclusive,
        },
        ExprKind::StructLiteral(lit) => HirExprKind::StructLiteral {
            root_type: lit.root_type.as_ref().map(|ident| ident.text.clone()),
            fields: lit
                .fields
                .iter()
                .map(|field| (field.name.text.clone(), lower_expr(&field.value)))
                .collect(),
        },
        ExprKind::ArrayLiteral(elements) => HirExprKind::StructLiteral {
            root_type: None,
            fields: elements
                .iter()
                .enumerate()
                .map(|(idx, element)| (format!("__{idx}"), lower_expr(element)))
                .collect(),
        },
        ExprKind::TupleLiteral(elements) => HirExprKind::StructLiteral {
            root_type: None,
            fields: elements
                .iter()
                .enumerate()
                .map(|(idx, element)| (format!("__{idx}"), lower_expr(element)))
                .collect(),
        },
        ExprKind::EnumVariantConstruct(variant) => HirExprKind::EnumVariant {
            variant: variant.variant.text.clone(),
            payload: variant.payload.iter().map(lower_expr).collect(),
        },
        ExprKind::Block(block) => HirExprKind::Block {
            body: {
                let mut body = block
                    .statements
                    .iter()
                    .map(|stmt| match stmt {
                        crate::compiler::ast::Stmt::Binding(binding) => HirExpr {
                            kind: HirExprKind::Let {
                                name: binding.name.text.clone(),
                                mutable: binding.mutable,
                                value: Box::new(lower_expr(&binding.value)),
                            },
                            span: binding.span,
                        },
                        crate::compiler::ast::Stmt::Expr(expr) => lower_expr(expr),
                    })
                    .collect::<Vec<_>>();
                if let Some(tail) = &block.tail_expr {
                    body.push(lower_expr(tail));
                }
                body
            },
        },
        ExprKind::If(if_expr) => HirExprKind::If {
            condition: Box::new(lower_expr(&if_expr.condition)),
            capture: if_expr.capture.as_ref().map(|capture| HirIfCapture {
                binding: capture.binding.as_ref().map(|ident| ident.text.clone()),
            }),
            then_branch: Box::new(lower_expr(&if_expr.then_branch)),
            else_branch: if_expr
                .else_branch
                .as_ref()
                .map(|expr| Box::new(lower_expr(expr))),
        },
        ExprKind::Match(match_expr) => HirExprKind::Match {
            value: Box::new(lower_expr(&match_expr.scrutinee)),
            arms: match_expr
                .arms
                .iter()
                .map(|arm| HirMatchArm {
                    pattern: lower_pattern(&arm.pattern.kind),
                    guard: arm.guard.as_ref().map(lower_expr),
                    value: lower_expr(&arm.value),
                })
                .collect(),
        },
        ExprKind::For(for_expr) => HirExprKind::For(match for_expr {
            crate::compiler::ast::ForExpr::Infinite { body } => {
                crate::compiler::hir::HirForExpr::Infinite {
                    body: Box::new(lower_expr(body)),
                }
            }
            crate::compiler::ast::ForExpr::WhileLike { condition, body } => {
                crate::compiler::hir::HirForExpr::WhileLike {
                    condition: Box::new(lower_expr(condition)),
                    body: Box::new(lower_expr(body)),
                }
            }
            crate::compiler::ast::ForExpr::Range {
                start,
                end,
                inclusive,
                binding,
                body,
            } => crate::compiler::hir::HirForExpr::Range {
                start: Box::new(lower_expr(start)),
                end: Box::new(lower_expr(end)),
                inclusive: *inclusive,
                binding: binding.as_ref().map(|ident| ident.text.clone()),
                body: Box::new(lower_expr(body)),
            },
            crate::compiler::ast::ForExpr::Iterate {
                iterable,
                binding,
                body,
            } => crate::compiler::hir::HirForExpr::Iterate {
                iterable: Box::new(lower_expr(iterable)),
                binding: binding.as_ref().map(|ident| ident.text.clone()),
                body: Box::new(lower_expr(body)),
            },
        }),
        ExprKind::Break(brk) => HirExprKind::Break {
            value: brk.value.as_ref().map(|value| Box::new(lower_expr(value))),
        },
        ExprKind::Continue => HirExprKind::Continue,
        ExprKind::Return { value } => HirExprKind::Return {
            value: value.as_ref().map(|expr| Box::new(lower_expr(expr))),
        },
        ExprKind::Defer(defer_expr) => HirExprKind::Defer {
            error_binding: defer_expr
                .error_binding
                .as_ref()
                .map(|ident| ident.text.clone()),
            body: Box::new(lower_expr(&defer_expr.body)),
        },
        ExprKind::OptionalUnwrap { expr } => HirExprKind::OptionalUnwrap {
            value: Box::new(lower_expr(expr)),
        },
        ExprKind::ErrorUnwrap { expr } => HirExprKind::ErrorUnwrap {
            value: Box::new(lower_expr(expr)),
        },
        ExprKind::OrElse(or_else) => HirExprKind::OrElse {
            value: Box::new(lower_expr(&or_else.value)),
            error_binding: or_else
                .error_binding
                .as_ref()
                .map(|ident| ident.text.clone()),
            fallback: Box::new(lower_expr(&or_else.fallback)),
        },
        ExprKind::Use { path } => HirExprKind::Use { path: path.clone() },
        ExprKind::TypeLiteral(ty) => HirExprKind::TypeLiteral(type_expr_to_string(ty)),
        ExprKind::Comptime { expr } => HirExprKind::Comptime {
            expr: Box::new(lower_expr(expr)),
        },
        ExprKind::Inline { expr } => HirExprKind::Inline {
            expr: Box::new(lower_expr(expr)),
        },
        ExprKind::Fn(fn_expr) => {
            let body = match &fn_expr.body {
                crate::compiler::ast::FnBody::Block(block) => HirExpr {
                    kind: HirExprKind::Block {
                        body: {
                            let mut body = block
                                .statements
                                .iter()
                                .map(|stmt| match stmt {
                                    crate::compiler::ast::Stmt::Binding(binding) => HirExpr {
                                        kind: HirExprKind::Let {
                                            name: binding.name.text.clone(),
                                            mutable: binding.mutable,
                                            value: Box::new(lower_expr(&binding.value)),
                                        },
                                        span: binding.span,
                                    },
                                    crate::compiler::ast::Stmt::Expr(expr) => lower_expr(expr),
                                })
                                .collect::<Vec<_>>();
                            if let Some(tail) = &block.tail_expr {
                                body.push(lower_expr(tail));
                            }
                            body
                        },
                    },
                    span: expr.span,
                },
                crate::compiler::ast::FnBody::ArrowExpr(arrow_expr) => lower_expr(arrow_expr),
            };
            HirExprKind::Function {
                params: fn_expr
                    .params
                    .iter()
                    .map(|param| param.name.text.clone())
                    .collect(),
                param_types: fn_expr
                    .params
                    .iter()
                    .map(|param| param.ty.as_ref().map(type_expr_to_string))
                    .collect(),
                param_defaults: fn_expr
                    .params
                    .iter()
                    .map(|param| param.default_value.as_ref().map(lower_expr))
                    .collect(),
                body: Box::new(body),
            }
        }
    };

    HirExpr {
        kind,
        span: expr.span,
    }
}

fn lower_pattern(pattern: &PatternKind) -> HirPattern {
    match pattern {
        PatternKind::Wildcard => HirPattern::Wildcard,
        PatternKind::IdentBind(ident) => HirPattern::IdentBind(ident.text.clone()),
        PatternKind::Literal(lit) => HirPattern::Literal(match lit {
            PatternLiteral::Integer(v) => HirLiteral::Integer(v.clone()),
            PatternLiteral::Float(v) => HirLiteral::Float(v.clone()),
            PatternLiteral::String(v) => HirLiteral::String(v.clone()),
            PatternLiteral::Char(v) => HirLiteral::Char(*v),
            PatternLiteral::Bool(v) => HirLiteral::Bool(*v),
            PatternLiteral::Null => HirLiteral::Null,
        }),
        PatternKind::EnumVariant {
            root,
            variant,
            bindings,
        } => HirPattern::EnumVariant {
            root: root.as_ref().map(|ident| ident.text.clone()),
            variant: variant.text.clone(),
            bindings: bindings.iter().map(|ident| ident.text.clone()).collect(),
        },
        PatternKind::Range {
            start,
            end,
            inclusive,
        } => {
            let Some(start_lit) = lower_pattern_literal(&start.kind) else {
                return HirPattern::Other;
            };
            let Some(end_lit) = lower_pattern_literal(&end.kind) else {
                return HirPattern::Other;
            };
            HirPattern::RangeLiteral {
                start: start_lit,
                end: end_lit,
                inclusive: *inclusive,
            }
        }
        PatternKind::Typed { pattern, .. } => lower_pattern(&pattern.kind),
    }
}

fn lower_pattern_literal(pattern: &PatternKind) -> Option<HirLiteral> {
    match pattern {
        PatternKind::Literal(PatternLiteral::Integer(v)) => Some(HirLiteral::Integer(v.clone())),
        PatternKind::Literal(PatternLiteral::Float(v)) => Some(HirLiteral::Float(v.clone())),
        PatternKind::Literal(PatternLiteral::String(v)) => Some(HirLiteral::String(v.clone())),
        PatternKind::Literal(PatternLiteral::Char(v)) => Some(HirLiteral::Char(*v)),
        PatternKind::Literal(PatternLiteral::Bool(v)) => Some(HirLiteral::Bool(*v)),
        PatternKind::Literal(PatternLiteral::Null) => Some(HirLiteral::Null),
        _ => None,
    }
}

fn type_expr_to_string(type_expr: &crate::compiler::ast::TypeExpr) -> String {
    match &type_expr.kind {
        TypeExprKind::Named(ident) => ident.text.clone(),
        TypeExprKind::Applied { callee, args } => {
            let rendered = args
                .iter()
                .map(type_expr_to_string)
                .collect::<Vec<_>>()
                .join(", ");
            format!("{}({})", callee.text, rendered)
        }
        TypeExprKind::Optional { inner } => format!("?{}", type_expr_to_string(inner)),
        TypeExprKind::Pointer { mutable, inner } => {
            if *mutable {
                format!("*mut {}", type_expr_to_string(inner))
            } else {
                format!("*{}", type_expr_to_string(inner))
            }
        }
        TypeExprKind::Slice { mutable, element } => {
            if *mutable {
                format!("[]mut {}", type_expr_to_string(element))
            } else {
                format!("[]{}", type_expr_to_string(element))
            }
        }
        TypeExprKind::Array { element, .. } => format!("[?]{}", type_expr_to_string(element)),
        TypeExprKind::Errorable { ok, errors } => {
            let list = errors
                .iter()
                .map(|ident| ident.text.clone())
                .collect::<Vec<_>>()
                .join(",");
            format!("{}!{}", type_expr_to_string(ok), list)
        }
        TypeExprKind::Struct(struct_ty) => {
            let fields = struct_ty
                .fields
                .iter()
                .map(|field| format!("{}:{}", field.name.text, type_expr_to_string(&field.ty)))
                .collect::<Vec<_>>()
                .join(",");
            format!("struct{{{fields}}}")
        }
        TypeExprKind::Function(fn_ty) => {
            let params = fn_ty
                .params
                .iter()
                .map(|param| type_expr_to_string(&param.ty))
                .collect::<Vec<_>>()
                .join(",");
            let ret = type_expr_to_string(&fn_ty.return_type);
            format!("fn({params})->{ret}")
        }
        _ => "<complex-type>".to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::compiler::pipeline::analyze_project;
    use crate::compiler::sema::typeck::infer_binding_type_strings;
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn make_temp_dir() -> PathBuf {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("time should be monotonic")
            .as_nanos();
        let path = std::env::temp_dir().join(format!("dyn_hir_{unique}"));
        fs::create_dir_all(&path).expect("temp directory should be created");
        path
    }

    #[test]
    fn lowers_module_units_into_hir_program() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na: i32 = 1\nb := use \"other\"\n",
        )
        .expect("file should be written");
        fs::write(root.join("other.dyn"), "module other\nx := 1\n")
            .expect("file should be written");

        let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
        let inferred = infer_binding_type_strings(&units);
        let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
        assert_eq!(hir.modules.len(), 2);
        assert!(hir
            .modules
            .iter()
            .any(|module| module.key.module_name == "main" && module.items.len() >= 2));
        let main_module = hir
            .modules
            .iter()
            .find(|module| module.key.module_name == "main")
            .expect("main module should exist");
        assert!(main_module
            .items
            .iter()
            .any(|item| item.def_id.is_some() && item.inferred_type.is_some()));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn rewrites_struct_member_method_calls_into_synthetic_functions() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { new := () i32 => 44, do := (self: Thing) i32 => 55 }\nmain := () i32 {\n  t := Thing{}\n  Thing.new()\n  t.do()\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
        let inferred = infer_binding_type_strings(&units);
        let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
        let main_module = hir
            .modules
            .iter()
            .find(|module| module.key.module_name == "main")
            .expect("main module should exist");
        assert!(main_module
            .items
            .iter()
            .any(|item| item.name == "Thing__new"));
        assert!(main_module
            .items
            .iter()
            .any(|item| item.name == "Thing__do"));

        let main_item = main_module
            .items
            .iter()
            .find(|item| item.name == "main")
            .expect("main binding should exist");
        let HirExprKind::Function { body, .. } = &main_item.value.kind else {
            panic!("main should lower to function")
        };
        let HirExprKind::Block { body } = &body.kind else {
            panic!("main body should be block")
        };
        assert!(body.iter().any(|expr| {
            matches!(
                &expr.kind,
                HirExprKind::Call { callee, .. }
                    if matches!(&callee.kind, HirExprKind::Ident(name) if name == "Thing__new")
            )
        }));
        assert!(body.iter().any(|expr| {
            matches!(
                &expr.kind,
                HirExprKind::Call { callee, .. }
                    if matches!(&callee.kind, HirExprKind::Ident(name) if name == "Thing__do")
            )
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn rewrites_type_constructor_static_method_call_into_synthetic_function() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nVec := (T: comp type) type => struct { new := () i32 => 44 }\nmain := () i32 {\n  Vec(i32).new()\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
        let inferred = infer_binding_type_strings(&units);
        let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
        let main_module = hir
            .modules
            .iter()
            .find(|module| module.key.module_name == "main")
            .expect("main module should exist");
        assert!(main_module.items.iter().any(|item| item.name == "Vec__new"));

        let main_item = main_module
            .items
            .iter()
            .find(|item| item.name == "main")
            .expect("main binding should exist");
        let HirExprKind::Function { body, .. } = &main_item.value.kind else {
            panic!("main should lower to function")
        };
        let HirExprKind::Block { body } = &body.kind else {
            panic!("main body should be block")
        };
        assert!(body.iter().any(|expr| {
            matches!(
                &expr.kind,
                HirExprKind::Call { callee, .. }
                    if matches!(&callee.kind, HirExprKind::Ident(name) if name == "Vec__new")
            )
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn rewrites_pointer_receiver_method_call_with_implicit_ref() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *Thing) i32 => 1 }\nmain := () i32 {\n  t := Thing{}\n  t.touch()\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
        let inferred = infer_binding_type_strings(&units);
        let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
        let main_module = hir
            .modules
            .iter()
            .find(|module| module.key.module_name == "main")
            .expect("main module should exist");
        let main_item = main_module
            .items
            .iter()
            .find(|item| item.name == "main")
            .expect("main binding should exist");
        let HirExprKind::Function { body, .. } = &main_item.value.kind else {
            panic!("main should lower to function")
        };
        let HirExprKind::Block { body } = &body.kind else {
            panic!("main body should be block")
        };
        assert!(body.iter().any(|expr| {
            matches!(
                &expr.kind,
                HirExprKind::Call { callee, args }
                    if matches!(&callee.kind, HirExprKind::Ident(name) if name == "Thing__touch")
                        && matches!(args.first().map(|arg| &arg.value.kind), Some(HirExprKind::Unary { op: UnaryOp::Ref, .. }))
            )
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn rewrites_mut_pointer_receiver_method_call_for_mutable_binding() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nmain := () i32 {\n  mut t := Thing{}\n  t.touch()\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
        let inferred = infer_binding_type_strings(&units);
        let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
        let main_module = hir
            .modules
            .iter()
            .find(|module| module.key.module_name == "main")
            .expect("main module should exist");
        let main_item = main_module
            .items
            .iter()
            .find(|item| item.name == "main")
            .expect("main binding should exist");
        let HirExprKind::Function { body, .. } = &main_item.value.kind else {
            panic!("main should lower to function")
        };
        let HirExprKind::Block { body } = &body.kind else {
            panic!("main body should be block")
        };
        assert!(body.iter().any(|expr| {
            matches!(
                &expr.kind,
                HirExprKind::Call { callee, args }
                    if matches!(&callee.kind, HirExprKind::Ident(name) if name == "Thing__touch")
                        && matches!(args.first().map(|arg| &arg.value.kind), Some(HirExprKind::Unary { op: UnaryOp::Ref, .. }))
            )
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn does_not_rewrite_mut_pointer_receiver_call_for_immutable_binding() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nmain := () i32 {\n  t := Thing{}\n  t.touch()\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
        let inferred = infer_binding_type_strings(&units);
        let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
        let main_module = hir
            .modules
            .iter()
            .find(|module| module.key.module_name == "main")
            .expect("main module should exist");
        let main_item = main_module
            .items
            .iter()
            .find(|item| item.name == "main")
            .expect("main binding should exist");
        let HirExprKind::Function { body, .. } = &main_item.value.kind else {
            panic!("main should lower to function")
        };
        let HirExprKind::Block { body } = &body.kind else {
            panic!("main body should be block")
        };
        assert!(body.iter().any(|expr| {
            matches!(
                &expr.kind,
                HirExprKind::Call { callee, .. }
                    if matches!(
                        &callee.kind,
                        HirExprKind::FieldAccess { field, .. } if field == "touch"
                    )
            )
        }));
        assert!(!body.iter().any(|expr| {
            matches!(
                &expr.kind,
                HirExprKind::Call { callee, .. }
                    if matches!(&callee.kind, HirExprKind::Ident(name) if name == "Thing__touch")
            )
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn rewrites_mut_pointer_receiver_call_for_mutable_field_binding() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nHolder := struct { item: Thing }\nmain := () i32 {\n  mut h := Holder{item: Thing{}}\n  h.item.touch()\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
        let inferred = infer_binding_type_strings(&units);
        let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
        let main_module = hir
            .modules
            .iter()
            .find(|module| module.key.module_name == "main")
            .expect("main module should exist");
        let main_item = main_module
            .items
            .iter()
            .find(|item| item.name == "main")
            .expect("main binding should exist");
        let HirExprKind::Function { body, .. } = &main_item.value.kind else {
            panic!("main should lower to function")
        };
        let HirExprKind::Block { body } = &body.kind else {
            panic!("main body should be block")
        };
        assert!(body.iter().any(|expr| {
            matches!(
                &expr.kind,
                HirExprKind::Call { callee, args }
                    if matches!(&callee.kind, HirExprKind::Ident(name) if name == "Thing__touch")
                        && matches!(args.first().map(|arg| &arg.value.kind), Some(HirExprKind::Unary { op: UnaryOp::Ref, .. }))
            )
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }
}
