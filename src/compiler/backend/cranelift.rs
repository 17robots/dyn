use cranelift_codegen::settings::Configurable;
use cranelift_codegen::{
    ir::{
        condcodes::IntCC,
        entities::StackSlot,
        stackslot::{StackSlotData, StackSlotKind},
        types::{F128, F32, F64, I128, I16, I32, I64, I8},
        AbiParam, Block, InstBuilder, InstructionData, Opcode, TrapCode, Type, Value, ValueDef,
    },
    settings,
};

use cranelift_frontend::{FunctionBuilder, FunctionBuilderContext};
use cranelift_module::{DataDescription, DataId, FuncId, Linkage, Module};
use cranelift_object::{ObjectBuilder, ObjectModule};

use object::{
    read::{File as ObjFile, Object as ObjRead, ObjectSection, ObjectSymbol},
    write::{Object, StandardSection, Symbol, SymbolSection},
    Architecture, BinaryFormat, Endianness, RelocationEncoding, RelocationFlags, RelocationKind,
    RelocationTarget, SectionKind, SymbolFlags, SymbolKind, SymbolScope,
};

use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Path, PathBuf},
    process::Command,
};

use crate::compiler::{
    ast::{BinaryOp, UnaryOp},
    backend::{BuildArtifact, BuildOptLevel},
    diagnostics::{Diagnostic, DiagnosticCode, DiagnosticPhase},
    hir::HirLiteral,
    mir::{
        MirBlockId, MirFunction, MirGlobalInit, MirInstr, MirModule, MirProgram, MirTerminator,
        MirValue, MirValueId, MirValueType,
    },
    type_text::parse_enum_type_descriptor,
};

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
    global_data_ids: BTreeMap<String, DataId>,
}

#[derive(Debug, Clone)]
pub(super) struct AggregateLayout {
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

    if ty == "u1" {
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
    if ty.starts_with("fn/") || (ty.starts_with('(') && ty.contains(")->")) {
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
            let exported = function.name == "main";
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
        returns_bytes_slice_by_id.insert(func_id.as_u32(), false);
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
        global_data_ids: BTreeMap::new(),
    })
}

fn declare_global_data(
    mir: &MirProgram,
    module: &mut ObjectModule,
) -> Result<BTreeMap<String, DataId>, String> {
    let mut data_ids = BTreeMap::new();
    for mir_module in &mir.modules {
        for global in &mir_module.globals {
            let data_id = module
                .declare_data(&global.name, Linkage::Local, global.mutable, false)
                .map_err(|err| format!("failed to declare global '{}': {err}", global.name))?;
            let size = type_hint_byte_size(global.type_hint.as_deref()).unwrap_or(8) as usize;
            let mut desc = DataDescription::new();
            match &global.init {
                MirGlobalInit::Zero => {
                    desc.define_zeroinit(size);
                }
                MirGlobalInit::Integer(v) => {
                    let bytes = integer_init_bytes(*v, size);
                    desc.define(bytes.into_boxed_slice());
                }
                MirGlobalInit::Bool(b) => {
                    desc.define(vec![u8::from(*b)].into_boxed_slice());
                }
            }
            module
                .define_data(data_id, &desc)
                .map_err(|err| format!("failed to define global '{}': {err}", global.name))?;
            data_ids.insert(global.name.clone(), data_id);
        }
    }
    Ok(data_ids)
}

fn type_hint_byte_size(hint: Option<&str>) -> Option<u32> {
    let hint = hint?.trim();
    match hint {
        "u1" | "i8" | "u8" => Some(1),
        "i16" | "u16" => Some(2),
        "i32" | "u32" | "f32" => Some(4),
        "i64" | "u64" | "f64" | "isize" | "usize" => Some(8),
        h if h.starts_with('*') || h.starts_with("[]") => Some(8),
        _ => None,
    }
}

fn integer_init_bytes(value: i64, size: usize) -> Vec<u8> {
    let full = value.to_le_bytes();
    full[..size.min(8)].to_vec()
}

fn returns_errorable_from_hint(return_type: Option<&str>) -> bool {
    return_type.unwrap_or("").contains('!')
}

fn runtime_intrinsics(pointer_ty: Type) -> Vec<RuntimeIntrinsic> {
    let p = pointer_ty;
    vec![
        // dyn_syscall: backing symbol for the $syscall builtin.
        // Signature: (i64 x 7) -> i64  — number + up to 6 args, padded with 0.
        RuntimeIntrinsic {
            name: "dyn_syscall",
            params: vec![I64, I64, I64, I64, I64, I64, I64],
            ret: I64,
        },
        // Standard C memory routines — used both by Cranelift libcalls (emitted
        // automatically for aggregate copies/compares) and by the $memcpy/$memset
        // language builtins.
        RuntimeIntrinsic {
            name: "memcpy",
            params: vec![p, p, I64],
            ret: p,
        },
        RuntimeIntrinsic {
            name: "memmove",
            params: vec![p, p, I64],
            ret: p,
        },
        RuntimeIntrinsic {
            name: "memset",
            params: vec![p, I32, I64],
            ret: p,
        },
        RuntimeIntrinsic {
            name: "memcmp",
            params: vec![p, p, I64],
            ret: I32,
        },
    ]
}

fn compute_block_emission_order(function: &MirFunction) -> Vec<usize> {
    fn visit(
        block_id: usize,
        function: &MirFunction,
        visited: &mut BTreeSet<usize>,
        order: &mut Vec<usize>,
    ) {
        if !visited.insert(block_id) {
            return;
        }
        order.push(block_id);
        let Some(block) = function.blocks.get(block_id) else {
            return;
        };
        match &block.terminator {
            Some(MirTerminator::Goto(target)) => {
                visit(target.0, function, visited, order);
            }
            Some(MirTerminator::Branch {
                then_block,
                else_block,
                ..
            }) => {
                visit(then_block.0, function, visited, order);
                visit(else_block.0, function, visited, order);
            }
            _ => {}
        }
    }

    let mut visited = BTreeSet::new();
    let mut order = Vec::with_capacity(function.blocks.len());
    visit(function.entry.0, function, &mut visited, &mut order);
    for block in &function.blocks {
        if visited.insert(block.id.0) {
            order.push(block.id.0);
        }
    }
    order
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
    if std::env::var("DYN_DEBUG_MIR_FUNCTION")
        .ok()
        .as_deref()
        .is_some_and(|name| name == function.name)
    {
        eprintln!("{function:#?}");
    }

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
    let errorable_scalar_payload_ty = backend_hint_mir_type(Some(
        normalized_return_type_hint(function.return_type.as_deref()).as_str(),
    ));
    let signature_ret_ty = if exported {
        I32
    } else if returns_bytes_slice || (returns_aggregate_layout.is_some() && !returns_errorable) {
        pointer_ty
    } else {
        scalar.ty()
    };
    let return_profile = FunctionReturnProfile {
        signature_ret_ty,
        pointer_ty,
        scalar,
        returns_bytes_slice,
        returns_aggregate_layout: returns_aggregate_layout.as_ref(),
        returns_errorable,
        returns_errorable_scalar,
        errorable_scalar_payload_ty,
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
    let block_emission_order = compute_block_emission_order(function);

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
        value_types: &value_types,
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
        global_data_ids: &symbols.global_data_ids,
    };

    let mut global_lowered = BTreeMap::<MirValueId, LoweredValue>::new();
    let mut function_out_len_ptr = None;
    let mut function_out_aggregate_ptr = None;
    let mut function_out_errorable_scalar_ptr = None;

    for &block_index in &block_emission_order {
        let block = &function.blocks[block_index];
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
        let return_out_ptrs = FunctionReturnOutPtrs {
            out_len_ptr: function_out_len_ptr,
            out_aggregate_ptr: function_out_aggregate_ptr,
            out_errorable_scalar_ptr: function_out_errorable_scalar_ptr,
        };

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
            Some(MirTerminator::Return(value)) => emit_function_return(
                module,
                &mut builder,
                &lowered,
                *value,
                &return_profile,
                return_out_ptrs,
                &value_defs,
                &value_types,
                &symbols.by_name,
                &symbols.returns_unknown_nominal_by_id,
            ),
            Some(MirTerminator::Goto(target)) => emit_goto_terminator(
                block.id.0,
                *target,
                &phi_layout,
                &global_lowered,
                pointer_ty,
                scalar,
                &clif_blocks,
                &mut builder,
            ),
            Some(MirTerminator::Branch {
                condition,
                then_block,
                else_block,
            }) => emit_branch_terminator(
                block.id.0,
                *condition,
                *then_block,
                *else_block,
                &phi_layout,
                &global_lowered,
                pointer_ty,
                scalar,
                &clif_blocks,
                &mut builder,
            ),
            Some(MirTerminator::Unreachable) => emit_unreachable_terminator(&mut builder),
            None => emit_function_return(
                module,
                &mut builder,
                &lowered,
                None,
                &return_profile,
                return_out_ptrs,
                &value_defs,
                &value_types,
                &symbols.by_name,
                &symbols.returns_unknown_nominal_by_id,
            ),
        }
    }

    let mut sealed = std::collections::BTreeSet::new();
    sealed.insert(function.entry.0);
    for &block_index in &block_emission_order {
        let block = &function.blocks[block_index];
        seal_terminator_successors(&block.terminator, &clif_blocks, &mut sealed, &mut builder);
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

/// Hand-assembled runtime blobs injected into every executable.
///
/// These satisfy two needs:
/// 1.  Cranelift libcalls – Cranelift emits calls to the standard C names
///     (`memcpy`, `memmove`, `memset`, `memcmp`) when it needs to copy or
///     compare aggregates.  The blobs here resolve those references.
/// 2.  `$memcpy`/`$memset` language builtins (future) – fast paths that the
///     compiler front-end can call directly.
///
/// Calling conventions follow the platform ABI used for ordinary function
/// calls (System V AMD64 for x86-64 Linux/macOS; AArch64 ABI for all AArch64
/// platforms).  Return value is the first argument (dst pointer) for memcpy /
/// memmove / memset, and a signed integer for memcmp – matching the C standard
/// signatures that Cranelift expects.
pub(super) fn mem_blobs(arch: Architecture) -> &'static [(&'static str, &'static [u8])] {
    match arch {
        Architecture::X86_64 => X86_64_SYSV,
        Architecture::Aarch64 => AARCH64,
        _ => &[],
    }
}

// ---------------------------------------------------------------------------
// x86-64 – System V AMD64 ABI  (Linux and macOS)
//   rdi=arg1, rsi=arg2, rdx=arg3 → return in rax
// ---------------------------------------------------------------------------

/// memcpy(rdi=dst, rsi=src, rdx=len) → rax=dst
///   mov rax, rdi          ; save dst for return
///   mov rcx, rdx          ; len → rcx (rep movsb counter)
///   rep movsb             ; copy bytes  (hardware-optimised on modern CPUs)
///   ret
static MEMCPY_X86_64: &[u8] = &[
    0x48, 0x89, 0xF8, // mov rax, rdi
    0x48, 0x89, 0xD1, // mov rcx, rdx
    0xF3, 0xA4, // rep movsb
    0xC3, // ret
];

/// memmove(rdi=dst, rsi=src, rdx=len) → rax=dst
///
/// If dst <= src or dst >= src+len: forward copy (rep movsb).
/// Otherwise: backward copy using std + rep movsb to handle overlap.
///
///   mov rax, rdi
///   mov rcx, rdx
///   cmp rdi, rsi
///   jbe .fwd               ; dst <= src → safe forward
///   lea r8, [rsi+rcx]
///   cmp rdi, r8
///   jae .fwd               ; dst >= src+len → no overlap
///   add rdi, rcx           ; point to one past end
///   dec rdi
///   add rsi, rcx
///   dec rsi
///   std                    ; count down
///   rep movsb
///   cld
///   ret
/// .fwd:
///   rep movsb
///   ret
static MEMMOVE_X86_64: &[u8] = &[
    0x48, 0x89, 0xF8, // mov rax, rdi
    0x48, 0x89, 0xD1, // mov rcx, rdx
    0x48, 0x39, 0xF7, // cmp rdi, rsi
    0x76, 0x1A, // jbe .fwd  (+26)
    0x4C, 0x8D, 0x04, 0x0E, // lea r8, [rsi+rcx]
    0x4C, 0x39, 0xC7, // cmp rdi, r8
    0x73, 0x11, // jae .fwd  (+17)
    0x48, 0x01, 0xCF, // add rdi, rcx
    0x48, 0xFF, 0xCF, // dec rdi
    0x48, 0x01, 0xCE, // add rsi, rcx
    0x48, 0xFF, 0xCE, // dec rsi
    0xFD, // std
    0xF3, 0xA4, // rep movsb
    0xFC, // cld
    0xC3, // ret
    0xF3, 0xA4, // .fwd: rep movsb
    0xC3, // ret
];

/// memset(rdi=dst, rsi=val_i32, rdx=len) → rax=dst
///   push rdi
///   movzx eax, sil         ; byte value (low byte of rsi)
///   mov rcx, rdx
///   rep stosb
///   pop rax                ; original dst → return value
///   ret
static MEMSET_X86_64: &[u8] = &[
    0x57, // push rdi
    0x40, 0x0F, 0xB6, 0xC6, // movzx eax, sil
    0x48, 0x89, 0xD1, // mov rcx, rdx
    0xF3, 0xAA, // rep stosb
    0x58, // pop rax
    0xC3, // ret
];

/// memcmp(rdi=a, rsi=b, rdx=len) → eax=result
///   xor eax, eax
///   mov rcx, rdx
///   repe cmpsb
///   jz .done               ; all equal → return 0
///   movzx eax, byte [rdi-1]
///   movzx ecx, byte [rsi-1]
///   sub eax, ecx
/// .done:
///   ret
static MEMCMP_X86_64: &[u8] = &[
    0x31, 0xC0, // xor eax, eax
    0x48, 0x89, 0xD1, // mov rcx, rdx
    0xF3, 0xA6, // repe cmpsb
    0x74, 0x0A, // jz .done  (+10)
    0x0F, 0xB6, 0x47, 0xFF, // movzx eax, byte [rdi-1]
    0x0F, 0xB6, 0x4E, 0xFF, // movzx ecx, byte [rsi-1]
    0x29, 0xC8, // sub eax, ecx
    0xC3, // ret  (.done)
];

static X86_64_SYSV: &[(&str, &[u8])] = &[
    ("memcpy", MEMCPY_X86_64),
    ("memmove", MEMMOVE_X86_64),
    ("memset", MEMSET_X86_64),
    ("memcmp", MEMCMP_X86_64),
];

// ---------------------------------------------------------------------------
// AArch64 – AArch64 ABI  (Linux, macOS, Windows)
//   x0=arg1, x1=arg2, x2=arg3 → return in x0
//   All blobs preserve x9/x10 as scratch (caller-saved); no callee-saved
//   registers are touched.
// ---------------------------------------------------------------------------

/// memcpy(x0=dst, x1=src, x2=len) → x0=dst
///   mov x9, x0
///   cbz x2, .done
/// .loop:
///   ldrb w3, [x1], #1
///   strb w3, [x0], #1
///   subs x2, x2, #1
///   b.ne .loop
/// .done:
///   mov x0, x9
///   ret
static MEMCPY_AARCH64: &[u8] = &[
    0xE9, 0x03, 0x00, 0xAA, // mov x9, x0
    0xA2, 0x00, 0x00, 0xB4, // cbz x2, .done  (+5 instrs)
    0x23, 0x14, 0x40, 0x38, // .loop: ldrb w3, [x1], #1
    0x03, 0x14, 0x00, 0x38, // strb w3, [x0], #1
    0x42, 0x04, 0x00, 0xF1, // subs x2, x2, #1
    0xA1, 0xFF, 0xFF, 0x54, // b.ne .loop  (-3 instrs)
    0xE0, 0x03, 0x09, 0xAA, // .done: mov x0, x9
    0xC0, 0x03, 0x5F, 0xD6, // ret
];

/// memmove(x0=dst, x1=src, x2=len) → x0=dst
///
/// Forward copy when dst <= src or dst >= src+len; backward copy otherwise.
///
///   mov x9, x0
///   cmp x0, x1
///   b.ls .fwd_loop_entry   ; dst <= src
///   add x10, x1, x2        ; src+len
///   cmp x0, x10
///   b.hs .fwd_loop_entry   ; dst >= src+len
///   add x0, x0, x2
///   add x1, x1, x2
/// .back_test:
///   cbz x2, .done
///   sub x0, x0, #1
///   sub x1, x1, #1
///   ldrb w3, [x1]
///   strb w3, [x0]
///   sub x2, x2, #1
///   b .back_test
/// .fwd_loop_entry:
///   cbz x2, .done
/// .fwd_loop:
///   ldrb w3, [x1], #1
///   strb w3, [x0], #1
///   subs x2, x2, #1
///   b.ne .fwd_loop
/// .done:
///   mov x0, x9
///   ret
static MEMMOVE_AARCH64: &[u8] = &[
    0xE9, 0x03, 0x00, 0xAA, // mov x9, x0
    0x1F, 0x00, 0x01, 0xEB, // cmp x0, x1
    0xA9, 0x01, 0x00, 0x54, // b.ls .fwd_loop_entry  (+13 instrs)
    0x2A, 0x00, 0x02, 0x8B, // add x10, x1, x2
    0x1F, 0x00, 0x0A, 0xEB, // cmp x0, x10
    0x42, 0x01, 0x00, 0x54, // b.hs .fwd_loop_entry  (+10 instrs)
    0x00, 0x00, 0x02, 0x8B, // add x0, x0, x2
    0x21, 0x00, 0x02, 0x8B, // add x1, x1, x2
    0x82, 0x01, 0x00, 0xB4, // .back_test: cbz x2, .done  (+12 instrs)
    0x00, 0x04, 0x00, 0xD1, // sub x0, x0, #1
    0x21, 0x04, 0x00, 0xD1, // sub x1, x1, #1
    0x23, 0x00, 0x40, 0x39, // ldrb w3, [x1]
    0x03, 0x00, 0x00, 0x39, // strb w3, [x0]
    0x42, 0x04, 0x00, 0xD1, // sub x2, x2, #1
    0xFA, 0xFF, 0xFF, 0x17, // b .back_test  (-6 instrs)
    0xA2, 0x00, 0x00, 0xB4, // .fwd_loop_entry: cbz x2, .done  (+5 instrs)
    0x23, 0x14, 0x40, 0x38, // .fwd_loop: ldrb w3, [x1], #1
    0x03, 0x14, 0x00, 0x38, // strb w3, [x0], #1
    0x42, 0x04, 0x00, 0xF1, // subs x2, x2, #1
    0xA1, 0xFF, 0xFF, 0x54, // b.ne .fwd_loop  (-3 instrs)
    0xE0, 0x03, 0x09, 0xAA, // .done: mov x0, x9
    0xC0, 0x03, 0x5F, 0xD6, // ret
];

/// memset(x0=dst, x1=val_i32, x2=len) → x0=dst
///   mov x9, x0
///   cbz x2, .done
/// .loop:
///   strb w1, [x0], #1
///   subs x2, x2, #1
///   b.ne .loop
/// .done:
///   mov x0, x9
///   ret
static MEMSET_AARCH64: &[u8] = &[
    0xE9, 0x03, 0x00, 0xAA, // mov x9, x0
    0x82, 0x00, 0x00, 0xB4, // cbz x2, .done  (+4 instrs)
    0x01, 0x14, 0x00, 0x38, // .loop: strb w1, [x0], #1
    0x42, 0x04, 0x00, 0xF1, // subs x2, x2, #1
    0xC1, 0xFF, 0xFF, 0x54, // b.ne .loop  (-2 instrs)
    0xE0, 0x03, 0x09, 0xAA, // .done: mov x0, x9
    0xC0, 0x03, 0x5F, 0xD6, // ret
];

/// memcmp(x0=a, x1=b, x2=len) → w0=result
///   cbz x2, .equal
/// .loop:
///   ldrb w3, [x0], #1
///   ldrb w4, [x1], #1
///   cmp w3, w4
///   b.ne .different
///   subs x2, x2, #1
///   b.ne .loop
/// .equal:
///   mov w0, #0
///   ret
/// .different:
///   sub w0, w3, w4
///   ret
static MEMCMP_AARCH64: &[u8] = &[
    0xE2, 0x00, 0x00, 0xB4, // cbz x2, .equal  (+7 instrs)
    0x03, 0x14, 0x40, 0x38, // .loop: ldrb w3, [x0], #1
    0x24, 0x14, 0x40, 0x38, // ldrb w4, [x1], #1
    0x7F, 0x00, 0x04, 0x6B, // cmp w3, w4
    0xA1, 0x00, 0x00, 0x54, // b.ne .different  (+5 instrs)
    0x42, 0x04, 0x00, 0xF1, // subs x2, x2, #1
    0x61, 0xFF, 0xFF, 0x54, // b.ne .loop  (-5 instrs)
    0x00, 0x00, 0x80, 0x52, // .equal: mov w0, #0
    0xC0, 0x03, 0x5F, 0xD6, // ret
    0x60, 0x00, 0x04, 0x4B, // .different: sub w0, w3, w4
    0xC0, 0x03, 0x5F, 0xD6, // ret
];

static AARCH64: &[(&str, &[u8])] = &[
    ("memcpy", MEMCPY_AARCH64),
    ("memmove", MEMMOVE_AARCH64),
    ("memset", MEMSET_AARCH64),
    ("memcmp", MEMCMP_AARCH64),
];

pub fn build_executable(
    mir: &MirProgram,
    build_dir: &Path,
    output_path: Option<&Path>,
    opt_level: BuildOptLevel,
    bin: Option<&str>,
) -> Result<(BuildArtifact, Vec<Diagnostic>), String> {
    fs::create_dir_all(build_dir).map_err(|err| format!("failed to create build dir: {err}"))?;

    let executable_path = output_path
        .map(PathBuf::from)
        .unwrap_or_else(|| build_dir.join(default_executable_name()));
    let object_path = build_dir.join("dyn_out.o");

    let mut diagnostics = Vec::new();
    let main_fns = find_main_functions(mir, bin);
    if main_fns.is_empty() {
        diagnostics.push(Diagnostic::error(
            DiagnosticPhase::Backend,
            DiagnosticCode::E5002,
            "no main function found",
        ));
        return Ok((
            BuildArtifact {
                executable_path,
                object_path,
            },
            diagnostics,
        ));
    }
    if main_fns.len() > 1 {
        let names = main_fns
            .iter()
            .map(|(module, _)| format!("'{}'", module.key.module_name))
            .collect::<Vec<_>>()
            .join(", ");
        diagnostics.push(Diagnostic::error(
            DiagnosticPhase::Backend,
            DiagnosticCode::E5002,
            format!("ambiguous entry point: main is defined in multiple modules ({names})"),
        ));
        return Ok((
            BuildArtifact {
                executable_path,
                object_path,
            },
            diagnostics,
        ));
    }

    diagnostics.extend(collect_unsupported_integer_width_diagnostics(mir));
    diagnostics.extend(collect_unsupported_float_width_diagnostics(mir));
    if !diagnostics.is_empty() {
        return Ok((
            BuildArtifact {
                executable_path,
                object_path,
            },
            diagnostics,
        ));
    }

    let mut flag_builder = settings::builder();
    flag_builder
        .set("is_pic", "false")
        .map_err(|err| format!("failed to configure target flags: {err}"))?;
    flag_builder
        .set("enable_llvm_abi_extensions", "true")
        .map_err(|err| format!("failed to configure target flags: {err}"))?;
    if let Some(opt) = opt_level.cranelift_opt_level() {
        flag_builder
            .set("opt_level", opt)
            .map_err(|err| format!("failed to configure optimization level: {err}"))?;
    }
    let isa = cranelift_native::builder()
        .map_err(|err| format!("failed to build host isa: {err}"))?
        .finish(settings::Flags::new(flag_builder))
        .map_err(|err| format!("failed to finalize host isa: {err}"))?;

    let object_builder =
        ObjectBuilder::new(isa, "dyn_module", cranelift_module::default_libcall_names())
            .map_err(|err| format!("failed to build object module: {err}"))?;
    let mut module = ObjectModule::new(object_builder);

    let mut symbols = declare_function_symbols(mir, &mut module)?;
    symbols.global_data_ids = declare_global_data(mir, &mut module)?;
    for mir_module in &mir.modules {
        for function in &mir_module.functions {
            compile_function(
                &mut module,
                function,
                mir_module.module_id.0,
                mir_module.key.module_name == "main" && function.name == "main",
                &symbols,
            )?;
        }
    }

    let object = module.finish();
    let obj_bytes = object
        .emit()
        .map_err(|err| format!("failed to emit object bytes: {err}"))?;

    // Always write the object file (useful for debugging).
    fs::write(&object_path, &obj_bytes)
        .map_err(|err| format!("failed to write object file: {err}"))?;

    // Try direct linking first (no external toolchain needed).
    let has_imports = mir
        .modules
        .iter()
        .any(|module| !module.extern_functions.is_empty());
    if !has_imports {
        let (_, arch, _) = host_object_format();
        if let Some(syscall_code) = syscall_machine_code(arch) {
            let mut runtime_blobs: Vec<(&str, &[u8])> = vec![("dyn_syscall", syscall_code)];
            runtime_blobs.extend_from_slice(mem_blobs(arch));
            if let Some(result) = try_link_direct(&obj_bytes, &runtime_blobs, "main") {
                match result {
                    Ok(exe_bytes) => {
                        fs::write(&executable_path, &exe_bytes)
                            .map_err(|err| format!("failed to write executable: {err}"))?;
                        set_executable(&executable_path)?;
                        return Ok((
                            BuildArtifact {
                                executable_path,
                                object_path,
                            },
                            diagnostics,
                        ));
                    }
                    Err(_) => {
                        // Unsupported relocation or other link error — fall through to
                        // external linker. The external linker error (if any) will be reported.
                    }
                }
            }
        }
    }

    // Fall back: write syscall object and invoke external linker.
    let runtime_syscall_object_path = build_dir.join("dyn_runtime_syscall.o");
    write_runtime_syscall_object(&runtime_syscall_object_path)?;

    link_executable_with_host_toolchain(
        &object_path,
        &runtime_syscall_object_path,
        &executable_path,
    )?;

    Ok((
        BuildArtifact {
            executable_path,
            object_path,
        },
        diagnostics,
    ))
}

fn write_runtime_syscall_object(output_path: &Path) -> Result<(), String> {
    if output_path.exists() {
        return Ok(());
    }
    let (binary_format, architecture, endianness) = host_object_format();
    let code = syscall_machine_code(architecture)
        .ok_or_else(|| format!("no dyn_syscall implementation for {:?}", architecture))?;
    let mut obj = Object::new(binary_format, architecture, endianness);
    let section = obj.section_id(StandardSection::Text);
    let offset = obj.append_section_data(section, code, 16);
    let symbol_id = obj.add_symbol(Symbol {
        name: b"dyn_syscall".to_vec(),
        value: offset,
        size: code.len() as u64,
        kind: SymbolKind::Text,
        scope: SymbolScope::Linkage,
        weak: false,
        section: SymbolSection::Section(section),
        flags: SymbolFlags::None,
    });
    let _ = symbol_id;
    let bytes = obj
        .write()
        .map_err(|err| format!("failed to write syscall object: {err}"))?;
    fs::write(output_path, bytes)
        .map_err(|err| format!("failed to write syscall object file: {err}"))
}

pub(crate) fn host_object_format() -> (BinaryFormat, Architecture, Endianness) {
    let format = if cfg!(target_os = "macos") {
        BinaryFormat::MachO
    } else if cfg!(target_os = "windows") {
        BinaryFormat::Coff
    } else {
        BinaryFormat::Elf
    };
    let (arch, endian) = if cfg!(target_arch = "x86_64") {
        (Architecture::X86_64, Endianness::Little)
    } else if cfg!(target_arch = "aarch64") {
        (Architecture::Aarch64, Endianness::Little)
    } else {
        (Architecture::Unknown, Endianness::Little)
    };
    (format, arch, endian)
}

/// Pre-assembled machine code for `dyn_syscall(n, a1, a2, a3, a4, a5, a6) -> isize`.
///
/// The function receives 7 i64 arguments via the platform calling convention and
/// performs a raw OS syscall, returning the result in the platform return register.
pub(crate) fn syscall_machine_code(arch: Architecture) -> Option<&'static [u8]> {
    match arch {
        Architecture::X86_64 => {
            if cfg!(target_os = "macos") {
                // macOS x86-64: syscall number offset by 0x2000000
                // SysV params:  rdi=n, rsi=a1, rdx=a2, rcx=a3, r8=a4, r9=a5, [rsp+8]=a6
                // macOS syscall: rax=n+0x2000000, rdi=a1, rsi=a2, rdx=a3, r10=a4, r8=a5, r9=a6
                Some(&[
                    0x48, 0x89, 0xF8, // mov rax, rdi
                    0x48, 0x05, 0x00, 0x00, 0x00, 0x02, // add rax, 0x2000000
                    0x48, 0x89, 0xF7, // mov rdi, rsi
                    0x48, 0x89, 0xD6, // mov rsi, rdx
                    0x48, 0x89, 0xCA, // mov rdx, rcx
                    0x4D, 0x89, 0xC2, // mov r10, r8
                    0x4D, 0x89, 0xC8, // mov r8,  r9
                    0x4C, 0x8B, 0x4C, 0x24, 0x08, // mov r9, [rsp+8]
                    0x0F, 0x05, // syscall
                    0xC3, // ret
                ])
            } else {
                // Linux x86-64
                // SysV params:  rdi=n, rsi=a1, rdx=a2, rcx=a3, r8=a4, r9=a5, [rsp+8]=a6
                // Linux syscall: rax=n, rdi=a1, rsi=a2, rdx=a3, r10=a4, r8=a5, r9=a6
                Some(&[
                    0x48, 0x89, 0xF8, // mov rax, rdi
                    0x48, 0x89, 0xF7, // mov rdi, rsi
                    0x48, 0x89, 0xD6, // mov rsi, rdx
                    0x48, 0x89, 0xCA, // mov rdx, rcx
                    0x4D, 0x89, 0xC2, // mov r10, r8
                    0x4D, 0x89, 0xC8, // mov r8,  r9
                    0x4C, 0x8B, 0x4C, 0x24, 0x08, // mov r9, [rsp+8]
                    0x0F, 0x05, // syscall
                    0xC3, // ret
                ])
            }
        }
        Architecture::Aarch64 => {
            if cfg!(target_os = "macos") {
                // macOS aarch64: syscall number in x16, svc #0x80
                // SysV params: x0=n, x1=a1, x2=a2, x3=a3, x4=a4, x5=a5, x6=a6
                Some(&[
                    0xF0, 0x03, 0x00, 0xAA, // mov x16, x0
                    0xE0, 0x03, 0x01, 0xAA, // mov x0,  x1
                    0xE1, 0x03, 0x02, 0xAA, // mov x1,  x2
                    0xE2, 0x03, 0x03, 0xAA, // mov x2,  x3
                    0xE3, 0x03, 0x04, 0xAA, // mov x3,  x4
                    0xE4, 0x03, 0x05, 0xAA, // mov x4,  x5
                    0xE5, 0x03, 0x06, 0xAA, // mov x5,  x6
                    0x01, 0x10, 0x00, 0xD4, // svc #0x80
                    0xC0, 0x03, 0x5F, 0xD6, // ret
                ])
            } else {
                // Linux aarch64: syscall number in x8, svc #0
                // SysV params: x0=n, x1=a1, x2=a2, x3=a3, x4=a4, x5=a5, x6=a6
                Some(&[
                    0xE8, 0x03, 0x00, 0xAA, // mov x8,  x0
                    0xE0, 0x03, 0x01, 0xAA, // mov x0,  x1
                    0xE1, 0x03, 0x02, 0xAA, // mov x1,  x2
                    0xE2, 0x03, 0x03, 0xAA, // mov x2,  x3
                    0xE3, 0x03, 0x04, 0xAA, // mov x3,  x4
                    0xE4, 0x03, 0x05, 0xAA, // mov x4,  x5
                    0xE5, 0x03, 0x06, 0xAA, // mov x5,  x6
                    0x01, 0x00, 0x00, 0xD4, // svc #0
                    0xC0, 0x03, 0x5F, 0xD6, // ret
                ])
            }
        }
        _ => None,
    }
}

fn link_executable_with_host_toolchain(
    object_path: &Path,
    runtime_syscall_object_path: &Path,
    executable_path: &Path,
) -> Result<(), String> {
    let cc_link_result = try_link_with_c_driver_candidates(
        object_path,
        runtime_syscall_object_path,
        executable_path,
    );
    if cc_link_result.is_ok() {
        return Ok(());
    }

    if cfg!(target_os = "linux") {
        let ld_result = link_executable_with_linux_ld(
            object_path,
            runtime_syscall_object_path,
            executable_path,
        );
        if ld_result.is_ok() {
            return Ok(());
        }
        let cc_error = cc_link_result
            .err()
            .unwrap_or_else(|| "cc-like linker failed".to_string());
        let ld_error = ld_result
            .err()
            .unwrap_or_else(|| "ld fallback failed".to_string());
        return Err(format!(
            "failed to link executable with host C toolchain; {cc_error}; {ld_error}"
        ));
    }

    Err(format!(
        "failed to link executable with host C toolchain; {}",
        cc_link_result
            .err()
            .unwrap_or_else(|| "unknown linker driver failure".to_string())
    ))
}

fn try_link_with_c_driver_candidates(
    object_path: &Path,
    runtime_syscall_object_path: &Path,
    executable_path: &Path,
) -> Result<(), String> {
    let mut errors = Vec::new();
    for driver in linker_driver_candidates() {
        let result = if driver == "cl" {
            try_link_with_msvc_cl(object_path, runtime_syscall_object_path, executable_path)
        } else {
            try_link_with_cc_like_driver(
                &driver,
                object_path,
                runtime_syscall_object_path,
                executable_path,
            )
        };
        if result.is_ok() {
            return Ok(());
        }
        errors.push(result.err().unwrap_or_else(|| format!("{driver} failed")));
    }
    if errors.is_empty() {
        return Err("no candidate linker drivers were configured".to_string());
    }
    Err(errors.join("; "))
}

fn try_link_with_cc_like_driver(
    driver: &str,
    object_path: &Path,
    runtime_syscall_object_path: &Path,
    executable_path: &Path,
) -> Result<(), String> {
    let mut command = Command::new(driver);
    command
        .arg(object_path)
        .arg(runtime_syscall_object_path)
        .arg("-o")
        .arg(executable_path);
    if cfg!(target_os = "linux") {
        command.arg("-no-pie");
    }
    let status = command
        .status()
        .map_err(|err| format!("failed to invoke linker driver ({driver}): {err}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!(
            "linker driver ({driver}) failed with status {:?}",
            status.code()
        ))
    }
}

fn try_link_with_msvc_cl(
    object_path: &Path,
    runtime_syscall_object_path: &Path,
    executable_path: &Path,
) -> Result<(), String> {
    if !cfg!(target_os = "windows") {
        return Err("linker driver (cl) is only available on windows targets".to_string());
    }
    let output_arg = format!("/Fe:{}", executable_path.display());
    let status = Command::new("cl")
        .arg("/nologo")
        .arg(object_path)
        .arg(runtime_syscall_object_path)
        .arg(output_arg)
        .status()
        .map_err(|err| format!("failed to invoke linker driver (cl): {err}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!(
            "linker driver (cl) failed with status {:?}",
            status.code()
        ))
    }
}

fn linker_driver_candidates() -> Vec<String> {
    if let Ok(custom) = std::env::var("DYN_LINKER") {
        let parsed = custom
            .split(',')
            .map(str::trim)
            .filter(|part| !part.is_empty())
            .map(ToString::to_string)
            .collect::<Vec<_>>();
        if !parsed.is_empty() {
            return parsed;
        }
    }

    if cfg!(target_os = "windows") {
        vec![
            "cl".to_string(),
            "clang".to_string(),
            "gcc".to_string(),
            "cc".to_string(),
        ]
    } else {
        vec!["cc".to_string(), "clang".to_string(), "gcc".to_string()]
    }
}

fn set_executable(path: &Path) -> Result<(), String> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(path)
            .map_err(|e| format!("failed to read permissions: {e}"))?
            .permissions();
        perms.set_mode(0o755);
        fs::set_permissions(path, perms)
            .map_err(|e| format!("failed to set executable permissions: {e}"))?;
    }
    #[cfg(not(unix))]
    let _ = path;
    Ok(())
}

fn default_executable_name() -> &'static str {
    if cfg!(target_os = "windows") {
        "dyn_out.exe"
    } else {
        "dyn_out"
    }
}

fn link_executable_with_linux_ld(
    object_path: &Path,
    runtime_syscall_object_path: &Path,
    executable_path: &Path,
) -> Result<(), String> {
    let crt_dirs = [
        "/usr/lib",
        "/usr/lib64",
        "/usr/lib/x86_64-linux-gnu",
        "/lib",
        "/lib64",
        "/lib/x86_64-linux-gnu",
    ];
    let linker_paths = [
        "/lib64/ld-linux-x86-64.so.2",
        "/usr/lib/ld-linux-x86-64.so.2",
        "/lib/ld-linux-x86-64.so.2",
        "/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2",
    ];

    let Some(crt_dir) = crt_dirs.iter().find(|dir| {
        Path::new(dir).join("crt1.o").exists()
            && Path::new(dir).join("crti.o").exists()
            && Path::new(dir).join("crtn.o").exists()
    }) else {
        return Err("failed to locate crt startup objects for linker".to_string());
    };
    let Some(dynamic_linker) = linker_paths.iter().find(|path| Path::new(path).exists()) else {
        return Err("failed to locate system dynamic linker".to_string());
    };

    let status = Command::new("ld")
        .arg("-o")
        .arg(executable_path)
        .arg(Path::new(crt_dir).join("crt1.o"))
        .arg(Path::new(crt_dir).join("crti.o"))
        .arg(object_path)
        .arg(runtime_syscall_object_path)
        .arg(format!("-L{crt_dir}"))
        .arg("-lc")
        .arg(Path::new(crt_dir).join("crtn.o"))
        .arg("-dynamic-linker")
        .arg(dynamic_linker)
        .status()
        .map_err(|err| format!("failed to invoke linker (ld): {err}"))?;
    if !status.success() {
        return Err("linker failed to produce executable".to_string());
    }

    Ok(())
}

fn find_main_functions<'a>(
    mir: &'a MirProgram,
    bin: Option<&str>,
) -> Vec<(&'a MirModule, &'a MirFunction)> {
    let bin_dir = bin.map(PathBuf::from);
    mir.modules
        .iter()
        .filter(|module| {
            bin_dir
                .as_ref()
                .map(|d| &module.key.directory == d)
                .unwrap_or(true)
        })
        .flat_map(|module| {
            module
                .functions
                .iter()
                .filter(|f| f.name == "main")
                .map(move |f| (module, f))
        })
        .collect()
}

fn collect_unsupported_float_width_diagnostics(mir: &MirProgram) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    for mir_module in &mir.modules {
        for function in &mir_module.functions {
            let mut reasons = Vec::new();
            if function
                .return_type
                .as_deref()
                .and_then(max_float_bits_in_type_text)
                .map(|bits| bits > 64)
                .unwrap_or(false)
            {
                reasons.push("return type".to_string());
            }
            if function.param_type_hints.iter().flatten().any(|hint| {
                max_float_bits_in_type_text(hint)
                    .map(|bits| bits > 64)
                    .unwrap_or(false)
            }) {
                reasons.push("parameter type hint".to_string());
            }
            if function
                .param_types
                .iter()
                .any(mir_type_uses_unsupported_float)
            {
                reasons.push("parameter type".to_string());
            }
            if function_uses_unsupported_float_values(function) {
                reasons.push("MIR value type".to_string());
            }

            if reasons.is_empty() {
                continue;
            }
            reasons.sort();
            reasons.dedup();
            diagnostics.push(Diagnostic::error(
                DiagnosticPhase::Backend,
                DiagnosticCode::E5002,
                format!(
                    "backend currently supports float widths up to f64; function `{}` uses unsupported float width ({})",
                    function.name,
                    reasons.join(", ")
                ),
            ));
        }
    }
    diagnostics
}

fn collect_unsupported_integer_width_diagnostics(mir: &MirProgram) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    for mir_module in &mir.modules {
        for function in &mir_module.functions {
            let mut reasons = Vec::new();
            if function
                .return_type
                .as_deref()
                .and_then(max_int_bits_in_type_text)
                .map(|bits| bits == 0 || bits > 128)
                .unwrap_or(false)
            {
                reasons.push("return type".to_string());
            }
            if function.param_type_hints.iter().flatten().any(|hint| {
                max_int_bits_in_type_text(hint)
                    .map(|bits| bits == 0 || bits > 128)
                    .unwrap_or(false)
            }) {
                reasons.push("parameter type hint".to_string());
            }
            if function
                .param_types
                .iter()
                .any(mir_type_uses_unsupported_integer)
            {
                reasons.push("parameter type".to_string());
            }
            if function_uses_unsupported_integer_values(function) {
                reasons.push("MIR value type".to_string());
            }

            if reasons.is_empty() {
                continue;
            }
            reasons.sort();
            reasons.dedup();
            diagnostics.push(Diagnostic::error(
                DiagnosticPhase::Backend,
                DiagnosticCode::E5002,
                format!(
                    "backend currently supports integer widths from i1/u1 up to i128/u128; function `{}` uses unsupported integer width ({})",
                    function.name,
                    reasons.join(", ")
                ),
            ));
        }
    }
    diagnostics
}

fn function_uses_unsupported_float_values(function: &MirFunction) -> bool {
    for block in &function.blocks {
        for instr in &block.instructions {
            match instr {
                MirInstr::Eval { ty, value, .. } => {
                    if mir_type_uses_unsupported_float(ty)
                        || mir_value_uses_unsupported_float(value)
                    {
                        return true;
                    }
                }
                MirInstr::Phi { ty, .. } => {
                    if mir_type_uses_unsupported_float(ty) {
                        return true;
                    }
                }
            }
        }
    }
    false
}

fn function_uses_unsupported_integer_values(function: &MirFunction) -> bool {
    for block in &function.blocks {
        for instr in &block.instructions {
            match instr {
                MirInstr::Eval { ty, value, .. } => {
                    if mir_type_uses_unsupported_integer(ty)
                        || mir_value_uses_unsupported_integer(value)
                    {
                        return true;
                    }
                }
                MirInstr::Phi { ty, .. } => {
                    if mir_type_uses_unsupported_integer(ty) {
                        return true;
                    }
                }
            }
        }
    }
    false
}

fn mir_value_uses_unsupported_float(value: &MirValue) -> bool {
    match value {
        MirValue::Cast { target, .. } => mir_type_uses_unsupported_float(target),
        _ => false,
    }
}

fn mir_value_uses_unsupported_integer(value: &MirValue) -> bool {
    match value {
        MirValue::Cast { target, .. } => mir_type_uses_unsupported_integer(target),
        _ => false,
    }
}

fn mir_type_uses_unsupported_float(ty: &MirValueType) -> bool {
    matches!(ty, MirValueType::Float { bits } if *bits > 64)
}

fn mir_type_uses_unsupported_integer(ty: &MirValueType) -> bool {
    matches!(ty, MirValueType::Int { bits, .. } if *bits == 0 || *bits > 128)
}

fn max_float_bits_in_type_text(text: &str) -> Option<u16> {
    text.split(|ch: char| !(ch.is_ascii_alphanumeric() || ch == '_'))
        .filter_map(|token| token.strip_prefix('f'))
        .filter(|digits| !digits.is_empty())
        .filter_map(|digits| digits.parse::<u16>().ok())
        .max()
}

fn max_int_bits_in_type_text(text: &str) -> Option<u16> {
    text.split(|ch: char| !(ch.is_ascii_alphanumeric() || ch == '_'))
        .filter_map(|token| {
            if token == "isize" || token == "usize" {
                return Some(64);
            }
            let digits = token
                .strip_prefix('i')
                .or_else(|| token.strip_prefix('u'))?;
            if digits.is_empty() {
                return None;
            }
            digits.parse::<u16>().ok()
        })
        .max()
}

pub(super) fn build_nominal_aggregate_layouts(
    mir: &MirProgram,
    pointer_ty: Type,
) -> BTreeMap<String, AggregateLayout> {
    let nominal_type_literals = collect_nominal_type_literals(mir);
    let mut layouts = BTreeMap::new();
    let mut visiting = BTreeSet::new();
    let names = nominal_type_literals.keys().cloned().collect::<Vec<_>>();
    for name in names {
        let _ = resolve_nominal_aggregate_layout(
            &name,
            &nominal_type_literals,
            pointer_ty,
            &mut layouts,
            &mut visiting,
        );
    }
    layouts
}

fn collect_nominal_type_literals(mir: &MirProgram) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    for module in &mir.modules {
        for function in &module.functions {
            if let Some(type_literal) = returned_type_literal(function) {
                out.entry(function.name.clone()).or_insert(type_literal);
            }
        }
    }
    out
}

fn returned_type_literal(function: &MirFunction) -> Option<String> {
    let mut value_defs = BTreeMap::<MirValueId, MirValue>::new();
    for block in &function.blocks {
        for instruction in &block.instructions {
            if let MirInstr::Eval { dest, value, .. } = instruction {
                value_defs.insert(*dest, value.clone());
            }
        }
    }

    let mut returned = None::<String>;
    for block in &function.blocks {
        let Some(MirTerminator::Return(Some(value_id))) = &block.terminator else {
            continue;
        };
        let type_name = resolve_type_literal_value(*value_id, &value_defs, 0)?;
        match &returned {
            Some(existing) if existing != &type_name => return None,
            Some(_) => {}
            None => returned = Some(type_name),
        }
    }
    returned
}

fn resolve_type_literal_value(
    value_id: MirValueId,
    value_defs: &BTreeMap<MirValueId, MirValue>,
    depth: usize,
) -> Option<String> {
    if depth > 16 {
        return None;
    }
    match value_defs.get(&value_id) {
        Some(MirValue::TypeLiteral(name)) => Some(name.clone()),
        Some(MirValue::LocalSet { value, .. }) | Some(MirValue::Assign { value, .. }) => {
            resolve_type_literal_value(*value, value_defs, depth + 1)
        }
        _ => None,
    }
}

pub(super) fn parse_aggregate_layout(
    type_hint: Option<&str>,
    nominal_aggregate_layouts: &BTreeMap<String, AggregateLayout>,
    pointer_ty: Type,
) -> Option<AggregateLayout> {
    let ty = normalize_runtime_type_text(type_hint?);
    if ty.is_empty() {
        return None;
    }
    if ty.starts_with("struct{") {
        return parse_struct_layout(&ty, nominal_aggregate_layouts, pointer_ty);
    }
    let nominal = nominal_base_name(&ty)?;
    nominal_aggregate_layouts
        .get(&nominal)
        .cloned()
        .or_else(|| parse_struct_layout(&ty, nominal_aggregate_layouts, pointer_ty))
}

fn resolve_nominal_aggregate_layout(
    name: &str,
    nominal_type_literals: &BTreeMap<String, String>,
    pointer_ty: Type,
    cache: &mut BTreeMap<String, AggregateLayout>,
    visiting: &mut BTreeSet<String>,
) -> Option<AggregateLayout> {
    if let Some(layout) = cache.get(name) {
        return Some(layout.clone());
    }
    if !visiting.insert(name.to_string()) {
        return None;
    }
    let Some(type_text) = nominal_type_literals.get(name) else {
        visiting.remove(name);
        return None;
    };
    let layout = resolve_layout_for_type_text(
        type_text,
        nominal_type_literals,
        pointer_ty,
        cache,
        visiting,
    );
    visiting.remove(name);
    if let Some(layout) = layout.clone() {
        cache.insert(name.to_string(), layout);
    }
    layout
}

fn resolve_layout_for_type_text(
    type_text: &str,
    nominal_type_literals: &BTreeMap<String, String>,
    pointer_ty: Type,
    cache: &mut BTreeMap<String, AggregateLayout>,
    visiting: &mut BTreeSet<String>,
) -> Option<AggregateLayout> {
    let normalized = normalize_runtime_type_text(type_text);
    if normalized.starts_with("struct{") {
        return parse_struct_layout_with_nominals(
            &normalized,
            nominal_type_literals,
            pointer_ty,
            cache,
            visiting,
        );
    }
    let nominal = nominal_base_name(&normalized)?;
    resolve_nominal_aggregate_layout(&nominal, nominal_type_literals, pointer_ty, cache, visiting)
}

fn parse_struct_layout(
    type_text: &str,
    nominal_aggregate_layouts: &BTreeMap<String, AggregateLayout>,
    pointer_ty: Type,
) -> Option<AggregateLayout> {
    if !type_text.starts_with("struct{") || !type_text.ends_with('}') {
        return None;
    }
    let inner = &type_text["struct{".len()..type_text.len() - 1];
    let mut fields = BTreeMap::new();
    let mut aggregate_fields = BTreeMap::new();
    let mut ordered = Vec::new();
    let mut scalar_leaves = Vec::new();
    let mut size = 0u32;
    let mut max_align = 1u32;

    for field in split_top_level(inner, ',') {
        let field = field.trim();
        if field.is_empty() {
            continue;
        }
        let Some(colon_idx) = top_level_separator(field, ':') else {
            continue;
        };
        let name = field[..colon_idx].trim().to_string();
        let ty_text = field[colon_idx + 1..].trim();
        let nested = parse_aggregate_layout(Some(ty_text), nominal_aggregate_layouts, pointer_ty);
        if let Some(nested) = nested {
            let field_align = nested.align.max(1);
            max_align = max_align.max(field_align);
            size = align_to(size, field_align);
            let offset = size as i32;
            size = size.saturating_add(nested.size.max(1));
            for (leaf_ty, leaf_offset) in &nested.scalar_leaves {
                scalar_leaves.push((*leaf_ty, offset + *leaf_offset));
            }
            aggregate_fields.insert(name, (offset, Box::new(nested)));
        } else {
            let field_ty = scalar_type_for_layout(ty_text, pointer_ty);
            let field_align = ((field_ty.bits() / 8).max(1)) as u32;
            max_align = max_align.max(field_align);
            size = align_to(size, field_align);
            let offset = size as i32;
            size = size.saturating_add(field_align);
            fields.insert(name, (field_ty, offset));
            ordered.push((field_ty, offset));
            scalar_leaves.push((field_ty, offset));
        }
    }

    size = align_to(size, max_align).max(1);
    Some(AggregateLayout {
        fields,
        aggregate_fields,
        ordered,
        scalar_leaves,
        size,
        align: max_align,
    })
}

fn parse_struct_layout_with_nominals(
    type_text: &str,
    nominal_type_literals: &BTreeMap<String, String>,
    pointer_ty: Type,
    cache: &mut BTreeMap<String, AggregateLayout>,
    visiting: &mut BTreeSet<String>,
) -> Option<AggregateLayout> {
    if !type_text.starts_with("struct{") || !type_text.ends_with('}') {
        return None;
    }
    let inner = &type_text["struct{".len()..type_text.len() - 1];
    let mut fields = BTreeMap::new();
    let mut aggregate_fields = BTreeMap::new();
    let mut ordered = Vec::new();
    let mut scalar_leaves = Vec::new();
    let mut size = 0u32;
    let mut max_align = 1u32;

    for field in split_top_level(inner, ',') {
        let field = field.trim();
        if field.is_empty() {
            continue;
        }
        let Some(colon_idx) = top_level_separator(field, ':') else {
            continue;
        };
        let name = field[..colon_idx].trim().to_string();
        let ty_text = field[colon_idx + 1..].trim();
        let nested = resolve_layout_for_type_text(
            ty_text,
            nominal_type_literals,
            pointer_ty,
            cache,
            visiting,
        );
        if let Some(nested) = nested {
            let field_align = nested.align.max(1);
            max_align = max_align.max(field_align);
            size = align_to(size, field_align);
            let offset = size as i32;
            size = size.saturating_add(nested.size.max(1));
            for (leaf_ty, leaf_offset) in &nested.scalar_leaves {
                scalar_leaves.push((*leaf_ty, offset + *leaf_offset));
            }
            aggregate_fields.insert(name, (offset, Box::new(nested)));
        } else {
            let field_ty = scalar_type_for_layout(ty_text, pointer_ty);
            let field_align = ((field_ty.bits() / 8).max(1)) as u32;
            max_align = max_align.max(field_align);
            size = align_to(size, field_align);
            let offset = size as i32;
            size = size.saturating_add(field_align);
            fields.insert(name, (field_ty, offset));
            ordered.push((field_ty, offset));
            scalar_leaves.push((field_ty, offset));
        }
    }

    size = align_to(size, max_align).max(1);
    Some(AggregateLayout {
        fields,
        aggregate_fields,
        ordered,
        scalar_leaves,
        size,
        align: max_align,
    })
}

fn split_top_level(input: &str, delimiter: char) -> Vec<String> {
    let mut out = Vec::new();
    let mut start = 0usize;
    let mut paren = 0i32;
    let mut brace = 0i32;
    let mut bracket = 0i32;
    for (idx, ch) in input.char_indices() {
        match ch {
            '(' => paren += 1,
            ')' => paren -= 1,
            '{' => brace += 1,
            '}' => brace -= 1,
            '[' => bracket += 1,
            ']' => bracket -= 1,
            _ => {}
        }
        if ch == delimiter && paren == 0 && brace == 0 && bracket == 0 {
            out.push(input[start..idx].to_string());
            start = idx + ch.len_utf8();
        }
    }
    out.push(input[start..].to_string());
    out
}

fn top_level_separator(input: &str, separator: char) -> Option<usize> {
    let mut paren = 0i32;
    let mut brace = 0i32;
    let mut bracket = 0i32;
    for (idx, ch) in input.char_indices() {
        match ch {
            '(' => paren += 1,
            ')' => paren -= 1,
            '{' => brace += 1,
            '}' => brace -= 1,
            '[' => bracket += 1,
            ']' => bracket -= 1,
            _ => {}
        }
        if ch == separator && paren == 0 && brace == 0 && bracket == 0 {
            return Some(idx);
        }
    }
    None
}

fn normalize_runtime_type_text(text: &str) -> String {
    let mut ty = text.trim().to_string();
    if let Some(stripped) = ty.strip_prefix('?') {
        ty = stripped.trim().to_string();
    }
    if let Some((ok, _errs)) = ty.split_once('!') {
        ty = ok.trim().to_string();
    }
    ty
}

fn nominal_base_name(type_text: &str) -> Option<String> {
    let trimmed = type_text.trim();
    if trimmed.is_empty() {
        return None;
    }
    let mut end = 0usize;
    for (idx, ch) in trimmed.char_indices() {
        if ch.is_ascii_alphanumeric() || ch == '_' {
            end = idx + ch.len_utf8();
        } else {
            break;
        }
    }
    if end == 0 {
        return None;
    }
    let head = &trimmed[..end];
    let tail = trimmed[end..].trim_start();
    if tail.is_empty() || tail.starts_with('(') {
        Some(head.to_string())
    } else {
        None
    }
}

fn scalar_type_for_layout(type_text: &str, pointer_ty: Type) -> Type {
    let ty = normalize_runtime_type_text(type_text);
    if ty.starts_with('*')
        || ty.starts_with("[]")
        || ty.starts_with("[?")
        || ty.starts_with("fn/")
        || ty.starts_with("fn(")
    {
        return pointer_ty;
    }

    if let Some((_, bits)) = parse_int_type_bits(&ty) {
        return int_carrier_type_for_bits(bits);
    }
    if let Some(bits) = parse_float_type_bits(&ty) {
        return float_carrier_type_for_bits(bits);
    }

    match ty.as_str() {
        "u1" => I8,
        "type" | "any" | "opaque" => I64,
        _ => pointer_ty,
    }
}

fn parse_int_type_bits(type_name: &str) -> Option<(bool, u16)> {
    if type_name == "isize" {
        return Some((true, 64));
    }
    if type_name == "usize" {
        return Some((false, 64));
    }

    let (signed, rest) = if let Some(bits) = type_name.strip_prefix('i') {
        (true, bits)
    } else if let Some(bits) = type_name.strip_prefix('u') {
        (false, bits)
    } else {
        return None;
    };

    if rest.is_empty() {
        return None;
    }
    let bits = rest.parse::<u16>().ok()?;
    if (1..=128).contains(&bits) {
        Some((signed, bits))
    } else {
        None
    }
}

fn parse_float_type_bits(type_name: &str) -> Option<u16> {
    let bits = type_name.strip_prefix('f')?;
    if bits.is_empty() {
        return None;
    }
    match bits.parse::<u16>().ok()? {
        32 | 64 => Some(bits.parse::<u16>().ok()?),
        _ => None,
    }
}

fn int_carrier_type_for_bits(bits: u16) -> Type {
    match bits {
        0..=8 => I8,
        9..=16 => I16,
        17..=32 => I32,
        33..=64 => I64,
        _ => I128,
    }
}

fn float_carrier_type_for_bits(bits: u16) -> Type {
    if bits <= 32 {
        F32
    } else if bits <= 64 {
        F64
    } else if bits <= 128 {
        I64
    } else {
        F64
    }
}

const PAGE: u64 = 0x1000;
const ELF_BASE: u64 = 0x400000;

fn align_up(v: u64, a: u64) -> u64 {
    (v + a - 1) & !(a - 1)
}

/// Attempt to produce a complete executable in memory without an external linker.
///
/// Returns `None` when the current host target is not yet supported — the caller
/// should fall back to an external linker in that case.
/// Returns `Some(Err(_))` when the target is supported but linking failed (e.g. an
/// unknown relocation type was encountered).
pub(super) fn try_link_direct(
    cranelift_obj: &[u8],
    runtime_blobs: &[(&str, &[u8])],
    entry_symbol: &str,
) -> Option<Result<Vec<u8>, String>> {
    let (fmt, arch, _) = host_object_format();
    match (fmt, arch) {
        (BinaryFormat::Elf, Architecture::X86_64) => Some(link_elf(
            cranelift_obj,
            runtime_blobs,
            entry_symbol,
            ElfArch::X86_64,
        )),
        (BinaryFormat::Elf, Architecture::Aarch64) => Some(link_elf(
            cranelift_obj,
            runtime_blobs,
            entry_symbol,
            ElfArch::Aarch64,
        )),
        (BinaryFormat::Coff, Architecture::X86_64) => {
            Some(link_pe_x86_64(cranelift_obj, runtime_blobs, entry_symbol))
        }
        (BinaryFormat::Coff, Architecture::Aarch64) => {
            Some(link_pe_arm64(cranelift_obj, runtime_blobs, entry_symbol))
        }
        (BinaryFormat::MachO, Architecture::X86_64) => Some(link_macho(
            cranelift_obj,
            runtime_blobs,
            entry_symbol,
            false,
        )),
        (BinaryFormat::MachO, Architecture::Aarch64) => {
            Some(link_macho(cranelift_obj, runtime_blobs, entry_symbol, true))
        }
        // Windows aarch64: not yet implemented — fall back to external linker
        _ => None,
    }
}

// ---------------------------------------------------------------------------
// Architecture-specific parameters for the shared ELF linker
// ---------------------------------------------------------------------------

enum ElfArch {
    X86_64,
    Aarch64,
}

impl ElfArch {
    fn em_machine(&self) -> u16 {
        match self {
            ElfArch::X86_64 => 62,   // EM_X86_64
            ElfArch::Aarch64 => 183, // EM_AARCH64
        }
    }

    fn start_size(&self) -> u64 {
        match self {
            // call + mov rdi,rax + mov eax,60 + syscall = 15 bytes
            ElfArch::X86_64 => 15,
            // bl + mov x8,#93 + svc #0 = 12 bytes
            ElfArch::Aarch64 => 12,
        }
    }

    fn write_start(&self, buf: &mut [u8], entry_addr: u64, start_vaddr: u64) {
        match self {
            ElfArch::X86_64 => write_start_x86_64_linux(buf, entry_addr, start_vaddr),
            ElfArch::Aarch64 => write_start_aarch64_linux(buf, entry_addr, start_vaddr),
        }
    }

    fn apply_reloc(
        &self,
        buf: &mut [u8],
        offset: usize,
        flags: RelocationFlags,
        sym_addr: u64,
        addend: i64,
        reloc_addr: u64,
    ) -> Result<(), String> {
        match self {
            ElfArch::X86_64 => apply_reloc_x86_64(buf, offset, flags, sym_addr, addend, reloc_addr),
            ElfArch::Aarch64 => {
                apply_reloc_aarch64(buf, offset, flags, sym_addr, addend, reloc_addr)
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Section collected from a parsed object
// ---------------------------------------------------------------------------

struct Section {
    #[allow(dead_code)]
    name: String,
    #[allow(dead_code)]
    kind: SectionKind,
    data: Vec<u8>,
    align: u64,
    orig_idx: usize,
    /// Byte offset of this section within its merged segment buffer.
    seg_offset: u64,
    /// Virtual address assigned during layout.
    vaddr: u64,
}

// ---------------------------------------------------------------------------
// Shared ELF linker (x86-64 and aarch64)
// ---------------------------------------------------------------------------

fn link_elf(
    obj_bytes: &[u8],
    runtime_blobs: &[(&str, &[u8])],
    entry_sym: &str,
    arch: ElfArch,
) -> Result<Vec<u8>, String> {
    let obj =
        ObjFile::parse(obj_bytes).map_err(|e| format!("failed to parse cranelift object: {e}"))?;

    // ---- Collect and categorise sections ----
    let mut text_secs: Vec<Section> = Vec::new();
    let mut data_secs: Vec<Section> = Vec::new();

    for sec in obj.sections() {
        let name = sec.name().unwrap_or("").to_string();
        let raw = sec
            .data()
            .map_err(|e| format!("section '{name}' data error: {e}"))?;
        let align = sec.align().max(1);
        let idx = sec.index().0;

        match sec.kind() {
            SectionKind::Text => {
                text_secs.push(Section {
                    name,
                    kind: SectionKind::Text,
                    data: raw.to_vec(),
                    align,
                    orig_idx: idx,
                    seg_offset: 0,
                    vaddr: 0,
                });
            }
            SectionKind::Data | SectionKind::ReadOnlyData => {
                data_secs.push(Section {
                    name,
                    kind: sec.kind(),
                    data: raw.to_vec(),
                    align,
                    orig_idx: idx,
                    seg_offset: 0,
                    vaddr: 0,
                });
            }
            SectionKind::UninitializedData => {
                // BSS: represent as explicit zeros so we can write them to the file.
                // (p_memsz > p_filesz for true BSS optimisation is a future improvement.)
                data_secs.push(Section {
                    name,
                    kind: SectionKind::UninitializedData,
                    data: vec![0u8; raw.len()],
                    align,
                    orig_idx: idx,
                    seg_offset: 0,
                    vaddr: 0,
                });
            }
            _ => {} // metadata sections — skip
        }
    }

    // ---- Layout: text segment ----
    //
    //   File offset 0x000 : ELF header + program headers (not in any PT_LOAD)
    //   File offset PAGE  : text segment   →  vaddr ELF_BASE + PAGE
    //   File offset next  : data segment   →  vaddr ELF_BASE + next
    //
    let text_file_off: u64 = PAGE;
    let text_vaddr: u64 = ELF_BASE + text_file_off;

    let mut cursor: u64 = 0;
    for s in &mut text_secs {
        cursor = align_up(cursor, s.align);
        s.seg_offset = cursor;
        s.vaddr = text_vaddr + cursor;
        cursor += s.data.len() as u64;
    }

    // runtime blobs (syscall stub etc.) immediately after compiled code
    let blob_align: u64 = match arch {
        ElfArch::Aarch64 => 4,
        _ => 16,
    };
    let blob_placements: Vec<(&str, u64, usize)> = {
        let mut placements = Vec::new();
        for &(name, bytes) in runtime_blobs {
            cursor = align_up(cursor, blob_align);
            placements.push((name, cursor, bytes.len()));
            cursor += bytes.len() as u64;
        }
        placements
    };

    // _start stub at the very end of text
    let start_align = match arch {
        ElfArch::Aarch64 => 4, // aarch64 instructions are 4-byte aligned
        _ => 16,
    };
    cursor = align_up(cursor, start_align);
    let start_seg_off = cursor;
    let start_vaddr = text_vaddr + cursor;
    let start_size = arch.start_size();
    cursor += start_size;

    let text_total = cursor;

    // ---- Layout: data segment ----
    let data_file_off = align_up(text_file_off + text_total, PAGE);
    let data_vaddr: u64 = ELF_BASE + data_file_off;

    cursor = 0;
    for s in &mut data_secs {
        cursor = align_up(cursor, s.align);
        s.seg_offset = cursor;
        s.vaddr = data_vaddr + cursor;
        cursor += s.data.len() as u64;
    }
    let data_total = cursor;
    let has_data = data_total > 0;

    // ---- Build symbol map ----
    let mut syms: BTreeMap<String, u64> = BTreeMap::new();
    for &(name, seg_off, _) in &blob_placements {
        syms.insert(name.to_string(), text_vaddr + seg_off);
    }
    syms.insert("_start".to_string(), start_vaddr);

    for sym in obj.symbols() {
        let Ok(name) = sym.name() else { continue };
        if name.is_empty() {
            continue;
        }
        let sec_idx = match sym.section() {
            object::read::SymbolSection::Section(i) => i.0,
            _ => continue,
        };
        let offset = sym.address();
        let addr = text_secs
            .iter()
            .find(|s| s.orig_idx == sec_idx)
            .map(|s| s.vaddr + offset)
            .or_else(|| {
                data_secs
                    .iter()
                    .find(|s| s.orig_idx == sec_idx)
                    .map(|s| s.vaddr + offset)
            });
        if let Some(a) = addr {
            syms.insert(name.to_string(), a);
        }
    }

    // Find entry
    let entry_addr = *syms
        .get(entry_sym)
        .ok_or_else(|| format!("entry symbol '{entry_sym}' not found in object"))?;

    // ---- Merge section data into segment buffers ----
    let mut text_buf = vec![0u8; text_total as usize];
    for s in &text_secs {
        let end = s.seg_offset as usize + s.data.len();
        text_buf[s.seg_offset as usize..end].copy_from_slice(&s.data);
    }
    // runtime blobs
    for (&(_, bytes), &(_, seg_off, len)) in runtime_blobs.iter().zip(blob_placements.iter()) {
        text_buf[seg_off as usize..seg_off as usize + len].copy_from_slice(bytes);
    }
    // _start stub (written after we know entry_addr)
    arch.write_start(
        &mut text_buf[start_seg_off as usize..],
        entry_addr,
        start_vaddr,
    );

    let mut data_buf = vec![0u8; data_total as usize];
    for s in &data_secs {
        let end = s.seg_offset as usize + s.data.len();
        data_buf[s.seg_offset as usize..end].copy_from_slice(&s.data);
    }

    // ---- Resolve relocations ----
    for sec in obj.sections() {
        let sec_idx = sec.index().0;
        let (is_text, seg_off, sec_vaddr) =
            if let Some(s) = text_secs.iter().find(|s| s.orig_idx == sec_idx) {
                (true, s.seg_offset, s.vaddr)
            } else if let Some(s) = data_secs.iter().find(|s| s.orig_idx == sec_idx) {
                (false, s.seg_offset, s.vaddr)
            } else {
                continue;
            };

        for (reloc_off, reloc) in sec.relocations() {
            let sym_addr = match reloc.target() {
                RelocationTarget::Symbol(sym_idx) => {
                    let sym = obj
                        .symbol_by_index(sym_idx)
                        .map_err(|e| format!("bad relocation symbol index: {e}"))?;
                    let name = sym.name().unwrap_or("");
                    *syms
                        .get(name)
                        .ok_or_else(|| format!("undefined symbol '{name}'"))?
                }
                RelocationTarget::Section(target_sec_idx) => {
                    let tidx = target_sec_idx.0;
                    text_secs
                        .iter()
                        .find(|s| s.orig_idx == tidx)
                        .map(|s| s.vaddr)
                        .or_else(|| {
                            data_secs
                                .iter()
                                .find(|s| s.orig_idx == tidx)
                                .map(|s| s.vaddr)
                        })
                        .ok_or_else(|| {
                            format!("section relocation target section {tidx} not found")
                        })?
                }
                _ => continue,
            };

            let size = reloc.size();
            let addend = if reloc.has_implicit_addend() {
                // REL format: addend embedded in the target bytes
                let off = (seg_off + reloc_off) as usize;
                match size {
                    32 => i32::from_le_bytes(text_buf[off..off + 4].try_into().unwrap()) as i64,
                    64 => i64::from_le_bytes(text_buf[off..off + 8].try_into().unwrap()),
                    _ => 0,
                }
            } else {
                reloc.addend()
            };

            let patch_loc = (seg_off + reloc_off) as usize;
            let reloc_addr = sec_vaddr + reloc_off;
            let buf = if is_text {
                &mut text_buf
            } else {
                &mut data_buf
            };

            arch.apply_reloc(buf, patch_loc, reloc.flags(), sym_addr, addend, reloc_addr)?;
        }
    }

    // ---- Write ELF executable ----
    let num_phdrs: u64 = if has_data { 2 } else { 1 };
    let text_file_end = text_file_off + text_total;
    let data_file_end = if has_data {
        data_file_off + data_total
    } else {
        text_file_end
    };
    let file_size = data_file_end;

    let mut file = vec![0u8; file_size as usize];

    // ELF64 header (64 bytes)
    {
        let h = &mut file[0..64];
        h[0..4].copy_from_slice(b"\x7fELF");
        h[4] = 2; // ELFCLASS64
        h[5] = 1; // ELFDATA2LSB
        h[6] = 1; // EV_CURRENT
        h[7] = 0; // ELFOSABI_NONE
                  // h[8..16] = ABI version + padding (already 0)
        put_u16(&mut h[16..], 2); // ET_EXEC
        put_u16(&mut h[18..], arch.em_machine());
        put_u32(&mut h[20..], 1); // e_version
        put_u64(&mut h[24..], start_vaddr); // e_entry (_start)
        put_u64(&mut h[32..], 64); // e_phoff (program headers right after)
        put_u64(&mut h[40..], 0); // e_shoff (no section headers)
        put_u32(&mut h[48..], 0); // e_flags
        put_u16(&mut h[52..], 64); // e_ehsize
        put_u16(&mut h[54..], 56); // e_phentsize
        put_u16(&mut h[56..], num_phdrs as u16); // e_phnum
        put_u16(&mut h[58..], 64); // e_shentsize
        put_u16(&mut h[60..], 0); // e_shnum
        put_u16(&mut h[62..], 0); // e_shstrndx
    }

    // Text PT_LOAD (RX)  — offset 64, size 56
    write_phdr(
        &mut file[64..120],
        text_file_off,
        text_vaddr,
        text_total,
        text_total,
        5, // PF_R | PF_X
        PAGE,
    );

    // Data PT_LOAD (RW)  — offset 120, size 56
    if has_data {
        write_phdr(
            &mut file[120..176],
            data_file_off,
            data_vaddr,
            data_total,
            data_total,
            6, // PF_R | PF_W
            PAGE,
        );
    }

    // Copy segment bytes
    file[text_file_off as usize..text_file_end as usize].copy_from_slice(&text_buf);
    if has_data {
        file[data_file_off as usize..(data_file_off + data_total) as usize]
            .copy_from_slice(&data_buf);
    }

    Ok(file)
}

// ---------------------------------------------------------------------------
// _start stub for x86-64 Linux
//   call <entry>       e8 XX XX XX XX   (5)
//   mov rdi, rax       48 89 c7         (3)
//   mov eax, 60        b8 3c 00 00 00   (5)
//   syscall            0f 05            (2)
//                                      = 15 bytes total
// ---------------------------------------------------------------------------
fn write_start_x86_64_linux(buf: &mut [u8], entry_addr: u64, start_vaddr: u64) {
    let rel = ((entry_addr as i64) - (start_vaddr as i64 + 5)) as i32;
    buf[0] = 0xe8;
    buf[1..5].copy_from_slice(&rel.to_le_bytes());
    buf[5] = 0x48;
    buf[6] = 0x89;
    buf[7] = 0xc7;
    buf[8] = 0xb8;
    buf[9] = 60;
    buf[10] = 0;
    buf[11] = 0;
    buf[12] = 0;
    buf[13] = 0x0f;
    buf[14] = 0x05;
}

// ---------------------------------------------------------------------------
// _start stub for aarch64 Linux
//   bl <entry>         (4) — call main; return value arrives in x0
//   mov x8, #93        (4) — sys_exit syscall number (Linux aarch64)
//   svc #0             (4) — kernel entry
//                         = 12 bytes total
// ---------------------------------------------------------------------------
fn write_start_aarch64_linux(buf: &mut [u8], entry_addr: u64, start_vaddr: u64) {
    // BL: opcode 0x94000000 | imm26, where imm26 = (target - pc) >> 2
    let delta = ((entry_addr as i64) - (start_vaddr as i64)) >> 2;
    let imm26 = (delta as u32) & 0x3FFFFFF;
    let bl = 0x94000000u32 | imm26;
    buf[0..4].copy_from_slice(&bl.to_le_bytes());

    // MOVZ x8, #93  →  0xD2800000 | (93 << 5) | 8
    let movz: u32 = 0xD280_0000 | (93u32 << 5) | 8;
    buf[4..8].copy_from_slice(&movz.to_le_bytes());

    // SVC #0  →  0xD4000001
    buf[8..12].copy_from_slice(&0xD400_0001u32.to_le_bytes());
}

// ---------------------------------------------------------------------------
// Relocation application for x86-64
// ---------------------------------------------------------------------------
fn apply_reloc_x86_64(
    buf: &mut [u8],
    offset: usize,
    flags: RelocationFlags,
    sym_addr: u64,
    addend: i64,
    reloc_addr: u64,
) -> Result<(), String> {
    let (kind, size) = match flags {
        RelocationFlags::Generic { kind, size, .. } => (kind, size),
        other => {
            return Err(format!(
                "unsupported x86-64 relocation flags: {other:?} at {offset:#x}"
            ));
        }
    };
    match (kind, size) {
        // R_X86_64_64 — 64-bit absolute: S + A
        (RelocationKind::Absolute, 64) => {
            let v = (sym_addr as i64).wrapping_add(addend) as u64;
            buf[offset..offset + 8].copy_from_slice(&v.to_le_bytes());
        }
        // R_X86_64_32 / R_X86_64_32S — 32-bit absolute: (S + A) truncated
        (RelocationKind::Absolute, 32) => {
            let v = (sym_addr as i64).wrapping_add(addend) as i32;
            buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
        }
        // R_X86_64_PC32 — 32-bit PC-relative: S + A - P
        // R_X86_64_PLT32 — same formula (PLT → direct call for static link)
        (RelocationKind::Relative | RelocationKind::PltRelative, 32) => {
            let v = ((sym_addr as i64) + addend - (reloc_addr as i64)) as i32;
            buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
        }
        // R_X86_64_GOTPCREL / R_X86_64_GOTPCRELX — for static linking we treat as PC32.
        // Cranelift in non-PIC mode uses `lea`/`mov [rip+disp]` patterns where the
        // GOT entry holds the symbol address directly; resolving as PC32 works for the
        // `lea` pattern (address of data). The `mov` (load-through-GOT) pattern would
        // require a real GOT entry; if that case arises the value will be wrong and the
        // caller should fall back to the external linker.
        (RelocationKind::GotRelative, 32) => {
            let v = ((sym_addr as i64) + addend - (reloc_addr as i64)) as i32;
            buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
        }
        _ => {
            return Err(format!(
                "unsupported x86-64 relocation: {kind:?} size={size} at {offset:#x}"
            ));
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Relocation application for aarch64
// ---------------------------------------------------------------------------
fn apply_reloc_aarch64(
    buf: &mut [u8],
    offset: usize,
    flags: RelocationFlags,
    sym_addr: u64,
    addend: i64,
    reloc_addr: u64,
) -> Result<(), String> {
    match flags {
        // Architecture-specific ELF relocations: ADRP, ADD, LDST patterns
        RelocationFlags::Elf { r_type } => {
            apply_reloc_aarch64_elf(buf, offset, r_type, sym_addr, addend, reloc_addr)?;
        }
        RelocationFlags::Generic {
            kind,
            encoding,
            size,
        } => {
            match (kind, encoding, size) {
                // R_AARCH64_ABS64
                (RelocationKind::Absolute, _, 64) => {
                    let v = (sym_addr as i64).wrapping_add(addend) as u64;
                    buf[offset..offset + 8].copy_from_slice(&v.to_le_bytes());
                }
                // R_AARCH64_ABS32
                (RelocationKind::Absolute, _, 32) => {
                    let v = (sym_addr as i64).wrapping_add(addend) as u32;
                    buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
                }
                // R_AARCH64_PREL32
                (RelocationKind::Relative, _, 32) => {
                    let v = ((sym_addr as i64) + addend - (reloc_addr as i64)) as i32;
                    buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
                }
                // R_AARCH64_CALL26 / R_AARCH64_JUMP26
                // Encodes (S + A - P) >> 2 into bits [25:0] of the BL/B instruction.
                (RelocationKind::PltRelative, RelocationEncoding::AArch64Call, 26) => {
                    let delta = ((sym_addr as i64) + addend - (reloc_addr as i64)) >> 2;
                    let imm26 = (delta as i32) & 0x3FF_FFFF;
                    let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
                    let new_insn = (insn & 0xFC00_0000) | (imm26 as u32 & 0x3FF_FFFF);
                    buf[offset..offset + 4].copy_from_slice(&new_insn.to_le_bytes());
                }
                _ => {
                    return Err(format!(
                        "unsupported aarch64 relocation: {kind:?} enc={encoding:?} size={size} at {offset:#x}"
                    ));
                }
            }
        }
        other => {
            return Err(format!(
                "unsupported aarch64 relocation flags: {other:?} at {offset:#x}"
            ));
        }
    }
    Ok(())
}

fn apply_reloc_aarch64_elf(
    buf: &mut [u8],
    offset: usize,
    r_type: u32,
    sym_addr: u64,
    addend: i64,
    reloc_addr: u64,
) -> Result<(), String> {
    let target = (sym_addr as i64).wrapping_add(addend);

    match r_type {
        // R_AARCH64_ADR_PREL_PG_HI21 (275)
        // ADRP: page-relative. Encodes ((page(sym+A) - page(P)) >> 12) into the instruction.
        // immlo in [30:29], immhi in [23:5].
        275 => {
            let sym_page = target & !0xFFF;
            let pc_page = (reloc_addr as i64) & !0xFFF;
            let delta = (sym_page - pc_page) >> 12;
            let immlo = (delta as u32) & 0x3;
            let immhi = ((delta as u32) >> 2) & 0x7_FFFF;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            // ADRP instruction: [31]=1,[30:29]=immlo,[28:24]=10000,[23:5]=immhi,[4:0]=Rd
            let new_insn = (insn & 0x9F00_001F) | (immlo << 29) | (immhi << 5);
            buf[offset..offset + 4].copy_from_slice(&new_insn.to_le_bytes());
        }
        // R_AARCH64_ADD_ABS_LO12_NC (277)
        // ADD: low 12 bits of sym+A, in bits [21:10] of ADD immediate instruction.
        277 => {
            let lo12 = (target as u32) & 0xFFF;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            let new_insn = (insn & 0xFFC0_03FF) | (lo12 << 10);
            buf[offset..offset + 4].copy_from_slice(&new_insn.to_le_bytes());
        }
        // R_AARCH64_LDST8_ABS_LO12_NC (278)
        // 8-bit load/store: low 12 bits (unscaled), in bits [21:10].
        278 => {
            let lo12 = (target as u32) & 0xFFF;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            let new_insn = (insn & 0xFFC0_03FF) | (lo12 << 10);
            buf[offset..offset + 4].copy_from_slice(&new_insn.to_le_bytes());
        }
        // R_AARCH64_LDST16_ABS_LO12_NC (284)
        // 16-bit load/store: low 12 bits >> 1, in bits [21:10].
        284 => {
            let lo12 = (target as u32) & 0xFFF;
            let scaled = lo12 >> 1;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            let new_insn = (insn & 0xFFC0_03FF) | (scaled << 10);
            buf[offset..offset + 4].copy_from_slice(&new_insn.to_le_bytes());
        }
        // R_AARCH64_LDST32_ABS_LO12_NC (285)
        // 32-bit load/store: low 12 bits >> 2, in bits [21:10].
        285 => {
            let lo12 = (target as u32) & 0xFFF;
            let scaled = lo12 >> 2;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            let new_insn = (insn & 0xFFC0_03FF) | (scaled << 10);
            buf[offset..offset + 4].copy_from_slice(&new_insn.to_le_bytes());
        }
        // R_AARCH64_LDST64_ABS_LO12_NC (286)
        // 64-bit load/store: low 12 bits >> 3, in bits [21:10].
        286 => {
            let lo12 = (target as u32) & 0xFFF;
            let scaled = lo12 >> 3;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            let new_insn = (insn & 0xFFC0_03FF) | (scaled << 10);
            buf[offset..offset + 4].copy_from_slice(&new_insn.to_le_bytes());
        }
        // R_AARCH64_LDST128_ABS_LO12_NC (299)
        // 128-bit load/store: low 12 bits >> 4, in bits [21:10].
        299 => {
            let lo12 = (target as u32) & 0xFFF;
            let scaled = lo12 >> 4;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            let new_insn = (insn & 0xFFC0_03FF) | (scaled << 10);
            buf[offset..offset + 4].copy_from_slice(&new_insn.to_le_bytes());
        }
        _ => {
            return Err(format!(
                "unsupported aarch64 ELF relocation type {r_type} at {offset:#x}"
            ));
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// ELF writing helpers
// ---------------------------------------------------------------------------

fn write_phdr(
    buf: &mut [u8],
    file_offset: u64,
    vaddr: u64,
    filesz: u64,
    memsz: u64,
    flags: u32,
    align: u64,
) {
    put_u32(&mut buf[0..], 1); // p_type  PT_LOAD
    put_u32(&mut buf[4..], flags); // p_flags
    put_u64(&mut buf[8..], file_offset); // p_offset
    put_u64(&mut buf[16..], vaddr); // p_vaddr
    put_u64(&mut buf[24..], vaddr); // p_paddr
    put_u64(&mut buf[32..], filesz); // p_filesz
    put_u64(&mut buf[40..], memsz); // p_memsz
    put_u64(&mut buf[48..], align); // p_align
}

fn put_u16(buf: &mut [u8], v: u16) {
    buf[..2].copy_from_slice(&v.to_le_bytes());
}
fn put_u32(buf: &mut [u8], v: u32) {
    buf[..4].copy_from_slice(&v.to_le_bytes());
}
fn put_u64(buf: &mut [u8], v: u64) {
    buf[..8].copy_from_slice(&v.to_le_bytes());
}

// ===========================================================================
// PE/COFF x86-64 direct linker  (Windows, no MSVC or lld required)
// ===========================================================================
//
// Produces a minimal PE32+ (64-bit) executable that imports exactly one
// symbol from the Win32 API: kernel32!ExitProcess.  That single import gives
// us a clean process exit; everything else is generated by Cranelift.
//
// Layout (all sizes page-aligned for memory, sector-aligned for file):
//
//   [0x000..hdr_file_size)  PE headers (DOS stub + COFF + OptHdr + section hdrs)
//   [text_file_off ..)      .text  — RX  — Cranelift code + syscall stub + _start
//   [data_file_off ..)      .data  — RW  — globals / bss (optional)
//   [idata_file_off..)      .idata — RW  — import directory + IAT for ExitProcess

// Preferred image base.  Not using DYNAMIC_BASE so the loader uses this
// address directly; no .reloc section is needed for position-independent data.
const PE_IMAGE_BASE: u64 = 0x0000_0001_4000_0000;
const PE_SEC_ALIGN: u64 = 0x1000;
const PE_FILE_ALIGN: u64 = 0x0200;

// .idata section — fixed layout (all offsets relative to section start):
//
//   0  ..  20  Import Directory Entry for kernel32.dll
//   20 ..  40  Null terminator IDT
//   40 ..  48  Import Lookup Table entry  (Hint/Name RVA, 8 bytes)
//   48 ..  56  ILT null terminator
//   56 ..  64  Import Address Table entry (same value; loader patches this)
//   64 ..  72  IAT null terminator
//   72 ..  86  Hint/Name:  hint(2) + "ExitProcess\0"(12)
//   86 ..  99  DLL name:   "kernel32.dll\0"
//   99 .. 104  padding
const IDATA_ILT_OFF: usize = 40;
const IDATA_IAT_OFF: usize = 56;
const IDATA_HN_OFF: usize = 72;
const IDATA_DLL_OFF: usize = 86;
const IDATA_SIZE: usize = 104;

fn link_pe_x86_64(
    obj_bytes: &[u8],
    runtime_blobs: &[(&str, &[u8])],
    entry_sym: &str,
) -> Result<Vec<u8>, String> {
    let obj = ObjFile::parse(obj_bytes).map_err(|e| format!("failed to parse COFF object: {e}"))?;

    // ---- Collect sections ----
    let mut text_secs: Vec<Section> = Vec::new();
    let mut data_secs: Vec<Section> = Vec::new();
    for sec in obj.sections() {
        let name = sec.name().unwrap_or("").to_string();
        let raw = sec
            .data()
            .map_err(|e| format!("section '{name}' data: {e}"))?;
        let align = sec.align().max(1);
        let idx = sec.index().0;
        match sec.kind() {
            SectionKind::Text => text_secs.push(Section {
                name,
                kind: SectionKind::Text,
                data: raw.to_vec(),
                align,
                orig_idx: idx,
                seg_offset: 0,
                vaddr: 0,
            }),
            SectionKind::Data | SectionKind::ReadOnlyData => data_secs.push(Section {
                name,
                kind: sec.kind(),
                data: raw.to_vec(),
                align,
                orig_idx: idx,
                seg_offset: 0,
                vaddr: 0,
            }),
            SectionKind::UninitializedData => data_secs.push(Section {
                name,
                kind: SectionKind::UninitializedData,
                data: vec![0u8; sec.size() as usize],
                align,
                orig_idx: idx,
                seg_offset: 0,
                vaddr: 0,
            }),
            _ => {}
        }
    }
    let has_data = !data_secs.is_empty();

    // ---- PE header region size ----
    // DOS(64) + PE-sig(4) + COFF-hdr(20) + OptHdr(240) + n_secs*40
    let n_secs: usize = 1 + (if has_data { 1 } else { 0 }) + 1; // text [+data] +idata
    let hdr_raw = 64 + 4 + 20 + 240 + n_secs * 40;
    let hdr_file_size = align_up(hdr_raw as u64, PE_FILE_ALIGN);

    // ---- Layout: .text ----
    let text_rva: u64 = PE_SEC_ALIGN; // 0x1000
    let text_vaddr = PE_IMAGE_BASE + text_rva;

    let mut cursor: u64 = 0;
    for s in &mut text_secs {
        cursor = align_up(cursor, s.align);
        s.seg_offset = cursor;
        s.vaddr = text_vaddr + cursor;
        cursor += s.data.len() as u64;
    }
    let blob_placements: Vec<(&str, u64, usize)> = {
        let mut placements = Vec::new();
        for &(name, bytes) in runtime_blobs {
            cursor = align_up(cursor, 16);
            placements.push((name, cursor, bytes.len()));
            cursor += bytes.len() as u64;
        }
        placements
    };
    cursor = align_up(cursor, 16);
    let start_seg_off = cursor;
    let start_vaddr = text_vaddr + cursor;
    // sub+call+mov+call[mem] = 4+5+3+6 = 18 bytes
    const PE_START_SIZE: u64 = 18;
    cursor += PE_START_SIZE;

    let text_vsz = cursor; // actual content bytes
    let text_raw_size = align_up(text_vsz, PE_FILE_ALIGN);
    let text_virt_aligned = align_up(text_vsz, PE_SEC_ALIGN);

    // ---- Layout: .data (optional) ----
    let data_rva = text_rva + text_virt_aligned;
    let data_vaddr = PE_IMAGE_BASE + data_rva;
    cursor = 0;
    for s in &mut data_secs {
        cursor = align_up(cursor, s.align);
        s.seg_offset = cursor;
        s.vaddr = data_vaddr + cursor;
        cursor += s.data.len() as u64;
    }
    let data_vsz = cursor;
    let data_raw_size = if has_data {
        align_up(data_vsz, PE_FILE_ALIGN)
    } else {
        0
    };
    let data_virt_aligned = if has_data {
        align_up(data_vsz, PE_SEC_ALIGN)
    } else {
        0
    };

    // ---- Layout: .idata ----
    let idata_rva = data_rva + data_virt_aligned;
    let idata_vaddr = PE_IMAGE_BASE + idata_rva;
    let idata_raw_size = align_up(IDATA_SIZE as u64, PE_FILE_ALIGN);
    let idata_virt_aligned = align_up(IDATA_SIZE as u64, PE_SEC_ALIGN);

    // VA of the IAT entry for ExitProcess (patched by the loader at runtime)
    let iat_vaddr = idata_vaddr + IDATA_IAT_OFF as u64;

    // ---- Symbol map ----
    let mut syms: BTreeMap<String, u64> = BTreeMap::new();
    for &(name, seg_off, _) in &blob_placements {
        syms.insert(name.to_string(), text_vaddr + seg_off);
    }
    syms.insert("_start".to_string(), start_vaddr);
    for sym in obj.symbols() {
        let Ok(name) = sym.name() else { continue };
        if name.is_empty() {
            continue;
        }
        let sec_idx = match sym.section() {
            object::read::SymbolSection::Section(i) => i.0,
            _ => continue,
        };
        let offset = sym.address();
        let addr = text_secs
            .iter()
            .find(|s| s.orig_idx == sec_idx)
            .map(|s| s.vaddr + offset)
            .or_else(|| {
                data_secs
                    .iter()
                    .find(|s| s.orig_idx == sec_idx)
                    .map(|s| s.vaddr + offset)
            });
        if let Some(a) = addr {
            syms.insert(name.to_string(), a);
        }
    }

    let entry_addr = *syms
        .get(entry_sym)
        .ok_or_else(|| format!("entry symbol '{entry_sym}' not found in object"))?;

    // ---- Merge section content into buffers ----
    let mut text_buf = vec![0u8; text_raw_size as usize];
    for s in &text_secs {
        let e = s.seg_offset as usize + s.data.len();
        text_buf[s.seg_offset as usize..e].copy_from_slice(&s.data);
    }
    for (&(_, bytes), &(_, seg_off, len)) in runtime_blobs.iter().zip(blob_placements.iter()) {
        text_buf[seg_off as usize..seg_off as usize + len].copy_from_slice(bytes);
    }
    write_start_pe_x86_64(
        &mut text_buf[start_seg_off as usize..],
        entry_addr,
        start_vaddr,
        iat_vaddr,
    );

    let mut data_buf = vec![0u8; data_raw_size as usize];
    for s in &data_secs {
        let e = s.seg_offset as usize + s.data.len();
        data_buf[s.seg_offset as usize..e].copy_from_slice(&s.data);
    }

    let idata_buf = build_idata_pe(idata_rva);

    // ---- Apply COFF relocations ----
    for sec in obj.sections() {
        let sec_idx = sec.index().0;
        let (is_text, seg_off, sec_vaddr) =
            if let Some(s) = text_secs.iter().find(|s| s.orig_idx == sec_idx) {
                (true, s.seg_offset, s.vaddr)
            } else if let Some(s) = data_secs.iter().find(|s| s.orig_idx == sec_idx) {
                (false, s.seg_offset, s.vaddr)
            } else {
                continue;
            };

        for (reloc_off, reloc) in sec.relocations() {
            let sym_addr = match reloc.target() {
                RelocationTarget::Symbol(sym_idx) => {
                    let sym = obj
                        .symbol_by_index(sym_idx)
                        .map_err(|e| format!("bad symbol index: {e}"))?;
                    let name = sym.name().unwrap_or("");
                    *syms
                        .get(name)
                        .ok_or_else(|| format!("undefined symbol '{name}'"))?
                }
                RelocationTarget::Section(tidx) => {
                    let t = tidx.0;
                    text_secs
                        .iter()
                        .find(|s| s.orig_idx == t)
                        .map(|s| s.vaddr)
                        .or_else(|| data_secs.iter().find(|s| s.orig_idx == t).map(|s| s.vaddr))
                        .ok_or_else(|| format!("section reloc target {t} not found"))?
                }
                _ => continue,
            };

            // COFF always uses implicit addends; read from the correct buffer.
            let patch_loc = (seg_off + reloc_off) as usize;
            let reloc_va = sec_vaddr + reloc_off;
            let addend: i64 = {
                let src = if is_text { &text_buf } else { &data_buf };
                match reloc.size() {
                    32 => {
                        i32::from_le_bytes(src[patch_loc..patch_loc + 4].try_into().unwrap()) as i64
                    }
                    64 => i64::from_le_bytes(src[patch_loc..patch_loc + 8].try_into().unwrap()),
                    _ => 0,
                }
            };

            let buf = if is_text {
                &mut text_buf
            } else {
                &mut data_buf
            };
            apply_reloc_coff_x86_64(buf, patch_loc, reloc.flags(), sym_addr, addend, reloc_va)?;
        }
    }

    // ---- File offset assignments ----
    let text_file_off = hdr_file_size;
    let data_file_off = text_file_off + text_raw_size;
    let idata_file_off = data_file_off + data_raw_size;
    let total_size = idata_file_off + idata_raw_size;
    let image_size = (idata_rva + idata_virt_aligned) as u32;

    // ---- Assemble PE file ----
    let mut file = vec![0u8; total_size as usize];

    // DOS stub: just the MZ magic and e_lfanew pointer
    put_u16(&mut file[0..], 0x5A4D); // MZ
    put_u16(&mut file[0x3C..], 0x40); // e_lfanew = 0x40

    // PE signature
    file[0x40..0x44].copy_from_slice(b"PE\0\0");

    // COFF file header (20 bytes at 0x44)
    {
        let h = &mut file[0x44..0x58];
        put_u16(&mut h[0..], 0x8664); // Machine: AMD64
        put_u16(&mut h[2..], n_secs as u16);
        put_u32(&mut h[4..], 0); // TimeDateStamp
        put_u32(&mut h[8..], 0); // PointerToSymbolTable
        put_u32(&mut h[12..], 0); // NumberOfSymbols
        put_u16(&mut h[16..], 240); // SizeOfOptionalHeader
        put_u16(&mut h[18..], 0x0022); // Characteristics: EXEC | LARGE_ADDR_AWARE
    }

    // PE32+ optional header (240 bytes at 0x58)
    {
        let h = &mut file[0x58..0x58 + 240];
        put_u16(&mut h[0..], 0x020B); // Magic: PE32+
                                      // MajorLinkerVersion, MinorLinkerVersion = 0 (already)
        put_u32(&mut h[4..], text_raw_size as u32); // SizeOfCode
        put_u32(&mut h[8..], (data_raw_size + idata_raw_size) as u32); // SizeOfInitData
        put_u32(&mut h[12..], 0); // SizeOfUninitData
        put_u32(&mut h[16..], (start_vaddr - PE_IMAGE_BASE) as u32); // AddressOfEntryPoint
        put_u32(&mut h[20..], text_rva as u32); // BaseOfCode
        put_u64(&mut h[24..], PE_IMAGE_BASE); // ImageBase
        put_u32(&mut h[32..], PE_SEC_ALIGN as u32); // SectionAlignment
        put_u32(&mut h[36..], PE_FILE_ALIGN as u32); // FileAlignment
        put_u16(&mut h[40..], 6); // MajorOperatingSystemVersion
                                  // MinorOperatingSystemVersion = 0
                                  // MajorImageVersion, MinorImageVersion = 0
        put_u16(&mut h[48..], 6); // MajorSubsystemVersion
                                  // MinorSubsystemVersion = 0
                                  // Win32VersionValue = 0
        put_u32(&mut h[56..], image_size); // SizeOfImage
        put_u32(&mut h[60..], hdr_file_size as u32); // SizeOfHeaders
                                                     // CheckSum = 0
        put_u16(&mut h[68..], 3); // Subsystem: IMAGE_SUBSYSTEM_WINDOWS_CUI
        put_u16(&mut h[70..], 0x0100); // DllCharacteristics: NX_COMPAT
        put_u64(&mut h[72..], 0x10_0000); // SizeOfStackReserve (1 MB)
        put_u64(&mut h[80..], 0x1000); // SizeOfStackCommit  (4 KB)
        put_u64(&mut h[88..], 0x10_0000); // SizeOfHeapReserve
        put_u64(&mut h[96..], 0x1000); // SizeOfHeapCommit
                                       // LoaderFlags = 0
        put_u32(&mut h[108..], 16); // NumberOfRvaAndSizes
                                    // DataDirectory[1]: Import Table (IDT = 2 entries × 20 bytes)
        put_u32(&mut h[112 + 8..], idata_rva as u32);
        put_u32(&mut h[112 + 12..], 40);
        // DataDirectory[12]: IAT (ExitProcess entry + null × 8 bytes each)
        put_u32(
            &mut h[112 + 96..],
            (idata_rva + IDATA_IAT_OFF as u64) as u32,
        );
        put_u32(&mut h[112 + 100..], 16);
    }

    // Section headers (40 bytes each, starting at 0x148)
    let mut shdr = 0x58 + 240;

    write_pe_sec_hdr(
        &mut file[shdr..shdr + 40],
        b".text\0\0\0",
        text_vsz as u32,
        text_rva as u32,
        text_raw_size as u32,
        text_file_off as u32,
        0x6000_0020,
    );
    shdr += 40;

    if has_data {
        write_pe_sec_hdr(
            &mut file[shdr..shdr + 40],
            b".data\0\0\0",
            data_vsz as u32,
            data_rva as u32,
            data_raw_size as u32,
            data_file_off as u32,
            0xC000_0040,
        );
        shdr += 40;
    }

    write_pe_sec_hdr(
        &mut file[shdr..shdr + 40],
        b".idata\0\0",
        IDATA_SIZE as u32,
        idata_rva as u32,
        idata_raw_size as u32,
        idata_file_off as u32,
        0xC000_0040,
    );

    // Copy section data
    let te = text_file_off as usize + text_raw_size as usize;
    file[text_file_off as usize..te].copy_from_slice(&text_buf);
    if has_data && data_raw_size > 0 {
        let de = data_file_off as usize + data_raw_size as usize;
        file[data_file_off as usize..de].copy_from_slice(&data_buf);
    }
    file[idata_file_off as usize..idata_file_off as usize + IDATA_SIZE].copy_from_slice(&idata_buf);

    Ok(file)
}

// ---------------------------------------------------------------------------
// Build the .idata section (import table for kernel32!ExitProcess)
// ---------------------------------------------------------------------------
fn build_idata_pe(idata_rva: u64) -> Vec<u8> {
    let mut b = vec![0u8; IDATA_SIZE];

    // Import Directory Entry for kernel32.dll (offset 0)
    put_u32(&mut b[0..], (idata_rva + IDATA_ILT_OFF as u64) as u32); // OriginalFirstThunk
                                                                     // TimeDateStamp, ForwarderChain = 0 (already)
    put_u32(&mut b[12..], (idata_rva + IDATA_DLL_OFF as u64) as u32); // Name RVA
    put_u32(&mut b[16..], (idata_rva + IDATA_IAT_OFF as u64) as u32); // FirstThunk (IAT)
                                                                      // Null IDT entry at [20..40]: already zero

    // ILT entry (offset 40): RVA of Hint/Name (bit63=0 → by-name import)
    let hn_rva = idata_rva + IDATA_HN_OFF as u64;
    put_u64(&mut b[IDATA_ILT_OFF..], hn_rva);
    // ILT null at [48..56]: already zero

    // IAT entry (offset 56): same value initially; loader overwrites with VA
    put_u64(&mut b[IDATA_IAT_OFF..], hn_rva);
    // IAT null at [64..72]: already zero

    // Hint/Name (offset 72): hint(2 bytes, 0) + "ExitProcess\0"
    // hint bytes already zero
    b[IDATA_HN_OFF + 2..IDATA_HN_OFF + 14].copy_from_slice(b"ExitProcess\0");

    // DLL name (offset 86)
    b[IDATA_DLL_OFF..IDATA_DLL_OFF + 13].copy_from_slice(b"kernel32.dll\0");

    b
}

// ---------------------------------------------------------------------------
// _start stub for PE x86-64 Windows (18 bytes)
//
//   sub  rsp, 0x28          48 83 EC 28        (4) stack alignment + shadow
//   call <entry>            E8 XX XX XX XX     (5) rax = main()
//   mov  rcx, rax           48 89 C1           (3) ExitProcess(exit_code)
//   call [rip + <iat_disp>] FF 15 XX XX XX XX  (6) indirect via IAT
// ---------------------------------------------------------------------------
fn write_start_pe_x86_64(buf: &mut [u8], entry_addr: u64, start_vaddr: u64, iat_vaddr: u64) {
    // sub rsp, 0x28  (at entry RSP%16==8; after this RSP%16==0 → call aligns correctly)
    buf[0] = 0x48;
    buf[1] = 0x83;
    buf[2] = 0xEC;
    buf[3] = 0x28;
    // call <entry>  — relative to next instruction (offset 9)
    let call_rel = (entry_addr as i64 - (start_vaddr as i64 + 9)) as i32;
    buf[4] = 0xE8;
    buf[5..9].copy_from_slice(&call_rel.to_le_bytes());
    // mov rcx, rax
    buf[9] = 0x48;
    buf[10] = 0x89;
    buf[11] = 0xC1;
    // call [rip + iat_disp]  — RIP is start_vaddr+18 when this executes
    let iat_disp = (iat_vaddr as i64 - (start_vaddr as i64 + 18)) as i32;
    buf[12] = 0xFF;
    buf[13] = 0x15;
    buf[14..18].copy_from_slice(&iat_disp.to_le_bytes());
}

// ---------------------------------------------------------------------------
// PE section header (40 bytes)
// ---------------------------------------------------------------------------
fn write_pe_sec_hdr(
    buf: &mut [u8],
    name: &[u8; 8],
    virtual_size: u32,
    virtual_addr: u32,
    raw_size: u32,
    raw_off: u32,
    characteristics: u32,
) {
    buf[0..8].copy_from_slice(name);
    put_u32(&mut buf[8..], virtual_size);
    put_u32(&mut buf[12..], virtual_addr);
    put_u32(&mut buf[16..], raw_size);
    put_u32(&mut buf[20..], raw_off);
    // PointerToRelocations, PointerToLinenumbers, counts = 0 (already)
    put_u32(&mut buf[36..], characteristics);
}

// ---------------------------------------------------------------------------
// COFF x86-64 relocation application
//
// COFF IMAGE_REL_AMD64_REL32 formula: S + A - P - 4
// (P is the VA of the 4-byte field; the -4 accounts for the end-of-field
//  RIP-relative base that x86-64 CALL/JMP use.  Cranelift initialises the
//  field to 0, so A is typically 0.)
// ---------------------------------------------------------------------------
fn apply_reloc_coff_x86_64(
    buf: &mut [u8],
    offset: usize,
    flags: RelocationFlags,
    sym_addr: u64,
    addend: i64,
    reloc_va: u64,
) -> Result<(), String> {
    let (kind, size) = match flags {
        RelocationFlags::Generic { kind, size, .. } => (kind, size),
        other => {
            return Err(format!(
                "unexpected COFF relocation flags {other:?} at {offset:#x}"
            ))
        }
    };
    match (kind, size) {
        // IMAGE_REL_AMD64_ADDR64 — 64-bit absolute VA
        (RelocationKind::Absolute, 64) => {
            let v = (sym_addr as i64 + addend) as u64;
            buf[offset..offset + 8].copy_from_slice(&v.to_le_bytes());
        }
        // IMAGE_REL_AMD64_ADDR32 — 32-bit absolute VA (truncated)
        (RelocationKind::Absolute, 32) => {
            let v = (sym_addr as i64 + addend) as u32;
            buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
        }
        // IMAGE_REL_AMD64_REL32 — 32-bit RIP-relative (end-of-field base)
        (RelocationKind::Relative, 32) => {
            let v = (sym_addr as i64 + addend - reloc_va as i64 - 4) as i32;
            buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
        }
        _ => {
            return Err(format!(
                "unsupported COFF x86-64 relocation: {kind:?} size={size} at {offset:#x}"
            ))
        }
    }
    Ok(())
}

// ===========================================================================
// PE/COFF ARM64 direct linker  (Windows ARM64, no MSVC or lld required)
// ===========================================================================
//
// Identical structure to the x86-64 PE linker; differences are:
//   • COFF machine field: 0xAA64 (IMAGE_FILE_MACHINE_ARM64)
//   • _start stub: 16 bytes (BL + ADRP + LDR + BR)
//   • Instruction alignment: 4 bytes
//   • COFF ARM64 relocation handler

fn link_pe_arm64(
    obj_bytes: &[u8],
    runtime_blobs: &[(&str, &[u8])],
    entry_sym: &str,
) -> Result<Vec<u8>, String> {
    let obj =
        ObjFile::parse(obj_bytes).map_err(|e| format!("failed to parse COFF ARM64 object: {e}"))?;

    // ---- Collect sections ----
    let mut text_secs: Vec<Section> = Vec::new();
    let mut data_secs: Vec<Section> = Vec::new();
    for sec in obj.sections() {
        let name = sec.name().unwrap_or("").to_string();
        let raw = sec
            .data()
            .map_err(|e| format!("section '{name}' data: {e}"))?;
        let align = sec.align().max(1);
        let idx = sec.index().0;
        match sec.kind() {
            SectionKind::Text => text_secs.push(Section {
                name,
                kind: SectionKind::Text,
                data: raw.to_vec(),
                align,
                orig_idx: idx,
                seg_offset: 0,
                vaddr: 0,
            }),
            SectionKind::Data | SectionKind::ReadOnlyData => data_secs.push(Section {
                name,
                kind: sec.kind(),
                data: raw.to_vec(),
                align,
                orig_idx: idx,
                seg_offset: 0,
                vaddr: 0,
            }),
            SectionKind::UninitializedData => data_secs.push(Section {
                name,
                kind: SectionKind::UninitializedData,
                data: vec![0u8; sec.size() as usize],
                align,
                orig_idx: idx,
                seg_offset: 0,
                vaddr: 0,
            }),
            _ => {}
        }
    }
    let has_data = !data_secs.is_empty();

    // ---- PE header region size ----
    let n_secs: usize = 1 + (if has_data { 1 } else { 0 }) + 1; // text [+data] +idata
    let hdr_raw = 64 + 4 + 20 + 240 + n_secs * 40;
    let hdr_file_size = align_up(hdr_raw as u64, PE_FILE_ALIGN);

    // ---- Layout: .text ----
    let text_rva: u64 = PE_SEC_ALIGN;
    let text_vaddr = PE_IMAGE_BASE + text_rva;

    let mut cursor: u64 = 0;
    for s in &mut text_secs {
        cursor = align_up(cursor, s.align);
        s.seg_offset = cursor;
        s.vaddr = text_vaddr + cursor;
        cursor += s.data.len() as u64;
    }
    let blob_placements: Vec<(&str, u64, usize)> = {
        let mut placements = Vec::new();
        for &(name, bytes) in runtime_blobs {
            cursor = align_up(cursor, 4); // AArch64 instruction alignment
            placements.push((name, cursor, bytes.len()));
            cursor += bytes.len() as u64;
        }
        placements
    };
    cursor = align_up(cursor, 4);
    let start_seg_off = cursor;
    let start_vaddr = text_vaddr + cursor;
    // BL + ADRP x16 + LDR x16,[x16,#lo12] + BR x16 = 4+4+4+4 = 16 bytes
    const PE_ARM64_START_SIZE: u64 = 16;
    cursor += PE_ARM64_START_SIZE;

    let text_vsz = cursor;
    let text_raw_size = align_up(text_vsz, PE_FILE_ALIGN);
    let text_virt_aligned = align_up(text_vsz, PE_SEC_ALIGN);

    // ---- Layout: .data (optional) ----
    let data_rva = text_rva + text_virt_aligned;
    let data_vaddr = PE_IMAGE_BASE + data_rva;
    cursor = 0;
    for s in &mut data_secs {
        cursor = align_up(cursor, s.align);
        s.seg_offset = cursor;
        s.vaddr = data_vaddr + cursor;
        cursor += s.data.len() as u64;
    }
    let data_vsz = cursor;
    let data_raw_size = if has_data {
        align_up(data_vsz, PE_FILE_ALIGN)
    } else {
        0
    };
    let data_virt_aligned = if has_data {
        align_up(data_vsz, PE_SEC_ALIGN)
    } else {
        0
    };

    // ---- Layout: .idata ----
    let idata_rva = data_rva + data_virt_aligned;
    let idata_vaddr = PE_IMAGE_BASE + idata_rva;
    let idata_raw_size = align_up(IDATA_SIZE as u64, PE_FILE_ALIGN);
    let idata_virt_aligned = align_up(IDATA_SIZE as u64, PE_SEC_ALIGN);
    let iat_vaddr = idata_vaddr + IDATA_IAT_OFF as u64;

    // ---- Symbol map ----
    let mut syms: BTreeMap<String, u64> = BTreeMap::new();
    for &(name, seg_off, _) in &blob_placements {
        syms.insert(name.to_string(), text_vaddr + seg_off);
    }
    syms.insert("_start".to_string(), start_vaddr);
    for sym in obj.symbols() {
        let Ok(name) = sym.name() else { continue };
        if name.is_empty() {
            continue;
        }
        let sec_idx = match sym.section() {
            object::read::SymbolSection::Section(i) => i.0,
            _ => continue,
        };
        let offset = sym.address();
        let addr = text_secs
            .iter()
            .find(|s| s.orig_idx == sec_idx)
            .map(|s| s.vaddr + offset)
            .or_else(|| {
                data_secs
                    .iter()
                    .find(|s| s.orig_idx == sec_idx)
                    .map(|s| s.vaddr + offset)
            });
        if let Some(a) = addr {
            syms.insert(name.to_string(), a);
        }
    }

    let entry_addr = *syms
        .get(entry_sym)
        .ok_or_else(|| format!("entry symbol '{entry_sym}' not found in object"))?;

    // ---- Merge section content ----
    let mut text_buf = vec![0u8; text_raw_size as usize];
    for s in &text_secs {
        let e = s.seg_offset as usize + s.data.len();
        text_buf[s.seg_offset as usize..e].copy_from_slice(&s.data);
    }
    for (&(_, bytes), &(_, seg_off, len)) in runtime_blobs.iter().zip(blob_placements.iter()) {
        text_buf[seg_off as usize..seg_off as usize + len].copy_from_slice(bytes);
    }
    write_start_pe_arm64(
        &mut text_buf[start_seg_off as usize..],
        entry_addr,
        start_vaddr,
        iat_vaddr,
    );

    let mut data_buf = vec![0u8; data_raw_size as usize];
    for s in &data_secs {
        let e = s.seg_offset as usize + s.data.len();
        data_buf[s.seg_offset as usize..e].copy_from_slice(&s.data);
    }

    let idata_buf = build_idata_pe(idata_rva);

    // ---- Apply COFF relocations ----
    for sec in obj.sections() {
        let sec_idx = sec.index().0;
        let (is_text, seg_off, sec_vaddr) =
            if let Some(s) = text_secs.iter().find(|s| s.orig_idx == sec_idx) {
                (true, s.seg_offset, s.vaddr)
            } else if let Some(s) = data_secs.iter().find(|s| s.orig_idx == sec_idx) {
                (false, s.seg_offset, s.vaddr)
            } else {
                continue;
            };

        for (reloc_off, reloc) in sec.relocations() {
            let sym_addr = match reloc.target() {
                RelocationTarget::Symbol(sym_idx) => {
                    let sym = obj
                        .symbol_by_index(sym_idx)
                        .map_err(|e| format!("bad symbol index: {e}"))?;
                    let name = sym.name().unwrap_or("");
                    *syms
                        .get(name)
                        .ok_or_else(|| format!("undefined symbol '{name}'"))?
                }
                RelocationTarget::Section(tidx) => {
                    let t = tidx.0;
                    text_secs
                        .iter()
                        .find(|s| s.orig_idx == t)
                        .map(|s| s.vaddr)
                        .or_else(|| data_secs.iter().find(|s| s.orig_idx == t).map(|s| s.vaddr))
                        .ok_or_else(|| format!("section reloc target {t} not found"))?
                }
                _ => continue,
            };

            // COFF always uses implicit addends (read from bytes at the relocation site).
            // For Unknown relocations (ADRP/ADD/LDR pattern), reloc.size() is typically 0,
            // so the addend reads as 0, which is correct for those types.
            let patch_loc = (seg_off + reloc_off) as usize;
            let reloc_va = sec_vaddr + reloc_off;
            let addend: i64 = {
                let src = if is_text { &text_buf } else { &data_buf };
                match reloc.size() {
                    32 => {
                        i32::from_le_bytes(src[patch_loc..patch_loc + 4].try_into().unwrap()) as i64
                    }
                    64 => i64::from_le_bytes(src[patch_loc..patch_loc + 8].try_into().unwrap()),
                    _ => 0,
                }
            };

            let buf = if is_text {
                &mut text_buf
            } else {
                &mut data_buf
            };
            apply_reloc_coff_arm64(buf, patch_loc, reloc.flags(), sym_addr, addend, reloc_va)?;
        }
    }

    // ---- File offset assignments ----
    let text_file_off = hdr_file_size;
    let data_file_off = text_file_off + text_raw_size;
    let idata_file_off = data_file_off + data_raw_size;
    let total_size = idata_file_off + idata_raw_size;
    let image_size = (idata_rva + idata_virt_aligned) as u32;

    // ---- Assemble PE file ----
    let mut file = vec![0u8; total_size as usize];

    // DOS stub
    put_u16(&mut file[0..], 0x5A4D); // MZ
    put_u16(&mut file[0x3C..], 0x40); // e_lfanew

    // PE signature
    file[0x40..0x44].copy_from_slice(b"PE\0\0");

    // COFF file header (20 bytes at 0x44)
    {
        let h = &mut file[0x44..0x58];
        put_u16(&mut h[0..], 0xAA64); // Machine: ARM64
        put_u16(&mut h[2..], n_secs as u16);
        put_u32(&mut h[4..], 0);
        put_u32(&mut h[8..], 0);
        put_u32(&mut h[12..], 0);
        put_u16(&mut h[16..], 240);
        put_u16(&mut h[18..], 0x0022); // Characteristics: EXEC | LARGE_ADDR_AWARE
    }

    // PE32+ optional header (240 bytes at 0x58)
    {
        let h = &mut file[0x58..0x58 + 240];
        put_u16(&mut h[0..], 0x020B); // Magic: PE32+
        put_u32(&mut h[4..], text_raw_size as u32);
        put_u32(&mut h[8..], (data_raw_size + idata_raw_size) as u32);
        put_u32(&mut h[12..], 0);
        put_u32(&mut h[16..], (start_vaddr - PE_IMAGE_BASE) as u32); // AddressOfEntryPoint
        put_u32(&mut h[20..], text_rva as u32);
        put_u64(&mut h[24..], PE_IMAGE_BASE);
        put_u32(&mut h[32..], PE_SEC_ALIGN as u32);
        put_u32(&mut h[36..], PE_FILE_ALIGN as u32);
        put_u16(&mut h[40..], 6); // MajorOperatingSystemVersion
        put_u16(&mut h[48..], 6); // MajorSubsystemVersion
        put_u32(&mut h[56..], image_size);
        put_u32(&mut h[60..], hdr_file_size as u32);
        put_u16(&mut h[68..], 3); // Subsystem: WINDOWS_CUI
        put_u16(&mut h[70..], 0x0100); // DllCharacteristics: NX_COMPAT
        put_u64(&mut h[72..], 0x10_0000); // SizeOfStackReserve
        put_u64(&mut h[80..], 0x1000); // SizeOfStackCommit
        put_u64(&mut h[88..], 0x10_0000); // SizeOfHeapReserve
        put_u64(&mut h[96..], 0x1000); // SizeOfHeapCommit
        put_u32(&mut h[108..], 16); // NumberOfRvaAndSizes
                                    // DataDirectory[1]: Import Table
        put_u32(&mut h[112 + 8..], idata_rva as u32);
        put_u32(&mut h[112 + 12..], 40);
        // DataDirectory[12]: IAT
        put_u32(
            &mut h[112 + 96..],
            (idata_rva + IDATA_IAT_OFF as u64) as u32,
        );
        put_u32(&mut h[112 + 100..], 16);
    }

    // Section headers
    let mut shdr = 0x58 + 240;
    write_pe_sec_hdr(
        &mut file[shdr..shdr + 40],
        b".text\0\0\0",
        text_vsz as u32,
        text_rva as u32,
        text_raw_size as u32,
        text_file_off as u32,
        0x6000_0020,
    );
    shdr += 40;
    if has_data {
        write_pe_sec_hdr(
            &mut file[shdr..shdr + 40],
            b".data\0\0\0",
            data_vsz as u32,
            data_rva as u32,
            data_raw_size as u32,
            data_file_off as u32,
            0xC000_0040,
        );
        shdr += 40;
    }
    write_pe_sec_hdr(
        &mut file[shdr..shdr + 40],
        b".idata\0\0",
        IDATA_SIZE as u32,
        idata_rva as u32,
        idata_raw_size as u32,
        idata_file_off as u32,
        0xC000_0040,
    );

    // Copy section data
    let te = text_file_off as usize + text_raw_size as usize;
    file[text_file_off as usize..te].copy_from_slice(&text_buf);
    if has_data && data_raw_size > 0 {
        let de = data_file_off as usize + data_raw_size as usize;
        file[data_file_off as usize..de].copy_from_slice(&data_buf);
    }
    file[idata_file_off as usize..idata_file_off as usize + IDATA_SIZE].copy_from_slice(&idata_buf);

    Ok(file)
}

// ---------------------------------------------------------------------------
// _start stub for PE ARM64 Windows (16 bytes)
//
//   bl <entry>              4 bytes — x0 = exit code (Windows ARM64 ABI: return in x0)
//   adrp x16, <iat_page>    4 bytes — page-relative address of IAT entry
//   ldr x16, [x16, #lo12]   4 bytes — load ExitProcess VA from IAT
//   br x16                  4 bytes — tail-call ExitProcess(exit_code)
//                                     (x0 already holds exit code from bl)
// ---------------------------------------------------------------------------
fn write_start_pe_arm64(buf: &mut [u8], entry_addr: u64, start_vaddr: u64, iat_vaddr: u64) {
    // BL <entry>  — PC = start_vaddr + 0
    let delta = (entry_addr as i64 - start_vaddr as i64) >> 2;
    let imm26 = (delta as u32) & 0x3FF_FFFF;
    put_u32(&mut buf[0..], 0x9400_0000 | imm26);

    // ADRP x16, <page>  — PC = start_vaddr + 4
    // Base instruction for ADRP x16 (Rd=16=0x10): 0x9000_0010
    //   bit31=1, bits[28:24]=10000, bits[4:0]=10000; immlo/immhi to be filled.
    let pc_adrp = start_vaddr + 4;
    let iat_page = iat_vaddr & !0xFFF;
    let pc_page = pc_adrp & !0xFFF;
    let adelta = ((iat_page as i64) - (pc_page as i64)) >> 12;
    let immlo = (adelta as u32) & 0x3;
    let immhi = ((adelta as u32) >> 2) & 0x7_FFFF;
    put_u32(&mut buf[4..], 0x9000_0010 | (immlo << 29) | (immhi << 5));

    // LDR x16, [x16, #lo12_scaled]  — base instruction 0xF940_0210 (Rn=Rt=x16)
    //   64-bit load, unsigned offset: scaled imm12 = lo12 / 8
    let lo12 = (iat_vaddr & 0xFFF) as u32;
    let scaled = lo12 >> 3;
    put_u32(&mut buf[8..], 0xF940_0210 | (scaled << 10));

    // BR x16  — 0xD61F_0200
    put_u32(&mut buf[12..], 0xD61F_0200);
}

// ---------------------------------------------------------------------------
// COFF ARM64 relocation application
//
// Mapped by the object crate:
//   IMAGE_REL_ARM64_BRANCH26    → Generic { Relative, AArch64Call, 26 }
//   IMAGE_REL_ARM64_ADDR64      → Generic { Absolute, 64 }
//   IMAGE_REL_ARM64_REL32       → Generic { Relative, 32 }   (formula: S+A-P-4)
//
// Not mapped (come through as Generic { Unknown, 0 }):
//   IMAGE_REL_ARM64_PAGEBASE_REL21  → ADRP instruction
//   IMAGE_REL_ARM64_PAGEOFFSET_12A  → ADD imm12 instruction
//   IMAGE_REL_ARM64_PAGEOFFSET_12L  → LDR/STR scaled-offset instruction
//
// For Unknown relocations we detect the instruction type by opcode bits:
//   ADRP: (insn >> 24) & 0x9F == 0x90   (bit31=1, bits[28:24]=10000)
//   ADD:  (insn >> 24) == 0x91 or 0x11  (64-bit/32-bit ADD imm)
//   else: LDR/STR scaled offset
// ---------------------------------------------------------------------------
fn apply_reloc_coff_arm64(
    buf: &mut [u8],
    offset: usize,
    flags: RelocationFlags,
    sym_addr: u64,
    addend: i64,
    reloc_va: u64,
) -> Result<(), String> {
    let (kind, encoding, size) = match flags {
        RelocationFlags::Generic {
            kind,
            encoding,
            size,
        } => (kind, encoding, size),
        other => {
            return Err(format!(
                "unexpected COFF ARM64 reloc flags {other:?} at {offset:#x}"
            ))
        }
    };

    match (kind, encoding, size) {
        // IMAGE_REL_ARM64_ADDR64 — 64-bit absolute VA
        (RelocationKind::Absolute, _, 64) => {
            let v = (sym_addr as i64 + addend) as u64;
            buf[offset..offset + 8].copy_from_slice(&v.to_le_bytes());
        }
        // IMAGE_REL_ARM64_REL32 — 32-bit PC-relative (end-of-field base, -4 adjustment)
        (RelocationKind::Relative, _, 32) => {
            let v = (sym_addr as i64 + addend - reloc_va as i64 - 4) as i32;
            buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
        }
        // IMAGE_REL_ARM64_BRANCH26 — BL/B imm26: (S+A-P)>>2 into bits[25:0]
        (RelocationKind::Relative, RelocationEncoding::AArch64Call, 26) => {
            let delta = (sym_addr as i64 + addend - reloc_va as i64) >> 2;
            let imm26 = (delta as i32) & 0x3FF_FFFF;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            buf[offset..offset + 4].copy_from_slice(
                &((insn & 0xFC00_0000) | (imm26 as u32 & 0x3FF_FFFF)).to_le_bytes(),
            );
        }
        // Unknown: PAGEBASE_REL21 (ADRP), PAGEOFFSET_12A (ADD), or PAGEOFFSET_12L (LDR/STR)
        // Detect instruction type by opcode bits.
        (RelocationKind::Unknown, _, _) => {
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            let target = (sym_addr as i64).wrapping_add(addend);

            if (insn >> 24) & 0x9F == 0x90 {
                // ADRP (PAGEBASE_REL21): ((page(S+A) - page(P)) >> 12) into immlo/immhi
                let sym_page = target & !0xFFF;
                let pc_page = (reloc_va as i64) & !0xFFF;
                let delta = (sym_page - pc_page) >> 12;
                let immlo = (delta as u32) & 0x3;
                let immhi = ((delta as u32) >> 2) & 0x7_FFFF;
                buf[offset..offset + 4].copy_from_slice(
                    &((insn & 0x9F00_001F) | (immlo << 29) | (immhi << 5)).to_le_bytes(),
                );
            } else {
                // ADD (PAGEOFFSET_12A) or LDR/STR (PAGEOFFSET_12L)
                // Both use lo12 of target address, placed in bits[21:10].
                let lo12 = (target as u32) & 0xFFF;
                let opcode_byte = (insn >> 24) as u8;
                let scaled = if opcode_byte == 0x91 || opcode_byte == 0x11 {
                    lo12 // ADD immediate: no scaling
                } else {
                    lo12 >> (insn >> 30) // LDR/STR: scale by access size (bits[31:30])
                };
                buf[offset..offset + 4]
                    .copy_from_slice(&((insn & 0xFFC0_03FF) | (scaled << 10)).to_le_bytes());
            }
        }
        _ => {
            return Err(format!(
            "unsupported COFF ARM64 reloc: {kind:?} enc={encoding:?} size={size} at {offset:#x}"
        ))
        }
    }
    Ok(())
}

// ===========================================================================
// Mach-O direct linker  (macOS x86-64 and arm64, no Xcode / ld required)
// ===========================================================================
//
// Uses LC_UNIXTHREAD (no dyld startup, no __LINKEDIT) with raw syscalls.
// For arm64 (Apple Silicon), appends an ad-hoc code signature — required
// by the kernel for all arm64 executables.
//
// Layout:
//   [0, 0x1000)                Mach-O header + load commands + padding
//   [0x1000, 0x1000+text_sz)  __text  (code + syscall stub + _start)
//   [data_off, data_off+d_sz) __data  (globals, optional)
//   [sig_off, sig_off+sig_sz) code signature (arm64 only)

const MACHO_BASE: u64 = 0x0000_0001_0000_0000; // standard macOS 64-bit load address
const MACHO_PAGE: u64 = 0x1000;

// Mach-O header + load command constants (little-endian)
const MH_MAGIC_64: u32 = 0xFEED_FACF;
const MH_EXECUTE: u32 = 2;
const MH_NOUNDEFS: u32 = 0x1;
const LC_SEGMENT_64: u32 = 0x19;
const LC_UNIXTHREAD: u32 = 0x5;
const LC_CODE_SIGNATURE: u32 = 0x1D;
const VM_PROT_RX: i32 = 5; // READ | EXECUTE
const VM_PROT_RW: i32 = 3; // READ | WRITE
const VM_PROT_RWX: i32 = 7; // READ | WRITE | EXECUTE (maxprot)
const S_ATTR_PURE_INST: u32 = 0x8000_0000;
const S_ATTR_SOME_INST: u32 = 0x0000_0400;

fn link_macho(
    obj_bytes: &[u8],
    runtime_blobs: &[(&str, &[u8])],
    entry_sym: &str,
    arm64: bool,
) -> Result<Vec<u8>, String> {
    let obj =
        ObjFile::parse(obj_bytes).map_err(|e| format!("failed to parse Mach-O object: {e}"))?;

    // ---- Collect sections ----
    let mut text_secs: Vec<Section> = Vec::new();
    let mut data_secs: Vec<Section> = Vec::new();
    for sec in obj.sections() {
        let name = sec.name().unwrap_or("").to_string();
        let raw = sec
            .data()
            .map_err(|e| format!("section '{name}' data: {e}"))?;
        let align = sec.align().max(1);
        let idx = sec.index().0;
        match sec.kind() {
            SectionKind::Text => text_secs.push(Section {
                name,
                kind: SectionKind::Text,
                data: raw.to_vec(),
                align,
                orig_idx: idx,
                seg_offset: 0,
                vaddr: 0,
            }),
            SectionKind::Data | SectionKind::ReadOnlyData => data_secs.push(Section {
                name,
                kind: sec.kind(),
                data: raw.to_vec(),
                align,
                orig_idx: idx,
                seg_offset: 0,
                vaddr: 0,
            }),
            SectionKind::UninitializedData => data_secs.push(Section {
                name,
                kind: SectionKind::UninitializedData,
                data: vec![0u8; sec.size() as usize],
                align,
                orig_idx: idx,
                seg_offset: 0,
                vaddr: 0,
            }),
            _ => {}
        }
    }
    let has_data = !data_secs.is_empty();

    // ---- Layout: __text (file starts at 0x1000, header occupies first page) ----
    let text_file_off: u64 = MACHO_PAGE;
    let text_vaddr = MACHO_BASE + text_file_off;

    let mut cursor: u64 = 0;
    for s in &mut text_secs {
        cursor = align_up(cursor, s.align);
        s.seg_offset = cursor;
        s.vaddr = text_vaddr + cursor;
        cursor += s.data.len() as u64;
    }
    let syscall_align: u64 = if arm64 { 4 } else { 16 };
    let blob_placements: Vec<(&str, u64, usize)> = {
        let mut placements = Vec::new();
        for &(name, bytes) in runtime_blobs {
            cursor = align_up(cursor, syscall_align);
            placements.push((name, cursor, bytes.len()));
            cursor += bytes.len() as u64;
        }
        placements
    };
    cursor = align_up(cursor, syscall_align);
    let start_seg_off = cursor;
    let start_vaddr = text_vaddr + cursor;
    let start_size: u64 = if arm64 { 12 } else { 14 };
    cursor += start_size;

    let text_content_size = cursor;
    let text_seg_filesize = align_up(text_file_off + text_content_size, MACHO_PAGE);
    // __TEXT vmsize covers header+cmds page + text content
    let text_seg_vmsize = text_seg_filesize;

    // ---- Layout: __data (if any) ----
    let data_file_off = text_seg_filesize;
    let data_vaddr = MACHO_BASE + data_file_off;
    cursor = 0;
    for s in &mut data_secs {
        cursor = align_up(cursor, s.align);
        s.seg_offset = cursor;
        s.vaddr = data_vaddr + cursor;
        cursor += s.data.len() as u64;
    }
    let data_content_size = cursor;
    let data_seg_filesize = if has_data {
        align_up(data_content_size, MACHO_PAGE)
    } else {
        0
    };

    // ---- Signature size (arm64 only) ----
    // code_limit = everything before the signature
    let code_limit = data_file_off + data_seg_filesize;
    let n_pages = code_limit.div_ceil(MACHO_PAGE) as usize;
    // SuperBlob(12) + BlobIndex(8) + CodeDirectory(88) + ident(4) + hashes(n*32)
    let sig_size_raw: u64 = if arm64 {
        12 + 8 + 88 + 4 + n_pages as u64 * 32
    } else {
        0
    };
    let sig_size = align_up(sig_size_raw, 16);
    let sig_off = code_limit;

    let total_size = code_limit + sig_size;

    // ---- Load commands ----
    // Sizes: __PAGEZERO(72) + __TEXT(152) + __DATA(152?) + LC_UNIXTHREAD + LC_CODE_SIG?
    let unixthread_size: u64 = if arm64 { 288 } else { 184 };
    let codesig_lc_size: u64 = if arm64 { 16 } else { 0 };
    let mut sizeofcmds: u64 = 72 + 152 + unixthread_size + codesig_lc_size;
    if has_data {
        sizeofcmds += 152;
    }
    let ncmds: u32 = 3 + (if has_data { 1 } else { 0 }) + (if arm64 { 1 } else { 0 });

    // ---- Symbol map ----
    let mut syms: BTreeMap<String, u64> = BTreeMap::new();
    for &(name, seg_off, _) in &blob_placements {
        syms.insert(name.to_string(), text_vaddr + seg_off);
    }
    syms.insert("_start".to_string(), start_vaddr);
    for sym in obj.symbols() {
        let Ok(name) = sym.name() else { continue };
        if name.is_empty() {
            continue;
        }
        let sec_idx = match sym.section() {
            object::read::SymbolSection::Section(i) => i.0,
            _ => continue,
        };
        let offset = sym.address();
        let addr = text_secs
            .iter()
            .find(|s| s.orig_idx == sec_idx)
            .map(|s| s.vaddr + offset)
            .or_else(|| {
                data_secs
                    .iter()
                    .find(|s| s.orig_idx == sec_idx)
                    .map(|s| s.vaddr + offset)
            });
        if let Some(a) = addr {
            syms.insert(name.to_string(), a);
        }
    }

    let entry_addr = *syms
        .get(entry_sym)
        .ok_or_else(|| format!("entry symbol '{entry_sym}' not found"))?;

    // ---- Merge section data ----
    let text_buf_size = align_up(text_content_size, MACHO_PAGE);
    let mut text_buf = vec![0u8; text_buf_size as usize];
    for s in &text_secs {
        let e = s.seg_offset as usize + s.data.len();
        text_buf[s.seg_offset as usize..e].copy_from_slice(&s.data);
    }
    for (&(_, bytes), &(_, seg_off, len)) in runtime_blobs.iter().zip(blob_placements.iter()) {
        text_buf[seg_off as usize..seg_off as usize + len].copy_from_slice(bytes);
    }
    if arm64 {
        write_start_macho_arm64(
            &mut text_buf[start_seg_off as usize..],
            entry_addr,
            start_vaddr,
        );
    } else {
        write_start_macho_x86_64(
            &mut text_buf[start_seg_off as usize..],
            entry_addr,
            start_vaddr,
        );
    }

    let data_buf_size = data_seg_filesize;
    let mut data_buf = vec![0u8; data_buf_size as usize];
    for s in &data_secs {
        let e = s.seg_offset as usize + s.data.len();
        data_buf[s.seg_offset as usize..e].copy_from_slice(&s.data);
    }

    // ---- Apply relocations ----
    for sec in obj.sections() {
        let sec_idx = sec.index().0;
        let (is_text, seg_off, sec_vaddr) =
            if let Some(s) = text_secs.iter().find(|s| s.orig_idx == sec_idx) {
                (true, s.seg_offset, s.vaddr)
            } else if let Some(s) = data_secs.iter().find(|s| s.orig_idx == sec_idx) {
                (false, s.seg_offset, s.vaddr)
            } else {
                continue;
            };

        for (reloc_off, reloc) in sec.relocations() {
            let sym_addr = match reloc.target() {
                RelocationTarget::Symbol(sym_idx) => {
                    let sym = obj
                        .symbol_by_index(sym_idx)
                        .map_err(|e| format!("bad symbol index: {e}"))?;
                    let name = sym.name().unwrap_or("");
                    *syms
                        .get(name)
                        .ok_or_else(|| format!("undefined symbol '{name}'"))?
                }
                RelocationTarget::Section(tidx) => {
                    let t = tidx.0;
                    text_secs
                        .iter()
                        .find(|s| s.orig_idx == t)
                        .map(|s| s.vaddr)
                        .or_else(|| data_secs.iter().find(|s| s.orig_idx == t).map(|s| s.vaddr))
                        .ok_or_else(|| format!("section reloc target {t} not found"))?
                }
                _ => continue,
            };

            let patch_loc = (seg_off + reloc_off) as usize;
            let reloc_va = sec_vaddr + reloc_off;
            // For Mach-O: addend = bytes_at_place + reloc.addend()
            // (reloc.addend() carries the -4 adjustment for x86-64 PC-relative,
            //  or the ARM64_RELOC_ADDEND value for arm64)
            let addend: i64 = {
                let src: &[u8] = if is_text { &text_buf } else { &data_buf };
                let implicit: i64 = if reloc.has_implicit_addend() {
                    match reloc.size() {
                        32 => i32::from_le_bytes(src[patch_loc..patch_loc + 4].try_into().unwrap())
                            as i64,
                        64 => i64::from_le_bytes(src[patch_loc..patch_loc + 8].try_into().unwrap()),
                        _ => 0,
                    }
                } else {
                    0
                };
                implicit + reloc.addend()
            };

            let buf = if is_text {
                &mut text_buf
            } else {
                &mut data_buf
            };
            if arm64 {
                apply_reloc_macho_arm64(buf, patch_loc, reloc.flags(), sym_addr, addend, reloc_va)?;
            } else {
                apply_reloc_macho_x86_64(
                    buf,
                    patch_loc,
                    reloc.flags(),
                    sym_addr,
                    addend,
                    reloc_va,
                )?;
            }
        }
    }

    // ---- Assemble file ----
    let mut file = vec![0u8; total_size as usize];

    // Mach-O header (32 bytes at offset 0)
    {
        let (cputype, cpusubtype): (i32, i32) = if arm64 {
            (0x0100_000C, 0) // ARM64, ALL
        } else {
            (0x0100_0007, 3) // X86_64, ALL
        };
        let h = &mut file[0..32];
        put_u32(&mut h[0..], MH_MAGIC_64);
        put_u32(&mut h[4..], cputype as u32);
        put_u32(&mut h[8..], cpusubtype as u32);
        put_u32(&mut h[12..], MH_EXECUTE);
        put_u32(&mut h[16..], ncmds);
        put_u32(&mut h[20..], sizeofcmds as u32);
        put_u32(&mut h[24..], MH_NOUNDEFS);
        // h[28]: reserved (already 0)
    }

    // Load commands starting at offset 32
    let mut lc = 32usize;

    // LC_SEGMENT_64 __PAGEZERO
    macho_segment(
        &mut file[lc..],
        "__PAGEZERO\0\0\0\0\0\0",
        0,
        0x100000000u64,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    );
    lc += 72;

    // LC_SEGMENT_64 __TEXT (contains __text section)
    macho_segment(
        &mut file[lc..],
        "__TEXT\0\0\0\0\0\0\0\0\0\0",
        MACHO_BASE,
        text_seg_vmsize,
        0,
        text_seg_filesize,
        VM_PROT_RWX,
        VM_PROT_RX,
        1,
        0,
        72 + 80,
    );
    macho_section(
        &mut file[lc + 72..],
        "__text\0\0\0\0\0\0\0\0\0\0",
        "__TEXT\0\0\0\0\0\0\0\0\0\0",
        text_vaddr,
        text_content_size,
        text_file_off as u32,
        if arm64 { 2 } else { 4 },
        S_ATTR_PURE_INST | S_ATTR_SOME_INST,
    );
    lc += 152;

    // LC_SEGMENT_64 __DATA (optional)
    if has_data {
        macho_segment(
            &mut file[lc..],
            "__DATA\0\0\0\0\0\0\0\0\0\0",
            data_vaddr,
            data_seg_filesize,
            data_file_off,
            data_seg_filesize,
            VM_PROT_RWX,
            VM_PROT_RW,
            1,
            0,
            72 + 80,
        );
        macho_section(
            &mut file[lc + 72..],
            "__data\0\0\0\0\0\0\0\0\0\0",
            "__DATA\0\0\0\0\0\0\0\0\0\0",
            data_vaddr,
            data_content_size,
            data_file_off as u32,
            3,
            0,
        );
        lc += 152;
    }

    // LC_UNIXTHREAD
    if arm64 {
        macho_unixthread_arm64(&mut file[lc..], start_vaddr);
        lc += 288;
    } else {
        macho_unixthread_x86_64(&mut file[lc..], start_vaddr);
        lc += 184;
    }

    // LC_CODE_SIGNATURE (arm64)
    if arm64 {
        let h = &mut file[lc..lc + 16];
        put_u32(&mut h[0..], LC_CODE_SIGNATURE);
        put_u32(&mut h[4..], 16);
        put_u32(&mut h[8..], sig_off as u32);
        put_u32(&mut h[12..], sig_size as u32);
        lc += 16;
    }
    let _ = lc; // suppress unused warning

    // Copy section data
    let te = text_file_off as usize + text_buf.len();
    file[text_file_off as usize..te].copy_from_slice(&text_buf);
    if has_data && data_seg_filesize > 0 {
        file[data_file_off as usize..data_file_off as usize + data_buf.len()]
            .copy_from_slice(&data_buf);
    }

    // Append code signature (arm64)
    if arm64 {
        let sig = build_adhoc_signature(&file[..code_limit as usize], n_pages, sig_size as usize);
        file[sig_off as usize..sig_off as usize + sig.len()].copy_from_slice(&sig);
    }

    Ok(file)
}

// ---------------------------------------------------------------------------
// Mach-O load command writers
// ---------------------------------------------------------------------------

#[allow(clippy::too_many_arguments)]
fn macho_segment(
    buf: &mut [u8],
    segname: &str,
    vmaddr: u64,
    vmsize: u64,
    fileoff: u64,
    filesize: u64,
    maxprot: i32,
    initprot: i32,
    nsects: u32,
    flags: u32,
    cmdsize: u32,
) {
    put_u32(&mut buf[0..], LC_SEGMENT_64);
    put_u32(&mut buf[4..], cmdsize);
    let nb = segname.len().min(16);
    buf[8..8 + nb].copy_from_slice(&segname.as_bytes()[..nb]);
    put_u64(&mut buf[24..], vmaddr);
    put_u64(&mut buf[32..], vmsize);
    put_u64(&mut buf[40..], fileoff);
    put_u64(&mut buf[48..], filesize);
    put_u32(&mut buf[56..], maxprot as u32);
    put_u32(&mut buf[60..], initprot as u32);
    put_u32(&mut buf[64..], nsects);
    put_u32(&mut buf[68..], flags);
}

#[allow(clippy::too_many_arguments)]
fn macho_section(
    buf: &mut [u8],
    sectname: &str,
    segname: &str,
    addr: u64,
    size: u64,
    offset: u32,
    align_pow2: u32,
    flags: u32,
) {
    let sn = sectname.len().min(16);
    buf[0..sn].copy_from_slice(&sectname.as_bytes()[..sn]);
    let gn = segname.len().min(16);
    buf[16..16 + gn].copy_from_slice(&segname.as_bytes()[..gn]);
    put_u64(&mut buf[32..], addr);
    put_u64(&mut buf[40..], size);
    put_u32(&mut buf[48..], offset);
    put_u32(&mut buf[52..], align_pow2);
    // reloff, nreloc = 0 (already zero)
    put_u32(&mut buf[64..], flags);
    // reserved1,2,3 = 0
}

fn macho_unixthread_x86_64(buf: &mut [u8], rip: u64) {
    put_u32(&mut buf[0..], LC_UNIXTHREAD);
    put_u32(&mut buf[4..], 184);
    put_u32(&mut buf[8..], 4); // x86_THREAD_STATE64
    put_u32(&mut buf[12..], 42); // count = 168 / 4
                                 // thread state: 168 bytes, all zeros except rip at offset 128 (= buf offset 16+128=144)
    put_u64(&mut buf[144..], rip);
}

fn macho_unixthread_arm64(buf: &mut [u8], pc: u64) {
    put_u32(&mut buf[0..], LC_UNIXTHREAD);
    put_u32(&mut buf[4..], 288);
    put_u32(&mut buf[8..], 6); // ARM_THREAD_STATE64
    put_u32(&mut buf[12..], 68); // count = 272 / 4
                                 // thread state: 272 bytes, all zeros except pc at offset 256 (= buf offset 16+256=272)
    put_u64(&mut buf[272..], pc);
}

// ---------------------------------------------------------------------------
// _start stubs for macOS
// ---------------------------------------------------------------------------

// x86-64 macOS _start (14 bytes)
//   call <entry>       E8 XX XX XX XX  (5)
//   mov edi, eax       89 C7           (2)  -- exit code in edi (SysV arg1)
//   mov eax, 0x2000001 B8 01 00 00 02  (5)  -- macOS exit syscall
//   syscall            0F 05           (2)
fn write_start_macho_x86_64(buf: &mut [u8], entry_addr: u64, start_vaddr: u64) {
    let rel = (entry_addr as i64 - (start_vaddr as i64 + 5)) as i32;
    buf[0] = 0xE8;
    buf[1..5].copy_from_slice(&rel.to_le_bytes());
    buf[5] = 0x89;
    buf[6] = 0xC7; // mov edi, eax
    buf[7] = 0xB8;
    buf[8] = 0x01;
    buf[9] = 0x00;
    buf[10] = 0x00;
    buf[11] = 0x02; // 0x2000001
    buf[12] = 0x0F;
    buf[13] = 0x05; // syscall
}

// arm64 macOS _start (12 bytes)
//   bl <entry>   4 bytes — x0 = return value
//   mov x16, #1  4 bytes — macOS exit syscall (MOVZ x16, #1)
//   svc #0x80    4 bytes — 0xD4001001
fn write_start_macho_arm64(buf: &mut [u8], entry_addr: u64, start_vaddr: u64) {
    let delta = ((entry_addr as i64) - (start_vaddr as i64)) >> 2;
    let imm26 = (delta as u32) & 0x3FF_FFFF;
    put_u32(&mut buf[0..], 0x9400_0000 | imm26); // BL
    put_u32(&mut buf[4..], 0xD280_0000 | (1u32 << 5) | 16); // MOVZ x16, #1
    put_u32(&mut buf[8..], 0xD400_1001); // SVC #0x80
}

// ---------------------------------------------------------------------------
// Mach-O x86-64 relocation application
//
// The object crate pre-adjusts addend for x86-64 PC-relative relocations:
// addend already has -4 applied (for end-of-field RIP base), so the standard
// S + A - P formula produces the correct result.
// ---------------------------------------------------------------------------
fn apply_reloc_macho_x86_64(
    buf: &mut [u8],
    offset: usize,
    flags: RelocationFlags,
    sym_addr: u64,
    addend: i64,
    reloc_va: u64,
) -> Result<(), String> {
    match flags {
        RelocationFlags::Generic { kind, size, .. } => match (kind, size) {
            // X86_64_RELOC_UNSIGNED (r_type=0, r_pcrel=false) — absolute
            (RelocationKind::Absolute, 64) => {
                let v = (sym_addr as i64 + addend) as u64;
                buf[offset..offset + 8].copy_from_slice(&v.to_le_bytes());
            }
            (RelocationKind::Absolute, 32) => {
                let v = (sym_addr as i64 + addend) as u32;
                buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
            }
            // X86_64_RELOC_BRANCH / X86_64_RELOC_SIGNED (r_pcrel=true)
            // addend already includes -4 from object crate; formula: S + A - P
            (RelocationKind::Relative, 32) => {
                let v = (sym_addr as i64 + addend - reloc_va as i64) as i32;
                buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
            }
            // X86_64_RELOC_GOT / GOT_LOAD — treat as PC-relative for static link
            (RelocationKind::GotRelative, 32) => {
                let v = (sym_addr as i64 + addend - reloc_va as i64) as i32;
                buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
            }
            _ => {
                return Err(format!(
                    "unsupported Mach-O x86-64 reloc: {kind:?} size={size} at {offset:#x}"
                ))
            }
        },
        other => {
            return Err(format!(
                "unexpected Mach-O x86-64 reloc flags: {other:?} at {offset:#x}"
            ))
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Mach-O arm64 relocation application
//
// Most arm64 Mach-O relocations come as RelocationFlags::MachO { r_type, ... }
// since the object crate only maps ARM64_RELOC_UNSIGNED to a Generic kind.
// ARM64_RELOC_ADDEND pairs are consumed by the object crate; the resulting
// addend arrives in the `addend` parameter.
// ---------------------------------------------------------------------------
fn apply_reloc_macho_arm64(
    buf: &mut [u8],
    offset: usize,
    flags: RelocationFlags,
    sym_addr: u64,
    addend: i64,
    reloc_va: u64,
) -> Result<(), String> {
    let r_type = match flags {
        RelocationFlags::MachO { r_type, .. } => r_type,
        RelocationFlags::Generic {
            kind: RelocationKind::Absolute,
            size: 64,
            ..
        } => 0,
        other => {
            return Err(format!(
                "unexpected Mach-O arm64 reloc flags: {other:?} at {offset:#x}"
            ))
        }
    };

    let target = (sym_addr as i64).wrapping_add(addend);

    match r_type {
        // ARM64_RELOC_UNSIGNED (0) — absolute 64-bit (r_length=3) or 32-bit (r_length=2)
        0 => match flags {
            RelocationFlags::MachO { r_length: 3, .. }
            | RelocationFlags::Generic { size: 64, .. } => {
                buf[offset..offset + 8].copy_from_slice(&(target as u64).to_le_bytes());
            }
            _ => {
                buf[offset..offset + 4].copy_from_slice(&(target as u32).to_le_bytes());
            }
        },
        // ARM64_RELOC_BRANCH26 (2) — BL/B: (S+A-P)>>2 into bits[25:0]
        2 => {
            let delta = (target - reloc_va as i64) >> 2;
            let imm26 = (delta as i32) & 0x3FF_FFFF;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            buf[offset..offset + 4].copy_from_slice(
                &((insn & 0xFC00_0000) | (imm26 as u32 & 0x3FF_FFFF)).to_le_bytes(),
            );
        }
        // ARM64_RELOC_PAGE21 (3) — ADRP
        3 => {
            let sym_page = target & !0xFFF;
            let pc_page = (reloc_va as i64) & !0xFFF;
            let delta = (sym_page - pc_page) >> 12;
            let immlo = (delta as u32) & 0x3;
            let immhi = ((delta as u32) >> 2) & 0x7_FFFF;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            buf[offset..offset + 4].copy_from_slice(
                &((insn & 0x9F00_001F) | (immlo << 29) | (immhi << 5)).to_le_bytes(),
            );
        }
        // ARM64_RELOC_PAGEOFF12 (4) — ADD imm12 or LDR/STR scaled offset
        4 => {
            let lo12 = (target as u32) & 0xFFF;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            // Detect ADD (opcode 0x91 = 64-bit ADD imm, 0x11 = 32-bit ADD imm)
            let opcode_byte = (insn >> 24) as u8;
            let scaled = if opcode_byte == 0x91 || opcode_byte == 0x11 {
                lo12 // ADD: no scaling
            } else {
                lo12 >> (insn >> 30) // LDR/STR: scale by access size
            };
            buf[offset..offset + 4]
                .copy_from_slice(&((insn & 0xFFC0_03FF) | (scaled << 10)).to_le_bytes());
        }
        // ARM64_RELOC_GOT_LOAD_PAGE21 (5) — treat as PAGE21 for static link
        5 => {
            let sym_page = target & !0xFFF;
            let pc_page = (reloc_va as i64) & !0xFFF;
            let delta = (sym_page - pc_page) >> 12;
            let immlo = (delta as u32) & 0x3;
            let immhi = ((delta as u32) >> 2) & 0x7_FFFF;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            buf[offset..offset + 4].copy_from_slice(
                &((insn & 0x9F00_001F) | (immlo << 29) | (immhi << 5)).to_le_bytes(),
            );
        }
        // ARM64_RELOC_GOT_LOAD_PAGEOFF12 (6) — treat as PAGEOFF12 for static link
        6 => {
            let lo12 = (target as u32) & 0xFFF;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            let opcode_byte = (insn >> 24) as u8;
            let scaled = if opcode_byte == 0x91 || opcode_byte == 0x11 {
                lo12
            } else {
                lo12 >> (insn >> 30)
            };
            buf[offset..offset + 4]
                .copy_from_slice(&((insn & 0xFFC0_03FF) | (scaled << 10)).to_le_bytes());
        }
        _ => {
            return Err(format!(
                "unsupported Mach-O arm64 reloc r_type={r_type} at {offset:#x}"
            ))
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Ad-hoc code signature for arm64 macOS
//
// Structure: CS_SuperBlob → CS_BlobIndex → CS_CodeDirectory → hashes
// The signature data is appended after all mapped content (code_limit bytes).
// ---------------------------------------------------------------------------
fn build_adhoc_signature(data: &[u8], n_pages: usize, total_sig_size: usize) -> Vec<u8> {
    const CSMAGIC_EMBEDDED_SIGNATURE: u32 = 0xFADE_0CC0;
    const CSMAGIC_CODEDIRECTORY: u32 = 0xFADE_0C02;
    const CS_ADHOC: u32 = 0x0000_0002;
    const CS_EXECSEG_MAIN_BINARY: u64 = 0x1;
    const CD_VERSION: u32 = 0x0002_0400;
    const HASH_SHA256: u8 = 2;
    const PAGE_LOG: u8 = 12; // log2(4096)
    const HASH_SIZE: u8 = 32;

    let code_limit = data.len() as u32;

    // Identifier string embedded in CodeDirectory: "dyn\0"
    let ident = b"dyn\0";

    // CodeDirectory layout:
    //   [0..88)    fixed fields
    //   [88..92)   identifier ("dyn\0")
    //   [92..)     n_pages × 32-byte SHA-256 hashes
    let cd_fixed: usize = 88;
    let ident_off: u32 = cd_fixed as u32;
    let hash_off: u32 = cd_fixed as u32 + ident.len() as u32;
    let cd_size = cd_fixed + ident.len() + n_pages * 32;

    // SuperBlob: 12-byte header + 8-byte BlobIndex + CodeDirectory
    let superblob_size = 12 + 8 + cd_size;

    let mut sig = vec![0u8; total_sig_size];

    // SuperBlob header
    put_u32_be(&mut sig[0..], CSMAGIC_EMBEDDED_SIGNATURE);
    put_u32_be(&mut sig[4..], superblob_size as u32);
    put_u32_be(&mut sig[8..], 1); // count = 1

    // BlobIndex[0]: type=0 (CSSLOT_CODEDIRECTORY), offset=20 (after 12+8)
    put_u32_be(&mut sig[12..], 0);
    put_u32_be(&mut sig[16..], 20);

    // CodeDirectory (starts at sig[20])
    let cd = &mut sig[20..20 + cd_size];
    put_u32_be(&mut cd[0..], CSMAGIC_CODEDIRECTORY);
    put_u32_be(&mut cd[4..], cd_size as u32);
    put_u32_be(&mut cd[8..], CD_VERSION);
    put_u32_be(&mut cd[12..], CS_ADHOC);
    put_u32_be(&mut cd[16..], hash_off); // hashOffset
    put_u32_be(&mut cd[20..], ident_off); // identOffset
                                          // nSpecialSlots = 0 (already 0)
    put_u32_be(&mut cd[28..], n_pages as u32); // nCodeSlots
    put_u32_be(&mut cd[32..], code_limit);
    cd[36] = HASH_SIZE;
    cd[37] = HASH_SHA256;
    // platform = 0
    cd[39] = PAGE_LOG;
    // spare2, scatterOffset, teamOffset, spare3 = 0
    // codeLimit64 = 0
    // execSegBase = 0 (TEXT segment starts at file offset 0)
    let text_seg_limit = align_up(0x1000 + (code_limit as u64), MACHO_PAGE); // __TEXT filesize
    put_u64_be(&mut cd[72..], text_seg_limit);
    put_u64_be(&mut cd[80..], CS_EXECSEG_MAIN_BINARY);

    // Identifier
    cd[cd_fixed..cd_fixed + ident.len()].copy_from_slice(ident);

    // Page hashes
    for i in 0..n_pages {
        let start = i * 4096;
        let end = ((i + 1) * 4096).min(data.len());
        let hash = if end - start < 4096 {
            let mut page = [0u8; 4096];
            page[..end - start].copy_from_slice(&data[start..end]);
            sha256(&page)
        } else {
            sha256(&data[start..end])
        };
        let h_off = cd_fixed + ident.len() + i * 32;
        cd[h_off..h_off + 32].copy_from_slice(&hash);
    }

    sig
}

fn put_u32_be(buf: &mut [u8], v: u32) {
    buf[..4].copy_from_slice(&v.to_be_bytes());
}
fn put_u64_be(buf: &mut [u8], v: u64) {
    buf[..8].copy_from_slice(&v.to_be_bytes());
}

// ---------------------------------------------------------------------------
// SHA-256 (inline, no external dependency)
// ---------------------------------------------------------------------------
fn sha256(data: &[u8]) -> [u8; 32] {
    #[rustfmt::skip]
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
        0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
        0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
        0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
        0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
        0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
        0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
        0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
        0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
        0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
        0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
        0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
    ];
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];

    let bit_len = (data.len() as u64) * 8;
    let mut padded = data.to_vec();
    padded.push(0x80);
    while padded.len() % 64 != 56 {
        padded.push(0);
    }
    padded.extend_from_slice(&bit_len.to_be_bytes());

    for chunk in padded.chunks(64) {
        let mut w = [0u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes(chunk[i * 4..i * 4 + 4].try_into().unwrap());
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh] = h;
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ (!e & g);
            let t1 = hh
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
        h[5] = h[5].wrapping_add(f);
        h[6] = h[6].wrapping_add(g);
        h[7] = h[7].wrapping_add(hh);
    }

    let mut out = [0u8; 32];
    for (i, word) in h.iter().enumerate() {
        out[i * 4..i * 4 + 4].copy_from_slice(&word.to_be_bytes());
    }
    out
}
fn edge_args(
    from_block: usize,
    to_block: usize,
    phi_layout: &PhiLayout,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    pointer_ty: Type,
    scalar: ScalarType,
    builder: &mut FunctionBuilder,
) -> Vec<Value> {
    let mut args = Vec::new();
    if let Some(phi_entries) = phi_layout.get(&to_block) {
        for (_, source_map, ty) in phi_entries {
            if matches!(ty, MirValueType::BytesSlice) {
                let (ptr, len) = source_map
                    .get(&from_block)
                    .and_then(|id| lowered.get(id))
                    .map(|value| match value {
                        LoweredValue::BytesSlice { ptr, len } => (*ptr, *len),
                        _ => (
                            value
                                .as_value()
                                .map(|v| cast_scalar(builder, v, pointer_ty, scalar))
                                .unwrap_or_else(|| zero_for_type(builder, pointer_ty)),
                            zero_for_type(builder, pointer_ty),
                        ),
                    })
                    .unwrap_or_else(|| {
                        (
                            zero_for_type(builder, pointer_ty),
                            zero_for_type(builder, pointer_ty),
                        )
                    });
                args.push(ptr);
                args.push(len);
            } else {
                let phi_ty = if matches!(ty, MirValueType::Unknown) {
                    pointer_ty
                } else {
                    mir_type_to_clif(ty, scalar)
                };
                let value = source_map
                    .get(&from_block)
                    .and_then(|id| lowered.get(id))
                    .and_then(|value| match value {
                        LoweredValue::StructMemory { slot, .. } => {
                            Some(builder.ins().stack_addr(pointer_ty, *slot, 0))
                        }
                        LoweredValue::StructPointer {
                            addr,
                            stack_slot,
                            stack_offset,
                            ..
                        } => Some(rematerialize_struct_pointer_addr(
                            builder,
                            pointer_ty,
                            *addr,
                            *stack_slot,
                            *stack_offset,
                        )),
                        _ => value.as_value(),
                    })
                    .map(|value| cast_scalar(builder, value, phi_ty, scalar))
                    .unwrap_or_else(|| zero_for_type(builder, phi_ty));
                args.push(value);
            }
        }
    }
    args
}

fn emit_goto_terminator(
    from_block: usize,
    target: MirBlockId,
    phi_layout: &PhiLayout,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    pointer_ty: Type,
    scalar: ScalarType,
    clif_blocks: &[Block],
    builder: &mut FunctionBuilder,
) {
    let args = edge_args(
        from_block, target.0, phi_layout, lowered, pointer_ty, scalar, builder,
    );
    builder.ins().jump(clif_blocks[target.0], &args);
}

fn emit_branch_terminator(
    from_block: usize,
    condition: MirValueId,
    then_block: MirBlockId,
    else_block: MirBlockId,
    phi_layout: &PhiLayout,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    pointer_ty: Type,
    scalar: ScalarType,
    clif_blocks: &[Block],
    builder: &mut FunctionBuilder,
) {
    let cond = lowered
        .get(&condition)
        .and_then(LoweredValue::as_int)
        .unwrap_or_else(|| zero_for_scalar(builder, scalar));
    let then_args = edge_args(
        from_block,
        then_block.0,
        phi_layout,
        lowered,
        pointer_ty,
        scalar,
        builder,
    );
    let else_args = edge_args(
        from_block,
        else_block.0,
        phi_layout,
        lowered,
        pointer_ty,
        scalar,
        builder,
    );
    builder.ins().brif(
        cond,
        clif_blocks[then_block.0],
        &then_args,
        clif_blocks[else_block.0],
        &else_args,
    );
}

fn emit_unreachable_terminator(builder: &mut FunctionBuilder) {
    builder.ins().trap(TrapCode::unwrap_user(1));
}

fn seal_terminator_successors(
    terminator: &Option<MirTerminator>,
    clif_blocks: &[Block],
    sealed: &mut BTreeSet<usize>,
    builder: &mut FunctionBuilder,
) {
    match terminator {
        Some(MirTerminator::Goto(target)) => {
            seal_block_if_needed(*target, clif_blocks, sealed, builder);
        }
        Some(MirTerminator::Branch {
            then_block,
            else_block,
            ..
        }) => {
            seal_block_if_needed(*then_block, clif_blocks, sealed, builder);
            seal_block_if_needed(*else_block, clif_blocks, sealed, builder);
        }
        _ => {}
    }
}

fn seal_block_if_needed(
    block: MirBlockId,
    clif_blocks: &[Block],
    sealed: &mut BTreeSet<usize>,
    builder: &mut FunctionBuilder,
) {
    if sealed.insert(block.0) {
        builder.seal_block(clif_blocks[block.0]);
    }
}

fn emit_function_return(
    module: &mut ObjectModule,
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    value: Option<MirValueId>,
    profile: &FunctionReturnProfile<'_>,
    out_ptrs: FunctionReturnOutPtrs,
    value_defs: &BTreeMap<MirValueId, MirValue>,
    value_types: &BTreeMap<MirValueId, MirValueType>,
    symbols_by_name: &BTreeMap<String, FuncId>,
    returns_unknown_nominal_by_id: &BTreeMap<u32, bool>,
) {
    if profile.returns_bytes_slice {
        emit_bytes_slice_return(module, builder, lowered, value, profile, out_ptrs);
    } else if let Some(layout) = profile.returns_aggregate_layout {
        emit_aggregate_return(builder, lowered, value, profile, out_ptrs, layout);
    } else if profile.returns_errorable_scalar {
        emit_errorable_scalar_return(
            module,
            builder,
            lowered,
            value,
            profile,
            out_ptrs,
            value_defs,
            value_types,
            symbols_by_name,
            returns_unknown_nominal_by_id,
        );
    } else {
        emit_scalar_return(module, builder, lowered, value, profile);
    }
}

fn emit_bytes_slice_return(
    module: &mut ObjectModule,
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    value: Option<MirValueId>,
    profile: &FunctionReturnProfile<'_>,
    out_ptrs: FunctionReturnOutPtrs,
) {
    let (ret_ptr, ret_len) = value
        .and_then(|id| lowered.get(&id))
        .map(|value| match value {
            LoweredValue::BytesSlice { ptr, len } => (*ptr, *len),
            LoweredValue::FunctionSymbol(func_id) => {
                let func_ref = module.declare_func_in_func(*func_id, builder.func);
                let ptr = builder.ins().func_addr(profile.pointer_ty, func_ref);
                let len = zero_for_type(builder, profile.pointer_ty);
                (ptr, len)
            }
            _ => (
                value
                    .as_value()
                    .map(|v| cast_scalar(builder, v, profile.pointer_ty, profile.scalar))
                    .unwrap_or_else(|| zero_for_type(builder, profile.pointer_ty)),
                zero_for_type(builder, profile.pointer_ty),
            ),
        })
        .unwrap_or_else(|| {
            (
                zero_for_type(builder, profile.pointer_ty),
                zero_for_type(builder, profile.pointer_ty),
            )
        });

    if let Some(out_len_ptr) = out_ptrs.out_len_ptr {
        builder.ins().store(
            cranelift_codegen::ir::MemFlags::new(),
            ret_len,
            out_len_ptr,
            0,
        );
    }

    builder.ins().return_(&[ret_ptr]);
}

fn emit_aggregate_return(
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    value: Option<MirValueId>,
    profile: &FunctionReturnProfile<'_>,
    out_ptrs: FunctionReturnOutPtrs,
    layout: &AggregateLayout,
) {
    let out_ptr = out_ptrs
        .out_aggregate_ptr
        .unwrap_or_else(|| zero_for_type(builder, profile.pointer_ty));
    if profile.returns_errorable {
        let status = if let Some(ret_value) = value.and_then(|id| lowered.get(&id)).cloned() {
            match ret_value {
                LoweredValue::StructPointer {
                    status: Some(status),
                    ..
                } => {
                    write_aggregate_to_pointer(builder, out_ptr, layout, &ret_value);
                    cast_scalar(builder, status, profile.signature_ret_ty, profile.scalar)
                }
                LoweredValue::StructMemory { .. }
                | LoweredValue::StructPointer { .. }
                | LoweredValue::Struct(_) => {
                    write_aggregate_to_pointer(builder, out_ptr, layout, &ret_value);
                    zero_for_type(builder, profile.signature_ret_ty)
                }
                _ => ret_value
                    .as_int()
                    .map(|v| cast_scalar(builder, v, profile.signature_ret_ty, profile.scalar))
                    .unwrap_or_else(|| zero_for_type(builder, profile.signature_ret_ty)),
            }
        } else {
            zero_for_type(builder, profile.signature_ret_ty)
        };
        builder.ins().return_(&[status]);
    } else {
        if let Some(ret_value) = value.and_then(|id| lowered.get(&id)).cloned() {
            write_aggregate_to_pointer(builder, out_ptr, layout, &ret_value);
        } else {
            zero_aggregate_at_pointer(builder, out_ptr, layout);
        }
        builder.ins().return_(&[out_ptr]);
    }
}

fn emit_errorable_scalar_return(
    module: &mut ObjectModule,
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    value: Option<MirValueId>,
    profile: &FunctionReturnProfile<'_>,
    out_ptrs: FunctionReturnOutPtrs,
    value_defs: &BTreeMap<MirValueId, MirValue>,
    value_types: &BTreeMap<MirValueId, MirValueType>,
    symbols_by_name: &BTreeMap<String, FuncId>,
    returns_unknown_nominal_by_id: &BTreeMap<u32, bool>,
) {
    let out_ptr = out_ptrs
        .out_errorable_scalar_ptr
        .unwrap_or_else(|| zero_for_type(builder, profile.pointer_ty));
    let payload_ty = if matches!(profile.errorable_scalar_payload_ty, MirValueType::Unknown) {
        profile.scalar.ty()
    } else {
        mir_type_to_clif(&profile.errorable_scalar_payload_ty, profile.scalar)
    };

    let mut status = zero_for_type(builder, profile.signature_ret_ty);
    let mut payload = zero_for_type(builder, payload_ty);

    if let Some(value_id) = value {
        if let Some(ret_value) = lowered.get(&value_id).cloned() {
            match ret_value {
                LoweredValue::ErrorableScalar {
                    status: inner_status,
                    payload: inner_payload,
                    ..
                } => {
                    status = cast_scalar(
                        builder,
                        inner_status,
                        profile.signature_ret_ty,
                        profile.scalar,
                    );
                    payload = cast_scalar(builder, inner_payload, payload_ty, profile.scalar);
                }
                other => {
                    let is_explicit_error =
                        mir_value_resolves_to_empty_enum_variant(value_id, value_defs, 0)
                            || mir_value_resolves_to_error_status(value_id, value_defs, 0)
                            || mir_value_resolves_to_unknown_nominal_call(
                                value_id,
                                value_defs,
                                symbols_by_name,
                                returns_unknown_nominal_by_id,
                                0,
                            )
                            || (!matches!(
                                profile.errorable_scalar_payload_ty,
                                MirValueType::Unknown
                            ) && value_types
                                .get(&value_id)
                                .is_some_and(|ty| matches!(ty, MirValueType::Unknown)));

                    if is_explicit_error {
                        status = other
                            .as_int()
                            .map(|v| {
                                cast_scalar(builder, v, profile.signature_ret_ty, profile.scalar)
                            })
                            .unwrap_or_else(|| zero_for_type(builder, profile.signature_ret_ty));
                    } else {
                        payload = match other {
                            LoweredValue::FunctionSymbol(func_id) => {
                                let func_ref = module.declare_func_in_func(func_id, builder.func);
                                let addr = builder.ins().func_addr(profile.pointer_ty, func_ref);
                                cast_scalar(builder, addr, payload_ty, profile.scalar)
                            }
                            _ => other
                                .as_value()
                                .map(|v| cast_scalar(builder, v, payload_ty, profile.scalar))
                                .unwrap_or_else(|| zero_for_type(builder, payload_ty)),
                        };
                    }
                }
            }
        }
    }

    builder
        .ins()
        .store(cranelift_codegen::ir::MemFlags::new(), payload, out_ptr, 0);
    builder.ins().return_(&[status]);
}

fn emit_scalar_return(
    module: &mut ObjectModule,
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    value: Option<MirValueId>,
    profile: &FunctionReturnProfile<'_>,
) {
    let ret = value
        .and_then(|id| lowered.get(&id))
        .and_then(|value| match value {
            LoweredValue::FunctionSymbol(func_id) => {
                let func_ref = module.declare_func_in_func(*func_id, builder.func);
                Some(builder.ins().func_addr(profile.pointer_ty, func_ref))
            }
            _ => value.as_value(),
        })
        .map(|value| cast_scalar(builder, value, profile.signature_ret_ty, profile.scalar))
        .unwrap_or_else(|| zero_for_type(builder, profile.signature_ret_ty));
    builder.ins().return_(&[ret]);
}

#[derive(Debug, Clone)]
enum LoweredValue {
    Int(Value),
    Float(Value),
    BytesSlice {
        ptr: Value,
        len: Value,
    },
    FunctionSymbol(FuncId),
    ErrorableScalar {
        status: Value,
        payload: Value,
        payload_is_float: bool,
    },
    Struct(BTreeMap<String, LoweredValue>),
    StructMemory {
        slot: StackSlot,
        fields: BTreeMap<String, (Type, i32)>,
        aggregate_fields: BTreeMap<String, (i32, Box<AggregateLayout>)>,
        ordered: Vec<(Type, i32)>,
        scalar_leaves: Vec<(Type, i32)>,
        size: u32,
        align: u32,
    },
    StructPointer {
        addr: Value,
        stack_slot: Option<StackSlot>,
        stack_offset: i32,
        status: Option<Value>,
        fields: BTreeMap<String, (Type, i32)>,
        aggregate_fields: BTreeMap<String, (i32, Box<AggregateLayout>)>,
        ordered: Vec<(Type, i32)>,
        scalar_leaves: Vec<(Type, i32)>,
        size: u32,
        align: u32,
    },
    PointerSlice {
        base_addr: Value,
        len: Value,
        elem_ty: Type,
        stride: i64,
    },
    EnumVariant {
        variant: String,
        payload: Vec<LoweredValue>,
    },
    EnumMemory {
        slot: StackSlot,
        ordered: Vec<(Type, i32)>,
    },
    /// Fat pointer closure: (fn_ptr, env_ptr)
    FatPtr {
        fn_ptr: Value,
        env_ptr: Value,
    },
}

impl LoweredValue {
    fn from_typed_value(value: Value, ty: &MirValueType) -> Self {
        match ty {
            MirValueType::Float { .. } => Self::Float(value),
            MirValueType::Int { .. } | MirValueType::Bool => Self::Int(value),
            MirValueType::BytesSlice => Self::Int(value),
            MirValueType::Function | MirValueType::FunctionPointer => Self::Int(value),
            MirValueType::Unknown => Self::Int(value),
            MirValueType::Type => Self::Int(value),
            MirValueType::Closure => Self::Int(value),
        }
    }

    fn as_int(&self) -> Option<Value> {
        match self {
            Self::Int(value) => Some(*value),
            Self::ErrorableScalar {
                payload,
                payload_is_float,
                ..
            } => {
                if *payload_is_float {
                    None
                } else {
                    Some(*payload)
                }
            }
            Self::BytesSlice { ptr, .. } => Some(*ptr),
            Self::PointerSlice { base_addr, .. } => Some(*base_addr),
            Self::StructPointer { addr, status, .. } => status.or(Some(*addr)),
            Self::Float(_)
            | Self::FunctionSymbol(_)
            | Self::Struct(_)
            | Self::StructMemory { .. }
            | Self::EnumVariant { .. }
            | Self::EnumMemory { .. }
            | Self::FatPtr { .. } => None,
        }
    }

    fn as_float(&self) -> Option<Value> {
        match self {
            Self::Float(value) => Some(*value),
            Self::ErrorableScalar {
                payload,
                payload_is_float,
                ..
            } => {
                if *payload_is_float {
                    Some(*payload)
                } else {
                    None
                }
            }
            Self::Int(_)
            | Self::BytesSlice { .. }
            | Self::FunctionSymbol(_)
            | Self::Struct(_)
            | Self::StructMemory { .. }
            | Self::StructPointer { .. }
            | Self::PointerSlice { .. }
            | Self::EnumVariant { .. }
            | Self::EnumMemory { .. }
            | Self::FatPtr { .. } => None,
        }
    }

    fn as_value(&self) -> Option<Value> {
        match self {
            Self::Int(value) | Self::Float(value) => Some(*value),
            Self::ErrorableScalar { payload, .. } => Some(*payload),
            Self::BytesSlice { ptr, .. } => Some(*ptr),
            Self::PointerSlice { base_addr, .. } => Some(*base_addr),
            Self::StructPointer { addr, .. } => Some(*addr),
            Self::FunctionSymbol(_)
            | Self::Struct(_)
            | Self::StructMemory { .. }
            | Self::EnumVariant { .. }
            | Self::EnumMemory { .. }
            | Self::FatPtr { .. } => None,
        }
    }

    fn error_status(&self) -> Option<Value> {
        match self {
            Self::ErrorableScalar { status, .. } => Some(*status),
            Self::StructPointer { status, .. } => *status,
            _ => None,
        }
    }
}

fn rematerialize_struct_pointer_addr(
    builder: &mut FunctionBuilder,
    pointer_ty: Type,
    addr: Value,
    stack_slot: Option<StackSlot>,
    stack_offset: i32,
) -> Value {
    stack_slot
        .map(|slot| builder.ins().stack_addr(pointer_ty, slot, stack_offset))
        .unwrap_or(addr)
}

#[derive(Clone, Copy)]
struct CallSymbolTables<'a> {
    param_types_by_id: &'a BTreeMap<u32, Vec<Type>>,
    returns_bytes_slice_by_id: &'a BTreeMap<u32, bool>,
    returns_errorable_by_id: &'a BTreeMap<u32, bool>,
    returns_errorable_scalar_payload_ty_by_id: &'a BTreeMap<u32, MirValueType>,
    returns_aggregate_layout_by_id: &'a BTreeMap<u32, AggregateLayout>,
}

struct LowerValueContext<'a> {
    value_defs: &'a BTreeMap<MirValueId, MirValue>,
    value_types: &'a BTreeMap<MirValueId, MirValueType>,
    param_access: &'a [ParamAccess],
    current_module_id: usize,
    scalar: ScalarType,
    symbols_by_key: &'a BTreeMap<(usize, String), FuncId>,
    symbols_by_name: &'a BTreeMap<String, FuncId>,
    call_symbol_tables: CallSymbolTables<'a>,
    global_data_ids: &'a BTreeMap<String, DataId>,
}

#[derive(Clone)]
struct CallReturnProfile {
    returns_bytes_slice: bool,
    returns_aggregate: Option<AggregateLayout>,
    returns_errorable: bool,
    returns_errorable_scalar: bool,
    errorable_scalar_payload_ty: Option<MirValueType>,
}

#[derive(Clone)]
struct FunctionReturnProfile<'a> {
    signature_ret_ty: Type,
    pointer_ty: Type,
    scalar: ScalarType,
    returns_bytes_slice: bool,
    returns_aggregate_layout: Option<&'a AggregateLayout>,
    returns_errorable: bool,
    returns_errorable_scalar: bool,
    errorable_scalar_payload_ty: MirValueType,
}

#[derive(Clone, Copy)]
struct FunctionReturnOutPtrs {
    out_len_ptr: Option<Value>,
    out_aggregate_ptr: Option<Value>,
    out_errorable_scalar_ptr: Option<Value>,
}

struct CallOutArgs {
    ret_len_slot: Option<StackSlot>,
    aggregate_out_slot: Option<StackSlot>,
    errorable_scalar_out: Option<(StackSlot, Type)>,
}

struct IndexRefs<'a> {
    base: &'a MirValueId,
    index: &'a MirValueId,
}

struct SliceRangeRef<'a> {
    start: &'a Option<MirValueId>,
    end: &'a Option<MirValueId>,
    inclusive: bool,
}

struct StackSequenceLayoutRef<'a> {
    slot: StackSlot,
    ordered: &'a [(Type, i32)],
}

struct CallSiteRef<'a> {
    callee: &'a MirValueId,
    args: &'a [MirValueId],
}

struct EmitCallContext<'a> {
    value_ty: &'a MirValueType,
    callee: &'a MirValueId,
    lowered: &'a BTreeMap<MirValueId, LoweredValue>,
    scalar: ScalarType,
    param_types_by_id: &'a BTreeMap<u32, Vec<Type>>,
    pointer_ty: Type,
    direct_callee: Option<FuncId>,
    profile: &'a CallReturnProfile,
}

#[derive(Clone, Copy)]
struct LowerValueData<'a> {
    lowered: &'a BTreeMap<MirValueId, LoweredValue>,
    scalar: ScalarType,
    #[allow(dead_code)]
    symbols_by_name: &'a BTreeMap<String, FuncId>,
}

#[derive(Clone, Copy)]
struct BinaryOperandsRef<'a> {
    left: Option<&'a LoweredValue>,
    right: Option<&'a LoweredValue>,
}

#[derive(Clone, Copy)]
struct EnumVariantValueRef<'a> {
    variant: &'a str,
    tag: i64,
    tag_bits: u16,
    payload: &'a [MirValueId],
}

fn lower_value(
    value: &MirValue,
    value_ty: &MirValueType,
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    module: &mut ObjectModule,
    context: &LowerValueContext<'_>,
) -> LoweredValue {
    let scalar = context.scalar;
    let data = LowerValueData {
        lowered,
        scalar,
        symbols_by_name: context.symbols_by_name,
    };
    match value {
        MirValue::Literal(literal) => lower_literal(
            literal,
            value_ty,
            scalar,
            builder,
            module,
            context.symbols_by_name,
        ),
        MirValue::Ident(name) => lower_ident_value(
            value_ty,
            name,
            builder,
            scalar,
            context.current_module_id,
            context.symbols_by_key,
            context.symbols_by_name,
        ),
        MirValue::Param { index } => {
            lower_param_value(value_ty, *index, builder, context.param_access, scalar)
        }
        MirValue::Unary { op, operand } => {
            lower_unary_value(value_ty, op, operand, builder, module, data)
        }
        MirValue::Cast { value, target } => lower_cast_value(
            value_ty,
            value,
            target,
            builder,
            context.value_defs,
            module,
            data,
        ),
        MirValue::Binary { op, left, right } => {
            let left_operand_ty = context.value_types.get(left);
            lower_binary_value(
                value_ty,
                op,
                left,
                right,
                builder,
                module,
                data,
                left_operand_ty,
            )
        }
        MirValue::Assign { target, value, .. } => {
            lower_assign_value(value_ty, target, value, builder, lowered, module, context)
        }
        MirValue::LocalSet { value, .. } => lowered
            .get(value)
            .cloned()
            .unwrap_or_else(|| zero_lowered_for_type(builder, value_ty, scalar)),
        MirValue::Call { callee, args } => lower_call_value(
            value_ty,
            CallSiteRef { callee, args },
            builder,
            lowered,
            scalar,
            module,
            context.call_symbol_tables,
        ),
        MirValue::ErrorStatus { value } => {
            lower_error_status_value(value_ty, value, builder, lowered, scalar)
        }
        MirValue::ErrorPayload { value } => {
            lower_error_payload_value(value_ty, value, builder, lowered, scalar)
        }
        MirValue::DerefAccess { base } => {
            lower_deref_access_value(value_ty, base, builder, lowered, scalar, module)
        }
        MirValue::StructLiteral { fields } => {
            lower_struct_literal_value(value_ty, fields, builder, lowered, scalar, module)
        }
        MirValue::FieldAccess { base, field } => {
            lower_field_access_value(value_ty, base, field, builder, lowered, scalar, module)
        }
        MirValue::EnumVariant {
            variant,
            tag,
            tag_bits,
            payload,
            ..
        } => lower_enum_variant_value(
            value_ty,
            EnumVariantValueRef {
                variant,
                tag: *tag,
                tag_bits: *tag_bits,
                payload,
            },
            builder,
            module,
            data,
        ),
        MirValue::Index { base, index } => lower_index_value(
            value_ty,
            IndexRefs { base, index },
            builder,
            lowered,
            context.value_defs,
            scalar,
            module,
        ),
        MirValue::Slice {
            base,
            start,
            end,
            inclusive,
        } => lower_slice_value(
            value_ty,
            base,
            SliceRangeRef {
                start,
                end,
                inclusive: *inclusive,
            },
            builder,
            lowered,
            scalar,
            module,
        ),
        MirValue::TypeLiteral(name) => lower_type_literal_value(value_ty, name, builder, scalar),
        // Module use-import expressions (e.g. `io := use "std/io"`) occasionally
        // appear as dead MIR instructions when a module binding is referenced in
        // a function scope before callee resolution eliminates the reference.
        // These instructions are never used in the actual computation, so
        // emitting a zero is safe.  A future MIR cleanup pass should eliminate
        // these instructions before they reach codegen.
        MirValue::Use { .. } => zero_lowered_for_type(builder, value_ty, scalar),
        MirValue::EmptySlice { element_type } => {
            let pointer_ty = module.target_config().pointer_type();
            let zero = builder.ins().iconst(pointer_ty, 0);
            if element_type.trim() == "u8" || matches!(value_ty, MirValueType::BytesSlice) {
                LoweredValue::BytesSlice {
                    ptr: zero,
                    len: zero,
                }
            } else {
                let elem_ty = mir_type_to_clif(&backend_hint_mir_type(Some(element_type)), scalar);
                let stride = (elem_ty.bits() / 8).max(1) as i64;
                LoweredValue::PointerSlice {
                    base_addr: zero,
                    len: zero,
                    elem_ty,
                    stride,
                }
            }
        }
        // Unknown is used as a placeholder for void-returning function calls:
        // the MIR Eval instruction still has a dest, but it is never read by
        // subsequent instructions.  Emitting zero is safe because the dest is
        // dead.  Semantic analysis must ensure void-call results are never used
        // in an expression; if that invariant holds, this zero is never visible.
        MirValue::Unknown => zero_lowered_for_type(builder, value_ty, scalar),
        MirValue::ClosureCreate {
            fn_symbol,
            captures,
        } => {
            let pointer_ty = module.target_config().pointer_type();

            // Resolve function pointer
            let func_id = context
                .symbols_by_key
                .get(&(context.current_module_id, fn_symbol.clone()))
                .or_else(|| context.symbols_by_name.get(fn_symbol.as_str()))
                .copied();
            let fn_ptr = if let Some(fid) = func_id {
                let func_ref = module.declare_func_in_func(fid, builder.func);
                builder.ins().func_addr(pointer_ty, func_ref)
            } else {
                builder.ins().iconst(pointer_ty, 0)
            };

            // Build env_ptr
            let env_ptr = if captures.is_empty() {
                builder.ins().iconst(pointer_ty, 0)
            } else {
                let ptr_bytes = pointer_ty.bytes();
                let env_size = captures.len() as u32 * ptr_bytes;
                let align_log2 = if ptr_bytes == 8 { 3 } else { 2 };
                let env_slot = builder.func.create_sized_stack_slot(
                    cranelift_codegen::ir::StackSlotData::new(
                        cranelift_codegen::ir::StackSlotKind::ExplicitSlot,
                        env_size,
                        align_log2,
                    ),
                );
                for (i, cap) in captures.iter().enumerate() {
                    let cap_val = lowered.get(cap).and_then(|lv| lv.as_value());
                    if let Some(val) = cap_val {
                        let val_ty = builder.func.dfg.value_type(val);
                        let ptr_val = if val_ty == pointer_ty {
                            val
                        } else if val_ty.is_int() && val_ty.bits() < pointer_ty.bits() {
                            builder.ins().uextend(pointer_ty, val)
                        } else if val_ty.is_int() {
                            builder.ins().ireduce(pointer_ty, val)
                        } else {
                            val
                        };
                        builder.ins().stack_store(
                            ptr_val,
                            env_slot,
                            (i as i32) * (ptr_bytes as i32),
                        );
                    }
                }
                builder.ins().stack_addr(pointer_ty, env_slot, 0)
            };

            LoweredValue::FatPtr { fn_ptr, env_ptr }
        }
        MirValue::ClosureEnvField { env_ptr, index } => {
            let pointer_ty = module.target_config().pointer_type();
            let env_val = lowered.get(env_ptr).and_then(|lv| lv.as_value());
            if let Some(env) = env_val {
                let offset = (*index as i32) * (pointer_ty.bytes() as i32);
                let loaded = builder.ins().load(
                    pointer_ty,
                    cranelift_codegen::ir::MemFlags::new(),
                    env,
                    offset,
                );
                LoweredValue::Int(loaded)
            } else {
                LoweredValue::Int(builder.ins().iconst(pointer_ty, 0))
            }
        }
        MirValue::GlobalLoad { name } => {
            let pointer_ty = module.target_config().pointer_type();
            let Some(&data_id) = context.global_data_ids.get(name) else {
                return zero_lowered_for_type(builder, value_ty, scalar);
            };
            let gv = module.declare_data_in_func(data_id, builder.func);
            let addr = builder.ins().global_value(pointer_ty, gv);
            let clif_ty = mir_type_to_clif(value_ty, scalar);
            let loaded =
                builder
                    .ins()
                    .load(clif_ty, cranelift_codegen::ir::MemFlags::new(), addr, 0);
            LoweredValue::from_typed_value(loaded, value_ty)
        }
        MirValue::GlobalStore { name, value } => {
            let pointer_ty = module.target_config().pointer_type();
            let Some(&data_id) = context.global_data_ids.get(name) else {
                return zero_lowered_for_type(builder, value_ty, scalar);
            };
            let gv = module.declare_data_in_func(data_id, builder.func);
            let addr = builder.ins().global_value(pointer_ty, gv);
            let Some(val) = lowered.get(value).and_then(|lv| lv.as_value()) else {
                return zero_lowered_for_type(builder, value_ty, scalar);
            };
            builder
                .ins()
                .store(cranelift_codegen::ir::MemFlags::new(), val, addr, 0);
            LoweredValue::from_typed_value(val, value_ty)
        }
    }
}

fn lower_ident_value(
    value_ty: &MirValueType,
    name: &str,
    builder: &mut FunctionBuilder,
    scalar: ScalarType,
    current_module_id: usize,
    symbols_by_key: &BTreeMap<(usize, String), FuncId>,
    symbols_by_name: &BTreeMap<String, FuncId>,
) -> LoweredValue {
    if let Some(func_id) = symbols_by_key
        .get(&(current_module_id, name.to_string()))
        .copied()
        .or_else(|| symbols_by_name.get(name).copied())
    {
        LoweredValue::FunctionSymbol(func_id)
    } else {
        zero_lowered_for_type(builder, value_ty, scalar)
    }
}

fn lower_type_literal_value(
    value_ty: &MirValueType,
    name: &str,
    builder: &mut FunctionBuilder,
    scalar: ScalarType,
) -> LoweredValue {
    let hash = i64::from(variant_tag(name));
    let ty = mir_type_to_clif(value_ty, scalar);
    LoweredValue::Int(builder.ins().iconst(ty, hash))
}

fn lower_param_value(
    value_ty: &MirValueType,
    index: usize,
    builder: &mut FunctionBuilder,
    param_access: &[ParamAccess],
    scalar: ScalarType,
) -> LoweredValue {
    let Some(block) = builder.current_block() else {
        return zero_lowered_for_type(builder, value_ty, scalar);
    };
    let block_params = builder.block_params(block);
    match param_access.get(index).cloned() {
        Some(ParamAccess::BytesSlice {
            ptr_param,
            len_param,
        }) => {
            let Some(ptr) = block_params.get(ptr_param).copied() else {
                return zero_lowered_for_type(builder, value_ty, scalar);
            };
            let Some(len) = block_params.get(len_param).copied() else {
                return zero_lowered_for_type(builder, value_ty, scalar);
            };
            LoweredValue::BytesSlice { ptr, len }
        }
        Some(ParamAccess::Scalar { block_param }) => {
            let Some(value) = block_params.get(block_param).copied() else {
                return zero_lowered_for_type(builder, value_ty, scalar);
            };
            if matches!(value_ty, MirValueType::Unknown) {
                let ty = builder.func.dfg.value_type(value);
                if ty.is_float() {
                    LoweredValue::Float(value)
                } else {
                    LoweredValue::Int(value)
                }
            } else {
                LoweredValue::from_typed_value(value, value_ty)
            }
        }
        Some(ParamAccess::Aggregate {
            block_param,
            layout,
        }) => {
            let Some(addr) = block_params.get(block_param).copied() else {
                return zero_lowered_for_type(builder, value_ty, scalar);
            };
            LoweredValue::StructPointer {
                addr,
                stack_slot: None,
                stack_offset: 0,
                status: None,
                fields: layout.fields.clone(),
                aggregate_fields: layout.aggregate_fields.clone(),
                ordered: layout.ordered.clone(),
                scalar_leaves: layout.scalar_leaves.clone(),
                size: layout.size,
                align: layout.align,
            }
        }
        None => zero_lowered_for_type(builder, value_ty, scalar),
    }
}

fn lower_unary_value(
    value_ty: &MirValueType,
    op: &UnaryOp,
    operand: &MirValueId,
    builder: &mut FunctionBuilder,
    module: &mut ObjectModule,
    data: LowerValueData<'_>,
) -> LoweredValue {
    let scalar = data.scalar;
    let Some(operand_value) = data.lowered.get(operand).cloned() else {
        return zero_lowered_for_type(builder, value_ty, scalar);
    };
    match op {
        UnaryOp::Ref | UnaryOp::RefMut => match operand_value {
            LoweredValue::StructMemory { slot, .. } => {
                let addr = builder
                    .ins()
                    .stack_addr(module.target_config().pointer_type(), slot, 0);
                LoweredValue::Int(addr)
            }
            LoweredValue::StructPointer {
                addr,
                stack_slot,
                stack_offset,
                ..
            } => {
                let current = rematerialize_struct_pointer_addr(
                    builder,
                    module.target_config().pointer_type(),
                    addr,
                    stack_slot,
                    stack_offset,
                );
                LoweredValue::Int(current)
            }
            LoweredValue::Struct(fields) => {
                let lowered_pairs = fields.into_iter().collect::<Vec<_>>();
                match materialize_struct_memory(builder, module, &lowered_pairs) {
                    Some(LoweredValue::StructMemory { slot, .. }) => {
                        let addr = builder.ins().stack_addr(
                            module.target_config().pointer_type(),
                            slot,
                            0,
                        );
                        LoweredValue::Int(addr)
                    }
                    Some(other) => other,
                    None => zero_lowered_for_type(builder, value_ty, scalar),
                }
            }
            LoweredValue::Int(value) | LoweredValue::Float(value) => {
                let addr = spill_scalar_to_stack_and_get_addr(builder, module, value);
                LoweredValue::Int(addr)
            }
            _ => zero_lowered_for_type(builder, value_ty, scalar),
        },
        _ => {
            let Some(operand) = operand_value.as_value() else {
                return zero_lowered_for_type(builder, value_ty, scalar);
            };
            match (op, value_ty) {
                (UnaryOp::Neg, MirValueType::Float { .. }) => {
                    LoweredValue::Float(builder.ins().fneg(operand))
                }
                (UnaryOp::Neg, _) => LoweredValue::Int(builder.ins().ineg(operand)),
                (UnaryOp::Not, _) => {
                    let one = builder.ins().iconst(bool_storage_type(scalar), 1);
                    let casted = cast_scalar(builder, operand, bool_storage_type(scalar), scalar);
                    LoweredValue::Int(builder.ins().bxor(casted, one))
                }
                (UnaryOp::BitNot, _) => {
                    let casted = cast_scalar(builder, operand, bool_storage_type(scalar), scalar);
                    LoweredValue::Int(builder.ins().bnot(casted))
                }
                (UnaryOp::Ref | UnaryOp::RefMut, MirValueType::Float { .. }) => {
                    LoweredValue::Float(operand)
                }
                (UnaryOp::Ref | UnaryOp::RefMut, _) => LoweredValue::Int(operand),
            }
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn lower_binary_value(
    value_ty: &MirValueType,
    op: &BinaryOp,
    left: &MirValueId,
    right: &MirValueId,
    builder: &mut FunctionBuilder,
    module: &mut ObjectModule,
    data: LowerValueData<'_>,
    left_operand_ty: Option<&MirValueType>,
) -> LoweredValue {
    let scalar = data.scalar;
    let left_val = data.lowered.get(left);
    let right_val = data.lowered.get(right);
    let float_operand_ty = left_val
        .and_then(LoweredValue::as_float)
        .map(|value| builder.func.dfg.value_type(value))
        .or_else(|| {
            right_val
                .and_then(LoweredValue::as_float)
                .map(|value| builder.func.dfg.value_type(value))
        });

    let float_op = matches!(
        op,
        BinaryOp::Add
            | BinaryOp::Sub
            | BinaryOp::Mul
            | BinaryOp::Div
            | BinaryOp::Eq
            | BinaryOp::Ne
            | BinaryOp::Lt
            | BinaryOp::Le
            | BinaryOp::Gt
            | BinaryOp::Ge
    );

    if matches!(value_ty, MirValueType::Float { .. }) || (float_op && float_operand_ty.is_some()) {
        return lower_float_binary_value(
            value_ty,
            op,
            builder,
            BinaryOperandsRef {
                left: left_val,
                right: right_val,
            },
            float_operand_ty,
            module,
            data,
        );
    }

    lower_int_binary_value(
        value_ty,
        op,
        builder,
        scalar,
        left_val,
        right_val,
        left_operand_ty,
    )
}

fn lower_float_binary_value(
    value_ty: &MirValueType,
    op: &BinaryOp,
    builder: &mut FunctionBuilder,
    operands: BinaryOperandsRef<'_>,
    float_ty_hint: Option<Type>,
    _module: &mut ObjectModule,
    data: LowerValueData<'_>,
) -> LoweredValue {
    let scalar = data.scalar;
    let left_val = operands.left;
    let right_val = operands.right;
    let float_ty = float_ty_hint.unwrap_or_else(|| mir_type_to_clif(value_ty, scalar));
    let Some(left) = left_val.and_then(LoweredValue::as_float).or_else(|| {
        left_val
            .and_then(LoweredValue::as_int)
            .map(|v| builder.ins().fcvt_from_sint(float_ty, v))
    }) else {
        return zero_lowered_for_type(builder, value_ty, scalar);
    };
    let Some(right) = right_val.and_then(LoweredValue::as_float).or_else(|| {
        right_val
            .and_then(LoweredValue::as_int)
            .map(|v| builder.ins().fcvt_from_sint(float_ty, v))
    }) else {
        return zero_lowered_for_type(builder, value_ty, scalar);
    };

    match op {
        BinaryOp::Add => LoweredValue::Float(builder.ins().fadd(left, right)),
        BinaryOp::Sub => LoweredValue::Float(builder.ins().fsub(left, right)),
        BinaryOp::Mul => LoweredValue::Float(builder.ins().fmul(left, right)),
        BinaryOp::Div => LoweredValue::Float(builder.ins().fdiv(left, right)),
        BinaryOp::Eq => lower_float_compare_to_bool(
            builder,
            scalar,
            cranelift_codegen::ir::condcodes::FloatCC::Equal,
            left,
            right,
        ),
        BinaryOp::Ne => lower_float_compare_to_bool(
            builder,
            scalar,
            cranelift_codegen::ir::condcodes::FloatCC::NotEqual,
            left,
            right,
        ),
        BinaryOp::Lt => lower_float_compare_to_bool(
            builder,
            scalar,
            cranelift_codegen::ir::condcodes::FloatCC::LessThan,
            left,
            right,
        ),
        BinaryOp::Le => lower_float_compare_to_bool(
            builder,
            scalar,
            cranelift_codegen::ir::condcodes::FloatCC::LessThanOrEqual,
            left,
            right,
        ),
        BinaryOp::Gt => lower_float_compare_to_bool(
            builder,
            scalar,
            cranelift_codegen::ir::condcodes::FloatCC::GreaterThan,
            left,
            right,
        ),
        BinaryOp::Ge => lower_float_compare_to_bool(
            builder,
            scalar,
            cranelift_codegen::ir::condcodes::FloatCC::GreaterThanOrEqual,
            left,
            right,
        ),
        _ => LoweredValue::Float(zero_for_type(builder, float_ty)),
    }
}

fn emit_declared_func_call(
    builder: &mut FunctionBuilder,
    module: &mut ObjectModule,
    func_id: FuncId,
    args: &[Value],
    fallback_ty: Type,
) -> Value {
    let func_ref = module.declare_func_in_func(func_id, builder.func);
    let inst = builder.ins().call(func_ref, args);
    builder
        .inst_results(inst)
        .first()
        .copied()
        .unwrap_or_else(|| zero_for_type(builder, fallback_ty))
}

#[allow(dead_code)]
fn saturate_i64_to_int_width(
    builder: &mut FunctionBuilder,
    raw: Value,
    bits: u16,
    signed: bool,
) -> Value {
    if bits == 0 || bits >= 64 {
        return raw;
    }

    if signed {
        let max = ((1_i128 << (bits - 1)) - 1) as i64;
        let min = (-(1_i128 << (bits - 1))) as i64;
        let low = builder.ins().icmp_imm(IntCC::SignedLessThan, raw, min);
        let high = builder.ins().icmp_imm(IntCC::SignedGreaterThan, raw, max);
        let min_v = builder.ins().iconst(I64, min);
        let max_v = builder.ins().iconst(I64, max);
        let clamped_low = builder.ins().select(low, min_v, raw);
        builder.ins().select(high, max_v, clamped_low)
    } else {
        let max = ((1_u128 << u32::from(bits)) - 1) as i64;
        let high = builder.ins().icmp_imm(IntCC::UnsignedGreaterThan, raw, max);
        let max_v = builder.ins().iconst(I64, max);
        builder.ins().select(high, max_v, raw)
    }
}

fn lower_int_binary_value(
    value_ty: &MirValueType,
    op: &BinaryOp,
    builder: &mut FunctionBuilder,
    scalar: ScalarType,
    left_val: Option<&LoweredValue>,
    right_val: Option<&LoweredValue>,
    left_operand_ty: Option<&MirValueType>,
) -> LoweredValue {
    // For comparison operators the result type is always u1 (bool, unsigned), but the
    // comparison direction (signed vs unsigned) must come from the OPERAND types, not
    // the result type.  Arithmetic operators (add, sub, …) may use the result type.
    let is_comparison = matches!(
        op,
        BinaryOp::Lt | BinaryOp::Le | BinaryOp::Gt | BinaryOp::Ge
    );
    let signed = if is_comparison {
        match left_operand_ty {
            Some(MirValueType::Int { signed, .. }) => *signed,
            _ => match value_ty {
                MirValueType::Int { signed, .. } => *signed,
                _ => matches!(scalar, ScalarType::Int { signed: true, .. }),
            },
        }
    } else {
        match value_ty {
            MirValueType::Int { signed, .. } => *signed,
            _ => matches!(scalar, ScalarType::Int { signed: true, .. }),
        }
    };
    let Some(left_raw) = left_val.and_then(LoweredValue::as_int) else {
        return zero_lowered_for_type(builder, value_ty, scalar);
    };
    let Some(right_raw) = right_val.and_then(LoweredValue::as_int) else {
        return zero_lowered_for_type(builder, value_ty, scalar);
    };
    let int_ty = if matches!(value_ty, MirValueType::Unknown) {
        let left_ty = builder.func.dfg.value_type(left_raw);
        let right_ty = builder.func.dfg.value_type(right_raw);
        if left_ty.is_int() && right_ty.is_int() {
            if left_ty.bits() >= right_ty.bits() {
                left_ty
            } else {
                right_ty
            }
        } else {
            mir_type_to_clif(value_ty, scalar)
        }
    } else {
        mir_type_to_clif(value_ty, scalar)
    };
    let left = cast_scalar(builder, left_raw, int_ty, scalar);
    let right = cast_scalar(builder, right_raw, int_ty, scalar);

    let out = match op {
        BinaryOp::Add => builder.ins().iadd(left, right),
        BinaryOp::Sub => builder.ins().isub(left, right),
        BinaryOp::Mul => builder.ins().imul(left, right),
        BinaryOp::Div => {
            if signed {
                builder.ins().sdiv(left, right)
            } else {
                builder.ins().udiv(left, right)
            }
        }
        BinaryOp::Mod => {
            if signed {
                builder.ins().srem(left, right)
            } else {
                builder.ins().urem(left, right)
            }
        }
        BinaryOp::Eq => {
            return lower_int_compare_to_bool(builder, scalar, IntCC::Equal, left, right);
        }
        BinaryOp::Ne => {
            return lower_int_compare_to_bool(builder, scalar, IntCC::NotEqual, left, right);
        }
        BinaryOp::Lt => {
            return lower_int_compare_to_bool(
                builder,
                scalar,
                if signed {
                    IntCC::SignedLessThan
                } else {
                    IntCC::UnsignedLessThan
                },
                left,
                right,
            );
        }
        BinaryOp::Le => {
            return lower_int_compare_to_bool(
                builder,
                scalar,
                if signed {
                    IntCC::SignedLessThanOrEqual
                } else {
                    IntCC::UnsignedLessThanOrEqual
                },
                left,
                right,
            );
        }
        BinaryOp::Gt => {
            return lower_int_compare_to_bool(
                builder,
                scalar,
                if signed {
                    IntCC::SignedGreaterThan
                } else {
                    IntCC::UnsignedGreaterThan
                },
                left,
                right,
            );
        }
        BinaryOp::Ge => {
            return lower_int_compare_to_bool(
                builder,
                scalar,
                if signed {
                    IntCC::SignedGreaterThanOrEqual
                } else {
                    IntCC::UnsignedGreaterThanOrEqual
                },
                left,
                right,
            );
        }
        BinaryOp::LogicalAnd => {
            let l_cmp = builder.ins().icmp_imm(IntCC::NotEqual, left, 0);
            let l = bool_to_int(builder, int_ty, l_cmp);
            let r_cmp = builder.ins().icmp_imm(IntCC::NotEqual, right, 0);
            let r = bool_to_int(builder, int_ty, r_cmp);
            let both = builder.ins().band(l, r);
            let out_cmp = builder.ins().icmp_imm(IntCC::NotEqual, both, 0);
            return LoweredValue::Int(bool_to_int(builder, int_ty, out_cmp));
        }
        BinaryOp::LogicalOr => {
            let l_cmp = builder.ins().icmp_imm(IntCC::NotEqual, left, 0);
            let l = bool_to_int(builder, int_ty, l_cmp);
            let r_cmp = builder.ins().icmp_imm(IntCC::NotEqual, right, 0);
            let r = bool_to_int(builder, int_ty, r_cmp);
            let any = builder.ins().bor(l, r);
            let out_cmp = builder.ins().icmp_imm(IntCC::NotEqual, any, 0);
            return LoweredValue::Int(bool_to_int(builder, int_ty, out_cmp));
        }
        BinaryOp::BitAnd => builder.ins().band(left, right),
        BinaryOp::BitOr => builder.ins().bor(left, right),
        BinaryOp::BitXor => builder.ins().bxor(left, right),
        BinaryOp::Shl => builder.ins().ishl(left, right),
        BinaryOp::Shr => {
            if signed {
                builder.ins().sshr(left, right)
            } else {
                builder.ins().ushr(left, right)
            }
        }
        _ => zero_for_type(builder, int_ty),
    };
    LoweredValue::Int(out)
}

fn lower_float_compare_to_bool(
    builder: &mut FunctionBuilder,
    scalar: ScalarType,
    cc: cranelift_codegen::ir::condcodes::FloatCC,
    left: Value,
    right: Value,
) -> LoweredValue {
    let cmp = builder.ins().fcmp(cc, left, right);
    LoweredValue::Int(bool_to_int(builder, bool_storage_type(scalar), cmp))
}

fn lower_int_compare_to_bool(
    builder: &mut FunctionBuilder,
    scalar: ScalarType,
    cc: IntCC,
    left: Value,
    right: Value,
) -> LoweredValue {
    let cmp = builder.ins().icmp(cc, left, right);
    LoweredValue::Int(bool_to_int(builder, bool_storage_type(scalar), cmp))
}

fn lower_cast_value(
    value_ty: &MirValueType,
    value: &MirValueId,
    target: &MirValueType,
    builder: &mut FunctionBuilder,
    value_defs: &BTreeMap<MirValueId, MirValue>,
    _module: &mut ObjectModule,
    data: LowerValueData<'_>,
) -> LoweredValue {
    let scalar = data.scalar;
    let Some(source) = data.lowered.get(value).cloned() else {
        return zero_lowered_for_type(builder, value_ty, scalar);
    };
    if matches!(target, MirValueType::Unknown) {
        return source;
    }
    if matches!(target, MirValueType::BytesSlice) {
        return match source {
            LoweredValue::BytesSlice { .. } => source,
            LoweredValue::StructMemory { slot, ordered, .. } => {
                let pointer_ty = _module.target_config().pointer_type();
                if let Some((elem_ty, base_offset, _stride)) = homogeneous_sequence_layout(&ordered)
                {
                    if elem_ty.is_int() {
                        let ptr = builder.ins().stack_addr(pointer_ty, slot, base_offset);
                        let len = builder
                            .ins()
                            .iconst(pointer_ty, i64::try_from(ordered.len()).unwrap_or(i64::MAX));
                        LoweredValue::BytesSlice { ptr, len }
                    } else {
                        zero_lowered_for_type(builder, target, scalar)
                    }
                } else {
                    zero_lowered_for_type(builder, target, scalar)
                }
            }
            _ => zero_lowered_for_type(builder, target, scalar),
        };
    }
    if let MirValueType::Int { bits, .. } = target {
        if int_carrier_type_for_bits(*bits) == I128 {
            if let Some(MirValue::Literal(HirLiteral::Integer(text))) = value_defs.get(value) {
                let parsed = parse_int_literal_wide_bits(text).unwrap_or(0);
                let lo = builder.ins().iconst(I64, parsed as u64 as i64);
                let hi = builder.ins().iconst(I64, (parsed >> 64) as u64 as i64);
                return LoweredValue::Int(builder.ins().iconcat(lo, hi));
            }
        }
    }
    let target_ty = mir_type_to_clif(target, scalar);
    if let LoweredValue::FunctionSymbol(func_id) = source {
        let func_ref = _module.declare_func_in_func(func_id, builder.func);
        let pointer_ty = _module.target_config().pointer_type();
        let addr = builder.ins().func_addr(pointer_ty, func_ref);
        let casted = cast_scalar(builder, addr, target_ty, scalar);
        return LoweredValue::from_typed_value(casted, target);
    }
    if matches!(target, MirValueType::Float { .. }) {
        if let Some(float_value) = source.as_float() {
            return LoweredValue::Float(cast_scalar(builder, float_value, target_ty, scalar));
        }
        if let Some(int_value) = source.as_int() {
            return LoweredValue::Float(builder.ins().fcvt_from_sint(target_ty, int_value));
        }
        return zero_lowered_for_type(builder, target, scalar);
    }
    let Some(raw) = source.as_value().or_else(|| source.as_int()) else {
        return zero_lowered_for_type(builder, target, scalar);
    };
    let casted = cast_scalar(builder, raw, target_ty, scalar);
    LoweredValue::from_typed_value(casted, target)
}

fn lower_assign_value(
    value_ty: &MirValueType,
    target: &MirValueId,
    value: &MirValueId,
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    module: &mut ObjectModule,
    context: &LowerValueContext<'_>,
) -> LoweredValue {
    let scalar = context.scalar;
    let stored = lowered
        .get(value)
        .cloned()
        .unwrap_or_else(|| zero_lowered_for_type(builder, value_ty, scalar));
    let Some((addr, store_ty)) =
        resolve_assignment_target_address(target, builder, lowered, module, context)
    else {
        return stored;
    };
    let raw = match &stored {
        LoweredValue::FunctionSymbol(func_id) => {
            let func_ref = module.declare_func_in_func(*func_id, builder.func);
            builder
                .ins()
                .func_addr(module.target_config().pointer_type(), func_ref)
        }
        _ => match stored.as_value().or_else(|| stored.as_int()) {
            Some(raw) => raw,
            None => return stored,
        },
    };
    let casted = cast_scalar(builder, raw, store_ty, scalar);
    builder
        .ins()
        .store(cranelift_codegen::ir::MemFlags::new(), casted, addr, 0);
    LoweredValue::from_typed_value(casted, value_ty)
}

fn resolve_assignment_target_address(
    target: &MirValueId,
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    module: &mut ObjectModule,
    context: &LowerValueContext<'_>,
) -> Option<(Value, Type)> {
    let pointer_ty = module.target_config().pointer_type();
    match context.value_defs.get(target)? {
        MirValue::DerefAccess { base } => {
            let addr = lowered
                .get(base)?
                .as_value()
                .or_else(|| lowered.get(base)?.as_int())?;
            let store_ty = mir_type_to_clif(context.value_types.get(target)?, context.scalar);
            Some((
                cast_scalar(builder, addr, pointer_ty, context.scalar),
                store_ty,
            ))
        }
        MirValue::FieldAccess { base, field } => match lowered.get(base)? {
            LoweredValue::StructMemory {
                slot,
                fields,
                aggregate_fields,
                ..
            } => {
                if let Some((ty, offset)) = fields.get(field).copied() {
                    let addr = builder.ins().stack_addr(pointer_ty, *slot, offset);
                    Some((addr, ty))
                } else if let Some((offset, layout)) = aggregate_fields.get(field) {
                    let addr = builder.ins().stack_addr(pointer_ty, *slot, *offset);
                    Some((
                        addr,
                        layout
                            .ordered
                            .first()
                            .map(|(ty, _)| *ty)
                            .unwrap_or(pointer_ty),
                    ))
                } else {
                    None
                }
            }
            LoweredValue::StructPointer {
                addr,
                stack_slot,
                stack_offset,
                fields,
                aggregate_fields,
                ..
            } => {
                let base_addr = rematerialize_struct_pointer_addr(
                    builder,
                    pointer_ty,
                    *addr,
                    *stack_slot,
                    *stack_offset,
                );
                if let Some((ty, offset)) = fields.get(field).copied() {
                    Some((builder.ins().iadd_imm(base_addr, i64::from(offset)), ty))
                } else if let Some((offset, layout)) = aggregate_fields.get(field) {
                    Some((
                        builder.ins().iadd_imm(base_addr, i64::from(*offset)),
                        layout
                            .ordered
                            .first()
                            .map(|(ty, _)| *ty)
                            .unwrap_or(pointer_ty),
                    ))
                } else {
                    None
                }
            }
            _ => None,
        },
        _ => None,
    }
}

fn lower_deref_access_value(
    value_ty: &MirValueType,
    base: &MirValueId,
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    scalar: ScalarType,
    module: &mut ObjectModule,
) -> LoweredValue {
    match lowered.get(base).cloned() {
        Some(LoweredValue::Int(addr)) => {
            if value_is_definitely_zero(builder, addr, 0) {
                return zero_lowered_for_type(builder, value_ty, scalar);
            }
            let load_ty = mir_type_to_clif(value_ty, scalar);
            let ptr = cast_scalar(builder, addr, module.target_config().pointer_type(), scalar);
            let loaded =
                builder
                    .ins()
                    .load(load_ty, cranelift_codegen::ir::MemFlags::new(), ptr, 0);
            LoweredValue::from_typed_value(loaded, value_ty)
        }
        Some(other) => other,
        None => zero_lowered_for_type(builder, value_ty, scalar),
    }
}

fn lower_struct_literal_value(
    value_ty: &MirValueType,
    fields: &[(String, MirValueId)],
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    scalar: ScalarType,
    module: &mut ObjectModule,
) -> LoweredValue {
    let mut lowered_pairs = Vec::with_capacity(fields.len());
    let mut lowered_fields = BTreeMap::new();
    for (name, value_id) in fields {
        let lowered_value = lowered
            .get(value_id)
            .cloned()
            .unwrap_or_else(|| zero_lowered_for_type(builder, value_ty, scalar));
        lowered_pairs.push((name.clone(), lowered_value.clone()));
        lowered_fields.insert(name.clone(), lowered_value);
    }
    materialize_struct_memory(builder, module, &lowered_pairs)
        .unwrap_or(LoweredValue::Struct(lowered_fields))
}

fn lower_enum_variant_value(
    value_ty: &MirValueType,
    enum_value: EnumVariantValueRef<'_>,
    builder: &mut FunctionBuilder,
    module: &mut ObjectModule,
    data: LowerValueData<'_>,
) -> LoweredValue {
    let scalar = data.scalar;
    if enum_value.payload.is_empty() {
        let mut ty = int_carrier_type_for_bits(enum_value.tag_bits);
        if !matches!(value_ty, MirValueType::Unknown) {
            ty = mir_type_to_clif(value_ty, scalar);
        }
        return LoweredValue::Int(builder.ins().iconst(ty, enum_value.tag));
    }
    let mut lowered_payload = Vec::with_capacity(enum_value.payload.len());
    for value_id in enum_value.payload {
        lowered_payload.push(
            data.lowered
                .get(value_id)
                .cloned()
                .unwrap_or_else(|| zero_lowered_for_type(builder, value_ty, scalar)),
        );
    }
    let lowered_enum = LoweredValue::EnumVariant {
        variant: enum_value.variant.to_string(),
        payload: lowered_payload.clone(),
    };
    materialize_enum_memory(
        builder,
        module,
        enum_value.tag,
        enum_value.tag_bits,
        &lowered_payload,
    )
    .unwrap_or(lowered_enum)
}

fn lower_field_access_value(
    value_ty: &MirValueType,
    base: &MirValueId,
    field: &str,
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    scalar: ScalarType,
    module: &mut ObjectModule,
) -> LoweredValue {
    match lowered.get(base) {
        Some(LoweredValue::Struct(fields)) => fields
            .get(field)
            .cloned()
            .unwrap_or_else(|| zero_lowered_for_type(builder, value_ty, scalar)),
        Some(LoweredValue::StructMemory {
            slot,
            fields,
            aggregate_fields,
            ..
        }) => {
            if let Some((ty, offset)) = fields.get(field).copied() {
                let loaded = builder.ins().stack_load(ty, *slot, offset);
                if ty.is_float() {
                    LoweredValue::Float(loaded)
                } else {
                    LoweredValue::Int(loaded)
                }
            } else if let Some((offset, layout)) = aggregate_fields.get(field) {
                let addr =
                    builder
                        .ins()
                        .stack_addr(module.target_config().pointer_type(), *slot, *offset);
                LoweredValue::StructPointer {
                    addr,
                    stack_slot: Some(*slot),
                    stack_offset: *offset,
                    status: None,
                    fields: layout.fields.clone(),
                    aggregate_fields: layout.aggregate_fields.clone(),
                    ordered: layout.ordered.clone(),
                    scalar_leaves: layout.scalar_leaves.clone(),
                    size: layout.size,
                    align: layout.align,
                }
            } else {
                zero_lowered_for_type(builder, value_ty, scalar)
            }
        }
        Some(LoweredValue::StructPointer {
            addr,
            stack_slot,
            stack_offset,
            fields,
            aggregate_fields,
            ..
        }) => {
            let pointer_ty = module.target_config().pointer_type();
            let base_addr = rematerialize_struct_pointer_addr(
                builder,
                pointer_ty,
                *addr,
                *stack_slot,
                *stack_offset,
            );
            if let Some((ty, offset)) = fields.get(field).copied() {
                let loaded = builder.ins().load(
                    ty,
                    cranelift_codegen::ir::MemFlags::new(),
                    base_addr,
                    offset,
                );
                if ty.is_float() {
                    LoweredValue::Float(loaded)
                } else {
                    LoweredValue::Int(loaded)
                }
            } else if let Some((offset, layout)) = aggregate_fields.get(field) {
                let nested_addr = builder.ins().iadd_imm(base_addr, i64::from(*offset));
                let (nested_stack_slot, nested_stack_offset) = if let Some(slot) = *stack_slot {
                    if let Some(offset_sum) = stack_offset.checked_add(*offset) {
                        (Some(slot), offset_sum)
                    } else {
                        (None, 0)
                    }
                } else {
                    (None, 0)
                };
                LoweredValue::StructPointer {
                    addr: nested_addr,
                    stack_slot: nested_stack_slot,
                    stack_offset: nested_stack_offset,
                    status: None,
                    fields: layout.fields.clone(),
                    aggregate_fields: layout.aggregate_fields.clone(),
                    ordered: layout.ordered.clone(),
                    scalar_leaves: layout.scalar_leaves.clone(),
                    size: layout.size,
                    align: layout.align,
                }
            } else {
                zero_lowered_for_type(builder, value_ty, scalar)
            }
        }
        Some(LoweredValue::BytesSlice { ptr, len }) => {
            if field == "len" {
                return LoweredValue::Int(*len);
            }
            if field == "ptr" {
                return LoweredValue::Int(*ptr);
            }
            zero_lowered_for_type(builder, value_ty, scalar)
        }
        Some(LoweredValue::PointerSlice { base_addr, len, .. }) => {
            if field == "len" {
                return LoweredValue::Int(*len);
            }
            if field == "ptr" {
                return LoweredValue::Int(*base_addr);
            }
            zero_lowered_for_type(builder, value_ty, scalar)
        }
        _ => zero_lowered_for_type(builder, value_ty, scalar),
    }
}

fn add_scaled_index_to_base(
    builder: &mut FunctionBuilder,
    scalar: ScalarType,
    pointer_ty: Type,
    base_addr: Value,
    index_value: Value,
    stride: i64,
) -> Value {
    let idx = cast_scalar(builder, index_value, pointer_ty, scalar);
    let scaled = if stride == 1 {
        idx
    } else {
        builder.ins().imul_imm(idx, stride)
    };
    builder.ins().iadd(base_addr, scaled)
}

fn lower_indexed_load_from_base_addr(
    builder: &mut FunctionBuilder,
    scalar: ScalarType,
    pointer_ty: Type,
    base_addr: Value,
    index_value: Value,
    elem_ty: Type,
    stride: i64,
) -> LoweredValue {
    let addr =
        add_scaled_index_to_base(builder, scalar, pointer_ty, base_addr, index_value, stride);
    let loaded = builder
        .ins()
        .load(elem_ty, cranelift_codegen::ir::MemFlags::new(), addr, 0);
    if elem_ty.is_float() {
        LoweredValue::Float(loaded)
    } else {
        LoweredValue::Int(loaded)
    }
}

fn lower_homogeneous_index_from_stack_slot(
    value_ty: &MirValueType,
    builder: &mut FunctionBuilder,
    scalar: ScalarType,
    pointer_ty: Type,
    slot: StackSlot,
    ordered: &[(Type, i32)],
    index_value: Value,
) -> LoweredValue {
    let Some((elem_ty, base_offset, stride)) = homogeneous_sequence_layout(ordered) else {
        return zero_lowered_for_type(builder, value_ty, scalar);
    };
    let base_addr = builder.ins().stack_addr(pointer_ty, slot, base_offset);
    lower_indexed_load_from_base_addr(
        builder,
        scalar,
        pointer_ty,
        base_addr,
        index_value,
        elem_ty,
        stride,
    )
}

fn lower_homogeneous_slice_from_stack_slot(
    value_ty: &MirValueType,
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    scalar: ScalarType,
    pointer_ty: Type,
    sequence: StackSequenceLayoutRef<'_>,
    start: &Option<MirValueId>,
) -> LoweredValue {
    let Some((elem_ty, base_offset, stride)) = homogeneous_sequence_layout(sequence.ordered) else {
        return zero_lowered_for_type(builder, value_ty, scalar);
    };
    let mut base_addr = builder
        .ins()
        .stack_addr(pointer_ty, sequence.slot, base_offset);
    let start_index = start
        .and_then(|id| lowered.get(&id).and_then(LoweredValue::as_int))
        .unwrap_or_else(|| zero_for_type(builder, pointer_ty));
    if !value_is_definitely_zero(builder, start_index, 0) {
        base_addr =
            add_scaled_index_to_base(builder, scalar, pointer_ty, base_addr, start_index, stride);
    }
    if matches!(value_ty, MirValueType::BytesSlice) || elem_ty.is_int() {
        let total_len = builder.ins().iconst(
            pointer_ty,
            i64::try_from(sequence.ordered.len()).unwrap_or(i64::MAX),
        );
        let len = builder.ins().isub(total_len, start_index);
        return LoweredValue::BytesSlice {
            ptr: base_addr,
            len,
        };
    }
    LoweredValue::PointerSlice {
        base_addr,
        len: builder.ins().iconst(
            pointer_ty,
            i64::try_from(sequence.ordered.len()).unwrap_or(i64::MAX),
        ),
        elem_ty,
        stride,
    }
}

fn lower_index_value(
    value_ty: &MirValueType,
    refs: IndexRefs<'_>,
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    value_defs: &BTreeMap<MirValueId, MirValue>,
    scalar: ScalarType,
    module: &mut ObjectModule,
) -> LoweredValue {
    let pointer_ty = module.target_config().pointer_type();
    match lowered.get(refs.base) {
        Some(LoweredValue::EnumMemory { slot, ordered }) => {
            let Some(index_value) = lowered.get(refs.index).and_then(LoweredValue::as_int) else {
                return zero_lowered_for_type(builder, value_ty, scalar);
            };
            lower_homogeneous_index_from_stack_slot(
                value_ty,
                builder,
                scalar,
                pointer_ty,
                *slot,
                ordered,
                index_value,
            )
        }
        Some(LoweredValue::EnumVariant { payload, .. }) => payload
            .first()
            .cloned()
            .unwrap_or_else(|| zero_lowered_for_type(builder, value_ty, scalar)),
        Some(LoweredValue::Struct(fields)) => fields
            .values()
            .next()
            .cloned()
            .unwrap_or_else(|| zero_lowered_for_type(builder, value_ty, scalar)),
        Some(LoweredValue::StructMemory { slot, ordered, .. }) => {
            let Some(index_value) = lowered.get(refs.index).and_then(LoweredValue::as_int) else {
                return zero_lowered_for_type(builder, value_ty, scalar);
            };
            lower_homogeneous_index_from_stack_slot(
                value_ty,
                builder,
                scalar,
                pointer_ty,
                *slot,
                ordered,
                index_value,
            )
        }
        Some(LoweredValue::PointerSlice {
            base_addr,
            len: _,
            elem_ty,
            stride,
        }) => {
            if value_is_definitely_zero(builder, *base_addr, 0) {
                return zero_lowered_for_type(builder, value_ty, scalar);
            }
            let Some(index_value) = lowered.get(refs.index).and_then(LoweredValue::as_int) else {
                return zero_lowered_for_type(builder, value_ty, scalar);
            };
            lower_indexed_load_from_base_addr(
                builder,
                scalar,
                pointer_ty,
                *base_addr,
                index_value,
                *elem_ty,
                *stride,
            )
        }
        Some(LoweredValue::BytesSlice { ptr, .. }) => {
            if value_is_definitely_zero(builder, *ptr, 0) {
                return zero_lowered_for_type(builder, value_ty, scalar);
            }
            let Some(index_value) = lowered.get(refs.index).and_then(LoweredValue::as_int) else {
                return zero_lowered_for_type(builder, value_ty, scalar);
            };
            let elem_ty = mir_type_to_clif(value_ty, scalar);
            let stride = (elem_ty.bits() / 8).max(1) as i64;
            let base_addr = cast_scalar(builder, *ptr, pointer_ty, scalar);
            lower_indexed_load_from_base_addr(
                builder,
                scalar,
                pointer_ty,
                base_addr,
                index_value,
                elem_ty,
                stride,
            )
        }
        Some(LoweredValue::Int(base_addr)) => {
            if mir_value_resolves_to_unknown(*refs.base, value_defs, 0) {
                return zero_lowered_for_type(builder, value_ty, scalar);
            }
            if value_is_definitely_zero(builder, *base_addr, 0) {
                return zero_lowered_for_type(builder, value_ty, scalar);
            }
            let Some(index_value) = lowered.get(refs.index).and_then(LoweredValue::as_int) else {
                return zero_lowered_for_type(builder, value_ty, scalar);
            };
            let elem_ty = mir_type_to_clif(value_ty, scalar);
            let stride = (elem_ty.bits() / 8).max(1) as i64;
            let typed_base_addr = cast_scalar(builder, *base_addr, pointer_ty, scalar);
            lower_indexed_load_from_base_addr(
                builder,
                scalar,
                pointer_ty,
                typed_base_addr,
                index_value,
                elem_ty,
                stride,
            )
        }
        _ => zero_lowered_for_type(builder, value_ty, scalar),
    }
}

fn lower_slice_value(
    value_ty: &MirValueType,
    base: &MirValueId,
    range: SliceRangeRef<'_>,
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    scalar: ScalarType,
    module: &mut ObjectModule,
) -> LoweredValue {
    let pointer_ty = module.target_config().pointer_type();
    match lowered.get(base).cloned() {
        Some(LoweredValue::EnumMemory { slot, ordered }) => {
            lower_homogeneous_slice_from_stack_slot(
                value_ty,
                builder,
                lowered,
                scalar,
                pointer_ty,
                StackSequenceLayoutRef {
                    slot,
                    ordered: &ordered,
                },
                range.start,
            )
        }
        Some(LoweredValue::StructMemory { slot, ordered, .. }) => {
            lower_homogeneous_slice_from_stack_slot(
                value_ty,
                builder,
                lowered,
                scalar,
                pointer_ty,
                StackSequenceLayoutRef {
                    slot,
                    ordered: &ordered,
                },
                range.start,
            )
        }
        Some(LoweredValue::BytesSlice { ptr, len }) => {
            let start_idx = range
                .start
                .and_then(|start| lowered.get(&start).and_then(LoweredValue::as_int))
                .map(|value| cast_scalar(builder, value, pointer_ty, scalar))
                .unwrap_or_else(|| zero_for_type(builder, pointer_ty));
            let mut end_idx = range
                .end
                .and_then(|end| lowered.get(&end).and_then(LoweredValue::as_int))
                .map(|value| cast_scalar(builder, value, pointer_ty, scalar))
                .unwrap_or(len);
            if range.inclusive && range.end.is_some() {
                end_idx = builder.ins().iadd_imm(end_idx, 1);
            }
            let new_ptr = builder.ins().iadd(ptr, start_idx);
            let new_len = builder.ins().isub(end_idx, start_idx);
            LoweredValue::BytesSlice {
                ptr: new_ptr,
                len: new_len,
            }
        }
        Some(LoweredValue::PointerSlice {
            base_addr,
            len,
            elem_ty,
            stride,
        }) => {
            let start_idx = range
                .start
                .and_then(|start| lowered.get(&start).and_then(LoweredValue::as_int))
                .map(|value| cast_scalar(builder, value, pointer_ty, scalar))
                .unwrap_or_else(|| zero_for_type(builder, pointer_ty));
            let mut end_idx = range
                .end
                .and_then(|end| lowered.get(&end).and_then(LoweredValue::as_int))
                .map(|value| cast_scalar(builder, value, pointer_ty, scalar))
                .unwrap_or(len);
            if range.inclusive && range.end.is_some() {
                end_idx = builder.ins().iadd_imm(end_idx, 1);
            }
            let scaled_start = if stride == 1 {
                start_idx
            } else {
                builder.ins().imul_imm(start_idx, stride)
            };
            let new_ptr = builder.ins().iadd(base_addr, scaled_start);
            let new_len = builder.ins().isub(end_idx, start_idx);
            LoweredValue::PointerSlice {
                base_addr: new_ptr,
                len: new_len,
                elem_ty,
                stride,
            }
        }
        Some(LoweredValue::EnumVariant { variant, payload }) => {
            LoweredValue::EnumVariant { variant, payload }
        }
        Some(other) => other,
        None => zero_lowered_for_type(builder, value_ty, scalar),
    }
}

fn lower_call_value(
    value_ty: &MirValueType,
    call: CallSiteRef<'_>,
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    scalar: ScalarType,
    module: &mut ObjectModule,
    symbol_tables: CallSymbolTables<'_>,
) -> LoweredValue {
    let pointer_ty = module.target_config().pointer_type();
    let direct_callee = match lowered.get(call.callee) {
        Some(LoweredValue::FunctionSymbol(func_id)) => Some(*func_id),
        _ => None,
    };

    // Handle fat pointer (closure) calls specially
    if let Some(lowered_value) = lower_fat_pointer_call(
        value_ty, &call, builder, lowered, scalar, module, pointer_ty,
    ) {
        return lowered_value;
    }

    let expected_param_types =
        direct_callee.and_then(|func_id| symbol_tables.param_types_by_id.get(&func_id.as_u32()));
    let Some(mut arg_vals) = marshal_call_arg_values(
        call.args,
        builder,
        lowered,
        module,
        expected_param_types.map(Vec::as_slice),
    ) else {
        return zero_lowered_for_type(builder, value_ty, scalar);
    };
    let profile = infer_call_return_profile(
        value_ty,
        direct_callee,
        symbol_tables.returns_bytes_slice_by_id,
        symbol_tables.returns_errorable_by_id,
        symbol_tables.returns_errorable_scalar_payload_ty_by_id,
        symbol_tables.returns_aggregate_layout_by_id,
    );
    let out_args = append_call_out_args(
        builder,
        pointer_ty,
        value_ty,
        scalar,
        &mut arg_vals,
        &profile,
    );
    let Some(ret) = emit_lowered_call(
        builder,
        module,
        arg_vals.as_mut_slice(),
        EmitCallContext {
            value_ty,
            callee: call.callee,
            lowered,
            scalar,
            param_types_by_id: symbol_tables.param_types_by_id,
            pointer_ty,
            direct_callee,
            profile: &profile,
        },
    ) else {
        return zero_lowered_for_type(builder, value_ty, scalar);
    };
    lower_call_result_value(
        value_ty, builder, scalar, pointer_ty, ret, profile, out_args,
    )
}

fn lower_fat_pointer_call(
    value_ty: &MirValueType,
    call: &CallSiteRef<'_>,
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    scalar: ScalarType,
    module: &mut ObjectModule,
    pointer_ty: Type,
) -> Option<LoweredValue> {
    let LoweredValue::FatPtr { fn_ptr, env_ptr } = lowered.get(call.callee).cloned()? else {
        return None;
    };
    let arg_vals = marshal_call_arg_values(call.args, builder, lowered, module, None)
        .unwrap_or_else(|| Vec::new());
    if arg_vals.is_empty() && !call.args.is_empty() {
        return Some(zero_lowered_for_type(builder, value_ty, scalar));
    }

    let mut call_args = vec![env_ptr];
    call_args.extend(arg_vals.iter().copied());

    let mut sig = module.make_signature();
    sig.params
        .push(cranelift_codegen::ir::AbiParam::new(pointer_ty));
    for &arg_value in &arg_vals {
        sig.params.push(cranelift_codegen::ir::AbiParam::new(
            builder.func.dfg.value_type(arg_value),
        ));
    }
    let return_ty = indirect_call_return_type(
        value_ty,
        scalar,
        pointer_ty,
        &CallReturnProfile {
            returns_bytes_slice: false,
            returns_aggregate: None,
            returns_errorable: false,
            returns_errorable_scalar: false,
            errorable_scalar_payload_ty: None,
        },
    );
    sig.returns
        .push(cranelift_codegen::ir::AbiParam::new(return_ty));
    let sig_ref = builder.import_signature(sig);
    let inst = builder.ins().call_indirect(sig_ref, fn_ptr, &call_args);
    let ret = builder
        .inst_results(inst)
        .first()
        .copied()
        .unwrap_or_else(|| zero_for_type(builder, return_ty));
    Some(LoweredValue::from_typed_value(ret, value_ty))
}

fn marshal_call_arg_values(
    args: &[MirValueId],
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    module: &mut ObjectModule,
    expected_param_types: Option<&[Type]>,
) -> Option<Vec<Value>> {
    let pointer_ty = module.target_config().pointer_type();
    let mut arg_vals = Vec::with_capacity(args.len().saturating_mul(2).saturating_add(1));
    let mut expected_index = 0usize;
    for arg in args {
        let expects_bytes_slice = expected_param_types.is_some_and(|types| {
            matches!(
                (types.get(expected_index), types.get(expected_index + 1)),
                (Some(a), Some(b)) if *a == pointer_ty && *b == pointer_ty
            )
        });
        match lowered.get(arg).cloned() {
            Some(LoweredValue::FunctionSymbol(func_id)) => {
                let func_ref = module.declare_func_in_func(func_id, builder.func);
                arg_vals.push(builder.ins().func_addr(pointer_ty, func_ref));
                expected_index += 1;
            }
            Some(LoweredValue::StructMemory { slot, .. }) => {
                if expects_bytes_slice {
                    let LoweredValue::StructMemory { ordered, .. } = lowered.get(arg).cloned()?
                    else {
                        return None;
                    };
                    let (elem_ty, base_offset, _stride) = homogeneous_sequence_layout(&ordered)?;
                    if !elem_ty.is_int() {
                        return None;
                    }
                    arg_vals.push(builder.ins().stack_addr(pointer_ty, slot, base_offset));
                    arg_vals.push(
                        builder
                            .ins()
                            .iconst(pointer_ty, i64::try_from(ordered.len()).unwrap_or(i64::MAX)),
                    );
                    expected_index += 2;
                } else {
                    arg_vals.push(builder.ins().stack_addr(pointer_ty, slot, 0));
                    expected_index += 1;
                }
            }
            Some(LoweredValue::StructPointer {
                addr,
                stack_slot,
                stack_offset,
                ..
            }) => {
                let current = rematerialize_struct_pointer_addr(
                    builder,
                    pointer_ty,
                    addr,
                    stack_slot,
                    stack_offset,
                );
                arg_vals.push(current);
                expected_index += 1;
            }
            Some(LoweredValue::Struct(fields)) => {
                let lowered_pairs = fields.into_iter().collect::<Vec<_>>();
                let materialized = materialize_struct_memory(builder, module, &lowered_pairs)?;
                match materialized {
                    LoweredValue::StructMemory { slot, .. } => {
                        arg_vals.push(builder.ins().stack_addr(pointer_ty, slot, 0));
                        expected_index += 1;
                    }
                    _ => return None,
                }
            }
            Some(LoweredValue::BytesSlice { ptr, len }) => {
                arg_vals.push(ptr);
                arg_vals.push(len);
                expected_index += 2;
            }
            Some(LoweredValue::FatPtr { fn_ptr, env_ptr }) => {
                // Stack-allocate the fat pointer and pass its address
                let ptr_bytes = pointer_ty.bytes();
                let align_log2 = if ptr_bytes == 8 { 3 } else { 2 };
                let slot = builder.func.create_sized_stack_slot(
                    cranelift_codegen::ir::StackSlotData::new(
                        cranelift_codegen::ir::StackSlotKind::ExplicitSlot,
                        ptr_bytes * 2,
                        align_log2,
                    ),
                );
                builder.ins().stack_store(fn_ptr, slot, 0);
                builder.ins().stack_store(env_ptr, slot, ptr_bytes as i32);
                let addr = builder.ins().stack_addr(pointer_ty, slot, 0);
                arg_vals.push(addr);
                expected_index += 1;
            }
            Some(other) => {
                arg_vals.push(other.as_value()?);
                expected_index += 1;
            }
            None => return None,
        }
    }
    Some(arg_vals)
}

fn infer_call_return_profile(
    value_ty: &MirValueType,
    direct_callee: Option<FuncId>,
    returns_bytes_slice_by_id: &BTreeMap<u32, bool>,
    returns_errorable_by_id: &BTreeMap<u32, bool>,
    returns_errorable_scalar_payload_ty_by_id: &BTreeMap<u32, MirValueType>,
    returns_aggregate_layout_by_id: &BTreeMap<u32, AggregateLayout>,
) -> CallReturnProfile {
    let mut returns_bytes_slice = matches!(value_ty, MirValueType::BytesSlice);
    let mut returns_aggregate = None;
    let mut returns_errorable = false;
    let mut errorable_scalar_payload_ty = None;
    if let Some(func_id) = direct_callee {
        if let Some(returns_slice) = returns_bytes_slice_by_id.get(&func_id.as_u32()) {
            returns_bytes_slice = *returns_slice;
        }
        if let Some(is_errorable) = returns_errorable_by_id.get(&func_id.as_u32()) {
            returns_errorable = *is_errorable;
        }
        if let Some(payload_ty) = returns_errorable_scalar_payload_ty_by_id.get(&func_id.as_u32()) {
            errorable_scalar_payload_ty = Some(payload_ty.clone());
        }
        if let Some(layout) = returns_aggregate_layout_by_id.get(&func_id.as_u32()) {
            returns_aggregate = Some(layout.clone());
        }
    }
    let returns_errorable_scalar =
        returns_errorable && !returns_bytes_slice && returns_aggregate.is_none();
    CallReturnProfile {
        returns_bytes_slice,
        returns_aggregate,
        returns_errorable,
        returns_errorable_scalar,
        errorable_scalar_payload_ty,
    }
}

fn append_call_out_args(
    builder: &mut FunctionBuilder,
    pointer_ty: Type,
    value_ty: &MirValueType,
    scalar: ScalarType,
    arg_vals: &mut Vec<Value>,
    profile: &CallReturnProfile,
) -> CallOutArgs {
    let ret_len_slot = if profile.returns_bytes_slice {
        Some(builder.func.create_sized_stack_slot(StackSlotData::new(
            StackSlotKind::ExplicitSlot,
            pointer_ty.bits() / 8,
            0,
        )))
    } else {
        None
    };
    if let Some(slot) = ret_len_slot {
        let out_len = builder.ins().stack_addr(pointer_ty, slot, 0);
        arg_vals.push(out_len);
    }
    let aggregate_out_slot = profile.returns_aggregate.as_ref().map(|layout| {
        let align_shift = layout.align.max(1).trailing_zeros() as u8;
        let slot = builder.func.create_sized_stack_slot(StackSlotData::new(
            StackSlotKind::ExplicitSlot,
            layout.size.max(1),
            align_shift,
        ));
        let out_ptr = builder.ins().stack_addr(pointer_ty, slot, 0);
        arg_vals.push(out_ptr);
        slot
    });

    let errorable_scalar_out = if profile.returns_errorable_scalar {
        let payload_mir_ty = if matches!(value_ty, MirValueType::Unknown) {
            profile
                .errorable_scalar_payload_ty
                .as_ref()
                .unwrap_or(value_ty)
        } else {
            value_ty
        };
        let payload_ty = if matches!(payload_mir_ty, MirValueType::Unknown) {
            scalar.ty()
        } else {
            mir_type_to_clif(payload_mir_ty, scalar)
        };
        let slot_size = (payload_ty.bits() / 8).max(1);
        let align_shift = slot_size.trailing_zeros() as u8;
        let slot = builder.func.create_sized_stack_slot(StackSlotData::new(
            StackSlotKind::ExplicitSlot,
            slot_size,
            align_shift,
        ));
        let out_ptr = builder.ins().stack_addr(pointer_ty, slot, 0);
        arg_vals.push(out_ptr);
        Some((slot, payload_ty))
    } else {
        None
    };

    CallOutArgs {
        ret_len_slot,
        aggregate_out_slot,
        errorable_scalar_out,
    }
}

fn indirect_call_return_type(
    value_ty: &MirValueType,
    scalar: ScalarType,
    pointer_ty: Type,
    profile: &CallReturnProfile,
) -> Type {
    if profile.returns_bytes_slice {
        pointer_ty
    } else if profile.returns_aggregate.is_some() {
        if profile.returns_errorable {
            scalar.ty()
        } else {
            pointer_ty
        }
    } else if matches!(value_ty, MirValueType::Unknown) {
        scalar.ty()
    } else {
        mir_type_to_clif(value_ty, scalar)
    }
}

fn emit_lowered_call(
    builder: &mut FunctionBuilder,
    module: &mut ObjectModule,
    arg_vals: &mut [Value],
    context: EmitCallContext<'_>,
) -> Option<Value> {
    if let Some(func_id) = context.direct_callee {
        if let Some(param_types) = context.param_types_by_id.get(&func_id.as_u32()) {
            if param_types.len() != arg_vals.len() {
                return None;
            }
            for (arg, ty) in arg_vals.iter_mut().zip(param_types) {
                *arg = cast_scalar(builder, *arg, *ty, context.scalar);
            }
        }
        return Some(emit_declared_func_call(
            builder,
            module,
            func_id,
            arg_vals,
            context.pointer_ty,
        ));
    }

    let callee_val = context
        .lowered
        .get(context.callee)
        .and_then(LoweredValue::as_value)?;
    if value_is_definitely_zero(builder, callee_val, 0) {
        return None;
    }
    let mut signature = module.make_signature();
    for arg in arg_vals.iter() {
        signature
            .params
            .push(AbiParam::new(builder.func.dfg.value_type(*arg)));
    }
    let return_ty = indirect_call_return_type(
        context.value_ty,
        context.scalar,
        context.pointer_ty,
        context.profile,
    );
    signature.returns.push(AbiParam::new(return_ty));
    let sig_ref = builder.import_signature(signature);
    let callee_ptr = cast_scalar(builder, callee_val, context.pointer_ty, context.scalar);
    let inst = builder.ins().call_indirect(sig_ref, callee_ptr, arg_vals);
    Some(
        builder
            .inst_results(inst)
            .first()
            .copied()
            .unwrap_or_else(|| zero_for_type(builder, return_ty)),
    )
}

fn lower_call_result_value(
    value_ty: &MirValueType,
    builder: &mut FunctionBuilder,
    scalar: ScalarType,
    pointer_ty: Type,
    ret: Value,
    profile: CallReturnProfile,
    out_args: CallOutArgs,
) -> LoweredValue {
    if profile.returns_bytes_slice {
        return lower_bytes_slice_call_result(builder, scalar, pointer_ty, ret, out_args);
    }

    if let (Some(layout), Some(slot)) = (
        profile.returns_aggregate.clone(),
        out_args.aggregate_out_slot,
    ) {
        return lower_aggregate_call_result(
            builder,
            scalar,
            pointer_ty,
            ret,
            profile.returns_errorable,
            layout,
            slot,
        );
    }

    if profile.returns_errorable_scalar {
        return lower_errorable_scalar_call_result(
            value_ty, builder, scalar, ret, profile, out_args,
        );
    }

    lower_scalar_call_result(value_ty, builder, scalar, ret)
}

fn lower_bytes_slice_call_result(
    builder: &mut FunctionBuilder,
    scalar: ScalarType,
    pointer_ty: Type,
    ret: Value,
    out_args: CallOutArgs,
) -> LoweredValue {
    let len = out_args
        .ret_len_slot
        .map(|slot| builder.ins().stack_load(pointer_ty, slot, 0))
        .unwrap_or_else(|| zero_for_type(builder, pointer_ty));
    LoweredValue::BytesSlice {
        ptr: cast_scalar(builder, ret, pointer_ty, scalar),
        len,
    }
}

fn lower_aggregate_call_result(
    builder: &mut FunctionBuilder,
    scalar: ScalarType,
    pointer_ty: Type,
    ret: Value,
    returns_errorable: bool,
    layout: AggregateLayout,
    slot: StackSlot,
) -> LoweredValue {
    let addr = builder.ins().stack_addr(pointer_ty, slot, 0);
    LoweredValue::StructPointer {
        addr,
        stack_slot: Some(slot),
        stack_offset: 0,
        status: returns_errorable.then(|| cast_scalar(builder, ret, scalar.ty(), scalar)),
        fields: layout.fields,
        aggregate_fields: layout.aggregate_fields,
        ordered: layout.ordered,
        scalar_leaves: layout.scalar_leaves,
        size: layout.size,
        align: layout.align,
    }
}

fn lower_errorable_scalar_call_result(
    value_ty: &MirValueType,
    builder: &mut FunctionBuilder,
    scalar: ScalarType,
    ret: Value,
    profile: CallReturnProfile,
    out_args: CallOutArgs,
) -> LoweredValue {
    let payload_mir_ty = if matches!(value_ty, MirValueType::Unknown) {
        profile
            .errorable_scalar_payload_ty
            .as_ref()
            .unwrap_or(value_ty)
    } else {
        value_ty
    };
    let (payload, payload_ty) = if let Some((slot, payload_ty)) = out_args.errorable_scalar_out {
        (builder.ins().stack_load(payload_ty, slot, 0), payload_ty)
    } else {
        let ty = if matches!(payload_mir_ty, MirValueType::Unknown) {
            scalar.ty()
        } else {
            mir_type_to_clif(payload_mir_ty, scalar)
        };
        (zero_for_type(builder, ty), ty)
    };
    LoweredValue::ErrorableScalar {
        status: cast_scalar(builder, ret, scalar.ty(), scalar),
        payload,
        payload_is_float: payload_ty.is_float(),
    }
}

fn lower_scalar_call_result(
    value_ty: &MirValueType,
    builder: &mut FunctionBuilder,
    scalar: ScalarType,
    ret: Value,
) -> LoweredValue {
    if matches!(value_ty, MirValueType::Unknown) {
        let ret_ty = builder.func.dfg.value_type(ret);
        if ret_ty.is_float() {
            return LoweredValue::Float(ret);
        }
        return LoweredValue::Int(ret);
    }

    if matches!(value_ty, MirValueType::Float { .. }) {
        LoweredValue::Float(cast_scalar(
            builder,
            ret,
            mir_type_to_clif(value_ty, scalar),
            scalar,
        ))
    } else {
        LoweredValue::Int(cast_scalar(
            builder,
            ret,
            mir_type_to_clif(value_ty, scalar),
            scalar,
        ))
    }
}

fn lower_error_status_value(
    value_ty: &MirValueType,
    value: &MirValueId,
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    scalar: ScalarType,
) -> LoweredValue {
    let status_ty = if matches!(value_ty, MirValueType::Unknown) {
        scalar.ty()
    } else {
        mir_type_to_clif(value_ty, scalar)
    };
    let status = lowered
        .get(value)
        .and_then(|lowered| lowered.error_status().or_else(|| lowered.as_int()))
        .map(|status| cast_scalar(builder, status, status_ty, scalar))
        .unwrap_or_else(|| zero_for_type(builder, status_ty));
    LoweredValue::Int(status)
}

fn lower_error_payload_value(
    value_ty: &MirValueType,
    value: &MirValueId,
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    scalar: ScalarType,
) -> LoweredValue {
    let Some(source) = lowered.get(value).cloned() else {
        return zero_lowered_for_type(builder, value_ty, scalar);
    };

    match source {
        LoweredValue::ErrorableScalar {
            payload,
            payload_is_float: _,
            ..
        } => {
            let target_ty = if matches!(value_ty, MirValueType::Unknown) {
                builder.func.dfg.value_type(payload)
            } else {
                mir_type_to_clif(value_ty, scalar)
            };
            let casted = cast_scalar(builder, payload, target_ty, scalar);
            if target_ty.is_float() {
                LoweredValue::Float(casted)
            } else {
                LoweredValue::Int(casted)
            }
        }
        LoweredValue::StructPointer {
            addr,
            stack_slot,
            stack_offset,
            fields,
            aggregate_fields,
            ordered,
            scalar_leaves,
            size,
            align,
            ..
        } => LoweredValue::StructPointer {
            addr,
            stack_slot,
            stack_offset,
            status: None,
            fields,
            aggregate_fields,
            ordered,
            scalar_leaves,
            size,
            align,
        },
        other => other,
    }
}

fn zero_lowered_for_type(
    builder: &mut FunctionBuilder,
    value_ty: &MirValueType,
    scalar: ScalarType,
) -> LoweredValue {
    if matches!(value_ty, MirValueType::BytesSlice) {
        let zero = zero_for_type(builder, I64);
        return LoweredValue::BytesSlice {
            ptr: zero,
            len: zero,
        };
    }

    let ty = if matches!(value_ty, MirValueType::Unknown) {
        scalar.ty()
    } else {
        mir_type_to_clif(value_ty, scalar)
    };
    if ty.is_float() {
        LoweredValue::Float(zero_for_type(builder, ty))
    } else {
        LoweredValue::Int(zero_for_type(builder, ty))
    }
}

fn lower_literal(
    literal: &HirLiteral,
    value_ty: &MirValueType,
    scalar: ScalarType,
    builder: &mut FunctionBuilder,
    module: &mut ObjectModule,
    _symbols_by_name: &BTreeMap<String, FuncId>,
) -> LoweredValue {
    match literal {
        HirLiteral::Integer(value) => {
            let int_ty = mir_type_to_clif(value_ty, scalar);
            if int_ty == I128 {
                let bits = parse_int_literal_wide_bits(value).unwrap_or(0);
                let lo = builder.ins().iconst(I64, bits as u64 as i64);
                let hi = builder.ins().iconst(I64, (bits >> 64) as u64 as i64);
                LoweredValue::Int(builder.ins().iconcat(lo, hi))
            } else {
                LoweredValue::Int(
                    builder
                        .ins()
                        .iconst(int_ty, parse_int_literal(value).unwrap_or(0)),
                )
            }
        }
        HirLiteral::Bool(value) => {
            let ty = bool_storage_type(scalar);
            LoweredValue::Int(builder.ins().iconst(ty, i64::from(*value)))
        }
        HirLiteral::Char(value) => {
            let int_ty = mir_type_to_clif(value_ty, scalar);
            LoweredValue::Int(builder.ins().iconst(int_ty, *value as i64))
        }
        HirLiteral::Float(value) => {
            let float_ty = mir_type_to_clif(value_ty, scalar);
            if float_ty == F32 {
                let bits = value.parse::<f32>().unwrap_or(0.0).to_bits();
                LoweredValue::Float(
                    builder
                        .ins()
                        .f32const(cranelift_codegen::ir::immediates::Ieee32::with_bits(bits)),
                )
            } else if float_ty == F64 {
                let bits = value.parse::<f64>().unwrap_or(0.0).to_bits();
                LoweredValue::Float(
                    builder
                        .ins()
                        .f64const(cranelift_codegen::ir::immediates::Ieee64::with_bits(bits)),
                )
            } else {
                LoweredValue::Float(zero_for_type(builder, float_ty))
            }
        }
        HirLiteral::Null => match scalar {
            ScalarType::Float { ty } => LoweredValue::Float(zero_for_type(builder, ty)),
            ScalarType::Int { ty, .. } => LoweredValue::Int(builder.ins().iconst(ty, 0)),
        },
        HirLiteral::String(value) => {
            let text = if value.len() >= 2 && value.starts_with('"') && value.ends_with('"') {
                &value[1..value.len() - 1]
            } else {
                value.as_str()
            };
            let bytes = text.as_bytes();
            let ptr_ty = module.target_config().pointer_type();
            let size = (bytes.len() + 1) as u32;
            let slot = builder.func.create_sized_stack_slot(StackSlotData::new(
                StackSlotKind::ExplicitSlot,
                size.max(1),
                0,
            ));
            for (idx, byte) in bytes.iter().enumerate() {
                let byte_val = builder.ins().iconst(I8, i64::from(*byte));
                builder.ins().stack_store(byte_val, slot, idx as i32);
            }
            let nul = builder.ins().iconst(I8, 0);
            builder.ins().stack_store(nul, slot, bytes.len() as i32);
            let addr = builder.ins().stack_addr(ptr_ty, slot, 0);
            let len_value = builder.ins().iconst(ptr_ty, bytes.len() as i64);
            LoweredValue::BytesSlice {
                ptr: addr,
                len: len_value,
            }
        }
    }
}

fn materialize_struct_memory(
    builder: &mut FunctionBuilder,
    module: &mut ObjectModule,
    fields: &[(String, LoweredValue)],
) -> Option<LoweredValue> {
    enum StorePlan {
        Scalar {
            value: Value,
            offset: i32,
        },
        CopyFromSlot {
            slot: StackSlot,
            leaves: Vec<(Type, i32)>,
            base_offset: i32,
        },
        CopyFromPtr {
            addr: Value,
            leaves: Vec<(Type, i32)>,
            base_offset: i32,
        },
    }

    let pointer_ty = module.target_config().pointer_type();
    let mut scalar_fields = BTreeMap::new();
    let mut aggregate_fields = BTreeMap::new();
    let mut ordered = Vec::new();
    let mut scalar_leaves = Vec::new();
    let mut plans = Vec::new();
    let mut size = 0u32;
    let mut max_align = 1u32;

    for (name, value) in fields {
        let lowered = match value.clone() {
            LoweredValue::Struct(nested) => {
                let nested_fields = nested.into_iter().collect::<Vec<_>>();
                materialize_struct_memory(builder, module, &nested_fields)?
            }
            other => other,
        };

        match lowered {
            LoweredValue::Int(field_value) | LoweredValue::Float(field_value) => {
                let field_ty = builder.func.dfg.value_type(field_value);
                let align = (field_ty.bits() / 8).max(1);
                max_align = max_align.max(align);
                size = align_to(size, align);
                let offset = size as i32;
                size = size.saturating_add(align);
                scalar_fields.insert(name.clone(), (field_ty, offset));
                ordered.push((field_ty, offset));
                scalar_leaves.push((field_ty, offset));
                plans.push(StorePlan::Scalar {
                    value: field_value,
                    offset,
                });
            }
            LoweredValue::PointerSlice { base_addr, .. }
            | LoweredValue::BytesSlice { ptr: base_addr, .. } => {
                let field_ty = builder.func.dfg.value_type(base_addr);
                let align = (field_ty.bits() / 8).max(1);
                max_align = max_align.max(align);
                size = align_to(size, align);
                let offset = size as i32;
                size = size.saturating_add(align);
                scalar_fields.insert(name.clone(), (field_ty, offset));
                ordered.push((field_ty, offset));
                scalar_leaves.push((field_ty, offset));
                plans.push(StorePlan::Scalar {
                    value: base_addr,
                    offset,
                });
            }
            LoweredValue::FunctionSymbol(func_id) => {
                let func_ref = module.declare_func_in_func(func_id, builder.func);
                let addr = builder.ins().func_addr(pointer_ty, func_ref);
                let align = (pointer_ty.bits() / 8).max(1);
                max_align = max_align.max(align);
                size = align_to(size, align);
                let offset = size as i32;
                size = size.saturating_add(align);
                scalar_fields.insert(name.clone(), (pointer_ty, offset));
                ordered.push((pointer_ty, offset));
                scalar_leaves.push((pointer_ty, offset));
                plans.push(StorePlan::Scalar {
                    value: addr,
                    offset,
                });
            }
            LoweredValue::StructMemory {
                slot,
                fields,
                aggregate_fields: nested_aggregate_fields,
                ordered: nested_ordered,
                scalar_leaves: nested_leaves,
                size: nested_size,
                align: nested_align,
            } => {
                let align = nested_align.max(1);
                max_align = max_align.max(align);
                size = align_to(size, align);
                let offset = size as i32;
                size = size.saturating_add(nested_size.max(1));

                for (leaf_ty, leaf_offset) in &nested_leaves {
                    scalar_leaves.push((*leaf_ty, offset + *leaf_offset));
                }

                let nested_layout = AggregateLayout {
                    fields,
                    aggregate_fields: nested_aggregate_fields,
                    ordered: nested_ordered,
                    scalar_leaves: nested_leaves.clone(),
                    size: nested_size,
                    align: nested_align,
                };
                aggregate_fields.insert(name.clone(), (offset, Box::new(nested_layout.clone())));
                plans.push(StorePlan::CopyFromSlot {
                    slot,
                    leaves: nested_layout.scalar_leaves,
                    base_offset: offset,
                });
            }
            LoweredValue::StructPointer {
                addr,
                stack_slot,
                stack_offset,
                status: _,
                fields,
                aggregate_fields: nested_aggregate_fields,
                ordered: nested_ordered,
                scalar_leaves: nested_leaves,
                size: nested_size,
                align: nested_align,
            } => {
                let align = nested_align.max(1);
                max_align = max_align.max(align);
                size = align_to(size, align);
                let offset = size as i32;
                size = size.saturating_add(nested_size.max(1));

                for (leaf_ty, leaf_offset) in &nested_leaves {
                    scalar_leaves.push((*leaf_ty, offset + *leaf_offset));
                }

                let nested_layout = AggregateLayout {
                    fields,
                    aggregate_fields: nested_aggregate_fields,
                    ordered: nested_ordered,
                    scalar_leaves: nested_leaves.clone(),
                    size: nested_size,
                    align: nested_align,
                };
                aggregate_fields.insert(name.clone(), (offset, Box::new(nested_layout.clone())));
                let source_addr = rematerialize_struct_pointer_addr(
                    builder,
                    pointer_ty,
                    addr,
                    stack_slot,
                    stack_offset,
                );
                plans.push(StorePlan::CopyFromPtr {
                    addr: source_addr,
                    leaves: nested_layout.scalar_leaves,
                    base_offset: offset,
                });
            }
            _ => return None,
        }
    }

    size = align_to(size, max_align).max(1);
    let align_shift = (max_align.max(1)).trailing_zeros() as u8;
    let slot = builder.func.create_sized_stack_slot(StackSlotData::new(
        StackSlotKind::ExplicitSlot,
        size,
        align_shift,
    ));
    zero_stack_slot(builder, slot, size);

    for plan in plans {
        match plan {
            StorePlan::Scalar { value, offset } => {
                builder.ins().stack_store(value, slot, offset);
            }
            StorePlan::CopyFromSlot {
                slot: src_slot,
                leaves,
                base_offset,
            } => {
                copy_scalar_leaves_to_stack_slot(
                    builder,
                    slot,
                    base_offset,
                    &leaves,
                    |builder, leaf_ty, leaf_offset| {
                        builder.ins().stack_load(leaf_ty, src_slot, leaf_offset)
                    },
                );
            }
            StorePlan::CopyFromPtr {
                addr,
                leaves,
                base_offset,
            } => {
                copy_scalar_leaves_to_stack_slot(
                    builder,
                    slot,
                    base_offset,
                    &leaves,
                    |builder, leaf_ty, leaf_offset| {
                        builder.ins().load(
                            leaf_ty,
                            cranelift_codegen::ir::MemFlags::new(),
                            addr,
                            leaf_offset,
                        )
                    },
                );
            }
        }
    }

    Some(LoweredValue::StructMemory {
        slot,
        fields: scalar_fields,
        aggregate_fields,
        ordered,
        scalar_leaves,
        size,
        align: max_align,
    })
}

fn zero_stack_slot(builder: &mut FunctionBuilder, slot: StackSlot, size: u32) {
    let mut offset = 0i32;
    let mut remaining = size as i32;
    for (chunk_size, ty) in [(8i32, I64), (4i32, I32), (2i32, I16), (1i32, I8)] {
        let zero = zero_for_type(builder, ty);
        while remaining >= chunk_size {
            builder.ins().stack_store(zero, slot, offset);
            offset += chunk_size;
            remaining -= chunk_size;
        }
    }
}

fn copy_scalar_leaves_to_stack_slot<F>(
    builder: &mut FunctionBuilder,
    dst_slot: StackSlot,
    base_offset: i32,
    leaves: &[(Type, i32)],
    mut load_leaf: F,
) where
    F: FnMut(&mut FunctionBuilder, Type, i32) -> Value,
{
    for (leaf_ty, leaf_offset) in leaves {
        let loaded = load_leaf(builder, *leaf_ty, *leaf_offset);
        builder
            .ins()
            .stack_store(loaded, dst_slot, base_offset + *leaf_offset);
    }
}

fn spill_scalar_to_stack_and_get_addr(
    builder: &mut FunctionBuilder,
    module: &ObjectModule,
    value: Value,
) -> Value {
    let value_ty = builder.func.dfg.value_type(value);
    let size = (value_ty.bits().max(8) / 8).max(1);
    let align = size.next_power_of_two();
    let align_shift = align.trailing_zeros() as u8;
    let slot = builder.func.create_sized_stack_slot(StackSlotData::new(
        StackSlotKind::ExplicitSlot,
        size,
        align_shift,
    ));
    builder.ins().stack_store(value, slot, 0);
    builder
        .ins()
        .stack_addr(module.target_config().pointer_type(), slot, 0)
}

fn materialize_enum_memory(
    builder: &mut FunctionBuilder,
    module: &mut ObjectModule,
    tag: i64,
    tag_bits: u16,
    payload: &[LoweredValue],
) -> Option<LoweredValue> {
    let mut values = Vec::with_capacity(payload.len() + 1);
    let tag_ty = int_carrier_type_for_bits(tag_bits);
    let tag_value = builder.ins().iconst(tag_ty, tag);
    values.push(("__tag".to_string(), LoweredValue::Int(tag_value)));
    for (idx, value) in payload.iter().cloned().enumerate() {
        values.push((format!("__payload_{idx}"), value));
    }

    let mut ordered_values = Vec::new();
    for (_name, value) in values {
        if !matches!(value, LoweredValue::Int(_) | LoweredValue::Float(_)) {
            return None;
        }
        ordered_values.push((String::new(), value));
    }
    let mem = materialize_struct_memory(builder, module, &ordered_values)?;
    match mem {
        LoweredValue::StructMemory { slot, ordered, .. } => {
            Some(LoweredValue::EnumMemory { slot, ordered })
        }
        _ => None,
    }
}

fn zero_aggregate_at_pointer(
    builder: &mut FunctionBuilder,
    out_ptr: Value,
    layout: &AggregateLayout,
) {
    for (ty, offset) in &layout.scalar_leaves {
        let zero = zero_for_type(builder, *ty);
        builder.ins().store(
            cranelift_codegen::ir::MemFlags::new(),
            zero,
            out_ptr,
            *offset,
        );
    }
}

fn cast_between_types(
    builder: &mut FunctionBuilder,
    value: Value,
    source_ty: Type,
    target_ty: Type,
) -> Value {
    if source_ty == target_ty {
        return value;
    }
    if source_ty.is_int() && target_ty.is_int() {
        return cast_int(builder, value, target_ty, false);
    }
    if source_ty.is_float() && target_ty.is_float() {
        if source_ty.bits() > target_ty.bits() {
            return builder.ins().fdemote(target_ty, value);
        }
        return builder.ins().fpromote(target_ty, value);
    }
    if source_ty.is_int() && target_ty.is_float() {
        return builder.ins().fcvt_from_uint(target_ty, value);
    }
    if source_ty.is_float() && target_ty.is_int() {
        return builder.ins().fcvt_to_uint_sat(target_ty, value);
    }
    value
}

fn scalar_leaf_types_by_offset(scalar_leaves: &[(Type, i32)]) -> BTreeMap<i32, Type> {
    scalar_leaves
        .iter()
        .copied()
        .map(|(ty, offset)| (offset, ty))
        .collect::<BTreeMap<_, _>>()
}

fn write_aggregate_leaves_with_loader<F>(
    builder: &mut FunctionBuilder,
    out_ptr: Value,
    dst_leaves: &[(Type, i32)],
    source_by_offset: &BTreeMap<i32, Type>,
    mut load_leaf: F,
) where
    F: FnMut(&mut FunctionBuilder, Type, i32) -> Value,
{
    for (dst_ty, dst_offset) in dst_leaves {
        let stored = if let Some(src_ty) = source_by_offset.get(dst_offset).copied() {
            let loaded = load_leaf(builder, src_ty, *dst_offset);
            cast_between_types(builder, loaded, src_ty, *dst_ty)
        } else {
            zero_for_type(builder, *dst_ty)
        };
        builder.ins().store(
            cranelift_codegen::ir::MemFlags::new(),
            stored,
            out_ptr,
            *dst_offset,
        );
    }
}

fn write_aggregate_to_pointer(
    builder: &mut FunctionBuilder,
    out_ptr: Value,
    layout: &AggregateLayout,
    value: &LoweredValue,
) {
    match value {
        LoweredValue::StructMemory {
            slot,
            scalar_leaves,
            ..
        } => {
            let source_by_offset = scalar_leaf_types_by_offset(scalar_leaves);
            write_aggregate_leaves_with_loader(
                builder,
                out_ptr,
                &layout.scalar_leaves,
                &source_by_offset,
                |builder, src_ty, dst_offset| builder.ins().stack_load(src_ty, *slot, dst_offset),
            );
        }
        LoweredValue::StructPointer {
            addr,
            stack_slot,
            stack_offset,
            scalar_leaves,
            ..
        } => {
            let pointer_ty = builder.func.dfg.value_type(*addr);
            let source_addr = rematerialize_struct_pointer_addr(
                builder,
                pointer_ty,
                *addr,
                *stack_slot,
                *stack_offset,
            );
            let source_by_offset = scalar_leaf_types_by_offset(scalar_leaves);
            write_aggregate_leaves_with_loader(
                builder,
                out_ptr,
                &layout.scalar_leaves,
                &source_by_offset,
                |builder, src_ty, dst_offset| {
                    builder.ins().load(
                        src_ty,
                        cranelift_codegen::ir::MemFlags::new(),
                        source_addr,
                        dst_offset,
                    )
                },
            );
        }
        _ => {
            zero_aggregate_at_pointer(builder, out_ptr, layout);
        }
    }
}

fn variant_tag(variant: &str) -> u32 {
    let mut hash = 2166136261u32;
    for byte in variant.as_bytes() {
        hash ^= u32::from(*byte);
        hash = hash.wrapping_mul(16777619);
    }
    hash
}

fn homogeneous_sequence_layout(ordered: &[(Type, i32)]) -> Option<(Type, i32, i64)> {
    let (first_ty, first_off) = ordered.first().copied()?;
    let stride = (first_ty.bits() / 8).max(1) as i64;
    for (idx, (ty, off)) in ordered.iter().copied().enumerate() {
        if ty != first_ty {
            return None;
        }
        let expected = first_off as i64 + (idx as i64 * stride);
        if off as i64 != expected {
            return None;
        }
    }
    Some((first_ty, first_off, stride))
}

fn mir_value_resolves_to_unknown(
    value_id: MirValueId,
    value_defs: &BTreeMap<MirValueId, MirValue>,
    depth: usize,
) -> bool {
    if depth > 32 {
        return false;
    }
    match value_defs.get(&value_id) {
        Some(MirValue::Unknown) => true,
        Some(MirValue::LocalSet { value, .. })
        | Some(MirValue::Assign { value, .. })
        | Some(MirValue::Unary { operand: value, .. })
        | Some(MirValue::Cast { value, .. })
        | Some(MirValue::ErrorStatus { value })
        | Some(MirValue::ErrorPayload { value })
        | Some(MirValue::FieldAccess { base: value, .. })
        | Some(MirValue::DerefAccess { base: value })
        | Some(MirValue::Slice { base: value, .. }) => {
            mir_value_resolves_to_unknown(*value, value_defs, depth + 1)
        }
        Some(MirValue::Binary { left, right, .. }) => {
            mir_value_resolves_to_unknown(*left, value_defs, depth + 1)
                || mir_value_resolves_to_unknown(*right, value_defs, depth + 1)
        }
        Some(MirValue::Index { base, index }) => {
            mir_value_resolves_to_unknown(*base, value_defs, depth + 1)
                || mir_value_resolves_to_unknown(*index, value_defs, depth + 1)
        }
        Some(MirValue::Call { callee, args }) => {
            mir_value_resolves_to_unknown(*callee, value_defs, depth + 1)
                || args
                    .iter()
                    .any(|arg| mir_value_resolves_to_unknown(*arg, value_defs, depth + 1))
        }
        Some(MirValue::StructLiteral { fields }) => fields
            .iter()
            .any(|(_, value)| mir_value_resolves_to_unknown(*value, value_defs, depth + 1)),
        Some(MirValue::EnumVariant { payload, .. }) => payload
            .iter()
            .any(|value| mir_value_resolves_to_unknown(*value, value_defs, depth + 1)),
        _ => false,
    }
}

fn mir_value_resolves_to_empty_enum_variant(
    value_id: MirValueId,
    value_defs: &BTreeMap<MirValueId, MirValue>,
    depth: usize,
) -> bool {
    if depth > 32 {
        return false;
    }
    match value_defs.get(&value_id) {
        Some(MirValue::EnumVariant { payload, .. }) => payload.is_empty(),
        Some(MirValue::LocalSet { value, .. })
        | Some(MirValue::Assign { value, .. })
        | Some(MirValue::Unary { operand: value, .. })
        | Some(MirValue::ErrorStatus { value })
        | Some(MirValue::ErrorPayload { value })
        | Some(MirValue::Cast { value, .. }) => {
            mir_value_resolves_to_empty_enum_variant(*value, value_defs, depth + 1)
        }
        _ => false,
    }
}

fn mir_value_resolves_to_error_status(
    value_id: MirValueId,
    value_defs: &BTreeMap<MirValueId, MirValue>,
    depth: usize,
) -> bool {
    if depth > 32 {
        return false;
    }
    match value_defs.get(&value_id) {
        Some(MirValue::ErrorStatus { .. }) => true,
        Some(MirValue::LocalSet { value, .. })
        | Some(MirValue::Assign { value, .. })
        | Some(MirValue::Unary { operand: value, .. })
        | Some(MirValue::Cast { value, .. }) => {
            mir_value_resolves_to_error_status(*value, value_defs, depth + 1)
        }
        _ => false,
    }
}

fn mir_value_resolve_callee_name(
    value_id: MirValueId,
    value_defs: &BTreeMap<MirValueId, MirValue>,
    depth: usize,
) -> Option<String> {
    if depth > 32 {
        return None;
    }
    match value_defs.get(&value_id) {
        Some(MirValue::Ident(name)) => Some(name.clone()),
        Some(MirValue::LocalSet { value, .. })
        | Some(MirValue::Assign { value, .. })
        | Some(MirValue::Unary { operand: value, .. })
        | Some(MirValue::Cast { value, .. })
        | Some(MirValue::ErrorPayload { value })
        | Some(MirValue::ErrorStatus { value }) => {
            mir_value_resolve_callee_name(*value, value_defs, depth + 1)
        }
        _ => None,
    }
}

fn mir_value_resolves_to_unknown_nominal_call(
    value_id: MirValueId,
    value_defs: &BTreeMap<MirValueId, MirValue>,
    symbols_by_name: &BTreeMap<String, FuncId>,
    returns_unknown_nominal_by_id: &BTreeMap<u32, bool>,
    depth: usize,
) -> bool {
    if depth > 32 {
        return false;
    }
    match value_defs.get(&value_id) {
        Some(MirValue::Call { callee, .. }) => {
            let Some(name) = mir_value_resolve_callee_name(*callee, value_defs, depth + 1) else {
                return false;
            };
            let Some(func_id) = symbols_by_name.get(&name) else {
                return false;
            };
            returns_unknown_nominal_by_id
                .get(&func_id.as_u32())
                .copied()
                .unwrap_or(false)
        }
        Some(MirValue::LocalSet { value, .. })
        | Some(MirValue::Assign { value, .. })
        | Some(MirValue::Unary { operand: value, .. })
        | Some(MirValue::Cast { value, .. })
        | Some(MirValue::ErrorPayload { value })
        | Some(MirValue::ErrorStatus { value }) => mir_value_resolves_to_unknown_nominal_call(
            *value,
            value_defs,
            symbols_by_name,
            returns_unknown_nominal_by_id,
            depth + 1,
        ),
        _ => false,
    }
}

fn value_is_definitely_zero(builder: &FunctionBuilder, value: Value, depth: usize) -> bool {
    if depth > 32 {
        return false;
    }
    match builder.func.dfg.value_def(value) {
        ValueDef::Result(inst, _) => match &builder.func.dfg.insts[inst] {
            InstructionData::UnaryImm { opcode, imm } => {
                *opcode == Opcode::Iconst && imm.bits() == 0
            }
            InstructionData::Unary { opcode, arg } => {
                matches!(*opcode, Opcode::Sextend | Opcode::Uextend | Opcode::Ireduce)
                    && value_is_definitely_zero(builder, *arg, depth + 1)
            }
            _ => false,
        },
        ValueDef::Union(left, right) => {
            value_is_definitely_zero(builder, left, depth + 1)
                && value_is_definitely_zero(builder, right, depth + 1)
        }
        ValueDef::Param(_, _) => false,
    }
}

fn align_to(value: u32, align: u32) -> u32 {
    let mask = align.saturating_sub(1);
    if value & mask == 0 {
        value
    } else {
        (value + mask) & !mask
    }
}

fn bool_to_int(builder: &mut FunctionBuilder, int_type: Type, condition: Value) -> Value {
    let cond_type = builder.func.dfg.value_type(condition);
    if cond_type == int_type {
        return condition;
    }
    if cond_type.is_int() {
        return cast_int(builder, condition, int_type, false);
    }
    builder.ins().uextend(int_type, condition)
}

fn cast_int(builder: &mut FunctionBuilder, value: Value, target_type: Type, signed: bool) -> Value {
    let source_type = builder.func.dfg.value_type(value);
    if source_type == target_type {
        value
    } else if source_type.bits() > target_type.bits() {
        builder.ins().ireduce(target_type, value)
    } else if signed {
        builder.ins().sextend(target_type, value)
    } else {
        builder.ins().uextend(target_type, value)
    }
}

fn canonicalize_int_value(
    builder: &mut FunctionBuilder,
    value: Value,
    signed: bool,
    bits: u16,
    carrier_ty: Type,
) -> Value {
    let source_ty = builder.func.dfg.value_type(value);
    let casted = if source_ty == carrier_ty {
        value
    } else {
        cast_int(builder, value, carrier_ty, signed)
    };

    if bits == 0 {
        return zero_for_type(builder, carrier_ty);
    }
    let carrier_bits = carrier_ty.bits() as u16;
    if bits >= carrier_bits {
        return casted;
    }

    if signed {
        let shift = i64::from(carrier_bits - bits);
        let shifted = builder.ins().ishl_imm(casted, shift);
        builder.ins().sshr_imm(shifted, shift)
    } else {
        let shift = i64::from(carrier_bits - bits);
        let shifted = builder.ins().ishl_imm(casted, shift);
        builder.ins().ushr_imm(shifted, shift)
    }
}

fn canonicalize_lowered_value_for_type(
    builder: &mut FunctionBuilder,
    lowered: LoweredValue,
    value_ty: &MirValueType,
    scalar: ScalarType,
) -> LoweredValue {
    if let LoweredValue::ErrorableScalar {
        status,
        payload,
        payload_is_float,
    } = lowered
    {
        let canonical_payload = canonicalize_lowered_value_for_type(
            builder,
            if payload_is_float {
                LoweredValue::Float(payload)
            } else {
                LoweredValue::Int(payload)
            },
            value_ty,
            scalar,
        );
        return match canonical_payload {
            LoweredValue::Float(payload) => LoweredValue::ErrorableScalar {
                status,
                payload,
                payload_is_float: true,
            },
            LoweredValue::Int(payload) => LoweredValue::ErrorableScalar {
                status,
                payload,
                payload_is_float: false,
            },
            other => {
                let payload = other
                    .as_value()
                    .unwrap_or_else(|| zero_for_type(builder, scalar.ty()));
                LoweredValue::ErrorableScalar {
                    status,
                    payload,
                    payload_is_float: builder.func.dfg.value_type(payload).is_float(),
                }
            }
        };
    }

    match value_ty {
        MirValueType::Int { signed, bits } => {
            if matches!(*bits, 8 | 16 | 32 | 64) {
                return lowered;
            }
            let Some(raw) = lowered.as_int() else {
                return lowered;
            };
            let carrier_ty = int_carrier_type_for_bits(*bits);
            let canonical = canonicalize_int_value(builder, raw, *signed, *bits, carrier_ty);
            LoweredValue::Int(canonical)
        }
        MirValueType::Bool => {
            let Some(raw) = lowered.as_int() else {
                return lowered;
            };
            let bool_ty = bool_storage_type(scalar);
            let int_value = cast_int(builder, raw, bool_ty, false);
            let cmp = builder.ins().icmp_imm(IntCC::NotEqual, int_value, 0);
            LoweredValue::Int(bool_to_int(builder, bool_ty, cmp))
        }
        _ => lowered,
    }
}

fn parse_return_scalar(return_type: Option<&str>) -> ScalarType {
    let ty_text = normalized_return_type_hint(return_type);
    let ty = ty_text.as_str();
    if ty.starts_with("fn/")
        || ty.starts_with("fn(")
        || (ty.starts_with('(') && ty.contains(")->"))
        || ty == "fn"
    {
        return ScalarType::Int {
            ty: I64,
            signed: false,
        };
    }
    if let Some(bits) = parse_scalar_enum_repr_bits(ty) {
        return ScalarType::Int {
            ty: int_carrier_type_for_bits(bits),
            signed: false,
        };
    }
    if ty.starts_with('*') || ty.starts_with("[]") || ty == "opaque" || ty == "any" {
        return ScalarType::Int {
            ty: I64,
            signed: false,
        };
    }

    if ty == "u1" {
        return ScalarType::Int {
            ty: I8,
            signed: false,
        };
    }
    if ty == "type" {
        return ScalarType::Int {
            ty: I64,
            signed: false,
        };
    }
    if let Some((signed, bits)) = parse_int_type_bits(ty) {
        return ScalarType::Int {
            ty: int_carrier_type_for_bits(bits),
            signed,
        };
    }
    if let Some(bits) = parse_float_type_bits(ty) {
        if bits == 128 {
            return ScalarType::Int {
                ty: I64,
                signed: false,
            };
        }
        return ScalarType::Float {
            ty: float_carrier_type_for_bits(bits),
        };
    }

    ScalarType::Int {
        ty: I32,
        signed: true,
    }
}

fn mir_type_to_clif(ty: &MirValueType, fallback: ScalarType) -> Type {
    match ty {
        MirValueType::Int { bits, .. } => int_carrier_type_for_bits(*bits),
        MirValueType::Float { bits } => float_carrier_type_for_bits(*bits),
        MirValueType::Bool => bool_storage_type(fallback),
        MirValueType::BytesSlice => I64,
        MirValueType::Type => I64,
        MirValueType::Function | MirValueType::FunctionPointer => fallback.ty(),
        MirValueType::Unknown => I64,
        MirValueType::Closure => fallback.ty(),
    }
}

fn bool_storage_type(fallback: ScalarType) -> Type {
    match fallback {
        ScalarType::Float { .. } => I32,
        ScalarType::Int { ty, .. } => ty,
    }
}

fn zero_for_type(builder: &mut FunctionBuilder, ty: Type) -> Value {
    if ty == F32 {
        builder
            .ins()
            .f32const(cranelift_codegen::ir::immediates::Ieee32::with_bits(0))
    } else if ty == F64 {
        builder
            .ins()
            .f64const(cranelift_codegen::ir::immediates::Ieee64::with_bits(0))
    } else if ty == F128 {
        let constant =
            builder
                .func
                .dfg
                .constants
                .insert(cranelift_codegen::ir::ConstantData::from(
                    cranelift_codegen::ir::immediates::Ieee128::with_bits(0),
                ));
        builder.ins().f128const(constant)
    } else {
        builder.ins().iconst(ty, 0)
    }
}

fn zero_for_scalar(builder: &mut FunctionBuilder, scalar: ScalarType) -> Value {
    zero_for_type(builder, scalar.ty())
}

fn cast_scalar(
    builder: &mut FunctionBuilder,
    value: Value,
    target_type: Type,
    scalar: ScalarType,
) -> Value {
    let source = builder.func.dfg.value_type(value);
    if source == target_type {
        return value;
    }
    if source.is_int() && target_type.is_int() {
        let signed = matches!(scalar, ScalarType::Int { signed: true, .. });
        return cast_int(builder, value, target_type, signed);
    }
    if source.is_int() && target_type.is_float() {
        return match scalar {
            ScalarType::Int { signed: true, .. } => {
                builder.ins().fcvt_from_sint(target_type, value)
            }
            ScalarType::Int { signed: false, .. } => {
                builder.ins().fcvt_from_uint(target_type, value)
            }
            ScalarType::Float { .. } => builder.ins().fcvt_from_sint(target_type, value),
        };
    }
    if source.is_float() && target_type.is_int() {
        return match scalar {
            ScalarType::Int { signed: true, .. } => {
                builder.ins().fcvt_to_sint_sat(target_type, value)
            }
            ScalarType::Int { signed: false, .. } => {
                builder.ins().fcvt_to_uint_sat(target_type, value)
            }
            ScalarType::Float { .. } => builder.ins().fcvt_to_sint_sat(target_type, value),
        };
    }
    if source.is_float() && target_type.is_float() {
        if source.bits() > target_type.bits() {
            return builder.ins().fdemote(target_type, value);
        }
        return builder.ins().fpromote(target_type, value);
    }
    value
}
