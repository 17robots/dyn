const std = @import("std");
const ModuleGraph = @import("module_graph.zig");
const Symbols = @import("symbols.zig");
const Resolver = @import("resolver.zig");
const Semantic = @import("semantic.zig");
const Diagnostics = @import("diagnostics.zig");

pub const Options = struct {
    max_graph_errors: usize = 100,
    max_scope_errors: usize = 100,
    max_resolve_errors: usize = 100,
    max_semantic_errors: usize = 100,
    std_dir: ?[]const u8 = null,
};

pub const FrontendResult = struct {
    graph: ModuleGraph.Self,
    symbols: Symbols.Self,
    resolver: Resolver.Self,
    semantic: Semantic.Self,
    graph_printed: usize,
    scope_printed: usize,
    resolve_printed: usize,
    semantic_printed: usize,

    pub const Summary = struct {
        graph_errors: usize,
        scope_errors: usize,
        resolve_errors: usize,
        semantic_errors: usize,
        printed_total: usize,
        can_codegen: bool,
    };

    pub fn deinit(self: *FrontendResult) void {
        self.resolver.deinit();
        self.semantic.deinit();
        self.symbols.deinit();
        self.graph.deinit();
    }

    pub fn canCodegen(self: FrontendResult) bool {
        return self.graph.errors.items.len == 0 and self.symbols.errors.items.len == 0 and self.resolver.errors.items.len == 0 and self.semantic.errors.items.len == 0;
    }

    pub fn summary(self: FrontendResult) Summary {
        return .{
            .graph_errors = self.graph.errors.items.len,
            .scope_errors = self.symbols.errors.items.len,
            .resolve_errors = self.resolver.errors.items.len,
            .semantic_errors = self.semantic.errors.items.len,
            .printed_total = self.graph_printed + self.scope_printed + self.resolve_printed + self.semantic_printed,
            .can_codegen = self.canCodegen(),
        };
    }
};

pub fn runFrontend(
    allocator: std.mem.Allocator,
    writer: anytype,
    entry_path: []const u8,
    opts: Options,
) !FrontendResult {
    var graph = try ModuleGraph.Self.buildFromEntryWithOptions(allocator, entry_path, .{ .std_dir = opts.std_dir });
    errdefer graph.deinit();

    var symbols = try Symbols.Self.collectFromGraph(allocator, &graph);
    errdefer symbols.deinit();

    var resolver = Resolver.Self.init(allocator);
    errdefer resolver.deinit();
    try resolver.resolveModuleMemberAccesses(&graph, &symbols);

    var semantic = Semantic.Self.init(allocator);
    errdefer semantic.deinit();
    try semantic.checkGraph(&graph);

    const graph_printed = try Diagnostics.reportGraphErrors(&graph.sm, writer, graph.errors.items, opts.max_graph_errors);
    const scope_printed = try Diagnostics.reportScopeErrors(&graph.sm, writer, symbols.errors.items, opts.max_scope_errors);
    const resolve_printed = try Diagnostics.reportResolveErrors(&graph.sm, writer, resolver.errors.items, opts.max_resolve_errors);
    const semantic_printed = try Diagnostics.reportSemanticErrors(&graph.sm, writer, semantic.errors.items, opts.max_semantic_errors);

    return .{
        .graph = graph,
        .symbols = symbols,
        .resolver = resolver,
        .semantic = semantic,
        .graph_printed = graph_printed,
        .scope_printed = scope_printed,
        .resolve_printed = resolve_printed,
        .semantic_printed = semantic_printed,
    };
}

test "frontend pipeline reports semantic issues" {
    const alloc = std.testing.allocator;
    const dir = "tmp_pipeline_frontend";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_pipeline_frontend/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nM := use \"other\"\nx := M.nope\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_pipeline_frontend/a.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module other\npub ok := 1\n");
    }

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);

    var res = try runFrontend(alloc, w, "tmp_pipeline_frontend/main.dyn", .{});
    defer res.deinit();

    try std.testing.expect(!res.canCodegen());
    try std.testing.expect(res.resolve_printed >= 1);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "no public member 'nope'") != null);
    const sum = res.summary();
    try std.testing.expect(!sum.can_codegen);
    try std.testing.expect(sum.printed_total >= 1);
}

test "frontend pipeline success case" {
    const alloc = std.testing.allocator;
    const dir = "tmp_pipeline_success";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_pipeline_success/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nadd := (x: i32, y: i32) i32 => x + y\nz := add(1, 2)\n");
    }

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);

    var res = try runFrontend(alloc, w, "tmp_pipeline_success/main.dyn", .{});
    defer res.deinit();
    const sum = res.summary();
    try std.testing.expect(sum.can_codegen);
    try std.testing.expectEqual(@as(usize, 0), sum.printed_total);
}

test "frontend pipeline graph failure case" {
    const alloc = std.testing.allocator;
    const dir = "tmp_pipeline_graph_fail";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_pipeline_graph_fail/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nM := use \"missing_mod\"\n");
    }

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);

    var res = try runFrontend(alloc, w, "tmp_pipeline_graph_fail/main.dyn", .{});
    defer res.deinit();
    const sum = res.summary();
    try std.testing.expect(!sum.can_codegen);
    try std.testing.expect(sum.graph_errors >= 1);
}
