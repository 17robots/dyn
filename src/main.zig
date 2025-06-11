const std = @import("std");
const File = @import("file.zig");
const ModuleResolver = @import("resolver.zig");

pub fn main() !void {
    const page_allocator = std.heap.page_allocator;
    var arena = std.heap.ArenaAllocator.init(page_allocator);
    defer arena.deinit();
    const alloc = arena.allocator();

    var mod_resolver = ModuleResolver.init(alloc);
    _ = try mod_resolver.resolveModule(".", "testing/testing");
    _ = try mod_resolver.resolveModule(".", "testing/testing2");
    _ = try mod_resolver.resolveModule(".", "testing/testing3");
    _ = try mod_resolver.resolveModule(".", "main");
    // for(x.files.items) |f| std.debug.print("{s}:\n{s}\n", .{f.name, f.content});
    // for(y.files.items) |f| std.debug.print("{s}:\n{s}\n", .{f.name, f.content});
    // for(z.files.items) |f| std.debug.print("{s}:\n{s}\n", .{f.name, f.content});
    var iterator = mod_resolver.c.iterator();
    while (iterator.next()) |i| {
        for (i.value_ptr.items) |j| {
            for (j.files.items) |k| {
                std.debug.print("{s}\n", .{try std.fs.path.resolve(alloc, &[_][]const u8{ i.key_ptr.*, k.name })});
            }
        }
    }
}
