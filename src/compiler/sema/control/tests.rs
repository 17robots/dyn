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
    let path = std::env::temp_dir().join(format!("dyn_control_{unique}"));
    fs::create_dir_all(&path).expect("temp directory should be created");
    path
}

#[test]
fn reports_break_continue_outside_loop() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := break\nb := continue\n",
    )
    .expect("file should be written");
    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = control_check_modules(&units);
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4007));
    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn allows_break_value_inside_or_fallback_block() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nn: ?i32 = null\na := n or { break 1 }\n",
    )
    .expect("file should be written");
    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = control_check_modules(&units);
    assert!(!diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4007));
    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_non_exhaustive_match() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nv := 1\na := match v { 1: 1 }\n",
    )
    .expect("file should be written");
    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = control_check_modules(&units);
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4008));
    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn treats_unguarded_enum_variant_match_as_exhaustive_without_type_info() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nv := .A\na := match v { .A: 1, .B: 0 }\n",
    )
    .expect("file should be written");
    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = control_check_modules(&units);
    assert!(!diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4008));
    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn accepts_exhaustive_bool_match_without_wildcard() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := match true { true: 1, false: 0 }\n",
    )
    .expect("file should be written");
    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = control_check_modules(&units);
    assert!(!diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4008));
    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn checks_control_flow_inside_function_body() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := () { return break }\n",
    )
    .expect("file should be written");
    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = control_check_modules(&units);
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4007));
    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn checks_control_flow_inside_match_guard() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := match 1 { 1 if break: 1, _: 0 }\n",
    )
    .expect("file should be written");
    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = control_check_modules(&units);
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4007));
    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn guarded_wildcard_does_not_count_as_exhaustive() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := match 1 { _ if false: 1 }\n",
    )
    .expect("file should be written");
    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = control_check_modules(&units);
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4008));
    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn guarded_bool_arm_does_not_count_as_exhaustive() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := match true { true if false: 1, false: 0 }\n",
    )
    .expect("file should be written");
    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = control_check_modules(&units);
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4008));
    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn guarded_ident_binding_does_not_count_as_exhaustive() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := match 1 { x if false: x }\n",
    )
    .expect("file should be written");
    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = control_check_modules(&units);
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4008));
    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn unguarded_ident_binding_counts_as_exhaustive() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\na := match 1 { x: x }\n")
        .expect("file should be written");
    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = control_check_modules(&units);
    assert!(!diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4008));
    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn literal_bool_scrutinee_single_matching_arm_is_exhaustive() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := match true { true: 1 }\n",
    )
    .expect("file should be written");
    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = control_check_modules(&units);
    assert!(!diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4008));
    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn literal_int_scrutinee_range_covering_value_is_exhaustive() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := match 5 { 1..=10: 1 }\n",
    )
    .expect("file should be written");
    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = control_check_modules(&units);
    assert!(!diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4008));
    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn literal_enum_scrutinee_matching_arm_is_exhaustive() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := match .Ready { .Ready: 1 }\n",
    )
    .expect("file should be written");
    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = control_check_modules(&units);
    assert!(!diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4008));
    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn literal_enum_scrutinee_non_matching_arm_is_not_exhaustive() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := match .Ready { .Waiting: 1 }\n",
    )
    .expect("file should be written");
    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = control_check_modules(&units);
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4008));
    fs::remove_dir_all(root).expect("temp directory should be removed");
}
