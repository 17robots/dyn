const std = @import("std");
const source = @import("source.zig");

pub const ExprId = enum(u32) { _ };
pub const PatternId = enum(u32) { _ };
pub const StmtId = enum(u32) { _ };
pub const DeclId = enum(u32) { _ };
pub const TopLevelItemId = enum(u32) { _ };
pub const Ident = struct {
    name: []const u8,
    span: source.Span,
};
pub const Visibility = enum { private, public };
pub const Mutability = enum { immutable, mutable };
pub const FunctionFlavor = enum { normal, inline_ };
pub const BodyKind = enum { block, arrow };
pub const UnaryOp = enum { not, neg, bit_not, address_of, comp };
pub const BinaryOp = enum { add, sub, mul, div, rem, bit_and, bit_or, bit_xor, shl, shr, lt, le, gt, ge, eq, ne, logical_and, logical_or, range_exclusive, range_inclusive, or_else };
pub const AssignOp = enum { assign, add, sub, mul, div, rem, bit_and, bit_or, bit_xor, bit_not, shl, shr };
pub const Literal = union(enum) {
    integer: []const u8,
    float: []const u8,
    string: []const u8,
    char: []const u8,
    true,
    false,
    null,
};
pub const Path = struct { parts: []Ident, span: source.Span };
pub const ParamType = union(enum) {
    ordinary: ExprId,
    mut_pointer: ExprId,
    mut_slice: ExprId,
};
pub const Param = struct {
    name: ?Ident,
    ty: ParamType,
    default_value: ?ExprId = null,
    is_comptime: bool = false,
    span: source.Span,
};
pub const Arg = struct {
    name: ?Ident = null,
    value: ExprId,
    span: source.Span,
};
pub const FieldInit = struct {
    name: Ident,
    value: ?ExprId = null,
    span: source.Span,
};
pub const StructField = struct {
    name: Ident,
    ty: ExprId,
    default_value: ?ExprId = null,
    span: source.Span,
};
pub const EnumVariant = struct {
    name: Ident,
    payload: ?ExprId = null,
    span: source.Span,
};
pub const MatchArm = struct {
    patterns: []PatternId,
    guard: ?ExprId = null,
    captures: []Ident = &.{},
    body: ExprId,
    span: source.Span,
};
pub const CaptureList = struct { bindings: []Ident, span: source.Span };
pub const Expr = struct {
    span: source.Span,
    kind: Kind,

    pub const Kind = union(enum) {
        err,
        literal: Literal,
        identifier: Ident,
        builtin_identifier: Ident,
        path: Path,
        block: []StmtId,
        grouped: ExprId,
        array_literal: []ExprId,
        array_type: struct { len: ExprId, elem: ExprId },
        slice_type: ExprId,
        tuple_literal: []ExprId,
        anon_struct_literal: []FieldInit,
        typed_struct_literal: struct { ty: ExprId, fields: []FieldInit },
        struct_type: []StructField,
        enum_type: struct { repr: ?ExprId = null, variants: []EnumVariant },
        use: []const u8,
        function: struct { flavor: FunctionFlavor = .normal, params: []Param, return_type: ?ExprId = null, error_types: []ExprId = &.{}, body: ExprId, body_kind: BodyKind },
        call: struct { callee: ExprId, args: []Arg },
        member: struct { object: ExprId, name: Ident },
        index: struct { object: ExprId, index: ExprId },
        deref: ExprId,
        optional_unwrap: ExprId,
        error_unwrap: ExprId,
        error_union_type: struct { ok: ExprId, errors: []ExprId = &.{} },
        unary: struct { op: UnaryOp, operand: ExprId },
        binary: struct { op: BinaryOp, lhs: ExprId, rhs: ExprId },
        or_fallback: struct { lhs: ExprId, capture: ?Ident = null, rhs: ExprId },
        if_expr: struct { condition: ExprId, captures: ?CaptureList = null, then_branch: ExprId, else_branch: ?ExprId = null },
        match_expr: struct { subject: ExprId, arms: []MatchArm },
        for_expr: struct { inline_: bool = false, head: ?ForHead = null, body: ExprId },
        labeled: struct { label: Ident, expr: ExprId },
    };
};
pub const ForHead = union(enum) {
    iteration: struct { iterables: []ExprId, captures: CaptureList },
    while_: struct { condition: ExprId, captures: ?CaptureList = null },
};
pub const Pattern = struct {
    span: source.Span,
    kind: Kind,

    pub const Kind = union(enum) {
        err,
        wildcard,
        identifier: Ident,
        literal: Literal,
        literal_range: struct { start: Literal, end: Literal, inclusive: bool },
        enum_variant: struct { path: Path, payload_binding: ?Ident = null },
        multi: []PatternId,
    };
};
pub const Declaration = struct {
    span: source.Span,
    visibility: Visibility = .private,
    mutability: Mutability = .immutable,
    target: Target,
    annotation: ?ExprId = null,
    value: ExprId,
    value_flavor: FunctionFlavor = .normal,

    pub const Target = union(enum) {
        name: Ident,
        associated: struct { type_path: Path, name: Ident },
        destructure: []PatternId,
        err,
    };
};
pub const Stmt = struct {
    span: source.Span,
    kind: Kind,

    pub const Kind = union(enum) {
        err,
        declaration: DeclId,
        assignment: struct { lhs: ExprId, op: AssignOp, rhs: ExprId },
        destructure_assign: struct { patterns: []PatternId, value: ExprId },
        return_: ?ExprId,
        break_: struct { label: ?Ident = null, value: ?ExprId = null },
        continue_: ?Ident,
        defer_: struct { capture: ?Ident = null, body: ExprId },
        if_stmt: ExprId,
        for_stmt: ExprId,
        match_stmt: ExprId,
        labeled: struct { label: Ident, stmt: StmtId },
        expr: ExprId,
    };
};
pub const TopLevelItem = struct {
    span: source.Span,
    kind: Kind,

    pub const Kind = union(enum) {
        declaration: DeclId,
        err,
    };
};
pub const File = struct {
    span: source.Span,
    module_name: Ident,
    items: []TopLevelItemId,
};
pub const Ast = struct {
    allocator: std.mem.Allocator,
    exprs: std.ArrayList(Expr),
    patterns: std.ArrayList(Pattern),
    stmts: std.ArrayList(Stmt),
    decls: std.ArrayList(Declaration),
    top_level_items: std.ArrayList(TopLevelItem),

    pub fn init(allocator: std.mem.Allocator) Ast {
        return .{
            .allocator = allocator,
            .exprs = .empty,
            .patterns = .empty,
            .stmts = .empty,
            .decls = .empty,
            .top_level_items = .empty,
        };
    }

    pub fn deinit(self: *Ast) void {
        self.exprs.deinit(self.allocator);
        self.patterns.deinit(self.allocator);
        self.stmts.deinit(self.allocator);
        self.decls.deinit(self.allocator);
        self.top_level_items.deinit(self.allocator);
    }

    pub fn addExpr(self: *Ast, node: Expr) !ExprId {
        const id: ExprId = @enumFromInt(self.exprs.items.len);
        try self.exprs.append(self.allocator, node);
        return id;
    }

    pub fn addPattern(self: *Ast, node: Pattern) !PatternId {
        const id: PatternId = @enumFromInt(self.patterns.items.len);
        try self.patterns.append(self.allocator, node);
        return id;
    }

    pub fn addStmt(self: *Ast, node: Stmt) !StmtId {
        const id: StmtId = @enumFromInt(self.stmts.items.len);
        try self.stmts.append(self.allocator, node);
        return id;
    }

    pub fn addDecl(self: *Ast, node: Declaration) !DeclId {
        const id: DeclId = @enumFromInt(self.decls.items.len);
        try self.decls.append(self.allocator, node);
        return id;
    }

    pub fn addTopLevelItem(self: *Ast, node: TopLevelItem) !TopLevelItemId {
        const id: TopLevelItemId = @enumFromInt(self.top_level_items.items.len);
        try self.top_level_items.append(self.allocator, node);
        return id;
    }

    pub fn expr(self: *const Ast, id: ExprId) *const Expr {
        return &self.exprs.items[@intFromEnum(id)];
    }
    pub fn pattern(self: *const Ast, id: PatternId) *const Pattern {
        return &self.patterns.items[@intFromEnum(id)];
    }
    pub fn stmt(self: *const Ast, id: StmtId) *const Stmt {
        return &self.stmts.items[@intFromEnum(id)];
    }
    pub fn decl(self: *const Ast, id: DeclId) *const Declaration {
        return &self.decls.items[@intFromEnum(id)];
    }
    pub fn topLevelItem(self: *const Ast, id: TopLevelItemId) *const TopLevelItem {
        return &self.top_level_items.items[@intFromEnum(id)];
    }
};
fn sp(start: u32, end: u32) source.Span {
    return .{ .start = start, .end = end };
}
fn ident(name: []const u8, start: u32, end: u32) Ident {
    return .{ .name = name, .span = sp(start, end) };
}

test "typed arenas allocate stable ids" {
    var ast = Ast.init(std.testing.allocator);
    defer ast.deinit();

    const a = try ast.addExpr(.{ .span = sp(0, 1), .kind = .{ .literal = .{ .integer = "1" } } });
    const b = try ast.addExpr(.{ .span = sp(2, 3), .kind = .{ .literal = .{ .integer = "2" } } });

    try std.testing.expectEqual(@as(u32, 0), @intFromEnum(a));
    try std.testing.expectEqual(@as(u32, 1), @intFromEnum(b));
    try std.testing.expectEqual(sp(2, 3), ast.expr(b).span);
}
test "error variants exist on expr pattern stmt" {
    var ast = Ast.init(std.testing.allocator);
    defer ast.deinit();

    const e = try ast.addExpr(.{ .span = sp(0, 0), .kind = .err });
    const p = try ast.addPattern(.{ .span = sp(0, 0), .kind = .err });
    const s = try ast.addStmt(.{ .span = sp(0, 0), .kind = .err });

    try std.testing.expect(ast.expr(e).kind == .err);
    try std.testing.expect(ast.pattern(p).kind == .err);
    try std.testing.expect(ast.stmt(s).kind == .err);
}
test "unified declaration covers named associated and destructure" {
    var ast = Ast.init(std.testing.allocator);
    defer ast.deinit();

    const value = try ast.addExpr(.{ .span = sp(5, 6), .kind = .{ .literal = .{ .integer = "1" } } });
    const ann = try ast.addExpr(.{ .span = sp(3, 6), .kind = .{ .identifier = ident("i32", 3, 6) } });
    const name_decl = try ast.addDecl(.{ .span = sp(0, 6), .mutability = .mutable, .target = .{ .name = ident("x", 0, 1) }, .annotation = ann, .value = value });
    try std.testing.expect(ast.decl(name_decl).target == .name);

    const parts = try std.testing.allocator.alloc(Ident, 1);
    defer std.testing.allocator.free(parts);
    parts[0] = ident("Point", 0, 5);
    const assoc = try ast.addDecl(.{ .span = sp(0, 16), .visibility = .public, .target = .{ .associated = .{ .type_path = .{ .parts = parts, .span = sp(0, 5) }, .name = ident("new", 6, 9) } }, .value = value });
    try std.testing.expect(ast.decl(assoc).target == .associated);

    const pat = try ast.addPattern(.{ .span = sp(1, 2), .kind = .{ .identifier = ident("x", 1, 2) } });
    const pats = try std.testing.allocator.alloc(PatternId, 1);
    defer std.testing.allocator.free(pats);
    pats[0] = pat;
    const destr = try ast.addDecl(.{ .span = sp(0, 8), .target = .{ .destructure = pats }, .value = value });
    try std.testing.expect(ast.decl(destr).target == .destructure);
}
