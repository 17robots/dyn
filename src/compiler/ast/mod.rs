pub mod expr;
pub mod ids;
pub mod item;
pub mod op;
pub mod pattern;
pub mod types;

pub use expr::*;
pub use ids::*;
pub use item::*;
pub use op::*;
pub use pattern::*;
pub use types::*;

use crate::compiler::diagnostics::SourceSpan;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Ident {
    pub text: String,
    pub span: SourceSpan,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Label {
    pub name: Ident,
    pub span: SourceSpan,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum Visibility {
    Private,
    Public,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DocComment {
    pub text: String,
    pub span: SourceSpan,
}
