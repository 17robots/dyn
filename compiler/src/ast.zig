const std = @import("std");

const Operator = enum {
    // in order of precedent
    Not, // !
    OrOr, // ||
    AndAnd, // &&
    Eql, // ==
    Neql, // !=
    Less, // <
    Leql, // <=
    Gtr, // >
    Geql, // >=
    Add, // +
    AddAdd, // ++
    Sub, // -
    SubSub, // --
    Or, // |
    Xor, // ^
    Mul, // *
    Div, // /
    Mod, // %
    And, // &
    Shl, // <<
    Shr, // >>
};
const OpPrec = enum {
    PrecOrOr,
    PrecAndAnd,
    PrecCmp,
    PrecAdd,
    PrecMul,
};
const LitKind = enum {
    Int,
    Float,
    Char,
    String,
};

pub const Program = struct {
    decls: std.ArrayList(ModuleDeclaration),
    pub fn init(alloc: *std.mem.Allocator) Program {
        return .{ .decls = std.ArrayList(ModuleDeclaration).init(alloc) };
    }
};

// declarations
pub const Decl = union {
    i: ImportDecl,
    s: StructDecl,
    e: EnumDecl,
    v: VarDecl,
    f: FuncDecl,
};

pub const ModuleDeclaration = struct { public: bool, declaration: Decl };
pub const ImportDecl = struct {
    source: []const u8,
    imports: std.ArrayList(Import),
};
pub const StructDecl = struct {
    name: []const u8,
    fields: std.ArrayList(Field),
    methods: std.ArrayList(FuncDecl),
};
pub const EnumDecl = struct {
    name: []const u8,
    members: std.ArrayList(EnumMember),
};
pub const VarDecl = struct {
    type: Expr,
    mutable: bool,
    constant: bool,
    name: []const u8,
    initial: ?Expr,
};
pub const FuncDecl = struct {
    return_type: Expr,
    name: []const u8,
    params: std.ArrayList(FuncParam),
    body: ?BlockStmt,
};

// expressions
pub const Expr = union {
    bl: BasicLit,
    fl: FuncLit,
    pe: ParenExpr,
    ae: AccessorExpr,
    ie: IndexExpr,
    se: SliceExpr,
    o: Operation,
    fe: FuncCallExpr,
};
pub const BasicLit = struct {
    kind: LitKind,
    val: []const u8,
};
pub const FuncLit = struct {
    type: FuncType,
    body: ?BlockStmt,
};
pub const ParenExpr = struct {
    expr: Expr,
};
pub const AccessorExpr = struct {
    expr: Expr,
    selector: []const u8,
};
pub const IndexExpr = struct {
    expr: Expr,
    index: Expr,
};
pub const SliceExpr = struct {
    expr: Expr,
    range: RangeClause,
};
pub const Operation = struct {
    op: Operator,
    lhs: ?Expr,
    rhs: ?Expr,
};
pub const FuncCallExpr = struct {
    name: []const u8,
    args: std.ArrayList(Expr),
};

// types
pub const ArrayType = struct {
    type: Expr,
    size: Expr,
};
pub const StructType = struct {
    fields: std.ArrayList(Field),
    methods: std.ArrayList(FuncDecl),
};
pub const FuncType = struct {
    result: Expr,
    params: std.ArrayList(Field),
};

// stmts
pub const Stmt = union {
    bls: BlockStmt,
    es: ExprStmt,
    decs: DeclStmt,
    as: AssignStmt,
    defs: DeferStmt,
    rs: ReturnStmt,
    brs: BreakStmt,
    cs: ContinueStmt,
    is: IfStmt,
    fs: ForStmt,
    ms: MatchStmt,
};
pub const BlockStmt = struct {
    stmts: std.ArrayList(Stmt),
};
pub const ExprStmt = struct {
    expr: Expr,
};
pub const DeclStmt = struct {
    decl: Decl,
};
pub const AssignStmt = struct {
    op: Operator,
    lhs: Expr,
    rhs: Expr,
};
pub const DeferStmt = struct {
    stmt: Stmt,
};
pub const ReturnStmt = struct {
    expr: ?Expr,
};
pub const BreakStmt = struct {};
pub const ContinueStmt = struct {};
pub const IfStmt = struct {
    cond: Expr,
    body: Stmt,
    else_stmt: ?IfStmt,
};
pub const ForStmt = struct {
    cond: ?Expr,
    body: Stmt,
};
pub const MatchStmt = struct {
    match_var: Expr,
    match_branches: std.ArrayList(MatchBranch),
};

// other
pub const FuncParam = struct {
    type: Expr,
    name: []const u8,
    default: ?Expr,
};
pub const Field = struct {
    type: Expr,
    name: ?[]const u8,
    default: ?Expr,
};
pub const RangeClause = struct {
    lhs: ?Expr,
    rhs: ?Expr,
};
pub const MatchBranch = struct {
    val: ?Expr,
    default: bool,
    body: Stmt,
};
pub const EnumMember = struct {
    name: []const u8,
    partners: std.ArrayList(Expr),
};
pub const Import = struct {
    import: []const u8,
    alias: ?[]const u8,
};
