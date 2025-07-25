const std = @import("std");
const module = @import("module.zig");
const Checker = @import("checker.zig");

pub fn main() !void {
    const page_allocator = std.heap.page_allocator;
    var arena = std.heap.ArenaAllocator.init(page_allocator);
    defer arena.deinit();
    const alloc = arena.allocator();

    var checker = try Checker.init(alloc);
    var mod_resolver = module.ModuleResolver.init(alloc);
    var a = try mod_resolver.resolveModule(".", "test");
    try a.parse();
    try checker.check_program(&a);
}
