const std = @import("std");
const ast = @import("ast.zig");
const SourceManager = @import("source.zig").SourceManager;
const Source = @import("source.zig").Source;
const FileId = @import("source.zig").FileId;
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;
const Lexer = @import("lexer.zig");
const Parser = @import("parser.zig");
const Token = @import("token.zig").Token;
const symbol = @import("symbol.zig");

pub const Module = struct {
    allocator: std.mem.Allocator,
    name: []const u8,
    file_ids: std.ArrayList(FileId),
    asts: std.ArrayList(ast.Node),
    scopes: symbol.ScopeStack,
    errored: bool = false,
    pub fn init(allocator: std.mem.Allocator, name: []const u8) Module {
        return .{ .allocator = allocator, .name = name, .file_ids = .empty, .asts = .empty, .scopes = .empty };
    }
    pub fn deinit(s: *Module) void {
        s.file_ids.deinit(s.allocator);
        s.asts.deinit(s.allocator);
    }
    pub fn lex(s: *Module, sm: *SourceManager, d: *DiagnosticEmitter) !std.ArrayList(Token) {
        var toks = std.ArrayList(Token).empty;
        for (s.file_ids.items) |f| {
            var l = Lexer.init(&sm.sources.items[f], d);
            var breakout: u32 = 0;
            while (true) {
                const tok = l.next();
                try toks.append(s.allocator, tok);
                if (tok.tok_type == .eof) break;
                if (breakout == 200000) break;
                breakout += 1;
            }
        }
        return toks;
    }
    pub fn parse(s: *Module, sm: *SourceManager, d: *DiagnosticEmitter) !void {
        var pool: std.Thread.Pool = undefined;
        try pool.init(.{ .allocator = s.allocator });
        var wait = std.Thread.WaitGroup{};
        for (0..s.file_ids.items.len) |i| {
            wait.start();
            try pool.spawn(struct {
                pub fn parse_file(alloc: std.mem.Allocator, sources: *SourceManager, module: *Module, diag: *DiagnosticEmitter, m: *std.Thread.Mutex, idx: usize, wg: *std.Thread.WaitGroup) void {
                    defer wg.finish();
                    var p = Parser.init(alloc, &sources.sources.items[idx], diag);
                    const n = p.parse();
                    m.lock();
                    defer m.unlock();
                    if (n) |r| module.asts.append(alloc, r) catch {} else module.errored = true;
                }
            }.parse_file, .{ s.allocator, sm, s, d, &pool.mutex, i, &wait });
        }
        wait.wait();
    }
    pub fn check(s: *Module, sources: *SourceManager, d: *DiagnosticEmitter) !void {
        try s.parse(sources, d);
        if (d.err_count > 0) {
            d.print_all(sources);
            return;
        }
        s.scopes.push(s.allocator, symbol.Scope{ .type = .global, .symbols = .empty, .types = .empty });
        for (0..s.asts.items.len) |i| {
            if (s.scopes.current()) |*scope| {
                blk: switch (s.asts.items[i].type) {
                    .module => {},
                    .declaration => |decl| {
                        if (!decl.mut) {
                            if (decl.val) |v| {
                                if (v.type == .undefined) {
                                    d.emit(i, decl.name.span, .err, "Immutable declaration set to undefined, did you mean to make it mutable?", .{});
                                    break :blk;
                                }
                            } else {
                                d.emit(i, decl.name.span, .err, "Immutable declaration must have a value specified", .{});
                                break :blk;
                            }
                        }
                        scope.symbols.append(s.allocator, symbol.Symbol{
                            .mutability = if (decl.mut) .mutable else .immutable,
                            .name = decl.name.type.identifier,
                            .span = if (decl.type) |t| decl.name.span.fromSpan(t) else if (decl.type) |t| decl.name.span.fromSpan(t) else decl.name.span,
                            .kind = if(decl.type) |t| switch(t) {} else switch(decl.val) {} orelse .@"var",
                        }) catch {};
                    },
                    else => unreachable, // error out because we shouldnt have anything else
                }
            }
        }
    }
    // pub fn compile(s: *Module) void {}
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
            while (it.next()) |l| l.deinit(s.allocator);
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
                    try m.file_ids.append(s.allocator, file_id);
                } else {
                    const mod = try s.allocator.create(Module);
                    mod.* = Module.init(s.allocator, mn);
                    try s.module_cache.put(mn, mod);
                    try s.module_cache.get(mn).?.file_ids.append(s.allocator, file_id);
                }
            }
        }
    }
    fn find_module_name_in_src(s: *ModuleResolver, file_id: FileId) !?[]const u8 {
        var parser = Parser.init(s.allocator, &s.source_manager.sources.items[file_id], s.diags);
        const module_decl = try parser.module_declaration();
        return switch (module_decl.type) {
            .module => |m| m.name.type.identifier,
            else => null,
        };
    }
    fn determine_target_directory(s: *ModuleResolver, from: []const u8, import: []const u8) ![]u8 {
        const import_dir = std.fs.path.dirname(import) orelse ".";
        return std.fs.path.resolve(s.allocator, &[_][]const u8{ from, import_dir });
    }
};
