use super::*;

#[test]
fn infers_or_fallback_type_for_optional_values() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\na: i32 = (null or 1)\n")
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
fn infers_or_fallback_type_for_errorable_values() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nErr := enum { Bad }\nwork := () i32!Err => 1\na: i32 = work() or 0\n",
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
fn allows_or_fallback_error_capture_binding() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmut n: ?i32 = null\na: i32 = n or |err| if err == err 7 else 0\n",
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
fn allows_if_optional_capture_binding() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\ncheck := (n: ?i32) i32 => if n: |v| v else 0\n",
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
fn supports_force_unwrap_on_errorable_values() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nErr := enum { Bad }\nwork := () i32!Err => 1\na: i32 = work().!\n",
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
fn reports_error_when_returning_rootless_error_variant_not_in_declared_set() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nE1 := enum { One }\nE2 := enum { Two }\nbad := () i32!E1 => .Two\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("returned error variant is not defined on enum")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn allows_rootless_error_variant_when_single_declared_error_enum_matches() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nE := enum { Bad }\nok := () i32!E => .Bad\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(!diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("returned error is not in function error set")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn infers_error_set_when_error_union_list_is_empty_from_rootless_variant() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nE := enum { Bad }\nwork := () i32! => .Bad\nforward := () i32!E => work()\n",
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
fn infers_error_set_when_error_union_list_is_empty_from_error_unwrap() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nE := enum { Bad }\nbase := () i32!E => .Bad\nforward := () i32! => base().!\nsink := () i32!E => forward()\n",
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
fn infers_error_set_for_implicit_union_from_local_unwrap_binding() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nE := enum { Bad }\nbase := () i32!E => .Bad\nforward := () i32! {\n  tmp := base()\n  return tmp.!\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(!diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4005));

    let inferred = infer_binding_type_strings(&units);
    let module_id = units[0].module_id;
    let forward = inferred
        .get(&(module_id, "forward".to_string()))
        .expect("forward type should be inferred");
    assert!(forward.contains("!E"), "inferred type was {forward}");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn infers_rootless_error_variant_across_module_enums_when_unique() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nE1 := enum { One }\nE2 := enum { Two }\npick := () i32! => .Two\nsink := () i32!E2 => pick()\n",
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
fn reports_error_when_rootless_error_variant_is_ambiguous_across_declared_sets() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nE1 := enum { Bad }\nE2 := enum { Bad }\namb := () i32!E1,E2 => .Bad\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("unqualified returned error variant is ambiguous")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_error_when_returning_errorable_with_undeclared_error_set() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nE1 := enum { One }\nE2 := enum { Two }\nwork := () i32!E2 => .Two\nforward := () i32!E1 => work()\n",
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
fn reports_error_when_error_unwrap_propagates_undeclared_error_set() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nE1 := enum { One }\nE2 := enum { Two }\nwork := () i32!E2 => .Two\nforward := () i32!E1 => work().!\n",
        )
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("error unwrap may propagate undeclared errors")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn allows_error_unwrap_propagation_when_error_set_is_declared() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nE := enum { One, Two }\nwork := () i32!E => .One\nforward := () i32!E => work().!\n",
        )
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(!diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("error unwrap may propagate undeclared errors")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn suppresses_compound_assignment_type_error_when_operand_unknown() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  mut acc: i32 = 0\n  acc += missing\n  return acc\n}\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(!diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("compound assignment requires numeric target and value")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn allows_optional_branch_unification_with_null_and_value() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na: ?i32 = if true null else 1\n",
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
