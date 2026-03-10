use super::*;

#[test]
fn builds_native_executable_with_comptime_function_returning_function_value() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\ninc := (x: i32) i32 => x + 1\nmake := () fn(i32) i32 => inc\nmain := () i32 {\n  f := comp make()\n  return f(41)\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(42));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_inline_for_range_unroll() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  mut total := 0\n  inline for 1..5: |i| {\n    total += i\n  }\n  return total\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(10));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_inline_function_call_site_paste() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\ninline_inc := inline (x: i32) i32 => x + 1\nmain := () i32 => inline_inc(41)\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(42));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_forced_inline_local_function_call() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  step := (x: i32) i32 => x + 1\n  return inline step(41)\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(42));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_comptime_local_immutable_binding() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  x := 3\n  y := comp x\n  return y\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(!diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4009));

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(3));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_comptime_local_expression_binding() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  x := 1\n  y := x + 2\n  z := comp y\n  return z\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(!diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4009));

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(3));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_comptime_local_after_direct_assignment() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  mut x := 1\n  x = 3\n  y := comp x\n  return y\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(!diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4009));

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(3));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_comptime_local_function_call() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  x := 3\n  f := () i32 => x\n  y := comp f()\n  return y\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(!diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4009));

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(3));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn deduplicates_duplicate_comptime_diagnostics_from_typecheck_and_mir() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  _x := comp (match 1 {\n    1: 2,\n    _: 3,\n  })\n  return 0\n}\n",
        )
        .expect("file should be written");

    let (_artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    let comptime_errors = diagnostics
        .iter()
        .filter(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4009
                && diagnostic
                    .message
                    .contains("comptime expression must be compile-time evaluable")
        })
        .count();
    assert_eq!(comptime_errors, 1, "diagnostics: {diagnostics:#?}");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_comptime_sizeof_type_constructor_call() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nVec := (T: type) type => struct { items: []T }\nmain := () i32 {\n  s := comp $sizeof(Vec(i32))\n  return $as(i32, s)\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(16));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}
