const std = @import("std");
const Ast = @import("ast.zig");
const Span = @import("token.zig").Span;
const ModuleGraph = @import("module_graph.zig");
const SourceManager = @import("source_manager.zig");

pub const Symbol = struct {
    name: []u8,
    decl_node: Ast.NodeId,
    is_pub: bool,
};

pub const ModuleScope = struct {
    module_index: u32,
    symbols: []Symbol,
    exports: []u32,
};

pub const ScopeError = struct {
    module_index: u32,
    file_id: SourceManager.FileId,
    span: Span,
    message: []const u8,
};

pub const Self = @This();

allocator: std.mem.Allocator,
scopes: std.ArrayListUnmanaged(ModuleScope) = .empty,
errors: std.ArrayListUnmanaged(ScopeError) = .empty,

pub fn init(allocator: std.mem.Allocator) Self {
    return .{ .allocator = allocator };
}

pub fn deinit(self: *Self) void {
    for (self.scopes.items) |s| {
        for (s.symbols) |sym| self.allocator.free(sym.name);
        self.allocator.free(s.symbols);
        self.allocator.free(s.exports);
    }
    self.scopes.deinit(self.allocator);
    self.errors.deinit(self.allocator);
}

pub fn collectFromGraph(allocator: std.mem.Allocator, graph: *ModuleGraph.Self) !Self {
    var out = Self.init(allocator);
    errdefer out.deinit();

    var m: u32 = 0;
    while (m < graph.modules.items.len) : (m += 1) {
        try out.collectModule(graph, m);
    }

    return out;
}

fn collectModule(self: *Self, graph: *ModuleGraph.Self, module_index: u32) !void {
    const mod = graph.modules.items[module_index];

    var symbols_tmp: std.ArrayListUnmanaged(Symbol) = .empty;
    defer symbols_tmp.deinit(self.allocator);

    var exports_tmp: std.ArrayListUnmanaged(u32) = .empty;
    defer exports_tmp.deinit(self.allocator);

    var by_name: std.StringHashMapUnmanaged(u32) = .empty;
    defer by_name.deinit(self.allocator);

    var mf: u32 = 0;
    while (mf < mod.file_count) : (mf += 1) {
        const file_index = graph.module_file_indices.items[mod.file_start + mf];
        const f = graph.files.items[file_index];

        if (f.root) |root_id| {
            const root = f.nodes[root_id];
            if (root.tag != .block) continue;

            const start = root.data.block.item_start;
            const count = root.data.block.item_count;

            var i: u32 = 0;
            while (i < count) : (i += 1) {
                const n_id = f.list_items[start + i];
                const n = f.nodes[n_id];
                if (n.tag != .decl) continue;

                var name_i: u32 = 0;
                while (name_i < n.data.decl.name_count) : (name_i += 1) {
                    const ident_id = f.decl_name_items[n.data.decl.name_start + name_i];
                    const ident = f.nodes[ident_id];
                    if (ident.tag != .identifier) continue;

                    try graph.sm.ensureTextLoaded(f.file_id);
                    const name_slice = graph.sm.spanSlice(f.file_id, ident.span) catch continue;
                    const name = try self.allocator.dupe(u8, name_slice);
                    errdefer self.allocator.free(name);

                    if (by_name.get(name_slice)) |_| {
                        self.allocator.free(name);
                        try self.errors.append(self.allocator, .{
                            .module_index = module_index,
                            .file_id = f.file_id,
                            .span = ident.span,
                            .message = "duplicate symbol in module scope",
                        });
                        continue;
                    }

                    const sym_idx: u32 = @intCast(symbols_tmp.items.len);
                    try symbols_tmp.append(self.allocator, .{
                        .name = name,
                        .decl_node = n_id,
                        .is_pub = n.data.decl.is_pub,
                    });
                    try by_name.put(self.allocator, symbols_tmp.items[sym_idx].name, sym_idx);
                    if (n.data.decl.is_pub) try exports_tmp.append(self.allocator, sym_idx);
                }
            }
        }
    }

    try self.scopes.append(self.allocator, .{
        .module_index = module_index,
        .symbols = try symbols_tmp.toOwnedSlice(self.allocator),
        .exports = try exports_tmp.toOwnedSlice(self.allocator),
    });
}

pub fn scopeForModule(self: *const Self, module_index: u32) ?ModuleScope {
    for (self.scopes.items) |s| {
        if (s.module_index == module_index) return s;
    }
    return null;
}

test "collects symbols and exports" {
    const alloc = std.testing.allocator;
    const dir = "tmp_symbols_ok";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_symbols_ok/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "pub add := (x: i32) i32 => x\n" ++
                "hidden := 1\n" ++
                "x, y: i32 = 0\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_symbols_ok/main.dyn");
    defer g.deinit();

    var col = try Self.collectFromGraph(alloc, &g);
    defer col.deinit();

    try std.testing.expectEqual(@as(usize, 0), col.errors.items.len);
    const scope = col.scopeForModule(0).?;
    try std.testing.expectEqual(@as(usize, 4), scope.symbols.len);
    try std.testing.expectEqual(@as(usize, 1), scope.exports.len);
}

test "reports duplicate symbols" {
    const alloc = std.testing.allocator;
    const dir = "tmp_symbols_dup";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_symbols_dup/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "a := 1\n" ++
                "a := 2\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_symbols_dup/main.dyn");
    defer g.deinit();

    var col = try Self.collectFromGraph(alloc, &g);
    defer col.deinit();

    try std.testing.expect(col.errors.items.len >= 1);
}
