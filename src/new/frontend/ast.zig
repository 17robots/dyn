const std = @import("std");
const source = @import("source/manager.zig");

pub const NodeId = u32;
pub const Node = struct {
    id: NodeId,
    tag: Tag,
    span: source.Span,
    file_id: u32,
    pub const Tag = enum {
        literal_bool,
        literal_int,
        literal_float,
        literal_string,
        literal_char,
        literal_null,
        identifier,
        prefix_expr,
        infix_expr,
        postfix_expr,
        call_expr,
        index_expr,
        type_expr,
        func_expr,
        if_expr,
        match_expr,
        block_expr,
        range_expr,
        array_literal,
        struct_literal,
        expr_stmt,
        decl_stmt,
        assign_stmt,
        if_stmt,
        for_stmt,
        while_stmt,
        match_stmt,
        defer_stmt,
        return_stmt,
        break_stmt,
        continue_stmt,
        var_decl,
        const_decl,
        func_decl,
        struct_decl,
        enum_decl,
        error_decl,
        module_decl,
        import_decl,
        named_type,
        pointer_type,
        array_type,
        slice_type,
        optional_type,
        func_type,
        error_type,
    };
    pub const Data = union(Tag) {
        pub const Param = struct {};
        pub const StructField = struct {};
        pub const EnumVariant = struct {};
        pub const ErrorVariant = struct {};
        pub const MatchCase = struct {};
        pub const ImportSymbol = struct {};
    };
    pub const PrefixOp = enum {};
    pub const InfixOp = enum {};
    pub const PostfixOp = enum {};
};
pub const AST = struct {
    alloctor: std.mem.Allocator,
    nodes: std.MultiArrayList(Node) = .empty,
    data: std.ArrayList(Node.Data) = .empty,
    pub fn init(allocator: std.mem.Allocator) AST {
        return .{ .allocator = allocator };
    }
    pub fn deinit(self: *AST) void {}
    pub fn add_node(self: *AST) NodeId {}
    pub fn get_node(self: *AST, node_id: NodeId) Node {}
    pub fn get_data(self: *AST, node_id: NodeId) Node.Data {}
    pub fn update_data(self: *AST, node_id: NodeId, new_data: Node.Data) void {}
};
