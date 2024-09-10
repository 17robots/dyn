const std = @import("std");
const Parser = @import("parser2.zig").Parser;
const ast = @import("ast.zig");
const Node = ast.Node;
const NodeType = ast.NodeType;

pub fn main() !void {
    const page_allocator = std.heap.page_allocator;
    var arena = std.heap.ArenaAllocator.init(page_allocator);
    const alloc = arena.allocator();
    defer arena.deinit();

    const x = try read_file(alloc, "syntax.dyn");

    var p = Parser.init(alloc, x);

    print_tree(p.parse(), 0);
}

fn print_tree(node: ?Node, level: usize) void {
    if (node) |n| {
        std.debug.print("level {d} {s} {any}", .{ level, get_node_type(n.t), n.metadata });
        for (n.nodes.items) |child| {
            print_tree(child, level + 1);
        }
    } else {
        std.debug.print("none", .{});
    }
}

pub fn get_node_type(nodeType: NodeType) []const u8 {
    return switch (nodeType) {
        .program => "program",
        .moduleDeclaration => "module declaration",
        .useDeclaration => "use declaration",
        .useBlock => "use block",
        .literal => "literal",
        .identifier => "identifier",
    };
}

pub fn read_file(a: std.mem.Allocator, filename: []const u8) ![]const u8 {
    const file = try std.fs.cwd().openFile(filename, .{ .mode = .read_only });
    defer file.close();
    const stat = try file.stat();
    return try file.readToEndAlloc(a, stat.size);
}
