use super::*;
use crate::compiler::mir::{MirBasicBlock, MirBlockId, MirFunction, MirModule, MirValueId};
use std::path::PathBuf;

#[test]
fn reports_unterminated_block() {
    let program = MirProgram {
        modules: vec![MirModule {
            module_id: crate::compiler::module_resolver::ModuleId(0),
            key: crate::compiler::module_resolver::ModuleKey {
                directory: PathBuf::from("."),
                module_name: "main".to_string(),
            },
            functions: vec![MirFunction {
                name: "f".to_string(),
                def_id: None,
                return_type: None,
                param_type_hints: Vec::new(),
                param_types: Vec::new(),
                entry: MirBlockId(0),
                blocks: vec![MirBasicBlock {
                    id: MirBlockId(0),
                    instructions: Vec::new(),
                    terminator: None,
                }],
            }],
        }],
    };

    let diagnostics = verify_mir_program(&program);
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E5001));
}

#[test]
fn reports_invalid_phi_source_and_undefined_return_value() {
    let program = MirProgram {
        modules: vec![MirModule {
            module_id: crate::compiler::module_resolver::ModuleId(0),
            key: crate::compiler::module_resolver::ModuleKey {
                directory: PathBuf::from("."),
                module_name: "main".to_string(),
            },
            functions: vec![MirFunction {
                name: "f".to_string(),
                def_id: None,
                return_type: None,
                param_type_hints: Vec::new(),
                param_types: Vec::new(),
                entry: MirBlockId(0),
                blocks: vec![
                    MirBasicBlock {
                        id: MirBlockId(0),
                        instructions: vec![MirInstr::Phi {
                            dest: MirValueId(0),
                            sources: vec![(MirBlockId(1), MirValueId(99))],
                            ty: MirValueType::Int {
                                signed: true,
                                bits: 32,
                            },
                        }],
                        terminator: Some(MirTerminator::Return(Some(MirValueId(5)))),
                    },
                    MirBasicBlock {
                        id: MirBlockId(1),
                        instructions: Vec::new(),
                        terminator: Some(MirTerminator::Goto(MirBlockId(0))),
                    },
                ],
            }],
        }],
    };

    let diagnostics = verify_mir_program(&program);
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E5003));
}

#[test]
fn reports_phi_after_non_phi() {
    let program = MirProgram {
        modules: vec![MirModule {
            module_id: crate::compiler::module_resolver::ModuleId(0),
            key: crate::compiler::module_resolver::ModuleKey {
                directory: PathBuf::from("."),
                module_name: "main".to_string(),
            },
            functions: vec![MirFunction {
                name: "f".to_string(),
                def_id: None,
                return_type: None,
                param_type_hints: Vec::new(),
                param_types: Vec::new(),
                entry: MirBlockId(0),
                blocks: vec![MirBasicBlock {
                    id: MirBlockId(0),
                    instructions: vec![
                        MirInstr::Eval {
                            dest: MirValueId(0),
                            value: MirValue::Literal(crate::compiler::hir::HirLiteral::Integer(
                                "1".to_string(),
                            )),
                            ty: MirValueType::Int {
                                signed: true,
                                bits: 32,
                            },
                        },
                        MirInstr::Phi {
                            dest: MirValueId(1),
                            sources: vec![(MirBlockId(0), MirValueId(0))],
                            ty: MirValueType::Int {
                                signed: true,
                                bits: 32,
                            },
                        },
                    ],
                    terminator: Some(MirTerminator::Return(Some(MirValueId(1)))),
                }],
            }],
        }],
    };

    let diagnostics = verify_mir_program(&program);
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E5003));
}

#[test]
fn treats_numeric_width_and_bool_int_phi_types_as_compatible() {
    assert!(types_compatible(
        &MirValueType::Int {
            signed: true,
            bits: 32,
        },
        &MirValueType::Int {
            signed: false,
            bits: 64,
        }
    ));
    assert!(types_compatible(
        &MirValueType::Bool,
        &MirValueType::Int {
            signed: false,
            bits: 8,
        }
    ));
    assert!(types_compatible(
        &MirValueType::Float { bits: 32 },
        &MirValueType::Float { bits: 64 }
    ));
}
