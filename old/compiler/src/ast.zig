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
    pub fn init(alloc: std.mem.Allocator) Program {
        return .{ .decls = std.ArrayList(ModuleDeclaration).init(alloc) };
    }
};

// declarations
pub const Decl = union(enum) {
    i: ImportDecl,
    s: StructDecl,
    e: EnumDecl,
    v: VarDecl,
    f: FuncDecl,
};

pub const ModuleDeclaration = struct {
    public: bool,
    declaration: Decl,
    pub fn init(decl: Decl, public: bool) ModuleDeclaration {
        return .{
            .public = public,
            .declaration = decl,
        };
    }
    pub fn deinit(s: *ModuleDeclaration) void {
        switch (s.declaration) {
            .i => |*import| import.deinit(),
            .s => |*str| str.deinit(),
            .e => |*enm| enm.deinit(),
            .v => |*varbl| varbl.deinit(),
            .f => |*func| func.deinit(),
        }
    }
};
pub const ImportDecl = struct {
    source: []const u8,
    imports: std.ArrayList(Import),
    pub fn init(source: []const u8, alloc: std.mem.Allocator) ImportDecl {
        return .{
            .source = source,
            .imports = std.ArrayList(Import).init(alloc),
        };
    }
    pub fn deinit(s: *ImportDecl) void {
        s.imports.deinit();
    }
};
pub const StructDecl = struct {
    name: []const u8,
    fields: std.ArrayList(Field),
    methods: std.ArrayList(FuncDecl),
    pub fn init(name: []const u8, alloc: std.mem.Allocator) StructDecl {
        return .{
            .name = name,
            .fields = std.ArrayList.init(alloc),
            .methods = std.ArrayList.init(alloc),
        };
    }
    pub fn deinit(s: *StructDecl) void {
        s.methods.deinit();
        s.fields.deinit();
    }
};
pub const EnumDecl = struct {
    name: []const u8,
    members: std.ArrayList(EnumMember),
    pub fn init(name: []const u8) EnumDecl {
        return .{
            .name = name,
            .members = std.ArrayList(EnumMember).init(),
        };
    }
    pub fn deinit(s: *EnumDecl) void {
        s.members.deinit();
    }
};
pub const VarDecl = struct {
    type: *Expr,
    mutable: bool,
    constant: bool,
    name: []const u8,
    initial: *?Expr,
    pub fn init(t: *Expr, mutable: bool, constant: bool, name: []const u8, initial: *?Expr) !VarDecl {
        if (constant and mutable) {} // we have an error
        return .{
            .type = t,
            .mutable = mutable,
            .constant = constant,
            .name = name,
            .initial = initial,
        };
    }
    pub fn deinit(s: *VarDecl) void {
        _ = s;
    }
};
pub const FuncDecl = struct {
    return_type: *Expr,
    name: []const u8,
    params: std.ArrayList(FuncParam),
    body: ?*BlockStmt,
    pub fn init(alloc: std.mem.Allocator, return_type: *Expr, name: []const u8, body: ?*BlockStmt) FuncDecl {
        return .{
            .return_type = return_type,
            .name = name,
            .body = body,
            .params = std.ArrayList(FuncParam).init(alloc),
        };
    }
    pub fn deinit(s: *FuncDecl) void {
        s.params.deinit();
    }
};

// expressions
pub const Expr = union(enum) {
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
    pub fn init(kind: LitKind, val: []const u8) BasicLit {
        return .{ .kind = kind, .val = val };
    }
    pub fn deinit(s: *BasicLit) void {
        _ = s;
    }
};
pub const FuncLit = struct {
    type: *FuncType,
    body: *?BlockStmt,
    pub fn init(t: *FuncType, body: *?BlockStmt) FuncLit {
        return .{ .type = t, .body = body };
    }
    pub fn deinit(s: *FuncLit) void {
        _ = s;
    }
};
pub const ParenExpr = struct {
    expr: *Expr,
    pub fn init(expr: *Expr) ParenExpr {
        return .{
            .expr = expr,
        };
    }
    pub fn deinit(s: *ParenExpr) void {
        _ = s;
    }
};
pub const AccessorExpr = struct {
    expr: *Expr,
    selector: []const u8,
    pub fn init(expr: *Expr, selector: []const u8) AccessorExpr {
        return .{
            .expr = expr,
            .selector = selector,
        };
    }
    pub fn deinit(s: *AccessorExpr) void {
        _ = s;
    }
};
pub const IndexExpr = struct {
    expr: *Expr,
    index: *Expr,
    pub fn init(expr: *Expr, index: *Expr) IndexExpr {
        return .{
            .expr = expr,
            .index = index,
        };
    }
    pub fn deinit(s: *IndexExpr) void {
        _ = s;
    }
};
pub const SliceExpr = struct {
    expr: *Expr,
    range: *RangeClause,
    pub fn init(expr: *Expr, range: *RangeClause) SliceExpr {
        return .{ .expr = expr, .range = range };
    }
    pub fn deinit(s: *SliceExpr) void {
        _ = s;
    }
};
pub const Operation = struct {
    op: Operator,
    lhs: *?Expr,
    rhs: *?Expr,
    pub fn init(op: Operator, lhs: *?Expr, rhs: *?Expr) Operation {
        return .{
            .op = op,
            .lhs = lhs,
            .rhs = rhs,
        };
    }
    pub fn deinit(s: *Operation) void {
        _ = s;
    }
};
pub const FuncCallExpr = struct {
    name: []const u8,
    args: std.ArrayList(Expr),
    pub fn init(alloc: std.mem.Allocator, name: []const u8) FuncCallExpr {
        return .{ .name = name, .args = std.ArrayList(Expr).init(alloc) };
    }
    pub fn deinit(s: *FuncCallExpr) void {
        s.args.deinit();
    }
};

// types
pub const ArrayType = struct {
    type: *Expr,
    size: *Expr,
    pub fn init(t: *Expr, size: *Expr) ArrayType {
        return .{
            .type = t,
            .size = size,
        };
    }
    pub fn deinit(s: *ArrayType) void {
        _ = s;
    }
};
pub const StructType = struct {
    fields: std.ArrayList(Field),
    methods: std.ArrayList(FuncDecl),
    pub fn init(alloc: std.mem.Allocator) StructType {
        return .{
            .fields = std.ArrayList(Field).init(alloc),
            .methods = std.ArrayList(FuncDecl).init(alloc),
        };
    }
    pub fn deinit(s: *StructType) void {
        s.fields.deinit();
        s.methods.deinit();
    }
};
pub const FuncType = struct {
    result: *Expr,
    params: std.ArrayList(Field),
    pub fn init(alloc: std.mem.Allocator, result: *Expr) FuncType {
        return .{ .result = result, .params = std.ArrayList(Field).init(alloc) };
    }
    pub fn deinit(s: *FuncType) void {
        s.params.deinit();
    }
};

// stmts
pub const Stmt = union(enum) {
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
    pub fn init(alloc: std.mem.Allocator) BlockStmt {
        return .{ .stmts = std.ArrayList(Stmt).init(alloc) };
    }
    pub fn deinit(s: *BlockStmt) void {
        s.stmts.deinit();
    }
};
pub const ExprStmt = struct {
    expr: *Expr,
    pub fn init(expr: *Expr) ExprStmt {
        return .{ .expr = expr };
    }
    pub fn deinit(s: *ExprStmt) void {
        _ = s;
    }
};
pub const DeclStmt = struct {
    decl: *Decl,
    pub fn init(decl: *Decl) DeclStmt {
        return .{ .decl = decl };
    }
    pub fn deinit(s: *DeclStmt) void {
        _ = s;
    }
};
pub const AssignStmt = struct {
    op: Operator,
    lhs: *Expr,
    rhs: *Expr,
    pub fn init(op: Operator, lhs: *Expr, rhs: *Expr) AssignStmt {
        return .{
            .op = op,
            .lhs = lhs,
            .rhs = rhs,
        };
    }
    pub fn deinit(s: *AssignStmt) void {
        _ = s;
    }
};
pub const DeferStmt = struct {
    stmt: *Stmt,
    pub fn init(stmt: *Stmt) DeferStmt {
        return .{ .stmt = stmt };
    }
    pub fn deinit(s: *DeferStmt) void {
        _ = s;
    }
};
pub const ReturnStmt = struct {
    expr: *?Expr,
    pub fn init(expr: *?Expr) ReturnStmt {
        return .{ .expr = expr };
    }
    pub fn deinit(s: *ReturnStmt) void {
        _ = s;
    }
};
pub const BreakStmt = struct {};
pub const ContinueStmt = struct {};
pub const IfStmt = struct {
    cond: *Expr,
    body: *Stmt,
    else_stmt: ?*IfStmt,
    pub fn init(cond: *Expr, body: *Stmt, else_stmt: ?*IfStmt) IfStmt {
        return .{
            .cond = cond,
            .body = body,
            .else_stmt = else_stmt,
        };
    }
    pub fn deinit(s: *IfStmt) void {
        _ = s;
    }
};
pub const ForStmt = struct {
    cond: *?Expr,
    body: *Stmt,
    pub fn init(cond: *?Expr, body: *Stmt) ForStmt {
        return .{ .cond = cond, .body = body };
    }
    pub fn deinit(s: *ForStmt) void {
        _ = s;
    }
};
pub const MatchStmt = struct {
    match_var: *Expr,
    match_branches: std.ArrayList(MatchBranch),
    pub fn init(alloc: std.mem.Allocator, match_var: *Expr) MatchStmt {
        return .{
            .match_var = match_var,
            .match_branches = std.ArrayList(MatchBranch).init(alloc),
        };
    }
    pub fn deinit(s: *MatchStmt) void {
        s.match_branches.deinit();
    }
};

// other
pub const FuncParam = struct {
    type: *Expr,
    name: []const u8,
    default: *?Expr,
    pub fn init(t: *Expr, name: []const u8, default: *?Expr) FuncParam {
        return .{
            .type = t,
            .name = name,
            .default = default,
        };
    }
    pub fn deinit(s: *FuncParam) void {
        _ = s;
    }
};
pub const Field = struct {
    type: *Expr,
    name: ?[]const u8,
    default: *?Expr,
    pub fn init(t: *Expr, name: ?[]const u8, default: *?Expr) Field {
        return .{
            .type = t,
            .name = name,
            .default = default,
        };
    }
    pub fn deinit(s: *Field) void {
        _ = s;
    }
};
pub const RangeClause = struct {
    lhs: *?Expr,
    rhs: *?Expr,
    pub fn init(lhs: *?Expr, rhs: *?Expr) RangeClause {
        return .{ .lhs = lhs, .rhs = rhs };
    }
    pub fn deinit(s: *RangeClause) void {
        _ = s;
    }
};
pub const MatchBranch = struct {
    val: *?Expr,
    default: bool,
    body: *Stmt,
    pub fn init(val: *?Expr, default: bool, body: *Stmt) MatchBranch {
        return .{
            .val = val,
            .default = default,
            .body = body,
        };
    }
    pub fn deinit(s: *MatchBranch) void {
        _ = s;
    }
};
pub const EnumMember = struct {
    name: []const u8,
    partners: std.ArrayList(Expr),
    pub fn init(alloc: std.mem.Allocator, name: []const u8) EnumMember {
        return .{ .name = name, .partners = std.ArrayList(Expr).init(alloc) };
    }
    pub fn deinit(s: *EnumMember) void {
        s.partners.deinit();
    }
};
pub const Import = struct {
    import: []const u8,
    alias: ?[]const u8,
    pub fn init(import: []const u8, alias: ?[]const u8) Import {
        return .{ .import = import, .alias = alias };
    }
    pub fn deinit(s: *Import) void {
        _ = s;
    }
};
