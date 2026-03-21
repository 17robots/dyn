use std::collections::{BTreeMap, BTreeSet};

use crate::compiler::diagnostics::{Diagnostic, DiagnosticCode, DiagnosticPhase};
use crate::compiler::mir::{
    MirInstr, MirProgram, MirTerminator, MirValue, MirValueId, MirValueType,
};

pub fn verify_mir_program(program: &MirProgram) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();

    for module in &program.modules {
        for function in &module.functions {
            if function.blocks.is_empty() {
                diagnostics.push(Diagnostic::error(
                    DiagnosticPhase::Mir,
                    DiagnosticCode::E5001,
                    format!("MIR function '{}' has no basic blocks", function.name),
                ));
                continue;
            }

            if function.entry.0 >= function.blocks.len() {
                diagnostics.push(Diagnostic::error(
                    DiagnosticPhase::Mir,
                    DiagnosticCode::E5001,
                    format!(
                        "MIR function '{}' has an invalid entry block",
                        function.name
                    ),
                ));
            }

            let mut predecessors: BTreeMap<usize, BTreeSet<usize>> = BTreeMap::new();
            for block in &function.blocks {
                let Some(terminator) = &block.terminator else {
                    diagnostics.push(Diagnostic::error(
                        DiagnosticPhase::Mir,
                        DiagnosticCode::E5001,
                        format!(
                            "MIR function '{}' has an unterminated block #{}",
                            function.name, block.id.0
                        ),
                    ));
                    continue;
                };

                match terminator {
                    MirTerminator::Goto(target) => {
                        if target.0 >= function.blocks.len() {
                            diagnostics.push(Diagnostic::error(
                                DiagnosticPhase::Mir,
                                DiagnosticCode::E5001,
                                format!(
                                    "MIR function '{}' has goto to invalid block #{}",
                                    function.name, target.0
                                ),
                            ));
                        } else {
                            predecessors.entry(target.0).or_default().insert(block.id.0);
                        }
                    }
                    MirTerminator::Branch {
                        then_block,
                        else_block,
                        ..
                    } => {
                        if then_block.0 >= function.blocks.len() {
                            diagnostics.push(Diagnostic::error(
                                DiagnosticPhase::Mir,
                                DiagnosticCode::E5001,
                                format!(
                                    "MIR function '{}' has branch to invalid then block #{}",
                                    function.name, then_block.0
                                ),
                            ));
                        } else {
                            predecessors
                                .entry(then_block.0)
                                .or_default()
                                .insert(block.id.0);
                        }

                        if else_block.0 >= function.blocks.len() {
                            diagnostics.push(Diagnostic::error(
                                DiagnosticPhase::Mir,
                                DiagnosticCode::E5001,
                                format!(
                                    "MIR function '{}' has branch to invalid else block #{}",
                                    function.name, else_block.0
                                ),
                            ));
                        } else {
                            predecessors
                                .entry(else_block.0)
                                .or_default()
                                .insert(block.id.0);
                        }
                    }
                    MirTerminator::Return(_) | MirTerminator::Unreachable => {}
                }
            }

            let mut value_types = BTreeMap::<MirValueId, MirValueType>::new();
            for (block_idx, block) in function.blocks.iter().enumerate() {
                if block.id.0 != block_idx {
                    diagnostics.push(Diagnostic::error(
                        DiagnosticPhase::Mir,
                        DiagnosticCode::E5001,
                        format!(
                            "MIR function '{}' has mismatched block id #{} at index #{}",
                            function.name, block.id.0, block_idx
                        ),
                    ));
                }

                let mut saw_non_phi = false;
                for instruction in &block.instructions {
                    match instruction {
                        MirInstr::Eval { dest, value, ty } => {
                            saw_non_phi = true;
                            if value_types.insert(*dest, ty.clone()).is_some() {
                                diagnostics.push(Diagnostic::error(
                                    DiagnosticPhase::Mir,
                                    DiagnosticCode::E5003,
                                    format!(
                                        "MIR function '{}' redefines value id #{}",
                                        function.name, dest.0
                                    ),
                                ));
                            }
                            let _ = value;
                        }
                        MirInstr::Phi { dest, sources, ty } => {
                            if saw_non_phi {
                                diagnostics.push(Diagnostic::error(
                                    DiagnosticPhase::Mir,
                                    DiagnosticCode::E5003,
                                    format!(
                                        "MIR function '{}' has phi after non-phi in block #{}",
                                        function.name, block.id.0
                                    ),
                                ));
                            }
                            if sources.is_empty() {
                                diagnostics.push(Diagnostic::error(
                                    DiagnosticPhase::Mir,
                                    DiagnosticCode::E5001,
                                    format!(
                                        "MIR function '{}' has phi in block #{} with no sources",
                                        function.name, block.id.0
                                    ),
                                ));
                            }
                            let preds = predecessors.get(&block.id.0).cloned().unwrap_or_default();
                            for (pred, _source_value) in sources {
                                if pred.0 >= function.blocks.len() {
                                    diagnostics.push(Diagnostic::error(
                                        DiagnosticPhase::Mir,
                                        DiagnosticCode::E5003,
                                        format!(
                                            "MIR function '{}' has phi in block #{} with invalid predecessor #{}",
                                            function.name, block.id.0, pred.0
                                        ),
                                    ));
                                } else if !preds.contains(&pred.0) {
                                    diagnostics.push(Diagnostic::error(
                                        DiagnosticPhase::Mir,
                                        DiagnosticCode::E5003,
                                        format!(
                                            "MIR function '{}' has phi in block #{} with non-predecessor source block #{}",
                                            function.name, block.id.0, pred.0
                                        ),
                                    ));
                                }
                            }

                            if value_types.insert(*dest, ty.clone()).is_some() {
                                diagnostics.push(Diagnostic::error(
                                    DiagnosticPhase::Mir,
                                    DiagnosticCode::E5003,
                                    format!(
                                        "MIR function '{}' redefines value id #{}",
                                        function.name, dest.0
                                    ),
                                ));
                            }
                        }
                    }
                }
            }

            for block in &function.blocks {
                for instruction in &block.instructions {
                    match instruction {
                        MirInstr::Eval { value, .. } => {
                            verify_eval_operands(
                                &function.name,
                                value,
                                &value_types,
                                &mut diagnostics,
                            );
                        }
                        MirInstr::Phi { sources, ty, .. } => {
                            for (_pred, source_value) in sources {
                                match value_types.get(source_value) {
                                    Some(source_ty) if !types_compatible(ty, source_ty) => {
                                        diagnostics.push(Diagnostic::error(
                                            DiagnosticPhase::Mir,
                                            DiagnosticCode::E5003,
                                            format!(
                                                "MIR function '{}' has phi with incompatible source type for value #{}",
                                                function.name, source_value.0
                                            ),
                                        ));
                                    }
                                    Some(_) => {}
                                    None => {
                                        diagnostics.push(Diagnostic::error(
                                            DiagnosticPhase::Mir,
                                            DiagnosticCode::E5003,
                                            format!(
                                                "MIR function '{}' has phi referencing undefined value #{}",
                                                function.name, source_value.0
                                            ),
                                        ));
                                    }
                                }
                            }
                        }
                    }
                }

                if let Some(terminator) = &block.terminator {
                    match terminator {
                        MirTerminator::Return(Some(value)) => {
                            if !value_types.contains_key(value) {
                                diagnostics.push(Diagnostic::error(
                                    DiagnosticPhase::Mir,
                                    DiagnosticCode::E5003,
                                    format!(
                                        "MIR function '{}' returns undefined value #{} in block #{}",
                                        function.name, value.0, block.id.0
                                    ),
                                ));
                            }
                        }
                        MirTerminator::Branch { condition, .. } => match value_types.get(condition)
                        {
                            Some(MirValueType::Bool)
                            | Some(MirValueType::Int { .. })
                            | Some(MirValueType::BytesSlice) => {}
                            Some(_) => diagnostics.push(Diagnostic::error(
                                DiagnosticPhase::Mir,
                                DiagnosticCode::E5003,
                                format!(
                                    "MIR function '{}' has non-scalar branch condition value #{} in block #{}",
                                    function.name, condition.0, block.id.0
                                ),
                            )),
                            None => diagnostics.push(Diagnostic::error(
                                DiagnosticPhase::Mir,
                                DiagnosticCode::E5003,
                                format!(
                                    "MIR function '{}' has branch on undefined value #{} in block #{}",
                                    function.name, condition.0, block.id.0
                                ),
                            )),
                        },
                        MirTerminator::Return(None)
                        | MirTerminator::Goto(_)
                        | MirTerminator::Unreachable => {}
                    }
                }
            }
        }
    }

    diagnostics
}

fn verify_eval_operands(
    function_name: &str,
    value: &MirValue,
    value_types: &BTreeMap<MirValueId, MirValueType>,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let mut check_value = |id: MirValueId, what: &str| {
        if !value_types.contains_key(&id) {
            diagnostics.push(Diagnostic::error(
                DiagnosticPhase::Mir,
                DiagnosticCode::E5003,
                format!(
                    "MIR function '{}' references undefined {} value #{}",
                    function_name, what, id.0
                ),
            ));
        }
    };

    match value {
        MirValue::Literal(_) | MirValue::Ident(_) | MirValue::Param { .. } | MirValue::Unknown => {}
        MirValue::Unary { operand, .. } => check_value(*operand, "unary operand"),
        MirValue::Cast { value, .. } => check_value(*value, "cast source"),
        MirValue::Binary { left, right, .. } => {
            check_value(*left, "binary left operand");
            check_value(*right, "binary right operand");
        }
        MirValue::Assign { target, value, .. } => {
            check_value(*target, "assignment target");
            check_value(*value, "assignment value");
        }
        MirValue::LocalSet { value, .. } => check_value(*value, "local set value"),
        MirValue::Call { callee, args } => {
            check_value(*callee, "call callee");
            for arg in args {
                check_value(*arg, "call argument");
            }
        }
        MirValue::ErrorStatus { value } => check_value(*value, "error status source"),
        MirValue::ErrorPayload { value } => check_value(*value, "error payload source"),
        MirValue::DerefAccess { base } => check_value(*base, "deref base"),
        MirValue::FieldAccess { base, .. } => check_value(*base, "field access base"),
        MirValue::Index { base, index } => {
            check_value(*base, "index base");
            check_value(*index, "index value");
        }
        MirValue::Slice {
            base, start, end, ..
        } => {
            check_value(*base, "slice base");
            if let Some(start) = start {
                check_value(*start, "slice start");
            }
            if let Some(end) = end {
                check_value(*end, "slice end");
            }
        }
        MirValue::StructLiteral { fields } => {
            for (_, value) in fields {
                check_value(*value, "struct field value");
            }
        }
        MirValue::EnumVariant { payload, .. } => {
            for value in payload {
                check_value(*value, "enum payload value");
            }
        }
        MirValue::Use { .. } | MirValue::TypeLiteral(_) => {}
    }
}

fn types_compatible(expected: &MirValueType, actual: &MirValueType) -> bool {
    expected == actual
        || matches!(expected, MirValueType::Unknown)
        || matches!(actual, MirValueType::Unknown)
        || matches!(
            (expected, actual),
            (MirValueType::Int { .. }, MirValueType::Int { .. })
                | (MirValueType::Float { .. }, MirValueType::Float { .. })
                | (MirValueType::Bool, MirValueType::Int { .. })
                | (MirValueType::Int { .. }, MirValueType::Bool)
                | (MirValueType::BytesSlice, MirValueType::BytesSlice)
                | (MirValueType::BytesSlice, MirValueType::Int { .. })
                | (MirValueType::Int { .. }, MirValueType::BytesSlice)
                | (MirValueType::FunctionPointer, MirValueType::Function)
                | (MirValueType::Function, MirValueType::FunctionPointer)
                | (MirValueType::FunctionPointer, MirValueType::Int { .. })
                | (MirValueType::Int { .. }, MirValueType::FunctionPointer)
        )
}

#[cfg(test)]
mod tests;
