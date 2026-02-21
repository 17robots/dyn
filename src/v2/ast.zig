const std = @import("std");
const Span = @import("token.zig").Span;

pub const NodeId = u32;
pub const NullNode: NodeId = std.math.maxInt(NodeId);

pub const Node = struct {
};
pub const Tag = enum {
};
pub const Data = union(enum) {
    none: void,
    unary: struct {},
    binary: struct {},
    call: struct {},
    assign: struct {},
    field: struct {},
    index: struct {},
    slice: struct {},
    if_expr: struct {},
    match_expr: struct {},
    block: struct {},
    decl: struct {},
    module_decl: struct {},
    use_expr: struct {},
    fn_expr: struct {},
    for_stmt: struct {},
    break_stmt: struct {},
    continue_stmt: struct {},
    defer_stmt: struct {},
    return_stmt: struct {},
    ptr_type: struct {},
    array_type: struct {},
    error_type: struct {},
};
