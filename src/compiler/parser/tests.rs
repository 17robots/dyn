use super::*;
use crate::compiler::diagnostics::DiagnosticCode;
use crate::compiler::lexer::scanner::Lexer;
use std::fs;
use std::path::Path;

#[test]
fn parses_basic_binding_file() {
    let src = "module main\na := 1\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(parsed.diagnostics.is_empty());
    assert!(parsed.ast.is_some());
    let ast = parsed.ast.expect("ast should be present");
    assert_eq!(ast.items.len(), 1);
}

#[test]
fn parses_example_files_with_stable_top_level_segmentation() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let full = root.join("full_example.dyn");
    let other = root.join("full_example_other.dyn");
    let also_main = root.join("full_example_also_main.dyn");

    let full_src = fs::read_to_string(&full).expect("full example should be readable");
    let full_tokens = Lexer::new(&full_src, PathBuf::from("full_example.dyn")).lex();
    let full_ast = parse_file(PathBuf::from("full_example.dyn"), &full_tokens.tokens)
        .ast
        .expect("full example should parse");
    assert!(full_ast.items.len() >= 14);

    let other_src = fs::read_to_string(&other).expect("other example should be readable");
    let other_tokens = Lexer::new(&other_src, PathBuf::from("full_example_other.dyn")).lex();
    let other_ast = parse_file(
        PathBuf::from("full_example_other.dyn"),
        &other_tokens.tokens,
    )
    .ast
    .expect("other example should parse");
    assert_eq!(other_ast.items.len(), 2);

    let also_src = fs::read_to_string(&also_main).expect("also-main example should be readable");
    let also_tokens = Lexer::new(&also_src, PathBuf::from("full_example_also_main.dyn")).lex();
    let also_ast = parse_file(
        PathBuf::from("full_example_also_main.dyn"),
        &also_tokens.tokens,
    )
    .ast
    .expect("also-main example should parse");
    assert_eq!(also_ast.items.len(), 1);
}

#[test]
fn keeps_top_level_binding_after_parenthesized_expr_in_struct_member_fn() {
    let src = "module main\nVec := (T: comp type) type => struct { x: usize, f := (self: Vec(T), idx: usize) u32 { src := (idx * 2)\ncopy := src\nreturn 1 }, }\nmain := () i32 { return 1 }\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(parsed.diagnostics.is_empty());
    let ast = parsed.ast.expect("ast should be present");
    assert_eq!(ast.items.len(), 2);
    let Item::Binding(binding) = &ast.items[1] else {
        panic!("expected second top-level item to be a binding")
    };
    assert_eq!(binding.name.text, "main");
}

#[test]
fn parses_empty_param_fn_with_type_return() {
    let src = "module main\nget_type := () type { return struct { vals: ?*type } }\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    assert_eq!(ast.items.len(), 1);
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    assert!(matches!(binding.value.kind, ExprKind::Fn(_)));
}

#[test]
fn parses_return_with_type_literal_value() {
    let src = "module main\nget_type := () type { return struct { vals: ?*type } }\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::Fn(fn_expr) = &binding.value.kind else {
        panic!("expected function value")
    };
    let crate::compiler::ast::FnBody::Block(block) = &fn_expr.body else {
        panic!("expected block body")
    };
    let Some(tail) = &block.tail_expr else {
        panic!("expected return tail expression")
    };
    let ExprKind::Return { value } = &tail.kind else {
        panic!("expected return expression")
    };
    assert!(matches!(
        value.as_deref().map(|expr| &expr.kind),
        Some(ExprKind::TypeLiteral(_))
    ));
}

#[test]
fn parses_comp_prefixed_function_followed_by_arrow_body() {
    let src = "module main\ncalc := () comp if use_f64 f64 else f32 => 3.14\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::Fn(fn_expr) = &binding.value.kind else {
        panic!("expected function value")
    };
    let crate::compiler::ast::FnBody::ArrowExpr(body) = &fn_expr.body else {
        panic!("expected arrow function body")
    };
    assert!(matches!(body.kind, ExprKind::Literal(Literal::Float(_))));
}

#[test]
fn reports_error_for_arrow_function_block_body() {
    let src = "module main\nmain := () i32 => { return 1 }\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(parsed.ast.is_some(), "ast should still be produced");
    assert!(parsed.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E3001
            && diagnostic
                .message
                .contains("arrow function body must be a single expression")
    }));
}

#[test]
fn parses_if_with_spaced_enum_variant_then_branch() {
    let src = "module main\ndivide := (y: f32) f32!Err => if y == 0 .DivideByZero else y\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::Fn(fn_expr) = &binding.value.kind else {
        panic!("expected function value")
    };
    let crate::compiler::ast::FnBody::ArrowExpr(body) = &fn_expr.body else {
        panic!("expected arrow function body")
    };
    let ExprKind::If(if_expr) = &body.kind else {
        panic!("expected if expression")
    };
    let ExprKind::Binary {
        op: BinaryOp::Eq, ..
    } = if_expr.condition.kind
    else {
        panic!("expected equality condition")
    };
    assert!(matches!(
        if_expr.then_branch.kind,
        ExprKind::EnumVariantConstruct(_)
    ));
}

#[test]
fn parses_if_capture_binding() {
    let src = "module main\nmain := (n: ?i32) i32 => if n: |v| v else 0\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::Fn(fn_expr) = &binding.value.kind else {
        panic!("expected function value")
    };
    let crate::compiler::ast::FnBody::ArrowExpr(body) = &fn_expr.body else {
        panic!("expected arrow function body")
    };
    let ExprKind::If(if_expr) = &body.kind else {
        panic!("expected if expression")
    };
    let capture = if_expr.capture.as_ref().expect("expected if capture");
    let binding = capture.binding.as_ref().expect("expected capture binding");
    assert_eq!(binding.text, "v");
}

#[test]
fn reports_error_for_single_expression_if_branch_block() {
    let src = "module main\nmain := () i32 => if true { 1 } else 0\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(parsed.ast.is_some(), "ast should still be produced");
    assert!(parsed.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E3001
            && diagnostic
                .message
                .contains("single-expression if branch must not use block braces")
    }));
}

#[test]
fn allows_if_branch_block_with_statements() {
    let src = "module main\nmain := () i32 => if true { x := 1 x } else 0\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(!parsed.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E3001
            && diagnostic
                .message
                .contains("single-expression if branch must not use block braces")
    }));
}

#[test]
fn parses_match_with_guard_and_range_pattern() {
    let src = "module main\nmain := () i32 => match 2 { 0..=1: 4, 2 if true: 9, _: 0 }\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::Fn(fn_expr) = &binding.value.kind else {
        panic!("expected function value")
    };
    let crate::compiler::ast::FnBody::ArrowExpr(body) = &fn_expr.body else {
        panic!("expected arrow function body")
    };
    let ExprKind::Match(match_expr) = &body.kind else {
        panic!("expected match expression")
    };
    assert_eq!(match_expr.arms.len(), 3);
    assert!(matches!(
        match_expr.arms[0].pattern.kind,
        PatternKind::Range {
            inclusive: true,
            ..
        }
    ));
    assert!(match_expr.arms[1].guard.is_some());
}

#[test]
fn parses_multiline_match_expression_body() {
    let src = "module main\nmain := () i32 {\n  v := 3\n  match v {\n    0..1: 4,\n    2 if true: 9,\n    _: 0,\n  }\n}\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::Fn(fn_expr) = &binding.value.kind else {
        panic!("expected function value")
    };
    let crate::compiler::ast::FnBody::Block(block) = &fn_expr.body else {
        panic!("expected block body")
    };
    let Some(last) = block.tail_expr.as_ref() else {
        panic!("expected match tail expression")
    };
    let ExprKind::Match(match_expr) = &last.kind else {
        panic!("expected match expression")
    };
    assert_eq!(match_expr.arms.len(), 3);
}

#[test]
fn recovers_match_arm_fat_arrow_separator_without_cascading_expression_errors() {
    let src = "module main\nmain := () i32 => match 1 { 1 => 2, _: 0 }\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(parsed.ast.is_some(), "ast should still be produced");
    assert!(parsed.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E3001
            && diagnostic
                .message
                .contains("expected ':' after match pattern")
    }));
    assert!(!parsed
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E3002));
}

#[test]
fn recovers_missing_comma_between_match_arms_without_cascading_expression_errors() {
    let src = "module main\nmain := () i32 => match 1 { 1: 2 _: 0 }\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(parsed.ast.is_some(), "ast should still be produced");
    assert!(parsed.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E3001
            && diagnostic
                .message
                .contains("expected ',' between match arms")
    }));
    assert!(!parsed
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E3002));
}

#[test]
fn recovers_missing_comma_between_struct_literal_fields() {
    let src =
        "module main\nPair := struct { a: i32, b: i32 }\nmain := () Pair => Pair{ a: 1 b: 2 }\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(parsed.ast.is_some(), "ast should still be produced");
    assert!(parsed.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E3001
            && diagnostic
                .message
                .contains("expected ',' between struct literal fields")
    }));
}

#[test]
fn recovers_missing_comma_between_array_literal_elements() {
    let src = "module main\nmain := () [3]i32 => [1 2, 3]\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(parsed.ast.is_some(), "ast should still be produced");
    assert!(parsed.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E3001
            && diagnostic
                .message
                .contains("expected ',' between array literal elements")
    }));
}

#[test]
fn recovers_missing_comma_between_tuple_literal_elements() {
    let src = "module main\nmain := () i32 { t := {1 2, 3}; return 0 }\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(parsed.ast.is_some(), "ast should still be produced");
    assert!(parsed.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E3001
            && diagnostic
                .message
                .contains("expected ',' between tuple literal elements")
    }));
}

#[test]
fn recovers_missing_comma_between_call_arguments() {
    let src = "module main\nmain := () i32 => $as(i32 7)\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(parsed.ast.is_some(), "ast should still be produced");
    assert!(parsed.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E3001
            && diagnostic
                .message
                .contains("expected ',' between call arguments")
    }));
}

#[test]
fn recovers_missing_comma_between_function_parameters() {
    let src = "module main\nmain := (a: i32 b: i32) i32 => a\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(parsed.ast.is_some(), "ast should still be produced");
    assert!(parsed.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E3001
            && diagnostic
                .message
                .contains("expected ',' between function parameters")
    }));
}

#[test]
fn parses_for_iterate_with_pipe_binding() {
    let src = "module main\na := for xs: |v| v\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::For(ForExpr::Iterate {
        iterable, binding, ..
    }) = &binding.value.kind
    else {
        panic!("expected iterate for expression")
    };
    assert!(matches!(iterable.kind, ExprKind::Ident(_)));
    let Some(binding) = binding else {
        panic!("expected iterate binding")
    };
    assert_eq!(binding.text, "v");
}

#[test]
fn parses_for_range_with_pipe_binding() {
    let src = "module main\na := for 0..10: |v| v\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::For(ForExpr::Range {
        start,
        end,
        binding,
        ..
    }) = &binding.value.kind
    else {
        panic!("expected range for expression")
    };
    assert!(matches!(start.kind, ExprKind::Literal(Literal::Integer(_))));
    assert!(matches!(end.kind, ExprKind::Literal(Literal::Integer(_))));
    let Some(binding) = binding else {
        panic!("expected range binding")
    };
    assert_eq!(binding.text, "v");
}

#[test]
fn parses_array_literal_expression() {
    let src = "module main\nxs := [1, 2, 3]\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::ArrayLiteral(elements) = &binding.value.kind else {
        panic!("expected array literal")
    };
    assert_eq!(elements.len(), 3);
    assert!(matches!(
        elements[0].kind,
        ExprKind::Literal(Literal::Integer(_))
    ));
}

#[test]
fn parses_brace_tuple_literal_expression() {
    let src = "module main\nxs := {1, 2, 3}\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::TupleLiteral(elements) = &binding.value.kind else {
        panic!("expected tuple literal")
    };
    assert_eq!(elements.len(), 3);
    assert!(matches!(
        elements[1].kind,
        ExprKind::Literal(Literal::Integer(_))
    ));
}

#[test]
fn parses_slice_expression_inside_index_brackets() {
    let src = "module main\nxs := arr[0..2]\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::Slice(slice) = &binding.value.kind else {
        panic!("expected slice expression")
    };
    assert!(matches!(slice.base.kind, ExprKind::Ident(_)));
    assert!(matches!(
        slice.start.as_ref().map(|expr| &expr.kind),
        Some(ExprKind::Literal(Literal::Integer(_)))
    ));
    assert!(matches!(
        slice.end.as_ref().map(|expr| &expr.kind),
        Some(ExprKind::Literal(Literal::Integer(_)))
    ));
    assert!(!slice.inclusive);
}

#[test]
fn parses_plain_equals_in_block_as_assignment_expression() {
    let src =
            "module main\nmain := () i32 {\n  mut d: u1 = false\n  d = true\n  return if d 1 else 0\n}\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::Fn(fn_expr) = &binding.value.kind else {
        panic!("expected function value")
    };
    let crate::compiler::ast::FnBody::Block(block) = &fn_expr.body else {
        panic!("expected block body")
    };
    assert!(matches!(block.statements[0], Stmt::Binding(_)));
    assert!(matches!(
        block.statements[1],
        Stmt::Expr(ref expr) if matches!(
            expr.kind,
            ExprKind::Assign {
                op: AssignOp::Assign,
                ..
            }
        )
    ));
}

#[test]
fn clears_stale_tail_expr_when_binding_follows_expression() {
    let src = "module main\nmain := () {\n  1\n  x := 2\n}\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::Fn(fn_expr) = &binding.value.kind else {
        panic!("expected function value")
    };
    let crate::compiler::ast::FnBody::Block(block) = &fn_expr.body else {
        panic!("expected block body")
    };
    assert_eq!(block.statements.len(), 2);
    assert!(matches!(
        block.statements[0],
        Stmt::Expr(ref expr) if matches!(expr.kind, ExprKind::Literal(Literal::Integer(_)))
    ));
    assert!(matches!(block.statements[1], Stmt::Binding(_)));
    assert!(block.tail_expr.is_none());
}

#[test]
fn parses_enum_match_pattern_with_bindings() {
    let src = "module main\nmain := (v: i32) i32 => match v { .Value(a, b): a, _: 0 }\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::Fn(fn_expr) = &binding.value.kind else {
        panic!("expected function value")
    };
    let crate::compiler::ast::FnBody::ArrowExpr(body) = &fn_expr.body else {
        panic!("expected arrow function body")
    };
    let ExprKind::Match(match_expr) = &body.kind else {
        panic!("expected match expression")
    };
    let PatternKind::EnumVariant {
        root,
        variant,
        bindings,
    } = &match_expr.arms[0].pattern.kind
    else {
        panic!("expected enum variant pattern")
    };
    assert!(root.is_none());
    assert_eq!(variant.text, "Value");
    assert_eq!(bindings.len(), 2);
}

#[test]
fn desugars_match_capture_into_enum_variant_binding() {
    let src = "module main\nmain := (v: i32) i32 => match v { .Value: |val| val, _: 0 }\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::Fn(fn_expr) = &binding.value.kind else {
        panic!("expected function value")
    };
    let crate::compiler::ast::FnBody::ArrowExpr(body) = &fn_expr.body else {
        panic!("expected arrow function body")
    };
    let ExprKind::Match(match_expr) = &body.kind else {
        panic!("expected match expression")
    };
    let PatternKind::EnumVariant { bindings, .. } = &match_expr.arms[0].pattern.kind else {
        panic!("expected enum variant pattern")
    };
    assert_eq!(bindings.len(), 1);
    assert_eq!(bindings[0].text, "val");
}

#[test]
fn parses_rooted_enum_match_pattern() {
    let src = "module main\nmain := (v: i32) i32 => match v { State.Ready: 1, _: 0 }\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::Fn(fn_expr) = &binding.value.kind else {
        panic!("expected function value")
    };
    let crate::compiler::ast::FnBody::ArrowExpr(body) = &fn_expr.body else {
        panic!("expected arrow function body")
    };
    let ExprKind::Match(match_expr) = &body.kind else {
        panic!("expected match expression")
    };
    let PatternKind::EnumVariant {
        root,
        variant,
        bindings,
    } = &match_expr.arms[0].pattern.kind
    else {
        panic!("expected enum variant pattern")
    };
    assert_eq!(
        root.as_ref().map(|ident| ident.text.as_str()),
        Some("State")
    );
    assert_eq!(variant.text, "Ready");
    assert!(bindings.is_empty());
}

#[test]
fn parses_applied_type_expression_in_binding_annotation() {
    let src = "module main\nxs: Vec(i32) = 0\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ty = binding.annotation.as_ref().expect("expected annotation");
    let TypeExprKind::Applied { callee, args } = &ty.kind else {
        panic!("expected applied type")
    };
    assert_eq!(callee.text, "Vec");
    assert_eq!(args.len(), 1);
    assert!(matches!(args[0].kind, TypeExprKind::Named(_)));
}

#[test]
fn parses_mutable_slice_type_expression() {
    let src = "module main\nxs: []mut i32 = 0\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ty = binding.annotation.as_ref().expect("expected annotation");
    let TypeExprKind::Slice { mutable, element } = &ty.kind else {
        panic!("expected slice type")
    };
    assert!(*mutable);
    assert!(matches!(element.kind, TypeExprKind::Named(_)));
}

#[test]
fn parses_builtin_as_pointer_type_designator_argument() {
    let src = "module main\nmain := () i32 => $as(*mut i32, $alloc(4, 4))\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::Fn(fn_expr) = &binding.value.kind else {
        panic!("expected function value")
    };
    let crate::compiler::ast::FnBody::ArrowExpr(body) = &fn_expr.body else {
        panic!("expected arrow body")
    };
    let ExprKind::Call(call) = &body.kind else {
        panic!("expected call expression")
    };
    assert_eq!(call.args.len(), 2);
    let ExprKind::TypeLiteral(ty) = &call.args[0].value.kind else {
        panic!("expected type literal first argument")
    };
    let TypeExprKind::Pointer { mutable, inner } = &ty.kind else {
        panic!("expected pointer type designator")
    };
    assert!(*mutable);
    assert!(matches!(inner.kind, TypeExprKind::Named(_)));
}

#[test]
fn parses_struct_type_with_function_members() {
    let src = "module main\nThing := struct { age: i32, new := () Thing => Thing{ age: 0 }, do := (self: Thing) i32 => self.age }\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::TypeLiteral(ty) = &binding.value.kind else {
        panic!("expected type literal")
    };
    let TypeExprKind::Struct(struct_ty) = &ty.kind else {
        panic!("expected struct type")
    };
    assert_eq!(struct_ty.fields.len(), 1);
    assert_eq!(struct_ty.members.len(), 2);
    assert!(matches!(struct_ty.members[0].value.kind, ExprKind::Fn(_)));
    assert!(matches!(struct_ty.members[1].value.kind, ExprKind::Fn(_)));
}

#[test]
fn parses_struct_type_with_function_typed_field() {
    let src = "module main\nThing := struct { do: fn(self: Thing) i32 }\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::TypeLiteral(ty) = &binding.value.kind else {
        panic!("expected type literal")
    };
    let TypeExprKind::Struct(struct_ty) = &ty.kind else {
        panic!("expected struct type")
    };
    assert_eq!(struct_ty.fields.len(), 1);
    assert!(matches!(
        struct_ty.fields[0].ty.kind,
        TypeExprKind::Function(_)
    ));
}

#[test]
fn defaults_function_type_return_to_void_when_omitted() {
    let src = "module main\nThing := struct { do: fn(self: Thing) }\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::TypeLiteral(ty) = &binding.value.kind else {
        panic!("expected type literal")
    };
    let TypeExprKind::Struct(struct_ty) = &ty.kind else {
        panic!("expected struct type")
    };
    let TypeExprKind::Function(fn_ty) = &struct_ty.fields[0].ty.kind else {
        panic!("expected function type")
    };
    assert!(matches!(&fn_ty.return_type.kind, TypeExprKind::Named(name) if name.text == "void"));
}

#[test]
fn decodes_string_literal_escape_sequences() {
    let src = "module main\ns := \"hi\\n\"\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::Literal(Literal::String(value)) = &binding.value.kind else {
        panic!("expected string literal")
    };
    assert_eq!(value, "hi\n");
}

#[test]
fn parses_use_path_without_quotes() {
    let src = "module main\nio := use \"std/io\"\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::Use { path } = &binding.value.kind else {
        panic!("expected use expression")
    };
    assert_eq!(path, "std/io");
}

#[test]
fn parses_nested_parenthesized_arithmetic_expression() {
    let src =
        "module main\nf := () i32 { elem_size := 1 src := 2 + ((3 - 1) * elem_size) return src }\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(
        parsed.diagnostics.is_empty(),
        "diagnostics: {:#?}",
        parsed.diagnostics
    );
}

#[test]
fn reports_unexpected_expression_token() {
    let src = "module main\na := )\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(parsed
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E3002));
}

#[test]
fn reports_missing_block_delimiter() {
    let src = "module main\nmain := () i32 {\n  return 1\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(parsed
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E3001));
}

#[test]
fn parses_semicolon_separated_block_statements() {
    let src = "module main\nmain := () i32 { s := $Self(); return if s == s 6 else 0 }\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(
        parsed.diagnostics.is_empty(),
        "diagnostics: {:#?}",
        parsed.diagnostics
    );
}

#[test]
fn reports_error_for_legacy_extern_declaration_syntax() {
    let src =
        "module main\npub extern write: fn(fd: i32, ptr: *u8, len: usize) i32 = \"dynrt_fd_write\"\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(parsed.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E3001
            && diagnostic
                .message
                .contains("extern declarations must use binding syntax")
    }));
}

#[test]
fn parses_extern_function_binding_with_link_name() {
    let src =
        "module main\nwrite := extern (fd: i32, ptr: *u8, len: usize) i32 = \"dynrt_fd_write\"\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(
        parsed.diagnostics.is_empty(),
        "diagnostics: {:#?}",
        parsed.diagnostics
    );
    let ast = parsed.ast.expect("ast should be present");
    let Item::Extern(extern_decl) = &ast.items[0] else {
        panic!("expected extern item")
    };
    assert_eq!(extern_decl.name.text, "write");
    assert_eq!(extern_decl.link_name.as_deref(), Some("dynrt_fd_write"));
    let TypeExprKind::Function(fn_ty) = &extern_decl.ty.kind else {
        panic!("expected function type")
    };
    assert_eq!(fn_ty.params.len(), 3);
}

#[test]
fn parses_packed_struct_type_literal() {
    let src = "module main\nThing := packed struct { value: u32 }\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(
        parsed.diagnostics.is_empty(),
        "diagnostics: {:#?}",
        parsed.diagnostics
    );
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::TypeLiteral(ty) = &binding.value.kind else {
        panic!("expected type literal")
    };
    let TypeExprKind::Struct(struct_ty) = &ty.kind else {
        panic!("expected struct type")
    };
    assert!(struct_ty.packed);
    assert_eq!(struct_ty.fields.len(), 1);
}

#[test]
fn parses_enum_type_with_repr_width() {
    let src = "module main\nState := enum(u8) { Ready, Busy }\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(
        parsed.diagnostics.is_empty(),
        "diagnostics: {:#?}",
        parsed.diagnostics
    );
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::TypeLiteral(ty) = &binding.value.kind else {
        panic!("expected type literal")
    };
    let TypeExprKind::Enum(enum_ty) = &ty.kind else {
        panic!("expected enum type")
    };
    let repr = enum_ty.repr.as_ref().expect("expected enum repr");
    let TypeExprKind::Named(name) = &repr.kind else {
        panic!("expected named repr type")
    };
    assert_eq!(name.text, "u8");
}

#[test]
fn reports_error_for_non_function_extern_binding() {
    let src = "module main\nvalue := extern i32\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(parsed.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E3001
            && diagnostic
                .message
                .contains("extern bindings must declare function signatures")
    }));
}

#[test]
fn reports_error_for_invalid_enum_repr_type() {
    let src = "module main\nState := enum(i32) { Ready }\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    assert!(parsed.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == DiagnosticCode::E3001
            && diagnostic
                .message
                .contains("enum representation type must be unsigned integer")
    }));
}

#[test]
fn parses_continue_with_label() {
    let src = "module main\na := continue :outer\n";
    let lex = Lexer::new(src, PathBuf::from("t.dyn")).lex();
    let parsed = parse_file(PathBuf::from("t.dyn"), &lex.tokens);
    let ast = parsed.ast.expect("ast should be present");
    let Item::Binding(binding) = &ast.items[0] else {
        panic!("expected binding item")
    };
    let ExprKind::Continue { label } = &binding.value.kind else {
        panic!("expected continue expression")
    };
    let label = label.as_ref().expect("expected continue label");
    assert_eq!(label.name.text, "outer");
}
