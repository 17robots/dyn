const std = @import("std");
const l = @import("lexer.zig");
pub const Ast = struct {
    allocator: std.mem.Allocator,
    source: []const u8,
    imports: std.StringHashMap(std.StringHashMap([]const u8)),
    tokens: std.ArrayList(l.Token),
    token_source_map: std.StringHashMap(std.ArrayList(l.Token)),
    const ParsingState = enum {
        start,
    };
    pub fn init(alloc: std.mem.Allocator, filename: []const u8) !Ast {
        return .{ .alloc = alloc, .source = filename, .tokens = undefined, .imports = std.StringHashMap(std.StringHashMap([]const u8).init(alloc)) };
    }
    pub fn deinit(self: *Ast) void {
        defer self.tokens.deinit();
        defer self.imports.deinit();
        for (self.imports.valueIterator().items) |i| {
            for (i.valueIterator().items) |j| {
                j.deinit();
            }
            i.deinit();
        }
    }
    fn tokenize(self: *Ast) !void {
        _ = self;
    }
};

const Node = struct {
    allocator: std.mem.Allocator,
    t: NodeType,
    children: std.ArrayList(Node),
    attrs: std.StringHashMap(type),
    const NodeType = enum {
        program,
        variable,
        struct_decl,
        struct_variable,
        struct_function,
        enum_decl,
        enum_member,
        function,
        function_arg,
        type_decl,
        import,
        if_stmt,
        loop_stmt,
        for_stmt,
        match_stmt,
        match_branch,
        defer_stmt,
        break_stmt,
        continue_stmt,
        identifier,
        int_lit,
        float_lit,
        bool_lit,
        string_lit,
        char_lit,
        function_call,
        unary,
        binary,
        paren_expr,
        anon_function,
        anon_struct,
        anon_enum,
        arr_lit,
        pointer_lit,
        ref_lit,
    };
    pub fn init(alloc: std.mem.Allocator) Node {
        return .{
            .alloc = alloc,
            .attrs = std.ArrayList(type).init(alloc),
            .t = undefined,
            .children = std.ArrayList(Node).init(alloc),
        };
    }
    pub fn deinit(self: *Node) void {
        defer self.children.deinit();
        defer self.attrs.deinit();
    }

    // root
    pub fn program(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    // declaration nodes
    pub fn declaration(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    } // pub?
    pub fn variable_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    } // mut?
    pub fn struct_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn struct_variable_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn struct_function_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn enum_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn enum_member_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn function_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn function_arg_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn type_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn import_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    // statements
    pub fn statement(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn if_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn loop_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn for_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn match_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn match_branch_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn defer_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn break_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn continue_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    // expressions
    pub fn expression(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn identifier_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn integer_literal_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn float_literal_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn boolean_literal_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn string_literal_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn char_literal_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn function_call_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn unary_expr_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn binary_expr_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn paren_expr_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn anon_function_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn anon_struct_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn anon_enum_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn type_literal_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn array_type_literal_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn pointer_type_literal_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
    pub fn reference_type_literal_node(toks: *std.ArrayList(l.Token), index: u32) !Node {
        _ = index;
        _ = toks;
    }
};
