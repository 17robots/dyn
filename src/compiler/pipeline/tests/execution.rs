use super::*;

#[test]
fn builds_native_executable_with_function_call_return() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nhelper := () i32 => 7\nmain := () i32 => helper()\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(7));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_function_call_arguments() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nadd := (x: i32, y: i32) i32 => x + y\nmain := () i32 => add(30, 41)\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(71));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_function_alias_call_return() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nhelper := () i32 => 73\nmain := () i32 {\n  f := helper\n  return f()\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(73));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_higher_order_function_parameter_call() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\ninc := (x: i32) i32 => x + 1\napply := (f, x: i32) i32 => f(x)\nmain := () i32 => apply(inc, 80)\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(81));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_typed_higher_order_function_parameter_call() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\ninc := (x: i32) i32 => x + 1\napply := (f: fn(i32) i32, x: i32) i32 => f(x)\nmain := () i32 => apply(inc, 82)\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(83));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_function_returning_function_value() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\ninc := (x: i32) i32 => x + 1\nmake := () fn(i32) i32 => inc\nmain := () i32 {\n  f := make()\n  return f(41)\n}\n",
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
fn builds_native_executable_with_local_noop_function_call() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  f := () {}\n  f()\n  return 9\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_default_argument_call() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nadd := (x: i32, y: i32 = 5) i32 => x + y\nmain := () i32 => add(70)\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(75));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_default_argument_call_via_alias() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nadd := (x: i32, y: i32 = 5) i32 => x + y\nmain := () i32 {\n  f := add\n  return f(70)\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(75));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_named_arguments_reordered_via_alias() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nadd := (x: i32, y: i32) i32 => x + y\nmain := () i32 {\n  f := add\n  return f(y: 12, x: 60)\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(72));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_named_arguments_reordered() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nadd := (x: i32, y: i32) i32 => x + y\nmain := () i32 => add(y: 12, x: 60)\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(72));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_named_and_default_arguments() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nscore := (a: i32, b: i32 = 2, c: i32 = 3) i32 => a + b + c\nmain := () i32 => score(c: 5, a: 10)\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(17));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_method_default_argument() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing, n: i32 = 7) i32 => n }\nmain := () i32 {\n  mut t := Thing{}\n  return t.touch()\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(7));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_method_named_argument() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing, n: i32 = 7) i32 => n }\nmain := () i32 {\n  mut t := Thing{}\n  return t.touch(n: 9)\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_generic_named_default_method_combo() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\ninc := (x: i32) i32 => x + 1\nThing := struct { run := (self: *mut Thing, f: fn(i32) i32, x: i32 = 40) i32 => f(x) }\nmain := () i32 {\n  mut t := Thing{}\n  _ignored := t.run(f: inc)\n  return t.run(f: inc, x: 2)\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(3));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_if_expression_return() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 { return if true 9 else 4 }\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_local_bindings() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 { x := 5 y := 8 return x + y }\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(13));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_comparison_and_logical_ops() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 => if (3 > 2) && (1 == 1) 21 else 0\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(21));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_float_expression_cast_to_main_exit() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () f64 => 1.5 + 2.5\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(4));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_calling_float_function() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nfoo := () f64 => 6.75\nmain := () f64 => foo()\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(6));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_narrow_unsigned_integer_wraparound() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nadd := (x: u7, y: u7) u7 => x + y\nmain := () i32 {\n  if add(120, 20) == 12 return 12\n  return 0\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(12));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_narrow_signed_integer_wraparound() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nadd := (a: i5, b: i5) i5 => a + b\nmain := () i32 {\n  if add(15, 3) < 0 return 14\n  return 0\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(14));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_annotated_local_narrow_integer_wraparound() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  mut x: u7 = 120\n  y: u7 = 20\n  x = x + y\n  if x == 12 return 13\n  return 0\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(13));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_f128_arithmetic_and_compare() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nadd := (lhs: f128, rhs: f128) f128 { return lhs + rhs }\nmain := () i32 {\n  a := $as(f128, 1.5)\n  b := $as(f128, 2.25)\n  c := add(a, b)\n  if c > $as(f128, 3.7) { return 7 }\n  return 1\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(7));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_f128_precision_beyond_f64() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  hi := $as(f128, 1.000000000000000000000000000001)\n  delta := hi - $as(f128, 1.0)\n  if delta > $as(f128, 0.0) { return 9 }\n  return 1\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_f128_integer_cast_roundtrip() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  a := $as(f128, 40.5)\n  b := a + $as(f128, 1.5)\n  c := $as(i32, b)\n  if c == 42 { return 10 }\n  return 1\n}\n",
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
fn builds_native_executable_with_f128_nan_comparisons() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  nan := $as(f128, 0.0) / $as(f128, 0.0)\n  if nan == nan return 1\n  if nan != nan return 17\n  return 2\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(17));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_f128_cast_saturates_small_int_widths() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  huge := $as(f128, 9999999999999999999999999999999999999.0)\n  tiny := $as(f128, -9999999999999999999999999999999999999.0)\n  hi: i8 = $as(i8, huge)\n  lo: i8 = $as(i8, tiny)\n  if hi != 127 { return 1 }\n  if lo != -128 { return 2 }\n  return 18\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(18));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_loop_break() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 { for { break } return 11 }\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(11));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_defer_executed_at_block_scope_exit() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  mut x := 0\n  {\n    defer { x = x + 1 }\n  }\n  if x == 1 return 31\n  return 0\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(31));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_defer_lifo_order_within_scope() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  mut x := 1\n  {\n    defer { x = x * 2 }\n    defer { x = x + 3 }\n  }\n  if x == 8 return 32\n  return 0\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(32));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_error_only_defer_on_error_path() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nio := use \"std/io\"\nErr := enum { Boom }\nwork := (fail: u1) i32!Err {\n  defer |e| { io.print(\"E\") or 0 }\n  if fail == true return .Boom\n  return 1\n}\nmain := () i32 {\n  work(true) or |err| {\n    io.print(\"X\") or 0\n    return 0\n  }\n  return 1\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let output = Command::new(&artifact.executable_path)
        .output()
        .expect("executable should run");
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "EX");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_error_only_defer_skipped_on_success() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nio := use \"std/io\"\nErr := enum { Boom }\nwork := (fail: u1) i32!Err {\n  defer |e| { io.print(\"E\") or 0 }\n  if fail == true return .Boom\n  return 2\n}\nmain := () i32 {\n  value := work(false) or return 1\n  if value != 2 return 2\n  io.print(\"S\") or 0\n  return 0\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let output = Command::new(&artifact.executable_path)
        .output()
        .expect("executable should run");
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "S");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_loop_continue_path() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 { for { if false { continue } break } return 12 }\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(12));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_while_like_loop_carried_local() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  mut total := 0\n  for total < 3: total += 1\n  return total\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(3));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_for_range_binding_sum() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  mut total = 0\n  for 0..=4: |v| total += v\n  return total\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(10));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_for_iterate_binding_sum() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  xs: [4]i32 = [1, 2, 3, 4]\n  mut total = 0\n  for xs: |v| total += v\n  return total\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(10));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_if_optional_capture_binding() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  n: ?i32 = 9\n  return if n: |v| v else 0\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_or_else_capture_binding() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  mut n: ?i32 = null\n  return n or |err| if err == err 7 else 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(7));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_optional_unwrap_success() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  n: ?i32 = 6\n  return n.?\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(6));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_optional_unwrap_trap_on_null() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  mut n: ?i32 = null\n  return n.?\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert!(!status.success());

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_error_unwrap_success() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nE := enum { Fail }\nok := () i32!E => 8\nmain := () i32 => ok().!\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(8));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_error_unwrap_trap_on_error() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nE := enum { Fail }\nfail := () i32!E => .Fail\nmain := () i32 => fail().!\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert!(!status.success());

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_error_unwrap_propagates_error_in_errorable_function() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nE := enum { Fail }\nfail := () i32!E => .Fail\nforward := () i32!E => fail().!\nmain := () i32 {\n  forward() or return 7\n  return 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(7));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_error_unwrap_propagates_success_value() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nE := enum { Fail }\nok := () i32!E => 9\nforward := () i32!E => ok().!\nmain := () i32 => forward() or return 7\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_source_match_guard_and_range() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  v := 2\n  return match v {\n    0..1: 4,\n    2 if true: 9,\n    _: 0,\n  }\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_source_enum_variant_match_binding() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nState := enum { Ready, Value: i32 }\nmain := () i32 {\n  s := .Value(9)\n  return match s {\n    .Ready: 1,\n    .Value(v): v,\n  }\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_source_struct_field_access() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 => Data{a: 4, b: 9}.b\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_source_dynamic_struct_index() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 { idx := 1 return Data{a: 4, b: 9}[idx] }\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_source_dynamic_enum_index() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 { idx := 1 e := .Ok(9) return e[idx] }\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_source_slice_then_index() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 => Data{a: 4, b: 9}[0..2][1]\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_generic_vec_type_constructor_container() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nVec := (T: comp type) type => struct {\n  new := (allocator: usize) usize => $vec_raw_init(allocator, comp $sizeof(T), comp $alignof(T)),\n  reserve := (vec: usize, new_cap: usize) u32 => $vec_raw_reserve(vec, new_cap),\n  push_bytes := (vec: usize, src: usize) u32 => $vec_raw_push_bytes(vec, src, comp $sizeof(T)),\n  get_bytes := (vec: usize, idx: usize, dst: usize) u32 => $vec_raw_get_bytes(vec, idx, dst, comp $sizeof(T)),\n  pop_bytes := (vec: usize, dst: usize) u32 => $vec_raw_pop_bytes(vec, dst, comp $sizeof(T)),\n  deinit := (vec: usize) u32 => $vec_raw_deinit(vec),\n}\nmain := () i32 {\n  alloc := $c_allocator()\n  vec := Vec(i32).new(alloc)\n  src := $alloc_with(alloc, 4, 4)\n  dst := $alloc_with(alloc, 4, 4)\n  $mem_set(src, 58, 4)\n  ok_reserve := Vec(i32).reserve(vec, 4)\n  ok_push := Vec(i32).push_bytes(vec, src)\n  ok_get := Vec(i32).get_bytes(vec, 0, dst)\n  eq_get := $mem_eq(src, dst, 4)\n  $mem_set(dst, 0, 4)\n  ok_pop := Vec(i32).pop_bytes(vec, dst)\n  eq_pop := $mem_eq(src, dst, 4)\n  ok_vec_free := Vec(i32).deinit(vec)\n  $free_with(alloc, src, 4, 4)\n  $free_with(alloc, dst, 4, 4)\n  return if ok_reserve == 1 && ok_push == 1 && ok_get == 1 && eq_get == 1 && ok_pop == 1 && eq_pop == 1 && ok_vec_free == 1 58 else 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(58));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_indirect_function_pointer_call() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  fp := $test_identity_i32_fn()\n  return fp(41)\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(41));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_struct_static_and_instance_method_calls() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { new := () i32 => 44, do := (self: Thing) i32 => 55 }\nmain := () i32 {\n  t := Thing{}\n  Thing.new()\n  return t.do()\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(55));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_generic_type_binding() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nid := (T: type, v: T) T => v\nmain := () i32 {\n  out := id(i32, 68)\n  return out\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(68));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_generic_type_binding_named_args() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nid := (T: type, v: T) T => v\nmain := () i32 {\n  out := id(v: 68, T: i32)\n  return out\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(68));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_errorable_void_main_without_explicit_return() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nio := use \"std/io\"\nmain := () ! {\n  io.println(\"ok: {}\", { 7 }).!\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let output = Command::new(&artifact.executable_path)
        .output()
        .expect("executable should run");
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "ok: 7\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_imported_module_member_function_call() {
    let root = make_temp_dir();
    fs::write(
        root.join("my_math.dyn"),
        "module my_math\npub inc := (value: i32) i32 => value + 1\n",
    )
    .expect("file should be written");
    fs::write(
        root.join("a.dyn"),
        "module main\nmath := use \"my_math\"\nmain := () i32 => math.inc(41)\n",
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
fn builds_native_executable_with_slice_u8_string_and_std_bytes() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nbytes_mod := use \"std/bytes\"\nmain := () i32 {\n  b: []u8 = \"hello\"\n  return if bytes_mod.len(b) == 5 0 else 1\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(0));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_embedded_nul_slice_u8_bytes() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nbytes_mod := use \"std/bytes\"\nio := use \"std/io\"\nmain := () i32 {\n  v: []u8 = \"a\\0b\"\n  if bytes_mod.len(v) != 3 return 1\n  if bytes_mod.eq(v, \"a\\0b\") == 0 return 2\n  io.print(v) or return 3\n  return 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let output = Command::new(&artifact.executable_path)
        .output()
        .expect("executable should run");
    assert_eq!(output.status.code(), Some(0));
    assert_eq!(output.stdout.as_slice(), b"a\0b");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_implicit_main_success_after_or_return_println() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nio := use \"std/io\"\nmain := () {\n  io.println(\"Hello world\\n\") or return 1\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let output = Command::new(&artifact.executable_path)
        .output()
        .expect("executable should run");
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "Hello world\n\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}
