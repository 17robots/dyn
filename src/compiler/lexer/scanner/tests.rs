use super::*;
use crate::compiler::lexer::token::{Keyword, Operator};

#[test]
fn lexes_keywords_identifiers_and_operators() {
    let source = "module main\na := b += c ..= d\n";
    let out = Lexer::new(source, PathBuf::from("test.dyn")).lex();

    assert!(out.diagnostics.is_empty());
    assert_eq!(out.tokens[0].kind, TokenKind::Keyword(Keyword::Module));
    assert_eq!(out.tokens[1].kind, TokenKind::Identifier);
    assert_eq!(out.tokens[2].kind, TokenKind::Identifier);
    assert_eq!(out.tokens[3].kind, TokenKind::Operator(Operator::Colon));
    assert_eq!(out.tokens[4].kind, TokenKind::Operator(Operator::Equal));
    assert_eq!(out.tokens[6].kind, TokenKind::Operator(Operator::PlusEqual));
    assert_eq!(out.tokens[8].kind, TokenKind::Operator(Operator::DotDotEq));
}

#[test]
fn keeps_doc_comments_and_skips_other_comments() {
    let source = "/// api docs\n// ignore\n/* skip */\nmain\n";
    let out = Lexer::new(source, PathBuf::from("test.dyn")).lex();

    assert!(out.diagnostics.is_empty());
    assert_eq!(out.tokens[0].kind, TokenKind::DocComment);
    assert_eq!(out.tokens[0].lexeme, " api docs");
    assert_eq!(out.tokens[1].kind, TokenKind::Identifier);
}

#[test]
fn enforces_builtin_identifier_rule() {
    let source = "$  $ok\n";
    let out = Lexer::new(source, PathBuf::from("test.dyn")).lex();

    assert_eq!(out.diagnostics.len(), 1);
    assert_eq!(out.diagnostics[0].code, DiagnosticCode::E2006);
    assert!(out
        .tokens
        .iter()
        .any(|token| token.kind == TokenKind::BuiltinIdentifier));
}

#[test]
fn lexes_numeric_literals_with_range_disambiguation() {
    let source = "1..=2 3.14 .5 5. 1e10 0b1010 0o755 0xFF 0x1.fp3\n";
    let out = Lexer::new(source, PathBuf::from("test.dyn")).lex();

    assert!(out.diagnostics.is_empty());
    assert_eq!(out.tokens[0].kind, TokenKind::IntLiteral);
    assert_eq!(out.tokens[0].lexeme, "1");
    assert_eq!(out.tokens[1].kind, TokenKind::Operator(Operator::DotDotEq));
    assert_eq!(out.tokens[2].kind, TokenKind::IntLiteral);
    assert_eq!(out.tokens[3].kind, TokenKind::FloatLiteral);
    assert_eq!(out.tokens[4].kind, TokenKind::FloatLiteral);
    assert_eq!(out.tokens[5].kind, TokenKind::FloatLiteral);
    assert_eq!(out.tokens[6].kind, TokenKind::FloatLiteral);
    assert_eq!(out.tokens[7].kind, TokenKind::IntLiteral);
    assert_eq!(out.tokens[8].kind, TokenKind::IntLiteral);
    assert_eq!(out.tokens[9].kind, TokenKind::IntLiteral);
    assert_eq!(out.tokens[10].kind, TokenKind::FloatLiteral);
}

#[test]
fn reports_invalid_numeric_literals_and_recovers() {
    let source = "0b102 1e+ 0x1.2\n";
    let out = Lexer::new(source, PathBuf::from("test.dyn")).lex();

    assert_eq!(out.diagnostics.len(), 3);
    assert!(out
        .diagnostics
        .iter()
        .all(|diagnostic| diagnostic.code == DiagnosticCode::E2005));
    assert_eq!(out.tokens[0].kind, TokenKind::IntLiteral);
    assert_eq!(out.tokens[1].kind, TokenKind::FloatLiteral);
    assert_eq!(out.tokens[2].kind, TokenKind::FloatLiteral);
    assert_eq!(out.tokens[3].kind, TokenKind::Eof);
}

#[test]
fn lexes_string_and_char_literals() {
    let source = "\"hi\\n\" 'a' '\\t'\n";
    let out = Lexer::new(source, PathBuf::from("test.dyn")).lex();

    assert!(out.diagnostics.is_empty());
    assert_eq!(out.tokens[0].kind, TokenKind::StringLiteral);
    assert_eq!(out.tokens[1].kind, TokenKind::CharLiteral);
    assert_eq!(out.tokens[2].kind, TokenKind::CharLiteral);
}

#[test]
fn reports_invalid_string_and_char_literals() {
    let source = "\"unterminated\n'' '\\x' 'ab'\n";
    let out = Lexer::new(source, PathBuf::from("test.dyn")).lex();

    assert!(out
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E2002));
    assert!(out
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == DiagnosticCode::E2003));
}
