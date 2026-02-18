const std = @import("std");
const Ast = @import("ast.zig");
const ModuleGraph = @import("module_graph.zig");
const Symbols = @import("symbols.zig");

pub const ResolveError = struct {
    file_id: @import("source_manager.zig").FileId,
    span: @import("token.zig").Span,
    message: []u8,
};

pub const Self = @This();

allocator: std.mem.Allocator,
errors: std.ArrayListUnmanaged(ResolveError) = .empty,

pub fn init(allocator: std.mem.Allocator) Self {
    return .{ .allocator = allocator };
}

pub fn deinit(self: *Self) void {
    for (self.errors.items) |e| self.allocator.free(e.message);
    self.errors.deinit(self.allocator);
}

pub fn resolveModuleMemberAccesses(self: *Self, graph: *ModuleGraph.Self, symbols: *const Symbols.Self) !void {
    var fi: u32 = 0;
    while (fi < graph.files.items.len) : (fi += 1) {
        try self.resolveFile(graph, symbols, fi);
    }
}

fn resolveFile(self: *Self, graph: *ModuleGraph.Self, symbols: *const Symbols.Self, file_index: u32) !void {
    const f = graph.files.items[file_index];
    const root = f.root orelse return;

    var alias_to_module: std.StringHashMapUnmanaged(u32) = .empty;
    defer alias_to_module.deinit(self.allocator);
    defer {
        var it = alias_to_module.keyIterator();
        while (it.next()) |k| self.allocator.free(k.*);
    }

    try self.collectUseAliases(graph, f, root, &alias_to_module);
    try self.walkNode(graph, symbols, f, root, &alias_to_module);
}

fn collectUseAliases(
    self: *Self,
    graph: *ModuleGraph.Self,
    f: ModuleGraph.FileUnit,
    root: Ast.NodeId,
    alias_to_module: *std.StringHashMapUnmanaged(u32),
) !void {
    const n = f.nodes[root];
    if (n.tag != .block) return;

    const start = n.data.block.item_start;
    const count = n.data.block.item_count;
    var i: u32 = 0;
    while (i < count) : (i += 1) {
        const item_id = f.list_items[start + i];
        const item = f.nodes[item_id];
        if (item.tag != .decl or !item.data.decl.has_init) continue;

        const init_n = f.nodes[item.data.decl.init_node];
        if (init_n.tag != .use_expr) continue;

        const to_module = self.findEdgeTargetForUse(graph, f.file_id, init_n.data.use_expr.path_span) orelse continue;
        var j: u32 = 0;
        while (j < item.data.decl.name_count) : (j += 1) {
            const ident_id = f.decl_name_items[item.data.decl.name_start + j];
            const ident = f.nodes[ident_id];
            if (ident.tag != .identifier) continue;

            try graph.sm.ensureTextLoaded(f.file_id);
            const name = graph.sm.spanSlice(f.file_id, ident.span) catch continue;
            if (alias_to_module.get(name) == null) {
                const copy = try self.allocator.dupe(u8, name);
                errdefer self.allocator.free(copy);
                try alias_to_module.put(self.allocator, copy, to_module);
            }
        }
    }
}

fn findEdgeTargetForUse(self: *Self, graph: *ModuleGraph.Self, file_id: @import("source_manager.zig").FileId, span: @import("token.zig").Span) ?u32 {
    _ = self;
    for (graph.edges.items) |e| {
        if (e.file_id == file_id and e.span.start == span.start and e.span.end == span.end) return e.to_module;
    }
    return null;
}

fn walkNode(
    self: *Self,
    graph: *ModuleGraph.Self,
    symbols: *const Symbols.Self,
    f: ModuleGraph.FileUnit,
    id: Ast.NodeId,
    alias_to_module: *std.StringHashMapUnmanaged(u32),
) !void {
    const n = f.nodes[id];
    switch (n.tag) {
        .field => {
            const obj = f.nodes[n.data.field.object];
            if (obj.tag == .identifier) {
                try graph.sm.ensureTextLoaded(f.file_id);
                const alias = graph.sm.spanSlice(f.file_id, obj.span) catch "";
                if (alias_to_module.get(alias)) |target_mod| {
                    const field_name = graph.sm.spanSlice(f.file_id, n.data.field.field_span) catch "";
                    const pub_state = exportState(symbols, target_mod, field_name);
                    if (pub_state != .public) {
                        const target_name = graph.modules.items[target_mod].name;
                        const avail = exportListHint(self.allocator, symbols, target_mod) catch "";
                        defer if (avail.len > 0) self.allocator.free(avail);

                        const msg = switch (pub_state) {
                            .private_only => if (avail.len > 0)
                                try std.fmt.allocPrint(self.allocator, "module '{s}' member '{s}' exists but is not public. available exports: {s}", .{ target_name, field_name, avail })
                            else
                                try std.fmt.allocPrint(self.allocator, "module '{s}' member '{s}' exists but is not public", .{ target_name, field_name }),
                            .missing => if (bestExportSuggestion(self.allocator, symbols, target_mod, field_name)) |hint|
                                if (avail.len > 0)
                                    try std.fmt.allocPrint(self.allocator, "module '{s}' has no public member '{s}'. did you mean '{s}'? available exports: {s}", .{ target_name, field_name, hint, avail })
                                else
                                    try std.fmt.allocPrint(self.allocator, "module '{s}' has no public member '{s}'. did you mean '{s}'?", .{ target_name, field_name, hint })
                            else if (avail.len > 0)
                                try std.fmt.allocPrint(self.allocator, "module '{s}' has no public member '{s}'. available exports: {s}", .{ target_name, field_name, avail })
                            else
                                try std.fmt.allocPrint(self.allocator, "module '{s}' has no public member '{s}'", .{ target_name, field_name }),
                            .public => unreachable,
                        };
                        try self.errors.append(self.allocator, .{
                            .file_id = f.file_id,
                            .span = n.data.field.field_span,
                            .message = msg,
                        });
                    }
                }
            }
            try self.walkNode(graph, symbols, f, n.data.field.object, alias_to_module);
        },
        .unary => try self.walkNode(graph, symbols, f, n.data.unary.rhs, alias_to_module),
        .binary => {
            try self.walkNode(graph, symbols, f, n.data.binary.lhs, alias_to_module);
            try self.walkNode(graph, symbols, f, n.data.binary.rhs, alias_to_module);
        },
        .assign => {
            try self.walkNode(graph, symbols, f, n.data.assign.lhs, alias_to_module);
            try self.walkNode(graph, symbols, f, n.data.assign.rhs, alias_to_module);
        },
        .call => {
            try self.walkNode(graph, symbols, f, n.data.call.callee, alias_to_module);
            var i: u32 = 0;
            while (i < n.data.call.arg_count) : (i += 1) {
                const arg = f.list_items[n.data.call.arg_start + i];
                try self.walkNode(graph, symbols, f, arg, alias_to_module);
            }
        },
        .index => {
            try self.walkNode(graph, symbols, f, n.data.index.object, alias_to_module);
            try self.walkNode(graph, symbols, f, n.data.index.index, alias_to_module);
        },
        .slice => {
            try self.walkNode(graph, symbols, f, n.data.slice.object, alias_to_module);
            if (n.data.slice.has_start) try self.walkNode(graph, symbols, f, n.data.slice.start, alias_to_module);
            if (n.data.slice.has_end) try self.walkNode(graph, symbols, f, n.data.slice.end, alias_to_module);
        },
        .if_expr => {
            try self.walkNode(graph, symbols, f, n.data.if_expr.cond, alias_to_module);
            try self.walkNode(graph, symbols, f, n.data.if_expr.then_expr, alias_to_module);
            if (n.data.if_expr.has_else) try self.walkNode(graph, symbols, f, n.data.if_expr.else_expr, alias_to_module);
        },
        .match_expr => {
            try self.walkNode(graph, symbols, f, n.data.match_expr.subject, alias_to_module);
            var i: u32 = 0;
            while (i < n.data.match_expr.arm_count) : (i += 1) {
                const arm = f.match_arms[n.data.match_expr.arm_start + i];
                if (arm.pat_start != Ast.NullNode) try self.walkNode(graph, symbols, f, arm.pat_start, alias_to_module);
                if (arm.pat_end != Ast.NullNode) try self.walkNode(graph, symbols, f, arm.pat_end, alias_to_module);
                if (arm.has_pat_payload) try self.walkNode(graph, symbols, f, arm.pat_payload, alias_to_module);
                try self.walkNode(graph, symbols, f, arm.body, alias_to_module);
            }
        },
        .block => {
            const b = n.data.block;
            var i: u32 = 0;
            while (i < b.item_count) : (i += 1) {
                try self.walkNode(graph, symbols, f, f.list_items[b.item_start + i], alias_to_module);
            }
        },
        .struct_expr, .enum_expr => {
            const b = n.data.aggregate;
            var i: u32 = 0;
            while (i < b.item_count) : (i += 1) {
                try self.walkNode(graph, symbols, f, f.list_items[b.item_start + i], alias_to_module);
            }
        },
        .decl => {
            if (n.data.decl.has_init) try self.walkNode(graph, symbols, f, n.data.decl.init_node, alias_to_module);
            if (n.data.decl.has_type) try self.walkNode(graph, symbols, f, n.data.decl.type_node, alias_to_module);
        },
        .fn_expr => {
            if (n.data.fn_expr.has_ret) try self.walkNode(graph, symbols, f, n.data.fn_expr.ret_node, alias_to_module);
            try self.walkNode(graph, symbols, f, n.data.fn_expr.body, alias_to_module);
        },
        .defer_stmt => try self.walkNode(graph, symbols, f, n.data.defer_stmt.value, alias_to_module),
        .for_stmt => {
            if (!n.data.for_stmt.is_infinite and n.data.for_stmt.cond != Ast.NullNode) try self.walkNode(graph, symbols, f, n.data.for_stmt.cond, alias_to_module);
            try self.walkNode(graph, symbols, f, n.data.for_stmt.body, alias_to_module);
        },
        .break_stmt => if (n.data.break_stmt.has_value) try self.walkNode(graph, symbols, f, n.data.break_stmt.value, alias_to_module),
        .labeled_block => try self.walkNode(graph, symbols, f, n.data.labeled_block.body, alias_to_module),
        .unwrap_optional, .unwrap_error, .deref, .address_of, .inline_expr, .comp_expr => try self.walkNode(graph, symbols, f, n.data.one.child, alias_to_module),
        .ptr_type => try self.walkNode(graph, symbols, f, n.data.ptr_type.child, alias_to_module),
        .slice_type => try self.walkNode(graph, symbols, f, n.data.one.child, alias_to_module),
        .array_type => {
            try self.walkNode(graph, symbols, f, n.data.array_type.len, alias_to_module);
            try self.walkNode(graph, symbols, f, n.data.array_type.child, alias_to_module);
        },
        else => {},
    }
}

fn isExported(symbols: *const Symbols.Self, module_index: u32, name: []const u8) bool {
    const scope = symbols.scopeForModule(module_index) orelse return false;
    for (scope.exports) |sym_idx| {
        const sym = scope.symbols[sym_idx];
        if (std.mem.eql(u8, sym.name, name)) return true;
    }
    return false;
}

const ExportState = enum { public, private_only, missing };

fn exportState(symbols: *const Symbols.Self, module_index: u32, name: []const u8) ExportState {
    const scope = symbols.scopeForModule(module_index) orelse return .missing;

    var has_any = false;
    var has_pub = false;
    for (scope.symbols) |sym| {
        if (std.mem.eql(u8, sym.name, name)) {
            has_any = true;
            if (sym.is_pub) has_pub = true;
        }
    }
    if (has_pub) return .public;
    if (has_any) return .private_only;
    return .missing;
}

fn exportListHint(allocator: std.mem.Allocator, symbols: *const Symbols.Self, module_index: u32) ![]u8 {
    const scope = symbols.scopeForModule(module_index) orelse return try allocator.dupe(u8, "(none)");
    if (scope.exports.len == 0) return try allocator.dupe(u8, "(none)");

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    const max_items: usize = 5;
    var i: usize = 0;
    while (i < scope.exports.len and i < max_items) : (i += 1) {
        const sym = scope.symbols[scope.exports[i]];
        if (i != 0) try out.appendSlice(allocator, ", ");
        try out.appendSlice(allocator, sym.name);
    }
    if (scope.exports.len > max_items) try out.appendSlice(allocator, ", ...");
    return try out.toOwnedSlice(allocator);
}

fn bestExportSuggestion(allocator: std.mem.Allocator, symbols: *const Symbols.Self, module_index: u32, wanted: []const u8) ?[]u8 {
    _ = allocator;
    const scope = symbols.scopeForModule(module_index) orelse return null;
    var best_dist: usize = std.math.maxInt(usize);
    var best_name: ?[]u8 = null;
    for (scope.exports) |sym_idx| {
        const sym = scope.symbols[sym_idx];
        const d = editDistanceBounded(sym.name, wanted, 3);
        if (d < best_dist) {
            best_dist = d;
            best_name = sym.name;
        }
    }
    if (best_name == null) return null;
    if (best_dist > 2) return null;
    return best_name;
}

fn editDistanceBounded(a: []const u8, b: []const u8, cap: usize) usize {
    const alen = a.len;
    const blen = b.len;
    if (alen == 0) return blen;
    if (blen == 0) return alen;
    if (alen > blen + cap or blen > alen + cap) return cap + 1;

    var prev: [128]usize = undefined;
    var curr: [128]usize = undefined;
    if (blen >= prev.len) return cap + 1;

    var j: usize = 0;
    while (j <= blen) : (j += 1) prev[j] = j;

    var i: usize = 1;
    while (i <= alen) : (i += 1) {
        curr[0] = i;
        var row_min = curr[0];
        j = 1;
        while (j <= blen) : (j += 1) {
            const cost: usize = if (a[i - 1] == b[j - 1]) 0 else 1;
            const del = prev[j] + 1;
            const ins = curr[j - 1] + 1;
            const sub = prev[j - 1] + cost;
            var v = del;
            if (ins < v) v = ins;
            if (sub < v) v = sub;
            curr[j] = v;
            if (v < row_min) row_min = v;
        }
        if (row_min > cap) return cap + 1;
        j = 0;
        while (j <= blen) : (j += 1) prev[j] = curr[j];
    }
    return prev[blen];
}

test "resolves imported public member access" {
    const alloc = std.testing.allocator;
    const dir = "tmp_resolve_ok";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_resolve_ok/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nM := use \"other\"\nval := M.ok\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_resolve_ok/a.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module other\npub ok := 1\n");
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_resolve_ok/main.dyn");
    defer g.deinit();
    var syms = try Symbols.Self.collectFromGraph(alloc, &g);
    defer syms.deinit();

    var r = Self.init(alloc);
    defer r.deinit();
    try r.resolveModuleMemberAccesses(&g, &syms);
    try std.testing.expectEqual(@as(usize, 0), r.errors.items.len);
}

test "errors on non-public or missing imported member" {
    const alloc = std.testing.allocator;
    const dir = "tmp_resolve_bad";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_resolve_bad/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nM := use \"other\"\na := M.hidden\nb := M.oky\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_resolve_bad/a.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module other\nhidden := 1\npub ok := 2\n");
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_resolve_bad/main.dyn");
    defer g.deinit();
    var syms = try Symbols.Self.collectFromGraph(alloc, &g);
    defer syms.deinit();

    var r = Self.init(alloc);
    defer r.deinit();
    try r.resolveModuleMemberAccesses(&g, &syms);
    try std.testing.expect(r.errors.items.len >= 2);

    var saw_private = false;
    var saw_suggest = false;
    var saw_exports_list = false;
    for (r.errors.items) |e| {
        if (std.mem.indexOf(u8, e.message, "exists but is not public") != null) saw_private = true;
        if (std.mem.indexOf(u8, e.message, "did you mean 'ok'") != null) saw_suggest = true;
        if (std.mem.indexOf(u8, e.message, "available exports:") != null) saw_exports_list = true;
    }
    try std.testing.expect(saw_private);
    try std.testing.expect(saw_suggest);
    try std.testing.expect(saw_exports_list);
}
