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
            lower_binary_value(value_ty, op, left, right, builder, module, data, left_operand_ty)
        }
        MirValue::Assign { value, .. } => lowered
            .get(value)
            .cloned()
            .unwrap_or_else(|| zero_lowered_for_type(builder, value_ty, scalar)),
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
        UnaryOp::Ref => match operand_value {
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
                (UnaryOp::Ref, MirValueType::Float { .. }) => LoweredValue::Float(operand),
                (UnaryOp::Ref, _) => LoweredValue::Int(operand),
            }
        }
    }
}

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

    lower_int_binary_value(value_ty, op, builder, scalar, left_val, right_val, left_operand_ty)
}

fn lower_float_binary_value(
    value_ty: &MirValueType,
    op: &BinaryOp,
    builder: &mut FunctionBuilder,
    operands: BinaryOperandsRef<'_>,
    float_ty_hint: Option<Type>,
    module: &mut ObjectModule,
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
    module: &mut ObjectModule,
    data: LowerValueData<'_>,
) -> LoweredValue {
    let scalar = data.scalar;
    let Some(source) = data.lowered.get(value).cloned() else {
        return zero_lowered_for_type(builder, value_ty, scalar);
    };
    if matches!(target, MirValueType::Unknown) {
        return source;
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
    if let Some(start_value) = start.and_then(|id| lowered.get(&id).and_then(LoweredValue::as_int))
    {
        base_addr =
            add_scaled_index_to_base(builder, scalar, pointer_ty, base_addr, start_value, stride);
    }
    LoweredValue::PointerSlice {
        base_addr,
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

    // Handle fat pointer (closure) calls specially
    if let Some(LoweredValue::FatPtr { fn_ptr, env_ptr }) = lowered.get(call.callee).cloned() {
        let Some(arg_vals) =
            marshal_call_arg_values(call.args, builder, lowered, module)
        else {
            return zero_lowered_for_type(builder, value_ty, scalar);
        };
        // Prepend env_ptr to args
        let mut call_args = vec![env_ptr];
        call_args.extend(arg_vals.iter().copied());

        // Build signature: (env_ptr, ...args...) -> ret
        let mut sig = module.make_signature();
        sig.params.push(cranelift_codegen::ir::AbiParam::new(pointer_ty));
        for &av in &arg_vals {
            sig.params
                .push(cranelift_codegen::ir::AbiParam::new(builder.func.dfg.value_type(av)));
        }
        let return_ty = indirect_call_return_type(value_ty, scalar, pointer_ty, &CallReturnProfile {
            returns_bytes_slice: false,
            returns_aggregate: None,
            returns_errorable: false,
            returns_errorable_scalar: false,
            errorable_scalar_payload_ty: None,
        });
        sig.returns
            .push(cranelift_codegen::ir::AbiParam::new(return_ty));
        let sig_ref = builder.import_signature(sig);
        let inst = builder.ins().call_indirect(sig_ref, fn_ptr, &call_args);
        let ret = builder
            .inst_results(inst)
            .first()
            .copied()
            .unwrap_or_else(|| zero_for_type(builder, return_ty));
        return LoweredValue::from_typed_value(ret, value_ty);
    }

    let Some(mut arg_vals) = marshal_call_arg_values(call.args, builder, lowered, module) else {
        return zero_lowered_for_type(builder, value_ty, scalar);
    };

    let direct_callee = match lowered.get(call.callee) {
        Some(LoweredValue::FunctionSymbol(func_id)) => Some(*func_id),
        _ => None,
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

fn marshal_call_arg_values(
    args: &[MirValueId],
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    module: &mut ObjectModule,
) -> Option<Vec<Value>> {
    let pointer_ty = module.target_config().pointer_type();
    let mut arg_vals = Vec::with_capacity(args.len().saturating_mul(2).saturating_add(1));
    for arg in args {
        match lowered.get(arg).cloned() {
            Some(LoweredValue::FunctionSymbol(func_id)) => {
                let func_ref = module.declare_func_in_func(func_id, builder.func);
                arg_vals.push(builder.ins().func_addr(pointer_ty, func_ref));
            }
            Some(LoweredValue::StructMemory { slot, .. }) => {
                arg_vals.push(builder.ins().stack_addr(pointer_ty, slot, 0));
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
            }
            Some(LoweredValue::Struct(fields)) => {
                let lowered_pairs = fields.into_iter().collect::<Vec<_>>();
                let materialized = materialize_struct_memory(builder, module, &lowered_pairs)?;
                match materialized {
                    LoweredValue::StructMemory { slot, .. } => {
                        arg_vals.push(builder.ins().stack_addr(pointer_ty, slot, 0));
                    }
                    _ => return None,
                }
            }
            Some(LoweredValue::BytesSlice { ptr, len }) => {
                arg_vals.push(ptr);
                arg_vals.push(len);
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
            }
            Some(other) => arg_vals.push(other.as_value()?),
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
    let payload_mir_ty = if matches!(value_ty, MirValueType::Unknown) {
        profile
            .errorable_scalar_payload_ty
            .as_ref()
            .unwrap_or(value_ty)
    } else {
        value_ty
    };

    if profile.returns_bytes_slice {
        let len = out_args
            .ret_len_slot
            .map(|slot| builder.ins().stack_load(pointer_ty, slot, 0))
            .unwrap_or_else(|| zero_for_type(builder, pointer_ty));
        return LoweredValue::BytesSlice {
            ptr: cast_scalar(builder, ret, pointer_ty, scalar),
            len,
        };
    }

    if let (Some(layout), Some(slot)) = (profile.returns_aggregate, out_args.aggregate_out_slot) {
        let addr = builder.ins().stack_addr(pointer_ty, slot, 0);
        return LoweredValue::StructPointer {
            addr,
            stack_slot: Some(slot),
            stack_offset: 0,
            status: if profile.returns_errorable {
                Some(cast_scalar(builder, ret, scalar.ty(), scalar))
            } else {
                None
            },
            fields: layout.fields,
            aggregate_fields: layout.aggregate_fields,
            ordered: layout.ordered,
            scalar_leaves: layout.scalar_leaves,
            size: layout.size,
            align: layout.align,
        };
    }

    if profile.returns_errorable_scalar {
        let (payload, payload_ty) = if let Some((slot, payload_ty)) = out_args.errorable_scalar_out
        {
            (builder.ins().stack_load(payload_ty, slot, 0), payload_ty)
        } else {
            let ty = if matches!(payload_mir_ty, MirValueType::Unknown) {
                scalar.ty()
            } else {
                mir_type_to_clif(payload_mir_ty, scalar)
            };
            (zero_for_type(builder, ty), ty)
        };
        return LoweredValue::ErrorableScalar {
            status: cast_scalar(builder, ret, scalar.ty(), scalar),
            payload,
            payload_is_float: payload_ty.is_float(),
        };
    }

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
    symbols_by_name: &BTreeMap<String, FuncId>,
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
    Some((signed, bits))
}

fn parse_float_type_bits(type_name: &str) -> Option<u16> {
    let bits = type_name.strip_prefix('f')?;
    if bits.is_empty() {
        return None;
    }
    bits.parse::<u16>().ok()
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
    if ty.starts_with("fn/") || ty.starts_with("fn(") || ty == "fn" {
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

    if ty == "bool" {
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
