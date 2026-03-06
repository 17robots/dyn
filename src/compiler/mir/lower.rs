use std::collections::BTreeMap;

use crate::compiler::ast::{AssignOp, BinaryOp, UnaryOp};
use crate::compiler::hir::{
    HirCallArg, HirExpr, HirExprKind, HirForExpr, HirLiteral, HirPattern, HirProgram,
};
use crate::compiler::mir::{
    MirBasicBlock, MirBlockId, MirFunction, MirInstr, MirModule, MirProgram, MirTerminator,
    MirValue, MirValueId, MirValueType,
};
use crate::compiler::module_resolver::{ModuleId, ModuleKey};

pub fn lower_hir_to_mir(hir: &HirProgram) -> MirProgram {
    let module_ids_by_key = hir
        .modules
        .iter()
        .map(|module| (module.key.clone(), module.module_id))
        .collect::<BTreeMap<_, _>>();

    let module_exports_by_id = hir
        .modules
        .iter()
        .map(|module| {
            (
                module.module_id,
                module
                    .items
                    .iter()
                    .map(|item| item.name.clone())
                    .collect::<Vec<_>>(),
            )
        })
        .collect::<BTreeMap<_, _>>();

    let mut qualified_function_return_types = BTreeMap::new();
    let mut qualified_function_param_names = BTreeMap::new();
    let mut qualified_function_param_defaults = BTreeMap::new();
    let mut qualified_function_param_type_hints = BTreeMap::new();
    let mut qualified_function_exprs = BTreeMap::new();

    for module in &hir.modules {
        for item in &module.items {
            let qualified_name = qualified_function_name(module.module_id, &item.name);
            qualified_function_return_types.insert(
                qualified_name.clone(),
                item.inferred_type
                    .as_deref()
                    .or(item.type_hint.as_deref())
                    .map(parse_type_hint)
                    .unwrap_or(MirValueType::Unknown),
            );
            qualified_function_exprs.insert(qualified_name.clone(), item.value.clone());

            if let HirExprKind::Function {
                params,
                param_types,
                param_defaults,
                ..
            } = &item.value.kind
            {
                qualified_function_param_names.insert(qualified_name.clone(), params.clone());
                qualified_function_param_defaults
                    .insert(qualified_name.clone(), param_defaults.clone());
                qualified_function_param_type_hints.insert(qualified_name, param_types.clone());
            }
        }
    }

    let modules = hir
        .modules
        .iter()
        .map(|module| {
            let local_function_return_types = module
                .items
                .iter()
                .map(|item| {
                    (
                        item.name.clone(),
                        item.inferred_type
                            .as_deref()
                            .or(item.type_hint.as_deref())
                            .map(parse_type_hint)
                            .unwrap_or(MirValueType::Unknown),
                    )
                })
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
                .filter_map(|item| {
                    if let HirExprKind::Function { param_types, .. } = &item.value.kind {
                        Some((item.name.clone(), param_types.clone()))
                    } else {
                        None
                    }
                })
                .collect::<BTreeMap<_, _>>();

            let local_function_exprs = module
                .items
                .iter()
                .map(|item| (item.name.clone(), item.value.clone()))
                .collect::<BTreeMap<_, _>>();

            let mut function_return_types = qualified_function_return_types.clone();
            function_return_types.extend(local_function_return_types.clone());

            let mut function_param_names = qualified_function_param_names.clone();
            function_param_names.extend(local_function_param_names.clone());

            let mut function_param_defaults = qualified_function_param_defaults.clone();
            function_param_defaults.extend(local_function_param_defaults.clone());

            let mut function_param_type_hints = qualified_function_param_type_hints.clone();
            function_param_type_hints.extend(local_function_param_type_hints.clone());

            let mut function_exprs = qualified_function_exprs.clone();
            function_exprs.extend(local_function_exprs.clone());

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

            let functions = module
                .items
                .iter()
                .map(|item| {
                    let mut lowerer = FunctionLowerer::new(
                        module.key.clone(),
                        item.name.clone(),
                        function_return_types.clone(),
                        named_type_literals.clone(),
                        function_param_names.clone(),
                        function_param_defaults.clone(),
                        function_param_type_hints.clone(),
                        function_exprs.clone(),
                        module_ids_by_key.clone(),
                        module_exports_by_id.clone(),
                    );
                    lowerer.function.def_id = item.def_id;
                    lowerer.function.return_type =
                        item.type_hint.clone().or(item.inferred_type.clone());

                    match &item.value.kind {
                        HirExprKind::Function {
                            params,
                            param_types,
                            param_defaults: _,
                            body,
                        } => {
                            lowerer.current_param_type_hints = param_types.clone();
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
                                lowerer.set_terminator(end_block, MirTerminator::Return(value));
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

                    lowerer.function
                })
                .collect::<Vec<_>>();

            MirModule {
                module_id: module.module_id,
                key: module.key.clone(),
                functions,
            }
        })
        .collect::<Vec<_>>();

    MirProgram { modules }
}

fn qualified_function_name(module_id: ModuleId, function_name: &str) -> String {
    format!("#{}::{function_name}", module_id.0)
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
    let mut directory = if current.directory == std::path::PathBuf::from(".") {
        std::path::PathBuf::new()
    } else {
        current.directory.clone()
    };
    for segment in parts {
        directory.push(segment);
    }
    if directory.as_os_str().is_empty() {
        directory = std::path::PathBuf::from(".");
    }

    ModuleKey {
        directory,
        module_name,
    }
}

struct FunctionLowerer {
    module_key: ModuleKey,
    function: MirFunction,
    next_value: usize,
    locals: BTreeMap<String, MirValueId>,
    value_types: BTreeMap<MirValueId, MirValueType>,
    value_defs: BTreeMap<MirValueId, MirValue>,
    struct_fields: BTreeMap<MirValueId, BTreeMap<String, MirValueId>>,
    aggregate_sequences: BTreeMap<MirValueId, Vec<MirValueId>>,
    function_return_types: BTreeMap<String, MirValueType>,
    named_type_literals: BTreeMap<String, String>,
    function_param_names: BTreeMap<String, Vec<String>>,
    function_param_defaults: BTreeMap<String, Vec<Option<HirExpr>>>,
    function_param_type_hints: BTreeMap<String, Vec<Option<String>>>,
    function_exprs: BTreeMap<String, HirExpr>,
    module_ids_by_key: BTreeMap<ModuleKey, ModuleId>,
    module_exports_by_id: BTreeMap<ModuleId, Vec<String>>,
    current_param_type_hints: Vec<Option<String>>,
    loop_stack: Vec<LoopContext>,
    or_break_stack: Vec<OrBreakContext>,
    deferred: Vec<DeferredExpr>,
    variant_tag_ids: BTreeMap<String, i64>,
    next_variant_tag: i64,
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

impl FunctionLowerer {
    fn new(
        module_key: ModuleKey,
        name: String,
        function_return_types: BTreeMap<String, MirValueType>,
        named_type_literals: BTreeMap<String, String>,
        function_param_names: BTreeMap<String, Vec<String>>,
        function_param_defaults: BTreeMap<String, Vec<Option<HirExpr>>>,
        function_param_type_hints: BTreeMap<String, Vec<Option<String>>>,
        function_exprs: BTreeMap<String, HirExpr>,
        module_ids_by_key: BTreeMap<ModuleKey, ModuleId>,
        module_exports_by_id: BTreeMap<ModuleId, Vec<String>>,
    ) -> Self {
        Self {
            module_key,
            function: MirFunction {
                name,
                def_id: None,
                return_type: None,
                param_types: Vec::new(),
                blocks: vec![MirBasicBlock {
                    id: MirBlockId(0),
                    instructions: Vec::new(),
                    terminator: None,
                }],
                entry: MirBlockId(0),
            },
            next_value: 0,
            locals: BTreeMap::new(),
            value_types: BTreeMap::new(),
            value_defs: BTreeMap::new(),
            struct_fields: BTreeMap::new(),
            aggregate_sequences: BTreeMap::new(),
            function_return_types,
            named_type_literals,
            function_param_names,
            function_param_defaults,
            function_param_type_hints,
            function_exprs,
            module_ids_by_key,
            module_exports_by_id,
            current_param_type_hints: Vec::new(),
            loop_stack: Vec::new(),
            or_break_stack: Vec::new(),
            deferred: Vec::new(),
            variant_tag_ids: BTreeMap::new(),
            next_variant_tag: 0,
        }
    }

    fn lower_expr(
        &mut self,
        block: MirBlockId,
        expr: &HirExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        match &expr.kind {
            HirExprKind::Literal(literal) => {
                let ty = literal_type(literal);
                (
                    block,
                    Some(self.push_eval(block, MirValue::Literal(literal.clone()), ty)),
                )
            }
            HirExprKind::Ident(name) => {
                if let Some(value) = self.locals.get(name).copied() {
                    (block, Some(value))
                } else if let Some(type_name) =
                    type_literal_name_for_ident(name, &self.named_type_literals)
                {
                    (
                        block,
                        Some(self.push_eval(
                            block,
                            MirValue::TypeLiteral(type_name),
                            MirValueType::Type,
                        )),
                    )
                } else {
                    let ty = if self.function_return_types.contains_key(name) {
                        MirValueType::Function
                    } else {
                        MirValueType::Unknown
                    };
                    (
                        block,
                        Some(self.push_eval(block, MirValue::Ident(name.clone()), ty)),
                    )
                }
            }
            HirExprKind::Unary { expr, op } => {
                let (end, operand) = self.lower_expr(block, expr);
                let Some(operand) = operand else {
                    return (end, None);
                };
                let ty = self
                    .value_types
                    .get(&operand)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown);
                (
                    end,
                    Some(self.push_eval(end, MirValue::Unary { op: *op, operand }, ty)),
                )
            }
            HirExprKind::Binary { left, right, op } => {
                let (left_end, left_value) = self.lower_expr(block, left);
                let (right_end, right_value) = self.lower_expr(left_end, right);
                let (Some(left_value), Some(right_value)) = (left_value, right_value) else {
                    return (right_end, None);
                };
                let left_ty = self
                    .value_types
                    .get(&left_value)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown);
                let right_ty = self
                    .value_types
                    .get(&right_value)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown);
                let result_ty = match op {
                    crate::compiler::ast::BinaryOp::Eq
                    | crate::compiler::ast::BinaryOp::Ne
                    | crate::compiler::ast::BinaryOp::Lt
                    | crate::compiler::ast::BinaryOp::Le
                    | crate::compiler::ast::BinaryOp::Gt
                    | crate::compiler::ast::BinaryOp::Ge
                    | crate::compiler::ast::BinaryOp::LogicalAnd
                    | crate::compiler::ast::BinaryOp::LogicalOr => MirValueType::Bool,
                    _ => merge_types(&left_ty, &right_ty),
                };
                (
                    right_end,
                    Some(self.push_eval(
                        right_end,
                        MirValue::Binary {
                            op: *op,
                            left: left_value,
                            right: right_value,
                        },
                        result_ty,
                    )),
                )
            }
            HirExprKind::Assign { target, value, op } => {
                let (target_end, target_value) = self.lower_expr(block, target);
                let (value_end, value_value) = self.lower_expr(target_end, value);
                let (Some(target_value), Some(value_value)) = (target_value, value_value) else {
                    return (value_end, None);
                };
                let target_ty = self
                    .value_types
                    .get(&target_value)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown);
                let value_ty = self
                    .value_types
                    .get(&value_value)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown);
                if let HirExprKind::Ident(name) = &target.kind {
                    let assigned_value = if let Some(binary_op) = assign_to_binary_op(*op) {
                        let result_ty = merge_types(&target_ty, &value_ty);
                        self.push_eval(
                            value_end,
                            MirValue::Binary {
                                op: binary_op,
                                left: target_value,
                                right: value_value,
                            },
                            result_ty,
                        )
                    } else {
                        value_value
                    };
                    let assigned_ty = self
                        .value_types
                        .get(&assigned_value)
                        .cloned()
                        .unwrap_or(value_ty.clone());
                    self.locals.insert(name.clone(), assigned_value);
                    return (
                        value_end,
                        Some(self.push_eval(
                            value_end,
                            MirValue::LocalSet {
                                name: name.clone(),
                                value: assigned_value,
                            },
                            assigned_ty,
                        )),
                    );
                }
                (
                    value_end,
                    Some(self.push_eval(
                        value_end,
                        MirValue::Assign {
                            op: *op,
                            target: target_value,
                            value: value_value,
                        },
                        value_ty,
                    )),
                )
            }
            HirExprKind::Let { name, value, .. } => {
                let (end, init_value) = self.lower_expr(block, value);
                let Some(init_value) = init_value else {
                    return (end, None);
                };
                self.locals.insert(name.clone(), init_value);
                let value_ty = self
                    .value_types
                    .get(&init_value)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown);
                (
                    end,
                    Some(self.push_eval(
                        end,
                        MirValue::LocalSet {
                            name: name.clone(),
                            value: init_value,
                        },
                        value_ty,
                    )),
                )
            }
            HirExprKind::Call { callee, args } => {
                if let HirExprKind::Ident(name) = &callee.kind {
                    if self.should_force_comptime_call(name) {
                        if let Some(constant) = self.try_eval_comptime_expr(expr, 0) {
                            let value = self.emit_comptime_value(block, constant);
                            return (block, Some(value));
                        }
                    }
                    if let Some((end, value)) = self.try_lower_builtin_call(block, name, args) {
                        return (end, value);
                    }
                }
                let (mut end, callee_value) = self.lower_expr(block, callee);
                let Some(callee_value) = callee_value else {
                    return (end, None);
                };
                let mut lowered_args = Vec::with_capacity(args.len());
                let mut lowered_named = Vec::with_capacity(args.len());
                for arg in args {
                    let (arg_end, arg_value) = self.lower_expr(end, &arg.value);
                    end = arg_end;
                    let Some(arg_value) = arg_value else {
                        return (end, None);
                    };
                    lowered_args.push(arg_value);
                    lowered_named.push((arg.name.clone(), arg_value));
                }
                let callee_name =
                    if let Some(name) = self.resolve_callee_function_name(callee_value, 0) {
                        Some(name)
                    } else if let HirExprKind::Ident(name) = &callee.kind {
                        Some(name.clone())
                    } else {
                        None
                    };

                if let Some(name) = callee_name {
                    if let Some(param_names) = self.function_param_names.get(&name) {
                        let mut ordered = vec![None; param_names.len()];
                        for (arg_name, value) in &lowered_named {
                            if let Some(arg_name) = arg_name {
                                if let Some(index) =
                                    param_names.iter().position(|param| param == arg_name)
                                {
                                    ordered[index] = Some(*value);
                                }
                            }
                        }
                        let mut positional_iter =
                            lowered_named.iter().filter_map(|(arg_name, value)| {
                                if arg_name.is_none() {
                                    Some(*value)
                                } else {
                                    None
                                }
                            });
                        for slot in &mut ordered {
                            if slot.is_none() {
                                *slot = positional_iter.next();
                            }
                        }

                        if let Some(defaults) = self.function_param_defaults.get(&name).cloned() {
                            for (idx, slot) in ordered.iter_mut().enumerate() {
                                if slot.is_none() {
                                    if let Some(Some(default_expr)) = defaults.get(idx) {
                                        let (default_end, default_value) =
                                            self.lower_expr(end, default_expr);
                                        end = default_end;
                                        if let Some(default_value) = default_value {
                                            *slot = Some(default_value);
                                        }
                                    }
                                }
                            }
                        }

                        if ordered.iter().all(|slot| slot.is_some()) {
                            lowered_args = ordered.into_iter().flatten().collect();
                        }
                    }
                }
                let result_ty = self.infer_call_result_type(callee_value, 0);
                (
                    end,
                    Some(self.push_eval(
                        end,
                        MirValue::Call {
                            callee: callee_value,
                            args: lowered_args,
                        },
                        result_ty,
                    )),
                )
            }
            HirExprKind::FieldAccess { base, field } => {
                if let HirExprKind::Ident(base_name) = &base.kind {
                    if !self.locals.contains_key(base_name) {
                        if let Some(import_path) = self.top_level_import_path(base_name) {
                            if let Some(qualified) =
                                self.resolve_import_member_ident(import_path, field)
                            {
                                return (
                                    block,
                                    Some(self.push_eval(
                                        block,
                                        MirValue::Ident(qualified),
                                        MirValueType::Function,
                                    )),
                                );
                            }
                        }
                    }
                }

                let (end, base_value) = self.lower_expr(block, base);
                let Some(base_value) = base_value else {
                    return (end, None);
                };
                if let Some(fields) = self.struct_fields.get(&base_value) {
                    if let Some(value) = fields.get(field).copied() {
                        return (end, Some(value));
                    }
                }
                (
                    end,
                    Some(self.push_eval(
                        end,
                        MirValue::FieldAccess {
                            base: base_value,
                            field: field.clone(),
                        },
                        MirValueType::Unknown,
                    )),
                )
            }
            HirExprKind::DerefAccess { base } => {
                let (end, base_value) = self.lower_expr(block, base);
                let Some(base_value) = base_value else {
                    return (end, None);
                };
                (
                    end,
                    Some(
                        self.push_eval(
                            end,
                            MirValue::DerefAccess { base: base_value },
                            self.value_types
                                .get(&base_value)
                                .cloned()
                                .unwrap_or(MirValueType::Unknown),
                        ),
                    ),
                )
            }
            HirExprKind::Index { base, index } => {
                if let HirExprKind::Binary { op, left, right } = &index.kind {
                    if matches!(
                        op,
                        crate::compiler::ast::BinaryOp::Range
                            | crate::compiler::ast::BinaryOp::RangeInclusive
                    ) {
                        let (base_end, base_value) = self.lower_expr(block, base);
                        let Some(base_value) = base_value else {
                            return (base_end, None);
                        };
                        let (after_start, start_value) = self.lower_expr(base_end, left);
                        let (after_end, end_value) = self.lower_expr(after_start, right);
                        let (Some(start_value), Some(end_value)) = (start_value, end_value) else {
                            return (after_end, None);
                        };

                        let inclusive =
                            matches!(op, crate::compiler::ast::BinaryOp::RangeInclusive);
                        let dest = self.push_eval(
                            after_end,
                            MirValue::Slice {
                                base: base_value,
                                start: Some(start_value),
                                end: Some(end_value),
                                inclusive,
                            },
                            MirValueType::Unknown,
                        );

                        if let Some(sequence) = self.aggregate_sequences.get(&base_value).cloned() {
                            let start_idx =
                                self.literal_int_value(start_value).unwrap_or(0).max(0) as usize;
                            let mut end_idx = self
                                .literal_int_value(end_value)
                                .map(|v| v.max(0) as usize)
                                .unwrap_or(sequence.len());
                            if inclusive {
                                end_idx = end_idx.saturating_add(1);
                            }
                            let clamped_start = start_idx.min(sequence.len());
                            let clamped_end = end_idx.min(sequence.len());
                            if clamped_start <= clamped_end {
                                self.aggregate_sequences
                                    .insert(dest, sequence[clamped_start..clamped_end].to_vec());
                            }
                        }
                        return (after_end, Some(dest));
                    }
                }

                let (base_end, base_value) = self.lower_expr(block, base);
                let (idx_end, index_value) = self.lower_expr(base_end, index);
                let (Some(base_value), Some(index_value)) = (base_value, index_value) else {
                    return (idx_end, None);
                };
                if let Some(values) = self.aggregate_sequences.get(&base_value) {
                    if let Some(idx) = self.literal_int_value(index_value) {
                        if let Some(target) = values.get(idx as usize).copied() {
                            return (idx_end, Some(target));
                        }
                    }
                }
                (
                    idx_end,
                    Some(self.push_eval(
                        idx_end,
                        MirValue::Index {
                            base: base_value,
                            index: index_value,
                        },
                        MirValueType::Unknown,
                    )),
                )
            }
            HirExprKind::Slice {
                base,
                start,
                end,
                inclusive,
            } => {
                let (base_end, base_value) = self.lower_expr(block, base);
                let Some(base_value) = base_value else {
                    return (base_end, None);
                };
                let (after_start, start_value) = if let Some(start) = start {
                    let (end, value) = self.lower_expr(base_end, start);
                    (end, value)
                } else {
                    (base_end, None)
                };
                let (after_end, end_value) = if let Some(end_expr) = end {
                    let (end, value) = self.lower_expr(after_start, end_expr);
                    (end, value)
                } else {
                    (after_start, None)
                };
                let dest = self.push_eval(
                    after_end,
                    MirValue::Slice {
                        base: base_value,
                        start: start_value,
                        end: end_value,
                        inclusive: *inclusive,
                    },
                    MirValueType::Unknown,
                );

                if let Some(sequence) = self.aggregate_sequences.get(&base_value).cloned() {
                    let start_idx = start_value
                        .and_then(|value| self.literal_int_value(value))
                        .unwrap_or(0)
                        .max(0) as usize;
                    let mut end_idx = end_value
                        .and_then(|value| self.literal_int_value(value))
                        .map(|v| v.max(0) as usize)
                        .unwrap_or(sequence.len());
                    if *inclusive {
                        end_idx = end_idx.saturating_add(1);
                    }
                    let clamped_start = start_idx.min(sequence.len());
                    let clamped_end = end_idx.min(sequence.len());
                    if clamped_start <= clamped_end {
                        self.aggregate_sequences
                            .insert(dest, sequence[clamped_start..clamped_end].to_vec());
                    }
                }

                (after_end, Some(dest))
            }
            HirExprKind::StructLiteral { fields, .. } => {
                let mut end = block;
                let mut lowered_fields = Vec::with_capacity(fields.len());
                let mut field_map = BTreeMap::new();
                let mut seq = Vec::with_capacity(fields.len());
                for (name, expr) in fields {
                    let (field_end, field_value) = self.lower_expr(end, expr);
                    end = field_end;
                    let Some(field_value) = field_value else {
                        return (end, None);
                    };
                    lowered_fields.push((name.clone(), field_value));
                    field_map.insert(name.clone(), field_value);
                    seq.push(field_value);
                }
                let dest = self.push_eval(
                    end,
                    MirValue::StructLiteral {
                        fields: lowered_fields,
                    },
                    MirValueType::Unknown,
                );
                self.struct_fields.insert(dest, field_map);
                self.aggregate_sequences.insert(dest, seq);
                (end, Some(dest))
            }
            HirExprKind::EnumVariant { variant, payload } => {
                let mut end = block;
                let mut lowered_payload = Vec::with_capacity(payload.len());
                for expr in payload {
                    let (payload_end, payload_value) = self.lower_expr(end, expr);
                    end = payload_end;
                    let Some(payload_value) = payload_value else {
                        return (end, None);
                    };
                    lowered_payload.push(payload_value);
                }
                let tag = self.variant_tag_for(variant);
                let tag_value = self.push_eval(
                    end,
                    MirValue::Literal(HirLiteral::Integer(tag.to_string())),
                    MirValueType::Int {
                        signed: false,
                        bits: 32,
                    },
                );
                (
                    end,
                    Some({
                        let dest = self.push_eval(
                            end,
                            MirValue::EnumVariant {
                                variant: variant.clone(),
                                payload: lowered_payload.clone(),
                            },
                            MirValueType::Unknown,
                        );
                        let mut aggregate = Vec::with_capacity(lowered_payload.len() + 1);
                        aggregate.push(tag_value);
                        aggregate.extend(lowered_payload);
                        self.aggregate_sequences.insert(dest, aggregate);
                        dest
                    }),
                )
            }
            HirExprKind::Block { body } => {
                let mut end = block;
                let mut last = None;
                for value in body {
                    if self.is_terminated(end) {
                        break;
                    }
                    let lowered = self.lower_expr(end, value);
                    end = lowered.0;
                    last = lowered.1;
                }
                (end, last)
            }
            HirExprKind::If {
                condition,
                capture,
                then_branch,
                else_branch,
            } => self.lower_if(
                block,
                condition,
                capture.as_ref(),
                then_branch,
                else_branch.as_deref(),
            ),
            HirExprKind::Return { value } => {
                let return_value = if let Some(value) = value {
                    let (end, lowered) = self.lower_expr(block, value);
                    let end = self.emit_deferred(end, None);
                    self.set_terminator(end, MirTerminator::Return(lowered));
                    return (end, None);
                } else {
                    None
                };
                let block = self.emit_deferred(block, None);
                self.set_terminator(block, MirTerminator::Return(return_value));
                (block, None)
            }
            HirExprKind::Use { path } => {
                let value = self.push_eval(
                    block,
                    MirValue::Use { path: path.clone() },
                    MirValueType::Unknown,
                );

                let target_key = import_path_to_module_key(&self.module_key, path);
                if let Some(target_module_id) = self.module_ids_by_key.get(&target_key).copied() {
                    if let Some(exports) = self.module_exports_by_id.get(&target_module_id).cloned()
                    {
                        let mut fields = BTreeMap::new();
                        for export_name in &exports {
                            let qualified = qualified_function_name(target_module_id, export_name);
                            let export_value = self.push_eval(
                                block,
                                MirValue::Ident(qualified),
                                MirValueType::Function,
                            );
                            fields.insert(export_name.clone(), export_value);
                        }
                        if !fields.is_empty() {
                            self.struct_fields.insert(value, fields);
                        }
                    }
                }

                (block, Some(value))
            }
            HirExprKind::TypeLiteral(name) => (
                block,
                Some(self.push_eval(
                    block,
                    MirValue::TypeLiteral(name.clone()),
                    MirValueType::Type,
                )),
            ),
            HirExprKind::Comptime { expr } | HirExprKind::Inline { expr } => {
                if let Some(constant) = self.try_eval_comptime_expr(expr, 0) {
                    (block, Some(self.emit_comptime_value(block, constant)))
                } else {
                    self.lower_expr(block, expr)
                }
            }
            HirExprKind::Match { value, arms } => self.lower_match(block, value, arms),
            HirExprKind::Unknown => (
                block,
                Some(self.push_eval(block, MirValue::Unknown, MirValueType::Unknown)),
            ),
            HirExprKind::For(for_expr) => self.lower_for(block, for_expr),
            HirExprKind::Break { value } => {
                let mut at = block;
                let mut break_value = None;
                if let Some(value) = value {
                    let (end, lowered) = self.lower_expr(at, value);
                    at = end;
                    break_value = lowered;
                }
                if let Some(ctx) = self.loop_stack.last_mut() {
                    let break_target = ctx.break_target;
                    if let Some(value) = break_value {
                        ctx.break_values.push((at, value));
                    }
                    self.set_terminator(at, MirTerminator::Goto(break_target));
                    (at, None)
                } else if let Some(ctx) = self.or_break_stack.last_mut() {
                    let target = ctx.target;
                    if let Some(value) = break_value {
                        ctx.values.push((at, value));
                    }
                    self.set_terminator(at, MirTerminator::Goto(target));
                    (at, None)
                } else {
                    (
                        at,
                        Some(self.push_eval(at, MirValue::Unknown, MirValueType::Unknown)),
                    )
                }
            }
            HirExprKind::Continue => {
                if let Some(ctx) = self.loop_stack.last().cloned() {
                    self.set_terminator(block, MirTerminator::Goto(ctx.continue_target));
                    (block, None)
                } else {
                    (
                        block,
                        Some(self.push_eval(block, MirValue::Unknown, MirValueType::Unknown)),
                    )
                }
            }
            HirExprKind::Defer {
                error_binding,
                body,
            } => {
                self.deferred.push(DeferredExpr {
                    error_binding: error_binding.clone(),
                    body: (**body).clone(),
                });
                (
                    block,
                    Some(self.push_eval(block, MirValue::Unknown, MirValueType::Unknown)),
                )
            }
            HirExprKind::OptionalUnwrap { value } => self.lower_force_unwrap(block, value, false),
            HirExprKind::ErrorUnwrap { value } => self.lower_force_unwrap(block, value, true),
            HirExprKind::OrElse {
                value,
                error_binding,
                fallback,
            } => self.lower_or_else(block, value, error_binding.as_deref(), fallback),
            HirExprKind::Function { .. } => (
                block,
                Some(self.push_eval(block, MirValue::Unknown, MirValueType::Unknown)),
            ),
        }
    }

    fn lower_or_else(
        &mut self,
        block: MirBlockId,
        value: &HirExpr,
        error_binding: Option<&str>,
        fallback: &HirExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        let (start, value_id) = self.lower_expr(block, value);
        let Some(value_id) = value_id else {
            return (start, None);
        };
        let value_ty = self
            .value_types
            .get(&value_id)
            .cloned()
            .unwrap_or(MirValueType::Unknown);

        let then_block = self.new_block();
        let else_block = self.new_block();
        let join = self.new_block();
        let cond = self.emit_nonzero_check(start, value_id, &value_ty);
        if !self.is_terminated(start) {
            self.set_terminator(
                start,
                MirTerminator::Branch {
                    condition: cond,
                    then_block,
                    else_block,
                },
            );
        }

        if !self.is_terminated(then_block) {
            self.set_terminator(then_block, MirTerminator::Goto(join));
        }

        self.or_break_stack.push(OrBreakContext {
            target: join,
            values: Vec::new(),
        });
        let prev_error_binding = error_binding.and_then(|binding| {
            self.locals
                .insert(binding.to_string(), value_id)
                .map(|prev| (binding.to_string(), prev))
        });
        let (else_end, else_value) = self.lower_expr(else_block, fallback);
        if let Some(binding) = error_binding {
            if let Some((name, prev)) = prev_error_binding {
                self.locals.insert(name, prev);
            } else {
                self.locals.remove(binding);
            }
        }
        let mut break_ctx = self
            .or_break_stack
            .pop()
            .expect("or-break context should exist");

        let mut fallback_sources = Vec::new();
        if !self.is_terminated(else_end) {
            self.set_terminator(else_end, MirTerminator::Goto(join));
            if let Some(value) = else_value {
                fallback_sources.push((else_end, value));
            }
        }
        fallback_sources.append(&mut break_ctx.values);

        if fallback_sources.is_empty() {
            return (join, Some(value_id));
        }

        let sources = std::iter::once((then_block, value_id))
            .chain(fallback_sources.iter().copied())
            .collect::<Vec<_>>();

        let dest = self.fresh_value();
        let phi_ty = fallback_sources
            .iter()
            .filter_map(|(_, value)| self.value_types.get(value))
            .fold(value_ty.clone(), |left, right| merge_types(&left, right));
        self.function.blocks[join.0]
            .instructions
            .push(MirInstr::Phi {
                dest,
                sources,
                ty: phi_ty.clone(),
            });
        self.value_types.insert(dest, phi_ty);
        (join, Some(dest))
    }

    fn emit_nonzero_check(
        &mut self,
        block: MirBlockId,
        value: MirValueId,
        value_ty: &MirValueType,
    ) -> MirValueId {
        let zero_literal = match value_ty {
            MirValueType::Float { .. } => HirLiteral::Float("0.0".to_string()),
            MirValueType::Bool => HirLiteral::Bool(false),
            _ => HirLiteral::Integer("0".to_string()),
        };
        let zero = self.push_eval(block, MirValue::Literal(zero_literal), value_ty.clone());
        self.push_eval(
            block,
            MirValue::Binary {
                op: crate::compiler::ast::BinaryOp::Ne,
                left: value,
                right: zero,
            },
            MirValueType::Bool,
        )
    }

    fn lower_force_unwrap(
        &mut self,
        block: MirBlockId,
        value_expr: &HirExpr,
        is_error_unwrap: bool,
    ) -> (MirBlockId, Option<MirValueId>) {
        let (start, value_id) = self.lower_expr(block, value_expr);
        let Some(value_id) = value_id else {
            return (start, None);
        };
        let value_ty = self
            .value_types
            .get(&value_id)
            .cloned()
            .unwrap_or(MirValueType::Unknown);
        let cond = self.emit_nonzero_check(start, value_id, &value_ty);

        let ok_block = self.new_block();
        let fail_block = self.new_block();
        if !self.is_terminated(start) {
            self.set_terminator(
                start,
                MirTerminator::Branch {
                    condition: cond,
                    then_block: ok_block,
                    else_block: fail_block,
                },
            );
        }

        let fail_end = self.emit_deferred(
            fail_block,
            if is_error_unwrap {
                Some(value_id)
            } else {
                None
            },
        );
        if !self.is_terminated(fail_end) {
            self.set_terminator(fail_end, MirTerminator::Unreachable);
        }

        (ok_block, Some(value_id))
    }

    fn emit_deferred(&mut self, block: MirBlockId, error_value: Option<MirValueId>) -> MirBlockId {
        let mut at = block;
        let deferred = self.deferred.clone();
        for deferred_expr in deferred.iter().rev() {
            if self.is_terminated(at) {
                break;
            }
            match (&deferred_expr.error_binding, error_value) {
                (Some(binding), Some(value)) => {
                    let prev = self.locals.insert(binding.clone(), value);
                    let (end, _) = self.lower_expr(at, &deferred_expr.body);
                    at = end;
                    if let Some(prev) = prev {
                        self.locals.insert(binding.clone(), prev);
                    } else {
                        self.locals.remove(binding);
                    }
                }
                (Some(_), None) => {}
                (None, _) => {
                    let (end, _) = self.lower_expr(at, &deferred_expr.body);
                    at = end;
                }
            }
        }
        at
    }

    fn lower_for(
        &mut self,
        block: MirBlockId,
        for_expr: &HirForExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        match for_expr {
            HirForExpr::Infinite { body } => self.lower_infinite_loop(block, body),
            HirForExpr::WhileLike { condition, body } => {
                self.lower_while_like_loop(block, condition, body)
            }
            HirForExpr::Range {
                start,
                end,
                inclusive,
                binding,
                body,
            } => self.lower_range_loop(block, start, end, *inclusive, binding.as_deref(), body),
            HirForExpr::Iterate {
                iterable,
                binding,
                body,
            } => self.lower_iterate_loop(block, iterable, binding.as_deref(), body),
        }
    }

    fn prepare_loop_carried_locals(
        &mut self,
        header: MirBlockId,
        incoming_block: MirBlockId,
        body: &HirExpr,
    ) -> Vec<(String, MirValueId)> {
        let mut carried = Vec::new();
        for name in assigned_local_names(body) {
            let Some(current) = self.locals.get(&name).copied() else {
                continue;
            };
            let ty = self
                .value_types
                .get(&current)
                .cloned()
                .unwrap_or(MirValueType::Unknown);
            let phi = self.fresh_value();
            self.function.blocks[header.0]
                .instructions
                .push(MirInstr::Phi {
                    dest: phi,
                    sources: vec![(incoming_block, current)],
                    ty,
                });
            self.value_types.insert(
                phi,
                self.value_types
                    .get(&current)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown),
            );
            self.locals.insert(name.clone(), phi);
            carried.push((name, phi));
        }
        carried
    }

    fn finalize_loop_carried_locals(
        &mut self,
        header: MirBlockId,
        backedge_block: MirBlockId,
        carried: &[(String, MirValueId)],
    ) {
        for (name, phi) in carried {
            let source = self.locals.get(name).copied().unwrap_or(*phi);
            for instr in &mut self.function.blocks[header.0].instructions {
                if let MirInstr::Phi { dest, sources, .. } = instr {
                    if *dest == *phi {
                        sources.push((backedge_block, source));
                        break;
                    }
                }
            }
            self.locals.insert(name.clone(), *phi);
        }
    }

    fn lower_range_loop(
        &mut self,
        block: MirBlockId,
        start: &HirExpr,
        end: &HirExpr,
        inclusive: bool,
        binding: Option<&str>,
        body: &HirExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        let (after_start, start_value) = self.lower_expr(block, start);
        let Some(start_value) = start_value else {
            return (after_start, None);
        };
        let (after_end, end_value) = self.lower_expr(after_start, end);
        let Some(end_value) = end_value else {
            return (after_end, None);
        };

        let iter_ty = self
            .value_types
            .get(&start_value)
            .cloned()
            .zip(self.value_types.get(&end_value).cloned())
            .map(|(left, right)| merge_types(&left, &right))
            .unwrap_or_else(|| {
                self.value_types
                    .get(&start_value)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown)
            });

        let header = self.new_block();
        let body_block = self.new_block();
        let step_block = self.new_block();
        let exit = self.new_block();

        if !self.is_terminated(after_end) {
            self.set_terminator(after_end, MirTerminator::Goto(header));
        }

        let iter_value = self.fresh_value();
        self.function.blocks[header.0]
            .instructions
            .push(MirInstr::Phi {
                dest: iter_value,
                sources: vec![(after_end, start_value)],
                ty: iter_ty.clone(),
            });
        self.value_types.insert(iter_value, iter_ty.clone());

        let carried = self.prepare_loop_carried_locals(header, after_end, body);

        let cond_op = if inclusive {
            crate::compiler::ast::BinaryOp::Le
        } else {
            crate::compiler::ast::BinaryOp::Lt
        };
        let cond = self.push_eval(
            header,
            MirValue::Binary {
                op: cond_op,
                left: iter_value,
                right: end_value,
            },
            MirValueType::Bool,
        );
        if !self.is_terminated(header) {
            self.set_terminator(
                header,
                MirTerminator::Branch {
                    condition: cond,
                    then_block: body_block,
                    else_block: exit,
                },
            );
        }

        self.loop_stack.push(LoopContext {
            continue_target: step_block,
            break_target: exit,
            break_values: Vec::new(),
        });

        let prev_binding = binding.and_then(|name| {
            self.locals
                .insert(name.to_string(), iter_value)
                .map(|prev| (name.to_string(), prev))
        });
        let (body_end, _) = self.lower_expr(body_block, body);
        if let Some(name) = binding {
            if let Some((saved_name, prev)) = prev_binding {
                self.locals.insert(saved_name, prev);
            } else {
                self.locals.remove(name);
            }
        }
        if !self.is_terminated(body_end) {
            self.set_terminator(body_end, MirTerminator::Goto(step_block));
        }

        let one_literal = match iter_ty {
            MirValueType::Float { .. } => HirLiteral::Float("1.0".to_string()),
            _ => HirLiteral::Integer("1".to_string()),
        };
        let one = self.push_eval(step_block, MirValue::Literal(one_literal), iter_ty.clone());
        let next_iter = self.push_eval(
            step_block,
            MirValue::Binary {
                op: crate::compiler::ast::BinaryOp::Add,
                left: iter_value,
                right: one,
            },
            iter_ty,
        );
        if let Some(MirInstr::Phi { sources, .. }) =
            self.function.blocks[header.0].instructions.first_mut()
        {
            sources.push((step_block, next_iter));
        }
        self.finalize_loop_carried_locals(header, step_block, &carried);
        if !self.is_terminated(step_block) {
            self.set_terminator(step_block, MirTerminator::Goto(header));
        }

        let ctx = self.loop_stack.pop().expect("loop context should exist");
        (exit, self.build_loop_break_value(exit, ctx.break_values))
    }

    fn lower_iterate_loop(
        &mut self,
        block: MirBlockId,
        iterable: &HirExpr,
        binding: Option<&str>,
        body: &HirExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        let (after_iterable, iterable_value) = self.lower_expr(block, iterable);
        let Some(iterable_value) = iterable_value else {
            return (after_iterable, None);
        };

        let len = self
            .aggregate_sequences
            .get(&iterable_value)
            .map(|values| values.len())
            .unwrap_or(0);

        let index_ty = MirValueType::Int {
            signed: false,
            bits: 64,
        };
        let index_start = self.push_eval(
            after_iterable,
            MirValue::Literal(HirLiteral::Integer("0".to_string())),
            index_ty.clone(),
        );
        let len_value = self.push_eval(
            after_iterable,
            MirValue::Literal(HirLiteral::Integer(len.to_string())),
            index_ty.clone(),
        );

        let header = self.new_block();
        let body_block = self.new_block();
        let step_block = self.new_block();
        let exit = self.new_block();

        if !self.is_terminated(after_iterable) {
            self.set_terminator(after_iterable, MirTerminator::Goto(header));
        }

        let index_value = self.fresh_value();
        self.function.blocks[header.0]
            .instructions
            .push(MirInstr::Phi {
                dest: index_value,
                sources: vec![(after_iterable, index_start)],
                ty: index_ty.clone(),
            });
        self.value_types.insert(index_value, index_ty.clone());

        let carried = self.prepare_loop_carried_locals(header, after_iterable, body);

        let cond = self.push_eval(
            header,
            MirValue::Binary {
                op: crate::compiler::ast::BinaryOp::Lt,
                left: index_value,
                right: len_value,
            },
            MirValueType::Bool,
        );
        if !self.is_terminated(header) {
            self.set_terminator(
                header,
                MirTerminator::Branch {
                    condition: cond,
                    then_block: body_block,
                    else_block: exit,
                },
            );
        }

        self.loop_stack.push(LoopContext {
            continue_target: step_block,
            break_target: exit,
            break_values: Vec::new(),
        });

        let (body_start, prev_binding) = if let Some(name) = binding {
            let element_value =
                if let Some(sequence) = self.aggregate_sequences.get(&iterable_value) {
                    if let Some(first_element) = sequence.first().copied() {
                        self.push_eval(
                            body_block,
                            MirValue::Index {
                                base: iterable_value,
                                index: index_value,
                            },
                            self.value_types
                                .get(&first_element)
                                .cloned()
                                .unwrap_or(MirValueType::Unknown),
                        )
                    } else {
                        self.push_eval(body_block, MirValue::Unknown, MirValueType::Unknown)
                    }
                } else {
                    self.push_eval(
                        body_block,
                        MirValue::Index {
                            base: iterable_value,
                            index: index_value,
                        },
                        MirValueType::Unknown,
                    )
                };
            let prev = self
                .locals
                .insert(name.to_string(), element_value)
                .map(|existing| (name.to_string(), existing));
            (body_block, prev)
        } else {
            (body_block, None)
        };

        let (body_end, _) = self.lower_expr(body_start, body);
        if let Some(name) = binding {
            if let Some((saved_name, prev)) = prev_binding {
                self.locals.insert(saved_name, prev);
            } else {
                self.locals.remove(name);
            }
        }
        if !self.is_terminated(body_end) {
            self.set_terminator(body_end, MirTerminator::Goto(step_block));
        }

        let one = self.push_eval(
            step_block,
            MirValue::Literal(HirLiteral::Integer("1".to_string())),
            index_ty.clone(),
        );
        let next_index = self.push_eval(
            step_block,
            MirValue::Binary {
                op: crate::compiler::ast::BinaryOp::Add,
                left: index_value,
                right: one,
            },
            index_ty,
        );
        if let Some(MirInstr::Phi { sources, .. }) =
            self.function.blocks[header.0].instructions.first_mut()
        {
            sources.push((step_block, next_index));
        }
        self.finalize_loop_carried_locals(header, step_block, &carried);
        if !self.is_terminated(step_block) {
            self.set_terminator(step_block, MirTerminator::Goto(header));
        }

        let ctx = self.loop_stack.pop().expect("loop context should exist");
        (exit, self.build_loop_break_value(exit, ctx.break_values))
    }

    fn lower_infinite_loop(
        &mut self,
        block: MirBlockId,
        body: &HirExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        let header = self.new_block();
        let body_block = self.new_block();
        let exit = self.new_block();

        if !self.is_terminated(block) {
            self.set_terminator(block, MirTerminator::Goto(header));
        }
        if !self.is_terminated(header) {
            self.set_terminator(header, MirTerminator::Goto(body_block));
        }

        self.loop_stack.push(LoopContext {
            continue_target: header,
            break_target: exit,
            break_values: Vec::new(),
        });

        let (body_end, _) = self.lower_expr(body_block, body);
        if !self.is_terminated(body_end) {
            self.set_terminator(body_end, MirTerminator::Goto(header));
        }
        let ctx = self.loop_stack.pop().expect("loop context should exist");

        (exit, self.build_loop_break_value(exit, ctx.break_values))
    }

    fn lower_while_like_loop(
        &mut self,
        block: MirBlockId,
        condition: &HirExpr,
        body: &HirExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        let header = self.new_block();
        let body_block = self.new_block();
        let exit = self.new_block();

        if !self.is_terminated(block) {
            self.set_terminator(block, MirTerminator::Goto(header));
        }

        let (cond_end, cond_value) = self.lower_expr(header, condition);
        let cond_value = cond_value.unwrap_or_else(|| {
            self.push_eval(
                cond_end,
                MirValue::Literal(HirLiteral::Bool(false)),
                MirValueType::Bool,
            )
        });
        if !self.is_terminated(cond_end) {
            self.set_terminator(
                cond_end,
                MirTerminator::Branch {
                    condition: cond_value,
                    then_block: body_block,
                    else_block: exit,
                },
            );
        }

        self.loop_stack.push(LoopContext {
            continue_target: header,
            break_target: exit,
            break_values: Vec::new(),
        });
        let (body_end, _) = self.lower_expr(body_block, body);
        if !self.is_terminated(body_end) {
            self.set_terminator(body_end, MirTerminator::Goto(header));
        }
        let ctx = self.loop_stack.pop().expect("loop context should exist");

        (exit, self.build_loop_break_value(exit, ctx.break_values))
    }

    fn build_loop_break_value(
        &mut self,
        exit: MirBlockId,
        break_values: Vec<(MirBlockId, MirValueId)>,
    ) -> Option<MirValueId> {
        if break_values.is_empty() {
            return None;
        }
        if break_values.len() == 1 {
            return Some(break_values[0].1);
        }

        let dest = self.fresh_value();
        let phi_ty = break_values
            .iter()
            .filter_map(|(_, value)| self.value_types.get(value))
            .cloned()
            .reduce(|left, right| merge_types(&left, &right))
            .unwrap_or(MirValueType::Unknown);
        self.function.blocks[exit.0]
            .instructions
            .push(MirInstr::Phi {
                dest,
                sources: break_values,
                ty: phi_ty.clone(),
            });
        self.value_types.insert(dest, phi_ty);
        Some(dest)
    }

    fn lower_match(
        &mut self,
        block: MirBlockId,
        scrutinee: &HirExpr,
        arms: &[crate::compiler::hir::HirMatchArm],
    ) -> (MirBlockId, Option<MirValueId>) {
        let (start_test, scrutinee_value) = self.lower_expr(block, scrutinee);
        let Some(scrutinee_value) = scrutinee_value else {
            return (start_test, None);
        };

        let join = self.new_block();
        let mut test_block = start_test;
        let mut join_sources: Vec<(MirBlockId, MirValueId)> = Vec::new();

        for (idx, arm) in arms.iter().enumerate() {
            let arm_block = self.new_block();
            let fallback_block = if idx + 1 == arms.len() {
                join
            } else {
                self.new_block()
            };

            let guard_block = if arm.guard.is_some() {
                Some(self.new_block())
            } else {
                None
            };

            let pattern_pass_block = guard_block.unwrap_or(arm_block);
            self.lower_match_pattern(
                test_block,
                scrutinee_value,
                &arm.pattern,
                pattern_pass_block,
                fallback_block,
            );

            if let Some(guard_expr) = &arm.guard {
                let guard_block = guard_block.expect("guard block should exist");
                let (guard_start, guard_saved) =
                    self.bind_match_pattern_values(guard_block, scrutinee_value, &arm.pattern);
                let (guard_end, guard_value) = self.lower_expr(guard_start, guard_expr);
                self.restore_local_bindings(guard_saved);
                let guard_cond = guard_value.unwrap_or_else(|| {
                    self.push_eval(
                        guard_end,
                        MirValue::Literal(HirLiteral::Bool(false)),
                        MirValueType::Bool,
                    )
                });
                if !self.is_terminated(guard_end) {
                    self.set_terminator(
                        guard_end,
                        MirTerminator::Branch {
                            condition: guard_cond,
                            then_block: arm_block,
                            else_block: fallback_block,
                        },
                    );
                }
            }

            let (arm_start, arm_saved) =
                self.bind_match_pattern_values(arm_block, scrutinee_value, &arm.pattern);
            let (arm_end, arm_value) = self.lower_expr(arm_start, &arm.value);
            self.restore_local_bindings(arm_saved);
            if !self.is_terminated(arm_end) {
                self.set_terminator(arm_end, MirTerminator::Goto(join));
                if let Some(arm_value) = arm_value {
                    join_sources.push((arm_end, arm_value));
                }
            }

            test_block = fallback_block;
        }

        if test_block != join && !self.is_terminated(test_block) {
            self.set_terminator(test_block, MirTerminator::Goto(join));
        }

        if join_sources.is_empty() {
            (join, None)
        } else if join_sources.len() == 1 {
            (join, Some(join_sources[0].1))
        } else {
            let dest = self.fresh_value();
            let phi_ty = join_sources
                .iter()
                .filter_map(|(_, value)| self.value_types.get(value))
                .cloned()
                .reduce(|left, right| merge_types(&left, &right))
                .unwrap_or(MirValueType::Unknown);
            self.function.blocks[join.0]
                .instructions
                .push(MirInstr::Phi {
                    dest,
                    sources: join_sources,
                    ty: phi_ty.clone(),
                });
            self.value_types.insert(dest, phi_ty);
            (join, Some(dest))
        }
    }

    fn lower_match_pattern(
        &mut self,
        test_block: MirBlockId,
        scrutinee_value: MirValueId,
        pattern: &HirPattern,
        then_block: MirBlockId,
        else_block: MirBlockId,
    ) {
        match pattern {
            HirPattern::Wildcard | HirPattern::IdentBind(_) | HirPattern::Other => {
                if !self.is_terminated(test_block) {
                    self.set_terminator(test_block, MirTerminator::Goto(then_block));
                }
            }
            HirPattern::EnumVariant { variant, .. } => {
                let scrutinee_tag = self
                    .aggregate_sequences
                    .get(&scrutinee_value)
                    .and_then(|sequence| sequence.first().copied())
                    .unwrap_or_else(|| {
                        let tag_index = self.push_eval(
                            test_block,
                            MirValue::Literal(HirLiteral::Integer("0".to_string())),
                            MirValueType::Int {
                                signed: false,
                                bits: 32,
                            },
                        );
                        self.push_eval(
                            test_block,
                            MirValue::Index {
                                base: scrutinee_value,
                                index: tag_index,
                            },
                            MirValueType::Int {
                                signed: false,
                                bits: 32,
                            },
                        )
                    });
                let variant_tag = self.variant_tag_for(variant);
                let expected_tag = self.push_eval(
                    test_block,
                    MirValue::Literal(HirLiteral::Integer(variant_tag.to_string())),
                    MirValueType::Int {
                        signed: false,
                        bits: 32,
                    },
                );
                let cond = self.push_eval(
                    test_block,
                    MirValue::Binary {
                        op: crate::compiler::ast::BinaryOp::Eq,
                        left: scrutinee_tag,
                        right: expected_tag,
                    },
                    MirValueType::Bool,
                );
                if !self.is_terminated(test_block) {
                    self.set_terminator(
                        test_block,
                        MirTerminator::Branch {
                            condition: cond,
                            then_block,
                            else_block,
                        },
                    );
                }
            }
            HirPattern::Literal(literal) => {
                let lit_ty = literal_type(literal);
                let literal_value =
                    self.push_eval(test_block, MirValue::Literal(literal.clone()), lit_ty);
                let cond = self.push_eval(
                    test_block,
                    MirValue::Binary {
                        op: crate::compiler::ast::BinaryOp::Eq,
                        left: scrutinee_value,
                        right: literal_value,
                    },
                    MirValueType::Bool,
                );
                if !self.is_terminated(test_block) {
                    self.set_terminator(
                        test_block,
                        MirTerminator::Branch {
                            condition: cond,
                            then_block,
                            else_block,
                        },
                    );
                }
            }
            HirPattern::RangeLiteral {
                start,
                end,
                inclusive,
            } => {
                let start_value = self.push_eval(
                    test_block,
                    MirValue::Literal(start.clone()),
                    literal_type(start),
                );
                let end_value = self.push_eval(
                    test_block,
                    MirValue::Literal(end.clone()),
                    literal_type(end),
                );
                let lower_ok = self.push_eval(
                    test_block,
                    MirValue::Binary {
                        op: crate::compiler::ast::BinaryOp::Ge,
                        left: scrutinee_value,
                        right: start_value,
                    },
                    MirValueType::Bool,
                );
                let upper_op = if *inclusive {
                    crate::compiler::ast::BinaryOp::Le
                } else {
                    crate::compiler::ast::BinaryOp::Lt
                };
                let upper_ok = self.push_eval(
                    test_block,
                    MirValue::Binary {
                        op: upper_op,
                        left: scrutinee_value,
                        right: end_value,
                    },
                    MirValueType::Bool,
                );
                let cond = self.push_eval(
                    test_block,
                    MirValue::Binary {
                        op: crate::compiler::ast::BinaryOp::LogicalAnd,
                        left: lower_ok,
                        right: upper_ok,
                    },
                    MirValueType::Bool,
                );
                if !self.is_terminated(test_block) {
                    self.set_terminator(
                        test_block,
                        MirTerminator::Branch {
                            condition: cond,
                            then_block,
                            else_block,
                        },
                    );
                }
            }
        }
    }

    fn bind_match_pattern_values(
        &mut self,
        block: MirBlockId,
        scrutinee_value: MirValueId,
        pattern: &HirPattern,
    ) -> (MirBlockId, Vec<(String, Option<MirValueId>)>) {
        let (end, bindings) = self.pattern_binding_values(block, scrutinee_value, pattern);
        let mut saved = Vec::with_capacity(bindings.len());
        for (name, value) in bindings {
            let prev = self.locals.insert(name.clone(), value);
            saved.push((name, prev));
        }
        (end, saved)
    }

    fn restore_local_bindings(&mut self, saved: Vec<(String, Option<MirValueId>)>) {
        for (name, previous) in saved {
            if let Some(previous) = previous {
                self.locals.insert(name, previous);
            } else {
                self.locals.remove(&name);
            }
        }
    }

    fn pattern_binding_values(
        &mut self,
        block: MirBlockId,
        scrutinee_value: MirValueId,
        pattern: &HirPattern,
    ) -> (MirBlockId, Vec<(String, MirValueId)>) {
        match pattern {
            HirPattern::IdentBind(name) if name != "_" => {
                (block, vec![(name.clone(), scrutinee_value)])
            }
            HirPattern::EnumVariant { bindings, .. } => {
                let at = block;
                let sequence = self.aggregate_sequences.get(&scrutinee_value).cloned();
                let mut out = Vec::new();
                for (idx, name) in bindings.iter().enumerate() {
                    if name == "_" {
                        continue;
                    }
                    let payload_index = idx + 1;
                    let payload_value = sequence
                        .as_ref()
                        .and_then(|values| values.get(payload_index).copied())
                        .unwrap_or_else(|| {
                            let index_value = self.push_eval(
                                at,
                                MirValue::Literal(HirLiteral::Integer(payload_index.to_string())),
                                MirValueType::Int {
                                    signed: false,
                                    bits: 32,
                                },
                            );
                            self.push_eval(
                                at,
                                MirValue::Index {
                                    base: scrutinee_value,
                                    index: index_value,
                                },
                                MirValueType::Unknown,
                            )
                        });
                    out.push((name.clone(), payload_value));
                }
                (at, out)
            }
            _ => (block, Vec::new()),
        }
    }

    fn lower_if(
        &mut self,
        block: MirBlockId,
        condition: &HirExpr,
        capture: Option<&crate::compiler::hir::HirIfCapture>,
        then_branch: &HirExpr,
        else_branch: Option<&HirExpr>,
    ) -> (MirBlockId, Option<MirValueId>) {
        let (cond_end, cond_value) = self.lower_expr(block, condition);
        let Some(cond_value) = cond_value else {
            return (cond_end, None);
        };
        let branch_condition = if capture.is_some() {
            let cond_ty = self
                .value_types
                .get(&cond_value)
                .cloned()
                .unwrap_or(MirValueType::Unknown);
            self.emit_nonzero_check(cond_end, cond_value, &cond_ty)
        } else {
            cond_value
        };

        let then_block = self.new_block();
        let else_block = self.new_block();
        let join_block = self.new_block();

        self.set_terminator(
            cond_end,
            MirTerminator::Branch {
                condition: branch_condition,
                then_block,
                else_block,
            },
        );

        let capture_binding = capture.and_then(|capture| capture.binding.as_deref());
        let prev_capture_binding = capture_binding.and_then(|name| {
            self.locals
                .insert(name.to_string(), cond_value)
                .map(|prev| (name.to_string(), prev))
        });
        let (then_end, then_value) = self.lower_expr(then_block, then_branch);
        if let Some(name) = capture_binding {
            if let Some((saved_name, prev)) = prev_capture_binding {
                self.locals.insert(saved_name, prev);
            } else {
                self.locals.remove(name);
            }
        }
        let then_pred = if self.is_terminated(then_end) {
            None
        } else {
            self.set_terminator(then_end, MirTerminator::Goto(join_block));
            Some((then_end, then_value))
        };

        let else_pred = if let Some(else_branch) = else_branch {
            let (else_end, else_value) = self.lower_expr(else_block, else_branch);
            if self.is_terminated(else_end) {
                None
            } else {
                self.set_terminator(else_end, MirTerminator::Goto(join_block));
                Some((else_end, else_value))
            }
        } else {
            self.set_terminator(else_block, MirTerminator::Goto(join_block));
            Some((else_block, None))
        };

        let mut sources = Vec::new();
        if let Some((pred, Some(value))) = then_pred {
            sources.push((pred, value));
        }
        if let Some((pred, Some(value))) = else_pred {
            sources.push((pred, value));
        }

        if sources.is_empty() {
            (join_block, None)
        } else if sources.len() == 1 {
            (join_block, Some(sources[0].1))
        } else {
            let dest = self.fresh_value();
            let phi_ty = sources
                .iter()
                .filter_map(|(_, value)| self.value_types.get(value))
                .cloned()
                .reduce(|left, right| merge_types(&left, &right))
                .unwrap_or(MirValueType::Unknown);
            self.function.blocks[join_block.0]
                .instructions
                .push(MirInstr::Phi {
                    dest,
                    sources,
                    ty: phi_ty.clone(),
                });
            self.value_types.insert(dest, phi_ty);
            (join_block, Some(dest))
        }
    }

    fn new_block(&mut self) -> MirBlockId {
        let id = MirBlockId(self.function.blocks.len());
        self.function.blocks.push(MirBasicBlock {
            id,
            instructions: Vec::new(),
            terminator: None,
        });
        id
    }

    fn push_eval(&mut self, block: MirBlockId, value: MirValue, ty: MirValueType) -> MirValueId {
        let dest = self.fresh_value();
        self.function.blocks[block.0]
            .instructions
            .push(MirInstr::Eval {
                dest,
                value: value.clone(),
                ty: ty.clone(),
            });
        self.value_types.insert(dest, ty);
        self.value_defs.insert(dest, value);
        dest
    }

    fn literal_int_value(&self, value_id: MirValueId) -> Option<i64> {
        match self.value_defs.get(&value_id) {
            Some(MirValue::Literal(HirLiteral::Integer(v))) => {
                let normalized = v.replace('_', "");
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
            _ => None,
        }
    }

    fn variant_tag_for(&mut self, variant: &str) -> i64 {
        if let Some(tag) = self.variant_tag_ids.get(variant) {
            *tag
        } else {
            let tag = self.next_variant_tag;
            self.next_variant_tag += 1;
            self.variant_tag_ids.insert(variant.to_string(), tag);
            tag
        }
    }

    fn fresh_value(&mut self) -> MirValueId {
        let id = MirValueId(self.next_value);
        self.next_value += 1;
        id
    }

    fn is_terminated(&self, block: MirBlockId) -> bool {
        self.function.blocks[block.0].terminator.is_some()
    }

    fn set_terminator(&mut self, block: MirBlockId, term: MirTerminator) {
        self.function.blocks[block.0].terminator = Some(term);
    }

    fn emit_comptime_value(&mut self, block: MirBlockId, value: ComptimeValue) -> MirValueId {
        let (value, ty) = match value {
            ComptimeValue::Literal(lit) => {
                let ty = literal_type(&lit);
                (MirValue::Literal(lit), ty)
            }
            ComptimeValue::Type(name) => (MirValue::TypeLiteral(name), MirValueType::Type),
            ComptimeValue::Function(name) => (MirValue::Ident(name), MirValueType::Function),
        };
        self.push_eval(block, value, ty)
    }

    fn should_force_comptime_call(&self, callee_name: &str) -> bool {
        if matches!(
            self.function_return_types.get(callee_name),
            Some(MirValueType::Type)
        ) {
            return true;
        }
        self.function_param_type_hints
            .get(callee_name)
            .map(|params| {
                params.iter().flatten().any(|hint| {
                    matches!(parse_type_hint(hint), MirValueType::Type)
                        || hint.trim() == "comp type"
                })
            })
            .unwrap_or(false)
    }

    fn eval_type_designator_name(
        &self,
        expr: &HirExpr,
        locals: &BTreeMap<String, ComptimeValue>,
    ) -> Option<String> {
        match self.try_eval_comptime_expr_with_locals(expr, 0, &mut locals.clone()) {
            Some(ComptimeValue::Type(name)) => Some(name),
            Some(ComptimeValue::Function(_)) => Some("fn".to_string()),
            _ => None,
        }
    }

    fn try_lower_builtin_call(
        &mut self,
        block: MirBlockId,
        name: &str,
        args: &[HirCallArg],
    ) -> Option<(MirBlockId, Option<MirValueId>)> {
        match name {
            "$as" => {
                if args.len() != 2 {
                    return Some((block, None));
                }
                let (arg_end, value) = self.lower_expr(block, &args[1].value);
                Some((arg_end, value))
            }
            "$sizeof" | "$alignof" | "$offsetof" => {
                let expected = if name == "$offsetof" { 2 } else { 1 };
                if args.len() != expected {
                    return Some((block, None));
                }
                let empty_locals = BTreeMap::new();
                let type_name = self
                    .eval_type_designator_name(&args[0].value, &empty_locals)
                    .unwrap_or_else(|| "unknown".to_string());
                let (size, align) = layout_for_builtin_type_name(&type_name);
                let raw = if name == "$sizeof" {
                    size
                } else if name == "$alignof" {
                    align
                } else {
                    builtin_offsetof_for_type_name(&type_name, &args[1].value).unwrap_or(0)
                };
                let value = self.push_eval(
                    block,
                    MirValue::Literal(HirLiteral::Integer(raw.to_string())),
                    MirValueType::Int {
                        signed: false,
                        bits: 64,
                    },
                );
                Some((block, Some(value)))
            }
            "$unreachable" => {
                self.set_terminator(block, MirTerminator::Unreachable);
                Some((block, None))
            }
            "$panic" => {
                if args.len() != 1 {
                    self.set_terminator(block, MirTerminator::Unreachable);
                    return Some((block, None));
                }
                let (arg_end, _) = self.lower_expr(block, &args[0].value);
                self.set_terminator(arg_end, MirTerminator::Unreachable);
                Some((arg_end, None))
            }
            "$Self" => {
                if !args.is_empty() {
                    return Some((block, None));
                }
                let self_name = self
                    .current_param_type_hints
                    .first()
                    .and_then(|hint| hint.as_ref())
                    .map(|hint| self_type_literal_from_param_hint(hint))
                    .unwrap_or_else(|| "unknown".to_string());
                let value =
                    self.push_eval(block, MirValue::TypeLiteral(self_name), MirValueType::Type);
                Some((block, Some(value)))
            }
            "$typeof" => {
                if args.len() != 1 {
                    return Some((block, None));
                }
                let (arg_end, arg_value) = self.lower_expr(block, &args[0].value);
                let Some(arg_value) = arg_value else {
                    return Some((arg_end, None));
                };
                let ty_name = match self
                    .value_types
                    .get(&arg_value)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown)
                {
                    MirValueType::Bool => "u1".to_string(),
                    MirValueType::Int { signed: true, bits } => format!("i{bits}"),
                    MirValueType::Int {
                        signed: false,
                        bits,
                    } => format!("u{bits}"),
                    MirValueType::Float { bits } => format!("f{bits}"),
                    MirValueType::Type => "type".to_string(),
                    MirValueType::Function => "fn".to_string(),
                    MirValueType::Unknown => "unknown".to_string(),
                };
                let value =
                    self.push_eval(arg_end, MirValue::TypeLiteral(ty_name), MirValueType::Type);
                Some((arg_end, Some(value)))
            }
            _ => None,
        }
    }

    fn try_eval_comptime_expr(&self, expr: &HirExpr, depth: usize) -> Option<ComptimeValue> {
        let mut locals = BTreeMap::new();
        self.try_eval_comptime_expr_with_locals(expr, depth, &mut locals)
    }

    fn try_eval_comptime_expr_with_locals(
        &self,
        expr: &HirExpr,
        depth: usize,
        locals: &mut BTreeMap<String, ComptimeValue>,
    ) -> Option<ComptimeValue> {
        if depth > 64 {
            return None;
        }
        match &expr.kind {
            HirExprKind::Literal(lit) => Some(ComptimeValue::Literal(lit.clone())),
            HirExprKind::TypeLiteral(name) => {
                Some(ComptimeValue::Type(substitute_type_locals(name, locals)))
            }
            HirExprKind::Ident(name) => {
                if let Some(value) = locals.get(name).cloned() {
                    return Some(value);
                }
                if let Some(type_name) =
                    type_literal_name_for_ident(name, &self.named_type_literals)
                {
                    return Some(ComptimeValue::Type(type_name));
                }
                if let Some(target) = self.function_exprs.get(name) {
                    if matches!(&target.kind, HirExprKind::Function { .. }) {
                        return Some(ComptimeValue::Function(name.clone()));
                    }
                    return self.try_eval_comptime_expr_with_locals(
                        target,
                        depth + 1,
                        &mut locals.clone(),
                    );
                }
                None
            }
            HirExprKind::Comptime { expr } | HirExprKind::Inline { expr } => {
                self.try_eval_comptime_expr_with_locals(expr, depth + 1, locals)
            }
            HirExprKind::Unary { op, expr } => {
                let value = self.try_eval_comptime_expr_with_locals(expr, depth + 1, locals)?;
                match (op, value) {
                    (UnaryOp::Neg, ComptimeValue::Literal(HirLiteral::Integer(v))) => {
                        let parsed = parse_i64_literal(&v)?;
                        Some(ComptimeValue::Literal(HirLiteral::Integer(
                            (-parsed).to_string(),
                        )))
                    }
                    (UnaryOp::Not, ComptimeValue::Literal(HirLiteral::Bool(v))) => {
                        Some(ComptimeValue::Literal(HirLiteral::Bool(!v)))
                    }
                    (UnaryOp::BitNot, ComptimeValue::Literal(HirLiteral::Integer(v))) => {
                        let parsed = parse_i64_literal(&v)?;
                        Some(ComptimeValue::Literal(HirLiteral::Integer(
                            (!parsed).to_string(),
                        )))
                    }
                    _ => None,
                }
            }
            HirExprKind::Binary { op, left, right } => {
                let left = self.try_eval_comptime_expr_with_locals(left, depth + 1, locals)?;
                let right = self.try_eval_comptime_expr_with_locals(right, depth + 1, locals)?;
                eval_comptime_binary(*op, left, right)
            }
            HirExprKind::Let { name, value, .. } => {
                let value = self.try_eval_comptime_expr_with_locals(value, depth + 1, locals)?;
                locals.insert(name.clone(), value.clone());
                Some(value)
            }
            HirExprKind::Assign { target, value, .. } => {
                let HirExprKind::Ident(name) = &target.kind else {
                    return None;
                };
                let value = self.try_eval_comptime_expr_with_locals(value, depth + 1, locals)?;
                locals.insert(name.clone(), value.clone());
                Some(value)
            }
            HirExprKind::Block { body } => {
                let mut scope = locals.clone();
                let mut last = None;
                for value in body {
                    if let HirExprKind::Return { value } = &value.kind {
                        if let Some(value) = value {
                            return self.try_eval_comptime_expr_with_locals(
                                value,
                                depth + 1,
                                &mut scope,
                            );
                        }
                        return None;
                    }
                    last = self.try_eval_comptime_expr_with_locals(value, depth + 1, &mut scope);
                }
                last
            }
            HirExprKind::If {
                condition,
                capture,
                then_branch,
                else_branch,
            } => {
                let condition_value =
                    self.try_eval_comptime_expr_with_locals(condition, depth + 1, locals)?;
                if comptime_truthy(&condition_value) {
                    let mut scope = locals.clone();
                    if let Some(capture) = capture {
                        if let Some(binding) = &capture.binding {
                            if binding != "_" {
                                scope.insert(binding.clone(), condition_value.clone());
                            }
                        }
                    }
                    self.try_eval_comptime_expr_with_locals(then_branch, depth + 1, &mut scope)
                } else if let Some(else_branch) = else_branch {
                    let mut scope = locals.clone();
                    self.try_eval_comptime_expr_with_locals(else_branch, depth + 1, &mut scope)
                } else {
                    None
                }
            }
            HirExprKind::Return { value } => value.as_ref().and_then(|value| {
                self.try_eval_comptime_expr_with_locals(value, depth + 1, locals)
            }),
            HirExprKind::Call { callee, args } => {
                let HirExprKind::Ident(name) = &callee.kind else {
                    return None;
                };
                match name.as_str() {
                    "$sizeof" | "$alignof" => {
                        if args.len() != 1 {
                            return None;
                        }
                        let type_name = self.comptime_type_name_from_expr_with_locals(
                            &args[0].value,
                            depth + 1,
                            locals,
                        )?;
                        let (size, align) = layout_for_builtin_type_name(&type_name);
                        let out = if name == "$sizeof" { size } else { align };
                        Some(ComptimeValue::Literal(HirLiteral::Integer(out.to_string())))
                    }
                    "$offsetof" => {
                        if args.len() != 2 {
                            return None;
                        }
                        let type_name = self.comptime_type_name_from_expr_with_locals(
                            &args[0].value,
                            depth + 1,
                            locals,
                        )?;
                        let off = builtin_offsetof_for_type_name(&type_name, &args[1].value)?;
                        Some(ComptimeValue::Literal(HirLiteral::Integer(off.to_string())))
                    }
                    "$typeof" => {
                        if args.len() != 1 {
                            return None;
                        }
                        let inner = self.try_eval_comptime_expr_with_locals(
                            &args[0].value,
                            depth + 1,
                            locals,
                        )?;
                        let ty_name = match inner {
                            ComptimeValue::Literal(HirLiteral::Integer(_)) => "i32".to_string(),
                            ComptimeValue::Literal(HirLiteral::Float(_)) => "f64".to_string(),
                            ComptimeValue::Literal(HirLiteral::Bool(_)) => "u1".to_string(),
                            ComptimeValue::Literal(HirLiteral::Char(_)) => "u8".to_string(),
                            ComptimeValue::Literal(HirLiteral::String(_)) => "bytes".to_string(),
                            ComptimeValue::Literal(HirLiteral::Null) => "unknown".to_string(),
                            ComptimeValue::Type(_) => "type".to_string(),
                            ComptimeValue::Function(_) => "fn".to_string(),
                        };
                        Some(ComptimeValue::Type(ty_name))
                    }
                    "$as" => {
                        if args.len() != 2 {
                            return None;
                        }
                        let target = self.comptime_type_name_from_expr_with_locals(
                            &args[0].value,
                            depth + 1,
                            locals,
                        )?;
                        let value = self.try_eval_comptime_expr_with_locals(
                            &args[1].value,
                            depth + 1,
                            locals,
                        )?;
                        eval_comptime_cast(&target, value)
                    }
                    "$Self" => {
                        if !args.is_empty() {
                            return None;
                        }
                        let self_name = self
                            .current_param_type_hints
                            .first()
                            .and_then(|hint| hint.as_ref())
                            .map(|hint| self_type_literal_from_param_hint(hint))
                            .unwrap_or_else(|| "unknown".to_string());
                        Some(ComptimeValue::Type(self_name))
                    }
                    _ => self.try_eval_named_comptime_call(name, args, depth + 1, locals),
                }
            }
            _ => None,
        }
    }

    fn try_eval_named_comptime_call(
        &self,
        name: &str,
        args: &[HirCallArg],
        depth: usize,
        caller_locals: &mut BTreeMap<String, ComptimeValue>,
    ) -> Option<ComptimeValue> {
        let resolved_name =
            if let Some(ComptimeValue::Function(function_name)) = caller_locals.get(name) {
                function_name.clone()
            } else {
                name.to_string()
            };
        let target = self.function_exprs.get(&resolved_name)?;
        match &target.kind {
            HirExprKind::Function {
                params,
                param_defaults,
                body,
                ..
            } => {
                if args.len() > params.len() {
                    return None;
                }

                let mut ordered = vec![None; params.len()];
                for arg in args {
                    if let Some(name) = &arg.name {
                        let index = params.iter().position(|param| param == name)?;
                        if ordered[index].is_some() {
                            return None;
                        }
                        ordered[index] = Some(&arg.value);
                    }
                }
                let mut positional = args.iter().filter(|arg| arg.name.is_none());
                for slot in &mut ordered {
                    if slot.is_none() {
                        *slot = positional.next().map(|arg| &arg.value);
                    }
                }

                let mut locals = BTreeMap::new();
                for (idx, param_name) in params.iter().enumerate() {
                    let value = if let Some(expr) = ordered[idx] {
                        self.try_eval_comptime_expr_with_locals(expr, depth + 1, caller_locals)?
                    } else if let Some(Some(default_expr)) = param_defaults.get(idx) {
                        self.try_eval_comptime_expr_with_locals(
                            default_expr,
                            depth + 1,
                            &mut locals,
                        )?
                    } else {
                        return None;
                    };
                    locals.insert(param_name.clone(), value);
                }

                self.try_eval_comptime_expr_with_locals(body, depth + 1, &mut locals)
            }
            _ => {
                if !args.is_empty() {
                    return None;
                }
                let mut locals = BTreeMap::new();
                self.try_eval_comptime_expr_with_locals(target, depth + 1, &mut locals)
            }
        }
    }

    fn comptime_type_name_from_expr_with_locals(
        &self,
        expr: &HirExpr,
        depth: usize,
        locals: &BTreeMap<String, ComptimeValue>,
    ) -> Option<String> {
        match &expr.kind {
            HirExprKind::TypeLiteral(name) => Some(substitute_type_locals(name, locals)),
            HirExprKind::Ident(name) => {
                if let Some(ComptimeValue::Type(type_name)) = locals.get(name) {
                    return Some(type_name.clone());
                }
                if let Some(resolved) = type_literal_name_for_ident(name, &self.named_type_literals)
                {
                    return Some(resolved);
                }
                if let Some(target) = self.function_exprs.get(name) {
                    if let Some(ComptimeValue::Type(type_name)) = self
                        .try_eval_comptime_expr_with_locals(target, depth + 1, &mut locals.clone())
                    {
                        return Some(type_name);
                    }
                }
                Some(name.clone())
            }
            _ => self
                .try_eval_comptime_expr_with_locals(expr, depth + 1, &mut locals.clone())
                .and_then(|value| match value {
                    ComptimeValue::Type(name) => Some(name),
                    ComptimeValue::Function(_) | ComptimeValue::Literal(_) => None,
                }),
        }
    }

    fn top_level_import_path(&self, name: &str) -> Option<&str> {
        self.function_exprs.get(name).and_then(|expr| {
            if let HirExprKind::Use { path } = &expr.kind {
                Some(path.as_str())
            } else {
                None
            }
        })
    }

    fn resolve_import_member_ident(&self, import_path: &str, field: &str) -> Option<String> {
        let target_key = import_path_to_module_key(&self.module_key, import_path);
        let target_module_id = self.module_ids_by_key.get(&target_key).copied()?;
        let exports = self.module_exports_by_id.get(&target_module_id)?;
        if exports.iter().any(|name| name == field) {
            Some(qualified_function_name(target_module_id, field))
        } else {
            None
        }
    }

    fn infer_call_result_type(&self, callee: MirValueId, depth: usize) -> MirValueType {
        if depth > 8 {
            return MirValueType::Unknown;
        }
        if let Some(name) = self.resolve_callee_function_name(callee, depth) {
            return self
                .function_return_types
                .get(&name)
                .cloned()
                .unwrap_or(MirValueType::Unknown);
        }
        match self.value_defs.get(&callee) {
            Some(MirValue::Param { index }) => {
                if let Some(Some(hint)) = self.current_param_type_hints.get(*index) {
                    if let Some(ret) = parse_function_return_hint(hint) {
                        return ret;
                    }
                }
                self.value_types
                    .get(&callee)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown)
            }
            _ => MirValueType::Unknown,
        }
    }

    fn resolve_callee_function_name(&self, value: MirValueId, depth: usize) -> Option<String> {
        if depth > 8 {
            return None;
        }
        match self.value_defs.get(&value) {
            Some(MirValue::Ident(name)) => Some(name.clone()),
            Some(MirValue::LocalSet { value, .. }) | Some(MirValue::Assign { value, .. }) => {
                self.resolve_callee_function_name(*value, depth + 1)
            }
            _ => None,
        }
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

fn substitute_type_locals(type_name: &str, locals: &BTreeMap<String, ComptimeValue>) -> String {
    let mut out = String::with_capacity(type_name.len());
    let mut iter = type_name.char_indices().peekable();
    while let Some((start, ch)) = iter.next() {
        if is_type_ident_start(ch) {
            let mut end = start + ch.len_utf8();
            while let Some((idx, next)) = iter.peek().copied() {
                if is_type_ident_continue(next) {
                    end = idx + next.len_utf8();
                    let _ = iter.next();
                } else {
                    break;
                }
            }
            let ident = &type_name[start..end];
            if let Some(ComptimeValue::Type(replacement)) = locals.get(ident) {
                out.push_str(replacement);
            } else {
                out.push_str(ident);
            }
        } else {
            out.push(ch);
        }
    }
    out
}

fn is_type_ident_start(ch: char) -> bool {
    ch == '_' || ch.is_ascii_alphabetic()
}

fn is_type_ident_continue(ch: char) -> bool {
    ch == '_' || ch.is_ascii_alphanumeric()
}

fn layout_for_builtin_type_name(name: &str) -> (u64, u64) {
    let name = name.trim();
    if let Some(fields) = parse_struct_fields(name) {
        return layout_for_struct_fields(&fields);
    }
    match name {
        "bool" | "u1" | "i8" | "u8" => (1, 1),
        "i16" | "u16" => (2, 2),
        "i32" | "u32" | "f32" => (4, 4),
        "i64" | "u64" | "isize" | "usize" | "f64" | "type" => (8, 8),
        "opaque" | "any" => (8, 8),
        n if n.starts_with('*') => (8, 8),
        n if n.starts_with("[]") => (16, 8),
        _ => (8, 8),
    }
}

#[cfg(test)]
fn builtin_offsetof_value(
    type_arg: &HirExpr,
    field_arg: &HirExpr,
    named_type_literals: &BTreeMap<String, String>,
) -> Option<u64> {
    let type_name = match &type_arg.kind {
        HirExprKind::TypeLiteral(name) | HirExprKind::Ident(name) => name.as_str(),
        _ => return None,
    };
    let resolved = named_type_literals
        .get(type_name)
        .map(String::as_str)
        .unwrap_or(type_name);
    builtin_offsetof_for_type_name(resolved.trim(), field_arg)
}

fn builtin_offsetof_for_type_name(type_name: &str, field_arg: &HirExpr) -> Option<u64> {
    let fields = parse_struct_fields(type_name)?;
    let offsets = struct_field_offsets(&fields);
    match &field_arg.kind {
        HirExprKind::Ident(field) => offsets
            .iter()
            .find(|(name, _)| name == field)
            .map(|(_, o)| *o),
        HirExprKind::Literal(HirLiteral::Integer(index)) => {
            let idx = index.parse::<usize>().ok()?;
            offsets.get(idx).map(|(_, offset)| *offset)
        }
        _ => None,
    }
}

fn parse_struct_fields(type_name: &str) -> Option<Vec<(String, String)>> {
    if !type_name.starts_with("struct{") || !type_name.ends_with('}') {
        return None;
    }
    let inner = &type_name[7..type_name.len() - 1];
    if inner.trim().is_empty() {
        return Some(Vec::new());
    }
    let mut fields = Vec::new();
    for part in split_top_level(inner, ',') {
        let mut pieces = part.splitn(2, ':');
        let name = pieces.next()?.trim();
        let ty = pieces.next()?.trim();
        if name.is_empty() || ty.is_empty() {
            return None;
        }
        fields.push((name.to_string(), ty.to_string()));
    }
    Some(fields)
}

fn split_top_level(input: &str, sep: char) -> Vec<String> {
    let mut out = Vec::new();
    let mut depth_paren = 0i32;
    let mut depth_brace = 0i32;
    let mut depth_bracket = 0i32;
    let mut start = 0usize;
    for (idx, ch) in input.char_indices() {
        match ch {
            '(' => depth_paren += 1,
            ')' => depth_paren -= 1,
            '{' => depth_brace += 1,
            '}' => depth_brace -= 1,
            '[' => depth_bracket += 1,
            ']' => depth_bracket -= 1,
            _ => {}
        }
        if ch == sep && depth_paren == 0 && depth_brace == 0 && depth_bracket == 0 {
            out.push(input[start..idx].trim().to_string());
            start = idx + ch.len_utf8();
        }
    }
    out.push(input[start..].trim().to_string());
    out
}

fn layout_for_struct_fields(fields: &[(String, String)]) -> (u64, u64) {
    let mut size = 0u64;
    let mut max_align = 1u64;
    for (_, ty_name) in fields {
        let (field_size, field_align) = layout_for_builtin_type_name(ty_name);
        max_align = max_align.max(field_align);
        size = align_to_u64(size, field_align);
        size += field_size;
    }
    (align_to_u64(size, max_align), max_align)
}

fn struct_field_offsets(fields: &[(String, String)]) -> Vec<(String, u64)> {
    let mut offsets = Vec::with_capacity(fields.len());
    let mut size = 0u64;
    for (name, ty_name) in fields {
        let (field_size, field_align) = layout_for_builtin_type_name(ty_name);
        size = align_to_u64(size, field_align);
        offsets.push((name.clone(), size));
        size += field_size;
    }
    offsets
}

fn align_to_u64(value: u64, align: u64) -> u64 {
    if align <= 1 {
        return value;
    }
    let mask = align - 1;
    if value & mask == 0 {
        value
    } else {
        (value + mask) & !mask
    }
}

fn parse_i64_literal(text: &str) -> Option<i64> {
    text.replace('_', "").parse::<i64>().ok()
}

fn comptime_truthy(value: &ComptimeValue) -> bool {
    match value {
        ComptimeValue::Literal(HirLiteral::Bool(v)) => *v,
        ComptimeValue::Literal(HirLiteral::Null) => false,
        ComptimeValue::Literal(HirLiteral::Integer(v)) => {
            parse_i64_literal(v).map(|n| n != 0).unwrap_or(false)
        }
        ComptimeValue::Literal(HirLiteral::Float(v)) => v
            .replace('_', "")
            .parse::<f64>()
            .map(|n| n != 0.0)
            .unwrap_or(false),
        ComptimeValue::Literal(HirLiteral::Char(v)) => *v != '\0',
        ComptimeValue::Literal(HirLiteral::String(v)) => !v.is_empty(),
        ComptimeValue::Type(_) | ComptimeValue::Function(_) => true,
    }
}

fn eval_comptime_binary(
    op: BinaryOp,
    left: ComptimeValue,
    right: ComptimeValue,
) -> Option<ComptimeValue> {
    match (left, right) {
        (
            ComptimeValue::Literal(HirLiteral::Integer(l)),
            ComptimeValue::Literal(HirLiteral::Integer(r)),
        ) => {
            let l = parse_i64_literal(&l)?;
            let r = parse_i64_literal(&r)?;
            let out = match op {
                BinaryOp::Add => ComptimeValue::Literal(HirLiteral::Integer((l + r).to_string())),
                BinaryOp::Sub => ComptimeValue::Literal(HirLiteral::Integer((l - r).to_string())),
                BinaryOp::Mul => ComptimeValue::Literal(HirLiteral::Integer((l * r).to_string())),
                BinaryOp::Div => {
                    if r == 0 {
                        return None;
                    }
                    ComptimeValue::Literal(HirLiteral::Integer((l / r).to_string()))
                }
                BinaryOp::Mod => {
                    if r == 0 {
                        return None;
                    }
                    ComptimeValue::Literal(HirLiteral::Integer((l % r).to_string()))
                }
                BinaryOp::Eq => ComptimeValue::Literal(HirLiteral::Bool(l == r)),
                BinaryOp::Ne => ComptimeValue::Literal(HirLiteral::Bool(l != r)),
                BinaryOp::Lt => ComptimeValue::Literal(HirLiteral::Bool(l < r)),
                BinaryOp::Le => ComptimeValue::Literal(HirLiteral::Bool(l <= r)),
                BinaryOp::Gt => ComptimeValue::Literal(HirLiteral::Bool(l > r)),
                BinaryOp::Ge => ComptimeValue::Literal(HirLiteral::Bool(l >= r)),
                BinaryOp::BitAnd => {
                    ComptimeValue::Literal(HirLiteral::Integer((l & r).to_string()))
                }
                BinaryOp::BitOr => ComptimeValue::Literal(HirLiteral::Integer((l | r).to_string())),
                BinaryOp::BitXor => {
                    ComptimeValue::Literal(HirLiteral::Integer((l ^ r).to_string()))
                }
                BinaryOp::Shl => {
                    if r < 0 {
                        return None;
                    }
                    ComptimeValue::Literal(HirLiteral::Integer((l << (r as u32)).to_string()))
                }
                BinaryOp::Shr => {
                    if r < 0 {
                        return None;
                    }
                    ComptimeValue::Literal(HirLiteral::Integer((l >> (r as u32)).to_string()))
                }
                _ => return None,
            };
            Some(out)
        }
        (
            ComptimeValue::Literal(HirLiteral::Bool(l)),
            ComptimeValue::Literal(HirLiteral::Bool(r)),
        ) => {
            let out = match op {
                BinaryOp::LogicalAnd => ComptimeValue::Literal(HirLiteral::Bool(l && r)),
                BinaryOp::LogicalOr => ComptimeValue::Literal(HirLiteral::Bool(l || r)),
                BinaryOp::Eq => ComptimeValue::Literal(HirLiteral::Bool(l == r)),
                BinaryOp::Ne => ComptimeValue::Literal(HirLiteral::Bool(l != r)),
                _ => return None,
            };
            Some(out)
        }
        (ComptimeValue::Type(l), ComptimeValue::Type(r)) => {
            let out = match op {
                BinaryOp::Eq => ComptimeValue::Literal(HirLiteral::Bool(l == r)),
                BinaryOp::Ne => ComptimeValue::Literal(HirLiteral::Bool(l != r)),
                _ => return None,
            };
            Some(out)
        }
        (ComptimeValue::Function(l), ComptimeValue::Function(r)) => {
            let out = match op {
                BinaryOp::Eq => ComptimeValue::Literal(HirLiteral::Bool(l == r)),
                BinaryOp::Ne => ComptimeValue::Literal(HirLiteral::Bool(l != r)),
                _ => return None,
            };
            Some(out)
        }
        _ => None,
    }
}

fn eval_comptime_cast(target: &str, value: ComptimeValue) -> Option<ComptimeValue> {
    match (target, value) {
        ("i32" | "i64" | "isize", ComptimeValue::Literal(HirLiteral::Integer(v))) => Some(
            ComptimeValue::Literal(HirLiteral::Integer(parse_i64_literal(&v)?.to_string())),
        ),
        ("u32" | "u64" | "usize", ComptimeValue::Literal(HirLiteral::Integer(v))) => {
            let parsed = parse_i64_literal(&v)?;
            Some(ComptimeValue::Literal(HirLiteral::Integer(
                (parsed as u64).to_string(),
            )))
        }
        ("u1" | "bool", ComptimeValue::Literal(HirLiteral::Bool(v))) => {
            Some(ComptimeValue::Literal(HirLiteral::Bool(v)))
        }
        (_, other) => Some(other),
    }
}

fn literal_type(literal: &HirLiteral) -> MirValueType {
    match literal {
        HirLiteral::Integer(_) => MirValueType::Int {
            signed: true,
            bits: 32,
        },
        HirLiteral::Float(_) => MirValueType::Float { bits: 64 },
        HirLiteral::Bool(_) => MirValueType::Bool,
        HirLiteral::Char(_) => MirValueType::Int {
            signed: false,
            bits: 8,
        },
        HirLiteral::String(_) | HirLiteral::Null => MirValueType::Int {
            signed: false,
            bits: 64,
        },
    }
}

fn parse_type_hint(text: &str) -> MirValueType {
    let trimmed = text.trim();
    if trimmed.starts_with("fn/") || trimmed.starts_with("fn(") {
        return MirValueType::Function;
    }
    match trimmed {
        "bool" | "u1" => return MirValueType::Bool,
        "type" => return MirValueType::Type,
        "isize" => {
            return MirValueType::Int {
                signed: true,
                bits: 64,
            };
        }
        "usize" | "bytes" | "opaque" => {
            return MirValueType::Int {
                signed: false,
                bits: 64,
            };
        }
        _ => {}
    }

    if let Some(rest) = trimmed.strip_prefix('i') {
        if let Ok(bits) = rest.parse::<u16>() {
            return MirValueType::Int { signed: true, bits };
        }
    }
    if let Some(rest) = trimmed.strip_prefix('u') {
        if let Ok(bits) = rest.parse::<u16>() {
            return MirValueType::Int {
                signed: false,
                bits,
            };
        }
    }
    if let Some(rest) = trimmed.strip_prefix('f') {
        if let Ok(bits) = rest.parse::<u16>() {
            return MirValueType::Float { bits };
        }
    }

    MirValueType::Unknown
}

fn parse_function_return_hint(text: &str) -> Option<MirValueType> {
    let trimmed = text.trim();
    let arrow = trimmed.rfind("->")?;
    let ret = &trimmed[arrow + 2..];
    let parsed = parse_type_hint(ret.trim());
    if matches!(parsed, MirValueType::Unknown) {
        None
    } else {
        Some(parsed)
    }
}

fn self_type_literal_from_param_hint(text: &str) -> String {
    let mut hint = text.trim();
    if let Some(stripped) = hint.strip_prefix("*mut ") {
        hint = stripped.trim();
    } else if let Some(stripped) = hint.strip_prefix('*') {
        hint = stripped.trim();
    }
    hint.to_string()
}

fn type_literal_name_for_ident(
    name: &str,
    named_type_literals: &BTreeMap<String, String>,
) -> Option<String> {
    if let Some(lit) = named_type_literals.get(name) {
        return Some(lit.clone());
    }
    if parse_type_hint(name) != MirValueType::Unknown
        || matches!(name, "type" | "bytes" | "opaque" | "any")
    {
        return Some(name.to_string());
    }
    None
}

fn merge_types(left: &MirValueType, right: &MirValueType) -> MirValueType {
    if left == right {
        return left.clone();
    }
    match (left, right) {
        (MirValueType::Unknown, other) | (other, MirValueType::Unknown) => other.clone(),
        (
            MirValueType::Int {
                signed: ls,
                bits: lb,
            },
            MirValueType::Int {
                signed: rs,
                bits: rb,
            },
        ) => MirValueType::Int {
            signed: *ls || *rs,
            bits: (*lb).max(*rb),
        },
        (MirValueType::Float { bits: lb }, MirValueType::Float { bits: rb }) => {
            MirValueType::Float {
                bits: (*lb).max(*rb),
            }
        }
        _ => MirValueType::Unknown,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::compiler::ast::Visibility;
    use crate::compiler::diagnostics::SourceSpan;
    use crate::compiler::hir::lower::lower_module_units_with_metadata;
    use crate::compiler::hir::{HirItem, HirMatchArm, HirModule, HirPattern};
    use crate::compiler::module_resolver::{ModuleId, ModuleKey};
    use crate::compiler::pipeline::analyze_project;
    use crate::compiler::sema::typeck::infer_binding_type_strings;
    use std::collections::BTreeMap;
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn make_temp_dir() -> PathBuf {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("time should be monotonic")
            .as_nanos();
        let path = std::env::temp_dir().join(format!("dyn_mir_{unique}"));
        fs::create_dir_all(&path).expect("temp directory should be created");
        path
    }

    #[test]
    fn lowers_if_and_return_into_branching_cfg() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nfoo := () i32 { if true { return 1 } else { return 2 } }\n",
        )
        .expect("file should be written");

        let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
        let inferred = infer_binding_type_strings(&units);
        let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
        let mir = lower_hir_to_mir(&hir);
        let function = &mir.modules[0].functions[0];

        assert!(function.blocks.len() >= 3);
        assert!(matches!(
            function.blocks[function.entry.0].terminator,
            Some(MirTerminator::Branch { .. })
        ));
        assert!(function
            .blocks
            .iter()
            .any(|block| matches!(block.terminator, Some(MirTerminator::Return(_)))));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn resolves_imported_module_member_call_to_qualified_function_ident() {
        let root = make_temp_dir();
        fs::write(
            root.join("my_id.dyn"),
            "module my_id\npub f := (v: i32) i32 => v\n",
        )
        .expect("file should be written");
        fs::write(
            root.join("a.dyn"),
            "module main\nid := use \"my_id\"\nmain := () i32 => id.f(12)\n",
        )
        .expect("file should be written");

        let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
        let inferred = infer_binding_type_strings(&units);
        let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
        let mir = lower_hir_to_mir(&hir);

        let imported_module = mir
            .modules
            .iter()
            .find(|module| module.key.module_name == "my_id")
            .expect("imported module should exist");
        let expected_callee = qualified_function_name(imported_module.module_id, "f");

        let main_module = mir
            .modules
            .iter()
            .find(|module| module.key.module_name == "main")
            .expect("main module should exist");
        let main_function = main_module
            .functions
            .iter()
            .find(|function| function.name == "main")
            .expect("main function should exist");

        let value_defs = main_function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .filter_map(|instr| {
                if let MirInstr::Eval { dest, value, .. } = instr {
                    Some((*dest, value.clone()))
                } else {
                    None
                }
            })
            .collect::<BTreeMap<_, _>>();

        let call_callees = main_function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .filter_map(|instr| {
                if let MirInstr::Eval {
                    value: MirValue::Call { callee, .. },
                    ..
                } = instr
                {
                    Some(match value_defs.get(callee) {
                        Some(MirValue::Ident(name)) => name.clone(),
                        Some(other) => format!("{other:?}"),
                        None => "<missing>".to_string(),
                    })
                } else {
                    None
                }
            })
            .collect::<Vec<_>>();

        assert!(
            call_callees.iter().any(|name| name == &expected_callee),
            "expected call callee {expected_callee}, got {call_callees:?}"
        );

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn lowers_match_into_branching_cfg() {
        let span = SourceSpan {
            start_byte: 0,
            end_byte: 0,
            start_line: 1,
            start_col: 1,
            end_line: 1,
            end_col: 1,
        };
        let program = HirProgram {
            modules: vec![HirModule {
                module_id: ModuleId(0),
                key: ModuleKey {
                    directory: PathBuf::from("."),
                    module_name: "main".to_string(),
                },
                items: vec![HirItem {
                    name: "main".to_string(),
                    def_id: None,
                    visibility: Visibility::Private,
                    mutable: false,
                    type_hint: Some("i32".to_string()),
                    inferred_type: Some("i32".to_string()),
                    span,
                    value: HirExpr {
                        span,
                        kind: HirExprKind::Function {
                            params: Vec::new(),
                            param_types: Vec::new(),
                            param_defaults: Vec::new(),
                            body: Box::new(HirExpr {
                                span,
                                kind: HirExprKind::Match {
                                    value: Box::new(HirExpr {
                                        span,
                                        kind: HirExprKind::Literal(HirLiteral::Integer(
                                            "2".to_string(),
                                        )),
                                    }),
                                    arms: vec![
                                        HirMatchArm {
                                            pattern: HirPattern::Literal(HirLiteral::Integer(
                                                "1".to_string(),
                                            )),
                                            guard: None,
                                            value: HirExpr {
                                                span,
                                                kind: HirExprKind::Literal(HirLiteral::Integer(
                                                    "5".to_string(),
                                                )),
                                            },
                                        },
                                        HirMatchArm {
                                            pattern: HirPattern::Literal(HirLiteral::Integer(
                                                "2".to_string(),
                                            )),
                                            guard: None,
                                            value: HirExpr {
                                                span,
                                                kind: HirExprKind::Literal(HirLiteral::Integer(
                                                    "9".to_string(),
                                                )),
                                            },
                                        },
                                        HirMatchArm {
                                            pattern: HirPattern::Wildcard,
                                            guard: None,
                                            value: HirExpr {
                                                span,
                                                kind: HirExprKind::Literal(HirLiteral::Integer(
                                                    "0".to_string(),
                                                )),
                                            },
                                        },
                                    ],
                                },
                            }),
                        },
                    },
                }],
            }],
        };

        let mir = lower_hir_to_mir(&program);
        let function = &mir.modules[0].functions[0];
        assert!(function.blocks.len() >= 5);
        assert!(function
            .blocks
            .iter()
            .any(|block| { matches!(block.terminator, Some(MirTerminator::Branch { .. })) }));
        assert!(function.blocks.iter().any(|block| {
            block
                .instructions
                .iter()
                .any(|instr| matches!(instr, MirInstr::Phi { .. }))
        }));
    }

    #[test]
    fn lowers_typeof_to_type_typed_value() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () type {\n  $typeof(1)\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
        let inferred = infer_binding_type_strings(&units);
        let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
        let mir = lower_hir_to_mir(&hir);
        let function = &mir.modules[0].functions[0];

        assert!(function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .any(|instr| {
                matches!(
                    instr,
                    MirInstr::Eval {
                        value: MirValue::TypeLiteral(name),
                        ty: MirValueType::Type,
                        ..
                    } if name == "i32"
                )
            }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn lowers_typeof_float_to_type_typed_value() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () type {\n  $typeof(1.0)\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
        let inferred = infer_binding_type_strings(&units);
        let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
        let mir = lower_hir_to_mir(&hir);
        let function = &mir.modules[0].functions[0];

        assert!(function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .any(|instr| {
                matches!(
                    instr,
                    MirInstr::Eval {
                        value: MirValue::TypeLiteral(name),
                        ty: MirValueType::Type,
                        ..
                    } if name == "f64"
                )
            }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn lowers_typeof_bool_to_u1_type_typed_value() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () type {\n  $typeof(true)\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
        let inferred = infer_binding_type_strings(&units);
        let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
        let mir = lower_hir_to_mir(&hir);
        let function = &mir.modules[0].functions[0];

        assert!(function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .any(|instr| {
                matches!(
                    instr,
                    MirInstr::Eval {
                        value: MirValue::TypeLiteral(name),
                        ty: MirValueType::Type,
                        ..
                    } if name == "u1"
                )
            }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn folds_simple_comptime_integer_expression() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  comp (2 + 3)\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
        let inferred = infer_binding_type_strings(&units);
        let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
        let mir = lower_hir_to_mir(&hir);
        let function = &mir.modules[0].functions[0];

        assert!(function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .any(|instr| {
                matches!(
                    instr,
                    MirInstr::Eval {
                        value: MirValue::Literal(HirLiteral::Integer(v)),
                        ..
                    } if v == "5"
                )
            }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn folds_comptime_named_zero_arg_function_call_to_literal() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmake := () i32 => 42\nmain := () i32 {\n  return comp make()\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
        let inferred = infer_binding_type_strings(&units);
        let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
        let mir = lower_hir_to_mir(&hir);
        let function = mir.modules[0]
            .functions
            .iter()
            .find(|function| function.name == "main")
            .expect("main function should exist");

        let value_defs = function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .filter_map(|instr| {
                if let MirInstr::Eval { dest, value, .. } = instr {
                    Some((*dest, value.clone()))
                } else {
                    None
                }
            })
            .collect::<BTreeMap<_, _>>();

        assert!(function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .any(|instr| {
                matches!(
                    instr,
                    MirInstr::Eval {
                        value: MirValue::Literal(HirLiteral::Integer(v)),
                        ..
                    } if v == "42"
                )
            }));

        assert!(!function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .any(|instr| {
                matches!(
                    instr,
                    MirInstr::Eval {
                        value: MirValue::Call { callee, .. },
                        ..
                    } if matches!(value_defs.get(callee), Some(MirValue::Ident(name)) if name == "make")
                )
            }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn folds_comptime_function_call_returning_function_symbol() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\ninc := (x: i32) i32 => x + 1\nmake := () fn(i32) i32 => inc\nmain := () i32 {\n  f := comp make()\n  return f(1)\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
        let inferred = infer_binding_type_strings(&units);
        let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
        let mir = lower_hir_to_mir(&hir);
        let function = mir.modules[0]
            .functions
            .iter()
            .find(|function| function.name == "main")
            .expect("main function should exist");

        let value_defs = function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .filter_map(|instr| {
                if let MirInstr::Eval { dest, value, .. } = instr {
                    Some((*dest, value.clone()))
                } else {
                    None
                }
            })
            .collect::<BTreeMap<_, _>>();

        assert!(function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .any(|instr| {
                matches!(
                    instr,
                    MirInstr::Eval {
                        value: MirValue::Ident(name),
                        ty: MirValueType::Function,
                        ..
                    } if name == "inc"
                )
            }));

        assert!(!function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .any(|instr| {
                matches!(
                    instr,
                    MirInstr::Eval {
                        value: MirValue::Call { callee, .. },
                        ..
                    } if matches!(value_defs.get(callee), Some(MirValue::Ident(name)) if name == "make")
                )
            }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn folds_type_returning_constructor_call_without_explicit_comp() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nVec := (T: type) type => struct { items: []T }\nmain := () i32 {\n  t := Vec(i32)\n  return if t == t 1 else 0\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
        let inferred = infer_binding_type_strings(&units);
        let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
        let mir = lower_hir_to_mir(&hir);
        let function = mir.modules[0]
            .functions
            .iter()
            .find(|function| function.name == "main")
            .expect("main function should exist");

        let value_defs = function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .filter_map(|instr| {
                if let MirInstr::Eval { dest, value, .. } = instr {
                    Some((*dest, value.clone()))
                } else {
                    None
                }
            })
            .collect::<BTreeMap<_, _>>();

        assert!(function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .any(|instr| {
                matches!(
                    instr,
                    MirInstr::Eval {
                        value: MirValue::TypeLiteral(name),
                        ty: MirValueType::Type,
                        ..
                    } if name == "struct{items:[]i32}"
                )
            }));

        assert!(!function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .any(|instr| {
                matches!(
                    instr,
                    MirInstr::Eval {
                        value: MirValue::Call { callee, .. },
                        ..
                    } if matches!(value_defs.get(callee), Some(MirValue::Ident(name)) if name == "Vec")
                )
            }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn lowers_typeof_builtin_type_identifier_to_type_kind() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () type {\n  $typeof(i32)\n}\n",
        )
        .expect("file should be written");

        let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
        let inferred = infer_binding_type_strings(&units);
        let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
        let mir = lower_hir_to_mir(&hir);
        let function = &mir.modules[0].functions[0];

        assert!(function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .any(|instr| {
                matches!(
                    instr,
                    MirInstr::Eval {
                        value: MirValue::TypeLiteral(name),
                        ty: MirValueType::Type,
                        ..
                    } if name == "type"
                )
            }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn computes_layout_for_struct_type_literal_name() {
        let (size, align) = layout_for_builtin_type_name("struct{a:u8,b:i32,c:u8}");
        assert_eq!(size, 12);
        assert_eq!(align, 4);
    }

    #[test]
    fn computes_offsetof_for_struct_field_name_and_index() {
        let span = SourceSpan {
            start_byte: 0,
            end_byte: 0,
            start_line: 1,
            start_col: 1,
            end_line: 1,
            end_col: 1,
        };
        let type_arg = HirExpr {
            span,
            kind: HirExprKind::TypeLiteral("struct{a:u8,b:i32,c:u8}".to_string()),
        };
        let by_name = HirExpr {
            span,
            kind: HirExprKind::Ident("b".to_string()),
        };
        let by_index = HirExpr {
            span,
            kind: HirExprKind::Literal(HirLiteral::Integer("1".to_string())),
        };
        let named = BTreeMap::new();
        assert_eq!(builtin_offsetof_value(&type_arg, &by_name, &named), Some(4));
        assert_eq!(
            builtin_offsetof_value(&type_arg, &by_index, &named),
            Some(4)
        );
    }

    #[test]
    fn lowers_or_else_into_branch_and_phi() {
        let span = SourceSpan {
            start_byte: 0,
            end_byte: 0,
            start_line: 1,
            start_col: 1,
            end_line: 1,
            end_col: 1,
        };
        let program = HirProgram {
            modules: vec![HirModule {
                module_id: ModuleId(0),
                key: ModuleKey {
                    directory: PathBuf::from("."),
                    module_name: "main".to_string(),
                },
                items: vec![HirItem {
                    name: "main".to_string(),
                    def_id: None,
                    visibility: Visibility::Private,
                    mutable: false,
                    type_hint: Some("i32".to_string()),
                    inferred_type: Some("i32".to_string()),
                    span,
                    value: HirExpr {
                        span,
                        kind: HirExprKind::Function {
                            params: Vec::new(),
                            param_types: Vec::new(),
                            param_defaults: Vec::new(),
                            body: Box::new(HirExpr {
                                span,
                                kind: HirExprKind::OrElse {
                                    value: Box::new(HirExpr {
                                        span,
                                        kind: HirExprKind::Literal(HirLiteral::Integer(
                                            "0".to_string(),
                                        )),
                                    }),
                                    error_binding: None,
                                    fallback: Box::new(HirExpr {
                                        span,
                                        kind: HirExprKind::Literal(HirLiteral::Integer(
                                            "7".to_string(),
                                        )),
                                    }),
                                },
                            }),
                        },
                    },
                }],
            }],
        };

        let mir = lower_hir_to_mir(&program);
        let function = &mir.modules[0].functions[0];
        assert!(function
            .blocks
            .iter()
            .any(|block| matches!(block.terminator, Some(MirTerminator::Branch { .. }))));
        assert!(function.blocks.iter().any(|block| {
            block
                .instructions
                .iter()
                .any(|instr| matches!(instr, MirInstr::Phi { .. }))
        }));
    }

    #[test]
    fn lowers_or_else_fallback_break_value_into_phi_source() {
        let span = SourceSpan {
            start_byte: 0,
            end_byte: 0,
            start_line: 1,
            start_col: 1,
            end_line: 1,
            end_col: 1,
        };
        let program = HirProgram {
            modules: vec![HirModule {
                module_id: ModuleId(0),
                key: ModuleKey {
                    directory: PathBuf::from("."),
                    module_name: "main".to_string(),
                },
                items: vec![HirItem {
                    name: "main".to_string(),
                    def_id: None,
                    visibility: Visibility::Private,
                    mutable: false,
                    type_hint: Some("i32".to_string()),
                    inferred_type: Some("i32".to_string()),
                    span,
                    value: HirExpr {
                        span,
                        kind: HirExprKind::Function {
                            params: Vec::new(),
                            param_types: Vec::new(),
                            param_defaults: Vec::new(),
                            body: Box::new(HirExpr {
                                span,
                                kind: HirExprKind::OrElse {
                                    value: Box::new(HirExpr {
                                        span,
                                        kind: HirExprKind::Literal(HirLiteral::Integer(
                                            "0".to_string(),
                                        )),
                                    }),
                                    error_binding: None,
                                    fallback: Box::new(HirExpr {
                                        span,
                                        kind: HirExprKind::Block {
                                            body: vec![HirExpr {
                                                span,
                                                kind: HirExprKind::Break {
                                                    value: Some(Box::new(HirExpr {
                                                        span,
                                                        kind: HirExprKind::Literal(
                                                            HirLiteral::Integer("7".to_string()),
                                                        ),
                                                    })),
                                                },
                                            }],
                                        },
                                    }),
                                },
                            }),
                        },
                    },
                }],
            }],
        };

        let mir = lower_hir_to_mir(&program);
        let function = &mir.modules[0].functions[0];
        let literal_seven_values = function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .filter_map(|instr| match instr {
                MirInstr::Eval {
                    dest,
                    value: MirValue::Literal(HirLiteral::Integer(v)),
                    ..
                } if v == "7" => Some(*dest),
                _ => None,
            })
            .collect::<Vec<_>>();
        assert!(!literal_seven_values.is_empty());
        assert!(function.blocks.iter().any(|block| {
            block.instructions.iter().any(|instr| {
                matches!(instr, MirInstr::Phi { sources, .. } if sources
                    .iter()
                    .any(|(_, value)| literal_seven_values.contains(value)))
            })
        }));
    }

    #[test]
    fn lowers_defer_before_return() {
        let span = SourceSpan {
            start_byte: 0,
            end_byte: 0,
            start_line: 1,
            start_col: 1,
            end_line: 1,
            end_col: 1,
        };
        let program = HirProgram {
            modules: vec![HirModule {
                module_id: ModuleId(0),
                key: ModuleKey {
                    directory: PathBuf::from("."),
                    module_name: "main".to_string(),
                },
                items: vec![HirItem {
                    name: "main".to_string(),
                    def_id: None,
                    visibility: Visibility::Private,
                    mutable: false,
                    type_hint: Some("i32".to_string()),
                    inferred_type: Some("i32".to_string()),
                    span,
                    value: HirExpr {
                        span,
                        kind: HirExprKind::Function {
                            params: Vec::new(),
                            param_types: Vec::new(),
                            param_defaults: Vec::new(),
                            body: Box::new(HirExpr {
                                span,
                                kind: HirExprKind::Block {
                                    body: vec![
                                        HirExpr {
                                            span,
                                            kind: HirExprKind::Defer {
                                                error_binding: None,
                                                body: Box::new(HirExpr {
                                                    span,
                                                    kind: HirExprKind::Literal(
                                                        HirLiteral::Integer("9".to_string()),
                                                    ),
                                                }),
                                            },
                                        },
                                        HirExpr {
                                            span,
                                            kind: HirExprKind::Return {
                                                value: Some(Box::new(HirExpr {
                                                    span,
                                                    kind: HirExprKind::Literal(
                                                        HirLiteral::Integer("1".to_string()),
                                                    ),
                                                })),
                                            },
                                        },
                                    ],
                                },
                            }),
                        },
                    },
                }],
            }],
        };

        let mir = lower_hir_to_mir(&program);
        let function = &mir.modules[0].functions[0];
        let instr_count = function
            .blocks
            .iter()
            .map(|block| block.instructions.len())
            .sum::<usize>();
        assert!(instr_count >= 3);
        assert!(function
            .blocks
            .iter()
            .any(|block| matches!(block.terminator, Some(MirTerminator::Return(_)))));
    }

    #[test]
    fn lowers_struct_literal_field_access_to_field_value() {
        let span = SourceSpan {
            start_byte: 0,
            end_byte: 0,
            start_line: 1,
            start_col: 1,
            end_line: 1,
            end_col: 1,
        };
        let program = HirProgram {
            modules: vec![HirModule {
                module_id: ModuleId(0),
                key: ModuleKey {
                    directory: PathBuf::from("."),
                    module_name: "main".to_string(),
                },
                items: vec![HirItem {
                    name: "main".to_string(),
                    def_id: None,
                    visibility: Visibility::Private,
                    mutable: false,
                    type_hint: Some("i32".to_string()),
                    inferred_type: Some("i32".to_string()),
                    span,
                    value: HirExpr {
                        span,
                        kind: HirExprKind::Function {
                            params: Vec::new(),
                            param_types: Vec::new(),
                            param_defaults: Vec::new(),
                            body: Box::new(HirExpr {
                                span,
                                kind: HirExprKind::FieldAccess {
                                    base: Box::new(HirExpr {
                                        span,
                                        kind: HirExprKind::StructLiteral {
                                            root_type: None,
                                            fields: vec![
                                                (
                                                    "a".to_string(),
                                                    HirExpr {
                                                        span,
                                                        kind: HirExprKind::Literal(
                                                            HirLiteral::Integer("4".to_string()),
                                                        ),
                                                    },
                                                ),
                                                (
                                                    "b".to_string(),
                                                    HirExpr {
                                                        span,
                                                        kind: HirExprKind::Literal(
                                                            HirLiteral::Integer("9".to_string()),
                                                        ),
                                                    },
                                                ),
                                            ],
                                        },
                                    }),
                                    field: "b".to_string(),
                                },
                            }),
                        },
                    },
                }],
            }],
        };

        let mir = lower_hir_to_mir(&program);
        let function = &mir.modules[0].functions[0];
        assert!(function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .any(|instr| matches!(
                instr,
                MirInstr::Eval {
                    value: MirValue::StructLiteral { .. },
                    ..
                }
            )));
        assert!(function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .any(|instr| matches!(instr, MirInstr::Eval { value: MirValue::Literal(HirLiteral::Integer(v)), .. } if v == "9")));
    }

    #[test]
    fn lowers_struct_literal_index_with_constant_to_value() {
        let span = SourceSpan {
            start_byte: 0,
            end_byte: 0,
            start_line: 1,
            start_col: 1,
            end_line: 1,
            end_col: 1,
        };
        let program = HirProgram {
            modules: vec![HirModule {
                module_id: ModuleId(0),
                key: ModuleKey {
                    directory: PathBuf::from("."),
                    module_name: "main".to_string(),
                },
                items: vec![HirItem {
                    name: "main".to_string(),
                    def_id: None,
                    visibility: Visibility::Private,
                    mutable: false,
                    type_hint: Some("i32".to_string()),
                    inferred_type: Some("i32".to_string()),
                    span,
                    value: HirExpr {
                        span,
                        kind: HirExprKind::Function {
                            params: Vec::new(),
                            param_types: Vec::new(),
                            param_defaults: Vec::new(),
                            body: Box::new(HirExpr {
                                span,
                                kind: HirExprKind::Index {
                                    base: Box::new(HirExpr {
                                        span,
                                        kind: HirExprKind::StructLiteral {
                                            root_type: None,
                                            fields: vec![
                                                (
                                                    "a".to_string(),
                                                    HirExpr {
                                                        span,
                                                        kind: HirExprKind::Literal(
                                                            HirLiteral::Integer("4".to_string()),
                                                        ),
                                                    },
                                                ),
                                                (
                                                    "b".to_string(),
                                                    HirExpr {
                                                        span,
                                                        kind: HirExprKind::Literal(
                                                            HirLiteral::Integer("9".to_string()),
                                                        ),
                                                    },
                                                ),
                                            ],
                                        },
                                    }),
                                    index: Box::new(HirExpr {
                                        span,
                                        kind: HirExprKind::Literal(HirLiteral::Integer(
                                            "1".to_string(),
                                        )),
                                    }),
                                },
                            }),
                        },
                    },
                }],
            }],
        };

        let mir = lower_hir_to_mir(&program);
        let function = &mir.modules[0].functions[0];
        assert!(function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .any(|instr| matches!(instr, MirInstr::Eval { value: MirValue::Literal(HirLiteral::Integer(v)), .. } if v == "9")));
        assert!(!function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .any(|instr| matches!(
                instr,
                MirInstr::Eval {
                    value: MirValue::Index { .. },
                    ..
                }
            )));
    }

    #[test]
    fn lowers_enum_variant_index_with_constant_to_payload_value() {
        let span = SourceSpan {
            start_byte: 0,
            end_byte: 0,
            start_line: 1,
            start_col: 1,
            end_line: 1,
            end_col: 1,
        };
        let program = HirProgram {
            modules: vec![HirModule {
                module_id: ModuleId(0),
                key: ModuleKey {
                    directory: PathBuf::from("."),
                    module_name: "main".to_string(),
                },
                items: vec![HirItem {
                    name: "main".to_string(),
                    def_id: None,
                    visibility: Visibility::Private,
                    mutable: false,
                    type_hint: Some("i32".to_string()),
                    inferred_type: Some("i32".to_string()),
                    span,
                    value: HirExpr {
                        span,
                        kind: HirExprKind::Function {
                            params: Vec::new(),
                            param_types: Vec::new(),
                            param_defaults: Vec::new(),
                            body: Box::new(HirExpr {
                                span,
                                kind: HirExprKind::Index {
                                    base: Box::new(HirExpr {
                                        span,
                                        kind: HirExprKind::EnumVariant {
                                            variant: "Ok".to_string(),
                                            payload: vec![HirExpr {
                                                span,
                                                kind: HirExprKind::Literal(HirLiteral::Integer(
                                                    "9".to_string(),
                                                )),
                                            }],
                                        },
                                    }),
                                    index: Box::new(HirExpr {
                                        span,
                                        kind: HirExprKind::Literal(HirLiteral::Integer(
                                            "1".to_string(),
                                        )),
                                    }),
                                },
                            }),
                        },
                    },
                }],
            }],
        };

        let mir = lower_hir_to_mir(&program);
        let function = &mir.modules[0].functions[0];
        assert!(function
            .blocks
            .iter()
            .flat_map(|block| block.instructions.iter())
            .any(|instr| matches!(instr, MirInstr::Eval { value: MirValue::Literal(HirLiteral::Integer(v)), .. } if v == "9")));
    }

    #[test]
    fn lowers_loop_with_break_value_into_loop_result() {
        let span = SourceSpan {
            start_byte: 0,
            end_byte: 0,
            start_line: 1,
            start_col: 1,
            end_line: 1,
            end_col: 1,
        };
        let program = HirProgram {
            modules: vec![HirModule {
                module_id: ModuleId(0),
                key: ModuleKey {
                    directory: PathBuf::from("."),
                    module_name: "main".to_string(),
                },
                items: vec![HirItem {
                    name: "main".to_string(),
                    def_id: None,
                    visibility: Visibility::Private,
                    mutable: false,
                    type_hint: Some("i32".to_string()),
                    inferred_type: Some("i32".to_string()),
                    span,
                    value: HirExpr {
                        span,
                        kind: HirExprKind::Function {
                            params: Vec::new(),
                            param_types: Vec::new(),
                            param_defaults: Vec::new(),
                            body: Box::new(HirExpr {
                                span,
                                kind: HirExprKind::For(HirForExpr::Infinite {
                                    body: Box::new(HirExpr {
                                        span,
                                        kind: HirExprKind::Break {
                                            value: Some(Box::new(HirExpr {
                                                span,
                                                kind: HirExprKind::Literal(HirLiteral::Integer(
                                                    "7".to_string(),
                                                )),
                                            })),
                                        },
                                    }),
                                }),
                            }),
                        },
                    },
                }],
            }],
        };

        let mir = lower_hir_to_mir(&program);
        let function = &mir.modules[0].functions[0];
        assert!(function
            .blocks
            .iter()
            .any(|block| matches!(block.terminator, Some(MirTerminator::Return(Some(_))))));
    }

    #[test]
    fn infers_pointer_like_mir_types_for_string_and_null_literals() {
        assert_eq!(
            literal_type(&HirLiteral::String("\"hi\"".to_string())),
            MirValueType::Int {
                signed: false,
                bits: 64,
            }
        );
        assert_eq!(
            literal_type(&HirLiteral::Null),
            MirValueType::Int {
                signed: false,
                bits: 64,
            }
        );
    }

    #[test]
    fn parses_bytes_and_opaque_type_hints_as_pointer_sized_ints() {
        assert_eq!(
            parse_type_hint("bytes"),
            MirValueType::Int {
                signed: false,
                bits: 64,
            }
        );
        assert_eq!(
            parse_type_hint("opaque"),
            MirValueType::Int {
                signed: false,
                bits: 64,
            }
        );
    }

    #[test]
    fn parses_nonstandard_int_and_float_type_hints() {
        assert_eq!(
            parse_type_hint("i31"),
            MirValueType::Int {
                signed: true,
                bits: 31,
            }
        );
        assert_eq!(
            parse_type_hint("u7"),
            MirValueType::Int {
                signed: false,
                bits: 7,
            }
        );
        assert_eq!(parse_type_hint("f128"), MirValueType::Float { bits: 128 });
    }
}
