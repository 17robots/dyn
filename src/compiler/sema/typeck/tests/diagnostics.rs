use super::*;

#[test]
fn reports_type_mismatch_on_annotated_binding() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\na: i32 = 1.0\n").expect("file should be written");
    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));
    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_null_assignment_without_mut() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\na: ?i32 = null\n").expect("file should be written");
    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4006));
    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_call_arity_issues() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nadd := (x: i32, y: i32) i32 => x + y\na := add(1)\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));
    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_direct_call_argument_type_mismatch() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nadd := (x: i32, y: i32) i32 => x + y\na := add(true, 2)\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic.message.contains("call argument type mismatch")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_non_bool_match_guard_type() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := match 1 { 1 if 2: 1, _: 0 }\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005 && diagnostic.message.contains("match guard")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_call_on_non_callable_value() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  x := 1\n  return x()\n}\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005 && diagnostic.message.contains("not a function")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_inline_for_with_non_comptime_bounds() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nlimit := 3\nmain := () i32 {\n  inline for 0..limit: |i| {\n    _v := i\n  }\n  return 0\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4011
            && diagnostic
                .message
                .contains("inline for requires compile-time range bounds")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_unsupported_inline_expression_kind() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  _x := inline (1 + 2)\n  return 0\n}\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4012
            && diagnostic.message.contains("unsupported inline expression")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}
