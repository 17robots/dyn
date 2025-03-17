const std = @import("std");
const Parser = @import("parser.zig");
const Node = @import("ast.zig").Node;

pub fn main() !void {
    const page_allocator = std.heap.page_allocator;
    var arena = std.heap.ArenaAllocator.init(page_allocator);
    const alloc = arena.allocator();
    defer arena.deinit();

    const file_body = try read_file(alloc, "src/test.dyn");

    var parser = Parser.init(alloc, file_body);
    print_tree(try parser.program());
}

pub fn read_file(a: std.mem.Allocator, filename: []const u8) ![]const u8 {
    const file = try std.fs.cwd().openFile(filename, .{ .mode = .read_only });
    defer file.close();
    const stat = try file.stat();
    return try file.readToEndAlloc(a, stat.size);
}

pub fn print_tree(n: Node) void {
    switch(n) {
        .program => |i| {
            std.debug.print("Program\n", .{});
            for (i.declarations.items) |v| print_tree(v);
        },
        .module => |i| {
            std.debug.print("Module\n", .{});
            print_tree(i.name.*);
        },
        .identifier => |i| std.debug.print("Identifier: {s}\n", .{i.value}),
        .declaration => |i| {
            std.debug.print("Declaration, public: {any}\n", .{i.pub_});
            print_tree(i.name.*);
            if(i.type) |j| print_tree(j.*);
            print_tree(i.val.*);
        },
        .mut_declaration => |i| {
            std.debug.print("Mut Declaration, mut: {any}\n", .{i.mut});
            print_tree(i.name.*);
            if(i.type) |j| print_tree(j.*);
            if(i.val) |j| print_tree(j.*);
        },
        .block => |i| {
            std.debug.print("Block\n", .{});
            for (i.statements.items) |j| print_tree(j);
        },
        .arrow_expression => |i| {
            std.debug.print("Arrow Expression\n", .{});
            print_tree(i.expression.*);
        },
        .assign_expression => |i| {
            std.debug.print("Assign Expression\n", .{});
            print_tree(i.left.*);
            std.debug.print("{s}", .{i.op.to_string()});
            print_tree(i.right.*);
        },
        .if_prefix => |i| {
            std.debug.print("If Prefix\n", .{});
            print_tree(i.expression.*);
            if(i.capture) |j| print_tree(j.*);
        },
        .for_prefix => |i| {
            std.debug.print("For Prefix\n", .{});
            for (i.expressions.items) |j| print_tree(j);
            print_tree(i.capture.*);
        },
        .while_prefix => |i| {
            std.debug.print("While Prefix\n", .{});
            print_tree(i.expression.*);
            if(i.capture) |j| print_tree(j.*);
        },
        .match => |i| {
            std.debug.print("Match\n", .{});
            print_tree(i.expression.*);
            for (i.arms.items) |j| print_tree(j);
        },
        .arm => |i| {
            std.debug.print("Match Arm\n", .{});
            for(i.expressions.items) |j| print_tree(j);
            if(i.capture) |j| print_tree(j.*);
        },
        .if_statement => |i| {
            std.debug.print("If Statement\n", .{});
            print_tree(i.prefix.*);
            print_tree(i.body.*);
            if(i.else_body) |j| print_tree(j.*);
        },
        .for_statement => |i| {
            std.debug.print("For Statement\n", .{});
            print_tree(i.prefix.*);
            print_tree(i.body.*);
        },
        .while_statement => |i| {
            std.debug.print("While Statement\n", .{});
            print_tree(i.prefix.*);
            print_tree(i.body.*);
        },
        .defer_statement => |i| {
            std.debug.print("Defer\n", .{});
            if(i.capture) |j| print_tree(j.*);
            print_tree(i.body.*);
        },
        .capture_val => |i| {
            std.debug.print("Capture Val, mut: {any}", .{i.mut});
            print_tree(i.val.*);
        },
        .capture => |i| {
            std.debug.print("Capture\n", .{});
            for(i.captures.items) |j| print_tree(j);
        },
        .return_expression => |i| {
            std.debug.print("Return\n", .{});
            if(i.val) |j| print_tree(j.*);
        },
        .break_expression => |i| {
            std.debug.print("Break\n", .{});
            if(i.label) |j| print_tree(j.*);
            if(i.val) |j| print_tree(j.*);
        },
        .continue_expression => |i| {
            std.debug.print("Continue\n", .{});
            if(i.label) |j| print_tree(j.*);
        },
        .nullish_expression => |i| {
            std.debug.print("Nullish\n", .{});
            print_tree(i.a.*);
            print_tree(i.b.*);
        },
        .range_expression => |i| {
            std.debug.print("Range\n", .{});
            print_tree(i.a.*);
            print_tree(i.b.*);
        },
        .array_init => |i| {
            std.debug.print("Array Init\n", .{});
            for(i.vals.items) |j| print_tree(j);
        },
        .struct_init => |i| {
            std.debug.print("Struct Init\n", .{});
            if(i.name) |j| print_tree(j.*);
            for(i.inits.items) |j| print_tree(j);
        },
        .struct_init_member => |i| {
            std.debug.print("Struct Init Member\n", .{});
            print_tree(i.name.*);
            print_tree(i.val.*);
        },
        .enum_error_init => |i| {
            std.debug.print("Enum/Error Init Member\n", .{});
            print_tree(i.name.*);
            if(i.val) |j| print_tree(j.*);
        },
        .struct_ => |i| {
            std.debug.print("Struct Declaration\n", .{});
            for (i.members.items) |j| print_tree(j);
        },
        .struct_member => |i| {
            std.debug.print("Struct Member\n", .{});
            for(i.names.items) |j| print_tree(j);
            print_tree(i.type.*);
            if (i.val) |j| print_tree(j.*);
        },
        .enum_ => |i| {
            std.debug.print("Enum Declaration\n", .{});
            for (i.members.items) |j| print_tree(j);
        },
        .enum_member => |i| {
            std.debug.print("Enum Member\n", .{});
            print_tree(i.name.*);
            if (i.type) |j| print_tree(j.*);
        },
        .error_ => |i| {
            std.debug.print("Error Declaration\n", .{});
            for (i.members.items) |j| print_tree(j);
        },
        .error_member => |i| {
            std.debug.print("Error Member\n", .{});
            print_tree(i.name.*);
            if (i.type) |j| print_tree(j.*);
        },
        .if_expression => |i| {
            std.debug.print("If Expression\n", .{});
            print_tree(i.prefix.*);
            print_tree(i.body.*);
            if(i.else_body) |j| print_tree(j.*);
        },
        .for_expression => |i| {
            std.debug.print("For Expression\n", .{});
            print_tree(i.prefix.*);
            print_tree(i.body.*);
        },
        .while_expression => |i| {
            std.debug.print("While Expression\n", .{});
            print_tree(i.prefix.*);
            print_tree(i.body.*);
        },
        .optional_type => |i| {
            std.debug.print("Optional Type\n", .{});
            print_tree(i.expression.*);
        },
        .pointer_type => |i| {
            std.debug.print("Pointer Type\n", .{});
            print_tree(i.expression.*);
        },
        .optional_dereference => |i| {
            std.debug.print("Optional Dereference\n", .{});
            print_tree(i.expression.*);
        },
        .pointer_dereference => |i| {
            std.debug.print("Pointer Dereference\n", .{});
            print_tree(i.expression.*);
        },
        .comp_expression => |i| {
            std.debug.print("Comp Expression\n", .{});
            print_tree(i.expression.*);
        },
        .call => |i| {
            std.debug.print("Function Call\n", .{});
            print_tree(i.name.*);
            for (i.args.items) |j| print_tree(j);
        },
        .try_ => |i| {
            std.debug.print("Try Expression\n", .{});
            print_tree(i.expression.*);
        },
        .catch_ => |i| {
            std.debug.print("Catch Expression\n", .{});
            print_tree(i.expression.*);
            print_tree(i.body.*);
        },
        .member_access => |i| {
            std.debug.print("Member Access\n", .{});
            print_tree(i.name.*);
            print_tree(i.member.*);
        },
        .array_index => |i| {
            std.debug.print("Array Index\n", .{});
            print_tree(i.name.*);
            print_tree(i.index.*);
        },
        .array_type => |i| {
            std.debug.print("Array Type\n", .{});
            print_tree(i.expression.*);
        },
        .error_union_type => |i| {
            std.debug.print("Error Union Type\n", .{});
            if(i.name) |j| print_tree(j.*);
            for (i.errors.items) |j| print_tree(j);
        },
        .grouped => |i| {
            std.debug.print("Grouped\n", .{});
            if(i.expression) |j| print_tree(j.*);
        },
        .use => |i| {
            std.debug.print("Use\n", .{});
            print_tree(i.path.*);
        },
        .literal => |i| std.debug.print("Literal, {s}, {s}\n", .{i.kind.to_string(), i.val}) ,
        .unary => |i| {
            std.debug.print("Unary\n", .{});
            std.debug.print("{s}\n", .{i.op.to_string()});
            print_tree(i.b.*);
        },
        .binary => |i| {
            std.debug.print("Binary\n", .{});
            print_tree(i.a.*);
            std.debug.print("{s}\n", .{i.op.to_string()});
            print_tree(i.b.*);
        },
        .function => |i| {
            std.debug.print("Function\n", .{});
            for(i.parameters.items) |j| print_tree(j);
            if(i.result) |j| print_tree(j.*);
            print_tree(i.body.*);
        },
        .function_parameter => |i| {
            std.debug.print("Function Parameter\n", .{});
            for(i.names.items) |j| print_tree(j);
            print_tree(i.type.*);
        },
        .function_type => |i| {
            std.debug.print("Function Type\n", .{});
            for(i.parameters.items) |j| print_tree(j);
            if(i.result) |j| print_tree(j.*);
        },
        .underscore => std.debug.print("Underscore\n", .{}),
        .@"type" => std.debug.print("Type\n", .{}),
    }
}
