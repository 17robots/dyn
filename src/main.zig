const std = @import("std");
const File = @import("file.zig");
const module = @import("module.zig");

pub fn main() !void {
    const page_allocator = std.heap.page_allocator;
    var arena = std.heap.ArenaAllocator.init(page_allocator);
    defer arena.deinit();
    const alloc = arena.allocator();

    const mod_resolver = module.ModuleResolver.init(alloc);
    _ = mod_resolver;
}
