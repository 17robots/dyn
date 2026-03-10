use super::*;

#[test]
fn accepts_applied_vec_type_annotation_shape() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nxs: Vec(i32) = placeholder\n",
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
fn reports_applied_vec_type_argument_mismatch() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na: Vec(i32) = placeholder\nb: Vec(u64) = a\n",
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
fn reports_function_value_call_arity_mismatch() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  f := (x: i32, y: i32) i32 => x + y\n  f(1)\n}\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005 && diagnostic.message.contains("arity mismatch")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_function_value_call_argument_type_mismatch() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  f := (x: i32) i32 => x\n  f(true)\n}\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("function value argument type mismatch")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_function_value_generic_argument_type_mismatch() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nid := (T: type, v: T) T => v\nmain := () i32 {\n  f := id\n  f(i32, true)\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("function value argument type mismatch")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn specializes_function_value_generic_return_type() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nid := (T: type, v: T) T => v\nmain := () i32 {\n  f := id\n  ok: i32 = f(i32, 1)\n  bad: u64 = f(i32, 1)\n  ok\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic.message.contains("type mismatch for 'bad'")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn accepts_type_designator_argument_for_type_parameter() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmeta := (T: type) type => T\nout: type = meta(i32)\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(!diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005 && diagnostic.message.contains("type designator")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_non_type_designator_argument_for_type_parameter() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmeta := (T: type) type => T\nout: type = meta(123)\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005 && diagnostic.message.contains("type designator")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn specializes_unknown_return_type_from_type_parameter_argument() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nid := (T: type, v: i32) T => v\nok: i32 = id(i32, 1)\nbad: u64 = id(i32, 1)\n",
        )
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic.message.contains("type mismatch for 'bad'")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn enforces_value_argument_against_bound_type_parameter() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nid := (T: type, v: T) T => v\nok: i32 = id(i32, 1)\nbad: i32 = id(i32, true)\n",
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
fn specializes_return_type_from_value_inferred_type_parameter() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nid := (v: T) T => v\nok: i32 = id(1)\nbad: u64 = id(1)\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic.message.contains("type mismatch for 'bad'")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn enforces_bound_type_parameter_with_named_arguments() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nid := (T: type, v: T) T => v\nok: i32 = id(v: 1, T: i32)\nbad: i32 = id(v: true, T: i32)\n",
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
fn accepts_generic_type_parameter_call_shape() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nprint := (T: type, value: T) i32 => if T == i32 1 else 0\nok := print(i32, 7)\n",
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
