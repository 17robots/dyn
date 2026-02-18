const std = @import("std");
const Ast = @import("ast.zig");
const ModuleGraph = @import("module_graph.zig");
const ExprKind = @import("expr_kind.zig");

pub const ModuleFunctionRef = struct {
    module_index: u32,
    file_index: u32,
    node_id: Ast.NodeId,
};

pub fn findUseAliasTargetModule(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, alias: []const u8) ?u32 {
    const root = f.root orelse return null;
    const rn = f.nodes[root];
    if (rn.tag != .block) return null;

    var i: u32 = 0;
    while (i < rn.data.block.item_count) : (i += 1) {
        const item_id = f.list_items[rn.data.block.item_start + i];
        const item = f.nodes[item_id];
        if (item.tag != .decl or !item.data.decl.has_init or item.data.decl.name_count == 0) continue;
        const init_n = f.nodes[item.data.decl.init_node];
        if (init_n.tag != .use_expr) continue;

        var j: u32 = 0;
        while (j < item.data.decl.name_count) : (j += 1) {
            const ident = f.nodes[f.decl_name_items[item.data.decl.name_start + j]];
            if (ident.tag != .identifier) continue;
            const name = graph.sm.spanSlice(f.file_id, ident.span) catch continue;
            if (!std.mem.eql(u8, name, alias)) continue;

            const raw = graph.sm.spanSlice(f.file_id, init_n.data.use_expr.path_span) catch "";

            for (graph.edges.items) |e| {
                if (e.file_id != f.file_id) continue;
                if (std.mem.eql(u8, e.raw_path, raw) or (e.span.start == init_n.data.use_expr.path_span.start and e.span.end == init_n.data.use_expr.path_span.end)) {
                    return e.to_module;
                }
            }

            if (tryResolveUseAliasFallback(graph, f, raw)) |mi| return mi;
        }
    }
    return null;
}

pub fn findModuleFunctionRef(graph: *ModuleGraph.Self, module_index: u32, name: []const u8) ?ModuleFunctionRef {
    const m = graph.modules.items[module_index];
    var mf: u32 = 0;
    while (mf < m.file_count) : (mf += 1) {
        const file_index = graph.module_file_indices.items[m.file_start + mf];
        const f = graph.files.items[file_index];
        const root = f.root orelse continue;
        const rn = f.nodes[root];
        if (rn.tag != .block) continue;

        var i: u32 = 0;
        while (i < rn.data.block.item_count) : (i += 1) {
            const item_id = f.list_items[rn.data.block.item_start + i];
            const item = f.nodes[item_id];
            if (item.tag != .decl or !item.data.decl.has_init or item.data.decl.name_count == 0) continue;
            const init_n = f.nodes[item.data.decl.init_node];
            if (init_n.tag == .fn_expr) {
                const ident = f.nodes[f.decl_name_items[item.data.decl.name_start]];
                const nm = graph.sm.spanSlice(f.file_id, ident.span) catch continue;
                if (std.mem.eql(u8, nm, name)) {
                    return .{ .module_index = module_index, .file_index = file_index, .node_id = item.data.decl.init_node };
                }

                const inner_body = f.nodes[ExprKind.peelComptimeWrappers(f, init_n.data.fn_expr.body)];
                if (inner_body.tag == .struct_expr) {
                    var si: u32 = 0;
                    while (si < inner_body.data.aggregate.item_count) : (si += 1) {
                        const sn_id = f.list_items[inner_body.data.aggregate.item_start + si];
                        const sn = f.nodes[sn_id];
                        if (sn.tag != .decl or !sn.data.decl.has_init or sn.data.decl.name_count == 0) continue;
                        const sinit = f.nodes[sn.data.decl.init_node];
                        if (sinit.tag != .fn_expr) continue;
                        const sident = f.nodes[f.decl_name_items[sn.data.decl.name_start]];
                        const sname = graph.sm.spanSlice(f.file_id, sident.span) catch continue;
                        if (std.mem.eql(u8, sname, name)) {
                            return .{ .module_index = module_index, .file_index = file_index, .node_id = sn.data.decl.init_node };
                        }
                    }
                }
            }
        }
    }
    return null;
}

pub fn findUniqueImportedModuleFunctionRef(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, name: []const u8) ?ModuleFunctionRef {
    const root = f.root orelse return null;
    const rn = f.nodes[root];
    if (rn.tag != .block) return null;

    var found: ?ModuleFunctionRef = null;
    var i: u32 = 0;
    while (i < rn.data.block.item_count) : (i += 1) {
        const item_id = f.list_items[rn.data.block.item_start + i];
        const item = f.nodes[item_id];
        if (item.tag != .decl or !item.data.decl.has_init or item.data.decl.name_count == 0) continue;
        const init_n = f.nodes[item.data.decl.init_node];
        if (init_n.tag != .use_expr) continue;

        const ident = f.nodes[f.decl_name_items[item.data.decl.name_start]];
        if (ident.tag != .identifier) continue;
        const alias = graph.sm.spanSlice(f.file_id, ident.span) catch continue;
        const mod_idx = findUseAliasTargetModule(graph, f, alias) orelse continue;
        const ref = findModuleFunctionRef(graph, mod_idx, name) orelse continue;
        if (found != null) return null;
        found = ref;
    }
    return found;
}

fn tryResolveUseAliasFallback(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, raw_path: []const u8) ?u32 {
    var path = raw_path;
    if (path.len >= 2 and path[0] == '"' and path[path.len - 1] == '"') {
        path = path[1 .. path.len - 1];
    }
    const slash = std.mem.lastIndexOfScalar(u8, path, '/') orelse return null;
    const mod_name = path[slash + 1 ..];
    const rel_dir = path[0..slash];
    const file_dir = std.fs.path.dirname(f.path) orelse return null;
    const abs_dir = std.fs.path.resolve(graph.allocator, &.{ file_dir, rel_dir }) catch return null;
    defer graph.allocator.free(abs_dir);

    for (graph.modules.items, 0..) |m, i| {
        if (std.mem.eql(u8, m.name, mod_name) and std.mem.eql(u8, m.dir_path, abs_dir)) return @intCast(i);
    }
    for (graph.modules.items, 0..) |m, i| {
        if (std.mem.eql(u8, m.name, mod_name)) return @intCast(i);
    }
    return null;
}
