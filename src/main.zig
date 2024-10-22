const std = @import("std");
const Parser = @import("parser2.zig").Parser;
const ast = @import("ast2.zig");

pub fn main() !void {
    const page_allocator = std.heap.page_allocator;
    var arena = std.heap.ArenaAllocator.init(page_allocator);
    const alloc = arena.allocator();
    defer arena.deinit();

    const x = try read_file(alloc, "src/main.dyn");

    var parser = Parser.init(alloc, x);
    var p = try parser.parse();
    defer p.deinit(parser.allocator);
    try print_tree(p);
}

pub fn read_file(a: std.mem.Allocator, filename: []const u8) ![]const u8 {
    const file = try std.fs.cwd().openFile(filename, .{ .mode = .read_only });
    defer file.close();
    const stat = try file.stat();
    return try file.readToEndAlloc(a, stat.size);
}

pub fn print_tree(node: *const ast.Node) !void {
    switch (node.*) {
        .Program => |s| {
            std.debug.print("Program\n", .{});
            std.debug.print("Public members:\n", .{});
            for (s.pub_declarations) |p| {
                try print_tree(p);
            }
            std.debug.print("Private members:\n", .{});
            for (s.declarations) |d| {
                try print_tree(d);
            }
        },
        .ModuleDeclaration => |s| {
            std.debug.print("Module declaration\n", .{});
            std.debug.print("Name: ", .{});
            std.debug.print("Name {!}", .{s});
            try print_tree(s.name);
        },
        .UseDeclaration => |s| {
            std.debug.print("Use Declaration\n", .{});
            std.debug.print("imports", .{});
            try print_tree(s.import);
            std.debug.print("Alias\n", .{});
            if (s.alias) |a| {
                try print_tree(a);
            } else {
                std.debug.print("None\n", .{});
            }
        },
        .UseBlock => |s| {
            std.debug.print("Use block\n", .{});
            for (s.uses) |u| {
                try print_tree(u);
            }
        },
        .Literal => |s| {
            std.debug.print("Literal\n", .{});
            std.debug.print("literal type: ", .{});
            switch (s.lit_type) {
                .int => std.debug.print("int\n", .{}),
                .float => std.debug.print("float\n", .{}),
                .string => std.debug.print("string\n", .{}),
            }
            std.debug.print("value: {s}\n", .{s.value});
        },
        .Identifier => |s| {
            std.debug.print("Identifier\n", .{});
            std.debug.print("value: {s}", .{s.value});
        },
        .Declaration => {
            std.debug.print("Declaration general, please remove when done\n", .{});
        },
    }
}
