const Ast = @import("ast.zig");
const ModuleGraph = @import("module_graph.zig");

pub const CalleeNorm = union(enum) {
    identifier: []const u8,
    field: struct {
        object: Ast.NodeId,
        member: []const u8,
        object_ident: ?[]const u8,
    },
    call_of_identifier: []const u8,
    call_of_field: []const u8,
    other: void,
};

pub fn normalize(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, callee_id: Ast.NodeId) !CalleeNorm {
    const callee = f.nodes[callee_id];
    switch (callee.tag) {
        .identifier => {
            try graph.sm.ensureTextLoaded(f.file_id);
            const name = try graph.sm.spanSlice(f.file_id, callee.span);
            return .{ .identifier = name };
        },
        .field => {
            try graph.sm.ensureTextLoaded(f.file_id);
            const member = try graph.sm.spanSlice(f.file_id, callee.data.field.field_span);
            const obj = f.nodes[callee.data.field.object];
            const object_ident = if (obj.tag == .identifier) (try graph.sm.spanSlice(f.file_id, obj.span)) else null;
            return .{ .field = .{ .object = callee.data.field.object, .member = member, .object_ident = object_ident } };
        },
        .call => {
            const inner = f.nodes[callee.data.call.callee];
            switch (inner.tag) {
                .identifier => {
                    try graph.sm.ensureTextLoaded(f.file_id);
                    return .{ .call_of_identifier = try graph.sm.spanSlice(f.file_id, inner.span) };
                },
                .field => {
                    try graph.sm.ensureTextLoaded(f.file_id);
                    return .{ .call_of_field = try graph.sm.spanSlice(f.file_id, inner.data.field.field_span) };
                },
                else => return .{ .other = {} },
            }
        },
        else => return .{ .other = {} },
    }
}
