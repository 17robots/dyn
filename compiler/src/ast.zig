const std = @import("std");
const Token = @import("lexer.zig").Token;
pub const Ast = struct {
    allocator: std.mem.Allocator,
    sources: std.ArrayList([]const u8),
    tokens: std.ArrayList(Token),
    token_source_map: std.StringHashMap(std.ArrayList(Token)),
    const ParsingState = enum {
        start,
    };
    pub fn init(alloc: std.mem.Allocator, filenames: [][]const u8) !Ast {
        var ast = Ast{ .alloc = alloc, .sources = std.ArrayList([]const u8).init(alloc), .tokens = undefined };
        for (filenames) |name| {
            try ast.sources.append(name);
        }
        return ast;
    }
    pub fn deinit(self: *Ast) void {
        defer self.sources.deinit();
        defer self.tokens.deinit();
    }
    pub fn add_source(self: *Ast, file: []const u8) !void {
        try self.sources.append(file);
    }
    fn tokenize_source(self: *Ast) !void {
        _ = self;
    }
};

const Node = struct {
    allocator: std.mem.Allocator,
    t: NodeType,
    children: std.ArrayList(Node),
    attrs: std.StringHashMap(type),
    const NodeType = enum {};
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
};
