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
fn builds_native_executable_with_module_level_mut_variable() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmut counter: i32 = 0\nmain := () i32 {\n  counter = counter + 1\n  counter = counter + 1\n  counter = counter + 1\n  return counter\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(3));

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
fn builds_native_executable_with_extern_function_declaration_and_call() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nabs := extern (x: i32) i32 = \"abs\"\nmain := () i32 => abs(-3)\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(3));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_using_syscall_builtin() {
    // Linux x86_64 SYS_exit = 60. We call $syscall(60, 42) which should exit
    // with code 42. The process exits before main returns, so we never reach
    // the `return 0` — the exit code comes from the syscall itself.
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmain := () i32 {\n  $syscall(60, 42)\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(42));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_extern_function_binding_and_call() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nabs := extern (x: i32) i32 = \"abs\"\nmain := () i32 => abs(-4)\n",
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
