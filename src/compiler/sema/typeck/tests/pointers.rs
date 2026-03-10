use super::*;

#[test]
fn accepts_slice_binding_from_array_slice_expression() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  i: [4]i32 = [1, 2, 3, 4]\n  k: []i32 = i[0..2]\n  return k[0]\n}\n",
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
fn accepts_mut_pointer_u1_binding_from_mut_ref() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  mut d: u1 = false\n  q: *mut u1 = &d\n  q.* = true\n  return if d 1 else 0\n}\n",
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
fn infers_iterate_binding_type_for_slice_elements() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nsum := (xs: []i32) i32 {\n  mut acc: i32 = 0\n  for xs: |v| { acc += v }\n  return acc\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(
        !diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("compound assignment requires numeric target and value")
        }),
        "{diagnostics:#?}"
    );

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn infers_iterate_binding_type_for_u8_slice_elements() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nsum := (b: []u8) i32 {\n  mut acc: i32 = 0\n  for b: |ch| { acc += ch }\n  return acc\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(
        !diagnostics.iter().any(|diagnostic| {
            diagnostic.code == DiagnosticCode::E4005
                && diagnostic
                    .message
                    .contains("compound assignment requires numeric target and value")
        }),
        "{diagnostics:#?}"
    );

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn parses_pointer_sized_integer_aliases() {
    assert_eq!(
        parse_int_type_name("usize"),
        Some(Type::Int {
            signed: false,
            bits: 64,
        })
    );
    assert_eq!(
        parse_int_type_name("isize"),
        Some(Type::Int {
            signed: true,
            bits: 64,
        })
    );
}

#[test]
fn allows_mut_pointer_to_const_pointer_coercion() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmut x: i32 = 1\npm: *mut i32 = &x\npc: *i32 = pm\n",
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
fn rejects_const_pointer_to_mut_pointer_coercion() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nx: i32 = 1\npc: *i32 = &x\npm: *mut i32 = pc\n",
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
fn rejects_assignment_through_const_pointer() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  x: i32 = 1\n  pc: *i32 = &x\n  pc.* = 2\n  0\n}\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4006));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn allows_assignment_through_mut_pointer() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  mut x: i32 = 1\n  pm: *mut i32 = &x\n  pm.* = 2\n  0\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(!diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E4006));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn accepts_struct_instance_member_with_self_receiver_name() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nThing := struct { do := (self: Thing) i32 => 0 }\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(!diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("first parameter is not named self")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_struct_instance_member_with_non_self_receiver_name() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nThing := struct { do := (this: Thing) i32 => 0 }\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("first parameter is not named self")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_mut_pointer_receiver_call_on_immutable_binding() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nmain := () i32 {\n  t := Thing{}\n  t.touch()\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4006
            && diagnostic
                .message
                .contains("cannot call mut receiver method on immutable value")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn accepts_mut_pointer_receiver_call_on_mutable_binding() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nmain := () i32 {\n  mut t := Thing{}\n  t.touch()\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(!diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4006
            && diagnostic
                .message
                .contains("cannot call mut receiver method on immutable value")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn accepts_mut_pointer_receiver_call_on_typed_mutable_binding() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nmain := () i32 {\n  mut t: Thing = Thing{}\n  t.touch()\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(!diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4006
            && diagnostic
                .message
                .contains("cannot call mut receiver method on immutable value")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_mut_pointer_receiver_call_on_immutable_field_receiver() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nHolder := struct { item: Thing }\nmain := () i32 {\n  h := Holder{item: Thing{}}\n  h.item.touch()\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4006
            && diagnostic
                .message
                .contains("cannot call mut receiver method on immutable value")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn accepts_mut_pointer_receiver_call_on_mutable_field_receiver() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nHolder := struct { item: Thing }\nmain := () i32 {\n  mut h := Holder{item: Thing{}}\n  h.item.touch()\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(!diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4006
            && diagnostic
                .message
                .contains("cannot call mut receiver method on immutable value")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn reports_mut_pointer_receiver_call_on_temporary_value() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nmain := () i32 {\n  Thing{}.touch()\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4006
            && diagnostic
                .message
                .contains("cannot call mut receiver method on immutable value")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn accepts_opaque_pointer_erasure_from_typed_pointer() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  mut x: i32 = 1\n  p: *mut i32 = &x\n  erased: *mut opaque = p\n  return if erased == null 1 else 0\n}\n",
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
fn accepts_u8_slice_annotation_with_string_literal() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\nb: []u8 = \"hi\"\n")
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
fn accepts_slice_u8_annotation_with_string_literal() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\nb: []u8 = \"hi\"\n")
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
fn accepts_u8_slice_parameter_with_u8_slice_value() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\naccept := (value: []u8) usize => value[0]\nmain := () i32 {\n  b: []u8 = \"hi\"\n  _ := accept(b)\n  return 0\n}\n",
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
fn accepts_any_in_function_parameter_type() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nuse_any := (x: any) i32 => 0\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(!diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("only allowed in function parameter")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn rejects_any_in_binding_annotation() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\nx: any = 0\n").expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005
            && diagnostic
                .message
                .contains("only allowed in function parameter")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn allows_any_parameter_to_flow_into_usize_context() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\naddr := (x: any) usize => x\n",
    )
    .expect("file should be written");

    let (_parsed, units) =
        parse_project_with_module_units(&root).expect("project should parse and merge");
    let diagnostics = type_check_modules(&units);
    assert!(!diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E4005 && diagnostic.message.contains("type mismatch")
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}
