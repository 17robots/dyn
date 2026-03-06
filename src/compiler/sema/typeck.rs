use std::collections::VecDeque;
use std::collections::{BTreeMap, BTreeSet};

use crate::compiler::ast::{
    AssignOp, BinaryOp, Expr, ExprKind, FnBody, Literal, MatchArm, PatternKind, PatternLiteral,
    Stmt, TypeExpr, TypeExprKind, UnaryOp,
};
use crate::compiler::diagnostics::{Diagnostic, DiagnosticCode, DiagnosticPhase};
use crate::compiler::sema::module_unit::{DeclKind, ModuleUnit};

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
    Bytes,
    Any,
    Opaque,
    Void,
    Null,
    Optional(TypeId),
    Errorable(TypeId),
    Pointer {
        inner: TypeId,
        mutable: bool,
    },
    Array(TypeId),
    Slice {
        element: TypeId,
        mutable: bool,
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
}

#[derive(Debug, Clone)]
struct FnSignature {
    params: Vec<FnParamSpec>,
    return_type: TypeId,
}

#[derive(Clone)]
struct NominalBinding {
    nominal_type: String,
    mutable: bool,
}

#[derive(Copy, Clone)]
enum AnyUsageContext {
    FunctionParam,
    Other,
}

pub fn type_check_modules(units: &[ModuleUnit]) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();

    for unit in units {
        let mut types = TypeStore::default();
        let unknown = types.intern(Type::Unknown);
        let mut env = BTreeMap::<String, TypeId>::new();
        let mut mutability = BTreeMap::<String, bool>::new();
        let mut nominal_bindings = BTreeMap::<String, NominalBinding>::new();
        let mut signatures = BTreeMap::<String, FnSignature>::new();
        insert_builtin_signatures(&mut signatures, &mut types);
        let mut_ptr_receiver_methods = collect_mut_pointer_receiver_methods(unit);
        let struct_field_nominals = collect_struct_field_nominal_types(unit);
        let named_struct_fields = collect_named_struct_fields(unit);

        for decl in &unit.declarations {
            if decl.kind != DeclKind::Binding {
                continue;
            }
            if let ExprKind::Fn(fn_expr) = &decl.value.kind {
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
            if let ExprKind::TypeLiteral(ty) = &decl.value.kind {
                validate_struct_type_members(ty, &decl.name, &mut diagnostics, &decl.file_path);
            }
            validate_mut_pointer_receiver_calls(
                &decl.value,
                &mut_ptr_receiver_methods,
                &struct_field_nominals,
                &mut diagnostics,
                &decl.file_path,
                &nominal_bindings,
            );
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

            if matches!(types.get(actual), Type::Null) && !decl.mutable {
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

            let final_type = if let Some(expected) = expected {
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

            env.insert(decl.name.clone(), final_type);
            mutability.insert(decl.name.clone(), decl.mutable);
            if let Some(nominal) = infer_decl_nominal_type(decl, &mut_ptr_receiver_methods) {
                nominal_bindings.insert(
                    decl.name.clone(),
                    NominalBinding {
                        nominal_type: nominal,
                        mutable: decl.mutable,
                    },
                );
            }
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
        insert_builtin_signatures(&mut signatures, &mut types);

        for decl in &unit.declarations {
            if decl.kind != DeclKind::Binding {
                continue;
            }
            if let ExprKind::Fn(fn_expr) = &decl.value.kind {
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
            let final_ty = decl
                .annotation
                .as_ref()
                .and_then(|ty| resolve_type_expr(ty, &mut types))
                .unwrap_or(actual);

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

fn infer_expr_type(
    expr: &Expr,
    env: &BTreeMap<String, TypeId>,
    mutability: &BTreeMap<String, bool>,
    signatures: &BTreeMap<String, FnSignature>,
    types: &mut TypeStore,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
    expected_return: Option<TypeId>,
) -> TypeId {
    match &expr.kind {
        ExprKind::Literal(lit) => match lit {
            Literal::Integer(_) => types.intern(Type::Int {
                signed: true,
                bits: 32,
            }),
            Literal::Float(_) => types.intern(Type::Float { bits: 64 }),
            Literal::String(_) => types.intern(Type::Bytes),
            Literal::Char(_) => types.intern(Type::Int {
                signed: false,
                bits: 8,
            }),
            Literal::Bool(_) => types.intern(Type::Bool),
            Literal::Null => types.intern(Type::Null),
        },
        ExprKind::Ident(ident) => {
            if let Some(ty) = env.get(&ident.text).copied() {
                ty
            } else if resolve_builtin_type_name(&ident.text, types).is_some() {
                types.intern(Type::TypeType)
            } else {
                types.intern(Type::Unknown)
            }
        }
        ExprKind::Unary { op, expr } => {
            let inner = infer_expr_type(
                expr,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            match op {
                UnaryOp::Not => types.intern(Type::Bool),
                UnaryOp::Neg => inner,
                UnaryOp::BitNot => inner,
                UnaryOp::Ref => {
                    let mutable_ref = matches!(expr.kind, ExprKind::Ident(ref ident) if mutability.get(&ident.text).copied().unwrap_or(false));
                    types.intern(Type::Pointer {
                        inner,
                        mutable: mutable_ref,
                    })
                }
            }
        }
        ExprKind::Binary { op, left, right } => {
            let left_ty = infer_expr_type(
                left,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            let right_ty = infer_expr_type(
                right,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );

            match op {
                BinaryOp::Add
                | BinaryOp::Sub
                | BinaryOp::Mul
                | BinaryOp::Div
                | BinaryOp::Mod
                | BinaryOp::BitAnd
                | BinaryOp::BitOr
                | BinaryOp::BitXor
                | BinaryOp::Shl
                | BinaryOp::Shr => {
                    if !is_numeric(left_ty, types) || !is_numeric(right_ty, types) {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "invalid operands for numeric operator",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(expr.span),
                                "both operands must be numeric",
                            ),
                        );
                    }
                    numeric_result_type(left_ty, right_ty, types)
                }
                BinaryOp::Eq
                | BinaryOp::Ne
                | BinaryOp::Lt
                | BinaryOp::Le
                | BinaryOp::Gt
                | BinaryOp::Ge
                | BinaryOp::LogicalAnd
                | BinaryOp::LogicalOr => types.intern(Type::Bool),
                BinaryOp::Range | BinaryOp::RangeInclusive => types.intern(Type::Unknown),
            }
        }
        ExprKind::Assign { op, target, value } => {
            let value_ty = infer_expr_type(
                value,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            let target_ty = infer_expr_type(
                target,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );

            if let ExprKind::Ident(ident) = &target.kind {
                if !mutability.get(&ident.text).copied().unwrap_or(false) {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4006,
                            format!("cannot assign to immutable binding '{}'", ident.text),
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "mark binding as mut to reassign",
                        ),
                    );
                }
            }
            if let ExprKind::DerefAccess { base } = &target.kind {
                let base_ty = infer_expr_type(
                    base,
                    env,
                    mutability,
                    signatures,
                    types,
                    diagnostics,
                    file_path,
                    expected_return,
                );
                if !matches!(types.get(base_ty), Type::Pointer { mutable: true, .. }) {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4006,
                            "cannot assign through immutable pointer",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "requires *mut pointer for write access",
                        ),
                    );
                }
            }
            if let ExprKind::Index { base, .. } = &target.kind {
                let base_ty = infer_expr_type(
                    base,
                    env,
                    mutability,
                    signatures,
                    types,
                    diagnostics,
                    file_path,
                    expected_return,
                );
                let writable = match types.get(base_ty) {
                    Type::Slice { mutable, .. } | Type::Pointer { mutable, .. } => *mutable,
                    _ => false,
                };
                if !writable {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4006,
                            "cannot assign through immutable indexed view",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "requires []mut/*mut view for indexed write",
                        ),
                    );
                }
            }
            if *op != AssignOp::Assign
                && !matches!(types.get(target_ty), Type::Unknown)
                && !matches!(types.get(value_ty), Type::Unknown)
                && (!is_numeric(target_ty, types) || !is_numeric(value_ty, types))
            {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "compound assignment requires numeric target and value",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "use numeric operands for compound assignment",
                    ),
                );
            }
            target_ty
        }
        ExprKind::Call(call) => infer_call_type(
            call,
            env,
            mutability,
            signatures,
            types,
            diagnostics,
            file_path,
            expr,
            expected_return,
        ),
        ExprKind::If(if_expr) => {
            let cond_ty = infer_expr_type(
                &if_expr.condition,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            if !matches!(
                types.get(cond_ty),
                Type::Bool | Type::Unknown | Type::Optional(_)
            ) {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "if condition must evaluate to bool or optional value for unwrap form",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(if_expr.condition.span),
                        "use a boolean expression",
                    ),
                );
            }
            let mut then_env = env.clone();
            let mut then_mutability = mutability.clone();
            if let Some(capture) = &if_expr.capture {
                if !matches!(types.get(cond_ty), Type::Optional(_) | Type::Unknown) {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "if capture requires optional condition",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(if_expr.condition.span),
                            "remove capture or use optional condition",
                        ),
                    );
                }
                if let Some(binding) = &capture.binding {
                    let binding_ty = match types.get(cond_ty) {
                        Type::Optional(inner) => *inner,
                        _ => types.intern(Type::Unknown),
                    };
                    then_env.insert(binding.text.clone(), binding_ty);
                    then_mutability.insert(binding.text.clone(), false);
                }
            }
            let then_ty = infer_expr_type(
                &if_expr.then_branch,
                &then_env,
                &then_mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            let else_ty = if let Some(else_branch) = &if_expr.else_branch {
                infer_expr_type(
                    else_branch,
                    env,
                    mutability,
                    signatures,
                    types,
                    diagnostics,
                    file_path,
                    expected_return,
                )
            } else {
                types.intern(Type::Unknown)
            };

            unify_branch_types(then_ty, else_ty, types, diagnostics, file_path, expr)
        }
        ExprKind::Match(match_expr) => {
            let scrutinee_ty = infer_expr_type(
                &match_expr.scrutinee,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            let mut result = types.intern(Type::Unknown);
            let mut first = true;
            for MatchArm {
                pattern,
                guard,
                value,
                ..
            } in &match_expr.arms
            {
                let mut arm_env = env.clone();
                let mut arm_mutability = mutability.clone();
                bind_pattern_names(
                    &pattern.kind,
                    scrutinee_ty,
                    types,
                    &mut arm_env,
                    &mut arm_mutability,
                );

                if let Some(reason) =
                    pattern_compatibility_issue(&pattern.kind, scrutinee_ty, types).or_else(|| {
                        enum_literal_pattern_issue(&pattern.kind, &match_expr.scrutinee.kind)
                    })
                {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            format!(
                                "match arm pattern is incompatible with scrutinee type: {reason}"
                            ),
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(pattern.span),
                            "adjust arm pattern or scrutinee expression type",
                        ),
                    );
                }

                if let Some(guard) = guard {
                    let guard_ty = infer_expr_type(
                        guard,
                        &arm_env,
                        &arm_mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                    if !matches!(types.get(guard_ty), Type::Bool | Type::Unknown) {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "match guard must evaluate to bool",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(guard.span),
                                "use a boolean guard expression",
                            ),
                        );
                    }
                }
                let arm_ty = infer_expr_type(
                    value,
                    &arm_env,
                    &arm_mutability,
                    signatures,
                    types,
                    diagnostics,
                    file_path,
                    expected_return,
                );
                if first {
                    result = arm_ty;
                    first = false;
                } else {
                    result =
                        unify_branch_types(result, arm_ty, types, diagnostics, file_path, expr);
                }
            }
            result
        }
        ExprKind::Block(block) => {
            let mut local_env = env.clone();
            let mut local_mutability = mutability.clone();
            let mut result = types.intern(Type::Unknown);

            for stmt in &block.statements {
                match stmt {
                    crate::compiler::ast::Stmt::Binding(binding) => {
                        let mut value_ty = infer_expr_type(
                            &binding.value,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            diagnostics,
                            file_path,
                            expected_return,
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
                            if !types_compatible(expected, value_ty, types) {
                                diagnostics.push(
                                    Diagnostic::error(
                                        DiagnosticPhase::TypeChecker,
                                        DiagnosticCode::E4005,
                                        format!(
                                            "type mismatch for '{}' in block binding",
                                            binding.name.text
                                        ),
                                    )
                                    .with_primary_file_label(
                                        file_path.to_path_buf(),
                                        Some(binding.span),
                                        "annotation and initializer disagree",
                                    ),
                                );
                            }
                            expected
                        } else {
                            value_ty
                        };
                        local_env.insert(binding.name.text.clone(), final_ty);
                        local_mutability.insert(binding.name.text.clone(), binding.mutable);
                        result = final_ty;
                    }
                    crate::compiler::ast::Stmt::Expr(stmt_expr) => {
                        result = infer_expr_type(
                            stmt_expr,
                            &local_env,
                            &local_mutability,
                            signatures,
                            types,
                            diagnostics,
                            file_path,
                            expected_return,
                        );
                    }
                }
            }

            if let Some(tail_expr) = &block.tail_expr {
                result = infer_expr_type(
                    tail_expr,
                    &local_env,
                    &local_mutability,
                    signatures,
                    types,
                    diagnostics,
                    file_path,
                    expected_return,
                );
            }

            result
        }
        ExprKind::For(for_expr) => {
            match for_expr {
                crate::compiler::ast::ForExpr::Range {
                    start,
                    end,
                    binding,
                    body,
                    ..
                } => {
                    let start_ty = infer_expr_type(
                        start,
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                    let end_ty = infer_expr_type(
                        end,
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                    let mut local_env = env.clone();
                    let mut local_mutability = mutability.clone();
                    if let Some(binding) = binding {
                        let binding_ty = if is_numeric(start_ty, types) && is_numeric(end_ty, types)
                        {
                            numeric_result_type(start_ty, end_ty, types)
                        } else {
                            types.intern(Type::Int {
                                signed: true,
                                bits: 32,
                            })
                        };
                        local_env.insert(binding.text.clone(), binding_ty);
                        local_mutability.insert(binding.text.clone(), false);
                    }
                    let _ = infer_expr_type(
                        body,
                        &local_env,
                        &local_mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                }
                crate::compiler::ast::ForExpr::Iterate {
                    iterable,
                    binding,
                    body,
                    ..
                } => {
                    let iterable_ty = infer_expr_type(
                        iterable,
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                    let mut local_env = env.clone();
                    let mut local_mutability = mutability.clone();
                    if let Some(binding) = binding {
                        let binding_ty = match types.get(iterable_ty) {
                            Type::Array(element)
                            | Type::Slice { element, .. }
                            | Type::Pointer { inner: element, .. } => *element,
                            Type::Bytes => types.intern(Type::Int {
                                signed: false,
                                bits: 8,
                            }),
                            _ => types.intern(Type::Unknown),
                        };
                        local_env.insert(binding.text.clone(), binding_ty);
                        local_mutability.insert(binding.text.clone(), false);
                    }
                    let _ = infer_expr_type(
                        body,
                        &local_env,
                        &local_mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                }
                crate::compiler::ast::ForExpr::WhileLike { condition, body } => {
                    let _ = infer_expr_type(
                        condition,
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                    let _ = infer_expr_type(
                        body,
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                }
                crate::compiler::ast::ForExpr::Infinite { body } => {
                    let _ = infer_expr_type(
                        body,
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                }
            }
            types.intern(Type::Unknown)
        }
        ExprKind::Return { value } => {
            let mut value_ty = value
                .as_ref()
                .map(|expr| {
                    infer_expr_type(
                        expr,
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    )
                })
                .unwrap_or_else(|| types.intern(Type::Unknown));

            if let Some(expected) = expected_return {
                if let Some(value_expr) = value {
                    value_ty =
                        maybe_coerce_literal_to_expected(value_expr, value_ty, expected, types);
                }
                if !types_compatible(expected, value_ty, types) {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "return type does not match function annotation",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "change returned value or function return type",
                        ),
                    );
                }
            }
            value_ty
        }
        ExprKind::Fn(fn_expr) => {
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

            let expected = fn_expr
                .return_type
                .as_ref()
                .and_then(|ty| resolve_type_expr(ty, types));

            match &fn_expr.body {
                crate::compiler::ast::FnBody::Block(block) => {
                    if strict_explicit_returns_enabled()
                        && block
                            .tail_expr
                            .as_ref()
                            .is_some_and(|tail| !matches!(tail.kind, ExprKind::Return { .. }))
                    {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "implicit tail returns are not allowed in strict return mode",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(expr.span),
                                "use explicit `return ...` statements",
                            ),
                        );
                    }
                    let _ = infer_expr_type(
                        &Expr {
                            kind: ExprKind::Block(block.clone()),
                            span: expr.span,
                        },
                        &local_env,
                        &local_mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected,
                    );
                }
                crate::compiler::ast::FnBody::ArrowExpr(arrow_expr) => {
                    let mut ret_ty = infer_expr_type(
                        arrow_expr,
                        &local_env,
                        &local_mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected,
                    );
                    if let Some(expected) = expected {
                        ret_ty =
                            maybe_coerce_literal_to_expected(arrow_expr, ret_ty, expected, types);
                        if !types_compatible(expected, ret_ty, types) {
                            diagnostics.push(
                                Diagnostic::error(
                                    DiagnosticPhase::TypeChecker,
                                    DiagnosticCode::E4005,
                                    "function arrow body type does not match return type",
                                )
                                .with_primary_file_label(
                                    file_path.to_path_buf(),
                                    Some(expr.span),
                                    "change expression or return annotation",
                                ),
                            );
                        }
                    }
                }
            }

            let return_type = expected.unwrap_or_else(|| types.intern(Type::Unknown));
            let param_types = fn_expr
                .params
                .iter()
                .map(|param| {
                    param
                        .ty
                        .as_ref()
                        .and_then(|ty| resolve_type_expr(ty, types))
                        .unwrap_or_else(|| types.intern(Type::Unknown))
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
            types.intern(Type::Function {
                param_types,
                param_names,
                has_defaults,
                return_type,
            })
        }
        ExprKind::Index { base, index } => {
            let base_ty = infer_expr_type(
                base,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            let _index_ty = infer_expr_type(
                index,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            match types.get(base_ty) {
                Type::Tuple(elements) => {
                    let Some(index_value) = tuple_index_literal(index) else {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "tuple index must be a compile-time integer literal",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(index.span),
                                "use a numeric literal like 0, 1, 2, ...",
                            ),
                        );
                        return types.intern(Type::Unknown);
                    };
                    if let Some(element_ty) = elements.get(index_value) {
                        *element_ty
                    } else {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "tuple index is out of bounds",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(index.span),
                                "index exceeds tuple element count",
                            ),
                        );
                        types.intern(Type::Unknown)
                    }
                }
                Type::Array(elem)
                | Type::Slice { element: elem, .. }
                | Type::Pointer { inner: elem, .. } => *elem,
                Type::Bytes => types.intern(Type::Int {
                    signed: false,
                    bits: 8,
                }),
                Type::Unknown => base_ty,
                _ => {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "indexing requires array/slice/pointer/bytes value",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "cannot index this expression",
                        ),
                    );
                    types.intern(Type::Unknown)
                }
            }
        }
        ExprKind::Slice(slice) => {
            let base_ty = infer_expr_type(
                &slice.base,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            match types.get(base_ty) {
                Type::Array(elem) => types.intern(Type::Slice {
                    element: *elem,
                    mutable: false,
                }),
                Type::Slice { element, mutable } => types.intern(Type::Slice {
                    element: *element,
                    mutable: *mutable,
                }),
                Type::Pointer { inner, mutable } => types.intern(Type::Slice {
                    element: *inner,
                    mutable: *mutable,
                }),
                Type::Bytes => types.intern(Type::Bytes),
                Type::Unknown => base_ty,
                _ => {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "slicing requires array/slice/pointer/bytes value",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "cannot slice this expression",
                        ),
                    );
                    types.intern(Type::Unknown)
                }
            }
        }
        ExprKind::DerefAccess { base } => {
            let base_ty = infer_expr_type(
                base,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            match types.get(base_ty) {
                Type::Pointer { inner, .. } => *inner,
                Type::Unknown => base_ty,
                _ => {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "deref access requires pointer value",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "cannot dereference this expression",
                        ),
                    );
                    types.intern(Type::Unknown)
                }
            }
        }
        ExprKind::OptionalUnwrap { expr: inner } => {
            let inner_ty = infer_expr_type(
                inner,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            match types.get(inner_ty) {
                Type::Optional(base) => *base,
                Type::Unknown => inner_ty,
                _ => {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "optional unwrap requires optional value",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "cannot use .? on non-optional expression",
                        ),
                    );
                    types.intern(Type::Unknown)
                }
            }
        }
        ExprKind::ErrorUnwrap { expr: inner } => {
            let inner_ty = infer_expr_type(
                inner,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            match types.get(inner_ty) {
                Type::Errorable(ok) => *ok,
                Type::Unknown => inner_ty,
                _ => {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "error unwrap requires errorable value",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(expr.span),
                            "cannot use .! on non-errorable expression",
                        ),
                    );
                    types.intern(Type::Unknown)
                }
            }
        }
        ExprKind::OrElse(or_else) => {
            let value_ty = infer_expr_type(
                &or_else.value,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            let mut fallback_env = env.clone();
            let mut fallback_mutability = mutability.clone();
            if let Some(binding) = &or_else.error_binding {
                let binding_ty = types.intern(Type::Unknown);
                fallback_env.insert(binding.text.clone(), binding_ty);
                fallback_mutability.insert(binding.text.clone(), false);
            }
            let fallback_ty = infer_expr_type(
                &or_else.fallback,
                &fallback_env,
                &fallback_mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );

            match types.get(value_ty) {
                Type::Optional(inner) => {
                    if types_compatible(*inner, fallback_ty, types) {
                        *inner
                    } else {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "fallback type does not match optional inner type",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(expr.span),
                                "make `or` fallback compatible with optional type",
                            ),
                        );
                        *inner
                    }
                }
                Type::Errorable(inner) => {
                    if types_compatible(*inner, fallback_ty, types) {
                        *inner
                    } else {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "fallback type does not match errorable ok type",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(expr.span),
                                "make `or` fallback compatible with errorable return type",
                            ),
                        );
                        *inner
                    }
                }
                Type::Null => fallback_ty,
                Type::Unknown => fallback_ty,
                _ => value_ty,
            }
        }
        ExprKind::Comptime { expr } => {
            let ty = infer_expr_type(
                expr,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            if !is_compile_time_expr(expr) {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "comptime expression must be compile-time evaluable",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "use literals, type designators, or comptime builtins",
                    ),
                );
            }
            ty
        }
        ExprKind::Inline { expr } => infer_expr_type(
            expr,
            env,
            mutability,
            signatures,
            types,
            diagnostics,
            file_path,
            expected_return,
        ),
        ExprKind::Use { .. } => types.intern(Type::Unknown),
        ExprKind::TypeLiteral(_) => types.intern(Type::TypeType),
        ExprKind::ArrayLiteral(elements) => {
            let Some(first) = elements.first() else {
                let unknown = types.intern(Type::Unknown);
                return types.intern(Type::Array(unknown));
            };
            let mut element_ty = infer_expr_type(
                first,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            for element in &elements[1..] {
                let next_ty = infer_expr_type(
                    element,
                    env,
                    mutability,
                    signatures,
                    types,
                    diagnostics,
                    file_path,
                    expected_return,
                );
                element_ty = if types_compatible(element_ty, next_ty, types) {
                    element_ty
                } else if types_compatible(next_ty, element_ty, types) {
                    next_ty
                } else if is_numeric(element_ty, types) && is_numeric(next_ty, types) {
                    numeric_result_type(element_ty, next_ty, types)
                } else {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "array literal elements must have compatible types",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(element.span),
                            "make all array elements the same type",
                        ),
                    );
                    types.intern(Type::Unknown)
                };
            }
            types.intern(Type::Array(element_ty))
        }
        ExprKind::TupleLiteral(elements) => {
            let element_types = elements
                .iter()
                .map(|element| {
                    infer_expr_type(
                        element,
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    )
                })
                .collect::<Vec<_>>();
            types.intern(Type::Tuple(element_types))
        }
        _ => types.intern(Type::Unknown),
    }
}

fn validate_struct_type_members(
    ty: &TypeExpr,
    struct_name: &str,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
) {
    let TypeExprKind::Struct(struct_ty) = &ty.kind else {
        return;
    };

    for member in &struct_ty.members {
        let ExprKind::Fn(fn_expr) = &member.value.kind else {
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

fn matches_receiver_type(param_ty: &TypeExpr, struct_name: &str) -> bool {
    matches!(&param_ty.kind, TypeExprKind::Named(ident) if ident.text == struct_name)
        || matches!(&param_ty.kind, TypeExprKind::Pointer { inner, .. }
            if matches!(inner.kind, TypeExprKind::Named(ref ident) if ident.text == struct_name))
}

fn collect_mut_pointer_receiver_methods(unit: &ModuleUnit) -> BTreeSet<(String, String)> {
    let mut methods = BTreeSet::new();
    for decl in &unit.declarations {
        let ExprKind::TypeLiteral(type_lit) = &decl.value.kind else {
            continue;
        };
        let TypeExprKind::Struct(struct_ty) = &type_lit.kind else {
            continue;
        };
        for member in &struct_ty.members {
            let ExprKind::Fn(fn_expr) = &member.value.kind else {
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

fn collect_struct_field_nominal_types(unit: &ModuleUnit) -> BTreeMap<(String, String), String> {
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

fn collect_named_struct_fields(unit: &ModuleUnit) -> BTreeMap<String, Vec<String>> {
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

fn validate_named_struct_offsetof_calls(
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
        | ExprKind::Continue
        | ExprKind::Use { .. }
        | ExprKind::TypeLiteral(_) => {}
    }
}

fn infer_decl_nominal_type(
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

fn validate_mut_pointer_receiver_calls(
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

fn validate_mut_pointer_receiver_calls_expr(
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
        | ExprKind::Continue
        | ExprKind::Use { .. }
        | ExprKind::TypeLiteral(_) => {}
    }
}

fn nominal_name_from_type_expr(
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

fn infer_nominal_type_from_expr(
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

fn can_take_mut_ref_from_expr(expr: &Expr, scopes: &[BTreeMap<String, NominalBinding>]) -> bool {
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

#[allow(clippy::too_many_arguments)]
fn infer_function_value_call_type(
    call: &crate::compiler::ast::CallExpr,
    callee_ty: TypeId,
    env: &BTreeMap<String, TypeId>,
    mutability: &BTreeMap<String, bool>,
    signatures: &BTreeMap<String, FnSignature>,
    types: &mut TypeStore,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
    expected_return: Option<TypeId>,
) -> Option<TypeId> {
    let Type::Function {
        param_types,
        param_names,
        has_defaults,
        return_type,
    } = types.get(callee_ty).clone()
    else {
        return None;
    };

    let required = has_defaults.iter().filter(|d| !**d).count();
    let mut ordered_args = vec![None; param_types.len()];
    for arg in &call.args {
        if let Some(name) = &arg.name {
            let Some(index) = param_names.iter().position(|param| {
                param
                    .as_ref()
                    .map(|text| text == &name.text)
                    .unwrap_or(false)
            }) else {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "unknown named argument for function value call",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(arg.value.span),
                        "named argument does not match any parameter",
                    ),
                );
                continue;
            };
            if ordered_args[index].is_some() {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "duplicate named argument for function value call",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(arg.value.span),
                        "parameter already has an argument",
                    ),
                );
                continue;
            }
            ordered_args[index] = Some(arg);
        }
    }
    let mut positional_iter = call.args.iter().filter(|arg| arg.name.is_none());
    for slot in &mut ordered_args {
        if slot.is_none() {
            *slot = positional_iter.next();
        }
    }
    let provided = ordered_args.iter().filter(|slot| slot.is_some()).count();
    if provided < required || provided > param_types.len() {
        diagnostics.push(
            Diagnostic::error(
                DiagnosticPhase::TypeChecker,
                DiagnosticCode::E4005,
                format!(
                    "function value call arity mismatch: expected {}..={}, got {}",
                    required,
                    param_types.len(),
                    call.args.len()
                ),
            )
            .with_primary_file_label(
                file_path.to_path_buf(),
                Some(call.callee.span),
                "adjust argument count to match function value signature",
            ),
        );
    }
    let mut type_param_bindings = BTreeMap::<String, TypeId>::new();
    let mut pending_type_designators = VecDeque::<TypeId>::new();
    for (idx, arg) in ordered_args.into_iter().enumerate() {
        if let (Some(expected_ty), Some(arg)) = (param_types.get(idx), arg) {
            if matches!(types.get(*expected_ty), Type::TypeType)
                && !is_type_designator_expr(&arg.value)
            {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "function value argument must be a type designator",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(arg.value.span),
                        "pass a type name or type literal",
                    ),
                );
            }
            let mut actual_ty = infer_expr_type(
                &arg.value,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            if matches!(types.get(*expected_ty), Type::TypeType) {
                if let Some(designated) = resolve_type_designator_arg(&arg.value, types) {
                    pending_type_designators.push_back(designated);
                }
            }
            let resolved_expected = match types.get(*expected_ty) {
                Type::TypeParam(name) => {
                    if let Some(bound) = type_param_bindings.get(name).copied() {
                        bound
                    } else if let Some(pending) = pending_type_designators.pop_front() {
                        type_param_bindings.insert(name.clone(), pending);
                        pending
                    } else {
                        type_param_bindings.insert(name.clone(), actual_ty);
                        actual_ty
                    }
                }
                _ => *expected_ty,
            };
            actual_ty =
                maybe_coerce_literal_to_expected(&arg.value, actual_ty, resolved_expected, types);
            if !types_compatible(resolved_expected, actual_ty, types) {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "function value argument type mismatch",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(arg.value.span),
                        "argument type does not match function value parameter",
                    ),
                );
            }
        }
    }
    if let Type::TypeParam(name) = types.get(return_type) {
        if let Some(bound) = type_param_bindings.get(name).copied() {
            return Some(bound);
        }
    }
    Some(return_type)
}

fn infer_call_type(
    call: &crate::compiler::ast::CallExpr,
    env: &BTreeMap<String, TypeId>,
    mutability: &BTreeMap<String, bool>,
    signatures: &BTreeMap<String, FnSignature>,
    types: &mut TypeStore,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
    expr: &Expr,
    expected_return: Option<TypeId>,
) -> TypeId {
    let callee_ty = infer_expr_type(
        &call.callee,
        env,
        mutability,
        signatures,
        types,
        diagnostics,
        file_path,
        expected_return,
    );

    let Some(callee_name) = extract_callee_name(&call.callee) else {
        if let Some(return_ty) = infer_function_value_call_type(
            call,
            callee_ty,
            env,
            mutability,
            signatures,
            types,
            diagnostics,
            file_path,
            expected_return,
        ) {
            return return_ty;
        }

        if !matches!(
            types.get(callee_ty),
            Type::Unknown
                | Type::Function { .. }
                | Type::Pointer { .. }
                | Type::TypeParam(_)
                | Type::Any
        ) {
            diagnostics.push(
                Diagnostic::error(
                    DiagnosticPhase::TypeChecker,
                    DiagnosticCode::E4005,
                    "called value is not a function",
                )
                .with_primary_file_label(
                    file_path.to_path_buf(),
                    Some(call.callee.span),
                    "call target must be a function or function value",
                ),
            );
        }
        return types.intern(Type::Unknown);
    };

    if let Some(builtin_ty) = infer_builtin_call_type(
        &callee_name,
        call,
        env,
        mutability,
        signatures,
        types,
        diagnostics,
        file_path,
        expr,
        expected_return,
    ) {
        return builtin_ty;
    }

    let Some(sig) = signatures.get(&callee_name) else {
        if let Some(return_ty) = infer_function_value_call_type(
            call,
            callee_ty,
            env,
            mutability,
            signatures,
            types,
            diagnostics,
            file_path,
            expected_return,
        ) {
            return return_ty;
        }

        if !matches!(
            types.get(callee_ty),
            Type::Unknown
                | Type::Function { .. }
                | Type::Pointer { .. }
                | Type::TypeParam(_)
                | Type::Any
        ) {
            diagnostics.push(
                Diagnostic::error(
                    DiagnosticPhase::TypeChecker,
                    DiagnosticCode::E4005,
                    "called value is not a function",
                )
                .with_primary_file_label(
                    file_path.to_path_buf(),
                    Some(call.callee.span),
                    "call target must be a function or function value",
                ),
            );
        }
        return types.intern(Type::Unknown);
    };

    let mut named_seen = BTreeSet::<String>::new();
    let mut positional_count = 0usize;
    let mut used_params = BTreeSet::<usize>::new();
    let mut specialized_return = None;
    let mut type_param_bindings = BTreeMap::<String, TypeId>::new();

    let direct_param_types = env
        .get(&callee_name)
        .and_then(|type_id| match types.get(*type_id) {
            Type::Function { param_types, .. } => Some(param_types.clone()),
            _ => None,
        });
    let return_from_type_param_idx = match types.get(sig.return_type) {
        Type::TypeParam(param_name) => sig
            .params
            .iter()
            .position(|param| param.name.as_deref() == Some(param_name.as_str())),
        Type::Unknown => direct_param_types.as_ref().and_then(|params| {
            params
                .iter()
                .position(|param| matches!(types.get(*param), Type::TypeType))
        }),
        _ => None,
    };

    for arg in &call.args {
        if let Some(name) = &arg.name {
            let Some(param_index) = sig
                .params
                .iter()
                .position(|param| param.name.as_deref() == Some(name.text.as_str()))
            else {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        format!("unknown named argument '{}'", name.text),
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "named argument does not match any parameter",
                    ),
                );
                continue;
            };

            if let Some(param_types) = &direct_param_types {
                if let Some(expected_ty) = param_types.get(param_index) {
                    let resolved_expected = match types.get(*expected_ty) {
                        Type::TypeParam(name) => type_param_bindings
                            .get(name)
                            .copied()
                            .unwrap_or(*expected_ty),
                        _ => *expected_ty,
                    };
                    if matches!(types.get(*expected_ty), Type::TypeType)
                        && !is_type_designator_expr(&arg.value)
                    {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "call argument must be a type designator",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(arg.value.span),
                                "pass a type name or type literal",
                            ),
                        );
                    }
                    let mut actual_ty = infer_expr_type(
                        &arg.value,
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                    actual_ty = maybe_coerce_literal_to_expected(
                        &arg.value,
                        actual_ty,
                        resolved_expected,
                        types,
                    );
                    if let Some(param_name) = sig.params[param_index].name.as_ref() {
                        if matches!(types.get(*expected_ty), Type::TypeType) {
                            if let Some(designated) = resolve_type_designator_arg(&arg.value, types)
                            {
                                if let Some(bound) = type_param_bindings.get(param_name).copied() {
                                    if bound != designated {
                                        diagnostics.push(
                                            Diagnostic::error(
                                                DiagnosticPhase::TypeChecker,
                                                DiagnosticCode::E4005,
                                                "call argument type mismatch",
                                            )
                                            .with_primary_file_label(
                                                file_path.to_path_buf(),
                                                Some(arg.value.span),
                                                "argument type does not match parameter type",
                                            ),
                                        );
                                    }
                                } else {
                                    type_param_bindings.insert(param_name.clone(), designated);
                                }
                            }
                        }
                    }
                    if let Type::TypeParam(name) = types.get(*expected_ty) {
                        if let Some(bound) = type_param_bindings.get(name).copied() {
                            if !types_compatible(bound, actual_ty, types) {
                                diagnostics.push(
                                    Diagnostic::error(
                                        DiagnosticPhase::TypeChecker,
                                        DiagnosticCode::E4005,
                                        "call argument type mismatch",
                                    )
                                    .with_primary_file_label(
                                        file_path.to_path_buf(),
                                        Some(arg.value.span),
                                        "argument type does not match parameter type",
                                    ),
                                );
                            }
                        } else {
                            type_param_bindings.insert(name.clone(), actual_ty);
                        }
                    }
                    if !types_compatible(resolved_expected, actual_ty, types) {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "call argument type mismatch",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(arg.value.span),
                                "argument type does not match parameter type",
                            ),
                        );
                    }
                }
            }

            if !named_seen.insert(name.text.clone()) {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        format!("duplicate named argument '{}'", name.text),
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "remove duplicate argument",
                    ),
                );
            }
            used_params.insert(param_index);
            if return_from_type_param_idx == Some(param_index) {
                specialized_return =
                    resolve_type_designator_arg(&arg.value, types).or(specialized_return);
            }
        } else {
            if positional_count >= sig.params.len() {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "too many positional arguments",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "call exceeds function arity",
                    ),
                );
                continue;
            }

            if let Some(param_types) = &direct_param_types {
                if let Some(expected_ty) = param_types.get(positional_count) {
                    let resolved_expected = match types.get(*expected_ty) {
                        Type::TypeParam(name) => type_param_bindings
                            .get(name)
                            .copied()
                            .unwrap_or(*expected_ty),
                        _ => *expected_ty,
                    };
                    if matches!(types.get(*expected_ty), Type::TypeType)
                        && !is_type_designator_expr(&arg.value)
                    {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "call argument must be a type designator",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(arg.value.span),
                                "pass a type name or type literal",
                            ),
                        );
                    }
                    let mut actual_ty = infer_expr_type(
                        &arg.value,
                        env,
                        mutability,
                        signatures,
                        types,
                        diagnostics,
                        file_path,
                        expected_return,
                    );
                    actual_ty = maybe_coerce_literal_to_expected(
                        &arg.value,
                        actual_ty,
                        resolved_expected,
                        types,
                    );
                    if let Some(param_name) = sig.params[positional_count].name.as_ref() {
                        if matches!(types.get(*expected_ty), Type::TypeType) {
                            if let Some(designated) = resolve_type_designator_arg(&arg.value, types)
                            {
                                if let Some(bound) = type_param_bindings.get(param_name).copied() {
                                    if bound != designated {
                                        diagnostics.push(
                                            Diagnostic::error(
                                                DiagnosticPhase::TypeChecker,
                                                DiagnosticCode::E4005,
                                                "call argument type mismatch",
                                            )
                                            .with_primary_file_label(
                                                file_path.to_path_buf(),
                                                Some(arg.value.span),
                                                "argument type does not match parameter type",
                                            ),
                                        );
                                    }
                                } else {
                                    type_param_bindings.insert(param_name.clone(), designated);
                                }
                            }
                        }
                    }
                    if let Type::TypeParam(name) = types.get(*expected_ty) {
                        if let Some(bound) = type_param_bindings.get(name).copied() {
                            if !types_compatible(bound, actual_ty, types) {
                                diagnostics.push(
                                    Diagnostic::error(
                                        DiagnosticPhase::TypeChecker,
                                        DiagnosticCode::E4005,
                                        "call argument type mismatch",
                                    )
                                    .with_primary_file_label(
                                        file_path.to_path_buf(),
                                        Some(arg.value.span),
                                        "argument type does not match parameter type",
                                    ),
                                );
                            }
                        } else {
                            type_param_bindings.insert(name.clone(), actual_ty);
                        }
                    }
                    if !types_compatible(resolved_expected, actual_ty, types) {
                        diagnostics.push(
                            Diagnostic::error(
                                DiagnosticPhase::TypeChecker,
                                DiagnosticCode::E4005,
                                "call argument type mismatch",
                            )
                            .with_primary_file_label(
                                file_path.to_path_buf(),
                                Some(arg.value.span),
                                "argument type does not match parameter type",
                            ),
                        );
                    }
                }
            }

            used_params.insert(positional_count);
            if return_from_type_param_idx == Some(positional_count) {
                specialized_return =
                    resolve_type_designator_arg(&arg.value, types).or(specialized_return);
            }
            positional_count += 1;
        }
    }

    for (idx, param) in sig.params.iter().enumerate() {
        if !used_params.contains(&idx) && !param.has_default {
            diagnostics.push(
                Diagnostic::error(
                    DiagnosticPhase::TypeChecker,
                    DiagnosticCode::E4005,
                    "missing required argument",
                )
                .with_primary_file_label(
                    file_path.to_path_buf(),
                    Some(expr.span),
                    "provide all non-default parameters",
                ),
            );
        }
    }

    if let Type::TypeParam(name) = types.get(sig.return_type) {
        if let Some(bound) = type_param_bindings.get(name).copied() {
            return bound;
        }
    }

    specialized_return.unwrap_or(sig.return_type)
}

fn bind_pattern_names(
    pattern: &PatternKind,
    scrutinee_ty: TypeId,
    types: &mut TypeStore,
    env: &mut BTreeMap<String, TypeId>,
    mutability: &mut BTreeMap<String, bool>,
) {
    match pattern {
        PatternKind::IdentBind(ident) => {
            env.insert(ident.text.clone(), scrutinee_ty);
            mutability.insert(ident.text.clone(), false);
        }
        PatternKind::Range { start, end, .. } => {
            bind_pattern_names(&start.kind, scrutinee_ty, types, env, mutability);
            bind_pattern_names(&end.kind, scrutinee_ty, types, env, mutability);
        }
        PatternKind::EnumVariant { bindings, .. } => {
            let unknown = types.intern(Type::Unknown);
            for ident in bindings {
                env.insert(ident.text.clone(), unknown);
                mutability.insert(ident.text.clone(), false);
            }
        }
        PatternKind::Typed { pattern, ty } => {
            let bound_ty = resolve_type_expr(ty, types).unwrap_or(scrutinee_ty);
            bind_pattern_names(&pattern.kind, bound_ty, types, env, mutability);
        }
        PatternKind::Wildcard | PatternKind::Literal(_) => {}
    }
}

#[allow(clippy::too_many_arguments)]
fn infer_builtin_call_type(
    name: &str,
    call: &crate::compiler::ast::CallExpr,
    env: &BTreeMap<String, TypeId>,
    mutability: &BTreeMap<String, bool>,
    signatures: &BTreeMap<String, FnSignature>,
    types: &mut TypeStore,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
    expr: &Expr,
    expected_return: Option<TypeId>,
) -> Option<TypeId> {
    match name {
        "$Self" => {
            if call.args.len() != 0 {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$Self expects no arguments",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "use $Self()",
                    ),
                );
            }
            if env.get("self").is_none() {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$Self is only available in self method context",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "use inside an instance method with self parameter",
                    ),
                );
            }
            return Some(types.intern(Type::TypeType));
        }
        "$sizeof" | "$alignof" => {
            if call.args.len() != 1 {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        format!("{} expects exactly one argument", name),
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "pass one type argument",
                    ),
                );
            }
            return Some(types.intern(Type::Int {
                signed: false,
                bits: 64,
            }));
        }
        "$offsetof" => {
            if call.args.len() != 2 {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$offsetof expects two arguments: type and field name",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "use $offsetof(Type, field)",
                    ),
                );
            } else {
                let type_arg = &call.args[0].value;
                let field_arg = &call.args[1].value;
                if !valid_offsetof_designator(type_arg, field_arg) {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "$offsetof field designator is invalid for the target type",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(field_arg.span),
                            "use an existing field name or in-range field index",
                        ),
                    );
                }
            }
            return Some(types.intern(Type::Int {
                signed: false,
                bits: 64,
            }));
        }
        "$typeof" => {
            if call.args.len() != 1 {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$typeof expects exactly one argument",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "pass one expression argument",
                    ),
                );
            }
            if let Some(arg) = call.args.first() {
                let _ = infer_expr_type(
                    &arg.value,
                    env,
                    mutability,
                    signatures,
                    types,
                    diagnostics,
                    file_path,
                    expected_return,
                );
            }
            return Some(types.intern(Type::TypeType));
        }
        "$as" => {
            if call.args.len() != 2 {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$as expects two arguments: target type and value",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "use $as(Type, value)",
                    ),
                );
                return Some(types.intern(Type::Unknown));
            }

            let target_ty = resolve_builtin_type_arg(&call.args[0].value, types)
                .unwrap_or_else(|| types.intern(Type::Unknown));
            let value_ty = infer_expr_type(
                &call.args[1].value,
                env,
                mutability,
                signatures,
                types,
                diagnostics,
                file_path,
                expected_return,
            );
            let numeric_cast =
                matches!(types.get(target_ty), Type::Int { .. } | Type::Float { .. })
                    && matches!(types.get(value_ty), Type::Int { .. } | Type::Float { .. });
            let pointer_cast = matches!(types.get(target_ty), Type::Pointer { .. })
                && matches!(types.get(value_ty), Type::Pointer { .. });
            let int_to_pointer_cast = matches!(types.get(target_ty), Type::Pointer { .. })
                && matches!(
                    types.get(value_ty),
                    Type::Int {
                        signed: false,
                        bits: 64
                    }
                );
            let slice_to_pointer_cast = matches!(types.get(target_ty), Type::Pointer { .. })
                && matches!(types.get(value_ty), Type::Slice { .. });
            let pointer_to_usize_cast = matches!(
                (types.get(target_ty), types.get(value_ty)),
                (
                    Type::Int {
                        signed: false,
                        bits: 64
                    },
                    Type::Pointer { .. }
                )
            );
            let slice_to_usize_cast = matches!(
                (types.get(target_ty), types.get(value_ty)),
                (
                    Type::Int {
                        signed: false,
                        bits: 64
                    },
                    Type::Slice { .. }
                )
            );
            if !numeric_cast
                && !pointer_cast
                && !int_to_pointer_cast
                && !slice_to_pointer_cast
                && !pointer_to_usize_cast
                && !slice_to_usize_cast
                && !types_compatible(target_ty, value_ty, types)
                && !types_compatible(value_ty, target_ty, types)
            {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$as value is incompatible with requested target type",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(call.args[1].value.span),
                        "adjust source value or target type",
                    ),
                );
            }
            return Some(target_ty);
        }
        "$compile_error" => {
            diagnostics.push(
                Diagnostic::error(
                    DiagnosticPhase::TypeChecker,
                    DiagnosticCode::E4005,
                    "$compile_error invoked",
                )
                .with_primary_file_label(
                    file_path.to_path_buf(),
                    Some(expr.span),
                    "remove compile error or gate it behind compile-time condition",
                ),
            );
            return Some(types.intern(Type::Unknown));
        }
        "$panic" => {
            if call.args.len() != 1 {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$panic expects one argument",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "use $panic(message)",
                    ),
                );
            } else {
                let message_ty = infer_expr_type(
                    &call.args[0].value,
                    env,
                    mutability,
                    signatures,
                    types,
                    diagnostics,
                    file_path,
                    expected_return,
                );
                let bytes_ty = types.intern(Type::Bytes);
                if !types_compatible(bytes_ty, message_ty, types) {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::TypeChecker,
                            DiagnosticCode::E4005,
                            "$panic message must be bytes/string compatible",
                        )
                        .with_primary_file_label(
                            file_path.to_path_buf(),
                            Some(call.args[0].value.span),
                            "pass a string literal or bytes value",
                        ),
                    );
                }
            }
            return Some(types.intern(Type::Unknown));
        }
        "$unreachable" => {
            if !call.args.is_empty() {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "$unreachable expects zero arguments",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(expr.span),
                        "remove arguments from $unreachable",
                    ),
                );
            }
            return Some(types.intern(Type::Unknown));
        }
        _ => {}
    }

    None
}

fn resolve_builtin_type_arg(expr: &Expr, types: &mut TypeStore) -> Option<TypeId> {
    resolve_type_designator_arg(expr, types)
}

fn resolve_type_designator_arg(expr: &Expr, types: &mut TypeStore) -> Option<TypeId> {
    match &expr.kind {
        ExprKind::TypeLiteral(ty) => resolve_type_expr(ty, types),
        ExprKind::Ident(ident) | ExprKind::BuiltinIdent(ident) => {
            if let Some(ty) = resolve_builtin_type_name(&ident.text, types) {
                Some(ty)
            } else {
                Some(types.intern(Type::Applied {
                    callee: ident.text.clone(),
                    args: Vec::new(),
                }))
            }
        }
        ExprKind::Call(call) => {
            let callee_name = match &call.callee.kind {
                ExprKind::Ident(ident) | ExprKind::BuiltinIdent(ident) => ident.text.clone(),
                _ => return None,
            };
            let mut args = Vec::with_capacity(call.args.len());
            for arg in &call.args {
                args.push(resolve_type_designator_arg(&arg.value, types)?);
            }
            Some(types.intern(Type::Applied {
                callee: callee_name,
                args,
            }))
        }
        _ => None,
    }
}

fn resolve_builtin_type_name(name: &str, types: &mut TypeStore) -> Option<TypeId> {
    if name == "u1" {
        return Some(types.intern(Type::Bool));
    }
    if let Some(int_ty) = parse_int_type_name(name) {
        return Some(types.intern(int_ty));
    }
    if let Some(float_ty) = parse_float_type_name(name) {
        return Some(types.intern(float_ty));
    }
    match name {
        "type" => Some(types.intern(Type::TypeType)),
        "bytes" => Some(types.intern(Type::Bytes)),
        "opaque" => Some(types.intern(Type::Opaque)),
        "any" => Some(types.intern(Type::Any)),
        "void" => Some(types.intern(Type::Void)),
        _ => None,
    }
}

fn is_type_designator_expr(expr: &Expr) -> bool {
    match &expr.kind {
        ExprKind::TypeLiteral(_) => true,
        ExprKind::Ident(ident) | ExprKind::BuiltinIdent(ident) => {
            parse_int_type_name(&ident.text).is_some()
                || parse_float_type_name(&ident.text).is_some()
                || matches!(
                    ident.text.as_str(),
                    "u1" | "type" | "opaque" | "any" | "bytes" | "void"
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

fn is_compile_time_expr(expr: &Expr) -> bool {
    match &expr.kind {
        ExprKind::Literal(_) | ExprKind::TypeLiteral(_) => true,
        ExprKind::Ident(_) | ExprKind::BuiltinIdent(_) => is_type_designator_expr(expr),
        ExprKind::Unary { expr, .. } => is_compile_time_expr(expr),
        ExprKind::Binary { left, right, .. } => {
            is_compile_time_expr(left) && is_compile_time_expr(right)
        }
        ExprKind::Call(call) => match &call.callee.kind {
            ExprKind::BuiltinIdent(ident) => match ident.text.as_str() {
                "$as" => {
                    call.args.len() == 2
                        && is_type_designator_expr(&call.args[0].value)
                        && is_compile_time_expr(&call.args[1].value)
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
                "$typeof" => call.args.len() == 1 && is_compile_time_expr(&call.args[0].value),
                _ => false,
            },
            ExprKind::Ident(_) => {
                call.args.is_empty()
                    || call
                        .args
                        .iter()
                        .all(|arg| is_type_designator_expr(&arg.value))
            }
            _ => false,
        },
        ExprKind::Comptime { expr } | ExprKind::Inline { expr } => is_compile_time_expr(expr),
        ExprKind::ArrayLiteral(elements) | ExprKind::TupleLiteral(elements) => {
            elements.iter().all(is_compile_time_expr)
        }
        _ => false,
    }
}

fn strict_explicit_returns_enabled() -> bool {
    let env = std::env::var("DYN_STRICT_RETURNS").ok();
    let parse = |v: &str| matches!(v, "1" | "true" | "TRUE" | "on" | "ON");
    match env.as_deref() {
        Some("0") | Some("false") | Some("FALSE") | Some("off") | Some("OFF") => false,
        Some(v) => parse(v),
        None => true,
    }
}

fn valid_offsetof_designator(type_arg: &Expr, field_arg: &Expr) -> bool {
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

fn pattern_compatibility_issue(
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
            let Some(typed_id) = resolve_type_expr(ty, types) else {
                return None;
            };
            if !types_compatible(typed_id, scrutinee, types) {
                return Some(
                    "typed pattern annotation is incompatible with scrutinee type".to_string(),
                );
            }
            pattern_compatibility_issue(&pattern.kind, typed_id, types)
        }
    }
}

fn enum_literal_pattern_issue(pattern: &PatternKind, scrutinee: &ExprKind) -> Option<String> {
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
enum NumericLiteralClass {
    Integer,
    Float,
}

fn literal_numeric_class(lit: &PatternLiteral) -> Option<NumericLiteralClass> {
    match lit {
        PatternLiteral::Integer(_) => Some(NumericLiteralClass::Integer),
        PatternLiteral::Float(_) => Some(NumericLiteralClass::Float),
        _ => None,
    }
}

fn literal_pattern_compatible(lit: &PatternLiteral, scrutinee: TypeId, types: &TypeStore) -> bool {
    match lit {
        PatternLiteral::Integer(_) => matches!(
            types.get(scrutinee),
            Type::Int { .. } | Type::Float { .. } | Type::Unknown
        ),
        PatternLiteral::Float(_) => {
            matches!(types.get(scrutinee), Type::Float { .. } | Type::Unknown)
        }
        PatternLiteral::String(_) => {
            matches!(types.get(scrutinee), Type::Bytes | Type::Unknown)
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

fn extract_callee_name(callee: &Expr) -> Option<String> {
    match &callee.kind {
        ExprKind::Ident(ident) | ExprKind::BuiltinIdent(ident) => Some(ident.text.clone()),
        _ => None,
    }
}

fn unify_branch_types(
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
        (Type::Errorable(l_inner), Type::Errorable(r_inner)) => {
            let inner = unify_branch_types(l_inner, r_inner, types, diagnostics, file_path, expr);
            types.intern(Type::Errorable(inner))
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

fn resolve_type_expr(ty: &TypeExpr, types: &mut TypeStore) -> Option<TypeId> {
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
            if name.text == "bytes" {
                return Some(types.intern(Type::Bytes));
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
        TypeExprKind::Errorable { ok, .. } => {
            let ok = resolve_type_expr(ok, types)?;
            Some(types.intern(Type::Errorable(ok)))
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
                if let ExprKind::Fn(fn_expr) = &member.value.kind {
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

fn is_numeric(ty: TypeId, types: &TypeStore) -> bool {
    matches!(types.get(ty), Type::Int { .. } | Type::Float { .. })
}

fn validate_any_usage(
    ty: &TypeExpr,
    context: AnyUsageContext,
    diagnostics: &mut Vec<Diagnostic>,
    file_path: &std::path::Path,
) {
    match &ty.kind {
        TypeExprKind::Named(ident) if ident.text == "any" => {
            if !matches!(context, AnyUsageContext::FunctionParam) {
                diagnostics.push(
                    Diagnostic::error(
                        DiagnosticPhase::TypeChecker,
                        DiagnosticCode::E4005,
                        "'any' is only allowed in function parameter types",
                    )
                    .with_primary_file_label(
                        file_path.to_path_buf(),
                        Some(ty.span),
                        "use concrete type or opaque pointer here",
                    ),
                );
            }
        }
        TypeExprKind::Pointer { inner, .. } | TypeExprKind::Optional { inner } => {
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

fn types_compatible(expected: TypeId, actual: TypeId, types: &TypeStore) -> bool {
    if expected == actual {
        return true;
    }

    match (types.get(expected), types.get(actual)) {
        (Type::Optional(_), Type::Null) => true,
        (Type::Optional(expected_inner), Type::Optional(actual_inner)) => {
            types_compatible(*expected_inner, *actual_inner, types)
        }
        (Type::Errorable(inner), _) if *inner == actual => true,
        (Type::Errorable(expected_inner), Type::Errorable(actual_inner)) => {
            types_compatible(*expected_inner, *actual_inner, types)
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

fn maybe_coerce_literal_to_expected(
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

fn array_literal_elements_fit_type(
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
            (ExprKind::Literal(Literal::String(_)), Type::Bytes) => true,
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

fn tuple_index_literal(expr: &Expr) -> Option<usize> {
    let ExprKind::Literal(Literal::Integer(text)) = &expr.kind else {
        return None;
    };
    let value = parse_integer_literal_value(text)?;
    usize::try_from(value).ok()
}

fn integer_literal_fits_type(text: &str, signed: bool, bits: u16) -> bool {
    if bits == 0 {
        return false;
    }
    let Some(value) = parse_integer_literal_value(text) else {
        return false;
    };

    if signed {
        if bits >= 128 {
            return true;
        }
        let shift = u32::from(bits - 1);
        let min = -(1_i128 << shift);
        let max = (1_i128 << shift) - 1;
        return (min..=max).contains(&value);
    }

    if value < 0 {
        return false;
    }
    if bits >= 128 {
        return true;
    }
    let max = (1_u128 << u32::from(bits)) - 1;
    (value as u128) <= max
}

fn float_literal_fits_type(text: &str, bits: u16) -> bool {
    let cleaned = text.replace('_', "");
    let Ok(value) = cleaned.parse::<f64>() else {
        return false;
    };
    if bits >= 64 {
        return true;
    }
    if bits >= 32 {
        let narrowed = value as f32;
        return !(value.is_finite() && narrowed.is_infinite());
    }
    true
}

fn parse_integer_literal_value(text: &str) -> Option<i128> {
    let cleaned = text.trim().replace('_', "");
    let (negative, unsigned_part) = if let Some(rest) = cleaned.strip_prefix('-') {
        (true, rest)
    } else {
        (false, cleaned.as_str())
    };

    let parse_radix = |digits: &str, radix: u32| -> Option<i128> {
        let magnitude = u128::from_str_radix(digits, radix).ok()?;
        if magnitude > i128::MAX as u128 {
            return None;
        }
        let as_i128 = magnitude as i128;
        if negative {
            as_i128.checked_neg()
        } else {
            Some(as_i128)
        }
    };

    if let Some(rest) = unsigned_part
        .strip_prefix("0x")
        .or_else(|| unsigned_part.strip_prefix("0X"))
    {
        return parse_radix(rest, 16);
    }
    if let Some(rest) = unsigned_part
        .strip_prefix("0b")
        .or_else(|| unsigned_part.strip_prefix("0B"))
    {
        return parse_radix(rest, 2);
    }
    if let Some(rest) = unsigned_part
        .strip_prefix("0o")
        .or_else(|| unsigned_part.strip_prefix("0O"))
    {
        return parse_radix(rest, 8);
    }

    cleaned.parse::<i128>().ok()
}

fn numeric_result_type(left: TypeId, right: TypeId, types: &mut TypeStore) -> TypeId {
    match (types.get(left).clone(), types.get(right).clone()) {
        (Type::Float { bits: lb }, Type::Float { bits: rb }) => {
            types.intern(Type::Float { bits: lb.max(rb) })
        }
        (Type::Float { bits }, Type::Int { .. }) | (Type::Int { .. }, Type::Float { bits }) => {
            types.intern(Type::Float { bits })
        }
        (
            Type::Int {
                signed: ls,
                bits: lb,
            },
            Type::Int {
                signed: rs,
                bits: rb,
            },
        ) => {
            let signed = ls || rs;
            types.intern(Type::Int {
                signed,
                bits: lb.max(rb),
            })
        }
        _ => types.intern(Type::Unknown),
    }
}

fn parse_int_type_name(name: &str) -> Option<Type> {
    if name == "isize" {
        return Some(Type::Int {
            signed: true,
            bits: 64,
        });
    }
    if name == "usize" {
        return Some(Type::Int {
            signed: false,
            bits: 64,
        });
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
    Some(Type::Int { signed, bits })
}

fn parse_float_type_name(name: &str) -> Option<Type> {
    let rest = name.strip_prefix('f')?;
    if rest.is_empty() {
        return None;
    }
    let bits = rest.parse::<u16>().ok()?;
    Some(Type::Float { bits })
}

fn insert_builtin_signatures(
    signatures: &mut BTreeMap<String, FnSignature>,
    types: &mut TypeStore,
) {
    let usize_ty = types.intern(Type::Int {
        signed: false,
        bits: 64,
    });
    let u32_ty = types.intern(Type::Int {
        signed: false,
        bits: 32,
    });
    let i32_ty = types.intern(Type::Int {
        signed: true,
        bits: 32,
    });
    let any_ty = types.intern(Type::Any);
    let identity_i32_fn_ty = types.intern(Type::Function {
        param_types: vec![i32_ty],
        param_names: vec![None],
        has_defaults: vec![false],
        return_type: i32_ty,
    });
    let bytes_ty = types.intern(Type::Bytes);

    signatures.insert(
        "__dyn_alloc".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("size".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("align".to_string()),
                    has_default: false,
                },
            ],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "__dyn_realloc".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("ptr".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("old_size".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("new_size".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("align".to_string()),
                    has_default: false,
                },
            ],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "__dyn_free".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("ptr".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("size".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("align".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_c_allocator".to_string(),
        FnSignature {
            params: vec![],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "__dyn_test_failing_allocator".to_string(),
        FnSignature {
            params: vec![],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "__dyn_test_set_fail_after".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("remaining_successes".to_string()),
                has_default: false,
            }],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_test_identity_i32_fn".to_string(),
        FnSignature {
            params: vec![],
            return_type: identity_i32_fn_ty,
        },
    );
    signatures.insert(
        "__dyn_arena_allocator".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("backing".to_string()),
                has_default: false,
            }],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "__dyn_arena_reset".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("arena".to_string()),
                has_default: false,
            }],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_arena_deinit".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("arena".to_string()),
                has_default: false,
            }],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_alloc_with".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("alloc".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("size".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("align".to_string()),
                    has_default: false,
                },
            ],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "__dyn_realloc_with".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("alloc".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("ptr".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("old_size".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("new_size".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("align".to_string()),
                    has_default: false,
                },
            ],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "__dyn_free_with".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("alloc".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("ptr".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("size".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("align".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_mem_copy".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("dst".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("src".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("size".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_mem_move".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("dst".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("src".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("size".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_mem_set".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("dst".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("byte_value".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("size".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_mem_eq".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("lhs".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("rhs".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("size".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_i32_init".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("alloc".to_string()),
                has_default: false,
            }],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_i32_deinit".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("handle".to_string()),
                has_default: false,
            }],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_i32_len".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("handle".to_string()),
                has_default: false,
            }],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_i32_cap".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("handle".to_string()),
                has_default: false,
            }],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_i32_push".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("value".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_i32_get".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("index".to_string()),
                    has_default: false,
                },
            ],
            return_type: types.intern(Type::Int {
                signed: true,
                bits: 32,
            }),
        },
    );
    signatures.insert(
        "__dyn_vec_i32_set".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("index".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("value".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_i32_pop".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("handle".to_string()),
                has_default: false,
            }],
            return_type: types.intern(Type::Int {
                signed: true,
                bits: 32,
            }),
        },
    );
    signatures.insert(
        "__dyn_vec_i32_clear".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("handle".to_string()),
                has_default: false,
            }],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_i32_reserve".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("new_cap".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "std_vec_i32_init".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("alloc".to_string()),
                has_default: false,
            }],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "std_vec_i32_deinit".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("handle".to_string()),
                has_default: false,
            }],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "std_vec_i32_len".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("handle".to_string()),
                has_default: false,
            }],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "std_vec_i32_cap".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("handle".to_string()),
                has_default: false,
            }],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "std_vec_i32_push".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("value".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "std_vec_i32_get".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("index".to_string()),
                    has_default: false,
                },
            ],
            return_type: types.intern(Type::Int {
                signed: true,
                bits: 32,
            }),
        },
    );
    signatures.insert(
        "std_vec_i32_set".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("index".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("value".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "std_vec_i32_pop".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("handle".to_string()),
                has_default: false,
            }],
            return_type: types.intern(Type::Int {
                signed: true,
                bits: 32,
            }),
        },
    );
    signatures.insert(
        "std_vec_i32_clear".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("handle".to_string()),
                has_default: false,
            }],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "std_vec_i32_reserve".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("new_cap".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_raw_init".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("alloc".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("elem_size".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("elem_align".to_string()),
                    has_default: false,
                },
            ],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_raw_deinit".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("handle".to_string()),
                has_default: false,
            }],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_raw_len".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("handle".to_string()),
                has_default: false,
            }],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_raw_cap".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("handle".to_string()),
                has_default: false,
            }],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_raw_push_u64".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("value".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_raw_get_u64".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("index".to_string()),
                    has_default: false,
                },
            ],
            return_type: types.intern(Type::Int {
                signed: false,
                bits: 64,
            }),
        },
    );
    signatures.insert(
        "__dyn_vec_raw_set_u64".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("index".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("value".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_raw_pop_u64".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("handle".to_string()),
                has_default: false,
            }],
            return_type: types.intern(Type::Int {
                signed: false,
                bits: 64,
            }),
        },
    );
    signatures.insert(
        "__dyn_vec_raw_clear".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("handle".to_string()),
                has_default: false,
            }],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_raw_reserve".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("new_cap".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_raw_ptr".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("index".to_string()),
                    has_default: false,
                },
            ],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_raw_push_bytes".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("src".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("src_size".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_raw_get_bytes".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("index".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("dst".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("dst_size".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_raw_set_bytes".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("index".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("src".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("src_size".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_vec_raw_pop_bytes".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("dst".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("dst_size".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "std_vec_init".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("alloc".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("elem_size".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("elem_align".to_string()),
                    has_default: false,
                },
            ],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "std_vec_deinit".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("handle".to_string()),
                has_default: false,
            }],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "std_vec_len".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("handle".to_string()),
                has_default: false,
            }],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "std_vec_cap".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("handle".to_string()),
                has_default: false,
            }],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "std_vec_push_u64".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("value".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "std_vec_get_u64".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("index".to_string()),
                    has_default: false,
                },
            ],
            return_type: types.intern(Type::Int {
                signed: false,
                bits: 64,
            }),
        },
    );
    signatures.insert(
        "std_vec_set_u64".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("index".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("value".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "std_vec_pop_u64".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("handle".to_string()),
                has_default: false,
            }],
            return_type: types.intern(Type::Int {
                signed: false,
                bits: 64,
            }),
        },
    );
    signatures.insert(
        "std_vec_clear".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("handle".to_string()),
                has_default: false,
            }],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "std_vec_reserve".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("new_cap".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "std_vec_ptr".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("index".to_string()),
                    has_default: false,
                },
            ],
            return_type: usize_ty,
        },
    );
    signatures.insert(
        "std_vec_push_bytes".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("src".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("src_size".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "std_vec_get_bytes".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("index".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("dst".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("dst_size".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "std_vec_set_bytes".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("index".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("src".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("src_size".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "std_vec_pop_bytes".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("handle".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("dst".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("dst_size".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_io_write_i32".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("value".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("newline".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "__dyn_io_write".to_string(),
        FnSignature {
            params: vec![
                FnParamSpec {
                    name: Some("value".to_string()),
                    has_default: false,
                },
                FnParamSpec {
                    name: Some("newline".to_string()),
                    has_default: false,
                },
            ],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "std_io_print_i32".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("value".to_string()),
                has_default: false,
            }],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "std_io_println_i32".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("value".to_string()),
                has_default: false,
            }],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "std_io_print".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("value".to_string()),
                has_default: false,
            }],
            return_type: u32_ty,
        },
    );
    signatures.insert(
        "std_io_println".to_string(),
        FnSignature {
            params: vec![FnParamSpec {
                name: Some("value".to_string()),
                has_default: false,
            }],
            return_type: u32_ty,
        },
    );

    let _ = (bytes_ty, any_ty);
}

fn type_to_string(type_id: TypeId, types: &TypeStore) -> String {
    match types.get(type_id) {
        Type::Unknown => "unknown".to_string(),
        Type::TypeType => "type".to_string(),
        Type::TypeParam(name) => name.clone(),
        Type::Bool => "u1".to_string(),
        Type::Int { signed, bits } => {
            if *signed {
                format!("i{bits}")
            } else {
                format!("u{bits}")
            }
        }
        Type::Float { bits } => format!("f{bits}"),
        Type::Bytes => "[]u8".to_string(),
        Type::Any => "any".to_string(),
        Type::Opaque => "opaque".to_string(),
        Type::Void => "void".to_string(),
        Type::Null => "null".to_string(),
        Type::Optional(inner) => format!("?{}", type_to_string(*inner, types)),
        Type::Errorable(ok) => format!("{}!", type_to_string(*ok, types)),
        Type::Pointer { inner, mutable } => {
            if *mutable {
                format!("*mut {}", type_to_string(*inner, types))
            } else {
                format!("*{}", type_to_string(*inner, types))
            }
        }
        Type::Array(elem) => format!("[?]{}", type_to_string(*elem, types)),
        Type::Slice { element, mutable } => {
            if *mutable {
                format!("[]mut {}", type_to_string(*element, types))
            } else {
                format!("[]{}", type_to_string(*element, types))
            }
        }
        Type::Tuple(elements) => {
            let rendered = elements
                .iter()
                .map(|element| type_to_string(*element, types))
                .collect::<Vec<_>>()
                .join(", ");
            format!("{{{rendered}}}")
        }
        Type::Applied { callee, args } => {
            let rendered = args
                .iter()
                .map(|arg| type_to_string(*arg, types))
                .collect::<Vec<_>>()
                .join(", ");
            format!("{}({})", callee, rendered)
        }
        Type::Function { param_types, .. } => format!("fn/{}", param_types.len()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::compiler::pipeline::parse_project_with_module_units;
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn make_temp_dir() -> PathBuf {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("time should be monotonic")
            .as_nanos();
        let path = std::env::temp_dir().join(format!("dyn_typeck_{unique}"));
        fs::create_dir_all(&path).expect("temp directory should be created");
        path
    }

    #[test]
    fn reports_type_mismatch_on_annotated_binding() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module main\na: i32 = 1.0\n")
            .expect("file should be written");
        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));
        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_null_assignment_without_mut() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module main\na: ?i32 = null\n")
            .expect("file should be written");
        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4006));
        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_call_arity_issues() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nadd := (x: i32, y: i32) i32 => x + y\na := add(1)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));
        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_direct_call_argument_type_mismatch() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nadd := (x: i32, y: i32) i32 => x + y\na := add(true, 2)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("call argument type mismatch")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn infers_or_fallback_type_for_optional_values() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module main\na: i32 = (null or 1)\n")
            .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn infers_or_fallback_type_for_errorable_values() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nErr := enum { Bad }\nwork := () i32!Err => 1\na: i32 = work() or 0\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn allows_or_fallback_error_capture_binding() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmut n: ?i32 = null\na: i32 = n or |err| if err == err 7 else 0\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn allows_if_optional_capture_binding() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\ncheck := (n: ?i32) i32 => if n: |v| v else 0\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn supports_force_unwrap_on_errorable_values() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nErr := enum { Bad }\nwork := () i32!Err => 1\na: i32 = work().!\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn allows_widening_unsigned_into_signed() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module main\na: i32 = 255\n")
            .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_narrow_integer_annotation_for_fitting_literal() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module main\na: i31 = 3\n").expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_f32_annotation_for_float_literal() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module main\na: f32 = 1.5\n")
            .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_array_annotation_for_integer_literal_elements() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module main\nxs: [3]i32 = [1, 2, 3]\n")
            .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_array_annotation_for_narrow_float_literal_elements() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module main\nxs: [1]f32 = [1.0]\n")
            .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_slice_binding_from_array_slice_expression() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  i: [4]i32 = [1, 2, 3, 4]\n  k: []i32 = i[0..2]\n  return k[0]\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_mut_pointer_u1_binding_from_mut_ref() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  mut d: u1 = false\n  q: *mut u1 = &d\n  q.* = true\n  return if d 1 else 0\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn allows_literal_argument_for_narrow_integer_parameter() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nf := (x: i31) i31 => x\nok: i31 = f(3)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn rejects_out_of_range_integer_literal_for_narrow_annotation() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module main\na: i8 = 1000\n")
            .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn infers_iterate_binding_type_for_slice_elements() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nsum := (xs: []i32) i32 {\n  mut acc: i32 = 0\n  for xs: |v| { acc += v }\n  return acc\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(
            !diagnostics.iter().any(|diagnostic| {
                diagnostic.code == DiagnosticCode::E4005
                    && diagnostic
                        .message
                        .contains("compound assignment requires numeric target and value")
            }),
            "{diagnostics:#?}"
        );

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn infers_iterate_binding_type_for_bytes_elements() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nsum := (b: bytes) i32 {\n  mut acc: i32 = 0\n  for b: |ch| { acc += ch }\n  return acc\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(
            !diagnostics.iter().any(|diagnostic| {
                diagnostic.code == DiagnosticCode::E4005
                    && diagnostic
                        .message
                        .contains("compound assignment requires numeric target and value")
            }),
            "{diagnostics:#?}"
        );

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn suppresses_compound_assignment_type_error_when_operand_unknown() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  mut acc: i32 = 0\n  acc += missing\n  return acc\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("compound assignment requires numeric target and value")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn rejects_signed_into_narrow_unsigned() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module main\na: u8 = -1\n").expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_non_bool_match_guard_type() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := match 1 { 1 if 2: 1, _: 0 }\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005 && diagnostic.message.contains("match guard")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_incompatible_match_pattern_for_scrutinee() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := match 1 { \"x\": 1, _: 0 }\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("pattern is incompatible")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn allows_optional_branch_unification_with_null_and_value() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na: ?i32 = if true null else 1\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_enum_pattern_incompatible_with_numeric_scrutinee() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := match 1 { .Ok: 1, _: 0 }\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("enum pattern requires enum-typed scrutinee")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_non_numeric_range_pattern_endpoints() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := match 1 { \"a\"..\"z\": 1, _: 0 }\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("range endpoint literal is incompatible")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_mixed_numeric_range_endpoint_kinds() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := match 1 { 1..2.0: 1, _: 0 }\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("range endpoint literal is incompatible")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_float_range_for_integer_scrutinee() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := match 1 { 1.0..2.0: 1, _: 0 }\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("range endpoint literal is incompatible")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn type_checks_match_identifier_binding_in_arm_value() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na: i32 = match 1 { x: x + 1, _: 0 }\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("invalid operands for numeric operator")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_enum_literal_variant_mismatch_in_match_pattern() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := match .Ready { .Waiting: 1, _: 0 }\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("variant does not match")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_enum_literal_payload_arity_mismatch_in_match_pattern() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := match .Ready(1) { .Ready(x, y): x, _: 0 }\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005 && diagnostic.message.contains("payload arity")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn parses_pointer_sized_integer_aliases() {
        assert_eq!(
            parse_int_type_name("usize"),
            Some(Type::Int {
                signed: false,
                bits: 64,
            })
        );
        assert_eq!(
            parse_int_type_name("isize"),
            Some(Type::Int {
                signed: true,
                bits: 64,
            })
        );
    }

    #[test]
    fn validates_builtin_allocator_call_arity() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module main\na := __dyn_alloc(16)\n")
            .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("missing required argument")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn validates_builtin_memory_call_arity() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := __dyn_mem_set(0, 255)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("missing required argument")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn validates_builtin_vec_call_arity() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := __dyn_vec_i32_push(0)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("missing required argument")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn validates_builtin_failing_allocator_call_arity() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := __dyn_test_set_fail_after()\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("missing required argument")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn validates_std_vec_wrapper_call_arity() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := std_vec_i32_push(0)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("missing required argument")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn validates_raw_vec_call_arity() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := __dyn_vec_raw_init(1, 4)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("missing required argument")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn validates_std_vec_raw_wrapper_call_arity() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module main\na := std_vec_init(1, 8)\n")
            .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("missing required argument")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn validates_raw_vec_bytes_call_arity() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := __dyn_vec_raw_push_bytes(0, 0)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("missing required argument")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn validates_std_vec_bytes_wrapper_call_arity() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := std_vec_pop_bytes(0, 0)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("missing required argument")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_applied_vec_type_annotation_shape() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nxs: Vec(i32) = placeholder\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_applied_vec_type_argument_mismatch() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na: Vec(i32) = placeholder\nb: Vec(u64) = a\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn allows_mut_pointer_to_const_pointer_coercion() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmut x: i32 = 1\npm: *mut i32 = &x\npc: *i32 = pm\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn rejects_const_pointer_to_mut_pointer_coercion() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nx: i32 = 1\npc: *i32 = &x\npm: *mut i32 = pc\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn rejects_assignment_through_const_pointer() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  x: i32 = 1\n  pc: *i32 = &x\n  pc.* = 2\n  0\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4006));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn allows_assignment_through_mut_pointer() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  mut x: i32 = 1\n  pm: *mut i32 = &x\n  pm.* = 2\n  0\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4006));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn validates_identity_function_pointer_builtin_arity() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := __dyn_test_identity_i32_fn(1)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn validates_arena_allocator_builtin_arity() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := __dyn_arena_reset()\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_struct_instance_member_with_self_receiver_name() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { do := (self: Thing) i32 => 0 }\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("first parameter is not named self")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_struct_instance_member_with_non_self_receiver_name() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { do := (this: Thing) i32 => 0 }\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("first parameter is not named self")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_mut_pointer_receiver_call_on_immutable_binding() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nmain := () i32 {\n  t := Thing{}\n  t.touch()\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4006
                && diagnostic
                    .message
                    .contains("cannot call mut receiver method on immutable value")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_mut_pointer_receiver_call_on_mutable_binding() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nmain := () i32 {\n  mut t := Thing{}\n  t.touch()\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4006
                && diagnostic
                    .message
                    .contains("cannot call mut receiver method on immutable value")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_mut_pointer_receiver_call_on_typed_mutable_binding() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nmain := () i32 {\n  mut t: Thing = Thing{}\n  t.touch()\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4006
                && diagnostic
                    .message
                    .contains("cannot call mut receiver method on immutable value")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_mut_pointer_receiver_call_on_immutable_field_receiver() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nHolder := struct { item: Thing }\nmain := () i32 {\n  h := Holder{item: Thing{}}\n  h.item.touch()\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4006
                && diagnostic
                    .message
                    .contains("cannot call mut receiver method on immutable value")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_mut_pointer_receiver_call_on_mutable_field_receiver() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nHolder := struct { item: Thing }\nmain := () i32 {\n  mut h := Holder{item: Thing{}}\n  h.item.touch()\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4006
                && diagnostic
                    .message
                    .contains("cannot call mut receiver method on immutable value")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_mut_pointer_receiver_call_on_temporary_value() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nmain := () i32 {\n  Thing{}.touch()\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4006
                && diagnostic
                    .message
                    .contains("cannot call mut receiver method on immutable value")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_function_value_call_arity_mismatch() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  f := (x: i32, y: i32) i32 => x + y\n  f(1)\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("arity mismatch")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_call_on_non_callable_value() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  x := 1\n  return x()\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("not a function")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_opaque_pointer_erasure_from_typed_pointer() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  mut x: i32 = 1\n  p: *mut i32 = &x\n  erased: *mut opaque = p\n  return if erased == null 1 else 0\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_u1_annotation_with_bool_literal() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  mut d: u1 = false\n  d = true\n  return if d 1 else 0\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_bytes_annotation_with_string_literal() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module main\nb: bytes = \"hi\"\n")
            .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn rejects_opaque_pointer_as_typed_pointer_without_cast() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  mut x: i32 = 1\n  p: *mut i32 = &x\n  erased: *mut opaque = p\n  typed: *mut i32 = erased\n  typed.*\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_any_in_function_parameter_type() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nuse_any := (x: any) i32 => 0\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("only allowed in function parameter")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn rejects_any_in_binding_annotation() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module main\nx: any = 0\n").expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("only allowed in function parameter")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn allows_any_parameter_to_flow_into_usize_context() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\naddr := (x: any) usize => x\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005 && diagnostic.message.contains("type mismatch")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_function_value_call_argument_type_mismatch() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  f := (x: i32) i32 => x\n  f(true)\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("function value argument type mismatch")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_function_value_generic_argument_type_mismatch() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nid := (T: type, v: T) T => v\nmain := () i32 {\n  f := id\n  f(i32, true)\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("function value argument type mismatch")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn specializes_function_value_generic_return_type() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nid := (T: type, v: T) T => v\nmain := () i32 {\n  f := id\n  ok: i32 = f(i32, 1)\n  bad: u64 = f(i32, 1)\n  ok\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("type mismatch for 'bad'")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn supports_basic_builtin_cast_and_sizeof_calls() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := $as(i32, 1)\nb := $sizeof(i32)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn supports_builtin_cast_between_usize_and_pointer() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  p := $as(*mut i32, __dyn_alloc(4, 4))\n  q := $as(usize, p)\n  return if q != 0 1 else 0\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn supports_builtin_cast_from_slice_to_usize() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  xs: [2]i32 = [1, 2]\n  s: []i32 = xs[..]\n  p := $as(usize, s)\n  return if p != 0 1 else 0\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn supports_basic_builtin_alignof_and_offsetof_calls() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := $alignof(i32)\nb := $offsetof(i32, 0)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_comptime_builtin_expression() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module main\na := comp $sizeof(i32)\n")
            .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("comptime expression must be compile-time evaluable")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_comptime_zero_arg_function_call_expression() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmake := () i32 => 1\na := comp make()\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("comptime expression must be compile-time evaluable")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_comptime_builtin_expression_with_type_constructor_call() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nVec := (T: type) type => struct { items: []T }\na := comp $sizeof(Vec(i32))\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("comptime expression must be compile-time evaluable")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_non_const_comptime_expression() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nid := (x: i32) i32 => x\na := comp id(1)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("comptime expression must be compile-time evaluable")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_self_builtin_in_method_context() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { f := (self: *Thing) type => $Self() }\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("$Self is only available in self method context")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_self_builtin_outside_method_context() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module main\na := $Self()\n")
            .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("$Self is only available in self method context")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_builtin_offsetof_invalid_struct_field_designator() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := $offsetof(struct { a: u8, b: i32 }, c)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("$offsetof field designator is invalid")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_builtin_offsetof_invalid_field_designator_expression_kind() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := $offsetof(i32, \"x\")\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("$offsetof field designator is invalid")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_builtin_offsetof_invalid_named_struct_field_designator() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nData := struct { a: u8, b: i32 }\na := $offsetof(Data, c)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("$offsetof field designator is invalid for named struct type")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn supports_basic_builtin_typeof_call() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module main\nt: type = $typeof(1)\n")
            .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_type_designator_argument_for_type_parameter() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmeta := (T: type) type => T\nout: type = meta(i32)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("type designator")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_non_type_designator_argument_for_type_parameter() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmeta := (T: type) type => T\nout: type = meta(123)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("type designator")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn specializes_unknown_return_type_from_type_parameter_argument() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nid := (T: type, v: i32) T => v\nok: i32 = id(i32, 1)\nbad: u64 = id(i32, 1)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("type mismatch for 'bad'")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn enforces_value_argument_against_bound_type_parameter() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nid := (T: type, v: T) T => v\nok: i32 = id(i32, 1)\nbad: i32 = id(i32, true)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("call argument type mismatch")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn specializes_return_type_from_value_inferred_type_parameter() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nid := (v: T) T => v\nok: i32 = id(1)\nbad: u64 = id(1)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("type mismatch for 'bad'")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn enforces_bound_type_parameter_with_named_arguments() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nid := (T: type, v: T) T => v\nok: i32 = id(v: 1, T: i32)\nbad: i32 = id(v: true, T: i32)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("call argument type mismatch")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_compile_error_builtin() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\na := $compile_error(\"nope\")\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic.message.contains("$compile_error invoked")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_panic_builtin_non_string_message() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module main\na := $panic(123)\n")
            .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("$panic message must be bytes/string compatible")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_tuple_index_with_compile_time_literal() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module main\na: i32 = {1, 2, 3}[1]\n")
            .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn reports_non_literal_tuple_index() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nidx := 1\na := {1, 2, 3}[idx]\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("tuple index must be a compile-time integer literal")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn accepts_generic_type_parameter_call_shape() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nprint := (T: type, value: T) i32 => if T == i32 1 else 0\nok := print(i32, 7)\n",
        )
        .expect("file should be written");

        let (_parsed, units) =
            parse_project_with_module_units(&root).expect("project should parse and merge");
        let diagnostics = type_check_modules(&units);
        assert!(!diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }
}
