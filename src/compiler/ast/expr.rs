use crate::compiler::ast::{AssignOp, BinaryOp, Binding, Ident, Label, Pattern, TypeExpr, UnaryOp};
use crate::compiler::diagnostics::SourceSpan;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Expr {
    pub kind: ExprKind,
    pub span: SourceSpan,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ExprKind {
    Literal(Literal),
    Ident(Ident),
    BuiltinIdent(Ident),
    Unary {
        op: UnaryOp,
        expr: Box<Expr>,
    },
    Binary {
        op: BinaryOp,
        left: Box<Expr>,
        right: Box<Expr>,
    },
    Assign {
        op: AssignOp,
        target: Box<Expr>,
        value: Box<Expr>,
    },
    Call(CallExpr),
    FieldAccess {
        base: Box<Expr>,
        field: Ident,
    },
    DerefAccess {
        base: Box<Expr>,
    },
    Index {
        base: Box<Expr>,
        index: Box<Expr>,
    },
    Slice(SliceExpr),
    Block(BlockExpr),
    If(IfExpr),
    Match(MatchExpr),
    For(ForExpr),
    Break(BreakExpr),
    Continue,
    Return {
        value: Option<Box<Expr>>,
    },
    Defer(DeferExpr),
    OptionalUnwrap {
        expr: Box<Expr>,
    },
    ErrorUnwrap {
        expr: Box<Expr>,
    },
    OrElse(OrElseExpr),
    StructLiteral(StructLiteralExpr),
    ArrayLiteral(Vec<Expr>),
    TupleLiteral(Vec<Expr>),
    EnumVariantConstruct(EnumVariantExpr),
    Fn(FnExpr),
    Use {
        path: String,
    },
    TypeLiteral(TypeExpr),
    Comptime {
        expr: Box<Expr>,
    },
    Inline {
        expr: Box<Expr>,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Literal {
    Integer(String),
    Float(String),
    String(String),
    Char(char),
    Bool(bool),
    Null,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CallExpr {
    pub callee: Box<Expr>,
    pub args: Vec<CallArg>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CallArg {
    pub name: Option<Ident>,
    pub value: Expr,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SliceExpr {
    pub base: Box<Expr>,
    pub start: Option<Box<Expr>>,
    pub end: Option<Box<Expr>>,
    pub inclusive: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BlockExpr {
    pub label: Option<Label>,
    pub statements: Vec<Stmt>,
    pub tail_expr: Option<Box<Expr>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Stmt {
    Binding(Binding),
    Expr(Expr),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IfExpr {
    pub condition: Box<Expr>,
    pub capture: Option<IfCapture>,
    pub then_branch: Box<Expr>,
    pub else_branch: Option<Box<Expr>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IfCapture {
    pub binding: Option<Ident>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MatchExpr {
    pub scrutinee: Box<Expr>,
    pub arms: Vec<MatchArm>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MatchArm {
    pub pattern: Pattern,
    pub guard: Option<Expr>,
    pub value: Expr,
    pub span: SourceSpan,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ForExpr {
    Range {
        start: Box<Expr>,
        end: Box<Expr>,
        inclusive: bool,
        binding: Option<Ident>,
        body: Box<Expr>,
    },
    Iterate {
        iterable: Box<Expr>,
        binding: Option<Ident>,
        body: Box<Expr>,
    },
    WhileLike {
        condition: Box<Expr>,
        body: Box<Expr>,
    },
    Infinite {
        body: Box<Expr>,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BreakExpr {
    pub label: Option<Label>,
    pub value: Option<Box<Expr>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeferExpr {
    pub error_binding: Option<Ident>,
    pub body: Box<Expr>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OrElseExpr {
    pub value: Box<Expr>,
    pub error_binding: Option<Ident>,
    pub fallback: Box<Expr>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StructLiteralExpr {
    pub root_type: Option<Ident>,
    pub fields: Vec<StructLiteralField>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StructLiteralField {
    pub name: Ident,
    pub value: Expr,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EnumVariantExpr {
    pub root: Option<Ident>,
    pub variant: Ident,
    pub payload: Vec<Expr>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FnExpr {
    pub params: Vec<FnParam>,
    pub return_type: Option<TypeExpr>,
    pub body: FnBody,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FnParam {
    pub name: Ident,
    pub ty: Option<TypeExpr>,
    pub default_value: Option<Expr>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FnBody {
    Block(BlockExpr),
    ArrowExpr(Box<Expr>),
}
