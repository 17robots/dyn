use std::collections::{BTreeMap, BTreeSet};

use crate::compiler::ast::{AssignOp, BinaryOp, UnaryOp};
use crate::compiler::diagnostics::{Diagnostic, DiagnosticCode, DiagnosticPhase};
use crate::compiler::hir::{
    HirCallArg, HirExpr, HirExprKind, HirForExpr, HirLiteral, HirPattern, HirProgram,
};
use crate::compiler::mir::{
    MirBasicBlock, MirBlockId, MirFunction, MirGlobal, MirGlobalInit, MirInstr, MirModule,
    MirProgram, MirTerminator, MirValue, MirValueId, MirValueType,
};
use crate::compiler::module_resolver::{ModuleId, ModuleKey};

mod function_lowerer;
mod helpers;

#[cfg(test)]
use self::helpers::builtin_offsetof_value;
use self::helpers::{
    builtin_offsetof_for_type_name, comptime_truthy, enum_type_repr_bits, enum_type_variants,
    eval_comptime_binary, eval_comptime_cast, layout_for_builtin_type_name, literal_type,
    merge_types, parse_function_return_hint, parse_i64_literal, parse_type_hint,
    self_type_literal_from_param_hint, substitute_type_locals, type_literal_name_for_ident,
};

pub fn lower_hir_to_mir(hir: &HirProgram) -> MirProgram {
    lower_hir_to_mir_with_diagnostics(hir).0
}

pub fn lower_hir_to_mir_with_diagnostics(hir: &HirProgram) -> (MirProgram, Vec<Diagnostic>) {
    let module_source_paths = BTreeMap::new();
    lower_hir_to_mir_with_diagnostics_and_paths(hir, &module_source_paths)
}

pub fn lower_hir_to_mir_with_diagnostics_and_paths(
    hir: &HirProgram,
    module_source_paths: &BTreeMap<ModuleId, std::path::PathBuf>,
) -> (MirProgram, Vec<Diagnostic>) {
    let module_ids_by_key = hir
        .modules
        .iter()
        .map(|module| (module.key.clone(), module.module_id))
        .collect::<BTreeMap<_, _>>();

    let module_exports_by_id = hir
        .modules
        .iter()
        .map(|module| {
            let mut exports = module
                .items
                .iter()
                .map(|item| item.name.clone())
                .collect::<Vec<_>>();
            exports.extend(
                module
                    .extern_functions
                    .iter()
                    .map(|extern_fn| extern_fn.name.clone()),
            );
            (module.module_id, exports)
        })
        .collect::<BTreeMap<_, _>>();

    let global_enum_type_literals = hir
        .modules
        .iter()
        .flat_map(|module| {
            module.items.iter().filter_map(|item| {
                if let HirExprKind::TypeLiteral(type_name) = &item.value.kind {
                    Some((
                        format!("#{}::{}", module.module_id.0, item.name),
                        type_name.clone(),
                    ))
                } else {
                    None
                }
            })
        })
        .collect::<BTreeMap<_, _>>();
    let (global_enum_repr_bits_by_name, global_enum_variant_tags_by_name) =
        collect_enum_type_metadata(&global_enum_type_literals);

    let mut qualified_function_return_types = BTreeMap::new();
    let mut qualified_function_return_hints = BTreeMap::new();
    let mut qualified_function_param_names = BTreeMap::new();
    let mut qualified_function_param_defaults = BTreeMap::new();
    let mut qualified_function_param_type_hints = BTreeMap::new();
    let mut qualified_function_exprs = BTreeMap::new();
    let mut qualified_inline_function_names = BTreeSet::new();

    for module in &hir.modules {
        for item in &module.items {
            let qualified_name = qualified_function_name(module.module_id, &item.name);
            qualified_function_return_types.insert(
                qualified_name.clone(),
                item.inferred_type
                    .as_deref()
                    .or(item.type_hint.as_deref())
                    .map(|text| {
                        parse_function_return_hint(text).unwrap_or_else(|| parse_type_hint(text))
                    })
                    .unwrap_or(MirValueType::Unknown),
            );
            qualified_function_return_hints.insert(
                qualified_name.clone(),
                item.inferred_type
                    .as_ref()
                    .cloned()
                    .or_else(|| item.type_hint.as_ref().cloned()),
            );
            qualified_function_exprs.insert(qualified_name.clone(), item.value.clone());

            match &item.value.kind {
                HirExprKind::Function {
                    params,
                    param_types,
                    param_defaults,
                    ..
                } => {
                    qualified_function_param_names.insert(qualified_name.clone(), params.clone());
                    qualified_function_param_defaults
                        .insert(qualified_name.clone(), param_defaults.clone());
                    qualified_function_param_type_hints
                        .insert(qualified_name.clone(), param_types.clone());
                }
                HirExprKind::Inline { expr } => {
                    if let HirExprKind::Function {
                        params,
                        param_types,
                        param_defaults,
                        ..
                    } = &expr.kind
                    {
                        qualified_function_param_names
                            .insert(qualified_name.clone(), params.clone());
                        qualified_function_param_defaults
                            .insert(qualified_name.clone(), param_defaults.clone());
                        qualified_function_param_type_hints
                            .insert(qualified_name.clone(), param_types.clone());
                        qualified_inline_function_names.insert(qualified_name);
                    }
                }
                _ => {}
            }
        }
        for extern_fn in &module.extern_functions {
            let qualified_name = qualified_function_name(module.module_id, &extern_fn.name);
            let return_ty = extern_fn
                .return_type
                .as_deref()
                .map(parse_type_hint)
                .unwrap_or(MirValueType::Unknown);
            qualified_function_return_types.insert(qualified_name.clone(), return_ty.clone());
            qualified_function_return_types.insert(extern_fn.name.clone(), return_ty);
            qualified_function_return_hints
                .insert(qualified_name.clone(), extern_fn.return_type.clone());
            qualified_function_return_hints
                .insert(extern_fn.name.clone(), extern_fn.return_type.clone());
            qualified_function_param_type_hints
                .insert(qualified_name.clone(), extern_fn.param_type_hints.clone());
            qualified_function_param_type_hints
                .insert(extern_fn.name.clone(), extern_fn.param_type_hints.clone());
        }
    }

    let mut diagnostics = Vec::new();
    let modules = hir
        .modules
        .iter()
        .map(|module| {
            let module_source_path = module_source_paths
                .get(&module.module_id)
                .cloned()
                .unwrap_or_else(|| module_key_source_path(&module.key));
            let mut module_diagnostics = Vec::new();
            let local_function_return_types = module
                .items
                .iter()
                .map(|item| {
                    (
                        item.name.clone(),
                        item.inferred_type
                            .as_deref()
                            .or(item.type_hint.as_deref())
                            .map(|text| {
                                parse_function_return_hint(text)
                                    .unwrap_or_else(|| parse_type_hint(text))
                            })
                            .unwrap_or(MirValueType::Unknown),
                    )
                })
                .collect::<BTreeMap<_, _>>();
            let local_extern_return_types = module
                .extern_functions
                .iter()
                .map(|extern_fn| {
                    (
                        extern_fn.name.clone(),
                        extern_fn
                            .return_type
                            .as_deref()
                            .map(parse_type_hint)
                            .unwrap_or(MirValueType::Unknown),
                    )
                })
                .collect::<BTreeMap<_, _>>();
            let local_function_return_hints = module
                .items
                .iter()
                .map(|item| {
                    (
                        item.name.clone(),
                        item.inferred_type
                            .as_ref()
                            .cloned()
                            .or_else(|| item.type_hint.as_ref().cloned()),
                    )
                })
                .collect::<BTreeMap<_, _>>();
            let local_extern_return_hints = module
                .extern_functions
                .iter()
                .map(|extern_fn| (extern_fn.name.clone(), extern_fn.return_type.clone()))
                .collect::<BTreeMap<_, _>>();
            let local_function_param_names = module
                .items
                .iter()
                .filter_map(|item| {
                    if let HirExprKind::Function { params, .. } = &item.value.kind {
                        Some((item.name.clone(), params.clone()))
                    } else {
                        None
                    }
                })
                .collect::<BTreeMap<_, _>>();
            let local_function_param_defaults = module
                .items
                .iter()
                .filter_map(|item| {
                    if let HirExprKind::Function { param_defaults, .. } = &item.value.kind {
                        Some((item.name.clone(), param_defaults.clone()))
                    } else {
                        None
                    }
                })
                .collect::<BTreeMap<_, _>>();
            let local_function_param_type_hints = module
                .items
                .iter()
                .filter_map(|item| match &item.value.kind {
                    HirExprKind::Function { param_types, .. } => {
                        Some((item.name.clone(), param_types.clone()))
                    }
                    HirExprKind::Inline { expr } => {
                        if let HirExprKind::Function { param_types, .. } = &expr.kind {
                            Some((item.name.clone(), param_types.clone()))
                        } else {
                            None
                        }
                    }
                    _ => None,
                })
                .collect::<BTreeMap<_, _>>();
            let local_extern_param_type_hints = module
                .extern_functions
                .iter()
                .map(|extern_fn| (extern_fn.name.clone(), extern_fn.param_type_hints.clone()))
                .collect::<BTreeMap<_, _>>();

            let local_inline_function_names = module
                .items
                .iter()
                .filter_map(|item| {
                    if let HirExprKind::Inline { expr } = &item.value.kind {
                        if matches!(expr.kind, HirExprKind::Function { .. }) {
                            return Some(item.name.clone());
                        }
                    }
                    None
                })
                .collect::<BTreeSet<_>>();

            let local_function_exprs = module
                .items
                .iter()
                .map(|item| (item.name.clone(), item.value.clone()))
                .collect::<BTreeMap<_, _>>();

            let mut function_return_types = qualified_function_return_types.clone();
            function_return_types.extend(local_function_return_types.clone());
            function_return_types.extend(local_extern_return_types.clone());

            let mut function_return_hints = qualified_function_return_hints.clone();
            function_return_hints.extend(local_function_return_hints.clone());
            function_return_hints.extend(local_extern_return_hints.clone());

            let mut function_param_names = qualified_function_param_names.clone();
            function_param_names.extend(local_function_param_names.clone());

            let mut function_param_defaults = qualified_function_param_defaults.clone();
            function_param_defaults.extend(local_function_param_defaults.clone());

            let mut function_param_type_hints = qualified_function_param_type_hints.clone();
            function_param_type_hints.extend(local_function_param_type_hints.clone());
            function_param_type_hints.extend(local_extern_param_type_hints.clone());

            let mut function_exprs = qualified_function_exprs.clone();
            function_exprs.extend(local_function_exprs.clone());

            let mut inline_function_names = qualified_inline_function_names.clone();
            inline_function_names.extend(local_inline_function_names.clone());

            let named_type_literals = module
                .items
                .iter()
                .filter_map(|item| {
                    if let HirExprKind::TypeLiteral(type_name) = &item.value.kind {
                        Some((item.name.clone(), type_name.clone()))
                    } else {
                        None
                    }
                })
                .collect::<BTreeMap<_, _>>();

            let globals = module
                .items
                .iter()
                .filter(|item| item.mutable)
                .filter_map(|item| {
                    let type_hint = item.type_hint.clone().or_else(|| item.inferred_type.clone());
                    let ty = type_hint.as_deref().map(parse_type_hint).unwrap_or(MirValueType::Unknown);
                    let init = match &item.value.kind {
                        HirExprKind::Literal(HirLiteral::Integer(v)) => {
                            parse_i64_literal(v).map(MirGlobalInit::Integer).unwrap_or(MirGlobalInit::Zero)
                        }
                        HirExprKind::Literal(HirLiteral::Bool(b)) => MirGlobalInit::Bool(*b),
                        _ => MirGlobalInit::Zero,
                    };
                    Some(MirGlobal {
                        name: item.name.clone(),
                        mutable: true,
                        type_hint,
                        ty,
                        init,
                    })
                })
                .collect::<Vec<_>>();

            let global_names: BTreeSet<String> =
                globals.iter().map(|g| g.name.clone()).collect();

            let shared = FunctionLowererShared {
                function_return_types: function_return_types.clone(),
                function_return_hints: function_return_hints.clone(),
                named_type_literals: named_type_literals.clone(),
                enum_repr_bits_by_name: global_enum_repr_bits_by_name.clone(),
                enum_variant_tags_by_name: global_enum_variant_tags_by_name.clone(),
                function_param_names: function_param_names.clone(),
                function_param_defaults: function_param_defaults.clone(),
                function_param_type_hints: function_param_type_hints.clone(),
                function_exprs: function_exprs.clone(),
                inline_function_names: inline_function_names.clone(),
                module_ids_by_key: module_ids_by_key.clone(),
                module_exports_by_id: module_exports_by_id.clone(),
                global_names: global_names.clone(),
            };

            let functions = module
                .items
                .iter()
                .filter(|item| !global_names.contains(&item.name))
                .map(|item| {
                    let mut lowerer = FunctionLowerer::new(
                        module.key.clone(),
                        module_source_path.clone(),
                        item.name.clone(),
                        shared.clone(),
                    );
                    lowerer.function.def_id = item.def_id;
                    lowerer.function.return_type =
                        item.type_hint.clone().or(item.inferred_type.clone());

                    match &item.value.kind {
                        HirExprKind::Function {
                            params,
                            param_types,
                            param_defaults: _,
                            has_explicit_return_type,
                            body,
                        } => {
                            let allows_or_return_tail_implicit_success =
                                has_or_return_tail(body) && !has_explicit_return_type;
                            let allows_non_i32_main_implicit_success =
                                allows_non_i32_main_implicit_success(
                                    &module.key,
                                    &item.name,
                                    item.type_hint.as_deref().or(item.inferred_type.as_deref()),
                                );

                            lowerer.current_param_type_hints = param_types.clone();
                            lowerer.current_self_type_hint = item.enclosing_struct.clone();
                            lowerer.function.param_type_hints = param_types.clone();
                            lowerer.function.param_types = param_types
                                .iter()
                                .map(|ty| {
                                    ty.as_deref()
                                        .map(parse_type_hint)
                                        .unwrap_or(MirValueType::Unknown)
                                })
                                .collect();
                            for (idx, param) in params.iter().enumerate() {
                                let ty = lowerer
                                    .function
                                    .param_types
                                    .get(idx)
                                    .cloned()
                                    .unwrap_or(MirValueType::Unknown);
                                let value = lowerer.push_eval(
                                    lowerer.function.entry,
                                    MirValue::Param { index: idx },
                                    ty,
                                );
                                lowerer.locals.insert(param.clone(), value);
                            }
                            let (end_block, value) =
                                lowerer.lower_expr(lowerer.function.entry, body);
                            if !lowerer.is_terminated(end_block) {
                                let end_block = lowerer.emit_deferred(end_block, None);
                                if allows_or_return_tail_implicit_success
                                    || allows_non_i32_main_implicit_success
                                {
                                    lowerer.set_terminator(end_block, MirTerminator::Return(None));
                                } else {
                                    lowerer.set_terminator(end_block, MirTerminator::Return(value));
                                }
                            }
                        }
                        HirExprKind::Inline { expr } => {
                            if let HirExprKind::Function {
                                params,
                                param_types,
                                param_defaults: _,
                                has_explicit_return_type,
                                body,
                            } = &expr.kind
                            {
                                let allows_or_return_tail_implicit_success =
                                    has_or_return_tail(body) && !has_explicit_return_type;
                                let allows_non_i32_main_implicit_success =
                                    allows_non_i32_main_implicit_success(
                                        &module.key,
                                        &item.name,
                                        item.type_hint.as_deref().or(item.inferred_type.as_deref()),
                                    );

                                lowerer.current_param_type_hints = param_types.clone();
                                lowerer.current_self_type_hint = item.enclosing_struct.clone();
                                lowerer.function.param_type_hints = param_types.clone();
                                lowerer.function.param_types = param_types
                                    .iter()
                                    .map(|ty| {
                                        ty.as_deref()
                                            .map(parse_type_hint)
                                            .unwrap_or(MirValueType::Unknown)
                                    })
                                    .collect();
                                for (idx, param) in params.iter().enumerate() {
                                    let ty = lowerer
                                        .function
                                        .param_types
                                        .get(idx)
                                        .cloned()
                                        .unwrap_or(MirValueType::Unknown);
                                    let value = lowerer.push_eval(
                                        lowerer.function.entry,
                                        MirValue::Param { index: idx },
                                        ty,
                                    );
                                    lowerer.locals.insert(param.clone(), value);
                                }
                                let (end_block, value) =
                                    lowerer.lower_expr(lowerer.function.entry, body);
                                if !lowerer.is_terminated(end_block) {
                                    let end_block = lowerer.emit_deferred(end_block, None);
                                    if allows_or_return_tail_implicit_success
                                        || allows_non_i32_main_implicit_success
                                    {
                                        lowerer
                                            .set_terminator(end_block, MirTerminator::Return(None));
                                    } else {
                                        lowerer.set_terminator(
                                            end_block,
                                            MirTerminator::Return(value),
                                        );
                                    }
                                }
                            } else {
                                let (end_block, value) =
                                    lowerer.lower_expr(lowerer.function.entry, &item.value);
                                if !lowerer.is_terminated(end_block) {
                                    let end_block = lowerer.emit_deferred(end_block, None);
                                    lowerer.set_terminator(end_block, MirTerminator::Return(value));
                                }
                            }
                        }
                        _ => {
                            let (end_block, value) =
                                lowerer.lower_expr(lowerer.function.entry, &item.value);
                            if !lowerer.is_terminated(end_block) {
                                let end_block = lowerer.emit_deferred(end_block, None);
                                lowerer.set_terminator(end_block, MirTerminator::Return(value));
                            }
                        }
                    }

                    module_diagnostics.append(&mut lowerer.diagnostics);
                    let mut result = std::mem::take(&mut lowerer.hoisted_lambdas);
                    result.push(lowerer.function);
                    result
                })
                .flatten()
                .collect::<Vec<_>>();

            let extern_functions = module
                .extern_functions
                .iter()
                .map(|extern_fn| crate::compiler::mir::MirExternFunction {
                    name: extern_fn.name.clone(),
                    symbol_name: extern_fn
                        .link_name
                        .clone()
                        .unwrap_or_else(|| extern_fn.name.clone()),
                    return_type: extern_fn.return_type.clone(),
                    param_type_hints: extern_fn.param_type_hints.clone(),
                    param_types: extern_fn
                        .param_type_hints
                        .iter()
                        .map(|ty| {
                            ty.as_deref()
                                .map(parse_type_hint)
                                .unwrap_or(MirValueType::Unknown)
                        })
                        .collect(),
                })
                .collect::<Vec<_>>();

            diagnostics.extend(module_diagnostics);

            MirModule {
                module_id: module.module_id,
                key: module.key.clone(),
                globals,
                functions,
                extern_functions,
            }
        })
        .collect::<Vec<_>>();

    (MirProgram { modules }, diagnostics)
}

fn qualified_function_name(module_id: ModuleId, function_name: &str) -> String {
    format!("#{}::{function_name}", module_id.0)
}

fn module_key_source_path(key: &ModuleKey) -> std::path::PathBuf {
    let mut path = if key.directory == std::path::Path::new(".") {
        std::path::PathBuf::new()
    } else {
        key.directory.clone()
    };
    path.push(format!("{}.dyn", key.module_name));
    path
}

fn has_or_return_tail(expr: &HirExpr) -> bool {
    match &expr.kind {
        HirExprKind::Block { body } => body.last().is_some_and(has_or_return_tail),
        HirExprKind::OrElse { fallback, .. } => {
            matches!(fallback.kind, HirExprKind::Return { .. })
        }
        _ => false,
    }
}

fn return_hint_ok_type_text(return_hint: &str) -> &str {
    let trimmed = return_hint.trim();
    if let Some((ok, _)) = trimmed.split_once('!') {
        ok.trim()
    } else if let Some(ok) = trimmed.strip_suffix('!') {
        ok.trim()
    } else {
        trimmed
    }
}

fn return_hint_is_void_like(return_hint: &str) -> bool {
    let candidate = if let Some((_, ret)) = return_hint.rsplit_once("->") {
        ret.trim()
    } else {
        return_hint.trim()
    };
    let ok = return_hint_ok_type_text(candidate);
    ok == "void" || ok.is_empty()
}

fn return_hint_is_errorable_aggregate(return_hint: &str) -> bool {
    let candidate = if let Some((_, ret)) = return_hint.rsplit_once("->") {
        ret.trim()
    } else {
        return_hint.trim()
    };
    if !candidate.contains('!') {
        return false;
    }
    let ok = return_hint_ok_type_text(candidate);
    matches!(parse_type_hint(ok), MirValueType::Unknown)
}

fn allows_non_i32_main_implicit_success(
    module_key: &ModuleKey,
    function_name: &str,
    return_hint: Option<&str>,
) -> bool {
    if module_key.module_name != "main" || function_name != "main" {
        return false;
    }
    match return_hint {
        Some(hint) => return_hint_is_void_like(hint),
        None => false,
    }
}

fn collect_enum_type_metadata(
    named_type_literals: &BTreeMap<String, String>,
) -> (
    BTreeMap<String, u16>,
    BTreeMap<String, BTreeMap<String, i64>>,
) {
    let mut enum_repr_bits_by_name = BTreeMap::new();
    let mut enum_variant_tags_by_name = BTreeMap::new();

    for (type_name, literal) in named_type_literals {
        let Some(repr_bits) = enum_type_repr_bits(literal) else {
            continue;
        };
        let Some(variants) = enum_type_variants(literal) else {
            continue;
        };

        enum_repr_bits_by_name.insert(type_name.clone(), repr_bits);

        let mut tags = BTreeMap::new();
        for (idx, variant) in variants.iter().enumerate() {
            let tag = idx as i64 + 1;
            tags.insert(variant.clone(), tag);
        }

        enum_variant_tags_by_name.insert(type_name.clone(), tags);
    }

    (enum_repr_bits_by_name, enum_variant_tags_by_name)
}

struct FunctionLowerer {
    module_key: ModuleKey,
    source_file_path: std::path::PathBuf,
    function: MirFunction,
    next_value: usize,
    locals: BTreeMap<String, MirValueId>,
    address_taken_values: BTreeMap<String, MirValueId>,
    comptime_known_locals: BTreeMap<String, ComptimeValue>,
    comptime_local_function_exprs: BTreeMap<String, HirExpr>,
    value_types: BTreeMap<MirValueId, MirValueType>,
    value_defs: BTreeMap<MirValueId, MirValue>,
    struct_fields: BTreeMap<MirValueId, BTreeMap<String, MirValueId>>,
    aggregate_sequences: BTreeMap<MirValueId, Vec<MirValueId>>,
    function_return_types: BTreeMap<String, MirValueType>,
    function_return_hints: BTreeMap<String, Option<String>>,
    errorable_aggregate_values: BTreeSet<MirValueId>,
    errorable_scalar_values: BTreeSet<MirValueId>,
    named_type_literals: BTreeMap<String, String>,
    enum_repr_bits_by_name: BTreeMap<String, u16>,
    enum_variant_tags_by_name: BTreeMap<String, BTreeMap<String, i64>>,
    function_param_names: BTreeMap<String, Vec<String>>,
    function_param_defaults: BTreeMap<String, Vec<Option<HirExpr>>>,
    function_param_type_hints: BTreeMap<String, Vec<Option<String>>>,
    function_exprs: BTreeMap<String, HirExpr>,
    inline_function_names: BTreeSet<String>,
    module_ids_by_key: BTreeMap<ModuleKey, ModuleId>,
    module_exports_by_id: BTreeMap<ModuleId, Vec<String>>,
    current_param_type_hints: Vec<Option<String>>,
    /// The enclosing struct name for member functions, used to resolve `$self()` when there is
    /// no `self` parameter in scope.
    current_self_type_hint: Option<String>,
    inline_call_depth: usize,
    inline_call_stack: Vec<String>,
    current_inline_module: Option<String>,
    loop_stack: Vec<LoopContext>,
    or_break_stack: Vec<OrBreakContext>,
    deferred: Vec<DeferredExpr>,
    diagnostics: Vec<Diagnostic>,
    /// Lambdas hoisted out of inline positions, to be emitted as top-level functions.
    hoisted_lambdas: Vec<MirFunction>,
    /// Names of module-level mutable globals in this module; used to distinguish global
    /// loads/stores from local variable accesses.
    global_names: BTreeSet<String>,
}

#[derive(Debug, Clone)]
struct LoopContext {
    continue_target: MirBlockId,
    break_target: MirBlockId,
    break_values: Vec<(MirBlockId, MirValueId)>,
}

#[derive(Debug, Clone)]
struct OrBreakContext {
    target: MirBlockId,
    values: Vec<(MirBlockId, MirValueId)>,
}

#[derive(Debug, Clone)]
struct DeferredExpr {
    error_binding: Option<String>,
    body: HirExpr,
}

#[derive(Clone)]
enum ComptimeValue {
    Literal(HirLiteral),
    Type(String),
    Function(String),
}

#[derive(Clone)]
struct FunctionLowererShared {
    function_return_types: BTreeMap<String, MirValueType>,
    function_return_hints: BTreeMap<String, Option<String>>,
    named_type_literals: BTreeMap<String, String>,
    enum_repr_bits_by_name: BTreeMap<String, u16>,
    enum_variant_tags_by_name: BTreeMap<String, BTreeMap<String, i64>>,
    function_param_names: BTreeMap<String, Vec<String>>,
    function_param_defaults: BTreeMap<String, Vec<Option<HirExpr>>>,
    function_param_type_hints: BTreeMap<String, Vec<Option<String>>>,
    function_exprs: BTreeMap<String, HirExpr>,
    inline_function_names: BTreeSet<String>,
    module_ids_by_key: BTreeMap<ModuleKey, ModuleId>,
    module_exports_by_id: BTreeMap<ModuleId, Vec<String>>,
    global_names: BTreeSet<String>,
}

fn extract_inline_function_body(expr: &HirExpr) -> Option<(&Vec<String>, &HirExpr)> {
    match &expr.kind {
        HirExprKind::Function { params, body, .. } => Some((params, body)),
        HirExprKind::Inline { expr } => extract_inline_function_body(expr),
        _ => None,
    }
}

fn normalize_inline_hir_body(expr: &HirExpr) -> HirExpr {
    let mut normalized = expr.clone();
    if let HirExprKind::Block { body } = &mut normalized.kind {
        if let Some(last) = body.last_mut() {
            if let HirExprKind::Return { value: Some(value) } = &last.kind {
                *last = (**value).clone();
            }
        }
    }
    normalized
}

fn inline_hir_body_supported(expr: &HirExpr) -> bool {
    !contains_disallowed_inline_flow_hir(expr)
}

fn contains_disallowed_inline_flow_hir(expr: &HirExpr) -> bool {
    match &expr.kind {
        HirExprKind::Break { .. }
        | HirExprKind::Continue
        | HirExprKind::Return { .. }
        | HirExprKind::Defer { .. } => true,
        HirExprKind::Unary { expr, .. }
        | HirExprKind::DerefAccess { base: expr }
        | HirExprKind::OptionalUnwrap { value: expr }
        | HirExprKind::ErrorUnwrap { value: expr }
        | HirExprKind::Comptime { expr }
        | HirExprKind::Inline { expr } => contains_disallowed_inline_flow_hir(expr),
        HirExprKind::Binary { left, right, .. }
        | HirExprKind::Assign {
            target: left,
            value: right,
            ..
        }
        | HirExprKind::Index {
            base: left,
            index: right,
        } => {
            contains_disallowed_inline_flow_hir(left) || contains_disallowed_inline_flow_hir(right)
        }
        HirExprKind::Call { callee, args } => {
            contains_disallowed_inline_flow_hir(callee)
                || args
                    .iter()
                    .any(|arg| contains_disallowed_inline_flow_hir(&arg.value))
        }
        HirExprKind::FieldAccess { base, .. } => contains_disallowed_inline_flow_hir(base),
        HirExprKind::Slice {
            base, start, end, ..
        } => {
            contains_disallowed_inline_flow_hir(base)
                || start
                    .as_ref()
                    .map(|expr| contains_disallowed_inline_flow_hir(expr))
                    .unwrap_or(false)
                || end
                    .as_ref()
                    .map(|expr| contains_disallowed_inline_flow_hir(expr))
                    .unwrap_or(false)
        }
        HirExprKind::StructLiteral { fields, .. } => fields
            .iter()
            .any(|(_, value)| contains_disallowed_inline_flow_hir(value)),
        HirExprKind::EnumVariant { payload, .. } => {
            payload.iter().any(contains_disallowed_inline_flow_hir)
        }
        HirExprKind::Block { body } => body.iter().any(contains_disallowed_inline_flow_hir),
        HirExprKind::Let { value, .. } => contains_disallowed_inline_flow_hir(value),
        HirExprKind::If {
            condition,
            then_branch,
            else_branch,
            ..
        } => {
            contains_disallowed_inline_flow_hir(condition)
                || contains_disallowed_inline_flow_hir(then_branch)
                || else_branch
                    .as_ref()
                    .map(|expr| contains_disallowed_inline_flow_hir(expr))
                    .unwrap_or(false)
        }
        HirExprKind::Match { value, arms } => {
            contains_disallowed_inline_flow_hir(value)
                || arms.iter().any(|arm| {
                    arm.guard
                        .as_ref()
                        .map(contains_disallowed_inline_flow_hir)
                        .unwrap_or(false)
                        || contains_disallowed_inline_flow_hir(&arm.value)
                })
        }
        HirExprKind::For(for_expr) => match for_expr {
            HirForExpr::Infinite { body } => contains_disallowed_inline_flow_hir(body),
            HirForExpr::WhileLike { condition, body } => {
                contains_disallowed_inline_flow_hir(condition)
                    || contains_disallowed_inline_flow_hir(body)
            }
            HirForExpr::Iterate { iterable, body, .. } => {
                contains_disallowed_inline_flow_hir(iterable)
                    || contains_disallowed_inline_flow_hir(body)
            }
            HirForExpr::Range {
                start, end, body, ..
            } => {
                contains_disallowed_inline_flow_hir(start)
                    || contains_disallowed_inline_flow_hir(end)
                    || contains_disallowed_inline_flow_hir(body)
            }
        },
        HirExprKind::OrElse {
            value, fallback, ..
        } => {
            contains_disallowed_inline_flow_hir(value)
                || contains_disallowed_inline_flow_hir(fallback)
        }
        HirExprKind::Function { body, .. } => contains_disallowed_inline_flow_hir(body),
        HirExprKind::Use { .. }
        | HirExprKind::TypeLiteral(_)
        | HirExprKind::Unknown
        | HirExprKind::Literal(_)
        | HirExprKind::Ident(_) => false,
    }
}

fn assign_to_binary_op(op: AssignOp) -> Option<BinaryOp> {
    match op {
        AssignOp::Assign => None,
        AssignOp::AddAssign => Some(BinaryOp::Add),
        AssignOp::SubAssign => Some(BinaryOp::Sub),
        AssignOp::MulAssign => Some(BinaryOp::Mul),
        AssignOp::DivAssign => Some(BinaryOp::Div),
        AssignOp::ModAssign => Some(BinaryOp::Mod),
        AssignOp::BitAndAssign => Some(BinaryOp::BitAnd),
        AssignOp::BitOrAssign => Some(BinaryOp::BitOr),
        AssignOp::BitXorAssign => Some(BinaryOp::BitXor),
        AssignOp::ShlAssign => Some(BinaryOp::Shl),
        AssignOp::ShrAssign => Some(BinaryOp::Shr),
    }
}

fn assigned_local_names(expr: &HirExpr) -> Vec<String> {
    let mut names = BTreeMap::<String, ()>::new();
    collect_assigned_local_names(expr, &mut names);
    names.into_keys().collect()
}

fn collect_assigned_local_names(expr: &HirExpr, names: &mut BTreeMap<String, ()>) {
    match &expr.kind {
        HirExprKind::Assign { target, value, .. } => {
            if let HirExprKind::Ident(name) = &target.kind {
                names.insert(name.clone(), ());
            }
            collect_assigned_local_names(target, names);
            collect_assigned_local_names(value, names);
        }
        HirExprKind::Unary { expr, .. }
        | HirExprKind::FieldAccess { base: expr, .. }
        | HirExprKind::DerefAccess { base: expr }
        | HirExprKind::OptionalUnwrap { value: expr }
        | HirExprKind::ErrorUnwrap { value: expr }
        | HirExprKind::Break { value: Some(expr) }
        | HirExprKind::Return { value: Some(expr) }
        | HirExprKind::Defer { body: expr, .. }
        | HirExprKind::Comptime { expr }
        | HirExprKind::Inline { expr }
        | HirExprKind::Let { value: expr, .. } => collect_assigned_local_names(expr, names),
        HirExprKind::Binary { left, right, .. }
        | HirExprKind::OrElse {
            value: left,
            fallback: right,
            ..
        } => {
            collect_assigned_local_names(left, names);
            collect_assigned_local_names(right, names);
        }
        HirExprKind::Call { callee, args } => {
            collect_assigned_local_names(callee, names);
            for arg in args {
                collect_assigned_local_names(&arg.value, names);
            }
        }
        HirExprKind::Index { base, index } => {
            collect_assigned_local_names(base, names);
            collect_assigned_local_names(index, names);
        }
        HirExprKind::Slice {
            base, start, end, ..
        } => {
            collect_assigned_local_names(base, names);
            if let Some(start) = start {
                collect_assigned_local_names(start, names);
            }
            if let Some(end) = end {
                collect_assigned_local_names(end, names);
            }
        }
        HirExprKind::StructLiteral { fields, .. } => {
            for (_, field) in fields {
                collect_assigned_local_names(field, names);
            }
        }
        HirExprKind::EnumVariant { payload, .. } => {
            for value in payload {
                collect_assigned_local_names(value, names);
            }
        }
        HirExprKind::Match { value, arms } => {
            collect_assigned_local_names(value, names);
            for arm in arms {
                if let Some(guard) = &arm.guard {
                    collect_assigned_local_names(guard, names);
                }
                collect_assigned_local_names(&arm.value, names);
            }
        }
        HirExprKind::Block { body } => {
            for value in body {
                collect_assigned_local_names(value, names);
            }
        }
        HirExprKind::If {
            condition,
            then_branch,
            else_branch,
            ..
        } => {
            collect_assigned_local_names(condition, names);
            collect_assigned_local_names(then_branch, names);
            if let Some(else_branch) = else_branch {
                collect_assigned_local_names(else_branch, names);
            }
        }
        HirExprKind::Function {
            param_defaults,
            body,
            ..
        } => {
            for default in param_defaults.iter().flatten() {
                collect_assigned_local_names(default, names);
            }
            collect_assigned_local_names(body, names);
        }
        HirExprKind::For(HirForExpr::Infinite { body }) => {
            collect_assigned_local_names(body, names);
        }
        HirExprKind::For(HirForExpr::WhileLike { condition, body }) => {
            collect_assigned_local_names(condition, names);
            collect_assigned_local_names(body, names);
        }
        HirExprKind::For(HirForExpr::Range {
            start, end, body, ..
        }) => {
            collect_assigned_local_names(start, names);
            collect_assigned_local_names(end, names);
            collect_assigned_local_names(body, names);
        }
        HirExprKind::For(HirForExpr::Iterate { iterable, body, .. }) => {
            collect_assigned_local_names(iterable, names);
            collect_assigned_local_names(body, names);
        }
        HirExprKind::Break { value: None }
        | HirExprKind::Continue
        | HirExprKind::Return { value: None }
        | HirExprKind::Use { .. }
        | HirExprKind::TypeLiteral(_)
        | HirExprKind::Ident(_)
        | HirExprKind::Literal(_)
        | HirExprKind::Unknown => {}
    }
}

#[cfg(test)]
mod tests;
