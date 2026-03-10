use super::*;
use crate::compiler::mir::{
    MirBasicBlock, MirBlockId, MirFunction, MirInstr, MirModule, MirTerminator, MirValue,
    MirValueType,
};
use crate::compiler::module_resolver::ModuleKey;
use std::path::Path;
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

mod builtins;
mod comptime;
mod core;
mod diagnostics;
mod execution;
mod io;
mod runtime;
mod stdlib;
