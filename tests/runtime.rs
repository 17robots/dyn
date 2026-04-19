use dyn_compiler::compiler::backend::BuildConfig;
use dyn_compiler::compiler::diagnostics::DiagnosticSeverity;
use dyn_compiler::compiler::pipeline::build_project_with_config;
use std::path::{Path, PathBuf};
use std::process::Command;

fn runtime_cases_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests")
        .join("cases")
        .join("runtime")
}

fn build_and_run(case: &str) -> std::process::Output {
    let dir = runtime_cases_dir().join(case);
    let dir_str = dir.to_str().expect("non-UTF-8 runtime test path");

    let (artifact, diagnostics) = build_project_with_config(dir_str, None, BuildConfig::default())
        .unwrap_or_else(|e| panic!("runtime/{case}: module resolver error: {e}"));

    let errors: Vec<_> = diagnostics
        .iter()
        .filter(|d| d.severity == DiagnosticSeverity::Error)
        .collect();

    assert!(
        errors.is_empty(),
        "runtime/{case}: expected zero build errors, got {}:\n{}",
        errors.len(),
        errors
            .iter()
            .map(|d| format!("  [{}] {}", d.code, d.message))
            .collect::<Vec<_>>()
            .join("\n")
    );

    Command::new(&artifact.executable_path)
        .current_dir(&dir)
        .output()
        .unwrap_or_else(|e| {
            panic!(
                "runtime/{case}: failed to run {}: {e}",
                artifact.executable_path.display()
            )
        })
}

#[test]
fn runtime_hello_world_builds_and_runs() {
    let output = build_and_run("../pass/hello_world");
    assert!(
        output.status.success(),
        "runtime/hello_world: program failed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}

#[test]
fn runtime_local_associated_decls_exit() {
    let output = build_and_run("../pass/local_associated_decls");
    assert_eq!(
        output.status.code(),
        Some(0),
        "runtime/local_associated_decls: bad exit code\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}

#[test]
fn runtime_function_surface_parity_exit() {
    let output = build_and_run("../pass/function_surface_parity");
    assert_eq!(
        output.status.code(),
        Some(0),
        "runtime/function_surface_parity: bad exit code\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}

#[test]
#[ignore = "native runtime stdout path still silent even for direct std/os writes"]
fn runtime_std_os_write() {
    let output = build_and_run("std_os_write");
    assert!(
        output.status.success(),
        "runtime/std_os_write: program failed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );

    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "xy\n");
}

#[test]
#[ignore = "native runtime stdout path still silent for std-backed printing"]
fn runtime_std_io_print() {
    let output = build_and_run("std_io_print");
    assert!(
        output.status.success(),
        "runtime/std_io_print: program failed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );

    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "abc\ntrue\n123\n-45\n1.5\n");
}

#[test]
fn runtime_enum_variant_capture_exit() {
    let output = build_and_run("enum_variant_capture_exit");
    assert_eq!(
        output.status.code(),
        Some(7),
        "runtime/enum_variant_capture_exit: bad exit code\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}

#[test]
fn runtime_typed_empty_slice_exit() {
    let output = build_and_run("typed_empty_slice_exit");
    assert_eq!(
        output.status.code(),
        Some(7),
        "runtime/typed_empty_slice_exit: bad exit code\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}

#[test]
fn runtime_declare_persistence_exit() {
    let output = build_and_run("declare_persistence_exit");
    assert_eq!(
        output.status.code(),
        Some(7),
        "runtime/declare_persistence_exit: bad exit code\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}

#[test]
fn runtime_dyn_trait_impl_exit() {
    let output = build_and_run("dyn_trait_impl_exit");
    assert_eq!(
        output.status.code(),
        Some(7),
        "runtime/dyn_trait_impl_exit: bad exit code\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}
