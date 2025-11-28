const std = @import("std");
const Checker = struct {
    m: *Module,
    d: *DiagnosticEmitter,
    sm: *FileManager,
    // global: *ScopedSymbolTable,
    dependency_graph: void,
};
const Compiler = struct {
    allocator: std.mem.Allocator,
    diagnostics: *DiagnosticEmitter,
    source_manager: *FileManager,
    module_resolver: *ModuleResolver,

    pub fn init(allocator: std.mem.Allocator, diagnostics: *DiagnosticEmitter, source_manager: *FileManager, module_resolver: *ModuleResolver) Compiler {
        return Compiler{ .allocator = allocator, .diagnostics = diagnostics, .source_manager = source_manager, .module_resolver = module_resolver };
    }
    pub fn compile(s: *Compiler, mod: []const u8, step: enum { lex, parse, check }) !void {
        var main_module = try s.module_resolver.resolveModule(".", mod);
        switch (step) {
            .lex => {
                const toks = try main_module.lex(s.source_manager, s.diagnostics);
                for (toks.items) |t| std.debug.print("Tok: {any}\n", .{t});
            },
            .parse => {
                try main_module.parse(s.source_manager, s.diagnostics);
                if (s.diagnostics.err_count > 0) {
                    s.diagnostics.print_all(s.source_manager);
                    return;
                }
                std.debug.print("We have: {any} valid asts\n", .{main_module.asts.items.len});
                for (main_module.asts.items) |a| {
                    for (a.type.program.declarations.items) |d| {
                        switch (d.type) {
                            .module => |m| std.debug.print("Module; {any}\n", .{m}),
                            .declaration => |decl| std.debug.print("Declaration; pub: {any}, mut: {any}, name: {any}, type: {any}, val: {any}\n", .{ decl.pub_, decl.mut, decl.name, decl.type, decl.val }),
                            else => {},
                        }
                    }
                }
            },
            .check => {
                try main_module.check(s.source_manager, s.diagnostics);
            },
        }
    }
};
const Diagnostic = struct {
    severity: Severity,
    location: FileLocation,
    message: []const u8,
};
const DiagnosticEmitter = struct {
    allocator: std.mem.Allocator,
    diagnostics: std.ArrayList(Diagnostic),
    err_count: usize = 0,
    pub fn init(allocator: std.mem.Allocator) DiagnosticEmitter {
        return .{ .allocator = allocator, .diagnostics = std.ArrayList(Diagnostic).empty };
    }
    pub fn deinit(s: *DiagnosticEmitter) void {
        for (s.diagnostics.items) |d| s.allocator.free(d.message);
        s.diagnostics.deinit();
    }
    pub fn emit(s: *DiagnosticEmitter, location: FileLocation, severity: Severity, comptime fmt: []const u8, args: anytype) void {
        if (severity == .err) s.err_count += 1;
        const msg = std.fmt.allocPrint(s.allocator, fmt, args) catch "out of memory";
        s.diagnostics.append(s.allocator, .{ .severity = severity, .location = location, .message = msg }) catch @panic("out of memory");
    }
    pub fn has_errors(s: DiagnosticEmitter) bool {
        return s.err_count > 0;
    }
    pub fn print_all(s: *DiagnosticEmitter, source_manager: *FileManager) void {
        var out_buf: [1024]u8 = undefined;
        var writer = std.fs.File.stderr().writer(&out_buf);
        const out = &writer.interface;
        for (s.diagnostics.items) |d| {
            const resolved = source_manager.resolve_location(d.location);
            out.print("{s}:{d}:{d}: {s}: {s}\n", .{ resolved.file_name, resolved.line, resolved.col, d.severity.to_string(), d.message }) catch {};
            out.flush() catch {};
        }
    }
};
const File = struct {
    id: FileId,
    name: []const u8,
    content: []const u8,
};
const FileId = u32;
const FileLocation = struct {
    file_id: FileId,
    span: Span,
    pub fn init(file_id: FileId, span: Span) FileLocation {
        return .{ .file_id = file_id, .span = span };
    }
    pub fn eql(s: *FileLocation, a: *FileLocation) bool {
        return s.file_id == a.file_id and s.span.start == a.span.start and s.span.end == s.span.end;
    }
};
const FileManager = struct {
    allocator: std.mem.Allocator,
    files: std.ArrayList(File),
    lookup: std.StringHashMap(FileId),
    pub fn init(allocator: std.mem.Allocator) FileManager {
        return .{ .allocator = allocator, .files = std.ArrayList(File).empty, .lookup = std.StringHashMap(FileId).init(allocator) };
    }
    pub fn deinit(s: *FileManager) void {
        s.lookup.deinit();
        for (s.files.items) |source| {
            s.allocator.free(source.name);
            s.allocator.free(source.content);
        }
        s.files.deinit();
    }
    pub fn load_file(s: *FileManager, path: []const u8) !FileId {
        if (s.lookup.get(path)) |fileid| return fileid;
        const file = try std.fs.cwd().openFile(path, .{ .mode = .read_only });
        defer file.close();
        const content = try file.readToEndAlloc(s.allocator, (try file.stat()).size);
        const file_id: FileId = @intCast(s.files.items.len);
        const owned_path = try s.allocator.dupe(u8, path);
        errdefer s.allocator.free(owned_path);
        try s.files.append(s.allocator, .{ .id = file_id, .name = owned_path, .content = content });
        try s.lookup.put(owned_path, file_id);
        return file_id;
    }
    pub fn resolve_location(s: *FileManager, loc: FileLocation) struct { file_name: []const u8, line: usize, col: usize } {
        const source = &s.files.items[loc.file_id];
        var line: usize = 1;
        var line_start_index: usize = 0;
        for (source.content[0..loc.span.start], 0..loc.span.start) |char, i| {
            if (char == '\n') {
                line += 1;
                line_start_index = i + 1;
            }
        }
        return .{ .file_name = source.name, .line = line, .col = loc.span.start - line_start_index + 1 };
    }
};
const Lexer = struct {
    diag: *DiagnosticEmitter,
    source: *File,
    idx: u32 = 0,
    errored: bool = false,

    pub fn init(source: *File, diag: *DiagnosticEmitter) Lexer {
        return Lexer{ .source = source, .diag = diag };
    }
    fn advance(s: *Lexer, n: u32) void {
        s.idx += n;
    }
    fn peek(s: *Lexer, n: usize) ?u8 {
        if (s.idx + n >= s.source.content.len) return null;
        return s.source.content[s.idx + n];
    }
    fn skipSpaces(s: *Lexer) void {
        while (s.idx < s.source.content.len) {
            switch (s.source.content[s.idx]) {
                ' ', '\t', '\n', '\r' => s.idx += 1,
                else => break,
            }
        }
    }
    fn is_alpha(c: u8) bool {
        return switch (c) {
            'a'...'z', 'A'...'Z', '_' => true,
            else => false,
        };
    }
    fn is_dec(c: u8) bool {
        return switch (c) {
            '0'...'9' => true,
            else => false,
        };
    }
    fn keyword_or_ident(s: *Lexer, start: u32, end: u32) Token {
        const word = s.source.content[start..end];
        const word_tok = switch (word.len) {
            1 => blk: {
                if (std.mem.eql(u8, word, "_")) break :blk TokenType.underscore;
                break :blk null;
            },
            2 => blk: {
                if (std.mem.eql(u8, word, "if")) break :blk TokenType.@"if";
                break :blk null;
            },
            3 => blk: {
                if (std.mem.eql(u8, word, "for")) break :blk TokenType.@"for";
                if (std.mem.eql(u8, word, "mod")) break :blk TokenType.module;
                if (std.mem.eql(u8, word, "mut")) break :blk TokenType.mut;
                if (std.mem.eql(u8, word, "pub")) break :blk TokenType.@"pub";
                if (std.mem.eql(u8, word, "try")) break :blk TokenType.@"try";
                if (std.mem.eql(u8, word, "use")) break :blk TokenType.use;
                break :blk null;
            },
            4 => blk: {
                if (std.mem.eql(u8, word, "comp")) break :blk TokenType.comp;
                if (std.mem.eql(u8, word, "else")) break :blk TokenType.@"else";
                if (std.mem.eql(u8, word, "enum")) break :blk TokenType.@"enum";
                if (std.mem.eql(u8, word, "null")) break :blk TokenType.null;
                if (std.mem.eql(u8, word, "true")) break :blk TokenType.true;
                if (std.mem.eql(u8, word, "type")) break :blk TokenType.type;
                if (std.mem.eql(u8, word, "void")) break :blk TokenType.void;
                break :blk null;
            },
            5 => blk: {
                if (std.mem.eql(u8, word, "break")) break :blk TokenType.@"break";
                if (std.mem.eql(u8, word, "catch")) break :blk TokenType.@"catch";
                if (std.mem.eql(u8, word, "defer")) break :blk TokenType.@"defer";
                if (std.mem.eql(u8, word, "error")) break :blk TokenType.@"error";
                if (std.mem.eql(u8, word, "false")) break :blk TokenType.false;
                if (std.mem.eql(u8, word, "match")) break :blk TokenType.match;
                break :blk null;
            },
            6 => blk: {
                if (std.mem.eql(u8, word, "inline")) break :blk TokenType.@"inline";
                if (std.mem.eql(u8, word, "module")) break :blk TokenType.module;
                if (std.mem.eql(u8, word, "packed")) break :blk TokenType.@"packed";
                if (std.mem.eql(u8, word, "return")) break :blk TokenType.@"return";
                if (std.mem.eql(u8, word, "struct")) break :blk TokenType.@"struct";
                break :blk null;
            },
            8 => blk: {
                if (std.mem.eql(u8, word, "comptime")) break :blk TokenType.comp;
                if (std.mem.eql(u8, word, "continue")) break :blk TokenType.@"continue";
                break :blk null;
            },
            9 => blk: {
                if (std.mem.eql(u8, word, "undefined")) break :blk TokenType.undefined;
                break :blk null;
            },
            else => null,
        };
        if (word_tok) |wt| {
            return s.tok(wt, null, start, end);
        } else {
            return s.tok(.identifier, word, start, end);
        }
    }
    fn read_ident(s: *Lexer) Token {
        const start = s.idx;
        s.advance(1);
        while (s.idx < s.source.content.len) : (s.idx += 1) {
            const c = s.source.content[s.idx];
            if (!is_alpha(c) and !is_dec(c)) break;
        }
        return s.keyword_or_ident(start, s.idx);
    }
    fn read_num_float_range(s: *Lexer) Token {
        const start = s.idx;
        while (s.idx < s.source.content.len and is_dec(s.source.content[s.idx])) s.advance(1);
        if (s.idx < s.source.content.len and s.source.content[s.idx] == '.') {
            if (s.peek(1)) |i| {
                if (i == '.') {
                    const end = s.idx;
                    return s.tok(.int, s.source.content[start..end], start, end);
                }
            }
            s.advance(1);
            while (s.idx < s.source.content.len and is_dec(s.source.content[s.idx])) s.advance(1);
            return s.tok(.float, s.source.content[start..s.idx], start, s.idx);
        }
        return s.tok(.int, s.source.content[start..s.idx], start, s.idx);
    }
    fn read_string(s: *Lexer) Token {
        const start = s.idx;
        s.advance(1);
        while (s.idx < s.source.content.len) : (s.advance(1)) {
            const c = s.source.content[s.idx];
            if (c == '\"') {
                const end = s.idx;
                s.advance(1);
                return s.tok(.string, s.source.content[start + 1 .. end], start, end);
            }
            if (c == '\\') {
                if (s.idx + 1 < s.source.content.len) s.idx += 1;
            }
        }
        s.diag.emit(.{ .file_id = s.source.id, .span = Span.from(start, s.idx) }, .err, "Unclosed string literal", .{});
        s.errored = true;
        return s.tok(.invalid, null, start, s.idx);
    }
    fn read_char(s: *Lexer) Token {
        const start = s.idx;
        s.advance(1);
        if (s.idx >= s.source.content.len) {
            s.diag.emit(.{ .file_id = s.source.id, .span = Span.from(start, s.idx) }, .err, "Unclosed characer literal", .{});
            s.errored = true;
            return s.tok(.invalid, null, start, s.idx);
        }
        if (s.source.content[s.idx] == '\\') {
            s.advance(1);
            if (s.idx >= s.source.content.len) {
                s.diag.emit(.{ .file_id = s.source.id, .span = Span.from(start, s.idx) }, .err, "Unclosed characer literal", .{});
                s.errored = true;
                return s.tok(.invalid, null, start, s.idx);
            }
            const esc = s.source.content[s.idx];
            switch (esc) {
                '\'', '\"', '?', '\\', 'a', 'b', 'f', 'n', 'r', 't', 'v' => {},
                else => {
                    s.diag.emit(.{ .file_id = s.source.id, .span = Span.from(start, s.idx) }, .err, "Invalid character escape {c}", .{esc});
                    s.errored = true;
                    return s.tok(.invalid, null, start, s.idx);
                },
            }
            s.advance(1);
        } else s.advance(1);
        if (s.idx >= s.source.content.len or s.source.content[s.idx] != '\'') {
            s.diag.emit(.{ .file_id = s.source.id, .span = Span.from(start, s.idx) }, .err, "Unclosed characer literal", .{});
            s.errored = true;
            return s.tok(.invalid, null, start, s.idx);
        }
        const end = s.idx;
        s.advance(1);
        return s.tok(.char, s.source.content[start..end], start, end);
    }
    fn skip_line_comment(s: *Lexer) void {
        while (s.idx < s.source.content.len and s.source.content[s.idx] != '\n') s.advance(1);
    }
    fn skip_block_comment(s: *Lexer) void {
        while (s.idx < s.source.content.len) {
            if (s.source.content[s.idx] == '*' and s.idx + 1 < s.source.content.len and s.source.content[s.idx + 1] == '/') {
                s.advance(2);
                return;
            }
            s.advance(1);
        }
        s.diag.emit(.{ .file_id = s.source.id, .span = Span.from(s.idx, s.idx) }, .err, "Unclosed comment", .{});
        s.errored = true;
        return;
    }
    fn read_compound_op(s: *Lexer, single: TokenType, pairs: []const struct { ch: u8, tok: TokenType }) Token {
        const start = s.idx;
        s.advance(1);
        if (s.idx < s.source.content.len) {
            const c1 = s.peek(0);
            for (pairs) |p| {
                if (c1) |c| {
                    if (c == p.ch) {
                        s.advance(1);
                        return s.tok(p.tok, null, start, s.idx);
                    }
                }
            }
        }
        return s.tok(single, null, start, s.idx);
    }
    pub fn next(s: *Lexer) Token {
        if (s.errored) return s.tok(.invalid, null, s.idx, s.idx);
        if (s.idx >= s.source.content.len) return s.tok(.eof, null, s.idx, s.idx);
        s.skipSpaces();
        if (s.idx >= s.source.content.len) return s.tok(.eof, null, s.idx, s.idx);
        const c = s.source.content[s.idx];
        switch (c) {
            '(' => {
                s.advance(1);
                return s.tok(.lparen, null, s.idx - 1, s.idx - 1);
            },
            ')' => {
                s.advance(1);
                return s.tok(.rparen, null, s.idx - 1, s.idx - 1);
            },
            '[' => {
                s.advance(1);
                return s.tok(.lbrack, null, s.idx - 1, s.idx - 1);
            },
            ']' => {
                s.advance(1);
                return s.tok(.rbrack, null, s.idx - 1, s.idx - 1);
            },
            '{' => {
                s.advance(1);
                return s.tok(.lbrace, null, s.idx - 1, s.idx - 1);
            },
            '}' => {
                s.advance(1);
                return s.tok(.rbrace, null, s.idx - 1, s.idx - 1);
            },
            ';' => {
                s.advance(1);
                return s.tok(.semicolon, null, s.idx - 1, s.idx - 1);
            },
            ',' => {
                s.advance(1);
                return s.tok(.comma, null, s.idx - 1, s.idx - 1);
            },
            '$', '_', 'a'...'z', 'A'...'Z' => return s.read_ident(),
            '0'...'9' => return s.read_num_float_range(),
            '.' => {
                const start = s.idx;
                s.advance(1);
                if (s.peek(0)) |p| {
                    if (p == '.') {
                        s.advance(1);
                        return s.tok(.dotdot, null, start, s.idx);
                    }
                    if (p == '?') {
                        s.advance(1);
                        return s.tok(.optional_deref, null, start, s.idx);
                    }
                    if (p == '*') {
                        s.advance(1);
                        return s.tok(.pointer_deref, null, start, s.idx);
                    }
                }
                return s.tok(.dot, null, start, s.idx);
            },
            '/' => {
                const start = s.idx;
                if (s.peek(1)) |p| {
                    if (p == '/') {
                        s.advance(2);
                        s.skip_line_comment();
                        return s.next();
                    }
                    if (p == '*') {
                        s.advance(2);
                        s.skip_block_comment();
                        return s.next();
                    }
                    if (p == '=') {
                        s.advance(2);
                        return s.tok(.diveq, null, start, s.idx);
                    }
                }
                s.advance(1);
                return s.tok(.div, null, start, s.idx - 1);
            },
            ':' => {
                const start = s.idx;
                s.advance(1);
                if (s.peek(0)) |p| {
                    if (p == '=') {
                        s.advance(1);
                        return s.tok(.walrus, null, start, s.idx);
                    }
                }
                return s.tok(.colon, null, start, s.idx);
            },
            '\"' => return s.read_string(),
            '\'' => return s.read_char(),
            '?' => return s.read_compound_op(.question, &.{.{ .ch = '?', .tok = .nullish }}),
            '+' => return s.read_compound_op(.add, &.{ .{ .ch = '+', .tok = .addadd }, .{ .ch = '=', .tok = .addeq } }),
            '-' => return s.read_compound_op(.sub, &.{ .{ .ch = '-', .tok = .subsub }, .{ .ch = '=', .tok = .subeq } }),
            '*' => return s.read_compound_op(.mul, &.{.{ .ch = '=', .tok = .muleq }}),
            '%' => return s.read_compound_op(.mod, &.{.{ .ch = '=', .tok = .modeq }}),
            '^' => return s.read_compound_op(.xor, &.{.{ .ch = '=', .tok = .xoreq }}),
            '~' => return s.read_compound_op(.flip, &.{.{ .ch = '=', .tok = .flipeq }}),
            '>' => return s.read_compound_op(.gt, &.{.{ .ch = '=', .tok = .gteq }}),
            '<' => return s.read_compound_op(.lt, &.{.{ .ch = '=', .tok = .lteq }}),
            '!' => return s.read_compound_op(.bang, &.{.{ .ch = '=', .tok = .bangeq }}),
            '=' => return s.read_compound_op(.eq, &.{ .{ .ch = '=', .tok = .eqeq }, .{ .ch = '>', .tok = .arrow } }),
            '|' => return s.read_compound_op(.@"or", &.{ .{ .ch = '=', .tok = .oreq }, .{ .ch = '|', .tok = .oror } }),
            '&' => return s.read_compound_op(.@"and", &.{ .{ .ch = '=', .tok = .andeq }, .{ .ch = '&', .tok = .andand } }),
            else => return s.tok(.invalid, null, s.idx, s.idx),
        }
    }
    fn tok(s: Lexer, t: TokenType, val: ?[]const u8, start: u32, end: u32) Token {
        return Token.init(t, s.source.id, val, start, end);
    }
};
const LiteralKind = enum {
    boolean,
    char,
    float,
    int,
    null,
    string,
    undefined,
    pub fn to_string(s: LiteralKind) []const u8 {
        return switch (s) {
            .string => "string",
            .int => "int",
            .float => "float",
            .boolean => "boolean",
            .char => "char",
            .null => "null",
            .undefined => "undefined",
        };
    }
};
const Module = struct {
    allocator: std.mem.Allocator,
    name: []const u8,
    file_ids: std.ArrayList(FileId),
    asts: std.ArrayList(Node),
    errored: bool = false,
    pub fn init(allocator: std.mem.Allocator, name: []const u8) Module {
        return .{ .allocator = allocator, .name = name, .file_ids = .empty, .asts = .empty, .scopes = .empty };
    }
    pub fn deinit(s: *Module) void {
        s.file_ids.deinit(s.allocator);
        s.asts.deinit(s.allocator);
    }
    pub fn lex(s: *Module, sm: *FileManager, d: *DiagnosticEmitter) !std.ArrayList(Token) {
        var toks = std.ArrayList(Token).empty;
        for (s.file_ids.items) |f| {
            var l = Lexer.init(&sm.files.items[f], d);
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
    pub fn parse(s: *Module, sm: *FileManager, d: *DiagnosticEmitter) !void {
        var pool: std.Thread.Pool = undefined;
        try pool.init(.{ .allocator = s.allocator });
        var wait = std.Thread.WaitGroup{};
        for (0..s.file_ids.items.len) |i| {
            wait.start();
            try pool.spawn(struct {
                pub fn parse_file(alloc: std.mem.Allocator, sources: *FileManager, module: *Module, diag: *DiagnosticEmitter, m: *std.Thread.Mutex, idx: usize, wg: *std.Thread.WaitGroup) void {
                    defer wg.finish();
                    var p = Parser.init(alloc, &sources.files.items[idx], diag);
                    const n = p.parse();
                    m.lock();
                    defer m.unlock();
                    if (n) |r| module.asts.append(alloc, r) catch {} else module.errored = true;
                }
            }.parse_file, .{ s.allocator, sm, s, d, &pool.mutex, i, &wait });
        }
        wait.wait();
    }
    pub fn check(s: *Module, sources: *FileManager, d: *DiagnosticEmitter) !void {
        _ = s;
        _ = sources;
        _ = d;
    }
    // pub fn compile(s: *Module) void {}
};
const ModuleResolver = struct {
    allocator: std.mem.Allocator,
    source_manager: *FileManager,
    diags: *DiagnosticEmitter,
    module_cache: std.StringHashMap(*Module),

    pub fn init(allocator: std.mem.Allocator, source_manager: *FileManager, diags: *DiagnosticEmitter) ModuleResolver {
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
            if (s.source_manager.files.items[file_id].content.len == 0) continue;
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
        var parser = Parser.init(s.allocator, &s.source_manager.files.items[file_id], s.diags);
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
const Mutability = enum { immutable, mutable };
const Node = struct { type: NodeType, span: Span };
const NodeType = union(enum) {
    add: void,
    addeq: void,
    @"and": void,
    andand: void,
    andeq: void,
    arm: struct { expressions: std.ArrayList(Node), capture: ?*Node, result: *Node },
    array_index: struct { name: *Node, index: *Node },
    array_init: struct { vals: std.ArrayList(Node) },
    array_type: struct { expression: *Node },
    arrow_expression: struct { expression: *Node },
    assign_expression: struct { left: *Node, op: *Node, right: *Node },
    bang: void,
    bangeq: void,
    binary: struct { a: *Node, op: *Node, b: *Node },
    block: struct { label: ?*Node, statements: std.ArrayList(Node) },
    break_expression: struct { label: ?*Node, val: ?*Node },
    call: struct { name: *Node, args: std.ArrayList(Node) },
    capture: struct { captures: std.ArrayList(Node) },
    capture_val: struct { mut: bool, val: *Node },
    catch_: struct { capture: ?*Node, expression: *Node, body: *Node },
    comp_expression: struct { expression: *Node },
    continue_expression: struct { label: ?*Node },
    declaration: struct { pub_: bool, mut: bool, name: *Node, type: ?*Node, val: ?*Node },
    defer_statement: struct { capture: ?*Node, body: *Node },
    div: void,
    diveq: void,
    enum_: struct { members: std.ArrayList(Node) },
    enum_error_init: struct { name: *Node, val: ?*Node },
    eq: void,
    eqeq: void,
    error_: struct { members: std.ArrayList(Node) },
    error_union_type: struct { errs: ?std.ArrayList(Node), name: *Node },
    for_statement: struct { inline_: bool, expressions: std.ArrayList(Node), capture: *Node, body: *Node },
    function: struct { inline_: bool, parameters: std.ArrayList(Node), result: *Node, body: *Node },
    function_parameter: struct { names: std.ArrayList(Node), type: *Node },
    function_type: struct { parameters: std.ArrayList(Node), result: ?*Node },
    grouped: struct { expression: ?*Node },
    gt: void,
    gte: void,
    identifier: []const u8,
    if_expression: struct { prefix: *Node, body: *Node, else_body: *Node },
    if_prefix: struct { expression: *Node, capture: ?*Node },
    if_statement: struct { prefix: *Node, body: *Node, else_body: ?*Node },
    literal: struct { kind: LiteralKind, val: []const u8 },
    lt: void,
    lte: void,
    match: struct { expression: *Node, arms: std.ArrayList(Node) },
    member: struct { names: std.ArrayList(Node), type: ?*Node, val: ?*Node },
    member_access: struct { name: *Node, member: *Node },
    member_basic: struct { names: std.ArrayList(Node), type: ?*Node },
    mod: void,
    modeq: void,
    module: struct { name: *Node },
    mul: void,
    muleq: void,
    nullish: void,
    nullish_expression: struct { a: *Node, b: *Node },
    optional_dereference: struct { expression: *Node },
    optional_type: struct { expression: *Node },
    @"or": void,
    oreq: void,
    oror: void,
    pointer_dereference: struct { expression: *Node },
    pointer_type: struct { expression: *Node, mut: bool },
    program: struct { declarations: std.ArrayList(Node) },
    range_expression: struct { a: *Node, b: *Node },
    return_expression: struct { val: ?*Node },
    struct_: struct { members: std.ArrayList(Node) },
    struct_init: struct { name: ?*Node, inits: std.ArrayList(Node) },
    struct_init_member: struct { name: *Node, val: *Node },
    sub: void,
    subeq: void,
    try_: struct { expression: *Node },
    type: void,
    unary: struct { op: *Node, b: *Node },
    undefined: void,
    underscore: void,
    use: struct { path: *Node },
    void: void,
    xor: void,
    xoreq: void,
};
const Parser = struct {
    const ParserError = error{
        recoverable,
        fatal,
    };

    allocator: std.mem.Allocator,
    diag: *DiagnosticEmitter,
    lexer: Lexer,
    source: *File,
    curr_tok: Token,
    next_tok: Token,
    peek_tok: Token,

    pub fn init(allocator: std.mem.Allocator, source: *File, diagnostics: *DiagnosticEmitter) Parser {
        var parser = Parser{ .allocator = allocator, .source = source, .lexer = Lexer.init(source, diagnostics), .diag = diagnostics, .curr_tok = undefined, .next_tok = undefined, .peek_tok = undefined };
        parser.advance();
        parser.advance();
        parser.advance();
        return parser;
    }
    pub fn module_declaration(s: *Parser) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        try s.expect(.module);
        const name = s.create_node_ptr(try s.identifier());
        return node(NodeType{ .module = .{ .name = name } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    pub fn parse(s: *Parser) ?Node {
        const span_start = s.curr_tok.loc.span;
        const module_decl = s.module_declaration() catch return null;
        s.expect(.semicolon) catch return null;
        var declarations = std.ArrayList(Node).empty;
        declarations.append(s.allocator, module_decl) catch |e| @panic(@errorName(e));
        blk: while (s.curr_tok.tok_type != .eof) {
            declarations.append(s.allocator, s.declaration(true) catch |e| switch (e) {
                error.recoverable => {
                    s.sync(&[_]TokenType{.semicolon});
                    continue :blk;
                },
                error.fatal => return null,
            }) catch |e| @panic(@errorName(e));
            s.expect(.semicolon) catch return null;
        }
        return node(NodeType{ .program = .{ .declarations = declarations } }, span_start.fromSpan(s.curr_tok.loc.span));
    }

    fn arm(s: *Parser, expr: bool) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        var exprs = std.ArrayList(Node).empty;
        while (s.curr_tok.tok_type != .eof) {
            if (s.curr_tok.tok_type == .colon) break;
            exprs.append(s.allocator, try s.expression(0)) catch |e| @panic(@errorName(e));
            if (s.curr_tok.tok_type == .colon) break;
            try s.expect(.comma);
        }
        try s.expect(.colon);
        const cap = if (s.curr_tok.tok_type == .@"or") s.create_node_ptr(try s.capture()) else null;
        const e = s.create_node_ptr(if (expr) try s.result_block_expression() else try s.result_block());
        return node(NodeType{ .arm = .{
            .expressions = exprs,
            .capture = cap,
            .result = e,
        } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    fn assign_expression(s: *Parser, n: Node) ParserError!Node {
        const a = s.create_node_ptr(n);
        const op: Node = switch (s.curr_tok.tok_type) {
            .addeq => node(NodeType.addeq, s.curr_tok.loc.span),
            .subeq => node(NodeType.subeq, s.curr_tok.loc.span),
            .muleq => node(NodeType.muleq, s.curr_tok.loc.span),
            .diveq => node(NodeType.diveq, s.curr_tok.loc.span),
            .modeq => node(NodeType.modeq, s.curr_tok.loc.span),
            .andeq => node(NodeType.andeq, s.curr_tok.loc.span),
            .oreq => node(NodeType.oreq, s.curr_tok.loc.span),
            .xoreq => node(NodeType.xoreq, s.curr_tok.loc.span),
            .eq => node(NodeType.eq, s.curr_tok.loc.span),
            else => {
                s.diag.emit(.{ .file_id = s.source.id, .span = s.curr_tok.loc.span }, .err, "Invalid assign operator {any}", .{s.curr_tok.tok_type});
                return ParserError.recoverable;
            },
        };
        try s.expect(s.curr_tok.tok_type);
        const expr = s.create_node_ptr(try s.expression(0));
        return node(NodeType{ .assign_expression = .{ .left = a, .op = s.create_node_ptr(op), .right = expr } }, n.span.fromSpan(s.curr_tok.loc.span));
    }
    fn block(s: *Parser, labeled: bool) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        const label = if (labeled) blk: {
            break :blk if (s.curr_tok.tok_type == .identifier) blk2: {
                const lbl = s.create_node_ptr(try s.identifier());
                try s.expect(.colon);
                break :blk2 lbl;
            } else null;
        } else null;
        try s.expect(.lbrace);
        var stmts = std.ArrayList(Node).empty;
        blk: while (s.curr_tok.tok_type != .eof) {
            if (s.curr_tok.tok_type == .rbrace) break;
            const stmt = s.statement() catch |e| switch (e) {
                ParserError.recoverable => {
                    s.sync(&[_]TokenType{ .rbrace, .semicolon });
                    continue :blk;
                },
                ParserError.fatal => return e,
            };
            if (should_read_semicolon(stmt)) try s.expect(.semicolon);
            stmts.append(s.allocator, stmt) catch |e| @panic(@errorName(e));
            if (s.curr_tok.tok_type == .rbrace) break;
        }
        try s.expect(.rbrace);
        return node(NodeType{ .block = .{ .label = label, .statements = stmts } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    fn catch_(s: *Parser, n: Node) ParserError!Node {
        try s.expect(.@"catch");
        const cap = if (s.curr_tok.tok_type == .@"or") s.create_node_ptr(try s.capture()) else null;
        const body = s.create_node_ptr(if (s.curr_tok.tok_type == .lbrace) try s.result_block() else try s.result_block_expression());
        return node(NodeType{ .catch_ = .{ .expression = s.create_node_ptr(n), .capture = cap, .body = body } }, n.span.fromSpan(s.curr_tok.loc.span));
    }
    fn capture(s: *Parser) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        try s.expect(.@"or");
        var captures = std.ArrayList(Node).empty;
        while (s.curr_tok.tok_type != .eof) {
            if (s.curr_tok.tok_type == .@"or") break;
            captures.append(s.allocator, try s.capture_item()) catch |e| @panic(@errorName(e));
            if (s.curr_tok.tok_type == .@"or") break;
            try s.expect(.comma);
        }
        try s.expect(.@"or");
        return node(NodeType{ .capture = .{ .captures = captures } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    fn capture_item(s: *Parser) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        const mut = if (s.curr_tok.tok_type == .mut) blk: {
            try s.expect(.mut);
            break :blk true;
        } else false;
        const val = s.create_node_ptr(try s.identifier());
        return node(NodeType{ .capture_val = .{ .mut = mut, .val = val } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    fn comp_expression(s: *Parser) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        try s.expect(.comp);
        const expr = s.create_node_ptr(try s.non_literal_expression());
        return node(NodeType{ .comp_expression = .{ .expression = expr } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    fn declaration(s: *Parser, global_decl: bool) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        const pub_ = if (global_decl) blk: {
            break :blk if (s.curr_tok.tok_type == .@"pub") blk2: {
                try s.expect(.@"pub");
                break :blk2 true;
            } else false;
        } else false;
        const mut = if (s.curr_tok.tok_type == .mut) blk: {
            try s.expect(.mut);
            break :blk true;
        } else false;
        const name = s.create_node_ptr(try s.identifier());
        const type_ = switch (s.curr_tok.tok_type) {
            .walrus, .semicolon => null,
            .colon => blk: {
                try s.expect(.colon);
                break :blk s.create_node_ptr(try s.non_literal_expression());
            },
            else => {
                s.diag.emit(.{ .file_id = s.source.id, .span = s.curr_tok.loc.span }, .err, "Invalid declaration symbol {any}, wanted := or : [Type]", .{s.curr_tok.tok_type});
                return ParserError.recoverable;
            },
        };
        const val = switch (s.curr_tok.tok_type) {
            .walrus, .eq => blk: {
                try s.expect(s.curr_tok.tok_type);
                break :blk s.create_node_ptr(try s.expression(0));
            },
            else => null,
        };
        return node(NodeType{ .declaration = .{ .pub_ = pub_, .mut = mut, .name = name, .type = type_, .val = val } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    fn defer_statement(s: *Parser) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        try s.expect(.@"defer");
        const cap = if (s.curr_tok.tok_type == .@"or") s.create_node_ptr(try s.capture()) else null;
        const body = s.create_node_ptr(try s.result_block());
        return node(NodeType{ .defer_statement = .{ .capture = cap, .body = body } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    fn enum_error_initialization(s: *Parser) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        const name = s.create_node_ptr(try s.identifier());
        const val = if (s.curr_tok.tok_type == .lparen) blk: {
            try s.expect(.lparen);
            const v = s.create_node_ptr(try s.expression(0));
            try s.expect(.rparen);
            break :blk v;
        } else null;
        return node(NodeType{ .enum_error_init = .{ .name = name, .val = val } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    fn error_union_type(s: *Parser, n: Node) ParserError!Node {
        const main_type = s.create_node_ptr(n);
        try s.expect(.bang);
        var errs = std.ArrayList(Node).empty;
        while (s.curr_tok.tok_type != .eof) {
            if (s.curr_tok.tok_type != .identifier) break;
            errs.append(s.allocator, try s.identifier()) catch |e| @panic(@errorName(e));
            if (s.curr_tok.tok_type != .bang) break;
            try s.expect(.bang);
        }
        return node(NodeType{ .error_union_type = .{ .errs = errs, .name = main_type } }, n.span.fromSpan(s.curr_tok.loc.span));
    }
    fn expression(s: *Parser, prec: u8) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        switch (s.curr_tok.tok_type) {
            .underscore => {
                try s.expect(.underscore);
                return node(NodeType.underscore, s.curr_tok.loc.span);
            },
            .use => return s.use_expression(),
            else => {},
        }
        var expr = switch (s.curr_tok.tok_type) {
            .int, .float, .string, .char, .true, .false, .undefined, .null => try s.literal(),
            .bang, .flip, .sub, .@"and" => try s.unary_expression(),
            else => try s.non_literal_expression(),
        };
        switch (s.curr_tok.tok_type) {
            .dotdot => return try s.range_expression(expr),
            .addeq, .andeq, .diveq, .flipeq, .modeq, .muleq, .subeq, .xoreq, .eq => return try s.assign_expression(expr),
            else => {},
        }
        while (s.curr_tok.tok_type != .eof and prec < s.precedence()) {
            if (s.curr_tok.tok_type == .dotdot) return try s.range_expression(expr);
            const new_prec = s.precedence();
            switch (s.curr_tok.tok_type) {
                .add, .@"and", .andand, .bang, .bangeq, .div, .eqeq, .gt, .gteq, .lt, .lteq, .mod, .mul, .nullish, .@"or", .oror, .sub, .xor => {},
                else => return expr,
            }
            const op = s.create_node_ptr(try s.operator());
            expr = node(NodeType{ .binary = .{ .a = s.create_node_ptr(expr), .op = op, .b = s.create_node_ptr(try s.expression(new_prec)) } }, span_start.fromSpan(s.curr_tok.loc.span));
        }
        return expr;
    }
    fn function(s: *Parser) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        const inline_ = if (s.curr_tok.tok_type == .@"inline") blk: {
            try s.expect(.@"inline");
            break :blk true;
        } else false;
        var fn_decl = true;
        var fn_parameters = std.ArrayList(Node).empty;
        var types = std.ArrayList(Node).empty;
        try s.expect(.lparen);
        while (s.curr_tok.tok_type != .eof) {
            var span_start2 = s.curr_tok.loc.span;
            if (s.curr_tok.tok_type == .rparen) break;
            if (fn_decl) {
                if (s.curr_tok.tok_type == .identifier) {
                    types.append(s.allocator, try s.identifier()) catch |e| @panic(@errorName(e));
                    if (s.curr_tok.tok_type == .colon) {
                        try s.expect(.colon);
                        const the_type = s.create_node_ptr(try s.non_literal_expression());
                        fn_parameters.append(s.allocator, node(NodeType{ .function_parameter = .{ .names = types.clone(s.allocator) catch |e| @panic(@errorName(e)), .type = the_type } }, span_start2.fromSpan(s.curr_tok.loc.span))) catch |e| @panic(@errorName(e));
                        types.deinit(s.allocator);
                        types = std.ArrayList(Node).empty;
                        span_start2 = s.curr_tok.loc.span;
                    }
                } else {
                    fn_decl = false;
                    continue;
                }
            } else {
                types.append(s.allocator, try s.non_literal_expression()) catch |e| @panic(@errorName(e));
                if (s.curr_tok.tok_type == .colon) {
                    s.diag.emit(.{ .file_id = s.source.id, .span = span_start2 }, .err, "", .{});
                    return ParserError.recoverable;
                }
            }
            if (s.curr_tok.tok_type == .rparen) break;
            try s.expect(.comma);
        }
        try s.expect(.rparen);
        var return_expr = switch (s.curr_tok.tok_type) {
            .identifier => blk: {
                if (s.next_tok.tok_type == .colon) break :blk try s.block(true);
                const chain = try s.identifier();
                break :blk try s.postfix_chain(chain, false);
            },
            else => try s.non_literal_expression(),
        };
        if (s.curr_tok.tok_type == .bang) return_expr = try s.error_union_type(return_expr);
        const body = switch (s.curr_tok.tok_type) {
            .arrow => blk: {
                const span_start2 = s.curr_tok.loc.span;
                try s.expect(.arrow);
                const expr = s.create_node_ptr(try s.expression(0));
                break :blk s.create_node_ptr(node(NodeType{ .arrow_expression = .{ .expression = expr } }, span_start2.fromSpan(s.curr_tok.loc.span)));
            },
            .lbrace => s.create_node_ptr(try s.block(false)),
            else => null,
        };
        if (fn_decl) {
            if (body) |b| {
                if (types.items.len > 0) {
                    s.diag.emit(.{ .file_id = s.source.id, .span = s.curr_tok.loc.span }, .err, "Identifiers missing type in function declaration", .{});
                    return ParserError.recoverable;
                }
                return node(NodeType{ .function = .{ .inline_ = inline_, .parameters = fn_parameters, .result = s.create_node_ptr(return_expr), .body = b } }, span_start.fromSpan(s.curr_tok.loc.span));
            }
            if (fn_parameters.items.len > 0) {
                s.diag.emit(.{ .file_id = s.source.id, .span = span_start }, .err, "Function declaration requires a body", .{});
                return ParserError.recoverable;
            }
            if (inline_) {
                s.diag.emit(.{ .file_id = s.source.id, .span = span_start }, .err, "Inline cannot be applied to function types", .{});
                return ParserError.recoverable;
            }
            return node(NodeType{ .function_type = .{ .parameters = types, .result = s.create_node_ptr(return_expr) } }, span_start.fromSpan(s.curr_tok.loc.span));
        }
        if (body) |b| {
            s.diag.emit(.{ .file_id = s.source.id, .span = b.span }, .err, "Function types should not have a body", .{});
            return ParserError.recoverable;
        }
        if (fn_parameters.items.len > 0) {
            s.diag.emit(.{ .file_id = s.source.id, .span = span_start }, .err, "Function declaration has types without corresponding identifiers", .{});
            return ParserError.recoverable;
        }
        if (inline_) {
            s.diag.emit(.{ .file_id = s.source.id, .span = span_start }, .err, "Inline cannot be applied to function types", .{});
            return ParserError.recoverable;
        }
        return node(NodeType{ .function_type = .{ .parameters = types, .result = s.create_node_ptr(return_expr) } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    fn identifier(s: *Parser) ParserError!Node {
        if (s.curr_tok.val) |v| {
            const span_start = s.curr_tok.loc.span;
            const val = v;
            try s.expect(.identifier);
            return node(NodeType{ .identifier = val }, span_start.fromSpan(s.curr_tok.loc.span));
        } else return ParserError.fatal;
    }
    fn if_prefix(s: *Parser) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        try s.expect(.@"if");
        const expr = s.create_node_ptr(try s.expression(0));
        try s.expect(.colon);
        const cap = if (s.curr_tok.tok_type == .@"or") s.create_node_ptr(try s.capture()) else null;
        return node(NodeType{ .if_prefix = .{ .capture = cap, .expression = expr } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    fn literal(s: *Parser) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        const lit_kind = switch (s.curr_tok.tok_type) {
            .int => LiteralKind.int,
            .float => LiteralKind.float,
            .true, .false => LiteralKind.boolean,
            .char => LiteralKind.char,
            .string => LiteralKind.string,
            .undefined => LiteralKind.undefined,
            .null => LiteralKind.null,
            else => {
                s.diag.emit(.{ .file_id = s.source.id, .span = s.curr_tok.loc.span }, .err, "Invalid literal {any}", .{s.curr_tok.tok_type});
                return ParserError.recoverable;
            },
        };
        const val = switch (s.curr_tok.tok_type) {
            .true => "true",
            .false => "false",
            .null, .undefined => "",
            else => s.curr_tok.val.?,
        };
        try s.expect(s.curr_tok.tok_type);
        return node(NodeType{ .literal = .{ .kind = lit_kind, .val = val } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    fn match(s: *Parser, is_expr: bool) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        try s.expect(.match);
        const expr = s.create_node_ptr(try s.expression(0));
        try s.expect(.colon);
        try s.expect(.lbrace);
        var arms = std.ArrayList(Node).empty;
        blk: while (s.curr_tok.tok_type != .eof) {
            if (s.curr_tok.tok_type == .rbrace) break :blk;
            arms.append(s.allocator, s.arm(is_expr) catch |e| switch (e) {
                ParserError.recoverable => {
                    s.sync(&[_]TokenType{ .comma, .rbrace });
                    continue :blk;
                },
                ParserError.fatal => return e,
            }) catch |e| @panic(@errorName(e));
            if (s.curr_tok.tok_type == .rbrace) break :blk;
            try s.expect(.comma);
        }
        try s.expect(.rbrace);
        return node(NodeType{ .match = .{ .expression = expr, .arms = arms } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    fn non_literal_expression(s: *Parser) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        var expr: Node = switch (s.curr_tok.tok_type) {
            .comp => return s.comp_expression(),
            .dot => blk: {
                try s.expect(.dot);
                break :blk try s.enum_error_initialization();
            },
            .@"enum" => blk: {
                try s.expect(.@"enum");
                try s.expect(.lbrace);
                var members = std.ArrayList(Node).empty;
                while (s.curr_tok.tok_type != .eof) {
                    if (s.curr_tok.tok_type == .rbrace) break;
                    members.append(s.allocator, try s.member(false)) catch |e| @panic(@errorName(e));
                    if (s.curr_tok.tok_type == .rbrace) break;
                    try s.expect(.comma);
                }
                try s.expect(.rbrace);
                break :blk node(NodeType{ .enum_ = .{ .members = members } }, span_start.fromSpan(s.curr_tok.loc.span));
            },
            .@"error" => blk: {
                try s.expect(.@"error");
                try s.expect(.lbrace);
                var members = std.ArrayList(Node).empty;
                while (s.curr_tok.tok_type != .eof) {
                    if (s.curr_tok.tok_type == .rbrace) break;
                    members.append(s.allocator, try s.member_basic()) catch |e| @panic(@errorName(e));
                    if (s.curr_tok.tok_type == .rbrace) break;
                    try s.expect(.comma);
                }
                try s.expect(.rbrace);
                break :blk node(NodeType{ .error_ = .{ .members = members } }, span_start.fromSpan(s.curr_tok.loc.span));
            },
            .identifier => blk: {
                if (s.next_tok.tok_type == .lbrace) break :blk try s.struct_initialization(null);
                break :blk try s.postfix_chain(try s.identifier(), true);
            },
            .@"if" => blk: {
                const prefix = s.create_node_ptr(try s.if_prefix());
                const body = s.create_node_ptr(try s.result_block_expression());
                break :blk node(NodeType{ .if_expression = .{ .prefix = prefix, .body = body, .else_body = blk2: {
                    try s.expect(.@"else");
                    break :blk2 s.create_node_ptr(try s.result_block_expression());
                } } }, span_start.fromSpan(s.curr_tok.loc.span));
            },
            .lbrace => blk: {
                var chain = try s.struct_initialization(null);
                if (s.curr_tok.tok_type == .dot) {
                    try s.expect(.dot);
                    chain = node(NodeType{ .member_access = .{ .name = s.create_node_ptr(chain), .member = s.create_node_ptr(try s.identifier()) } }, span_start.fromSpan(s.curr_tok.loc.span));
                    break :blk try s.postfix_chain(chain, true);
                }
                break :blk chain;
            },
            .lbrack => blk: {
                if (s.curr_tok.tok_type == .lbrack and s.next_tok.tok_type == .rbrack) {
                    switch (s.peek_tok.tok_type) {
                        .identifier, .lbrack, .@"struct", .@"enum", .@"error", .lparen, .@"if", .mul, .question => {
                            try s.expect(.lbrack);
                            try s.expect(.rbrack);
                            break :blk node(NodeType{ .array_type = .{ .expression = s.create_node_ptr(try s.non_literal_expression()) } }, span_start.fromSpan(s.curr_tok.loc.span));
                        },
                        else => {
                            try s.expect(.lbrack);
                            var vals = std.ArrayList(Node).empty;
                            while (s.curr_tok.tok_type != .eof) {
                                if (s.curr_tok.tok_type == .rbrack) break;
                                vals.append(s.allocator, try s.expression(0)) catch |e| @panic(@errorName(e));
                                if (s.curr_tok.tok_type == .rbrack) break;
                                try s.expect(.comma);
                            }
                            try s.expect(.rbrack);
                            break :blk node(NodeType{ .array_init = .{ .vals = vals } }, span_start.fromSpan(s.curr_tok.loc.span));
                        },
                    }
                } else {
                    try s.expect(.lbrack);
                    var vals = std.ArrayList(Node).empty;
                    while (s.curr_tok.tok_type != .eof) {
                        if (s.curr_tok.tok_type == .rbrack) break;
                        vals.append(s.allocator, try s.expression(0)) catch |e| @panic(@errorName(e));
                        if (s.curr_tok.tok_type == .rbrack) break;
                        try s.expect(.comma);
                    }
                    try s.expect(.rbrack);
                    break :blk node(NodeType{ .array_init = .{ .vals = vals } }, span_start.fromSpan(s.curr_tok.loc.span));
                }
            },
            .lparen, .@"inline" => blk: {
                var chain: Node = undefined;
                const is_fn: bool = s.curr_tok.tok_type == .@"inline" or switch (s.next_tok.tok_type) {
                    .comp => true,
                    .identifier => s.peek_tok.tok_type == .colon or s.peek_tok.tok_type == .comma, // return fn,
                    .rparen => switch (s.peek_tok.tok_type) {
                        .lparen, .mul, .identifier, .@"struct", .@"enum", .@"error", .lbrack, .question, .void, .comp, .type => true, // return
                        else => false,
                    },
                    else => false,
                };
                if (is_fn) {
                    chain = try s.function();
                    if (chain.type == .function_type) break :blk chain;
                    if (s.curr_tok.tok_type != .lparen) break :blk chain;
                    try s.expect(.lparen);
                    var call_args = std.ArrayList(Node).empty;
                    while (s.curr_tok.tok_type != .eof) {
                        if (s.curr_tok.tok_type == .rparen) break;
                        call_args.append(s.allocator, try s.expression(0)) catch |e| @panic(@errorName(e));
                        if (s.curr_tok.tok_type == .rparen) break;
                        try s.expect(.comma);
                    }
                    try s.expect(.rparen);
                    chain = node(.{ .call = .{ .name = s.create_node_ptr(chain), .args = call_args } }, span_start.fromSpan(s.curr_tok.loc.span));
                    break :blk try s.postfix_chain(chain, true);
                }
                try s.expect(.lparen);
                const expr = switch (s.curr_tok.tok_type) {
                    .identifier => switch (s.next_tok.tok_type) {
                        .colon => s.create_node_ptr(try s.block(true)),
                        else => s.create_node_ptr(try s.expression(0)),
                    },
                    .rparen => null,
                    else => s.create_node_ptr(try s.expression(0)),
                };
                try s.expect(.rparen);
                chain = node(NodeType{ .grouped = .{ .expression = expr } }, span_start.fromSpan(s.curr_tok.loc.span));
                break :blk try s.postfix_chain(chain, true);
            },
            .match => try s.match(true),
            .mul => blk: {
                try s.expect(.mul);
                const mut = if (s.curr_tok.tok_type == .mut) blk2: {
                    try s.expect(.mut);
                    break :blk2 true;
                } else false;
                break :blk node(NodeType{ .pointer_type = .{ .expression = s.create_node_ptr(try s.non_literal_expression()), .mut = mut } }, span_start.fromSpan(s.curr_tok.loc.span));
            },
            .question => blk: {
                try s.expect(.question);
                break :blk node(NodeType{ .optional_type = .{ .expression = s.create_node_ptr(try s.non_literal_expression()) } }, span_start.fromSpan(s.curr_tok.loc.span));
            },
            .@"struct" => blk: {
                try s.expect(.@"struct");
                try s.expect(.lbrace);
                var members = std.ArrayList(Node).empty;
                while (s.curr_tok.tok_type != .eof) {
                    if (s.curr_tok.tok_type == .rbrace) break;
                    members.append(s.allocator, try s.member(true)) catch |e| @panic(@errorName(e));
                    if (s.curr_tok.tok_type == .rbrace) break;
                    try s.expect(.comma);
                }
                try s.expect(.rbrace);
                break :blk node(NodeType{ .struct_ = .{ .members = members } }, span_start.fromSpan(s.curr_tok.loc.span));
            },
            .@"try" => blk: {
                try s.expect(.@"try");
                break :blk node(NodeType{ .try_ = .{ .expression = s.create_node_ptr(try s.non_literal_expression()) } }, span_start.fromSpan(s.curr_tok.loc.span));
            },
            .type => blk: {
                try s.expect(.type);
                break :blk node(NodeType.type, span_start.fromSpan(s.curr_tok.loc.span));
            },
            .undefined => blk: {
                try s.expect(.undefined);
                break :blk node(NodeType.undefined, span_start.fromSpan(s.curr_tok.loc.span));
            },
            .void => blk: {
                try s.expect(.void);
                break :blk node(NodeType.void, span_start.fromSpan(s.curr_tok.loc.span));
            },
            else => {
                s.diag.emit(.{ .file_id = s.source.id, .span = s.curr_tok.loc.span }, .err, "Invalid non literal expression {any}", .{s.curr_tok.tok_type});
                return ParserError.recoverable;
            },
        };
        switch (expr.type) {
            .array_index, .array_type, .catch_, .enum_, .error_, .identifier, .grouped, .if_expression, .member_access, .optional_dereference, .optional_type, .pointer_dereference, .pointer_type, .struct_, .try_ => {
                if (s.curr_tok.tok_type == .bang) expr = try s.error_union_type(expr);
            },
            .block => |i| {
                if (i.label) |_| {
                    if (s.curr_tok.tok_type == .bang) expr = try s.error_union_type(expr);
                } else {
                    s.diag.emit(.{ .file_id = s.source.id, .span = span_start }, .err, "Blocks must have labels to be used as expression", .{});
                    return ParserError.recoverable;
                }
            },
            .call => {
                if (s.curr_tok.tok_type == .@"catch") expr = try s.catch_(expr);
                if (s.curr_tok.tok_type == .bang) expr = try s.error_union_type(expr);
            },
            else => {},
        }
        return expr;
    }
    fn operator(s: *Parser) ParserError!Node {
        const op: Node = switch (s.curr_tok.tok_type) {
            .add => node(NodeType.add, s.curr_tok.loc.span),
            .@"and" => node(NodeType.@"and", s.curr_tok.loc.span),
            .andand => node(NodeType.andand, s.curr_tok.loc.span),
            .bang => node(NodeType.bang, s.curr_tok.loc.span),
            .bangeq => node(NodeType.bangeq, s.curr_tok.loc.span),
            .div => node(NodeType.div, s.curr_tok.loc.span),
            .eqeq => node(NodeType.eqeq, s.curr_tok.loc.span),
            .gt => node(NodeType.gt, s.curr_tok.loc.span),
            .gteq => node(NodeType.gte, s.curr_tok.loc.span),
            .lt => node(NodeType.lt, s.curr_tok.loc.span),
            .lteq => node(NodeType.lte, s.curr_tok.loc.span),
            .mod => node(NodeType.mod, s.curr_tok.loc.span),
            .mul => node(NodeType.mul, s.curr_tok.loc.span),
            .nullish => node(NodeType.nullish, s.curr_tok.loc.span),
            .@"or" => node(NodeType.@"or", s.curr_tok.loc.span),
            .oror => node(NodeType.oror, s.curr_tok.loc.span),
            .sub => node(NodeType.sub, s.curr_tok.loc.span),
            .xor => node(NodeType.xor, s.curr_tok.loc.span),
            else => {
                s.diag.emit(.{ .file_id = s.source.id, .span = s.curr_tok.loc.span }, .err, "Unexpected assign op {any}", .{s.curr_tok.tok_type});
                return ParserError.recoverable;
            },
        };
        try s.expect(s.curr_tok.tok_type);
        return op;
    }
    fn range_expression(s: *Parser, expr: Node) ParserError!Node {
        try s.expect(.dotdot);
        return node(NodeType{ .range_expression = .{ .a = s.create_node_ptr(expr), .b = s.create_node_ptr(try s.expression(0)) } }, expr.span.fromSpan(s.curr_tok.loc.span));
    }
    fn result_block(s: *Parser) ParserError!Node {
        return switch (s.curr_tok.tok_type) {
            .identifier => switch (s.next_tok.tok_type) {
                .colon => try s.block(true),
                else => try s.statement(),
            },
            .lbrace => try s.block(false),
            else => try s.statement(),
        };
    }
    fn result_block_expression(s: *Parser) ParserError!Node {
        return switch (s.curr_tok.tok_type) {
            .identifier => switch (s.next_tok.tok_type) {
                .colon => try s.block(true),
                else => try s.expression(0),
            },
            .lbrace => try s.block(false),
            else => try s.expression(0),
        };
    }
    fn statement(s: *Parser) ParserError!Node {
        if (s.curr_tok.tok_type == .identifier) {
            if (s.next_tok.tok_type == .colon) return if (s.peek_tok.tok_type == .lbrace) try s.block(true) else try s.declaration(false);
            if (s.next_tok.tok_type == .walrus) return try s.declaration(false);
        }
        return switch (s.curr_tok.tok_type) {
            .@"break" => blk: {
                const span_start = s.curr_tok.loc.span;
                try s.expect(.@"break");
                const label = if (s.curr_tok.tok_type == .colon) blk2: {
                    try s.expect(.colon);
                    break :blk2 s.create_node_ptr(try s.identifier());
                } else null;
                break :blk node(NodeType{ .break_expression = .{ .label = label, .val = if (s.curr_tok.tok_type == .semicolon) null else s.create_node_ptr(try s.expression(0)) } }, span_start.fromSpan(s.curr_tok.loc.span));
            },
            .@"continue" => blk: {
                const span_start = s.curr_tok.loc.span;
                try s.expect(.@"continue");
                break :blk node(NodeType{ .continue_expression = .{ .label = if (s.curr_tok.tok_type == .colon) blk2: {
                    try s.expect(.colon);
                    break :blk2 s.create_node_ptr(try s.identifier());
                } else null } }, span_start.fromSpan(s.curr_tok.loc.span));
            },
            .@"defer" => try s.defer_statement(),
            .@"if" => blk: {
                const span_start = s.curr_tok.loc.span;
                const prefix = s.create_node_ptr(try s.if_prefix());
                const body = s.create_node_ptr(try s.result_block());
                break :blk node(NodeType{ .if_statement = .{ .prefix = prefix, .body = body, .else_body = if (s.curr_tok.tok_type == .@"else") blk2: {
                    try s.expect(.@"else");
                    break :blk2 s.create_node_ptr(try s.result_block());
                } else null } }, span_start.fromSpan(s.curr_tok.loc.span));
            },
            .@"inline", .@"for" => blk: {
                const span_start = s.curr_tok.loc.span;
                const inline_ = if (s.curr_tok.tok_type == .@"inline") blk2: {
                    try s.expect(.@"inline");
                    break :blk2 true;
                } else false;
                try s.expect(.@"for");
                var expressions = std.ArrayList(Node).empty;
                while (s.curr_tok.tok_type != .eof) {
                    if (s.curr_tok.tok_type == .colon) break;
                    expressions.append(s.allocator, try s.expression(0)) catch |e| @panic(@errorName(e));
                    if (s.curr_tok.tok_type == .colon) break;
                    try s.expect(.comma);
                }
                try s.expect(.colon);
                const cap = s.create_node_ptr(try s.capture());
                break :blk node(NodeType{ .for_statement = .{ .inline_ = inline_, .expressions = expressions, .capture = cap, .body = s.create_node_ptr(try s.result_block()) } }, span_start.fromSpan(s.curr_tok.loc.span));
            },
            .lbrace => try s.block(false),
            .match => try s.match(false),
            .mut => try s.declaration(false),
            .@"return" => blk: {
                const span_start = s.curr_tok.loc.span;
                try s.expect(.@"return");
                break :blk node(NodeType{ .return_expression = .{ .val = if (s.curr_tok.tok_type == .semicolon or s.curr_tok.tok_type == .comma) null else s.create_node_ptr(try s.expression(0)) } }, span_start.fromSpan(s.curr_tok.loc.span));
            },
            else => try s.expression(0),
        };
    }
    fn struct_initialization(s: *Parser, current_name: ?Node) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        const name = if (current_name) |n| s.create_node_ptr(n) else if (s.curr_tok.tok_type == .identifier) s.create_node_ptr(try s.identifier()) else null;
        try s.expect(.lbrace);
        var inits = std.ArrayList(Node).empty;
        while (s.curr_tok.tok_type != .eof) {
            if (s.curr_tok.tok_type == .rbrace) break;
            inits.append(s.allocator, try s.struct_init_member()) catch |e| @panic(@errorName(e));
            if (s.curr_tok.tok_type == .rbrace) break;
            try s.expect(.comma);
        }
        try s.expect(.rbrace);
        return node(NodeType{ .struct_init = .{ .name = name, .inits = inits } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    fn struct_init_member(s: *Parser) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        const name = s.create_node_ptr(try s.identifier());
        try s.expect(.colon);
        return node(NodeType{ .struct_init_member = .{ .name = name, .val = s.create_node_ptr(try s.expression(0)) } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    fn member(s: *Parser, is_struct: bool) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        var names = std.ArrayList(Node).empty;
        while (s.curr_tok.tok_type != .eof) {
            if (s.curr_tok.tok_type == .colon or s.curr_tok.tok_type == .walrus or s.curr_tok.tok_type == .rbrace) break;
            names.append(s.allocator, try s.identifier()) catch |e| @panic(@errorName(e));
            if (s.curr_tok.tok_type == .colon or s.curr_tok.tok_type == .walrus or s.curr_tok.tok_type == .rbrace) break;
            try s.expect(.comma);
        }
        const type_ = switch (s.curr_tok.tok_type) {
            .walrus => null,
            .colon => blk: {
                try s.expect(.colon);
                break :blk s.create_node_ptr(try s.non_literal_expression());
            },
            .rbrace => blk: {
                if (is_struct) {
                    s.diag.emit(.{ .file_id = s.source.id, .span = s.curr_tok.loc.span }, .err, "Invalid declaration symbol {any}, wanted := or : [Type]", .{s.curr_tok.tok_type});
                    return ParserError.recoverable;
                }
                break :blk null;
            },
            else => {
                s.diag.emit(.{ .file_id = s.source.id, .span = s.curr_tok.loc.span }, .err, "Invalid declaration symbol {any}, wanted := or : [Type]", .{s.curr_tok.tok_type});
                return ParserError.recoverable;
            },
        };
        const val = switch (s.curr_tok.tok_type) {
            .eq, .walrus => blk: {
                try s.expect(s.curr_tok.tok_type);
                break :blk s.create_node_ptr(try s.expression(0));
            },
            else => null,
        };
        return node(NodeType{ .member = .{ .names = names, .type = type_, .val = val } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    fn member_basic(s: *Parser) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        var names = std.ArrayList(Node).empty;
        while (s.curr_tok.tok_type != .eof) {
            if (s.curr_tok.tok_type == .colon or s.curr_tok.tok_type == .walrus or s.curr_tok.tok_type == .rbrace) break;
            names.append(s.allocator, try s.identifier()) catch |e| @panic(@errorName(e));
            if (s.curr_tok.tok_type == .colon or s.curr_tok.tok_type == .walrus or s.curr_tok.tok_type == .rbrace) break;
            try s.expect(.comma);
        }
        const member_type = if (s.curr_tok.tok_type == .colon) blk: {
            try s.expect(.colon);
            break :blk s.create_node_ptr(try s.non_literal_expression());
        } else null;
        return node(NodeType{ .member_basic = .{ .names = names, .type = member_type } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    fn unary_expression(s: *Parser) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        const op = s.create_node_ptr(try s.operator());
        return node(NodeType{ .unary = .{ .op = op, .b = s.create_node_ptr(try s.expression(0)) } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    fn use_expression(s: *Parser) ParserError!Node {
        const span_start = s.curr_tok.loc.span;
        try s.expect(.use);
        if (s.curr_tok.tok_type != .string) {
            s.diag.emit(.{ .file_id = s.source.id, .span = span_start }, .err, "String literal expected for use paths", .{});
            return ParserError.recoverable;
        }
        return node(NodeType{ .use = .{ .path = s.create_node_ptr(try s.literal()) } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    fn postfix_chain(s: *Parser, base: Node, allow_struct: bool) ParserError!Node {
        var chain = base;
        while (s.curr_tok.tok_type != .eof) switch (s.curr_tok.tok_type) {
            .dot => {
                try s.expect(.dot);
                chain = node(NodeType{ .member_access = .{ .name = s.create_node_ptr(chain), .member = s.create_node_ptr(try s.identifier()) } }, chain.span.fromSpan(s.curr_tok.loc.span));
            },
            .lbrack => {
                try s.expect(.lbrack);
                const expr = s.create_node_ptr(try s.expression(0));
                try s.expect(.rbrack);
                chain = node(NodeType{ .array_index = .{ .name = s.create_node_ptr(chain), .index = expr } }, chain.span.fromSpan(s.curr_tok.loc.span));
            },
            .lbrace => {
                if (!allow_struct) break;
                chain = try s.struct_initialization(chain);
            },
            .lparen => {
                try s.expect(.lparen);
                var args = std.ArrayList(Node).empty;
                while (s.curr_tok.tok_type != .eof) {
                    if (s.curr_tok.tok_type == .rparen) break;
                    args.append(s.allocator, try s.expression(0)) catch |e| @panic(@errorName(e));
                    if (s.curr_tok.tok_type == .rparen) break;
                    try s.expect(.comma);
                }
                try s.expect(.rparen);
                chain = node(NodeType{ .call = .{ .name = s.create_node_ptr(chain), .args = args } }, chain.span.fromSpan(s.curr_tok.loc.span));
            },
            .pointer_deref => {
                try s.expect(.pointer_deref);
                chain = node(NodeType{ .pointer_dereference = .{ .expression = s.create_node_ptr(chain) } }, chain.span.fromSpan(s.curr_tok.loc.span));
            },
            .optional_deref => {
                try s.expect(.optional_deref);
                chain = node(NodeType{ .optional_dereference = .{ .expression = s.create_node_ptr(chain) } }, chain.span.fromSpan(s.curr_tok.loc.span));
            },
            else => break,
        };
        return chain;
    }

    fn advance(s: *Parser) void {
        s.curr_tok = s.next_tok;
        s.next_tok = s.peek_tok;
        s.peek_tok = s.lexer.next();
    }
    fn create_node_ptr(s: *Parser, n: Node) *Node {
        const x = s.allocator.create(Node) catch |e| @panic(@errorName(e));
        x.* = n;
        return x;
    }
    fn expect(s: *Parser, expected: TokenType) ParserError!void {
        if (s.curr_tok.tok_type == .invalid) return ParserError.fatal;
        if (s.curr_tok.tok_type != expected) {
            s.diag.emit(.{ .file_id = s.source.id, .span = s.curr_tok.loc.span }, .err, "Unexpected token {any}, expected {any}", .{ s.curr_tok.tok_type, expected });
            return ParserError.recoverable;
        }
        s.advance();
    }
    fn node(nodeType: NodeType, span: Span) Node {
        return Node{ .type = nodeType, .span = span };
    }
    fn precedence(s: *Parser) u8 {
        return switch (s.curr_tok.tok_type) {
            .dot, .lbrack, .lparen => 17,
            .bang, .xor => 16,
            .div, .mod, .mul => 15,
            .add, .sub => 14,
            .nullish => 13,
            .@"and", .@"or" => 12,
            .gt, .lt => 11,
            .gteq, .lteq => 10,
            .bangeq, .eqeq => 9,
            .andand => 8,
            .oror => 7,
            .dotdot => 6,
            else => 0,
        };
    }
    fn should_read_semicolon(n: Node) bool {
        return switch (n.type) {
            .if_statement => |i| if (i.else_body) |e| should_read_semicolon(e.*) else should_read_semicolon(i.body.*),
            .for_statement => |i| should_read_semicolon(i.body.*),
            .block, .match => false,
            .defer_statement => |i| should_read_semicolon(i.body.*),
            else => true,
        };
    }
    fn sync(s: *Parser, toks: []const TokenType) void {
        while (s.curr_tok.tok_type != .eof) {
            if (std.mem.indexOf(TokenType, toks, &[_]TokenType{s.curr_tok.tok_type})) |_| {
                s.advance();
                return;
            }
            s.advance();
        }
    }
};
const Severity = enum {
    err,
    warn,
    info,
    pub fn to_string(s: Severity) []const u8 {
        return switch (s) {
            .err => "error",
            .warn => "warning",
            .info => "info",
        };
    }
};
const Span = struct {
    start: u32,
    end: u32,
    pub fn from(start: u32, end: u32) Span {
        return .{ .start = start, .end = end };
    }
    pub fn fromSpan(a: Span, b: Span) Span {
        return .{ .start = a.start, .end = b.end };
    }
};
const Token = struct {
    tok_type: TokenType,
    loc: FileLocation,
    val: ?[]const u8 = null,
    pub fn init(tok: TokenType, file_id: FileId, val: ?[]const u8, start: u32, end: u32) Token {
        return Token{ .tok_type = tok, .loc = FileLocation{ .file_id = file_id, .span = Span.from(start, end) }, .val = val };
    }
};
const TokenType = enum {
    eof,
    invalid,
    // literals
    identifier,
    int,
    float,
    string,
    char,
    // operators
    add, // +
    sub, // -
    mul, // *
    div, // /
    mod, // %
    @"and", // &
    @"or", // |
    xor, // ^
    flip, // ~
    eq, // =
    addeq, // +=
    addadd, // ++
    subeq, // -=
    subsub, // --
    muleq, // *=
    diveq, // /=
    modeq, // %=
    andeq, // &=
    oreq, // |=
    xoreq, // ^=
    flipeq, // ~=
    andand, // &&
    oror, // ||
    eqeq, // ==
    gt, // >
    lt, // <
    gteq, // >=
    lteq, // <=
    lparen, // (
    rparen, // )
    lbrack, // [
    rbrack, // ]
    lbrace, // {
    rbrace, // }
    dot, // .
    dotdot, // ..
    colon, // :
    semicolon, // ;
    underscore, // _
    comma, // ,
    arrow, // =>
    bang, // !
    bangeq, // !=
    question, // ?
    dollar, // $
    walrus, // :=
    nullish, // ??
    // keywords
    module,
    pointer_deref,
    optional_deref,
    use,
    mut,
    true,
    false,
    @"if",
    @"else",
    match,
    @"defer",
    @"for",
    @"enum",
    @"error",
    @"try",
    @"catch",
    @"struct",
    @"packed",
    type,
    comp,
    @"pub",
    null,
    undefined,
    @"return",
    @"break",
    @"inline",
    @"continue",
    void,
};
const Type = enum {
    void,
    boolean,
    char,
    int,
    float,
    string,
    undefined,
    null,
    pointer,
    optional,
    error_union,
    array,
    slice,
    function,
    struct_,
    enum_,
    error_,
    type,
    unknown,
};
pub fn main() !void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const allocator = arena.allocator();
    var source_manager = FileManager.init(allocator);
    var diagnostics = DiagnosticEmitter.init(allocator);
    var module_resolver = ModuleResolver.init(allocator, &source_manager, &diagnostics);
    var compiler = Compiler.init(allocator, &diagnostics, &source_manager, &module_resolver);
    try compiler.compile("example/main", .check);
}
