use std::collections::BTreeMap;

use cranelift_codegen::ir::condcodes::IntCC;
use cranelift_codegen::ir::entities::StackSlot;
use cranelift_codegen::ir::stackslot::{StackSlotData, StackSlotKind};
use cranelift_codegen::ir::types::{F128, F32, F64, I128, I16, I32, I64, I8};
use cranelift_codegen::ir::{
    AbiParam, InstBuilder, InstructionData, Opcode, TrapCode, Type, Value, ValueDef,
};
use cranelift_frontend::{FunctionBuilder, FunctionBuilderContext};
use cranelift_module::{FuncId, Linkage, Module};
use cranelift_object::ObjectModule;

use crate::compiler::ast::{BinaryOp, UnaryOp};
use crate::compiler::hir::HirLiteral;
use crate::compiler::intrinsics::{
    runtime_intrinsic_for_symbol, RuntimeAbiType, RuntimeReturnKind, RUNTIME_INTRINSICS,
};
use crate::compiler::mir::{
    MirFunction, MirInstr, MirProgram, MirTerminator, MirValue, MirValueId, MirValueType,
};
use crate::compiler::type_text::parse_enum_type_descriptor;

mod driver;
mod layout;
#[cfg(test)]
mod tests;

pub use self::driver::build_executable;
use self::layout::{build_nominal_aggregate_layouts, parse_aggregate_layout};

struct FunctionSymbols {
    by_key: BTreeMap<(usize, String), FuncId>,
    by_name: BTreeMap<String, FuncId>,
    param_types_by_id: BTreeMap<u32, Vec<Type>>,
    returns_bytes_slice_by_id: BTreeMap<u32, bool>,
    returns_errorable_by_id: BTreeMap<u32, bool>,
    returns_errorable_scalar_payload_ty_by_id: BTreeMap<u32, MirValueType>,
    returns_unknown_nominal_by_id: BTreeMap<u32, bool>,
    returns_aggregate_layout_by_id: BTreeMap<u32, AggregateLayout>,
    nominal_aggregate_layouts: BTreeMap<String, AggregateLayout>,
}

#[derive(Debug, Clone)]
struct AggregateLayout {
    fields: BTreeMap<String, (Type, i32)>,
    aggregate_fields: BTreeMap<String, (i32, Box<AggregateLayout>)>,
    ordered: Vec<(Type, i32)>,
    scalar_leaves: Vec<(Type, i32)>,
    size: u32,
    align: u32,
}

struct RuntimeIntrinsic {
    name: &'static str,
    params: Vec<Type>,
    ret: Type,
}

type PhiSources = BTreeMap<usize, MirValueId>;
type PhiEntry = (MirValueId, PhiSources, MirValueType);
type PhiLayout = BTreeMap<usize, Vec<PhiEntry>>;

fn backend_hint_mir_type(type_hint: Option<&str>) -> MirValueType {
    let normalized = normalized_return_type_hint(type_hint);
    let ty = normalized.as_str();

    if ty == "bool" || ty == "u1" {
        return MirValueType::Bool;
    }
    if ty == "[]u8" {
        return MirValueType::BytesSlice;
    }
    if ty == "type" {
        return MirValueType::Type;
    }
    if ty.starts_with('*') || ty.starts_with("[]") || ty == "opaque" || ty == "any" {
        return MirValueType::Int {
            signed: false,
            bits: 64,
        };
    }
    if ty.starts_with("fn/") {
        return MirValueType::FunctionPointer;
    }
    if let Some(bits) = parse_scalar_enum_repr_bits(ty) {
        return MirValueType::Int {
            signed: false,
            bits,
        };
    }
    if let Some((signed, bits)) = parse_int_type_bits(ty) {
        return MirValueType::Int { signed, bits };
    }
    if let Some(bits) = parse_float_type_bits(ty) {
        return MirValueType::Float { bits };
    }

    MirValueType::Unknown
}

fn effective_param_type(function: &MirFunction, index: usize) -> MirValueType {
    let declared = function
        .param_types
        .get(index)
        .cloned()
        .unwrap_or(MirValueType::Unknown);
    if !matches!(declared, MirValueType::Unknown) {
        return declared;
    }

    let hinted = backend_hint_mir_type(
        function
            .param_type_hints
            .get(index)
            .and_then(|hint| hint.as_deref()),
    );
    if matches!(hinted, MirValueType::Unknown) {
        declared
    } else {
        hinted
    }
}

fn declare_function_symbols(
    mir: &MirProgram,
    module: &mut ObjectModule,
) -> Result<FunctionSymbols, String> {
    let mut by_key = BTreeMap::new();
    let mut by_name = BTreeMap::new();
    let mut param_types_by_id = BTreeMap::new();
    let mut returns_bytes_slice_by_id = BTreeMap::new();
    let mut returns_errorable_by_id = BTreeMap::new();
    let mut returns_errorable_scalar_payload_ty_by_id = BTreeMap::new();
    let mut returns_unknown_nominal_by_id = BTreeMap::new();
    let mut returns_aggregate_layout_by_id = BTreeMap::new();
    let pointer_ty = module.target_config().pointer_type();
    let nominal_aggregate_layouts = build_nominal_aggregate_layouts(mir, pointer_ty);

    for mir_module in &mir.modules {
        for function in &mir_module.functions {
            let mut signature = module.make_signature();
            let ret_scalar = parse_return_scalar(function.return_type.as_deref());
            let mut param_types = Vec::with_capacity(function.param_types.len());
            for idx in 0..function.param_types.len() {
                let param = effective_param_type(function, idx);
                if matches!(param, MirValueType::BytesSlice) {
                    signature.params.push(AbiParam::new(pointer_ty));
                    signature.params.push(AbiParam::new(pointer_ty));
                    param_types.push(pointer_ty);
                    param_types.push(pointer_ty);
                    continue;
                }

                let clif_ty = if matches!(
                    param,
                    MirValueType::Unknown | MirValueType::Function | MirValueType::FunctionPointer
                ) {
                    pointer_ty
                } else {
                    mir_type_to_clif(&param, ret_scalar)
                };
                signature.params.push(AbiParam::new(clif_ty));
                param_types.push(clif_ty);
            }
            let exported = mir_module.key.module_name == "main" && function.name == "main";
            let returns_bytes_slice =
                !exported && returns_bytes_slice_from_hint(function.return_type.as_deref());
            let returns_errorable = returns_errorable_from_hint(function.return_type.as_deref());
            let returns_aggregate_layout = if returns_bytes_slice {
                None
            } else {
                parse_aggregate_layout(
                    function.return_type.as_deref(),
                    &nominal_aggregate_layouts,
                    pointer_ty,
                )
            };
            let returns_unknown_nominal = !returns_errorable
                && !returns_bytes_slice
                && returns_aggregate_layout.is_none()
                && matches!(
                    backend_hint_mir_type(function.return_type.as_deref()),
                    MirValueType::Unknown
                );
            let returns_errorable_scalar = !exported
                && returns_errorable
                && !returns_bytes_slice
                && returns_aggregate_layout.is_none();
            if returns_bytes_slice {
                signature.params.push(AbiParam::new(pointer_ty));
                param_types.push(pointer_ty);
                signature.returns.push(AbiParam::new(pointer_ty));
            } else if returns_aggregate_layout.is_some() {
                signature.params.push(AbiParam::new(pointer_ty));
                param_types.push(pointer_ty);
                signature.returns.push(AbiParam::new(if returns_errorable {
                    ret_scalar.ty()
                } else {
                    pointer_ty
                }));
            } else if returns_errorable_scalar {
                signature.params.push(AbiParam::new(pointer_ty));
                param_types.push(pointer_ty);
                signature.returns.push(AbiParam::new(ret_scalar.ty()));
            } else {
                signature
                    .returns
                    .push(AbiParam::new(if exported { I32 } else { ret_scalar.ty() }));
            }
            let symbol_name = if exported {
                "main".to_string()
            } else {
                format!(
                    "dyn_m{}_{}",
                    mir_module.module_id.0,
                    sanitize_symbol_name(&function.name)
                )
            };

            let func_id = module
                .declare_function(
                    &symbol_name,
                    if exported {
                        Linkage::Export
                    } else {
                        Linkage::Local
                    },
                    &signature,
                )
                .map_err(|err| format!("failed to declare function '{}': {err}", function.name))?;

            by_key.insert((mir_module.module_id.0, function.name.clone()), func_id);
            by_name.insert(
                format!("#{}::{}", mir_module.module_id.0, function.name),
                func_id,
            );
            by_name.entry(function.name.clone()).or_insert(func_id);
            param_types_by_id.insert(func_id.as_u32(), param_types);
            returns_bytes_slice_by_id.insert(func_id.as_u32(), returns_bytes_slice);
            returns_errorable_by_id.insert(func_id.as_u32(), returns_errorable);
            if returns_errorable_scalar {
                returns_errorable_scalar_payload_ty_by_id.insert(
                    func_id.as_u32(),
                    backend_hint_mir_type(function.return_type.as_deref()),
                );
            }
            returns_unknown_nominal_by_id.insert(func_id.as_u32(), returns_unknown_nominal);
            if let Some(layout) = returns_aggregate_layout {
                returns_aggregate_layout_by_id.insert(func_id.as_u32(), layout);
            }
        }

        for extern_fn in &mir_module.extern_functions {
            let mut signature = module.make_signature();
            let ret_scalar = parse_return_scalar(extern_fn.return_type.as_deref());
            let mut param_types = Vec::with_capacity(extern_fn.param_types.len());
            for idx in 0..extern_fn.param_types.len() {
                let declared = extern_fn
                    .param_types
                    .get(idx)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown);
                let param = if matches!(declared, MirValueType::Unknown) {
                    backend_hint_mir_type(
                        extern_fn
                            .param_type_hints
                            .get(idx)
                            .and_then(|hint| hint.as_deref()),
                    )
                } else {
                    declared
                };

                if matches!(param, MirValueType::BytesSlice) {
                    signature.params.push(AbiParam::new(pointer_ty));
                    signature.params.push(AbiParam::new(pointer_ty));
                    param_types.push(pointer_ty);
                    param_types.push(pointer_ty);
                    continue;
                }

                let clif_ty = if matches!(
                    param,
                    MirValueType::Unknown | MirValueType::Function | MirValueType::FunctionPointer
                ) {
                    pointer_ty
                } else {
                    mir_type_to_clif(&param, ret_scalar)
                };
                signature.params.push(AbiParam::new(clif_ty));
                param_types.push(clif_ty);
            }

            let returns_bytes_slice =
                returns_bytes_slice_from_hint(extern_fn.return_type.as_deref());
            let returns_errorable = returns_errorable_from_hint(extern_fn.return_type.as_deref());
            let returns_aggregate_layout = if returns_bytes_slice {
                None
            } else {
                parse_aggregate_layout(
                    extern_fn.return_type.as_deref(),
                    &nominal_aggregate_layouts,
                    pointer_ty,
                )
            };
            let returns_unknown_nominal = !returns_errorable
                && !returns_bytes_slice
                && returns_aggregate_layout.is_none()
                && matches!(
                    backend_hint_mir_type(extern_fn.return_type.as_deref()),
                    MirValueType::Unknown
                );
            let returns_errorable_scalar =
                returns_errorable && !returns_bytes_slice && returns_aggregate_layout.is_none();

            if returns_bytes_slice {
                signature.params.push(AbiParam::new(pointer_ty));
                param_types.push(pointer_ty);
                signature.returns.push(AbiParam::new(pointer_ty));
            } else if returns_aggregate_layout.is_some() {
                signature.params.push(AbiParam::new(pointer_ty));
                param_types.push(pointer_ty);
                signature.returns.push(AbiParam::new(if returns_errorable {
                    ret_scalar.ty()
                } else {
                    pointer_ty
                }));
            } else if returns_errorable_scalar {
                signature.params.push(AbiParam::new(pointer_ty));
                param_types.push(pointer_ty);
                signature.returns.push(AbiParam::new(ret_scalar.ty()));
            } else {
                signature.returns.push(AbiParam::new(ret_scalar.ty()));
            }

            let func_id = module
                .declare_function(&extern_fn.symbol_name, Linkage::Import, &signature)
                .map_err(|err| {
                    format!(
                        "failed to declare extern function '{}': {err}",
                        extern_fn.name
                    )
                })?;

            by_key.insert((mir_module.module_id.0, extern_fn.name.clone()), func_id);
            by_name.entry(extern_fn.name.clone()).or_insert(func_id);
            by_name.insert(
                format!("#{}::{}", mir_module.module_id.0, extern_fn.name),
                func_id,
            );
            by_name
                .entry(extern_fn.symbol_name.clone())
                .or_insert(func_id);
            param_types_by_id.insert(func_id.as_u32(), param_types);
            returns_bytes_slice_by_id.insert(func_id.as_u32(), returns_bytes_slice);
            returns_errorable_by_id.insert(func_id.as_u32(), returns_errorable);
            if returns_errorable_scalar {
                returns_errorable_scalar_payload_ty_by_id.insert(
                    func_id.as_u32(),
                    backend_hint_mir_type(extern_fn.return_type.as_deref()),
                );
            }
            returns_unknown_nominal_by_id.insert(func_id.as_u32(), returns_unknown_nominal);
            if let Some(layout) = returns_aggregate_layout {
                returns_aggregate_layout_by_id.insert(func_id.as_u32(), layout);
            }
        }
    }

    for intrinsic in runtime_intrinsics(pointer_ty) {
        let mut signature = module.make_signature();
        for param in &intrinsic.params {
            signature.params.push(AbiParam::new(*param));
        }
        signature.returns.push(AbiParam::new(intrinsic.ret));
        let func_id = module
            .declare_function(intrinsic.name, Linkage::Import, &signature)
            .map_err(|err| {
                format!(
                    "failed to declare runtime intrinsic '{}': {err}",
                    intrinsic.name
                )
            })?;
        by_name.entry(intrinsic.name.to_string()).or_insert(func_id);
        param_types_by_id.insert(func_id.as_u32(), intrinsic.params);
        returns_bytes_slice_by_id.insert(
            func_id.as_u32(),
            runtime_intrinsic_returns_bytes_slice(intrinsic.name),
        );
        returns_errorable_by_id.insert(func_id.as_u32(), false);
        returns_unknown_nominal_by_id.insert(func_id.as_u32(), false);
    }

    Ok(FunctionSymbols {
        by_key,
        by_name,
        param_types_by_id,
        returns_bytes_slice_by_id,
        returns_errorable_by_id,
        returns_errorable_scalar_payload_ty_by_id,
        returns_unknown_nominal_by_id,
        returns_aggregate_layout_by_id,
        nominal_aggregate_layouts,
    })
}

fn returns_errorable_from_hint(return_type: Option<&str>) -> bool {
    return_type.unwrap_or("").contains('!')
}

fn runtime_intrinsics(pointer_ty: Type) -> Vec<RuntimeIntrinsic> {
    RUNTIME_INTRINSICS
        .iter()
        .map(|intrinsic| RuntimeIntrinsic {
            name: intrinsic.symbol,
            params: intrinsic
                .abi_params
                .iter()
                .map(|param| runtime_abi_type_to_clif(*param, pointer_ty))
                .collect(),
            ret: runtime_abi_type_to_clif(intrinsic.abi_return, pointer_ty),
        })
        .collect()
}

fn runtime_abi_type_to_clif(kind: RuntimeAbiType, pointer_ty: Type) -> Type {
    match kind {
        RuntimeAbiType::Ptr => pointer_ty,
        RuntimeAbiType::I32 => I32,
        RuntimeAbiType::I64 => I64,
        RuntimeAbiType::F64 => F64,
    }
}

fn runtime_intrinsic_returns_bytes_slice(name: &str) -> bool {
    runtime_intrinsic_for_symbol(name)
        .map(|intrinsic| matches!(intrinsic.return_kind, RuntimeReturnKind::BytesSlice))
        .unwrap_or(false)
}

fn returns_bytes_slice_from_hint(return_type: Option<&str>) -> bool {
    normalized_return_type_hint(return_type) == "[]u8"
}

fn normalized_return_type_hint(return_type: Option<&str>) -> String {
    let mut ty = return_type.unwrap_or("").trim().to_string();
    if let Some(stripped) = ty.strip_prefix('?') {
        ty = stripped.trim().to_string();
    }
    if ty.starts_with("fn/") {
        if let Some((_, ret)) = ty.split_once("->") {
            ty = ret.trim().to_string();
        }
    }
    if ty.starts_with('(') {
        if let Some((_, tail)) = ty.rsplit_once(')') {
            ty = tail.trim().to_string();
        }
    }
    if let Some((ok, _errs)) = ty.split_once('!') {
        ty = ok.trim().to_string();
    }
    ty
}

fn parse_scalar_enum_repr_bits(type_text: &str) -> Option<u16> {
    let (bits, inner) = parse_enum_type_descriptor(type_text)?;

    let mut depth_paren = 0i32;
    let mut depth_brace = 0i32;
    let mut depth_bracket = 0i32;
    for ch in inner.chars() {
        match ch {
            '(' => depth_paren += 1,
            ')' => depth_paren -= 1,
            '{' => depth_brace += 1,
            '}' => depth_brace -= 1,
            '[' => depth_bracket += 1,
            ']' => depth_bracket -= 1,
            ':' if depth_paren == 0 && depth_brace == 0 && depth_bracket == 0 => return None,
            _ => {}
        }
    }

    Some(bits)
}

fn sanitize_symbol_name(name: &str) -> String {
    name.chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == '_' {
                ch
            } else {
                '_'
            }
        })
        .collect()
}

#[derive(Debug, Copy, Clone)]
enum ScalarType {
    Int { ty: Type, signed: bool },
    Float { ty: Type },
}

impl ScalarType {
    fn ty(self) -> Type {
        match self {
            Self::Int { ty, .. } | Self::Float { ty } => ty,
        }
    }
}

#[derive(Debug, Clone)]
enum ParamAccess {
    Scalar {
        block_param: usize,
    },
    BytesSlice {
        ptr_param: usize,
        len_param: usize,
    },
    Aggregate {
        block_param: usize,
        layout: AggregateLayout,
    },
}

fn compile_function(
    module: &mut ObjectModule,
    function: &MirFunction,
    current_module_id: usize,
    exported: bool,
    symbols: &FunctionSymbols,
) -> Result<(), String> {
    let func_id = symbols
        .by_key
        .get(&(current_module_id, function.name.clone()))
        .copied()
        .ok_or_else(|| format!("missing symbol for function '{}'", function.name))?;

    let scalar = parse_return_scalar(function.return_type.as_deref());
    let mut ctx = module.make_context();
    let pointer_ty = module.target_config().pointer_type();
    let returns_bytes_slice =
        !exported && returns_bytes_slice_from_hint(function.return_type.as_deref());
    let returns_errorable = returns_errorable_from_hint(function.return_type.as_deref());
    let returns_aggregate_layout = if returns_bytes_slice {
        None
    } else {
        parse_aggregate_layout(
            function.return_type.as_deref(),
            &symbols.nominal_aggregate_layouts,
            pointer_ty,
        )
    };
    let returns_errorable_scalar = !exported
        && returns_errorable
        && !returns_bytes_slice
        && returns_aggregate_layout.is_none();
    let signature_ret_ty = if exported {
        I32
    } else if returns_bytes_slice || (returns_aggregate_layout.is_some() && !returns_errorable) {
        pointer_ty
    } else {
        scalar.ty()
    };

    let mut param_access = Vec::with_capacity(function.param_types.len());
    let mut block_param_index = 0usize;
    for idx in 0..function.param_types.len() {
        let param = effective_param_type(function, idx);
        if matches!(param, MirValueType::BytesSlice) {
            ctx.func.signature.params.push(AbiParam::new(pointer_ty));
            ctx.func.signature.params.push(AbiParam::new(pointer_ty));
            param_access.push(ParamAccess::BytesSlice {
                ptr_param: block_param_index,
                len_param: block_param_index + 1,
            });
            block_param_index += 2;
            continue;
        }

        let param_ty = if matches!(
            param,
            MirValueType::Unknown | MirValueType::Function | MirValueType::FunctionPointer
        ) {
            pointer_ty
        } else {
            mir_type_to_clif(&param, scalar)
        };
        ctx.func.signature.params.push(AbiParam::new(param_ty));
        if matches!(param, MirValueType::Unknown)
            && function
                .param_type_hints
                .get(idx)
                .and_then(|hint| {
                    parse_aggregate_layout(
                        hint.as_deref(),
                        &symbols.nominal_aggregate_layouts,
                        pointer_ty,
                    )
                })
                .is_some()
        {
            let layout = function
                .param_type_hints
                .get(idx)
                .and_then(|hint| {
                    parse_aggregate_layout(
                        hint.as_deref(),
                        &symbols.nominal_aggregate_layouts,
                        pointer_ty,
                    )
                })
                .expect("aggregate layout checked above");
            param_access.push(ParamAccess::Aggregate {
                block_param: block_param_index,
                layout,
            });
        } else {
            param_access.push(ParamAccess::Scalar {
                block_param: block_param_index,
            });
        }
        block_param_index += 1;
    }

    let slice_out_len_param = if returns_bytes_slice {
        ctx.func.signature.params.push(AbiParam::new(pointer_ty));
        let index = block_param_index;
        block_param_index += 1;
        Some(index)
    } else {
        None
    };

    let aggregate_out_ptr_param = if returns_aggregate_layout.is_some() {
        ctx.func.signature.params.push(AbiParam::new(pointer_ty));
        let index = block_param_index;
        block_param_index += 1;
        Some(index)
    } else {
        None
    };

    let errorable_scalar_out_ptr_param = if returns_errorable_scalar {
        ctx.func.signature.params.push(AbiParam::new(pointer_ty));
        let index = block_param_index;
        block_param_index += 1;
        Some(index)
    } else {
        None
    };

    let _ = block_param_index;
    ctx.func
        .signature
        .returns
        .push(AbiParam::new(signature_ret_ty));

    let mut fn_builder_ctx = FunctionBuilderContext::new();
    let mut builder = FunctionBuilder::new(&mut ctx.func, &mut fn_builder_ctx);

    let mut clif_blocks = Vec::with_capacity(function.blocks.len());
    for _ in &function.blocks {
        clif_blocks.push(builder.create_block());
    }

    let mut phi_layout = PhiLayout::new();
    for block in &function.blocks {
        let mut entries = Vec::new();
        for instruction in &block.instructions {
            if let MirInstr::Phi { dest, sources, ty } = instruction {
                let mut source_map = BTreeMap::new();
                for (pred, value) in sources {
                    source_map.insert(pred.0, *value);
                }
                entries.push((*dest, source_map, ty.clone()));
            }
        }
        phi_layout.insert(block.id.0, entries);
    }

    for block in &function.blocks {
        if let Some(phi_entries) = phi_layout.get(&block.id.0) {
            for (_, _, ty) in phi_entries {
                if matches!(ty, MirValueType::BytesSlice) {
                    builder.append_block_param(clif_blocks[block.id.0], pointer_ty);
                    builder.append_block_param(clif_blocks[block.id.0], pointer_ty);
                } else {
                    let phi_ty = if matches!(ty, MirValueType::Unknown) {
                        pointer_ty
                    } else {
                        mir_type_to_clif(ty, scalar)
                    };
                    builder.append_block_param(clif_blocks[block.id.0], phi_ty);
                }
            }
        }
    }

    let mut value_defs = BTreeMap::<MirValueId, MirValue>::new();
    let mut value_types = BTreeMap::<MirValueId, MirValueType>::new();
    for block in &function.blocks {
        for instruction in &block.instructions {
            match instruction {
                MirInstr::Eval { dest, value, ty } => {
                    value_defs.insert(*dest, value.clone());
                    value_types.insert(*dest, ty.clone());
                }
                MirInstr::Phi { dest, ty, .. } => {
                    value_defs.entry(*dest).or_insert(MirValue::Unknown);
                    value_types.insert(*dest, ty.clone());
                }
            }
        }
    }

    let lower_value_context = LowerValueContext {
        value_defs: &value_defs,
        param_access: &param_access,
        current_module_id,
        scalar,
        symbols_by_key: &symbols.by_key,
        symbols_by_name: &symbols.by_name,
        call_symbol_tables: CallSymbolTables {
            param_types_by_id: &symbols.param_types_by_id,
            returns_bytes_slice_by_id: &symbols.returns_bytes_slice_by_id,
            returns_errorable_by_id: &symbols.returns_errorable_by_id,
            returns_errorable_scalar_payload_ty_by_id: &symbols
                .returns_errorable_scalar_payload_ty_by_id,
            returns_aggregate_layout_by_id: &symbols.returns_aggregate_layout_by_id,
        },
    };

    let mut global_lowered = BTreeMap::<MirValueId, LoweredValue>::new();
    let mut function_out_len_ptr = None;
    let mut function_out_aggregate_ptr = None;
    let mut function_out_errorable_scalar_ptr = None;

    for block in &function.blocks {
        let clif_block = clif_blocks[block.id.0];
        builder.switch_to_block(clif_block);
        if block.id.0 == function.entry.0 {
            builder.append_block_params_for_function_params(clif_block);
            if let Some(out_len_param) = slice_out_len_param {
                function_out_len_ptr = builder.block_params(clif_block).get(out_len_param).copied();
            }
            if let Some(out_ptr_param) = aggregate_out_ptr_param {
                function_out_aggregate_ptr =
                    builder.block_params(clif_block).get(out_ptr_param).copied();
            }
            if let Some(out_ptr_param) = errorable_scalar_out_ptr_param {
                function_out_errorable_scalar_ptr =
                    builder.block_params(clif_block).get(out_ptr_param).copied();
            }
            builder.seal_block(clif_block);
        }

        let mut lowered = global_lowered.clone();
        if let Some(phi_entries) = phi_layout.get(&block.id.0) {
            let block_params = builder.block_params(clif_block).to_vec();
            let mut param_cursor = 0usize;
            for (dest, source_map, ty) in phi_entries {
                if matches!(ty, MirValueType::BytesSlice) {
                    let ptr = block_params
                        .get(param_cursor)
                        .copied()
                        .unwrap_or_else(|| zero_for_type(&mut builder, pointer_ty));
                    let len = block_params
                        .get(param_cursor + 1)
                        .copied()
                        .unwrap_or_else(|| zero_for_type(&mut builder, pointer_ty));
                    let lowered_value = LoweredValue::BytesSlice { ptr, len };
                    lowered.insert(*dest, lowered_value.clone());
                    global_lowered.insert(*dest, lowered_value);
                    param_cursor += 2;
                } else {
                    let val = block_params.get(param_cursor).copied().unwrap_or_else(|| {
                        zero_for_type(&mut builder, mir_type_to_clif(ty, scalar))
                    });
                    let inferred_layout = if matches!(ty, MirValueType::Unknown) {
                        source_map
                            .values()
                            .find_map(|source_id| {
                                lowered
                                    .get(source_id)
                                    .or_else(|| global_lowered.get(source_id))
                            })
                            .and_then(|source| match source {
                                LoweredValue::StructMemory {
                                    fields,
                                    aggregate_fields,
                                    ordered,
                                    scalar_leaves,
                                    size,
                                    align,
                                    ..
                                }
                                | LoweredValue::StructPointer {
                                    fields,
                                    aggregate_fields,
                                    ordered,
                                    scalar_leaves,
                                    size,
                                    align,
                                    ..
                                } => Some(AggregateLayout {
                                    fields: fields.clone(),
                                    aggregate_fields: aggregate_fields.clone(),
                                    ordered: ordered.clone(),
                                    scalar_leaves: scalar_leaves.clone(),
                                    size: *size,
                                    align: *align,
                                }),
                                _ => None,
                            })
                    } else {
                        None
                    };
                    let lowered_value = if let Some(layout) = inferred_layout {
                        LoweredValue::StructPointer {
                            addr: cast_scalar(&mut builder, val, pointer_ty, scalar),
                            stack_slot: None,
                            stack_offset: 0,
                            status: None,
                            fields: layout.fields,
                            aggregate_fields: layout.aggregate_fields,
                            ordered: layout.ordered,
                            scalar_leaves: layout.scalar_leaves,
                            size: layout.size,
                            align: layout.align,
                        }
                    } else {
                        LoweredValue::from_typed_value(val, ty)
                    };
                    let lowered_value = canonicalize_lowered_value_for_type(
                        &mut builder,
                        lowered_value,
                        ty,
                        scalar,
                    );
                    lowered.insert(*dest, lowered_value.clone());
                    global_lowered.insert(*dest, lowered_value);
                    param_cursor += 1;
                }
            }
        }

        for instruction in &block.instructions {
            match instruction {
                MirInstr::Eval { dest, value, ty } => {
                    let lowered_value = lower_value(
                        value,
                        ty,
                        &mut builder,
                        &lowered,
                        module,
                        &lower_value_context,
                    );
                    let lowered_value = canonicalize_lowered_value_for_type(
                        &mut builder,
                        lowered_value,
                        ty,
                        scalar,
                    );
                    lowered.insert(*dest, lowered_value.clone());
                    global_lowered.insert(*dest, lowered_value);
                }
                MirInstr::Phi { .. } => {}
            }
        }

        match &block.terminator {
            Some(MirTerminator::Return(value)) => {
                if returns_bytes_slice {
                    let (ret_ptr, ret_len) = value
                        .and_then(|id| lowered.get(&id))
                        .map(|value| match value {
                            LoweredValue::BytesSlice { ptr, len } => (*ptr, *len),
                            LoweredValue::FunctionSymbol(func_id) => {
                                let func_ref = module.declare_func_in_func(*func_id, builder.func);
                                let ptr = builder.ins().func_addr(pointer_ty, func_ref);
                                let len = zero_for_type(&mut builder, pointer_ty);
                                (ptr, len)
                            }
                            _ => (
                                value
                                    .as_value()
                                    .map(|v| cast_scalar(&mut builder, v, pointer_ty, scalar))
                                    .unwrap_or_else(|| zero_for_type(&mut builder, pointer_ty)),
                                zero_for_type(&mut builder, pointer_ty),
                            ),
                        })
                        .unwrap_or_else(|| {
                            (
                                zero_for_type(&mut builder, pointer_ty),
                                zero_for_type(&mut builder, pointer_ty),
                            )
                        });

                    if let Some(out_len_ptr) = function_out_len_ptr {
                        builder.ins().store(
                            cranelift_codegen::ir::MemFlags::new(),
                            ret_len,
                            out_len_ptr,
                            0,
                        );
                    }

                    builder.ins().return_(&[ret_ptr]);
                } else if let Some(layout) = returns_aggregate_layout.as_ref() {
                    let out_ptr = function_out_aggregate_ptr
                        .unwrap_or_else(|| zero_for_type(&mut builder, pointer_ty));
                    if returns_errorable {
                        let status = if let Some(ret_value) =
                            value.and_then(|id| lowered.get(&id)).cloned()
                        {
                            match ret_value {
                                LoweredValue::StructPointer {
                                    status: Some(status),
                                    ..
                                } => {
                                    write_aggregate_to_pointer(
                                        &mut builder,
                                        out_ptr,
                                        layout,
                                        &ret_value,
                                    );
                                    cast_scalar(&mut builder, status, signature_ret_ty, scalar)
                                }
                                LoweredValue::StructMemory { .. }
                                | LoweredValue::StructPointer { .. }
                                | LoweredValue::Struct(_) => {
                                    write_aggregate_to_pointer(
                                        &mut builder,
                                        out_ptr,
                                        layout,
                                        &ret_value,
                                    );
                                    zero_for_type(&mut builder, signature_ret_ty)
                                }
                                _ => ret_value
                                    .as_int()
                                    .map(|v| cast_scalar(&mut builder, v, signature_ret_ty, scalar))
                                    .unwrap_or_else(|| {
                                        zero_for_type(&mut builder, signature_ret_ty)
                                    }),
                            }
                        } else {
                            zero_for_type(&mut builder, signature_ret_ty)
                        };
                        builder.ins().return_(&[status]);
                    } else {
                        if let Some(ret_value) = value.and_then(|id| lowered.get(&id)).cloned() {
                            write_aggregate_to_pointer(&mut builder, out_ptr, layout, &ret_value);
                        } else {
                            zero_aggregate_at_pointer(&mut builder, out_ptr, layout);
                        }
                        builder.ins().return_(&[out_ptr]);
                    }
                } else if returns_errorable_scalar {
                    let out_ptr = function_out_errorable_scalar_ptr
                        .unwrap_or_else(|| zero_for_type(&mut builder, pointer_ty));
                    let payload_mir_ty = backend_hint_mir_type(Some(
                        normalized_return_type_hint(function.return_type.as_deref()).as_str(),
                    ));
                    let payload_ty = if matches!(payload_mir_ty, MirValueType::Unknown) {
                        scalar.ty()
                    } else {
                        mir_type_to_clif(&payload_mir_ty, scalar)
                    };

                    let mut status = zero_for_type(&mut builder, signature_ret_ty);
                    let mut payload = zero_for_type(&mut builder, payload_ty);

                    if let Some(value_id) = value {
                        let ret_value = lowered.get(value_id).cloned();
                        if let Some(ret_value) = ret_value {
                            match ret_value {
                                LoweredValue::ErrorableScalar {
                                    status: inner_status,
                                    payload: inner_payload,
                                    ..
                                } => {
                                    status = cast_scalar(
                                        &mut builder,
                                        inner_status,
                                        signature_ret_ty,
                                        scalar,
                                    );
                                    payload = cast_scalar(
                                        &mut builder,
                                        inner_payload,
                                        payload_ty,
                                        scalar,
                                    );
                                }
                                other => {
                                    let is_explicit_error =
                                        mir_value_resolves_to_empty_enum_variant(
                                            *value_id,
                                            &value_defs,
                                            0,
                                        ) || mir_value_resolves_to_error_status(
                                            *value_id,
                                            &value_defs,
                                            0,
                                        ) || mir_value_resolves_to_unknown_nominal_call(
                                            *value_id,
                                            &value_defs,
                                            &symbols.by_name,
                                            &symbols.returns_unknown_nominal_by_id,
                                            0,
                                        ) || (!matches!(payload_mir_ty, MirValueType::Unknown)
                                            && value_types.get(value_id).is_some_and(|ty| {
                                                matches!(ty, MirValueType::Unknown)
                                            }));

                                    if is_explicit_error {
                                        status = other
                                            .as_int()
                                            .map(|v| {
                                                cast_scalar(
                                                    &mut builder,
                                                    v,
                                                    signature_ret_ty,
                                                    scalar,
                                                )
                                            })
                                            .unwrap_or_else(|| {
                                                zero_for_type(&mut builder, signature_ret_ty)
                                            });
                                    } else {
                                        payload = match other {
                                            LoweredValue::FunctionSymbol(func_id) => {
                                                let func_ref = module
                                                    .declare_func_in_func(func_id, builder.func);
                                                let addr =
                                                    builder.ins().func_addr(pointer_ty, func_ref);
                                                cast_scalar(&mut builder, addr, payload_ty, scalar)
                                            }
                                            _ => other
                                                .as_value()
                                                .map(|v| {
                                                    cast_scalar(&mut builder, v, payload_ty, scalar)
                                                })
                                                .unwrap_or_else(|| {
                                                    zero_for_type(&mut builder, payload_ty)
                                                }),
                                        };
                                    }
                                }
                            }
                        }
                    }

                    builder.ins().store(
                        cranelift_codegen::ir::MemFlags::new(),
                        payload,
                        out_ptr,
                        0,
                    );
                    builder.ins().return_(&[status]);
                } else {
                    let ret = value
                        .and_then(|id| lowered.get(&id))
                        .and_then(|value| match value {
                            LoweredValue::FunctionSymbol(func_id) => {
                                let func_ref = module.declare_func_in_func(*func_id, builder.func);
                                Some(builder.ins().func_addr(pointer_ty, func_ref))
                            }
                            _ => value.as_value(),
                        })
                        .map(|value| cast_scalar(&mut builder, value, signature_ret_ty, scalar))
                        .unwrap_or_else(|| zero_for_type(&mut builder, signature_ret_ty));
                    builder.ins().return_(&[ret]);
                }
            }
            Some(MirTerminator::Goto(target)) => {
                let args = edge_args(
                    block.id.0,
                    target.0,
                    &phi_layout,
                    &lowered,
                    pointer_ty,
                    scalar,
                    &mut builder,
                );
                builder.ins().jump(clif_blocks[target.0], &args);
            }
            Some(MirTerminator::Branch {
                condition,
                then_block,
                else_block,
            }) => {
                let cond = lowered
                    .get(condition)
                    .and_then(LoweredValue::as_int)
                    .unwrap_or_else(|| zero_for_scalar(&mut builder, scalar));
                let then_args = edge_args(
                    block.id.0,
                    then_block.0,
                    &phi_layout,
                    &lowered,
                    pointer_ty,
                    scalar,
                    &mut builder,
                );
                let else_args = edge_args(
                    block.id.0,
                    else_block.0,
                    &phi_layout,
                    &lowered,
                    pointer_ty,
                    scalar,
                    &mut builder,
                );
                builder.ins().brif(
                    cond,
                    clif_blocks[then_block.0],
                    &then_args,
                    clif_blocks[else_block.0],
                    &else_args,
                );
            }
            Some(MirTerminator::Unreachable) => {
                builder.ins().trap(TrapCode::unwrap_user(1));
            }
            None => {
                if returns_bytes_slice {
                    let ret_ptr = zero_for_type(&mut builder, pointer_ty);
                    let ret_len = zero_for_type(&mut builder, pointer_ty);
                    if let Some(out_len_ptr) = function_out_len_ptr {
                        builder.ins().store(
                            cranelift_codegen::ir::MemFlags::new(),
                            ret_len,
                            out_len_ptr,
                            0,
                        );
                    }
                    builder.ins().return_(&[ret_ptr]);
                } else if let Some(layout) = returns_aggregate_layout.as_ref() {
                    let out_ptr = function_out_aggregate_ptr
                        .unwrap_or_else(|| zero_for_type(&mut builder, pointer_ty));
                    if returns_errorable {
                        zero_aggregate_at_pointer(&mut builder, out_ptr, layout);
                        let status = zero_for_type(&mut builder, signature_ret_ty);
                        builder.ins().return_(&[status]);
                    } else {
                        zero_aggregate_at_pointer(&mut builder, out_ptr, layout);
                        builder.ins().return_(&[out_ptr]);
                    }
                } else if returns_errorable_scalar {
                    let out_ptr = function_out_errorable_scalar_ptr
                        .unwrap_or_else(|| zero_for_type(&mut builder, pointer_ty));
                    let payload_mir_ty = backend_hint_mir_type(Some(
                        normalized_return_type_hint(function.return_type.as_deref()).as_str(),
                    ));
                    let payload_ty = if matches!(payload_mir_ty, MirValueType::Unknown) {
                        scalar.ty()
                    } else {
                        mir_type_to_clif(&payload_mir_ty, scalar)
                    };
                    let payload = zero_for_type(&mut builder, payload_ty);
                    builder.ins().store(
                        cranelift_codegen::ir::MemFlags::new(),
                        payload,
                        out_ptr,
                        0,
                    );
                    let status = zero_for_type(&mut builder, signature_ret_ty);
                    builder.ins().return_(&[status]);
                } else {
                    let ret = zero_for_type(&mut builder, signature_ret_ty);
                    builder.ins().return_(&[ret]);
                }
            }
        }
    }

    let mut sealed = std::collections::BTreeSet::new();
    sealed.insert(function.entry.0);
    for block in &function.blocks {
        match &block.terminator {
            Some(MirTerminator::Goto(target)) => {
                if sealed.insert(target.0) {
                    builder.seal_block(clif_blocks[target.0]);
                }
            }
            Some(MirTerminator::Branch {
                then_block,
                else_block,
                ..
            }) => {
                if sealed.insert(then_block.0) {
                    builder.seal_block(clif_blocks[then_block.0]);
                }
                if sealed.insert(else_block.0) {
                    builder.seal_block(clif_blocks[else_block.0]);
                }
            }
            _ => {}
        }
    }

    for (idx, clif_block) in clif_blocks.iter().enumerate() {
        if sealed.insert(idx) {
            builder.seal_block(*clif_block);
        }
    }

    builder.finalize();

    module.define_function(func_id, &mut ctx).map_err(|err| {
        format!(
            "failed to define function '{}': {err} ({err:?})",
            function.name,
        )
    })?;
    module.clear_context(&mut ctx);
    Ok(())
}

include!("cranelift/lowering.rs");

fn parse_int_literal_parts(value: &str) -> Option<(bool, u128)> {
    let normalized = value.replace('_', "");
    let (negative, digits) = if let Some(rest) = normalized.strip_prefix('-') {
        (true, rest)
    } else if let Some(rest) = normalized.strip_prefix('+') {
        (false, rest)
    } else {
        (false, normalized.as_str())
    };

    if digits.is_empty() {
        return None;
    }

    let (radix, body) = if let Some(bits) = digits.strip_prefix("0x") {
        (16, bits)
    } else if let Some(bits) = digits.strip_prefix("0b") {
        (2, bits)
    } else if let Some(bits) = digits.strip_prefix("0o") {
        (8, bits)
    } else {
        (10, digits)
    };

    if body.is_empty() {
        return None;
    }

    let magnitude = u128::from_str_radix(body, radix).ok()?;
    Some((negative, magnitude))
}

fn parse_int_literal(value: &str) -> Option<i64> {
    let (negative, magnitude) = parse_int_literal_parts(value)?;
    if negative {
        if magnitude == (i64::MAX as u128) + 1 {
            Some(i64::MIN)
        } else {
            i64::try_from(magnitude).ok().map(|parsed| -parsed)
        }
    } else {
        i64::try_from(magnitude).ok()
    }
}

fn parse_int_literal_wide_bits(value: &str) -> Option<u128> {
    let (negative, magnitude) = parse_int_literal_parts(value)?;
    if negative {
        Some((0u128).wrapping_sub(magnitude))
    } else {
        Some(magnitude)
    }
}
