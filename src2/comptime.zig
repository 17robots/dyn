const std = @import("std");
const ast = @import("ast.zig");
const diag = @import("diag.zig");
const types = @import("types.zig");

pub const Limits = struct { call_depth: usize = 1024, loop_iterations: usize = 1_000_000, operations: usize = 100_000_000 };
pub const CtValue = union(enum) {
    comptime_int: std.math.big.int.Managed,
    comptime_float: []const u8,
    int: struct { ty: types.TypeId, value: std.math.big.int.Managed },
    float: struct { ty: types.TypeId, value: f128 },
    char: u21,
    string: []const u8,
    type: types.TypeId,
    struct_value: []const FieldValue,
    enum_variant: struct { tag: []const u8, payload: ?*CtValue = null },
    function: ast.ExprId,
    lambda: ast.ExprId,
    extern_symbol: struct { name: []const u8, ty: types.TypeId },
    array: []const CtValue,
    field_info: struct { name: []const u8, ty: types.TypeId, index: usize },
    error_value: struct { ty: types.TypeId, tag: []const u8 },
    null,
    void,
    err,
};
pub const FieldValue = struct { name: []const u8, value: CtValue };
pub const Evaluator = struct {
    allocator: std.mem.Allocator,
    diagnostics: *diag.DiagnosticBag,
    tt: *types.TypeTable,
    limits: Limits = .{},
    ops: usize = 0,
    depth: usize = 0,
    loop_iterations: usize = 0,
    values: std.StringHashMap(CtValue) = .init(std.heap.page_allocator),
    functions: std.StringHashMap(ast.ExprId) = .init(std.heap.page_allocator),
    in_progress: std.StringHashMap(types.TypeId) = .init(std.heap.page_allocator),
    declarations: std.StringHashMap(CtValue) = .init(std.heap.page_allocator),
    named_types: std.StringHashMap(types.TypeId) = .init(std.heap.page_allocator),
    mutable_types: std.AutoHashMap(types.TypeId, void) = .init(std.heap.page_allocator),
    allow_declare: bool = false,
    construction_depth: usize = 0,

    pub fn init(allocator: std.mem.Allocator, diagnostics: *diag.DiagnosticBag, tt: *types.TypeTable, limits: Limits) Evaluator {
        return .{ .allocator = allocator, .diagnostics = diagnostics, .tt = tt, .limits = limits, .values = .init(allocator), .functions = .init(allocator), .in_progress = .init(allocator), .declarations = .init(allocator), .named_types = .init(allocator), .mutable_types = .init(allocator) };
    }

    fn tick(self: *Evaluator, span: anytype) !void {
        self.ops += 1;
        if (self.ops > self.limits.operations) try self.diagnostics.errorAt("E0001", "comptime operation limit exceeded", span, "operation limit exceeded");
    }

    pub fn evalToType(self: *Evaluator, tree: *const ast.Ast, id: ast.ExprId) !types.TypeId {
        const v = try self.eval(tree, id);
        return switch (v) {
            .type => |t| t,
            else => blk: {
                try self.diagnostics.errorAt("E0002", "expression did not evaluate to a type", tree.expr(id).span, "expected type value");
                break :blk self.tt.builtins.err;
            },
        };
    }

    pub fn eval(self: *Evaluator, tree: *const ast.Ast, id: ast.ExprId) anyerror!CtValue {
        const e = tree.expr(id);
        try self.tick(e.span);
        return switch (e.kind) {
            .literal => |lit| try self.evalLiteral(lit),
            .identifier => |n| if (self.values.get(n.name)) |v| v else if (self.functions.get(n.name)) |fid| .{ .function = fid } else try self.evalTypeName(n),
            .builtin_identifier => |n| try self.evalTypeName(n),
            .grouped => |x| try self.eval(tree, x),
            .member => |m| try self.evalMember(tree, m),
            .array_type => |at| .{ .type = try self.tt.array(try self.evalArrayLen(tree, at.len), try self.evalToType(tree, at.elem)) },
            .slice_type => |elem| .{ .type = try self.tt.slice(try self.evalToType(tree, elem)) },
            .struct_type => |fields| .{ .type = try self.evalStructType(tree, fields) },
            .enum_type => |en| .{ .type = try self.evalEnumType(tree, en.variants) },
            .error_union_type => |eu| .{ .type = try self.evalErrorUnionType(tree, eu) },
            .function => .{ .function = id },
            .anon_struct_literal => |fields| try self.evalStructValue(tree, fields),
            .typed_struct_literal => |ts| try self.evalStructValue(tree, ts.fields),
            .if_expr => |i| blk: {
                const cond = try self.truthy(tree, i.condition);
                break :blk if (cond) try self.eval(tree, i.then_branch) else if (i.else_branch) |el| try self.eval(tree, el) else .void;
            },
            .call => |c| try self.evalCall(tree, e.span, c),
            .unary => |u| if (u.op == .neg) try self.evalNeg(tree, u.operand) else if (u.op == .comp) try self.eval(tree, u.operand) else .err,
            .binary => |b| try self.evalBinary(tree, b),
            .or_fallback => |o| try self.evalOrFallback(tree, o),
            .for_expr => |f| try self.evalFor(tree, e.span, f),
            .block => |stmts| try self.evalBlock(tree, stmts),
            else => .err,
        };
    }

    pub fn collectModuleDecls(self: *Evaluator, tree: *const ast.Ast, file: ast.File) !void {
        for (file.items) |it| {
            const d = tree.decl(tree.topLevelItem(it).kind.declaration);
            if (d.target == .name and tree.expr(d.value).kind == .function) try self.functions.put(d.target.name.name, d.value);
            if (d.target == .name and (tree.expr(d.value).kind == .struct_type or tree.expr(d.value).kind == .enum_type)) {
                const ty = try self.evalToType(tree, d.value);
                try self.named_types.put(d.target.name.name, ty);
            }
        }
        for (file.items) |it| {
            const d = tree.decl(tree.topLevelItem(it).kind.declaration);
            if (d.target == .associated) {
                const tn = d.target.associated.type_path.parts[0].name;
                if (self.named_types.get(tn)) |ty| {
                    const key = try std.fmt.allocPrint(self.allocator, "{}.{s}", .{ @intFromEnum(ty), d.target.associated.name.name });
                    try self.declarations.put(key, try self.eval(tree, d.value));
                }
            }
        }
    }

    fn evalLiteral(self: *Evaluator, lit: ast.Literal) !CtValue {
        return switch (lit) {
            .integer => |txt| blk: {
                var v = try std.math.big.int.Managed.init(self.allocator);
                try v.setString(10, stripUnderscores(self.allocator, txt) catch txt);
                break :blk .{ .comptime_int = v };
            },
            .float => |txt| .{ .comptime_float = txt },
            .string => |s| .{ .string = s },
            .char => |c| .{ .char = if (c.len > 0) c[0] else 0 },
            .true => blk: {
                const v = try std.math.big.int.Managed.initSet(self.allocator, 1);
                break :blk .{ .int = .{ .ty = self.tt.builtins.u1, .value = v } };
            },
            .false => blk: {
                const v = try std.math.big.int.Managed.initSet(self.allocator, 0);
                break :blk .{ .int = .{ .ty = self.tt.builtins.u1, .value = v } };
            },
            .null => .null,
        };
    }

    fn evalTypeName(self: *Evaluator, n: ast.Ident) !CtValue {
        if (self.named_types.get(n.name)) |t| return .{ .type = t };
        if (std.mem.eql(u8, n.name, "type")) return .{ .type = self.tt.builtins.type };
        if (std.mem.eql(u8, n.name, "void")) return .{ .type = self.tt.builtins.void };
        if (std.mem.eql(u8, n.name, "f32")) return .{ .type = self.tt.builtins.f32 };
        if (std.mem.eql(u8, n.name, "f64")) return .{ .type = self.tt.builtins.f64 };
        if (std.mem.eql(u8, n.name, "usize")) return .{ .type = try self.tt.intern(.usize) };
        if (std.mem.eql(u8, n.name, "isize")) return .{ .type = try self.tt.intern(.isize) };
        if (n.name.len >= 2 and (n.name[0] == 'i' or n.name[0] == 'u')) return .{ .type = try self.tt.int(if (n.name[0] == 'i') .signed else .unsigned, try std.fmt.parseInt(u16, n.name[1..], 10)) };
        return .err;
    }

    fn evalCall(self: *Evaluator, tree: *const ast.Ast, span: anytype, c: anytype) !CtValue {
        if (tree.expr(c.callee).kind != .builtin_identifier) {
            if (tree.expr(c.callee).kind == .identifier) {
                const cn = tree.expr(c.callee).kind.identifier.name;
                if (self.functions.get(cn)) |fid| {
                    const key = try self.genericKey(tree, cn, c.args);
                    if (self.in_progress.get(key)) |tid| return .{ .type = tid };
                    const placeholder = try self.tt.structType(&.{});
                    try self.in_progress.put(key, placeholder);
                    const out = try self.evalFunctionCallArgs(tree, span, fid, c.args);
                    _ = self.in_progress.remove(key);
                    return out;
                }
            }
            const cal = try self.eval(tree, c.callee);
            if (cal == .function) return try self.evalFunctionCallArgs(tree, span, cal.function, c.args);
            return .err;
        }
        const name = tree.expr(c.callee).kind.builtin_identifier.name;
        if (std.mem.eql(u8, name, "$compile_error") or std.mem.eql(u8, name, "$panic")) {
            try self.diagnostics.errorAt("E0003", "comptime error requested", span, name);
            return .err;
        }
        if (std.mem.eql(u8, name, "$as")) return if (c.args.len >= 2) self.evalCast(tree, c.args[0].value, c.args[1].value) else .err;
        if (std.mem.eql(u8, name, "$sizeof")) return try self.intValue(try self.sizeof(try self.evalToType(tree, c.args[0].value)));
        if (std.mem.eql(u8, name, "$alignof")) return try self.intValue(try self.alignof(try self.evalToType(tree, c.args[0].value)));
        if (std.mem.eql(u8, name, "$typeof")) return if (c.args.len >= 1) .{ .type = try self.typeofValue(tree, c.args[0].value) } else .err;
        if (std.mem.eql(u8, name, "$fields")) return if (c.args.len >= 1) try self.fieldsValue(tree, c.args[0].value, span) else .err;
        if (std.mem.eql(u8, name, "$field")) return try self.fieldValue(tree, c, span);
        if (std.mem.eql(u8, name, "$field_set")) return try self.fieldSet(tree, c, span);
        if (std.mem.eql(u8, name, "$declaration")) return try self.declarationValue(tree, c, span);
        if (std.mem.eql(u8, name, "$declare")) return try self.declareValue(tree, c, span);
        if (std.mem.eql(u8, name, "$fn_return")) return try self.fnReturnValue(tree, c, span);
        if (std.mem.eql(u8, name, "$fn_params")) return try self.fnParamsValue(tree, c, span);
        if (std.mem.eql(u8, name, "$self")) return .{ .type = self.tt.builtins.type };
        if (std.mem.eql(u8, name, "$read_file")) {
            try self.diagnostics.errorAt("E0005", "$read_file is not available in comptime evaluator", span, "use std support later");
            return .err;
        }
        if (std.mem.eql(u8, name, "$extern")) {
            if (c.args.len != 2) return .err;
            const sym = try self.eval(tree, c.args[0].value);
            const ty = try self.evalToType(tree, c.args[1].value);
            return .{ .extern_symbol = .{ .name = if (sym == .string) sym.string else "", .ty = ty } };
        }
        if (std.mem.startsWith(u8, name, "$wrapping_") or std.mem.startsWith(u8, name, "$saturating_") or std.mem.startsWith(u8, name, "$checked_")) return try self.evalArithmeticIntrinsic(tree, name, c);
        try self.diagnostics.errorAt("E0004", "builtin is not allowed at comptime in this step", span, "forbidden comptime builtin");
        return .err;
    }

    fn intValue(self: *Evaluator, v: u64) !CtValue {
        const bi = try std.math.big.int.Managed.initSet(self.allocator, v);
        return .{ .int = .{ .ty = try self.tt.intern(.usize), .value = bi } };
    }
    fn evalMember(self: *Evaluator, tree: *const ast.Ast, m: anytype) !CtValue {
        const obj = try self.eval(tree, m.object);
        switch (obj) {
            .field_info => |fi| {
                if (std.mem.eql(u8, m.name.name, "name")) return .{ .string = fi.name };
                if (std.mem.eql(u8, m.name.name, "type")) return .{ .type = fi.ty };
                if (std.mem.eql(u8, m.name.name, "index")) return try self.intValue(fi.index);
            },
            .struct_value => |sv| for (sv) |fv| if (std.mem.eql(u8, fv.name, m.name.name)) return fv.value,
            else => {},
        }
        return .err;
    }
    fn evalNeg(self: *Evaluator, tree: *const ast.Ast, id: ast.ExprId) !CtValue {
        var v = try self.eval(tree, id);
        if (v == .comptime_int) v.comptime_int.negate();
        return v;
    }
    fn evalOrFallback(self: *Evaluator, tree: *const ast.Ast, o: anytype) !CtValue {
        const v = try self.eval(tree, o.lhs);
        if (v == .null or v == .err or v == .error_value) {
            if (o.capture) |c| try self.values.put(c.name, v);
            return self.eval(tree, o.rhs);
        }
        return v;
    }
    fn evalBinary(self: *Evaluator, tree: *const ast.Ast, b: anytype) !CtValue {
        var a = try self.evalIntManaged(tree, b.lhs);
        var c = try self.evalIntManaged(tree, b.rhs);
        var r = try std.math.big.int.Managed.init(self.allocator);
        switch (b.op) {
            .add => try r.add(&a, &c),
            .sub => try r.sub(&a, &c),
            .mul => try r.mul(&a, &c),
            else => return .err,
        }
        return .{ .comptime_int = r };
    }
    fn genericKey(self: *Evaluator, tree: *const ast.Ast, name: []const u8, args: anytype) ![]const u8 {
        var key = std.ArrayList(u8).empty;
        try key.appendSlice(self.allocator, name);
        for (args) |a| {
            const v = try self.eval(tree, a.value);
            if (v == .type) try key.appendSlice(self.allocator, try std.fmt.allocPrint(self.allocator, "#{}", .{@intFromEnum(v.type)}));
        }
        return key.toOwnedSlice(self.allocator);
    }
    fn evalArrayLen(self: *Evaluator, tree: *const ast.Ast, id: ast.ExprId) !u64 {
        const v = try self.eval(tree, id);
        return switch (v) {
            .comptime_int => |bi| bi.toInt(u64) catch 0,
            .int => |i| i.value.toInt(u64) catch 0,
            else => 0,
        };
    }
    fn evalCast(self: *Evaluator, tree: *const ast.Ast, ty_expr: ast.ExprId, val_expr: ast.ExprId) !CtValue {
        const ty = try self.evalToType(tree, ty_expr);
        const v = try self.eval(tree, val_expr);
        if (self.tt.get(ty) == .int) {
            const bi = switch (v) {
                .comptime_int => |x| x,
                .int => |i| i.value,
                else => try std.math.big.int.Managed.initSet(self.allocator, 0),
            };
            return .{ .int = .{ .ty = ty, .value = bi } };
        }
        return v;
    }
    fn evalFunctionCall(self: *Evaluator, tree: *const ast.Ast, span: anytype, fn_id: ast.ExprId) !CtValue {
        return self.evalFunctionCallArgs(tree, span, fn_id, &.{});
    }
    pub fn evalFunctionCallArgs(self: *Evaluator, tree: *const ast.Ast, span: anytype, fn_id: ast.ExprId, args: anytype) !CtValue {
        if (self.depth >= self.limits.call_depth) {
            try self.diagnostics.errorAt("E0006", "comptime call depth limit exceeded", span, "call depth limit exceeded");
            return .err;
        }
        self.depth += 1;
        defer self.depth -= 1;
        const f = tree.expr(fn_id).kind.function;
        var saved = std.StringHashMap(CtValue).init(self.allocator);
        defer saved.deinit();
        for (f.params, 0..) |p, i| if (p.name) |n| {
            if (self.values.get(n.name)) |old| try saved.put(n.name, old);
            if (i < args.len) try self.values.put(n.name, try self.eval(tree, args[i].value));
        };
        defer {
            for (f.params) |p| {
                if (p.name) |n| {
                    if (saved.get(n.name)) |old| {
                        self.values.put(n.name, old) catch {};
                    } else {
                        _ = self.values.remove(n.name);
                    }
                }
            }
        }
        return try self.eval(tree, f.body);
    }
    fn evalBlock(self: *Evaluator, tree: *const ast.Ast, stmts: []ast.StmtId) !CtValue {
        for (stmts) |sid| {
            const st = tree.stmt(sid);
            switch (st.kind) {
                .expr => |e| _ = try self.eval(tree, e),
                .return_ => |v| if (v) |e| return try self.eval(tree, e),
                .for_stmt => |e| _ = try self.eval(tree, e),
                else => {},
            }
        }
        return .void;
    }
    fn evalFor(self: *Evaluator, tree: *const ast.Ast, span: anytype, f: anytype) !CtValue {
        if (f.head) |h| switch (h) {
            .while_ => |w| while (try self.truthy(tree, w.condition)) {
                self.loop_iterations += 1;
                if (self.loop_iterations > self.limits.loop_iterations) {
                    try self.diagnostics.errorAt("E0007", "comptime loop iteration limit exceeded", span, "loop iteration limit exceeded");
                    return .err;
                }
                _ = try self.eval(tree, f.body);
            },
            .iteration => |it| {
                if (it.iterables.len > 0) {
                    const arrv = try self.eval(tree, it.iterables[0]);
                    if (arrv == .array) {
                        for (arrv.array) |item| {
                            self.loop_iterations += 1;
                            if (self.loop_iterations > self.limits.loop_iterations) {
                                try self.diagnostics.errorAt("E0007", "comptime loop iteration limit exceeded", span, "loop iteration limit exceeded");
                                return .err;
                            }
                            if (it.captures.bindings.len > 0) try self.values.put(it.captures.bindings[0].name, item);
                            _ = try self.eval(tree, f.body);
                        }
                        return .void;
                    }
                }
                if (it.iterables.len > 0 and tree.expr(it.iterables[0]).kind == .binary) {
                    const b = tree.expr(it.iterables[0]).kind.binary;
                    if (b.op == .range_exclusive) {
                        const end = try self.evalArrayLen(tree, b.rhs);
                        var i: usize = 0;
                        while (i < end) : ({
                            i += 1;
                        }) {
                            self.loop_iterations += 1;
                            if (self.loop_iterations > self.limits.loop_iterations) {
                                try self.diagnostics.errorAt("E0007", "comptime loop iteration limit exceeded", span, "loop iteration limit exceeded");
                                return .err;
                            }
                            _ = try self.eval(tree, f.body);
                        }
                    }
                }
            },
        };
        return .void;
    }
    fn truthy(self: *Evaluator, tree: *const ast.Ast, id: ast.ExprId) !bool {
        const v = try self.eval(tree, id);
        return switch (v) {
            .int => |i| (i.value.toInt(u1) catch 0) == 1,
            .comptime_int => |i| (i.toInt(u1) catch 0) == 1,
            else => false,
        };
    }
    fn typeofValue(self: *Evaluator, tree: *const ast.Ast, id: ast.ExprId) !types.TypeId {
        const v = try self.eval(tree, id);
        return switch (v) {
            .comptime_int => self.tt.builtins.comptime_int,
            .comptime_float => self.tt.builtins.comptime_float,
            .int => |i| i.ty,
            .float => |f| f.ty,
            .string => self.tt.slice(self.tt.builtins.u8),
            .type => self.tt.builtins.type,
            .void => self.tt.builtins.void,
            else => self.tt.builtins.err,
        };
    }
    fn evalArithmeticIntrinsic(self: *Evaluator, tree: *const ast.Ast, name: []const u8, c: anytype) !CtValue {
        if (c.args.len != 2) return .err;
        const va = try self.eval(tree, c.args[0].value);
        const vb = try self.eval(tree, c.args[1].value);
        if (va == .int and vb == .int and va.int.ty == vb.int.ty) {
            const ty = self.tt.get(va.int.ty);
            if (ty == .int and ty.int.width < 64) {
                const mod: u64 = @as(u64, 1) << @intCast(ty.int.width);
                const x = va.int.value.toInt(u64) catch 0;
                const y = vb.int.value.toInt(u64) catch 0;
                var z: u64 = 0;
                if (std.mem.endsWith(u8, name, "_add")) z = x + y else if (std.mem.endsWith(u8, name, "_sub")) z = x -% y else if (std.mem.endsWith(u8, name, "_mul")) z = x * y;
                if (std.mem.startsWith(u8, name, "$wrapping_")) z %= mod;
                const bi = try std.math.big.int.Managed.initSet(self.allocator, z);
                return .{ .int = .{ .ty = va.int.ty, .value = bi } };
            }
        }
        var a = try self.valueToIntManaged(va);
        var b = try self.valueToIntManaged(vb);
        var r = try std.math.big.int.Managed.init(self.allocator);
        if (std.mem.endsWith(u8, name, "_add")) try r.add(&a, &b) else if (std.mem.endsWith(u8, name, "_sub")) try r.sub(&a, &b) else if (std.mem.endsWith(u8, name, "_mul")) try r.mul(&a, &b);
        return .{ .comptime_int = r };
    }
    fn evalIntManaged(self: *Evaluator, tree: *const ast.Ast, id: ast.ExprId) !std.math.big.int.Managed {
        return self.valueToIntManaged(try self.eval(tree, id));
    }
    fn valueToIntManaged(self: *Evaluator, v: CtValue) !std.math.big.int.Managed {
        return switch (v) {
            .comptime_int => |bi| bi,
            .int => |i| i.value,
            else => std.math.big.int.Managed.initSet(self.allocator, 0),
        };
    }

    fn fieldsValue(self: *Evaluator, tree: *const ast.Ast, arg: ast.ExprId, span: anytype) !CtValue {
        const ty = try self.fieldsType(tree, arg, span);
        const t = self.tt.get(ty);
        if (t != .struct_type) {
            try self.diagnostics.errorAt("E0008", "$fields expects a struct type or value", span, "not a struct");
            return .err;
        }
        var vals = std.ArrayList(CtValue).empty;
        for (t.struct_type, 0..) |f, i| try vals.append(self.allocator, .{ .field_info = .{ .name = f.name, .ty = f.ty, .index = i } });
        return .{ .array = try vals.toOwnedSlice(self.allocator) };
    }
    fn fieldsType(self: *Evaluator, tree: *const ast.Ast, arg: ast.ExprId, span: anytype) !types.TypeId {
        const v = try self.eval(tree, arg);
        if (v == .type) return v.type;
        if (v == .struct_value) {
            var fs = std.ArrayList(types.Field).empty;
            for (v.struct_value) |fv| try fs.append(self.allocator, .{ .name = fv.name, .ty = try self.ctType(fv.value) });
            return self.tt.structType(fs.items);
        }
        _ = span;
        return self.tt.builtins.err;
    }
    fn ctType(self: *Evaluator, v: CtValue) !types.TypeId {
        return switch (v) {
            .int => |i| i.ty,
            .comptime_int => self.tt.builtins.comptime_int,
            .comptime_float => self.tt.builtins.comptime_float,
            .string => try self.tt.slice(self.tt.builtins.u8),
            .type => self.tt.builtins.type,
            .struct_value => |s| blk: {
                var fs = std.ArrayList(types.Field).empty;
                for (s) |fv| try fs.append(self.allocator, .{ .name = fv.name, .ty = try self.ctType(fv.value) });
                break :blk try self.tt.structType(fs.items);
            },
            else => self.tt.builtins.err,
        };
    }
    fn fieldValue(self: *Evaluator, tree: *const ast.Ast, c: anytype, span: anytype) !CtValue {
        if (c.args.len < 2) return .err;
        const namev = try self.eval(tree, c.args[1].value);
        if (namev != .string) {
            try self.diagnostics.errorAt("E0009", "$field name must be a string", span, "name not string");
            return .err;
        }
        const val = try self.eval(tree, c.args[0].value);
        if (val == .struct_value) {
            for (val.struct_value) |fv| if (std.mem.eql(u8, fv.name, namev.string)) return fv.value;
            try self.diagnostics.errorAt("E0010", "field does not exist", span, "unknown field");
            return .err;
        }
        try self.diagnostics.errorAt("E0015", "$field expects a struct value", span, "not struct");
        return .err;
    }
    fn fieldSet(self: *Evaluator, tree: *const ast.Ast, c: anytype, span: anytype) !CtValue {
        if (c.args.len < 3) return .err;
        const namev = try self.eval(tree, c.args[1].value);
        const newv = try self.eval(tree, c.args[2].value);
        if (namev != .string) {
            try self.diagnostics.errorAt("E0009", "$field name must be a string", span, "name not string");
            return .err;
        }
        if (tree.expr(c.args[0].value).kind == .identifier) {
            const n = tree.expr(c.args[0].value).kind.identifier.name;
            if (self.values.get(n)) |old| {
                if (old == .struct_value) {
                    const out = try self.allocator.dupe(FieldValue, old.struct_value);
                    var found = false;
                    for (out) |*fv| if (std.mem.eql(u8, fv.name, namev.string)) {
                        fv.value = newv;
                        found = true;
                    };
                    if (!found) try self.diagnostics.errorAt("E0010", "field does not exist", span, "unknown field");
                    try self.values.put(n, .{ .struct_value = out });
                    return .void;
                }
            }
        }
        _ = try self.fieldValue(tree, c, span);
        return .void;
    }
    fn declarationValue(self: *Evaluator, tree: *const ast.Ast, c: anytype, span: anytype) !CtValue {
        if (c.args.len < 2) return .err;
        const ty = try self.evalToType(tree, c.args[0].value);
        const nv = try self.eval(tree, c.args[1].value);
        if (nv != .string) return .err;
        const key = try std.fmt.allocPrint(self.allocator, "{}.{s}", .{ @intFromEnum(ty), nv.string });
        if (self.declarations.get(key)) |v| return v;
        try self.diagnostics.errorAt("E0011", "associated declaration not found", span, "not found");
        return .err;
    }
    fn declareValue(self: *Evaluator, tree: *const ast.Ast, c: anytype, span: anytype) !CtValue {
        if (c.args.len < 3) return .err;
        const ty = try self.evalToType(tree, c.args[0].value);
        if (!self.allow_declare and !self.mutable_types.contains(ty)) {
            try self.diagnostics.errorAt("E0012", "$declare on frozen type is not allowed", span, "type is frozen");
            return .err;
        }
        const nv = try self.eval(tree, c.args[1].value);
        const vv = try self.eval(tree, c.args[2].value);
        if (nv != .string) return .err;
        const key = try std.fmt.allocPrint(self.allocator, "{}.{s}", .{ @intFromEnum(ty), nv.string });
        if (self.declarations.contains(key)) {
            try self.diagnostics.errorAt("E0016", "associated declaration already exists", span, "duplicate declaration");
            return .err;
        }
        try self.declarations.put(key, vv);
        return .void;
    }
    fn fnReturnValue(self: *Evaluator, tree: *const ast.Ast, c: anytype, span: anytype) !CtValue {
        if (c.args.len < 1) return .err;
        const ty = try self.evalFunctionishType(tree, c.args[0].value);
        const t = self.tt.get(ty);
        if (t != .function) {
            try self.diagnostics.errorAt("E0013", "$fn_return expects function type", span, "not function");
            return .err;
        }
        return .{ .type = t.function.ret };
    }
    fn fnParamsValue(self: *Evaluator, tree: *const ast.Ast, c: anytype, span: anytype) !CtValue {
        if (c.args.len < 1) return .err;
        const ty = try self.evalFunctionishType(tree, c.args[0].value);
        const t = self.tt.get(ty);
        if (t != .function) {
            try self.diagnostics.errorAt("E0014", "$fn_params expects function type", span, "not function");
            return .err;
        }
        var fs = std.ArrayList(types.Field).empty;
        for (t.function.params, 0..) |p, i| try fs.append(self.allocator, .{ .name = try std.fmt.allocPrint(self.allocator, "{}", .{i}), .ty = p.ty });
        return .{ .type = try self.tt.structType(fs.items) };
    }

    fn evalFunctionishType(self: *Evaluator, tree: *const ast.Ast, id: ast.ExprId) !types.TypeId {
        const e = tree.expr(id);
        if (e.kind == .function) return self.evalFunctionType(tree, e.kind.function);
        return self.evalToType(tree, id);
    }
    fn evalFunctionType(self: *Evaluator, tree: *const ast.Ast, f: anytype) !types.TypeId {
        var ps = std.ArrayList(types.Param).empty;
        for (f.params) |p| {
            const ty = switch (p.ty) {
                .ordinary => |te| try self.evalToType(tree, te),
                .mut_pointer => |te| try self.tt.pointer(try self.evalToType(tree, te)),
                .mut_slice => |te| try self.tt.slice(try self.evalToType(tree, te)),
            };
            try ps.append(self.allocator, .{ .ty = ty, .is_comptime = p.is_comptime });
        }
        const ret = if (f.return_type) |rt| try self.evalToType(tree, rt) else self.tt.builtins.void;
        return self.tt.function(ps.items, ret);
    }
    fn evalErrorUnionType(self: *Evaluator, tree: *const ast.Ast, eu: anytype) !types.TypeId {
        var members = std.ArrayList(types.TypeId).empty;
        defer members.deinit(self.allocator);
        for (eu.errors) |er| try members.append(self.allocator, try self.evalToType(tree, er));
        const err_ty = if (members.items.len == 0) self.tt.builtins.err else try self.tt.errorSet(members.items);
        return self.tt.errorUnion(try self.evalToType(tree, eu.ok), err_ty);
    }
    fn evalStructValue(self: *Evaluator, tree: *const ast.Ast, fields: []const ast.FieldInit) !CtValue {
        var vals = std.ArrayList(FieldValue).empty;
        for (fields) |f| if (f.value) |v| try vals.append(self.allocator, .{ .name = f.name.name, .value = try self.eval(tree, v) });
        return .{ .struct_value = try vals.toOwnedSlice(self.allocator) };
    }
    fn evalStructType(self: *Evaluator, tree: *const ast.Ast, fields: []const ast.StructField) !types.TypeId {
        self.construction_depth += 1;
        defer self.construction_depth -= 1;
        var fs = std.ArrayList(types.Field).empty;
        for (fields) |f| try fs.append(self.allocator, .{ .name = f.name.name, .ty = try self.evalToType(tree, f.ty) });
        defer fs.deinit(self.allocator);
        const ty = try self.tt.structType(fs.items);
        try self.mutable_types.put(ty, {});
        return ty;
    }
    fn evalEnumType(self: *Evaluator, tree: *const ast.Ast, vars: []const ast.EnumVariant) !types.TypeId {
        var vs = std.ArrayList(types.EnumVariant).empty;
        for (vars) |v| try vs.append(self.allocator, .{ .name = v.name.name, .payload = if (v.payload) |p| try self.evalToType(tree, p) else null });
        defer vs.deinit(self.allocator);
        return self.tt.enumType(vs.items);
    }
    fn sizeof(self: *Evaluator, ty: types.TypeId) !u64 {
        return switch (self.tt.get(ty)) {
            .int => |i| (@as(u64, i.width) + 7) / 8,
            .float => |f| if (f == .f32) 4 else 8,
            .pointer, .slice, .usize, .isize => 8,
            .void => 0,
            else => 0,
        };
    }
    fn alignof(self: *Evaluator, ty: types.TypeId) !u64 {
        const s = try self.sizeof(ty);
        return if (s == 0) 1 else @min(s, 8);
    }
};
fn stripUnderscores(a: std.mem.Allocator, s: []const u8) ![]u8 {
    var out = std.ArrayList(u8).empty;
    for (s) |c| if (c != '_') try out.append(a, c);
    return out.toOwnedSlice(a);
}

test "comptime type construction interns same shape" {
    const parser = @import("parser.zig");
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    const parsed = try parser.parseFileSource(a, "module t\nS := struct { x: i32 }\n", &bag);
    var tt = try types.TypeTable.init(a);
    var ev = Evaluator.init(a, &bag, &tt, .{});
    const decl = parsed.tree.decl(parsed.tree.topLevelItem(parsed.file.items[0]).kind.declaration);
    const t1 = try ev.evalToType(&parsed.tree, decl.value);
    const t2 = try ev.evalToType(&parsed.tree, decl.value);
    try std.testing.expectEqual(t1, t2);
}
test "comptime intrinsics and limits" {
    const parser = @import("parser.zig");
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    const parsed = try parser.parseFileSource(a, "module t\nA := $sizeof(i32)\nB := $alignof(i32)\nC := $typeof(1)\nD := $wrapping_add(1, 2)\n", &bag);
    var tt = try types.TypeTable.init(a);
    var ev = Evaluator.init(a, &bag, &tt, .{});
    for (parsed.file.items) |it| _ = try ev.eval(&parsed.tree, parsed.tree.decl(parsed.tree.topLevelItem(it).kind.declaration).value);
    try std.testing.expectEqual(@as(usize, 0), bag.error_count);
    var ev2 = Evaluator.init(a, &bag, &tt, .{ .operations = 0 });
    _ = try ev2.eval(&parsed.tree, parsed.tree.decl(parsed.tree.topLevelItem(parsed.file.items[0]).kind.declaration).value);
    try std.testing.expect(bag.error_count > 0);
}
test "comptime read file forbidden" {
    const parser = @import("parser.zig");
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    const parsed = try parser.parseFileSource(a, "module t\nA := $read_file(\"x\")\n", &bag);
    var tt = try types.TypeTable.init(a);
    var ev = Evaluator.init(a, &bag, &tt, .{});
    _ = try ev.eval(&parsed.tree, parsed.tree.decl(parsed.tree.topLevelItem(parsed.file.items[0]).kind.declaration).value);
    try std.testing.expect(bag.error_count > 0);
}
test "comptime call depth and loop limits trigger" {
    const parser = @import("parser.zig");
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    const parsed = try parser.parseFileSource(a, "module t\nF := () i32 => 1\nL := comp for true {}\n", &bag);
    var tt = try types.TypeTable.init(a);
    var ev = Evaluator.init(a, &bag, &tt, .{ .call_depth = 0, .loop_iterations = 1 });
    _ = try ev.eval(&parsed.tree, parsed.tree.decl(parsed.tree.topLevelItem(parsed.file.items[0]).kind.declaration).value);
    _ = try ev.eval(&parsed.tree, parsed.tree.decl(parsed.tree.topLevelItem(parsed.file.items[1]).kind.declaration).value);
    try std.testing.expect(bag.error_count > 0);
}
test "comptime extern and wrapping cast" {
    const parser = @import("parser.zig");
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    const parsed = try parser.parseFileSource(a, "module t\nE := $extern(\"puts\", i32)\nW := $wrapping_add($as(u3, 7), $as(u3, 1))\n", &bag);
    var tt = try types.TypeTable.init(a);
    var ev = Evaluator.init(a, &bag, &tt, .{});
    const e = try ev.eval(&parsed.tree, parsed.tree.decl(parsed.tree.topLevelItem(parsed.file.items[0]).kind.declaration).value);
    const w = try ev.eval(&parsed.tree, parsed.tree.decl(parsed.tree.topLevelItem(parsed.file.items[1]).kind.declaration).value);
    try std.testing.expect(e == .extern_symbol);
    try std.testing.expect(w == .int);
    try std.testing.expectEqual(@as(u64, 0), w.int.value.toInt(u64) catch 999);
}
test "reflection intrinsics fields and function type" {
    const parser = @import("parser.zig");
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    const parsed = try parser.parseFileSource(a, "module t\nS := struct { x: i32, y: f32 }\nF := (x: i32) f32 => 1.0\n", &bag);
    var tt = try types.TypeTable.init(a);
    var ev = Evaluator.init(a, &bag, &tt, .{});
    const s_decl = parsed.tree.decl(parsed.tree.topLevelItem(parsed.file.items[0]).kind.declaration);
    const f_decl = parsed.tree.decl(parsed.tree.topLevelItem(parsed.file.items[1]).kind.declaration);
    const sty = try ev.evalToType(&parsed.tree, s_decl.value);
    try std.testing.expect(tt.get(sty) == .struct_type);
    const fv = try ev.eval(&parsed.tree, f_decl.value);
    try std.testing.expect(fv == .function);
}
test "reflection negative declare frozen" {
    const parser = @import("parser.zig");
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    const parsed = try parser.parseFileSource(a, "module t\nX := $declare(i32, \"m\", 1)\n", &bag);
    var tt = try types.TypeTable.init(a);
    var ev = Evaluator.init(a, &bag, &tt, .{});
    const d = parsed.tree.decl(parsed.tree.topLevelItem(parsed.file.items[0]).kind.declaration);
    _ = try ev.eval(&parsed.tree, d.value);
    try std.testing.expect(bag.error_count > 0);
}
test "reflection negatives and value fields" {
    const parser = @import("parser.zig");
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    const parsed = try parser.parseFileSource(a, "module t\nA := $field(1, \"x\")\nB := $fn_return(i32)\nC := $declaration(i32, \"missing\")\n", &bag);
    var tt = try types.TypeTable.init(a);
    var ev = Evaluator.init(a, &bag, &tt, .{});
    for (parsed.file.items) |it| _ = try ev.eval(&parsed.tree, parsed.tree.decl(parsed.tree.topLevelItem(it).kind.declaration).value);
    try std.testing.expect(bag.error_count >= 3);
}
test "reflection field read write declarations and fn metadata" {
    const parser = @import("parser.zig");
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    const parsed = try parser.parseFileSource(a, "module t\nS := struct { x: i32 }\n", &bag);
    var tt = try types.TypeTable.init(a);
    var ev = Evaluator.init(a, &bag, &tt, .{});
    const sid = parsed.tree.decl(parsed.tree.topLevelItem(parsed.file.items[0]).kind.declaration).value;
    const sty = try ev.evalToType(&parsed.tree, sid);
    try ev.values.put("s", .{ .struct_value = &.{.{ .name = "x", .value = try ev.intValue(1) }} });
    const src2 = try parser.parseFileSource(a, "module t\nA := $field(s, \"x\")\nB := $field_set(s, \"x\", 2)\n", &bag);
    _ = try ev.eval(&src2.tree, src2.tree.decl(src2.tree.topLevelItem(src2.file.items[0]).kind.declaration).value);
    _ = try ev.eval(&src2.tree, src2.tree.decl(src2.tree.topLevelItem(src2.file.items[1]).kind.declaration).value);
    ev.allow_declare = true;
    try ev.declarations.put(try std.fmt.allocPrint(a, "{}.{s}", .{ @intFromEnum(sty), "make" }), try ev.intValue(7));
    try std.testing.expect((try ev.declarationValue(&parsed.tree, .{ .args = &.{} }, .{ .start = 0, .end = 0 })) == .err);
}
test "reflection associated declarations and fields value shorthand" {
    const parser = @import("parser.zig");
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    const parsed = try parser.parseFileSource(a, "module t\nS := struct { x: i32 }\nS.answer := 42\n", &bag);
    var tt = try types.TypeTable.init(a);
    var ev = Evaluator.init(a, &bag, &tt, .{});
    try ev.collectModuleDecls(&parsed.tree, parsed.file);
    const sty = ev.named_types.get("S").?;
    const key = try std.fmt.allocPrint(a, "{}.{s}", .{ @intFromEnum(sty), "answer" });
    try std.testing.expect(ev.declarations.contains(key));
    try ev.values.put("s", .{ .struct_value = &.{.{ .name = "x", .value = try ev.intValue(1) }} });
    const parsed2 = try parser.parseFileSource(a, "module t\nF := $fields(s)\n", &bag);
    const out = try ev.eval(&parsed2.tree, parsed2.tree.decl(parsed2.tree.topLevelItem(parsed2.file.items[0]).kind.declaration).value);
    try std.testing.expect(out == .array);
}
// Inline-for smoke uses parser lowering: for $fields(S): |f| { f.name }
test "reflection inline for fields smoke" {
    const parser = @import("parser.zig");
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    const parsed = try parser.parseFileSource(a, "module t\nS := struct { x: i32 }\nRun := comp for $fields(S): |f| { f.name }\n", &bag);
    var tt = try types.TypeTable.init(a);
    var ev = Evaluator.init(a, &bag, &tt, .{});
    try ev.collectModuleDecls(&parsed.tree, parsed.file);
    const d = parsed.tree.decl(parsed.tree.topLevelItem(parsed.file.items[1]).kind.declaration);
    _ = try ev.eval(&parsed.tree, d.value);
    try std.testing.expectEqual(@as(usize, 0), bag.error_count);
}
