const std = @import("std");
const File = @import("file.zig");
const Diagnostic = @import("diagnostic.zig");

pub const Module = struct {
    a: std.mem.Allocator,
    diagnostics: ?std.ArrayList(Diagnostic) = null,
    dir: []const u8,
    files: std.ArrayList(File),
    name: []const u8,
    pub_members: ?[]const i32, // change this
    status: enum { compiling, compiled },
    pub fn init(a: std.mem.Allocator, dir: []const u8, name: []const u8) Module {
        return Module{ .a = a, .dir = dir, .name = name, .files = std.ArrayList(File).init(a) };
    }
    pub fn parse(s: *Module) !void {
        var threads = std.ArrayList(std.Thread).init(s.a);
        defer threads.deinit();
        for (s.files.items) |*f| try threads.append(try std.Thread.spawn(.{}, File.parse, .{ f, s.a }));
        for (threads.items) |i| i.join();
        for (s.files.items) |f| {
            if (f.diagnostics.items.len > 0) {
                if (s.diagnostics) |*d| try d.appendSlice(f.diagnostics.items) else {
                    s.diagnostics = std.ArrayList(Diagnostic).init(s.a);
                    try s.diagnostics.?.appendSlice(f.diagnostics.items);
                }
            }
        }
    }
};

pub const ModuleResolver = struct {
    c: std.StringHashMap(std.ArrayList(Module)),
    a: std.mem.Allocator,
    pub fn init(allocator: std.mem.Allocator) ModuleResolver {
        return .{ .a = allocator, .c = std.StringHashMap(std.ArrayList(Module)).init(allocator) };
    }
    pub fn resolveModule(s: *ModuleResolver, calling_file_path_from_cwd: []const u8, modulePath: []const u8) !Module {
        const module_parts = try getModuleNamePath(s.a, calling_file_path_from_cwd, modulePath);
        const path = try std.fs.path.resolve(s.a, &[_][]const u8{module_parts.path});
        if (s.c.get(path)) |modules| { // if cached then attempt to load
            for (modules.items) |module| {
                if (std.mem.eql(u8, module.name, module_parts.name)) {
                    return module;
                }
            }
            return error.ModuleNotFound;
        } else {
            var dir = try std.fs.cwd().openDir(path, .{ .iterate = true, .access_sub_paths = false });
            defer dir.close();
            try s.c.put(path, std.ArrayList(Module).init(s.a));
            const mods = s.c.getPtr(path).?;
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
                var mod = Module.init(s.a, module_parts.path, mod_name);
                try mod.files.append(file);
                try mods.append(mod);
            }
            for (mods.items) |i| {
                if (std.mem.eql(u8, i.name, module_parts.name)) return i;
            }
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
        return .{ .path = try std.mem.join(alloc, "/", &[_][]const u8{ calling_file_path_from_cwd, path.items }), .name = module_name };
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
};
