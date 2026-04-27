const std = @import("std");
const ast = @import("ast.zig");
const diag = @import("diag.zig");
const parser = @import("parser.zig");
const source = @import("source.zig");

pub const ModuleId = enum(u32) { _ };
pub const Module = struct {
    id: ModuleId,
    name: []const u8,
    path: []const u8,
    tree: ast.Ast,
    file: ast.File,
};
pub const Options = struct { std_path: ?[]const u8 = null, base_path: []const u8 = "." };
pub const ModuleLoader = struct {
    allocator: std.mem.Allocator,
    diagnostics: *diag.DiagnosticBag,
    options: Options,
    modules: std.ArrayList(Module),
    cache: std.StringHashMap(ModuleId),
    loading: std.StringHashMap(void),

    pub fn init(allocator: std.mem.Allocator, diagnostics: *diag.DiagnosticBag, options: Options) ModuleLoader {
        return .{ .allocator = allocator, .diagnostics = diagnostics, .options = options, .modules = .empty, .cache = .init(allocator), .loading = .init(allocator) };
    }
    pub fn deinit(self: *ModuleLoader) void {
        for (self.modules.items) |*m| m.tree.deinit();
        self.modules.deinit(self.allocator);
        self.cache.deinit();
        self.loading.deinit();
    }
    pub fn addParsed(self: *ModuleLoader, name: []const u8, path: []const u8, parsed: parser.FileResult) !ModuleId {
        const key = try self.allocator.dupe(u8, path);
        if (self.cache.get(key)) |id| return id;
        const id: ModuleId = @enumFromInt(self.modules.items.len);
        try self.modules.append(self.allocator, .{ .id = id, .name = name, .path = key, .tree = parsed.tree, .file = parsed.file });
        try self.cache.put(key, id);
        return id;
    }
    pub fn loadUse(self: *ModuleLoader, importer: ModuleId, use_path: []const u8, span: source.Span) !?ModuleId {
        _ = importer;
        const key = try self.resolveKey(use_path);
        if (self.cache.get(key)) |id| return id;
        if (self.loading.contains(key)) {
            try self.diagnostics.errorAt("R0003", "cyclic import detected", span, "import participates in a cycle");
            return null;
        }
        try self.loading.put(key, {});
        defer _ = self.loading.remove(key);
        const parsed = self.parsePath(key, span) catch return null;
        return try self.addParsed(moduleNameFromPath(use_path), key, parsed);
    }
    fn resolveKey(self: *ModuleLoader, use_path: []const u8) ![]const u8 {
        if (std.mem.startsWith(u8, use_path, "std/")) {
            const base = self.options.std_path orelse "std"; // DYN_STD_PATH handled by CLI/config layer when available
            return std.fs.path.join(self.allocator, &.{ base, use_path[4..] });
        }
        return std.fs.path.join(self.allocator, &.{ self.options.base_path, use_path });
    }
    fn parsePath(self: *ModuleLoader, key: []const u8, span: source.Span) !parser.FileResult {
        const file_path = try std.fmt.allocPrint(self.allocator, "{s}.dyn", .{key});
        const has_file = fileExists(file_path);
        const has_dir = dirExists(key);
        if (has_file and has_dir) {
            try self.diagnostics.errorAt("R0001", "import path is ambiguous", span, "both file and directory module exist");
            return error.ImportFailed;
        }
        if (!has_file and !has_dir) {
            try self.diagnostics.errorAt("R0002", "import path does not exist", span, "no module found for this import");
            return error.ImportFailed;
        }
        if (has_file) {
            const src = readFileAllocPosix(self.allocator, file_path) catch {
                try self.diagnostics.errorAt("R0002", "import path does not exist", span, "module file could not be read");
                return error.ImportFailed;
            };
            return parser.parseFileSource(self.allocator, src, self.diagnostics);
        }
        return self.parseDirModule(key, span);
    }
    fn parseDirModule(self: *ModuleLoader, key: []const u8, span: source.Span) !parser.FileResult {
        var io_threaded: std.Io.Threaded = .init(self.allocator, .{});
        defer io_threaded.deinit();
        const io = io_threaded.io();
        var dir = std.Io.Dir.cwd().openDir(io, key, .{ .iterate = true }) catch {
            try self.diagnostics.errorAt("R0002", "import path does not exist", span, "directory module could not be opened");
            return error.ImportFailed;
        };
        defer dir.close(io);
        var it = dir.iterate();
        var combined = std.ArrayList(u8).empty;
        var found = false;
        while (try it.next(io)) |entry| {
            if (entry.kind != .file) continue;
            if (!std.mem.endsWith(u8, entry.name, ".dyn")) continue;
            const path = try std.fs.path.join(self.allocator, &.{ key, entry.name });
            const src = readFileAllocPosix(self.allocator, path) catch continue;
            try combined.appendSlice(self.allocator, src);
            try combined.append(self.allocator, '\n');
            found = true;
        }
        if (!found) {
            try self.diagnostics.errorAt("R0002", "import path does not exist", span, "directory module contains no `.dyn` files");
            return error.ImportFailed;
        }
        return parser.parseFileSource(self.allocator, combined.items, self.diagnostics);
    }
};
fn fileExists(path: []const u8) bool {
    const fd = std.posix.openat(std.posix.AT.FDCWD, path, .{ .ACCMODE = .RDONLY, .CLOEXEC = true }, 0) catch return false;
    _ = std.os.linux.close(fd);
    return true;
}
fn dirExists(path: []const u8) bool {
    const fd = std.posix.openat(std.posix.AT.FDCWD, path, .{ .ACCMODE = .RDONLY, .CLOEXEC = true, .DIRECTORY = true }, 0) catch return false;
    _ = std.os.linux.close(fd);
    return true;
}
fn readFileAllocPosix(allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    const fd = try std.posix.openat(std.posix.AT.FDCWD, path, .{ .ACCMODE = .RDONLY, .CLOEXEC = true }, 0);
    defer _ = std.os.linux.close(fd);
    var list = std.ArrayList(u8).empty;
    var buf: [4096]u8 = undefined;
    while (true) {
        const n = try std.posix.read(fd, &buf);
        if (n == 0) break;
        try list.appendSlice(allocator, buf[0..n]);
        if (list.items.len > (1 << 20)) return error.FileTooBig;
    }
    return list.toOwnedSlice(allocator);
}
fn moduleNameFromPath(path: []const u8) []const u8 {
    return std.fs.path.basename(path);
}
