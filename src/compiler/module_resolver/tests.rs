use super::*;
use std::time::{SystemTime, UNIX_EPOCH};

fn make_temp_dir() -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time should be monotonic")
        .as_nanos();
    for attempt in 0..1000usize {
        let path = std::env::temp_dir().join(format!(
            "dyn_module_resolver_{}_{}_{}",
            std::process::id(),
            unique,
            attempt
        ));
        if fs::create_dir(&path).is_ok() {
            return path;
        }
    }

    panic!("failed to create unique temp directory");
}

#[test]
fn groups_by_directory_and_module_name() {
    let root = make_temp_dir();
    let sub = root.join("nested");
    fs::create_dir_all(&sub).expect("nested directory should be created");

    fs::write(root.join("a.dyn"), "module math\nval := 1\n").expect("file should be written");
    fs::write(root.join("b.dyn"), "module math\nval := 2\n").expect("file should be written");
    fs::write(root.join("c.dyn"), "module io\nval := 3\n").expect("file should be written");
    fs::write(sub.join("d.dyn"), "module math\nval := 4\n").expect("file should be written");

    let graph = resolve_module_graph(&root).expect("module resolution should succeed");
    assert!(graph.diagnostics.is_empty());
    assert_eq!(graph.groups.len(), 3);

    let root_key_math = ModuleKey {
        directory: PathBuf::from("."),
        module_name: "math".to_string(),
    };
    let root_key_io = ModuleKey {
        directory: PathBuf::from("."),
        module_name: "io".to_string(),
    };
    let sub_key_math = ModuleKey {
        directory: PathBuf::from("nested"),
        module_name: "math".to_string(),
    };

    assert_eq!(graph.groups.get(&root_key_math).map(Vec::len), Some(2));
    assert_eq!(graph.groups.get(&root_key_io).map(Vec::len), Some(1));
    assert_eq!(graph.groups.get(&sub_key_math).map(Vec::len), Some(1));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn skips_comments_before_module_declaration() {
    let root = make_temp_dir();
    let file_path = root.join("comments_ok.dyn");

    fs::write(
        &file_path,
        "// heading\n/// doc\n/* block\ncomment */\nmodule main\n",
    )
    .expect("file should be written");

    let graph = resolve_module_graph(&root).expect("module resolution should succeed");
    assert!(graph.diagnostics.is_empty());
    assert_eq!(graph.groups.len(), 1);

    let key = ModuleKey {
        directory: PathBuf::from("."),
        module_name: "main".to_string(),
    };
    assert_eq!(graph.groups.get(&key).map(Vec::len), Some(1));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn collects_all_bad_files_as_diagnostics() {
    let root = make_temp_dir();

    fs::write(root.join("good.dyn"), "module good\nval := 1\n").expect("file should be written");
    fs::write(
        root.join("bad_missing.dyn"),
        "// only comments\n/* still comments */\n",
    )
    .expect("file should be written");
    fs::write(root.join("bad_invalid.dyn"), "not_module main\n").expect("file should be written");

    let graph = resolve_module_graph(&root).expect("module resolution should succeed");
    assert_eq!(graph.groups.len(), 1);
    assert_eq!(graph.diagnostics.len(), 2);
    assert!(matches!(
        graph.diagnostics[0].code,
        DiagnosticCode::E1003 | DiagnosticCode::E1004
    ));
    assert!(matches!(
        graph.diagnostics[1].code,
        DiagnosticCode::E1003 | DiagnosticCode::E1004
    ));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn assigns_stable_module_ids_from_sorted_keys() {
    let root = make_temp_dir();
    let a_dir = root.join("a");
    let b_dir = root.join("b");
    fs::create_dir_all(&a_dir).expect("a directory should be created");
    fs::create_dir_all(&b_dir).expect("b directory should be created");

    fs::write(a_dir.join("z.dyn"), "module zoo\n").expect("file should be written");
    fs::write(a_dir.join("a.dyn"), "module alpha\n").expect("file should be written");
    fs::write(b_dir.join("k.dyn"), "module alpha\n").expect("file should be written");

    let graph = resolve_module_graph(&root).expect("module resolution should succeed");
    assert!(graph.diagnostics.is_empty());
    assert_eq!(graph.modules.len(), 3);

    let key_a_alpha = ModuleKey {
        directory: PathBuf::from("a"),
        module_name: "alpha".to_string(),
    };
    let key_a_zoo = ModuleKey {
        directory: PathBuf::from("a"),
        module_name: "zoo".to_string(),
    };
    let key_b_alpha = ModuleKey {
        directory: PathBuf::from("b"),
        module_name: "alpha".to_string(),
    };

    assert_eq!(graph.module_id(&key_a_alpha), Some(ModuleId(0)));
    assert_eq!(graph.module_id(&key_a_zoo), Some(ModuleId(1)));
    assert_eq!(graph.module_id(&key_b_alpha), Some(ModuleId(2)));

    let module = graph.module(ModuleId(1)).expect("module id 1 should exist");
    assert_eq!(module.key, key_a_zoo);

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn includes_bundled_std_module_when_project_imports_std_path() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nio := use \"std/io\"\nmain := () i32 => 0\n",
    )
    .expect("file should be written");

    let graph = resolve_module_graph(&root).expect("module resolution should succeed");
    let stdlib_io_key = ModuleKey {
        directory: PathBuf::from("std"),
        module_name: "io".to_string(),
    };
    assert!(
        graph.module_id(&stdlib_io_key).is_some(),
        "expected std/io to be present in resolved modules"
    );

    fs::remove_dir_all(root).expect("temp directory should be removed");
}
