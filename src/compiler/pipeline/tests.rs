use super::*;
use crate::compiler::mir::{
    MirBasicBlock, MirBlockId, MirFunction, MirInstr, MirModule, MirTerminator, MirValue,
    MirValueType,
};
use crate::compiler::module_resolver::ModuleKey;
use std::path::Path;
use std::process::Command;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

static TEMP_DIR_COUNTER: AtomicU64 = AtomicU64::new(0);

fn make_temp_dir() -> PathBuf {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time should be monotonic")
        .as_nanos();
    let counter = TEMP_DIR_COUNTER.fetch_add(1, Ordering::Relaxed);
    let pid = std::process::id();

    let path = std::env::temp_dir().join(format!("dyn_pipeline_{pid}_{now}_{counter}"));
    fs::create_dir_all(&path).expect("temp directory should be created");
    path
}

fn collect_files_with_extension(root: &Path, extension: &str, out: &mut Vec<PathBuf>) {
    let entries = fs::read_dir(root).expect("directory should be readable");
    for entry in entries {
        let entry = entry.expect("directory entry should be readable");
        let path = entry.path();
        let file_type = entry.file_type().expect("file type should be readable");
        if file_type.is_dir() {
            collect_files_with_extension(&path, extension, out);
            continue;
        }
        if path.extension().and_then(|ext| ext.to_str()) == Some(extension) {
            out.push(path);
        }
    }
}

fn write_dyn_file(root: &Path, relative_path: &str, source: &str) {
    fs::write(root.join(relative_path), source).expect("file should be written");
}

fn build_clean_project(root: &Path) -> crate::compiler::backend::BuildArtifact {
    let (artifact, diagnostics) = build_project(root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());
    artifact
}

fn run_exit_code(executable_path: &Path) -> Option<i32> {
    Command::new(executable_path)
        .status()
        .expect("executable should run")
        .code()
}

fn run_output(executable_path: &Path) -> std::process::Output {
    Command::new(executable_path)
        .output()
        .expect("executable should run")
}

fn run_output_in_dir(executable_path: &Path, current_dir: &Path) -> std::process::Output {
    Command::new(executable_path)
        .current_dir(current_dir)
        .output()
        .expect("executable should run")
}

fn run_exit_code_with_env(executable_path: &Path, key: &str, value: &str) -> Option<i32> {
    Command::new(executable_path)
        .env(key, value)
        .status()
        .expect("executable should run")
        .code()
}

mod builtins;
mod comptime;
mod core;
mod diagnostics;
mod execution;
mod io;
mod runtime;
mod stdlib;
