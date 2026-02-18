const std = @import("std");
const Ast = @import("ast.zig");
const ModuleGraph = @import("module_graph.zig");
const ExprKind = @import("expr_kind.zig");
const FileId = @import("source_manager.zig").FileId;

pub const Kind = enum(u8) {
    unknown,
    int_value,
    bool_value,
    type_value,
    fn_value,
    module_value,
};

pub const Value = union(Kind) {
    unknown: void,
    int_value: i64,
    bool_value: bool,
    type_value: Identity,
    fn_value: Identity,
    module_value: Identity,
};

pub const Identity = struct {
    file_id: FileId,
    node_id: Ast.NodeId,
};

pub fn inferKind(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, node_id: Ast.NodeId) Kind {
    return switch (inferValue(graph, f, node_id)) {
        .unknown => .unknown,
        .int_value => .int_value,
        .bool_value => .bool_value,
        .type_value => .type_value,
        .fn_value => .fn_value,
        .module_value => .module_value,
    };
}

pub fn inferValue(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, node_id: Ast.NodeId) Value {
    const id = ExprKind.peelComptimeWrappers(f, node_id);
    const n = f.nodes[id];
    const ident: Identity = .{ .file_id = f.file_id, .node_id = id };
    return switch (n.tag) {
        .int_lit => .{ .int_value = parseInt(graph, f, n.span) orelse 0 },
        .bool_lit => .{ .bool_value = parseBool(graph, f, n.span) orelse false },
        .struct_expr, .enum_expr, .type_lit, .ptr_type, .slice_type, .array_type => .{ .type_value = ident },
        .fn_expr => .{ .fn_value = ident },
        .use_expr => .{ .module_value = ident },
        else => switch (ExprKind.classify(f, id)) {
            .type_value => .{ .type_value = ident },
            .fn_value => .{ .fn_value = ident },
            .module_value => .{ .module_value = ident },
            else => .{ .unknown = {} },
        },
    };
}

fn parseInt(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, span: @import("token.zig").Span) ?i64 {
    graph.sm.ensureTextLoaded(f.file_id) catch return null;
    const sv = graph.sm.spanSlice(f.file_id, span) catch return null;
    return std.fmt.parseInt(i64, sv, 10) catch null;
}

fn parseBool(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, span: @import("token.zig").Span) ?bool {
    graph.sm.ensureTextLoaded(f.file_id) catch return null;
    const sv = graph.sm.spanSlice(f.file_id, span) catch return null;
    if (std.mem.eql(u8, sv, "true")) return true;
    if (std.mem.eql(u8, sv, "false")) return false;
    return null;
}
