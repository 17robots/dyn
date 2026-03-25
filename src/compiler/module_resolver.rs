use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::fs;
use std::fs::File;
use std::io;
use std::io::BufRead;
use std::io::BufReader;
use std::path::Path;
use std::path::PathBuf;

use crate::compiler::diagnostic_utils::sort_diagnostics_by_primary_path;
use crate::compiler::diagnostics::{Diagnostic, DiagnosticCode, DiagnosticPhase};

const STD_COLLECTION_DIR: &str = "std";
const STD_PATH_ENV: &str = "DYN_STD_PATH";

#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct ModuleKey {
    pub directory: PathBuf,
    pub module_name: String,
}

pub type ModuleGroups = BTreeMap<ModuleKey, Vec<PathBuf>>;

#[derive(Debug, Copy, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct ModuleId(pub usize);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResolvedModule {
    pub id: ModuleId,
    pub key: ModuleKey,
    pub files: Vec<PathBuf>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ModuleGraph {
    pub root_dir: PathBuf,
    pub groups: ModuleGroups,
    pub diagnostics: Vec<Diagnostic>,
    pub modules: Vec<ResolvedModule>,
    pub key_to_id: BTreeMap<ModuleKey, ModuleId>,
}

impl ModuleGraph {
    pub fn module_id(&self, key: &ModuleKey) -> Option<ModuleId> {
        self.key_to_id.get(key).copied()
    }

    pub fn module(&self, id: ModuleId) -> Option<&ResolvedModule> {
        self.modules.get(id.0)
    }
}

pub fn configured_std_root_dir() -> Option<PathBuf> {
    if let Ok(path) = std::env::var(STD_PATH_ENV) {
        let candidate = PathBuf::from(path);
        if candidate.is_dir() {
            return Some(candidate);
        }
    }

    let bundled = Path::new(env!("CARGO_MANIFEST_DIR")).join(STD_COLLECTION_DIR);
    if bundled.is_dir() {
        Some(bundled)
    } else {
        None
    }
}

pub fn normalize_import_path(import_path: &str) -> String {
    import_path.trim_matches('"').trim().to_string()
}

pub fn module_key_for_import(current: &ModuleKey, import_path: &str) -> ModuleKey {
    let normalized = normalize_import_path(import_path);
    let mut parts = normalized
        .split('/')
        .filter(|segment| !segment.is_empty())
        .collect::<Vec<_>>();

    if parts.is_empty() {
        return current.clone();
    }

    let module_name = parts.pop().unwrap_or_default().to_string();
    let is_std_absolute = normalized.starts_with("std/");
    let mut directory = if is_std_absolute || current.directory == Path::new(".") {
        PathBuf::new()
    } else {
        current.directory.clone()
    };
    for segment in parts {
        directory.push(segment);
    }
    if directory.as_os_str().is_empty() {
        directory = PathBuf::from(".");
    }

    ModuleKey {
        directory,
        module_name,
    }
}

pub fn resolve_graph_file_path(graph: &ModuleGraph, logical_file_path: &Path) -> PathBuf {
    let project_candidate = graph.root_dir.join(logical_file_path);
    if project_candidate.is_file() {
        return project_candidate;
    }

    let Some(std_relative_path) = strip_std_prefix(logical_file_path) else {
        return project_candidate;
    };
    let Some(std_root) = configured_std_root_dir() else {
        return project_candidate;
    };

    let std_candidate = std_root.join(std_relative_path);
    if std_candidate.is_file() {
        std_candidate
    } else {
        project_candidate
    }
}

#[derive(Debug)]
pub enum ModuleResolverError {
    InvalidStartDirectory(PathBuf),
    Io { path: PathBuf, source: io::Error },
}

impl fmt::Display for ModuleResolverError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidStartDirectory(path) => {
                write!(f, "start directory is invalid: {}", path.display())
            }
            Self::Io { path, source } => {
                write!(f, "io error at {}: {}", path.display(), source)
            }
        }
    }
}

impl std::error::Error for ModuleResolverError {}

pub fn resolve_module_graph<P: AsRef<Path>>(
    start_dir: P,
) -> Result<ModuleGraph, ModuleResolverError> {
    let start_dir = start_dir.as_ref().canonicalize().map_err(|_| {
        ModuleResolverError::InvalidStartDirectory(start_dir.as_ref().to_path_buf())
    })?;

    if !start_dir.is_dir() {
        return Err(ModuleResolverError::InvalidStartDirectory(start_dir));
    }

    let mut project_dyn_files = Vec::new();
    collect_dyn_files(&start_dir, &mut project_dyn_files)?;
    project_dyn_files.sort();

    let mut groups: ModuleGroups = BTreeMap::new();
    let mut diagnostics = Vec::new();
    let mut seen_files = BTreeSet::<PathBuf>::new();

    for path in &project_dyn_files {
        let relative_file_path = to_relative_path(&start_dir, path);
        register_module_file(
            path,
            relative_file_path,
            &mut groups,
            &mut diagnostics,
            &mut seen_files,
        );
    }

    if project_requests_std_modules(&project_dyn_files) {
        if let Some(std_root) = configured_std_root_dir() {
            let mut std_dyn_files = Vec::new();
            collect_dyn_files(&std_root, &mut std_dyn_files)?;
            std_dyn_files.sort();

            for std_file in std_dyn_files {
                let Ok(within_std) = std_file.strip_prefix(&std_root) else {
                    continue;
                };
                let logical_file_path = PathBuf::from(STD_COLLECTION_DIR).join(within_std);
                register_module_file(
                    &std_file,
                    logical_file_path,
                    &mut groups,
                    &mut diagnostics,
                    &mut seen_files,
                );
            }
        }
    }

    for files in groups.values_mut() {
        files.sort();
    }

    sort_diagnostics_by_primary_path(&mut diagnostics);

    let mut modules = Vec::with_capacity(groups.len());
    let mut key_to_id = BTreeMap::new();

    for (index, (key, files)) in groups.iter().enumerate() {
        let id = ModuleId(index);
        key_to_id.insert(key.clone(), id);
        modules.push(ResolvedModule {
            id,
            key: key.clone(),
            files: files.clone(),
        });
    }

    Ok(ModuleGraph {
        root_dir: start_dir,
        groups,
        diagnostics,
        modules,
        key_to_id,
    })
}

pub fn resolve_modules<P: AsRef<Path>>(start_dir: P) -> Result<ModuleGroups, ModuleResolverError> {
    let graph = resolve_module_graph(start_dir)?;
    Ok(graph.groups)
}

fn register_module_file(
    absolute_path: &Path,
    logical_file_path: PathBuf,
    groups: &mut ModuleGroups,
    diagnostics: &mut Vec<Diagnostic>,
    seen_files: &mut BTreeSet<PathBuf>,
) {
    if !seen_files.insert(logical_file_path.clone()) {
        return;
    }

    let module_name = match read_module_name(absolute_path) {
        Ok(module_name) => module_name,
        Err(kind) => {
            diagnostics.push(to_resolver_diagnostic(logical_file_path, kind));
            return;
        }
    };

    let directory = relative_directory_of(&logical_file_path);
    let key = ModuleKey {
        directory,
        module_name,
    };

    groups.entry(key).or_default().push(logical_file_path);
}

fn project_requests_std_modules(project_files: &[PathBuf]) -> bool {
    project_files.iter().any(|path| {
        fs::read_to_string(path)
            .map(|source| source_requests_std_import(&source))
            .unwrap_or(false)
    })
}

fn source_requests_std_import(source: &str) -> bool {
    source.contains("use \"std/")
}

fn collect_dyn_files(directory: &Path, out: &mut Vec<PathBuf>) -> Result<(), ModuleResolverError> {
    let entries = fs::read_dir(directory).map_err(|source| ModuleResolverError::Io {
        path: directory.to_path_buf(),
        source,
    })?;

    for entry in entries {
        let entry = entry.map_err(|source| ModuleResolverError::Io {
            path: directory.to_path_buf(),
            source,
        })?;

        let path = entry.path();
        let file_type = entry
            .file_type()
            .map_err(|source| ModuleResolverError::Io {
                path: path.clone(),
                source,
            })?;

        if file_type.is_dir() {
            collect_dyn_files(&path, out)?;
            continue;
        }

        if file_type.is_file() && path.extension().is_some_and(|ext| ext == "dyn") {
            out.push(path);
        }
    }

    Ok(())
}

fn read_module_name(path: &Path) -> Result<String, ModuleReadError> {
    let file = File::open(path).map_err(|source| ModuleResolverError::Io {
        path: path.to_path_buf(),
        source,
    });

    let file = match file {
        Ok(file) => file,
        Err(err) => {
            return Err(ModuleReadError::Io {
                message: err.to_string(),
            });
        }
    };

    let reader = BufReader::new(file);
    let mut in_block_comment = false;

    for line_result in reader.lines() {
        let line = match line_result {
            Ok(line) => line,
            Err(err) => {
                return Err(ModuleReadError::Io {
                    message: err.to_string(),
                });
            }
        };

        let stripped = strip_comments(&line, &mut in_block_comment);
        let candidate = stripped.trim();
        if candidate.is_empty() {
            continue;
        }

        let mut tokens = candidate.split_whitespace();
        let keyword = tokens.next();
        let module_name = tokens.next();
        let extra = tokens.next();

        if keyword != Some("module") || module_name.is_none() || extra.is_some() {
            return Err(ModuleReadError::InvalidModuleDeclaration {
                line: candidate.to_string(),
            });
        }

        let module_name = module_name.unwrap();
        if !is_valid_module_name(module_name) {
            return Err(ModuleReadError::InvalidModuleDeclaration {
                line: candidate.to_string(),
            });
        }

        return Ok(module_name.to_string());
    }

    Err(ModuleReadError::MissingModuleDeclaration)
}

#[derive(Debug)]
enum ModuleReadError {
    MissingModuleDeclaration,
    InvalidModuleDeclaration { line: String },
    Io { message: String },
}

fn to_resolver_diagnostic(file_path: PathBuf, kind: ModuleReadError) -> Diagnostic {
    match kind {
        ModuleReadError::MissingModuleDeclaration => Diagnostic::error(
            DiagnosticPhase::ModuleResolver,
            DiagnosticCode::E1003,
            "missing module declaration",
        )
        .with_primary_file_label(
            file_path.clone(),
            None,
            "file must declare `module <name>`",
        ),
        ModuleReadError::InvalidModuleDeclaration { line } => Diagnostic::error(
            DiagnosticPhase::ModuleResolver,
            DiagnosticCode::E1004,
            format!("invalid module declaration: '{line}'"),
        )
        .with_primary_file_label(
            file_path.clone(),
            None,
            "expected `module <name>` as first non-comment declaration",
        ),
        ModuleReadError::Io { message } => Diagnostic::error(
            DiagnosticPhase::ModuleResolver,
            DiagnosticCode::E1002,
            format!("failed to read module file: {message}"),
        )
        .with_primary_file_label(file_path, None, "io error while reading file"),
    }
}

fn strip_comments(line: &str, in_block_comment: &mut bool) -> String {
    let chars: Vec<char> = line.chars().collect();
    let mut out = String::new();
    let mut index = 0;

    while index < chars.len() {
        if *in_block_comment {
            if chars[index] == '*' && (index + 1) < chars.len() && chars[index + 1] == '/' {
                *in_block_comment = false;
                index += 2;
            } else {
                index += 1;
            }

            continue;
        }

        if chars[index] == '/' && (index + 1) < chars.len() {
            if chars[index + 1] == '/' {
                break;
            }

            if chars[index + 1] == '*' {
                *in_block_comment = true;
                index += 2;
                continue;
            }
        }

        out.push(chars[index]);
        index += 1;
    }

    out
}

fn to_relative_path(root_dir: &Path, path: &Path) -> PathBuf {
    path.strip_prefix(root_dir)
        .map(|relative| relative.to_path_buf())
        .unwrap_or_else(|_| path.to_path_buf())
}

fn relative_directory_of(path: &Path) -> PathBuf {
    match path.parent() {
        Some(parent) if parent.as_os_str().is_empty() => PathBuf::from("."),
        Some(parent) => parent.to_path_buf(),
        None => PathBuf::from("."),
    }
}

fn strip_std_prefix(path: &Path) -> Option<PathBuf> {
    let mut components = path.components();
    let first = components.next()?;
    if first.as_os_str() != STD_COLLECTION_DIR {
        return None;
    }

    let mut relative = PathBuf::new();
    for component in components {
        relative.push(component.as_os_str());
    }
    Some(relative)
}

fn is_valid_module_name(name: &str) -> bool {
    let mut chars = name.chars();
    let Some(first) = chars.next() else {
        return false;
    };

    if !(first.is_ascii_alphabetic() || first == '_') {
        return false;
    }

    chars.all(|ch| ch.is_ascii_alphanumeric() || ch == '_')
}

#[cfg(test)]
mod tests;
