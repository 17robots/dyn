use std::collections::BTreeMap;
use std::fmt;
use std::fs;
use std::fs::File;
use std::io;
use std::io::BufRead;
use std::io::BufReader;
use std::path::Path;
use std::path::PathBuf;

use crate::compiler::diagnostics::{Diagnostic, DiagnosticCode, DiagnosticPhase};

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

    let mut dyn_files = Vec::new();
    collect_dyn_files(&start_dir, &mut dyn_files)?;
    dyn_files.sort();

    let mut groups: ModuleGroups = BTreeMap::new();
    let mut diagnostics = Vec::new();

    for path in dyn_files {
        let module_name = match read_module_name(&path) {
            Ok(module_name) => module_name,
            Err(kind) => {
                diagnostics.push(to_resolver_diagnostic(&start_dir, &path, kind));
                continue;
            }
        };

        let relative_file_path = to_relative_path(&start_dir, &path);
        let directory = relative_directory_of(&relative_file_path);

        let key = ModuleKey {
            directory,
            module_name,
        };

        groups.entry(key).or_default().push(relative_file_path);
    }

    for files in groups.values_mut() {
        files.sort();
    }

    diagnostics.sort_by(|left, right| {
        let left_path = left.labels.first().map(|label| &label.file_path);
        let right_path = right.labels.first().map(|label| &label.file_path);
        left_path.cmp(&right_path)
    });

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

fn to_resolver_diagnostic(root_dir: &Path, path: &Path, kind: ModuleReadError) -> Diagnostic {
    let relative_path = to_relative_path(root_dir, path);

    match kind {
        ModuleReadError::MissingModuleDeclaration => Diagnostic::error(
            DiagnosticPhase::ModuleResolver,
            DiagnosticCode::E1003,
            "missing module declaration",
        )
        .with_primary_file_label(relative_path, None, "file must declare `module <name>`"),
        ModuleReadError::InvalidModuleDeclaration { line } => Diagnostic::error(
            DiagnosticPhase::ModuleResolver,
            DiagnosticCode::E1004,
            format!("invalid module declaration: '{line}'"),
        )
        .with_primary_file_label(
            relative_path,
            None,
            "expected `module <name>` as first non-comment declaration",
        ),
        ModuleReadError::Io { message } => Diagnostic::error(
            DiagnosticPhase::ModuleResolver,
            DiagnosticCode::E1002,
            format!("failed to read module file: {message}"),
        )
        .with_primary_file_label(relative_path, None, "io error while reading file"),
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
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn make_temp_dir() -> PathBuf {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("time should be monotonic")
            .as_nanos();
        for attempt in 0..1000usize {
            let path = std::env::temp_dir().join(format!(
                "dyn_module_resolver_{}_{}_{}",
                std::process::id(),
                unique,
                attempt
            ));
            if fs::create_dir(&path).is_ok() {
                return path;
            }
        }

        panic!("failed to create unique temp directory");
    }

    #[test]
    fn groups_by_directory_and_module_name() {
        let root = make_temp_dir();
        let sub = root.join("nested");
        fs::create_dir_all(&sub).expect("nested directory should be created");

        fs::write(root.join("a.dyn"), "module math\nval := 1\n").expect("file should be written");
        fs::write(root.join("b.dyn"), "module math\nval := 2\n").expect("file should be written");
        fs::write(root.join("c.dyn"), "module io\nval := 3\n").expect("file should be written");
        fs::write(sub.join("d.dyn"), "module math\nval := 4\n").expect("file should be written");

        let graph = resolve_module_graph(&root).expect("module resolution should succeed");
        assert!(graph.diagnostics.is_empty());
        assert_eq!(graph.groups.len(), 3);

        let root_key_math = ModuleKey {
            directory: PathBuf::from("."),
            module_name: "math".to_string(),
        };
        let root_key_io = ModuleKey {
            directory: PathBuf::from("."),
            module_name: "io".to_string(),
        };
        let sub_key_math = ModuleKey {
            directory: PathBuf::from("nested"),
            module_name: "math".to_string(),
        };

        assert_eq!(graph.groups.get(&root_key_math).map(Vec::len), Some(2));
        assert_eq!(graph.groups.get(&root_key_io).map(Vec::len), Some(1));
        assert_eq!(graph.groups.get(&sub_key_math).map(Vec::len), Some(1));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn skips_comments_before_module_declaration() {
        let root = make_temp_dir();
        let file_path = root.join("comments_ok.dyn");

        fs::write(
            &file_path,
            "// heading\n/// doc\n/* block\ncomment */\nmodule main\n",
        )
        .expect("file should be written");

        let graph = resolve_module_graph(&root).expect("module resolution should succeed");
        assert!(graph.diagnostics.is_empty());
        assert_eq!(graph.groups.len(), 1);

        let key = ModuleKey {
            directory: PathBuf::from("."),
            module_name: "main".to_string(),
        };
        assert_eq!(graph.groups.get(&key).map(Vec::len), Some(1));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn collects_all_bad_files_as_diagnostics() {
        let root = make_temp_dir();

        fs::write(root.join("good.dyn"), "module good\nval := 1\n")
            .expect("file should be written");
        fs::write(
            root.join("bad_missing.dyn"),
            "// only comments\n/* still comments */\n",
        )
        .expect("file should be written");
        fs::write(root.join("bad_invalid.dyn"), "not_module main\n")
            .expect("file should be written");

        let graph = resolve_module_graph(&root).expect("module resolution should succeed");
        assert_eq!(graph.groups.len(), 1);
        assert_eq!(graph.diagnostics.len(), 2);
        assert!(matches!(
            graph.diagnostics[0].code,
            DiagnosticCode::E1003 | DiagnosticCode::E1004
        ));
        assert!(matches!(
            graph.diagnostics[1].code,
            DiagnosticCode::E1003 | DiagnosticCode::E1004
        ));

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }

    #[test]
    fn assigns_stable_module_ids_from_sorted_keys() {
        let root = make_temp_dir();
        let a_dir = root.join("a");
        let b_dir = root.join("b");
        fs::create_dir_all(&a_dir).expect("a directory should be created");
        fs::create_dir_all(&b_dir).expect("b directory should be created");

        fs::write(a_dir.join("z.dyn"), "module zoo\n").expect("file should be written");
        fs::write(a_dir.join("a.dyn"), "module alpha\n").expect("file should be written");
        fs::write(b_dir.join("k.dyn"), "module alpha\n").expect("file should be written");

        let graph = resolve_module_graph(&root).expect("module resolution should succeed");
        assert!(graph.diagnostics.is_empty());
        assert_eq!(graph.modules.len(), 3);

        let key_a_alpha = ModuleKey {
            directory: PathBuf::from("a"),
            module_name: "alpha".to_string(),
        };
        let key_a_zoo = ModuleKey {
            directory: PathBuf::from("a"),
            module_name: "zoo".to_string(),
        };
        let key_b_alpha = ModuleKey {
            directory: PathBuf::from("b"),
            module_name: "alpha".to_string(),
        };

        assert_eq!(graph.module_id(&key_a_alpha), Some(ModuleId(0)));
        assert_eq!(graph.module_id(&key_a_zoo), Some(ModuleId(1)));
        assert_eq!(graph.module_id(&key_b_alpha), Some(ModuleId(2)));

        let module = graph.module(ModuleId(1)).expect("module id 1 should exist");
        assert_eq!(module.key, key_a_zoo);

        fs::remove_dir_all(root).expect("temp directory should be removed");
    }
}
