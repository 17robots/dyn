use super::*;

#[test]
fn validates_builtin_allocator_call_arity() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\na := dynrt_alloc(16)\n")
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic.message.contains("missing required argument")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn validates_builtin_memory_call_arity() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := dynrt_mem_set(0, 255)\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic.message.contains("missing required argument")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn validates_builtin_vec_call_arity() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := dynrt_vec_i32_push(0)\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic.message.contains("missing required argument")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn validates_builtin_failing_allocator_call_arity() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := dynrt_test_set_fail_after()\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic.message.contains("missing required argument")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn validates_raw_vec_call_arity() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := dynrt_vec_raw_init(1, 4)\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic.message.contains("missing required argument")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn validates_raw_vec_bytes_call_arity() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := dynrt_vec_raw_push_bytes(0, 0)\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic.message.contains("missing required argument")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn validates_identity_function_pointer_builtin_arity() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := dynrt_test_identity_i32_fn(1)\n",
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
fn validates_arena_allocator_builtin_arity() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := dynrt_arena_reset()\n",
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
fn rejects_opaque_pointer_as_typed_pointer_without_cast() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  mut x: i32 = 1\n  p: *mut i32 = &x\n  erased: *mut opaque = p\n  typed: *mut i32 = erased\n  typed.*\n}\n",
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
fn supports_basic_builtin_cast_and_sizeof_calls() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := $as(i32, 1)\nb := $sizeof(i32)\n",
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
fn supports_builtin_cast_between_usize_and_pointer() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  p := $as(*mut i32, dynrt_alloc(4, 4))\n  q := $as(usize, p)\n  return if q != 0 1 else 0\n}\n",
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
fn supports_builtin_cast_from_slice_to_usize() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  xs: [2]i32 = [1, 2]\n  s: []i32 = xs[..]\n  p := $as(usize, s)\n  return if p != 0 1 else 0\n}\n",
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
fn supports_basic_builtin_alignof_and_offsetof_calls() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := $alignof(i32)\nb := $offsetof(i32, 0)\n",
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
fn accepts_comptime_builtin_expression() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\na := comp $sizeof(i32)\n")
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
fn accepts_comptime_builtin_expression_with_type_constructor_call() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nVec := (T: type) type => struct { items: []T }\na := comp $sizeof(Vec(i32))\n",
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
fn accepts_self_builtin_in_method_context() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nThing := struct { f := (self: *Thing) type => $Self() }\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(!diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("$Self is only available in self method context")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_self_builtin_outside_method_context() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\na := $Self()\n").expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("$Self is only available in self method context")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_builtin_offsetof_invalid_struct_field_designator() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := $offsetof(struct { a: u8, b: i32 }, c)\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("$offsetof field designator is invalid")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_builtin_offsetof_invalid_field_designator_expression_kind() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := $offsetof(i32, \"x\")\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("$offsetof field designator is invalid")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_builtin_offsetof_invalid_named_struct_field_designator() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nData := struct { a: u8, b: i32 }\na := $offsetof(Data, c)\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("$offsetof field designator is invalid for named struct type")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn supports_basic_builtin_typeof_call() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\nt: type = $typeof(1)\n")
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
fn reports_compile_error_builtin() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na := $compile_error(\"nope\")\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic.message.contains("$compile_error invoked")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_panic_builtin_non_string_message() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\na := $panic(123)\n")
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("$panic message must be []u8/string compatible")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}
