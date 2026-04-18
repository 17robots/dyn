use dyn_compiler::compiler::ast::Visibility;
use dyn_compiler::compiler::diagnostics::SourceSpan;
use dyn_compiler::compiler::hir::{
    HirExpr, HirExprKind, HirItem, HirLiteral, HirModule, HirProgram,
};
use dyn_compiler::compiler::mir::lower::lower_hir_to_mir_with_diagnostics;
use dyn_compiler::compiler::mir::MirInstr;
use dyn_compiler::compiler::module_resolver::{ModuleId, ModuleKey};
use std::path::PathBuf;

fn span() -> SourceSpan {
    SourceSpan {
        start_byte: 0,
        end_byte: 0,
        start_line: 1,
        start_col: 1,
        end_line: 1,
        end_col: 1,
    }
}

fn expr(kind: HirExprKind) -> HirExpr {
    HirExpr { kind, span: span() }
}

#[test]
fn block_break_value_lowers_to_join_phi() {
    let program = HirProgram {
        modules: vec![HirModule {
            module_id: ModuleId(0),
            key: ModuleKey {
                directory: PathBuf::from("."),
                module_name: "main".to_string(),
            },
            items: vec![HirItem {
                name: "main".to_string(),
                def_id: None,
                visibility: Visibility::Private,
                mutable: false,
                type_hint: Some("i32".to_string()),
                inferred_type: Some("i32".to_string()),
                value: expr(HirExprKind::Function {
                    params: vec!["cond".to_string()],
                    param_types: vec![Some("u1".to_string())],
                    param_defaults: Vec::new(),
                    has_explicit_return_type: true,
                    body: Box::new(expr(HirExprKind::Block {
                        label: None,
                        body: vec![expr(HirExprKind::Block {
                            label: None,
                            body: vec![
                                expr(HirExprKind::If {
                                    condition: Box::new(expr(HirExprKind::Ident(
                                        "cond".to_string(),
                                    ))),
                                    capture: None,
                                    then_branch: Box::new(expr(HirExprKind::Break {
                                        label: None,
                                        value: Some(Box::new(expr(HirExprKind::Literal(
                                            HirLiteral::Integer("7".to_string()),
                                        )))),
                                    })),
                                    else_branch: None,
                                }),
                                expr(HirExprKind::Literal(HirLiteral::Integer("9".to_string()))),
                            ],
                        })],
                    })),
                }),
                span: span(),
                enclosing_struct: None,
            }],
            extern_functions: Vec::new(),
        }],
    };

    let (mir, diagnostics) = lower_hir_to_mir_with_diagnostics(&program);
    assert!(
        diagnostics.is_empty(),
        "expected zero MIR diagnostics, got:\n{}",
        diagnostics
            .iter()
            .map(|d| format!("  [{}] {}", d.code, d.message))
            .collect::<Vec<_>>()
            .join("\n")
    );

    let main_fn = &mir.modules[0].functions[0];
    let phi_count = main_fn
        .blocks
        .iter()
        .flat_map(|block| block.instructions.iter())
        .filter(|instr| matches!(instr, MirInstr::Phi { sources, .. } if sources.len() == 2))
        .count();

    assert!(
        phi_count >= 1,
        "expected block break lowering to produce join phi with two sources"
    );
}
