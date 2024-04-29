const std = @import("std");

const Operator = enum {};

pub const Program = struct {};

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
pub const BasicLit = struct {};
pub const FuncLit = struct {};
pub const ParenExpr = struct {};
pub const AccessorExpr = struct {};
pub const IndexExpr = struct {};
pub const SliceExpr = struct {};
pub const Operation = struct {};
pub const FuncCallExpr = struct {};

// types
pub const ArrayType = struct {
    type: Expr,
    size: Expr,
};
pub const StructType = struct {
    fields: std.ArrayList(Field),
    methods: std.ArrayList(FuncDecl),
};
pub const FuncType = struct {};

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
    name: []const u8,
    default: ?Expr,
};
pub const RangeClause = struct {
    lhs: Expr,
    rhs: Expr,
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
