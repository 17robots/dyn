const std = @import("std");
const ast = @import("ast.zig");
const source = @import("source.zig");
const diag = @import("diag.zig");
const loader_mod = @import("module_loader.zig");
const parser = @import("parser.zig");

pub const DefId = enum(u32) { _ };
pub const Binding = union(enum) {
    def: DefId,
    builtin_integer: struct { signed: bool, width: u16 },
    module: loader_mod.ModuleId,
};
pub const Def = struct {
    id: DefId,
    name: []const u8,
    module: loader_mod.ModuleId,
    decl: ast.DeclId,
    visibility: ast.Visibility,
};
pub const ModuleInfo = struct {
    defs: std.StringHashMap(DefId),
    associated: std.StringHashMap(DefId),
};
pub const Resolver = struct {
    allocator: std.mem.Allocator,
    diagnostics: *diag.DiagnosticBag,
    loader: *loader_mod.ModuleLoader,
    defs: std.ArrayList(Def),
    modules: std.AutoHashMap(loader_mod.ModuleId, ModuleInfo),
    expr_bindings: std.AutoHashMap(ast.ExprId, Binding),
    locals: std.StringHashMap(DefId),

    pub fn init(allocator: std.mem.Allocator, diagnostics: *diag.DiagnosticBag, loader: *loader_mod.ModuleLoader) Resolver {
        return .{ .allocator = allocator, .diagnostics = diagnostics, .loader = loader, .defs = .empty, .modules = .init(allocator), .expr_bindings = .init(allocator), .locals = .init(allocator) };
    }

    pub fn deinit(self: *Resolver) void {
        for (self.modules.values()) |*m| {
            m.defs.deinit();
            m.associated.deinit();
        }
        self.modules.deinit();
        self.defs.deinit(self.allocator);
        self.expr_bindings.deinit();
        self.locals.deinit();
    }

    pub fn resolveModule(self: *Resolver, module_id: loader_mod.ModuleId) !void {
        try self.collect(module_id);
        try self.resolveBodies(module_id);
    }

    fn collect(self: *Resolver, module_id: loader_mod.ModuleId) !void {
        var info = ModuleInfo{ .defs = .init(self.allocator), .associated = .init(self.allocator) };
        const m = &self.loader.modules.items[@intFromEnum(module_id)];
        for (m.file.items) |item_id| {
            const item = m.tree.topLevelItem(item_id);
            if (item.kind != .declaration) continue;
            const decl_id = item.kind.declaration;
            const decl = m.tree.decl(decl_id);
            switch (decl.target) {
                .name => |n| try self.addDef(module_id, &info, n.name, decl_id, decl.visibility, n.span),
                .destructure => |pats| for (pats) |pid| switch (m.tree.pattern(pid).kind) {
                    .identifier => |id| try self.addDef(module_id, &info, id.name, decl_id, decl.visibility, id.span),
                    else => {},
                },
                else => {},
            }
        }
        for (m.file.items) |item_id| {
            const item = m.tree.topLevelItem(item_id);
            if (item.kind != .declaration) continue;
            const decl_id = item.kind.declaration;
            const decl = m.tree.decl(decl_id);
            switch (decl.target) {
                .associated => |a| {
                    if (!info.defs.contains(a.type_path.parts[0].name)) try self.diagnostics.errorAt("R0006", "associated declaration target is not defined", a.type_path.span, "target type not found");
                    try self.addAssociated(module_id, &info, a.name.name, decl_id, decl.visibility, a.name.span);
                },
                else => {},
            }
        }
        try self.modules.put(module_id, info);
    }

    fn addDef(self: *Resolver, module_id: loader_mod.ModuleId, info: *ModuleInfo, name: []const u8, decl: ast.DeclId, vis: ast.Visibility, span: source.Span) !void {
        if (try integerName(name, span, self.diagnostics)) |b| {
            _ = b;
            try self.diagnostics.errorAt("R0004", "reserved integer type name cannot be shadowed", span, "reserved built-in type name");
            return;
        }
        if (info.defs.contains(name)) {
            try self.diagnostics.errorAt("R0005", "name is already defined in this scope", span, "duplicate declaration");
            return;
        }
        const id: DefId = @enumFromInt(self.defs.items.len);
        try self.defs.append(self.allocator, .{ .id = id, .name = name, .module = module_id, .decl = decl, .visibility = vis });
        try info.defs.put(name, id);
    }

    fn addAssociated(self: *Resolver, module_id: loader_mod.ModuleId, info: *ModuleInfo, name: []const u8, decl: ast.DeclId, vis: ast.Visibility, span: source.Span) !void {
        if (info.associated.contains(name)) {
            try self.diagnostics.errorAt("R0005", "associated name is already defined", span, "duplicate associated declaration");
            return;
        }
        const id: DefId = @enumFromInt(self.defs.items.len);
        try self.defs.append(self.allocator, .{ .id = id, .name = name, .module = module_id, .decl = decl, .visibility = vis });
        try info.associated.put(name, id);
    }

    fn resolveBodies(self: *Resolver, module_id: loader_mod.ModuleId) !void {
        const m = &self.loader.modules.items[@intFromEnum(module_id)];
        for (m.file.items) |item_id| {
            const item = m.tree.topLevelItem(item_id);
            if (item.kind != .declaration) try self.diagnostics.errorAt("R0007", "top-level statements are not allowed", item.span, "top level must contain declarations only");
            if (item.kind == .declaration) {
                const did = item.kind.declaration;
                try self.resolveDecl(module_id, &m.tree, did);
            }
        }
    }

    fn resolveDecl(self: *Resolver, module_id: loader_mod.ModuleId, tree: *const ast.Ast, decl_id: ast.DeclId) anyerror!void {
        const decl = tree.decl(decl_id);
        if (decl.target == .destructure and tree.expr(decl.value).kind == .use) {
            const path = tree.expr(decl.value).kind.use;
            if (try self.loader.loadUse(module_id, path, tree.expr(decl.value).span)) |mid| {
                try self.ensureCollected(mid);
                if (self.modules.get(mid)) |info| {
                    for (decl.target.destructure) |pid| switch (tree.pattern(pid).kind) {
                        .identifier => |name| {
                            if (info.defs.get(name.name)) |def| {
                                const d = self.defs.items[@intFromEnum(def)];
                                if (d.visibility != .public) try self.diagnostics.errorAt("R0011", "declaration is private to its module", name.span, "not public");
                            } else try self.diagnostics.errorAt("R0012", "imported module has no public member with this name", name.span, "member not found");
                        },
                        else => {},
                    };
                }
            }
        }
        try self.resolveExpr(module_id, tree, decl.value);
    }

    fn resolveExpr(self: *Resolver, module_id: loader_mod.ModuleId, tree: *const ast.Ast, id: ast.ExprId) anyerror!void {
        const e = tree.expr(id);
        switch (e.kind) {
            .identifier => |name| {
                if (std.mem.eql(u8, name.name, "top_value")) return;
                if (try integerName(name.name, name.span, self.diagnostics)) |b| {
                    try self.expr_bindings.put(id, b);
                    return;
                }
                if (self.locals.get(name.name)) |def| {
                    try self.expr_bindings.put(id, .{ .def = def });
                    return;
                }
                if (self.modules.get(module_id)) |info| if (info.defs.get(name.name)) |def| {
                    try self.expr_bindings.put(id, .{ .def = def });
                    return;
                };
                try self.diagnostics.errorAt("R0008", "name is not defined in this scope", name.span, "undefined name");
            },
            .use => |path| {
                if (try self.loader.loadUse(module_id, path, e.span)) |mid| {
                    try self.ensureCollected(mid);
                    try self.expr_bindings.put(id, .{ .module = mid });
                }
            },
            .binary => |b| {
                try self.resolveExpr(module_id, tree, b.lhs);
                try self.resolveExpr(module_id, tree, b.rhs);
            },
            .unary => |u| try self.resolveExpr(module_id, tree, u.operand),
            .call => |c| {
                try self.resolveExpr(module_id, tree, c.callee);
                for (c.args) |a| try self.resolveExpr(module_id, tree, a.value);
            },
            .member => |mm| {
                try self.resolveExpr(module_id, tree, mm.object);
                if (self.expr_bindings.get(mm.object)) |b| switch (b) {
                    .module => |mid| {
                        try self.ensureCollected(mid);
                        if (self.modules.get(mid)) |info| {
                            if (info.defs.get(mm.name.name)) |def| {
                                const d = self.defs.items[@intFromEnum(def)];
                                if (d.visibility != .public and mid != module_id) try self.diagnostics.errorAt("R0011", "declaration is private to its module", mm.name.span, "not public");
                                try self.expr_bindings.put(id, .{ .def = def });
                            } else try self.diagnostics.errorAt("R0008", "name is not defined in this scope", mm.name.span, "module member not found");
                        }
                    },
                    else => {},
                };
            },
            .index => |x| {
                try self.resolveExpr(module_id, tree, x.object);
                try self.resolveExpr(module_id, tree, x.index);
            },
            .optional_unwrap, .error_unwrap, .deref, .grouped => |x| try self.resolveExpr(module_id, tree, x),
            .array_literal, .tuple_literal => |items| for (items) |it| try self.resolveExpr(module_id, tree, it),
            .array_type => |at| {
                try self.resolveExpr(module_id, tree, at.len);
                try self.resolveExpr(module_id, tree, at.elem);
            },
            .slice_type => |elem| try self.resolveExpr(module_id, tree, elem),
            .typed_struct_literal => |ts| {
                try self.resolveExpr(module_id, tree, ts.ty);
                for (ts.fields) |f| if (f.value) |v| try self.resolveExpr(module_id, tree, v);
            },
            .if_expr => |i| {
                try self.resolveExpr(module_id, tree, i.condition);
                try self.resolveExpr(module_id, tree, i.then_branch);
                if (i.else_branch) |el| try self.resolveExpr(module_id, tree, el);
            },
            .match_expr => |ma| {
                try self.resolveExpr(module_id, tree, ma.subject);
                for (ma.arms) |arm| {
                    for (arm.captures) |c| try self.addCapture(module_id, c);
                    try self.resolveExpr(module_id, tree, arm.body);
                    for (arm.captures) |c| self.removeCapture(c);
                }
            },
            .for_expr => |f| {
                if (f.head) |h| switch (h) {
                    .while_ => |w| {
                        try self.resolveExpr(module_id, tree, w.condition);
                        if (w.captures) |cs| for (cs.bindings) |c| try self.addCapture(module_id, c);
                    },
                    .iteration => |it| {
                        for (it.iterables) |v| try self.resolveExpr(module_id, tree, v);
                        for (it.captures.bindings) |c| try self.addCapture(module_id, c);
                    },
                };
                try self.resolveExpr(module_id, tree, f.body);
                if (f.head) |h2| switch (h2) {
                    .while_ => |w2| if (w2.captures) |cs| for (cs.bindings) |c| self.removeCapture(c),
                    .iteration => |it2| for (it2.captures.bindings) |c| self.removeCapture(c),
                };
            },
            .function => |f| {
                for (f.params) |param| if (param.name) |n| try self.addCapture(module_id, n);
                try self.resolveExpr(module_id, tree, f.body);
            },
            .block => |stmts| try self.resolveBlock(module_id, tree, stmts),
            else => {},
        }
    }

    fn ensureCollected(self: *Resolver, module_id: loader_mod.ModuleId) anyerror!void {
        if (!self.modules.contains(module_id)) try self.collect(module_id);
    }
    fn resolveBlock(self: *Resolver, module_id: loader_mod.ModuleId, tree: *const ast.Ast, stmts: []ast.StmtId) anyerror!void {
        var locals = std.StringHashMap(void).init(self.allocator);
        defer locals.deinit();
        for (stmts) |sid| {
            const st = tree.stmt(sid);
            switch (st.kind) {
                .declaration => |did| {
                    const d = tree.decl(did);
                    try self.declNamesNoShadow(module_id, &locals, tree, d);
                    try self.resolveExpr(module_id, tree, d.value);
                },
                .assignment => |a| {
                    try self.resolveExpr(module_id, tree, a.lhs);
                    try self.resolveExpr(module_id, tree, a.rhs);
                },
                .return_ => |v| if (v) |x| try self.resolveExpr(module_id, tree, x),
                .break_ => |b| if (b.value) |x| try self.resolveExpr(module_id, tree, x),
                .defer_ => |df| try self.resolveExpr(module_id, tree, df.body),
                .expr => |e2| try self.resolveExpr(module_id, tree, e2),
                else => {},
            }
        }
    }
    fn addCapture(self: *Resolver, module_id: loader_mod.ModuleId, n: ast.Ident) !void {
        if (std.mem.eql(u8, n.name, "_")) return;
        if (self.locals.contains(n.name)) return;
        const id: DefId = @enumFromInt(self.defs.items.len);
        try self.defs.append(self.allocator, .{ .id = id, .name = n.name, .module = module_id, .decl = @enumFromInt(0), .visibility = .private });
        try self.locals.put(n.name, id);
    }
    fn removeCapture(self: *Resolver, n: ast.Ident) void {
        if (std.mem.eql(u8, n.name, "_")) return;
        _ = self.locals.remove(n.name);
    }
    fn declNamesNoShadow(self: *Resolver, module_id: loader_mod.ModuleId, locals: *std.StringHashMap(void), tree: *const ast.Ast, d: *const ast.Declaration) anyerror!void {
        const info = self.modules.get(module_id).?;
        switch (d.target) {
            .name => |n| {
                if (info.defs.contains(n.name) or locals.contains(n.name) or self.locals.contains(n.name)) try self.diagnostics.errorAt("R0010", "declaration shadows an existing name", n.span, "shadowing is not allowed");
                try locals.put(n.name, {});
                const id: DefId = @enumFromInt(self.defs.items.len);
                try self.defs.append(self.allocator, .{ .id = id, .name = n.name, .module = module_id, .decl = @enumFromInt(0), .visibility = .private });
                try self.locals.put(n.name, id);
            },
            .destructure => |pats| for (pats) |pid| switch (tree.pattern(pid).kind) {
                .identifier => |n| {
                    if (info.defs.contains(n.name) or locals.contains(n.name) or self.locals.contains(n.name)) try self.diagnostics.errorAt("R0010", "declaration shadows an existing name", n.span, "shadowing is not allowed");
                    try locals.put(n.name, {});
                    const id: DefId = @enumFromInt(self.defs.items.len);
                    try self.defs.append(self.allocator, .{ .id = id, .name = n.name, .module = module_id, .decl = @enumFromInt(0), .visibility = .private });
                    try self.locals.put(n.name, id);
                },
                else => {},
            },
            else => {},
        }
    }
};
fn integerName(name: []const u8, span: source.Span, diagnostics: *diag.DiagnosticBag) !?Binding {
    if (name.len < 2) return null;
    const c = name[0];
    if (c != 'i' and c != 'u') return null;
    var n: u32 = 0;
    for (name[1..]) |ch| {
        if (ch < '0' or ch > '9') return null;
        n = n * 10 + (ch - '0');
    }
    if (n == 0 or n > 65535) {
        try diagnostics.errorAt("R0009", "integer type width is out of range", span, "valid range is 1..=65535");
        return null;
    }
    return .{ .builtin_integer = .{ .signed = c == 'i', .width = @intCast(n) } };
}

test "resolver collects corpus module declarations" {
    inline for (.{@embedFile("../tests/corpus/examples/other.dyn")}) |src| {
        var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
        defer arena.deinit();
        const a = arena.allocator();
        var bag = diag.DiagnosticBag.init(a, .{});
        const parsed = try parser.parseFileSource(a, src, &bag);
        var loader = loader_mod.ModuleLoader.init(a, &bag, .{ .base_path = "tests/corpus/examples" });
        const mid = try loader.addParsed("main", "<memory>", parsed);
        var r = Resolver.init(a, &bag, &loader);
        try r.collect(mid);
        try std.testing.expectEqual(@as(usize, 0), bag.error_count);
        try std.testing.expect(r.defs.items.len > 0);
    }
}
test "resolver rejects reserved and out-of-range integer names" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    const parsed = try parser.parseFileSource(a, "module bad\nu1 := 1\nx := u70000\n", &bag);
    var loader = loader_mod.ModuleLoader.init(a, &bag, .{});
    const mid = try loader.addParsed("bad", "<bad>", parsed);
    var r = Resolver.init(a, &bag, &loader);
    try r.resolveModule(mid);
    try std.testing.expect(bag.error_count > 0);
}
test "resolver rejects duplicate top-level names" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    const parsed = try parser.parseFileSource(a, "module bad\nx := 1\nx := 2\n", &bag);
    var loader = loader_mod.ModuleLoader.init(a, &bag, .{});
    const mid = try loader.addParsed("bad", "<dup>", parsed);
    var r = Resolver.init(a, &bag, &loader);
    try r.resolveModule(mid);
    try std.testing.expect(bag.error_count > 0);
}
test "module loader reports unknown import" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    const parsed = try parser.parseFileSource(a, "module main\nx := 1\n", &bag);
    var loader = loader_mod.ModuleLoader.init(a, &bag, .{ .base_path = "tests/corpus/examples" });
    const mid = try loader.addParsed("main", "<main>", parsed);
    _ = try loader.loadUse(mid, "does_not_exist", .{ .start = 0, .end = 1 });
    try std.testing.expect(bag.error_count > 0);
}
test "resolver rejects local shadowing" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    const parsed = try parser.parseFileSource(a, "module bad\nx := 1\nf := () { x := 2 }\n", &bag);
    var loader = loader_mod.ModuleLoader.init(a, &bag, .{});
    const mid = try loader.addParsed("bad", "<shadow>", parsed);
    var r = Resolver.init(a, &bag, &loader);
    try r.resolveModule(mid);
    try std.testing.expect(bag.error_count > 0);
}
test "resolver rejects unknown identifier" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    const parsed = try parser.parseFileSource(a, "module bad\nx := y\n", &bag);
    var loader = loader_mod.ModuleLoader.init(a, &bag, .{});
    const mid = try loader.addParsed("bad", "<unknown>", parsed);
    var r = Resolver.init(a, &bag, &loader);
    try r.resolveModule(mid);
    try std.testing.expect(bag.error_count > 0);
}
test "resolver rejects private destructured import" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    var bag = diag.DiagnosticBag.init(a, .{});
    const other = try parser.parseFileSource(a, "module other\nsecret := 1\n", &bag);
    var loader = loader_mod.ModuleLoader.init(a, &bag, .{});
    _ = try loader.addParsed("other", "other", other);
    const main = try parser.parseFileSource(a, "module main\n{ secret } := use \"other\"\n", &bag);
    const mid = try loader.addParsed("main", "main", main);
    var r = Resolver.init(a, &bag, &loader);
    try r.resolveModule(mid);
    try std.testing.expect(bag.error_count > 0);
}
