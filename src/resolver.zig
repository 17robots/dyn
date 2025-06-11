const std = @import("std");
const File = @import("file.zig");

pub const Module = struct {
    name: []const u8,
    files: std.ArrayList(File),
    pub fn check(m: *Module) void {
        _ = m;
    }
};

const ModuleResolver = @This();

c: std.StringHashMap(std.ArrayList(Module)),
a: std.mem.Allocator,

pub fn init(allocator: std.mem.Allocator) ModuleResolver {
    return .{ .a = allocator, .c = std.StringHashMap(std.ArrayList(Module)).init(allocator) };
}

pub fn resolveModule(s: *ModuleResolver, calling_file_path_from_cwd: []const u8, modulePath: []const u8) !Module {
    const module_parts = try getModuleNamePath(s.a, calling_file_path_from_cwd, modulePath);
    if (s.c.get(module_parts.path)) |modules| { // if cached then attempt to load
        for (modules.items) |module| {
            if (std.mem.eql(u8, module.name, module_parts.name)) {
                return module;
            }
        }
        return error.ModuleNotFound;
    } else {
        // make sure the dir opens before we cache it
        var dir = try std.fs.cwd().openDir(module_parts.path, .{ .iterate = true, .access_sub_paths = false });
        defer dir.close();
        try s.c.put(module_parts.path, std.ArrayList(Module).init(s.a));
        const mods = s.c.getPtr(module_parts.path).?;
        var iterator = dir.iterate();
        outer: while (try iterator.next()) |entry| {
            if (entry.kind != .file) continue;
            if (!std.mem.endsWith(u8, entry.name, ".dyn")) continue;
            const file = try File.init(s.a, dir, try s.a.dupe(u8, entry.name));
            var lines = std.mem.splitScalar(u8, file.content, '\n');
            const line = lines.next() orelse continue;
            const mod_name = parseModuleName(line) catch continue;
            for (mods.items) |*mod| {
                if (std.mem.eql(u8, mod.name, mod_name)) {
                    try mod.files.append(file);
                    continue :outer;
                }
            }
            // module not found, create one
            var mod = Module{ .name = mod_name, .files = std.ArrayList(File).init(s.a) };
            // std.debug.print("Adding {s} to {s}\n", .{ file.name, mod.name });
            try mod.files.append(file);
            try mods.append(mod);
        }
        iterator.reset();
        for (mods.items) |i| { if (std.mem.eql(u8, i.name, module_parts.name)) return i; }
        return error.ModuleNotFound;
    }
}
fn getModuleNamePath(alloc: std.mem.Allocator, calling_file_path_from_cwd: []const u8, modulePath: []const u8) !struct { path: []const u8, name: []const u8 } {
    var module_pieces = std.mem.splitScalar(u8, modulePath, '/');
    var parts = std.ArrayList([]const u8).init(alloc);
    defer parts.deinit();
    while (module_pieces.next()) |part| try parts.append(part);
    var path = std.ArrayList(u8).init(alloc);
    defer path.deinit();
    if (parts.items.len > 1) {
        try path.appendSlice(parts.items[0]);
        for (1..parts.items.len - 1) |i| {
            try path.append(std.fs.path.sep);
            try path.append(path.items[i]);
        }
    }
    const module_name = parts.items[parts.items.len - 1];
    if (module_name.len == 0) return error.InvalidModuleName;
    const module_path = path.items;
    return .{ .path = try std.mem.join(alloc, "/", &[_][]const u8{ calling_file_path_from_cwd, module_path }), .name = module_name };
}

fn parseModuleName(line: []const u8) ![]const u8 {
    if (std.mem.startsWith(u8, line, "module ")) {
        var words = std.mem.splitScalar(u8, line, ' ');
        _ = words.next(); // skip module
        if (words.next()) |name| {
            if (name.len <= 2) return error.InvalidModuleName;
            if (name[name.len - 2] == ';') {
                return name[0 .. name.len - 2];
            }
            return error.InvalidModuleName;
        } else return error.InvalidModuleName;
    }
    return error.ModuleNotFound;
}
