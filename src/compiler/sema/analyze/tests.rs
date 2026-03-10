use super::*;
use crate::compiler::pipeline::parse_project_with_module_units;
use std::fs;
use std::time::{SystemTime, UNIX_EPOCH};

fn make_temp_dir() -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time should be monotonic")
        .as_nanos();

    let path = std::env::temp_dir().join(format!("dyn_semantic_{unique}"));
    fs::create_dir_all(&path).expect("temp directory should be created");
    path
}

#[test]
fn reports_duplicate_declarations_per_module() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\na := 1\n").expect("file should be written");
    fs::write(root.join("b.dyn"), "module main\na := 2\n").expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let sema = analyze_modules(&units);
    assert!(sema
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4002));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn resolves_and_reports_import_targets() {
    let root = make_temp_dir();
    fs::write(
        root.join("main.dyn"),
        "module main\nok := use \"other\"\nbad := use \"missing\"\n",
    )
    .expect("file should be written");
    fs::write(root.join("other.dyn"), "module other\nval := 1\n").expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let sema = analyze_modules(&units);

    let main = sema
        .modules
        .iter()
        .find(|module| module.key.module_name == "main")
        .expect("main module should exist");
    assert_eq!(main.imports.len(), 2);
    assert!(main
        .imports
        .iter()
        .any(|import| import.path == "other" && import.target.is_some()));
    assert!(main
        .imports
        .iter()
        .any(|import| import.path == "missing" && import.target.is_none()));
    assert!(sema
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4003));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_unresolved_names() {
    let root = make_temp_dir();
    fs::write(root.join("main.dyn"), "module main\na := missing_name\n")
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let sema = analyze_modules(&units);

    assert!(sema
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4001));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_out_of_scope_names_with_declaration_location() {
    let root = make_temp_dir();
    fs::write(
        root.join("main.dyn"),
        "module main\nmain := () i32 {\n  {\n    temp := 1\n  }\n  return temp\n}\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let sema = analyze_modules(&units);

    let diagnostic = sema
        .diagnostics
        .iter()
        .find(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4001 && diagnostic.message.contains("out of scope")
        })
        .expect("out-of-scope diagnostic should be present");
    assert!(diagnostic.labels.iter().any(|label| !label.is_primary));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_private_member_access_from_imported_module() {
    let root = make_temp_dir();
    fs::write(
        root.join("main.dyn"),
        "module main\nmod_ref := use \"other\"\nx := mod_ref.secret\ny := mod_ref.open\n",
    )
    .expect("file should be written");
    fs::write(
        root.join("other.dyn"),
        "module other\nsecret := 1\npub open := 2\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let sema = analyze_modules(&units);

    assert!(sema
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4004));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn resolves_match_binding_in_guard_scope() {
    let root = make_temp_dir();
    fs::write(
        root.join("main.dyn"),
        "module main\ncheck := (v: i32) i32 => match v { x if x > 0: x, _: 0 }\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let sema = analyze_modules(&units);

    assert!(!sema
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4001));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_unresolved_name_inside_match_guard() {
    let root = make_temp_dir();
    fs::write(
        root.join("main.dyn"),
        "module main\ncheck := (v: i32) i32 => match v { x if missing_name: x, _: 0 }\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let sema = analyze_modules(&units);

    assert!(sema.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4001 && diagnostic.message.contains("missing_name")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_duplicate_bindings_in_enum_pattern() {
    let root = make_temp_dir();
    fs::write(
        root.join("main.dyn"),
        "module main\ncheck := (v: i32) i32 => match v { .Value(a, a): a, _: 0 }\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let sema = analyze_modules(&units);

    assert!(sema.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4002 && diagnostic.message.contains("duplicate binding")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn resolves_if_capture_binding_in_then_branch() {
    let root = make_temp_dir();
    fs::write(
        root.join("main.dyn"),
        "module main\ncheck := (n: ?i32) i32 => if n: |v| v else 0\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let sema = analyze_modules(&units);

    assert!(!sema.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4001 && diagnostic.message.contains("'v'")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn resolves_or_else_capture_binding_in_fallback() {
    let root = make_temp_dir();
    fs::write(
        root.join("main.dyn"),
        "module main\ncheck := (n: ?i32) i32 => n or |err| err\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let sema = analyze_modules(&units);

    assert!(!sema.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4001 && diagnostic.message.contains("'err'")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn accepts_allocator_dollar_builtin_in_resolution() {
    let root = make_temp_dir();
    fs::write(root.join("main.dyn"), "module main\na := $alloc(16, 8)\n")
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let sema = analyze_modules(&units);

    assert!(!sema
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4001));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}
