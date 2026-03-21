pub mod lower;

pub use lower::*;

use crate::compiler::ast::Visibility;
use crate::compiler::ast::{AssignOp, BinaryOp, UnaryOp};
use crate::compiler::diagnostics::SourceSpan;
use crate::compiler::module_resolver::{ModuleId, ModuleKey};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HirProgram {
    pub modules: Vec<HirModule>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HirModule {
    pub module_id: ModuleId,
    pub key: ModuleKey,
    pub items: Vec<HirItem>,
    pub extern_functions: Vec<HirExternFunction>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HirExternFunction {
    pub name: String,
    pub link_name: Option<String>,
    pub return_type: Option<String>,
    pub param_type_hints: Vec<Option<String>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HirItem {
    pub name: String,
    pub def_id: Option<usize>,
    pub visibility: Visibility,
    pub mutable: bool,
    pub type_hint: Option<String>,
    pub inferred_type: Option<String>,
    pub value: HirExpr,
    pub span: SourceSpan,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HirExpr {
    pub kind: HirExprKind,
    pub span: SourceSpan,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HirCallArg {
    pub name: Option<String>,
    pub value: HirExpr,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HirIfCapture {
    pub binding: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HirExprKind {
    Literal(HirLiteral),
    Ident(String),
    Unary {
        op: UnaryOp,
        expr: Box<HirExpr>,
    },
    Binary {
        op: BinaryOp,
        left: Box<HirExpr>,
        right: Box<HirExpr>,
    },
    Assign {
        op: AssignOp,
        target: Box<HirExpr>,
        value: Box<HirExpr>,
    },
    Call {
        callee: Box<HirExpr>,
        args: Vec<HirCallArg>,
    },
    FieldAccess {
        base: Box<HirExpr>,
        field: String,
    },
    DerefAccess {
        base: Box<HirExpr>,
    },
    Index {
        base: Box<HirExpr>,
        index: Box<HirExpr>,
    },
    Slice {
        base: Box<HirExpr>,
        start: Option<Box<HirExpr>>,
        end: Option<Box<HirExpr>>,
        inclusive: bool,
    },
    StructLiteral {
        root_type: Option<String>,
        fields: Vec<(String, HirExpr)>,
    },
    EnumVariant {
        root: Option<String>,
        variant: String,
        payload: Vec<HirExpr>,
    },
    Block {
        body: Vec<HirExpr>,
    },
    Let {
        name: String,
        mutable: bool,
        type_hint: Option<String>,
        value: Box<HirExpr>,
    },
    If {
        condition: Box<HirExpr>,
        capture: Option<HirIfCapture>,
        then_branch: Box<HirExpr>,
        else_branch: Option<Box<HirExpr>>,
    },
    Match {
        value: Box<HirExpr>,
        arms: Vec<HirMatchArm>,
    },
    For(HirForExpr),
    Break {
        value: Option<Box<HirExpr>>,
    },
    Continue,
    Return {
        value: Option<Box<HirExpr>>,
    },
    Defer {
        error_binding: Option<String>,
        body: Box<HirExpr>,
    },
    OptionalUnwrap {
        value: Box<HirExpr>,
    },
    ErrorUnwrap {
        value: Box<HirExpr>,
    },
    OrElse {
        value: Box<HirExpr>,
        error_binding: Option<String>,
        fallback: Box<HirExpr>,
    },
    Use {
        path: String,
    },
    TypeLiteral(String),
    Comptime {
        expr: Box<HirExpr>,
    },
    Inline {
        expr: Box<HirExpr>,
    },
    Function {
        params: Vec<String>,
        param_types: Vec<Option<String>>,
        param_defaults: Vec<Option<HirExpr>>,
        has_explicit_return_type: bool,
        body: Box<HirExpr>,
    },
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HirForExpr {
    Infinite {
        body: Box<HirExpr>,
    },
    WhileLike {
        condition: Box<HirExpr>,
        body: Box<HirExpr>,
    },
    Range {
        start: Box<HirExpr>,
        end: Box<HirExpr>,
        inclusive: bool,
        binding: Option<String>,
        body: Box<HirExpr>,
    },
    Iterate {
        iterable: Box<HirExpr>,
        binding: Option<String>,
        body: Box<HirExpr>,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HirMatchArm {
    pub pattern: HirPattern,
    pub guard: Option<HirExpr>,
    pub value: HirExpr,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HirPattern {
    Wildcard,
    IdentBind(String),
    Literal(HirLiteral),
    RangeLiteral {
        start: HirLiteral,
        end: HirLiteral,
        inclusive: bool,
    },
    EnumVariant {
        root: Option<String>,
        variant: String,
        bindings: Vec<String>,
    },
    Other,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HirLiteral {
    Integer(String),
    Float(String),
    String(String),
    Char(char),
    Bool(bool),
    Null,
}
