use super::*;

#[test]
fn allows_widening_unsigned_into_signed() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\na: i32 = 255\n").expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(!diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn accepts_narrow_integer_annotation_for_fitting_literal() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\na: i31 = 3\n").expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(!diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn accepts_f32_annotation_for_float_literal() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\na: f32 = 1.5\n").expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(!diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn accepts_array_annotation_for_integer_literal_elements() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\nxs: [3]i32 = [1, 2, 3]\n")
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
fn accepts_array_annotation_for_narrow_float_literal_elements() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\nxs: [1]f32 = [1.0]\n")
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
fn allows_literal_argument_for_narrow_integer_parameter() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nf := (x: i31) i31 => x\nok: i31 = f(3)\n",
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
fn rejects_out_of_range_integer_literal_for_narrow_annotation() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\na: i8 = 1000\n").expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn rejects_signed_into_narrow_unsigned() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\na: u8 = -1\n").expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_incompatible_match_pattern_for_scrutinee() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := match 1 { \"x\": 1, _: 0 }\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic.message.contains("pattern is incompatible")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_enum_pattern_incompatible_with_numeric_scrutinee() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := match 1 { .Ok: 1, _: 0 }\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("enum pattern requires enum-typed scrutinee")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_non_numeric_range_pattern_endpoints() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := match 1 { \"a\"..\"z\": 1, _: 0 }\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("range endpoint literal is incompatible")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_mixed_numeric_range_endpoint_kinds() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := match 1 { 1..2.0: 1, _: 0 }\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("range endpoint literal is incompatible")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_float_range_for_integer_scrutinee() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := match 1 { 1.0..2.0: 1, _: 0 }\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("range endpoint literal is incompatible")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_enum_literal_variant_mismatch_in_match_pattern() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := match .Ready { .Waiting: 1, _: 0 }\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic.message.contains("variant does not match")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_enum_literal_payload_arity_mismatch_in_match_pattern() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := match .Ready(1) { .Ready(x, y): x, _: 0 }\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005 && diagnostic.message.contains("payload arity")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn accepts_tuple_index_with_compile_time_literal() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\na: i32 = {1, 2, 3}[1]\n")
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
fn reports_non_literal_tuple_index() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nidx := 1\na := {1, 2, 3}[idx]\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("tuple index must be a compile-time integer literal")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}
