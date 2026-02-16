const std = @import("std");
const Tok = @import("token.zig").Tok;
const Span = @import("token.zig").Span;
const SourceManager = @import("source_manager.zig");
const Lexer = @import("lexer2.zig");
const Resolver = @import("resolver.zig");
const ModuleGraph = @import("module_graph.zig");
const Symbols = @import("symbols.zig");
const Semantic = @import("semantic.zig");

pub const LexReportOptions = struct {
    max_errors: usize = 50,
    stop_on_first: bool = false,
};

pub const LexReportResult = struct {
    error_count: usize,
    token_count: usize,
    stopped_early: bool,
};

pub fn printDiagnostic(
    sm: *SourceManager,
    writer: anytype,
    file_id: SourceManager.FileId,
    span: Span,
    message: []const u8,
) !void {
    const pos = sm.positionOfSpanStart(file_id, span);
    try writer.print("{s}:{d}:{d}: {s}\n", .{ sm.filePath(file_id), pos.line, pos.column, message });

    const line = sm.lineSlice(file_id, pos.line) catch |err| blk: {
        if (err == error.SourceNotLoaded) {
            try sm.ensureTextLoaded(file_id);
            break :blk try sm.lineSlice(file_id, pos.line);
        }
        return err;
    };

    try writer.print("{s}\n", .{line});

    const span_len = if (span.end >= span.start) (span.end - span.start) + 1 else 1;
    const caret_count: usize = @max(@as(usize, 1), span_len);

    var i: usize = 1;
    while (i < pos.column) : (i += 1) {
        if (i - 1 < line.len and line[i - 1] == '\t') {
            try writer.writeAll("\t");
        } else {
            try writer.writeByte(' ');
        }
    }

    i = 0;
    while (i < caret_count) : (i += 1) {
        try writer.writeByte('^');
    }
    try writer.writeByte('\n');
}

pub fn lexerErrorMessage(kind: Tok.Kind) ?[]const u8 {
    return switch (kind) {
        .illegal => "illegal token",
        .invalid_escape => "invalid escape sequence",
        .unclosed_string => "unclosed string literal",
        .unclosed_block_comment => "unclosed block comment",
        .unclosed_character => "unclosed character literal",
        .empty_character => "empty character literal",
        .character_too_long => "character literal too long",
        else => null,
    };
}

pub fn reportLexerTokenIfError(
    sm: *SourceManager,
    writer: anytype,
    file_id: SourceManager.FileId,
    tok: Tok,
) !bool {
    const msg = lexerErrorMessage(tok.kind) orelse return false;
    try printDiagnostic(sm, writer, file_id, tok.span, msg);
    return true;
}

pub fn reportLexerErrorsForFile(
    sm: *SourceManager,
    writer: anytype,
    file_id: SourceManager.FileId,
    opts: LexReportOptions,
) !LexReportResult {
    try sm.ensureTextLoaded(file_id);

    const text = sm.fileText(file_id).?;

    var lexer = Lexer.init(text);
    var error_count: usize = 0;
    var token_count: usize = 0;
    var stopped_early = false;

    while (lexer.next()) |tok| {
        token_count += 1;
        if (try reportLexerTokenIfError(sm, writer, file_id, tok)) {
            error_count += 1;
            if (opts.stop_on_first or error_count >= opts.max_errors) {
                stopped_early = true;
                break;
            }
        }
    }

    return .{
        .error_count = error_count,
        .token_count = token_count,
        .stopped_early = stopped_early,
    };
}

pub fn reportResolveError(sm: *SourceManager, writer: anytype, err: Resolver.ResolveError) !void {
    try printDiagnostic(sm, writer, err.file_id, err.span, err.message);
}

pub fn reportResolveErrors(
    sm: *SourceManager,
    writer: anytype,
    errors: []const Resolver.ResolveError,
    max_errors: usize,
) !usize {
    const sorted = try sm.allocator.alloc(Resolver.ResolveError, errors.len);
    defer sm.allocator.free(sorted);
    @memcpy(sorted, errors);
    std.sort.block(Resolver.ResolveError, sorted, {}, lessResolveErr);

    var count: usize = 0;
    for (sorted) |err| {
        if (count >= max_errors) break;
        try reportResolveError(sm, writer, err);
        count += 1;
    }
    return count;
}

pub fn reportGraphErrors(
    sm: *SourceManager,
    writer: anytype,
    errors: []const ModuleGraph.GraphError,
    max_errors: usize,
) !usize {
    const sorted = try sm.allocator.alloc(ModuleGraph.GraphError, errors.len);
    defer sm.allocator.free(sorted);
    @memcpy(sorted, errors);
    std.sort.block(ModuleGraph.GraphError, sorted, {}, lessGraphErr);

    var count: usize = 0;
    for (sorted) |err| {
        if (count >= max_errors) break;
        try printDiagnostic(sm, writer, err.file_id, err.span, err.message);
        count += 1;
    }
    return count;
}

pub fn reportScopeErrors(
    sm: *SourceManager,
    writer: anytype,
    errors: []const Symbols.ScopeError,
    max_errors: usize,
) !usize {
    const sorted = try sm.allocator.alloc(Symbols.ScopeError, errors.len);
    defer sm.allocator.free(sorted);
    @memcpy(sorted, errors);
    std.sort.block(Symbols.ScopeError, sorted, {}, lessScopeErr);

    var count: usize = 0;
    for (sorted) |err| {
        if (count >= max_errors) break;
        try printDiagnostic(sm, writer, err.file_id, err.span, err.message);
        count += 1;
    }
    return count;
}

pub fn reportSemanticErrors(
    sm: *SourceManager,
    writer: anytype,
    errors: []const Semantic.SemanticError,
    max_errors: usize,
) !usize {
    const sorted = try sm.allocator.alloc(Semantic.SemanticError, errors.len);
    defer sm.allocator.free(sorted);
    @memcpy(sorted, errors);
    std.sort.block(Semantic.SemanticError, sorted, {}, lessSemanticErr);

    var count: usize = 0;
    for (sorted) |err| {
        if (count >= max_errors) break;
        try printDiagnostic(sm, writer, err.file_id, err.span, err.message);
        count += 1;
    }
    return count;
}

fn spanLess(a: Span, b: Span) bool {
    if (a.start != b.start) return a.start < b.start;
    return a.end < b.end;
}

fn lessResolveErr(_: void, a: Resolver.ResolveError, b: Resolver.ResolveError) bool {
    if (a.file_id != b.file_id) return a.file_id < b.file_id;
    return spanLess(a.span, b.span);
}

fn lessGraphErr(_: void, a: ModuleGraph.GraphError, b: ModuleGraph.GraphError) bool {
    if (a.file_id != b.file_id) return a.file_id < b.file_id;
    return spanLess(a.span, b.span);
}

fn lessScopeErr(_: void, a: Symbols.ScopeError, b: Symbols.ScopeError) bool {
    if (a.file_id != b.file_id) return a.file_id < b.file_id;
    return spanLess(a.span, b.span);
}

fn lessSemanticErr(_: void, a: Semantic.SemanticError, b: Semantic.SemanticError) bool {
    if (a.file_id != b.file_id) return a.file_id < b.file_id;
    return spanLess(a.span, b.span);
}

test "prints diagnostic with lazy source reload" {
    const alloc = std.testing.allocator;
    var sm = SourceManager.init(alloc);
    defer sm.deinit();

    const file_path = "src/__diag_test__.dyn";
    const sample = "alpha\nbeta\ngamma\n";

    {
        var f = try std.fs.cwd().createFile(file_path, .{ .truncate = true });
        defer f.close();
        try f.writeAll(sample);
    }
    defer std.fs.cwd().deleteFile(file_path) catch {};

    const id = try sm.addFileFromDisk(file_path, true);
    sm.evictText(id);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);

    const w = out.writer(alloc);
    const span = Span{ .start = 6, .end = 9 };
    try printDiagnostic(&sm, w, id, span, "example error");

    try std.testing.expect(std.mem.indexOf(u8, out.items, "src/__diag_test__.dyn:2:1: example error") != null);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "beta") != null);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "^^^^") != null);
}

test "reports lexer error token" {
    const alloc = std.testing.allocator;
    var sm = SourceManager.init(alloc);
    defer sm.deinit();

    const id = try sm.addFile("mem://lex", "x := '\\q'\n", true);
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);

    const tok = Tok.new(.invalid_escape, 5, 8);
    const w = out.writer(alloc);
    const did_report = try reportLexerTokenIfError(&sm, w, id, tok);

    try std.testing.expect(did_report);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "mem://lex:1:6: invalid escape sequence") != null);
}

test "reports lexer errors for full file with cap" {
    const alloc = std.testing.allocator;
    var sm = SourceManager.init(alloc);
    defer sm.deinit();

    const src =
        "a := '\\q'\n" ++
        "b := '\\q'\n" ++
        "c := '\\q'\n";

    const id = try sm.addFile("mem://cap", src, true);
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);

    const w = out.writer(alloc);
    const res = try reportLexerErrorsForFile(&sm, w, id, .{ .max_errors = 2 });

    try std.testing.expectEqual(@as(usize, 2), res.error_count);
    try std.testing.expect(res.stopped_early);
}

test "reports resolver errors with context" {
    const alloc = std.testing.allocator;
    var sm = SourceManager.init(alloc);
    defer sm.deinit();

    const id = try sm.addFile("mem://resolve", "x := M.oky\n", true);
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);

    const msg = try alloc.dupe(u8, "module 'other' has no public member 'oky'. did you mean 'ok'?");
    defer alloc.free(msg);

    var errs = [_]Resolver.ResolveError{.{
        .file_id = id,
        .span = .{ .start = 7, .end = 9 },
        .message = msg,
    }};

    const w = out.writer(alloc);
    const n = try reportResolveErrors(&sm, w, &errs, 10);

    try std.testing.expectEqual(@as(usize, 1), n);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "mem://resolve:1:8:") != null);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "M.oky") != null);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "^^^") != null);
}

test "reports graph and scope errors" {
    const alloc = std.testing.allocator;
    var sm = SourceManager.init(alloc);
    defer sm.deinit();

    const id = try sm.addFile("mem://graph", "x := use \"missing\"\ny := 1\ny := 2\n", true);
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);

    const ge = [_]ModuleGraph.GraphError{.{
        .file_id = id,
        .span = .{ .start = 9, .end = 17 },
        .message = "import module not found in target directory",
    }};
    const se = [_]Symbols.ScopeError{.{
        .module_index = 0,
        .file_id = id,
        .span = .{ .start = 24, .end = 24 },
        .message = "duplicate symbol in module scope",
    }};

    const n1 = try reportGraphErrors(&sm, w, &ge, 10);
    const n2 = try reportScopeErrors(&sm, w, &se, 10);
    try std.testing.expectEqual(@as(usize, 1), n1);
    try std.testing.expectEqual(@as(usize, 1), n2);
}

test "golden lexer diagnostic output is stable" {
    const alloc = std.testing.allocator;
    var sm = SourceManager.init(alloc);
    defer sm.deinit();

    const id = try sm.addFile("mem://golden", "a := '\\q'\n", true);
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);

    const tok = Tok.new(.invalid_escape, 5, 8);
    const w = out.writer(alloc);
    _ = try reportLexerTokenIfError(&sm, w, id, tok);

    const expected =
        "mem://golden:1:6: invalid escape sequence\n" ++
        "a := '\\q'\n" ++
        "\n" ++
        "     ^^^^\n";
    try std.testing.expectEqualStrings(expected, out.items);
}
