const std = @import("std");
const ast = @import("ast.zig");
const diag = @import("diag.zig");

pub const IntType = struct { bits: u16 = 32, signed: bool = true };
pub const Type = union(enum) { int: IntType, struct_: []const u8, ptr: []const u8, enum_: []const u8, array: struct { len: u64, elem: *const Type }, slice: *const Type, optional: *const Type, error_union: *const Type };
pub const Field = struct { name: []const u8, ty: Type };
pub const StructType = struct { name: []const u8, fields: []Field };
pub const EnumType = struct { name: []const u8, variants: []const []const u8 };
pub const Module = struct { structs: []StructType, enums: []EnumType, functions: []Function };
pub const Function = struct { name: []const u8, params: []const Param = &.{}, ret: Type, stmts: []Stmt };
pub const Param = struct { name: []const u8, ty: Type };
pub const Stmt = union(enum) { decl: struct { name: []const u8, ty: Type, value: Expr }, assign: struct { name: []const u8, value: Expr }, while_: struct { cond: Expr, body: []Stmt }, for_range: struct { name: []const u8, start: Expr, end: Expr, inclusive: bool = false, body: []Stmt }, for_indexed: struct { name: []const u8, iterable: []const u8, body: []Stmt }, ret: Expr };
pub const Expr = union(enum) {
    int: i64,
    string: []const u8,
    var_: []const u8,
    opt_payload: []const u8,
    array_lit: []Expr,
    index: struct { object: []const u8, index: *Expr },
    slice_from_array: struct { object: []const u8, start: *Expr, end: *Expr },
    call: struct { name: []const u8, args: []Expr },
    method_call: struct { receiver: []const u8, type_name: []const u8, method: []const u8, args: []Expr },
    field: struct { object: []const u8, name: []const u8 },
    struct_lit: struct { ty: []const u8, fields: []FieldValue },
    optional_some: *Expr,
    optional_null,
    optional_or: struct { name: []const u8, fallback: *Expr },
    error_some: *Expr,
    err_payload: []const u8,
    add: Bin,
    sub: Bin,
    mul: Bin,
    div: Bin,
    rem: Bin,
    eq: Bin,
    ne: Bin,
    lt: Bin,
    le: Bin,
    gt: Bin,
    ge: Bin,
    neg: *Expr,
    if_: struct { cond: *Expr, then_expr: *Expr, else_expr: *Expr },
    pub const Bin = struct { lhs: *Expr, rhs: *Expr };
};
pub const FieldValue = struct { name: []const u8, value: Expr };
const LowerError = anyerror;
const Ctx = struct { allocator: std.mem.Allocator, tree: *const ast.Ast, bag: *diag.DiagnosticBag, vars: std.StringHashMap(Type), funcs: std.StringHashMap(Type), structs: std.StringHashMap(StructType), enums: std.StringHashMap(EnumType) };
const i32t = Type{ .int = .{} };
pub fn lowerTrivial(allocator: std.mem.Allocator, tree: *const ast.Ast, file: ast.File, bag: *diag.DiagnosticBag) !?Module {
    var ctx = Ctx{ .allocator = allocator, .tree = tree, .bag = bag, .vars = .init(allocator), .funcs = .init(allocator), .structs = .init(allocator), .enums = .init(allocator) };
    defer ctx.vars.deinit();
    defer ctx.funcs.deinit();
    defer ctx.structs.deinit();
    defer ctx.enums.deinit();
    var structs = std.ArrayList(StructType).empty;
    var enums = std.ArrayList(EnumType).empty;
    for (file.items) |iid| {
        const it = tree.topLevelItem(iid);
        if (it.kind != .declaration) continue;
        const d = tree.decl(it.kind.declaration);
        if (d.target != .name) continue;
        const name = d.target.name.name;
        const de = tree.expr(d.value);
        if (de.kind == .struct_type) {
            var fs = std.ArrayList(Field).empty;
            for (de.kind.struct_type) |f| try fs.append(allocator, .{ .name = f.name.name, .ty = typeExpr(&ctx, f.ty) });
            const st = StructType{ .name = name, .fields = try fs.toOwnedSlice(allocator) };
            try structs.append(allocator, st);
            try ctx.structs.put(st.name, st);
        } else if (de.kind == .enum_type) {
            var vs = std.ArrayList([]const u8).empty;
            for (de.kind.enum_type.variants) |v| try vs.append(allocator, v.name.name);
            const et = EnumType{ .name = name, .variants = try vs.toOwnedSlice(allocator) };
            try enums.append(allocator, et);
            try ctx.enums.put(et.name, et);
        }
    }
    for (file.items) |iid| {
        const item = tree.topLevelItem(iid);
        if (item.kind != .declaration) continue;
        const d = tree.decl(item.kind.declaration);
        if (tree.expr(d.value).kind == .function) {
            const fname = switch (d.target) {
                .name => |n| n.name,
                .associated => |a| try std.fmt.allocPrint(allocator, "{s}.{s}", .{ a.type_path.parts[0].name, a.name.name }),
                else => continue,
            };
            try ctx.funcs.put(fname, retTypeOf(&ctx, tree.expr(d.value).kind.function));
        }
    }
    var funcs = std.ArrayList(Function).empty;
    var has_main = false;
    for (file.items) |iid| {
        const item = tree.topLevelItem(iid);
        if (item.kind != .declaration) continue;
        const d = tree.decl(item.kind.declaration);
        const e = tree.expr(d.value);
        if (e.kind != .function) continue;
        const name = switch (d.target) {
            .name => |n| n.name,
            .associated => |a| try std.fmt.allocPrint(allocator, "{s}.{s}", .{ a.type_path.parts[0].name, a.name.name }),
            else => continue,
        };
        if (std.mem.eql(u8, name, "main")) has_main = true;
        const f = e.kind.function;
        var params = std.ArrayList(Param).empty;
        ctx.vars.clearRetainingCapacity();
        for (f.params) |p| if (p.name) |pn| {
            const ty = paramType(&ctx, p);
            try params.append(allocator, .{ .name = pn.name, .ty = ty });
            try ctx.vars.put(pn.name, ty);
        } else {
            try bag.errorAt("C0002", "codegen requires named parameters", e.span, "unnamed parameter");
            return null;
        };
        const ret = retTypeOf(&ctx, f);
        try funcs.append(allocator, .{ .name = name, .params = try params.toOwnedSlice(allocator), .ret = ret, .stmts = (try lowerFunctionBody(&ctx, f)) orelse return null });
    }
    if (!has_main) {
        try bag.errorAt("C0003", "main function not found", file.span, "missing `main`");
        return null;
    }
    return .{ .structs = try structs.toOwnedSlice(allocator), .enums = try enums.toOwnedSlice(allocator), .functions = try funcs.toOwnedSlice(allocator) };
}
fn retTypeOf(ctx: *Ctx, f: anytype) Type {
    return if (f.return_type) |rt| typeExpr(ctx, rt) else i32t;
}
fn paramType(ctx: *Ctx, p: ast.Param) Type {
    return switch (p.ty) {
        .ordinary => |e| typeExpr(ctx, e),
        .mut_pointer => |e| ptrType(ctx, e),
        else => i32t,
    };
}
fn ptrType(ctx: *Ctx, id: ast.ExprId) Type {
    const t = typeExpr(ctx, id);
    return switch (t) {
        .struct_ => |s| .{ .ptr = s },
        else => i32t,
    };
}
fn typeExpr(ctx: *Ctx, id: ast.ExprId) Type {
    const e = ctx.tree.expr(id);
    if (e.kind == .array_type) {
        const p = ctx.allocator.create(Type) catch return i32t;
        p.* = typeExpr(ctx, e.kind.array_type.elem);
        const len_e = ctx.tree.expr(e.kind.array_type.len);
        const len: u64 = if (len_e.kind == .literal and len_e.kind.literal == .integer) std.fmt.parseInt(u64, len_e.kind.literal.integer, 10) catch 0 else 0;
        return .{ .array = .{ .len = len, .elem = p } };
    }
    if (e.kind == .slice_type) {
        const p = ctx.allocator.create(Type) catch return i32t;
        p.* = typeExpr(ctx, e.kind.slice_type);
        return .{ .slice = p };
    }
    if (e.kind == .unary and e.kind.unary.op == .not) {
        const p = ctx.allocator.create(Type) catch return i32t;
        p.* = typeExpr(ctx, e.kind.unary.operand);
        return .{ .optional = p };
    }
    if (e.kind == .error_unwrap) {
        const p = ctx.allocator.create(Type) catch return i32t;
        p.* = typeExpr(ctx, e.kind.error_unwrap);
        return .{ .error_union = p };
    }
    if (e.kind == .error_union_type) {
        const p = ctx.allocator.create(Type) catch return i32t;
        const ok = e.kind.error_union_type.ok;
        p.* = if (ctx.tree.expr(ok).kind == .error_unwrap) typeExpr(ctx, ctx.tree.expr(ok).kind.error_unwrap) else typeExpr(ctx, ok);
        return .{ .error_union = p };
    }
    if (e.kind == .unary and e.kind.unary.op == .address_of) return ptrType(ctx, e.kind.unary.operand);
    if (e.kind == .identifier) {
        const n = e.kind.identifier.name;
        if (n.len >= 2 and (n[0] == 'i' or n[0] == 'u')) if (std.fmt.parseInt(u16, n[1..], 10)) |w| return .{ .int = .{ .bits = w, .signed = n[0] == 'i' } } else |_| {};
        if (ctx.enums.contains(n)) return .{ .enum_ = n };
        return .{ .struct_ = n };
    }
    return i32t;
}
fn enumIndex(ctx: *Ctx, ty: Type, name: []const u8) ?i64 {
    if (ty != .enum_) return null;
    const e = ctx.enums.get(ty.enum_) orelse return null;
    for (e.variants, 0..) |v, i| if (std.mem.eql(u8, v, name)) return @intCast(i);
    return null;
}
fn lowerFunctionBody(ctx: *Ctx, f: anytype) LowerError!?[]Stmt {
    var stmts = std.ArrayList(Stmt).empty;
    if (f.body_kind == .arrow) {
        try stmts.append(ctx.allocator, .{ .ret = (try lowerExpr(ctx, f.body, null)) orelse return null });
        return try stmts.toOwnedSlice(ctx.allocator);
    }
    try lowerBlockStmts(ctx, f.body, &stmts, true);
    return try stmts.toOwnedSlice(ctx.allocator);
}
fn lowerBlockStmts(ctx: *Ctx, body: ast.ExprId, out: *std.ArrayList(Stmt), add_default_return: bool) LowerError!void {
    const e = ctx.tree.expr(body);
    if (e.kind != .block) {
        if (add_default_return) try out.append(ctx.allocator, .{ .ret = (try lowerExpr(ctx, body, null)) orelse return });
        return;
    }
    var saw = false;
    for (e.kind.block) |sid| switch (ctx.tree.stmt(sid).kind) {
        .declaration => |did| if (!saw) {
            const d = ctx.tree.decl(did);
            if (d.target == .name) {
                const ty = if (d.annotation) |a| typeExpr(ctx, a) else inferExprType(ctx, d.value);
                try ctx.vars.put(d.target.name.name, ty);
                try out.append(ctx.allocator, .{ .decl = .{ .name = d.target.name.name, .ty = ty, .value = (try lowerExpr(ctx, d.value, ty)) orelse return } });
            }
        },
        .assignment => |a| if (!saw and ctx.tree.expr(a.lhs).kind == .identifier) {
            const n = ctx.tree.expr(a.lhs).kind.identifier.name;
            try out.append(ctx.allocator, .{ .assign = .{ .name = n, .value = (try lowerExpr(ctx, a.rhs, ctx.vars.get(n))) orelse return } });
        },
        .for_stmt => |fid| if (!saw) if (try lowerWhile(ctx, fid)) |w| try out.append(ctx.allocator, w),
        .expr => |x| if (!saw) {
            if (try lowerWhile(ctx, x)) |w| try out.append(ctx.allocator, w) else try out.append(ctx.allocator, .{ .ret = (try lowerExpr(ctx, x, null)) orelse return });
        },
        .return_ => |m| if (!saw) {
            try out.append(ctx.allocator, .{ .ret = if (m) |rid| (try lowerExpr(ctx, rid, null)) orelse return else .{ .int = 0 } });
            saw = true;
        },
        else => {},
    };
    if (!saw and add_default_return) try out.append(ctx.allocator, .{ .ret = .{ .int = 0 } });
}
fn inferExprType(ctx: *Ctx, id: ast.ExprId) Type {
    const e = ctx.tree.expr(id);
    return switch (e.kind) {
        .typed_struct_literal => |ts| typeExpr(ctx, ts.ty),
        .literal => |lit| switch (lit) {
            .string => blk: {
                const p = ctx.allocator.create(Type) catch break :blk i32t;
                p.* = .{ .int = .{ .bits = 8, .signed = false } };
                break :blk .{ .slice = p };
            },
            else => i32t,
        },
        .array_literal => |items| blk: {
            const p = ctx.allocator.create(Type) catch break :blk i32t;
            p.* = i32t;
            break :blk .{ .array = .{ .len = items.len, .elem = p } };
        },
        else => i32t,
    };
}
fn lowerWhile(ctx: *Ctx, id: ast.ExprId) LowerError!?Stmt {
    const e = ctx.tree.expr(id);
    if (e.kind != .for_expr or e.kind.for_expr.head == null) return null;
    if (e.kind.for_expr.head.? == .while_) {
        var body = std.ArrayList(Stmt).empty;
        try lowerBlockStmts(ctx, e.kind.for_expr.body, &body, false);
        return .{ .while_ = .{ .cond = (try lowerExpr(ctx, e.kind.for_expr.head.?.while_.condition, null)) orelse return null, .body = try body.toOwnedSlice(ctx.allocator) } };
    }
    if (e.kind.for_expr.head.? == .iteration and e.kind.for_expr.head.?.iteration.iterables.len == 1 and e.kind.for_expr.head.?.iteration.captures.bindings.len > 0) {
        const it = e.kind.for_expr.head.?.iteration.iterables[0];
        const ie = ctx.tree.expr(it);
        if (ie.kind == .binary and (ie.kind.binary.op == .range_exclusive or ie.kind.binary.op == .range_inclusive)) {
            var body = std.ArrayList(Stmt).empty;
            const nm = e.kind.for_expr.head.?.iteration.captures.bindings[0].name;
            try ctx.vars.put(nm, i32t);
            try lowerBlockStmts(ctx, e.kind.for_expr.body, &body, false);
            _ = ctx.vars.remove(nm);
            return .{ .for_range = .{ .name = nm, .start = (try lowerExpr(ctx, ie.kind.binary.lhs, null)) orelse return null, .end = (try lowerExpr(ctx, ie.kind.binary.rhs, null)) orelse return null, .inclusive = ie.kind.binary.op == .range_inclusive, .body = try body.toOwnedSlice(ctx.allocator) } };
        }
        if (ie.kind == .identifier) {
            const nm = e.kind.for_expr.head.?.iteration.captures.bindings[0].name;
            const ity = ctx.vars.get(ie.kind.identifier.name) orelse i32t;
            const elem = if (ity == .array) ity.array.elem.* else if (ity == .slice) ity.slice.* else i32t;
            var body = std.ArrayList(Stmt).empty;
            try ctx.vars.put(nm, elem);
            try lowerBlockStmts(ctx, e.kind.for_expr.body, &body, false);
            _ = ctx.vars.remove(nm);
            return .{ .for_indexed = .{ .name = nm, .iterable = ie.kind.identifier.name, .body = try body.toOwnedSlice(ctx.allocator) } };
        }
    }
    return null;
}
fn boxed(ctx: *Ctx, value: Expr) !*Expr {
    const p = try ctx.allocator.create(Expr);
    p.* = value;
    return p;
}
fn lowerExpr(ctx: *Ctx, id: ast.ExprId, expected: ?Type) LowerError!?Expr {
    const e = ctx.tree.expr(id);
    switch (e.kind) {
        .literal => |lit| switch (lit) {
            .string => |s| return .{ .string = s },
            .integer => |txt| {
                const v = Expr{ .int = try std.fmt.parseInt(i64, txt, 0) };
                if (expected) |ty| {
                    if (ty == .optional) return .{ .optional_some = try boxed(ctx, v) };
                    if (ty == .error_union) return .{ .error_some = try boxed(ctx, v) };
                }
                return v;
            },
            .true => return .{ .int = 1 },
            .false => return .{ .int = 0 },
            .null => {
                if (expected) |ty| if (ty == .optional) return .optional_null;
                return .{ .int = 0 };
            },
            else => {},
        },
        .identifier => |n| return .{ .var_ = n.name },
        .array_literal => |items| {
            var vals = std.ArrayList(Expr).empty;
            for (items) |it| try vals.append(ctx.allocator, (try lowerExpr(ctx, it, null)) orelse return null);
            return .{ .array_lit = try vals.toOwnedSlice(ctx.allocator) };
        },
        .index => |ix| if (ctx.tree.expr(ix.object).kind == .identifier) {
            const on = ctx.tree.expr(ix.object).kind.identifier.name;
            const ie = ctx.tree.expr(ix.index);
            if (ie.kind == .binary and (ie.kind.binary.op == .range_exclusive or ie.kind.binary.op == .range_inclusive)) return .{ .slice_from_array = .{ .object = on, .start = try boxed(ctx, (try lowerExpr(ctx, ie.kind.binary.lhs, null)) orelse return null), .end = try boxed(ctx, (try lowerExpr(ctx, ie.kind.binary.rhs, null)) orelse return null) } };
            return .{ .index = .{ .object = on, .index = try boxed(ctx, (try lowerExpr(ctx, ix.index, null)) orelse return null) } };
        },
        .optional_unwrap => |x| if (ctx.tree.expr(x).kind == .identifier) return .{ .opt_payload = ctx.tree.expr(x).kind.identifier.name },
        .error_unwrap => |x| if (ctx.tree.expr(x).kind == .identifier) return .{ .err_payload = ctx.tree.expr(x).kind.identifier.name },
        .or_fallback => |o| if (ctx.tree.expr(o.lhs).kind == .identifier) {
            const n = ctx.tree.expr(o.lhs).kind.identifier.name;
            if (ctx.vars.get(n)) |ty| if (ty == .optional) return .{ .optional_or = .{ .name = n, .fallback = try boxed(ctx, (try lowerExpr(ctx, o.rhs, ty.optional.*)) orelse return null) } };
            return .{ .err_payload = n };
        },
        .member => |m| if (ctx.tree.expr(m.object).kind == .identifier) {
            const on = ctx.tree.expr(m.object).kind.identifier.name;
            if (std.mem.eql(u8, on, ".")) {
                if (expected) |ty| if (enumIndex(ctx, ty, m.name.name)) |idx| return .{ .int = idx };
            }
            return .{ .field = .{ .object = on, .name = m.name.name } };
        },
        .typed_struct_literal => |ts| {
            var vals = std.ArrayList(FieldValue).empty;
            const tn = ctx.tree.expr(ts.ty).kind.identifier.name;
            for (ts.fields) |f| if (f.value) |v| try vals.append(ctx.allocator, .{ .name = f.name.name, .value = (try lowerExpr(ctx, v, null)) orelse return null });
            return .{ .struct_lit = .{ .ty = tn, .fields = try vals.toOwnedSlice(ctx.allocator) } };
        },
        .call => |c| {
            if (ctx.tree.expr(c.callee).kind == .member) {
                const m = ctx.tree.expr(c.callee).kind.member;
                if (ctx.tree.expr(m.object).kind == .identifier) {
                    const recv = ctx.tree.expr(m.object).kind.identifier.name;
                    const ty = ctx.vars.get(recv) orelse i32t;
                    if (ty == .struct_) {
                        var args = std.ArrayList(Expr).empty;
                        for (c.args) |a| try args.append(ctx.allocator, (try lowerExpr(ctx, a.value, null)) orelse return null);
                        return .{ .method_call = .{ .receiver = recv, .type_name = ty.struct_, .method = m.name.name, .args = try args.toOwnedSlice(ctx.allocator) } };
                    }
                }
            }
            if (ctx.tree.expr(c.callee).kind == .identifier) {
                var args = std.ArrayList(Expr).empty;
                for (c.args) |a| try args.append(ctx.allocator, (try lowerExpr(ctx, a.value, null)) orelse return null);
                return .{ .call = .{ .name = ctx.tree.expr(c.callee).kind.identifier.name, .args = try args.toOwnedSlice(ctx.allocator) } };
            }
        },
        .unary => |u| if (u.op == .neg) return .{ .neg = try boxed(ctx, (try lowerExpr(ctx, u.operand, null)) orelse return null) },
        .if_expr => |i| if (i.else_branch) |el| return .{ .if_ = .{ .cond = try boxed(ctx, (try lowerExpr(ctx, i.condition, null)) orelse return null), .then_expr = try boxed(ctx, (try lowerExpr(ctx, i.then_branch, expected)) orelse return null), .else_expr = try boxed(ctx, (try lowerExpr(ctx, el, expected)) orelse return null) } },
        .binary => |b| {
            const lhs_ty = if (ctx.tree.expr(b.lhs).kind == .identifier) ctx.vars.get(ctx.tree.expr(b.lhs).kind.identifier.name) else null;
            const lhs = try boxed(ctx, (try lowerExpr(ctx, b.lhs, null)) orelse return null);
            const rhs = try boxed(ctx, (try lowerExpr(ctx, b.rhs, lhs_ty)) orelse return null);
            return switch (b.op) {
                .add => .{ .add = .{ .lhs = lhs, .rhs = rhs } },
                .sub => .{ .sub = .{ .lhs = lhs, .rhs = rhs } },
                .mul => .{ .mul = .{ .lhs = lhs, .rhs = rhs } },
                .div => .{ .div = .{ .lhs = lhs, .rhs = rhs } },
                .rem => .{ .rem = .{ .lhs = lhs, .rhs = rhs } },
                .eq => .{ .eq = .{ .lhs = lhs, .rhs = rhs } },
                .ne => .{ .ne = .{ .lhs = lhs, .rhs = rhs } },
                .lt => .{ .lt = .{ .lhs = lhs, .rhs = rhs } },
                .le => .{ .le = .{ .lhs = lhs, .rhs = rhs } },
                .gt => .{ .gt = .{ .lhs = lhs, .rhs = rhs } },
                .ge => .{ .ge = .{ .lhs = lhs, .rhs = rhs } },
                else => null,
            };
        },
        .grouped => |g| return lowerExpr(ctx, g, expected),
        else => {},
    }
    try ctx.bag.errorAt("C0004", "codegen currently supports scalar subset plus simple structs/methods/enums", e.span, "unsupported expression");
    return null;
}
