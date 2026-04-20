use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::fmt;
use std::fs;
use std::fs::File;
use std::io;
use std::io::BufRead;
use std::io::BufReader;
use std::path::Path;
use std::path::PathBuf;

use crate::compiler::diagnostics::normalize_diagnostic_path;
use crate::compiler::diagnostics::sort_diagnostics_by_primary_path;
use crate::compiler::diagnostics::{Diagnostic, DiagnosticCode, DiagnosticPhase};

const STD_COLLECTION_DIR: &str = "std";
const STD_PATH_ENV: &str = "DYN_STD_PATH";
const STD_HOST_PLATFORM_ENV: &str = "DYN_STD_HOST_PLATFORM";
const STD_HOST_LOGICAL_PATH: &str = "std/platform/host.dyn";

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

fn configured_std_host_platform() -> &'static str {
    match std::env::var(STD_HOST_PLATFORM_ENV).ok().as_deref() {
        Some("linux") => "linux",
        Some("macos") => "macos",
        Some("windows") => "windows",
        _ => {
            if cfg!(target_os = "windows") {
                "windows"
            } else if cfg!(target_os = "macos") {
                "macos"
            } else {
                "linux"
            }
        }
    }
}

fn generated_std_host_platform_source() -> String {
    let platform = configured_std_host_platform();
    format!(
        "module host\n\nplatform := use \"std/platform/{platform}\"\nAllocator := (use \"std/mem\").Allocator\n\npub open_readonly := (path: *any) i32 => platform.open_readonly(path)\npub close := (fd: i32) i32 => platform.close(fd)\npub read := (fd: i32, buf: *any, len: usize) isize => platform.read(fd, buf, len)\npub write := (fd: i32, buf: *any, len: usize) isize => platform.write(fd, buf, len)\npub getenv := (name: *any) ?*any => platform.getenv(name)\npub fork := () i32 => platform.fork()\npub execvp := (file: *any, argv: *any) i32 => platform.execvp(file, argv)\npub waitpid := (pid: i32, status: *i32, options: i32) i32 => platform.waitpid(pid, status, options)\npub exit := (code: i32) {{ platform.exit(code); return }}\npub wexitstatus := (status: i32) i32 => platform.wexitstatus(status)\npub spawn_process := (file: *any, argv: *any) i32 => platform.spawn_process(file, argv)\npub path_sep := () u8 => platform.path_sep()\npub path_is_abs := (path: []u8) u1 => platform.path_is_abs(path)\npub path_dirname := (path: []u8) []u8 => platform.path_dirname(path)\npub path_basename := (path: []u8) []u8 => platform.path_basename(path)\npub path_join := (base: []u8, part: []u8, alloc: Allocator) ?[]u8 => platform.path_join(base, part, alloc)\npub process_args := (alloc: Allocator) ?[][]u8 => platform.process_args(alloc)\n"
    )
}

fn generated_std_host_platform_file() -> Result<PathBuf, ModuleResolverError> {
    let platform = configured_std_host_platform();
    let path = std::env::temp_dir().join(format!("dyn_std_host_{platform}.dyn"));
    let desired = generated_std_host_platform_source();
    let current = fs::read_to_string(&path).unwrap_or_default();
    if current == desired {
        return Ok(path);
    }
    fs::write(&path, desired).map_err(|source| ModuleResolverError::Io {
        path: path.clone(),
        source,
    })?;
    Ok(path)
}

pub fn normalize_import_path(import_path: &str) -> String {
    import_path.trim_matches('"').trim().to_string()
}

pub fn module_key_for_import(current: &ModuleKey, import_path: &str) -> ModuleKey {
    let normalized = normalize_import_path(import_path);

    // Relative imports start with "./" or "../"
    let is_relative = normalized.starts_with("./") || normalized.starts_with("../");
    // Stdlib imports start with "std/"
    let is_std_absolute = normalized.starts_with("std/");

    let mut parts = normalized
        .split('/')
        .filter(|segment| !segment.is_empty())
        .collect::<Vec<_>>();

    if parts.is_empty() {
        return current.clone();
    }

    let module_name = parts.pop().unwrap_or_default().to_string();

    let mut directory = if is_relative {
        // Resolve relative to current module's directory
        current.directory.clone()
    } else {
        // Project-root-absolute (including std/): start from root "."
        PathBuf::new()
    };

    for segment in &parts {
        match *segment {
            "." => {} // current dir — no-op
            ".." => {
                // Go up one level
                if !directory.pop() {
                    // Already at root; can't go higher
                }
            }
            s => directory.push(s),
        }
    }

    if directory.as_os_str().is_empty() {
        directory = PathBuf::from(".");
    }

    // For std imports: the "std" segment is part of the directory, not a module name.
    // Parts already includes "std" as first segment which gets pushed onto directory.
    let _ = is_std_absolute; // consumed implicitly via root-absolute behavior

    ModuleKey {
        directory,
        module_name,
    }
}

pub fn resolve_graph_file_path(graph: &ModuleGraph, logical_file_path: &Path) -> PathBuf {
    if normalize_diagnostic_path(logical_file_path) == STD_HOST_LOGICAL_PATH {
        if let Ok(path) = generated_std_host_platform_file() {
            return path;
        }
    }

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
    resolve_module_graph_with_bin(start_dir, None)
}

pub fn resolve_module_graph_with_bin<P: AsRef<Path>>(
    start_dir: P,
    bin: Option<&str>,
) -> Result<ModuleGraph, ModuleResolverError> {
    let mut graph = build_raw_module_graph(start_dir)?;
    filter_graph_to_reachable_modules(&mut graph, bin);
    Ok(graph)
}

pub(crate) fn build_raw_module_graph<P: AsRef<Path>>(
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

    // Detect conflict: X.dyn and X/*.dyn both declaring module X in the same group.
    // A file is "hoisted" if its parent dir name matches the module name (i.e. it came
    // from a directory). A file is "flat" if its parent dir matches the key's directory
    // directly. If a group contains both, it's an ambiguous definition.
    let mut conflict_keys: Vec<ModuleKey> = Vec::new();
    for (key, files) in &groups {
        let has_flat = files
            .iter()
            .any(|f| relative_directory_of(f) == key.directory);
        let has_hoisted = files.iter().any(|f| {
            let d = relative_directory_of(f);
            d != key.directory
                && d.file_name().and_then(|n| n.to_str()) == Some(key.module_name.as_str())
        });
        if has_flat && has_hoisted {
            conflict_keys.push(key.clone());
        }
    }
    for key in conflict_keys {
        let files = groups.remove(&key).unwrap_or_default();
        let dir_display = key.directory.display().to_string();
        let name = &key.module_name;
        let hint = if dir_display == "." {
            format!("use either {name}.dyn or {name}/*.dyn, not both")
        } else {
            format!(
                "use either {dir}/{name}.dyn or {dir}/{name}/*.dyn, not both",
                dir = dir_display,
                name = name
            )
        };
        for file in files {
            diagnostics.push(
                Diagnostic::error(
                    DiagnosticPhase::ModuleResolver,
                    DiagnosticCode::E1005,
                    format!("ambiguous module definition for '{name}'"),
                )
                .with_primary_file_label(file, None, hint.as_str()),
            );
        }
    }

    sort_diagnostics_by_primary_path(&mut diagnostics);
    let (modules, key_to_id) = build_module_index(&groups);

    Ok(ModuleGraph {
        root_dir: start_dir,
        groups,
        diagnostics,
        modules,
        key_to_id,
    })
}

fn scan_use_import_paths(source: &str) -> Vec<String> {
    let mut paths = Vec::new();
    for line in source.lines() {
        let code = if let Some(comment_start) = line.find("//") {
            &line[..comment_start]
        } else {
            line
        };
        let mut remaining = code;
        while let Some(idx) = remaining.find("use \"") {
            remaining = &remaining[idx + 5..];
            if let Some(end) = remaining.find('"') {
                paths.push(remaining[..end].to_string());
                remaining = &remaining[end + 1..];
            } else {
                break;
            }
        }
    }
    paths
}

fn filter_graph_to_reachable_modules(graph: &mut ModuleGraph, bin: Option<&str>) {
    // Seed reachability from explicit entry modules.
    // If `--bin <name>` is given, start from that directory's modules.
    // Otherwise, start from root project modules only (`.`), then follow imports.
    let mut reachable: BTreeSet<ModuleKey> = BTreeSet::new();
    let mut queue: VecDeque<ModuleKey> = if let Some(bin_name) = bin {
        let bin_dir = PathBuf::from(bin_name);
        graph
            .key_to_id
            .keys()
            .filter(|key| key.directory == bin_dir)
            .cloned()
            .collect()
    } else {
        let mut roots = graph
            .key_to_id
            .keys()
            .filter(|key| key.directory == Path::new("."))
            .cloned()
            .collect::<VecDeque<_>>();
        if roots.is_empty() {
            roots = graph
                .key_to_id
                .keys()
                .filter(|key| !key.directory.starts_with("std"))
                .cloned()
                .collect();
        }
        roots
    };

    while let Some(key) = queue.pop_front() {
        if !reachable.insert(key.clone()) {
            continue;
        }
        let Some(files) = graph.groups.get(&key).cloned() else {
            continue;
        };
        for file in &files {
            let abs_path = resolve_graph_file_path(graph, file);
            let Ok(source) = fs::read_to_string(&abs_path) else {
                continue;
            };
            for import_path in scan_use_import_paths(&source) {
                let imported_key = module_key_for_import(&key, &import_path);
                if !reachable.contains(&imported_key) && graph.key_to_id.contains_key(&imported_key)
                {
                    queue.push_back(imported_key);
                }
            }
        }
    }

    graph.groups.retain(|key, _| reachable.contains(key));
    let retained_files = graph
        .groups
        .values()
        .flat_map(|files| files.iter())
        .map(|path| normalize_diagnostic_path(path))
        .collect::<BTreeSet<_>>();
    graph.diagnostics.retain(|diagnostic| {
        diagnostic.labels.is_empty()
            || diagnostic
                .labels
                .iter()
                .any(|label| retained_files.contains(&normalize_diagnostic_path(&label.file_path)))
    });
    sort_diagnostics_by_primary_path(&mut graph.diagnostics);
    let (modules, key_to_id) = build_module_index(&graph.groups);
    graph.key_to_id = key_to_id;
    graph.modules = modules;
}

pub fn resolve_modules<P: AsRef<Path>>(start_dir: P) -> Result<ModuleGroups, ModuleResolverError> {
    let graph = resolve_module_graph(start_dir)?;
    Ok(graph.groups)
}

fn build_module_index(
    groups: &ModuleGroups,
) -> (Vec<ResolvedModule>, BTreeMap<ModuleKey, ModuleId>) {
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

    (modules, key_to_id)
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

    let file_dir = relative_directory_of(&logical_file_path);
    let file_stem = logical_file_path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_string();
    let dir_name = file_dir.file_name().and_then(|n| n.to_str());

    let key = if dir_name == Some(module_name.as_str()) {
        // Directory module: parser/lexer.dyn declares module parser — hoist to parent
        let grandparent = file_dir
            .parent()
            .map(|p| {
                if p.as_os_str().is_empty() {
                    Path::new(".")
                } else {
                    p
                }
            })
            .unwrap_or(Path::new("."));
        ModuleKey {
            directory: grandparent.to_path_buf(),
            module_name,
        }
    } else if file_dir == Path::new(".") || module_name == file_stem.as_str() {
        // Root files can declare any module name.
        // Subdirectory files declaring their file stem are single-file submodules.
        ModuleKey {
            directory: file_dir,
            module_name,
        }
    } else {
        // In a subdirectory and matches neither file stem nor directory name
        let d = dir_name.unwrap_or("?");
        diagnostics.push(
            Diagnostic::error(
                DiagnosticPhase::ModuleResolver,
                DiagnosticCode::E1006,
                format!("module name '{module_name}' does not match the file or directory name"),
            )
            .with_primary_file_label(
                logical_file_path,
                None,
                format!("expected 'module {file_stem}' or 'module {d}'"),
            ),
        );
        return;
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
