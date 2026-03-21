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
fn infers_index_and_slice_types_for_bytes_slice_values() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  b: []u8 = \"abcd\"\n  _x := b[1]\n  _s := b[1..3]\n  return 0\n}\n",
    )
    .expect("file should be written");

    let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
    let inferred = infer_binding_type_strings(&units);
    let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
    let mir = lower_hir_to_mir(&hir);
    let main_module = mir
        .modules
        .iter()
        .find(|module| module.key.module_name == "main")
        .expect("main module should exist");
    let function = main_module
        .functions
        .iter()
        .find(|function| function.name == "main")
        .expect("main function should exist");

    let mut saw_index_u8 = false;
    let mut saw_slice_bytes = false;
    for block in &function.blocks {
        for instr in &block.instructions {
            if let MirInstr::Eval { value, ty, .. } = instr {
                match value {
                    MirValue::Index { .. } => {
                        if matches!(
                            ty,
                            MirValueType::Int {
                                signed: false,
                                bits: 8
                            }
                        ) {
                            saw_index_u8 = true;
                        }
                    }
                    MirValue::Slice { .. } => {
                        if matches!(ty, MirValueType::BytesSlice) {
                            saw_slice_bytes = true;
                        }
                    }
                    _ => {}
                }
            }
        }
    }

    assert!(
        saw_index_u8,
        "expected bytes index result type to be u8-like"
    );
    assert!(
        saw_slice_bytes,
        "expected bytes slice result type to be []u8"
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
            extern_functions: Vec::new(),
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
                        has_explicit_return_type: true,
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
                    ty: MirValueType::FunctionPointer,
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
            extern_functions: Vec::new(),
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
                        has_explicit_return_type: true,
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
            extern_functions: Vec::new(),
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
                        has_explicit_return_type: true,
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
            extern_functions: Vec::new(),
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
                        has_explicit_return_type: true,
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
                                                kind: HirExprKind::Literal(HirLiteral::Integer(
                                                    "9".to_string(),
                                                )),
                                            }),
                                        },
                                    },
                                    HirExpr {
                                        span,
                                        kind: HirExprKind::Return {
                                            value: Some(Box::new(HirExpr {
                                                span,
                                                kind: HirExprKind::Literal(HirLiteral::Integer(
                                                    "1".to_string(),
                                                )),
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
            extern_functions: Vec::new(),
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
                        has_explicit_return_type: true,
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
            extern_functions: Vec::new(),
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
                        has_explicit_return_type: true,
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
            extern_functions: Vec::new(),
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
                        has_explicit_return_type: true,
                        body: Box::new(HirExpr {
                            span,
                            kind: HirExprKind::Index {
                                base: Box::new(HirExpr {
                                    span,
                                    kind: HirExprKind::EnumVariant {
                                        root: None,
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
            extern_functions: Vec::new(),
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
                        has_explicit_return_type: true,
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
fn infers_mir_types_for_string_and_null_literals() {
    assert_eq!(
        literal_type(&HirLiteral::String("\"hi\"".to_string())),
        MirValueType::BytesSlice
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
fn parses_slice_and_opaque_type_hints() {
    assert_eq!(parse_type_hint("[]u8"), MirValueType::BytesSlice);
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

#[test]
fn lowers_f128_function_parameters_and_binary_values_as_float() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nadd := (lhs: f128, rhs: f128) f128 { return lhs + rhs }\nmain := () i32 {\n  a := $as(f128, 1.5)\n  b := $as(f128, 2.25)\n  c := add(a, b)\n  if c > $as(f128, 3.7) return 7 else return 1\n}\n",
    )
    .expect("file should be written");

    let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
    let inferred = infer_binding_type_strings(&units);
    let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
    let hir_main = hir
        .modules
        .iter()
        .find(|module| module.key.module_name == "main")
        .expect("main HIR module should exist");
    let add_item = hir_main
        .items
        .iter()
        .find(|item| item.name == "add")
        .expect("add HIR item should exist");
    let add_type_info = format!(
        "add HIR inferred={:?} hint={:?}",
        add_item.inferred_type, add_item.type_hint
    );
    let mir = lower_hir_to_mir(&hir);
    let main_module = mir
        .modules
        .iter()
        .find(|module| module.key.module_name == "main")
        .expect("main module should exist");
    let add_fn = main_module
        .functions
        .iter()
        .find(|function| function.name == "add")
        .expect("add function should exist");
    let main_fn = main_module
        .functions
        .iter()
        .find(|function| function.name == "main")
        .expect("main function should exist");

    assert_eq!(
        add_fn.param_types,
        vec![
            MirValueType::Float { bits: 128 },
            MirValueType::Float { bits: 128 }
        ]
    );
    assert!(add_fn
        .blocks
        .iter()
        .any(|block| block.instructions.iter().any(|instr| matches!(
            instr,
            MirInstr::Eval {
                value: MirValue::Binary {
                    op: crate::compiler::ast::BinaryOp::Add,
                    ..
                },
                ty: MirValueType::Float { bits: 128 },
                ..
            }
        ))));
    let call_types = main_fn
        .blocks
        .iter()
        .flat_map(|block| block.instructions.iter())
        .filter_map(|instr| match instr {
            MirInstr::Eval {
                value: MirValue::Call { .. },
                ty,
                ..
            } => Some(ty.clone()),
            _ => None,
        })
        .collect::<Vec<_>>();
    assert!(
        call_types.contains(&MirValueType::Float { bits: 128 }),
        "{add_type_info}; call types: {call_types:#?}"
    );

    fs::remove_dir_all(root).expect("temp directory should be removed");
}
