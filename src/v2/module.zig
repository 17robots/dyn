const std = @import("std");
const ast = @import("../../ast.zig");
const SourceManager = @import("../../common/source.zig").SourceManager;
const FileId = @import("../../common/source.zig").FileId;
const DiagnosticEmitter = @import("../../common/diagnostic.zig").DiagnosticEmitter;
const Lexer = @import("../../lexer.zig");
const Parser = @import("../../parser.zig");

pub const Module = struct {
    name: []const u8,
    file_ids: std.ArrayList(FileId),
    asts: std.ArrayList(ast.Node),
    pub fn init(allocator: std.mem.Allocator, name: []const u8) Module {
        return .{ .name = name, .file_ids = std.ArrayList(FileId).init(allocator), .asts = std.ArrayList(ast.Node).init(allocator) };
    }
    pub fn deinit(s: *Module) void {
        s.file_ids.deinit();
        s.asts.deinit();
    }
};

pub const ModuleResolver = struct {
    allocator: std.mem.Allocator,
    source_manager: *SourceManager,
    diags: *DiagnosticEmitter,
    module_cache: std.StringHashMap(*Module),

    pub fn init(allocator: std.mem.Allocator, source_manager: *SourceManager, diags: *DiagnosticEmitter) ModuleResolver {
        return .{ .allocator = allocator, .source_manager = source_manager, .diags = diags, .module_cache = std.StringHashMap(*Module).init(allocator) };
    }
    pub fn deinit(s: *ModuleResolver) void {
        var it = s.module_cache.valueIterator();
        while (it.next()) |module| {
            module.deinit();
            s.allocator.destroy(module);
        }
        s.module_cache.deinit();
    }
    pub fn resolveModule(s: *ModuleResolver, from_path: []const u8, import_str: []const u8) !*Module {
        const target_dir_path = try s.determine_target_directory(from_path, import_str);
        defer s.allocator.free(target_dir_path);
        const module_name = std.fs.path.basename(import_str);
        const qualified_name = try std.fmt.allocPrint(s.allocator, "{s}/{s}", .{ std.fs.path.dirname(import_str), module_name });
        defer s.allocator.free(qualified_name);
        if (s.module_cache.get(qualified_name)) |m| return m;
        try s.scan_dir_for_modules(target_dir_path);
        if (s.module_cache.get(qualified_name)) |m| return m;
        s.diags.emit(); //  not found module
        return error.ModuleNotFound;
    }
    fn scan_dir_for_modules(s: *ModuleResolver, dir_path: []const u8) !void {
        var module_files_map = std.StringHashMap(std.ArrayList(FileId)).init(s.allocator);
        defer {
            var it = module_files_map.valueIterator();
            while (it.next()) |l| l.deinit();
            module_files_map.deinit();
        }
        var dir = std.fs.cwd().openDir(dir_path, .{ .iterate = true }) catch |err| {
            if (err == error.FileNotFound) return;
            return err;
        };
        defer dir.close();
        var iterator = dir.iterate();
        while (try iterator.next()) |entry| {
            if (entry.kind != .file or !std.mem.endsWith(u8, entry.name, ".dyn")) continue;
            const full_path = try std.fs.path.join(s.allocator, &[_][]const u8{ dir_path, entry.name });
            defer s.allocator.free(full_path);
            const file_id = try s.source_manager.load_file(full_path);
        }
    }
    fn find_module_name_in_src(s: *ModuleResolver, file_id: FileId) !?[]const u8 {
        const src = &s.source_manager.sources.items[file_id];
        const lexer = Lexer.init(file: *File)
    }
    fn determine_target_directory(s: *ModuleResolver, from: []const u8, import: []const u8) ![]u8 {
        const import_dir = std.fs.path.dirname(import) orelse ".";
        return std.fs.path.resolve(s.allocator, &[_][]const u8{ from, import_dir });
    }
};
