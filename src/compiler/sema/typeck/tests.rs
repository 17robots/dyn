use super::*;
use crate::compiler::pipeline::parse_project_with_module_units;
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

fn make_temp_dir() -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time should be monotonic")
        .as_nanos();
    let path = std::env::temp_dir().join(format!("dyn_typeck_{unique}"));
    fs::create_dir_all(&path).expect("temp directory should be created");
    path
}

mod builtins;
mod core;
mod diagnostics;
mod errors;
mod generics;
mod numeric;
mod pointers;
