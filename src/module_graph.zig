const std = @import("std");
const Ast = @import("ast.zig");
const Tok = @import("token.zig").Tok;
const Span = @import("token.zig").Span;
const Parser = @import("parser.zig");
const Lexer = @import("lexer2.zig");
const SourceManager = @import("source_manager.zig");

pub const FileUnit = struct {
    file_id: SourceManager.FileId,
    path: []u8,
    dir_path: []u8,
    module_name: []u8,
    root: ?Ast.NodeId,
    nodes: []Ast.Node,
    list_items: []Ast.NodeId,
    decl_name_items: []Ast.NodeId,
    param_name_items: []Ast.NodeId,
    match_arms: []Ast.MatchArm,
};

pub const Module = struct {
    name: []u8,
    dir_path: []u8,
    file_start: u32,
    file_count: u32,
};

pub const ImportEdge = struct {
    from_module: u32,
    to_module: ?u32,
    raw_path: []u8,
    span: Span,
    file_id: SourceManager.FileId,
};

pub const GraphError = struct {
    file_id: SourceManager.FileId,
    span: Span,
    message: []const u8,
};

pub const Self = @This();

pub const BuildOptions = struct {
    std_dir: ?[]const u8 = null,
};

allocator: std.mem.Allocator,
sm: SourceManager,
files: std.ArrayListUnmanaged(FileUnit) = .empty,
modules: std.ArrayListUnmanaged(Module) = .empty,
module_file_indices: std.ArrayListUnmanaged(u32) = .empty,
edges: std.ArrayListUnmanaged(ImportEdge) = .empty,
errors: std.ArrayListUnmanaged(GraphError) = .empty,

path_to_file: std.StringHashMapUnmanaged(u32) = .empty,
module_key_to_module: std.StringHashMapUnmanaged(u32) = .empty,
file_to_module: std.AutoHashMapUnmanaged(u32, u32) = .empty,
std_dir_abs: ?[]u8 = null,

pub fn init(allocator: std.mem.Allocator) Self {
    return .{ .allocator = allocator, .sm = SourceManager.init(allocator) };
}

pub fn deinit(self: *Self) void {
    self.sm.deinit();

    for (self.files.items) |f| {
        self.allocator.free(f.path);
        self.allocator.free(f.dir_path);
        self.allocator.free(f.module_name);
        self.allocator.free(f.nodes);
        self.allocator.free(f.list_items);
        self.allocator.free(f.decl_name_items);
        self.allocator.free(f.param_name_items);
        self.allocator.free(f.match_arms);
    }
    for (self.modules.items) |m| {
        self.allocator.free(m.name);
        self.allocator.free(m.dir_path);
    }
    for (self.edges.items) |e| self.allocator.free(e.raw_path);

    self.files.deinit(self.allocator);
    self.modules.deinit(self.allocator);
    self.module_file_indices.deinit(self.allocator);
    self.edges.deinit(self.allocator);
    self.errors.deinit(self.allocator);
    self.path_to_file.deinit(self.allocator);
    var it = self.module_key_to_module.keyIterator();
    while (it.next()) |k| self.allocator.free(k.*);
    self.module_key_to_module.deinit(self.allocator);
    self.file_to_module.deinit(self.allocator);
    if (self.std_dir_abs) |p| self.allocator.free(p);
}

pub fn buildFromEntry(allocator: std.mem.Allocator, entry_path: []const u8) !Self {
    return buildFromEntryWithOptions(allocator, entry_path, .{});
}

pub fn buildFromEntryWithOptions(allocator: std.mem.Allocator, entry_path: []const u8, opts: BuildOptions) !Self {
    var g = Self.init(allocator);
    errdefer g.deinit();

    if (opts.std_dir) |std_dir| {
        const std_rel = try std.fs.path.resolve(allocator, &.{std_dir});
        defer allocator.free(std_rel);
        g.std_dir_abs = try std.fs.cwd().realpathAlloc(allocator, std_rel);
    }

    const rel = try std.fs.path.resolve(allocator, &.{entry_path});
    defer allocator.free(rel);
    const abs = try std.fs.cwd().realpathAlloc(allocator, rel);
    defer allocator.free(abs);

    const entry_file = try g.processFile(abs);
    const entry_mod = g.file_to_module.get(entry_file) orelse unreachable;

    const entry_dir = g.files.items[entry_file].dir_path;
    try g.loadModuleFilesInDirectory(entry_dir);

    try g.collectImportsForModule(entry_mod);
    try g.detectImportCycles();
    return g;
}

fn processFile(self: *Self, abs_path: []const u8) anyerror!u32 {
    if (self.path_to_file.get(abs_path)) |idx| return idx;

    const own_path = try self.allocator.dupe(u8, abs_path);
    errdefer self.allocator.free(own_path);

    const dir = std.fs.path.dirname(own_path) orelse ".";
    const own_dir = try self.allocator.dupe(u8, dir);
    errdefer self.allocator.free(own_dir);

    const file_id = try self.sm.addFileFromDisk(own_path, true);
    const src = self.sm.fileText(file_id).?;
    const toks = try lexAll(self.allocator, src);
    defer self.allocator.free(toks);

    var p = Parser.init(self.allocator, toks);
    defer p.deinit();

    const root = try p.parseFile();
    const nodes = try self.allocator.dupe(Ast.Node, p.nodes.items);
    errdefer self.allocator.free(nodes);
    const list_items = try self.allocator.dupe(Ast.NodeId, p.list_items.items);
    errdefer self.allocator.free(list_items);
    const decl_name_items = try self.allocator.dupe(Ast.NodeId, p.decl_name_items.items);
    errdefer self.allocator.free(decl_name_items);
    const param_name_items = try self.allocator.dupe(Ast.NodeId, p.param_name_items.items);
    errdefer self.allocator.free(param_name_items);
    const match_arms = try self.allocator.dupe(Ast.MatchArm, p.match_arms.items);
    errdefer self.allocator.free(match_arms);

    for (p.errors.items) |e| {
        try self.errors.append(self.allocator, .{ .file_id = file_id, .span = e.span, .message = e.message });
    }

    const module_name = if (root) |r| try self.extractModuleName(file_id, &p, r) else try self.allocator.dupe(u8, "");
    errdefer self.allocator.free(module_name);

    const file_idx: u32 = @intCast(self.files.items.len);
    try self.files.append(self.allocator, .{
        .file_id = file_id,
        .path = own_path,
        .dir_path = own_dir,
        .module_name = module_name,
        .root = root,
        .nodes = nodes,
        .list_items = list_items,
        .decl_name_items = decl_name_items,
        .param_name_items = param_name_items,
        .match_arms = match_arms,
    });
    try self.path_to_file.put(self.allocator, own_path, file_idx);

    const mod_idx = try self.ensureModuleForFile(file_idx);
    try self.file_to_module.put(self.allocator, file_idx, mod_idx);
    return file_idx;
}

fn ensureModuleForFile(self: *Self, file_idx: u32) !u32 {
    const f = self.files.items[file_idx];
    const key = try std.mem.concat(self.allocator, u8, &.{ f.dir_path, "\x1f", f.module_name });
    defer self.allocator.free(key);

    if (self.module_key_to_module.get(key)) |m| {
        try self.module_file_indices.append(self.allocator, file_idx);
        self.modules.items[m].file_count += 1;
        return m;
    }

    const own_name = try self.allocator.dupe(u8, f.module_name);
    errdefer self.allocator.free(own_name);
    const own_dir = try self.allocator.dupe(u8, f.dir_path);
    errdefer self.allocator.free(own_dir);

    const start: u32 = @intCast(self.module_file_indices.items.len);
    try self.module_file_indices.append(self.allocator, file_idx);
    const mod_idx: u32 = @intCast(self.modules.items.len);
    try self.modules.append(self.allocator, .{
        .name = own_name,
        .dir_path = own_dir,
        .file_start = start,
        .file_count = 1,
    });

    const key_copy = try std.mem.concat(self.allocator, u8, &.{ own_dir, "\x1f", own_name });
    try self.module_key_to_module.put(self.allocator, key_copy, mod_idx);
    return mod_idx;
}

fn collectImportsForModule(self: *Self, module_index: u32) anyerror!void {
    const m = self.modules.items[module_index];
    var i: u32 = 0;
    while (i < m.file_count) : (i += 1) {
        const file_idx = self.module_file_indices.items[m.file_start + i];
        try self.collectImportsForFile(module_index, file_idx);
    }
}

fn collectImportsForFile(self: *Self, source_mod: u32, file_idx: u32) anyerror!void {
    const f = self.files.items[file_idx];
    const root = f.root orelse return;
    const root_node = f.nodes[root];
    if (root_node.tag != .block) return;

    const start = root_node.data.block.item_start;
    const count = root_node.data.block.item_count;
    var i: u32 = 0;
    while (i < count) : (i += 1) {
        const n_id = f.list_items[start + i];
        const n = f.nodes[n_id];

        var use_node_id: ?Ast.NodeId = null;
        if (n.tag == .use_expr) use_node_id = n_id else if (n.tag == .decl and n.data.decl.has_init) {
            const init_n = f.nodes[n.data.decl.init_node];
            if (init_n.tag == .use_expr) use_node_id = n.data.decl.init_node;
        }

        if (use_node_id) |u_id| {
            const u = f.nodes[u_id];
            const raw = try self.extractUsePath(f.file_id, u.data.use_expr.path_span);

            var target_opt: ?UseTarget = self.resolveUseTarget(f.dir_path, raw) catch null;
            if (target_opt == null) {
                target_opt = try self.tryResolveStdUseTarget(raw);
            }
            if (target_opt == null) {
                try self.errors.append(self.allocator, .{ .file_id = f.file_id, .span = u.data.use_expr.path_span, .message = "unable to resolve import path" });
                try self.edges.append(self.allocator, .{ .from_module = source_mod, .to_module = null, .raw_path = raw, .span = u.data.use_expr.path_span, .file_id = f.file_id });
                continue;
            }
            const target = target_opt.?;
            defer self.allocator.free(target.dir);
            defer self.allocator.free(target.module_name);

            try self.loadModuleFilesInDirectory(target.dir);
            var mod_idx = self.findModuleByDirAndName(target.dir, target.module_name);
            if (mod_idx == null) {
                if (try self.tryResolveStdUseTarget(raw)) |std_target| {
                    defer self.allocator.free(std_target.dir);
                    defer self.allocator.free(std_target.module_name);
                    try self.loadModuleFilesInDirectory(std_target.dir);
                    mod_idx = self.findModuleByDirAndName(std_target.dir, std_target.module_name);
                }
            }
            if (mod_idx == null) {
                try self.errors.append(self.allocator, .{ .file_id = f.file_id, .span = u.data.use_expr.path_span, .message = "import module not found in target directory" });
                try self.edges.append(self.allocator, .{ .from_module = source_mod, .to_module = null, .raw_path = raw, .span = u.data.use_expr.path_span, .file_id = f.file_id });
                continue;
            }

            try self.edges.append(self.allocator, .{
                .from_module = source_mod,
                .to_module = mod_idx,
                .raw_path = raw,
                .span = u.data.use_expr.path_span,
                .file_id = f.file_id,
            });

            try self.collectImportsForModule(mod_idx.?);
        }
    }
}

fn loadModuleFilesInDirectory(self: *Self, abs_dir: []const u8) !void {
    var dir = try std.fs.openDirAbsolute(abs_dir, .{ .iterate = true });
    defer dir.close();

    var names = std.ArrayList([]u8).empty;
    defer {
        for (names.items) |n| self.allocator.free(n);
        names.deinit(self.allocator);
    }

    var it = dir.iterate();
    while (try it.next()) |ent| {
        if (ent.kind != .file) continue;
        if (!std.mem.endsWith(u8, ent.name, ".dyn")) continue;
        try names.append(self.allocator, try self.allocator.dupe(u8, ent.name));
    }

    std.mem.sort([]u8, names.items, {}, struct {
        fn lessThan(_: void, a: []u8, b: []u8) bool {
            return std.mem.lessThan(u8, a, b);
        }
    }.lessThan);

    for (names.items) |name| {
        const abs = try std.fs.path.resolve(self.allocator, &.{ abs_dir, name });
        defer self.allocator.free(abs);
        _ = try self.processFile(abs);
    }
}

const UseTarget = struct { dir: []u8, module_name: []u8 };

fn resolveUseTarget(self: *Self, from_dir: []const u8, raw_import: []const u8) !UseTarget {
    const slash_idx = std.mem.lastIndexOfScalar(u8, raw_import, '/');
    const rel_dir = if (slash_idx) |idx| raw_import[0..idx] else "";
    const mod_name = if (slash_idx) |idx| raw_import[idx + 1 ..] else raw_import;

    const dir_rel = if (rel_dir.len == 0)
        try self.allocator.dupe(u8, from_dir)
    else
        try std.fs.path.resolve(self.allocator, &.{ from_dir, rel_dir });
    defer self.allocator.free(dir_rel);

    const dir_abs = try std.fs.cwd().realpathAlloc(self.allocator, dir_rel);
    errdefer self.allocator.free(dir_abs);

    return .{ .dir = dir_abs, .module_name = try self.allocator.dupe(u8, mod_name) };
}

fn tryResolveStdUseTarget(self: *Self, raw_import: []const u8) !?UseTarget {
    const std_root = self.std_dir_abs orelse return null;
    if (!std.mem.startsWith(u8, raw_import, "std/")) return null;
    const rest = raw_import[4..];
    if (rest.len == 0) return null;

    const slash_idx = std.mem.lastIndexOfScalar(u8, rest, '/');
    const rel_dir = if (slash_idx) |idx| rest[0..idx] else "";
    const mod_name = if (slash_idx) |idx| rest[idx + 1 ..] else rest;

    const dir_rel = if (rel_dir.len == 0)
        try self.allocator.dupe(u8, std_root)
    else
        try std.fs.path.resolve(self.allocator, &.{ std_root, rel_dir });
    defer self.allocator.free(dir_rel);

    const dir_abs = std.fs.cwd().realpathAlloc(self.allocator, dir_rel) catch return null;
    return .{ .dir = dir_abs, .module_name = try self.allocator.dupe(u8, mod_name) };
}

fn findModuleByDirAndName(self: *Self, dir_abs: []const u8, module_name: []const u8) ?u32 {
    var i: u32 = 0;
    while (i < self.modules.items.len) : (i += 1) {
        const m = self.modules.items[i];
        if (std.mem.eql(u8, m.dir_path, dir_abs) and std.mem.eql(u8, m.name, module_name)) return i;
    }
    return null;
}

fn detectImportCycles(self: *Self) !void {
    var state: std.ArrayListUnmanaged(u8) = .empty;
    defer state.deinit(self.allocator);
    try state.resize(self.allocator, self.modules.items.len);
    @memset(state.items, 0);

    var m: u32 = 0;
    while (m < self.modules.items.len) : (m += 1) {
        if (state.items[m] == 0) try self.dfsCycle(m, state.items);
    }
}

fn dfsCycle(self: *Self, mod_idx: u32, state: []u8) !void {
    state[mod_idx] = 1;
    for (self.edges.items) |e| {
        if (e.from_module != mod_idx) continue;
        const target = e.to_module orelse continue;
        if (state[target] == 0) {
            try self.dfsCycle(target, state);
        } else if (state[target] == 1) {
            try self.errors.append(self.allocator, .{ .file_id = e.file_id, .span = e.span, .message = "import cycle detected" });
        }
    }
    state[mod_idx] = 2;
}

fn extractModuleName(self: *Self, file_id: SourceManager.FileId, p: *Parser, root: Ast.NodeId) ![]u8 {
    const root_node = p.nodes.items[root];
    if (root_node.tag != .block) return try self.allocator.dupe(u8, "");
    const start = root_node.data.block.item_start;
    const count = root_node.data.block.item_count;
    var first_name: ?[]u8 = null;
    var i: u32 = 0;
    while (i < count) : (i += 1) {
        const n_id = p.list_items.items[start + i];
        const n = p.nodes.items[n_id];
        if (n.tag == .module_decl) {
            try self.sm.ensureTextLoaded(file_id);
            const slice = try self.sm.spanSlice(file_id, n.data.module_decl.name_span);
            if (first_name == null) {
                first_name = try self.allocator.dupe(u8, slice);
            } else {
                try self.errors.append(self.allocator, .{ .file_id = file_id, .span = n.span, .message = "multiple module declarations in file" });
                if (!std.mem.eql(u8, first_name.?, slice)) {
                    try self.errors.append(self.allocator, .{ .file_id = file_id, .span = n.span, .message = "conflicting module declarations in file" });
                }
            }
        }
    }
    return first_name orelse try self.allocator.dupe(u8, "");
}

fn extractUsePath(self: *Self, file_id: SourceManager.FileId, span: Span) ![]u8 {
    try self.sm.ensureTextLoaded(file_id);
    const token_slice = try self.sm.spanSlice(file_id, span);
    if (token_slice.len < 2 or token_slice[0] != '"' or token_slice[token_slice.len - 1] != '"') {
        return try self.allocator.dupe(u8, token_slice);
    }
    return try self.allocator.dupe(u8, token_slice[1 .. token_slice.len - 1]);
}

fn lexAll(allocator: std.mem.Allocator, src: []const u8) ![]Tok {
    var lx = Lexer.init(src);
    var toks: std.ArrayListUnmanaged(Tok) = .empty;
    errdefer toks.deinit(allocator);
    while (lx.next()) |tok| try toks.append(allocator, tok);
    return try toks.toOwnedSlice(allocator);
}

test "use resolves module in same directory by module declaration" {
    const alloc = std.testing.allocator;
    const dir = "tmp_mod_group_same_dir";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_mod_group_same_dir/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nM := use \"other_module\"\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_mod_group_same_dir/a.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module other_module\nA := 1\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_mod_group_same_dir/b.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module other_module\nB := 2\n");
    }

    var g = try Self.buildFromEntry(alloc, "tmp_mod_group_same_dir/main.dyn");
    defer g.deinit();

    try std.testing.expect(g.modules.items.len >= 2);
    try std.testing.expectEqual(@as(usize, 0), g.errors.items.len);

    var found_other = false;
    var other_count: u32 = 0;
    for (g.modules.items) |m| {
        if (std.mem.eql(u8, m.name, "other_module")) {
            found_other = true;
            other_count = m.file_count;
        }
    }
    try std.testing.expect(found_other);
    try std.testing.expect(other_count >= 2);
}

test "use errors when no matching module declaration in target directory" {
    const alloc = std.testing.allocator;
    const dir = "tmp_mod_group_missing";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_mod_group_missing/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nX := use \"other_module\"\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_mod_group_missing/a.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module not_it\nA := 1\n");
    }

    var g = try Self.buildFromEntry(alloc, "tmp_mod_group_missing/main.dyn");
    defer g.deinit();
    try std.testing.expect(g.errors.items.len >= 1);
}

test "use resolves nested directory module target" {
    const alloc = std.testing.allocator;
    const dir = "tmp_mod_nested";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    try std.fs.cwd().makePath("tmp_mod_nested/pkg");
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_mod_nested/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nP := use \"pkg/math\"\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_mod_nested/pkg/math.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module math\npub v := 1\n");
    }

    var g = try Self.buildFromEntry(alloc, "tmp_mod_nested/main.dyn");
    defer g.deinit();
    try std.testing.expectEqual(@as(usize, 0), g.errors.items.len);

    var found = false;
    for (g.modules.items) |m| {
        if (std.mem.eql(u8, m.name, "math") and std.mem.endsWith(u8, m.dir_path, "tmp_mod_nested/pkg")) {
            found = true;
        }
    }
    try std.testing.expect(found);
}

test "module graph reports conflicting module declarations in one file" {
    const alloc = std.testing.allocator;
    const dir = "tmp_mod_conflict_decl";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_mod_conflict_decl/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nmodule other\na := 1\n");
    }

    var g = try Self.buildFromEntry(alloc, "tmp_mod_conflict_decl/main.dyn");
    defer g.deinit();

    var saw = false;
    for (g.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "conflicting module declarations in file")) saw = true;
    }
    try std.testing.expect(saw);
}

test "module graph loads module files in deterministic lexical order" {
    const alloc = std.testing.allocator;
    const dir = "tmp_mod_deterministic_order";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_mod_deterministic_order/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nmain := () i32 => a + z\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_mod_deterministic_order/zeta.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nz := 1\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_mod_deterministic_order/alpha.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\na := 2\n");
    }

    var g = try Self.buildFromEntry(alloc, "tmp_mod_deterministic_order/main.dyn");
    defer g.deinit();

    var main_idx: ?u32 = null;
    for (g.modules.items, 0..) |m, i| {
        if (std.mem.eql(u8, m.name, "main") and std.mem.endsWith(u8, m.dir_path, "tmp_mod_deterministic_order")) {
            main_idx = @intCast(i);
            break;
        }
    }
    try std.testing.expect(main_idx != null);

    const m = g.modules.items[main_idx.?];
    var alpha_pos: ?u32 = null;
    var zeta_pos: ?u32 = null;
    var i: u32 = 0;
    while (i < m.file_count) : (i += 1) {
        const fi = g.module_file_indices.items[m.file_start + i];
        const p = g.files.items[fi].path;
        if (std.mem.endsWith(u8, p, "alpha.dyn")) alpha_pos = i;
        if (std.mem.endsWith(u8, p, "zeta.dyn")) zeta_pos = i;
    }

    try std.testing.expect(alpha_pos != null and zeta_pos != null);
    try std.testing.expect(alpha_pos.? < zeta_pos.?);
}

test "use std fallback resolves from configured std_dir" {
    const alloc = std.testing.allocator;
    const dir = "tmp_mod_std_fallback";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath("tmp_mod_std_fallback/app");
    try std.fs.cwd().makePath("tmp_mod_std_fallback/sdk/std");
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_mod_std_fallback/app/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nIo := use \"std/io\"\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_mod_std_fallback/sdk/std/io.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module io\npub v := 1\n");
    }

    var g = try Self.buildFromEntryWithOptions(alloc, "tmp_mod_std_fallback/app/main.dyn", .{ .std_dir = "tmp_mod_std_fallback/sdk/std" });
    defer g.deinit();
    try std.testing.expectEqual(@as(usize, 0), g.errors.items.len);

    var found = false;
    for (g.modules.items) |m| {
        if (std.mem.eql(u8, m.name, "io") and std.mem.endsWith(u8, m.dir_path, "tmp_mod_std_fallback/sdk/std")) {
            found = true;
        }
    }
    try std.testing.expect(found);
}

test "local std directory takes precedence over std_dir fallback" {
    const alloc = std.testing.allocator;
    const dir = "tmp_mod_std_precedence";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath("tmp_mod_std_precedence/app/std");
    try std.fs.cwd().makePath("tmp_mod_std_precedence/sdk/std");
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_mod_std_precedence/app/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nIo := use \"std/io\"\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_mod_std_precedence/app/std/io.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module io\npub from_local := 1\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_mod_std_precedence/sdk/std/io.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module io\npub from_sdk := 1\n");
    }

    var g = try Self.buildFromEntryWithOptions(alloc, "tmp_mod_std_precedence/app/main.dyn", .{ .std_dir = "tmp_mod_std_precedence/sdk/std" });
    defer g.deinit();
    try std.testing.expectEqual(@as(usize, 0), g.errors.items.len);

    var picked_local = false;
    for (g.edges.items) |e| {
        if (!std.mem.eql(u8, e.raw_path, "std/io")) continue;
        const to = e.to_module orelse continue;
        const m = g.modules.items[to];
        if (std.mem.eql(u8, m.name, "io") and std.mem.endsWith(u8, m.dir_path, "tmp_mod_std_precedence/app/std")) {
            picked_local = true;
        }
    }
    try std.testing.expect(picked_local);
}
