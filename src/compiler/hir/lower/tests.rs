use super::*;
use crate::compiler::pipeline::analyze_project;
use crate::compiler::sema::typeck::infer_binding_type_strings;
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

fn make_temp_dir() -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time should be monotonic")
        .as_nanos();
    let path = std::env::temp_dir().join(format!("dyn_hir_{unique}"));
    fs::create_dir_all(&path).expect("temp directory should be created");
    path
}

#[test]
fn lowers_module_units_into_hir_program() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\na: i32 = 1\nb := use \"other\"\n",
    )
    .expect("file should be written");
    fs::write(root.join("other.dyn"), "module other\nx := 1\n").expect("file should be written");

    let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
    let inferred = infer_binding_type_strings(&units);
    let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
    assert_eq!(hir.modules.len(), 2);
    assert!(hir
        .modules
        .iter()
        .any(|module| module.key.module_name == "main" && module.items.len() >= 2));
    let main_module = hir
        .modules
        .iter()
        .find(|module| module.key.module_name == "main")
        .expect("main module should exist");
    assert!(main_module
        .items
        .iter()
        .any(|item| item.def_id.is_some() && item.inferred_type.is_some()));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn preserves_local_binding_type_hint_in_hir_block() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmain := () i32 {\n  x: u7 = 1\n  return $as(i32, x)\n}\n",
    )
    .expect("file should be written");

    let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
    let inferred = infer_binding_type_strings(&units);
    let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
    let main_module = hir
        .modules
        .iter()
        .find(|module| module.key.module_name == "main")
        .expect("main module should exist");
    let main_item = main_module
        .items
        .iter()
        .find(|item| item.name == "main")
        .expect("main binding should exist");
    let HirExprKind::Function { body, .. } = &main_item.value.kind else {
        panic!("main should lower to function")
    };
    let HirExprKind::Block { body } = &body.kind else {
        panic!("main body should be block")
    };

    assert!(body.iter().any(|expr| {
        matches!(
            &expr.kind,
            HirExprKind::Let {
                name,
                type_hint,
                ..
            } if name == "x" && type_hint.as_deref() == Some("u7")
        )
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn rewrites_struct_member_method_calls_into_synthetic_functions() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { new := () i32 => 44, do := (self: Thing) i32 => 55 }\nmain := () i32 {\n  t := Thing{}\n  Thing.new()\n  t.do()\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
    let inferred = infer_binding_type_strings(&units);
    let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
    let main_module = hir
        .modules
        .iter()
        .find(|module| module.key.module_name == "main")
        .expect("main module should exist");
    assert!(main_module
        .items
        .iter()
        .any(|item| item.name == "Thing__new"));
    assert!(main_module
        .items
        .iter()
        .any(|item| item.name == "Thing__do"));

    let main_item = main_module
        .items
        .iter()
        .find(|item| item.name == "main")
        .expect("main binding should exist");
    let HirExprKind::Function { body, .. } = &main_item.value.kind else {
        panic!("main should lower to function")
    };
    let HirExprKind::Block { body } = &body.kind else {
        panic!("main body should be block")
    };
    assert!(body.iter().any(|expr| {
        matches!(
            &expr.kind,
            HirExprKind::Call { callee, .. }
                if matches!(&callee.kind, HirExprKind::Ident(name) if name == "Thing__new")
        )
    }));
    assert!(body.iter().any(|expr| {
        matches!(
            &expr.kind,
            HirExprKind::Call { callee, .. }
                if matches!(&callee.kind, HirExprKind::Ident(name) if name == "Thing__do")
        )
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn rewrites_type_constructor_static_method_call_into_synthetic_function() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nVec := (T: comp type) type => struct { new := () i32 => 44 }\nmain := () i32 {\n  Vec(i32).new()\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
    let inferred = infer_binding_type_strings(&units);
    let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
    let main_module = hir
        .modules
        .iter()
        .find(|module| module.key.module_name == "main")
        .expect("main module should exist");
    assert!(main_module.items.iter().any(|item| item.name == "Vec__new"));

    let main_item = main_module
        .items
        .iter()
        .find(|item| item.name == "main")
        .expect("main binding should exist");
    let HirExprKind::Function { body, .. } = &main_item.value.kind else {
        panic!("main should lower to function")
    };
    let HirExprKind::Block { body } = &body.kind else {
        panic!("main body should be block")
    };
    assert!(body.iter().any(|expr| {
        matches!(
            &expr.kind,
            HirExprKind::Call { callee, .. }
                if matches!(&callee.kind, HirExprKind::Ident(name) if name == "Vec__new")
        )
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn rewrites_pointer_receiver_method_call_with_implicit_ref() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *Thing) i32 => 1 }\nmain := () i32 {\n  t := Thing{}\n  t.touch()\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
    let inferred = infer_binding_type_strings(&units);
    let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
    let main_module = hir
        .modules
        .iter()
        .find(|module| module.key.module_name == "main")
        .expect("main module should exist");
    let main_item = main_module
        .items
        .iter()
        .find(|item| item.name == "main")
        .expect("main binding should exist");
    let HirExprKind::Function { body, .. } = &main_item.value.kind else {
        panic!("main should lower to function")
    };
    let HirExprKind::Block { body } = &body.kind else {
        panic!("main body should be block")
    };
    assert!(body.iter().any(|expr| {
            matches!(
                &expr.kind,
                HirExprKind::Call { callee, args }
                    if matches!(&callee.kind, HirExprKind::Ident(name) if name == "Thing__touch")
                        && matches!(args.first().map(|arg| &arg.value.kind), Some(HirExprKind::Unary { op: UnaryOp::Ref, .. }))
            )
        }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn rewrites_mut_pointer_receiver_method_call_for_mutable_binding() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nmain := () i32 {\n  mut t := Thing{}\n  t.touch()\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
    let inferred = infer_binding_type_strings(&units);
    let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
    let main_module = hir
        .modules
        .iter()
        .find(|module| module.key.module_name == "main")
        .expect("main module should exist");
    let main_item = main_module
        .items
        .iter()
        .find(|item| item.name == "main")
        .expect("main binding should exist");
    let HirExprKind::Function { body, .. } = &main_item.value.kind else {
        panic!("main should lower to function")
    };
    let HirExprKind::Block { body } = &body.kind else {
        panic!("main body should be block")
    };
    assert!(body.iter().any(|expr| {
            matches!(
                &expr.kind,
                HirExprKind::Call { callee, args }
                    if matches!(&callee.kind, HirExprKind::Ident(name) if name == "Thing__touch")
                        && matches!(args.first().map(|arg| &arg.value.kind), Some(HirExprKind::Unary { op: UnaryOp::Ref, .. }))
            )
        }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn does_not_rewrite_mut_pointer_receiver_call_for_immutable_binding() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nmain := () i32 {\n  t := Thing{}\n  t.touch()\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
    let inferred = infer_binding_type_strings(&units);
    let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
    let main_module = hir
        .modules
        .iter()
        .find(|module| module.key.module_name == "main")
        .expect("main module should exist");
    let main_item = main_module
        .items
        .iter()
        .find(|item| item.name == "main")
        .expect("main binding should exist");
    let HirExprKind::Function { body, .. } = &main_item.value.kind else {
        panic!("main should lower to function")
    };
    let HirExprKind::Block { body } = &body.kind else {
        panic!("main body should be block")
    };
    assert!(body.iter().any(|expr| {
        matches!(
            &expr.kind,
            HirExprKind::Call { callee, .. }
                if matches!(
                    &callee.kind,
                    HirExprKind::FieldAccess { field, .. } if field == "touch"
                )
        )
    }));
    assert!(!body.iter().any(|expr| {
        matches!(
            &expr.kind,
            HirExprKind::Call { callee, .. }
                if matches!(&callee.kind, HirExprKind::Ident(name) if name == "Thing__touch")
        )
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn rewrites_mut_pointer_receiver_call_for_mutable_field_binding() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nThing := struct { touch := (self: *mut Thing) i32 => 1 }\nHolder := struct { item: Thing }\nmain := () i32 {\n  mut h := Holder{item: Thing{}}\n  h.item.touch()\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
    let inferred = infer_binding_type_strings(&units);
    let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
    let main_module = hir
        .modules
        .iter()
        .find(|module| module.key.module_name == "main")
        .expect("main module should exist");
    let main_item = main_module
        .items
        .iter()
        .find(|item| item.name == "main")
        .expect("main binding should exist");
    let HirExprKind::Function { body, .. } = &main_item.value.kind else {
        panic!("main should lower to function")
    };
    let HirExprKind::Block { body } = &body.kind else {
        panic!("main body should be block")
    };
    assert!(body.iter().any(|expr| {
            matches!(
                &expr.kind,
                HirExprKind::Call { callee, args }
                    if matches!(&callee.kind, HirExprKind::Ident(name) if name == "Thing__touch")
                        && matches!(args.first().map(|arg| &arg.value.kind), Some(HirExprKind::Unary { op: UnaryOp::Ref, .. }))
            )
        }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn rewrites_method_calls_through_anonymous_struct_literal_binding() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nBox := (T: comp type) type => struct {\n  value: T,\n  get := (self: Box(T)) T => self.value,\n}\nWrapper := (T: comp type) type => struct {\n  inner: Box(T),\n  test := (self: Wrapper(T)) T => {\n    next := .{ inner: self.inner }\n    next.inner.get()\n  },\n}\nmain := () i32 {\n  return 0\n}\n",
        )
        .expect("file should be written");

    let (_parsed, units, sema) = analyze_project(&root).expect("project should analyze");
    let inferred = infer_binding_type_strings(&units);
    let hir = lower_module_units_with_metadata(&units, Some(&sema), &inferred);
    let main_module = hir
        .modules
        .iter()
        .find(|module| module.key.module_name == "main")
        .expect("main module should exist");
    let wrapper_test = main_module
        .items
        .iter()
        .find(|item| item.name == "Wrapper__test")
        .expect("Wrapper__test synthetic function should exist");
    let HirExprKind::Function { body, .. } = &wrapper_test.value.kind else {
        panic!("Wrapper__test should lower to function")
    };
    let HirExprKind::Block { body } = &body.kind else {
        panic!("Wrapper__test body should be block")
    };
    assert!(body.iter().any(|expr| {
        matches!(
            &expr.kind,
            HirExprKind::Call { callee, .. }
                if matches!(&callee.kind, HirExprKind::Ident(name) if name == "Box__get")
        )
    }));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}
