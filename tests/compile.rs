//! Integration test harness for the Dyn compiler.
//!
//! # Test structure
//!
//! ```
//! tests/cases/
//!   pass/<name>/          — must compile with zero errors
//!     *.dyn               — source files
//!   fail/<name>/          — must produce at least one error
//!     *.dyn               — source files
//!     expected_error      — text that must appear in at least one diagnostic message
//! ```
//!
//! # Adding tests
//!
//! Pass test: create `tests/cases/pass/<name>/main.dyn`.
//! Fail test: create `tests/cases/fail/<name>/main.dyn` and `expected_error`.
//!
//! Tests are discovered and registered via the macro at the bottom of this file.

use dyn_compiler::compiler::diagnostics::DiagnosticSeverity;
use dyn_compiler::compiler::pipeline::analyze_project;
use std::path::Path;

// ── helpers ───────────────────────────────────────────────────────────────────

fn cases_dir() -> std::path::PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests")
        .join("cases")
}

/// Run a pass test: the project in `dir` must produce zero errors.
fn assert_compiles(name: &str) {
    let dir = cases_dir().join("pass").join(name);
    let dir_str = dir.to_str().expect("non-UTF-8 test path");

    let (_, _, sema) = analyze_project(dir_str)
        .unwrap_or_else(|e| panic!("pass/{name}: module resolver error: {e}"));

    let errors: Vec<_> = sema
        .diagnostics
        .iter()
        .filter(|d| d.severity == DiagnosticSeverity::Error)
        .collect();

    assert!(
        errors.is_empty(),
        "pass/{name}: expected zero errors, got {}:\n{}",
        errors.len(),
        errors
            .iter()
            .map(|d| format!("  [{}] {}", d.code, d.message))
            .collect::<Vec<_>>()
            .join("\n")
    );
}

/// Run a fail test: the project in `dir` must produce at least one error whose
/// message contains the text in `tests/cases/fail/<name>/expected_error`.
fn assert_fails(name: &str) {
    let dir = cases_dir().join("fail").join(name);
    let dir_str = dir.to_str().expect("non-UTF-8 test path");

    let expected_path = dir.join("expected_error");
    let expected = std::fs::read_to_string(&expected_path).unwrap_or_else(|_| {
        panic!(
            "fail/{name}: missing expected_error file at {}",
            expected_path.display()
        )
    });
    let expected = expected.trim();

    let (_, _, sema) = analyze_project(dir_str)
        .unwrap_or_else(|e| panic!("fail/{name}: module resolver error: {e}"));

    let errors: Vec<_> = sema
        .diagnostics
        .iter()
        .filter(|d| d.severity == DiagnosticSeverity::Error)
        .collect();

    assert!(
        !errors.is_empty(),
        "fail/{name}: expected at least one error, but compiled cleanly"
    );

    let found = errors.iter().any(|d| d.message.contains(expected));
    assert!(
        found,
        "fail/{name}: no error contained {:?}\nActual errors:\n{}",
        expected,
        errors
            .iter()
            .map(|d| format!("  [{}] {}", d.code, d.message))
            .collect::<Vec<_>>()
            .join("\n")
    );
}

// ── pass tests ────────────────────────────────────────────────────────────────

#[test]
fn pass_hello_world() {
    assert_compiles("hello_world");
}

#[test]
fn pass_arithmetic() {
    assert_compiles("arithmetic");
}

#[test]
fn pass_structs() {
    assert_compiles("structs");
}

#[test]
fn pass_enums() {
    assert_compiles("enums");
}

#[test]
fn pass_optionals() {
    assert_compiles("optionals");
}

#[test]
fn pass_closures() {
    assert_compiles("closures");
}

#[test]
fn pass_type_bindings() {
    assert_compiles("type_bindings");
}

#[test]
fn pass_generics() {
    assert_compiles("generics");
}

#[test]
fn pass_defer() {
    assert_compiles("defer");
}

#[test]
fn pass_multi_module() {
    assert_compiles("multi_module");
}

#[test]
fn pass_struct_literal_shorthand() {
    assert_compiles("struct_literal_shorthand");
}

#[test]
fn pass_mut_param_types() {
    assert_compiles("mut_param_types");
}

#[test]
fn pass_legacy_surface() {
    assert_compiles("legacy_surface");
}

#[test]
fn pass_if_statement_without_else() {
    assert_compiles("if_statement_without_else");
}

#[test]
fn pass_std_str() {
    assert_compiles("std_str");
}

#[test]
fn pass_std_collections() {
    assert_compiles("std_collections");
}

#[test]
fn pass_std_os() {
    assert_compiles("std_os");
}

// ── fail tests ────────────────────────────────────────────────────────────────

#[test]
fn fail_undeclared_var() {
    assert_fails("undeclared_var");
}

#[test]
fn fail_duplicate_decl() {
    assert_fails("duplicate_decl");
}

#[test]
fn fail_missing_import() {
    assert_fails("missing_import");
}

#[test]
fn fail_out_of_scope() {
    assert_fails("out_of_scope");
}

#[test]
fn fail_shadowing() {
    assert_fails("shadowing");
}

#[test]
fn fail_if_expr_missing_else() {
    assert_fails("if_expr_missing_else");
}

#[test]
fn fail_top_level_statement() {
    assert_fails("top_level_statement");
}

#[test]
fn fail_typed_struct_literal_missing_field() {
    assert_fails("typed_struct_literal_missing_field");
}

#[test]
fn fail_typed_struct_literal_unknown_field() {
    assert_fails("typed_struct_literal_unknown_field");
}

#[test]
fn fail_unsupported_struct_equality() {
    assert_fails("unsupported_struct_equality");
}

#[test]
fn fail_borrow_conflict() {
    assert_fails("borrow_conflict");
}

#[test]
fn fail_call_borrow_conflict() {
    assert_fails("call_borrow_conflict");
}

#[test]
fn fail_f128_removed() {
    assert_fails("f128_removed");
}

#[test]
fn fail_i256_removed() {
    assert_fails("i256_removed");
}

#[test]
fn fail_positional_after_named() {
    assert_fails("positional_after_named");
}

#[test]
fn fail_removed_fn_type_syntax() {
    assert_fails("removed_fn_type_syntax");
}

#[test]
fn fail_enum_body_member() {
    assert_fails("enum_body_member");
}

#[test]
fn fail_word_and_operator() {
    assert_fails("word_and_operator");
}
