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
        pub_node,
        mut_node,
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
    const kwds = [_][]const u8{ "con", "pub", "struct", "enum", "mut", "true", "false", "void", "for", "loop", "match", "type", "f32", "f64", "if", "else", "defer", "continue", "break" };
    pub fn init(alloc: std.mem.Allocator, t: NodeType) Node {
        return .{
            .allocator = alloc,
            .attrs = std.ArrayList(type).init(alloc),
            .t = t,
            .children = std.ArrayList(Node).init(alloc),
        };
    }
    pub fn deinit(self: *Node) void {
        defer self.children.deinit();
        defer self.attrs.deinit();
    }

    pub fn is_keyword() bool {}

    // root
    pub fn program(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .program);
    }
    // declaration nodes
    pub fn declaration(toks: *std.ArrayList(l.Token), index: *u32, allocator: std.mem.Allocator) !Node {
        var node: Node = Node.init(allocator, .declaration);
        if (toks.items[index].t == 3 and std.mem.eql(u8, toks.items[index].v, "pub")) {
            try node.children.append(.{ .allocator = allocator.*, .t = .pub_node, .children = undefined, .attrs = undefined });
            index.* += 1;
        }
        if (toks.items[index].t == 3 and std.mem.eql(u8, toks.items[index].v, "struct")) {
            const n: Node = try Node.struct_node(toks, index, allocator);
            if (n.t != NodeType.struct_decl) {} // error
            try node.children.append(n);
        } else if (toks.items[index].t == 3 and std.mem.eql(u8, toks.items[index].v, "enum")) {
            const n: Node = try Node.enum_node(toks, index, allocator);
            if (n.t != NodeType.struct_decl) {} // error
            try node.children.append(n);
        } else {
            const n: Node = try Node.variable_node(toks, index, allocator);
            if (n.t != .variable or n.t != .function) {} // error
            try node.children.append(n);
        }
        return node;
    } // pub?
    pub fn variable_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        var node: Node = Node.init(allocator, .variable);
        if (toks.items[index].t != 1) {} // error
        try node.children.append(Node{ .t = .identifier, .children = undefined, .attrs = .{} });
    } // mut?
    pub fn struct_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn struct_variable_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn struct_function_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn enum_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn enum_member_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn function_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn function_arg_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn type_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn import_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    // statements
    pub fn statement(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn if_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn loop_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn for_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn match_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn match_branch_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn defer_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn break_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn continue_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    // expressions
    pub fn expression(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn identifier_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn integer_literal_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn float_literal_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn boolean_literal_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn string_literal_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn char_literal_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn function_call_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn unary_expr_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn binary_expr_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn paren_expr_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn anon_function_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn anon_struct_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn anon_enum_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn type_literal_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn array_type_literal_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn pointer_type_literal_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
    pub fn reference_type_literal_node(toks: *std.ArrayList(l.Token), index: u32, allocator: std.mem.Allocator) !Node {
        _ = index;
        _ = toks;
        return Node.init(allocator, .struct_decl);
    }
};
