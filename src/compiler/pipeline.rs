use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::fs;
use std::path::{Path, PathBuf};

use crate::compiler::ast::AstFile;
use crate::compiler::backend::cranelift::build_executable;
use crate::compiler::backend::{BuildArtifact, BuildOptLevel};
use crate::compiler::diagnostics::{Diagnostic, DiagnosticCode, DiagnosticPhase};
use crate::compiler::hir::lower::lower_module_units_with_metadata;
use crate::compiler::hir::HirProgram;
use crate::compiler::lexer::scanner::Lexer;
use crate::compiler::lexer::token::Token;
use crate::compiler::mir::lower::lower_hir_to_mir;
use crate::compiler::mir::verify::verify_mir_program;
use crate::compiler::mir::{MirInstr, MirProgram, MirValue, MirValueId};
use crate::compiler::module_resolver::{resolve_module_graph, ModuleId, ModuleResolverError};
use crate::compiler::parser::parse_file;
use crate::compiler::sema::analyze::{analyze_modules, SemanticSession};
use crate::compiler::sema::control::control_check_modules;
use crate::compiler::sema::module_unit::{build_module_units, ModuleUnit};
use crate::compiler::sema::typeck::{infer_binding_type_strings, type_check_modules};

#[derive(Debug, Clone)]
pub struct LexedFile {
    pub module_id: ModuleId,
    pub file_path: PathBuf,
    pub tokens: Vec<Token>,
}

#[derive(Debug, Clone)]
pub struct LexSession {
    pub files: Vec<LexedFile>,
    pub diagnostics: Vec<Diagnostic>,
}

#[derive(Debug, Clone)]
pub struct ParsedFile {
    pub module_id: ModuleId,
    pub file_path: PathBuf,
    pub ast: Option<AstFile>,
}

#[derive(Debug, Clone)]
pub struct ParseSession {
    pub files: Vec<ParsedFile>,
    pub diagnostics: Vec<Diagnostic>,
}

pub fn lex_project<P: AsRef<Path>>(start_dir: P) -> Result<LexSession, ModuleResolverError> {
    let graph = resolve_module_graph(start_dir)?;
    Ok(lex_module_graph(&graph))
}

pub fn lex_module_graph(graph: &crate::compiler::module_resolver::ModuleGraph) -> LexSession {
    let mut files = Vec::new();
    let mut diagnostics = graph.diagnostics.clone();

    for module in &graph.modules {
        for relative_file in &module.files {
            let absolute_path = graph.root_dir.join(relative_file);
            let source = match fs::read_to_string(&absolute_path) {
                Ok(source) => source,
                Err(err) => {
                    diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::Lexer,
                            DiagnosticCode::E2007,
                            format!("failed to read source file: {err}"),
                        )
                        .with_primary_file_label(
                            relative_file.clone(),
                            None,
                            "could not load file contents for lexing",
                        ),
                    );
                    continue;
                }
            };

            let output = Lexer::new(&source, relative_file.clone()).lex();
            diagnostics.extend(output.diagnostics);

            files.push(LexedFile {
                module_id: module.id,
                file_path: relative_file.clone(),
                tokens: output.tokens,
            });
        }
    }

    diagnostics.sort_by(|left, right| {
        let left_path = left.labels.first().map(|label| &label.file_path);
        let right_path = right.labels.first().map(|label| &label.file_path);
        left_path.cmp(&right_path)
    });

    LexSession { files, diagnostics }
}

pub fn parse_project<P: AsRef<Path>>(start_dir: P) -> Result<ParseSession, ModuleResolverError> {
    let lexed = lex_project(start_dir)?;
    Ok(parse_lex_session(lexed))
}

pub fn parse_project_with_module_units<P: AsRef<Path>>(
    start_dir: P,
) -> Result<(ParseSession, Vec<ModuleUnit>), ModuleResolverError> {
    let graph = resolve_module_graph(start_dir)?;
    let lexed = lex_module_graph(&graph);
    let parsed = parse_lex_session(lexed);
    let units = build_module_units(&graph, &parsed);
    Ok((parsed, units))
}

pub fn analyze_project<P: AsRef<Path>>(
    start_dir: P,
) -> Result<(ParseSession, Vec<ModuleUnit>, SemanticSession), ModuleResolverError> {
    let (parsed, units) = parse_project_with_module_units(start_dir)?;
    let mut sema = analyze_modules(&units);
    sema.diagnostics.extend(type_check_modules(&units));
    sema.diagnostics.extend(control_check_modules(&units));
    sema.diagnostics.sort_by(|left, right| {
        let left_path = left.labels.first().map(|label| &label.file_path);
        let right_path = right.labels.first().map(|label| &label.file_path);
        left_path.cmp(&right_path)
    });
    Ok((parsed, units, sema))
}

pub fn lower_project_hir<P: AsRef<Path>>(
    start_dir: P,
) -> Result<(ParseSession, Vec<ModuleUnit>, SemanticSession, HirProgram), ModuleResolverError> {
    let (parsed, units, sema) = analyze_project(start_dir)?;
    let inferred_types = infer_binding_type_strings(&units);
    let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred_types);
    Ok((parsed, units, sema, hir))
}

pub fn lower_project_mir<P: AsRef<Path>>(
    start_dir: P,
) -> Result<
    (
        ParseSession,
        Vec<ModuleUnit>,
        SemanticSession,
        HirProgram,
        MirProgram,
        Vec<Diagnostic>,
    ),
    ModuleResolverError,
> {
    let (parsed, units, sema, hir) = lower_project_hir(start_dir)?;
    let mir = shake_mir_program(&lower_hir_to_mir(&hir));
    let mut mir_diagnostics = verify_mir_program(&mir);
    mir_diagnostics.sort_by(|left, right| {
        let left_path = left.labels.first().map(|label| &label.file_path);
        let right_path = right.labels.first().map(|label| &label.file_path);
        left_path.cmp(&right_path)
    });
    Ok((parsed, units, sema, hir, mir, mir_diagnostics))
}

fn shake_mir_program(mir: &MirProgram) -> MirProgram {
    let mut by_name = BTreeMap::<String, Vec<(usize, usize)>>::new();
    let mut entry = None;
    for (mi, module) in mir.modules.iter().enumerate() {
        for (fi, function) in module.functions.iter().enumerate() {
            by_name
                .entry(function.name.clone())
                .or_default()
                .push((mi, fi));
            if module.key.module_name == "main" && function.name == "main" {
                entry = Some((mi, fi));
            }
        }
    }

    let Some(entry) = entry else {
        return mir.clone();
    };

    let mut reachable = BTreeSet::<(usize, usize)>::new();
    let mut queue = VecDeque::from([entry]);
    let mut conservative_all = false;

    while let Some((mi, fi)) = queue.pop_front() {
        if !reachable.insert((mi, fi)) {
            continue;
        }
        let function = &mir.modules[mi].functions[fi];
        let value_defs = collect_value_defs(function);
        for block in &function.blocks {
            for instr in &block.instructions {
                let MirInstr::Eval {
                    value: MirValue::Call { callee, .. },
                    ..
                } = instr
                else {
                    continue;
                };
                match resolve_possible_callees(*callee, &value_defs, &by_name, 0) {
                    Some(callees) => {
                        for callee in callees {
                            if !reachable.contains(&callee) {
                                queue.push_back(callee);
                            }
                        }
                    }
                    None => {
                        conservative_all = true;
                    }
                }
            }
        }
    }

    if conservative_all {
        return mir.clone();
    }

    let modules = mir
        .modules
        .iter()
        .enumerate()
        .map(|(mi, module)| {
            let mut next = module.clone();
            next.functions = module
                .functions
                .iter()
                .enumerate()
                .filter_map(|(fi, function)| {
                    if reachable.contains(&(mi, fi)) {
                        Some(function.clone())
                    } else {
                        None
                    }
                })
                .collect();
            next
        })
        .collect();
    MirProgram { modules }
}

fn collect_value_defs(
    function: &crate::compiler::mir::MirFunction,
) -> BTreeMap<MirValueId, MirValue> {
    let mut defs = BTreeMap::new();
    for block in &function.blocks {
        for instr in &block.instructions {
            if let MirInstr::Eval { dest, value, .. } = instr {
                defs.insert(*dest, value.clone());
            }
        }
    }
    defs
}

fn resolve_possible_callees(
    value_id: MirValueId,
    defs: &BTreeMap<MirValueId, MirValue>,
    by_name: &BTreeMap<String, Vec<(usize, usize)>>,
    depth: usize,
) -> Option<Vec<(usize, usize)>> {
    if depth > 16 {
        return None;
    }
    let value = defs.get(&value_id)?;
    match value {
        MirValue::Ident(name) => by_name.get(name).cloned(),
        MirValue::LocalSet { value, .. } | MirValue::Assign { value, .. } => {
            resolve_possible_callees(*value, defs, by_name, depth + 1)
        }
        _ => None,
    }
}

pub fn build_project<P: AsRef<Path>>(
    start_dir: P,
    output_path: Option<&Path>,
) -> Result<(BuildArtifact, Vec<Diagnostic>), ModuleResolverError> {
    build_project_with_opt_level(start_dir, output_path, BuildOptLevel::Default)
}

pub fn build_project_with_opt_level<P: AsRef<Path>>(
    start_dir: P,
    output_path: Option<&Path>,
    opt_level: BuildOptLevel,
) -> Result<(BuildArtifact, Vec<Diagnostic>), ModuleResolverError> {
    let (_parsed, _units, sema, _hir, mir, mut mir_diagnostics) = lower_project_mir(&start_dir)?;

    let mut diagnostics = sema.diagnostics;
    diagnostics.append(&mut mir_diagnostics);
    if !diagnostics.is_empty() {
        diagnostics.sort_by(|left, right| {
            let left_path = left.labels.first().map(|label| &label.file_path);
            let right_path = right.labels.first().map(|label| &label.file_path);
            left_path.cmp(&right_path)
        });
        return Ok((
            BuildArtifact {
                executable_path: PathBuf::new(),
                object_path: PathBuf::new(),
            },
            diagnostics,
        ));
    }

    let start_dir = start_dir.as_ref();
    let build_dir = start_dir.join(".dyn_build");
    let (artifact, mut backend_diagnostics) =
        match build_executable(&mir, &build_dir, output_path, opt_level) {
            Ok(ok) => ok,
            Err(message) => {
                return Ok((
                    BuildArtifact {
                        executable_path: PathBuf::new(),
                        object_path: PathBuf::new(),
                    },
                    vec![Diagnostic::error(
                        DiagnosticPhase::Backend,
                        DiagnosticCode::E5002,
                        format!("native build failed: {message}"),
                    )],
                ));
            }
        };

    diagnostics.append(&mut backend_diagnostics);
    diagnostics.sort_by(|left, right| {
        let left_path = left.labels.first().map(|label| &label.file_path);
        let right_path = right.labels.first().map(|label| &label.file_path);
        left_path.cmp(&right_path)
    });

    Ok((artifact, diagnostics))
}

pub fn parse_lex_session(lexed: LexSession) -> ParseSession {
    let mut files = Vec::new();
    let mut diagnostics = lexed.diagnostics;

    for lexed_file in lexed.files {
        let parsed = parse_file(lexed_file.file_path.clone(), &lexed_file.tokens);
        diagnostics.extend(parsed.diagnostics);
        files.push(ParsedFile {
            module_id: lexed_file.module_id,
            file_path: lexed_file.file_path,
            ast: parsed.ast,
        });
    }

    diagnostics.sort_by(|left, right| {
        let left_path = left.labels.first().map(|label| &label.file_path);
        let right_path = right.labels.first().map(|label| &label.file_path);
        left_path.cmp(&right_path)
    });

    ParseSession { files, diagnostics }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::compiler::mir::{
        MirBasicBlock, MirBlockId, MirFunction, MirInstr, MirModule, MirTerminator, MirValue,
        MirValueType,
    };
    use crate::compiler::module_resolver::ModuleKey;
    use std::process::Command;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn make_temp_dir() -> PathBuf {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("time should be monotonic")
            .as_nanos();

        let path = std::env::temp_dir().join(format!("dyn_pipeline_{unique}"));
        fs::create_dir_all(&path).expect("temp directory should be created");
        path
    }

    #[test]
    fn shakes_unreachable_functions_from_main_entry() {
        let mk_fun = |name: &str, call: Option<&str>, ret: i32| MirFunction {
            name: name.to_string(),
            def_id: None,
            return_type: Some("i32".to_string()),
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
                        param_types: Vec::new(),
                        entry: MirBlockId(0),
                        blocks: vec![MirBasicBlock {
                            id: MirBlockId(0),
                            instructions: vec![],
                            terminator: Some(MirTerminator::Return(None)),
                        }],
                    },
                ],
            }],
        };

        let shaken = shake_mir_program(&mir);
        assert_eq!(shaken.modules[0].functions.len(), 2);
    }

    #[test]
    fn lexes_all_resolved_module_files() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module main\nmsg := \"ok\"\n")
            .expect("file should be written");
        fs::write(root.join("b.dyn"), "module main\nval := 1..=2\n")
            .expect("file should be written");

        let session = lex_project(&root).expect("pipeline should resolve modules");
        assert_eq!(session.files.len(), 2);
        assert!(session.diagnostics.is_empty());

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn aggregates_resolver_and_lexer_diagnostics() {
        let root = make_temp_dir();
        fs::write(root.join("bad_module.dyn"), "not_module main\n")
            .expect("file should be written");
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
        fs::write(root.join("bad_parse.dyn"), "module main\na :=\n")
            .expect("file should be written");

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

    #[test]
    fn returns_diagnostics_when_build_has_no_main() {
        let root = make_temp_dir();
        fs::write(root.join("a.dyn"), "module other\na := 1\n").expect("file should be written");

        let (_artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E5002));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn returns_diagnostics_for_immutable_mut_receiver_method_call() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nmain := () i32 {\n  t := Thing{}\n  return t.touch()\n}\n",
        )
        .expect("file should be written");

        let (_artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4006
                && diagnostic
                    .message
                    .contains("cannot call mut receiver method on immutable value")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn returns_diagnostics_for_immutable_field_mut_receiver_method_call() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nHolder := struct { item: Thing }\nmain := () i32 {\n  h := Holder{item: Thing{}}\n  h.item.touch()\n}\n",
        )
        .expect("file should be written");

        let (_artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4006
                && diagnostic
                    .message
                    .contains("cannot call mut receiver method on immutable value")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn returns_diagnostics_for_invalid_named_struct_offsetof_designator() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nData := struct { a: u8, b: i32 }\nmain := () i32 {\n  $as(i32, $offsetof(Data, c))\n}\n",
        )
        .expect("file should be written");

        let (_artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("$offsetof field designator is invalid for named struct type")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn returns_diagnostics_for_mut_receiver_call_on_temporary() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nmain := () i32 {\n  Thing{}.touch()\n}\n",
        )
        .expect("file should be written");

        let (_artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4006
                && diagnostic
                    .message
                    .contains("cannot call mut receiver method on immutable value")
        }));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_function_call_return() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nhelper := () i32 => 7\nmain := () i32 => helper()\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(7));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_function_call_arguments() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nadd := (x: i32, y: i32) i32 => x + y\nmain := () i32 => add(30, 41)\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(71));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_function_alias_call_return() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nhelper := () i32 => 73\nmain := () i32 {\n  f := helper\n  return f()\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(73));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_higher_order_function_parameter_call() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\ninc := (x: i32) i32 => x + 1\napply := (f, x: i32) i32 => f(x)\nmain := () i32 => apply(inc, 80)\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(81));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_typed_higher_order_function_parameter_call() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\ninc := (x: i32) i32 => x + 1\napply := (f: fn(i32) i32, x: i32) i32 => f(x)\nmain := () i32 => apply(inc, 82)\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(83));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_function_returning_function_value() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\ninc := (x: i32) i32 => x + 1\nmake := () fn(i32) i32 => inc\nmain := () i32 {\n  f := make()\n  return f(41)\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(42));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_comptime_function_returning_function_value() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\ninc := (x: i32) i32 => x + 1\nmake := () fn(i32) i32 => inc\nmain := () i32 {\n  f := comp make()\n  return f(41)\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(42));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_default_argument_call() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nadd := (x: i32, y: i32 = 5) i32 => x + y\nmain := () i32 => add(70)\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(75));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_default_argument_call_via_alias() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nadd := (x: i32, y: i32 = 5) i32 => x + y\nmain := () i32 {\n  f := add\n  return f(70)\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(75));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_named_arguments_reordered_via_alias() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nadd := (x: i32, y: i32) i32 => x + y\nmain := () i32 {\n  f := add\n  return f(y: 12, x: 60)\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(72));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_named_arguments_reordered() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nadd := (x: i32, y: i32) i32 => x + y\nmain := () i32 => add(y: 12, x: 60)\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(72));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_named_and_default_arguments() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nscore := (a: i32, b: i32 = 2, c: i32 = 3) i32 => a + b + c\nmain := () i32 => score(c: 5, a: 10)\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(17));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_method_default_argument() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing, n: i32 = 7) i32 => n }\nmain := () i32 {\n  mut t := Thing{}\n  return t.touch()\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(7));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_method_named_argument() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing, n: i32 = 7) i32 => n }\nmain := () i32 {\n  mut t := Thing{}\n  return t.touch(n: 9)\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(9));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_self_builtin_in_method() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { check := (self: *Thing) i32 => { s := $Self(); return if s == s 6 else 0 } }\nmain := () i32 {\n  t := Thing{}\n  return t.check()\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(6));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_generic_named_default_method_combo() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\ninc := (x: i32) i32 => x + 1\nThing := struct { run := (self: *mut Thing, f: fn(i32) i32, x: i32 = 40) i32 => f(x) }\nmain := () i32 {\n  mut t := Thing{}\n  _ignored := t.run(f: inc)\n  return t.run(f: inc, x: 2)\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(3));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_if_expression_return() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 { return if true 9 else 4 }\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(9));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_local_bindings() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 { x := 5 y := 8 return x + y }\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(13));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_comparison_and_logical_ops() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 => if (3 > 2) && (1 == 1) 21 else 0\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(21));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_float_expression_cast_to_main_exit() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () f64 => 1.5 + 2.5\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(4));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_calling_float_function() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nfoo := () f64 => 6.75\nmain := () f64 => foo()\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(6));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_loop_break() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 { for { break } return 11 }\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(11));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_loop_continue_path() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 { for { if false { continue } break } return 12 }\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(12));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_for_range_binding_sum() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  mut total = 0\n  for 0..=4: |v| total += v\n  return total\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(10));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_for_iterate_binding_sum() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  xs: [4]i32 = [1, 2, 3, 4]\n  mut total = 0\n  for xs: |v| total += v\n  return total\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty(), "{diagnostics:#?}");
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(10));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_if_optional_capture_binding() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  n: ?i32 = 9\n  return if n: |v| v else 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty(), "{diagnostics:#?}");
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(9));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_or_else_capture_binding() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  mut n: ?i32 = null\n  return n or |err| if err == err 7 else 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty(), "{diagnostics:#?}");
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(7));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_optional_unwrap_success() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  n: ?i32 = 6\n  return n.?\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty(), "{diagnostics:#?}");
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(6));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_optional_unwrap_trap_on_null() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  mut n: ?i32 = null\n  return n.?\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty(), "{diagnostics:#?}");
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert!(!status.success());

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_source_match_guard_and_range() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  v := 2\n  return match v {\n    0..1: 4,\n    2 if true: 9,\n    _: 0,\n  }\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(9));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_source_enum_variant_match_binding() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nState := enum { Ready, Value: i32 }\nmain := () i32 {\n  s := .Value(9)\n  return match s {\n    .Ready: 1,\n    .Value(v): v,\n  }\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty(), "{diagnostics:#?}");
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(9));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_source_struct_field_access() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 => Data{a: 4, b: 9}.b\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(9));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_source_dynamic_struct_index() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 { idx := 1 return Data{a: 4, b: 9}[idx] }\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(9));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_source_dynamic_enum_index() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 { idx := 1 e := .Ok(9) return e[idx] }\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(9));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_source_slice_then_index() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 => Data{a: 4, b: 9}[0..2][1]\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(9));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_runtime_vec_i32_intrinsics() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := __dyn_c_allocator()\n  vec := __dyn_vec_i32_init(alloc)\n  __dyn_vec_i32_push(vec, 4)\n  __dyn_vec_i32_push(vec, 9)\n  value := __dyn_vec_i32_get(vec, 1)\n  __dyn_vec_i32_deinit(vec)\n  return value\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(9));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_runtime_memory_intrinsics() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := __dyn_c_allocator()\n  p := __dyn_alloc_with(alloc, 4, 4)\n  q := __dyn_alloc_with(alloc, 4, 4)\n  __dyn_mem_set(p, 7, 4)\n  __dyn_mem_copy(q, p, 4)\n  eq := __dyn_mem_eq(p, q, 4)\n  __dyn_free_with(alloc, p, 4, 4)\n  __dyn_free_with(alloc, q, 4, 4)\n  return if eq == 1 23 else 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(23));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_failing_allocator_vec_behavior() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := __dyn_test_failing_allocator()\n  __dyn_test_set_fail_after(1)\n  vec := __dyn_vec_i32_init(alloc)\n  __dyn_vec_i32_push(vec, 3)\n  __dyn_vec_i32_push(vec, 5)\n  __dyn_vec_i32_push(vec, 7)\n  __dyn_vec_i32_push(vec, 11)\n  fail := __dyn_vec_i32_push(vec, 13)\n  len := __dyn_vec_i32_len(vec)\n  last := __dyn_vec_i32_get(vec, 3)\n  __dyn_vec_i32_deinit(vec)\n  return if (fail == 0) && (len == 4) && (last == 11) 29 else 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(29));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_std_vec_i32_wrappers() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := __dyn_c_allocator()\n  vec := std_vec_i32_init(alloc)\n  std_vec_i32_push(vec, 10)\n  std_vec_i32_push(vec, 14)\n  out := std_vec_i32_get(vec, 1)\n  std_vec_i32_deinit(vec)\n  return out\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(14));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_std_vec_i32_cap_and_reserve() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := __dyn_c_allocator()\n  vec := std_vec_i32_init(alloc)\n  std_vec_i32_reserve(vec, 9)\n  cap := std_vec_i32_cap(vec)\n  std_vec_i32_deinit(vec)\n  return if cap >= 9 9 else 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(9));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_std_vec_i32_set_pop_and_clear() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := __dyn_c_allocator()\n  vec := std_vec_i32_init(alloc)\n  std_vec_i32_push(vec, 4)\n  std_vec_i32_push(vec, 6)\n  std_vec_i32_set(vec, 1, 21)\n  popped := std_vec_i32_pop(vec)\n  std_vec_i32_clear(vec)\n  len := std_vec_i32_len(vec)\n  std_vec_i32_deinit(vec)\n  return if len == 0 popped else 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(21));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_raw_vec_u64_intrinsics() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := __dyn_c_allocator()\n  vec := __dyn_vec_raw_init(alloc, 8, 8)\n  __dyn_vec_raw_push_u64(vec, 5)\n  __dyn_vec_raw_push_u64(vec, 31)\n  out := __dyn_vec_raw_get_u64(vec, 1)\n  __dyn_vec_raw_deinit(vec)\n  return if out == 31 31 else 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(31));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_std_vec_raw_wrappers() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := __dyn_c_allocator()\n  vec := std_vec_init(alloc, 8, 8)\n  std_vec_push_u64(vec, 2)\n  std_vec_push_u64(vec, 37)\n  out := std_vec_get_u64(vec, 1)\n  std_vec_deinit(vec)\n  return if out == 37 37 else 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(37));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_std_vec_raw_cap_and_reserve() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := __dyn_c_allocator()\n  vec := std_vec_init(alloc, 8, 8)\n  std_vec_reserve(vec, 11)\n  cap := std_vec_cap(vec)\n  std_vec_deinit(vec)\n  return if cap >= 11 11 else 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(11));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_std_vec_raw_set_pop_and_clear() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := __dyn_c_allocator()\n  vec := std_vec_init(alloc, 8, 8)\n  std_vec_push_u64(vec, 3)\n  std_vec_push_u64(vec, 8)\n  std_vec_set_u64(vec, 1, 42)\n  popped := std_vec_pop_u64(vec)\n  std_vec_clear(vec)\n  len := std_vec_len(vec)\n  std_vec_deinit(vec)\n  return if len == 0 && popped == 42 42 else 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(42));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_std_vec_raw_byte_pointer_ops() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := __dyn_c_allocator()\n  vec := std_vec_init(alloc, 4, 4)\n  src := __dyn_alloc_with(alloc, 4, 4)\n  dst := __dyn_alloc_with(alloc, 4, 4)\n  __dyn_mem_set(src, 7, 4)\n  ok_push := std_vec_push_bytes(vec, src, 4)\n  ptr := std_vec_ptr(vec, 0)\n  __dyn_mem_set(src, 9, 4)\n  ok_set := std_vec_set_bytes(vec, 0, src, 4)\n  ok_get := std_vec_get_bytes(vec, 0, dst, 4)\n  eq := __dyn_mem_eq(src, dst, 4)\n  ok_pop := std_vec_pop_bytes(vec, dst, 4)\n  eq_pop := __dyn_mem_eq(src, dst, 4)\n  std_vec_deinit(vec)\n  __dyn_free_with(alloc, src, 4, 4)\n  __dyn_free_with(alloc, dst, 4, 4)\n  return if ok_push == 1 && ptr != 0 && ok_set == 1 && ok_get == 1 && eq == 1 && ok_pop == 1 && eq_pop == 1 57 else 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(57));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_generic_vec_type_constructor_container() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nVec := (T: comp type) type => struct {\n  new := (allocator: usize) usize => std_vec_init(allocator, comp $sizeof(T), comp $alignof(T)),\n  reserve := (vec: usize, new_cap: usize) u32 => std_vec_reserve(vec, new_cap),\n  push_bytes := (vec: usize, src: usize) u32 => std_vec_push_bytes(vec, src, comp $sizeof(T)),\n  get_bytes := (vec: usize, idx: usize, dst: usize) u32 => std_vec_get_bytes(vec, idx, dst, comp $sizeof(T)),\n  pop_bytes := (vec: usize, dst: usize) u32 => std_vec_pop_bytes(vec, dst, comp $sizeof(T)),\n  deinit := (vec: usize) u32 => std_vec_deinit(vec),\n}\nmain := () i32 {\n  alloc := __dyn_c_allocator()\n  vec := Vec(i32).new(alloc)\n  src := __dyn_alloc_with(alloc, 4, 4)\n  dst := __dyn_alloc_with(alloc, 4, 4)\n  __dyn_mem_set(src, 58, 4)\n  ok_reserve := Vec(i32).reserve(vec, 4)\n  ok_push := Vec(i32).push_bytes(vec, src)\n  ok_get := Vec(i32).get_bytes(vec, 0, dst)\n  eq_get := __dyn_mem_eq(src, dst, 4)\n  __dyn_mem_set(dst, 0, 4)\n  ok_pop := Vec(i32).pop_bytes(vec, dst)\n  eq_pop := __dyn_mem_eq(src, dst, 4)\n  ok_vec_free := Vec(i32).deinit(vec)\n  __dyn_free_with(alloc, src, 4, 4)\n  __dyn_free_with(alloc, dst, 4, 4)\n  return if ok_reserve == 1 && ok_push == 1 && ok_get == 1 && eq_get == 1 && ok_pop == 1 && eq_pop == 1 && ok_vec_free == 1 58 else 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(58));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_indirect_function_pointer_call() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  fp := __dyn_test_identity_i32_fn()\n  return fp(41)\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty(), "{diagnostics:#?}");
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(41));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_struct_static_and_instance_method_calls() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { new := () i32 => 44, do := (self: Thing) i32 => 55 }\nmain := () i32 {\n  t := Thing{}\n  Thing.new()\n  return t.do()\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(55));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_generic_type_binding() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nid := (T: type, v: T) T => v\nmain := () i32 {\n  out := id(i32, 68)\n  return out\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(68));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_generic_type_binding_named_args() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nid := (T: type, v: T) T => v\nmain := () i32 {\n  out := id(v: 68, T: i32)\n  return out\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(68));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_arena_allocator_intrinsics() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  base := __dyn_c_allocator()\n  arena := __dyn_arena_allocator(base)\n  p := __dyn_alloc_with(arena, 4, 4)\n  __dyn_mem_set(p, 7, 4)\n  __dyn_arena_reset(arena)\n  __dyn_arena_deinit(arena)\n  return 33\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(33));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_builtin_sizeof_and_cast() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  sz := $sizeof(i32)\n  v := $as(i32, sz)\n  return v\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(4));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_builtin_cast_from_slice_to_usize() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  xs: [2]i32 = [1, 2]\n  s: []i32 = xs[..]\n  p := $as(usize, s)\n  return if p != 0 1 else 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(1));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_builtin_alignof_and_offsetof() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  a := $alignof(i32)\n  o := $offsetof(i32, 0)\n  return $as(i32, a + o)\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(4));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_builtin_offsetof_struct_field_name() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  o := $offsetof(struct { a: u8, b: i32, c: u8 }, b)\n  return $as(i32, o)\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(4));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_builtin_offsetof_struct_field_index() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  o := $offsetof(struct { a: u8, b: i32, c: u8 }, 1)\n  return $as(i32, o)\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(4));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_builtin_offsetof_named_struct_field_name() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nData := struct { a: u8, b: i32, c: u8 }\nmain := () i32 {\n  o := $offsetof(Data, b)\n  return $as(i32, o)\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(4));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_builtin_panic_traps() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  $panic(\"boom\")\n  return 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert!(!status.success());

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_builtin_unreachable_traps() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  $unreachable()\n  return 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert!(!status.success());

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_console_print_i32() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  std_io_print_i32(12)\n  std_io_println_i32(34)\n  return 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let output = Command::new(&artifact.executable_path)
            .output()
            .expect("executable should run");
        assert_eq!(output.status.code(), Some(0));
        let stdout = String::from_utf8_lossy(&output.stdout);
        assert_eq!(stdout, "1234\n");

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_console_println_bytes() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  std_io_println(\"Hello, world\")\n  return 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let output = Command::new(&artifact.executable_path)
            .output()
            .expect("executable should run");
        assert_eq!(output.status.code(), Some(0));
        let stdout = String::from_utf8_lossy(&output.stdout);
        assert_eq!(stdout, "Hello, world\n");

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_std_defined_io_print_type_dispatch() {
        let root = make_temp_dir();
        fs::write(
            root.join("my_io.dyn"),
            "module my_io\npub print := (T: type, value: T) u32 => if T == i32 __dyn_io_write_i32($as(i32, value), 0) else __dyn_io_write_i32(0, 0)\npub println := (T: type, value: T) u32 => if T == i32 __dyn_io_write_i32($as(i32, value), 1) else __dyn_io_write_i32(0, 1)\n",
        )
        .expect("file should be written");
        fs::write(
            root.join("a.dyn"),
            "module main\nio := use \"my_io\"\nmain := () i32 {\n  io.print(i32, 12)\n  io.println(i32, 34)\n  return 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let output = Command::new(&artifact.executable_path)
            .output()
            .expect("executable should run");
        assert_eq!(output.status.code(), Some(0));
        let stdout = String::from_utf8_lossy(&output.stdout);
        assert_eq!(stdout, "1234\n");

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_io_print_module_member_call() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmy_io := use \"my_io\"\nmain := () i32 {\n  my_io.print(12)\n  return 0\n}\n",
        )
        .expect("file should be written");
        fs::write(
            root.join("my_io.dyn"),
            "module my_io\npub print := (value: i32) u32 => __dyn_io_write_i32(value, 0)\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let output = Command::new(&artifact.executable_path)
            .output()
            .expect("executable should run");
        assert_eq!(output.status.code(), Some(0));
        let stdout = String::from_utf8_lossy(&output.stdout);
        assert_eq!(stdout, "12");

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_imported_module_member_function_call() {
        let root = make_temp_dir();
        fs::write(
            root.join("my_math.dyn"),
            "module my_math\npub inc := (value: i32) i32 => value + 1\n",
        )
        .expect("file should be written");
        fs::write(
            root.join("a.dyn"),
            "module main\nmath := use \"my_math\"\nmain := () i32 => math.inc(41)\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(42));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_std_subdir_io_hello_world_import() {
        let root = make_temp_dir();
        fs::create_dir_all(root.join("std")).expect("std directory should be created");
        fs::write(
            root.join("std").join("io.dyn"),
            "module io\npub println := (text: bytes) u32 => __dyn_io_write(text, 1)\n",
        )
        .expect("file should be written");
        fs::write(
            root.join("a.dyn"),
            "module main\nio := use \"std/io\"\nmain := () i32 {\n  io.println(\"Hello, world\")\n  return 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let output = Command::new(&artifact.executable_path)
            .output()
            .expect("executable should run");
        assert_eq!(output.status.code(), Some(0));
        let stdout = String::from_utf8_lossy(&output.stdout);
        assert_eq!(stdout, "Hello, world\n");

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn returns_diagnostics_for_global_print_without_io_import() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  print(\"hello\")\n  return 0\n}\n",
        )
        .expect("file should be written");

        let (_artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4001));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_user_defined_print_function() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nprint := (value: i32) i32 => value + 1\nmain := () i32 {\n  return print(41)\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(42));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_builtin_typeof_value() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  t := $typeof(1)\n  return if t == t 61 else 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(61));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_builtin_typeof_distinct_tags() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  ti := $typeof(1)\n  tf := $typeof(1.0)\n  return if ti != tf 62 else 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(62));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_builtin_typeof_type_identifier() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  tt := $typeof(i32)\n  ti := $typeof(1)\n  return if tt != ti 64 else 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(64));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_direct_type_value_comparison() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  t := i32\n  return if t == $typeof(1) 69 else 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(69));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_builtin_alignof_and_sizeof_u1() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  s := $sizeof(u1)\n  a := $alignof(u1)\n  return $as(i32, s + a)\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(2));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_comptime_builtin_expression() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  return $as(i32, comp $sizeof(i32))\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(4));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_typed_allocator_type_parameter_api() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nalloc_t := (alloc: usize, T: comp type, count: usize) ?usize => {\n  size := count * comp $sizeof(T)\n  ptr := __dyn_alloc_with(alloc, size, comp $alignof(T))\n  if ptr == 0 null else ptr\n}\nfree_t := (alloc: usize, T: comp type, ptr: usize, count: usize) u32 =>\n  __dyn_free_with(alloc, ptr, count * comp $sizeof(T), comp $alignof(T))\nmain := () i32 {\n  alloc := __dyn_c_allocator()\n  p := alloc_t(alloc, i32, 2) or $as(usize, 0)\n  if p == 0 return 0\n  __dyn_mem_set(p, 0x22, 8)\n  ok := free_t(alloc, i32, p, 2)\n  return if ok == 1 34 else 0\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(34));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_comptime_sizeof_type_constructor_call() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nVec := (T: type) type => struct { items: []T }\nmain := () i32 {\n  s := comp $sizeof(Vec(i32))\n  return $as(i32, s)\n}\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(16));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn builds_native_executable_with_u1_main_return() {
        let root = make_temp_dir();
        fs::write(
            root.join("a.dyn"),
            "module main\nmain := () u1 { return true }\n",
        )
        .expect("file should be written");

        let (artifact, diagnostics) =
            build_project(&root, None).expect("build pipeline should run");
        assert!(diagnostics.is_empty());
        assert!(artifact.executable_path.exists());

        let status = Command::new(&artifact.executable_path)
            .status()
            .expect("executable should run");
        assert_eq!(status.code(), Some(1));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }
}
