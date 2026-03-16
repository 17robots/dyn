const std = @import("std");
const diagnostic = @import("diagnostic.zig");

fn Tree(comptime T: type) type {
    return struct {
        const Node = struct {
            val: T,
            left: ?*Node = null,
            right: ?*Node = null,
        };
        allocator: std.mem.Allocator,
        root: ?Node,
    };
}

const STD_COLLECTION_DIR = "std";
const STD_PATH_ENV = "DYN_STD_PATH";

const ModuleId = usize;
const ModuleKey = struct { directory: []const u8, module_name: []const u8 };
const ResolvedModule = struct { id: ModuleId, key: ModuleKey, files: std.ArrayList([]const u8) };
const ModuleGraph = struct {
    root_dir: []const u8,
    groups: std.AutoHashMap(ModuleKey, std.ArrayList([]const u8)),
    diagnostics: std.ArrayList(diagnostic.Diagnostic),
    modules: std.ArrayList(ResolvedModule),
    key_to_id: std.AutoHashMap(ModuleKey, ModuleId),
    pub fn module_id(self: ModuleGraph, key: ModuleId) ?ModuleId {
        return self.key_to_id.get(key);
    }
    pub fn module(self: ModuleGraph, id: ModuleId) ?ResolvedModule {
        if (id >= self.modules.items.len) return null;
        return self.modules.items[id];
    }
};
const ModuleResolverError = error {
    InvalidStartDirectory,
    Io
};

pub fn resolve_module_graph(allocator: std.mem.Allocator, start_dir: []const u8) ModuleResolverError!ModuleGraph {

}

pub fn configured_std_root_dir(allocator: std.mem.Allocator) ?[]const u8 {
    if (std.process.getEnvVarOwned(allocator, STD_PATH_ENV) catch null) |p| {
        const stat = std.fs.cwd().stat(p) catch null;
        return switch (stat.kind) {
            .directory => p,
            else => null,
        };
    }
    return null;
}
pub fn resolve_graph_file_path(allocator: std.mem.Allocator, graph: ModuleGraph, logical_file_path: []const u8) []const u8 {
    const project_candidate = std.fs.path.join(allocator, &.{ graph.root_dir, logical_file_path });
    const stat = std.fs.cwd().stat(project_candidate) catch {};
    if (stat.kind == .file) return project_candidate;
    if (strip_std_prefix(allocator, logical_file_path) == null) return project_candidate;
    if(configured_std_root_dir(allocator) == null) return project_candidate;
}
fn strip_std_prefix(allocator: std.mem.Allocator, path: []const u8) ?[]const u8 {
    var components = std.fs.path.componentIterator(path) catch {};
    if (components.next()) |f| {
        if (!std.mem.eql(u8, f.path, STD_PATH_ENV)) return null;
    }
    var res = "";
    while (components.next()) |c| res = std.fs.path.join(allocator, &.{ res, '/', c.name });
    return res;
}
