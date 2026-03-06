use crate::compiler::ast::{Ident, TypeExpr};
use crate::compiler::diagnostics::SourceSpan;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Pattern {
    pub kind: PatternKind,
    pub span: SourceSpan,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PatternKind {
    Wildcard,
    Literal(PatternLiteral),
    IdentBind(Ident),
    Range {
        start: Box<Pattern>,
        end: Box<Pattern>,
        inclusive: bool,
    },
    EnumVariant {
        root: Option<Ident>,
        variant: Ident,
        bindings: Vec<Ident>,
    },
    Typed {
        pattern: Box<Pattern>,
        ty: TypeExpr,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PatternLiteral {
    Integer(String),
    Float(String),
    String(String),
    Char(char),
    Bool(bool),
    Null,
}
