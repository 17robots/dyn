const std = @import("std");
const ast = @import("ast.zig");
const SourceManager = @import("source.zig").SourceManager;
const FileId = @import("source.zig").FileId;
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;
const Lexer = @import("lexer.zig");
const Parser = @import("parser.zig");
const Token = @import("token.zig").Token;

pub const Module = struct {
    allocator: std.mem.Allocator,
    name: []const u8,
    file_ids: std.ArrayList(FileId),
    asts: std.ArrayList(ast.Node),
    pub fn init(allocator: std.mem.Allocator, name: []const u8) Module {
        return .{ .allocator = allocator, .name = name, .file_ids = std.ArrayList(FileId).init(allocator), .asts = std.ArrayList(ast.Node).init(allocator) };
    }
    pub fn deinit(s: *Module) void {
        s.file_ids.deinit();
        s.asts.deinit();
    }
    pub fn lex(s: *Module, sm: *SourceManager, d: *DiagnosticEmitter) !std.ArrayList(Token) {
        var toks = std.ArrayList(Token).init(s.allocator);
        for (s.file_ids.items) |f| {
            var l = Lexer.init(&sm.sources.items[f], d);
            var breakout: u32 = 0;
            while (true) {
                const tok = l.next();
                try toks.append(tok);
                if (tok.tok_type == .eof) break;
                if (breakout == 200000) break;
                breakout += 1;
            }
        }
        return toks;
    }
    pub fn parse(s: *Module, sm: *SourceManager, d: *DiagnosticEmitter) !void {
        for (s.file_ids.items) |f| {
            var p = Parser.init(s.allocator, &sm.sources.items[f], d);
            if (p.parse()) |result| try s.asts.append(result);
        }
    }
};

pub const ModuleKey = struct { dir: []const u8, name: []const u8 };
pub const ModuleResolver = struct {
    allocator: std.mem.Allocator,
    source_manager: *SourceManager,
    diags: *DiagnosticEmitter,
    module_cache: std.AutoHashMap(ModuleKey, *Module),

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
        const import_dir = std.fs.path.dirname(import_str) orelse ".";
        const abs_dir = try std.fs.path.resolve(s.allocator, &[_][]const u8{ from_path, import_dir });
        defer s.allocator.free(abs_dir);
        const module_name = std.fs.path.basename(import_str);
        try s.scan_dir_for_modules(abs_dir);
        if (s.module_cache.get(module_name)) |m| return m;
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
            if (s.source_manager.sources.items[file_id].content.len == 0) continue;
            const mod_name = try s.find_module_name_in_src(file_id);
            if (mod_name) |mn| {
                if (s.module_cache.get(mn)) |m| {
                    try m.file_ids.append(file_id);
                } else {
                    const mod = try s.allocator.create(Module);
                    mod.* = Module.init(s.allocator, mn);
                    try s.module_cache.put(mn, mod);
                    try s.module_cache.get(mn).?.file_ids.append(file_id);
                }
            }
        }
    }
    fn find_module_name_in_src(s: *ModuleResolver, file_id: FileId) !?[]const u8 {
        var parser = Parser.init(s.allocator, &s.source_manager.sources.items[file_id], s.diags);
        const module_decl = try parser.module_declaration();
        return switch (module_decl) {
            .module => |m| m.name.identifier,
            else => null,
        };
    }
    fn determine_target_directory(s: *ModuleResolver, from: []const u8, import: []const u8) ![]u8 {
        const import_dir = std.fs.path.dirname(import) orelse ".";
        return std.fs.path.resolve(s.allocator, &[_][]const u8{ from, import_dir });
    }
};
