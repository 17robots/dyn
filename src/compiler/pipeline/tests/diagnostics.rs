use super::*;

#[test]
fn returns_diagnostics_when_build_has_no_main() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module other\na := 1\n").expect("file should be written");

    let (_artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E5002));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn returns_diagnostics_for_immutable_mut_receiver_method_call() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nmain := () i32 {\n  t := Thing{}\n  return t.touch()\n}\n",
        )
        .expect("file should be written");

    let (_artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4006
            && diagnostic
                .message
                .contains("cannot call mut receiver method on immutable value")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn returns_diagnostics_for_immutable_field_mut_receiver_method_call() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nHolder := struct { item: Thing }\nmain := () i32 {\n  h := Holder{item: Thing{}}\n  h.item.touch()\n}\n",
        )
        .expect("file should be written");

    let (_artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4006
            && diagnostic
                .message
                .contains("cannot call mut receiver method on immutable value")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn returns_diagnostics_for_invalid_named_struct_offsetof_designator() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nData := struct { a: u8, b: i32 }\nmain := () i32 {\n  $as(i32, $offsetof(Data, c))\n}\n",
        )
        .expect("file should be written");

    let (_artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("$offsetof field designator is invalid for named struct type")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn returns_diagnostics_for_mut_receiver_call_on_temporary() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nmain := () i32 {\n  Thing{}.touch()\n}\n",
        )
        .expect("file should be written");

    let (_artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4006
            && diagnostic
                .message
                .contains("cannot call mut receiver method on immutable value")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn allows_general_inline_expression_shape() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  _v := inline (1 + 2)\n  return 0\n}\n",
    )
    .expect("file should be written");

    let (_artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(
        !diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4012),
        "diagnostics: {diagnostics:#?}"
    );

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn allows_forced_inline_call_with_non_inlineable_body() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nstep := (x: i32) i32 {\n  return x + 1\n}\nmain := () i32 {\n  return inline step(41)\n}\n",
        )
        .expect("file should be written");

    let (_artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(
        !diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4010),
        "diagnostics: {diagnostics:#?}"
    );

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn allows_implicit_inline_call_when_inlining_falls_back_to_call() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\ninline_loop := inline (x: i32) i32 => inline_loop(x)\nmain := () i32 {\n  return inline_loop(41)\n}\n",
        )
        .expect("file should be written");

    let (_artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(
        !diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4010),
        "diagnostics: {diagnostics:#?}"
    );

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn allows_inline_for_with_runtime_evaluable_bounds() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nlimit := () i32 => match 1 {\n  1 => 3,\n  _ => 0,\n}\nmain := () i32 {\n  mut total := 0\n  inline for 0..limit(): |i| {\n    total += i\n  }\n  return total\n}\n",
        )
        .expect("file should be written");

    let (_artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(
        !diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E4011),
        "diagnostics: {diagnostics:#?}"
    );

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn returns_diagnostics_when_comptime_call_cannot_be_evaluated() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nstep := (x: i32) i32 => match x {\n  0 => 1,\n  _ => x,\n}\nmain := () i32 {\n  return comp step(41)\n}\n",
        )
        .expect("file should be written");

    let (_artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4009
            && diagnostic
                .message
                .contains("comptime expression must be compile-time evaluable")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_strict_return_error_for_i32_main_without_explicit_return() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  1\n}\n",
    )
    .expect("file should be written");

    let (_artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("function must use explicit return statements in strict return mode")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn returns_diagnostics_for_global_print_without_io_import() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  print(\"hello\")\n  return 0\n}\n",
    )
    .expect("file should be written");

    let (_artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4001));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn returns_diagnostics_for_backend_unsupported_float_width() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  _v := $as(f256, 1.0)\n  return 0\n}\n",
    )
    .expect("file should be written");

    let (_artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(
        diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E5002
                && diagnostic.message.contains("unsupported float width")),
        "diagnostics: {diagnostics:#?}"
    );

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn returns_diagnostics_for_backend_unsupported_integer_width() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  _v := $as(i129, 1)\n  return 0\n}\n",
    )
    .expect("file should be written");

    let (_artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(
        diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == DiagnosticCode::E5002
                && diagnostic.message.contains("unsupported integer width")),
        "diagnostics: {diagnostics:#?}"
    );

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn returns_diagnostics_for_error_unwrap_propagation_with_undeclared_error_set() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nE1 := enum { One }\nE2 := enum { Two }\nwork := () i32!E2 => .Two\nforward := () i32!E1 => work().!\nmain := () i32 {\n  forward() or return 9\n  return 0\n}\n",
        )
        .expect("file should be written");

    let (_artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("error unwrap may propagate undeclared errors")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn returns_diagnostics_for_rootless_error_variant_not_in_declared_error_set() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nE1 := enum { One }\nE2 := enum { Two }\nbad := () i32!E1 => .Two\nmain := () i32 => bad() or return 9\n",
        )
        .expect("file should be written");

    let (_artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("returned error variant is not defined on enum")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn returns_diagnostics_for_parser_syntax_error() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  return )\n}\n",
    )
    .expect("file should be written");

    let (_artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E3002));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}
