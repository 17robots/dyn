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

// expr
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
    Continue {
        label: Option<Label>,
    },
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
    /// `expr { field: val, ... }` — construct a struct whose type is the result of evaluating
    /// `ty_expr`. Used for patterns like `get_type(){}` where a function returns a `type`.
    TypeConstruct {
        ty_expr: Box<Expr>,
        fields: Vec<StructLiteralField>,
    },
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
    Declaration(Box<Declaration>),
    Assignment(Box<AssignmentStmt>),
    Expr(Box<Expr>),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AssignmentStmt {
    pub op: AssignOp,
    pub target: Expr,
    pub value: Expr,
    pub span: SourceSpan,
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
    pub bindings: Vec<Option<Ident>>,
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
    /// True if the parameter was annotated with `comp`, meaning the argument
    /// must be a compile-time-known value.
    pub comp: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FnBody {
    Block(BlockExpr),
    ArrowExpr(Box<Expr>),
}

// ids
#[derive(Debug, Copy, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct FileId(pub usize);

#[derive(Debug, Copy, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct ItemId(pub usize);

#[derive(Debug, Copy, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct StmtId(pub usize);

#[derive(Debug, Copy, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct ExprId(pub usize);

#[derive(Debug, Copy, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct TypeId(pub usize);

#[derive(Debug, Copy, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct PatternId(pub usize);

// items
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
    Declaration(Box<Declaration>),
    ExprStmt(Box<Expr>),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Declaration {
    pub docs: Vec<DocComment>,
    pub visibility: Visibility,
    pub modifiers: DeclModifiers,
    pub target: DeclTarget,
    pub annotation: Option<TypeExpr>,
    pub value: DeclValue,
    pub span: SourceSpan,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeclModifiers {
    pub mutable: bool,
    pub inline: bool,
    pub linkage: Linkage,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Linkage {
    Normal,
    Extern { link_name: Option<String> },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DeclTarget {
    Name(Ident),
    Associated { owner: Ident, member: Ident },
    Destructure(Vec<DestructureName>),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DeclValue {
    Expr(Expr),
    ExternSignature(ExternSignature),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExternSignature {
    pub ty: TypeExpr,
    pub link_name: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DestructureName {
    pub mutable: bool,
    pub name: Ident,
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

impl Declaration {
    pub fn expr_value(&self) -> Option<&Expr> {
        match &self.value {
            DeclValue::Expr(expr) => Some(expr),
            DeclValue::ExternSignature(_) => None,
        }
    }

    pub fn expr_value_mut(&mut self) -> Option<&mut Expr> {
        match &mut self.value {
            DeclValue::Expr(expr) => Some(expr),
            DeclValue::ExternSignature(_) => None,
        }
    }
}

// op
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum UnaryOp {
    Neg,
    Not,
    BitNot,
    Ref,
    RefMut,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum BinaryOp {
    Add,
    Sub,
    Mul,
    Div,
    Mod,
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
    LogicalAnd,
    LogicalOr,
    BitAnd,
    BitOr,
    BitXor,
    Shl,
    Shr,
    Range,
    RangeInclusive,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum AssignOp {
    Assign,
    AddAssign,
    SubAssign,
    MulAssign,
    DivAssign,
    ModAssign,
    BitAndAssign,
    BitOrAssign,
    BitXorAssign,
    ShlAssign,
    ShrAssign,
}

// pattern
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
    /// A type expression used as a pattern in `comp match $typeof(v) { []u8: ... }`
    TypeLiteral(TypeExpr),
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

// types
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
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StructFieldType {
    pub name: Ident,
    pub ty: TypeExpr,
    pub default_value: Option<Expr>,
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
    pub members: Vec<StructMemberType>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EnumVariantType {
    pub name: Ident,
    pub payload: Option<TypeExpr>,
}
