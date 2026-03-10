use super::*;
use crate::compiler::module_resolver::resolve_module_graph;
use crate::compiler::pipeline::parse_project;
use std::fs;
use std::time::{SystemTime, UNIX_EPOCH};

fn make_temp_dir() -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time should be monotonic")
        .as_nanos();

    let path = std::env::temp_dir().join(format!("dyn_module_unit_{unique}"));
    fs::create_dir_all(&path).expect("temp directory should be created");
    path
}

#[test]
fn merges_declarations_by_module_id() {
    let root = make_temp_dir();
    fs::write(root.join("a.dyn"), "module main\na := 1\n").expect("file should be written");
    fs::write(root.join("b.dyn"), "module main\nb := 2\n").expect("file should be written");
    fs::write(root.join("c.dyn"), "module other\nc := 3\n").expect("file should be written");

    let graph = resolve_module_graph(&root).expect("module graph should resolve");
    let parsed = parse_project(&root).expect("project should parse");
    let units = build_module_units(&graph, &parsed);

    assert_eq!(units.len(), 2);
    let main = units
        .iter()
        .find(|unit| unit.key.module_name == "main")
        .expect("main module should exist");
    let other = units
        .iter()
        .find(|unit| unit.key.module_name == "other")
        .expect("other module should exist");

    assert_eq!(main.declarations.len(), 2);
    assert_eq!(other.declarations.len(), 1);
    assert!(main
        .declarations
        .iter()
        .any(|decl| decl.file_path == std::path::Path::new("a.dyn")));
    assert!(main
        .declarations
        .iter()
        .any(|decl| decl.file_path == std::path::Path::new("b.dyn")));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}
