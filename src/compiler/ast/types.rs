use crate::compiler::ast::{Expr, Ident};
use crate::compiler::diagnostics::SourceSpan;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TypeExpr {
    pub kind: TypeExprKind,
    pub span: SourceSpan,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TypeExprKind {
    Named(Ident),
    Applied {
        callee: Ident,
        args: Vec<TypeExpr>,
    },
    Pointer {
        mutable: bool,
        inner: Box<TypeExpr>,
    },
    Array {
        len: Option<Box<Expr>>,
        element: Box<TypeExpr>,
    },
    Slice {
        mutable: bool,
        element: Box<TypeExpr>,
    },
    Optional {
        inner: Box<TypeExpr>,
    },
    Function(FnType),
    Errorable {
        ok: Box<TypeExpr>,
        errors: Vec<Ident>,
    },
    Struct(StructType),
    Enum(EnumType),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FnType {
    pub params: Vec<FnTypeParam>,
    pub return_type: Box<TypeExpr>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FnTypeParam {
    pub name: Option<Ident>,
    pub ty: TypeExpr,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StructType {
    pub packed: bool,
    pub fields: Vec<StructFieldType>,
    pub members: Vec<StructMemberType>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StructFieldType {
    pub name: Ident,
    pub ty: TypeExpr,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StructMemberType {
    pub name: Ident,
    pub value: Expr,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EnumType {
    pub repr: Option<Box<TypeExpr>>,
    pub variants: Vec<EnumVariantType>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EnumVariantType {
    pub name: Ident,
    pub payload: Option<TypeExpr>,
}
