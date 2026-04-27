const std = @import("std");
const source = @import("source.zig");

pub const Codes = struct {
    pub const L0001 = "expected digits after numeric base prefix";
    pub const L0002 = "expected exponent digits";
    pub const L0003 = "unterminated string literal";
    pub const L0004 = "unterminated char literal";
    pub const L0005 = "unterminated escape sequence";
    pub const L0006 = "expected two hex digits after \\x";
    pub const L0007 = "expected `{` after \\u";
    pub const L0008 = "expected hex digits in unicode escape";
    pub const L0009 = "expected `}` to close unicode escape";
    pub const L0010 = "unknown escape sequence";
    pub const L0011 = "unterminated block comment";
    pub const L0012 = "unexpected character";
};
pub const Severity = enum {
    error_,
    warning,
    note,
    hint,

    pub fn text(self: Severity) []const u8 {
        return switch (self) {
            .error_ => "error",
            .warning => "warning",
            .note => "note",
            .hint => "hint",
        };
    }
};
pub const Label = struct {
    span: source.Span,
    message: []const u8 = "",
};
pub const Note = struct { message: []const u8 };
pub const Suggestion = struct {
    replacement: []const u8,
    span: source.Span,
    machine_applicable: bool = false,
};
pub const Help = struct {
    message: []const u8,
    suggestion: ?Suggestion = null,
};
pub const Diagnostic = struct {
    severity: Severity,
    code: []const u8,
    message: []const u8,
    primary: Label,
    secondary: []const Label = &.{},
    notes: []const Note = &.{},
    help: []const Help = &.{},
};
pub const BagOptions = struct { max_errors: usize = 50 };
pub const DiagnosticBag = struct {
    allocator: std.mem.Allocator,
    diagnostics: std.ArrayList(Diagnostic),
    max_errors: usize,
    error_count: usize = 0,
    capped: bool = false,

    pub fn init(allocator: std.mem.Allocator, options: BagOptions) DiagnosticBag {
        return .{ .allocator = allocator, .diagnostics = .empty, .max_errors = options.max_errors };
    }

    pub fn deinit(self: *DiagnosticBag) void {
        self.diagnostics.deinit(self.allocator);
    }

    pub fn add(self: *DiagnosticBag, d: Diagnostic) !void {
        if (d.severity == .error_) {
            if (self.error_count >= self.max_errors) {
                self.capped = true;
                return;
            }
            self.error_count += 1;
        }
        var owned = d;
        owned.secondary = try self.allocator.dupe(Label, d.secondary);
        owned.notes = try self.allocator.dupe(Note, d.notes);
        owned.help = try self.allocator.dupe(Help, d.help);
        try self.diagnostics.append(self.allocator, owned);
    }

    pub fn errorAt(self: *DiagnosticBag, code: []const u8, message: []const u8, span: source.Span, label: []const u8) !void {
        try self.add(.{ .severity = .error_, .code = code, .message = message, .primary = .{ .span = span, .message = label } });
    }

    pub fn hasErrors(self: *const DiagnosticBag) bool {
        return self.error_count > 0;
    }
};
pub const SourceView = struct { path: []const u8, text: []const u8 };
pub const SourceProvider = struct {
    context: *const anyopaque,
    getFn: *const fn (*const anyopaque, source.FileId) ?SourceView,

    pub fn get(self: SourceProvider, id: source.FileId) ?SourceView {
        return self.getFn(self.context, id);
    }
};
pub const SingleSource = struct {
    file_id: source.FileId = 0,
    path: []const u8,
    text: []const u8,

    pub fn provider(self: *const SingleSource) SourceProvider {
        return .{ .context = self, .getFn = get };
    }

    fn get(ctx: *const anyopaque, id: source.FileId) ?SourceView {
        const self: *const SingleSource = @ptrCast(@alignCast(ctx));
        if (id != self.file_id) return null;
        return .{ .path = self.path, .text = self.text };
    }
};
pub fn render(allocator: std.mem.Allocator, provider: SourceProvider, diagnostics: []const Diagnostic) ![]u8 {
    var out = std.array_list.Managed(u8).init(allocator);
    for (diagnostics, 0..) |d, idx| {
        if (idx != 0) try out.append('\n');
        try renderOne(&out, provider, d);
    }
    return out.toOwnedSlice();
}
fn renderOne(out: *std.array_list.Managed(u8), provider: SourceProvider, d: Diagnostic) !void {
    try out.print("{s}[{s}]: {s}\n", .{ d.severity.text(), d.code, d.message });
    try renderLabel(out, provider, d.primary, true);
    for (d.secondary) |label| try renderLabel(out, provider, label, false);
    for (d.notes) |n| try out.print("  = note: {s}\n", .{n.message});
    for (d.help) |h| try out.print("  = help: {s}\n", .{h.message});
}
fn renderLabel(out: *std.array_list.Managed(u8), provider: SourceProvider, label: Label, primary: bool) !void {
    const view: SourceView = provider.get(label.span.file) orelse SourceView{ .path = "<unknown>", .text = "" };
    const lc = lineCol(view.text, label.span.start);
    const line = lineSlice(view.text, lc.line_start);
    const gutter_width = digits(lc.line);
    try out.print("  ┌─ {s}:{}:{}\n", .{ view.path, lc.line, lc.col });
    try out.print("  │\n", .{});
    try out.print("{} │ {s}\n", .{ lc.line, line });
    try out.print("  │ ", .{});
    try appendSpaces(out, gutter_width + 1 + lc.col - 1);
    const len = @max(@as(u32, 1), label.span.len());
    const marker: u8 = if (primary) '^' else '-';
    var i: u32 = 0;
    while (i < len) : (i += 1) try out.append(marker);
    if (label.message.len > 0) try out.print(" {s}", .{label.message});
    try out.append('\n');
}
const LineCol = struct { line: usize, col: usize, line_start: usize };
fn lineCol(text: []const u8, byte: u32) LineCol {
    var line: usize = 1;
    var col: usize = 1;
    var line_start: usize = 0;
    var i: usize = 0;
    const end = @min(@as(usize, byte), text.len);
    while (i < end) : (i += 1) {
        if (text[i] == '\n') {
            line += 1;
            col = 1;
            line_start = i + 1;
        } else col += 1;
    }
    return .{ .line = line, .col = col, .line_start = line_start };
}
fn lineSlice(text: []const u8, start: usize) []const u8 {
    var end = start;
    while (end < text.len and text[end] != '\n' and text[end] != '\r') end += 1;
    return text[start..end];
}
fn digits(n0: usize) usize {
    var n = n0;
    var d: usize = 1;
    while (n >= 10) : (n /= 10) d += 1;
    return d;
}
fn appendSpaces(out: *std.array_list.Managed(u8), n: usize) !void {
    var i: usize = 0;
    while (i < n) : (i += 1) try out.append(' ');
}
fn expectRender(name: []const u8, actual: []const u8) !void {
    const expected = if (std.mem.eql(u8, name, "with_help"))
        @embedFile("../tests/snapshots/diag/with_help.txt")
    else if (std.mem.eql(u8, name, "multi_span"))
        @embedFile("../tests/snapshots/diag/multi_span.txt")
    else
        return error.UnknownSnapshot;
    try std.testing.expectEqualStrings(expected, actual);
}

test "render with help snapshot" {
    const src = "let x = \"oops\n";
    const ss = SingleSource{ .path = "main.dyn", .text = src };
    const d = Diagnostic{ .severity = .error_, .code = "L0003", .message = Codes.L0003, .primary = .{ .span = .{ .start = 8, .end = 13 }, .message = "string starts here" }, .help = &.{.{ .message = "close the string literal with `\"`" }} };
    const rendered = try render(std.testing.allocator, ss.provider(), &.{d});
    defer std.testing.allocator.free(rendered);
    try expectRender("with_help", rendered);
}
test "render multi span snapshot" {
    const src = "first\nsecond\n";
    const ss = SingleSource{ .path = "main.dyn", .text = src };
    const secondary = [_]Label{.{ .span = .{ .start = 6, .end = 12 }, .message = "related span" }};
    const notes = [_]Note{.{ .message = "extra context" }};
    const d = Diagnostic{ .severity = .error_, .code = "T0001", .message = "example multi-span diagnostic", .primary = .{ .span = .{ .start = 0, .end = 5 }, .message = "primary span" }, .secondary = &secondary, .notes = &notes };
    const rendered = try render(std.testing.allocator, ss.provider(), &.{d});
    defer std.testing.allocator.free(rendered);
    try expectRender("multi_span", rendered);
}
test "bag respects max errors" {
    var bag = DiagnosticBag.init(std.testing.allocator, .{ .max_errors = 1 });
    defer bag.deinit();
    try bag.errorAt("L0012", Codes.L0012, .{ .start = 0, .end = 1 }, "bad char");
    try bag.errorAt("L0012", Codes.L0012, .{ .start = 1, .end = 2 }, "bad char");
    try std.testing.expectEqual(@as(usize, 1), bag.diagnostics.items.len);
    try std.testing.expect(bag.capped);
}
