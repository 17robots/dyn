const Ast = @import("ast.zig");
const ModuleGraph = @import("module_graph.zig");

pub const ExprKind = enum {
    runtime_value,
    type_value,
    fn_value,
    module_value,
    unknown,
};

pub fn peelComptimeWrappers(f: ModuleGraph.FileUnit, node_id: Ast.NodeId) Ast.NodeId {
    var cur = node_id;
    while (true) {
        const n = f.nodes[cur];
        switch (n.tag) {
            .comp_expr, .inline_expr => cur = n.data.one.child,
            else => return cur,
        }
    }
}

pub fn classify(f: ModuleGraph.FileUnit, node_id: Ast.NodeId) ExprKind {
    const n = f.nodes[peelComptimeWrappers(f, node_id)];
    return switch (n.tag) {
        .struct_expr, .enum_expr, .type_lit, .ptr_type, .slice_type, .array_type => .type_value,
        .fn_expr => .fn_value,
        .use_expr => .module_value,
        .identifier, .call, .field, .binary, .unary, .if_expr, .match_expr, .block, .assign, .int_lit, .bool_lit, .float_lit, .string_lit, .char_lit, .address_of, .deref, .index, .slice => .runtime_value,
        else => .unknown,
    };
}
