const std = @import("std");
const ast = @import("ast.zig");
const diag = @import("diag.zig");
const parser = @import("parser.zig");
const types = @import("types.zig");
const source = @import("source.zig");
const comptime_eval = @import("comptime.zig");

const Var = struct { ty: types.TypeId, mutable: bool = false, source_mutable: bool = false };
const GenericFnSpec = struct { ret: types.TypeId, params: []const types.Param, name: []const u8 };
pub const Checker = struct {
    allocator: std.mem.Allocator,
    diagnostics: *diag.DiagnosticBag,
    tt: types.TypeTable,
    vars: std.StringHashMap(Var),
    type_values: std.StringHashMap(types.TypeId),
    methods: std.StringHashMap(types.TypeId),
    enum_variants: std.StringHashMap(types.TypeId),
    generic_cache: std.StringHashMap(types.TypeId),
    generic_fn_cache: std.StringHashMap(GenericFnSpec),
    current_return: ?types.TypeId = null,
    inferred_error: bool = false,
    error_defers: std.ArrayList(ast.StmtId),

    pub fn init(allocator: std.mem.Allocator, diagnostics: *diag.DiagnosticBag) !Checker {
        return .{ .allocator = allocator, .diagnostics = diagnostics, .tt = try types.TypeTable.init(allocator), .vars = .init(allocator), .type_values = .init(allocator), .methods = .init(allocator), .enum_variants = .init(allocator), .generic_cache = .init(allocator), .generic_fn_cache = .init(allocator), .error_defers = .empty };
    }
    pub fn deinit(self: *Checker) void {
        self.tt.deinit();
        self.vars.deinit();
        self.type_values.deinit();
        self.methods.deinit();
        self.enum_variants.deinit();
        self.generic_cache.deinit();
        self.generic_fn_cache.deinit();
        self.error_defers.deinit(self.allocator);
    }

    pub fn checkFile(self: *Checker, tree: *const ast.Ast, file: ast.File) !void {
        for (file.items) |iid| {
            const item = tree.topLevelItem(iid);
            if (item.kind == .declaration) try self.checkDecl(tree, item.kind.declaration);
        }
    }

    fn checkDecl(self: *Checker, tree: *const ast.Ast, did: ast.DeclId) !void {
        const d = tree.decl(did);
        const ann_ty_opt: ?types.TypeId = if (d.annotation) |ann| try self.evalType(tree, ann) else null;
        var ty = if (ann_ty_opt) |t| blk: {
            if (t == self.tt.builtins.type and tree.expr(d.value).kind == .function) {
                const f = tree.expr(d.value).kind.function;
                if (f.return_type) |rt| _ = try self.evalType(tree, rt);
                break :blk try self.synthFunction(tree, f);
            }
            if (tree.expr(d.value).kind == .enum_type or tree.expr(d.value).kind == .struct_type) break :blk try self.evalType(tree, d.value);
            try self.check(tree, d.value, t);
            break :blk t;
        } else try self.synth(tree, d.value);
        if (ty == self.tt.builtins.type) {
            var ev = comptime_eval.Evaluator.init(self.allocator, self.diagnostics, &self.tt, .{});
            try self.populateEvaluatorFunctions(tree, &ev);
            const cv = try ev.eval(tree, d.value);
            if (cv == .type) ty = cv.type;
        }
        switch (d.target) {
            .name => |n| {
                try self.vars.put(n.name, .{ .ty = ty, .mutable = d.mutability == .mutable, .source_mutable = d.mutability == .mutable or self.sourceMutable(tree, d.value) });
                if (tree.expr(d.value).kind == .enum_type) ty = try self.evalType(tree, d.value);
                if (tree.expr(d.value).kind == .struct_type) ty = try self.evalType(tree, d.value);
                if (tree.expr(d.value).kind == .struct_type or tree.expr(d.value).kind == .enum_type or tree.expr(d.value).kind == .call) try self.type_values.put(n.name, ty);
                if (tree.expr(d.value).kind == .enum_type) {
                    for (self.tt.get(ty).enum_type) |v| try self.enum_variants.put(v.name, ty);
                }
            },
            .associated => |a| {
                const fty = try self.synth(tree, d.value);
                const key = try std.fmt.allocPrint(self.allocator, "{s}.{s}", .{ a.type_path.parts[0].name, a.name.name });
                try self.methods.put(key, fty);
                try self.vars.put(key, .{ .ty = fty });
            },
            else => {},
        }
    }

    fn check(self: *Checker, tree: *const ast.Ast, id: ast.ExprId, expected: types.TypeId) anyerror!void {
        const e = tree.expr(id);
        switch (e.kind) {
            .struct_type, .enum_type => if (expected != self.tt.builtins.type) try self.typeMismatch(e.span),
            .literal => |lit| switch (lit) {
                .null => switch (self.tt.get(expected)) {
                    .optional => {},
                    .error_union => {},
                    else => try self.typeMismatch(e.span),
                },
                .integer => |txt| {
                    const int_expected = if (self.tt.get(expected) == .error_union) self.tt.get(expected).error_union.ok else expected;
                    if (!self.intLiteralFits(txt, int_expected, false)) try self.diagnostics.errorAt("T0004", "integer literal is out of range for target type", e.span, "literal does not fit target integer type");
                },
                .true, .false => if (expected != self.tt.builtins.u1) try self.typeMismatch(e.span),
                .float => if (self.tt.get(expected) != .float and expected != self.tt.builtins.comptime_float) try self.typeMismatch(e.span),
                else => {},
            },
            .unary => |u| if (u.op == .neg and tree.expr(u.operand).kind == .literal and tree.expr(u.operand).kind.literal == .integer) {
                if (!self.intLiteralFits(tree.expr(u.operand).kind.literal.integer, expected, true)) try self.diagnostics.errorAt("T0004", "integer literal is out of range for target type", e.span, "literal does not fit target integer type");
            } else try self.expectAssignable(try self.synth(tree, id), expected, e.span),
            .array_literal => |items| if (self.tt.get(expected) == .array) {
                const at = self.tt.get(expected).array;
                if (items.len != at.len) try self.diagnostics.errorAt("T0011", "array length mismatch", e.span, "wrong number of elements");
                for (items) |it| try self.check(tree, it, at.elem);
            } else try self.expectAssignable(try self.synth(tree, id), expected, e.span),
            .function => |f| {
                const fty = try self.synthFunction(tree, f);
                if (expected != self.tt.builtins.type) try self.expectAssignable(fty, expected, e.span);
            },
            .anon_struct_literal => |fields| try self.checkStructLiteral(tree, e.span, expected, fields),
            .typed_struct_literal => |ts| {
                const ty = try self.evalType(tree, ts.ty);
                try self.expectAssignable(ty, expected, e.span);
                try self.checkStructLiteral(tree, e.span, ty, ts.fields);
            },
            .member => |m| if (tree.expr(m.object).kind == .identifier and (std.mem.eql(u8, tree.expr(m.object).kind.identifier.name, ".") or self.type_values.contains(tree.expr(m.object).kind.identifier.name))) if (expected != self.tt.builtins.u1) try self.checkEnumVariant(tree, e.span, expected, m.name, null) else try self.expectAssignable(try self.synth(tree, id), expected, e.span),
            .call => |c| if (tree.expr(c.callee).kind == .member) blk: {
                const mm = tree.expr(c.callee).kind.member;
                if (tree.expr(mm.object).kind == .identifier and std.mem.eql(u8, tree.expr(mm.object).kind.identifier.name, ".")) {
                    try self.checkEnumVariant(tree, e.span, expected, mm.name, if (c.args.len > 0) c.args[0].value else null);
                    break :blk;
                }
                try self.expectAssignable(try self.synth(tree, id), expected, e.span);
            } else try self.expectAssignable(try self.synth(tree, id), expected, e.span),
            else => try self.expectAssignable(try self.synth(tree, id), expected, e.span),
        }
    }

    fn synth(self: *Checker, tree: *const ast.Ast, id: ast.ExprId) anyerror!types.TypeId {
        const e = tree.expr(id);
        return switch (e.kind) {
            .err => self.tt.builtins.err,
            .literal => |lit| switch (lit) {
                .null => blk: {
                    try self.diagnostics.errorAt("T0023", "null requires optional context", e.span, "null has no type here");
                    break :blk self.tt.builtins.err;
                },
                .integer => self.tt.builtins.comptime_int,
                .float => self.tt.builtins.comptime_float,
                .true, .false => self.tt.builtins.u1,
                .string => try self.tt.slice(self.tt.builtins.u8),
                .char => self.tt.builtins.u8,
            },
            .identifier => |n| if (self.type_values.contains(n.name)) self.tt.builtins.type else if (self.vars.get(n.name)) |v| v.ty else blk: {
                try self.diagnostics.errorAt("T0001", "unknown value", n.span, "not declared");
                break :blk self.tt.builtins.err;
            },
            .grouped => |x| try self.synth(tree, x),
            .optional_unwrap => |x| try self.unwrapOptional(tree, e.span, x),
            .error_unwrap => |x| try self.unwrapError(tree, e.span, x),
            .unary => |u| switch (u.op) {
                .not => blk: {
                    try self.check(tree, u.operand, self.tt.builtins.u1);
                    break :blk self.tt.builtins.u1;
                },
                .neg => try self.synth(tree, u.operand),
                .address_of => try self.tt.pointer(try self.synth(tree, u.operand)),
                else => try self.synth(tree, u.operand),
            },
            .binary => |b| try self.synthBinary(tree, e.span, b),
            .struct_type, .enum_type => try self.evalType(tree, id),
            .function => |f| try self.synthFunction(tree, f),
            .call => |c| try self.synthCall(tree, e.span, c),
            .if_expr => |i| blk: {
                try self.checkConditionCaptures(tree, i.condition, i.captures);
                try self.checkCondition(tree, i.condition);
                var saved = std.StringHashMap(Var).init(self.allocator);
                defer saved.deinit();
                try self.bindConditionCaptures(tree, i.condition, i.captures, true, &saved);
                const t = try self.synth(tree, i.then_branch);
                try self.restoreCaptures(i.captures, &saved);
                if (i.else_branch) |el| try self.check(tree, el, t);
                break :blk t;
            },
            .block => |stmts| blk: {
                try self.checkBlock(tree, stmts, self.tt.builtins.void);
                break :blk self.tt.builtins.void;
            },
            .array_literal => |items| blk: {
                const elem = if (items.len == 0) self.tt.builtins.err else try self.synth(tree, items[0]);
                for (items[1..]) |it| try self.check(tree, it, elem);
                break :blk try self.tt.array(items.len, elem);
            },
            .for_expr => |f| blk: {
                try self.checkFor(tree, f);
                break :blk self.tt.builtins.void;
            },
            .member => |m| if (tree.expr(m.object).kind == .identifier and std.mem.eql(u8, tree.expr(m.object).kind.identifier.name, ".")) blk: {
                if (self.enum_variants.get(m.name.name)) |ety| break :blk ety;
                break :blk try self.synthMember(tree, id, m);
            } else try self.synthMember(tree, id, m),
            .or_fallback => |o| try self.checkOrFallback(tree, e.span, o),
            .anon_struct_literal => blk: {
                try self.diagnostics.errorAt("T0012", "anonymous struct literal needs expected type", e.span, "no expected struct type");
                break :blk self.tt.builtins.err;
            },
            .typed_struct_literal => |ts| blk: {
                const ty = try self.evalType(tree, ts.ty);
                try self.checkStructLiteral(tree, e.span, ty, ts.fields);
                break :blk ty;
            },
            .match_expr => |ma| try self.synthMatch(tree, ma),
            .index => |x| blk: {
                const obj_ty = try self.synth(tree, x.object);
                const obj = self.tt.get(obj_ty);
                const ix = tree.expr(x.index);
                if (ix.kind == .binary and (ix.kind.binary.op == .range_exclusive or ix.kind.binary.op == .range_inclusive)) {
                    break :blk switch (obj) {
                        .array => |a| try self.tt.slice(a.elem),
                        .slice => obj_ty,
                        else => self.tt.builtins.err,
                    };
                }
                _ = try self.synth(tree, x.index);
                break :blk switch (obj) {
                    .array => |a| a.elem,
                    .slice => |s| s,
                    else => self.tt.builtins.err,
                };
            },
            else => self.tt.builtins.err,
        };
    }

    fn checkOrFallback(self: *Checker, tree: *const ast.Ast, span: anytype, o: anytype) !types.TypeId {
        const lt = try self.synth(tree, o.lhs);
        const ltt = self.tt.get(lt);
        if (ltt == .optional) {
            const inner = ltt.optional;
            if (o.capture) |c| try self.vars.put(c.name, .{ .ty = inner, .mutable = false });
            try self.checkOrRhs(tree, o.rhs, inner);
            return inner;
        }
        if (ltt == .error_union) {
            const inner = ltt.error_union.ok;
            if (o.capture) |c| try self.vars.put(c.name, .{ .ty = ltt.error_union.err, .mutable = false });
            try self.checkOrRhs(tree, o.rhs, inner);
            return inner;
        }
        try self.diagnostics.errorAt("T0024", "`or` requires optional or error union", span, "invalid left side");
        return self.tt.builtins.err;
    }
    fn checkOrRhs(self: *Checker, tree: *const ast.Ast, rhs: ast.ExprId, expected: types.TypeId) !void {
        const e = tree.expr(rhs);
        if (e.kind == .block) {
            for (e.kind.block) |sid| switch (tree.stmt(sid).kind) {
                .return_, .break_, .continue_ => return,
                else => {},
            };
        }
        try self.check(tree, rhs, expected);
    }
    fn synthBinary(self: *Checker, tree: *const ast.Ast, span: anytype, b: anytype) anyerror!types.TypeId {
        switch (b.op) {
            .logical_and, .logical_or => {
                try self.checkCondition(tree, b.lhs);
                try self.checkCondition(tree, b.rhs);
                return self.tt.builtins.u1;
            },
            .eq, .ne, .lt, .le, .gt, .ge => {
                const lt = try self.synth(tree, b.lhs);
                if (self.tt.get(lt) == .enum_type) return self.tt.builtins.u1;
                if (try self.isEnumTagCheck(tree, b.lhs, b.rhs, lt)) return self.tt.builtins.u1;
                try self.check(tree, b.rhs, lt);
                return self.tt.builtins.u1;
            },
            .or_else => {
                const lt = try self.synth(tree, b.lhs);
                const ltt = self.tt.get(lt);
                if (ltt == .optional) {
                    try self.check(tree, b.rhs, ltt.optional);
                    return ltt.optional;
                }
                if (ltt == .error_union) {
                    try self.check(tree, b.rhs, ltt.error_union.ok);
                    return ltt.error_union.ok;
                }
                try self.diagnostics.errorAt("T0024", "`or` requires optional or error union", span, "invalid left side");
                return self.tt.builtins.err;
            },
            .range_exclusive, .range_inclusive => {
                const lt = try self.synth(tree, b.lhs);
                try self.check(tree, b.rhs, lt);
                return self.tt.range(lt);
            },
            else => {
                const lt = try self.synth(tree, b.lhs);
                try self.check(tree, b.rhs, lt);
                return lt;
            },
        }
    }

    fn synthFunction(self: *Checker, tree: *const ast.Ast, f: anytype) anyerror!types.TypeId {
        var has_comp = false;
        for (f.params) |p0| {
            if (p0.is_comptime) has_comp = true;
        }
        if (has_comp) return self.tt.function(&.{}, self.tt.builtins.err);
        var params = std.ArrayList(types.Param).empty;
        var saved = std.StringHashMap(Var).init(self.allocator);
        defer saved.deinit();
        for (f.params) |p| {
            const base = switch (p.ty) {
                .ordinary => |te| try self.evalType(tree, te),
                .mut_pointer => |te| try self.tt.pointer(try self.evalType(tree, te)),
                .mut_slice => |te| try self.tt.slice(try self.evalType(tree, te)),
            };
            const mut: @TypeOf(@as(types.Param, undefined).mutating) = switch (p.ty) {
                .ordinary => .none,
                .mut_pointer => .pointer,
                .mut_slice => .slice,
            };
            try params.append(self.allocator, .{ .ty = base, .mutating = mut, .is_comptime = p.is_comptime });
            if (p.name) |n| {
                if (self.vars.get(n.name)) |old| try saved.put(n.name, old);
                try self.vars.put(n.name, .{ .ty = base });
            }
        }
        defer {
            for (f.params) |p| if (p.name) |n| {
                if (saved.get(n.name)) |old| {
                    self.vars.put(n.name, old) catch {};
                } else {
                    _ = self.vars.remove(n.name);
                }
            };
            params.deinit(self.allocator);
        }
        var ret = if (f.return_type) |rt| try self.evalType(tree, rt) else self.tt.builtins.void;
        const saved_ret = self.current_return;
        const saved_inf = self.inferred_error;
        self.current_return = ret;
        self.inferred_error = false;
        if (f.body_kind == .arrow) try self.check(tree, f.body, ret) else try self.checkBlockExpr(tree, f.body, ret);
        if (self.inferred_error and self.tt.get(ret) != .error_union) ret = try self.tt.errorUnion(ret, self.tt.builtins.err);
        self.current_return = saved_ret;
        self.inferred_error = saved_inf;
        return self.tt.function(params.items, ret);
    }

    fn synthCall(self: *Checker, tree: *const ast.Ast, span: anytype, c: anytype) anyerror!types.TypeId {
        if (tree.expr(c.callee).kind == .member) return try self.synthMethodOrEnumCall(tree, span, c);
        if (try self.tryGenericFunctionCall(tree, c)) |gf| return gf;
        if (try self.tryGenericTypeCall(tree, c)) |gt| return gt;
        if (tree.expr(c.callee).kind == .builtin_identifier and std.mem.eql(u8, tree.expr(c.callee).kind.builtin_identifier.name, "$as")) {
            if (c.args.len != 2) {
                try self.diagnostics.errorAt("T0005", "argument count mismatch", span, "expected 2 arguments");
                return self.tt.builtins.err;
            }
            const target = try self.evalType(tree, c.args[0].value);
            _ = try self.synth(tree, c.args[1].value);
            return target;
        }
        const callee = self.tt.get(try self.synth(tree, c.callee));
        if (callee != .function) return self.tt.builtins.err;
        if (callee.function.params.len != c.args.len) try self.diagnostics.errorAt("T0005", "argument count mismatch", span, "wrong number of arguments");
        const n = @min(callee.function.params.len, c.args.len);
        for (callee.function.params[0..n], c.args[0..n]) |p, a| {
            try self.check(tree, a.value, p.ty);
            if (p.mutating != .none and !self.sourceMutable(tree, a.value)) try self.diagnostics.errorAt("T0010", "argument requires mutable source", tree.expr(a.value).span, "source is not mutable");
        }
        return callee.function.ret;
    }

    fn checkBlockExpr(self: *Checker, tree: *const ast.Ast, body: ast.ExprId, ret: types.TypeId) anyerror!void {
        if (tree.expr(body).kind == .block) try self.checkBlock(tree, tree.expr(body).kind.block, ret) else try self.check(tree, body, ret);
    }
    fn checkBlock(self: *Checker, tree: *const ast.Ast, stmts: []ast.StmtId, ret: types.TypeId) anyerror!void {
        for (stmts) |sid| switch (tree.stmt(sid).kind) {
            .declaration => |d| try self.checkDecl(tree, d),
            .return_ => |v| if (v) |x| try self.checkReturn(tree, x, ret),
            .defer_ => |d| if (d.capture) |_| try self.error_defers.append(self.allocator, sid),
            .assignment => |a| {
                try self.checkAssignablePlace(tree, a.lhs);
                try self.check(tree, a.rhs, try self.synth(tree, a.lhs));
            },
            .expr => |x| _ = try self.synth(tree, x),
            .for_stmt, .if_stmt, .match_stmt => |x| _ = try self.synth(tree, x),
            else => {},
        };
    }

    fn checkReturn(self: *Checker, tree: *const ast.Ast, id: ast.ExprId, ret: types.TypeId) !void {
        const got = try self.synth(tree, id);
        if (self.tt.get(ret) == .error_union) {
            const eu = self.tt.get(ret).error_union;
            if (got == eu.ok) return;
            if (self.tt.get(got) == .enum_type or self.tt.get(got) == .error_union) {
                self.inferred_error = true;
                return;
            }
            try self.expectAssignable(got, eu.ok, tree.expr(id).span);
        } else try self.expectAssignable(got, ret, tree.expr(id).span);
    }
    fn runErrorDefers(self: *Checker, tree: *const ast.Ast, err_ty: types.TypeId) !void {
        for (self.error_defers.items) |sid| {
            const d = tree.stmt(sid).kind.defer_;
            if (d.capture) |c| try self.vars.put(c.name, .{ .ty = err_ty });
            _ = try self.synth(tree, d.body);
            if (d.capture) |c| _ = self.vars.remove(c.name);
        }
    }
    fn checkAssignablePlace(self: *Checker, tree: *const ast.Ast, id: ast.ExprId) !void {
        if (tree.expr(id).kind == .identifier) {
            const n = tree.expr(id).kind.identifier;
            if (self.vars.get(n.name)) |v| if (!v.mutable) try self.diagnostics.errorAt("T0006", "cannot assign to immutable binding", n.span, "binding is not mutable");
        }
    }

    fn expectAssignable(self: *Checker, got: types.TypeId, expected: types.TypeId, span: anytype) !void {
        if (self.tt.get(got) == .enum_type and expected == self.tt.builtins.u1) return;
        if (got == expected) return;
        if (self.tt.get(expected) == .error_union and got == self.tt.get(expected).error_union.ok) return;
        if (self.tt.get(got) == .error_union and self.tt.get(got).error_union.ok == expected) return;
        if (got == self.tt.builtins.type and self.tt.get(expected) != .type) return;
        if (got == self.tt.builtins.comptime_int and self.tt.get(expected) == .int) return;
        if (got == self.tt.builtins.comptime_float and self.tt.get(expected) == .float) return;
        if (types.canWiden(&self.tt, got, expected)) return;
        try self.typeMismatch(span);
    }
    fn typeMismatch(self: *Checker, span: anytype) !void {
        try self.diagnostics.errorAt("T0002", "type mismatch", span, "expression has incompatible type");
    }

    fn unwrapOptional(self: *Checker, tree: *const ast.Ast, span: anytype, id: ast.ExprId) !types.TypeId {
        const ty = try self.synth(tree, id);
        const t = self.tt.get(ty);
        if (t == .error_union and self.tt.get(t.error_union.ok) == .optional) return self.tt.get(t.error_union.ok).optional;
        if (t != .optional) {
            try self.diagnostics.errorAt("T0025", "`.?` requires optional", span, "not optional");
            return self.tt.builtins.err;
        }
        return t.optional;
    }
    fn unwrapError(self: *Checker, tree: *const ast.Ast, span: anytype, id: ast.ExprId) !types.TypeId {
        const ty = try self.synth(tree, id);
        const t = self.tt.get(ty);
        if (t != .error_union) {
            try self.diagnostics.errorAt("T0026", "`.!` requires error union", span, "not error union");
            return self.tt.builtins.err;
        }
        if (self.current_return) |ret| {
            if (self.tt.get(ret) != .error_union) try self.diagnostics.errorAt("T0028", "`.!` used in non-error-returning function", span, "function cannot propagate this error") else try self.runErrorDefers(tree, t.error_union.err);
        } else try self.diagnostics.errorAt("T0028", "`.!` used outside error-returning context", span, "no error propagation context");
        self.inferred_error = true;
        return t.error_union.ok;
    }
    fn evalType(self: *Checker, tree: *const ast.Ast, id: ast.ExprId) anyerror!types.TypeId {
        const e = tree.expr(id);
        if (e.kind == .unary and e.kind.unary.op == .not) return try self.tt.optional(try self.evalType(tree, e.kind.unary.operand));
        if (e.kind == .unary and e.kind.unary.op == .address_of) return try self.tt.pointer(try self.evalType(tree, e.kind.unary.operand));
        if (e.kind == .error_unwrap) return try self.tt.errorUnion(try self.evalType(tree, e.kind.error_unwrap), self.tt.builtins.err);
        if (e.kind == .error_union_type) {
            const eu = e.kind.error_union_type;
            var members = std.ArrayList(types.TypeId).empty;
            defer members.deinit(self.allocator);
            for (eu.errors) |er| try members.append(self.allocator, try self.evalType(tree, er));
            const err_ty = if (members.items.len == 0) self.tt.builtins.err else try self.tt.errorSet(members.items);
            return try self.tt.errorUnion(try self.evalType(tree, eu.ok), err_ty);
        }
        if (e.kind == .identifier) {
            if (self.type_values.get(e.kind.identifier.name)) |t| return t;
            return self.namedType(e.kind.identifier);
        }
        if (e.kind == .enum_type) {
            var vs = std.ArrayList(types.EnumVariant).empty;
            defer vs.deinit(self.allocator);
            for (e.kind.enum_type.variants) |v| try vs.append(self.allocator, .{ .name = v.name.name, .payload = if (v.payload) |p| try self.evalType(tree, p) else null });
            return self.tt.enumType(vs.items);
        }
        if (e.kind == .struct_type) {
            var fs = std.ArrayList(types.Field).empty;
            defer fs.deinit(self.allocator);
            for (e.kind.struct_type) |f| try fs.append(self.allocator, .{ .name = f.name.name, .ty = try self.evalType(tree, f.ty) });
            return self.tt.structType(fs.items);
        }
        var ev = comptime_eval.Evaluator.init(self.allocator, self.diagnostics, &self.tt, .{});
        try self.populateEvaluatorFunctions(tree, &ev);
        const t = if (e.kind == .block) self.tt.builtins.err else try ev.evalToType(tree, id);
        if (t != self.tt.builtins.err) return t;
        return switch (e.kind) {
            .function => |f| try self.synthFunction(tree, f),
            .call => |c| (try self.tryGenericTypeCall(tree, c)) orelse self.tt.builtins.err,
            else => self.tt.builtins.err,
        };
    }
    fn namedType(self: *Checker, n: ast.Ident) !types.TypeId {
        if (std.mem.eql(u8, n.name, "type")) return self.tt.builtins.type;
        if (std.mem.eql(u8, n.name, "void")) return self.tt.builtins.void;
        if (std.mem.eql(u8, n.name, "f32")) return self.tt.builtins.f32;
        if (std.mem.eql(u8, n.name, "f64")) return self.tt.builtins.f64;
        if (std.mem.eql(u8, n.name, "usize")) return self.tt.intern(.usize);
        if (std.mem.eql(u8, n.name, "isize")) return self.tt.intern(.isize);
        if (n.name.len >= 2 and (n.name[0] == 'i' or n.name[0] == 'u')) {
            const w = try std.fmt.parseInt(u16, n.name[1..], 10);
            return self.tt.int(if (n.name[0] == 'i') .signed else .unsigned, w);
        }
        try self.diagnostics.errorAt("T0003", "unknown type", n.span, "type not found");
        return self.tt.builtins.err;
    }

    fn tryGenericTypeCall(self: *Checker, tree: *const ast.Ast, c: anytype) !?types.TypeId {
        if (tree.expr(c.callee).kind != .identifier) return null;
        const name = tree.expr(c.callee).kind.identifier.name;
        if (self.vars.get(name)) |v| if (self.tt.get(v.ty) == .function) {
            var key = std.ArrayList(u8).empty;
            defer key.deinit(self.allocator);
            try key.appendSlice(self.allocator, name);
            var ev = comptime_eval.Evaluator.init(self.allocator, self.diagnostics, &self.tt, .{});
            try self.populateEvaluatorFunctions(tree, &ev);
            const fn_expr = self.findFunctionExpr(tree, name) orelse return null;
            for (c.args) |a| {
                const tv = try ev.eval(tree, a.value);
                if (tv == .type) try key.appendSlice(self.allocator, try std.fmt.allocPrint(self.allocator, "#{}", .{@intFromEnum(tv.type)}));
            }
            const ks = try key.toOwnedSlice(self.allocator);
            if (self.generic_cache.get(ks)) |hit| return hit;
            const res = try ev.evalFunctionCallArgs(tree, tree.expr(c.callee).span, fn_expr, c.args);
            if (res == .type) {
                try self.generic_cache.put(ks, res.type);
                return res.type;
            }
        };
        return null;
    }
    fn tryGenericFunctionCall(self: *Checker, tree: *const ast.Ast, c: anytype) !?types.TypeId {
        if (tree.expr(c.callee).kind != .identifier) return null;
        const name = tree.expr(c.callee).kind.identifier.name;
        const fn_expr = self.findFunctionExpr(tree, name) orelse return null;
        const f = tree.expr(fn_expr).kind.function;
        var comp_count: usize = 0;
        for (f.params) |p| {
            if (p.is_comptime) comp_count += 1;
        }
        if (comp_count == 0) return null;
        var key = std.ArrayList(u8).empty;
        defer key.deinit(self.allocator);
        try key.appendSlice(self.allocator, name);
        var saved = std.StringHashMap(types.TypeId).init(self.allocator);
        defer saved.deinit();
        var arg_i: usize = 0;
        for (f.params) |p| if (p.is_comptime) {
            if (arg_i >= c.args.len) return self.tt.builtins.err;
            const tv = try self.evalType(tree, c.args[arg_i].value);
            if (p.name) |n| {
                if (self.type_values.get(n.name)) |old| try saved.put(n.name, old);
                try self.type_values.put(n.name, tv);
            }
            try key.appendSlice(self.allocator, try std.fmt.allocPrint(self.allocator, "#{}", .{@intFromEnum(tv)}));
            arg_i += 1;
        };
        defer {
            for (f.params) |p| if (p.is_comptime) if (p.name) |n| {
                if (saved.get(n.name)) |old| {
                    self.type_values.put(n.name, old) catch {};
                } else {
                    _ = self.type_values.remove(n.name);
                }
            };
        }
        const ks = try key.toOwnedSlice(self.allocator);
        if (self.generic_fn_cache.get(ks)) |spec| return spec.ret;
        var runtime_params = std.ArrayList(types.Param).empty;
        defer runtime_params.deinit(self.allocator);
        for (f.params[comp_count..]) |p| {
            const base = switch (p.ty) {
                .ordinary => |te| try self.evalType(tree, te),
                .mut_pointer => |te| try self.tt.pointer(try self.evalType(tree, te)),
                .mut_slice => |te| try self.tt.slice(try self.evalType(tree, te)),
            };
            try runtime_params.append(self.allocator, .{ .ty = base, .mutating = .none });
        }
        const ret = if (f.return_type) |rt| try self.evalType(tree, rt) else self.tt.builtins.void;
        for (runtime_params.items, c.args[comp_count..]) |p, a| try self.check(tree, a.value, p.ty);
        const owned_params = try self.allocator.dupe(types.Param, runtime_params.items);
        const spec_name = try std.fmt.allocPrint(self.allocator, "{s}__gen{}", .{ name, self.generic_fn_cache.count() });
        try self.generic_fn_cache.put(ks, .{ .ret = ret, .params = owned_params, .name = spec_name });
        return ret;
    }
    fn populateEvaluatorFunctions(self: *Checker, tree: *const ast.Ast, ev: *comptime_eval.Evaluator) !void {
        _ = self;
        for (tree.decls.items) |d| if (d.target == .name and tree.expr(d.value).kind == .function) try ev.functions.put(d.target.name.name, d.value);
    }
    fn findFunctionExpr(self: *Checker, tree: *const ast.Ast, name: []const u8) ?ast.ExprId {
        _ = self;
        for (tree.decls.items) |d| if (d.target == .name and std.mem.eql(u8, d.target.name.name, name)) if (tree.expr(d.value).kind == .function) return d.value;
        return null;
    }
    fn checkCondition(self: *Checker, tree: *const ast.Ast, id: ast.ExprId) !void {
        const ty = try self.synth(tree, id);
        const t = self.tt.get(ty);
        if (ty == self.tt.builtins.u1 or t == .optional) return;
        try self.check(tree, id, self.tt.builtins.u1);
    }
    const CaptureInfo = struct { ty: ?types.TypeId, span: source.Span };
    fn bindConditionCaptures(self: *Checker, tree: *const ast.Ast, cond: ast.ExprId, caps: ?ast.CaptureList, pure: bool, saved: *std.StringHashMap(Var)) !void {
        if (caps == null) return;
        var infos = std.ArrayList(CaptureInfo).empty;
        defer infos.deinit(self.allocator);
        try self.collectCaptureInfos(tree, cond, pure, &infos);
        var i: usize = 0;
        while (i < infos.items.len and i < caps.?.bindings.len) : (i += 1) {
            const b = caps.?.bindings[i];
            if (std.mem.eql(u8, b.name, "_") or infos.items[i].ty == null) continue;
            if (self.vars.get(b.name)) |old| try saved.put(b.name, old);
            try self.vars.put(b.name, .{ .ty = infos.items[i].ty.? });
        }
    }
    fn checkConditionCaptures(self: *Checker, tree: *const ast.Ast, cond: ast.ExprId, caps: ?ast.CaptureList) !void {
        if (caps == null) return;
        var infos = std.ArrayList(CaptureInfo).empty;
        defer infos.deinit(self.allocator);
        try self.collectCaptureInfos(tree, cond, true, &infos);
        if (infos.items.len != caps.?.bindings.len) try self.diagnostics.errorAt("T0020", "capture count does not match condition checks", caps.?.span, "wrong number of captures");
        const n = @min(infos.items.len, caps.?.bindings.len);
        for (infos.items[0..n], caps.?.bindings[0..n]) |ci, b| if (ci.ty == null and !std.mem.eql(u8, b.name, "_")) try self.diagnostics.errorAt("T0021", "payloadless check cannot be captured", b.span, "use `_`");
        if (tree.expr(cond).kind == .binary and tree.expr(cond).kind.binary.op == .logical_or) {
            var pt: ?types.TypeId = null;
            for (infos.items) |ci| if (ci.ty) |ct| {
                const base = if (self.tt.get(ct) == .optional) self.tt.get(ct).optional else ct;
                if (pt) |old| {
                    if (old != base) try self.diagnostics.errorAt("T0022", "enum payload types differ across ||", tree.expr(cond).span, "use match");
                } else pt = base;
            };
        }
    }
    fn collectCaptureInfos(self: *Checker, tree: *const ast.Ast, id: ast.ExprId, pure: bool, out: *std.ArrayList(CaptureInfo)) !void {
        const e = tree.expr(id);
        if (e.kind == .binary) {
            const b = e.kind.binary;
            if (b.op == .logical_and or b.op == .logical_or) {
                const child_pure = pure and b.op == .logical_and;
                try self.collectCaptureInfos(tree, b.lhs, child_pure, out);
                try self.collectCaptureInfos(tree, b.rhs, child_pure, out);
                return;
            }
            if (b.op == .eq) {
                const rhs_e = tree.expr(b.rhs);
                if (rhs_e.kind == .member or rhs_e.kind == .identifier) {
                    const m = if (rhs_e.kind == .member) rhs_e.kind.member.name else rhs_e.kind.identifier;
                    const lt = try self.synth(tree, b.lhs);
                    const ety = if (self.tt.get(lt) == .enum_type) lt else self.enum_variants.get(m.name) orelse self.tt.builtins.err;
                    if (self.findVariant(ety, m.name)) |v| {
                        const ty: ?types.TypeId = if (v.payload) |p| if (pure) p else try self.tt.optional(p) else null;
                        try out.append(self.allocator, .{ .ty = ty, .span = m.span });
                        return;
                    }
                }
            }
        }
        if (e.kind == .identifier) if (self.vars.get(e.kind.identifier.name)) |vv| if (self.tt.get(vv.ty) == .optional) {
            const inner = self.tt.get(vv.ty).optional;
            try out.append(self.allocator, .{ .ty = if (pure) inner else try self.tt.optional(inner), .span = e.span });
            return;
        };
        const ty = try self.synth(tree, id);
        if (self.tt.get(ty) == .optional) {
            const inner = self.tt.get(ty).optional;
            try out.append(self.allocator, .{ .ty = if (pure) inner else try self.tt.optional(inner), .span = e.span });
        }
    }
    fn restoreCaptures(self: *Checker, caps: ?ast.CaptureList, saved: *std.StringHashMap(Var)) !void {
        if (caps == null) return;
        for (caps.?.bindings) |b| {
            if (std.mem.eql(u8, b.name, "_")) continue;
            if (saved.get(b.name)) |old| try self.vars.put(b.name, old) else _ = self.vars.remove(b.name);
        }
    }
    fn collectOptionalCaptureTypes(self: *Checker, tree: *const ast.Ast, id: ast.ExprId, pure: bool, out: *std.ArrayList(types.TypeId)) !void {
        const e = tree.expr(id);
        if (e.kind == .binary and (e.kind.binary.op == .logical_and or e.kind.binary.op == .logical_or)) {
            try self.collectOptionalCaptureTypes(tree, e.kind.binary.lhs, pure and e.kind.binary.op == .logical_and, out);
            try self.collectOptionalCaptureTypes(tree, e.kind.binary.rhs, pure and e.kind.binary.op == .logical_and, out);
            return;
        }
        const ty = try self.synth(tree, id);
        if (self.tt.get(ty) == .optional) {
            const inner = self.tt.get(ty).optional;
            try out.append(self.allocator, if (pure) inner else try self.tt.optional(inner));
        }
    }
    fn countOptionalChecks(self: *Checker, tree: *const ast.Ast, id: ast.ExprId, out: *std.ArrayList(types.TypeId)) !void {
        const e = tree.expr(id);
        if (e.kind == .binary and (e.kind.binary.op == .logical_and or e.kind.binary.op == .logical_or)) {
            try self.countOptionalChecks(tree, e.kind.binary.lhs, out);
            try self.countOptionalChecks(tree, e.kind.binary.rhs, out);
            return;
        }
        const ty = try self.synth(tree, id);
        if (self.tt.get(ty) == .optional) try out.append(self.allocator, self.tt.get(ty).optional);
    }
    fn checkOptionalCaptures(self: *Checker, tree: *const ast.Ast, cond: ast.ExprId, caps: ?ast.CaptureList) !void {
        if (caps == null) return;
        var checks = std.ArrayList(types.TypeId).empty;
        defer checks.deinit(self.allocator);
        try self.countOptionalChecks(tree, cond, &checks);
        if (checks.items.len == 0) return;
        if (caps.?.bindings.len < checks.items.len) try self.diagnostics.errorAt("T0027", "capture count does not match optional checks", caps.?.span, "wrong number of captures");
    }
    fn isEnumTagCheck(self: *Checker, tree: *const ast.Ast, lhs: ast.ExprId, rhs: ast.ExprId, lty: types.TypeId) !bool {
        _ = lhs;
        const lt = self.tt.get(lty);
        if (lt != .enum_type) return false;
        const r = tree.expr(rhs);
        if (r.kind == .member) {
            const m = r.kind.member;
            return self.findVariant(lty, m.name.name) != null;
        }
        return false;
    }
    fn countEnumChecks(self: *Checker, tree: *const ast.Ast, id: ast.ExprId, out: *std.ArrayList(types.EnumVariant)) !void {
        const e = tree.expr(id);
        if (e.kind == .binary) {
            const b = e.kind.binary;
            if (b.op == .logical_and or b.op == .logical_or) {
                try self.countEnumChecks(tree, b.lhs, out);
                try self.countEnumChecks(tree, b.rhs, out);
                return;
            }
            if (b.op == .eq) {
                const lt = try self.synth(tree, b.lhs);
                if (self.tt.get(lt) == .enum_type and tree.expr(b.rhs).kind == .member) {
                    const m = tree.expr(b.rhs).kind.member;
                    if (tree.expr(m.object).kind == .identifier) {
                        const on = tree.expr(m.object).kind.identifier.name;
                        if (std.mem.eql(u8, on, ".")) {
                            if (self.findVariant(lt, m.name.name)) |v| try out.append(self.allocator, v);
                        } else if (self.type_values.get(on)) |ety| if (ety == lt) if (self.findVariant(lt, m.name.name)) |v| try out.append(self.allocator, v);
                    }
                }
            }
        }
    }
    fn checkEnumCaptures(self: *Checker, tree: *const ast.Ast, cond: ast.ExprId, caps: ?ast.CaptureList) !void {
        if (caps == null) return;
        var checks = std.ArrayList(types.EnumVariant).empty;
        defer checks.deinit(self.allocator);
        try self.countEnumChecks(tree, cond, &checks);
        const bindings = caps.?.bindings;
        if (checks.items.len == 0) return;
        var opt_checks = std.ArrayList(types.TypeId).empty;
        defer opt_checks.deinit(self.allocator);
        try self.countOptionalChecks(tree, cond, &opt_checks);
        if (opt_checks.items.len == 0 and checks.items.len != bindings.len) try self.diagnostics.errorAt("T0020", "capture count does not match enum checks", caps.?.span, "wrong number of captures");
        const n = @min(checks.items.len, bindings.len);
        for (checks.items[0..n], bindings[0..n]) |v, b| {
            if (v.payload == null and !std.mem.eql(u8, b.name, "_")) try self.diagnostics.errorAt("T0021", "payloadless variant cannot be captured", b.span, "use `_`");
        }
        if (tree.expr(cond).kind == .binary and tree.expr(cond).kind.binary.op == .logical_or and checks.items.len > 1) {
            var pt: ?types.TypeId = null;
            for (checks.items) |v| if (v.payload) |p| {
                if (pt) |old| {
                    if (old != p) try self.diagnostics.errorAt("T0022", "enum payload types differ across ||", tree.expr(cond).span, "use match");
                } else pt = p;
            };
        }
    }
    fn findField(self: *Checker, ty: types.TypeId, name: []const u8) ?types.TypeId {
        const t = self.tt.get(ty);
        if (t != .struct_type) return null;
        for (t.struct_type) |f| if (std.mem.eql(u8, f.name, name)) return f.ty;
        return null;
    }
    fn findVariant(self: *Checker, ty: types.TypeId, name: []const u8) ?types.EnumVariant {
        const t = self.tt.get(ty);
        if (t != .enum_type) return null;
        for (t.enum_type) |v| if (std.mem.eql(u8, v.name, name)) return v;
        return null;
    }
    fn synthMember(self: *Checker, tree: *const ast.Ast, id: ast.ExprId, m: anytype) !types.TypeId {
        _ = id;
        if (tree.expr(m.object).kind == .identifier) {
            const on = tree.expr(m.object).kind.identifier.name;
            if (self.type_values.get(on)) |ety| {
                if (self.findVariant(ety, m.name.name)) |_| return ety;
            }
        }
        const obj = try self.synth(tree, m.object);
        if (self.findField(obj, m.name.name)) |fty| return fty;
        if (self.tt.get(obj) == .pointer) if (self.findField(self.tt.get(obj).pointer, m.name.name)) |fty| return fty;
        return self.tt.builtins.err;
    }
    fn checkStructLiteral(self: *Checker, tree: *const ast.Ast, span: anytype, ty: types.TypeId, fields: []const ast.FieldInit) !void {
        const st = self.tt.get(ty);
        if (st != .struct_type) {
            try self.typeMismatch(span);
            return;
        }
        var seen = std.StringHashMap(void).init(self.allocator);
        defer seen.deinit();
        for (fields) |f| {
            if (seen.contains(f.name.name)) try self.diagnostics.errorAt("T0013", "duplicate field in struct literal", f.span, "duplicate field");
            try seen.put(f.name.name, {});
            if (self.findField(ty, f.name.name)) |fty| {
                if (f.value) |v| try self.check(tree, v, fty);
            } else try self.diagnostics.errorAt("T0014", "extra field in struct literal", f.span, "field not declared");
        }
        for (st.struct_type) |sf| if (!seen.contains(sf.name)) try self.diagnostics.errorAt("T0015", "missing required field in struct literal", span, "missing field");
    }
    fn checkEnumVariant(self: *Checker, tree: *const ast.Ast, span: anytype, expected: types.TypeId, name: ast.Ident, payload: ?ast.ExprId) !void {
        const target0 = if (self.tt.get(expected) == .error_union) self.tt.get(expected).error_union.ok else expected;
        const target = if (self.enum_variants.get(name.name)) |et| et else if (self.tt.get(target0) == .err) target0 else target0;
        if (self.findVariant(target, name.name)) |v| {
            if (v.payload) |pty| {
                if (payload) |p| try self.check(tree, p, pty);
            } else if (payload != null) try self.diagnostics.errorAt("T0017", "enum variant has no payload", span, "unexpected payload");
        } else try self.diagnostics.errorAt("T0018", "enum variant not found", name.span, "unknown variant");
    }
    fn synthMethodOrEnumCall(self: *Checker, tree: *const ast.Ast, span: anytype, c: anytype) !types.TypeId {
        _ = span;
        const m = tree.expr(c.callee).kind.member;
        if (tree.expr(m.object).kind == .identifier) {
            const on = tree.expr(m.object).kind.identifier.name;
            if (self.type_values.get(on)) |ety| {
                if (self.findVariant(ety, m.name.name)) |v| {
                    if (v.payload) |pty| {
                        if (c.args.len > 0) try self.check(tree, c.args[0].value, pty);
                    }
                    return ety;
                }
            }
        }
        const objty = try self.synth(tree, m.object);
        const tn = self.typeNameFor(objty) orelse return self.tt.builtins.err;
        const key = try std.fmt.allocPrint(self.allocator, "{s}.{s}", .{ tn, m.name.name });
        if (self.methods.get(key)) |fty| {
            const ft = self.tt.get(fty);
            if (ft == .function) {
                const start: usize = if (ft.function.params.len > 0) 1 else 0;
                if (ft.function.params.len > 0 and ft.function.params[0].mutating == .pointer and !self.sourceMutable(tree, m.object)) try self.diagnostics.errorAt("T0010", "argument requires mutable source", tree.expr(m.object).span, "source is not mutable");
                for (ft.function.params[start..], c.args) |p, a| try self.check(tree, a.value, p.ty);
                return ft.function.ret;
            }
        }
        return self.tt.builtins.err;
    }
    fn typeNameFor(self: *Checker, ty: types.TypeId) ?[]const u8 {
        var it = self.type_values.iterator();
        while (it.next()) |e| if (e.value_ptr.* == ty) return e.key_ptr.*;
        return null;
    }
    fn synthMatch(self: *Checker, tree: *const ast.Ast, ma: anytype) !types.TypeId {
        const sty = try self.synth(tree, ma.subject);
        const t = self.tt.get(sty);
        var has_wild = false;
        var seen = std.StringHashMap(void).init(self.allocator);
        defer seen.deinit();
        for (ma.arms) |arm| {
            for (arm.patterns) |pid| switch (tree.pattern(pid).kind) {
                .wildcard => has_wild = true,
                .enum_variant => |ev| if (ev.path.parts.len > 0) try seen.put(ev.path.parts[0].name, {}),
                .literal => |lit| switch (lit) {
                    .true => try seen.put("true", {}),
                    .false => try seen.put("false", {}),
                    else => {},
                },
                else => {},
            };
            _ = try self.synth(tree, arm.body);
        }
        if (!has_wild) {
            if (t == .enum_type) {
                for (t.enum_type) |v| if (!seen.contains(v.name)) try self.diagnostics.errorAt("T0019", "non-exhaustive match", tree.expr(ma.subject).span, "missing enum variant");
            } else if (sty == self.tt.builtins.u1) {
                if (!seen.contains("true") or !seen.contains("false")) try self.diagnostics.errorAt("T0019", "non-exhaustive match", tree.expr(ma.subject).span, "missing boolean case");
            }
        }
        return self.tt.builtins.void;
    }
    fn evalArrayLen(self: *Checker, tree: *const ast.Ast, id: ast.ExprId) !u64 {
        const e = tree.expr(id);
        if (e.kind == .literal and e.kind.literal == .integer) return std.fmt.parseInt(u64, e.kind.literal.integer, 0) catch 0;
        try self.diagnostics.errorAt("T0007", "array length must be an integer literal in this subset", e.span, "length not supported yet");
        return 0;
    }
    fn checkFor(self: *Checker, tree: *const ast.Ast, f: anytype) !void {
        if (f.head) |h| switch (h) {
            .while_ => |w| try self.check(tree, w.condition, self.tt.builtins.u1),
            .iteration => |it| {
                if (it.captures.bindings.len != it.iterables.len) try self.diagnostics.errorAt("T0008", "for capture count does not match iterable count", it.captures.span, "wrong number of captures");
                for (it.iterables, 0..) |ex, idx| {
                    const ty0 = try self.synth(tree, ex);
                    const ty = self.tt.get(ty0);
                    const elem = switch (ty) {
                        .array => |a| a.elem,
                        .slice => |s| s,
                        .range => |r| r,
                        else => blk: {
                            try self.diagnostics.errorAt("T0009", "for iterable must be array, slice, or range", tree.expr(ex).span, "not iterable");
                            break :blk self.tt.builtins.err;
                        },
                    };
                    if (idx < it.captures.bindings.len) try self.vars.put(it.captures.bindings[idx].name, .{ .ty = elem });
                }
            },
        };
        _ = try self.synth(tree, f.body);
    }
    fn sourceMutable(self: *Checker, tree: *const ast.Ast, id: ast.ExprId) bool {
        const e = tree.expr(id);
        return switch (e.kind) {
            .identifier => |n| if (self.vars.get(n.name)) |v| v.source_mutable or v.mutable else false,
            .unary => |u| u.op == .address_of and self.sourceMutable(tree, u.operand),
            .index => |x| self.sourceMutable(tree, x.object),
            .member => |m| self.sourceMutable(tree, m.object),
            .grouped => |g| self.sourceMutable(tree, g),
            else => false,
        };
    }
    fn intLiteralFits(self: *Checker, txt: []const u8, target: types.TypeId, neg: bool) bool {
        const ty = self.tt.get(target);
        if (ty != .int) return true;
        const clean = stripUnderscores(self.allocator, txt) catch return false;
        defer self.allocator.free(clean);
        const val = std.fmt.parseInt(u128, clean, 0) catch return ty.int.width > 128;
        if (ty.int.width >= 128) return true;
        if (ty.int.signedness == .unsigned) return !neg and val < (@as(u128, 1) << @intCast(ty.int.width));
        const max = (@as(u128, 1) << @intCast(ty.int.width - 1)) - 1;
        return if (neg) val <= max + 1 else val <= max;
    }
};
fn stripUnderscores(a: std.mem.Allocator, s: []const u8) ![]u8 {
    var out = std.ArrayList(u8).empty;
    for (s) |c| if (c != '_') try out.append(a, c);
    return out.toOwnedSlice(a);
}
pub fn checkSource(allocator: std.mem.Allocator, src: []const u8, bag: *diag.DiagnosticBag) !void {
    const parsed = try parser.parseFileSource(allocator, src, bag);
    var c = try Checker.init(allocator, bag);
    defer c.deinit();
    try c.checkFile(&parsed.tree, parsed.file);
}

test "checker accepts arbitrary integer widths" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nx: u3 = 5\ny: i17 = -1\nz: u129 = 0\nflag: u1 = true\n", &bag);
    try std.testing.expectEqual(@as(usize, 0), bag.error_count);
}
test "checker rejects out of range integer literal" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nx: u3 = 9\n", &bag);
    try std.testing.expect(bag.error_count > 0);
}
test "checker accepts simple function call" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nadd := (a: i32, b: i32) i32 => a + b\nx := add(1, 2)\n", &bag);
    try std.testing.expectEqual(@as(usize, 0), bag.error_count);
}
test "checker handles arrays slices for and assignment mutability" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nmain := () {\nmut x: i32 = 1\nx = 2\narr: [3]i32 = [1,2,3]\n}\n", &bag);
    try std.testing.expectEqual(@as(usize, 0), bag.error_count);
}
test "checker rejects immutable assignment and for count mismatch" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nmain := () {\nx: i32 = 1\nx = 2\nfor 0..3: |a, b| {}\n}\n", &bag);
    try std.testing.expect(bag.error_count >= 2);
}
test "checker handles structs enums and methods" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nPoint := struct { x: i32, y: i32 }\nColor := enum { Red, Green }\nPoint.sum := (self: Point) i32 => self.x + self.y\np: Point = Point{ x: 1, y: 2 }\na: Point = .{ x: 1, y: 2 }\nr: Color = .Red\ns := p.sum()\n", &bag);
    try std.testing.expectEqual(@as(usize, 0), bag.error_count);
}
test "checker rejects struct literal and match errors" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nPoint := struct { x: i32, y: i32 }\nColor := enum { Red, Green }\np: Point = Point{ x: 1, z: 2 }\nr: Color = .Red\nmain := () { match r { .Red: {} } }\n", &bag);
    try std.testing.expect(bag.error_count >= 2);
}
test "checker enum captures and payload diagnostics" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nE := enum { A: i32, B, C: f32 }\nmain := () {\ne: E = .A(1)\nif e == .A: |v| {}\nif e == .B: |bad| {}\nif e == .A || e == .C: |a, c| {}\n}\n", &bag);
    try std.testing.expect(bag.error_count >= 2);
}
test "checker mut receiver method requires mutable source" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nPoint := struct { x: i32 }\nPoint.bump := (self: *mut Point) void => 0\nmain := () {\np: Point = .{ x: 1 }\np.bump()\n}\n", &bag);
    try std.testing.expect(bag.error_count > 0);
}
test "checker generic type memoizes and comp if works" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nList := (comp T: type) type => struct { item: T }\nA := List(i32)\nB := List(i32)\n", &bag);
    try std.testing.expectEqual(@as(usize, 0), bag.error_count);
}
test "checker generic function and comp if type" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nid := (comp T: type, x: T) T => x\ny: i32 = id(i32, 1)\nPick := () comp if true i32 else f32 => 1\nz: i32 = Pick()\n", &bag);
    try std.testing.expectEqual(@as(usize, 0), bag.error_count);
}
test "checker recursive generic type does not recurse forever" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nTree := (comp T: type) type => struct { value: T, children: []Tree(T) }\nA := Tree(i32)\n", &bag);
    try std.testing.expectEqual(@as(usize, 0), bag.error_count);
}
test "checker generic pair and fn specialization cache" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    const src = "module t\nPair := (comp A: type, comp B: type) type => struct { a: A, b: B }\nid := (comp T: type, x: T) T => x\nP := Pair(i32, f32)\ny: i32 = id(i32, 1)\nz: i32 = id(i32, 2)\n";
    const parsed = try parser.parseFileSource(a, src, &bag);
    var c = try Checker.init(a, &bag);
    defer c.deinit();
    try c.checkFile(&parsed.tree, parsed.file);
    try std.testing.expectEqual(@as(usize, 0), bag.error_count);
    try std.testing.expect(c.generic_fn_cache.count() >= 1);
}
test "checker comp if type branch and recursive generic smoke" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nPick := () comp if true i32 else f32 => 1\nz: i32 = Pick()\nTree := (comp T: type) type => struct { value: T, children: []Tree(T) }\nA := Tree(i32)\n", &bag);
    try std.testing.expectEqual(@as(usize, 0), bag.error_count);
}
test "checker optionals unwrap and or" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nx: ?i32 = null\ny: ?i32 = 1\nz: i32 = y.?\nw: i32 = x or 0\n", &bag);
    try std.testing.expectEqual(@as(usize, 0), bag.error_count);
}
test "checker rejects bad optional unwrap and null context" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nx := null\ny: i32 = 1.?\n", &bag);
    try std.testing.expect(bag.error_count >= 2);
}

test "checker error unions unwrap and or" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nmain := () i32! {\nx: i32! = 1\ny: i32 = x.!\nz: i32 = x or 0\nreturn y\n}\n", &bag);
    try std.testing.expectEqual(@as(usize, 0), bag.error_count);
}

test "checker optional condition captures forms" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nmain := () {\na: ?i32 = 1\nb: ?i32 = 2\nif a: |x| {}\nif a && b: |x, y| {}\nif a || b: |x, y| {}\nif 1 < 2 && a: |x| {}\n}\n", &bag);
    try std.testing.expectEqual(@as(usize, 0), bag.error_count);
}

test "checker or capture and control fallback parse/check" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nmain := () {\nx: i32! = 1\ny := x or |e| 0\nz := x or return\nreturn\n}\n", &bag);
    try std.testing.expectEqual(@as(usize, 0), bag.error_count);
}

test "checker combined optional error union outside in" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nmain := () i32! {\nx: ?i32! = null\ny: i32 = x.!.?\nreturn y\n}\n", &bag);
    try std.testing.expectEqual(@as(usize, 0), bag.error_count);
}

test "checker rejects error unwrap in non error function and runs defer capture" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nbad := () i32 { x: i32! = 1; y := x.!; return y }\ngood := () i32! { defer |e| { e }; x: i32! = 1; y := x.!; return y }\n", &bag);
    try std.testing.expect(bag.error_count >= 1);
}

test "checker optional capture vars have conjunctive or disjunctive types" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nmain := () {\na: ?i32 = 1\nb: ?i32 = 2\nif a && b: |x, y| { z: i32 = x }\nif a || b: |x, y| { z: ?i32 = x }\n}\n", &bag);
    try std.testing.expectEqual(@as(usize, 0), bag.error_count);
}

test "checker explicit error set syntax consumed" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nErr1 := enum { A }\nErr2 := enum { B }\nx: i32!Err1|Err2 = 1\n", &bag);
    try std.testing.expectEqual(@as(usize, 0), bag.error_count);
}

test "checker enum registry smoke" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    const parsed = try parser.parseFileSource(a, "module t\nE := enum { V: i32, N }\n", &bag);
    var c = try Checker.init(a, &bag);
    defer c.deinit();
    try c.checkFile(&parsed.tree, parsed.file);
    try std.testing.expect(c.enum_variants.contains("V"));
    try std.testing.expect(c.enum_variants.contains("N"));
}

test "checker enum variant construction and mixed optional captures" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    try checkSource(a, "module t\nE := enum { V: i32, N }\nmain := () {\ne: E = E.V(1)\ne2: E = .N\no: ?i32 = 2\nif e == .V && o: |v, x| { y: i32 = x }\nif e == .V || o: |v, x| { y: ?i32 = x }\n}\n", &bag);
    if (bag.error_count != 0) for (bag.diagnostics.items) |d| std.debug.print("ERR {s}@{} {s}\n", .{ d.code, d.primary.span.start, d.message });
    try std.testing.expectEqual(@as(usize, 0), bag.error_count);
}
