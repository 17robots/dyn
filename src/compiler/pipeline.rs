use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::fs;
use std::path::{Path, PathBuf};

use crate::compiler::ast::AstFile;
use crate::compiler::backend::cranelift::build_executable;
use crate::compiler::backend::{BuildArtifact, BuildOptLevel};
use crate::compiler::diagnostic_utils::{
    dedupe_diagnostics_by_primary_span, sort_diagnostics_by_primary_path,
};
use crate::compiler::diagnostics::{Diagnostic, DiagnosticCode, DiagnosticPhase};
use crate::compiler::hir::lower::lower_module_units_with_metadata;
use crate::compiler::hir::HirProgram;
use crate::compiler::lexer::scanner::Lexer;
use crate::compiler::lexer::token::Token;
use crate::compiler::mir::lower::lower_hir_to_mir_with_diagnostics_and_paths;
use crate::compiler::mir::verify::verify_mir_program;
use crate::compiler::mir::{MirInstr, MirProgram, MirValue, MirValueId};
use crate::compiler::module_resolver::{
    resolve_graph_file_path, resolve_module_graph, ModuleId, ModuleResolverError,
};
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

type LowerProjectMirOutput = (
    ParseSession,
    Vec<ModuleUnit>,
    SemanticSession,
    HirProgram,
    MirProgram,
    Vec<Diagnostic>,
);

pub fn lex_project<P: AsRef<Path>>(start_dir: P) -> Result<LexSession, ModuleResolverError> {
    let graph = resolve_module_graph(start_dir)?;
    Ok(lex_module_graph(&graph))
}

pub fn lex_module_graph(graph: &crate::compiler::module_resolver::ModuleGraph) -> LexSession {
    let mut files = Vec::new();
    let mut diagnostics = graph.diagnostics.clone();

    for module in &graph.modules {
        for relative_file in &module.files {
            let absolute_path = resolve_graph_file_path(graph, relative_file);
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

    sort_diagnostics_by_primary_path(&mut diagnostics);

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
    sema.diagnostics.extend(parsed.diagnostics.clone());
    sema.diagnostics.extend(type_check_modules(&units));
    sema.diagnostics.extend(control_check_modules(&units));
    sort_diagnostics_by_primary_path(&mut sema.diagnostics);
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
) -> Result<LowerProjectMirOutput, ModuleResolverError> {
    let (parsed, units, sema, hir) = lower_project_hir(start_dir)?;
    let module_source_paths = units
        .iter()
        .filter_map(|unit| {
            unit.files
                .first()
                .cloned()
                .map(|path| (unit.module_id, path))
        })
        .collect::<BTreeMap<_, _>>();
    let (mir_unshaken, mut mir_diagnostics) =
        lower_hir_to_mir_with_diagnostics_and_paths(&hir, &module_source_paths);
    let mir = shake_mir_program(&mir_unshaken);
    mir_diagnostics.extend(verify_mir_program(&mir));
    dedupe_diagnostics_by_primary_span(&mut mir_diagnostics);
    sort_diagnostics_by_primary_path(&mut mir_diagnostics);
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
    dedupe_diagnostics_by_primary_span(&mut diagnostics);
    if !diagnostics.is_empty() {
        sort_diagnostics_by_primary_path(&mut diagnostics);
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
    dedupe_diagnostics_by_primary_span(&mut diagnostics);
    sort_diagnostics_by_primary_path(&mut diagnostics);

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

    sort_diagnostics_by_primary_path(&mut diagnostics);

    ParseSession { files, diagnostics }
}

#[cfg(test)]
mod tests;
