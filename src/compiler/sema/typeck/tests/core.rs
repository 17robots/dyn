use super::*;

#[test]
fn type_checks_match_identifier_binding_in_arm_value() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na: i32 = match 1 { x: x + 1, _: 0 }\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(!diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("invalid operands for numeric operator")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn accepts_u1_annotation_with_bool_literal() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  mut d: u1 = false\n  d = true\n  return if d 1 else 0\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(!diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn rejects_legacy_bytes_type_alias_annotation() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\nb: bytes = \"hi\"\n")
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("'bytes' is not a language type; use []u8")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn accepts_comptime_zero_arg_function_call_expression() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmake := () i32 => 1\na := comp make()\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(!diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("comptime expression must be compile-time evaluable")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn accepts_comptime_function_call_with_value_arguments() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nid := (x: i32) i32 => x\na := comp id(1)\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(!diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("comptime expression must be compile-time evaluable")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}
