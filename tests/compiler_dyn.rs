use dyn_compiler::compiler::diagnostics::DiagnosticSeverity;
use dyn_compiler::compiler::pipeline::analyze_project;

#[test]
fn compiler_dyn_analyzes_cleanly() {
    let (_, _, sema) = analyze_project("compiler-dyn")
        .unwrap_or_else(|e| panic!("compiler-dyn: module resolver error: {e}"));

    let errors: Vec<_> = sema
        .diagnostics
        .iter()
        .filter(|d| d.severity == DiagnosticSeverity::Error)
        .collect();

    assert!(
        errors.is_empty(),
        "compiler-dyn: expected zero errors, got {}:\n{}",
        errors.len(),
        errors
            .iter()
            .map(|d| format!("  [{}] {}", d.code, d.message))
            .collect::<Vec<_>>()
            .join("\n")
    );
}
