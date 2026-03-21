use super::*;

#[test]
fn builds_native_executable_with_function_call_return() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nhelper := () i32 => 7\nmain := () i32 => helper()\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(7));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_function_call_arguments() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nadd := (x: i32, y: i32) i32 => x + y\nmain := () i32 => add(30, 41)\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(71));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_function_alias_call_return() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nhelper := () i32 => 73\nmain := () i32 {\n  f := helper\n  return f()\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(73));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_higher_order_function_parameter_call() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\ninc := (x: i32) i32 => x + 1\napply := (f, x: i32) i32 => f(x)\nmain := () i32 => apply(inc, 80)\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(81));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_typed_higher_order_function_parameter_call() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\ninc := (x: i32) i32 => x + 1\napply := (f: fn(i32) i32, x: i32) i32 => f(x)\nmain := () i32 => apply(inc, 82)\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(83));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_function_returning_function_value() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\ninc := (x: i32) i32 => x + 1\nmake := () fn(i32) i32 => inc\nmain := () i32 {\n  f := make()\n  return f(41)\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(42));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_local_noop_function_call() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 {\n  f := () {}\n  f()\n  return 9\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_default_argument_call() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nadd := (x: i32, y: i32 = 5) i32 => x + y\nmain := () i32 => add(70)\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(75));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_default_argument_call_via_alias() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nadd := (x: i32, y: i32 = 5) i32 => x + y\nmain := () i32 {\n  f := add\n  return f(70)\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(75));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_named_arguments_reordered_via_alias() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nadd := (x: i32, y: i32) i32 => x + y\nmain := () i32 {\n  f := add\n  return f(y: 12, x: 60)\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(72));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_named_arguments_reordered() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nadd := (x: i32, y: i32) i32 => x + y\nmain := () i32 => add(y: 12, x: 60)\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(72));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_named_and_default_arguments() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nscore := (a: i32, b: i32 = 2, c: i32 = 3) i32 => a + b + c\nmain := () i32 => score(c: 5, a: 10)\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(17));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_method_default_argument() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nThing := struct { touch := (self: *mut Thing, n: i32 = 7) i32 => n }\nmain := () i32 {\n  mut t := Thing{}\n  return t.touch()\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(7));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_method_named_argument() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nThing := struct { touch := (self: *mut Thing, n: i32 = 7) i32 => n }\nmain := () i32 {\n  mut t := Thing{}\n  return t.touch(n: 9)\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_generic_named_default_method_combo() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\ninc := (x: i32) i32 => x + 1\nThing := struct { run := (self: *mut Thing, f: fn(i32) i32, x: i32 = 40) i32 => f(x) }\nmain := () i32 {\n  mut t := Thing{}\n  _ignored := t.run(f: inc)\n  return t.run(f: inc, x: 2)\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(3));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_if_expression_return() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 { return if true 9 else 4 }\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_local_bindings() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 { x := 5 y := 8 return x + y }\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(13));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_comparison_and_logical_ops() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 => if (3 > 2) && (1 == 1) 21 else 0\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(21));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_float_expression_cast_to_main_exit() {
    let root = make_temp_dir();
    write_dyn_file(&root, "a.dyn", "module main\nmain := () f64 => 1.5 + 2.5\n");

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(4));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_calling_float_function() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nfoo := () f64 => 6.75\nmain := () f64 => foo()\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(6));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_narrow_unsigned_integer_wraparound() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nadd := (x: u7, y: u7) u7 => x + y\nmain := () i32 {\n  if add(120, 20) == 12 return 12\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(12));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_narrow_signed_integer_wraparound() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nadd := (a: i5, b: i5) i5 => a + b\nmain := () i32 {\n  if add(15, 3) < 0 return 14\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(14));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_annotated_local_narrow_integer_wraparound() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 {\n  mut x: u7 = 120\n  y: u7 = 20\n  x = x + y\n  if x == 12 return 13\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(13));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_wide_integer_widths_up_to_128_bits() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nadd := (a: i128, b: i128) i128 => a + b\nmain := () i32 {\n  x: i128 = 42\n  y: i128 = 1\n  z := add(x, y)\n  if z != 43 return 1\n  uz: u128 = $as(u128, z)\n  return if uz == 43 19 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(19));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_u128_literal_above_i64_range() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 {\n  base: u128 = $as(u128, 0x10000000000000000)\n  out := base + $as(u128, 5)\n  expect: u128 = $as(u128, 0x10000000000000005)\n  return if out == expect 20 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(20));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_f128_arithmetic_and_compare() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nadd := (lhs: f128, rhs: f128) f128 { return lhs + rhs }\nmain := () i32 {\n  a := $as(f128, 1.5)\n  b := $as(f128, 2.25)\n  c := add(a, b)\n  if c > $as(f128, 3.7) { return 7 }\n  return 1\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(7));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_f128_precision_beyond_f64() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 {\n  hi := $as(f128, 1.000000000000000000000000000001)\n  delta := hi - $as(f128, 1.0)\n  if delta > $as(f128, 0.0) { return 9 }\n  return 1\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_f128_integer_cast_roundtrip() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 {\n  a := $as(f128, 40.5)\n  b := a + $as(f128, 1.5)\n  c := $as(i32, b)\n  if c == 42 { return 10 }\n  return 1\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(10));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_f128_nan_comparisons() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 {\n  nan := $as(f128, 0.0) / $as(f128, 0.0)\n  if nan == nan return 1\n  if nan != nan return 17\n  return 2\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(17));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_f128_cast_saturates_small_int_widths() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 {\n  huge := $as(f128, 9999999999999999999999999999999999999.0)\n  tiny := $as(f128, -9999999999999999999999999999999999999.0)\n  hi: i8 = $as(i8, huge)\n  lo: i8 = $as(i8, tiny)\n  if hi != 127 { return 1 }\n  if lo != -128 { return 2 }\n  return 18\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(18));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_loop_break() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 { for { break } return 11 }\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(11));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_defer_executed_at_block_scope_exit() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 {\n  mut x := 0\n  {\n    defer { x = x + 1 }\n  }\n  if x == 1 return 31\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(31));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_defer_lifo_order_within_scope() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 {\n  mut x := 1\n  {\n    defer { x = x * 2 }\n    defer { x = x + 3 }\n  }\n  if x == 8 return 32\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(32));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_error_only_defer_on_error_path() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nio := use \"std/io\"\nErr := enum { Boom }\nwork := (fail: u1) i32!Err {\n  defer |e| { io.print(\"E\") or 0 }\n  if fail == true return .Boom\n  return 1\n}\nmain := () i32 {\n  work(true) or |err| {\n    io.print(\"X\") or 0\n    return 0\n  }\n  return 1\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output(&artifact.executable_path);
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "EX");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_error_only_defer_skipped_on_success() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nio := use \"std/io\"\nErr := enum { Boom }\nwork := (fail: u1) i32!Err {\n  defer |e| { io.print(\"E\") or 0 }\n  if fail == true return .Boom\n  return 2\n}\nmain := () i32 {\n  value := work(false) or return 1\n  if value != 2 return 2\n  io.print(\"S\") or 0\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output(&artifact.executable_path);
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "S");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_loop_continue_path() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 { for { if false { continue } break } return 12 }\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(12));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_while_like_loop_carried_local() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 {\n  mut total := 0\n  for total < 3: total += 1\n  return total\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(3));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_for_range_binding_sum() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 {\n  mut total = 0\n  for 0..=4: |v| total += v\n  return total\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(10));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_for_iterate_binding_sum() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 {\n  xs: [4]i32 = [1, 2, 3, 4]\n  mut total = 0\n  for xs: |v| total += v\n  return total\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(10));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_if_optional_capture_binding() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 {\n  n: ?i32 = 9\n  return if n: |v| v else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_or_else_capture_binding() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 {\n  mut n: ?i32 = null\n  return n or |err| if err == err 7 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(7));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_optional_unwrap_success() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 {\n  n: ?i32 = 6\n  return n.?\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(6));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_optional_unwrap_trap_on_null() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 {\n  mut n: ?i32 = null\n  return n.?\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_ne!(run_exit_code(&artifact.executable_path), Some(0));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_error_unwrap_success() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nE := enum { Fail }\nok := () i32!E => 8\nmain := () i32 => ok().!\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(8));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_error_unwrap_success_zero_value() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nE := enum { Fail }\nok := () i32!E => 0\nmain := () i32 {\n  v := ok().!\n  return if v == 0 12 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(12));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_error_unwrap_trap_on_error() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nE := enum { Fail }\nfail := () i32!E => .Fail\nmain := () i32 => fail().!\n",
    );

    let artifact = build_clean_project(&root);
    assert_ne!(run_exit_code(&artifact.executable_path), Some(0));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_error_unwrap_propagates_error_in_errorable_function() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nE := enum { Fail }\nfail := () i32!E => .Fail\nforward := () i32!E => fail().!\nmain := () i32 {\n  forward() or return 7\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(7));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_error_unwrap_propagates_success_value() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nE := enum { Fail }\nok := () i32!E => 9\nforward := () i32!E => ok().!\nmain := () i32 => forward() or return 7\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_error_unwrap_propagates_f128_success_value() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nE := enum { Fail }\nok := () f128!E => $as(f128, 42.0)\nforward := () f128!E => ok().!\nmain := () i32 {\n  v := forward() or return 7\n  return if $as(i32, v) == 42 14 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(14));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_error_union_return_call_coerces_to_error() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nE := enum { One, Two }\nmake_err := () E => .Two\nfail := () i32!E => make_err()\nmain := () i32 {\n  fail() or |err| {\n    return if err == .Two 13 else 0\n  }\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(13));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_source_match_guard_and_range() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 {\n  v := 2\n  return match v {\n    0..1: 4,\n    2 if true: 9,\n    _: 0,\n  }\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_source_enum_variant_match_binding() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nState := enum { Ready, Value: i32 }\nmain := () i32 {\n  s := .Value(9)\n  return match s {\n    .Ready: 1,\n    .Value(v): v,\n  }\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_source_struct_field_access() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 => Data{a: 4, b: 9}.b\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_source_dynamic_struct_index() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 { idx := 1 return Data{a: 4, b: 9}[idx] }\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_source_dynamic_enum_index() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 { idx := 1 e := .Ok(9) return e[idx] }\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_source_slice_then_index() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 => Data{a: 4, b: 9}[0..2][1]\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_generic_vec_type_constructor_container() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nheap := use \"std/heap\"\nmem := use \"std/mem\"\nVec := (T: comp type) type => struct {\n  new := (allocator: usize) usize => $vec_raw_init(allocator, comp $sizeof(T), comp $alignof(T)),\n  reserve := (vec: usize, new_cap: usize) u32 => $vec_raw_reserve(vec, new_cap),\n  push_bytes := (vec: usize, src: usize) u32 => $vec_raw_push_bytes(vec, src, comp $sizeof(T)),\n  get_bytes := (vec: usize, idx: usize, dst: usize) u32 => $vec_raw_get_bytes(vec, idx, dst, comp $sizeof(T)),\n  pop_bytes := (vec: usize, dst: usize) u32 => $vec_raw_pop_bytes(vec, dst, comp $sizeof(T)),\n  deinit := (vec: usize) u32 => $vec_raw_deinit(vec),\n}\nmain := () i32 {\n  c := heap.CAllocator().new()\n  alloc_obj := c.allocator()\n  alloc := alloc_obj.ctx\n  vec := Vec(i32).new(alloc)\n  src := alloc_obj.alloc(u8, 4) or return 0\n  dst := alloc_obj.alloc(u8, 4) or return 0\n  ok_src_set := mem.set(src, 58, 4)\n  ok_reserve := Vec(i32).reserve(vec, 4)\n  ok_push := Vec(i32).push_bytes(vec, src)\n  ok_get := Vec(i32).get_bytes(vec, 0, dst)\n  eq_get := mem.eq(src, dst, 4)\n  ok_dst_clear := mem.set(dst, 0, 4)\n  ok_pop := Vec(i32).pop_bytes(vec, dst)\n  eq_pop := mem.eq(src, dst, 4)\n  ok_vec_free := Vec(i32).deinit(vec)\n  ok_src_free := alloc_obj.free(u8, src, 4)\n  ok_dst_free := alloc_obj.free(u8, dst, 4)\n  return if ok_src_set == 1 && ok_reserve == 1 && ok_push == 1 && ok_get == 1 && eq_get == 1 && ok_dst_clear == 1 && ok_pop == 1 && eq_pop == 1 && ok_vec_free == 1 && ok_src_free == 1 && ok_dst_free == 1 58 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(58));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_indirect_function_pointer_call() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 {\n  fp := $test_identity_i32_fn()\n  return fp(41)\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(41));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_extern_function_declaration_and_call() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nbytes_len := extern (b: []u8) usize = \"dynrt_bytes_len\"\nmain := () i32 => $as(i32, bytes_len(\"abc\"))\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(3));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_extern_function_binding_and_call() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nbytes_len := extern (b: []u8) usize = \"dynrt_bytes_len\"\nmain := () i32 => $as(i32, bytes_len(\"abcd\"))\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(4));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_packed_struct_and_enum_repr_type_literals() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nState := enum(u8) { Off, On }\nPair := packed struct { left: u8, right: u8 }\nmain := () i32 {\n  s := .On\n  p := Pair{ left: 7, right: 8 }\n  return if s == .On && p.left == 7 && p.right == 8 81 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(81));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_linux_raw_write_syscall() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nlinux := use \"std/os/linux\"\nmain := () i32 {\n  msg := \"ok\"\n  ptr := $as(isize, $as(usize, msg))\n  rc := linux.syscall3(linux.sys_write(), 1, ptr, 2)\n  return if rc == 2 77 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output(&artifact.executable_path);
    assert_eq!(output.status.code(), Some(77));
    assert_eq!(output.stdout.as_slice(), b"ok");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_linux_checked_syscall_errno_mapping() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nlinux := use \"std/os/linux\"\nmain := () i32 {\n  mapped := linux.errno_to_error(9)\n  return if mapped == .BadFd 78 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(78));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_linux_io_write_syscall_wrapper() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nlinux := use \"std/os/linux\"\nmain := () i32 {\n  ok := linux.io_write(\"ok\", 0)\n  return if ok == 1 79 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output(&artifact.executable_path);
    assert_eq!(output.status.code(), Some(79));
    assert_eq!(output.stdout.as_slice(), b"ok");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_os_io_write_facade_wrapper() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nos := use \"std/os\"\nmain := () i32 {\n  ok := os.io_write(\"ok\", 0)\n  return if ok == 1 80 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output(&artifact.executable_path);
    assert_eq!(output.status.code(), Some(80));
    assert_eq!(output.stdout.as_slice(), b"ok");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_linux_fd_write_checked_error_path() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nlinux := use \"std/os/linux\"\nmain := () i32 {\n  msg := \"x\"\n  ptr := $as(isize, $as(usize, msg))\n  linux.fd_write_ptr_checked($as(isize, -1), ptr, 1) or |err| {\n    return if err == .BadFd 81 else 0\n  }\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(81));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_writer_stdout_writeln() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nwriter := use \"std/io/writer\"\nmain := () i32 {\n  msg := \"ok\"\n  ptr := $as(isize, $as(usize, msg))\n  writer.write_fd_raw(1, ptr, 2, 1) or return 1\n  return 82\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output(&artifact.executable_path);
    assert_eq!(output.status.code(), Some(82));
    assert_eq!(output.stdout.as_slice(), b"ok\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_file_open_read_and_close() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nfile := use \"std/fs/file\"\nmain := () i32 {\n  path := \"/dev/null\\0\"\n  path_ptr := $as(isize, $as(usize, path))\n  fd := file.open_read_ptr(path_ptr) or return 1\n  file.close_fd(fd) or return 2\n  return 83\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(83));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_struct_static_and_instance_method_calls() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nThing := struct { new := () i32 => 44, do := (self: Thing) i32 => 55 }\nmain := () i32 {\n  t := Thing{}\n  Thing.new()\n  return t.do()\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(55));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_generic_type_binding() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nid := (T: type, v: T) T => v\nmain := () i32 {\n  out := id(i32, 68)\n  return out\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(68));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_generic_type_binding_named_args() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nid := (T: type, v: T) T => v\nmain := () i32 {\n  out := id(v: 68, T: i32)\n  return out\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(68));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_errorable_void_main_without_explicit_return() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nio := use \"std/io\"\nmain := () ! {\n  io.println(\"ok: {}\", { 7 }).!\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output(&artifact.executable_path);
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "ok: 7\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_imported_module_member_function_call() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "my_math.dyn",
        "module my_math\npub inc := (value: i32) i32 => value + 1\n",
    );
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmath := use \"my_math\"\nmain := () i32 => math.inc(41)\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(42));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_slice_u8_string_and_std_bytes() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nbytes_mod := use \"std/bytes\"\nmain := () i32 {\n  b: []u8 = \"hello\"\n  return if bytes_mod.len(b) == 5 0 else 1\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(0));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_embedded_nul_slice_u8_bytes() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nbytes_mod := use \"std/bytes\"\nio := use \"std/io\"\nmain := () i32 {\n  v: []u8 = \"a\\0b\"\n  if bytes_mod.len(v) != 3 return 1\n  if bytes_mod.eq(v, \"a\\0b\") == 0 return 2\n  io.print(v) or return 3\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output(&artifact.executable_path);
    assert_eq!(output.status.code(), Some(0));
    assert_eq!(output.stdout.as_slice(), b"a\0b");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_implicit_main_success_after_or_return_println() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nio := use \"std/io\"\nmain := () {\n  io.println(\"Hello world\\n\") or return 1\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output(&artifact.executable_path);
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "Hello world\n\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}
