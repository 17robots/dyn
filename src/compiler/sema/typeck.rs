use std::collections::VecDeque;
use std::collections::{BTreeMap, BTreeSet};

use crate::compiler::ast::{
    AssignOp, BinaryOp, Expr, ExprKind, FnBody, Literal, MatchArm, PatternKind, PatternLiteral,
    Stmt, TypeExpr, TypeExprKind, UnaryOp,
};
use crate::compiler::diagnostics::{Diagnostic, DiagnosticCode, DiagnosticPhase, SourceSpan};
use crate::compiler::sema::comptime::{is_compile_time_expr, is_type_designator_expr};
use crate::compiler::sema::module_unit::{DeclKind, DeclStub, ModuleUnit};

mod helpers;
mod infer;

use self::helpers::{
    bytes_type, float_literal_fits_type, integer_literal_fits_type, numeric_result_type,
    parse_float_type_name, parse_int_type_name, tuple_index_literal, type_to_string,
};

use self::infer::*;

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
    comp: bool,
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
        let mut nominal_bindings = BTreeMap::<String, NominalBinding>::new();
        let mut signatures = BTreeMap::<String, FnSignature>::new();
        let mut_ptr_receiver_methods = collect_mut_pointer_receiver_methods(unit);
        let struct_field_nominals = collect_struct_field_nominal_types(unit);
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
                        comp: param.comp,
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
                        comp: param.comp,
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

#[cfg(test)]
mod tests;
