use crate::compiler::ast::{DocComment, Expr, Ident, TypeExpr, Visibility};
use crate::compiler::diagnostics::SourceSpan;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AstFile {
    pub module_decl: ModuleDecl,
    pub items: Vec<Item>,
    pub span: SourceSpan,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ModuleDecl {
    pub name: Ident,
    pub span: SourceSpan,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Item {
    Binding(Box<Binding>),
    ExprStmt(Box<Expr>),
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum BindingKind {
    Infer,
    Typed,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Binding {
    pub docs: Vec<DocComment>,
    pub visibility: Visibility,
    pub mutable: bool,
    pub kind: BindingKind,
    pub name: Ident,
    pub annotation: Option<TypeExpr>,
    pub value: Expr,
    pub span: SourceSpan,
}
