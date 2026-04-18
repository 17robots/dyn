use dyn_compiler::compiler::pipeline::lower_project_mir;
#[test]
#[ignore]
fn tmp_debug() {
    let (_, _, _, _, mir, diags) =
        lower_project_mir("tests/cases/runtime/dyn_trait_impl_exit").unwrap();
    eprintln!("diags={:?}", diags);
    for m in &mir.modules {
        eprintln!("module {}", m.key.module_name);
        for f in &m.functions {
            eprintln!(
                "fn {} ret={:?} hints={:?}",
                f.name, f.return_type, f.param_type_hints
            );
            for b in &f.blocks {
                eprintln!(" block {:?}", b.id);
                for i in &b.instructions {
                    eprintln!("  {:?}", i);
                }
                eprintln!("  term {:?}", b.terminator);
            }
        }
    }
}
