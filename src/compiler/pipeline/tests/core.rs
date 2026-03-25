use super::*;

#[test]
fn shakes_unreachable_functions_from_main_entry() {
    let mk_fun = |name: &str, call: Option<&str>, ret: i32| MirFunction {
        name: name.to_string(),
        def_id: None,
        return_type: Some("i32".to_string()),
        param_type_hints: Vec::new(),
        param_types: Vec::new(),
        entry: MirBlockId(0),
        blocks: vec![MirBasicBlock {
            id: MirBlockId(0),
            instructions: {
                let mut out = Vec::new();
                if let Some(callee) = call {
                    out.push(MirInstr::Eval {
                        dest: crate::compiler::mir::MirValueId(0),
                        value: MirValue::Ident(callee.to_string()),
                        ty: MirValueType::Function,
                    });
                    out.push(MirInstr::Eval {
                        dest: crate::compiler::mir::MirValueId(1),
                        value: MirValue::Call {
                            callee: crate::compiler::mir::MirValueId(0),
                            args: vec![],
                        },
                        ty: MirValueType::Int {
                            signed: true,
                            bits: 32,
                        },
                    });
                }
                out.push(MirInstr::Eval {
                    dest: crate::compiler::mir::MirValueId(2),
                    value: MirValue::Literal(crate::compiler::hir::HirLiteral::Integer(
                        ret.to_string(),
                    )),
                    ty: MirValueType::Int {
                        signed: true,
                        bits: 32,
                    },
                });
                out
            },
            terminator: Some(MirTerminator::Return(Some(
                crate::compiler::mir::MirValueId(2),
            ))),
        }],
    };

    let mir = MirProgram {
        modules: vec![MirModule {
            module_id: ModuleId(0),
            key: ModuleKey {
                directory: PathBuf::from("."),
                module_name: "main".to_string(),
            },
            functions: vec![
                mk_fun("main", Some("used"), 0),
                mk_fun("used", None, 1),
                mk_fun("unused", None, 2),
            ],
            globals: Vec::new(),
            extern_functions: Vec::new(),
        }],
    };

    let shaken = shake_mir_program(&mir);
    assert_eq!(shaken.modules[0].functions.len(), 2);
    assert!(shaken.modules[0].functions.iter().any(|f| f.name == "main"));
    assert!(shaken.modules[0].functions.iter().any(|f| f.name == "used"));
    assert!(!shaken.modules[0]
        .functions
        .iter()
        .any(|f| f.name == "unused"));
}

#[test]
fn keeps_all_functions_when_indirect_call_target_unknown() {
    let mir = MirProgram {
        modules: vec![MirModule {
            module_id: ModuleId(0),
            key: ModuleKey {
                directory: PathBuf::from("."),
                module_name: "main".to_string(),
            },
            functions: vec![
                MirFunction {
                    name: "main".to_string(),
                    def_id: None,
                    return_type: Some("i32".to_string()),
                    param_type_hints: Vec::new(),
                    param_types: Vec::new(),
                    entry: MirBlockId(0),
                    blocks: vec![MirBasicBlock {
                        id: MirBlockId(0),
                        instructions: vec![
                            MirInstr::Eval {
                                dest: crate::compiler::mir::MirValueId(0),
                                value: MirValue::Param { index: 0 },
                                ty: MirValueType::Function,
                            },
                            MirInstr::Eval {
                                dest: crate::compiler::mir::MirValueId(1),
                                value: MirValue::Call {
                                    callee: crate::compiler::mir::MirValueId(0),
                                    args: vec![],
                                },
                                ty: MirValueType::Unknown,
                            },
                        ],
                        terminator: Some(MirTerminator::Return(None)),
                    }],
                },
                MirFunction {
                    name: "unused".to_string(),
                    def_id: None,
                    return_type: Some("i32".to_string()),
                    param_type_hints: Vec::new(),
                    param_types: Vec::new(),
                    entry: MirBlockId(0),
                    blocks: vec![MirBasicBlock {
                        id: MirBlockId(0),
                        instructions: vec![],
                        terminator: Some(MirTerminator::Return(None)),
                    }],
                },
            ],
            globals: Vec::new(),
            extern_functions: Vec::new(),
        }],
    };

    let shaken = shake_mir_program(&mir);
    assert_eq!(shaken.modules[0].functions.len(), 2);
}

#[test]
fn lexes_all_resolved_module_files() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\nmsg := \"ok\"\n").expect("file should be written");
    fs::write(root.join("b.dyn"), "module main\nval := 1..=2\n").expect("file should be written");

    let session = lex_project(&root).expect("pipeline should resolve modules");
    assert_eq!(session.files.len(), 2);
    assert!(session.diagnostics.is_empty());

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn aggregates_resolver_and_lexer_diagnostics() {
    let root = make_temp_dir();
    fs::write(root.join("bad_module.dyn"), "not_module main\n").expect("file should be written");
    fs::write(root.join("bad_lex.dyn"), "module x\nmsg := \"oops\n")
        .expect("file should be written");

    let session = lex_project(&root).expect("pipeline should resolve modules");
    assert!(session
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E1004));
    assert!(session
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E2002));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn parses_lexed_files_with_tolerant_parser() {
    let root = make_temp_dir();
    fs::write(root.join("good.dyn"), "module main\na := 1\n").expect("file should be written");
    fs::write(root.join("bad_parse.dyn"), "module main\na :=\n").expect("file should be written");

    let parsed = parse_project(&root).expect("project parse should run");
    assert_eq!(parsed.files.len(), 2);
    assert!(parsed.files.iter().all(|file| file.ast.is_some()));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_module_units_from_parsed_project() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\na := 1\n").expect("file should be written");
    fs::write(root.join("b.dyn"), "module main\nb := 2\n").expect("file should be written");
    fs::write(root.join("c.dyn"), "module other\nc := 3\n").expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project parse should run");
    assert_eq!(units.len(), 2);
    assert!(units
        .iter()
        .any(|unit| unit.key.module_name == "main" && unit.declarations.len() == 2));
    assert!(units
        .iter()
        .any(|unit| unit.key.module_name == "other" && unit.declarations.len() == 1));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn analyzes_project_for_duplicate_and_import_issues() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := 1\na := 2\nmod_ref := use \"missing\"\n",
    )
    .expect("file should be written");

    let (_parsed, _units, sema) = analyze_project(&root).expect("analysis should run");
    assert!(sema
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4002));
    assert!(sema
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4003));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn lowers_hir_after_semantic_pipeline() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\na := 1\n").expect("file should be written");

    let (_parsed, _units, _sema, hir) =
        lower_project_hir(&root).expect("lowering pipeline should run");
    assert_eq!(hir.modules.len(), 1);
    assert_eq!(hir.modules[0].items.len(), 1);

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn lowers_mir_after_hir_pipeline() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\na := 1\n").expect("file should be written");

    let (_parsed, _units, _sema, _hir, mir, mir_diagnostics) =
        lower_project_mir(&root).expect("mir lowering pipeline should run");
    assert_eq!(mir.modules.len(), 1);
    assert_eq!(mir.modules[0].functions.len(), 1);
    assert!(mir_diagnostics.is_empty());

    fs::remove_dir_all(root).expect("temp directory should be removed");
}
