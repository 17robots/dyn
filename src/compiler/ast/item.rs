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
    Destructure(Box<DestructureBinding>),
    Extern(Box<ExternDecl>),
    ExprStmt(Box<Expr>),
}

/// `{a, b} := expr` — destructure the RHS by field name into multiple bindings.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DestructureBinding {
    pub docs: Vec<DocComment>,
    pub visibility: Visibility,
    pub names: Vec<DestructureName>,
    pub value: Expr,
    pub span: SourceSpan,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DestructureName {
    pub mutable: bool,
    pub name: Ident,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExternDecl {
    pub docs: Vec<DocComment>,
    pub visibility: Visibility,
    pub name: Ident,
    pub ty: TypeExpr,
    pub link_name: Option<String>,
    pub span: SourceSpan,
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
