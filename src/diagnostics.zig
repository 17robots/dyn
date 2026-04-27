const std = @import("std");
const source = @import("source.zig");

pub const DiagnosticCodes = struct {
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
pub const Severity = enum(u2) {
    err,
    warn,
    note,
    hint,
    pub fn text(self: Severity) []const u8 {
        return switch (self) {
            .err => "error",
            .warn => "warning",
            .note => "note",
            .hint => "hint",
        };
    }
};
pub const Label = struct { span: source.Span, message: []const u8 = "" };
pub const Suggestion = struct { replacement: []const u8, span: source.Span, machine_applicable: bool };
pub const Help = struct { message: []const u8, suggestion: ?Suggestion = null };
pub const Diagnostic = struct {
    severity: Severity,
    code: []const u8,
    message: []const u8,
    primary: Label,
    secondary: []const Label = &.{},
    notes: []const []const u8 = &.{},
    help: []const Help = &.{},
};
pub const DiagnosticBag = struct {
    const BagOptions = struct { max_errors: usize = 50 };
    allocator: std.mem.Allocator,
    diagnostics: std.MultiArrayList(Diagnostic) = .empty,
    options: BagOptions,
    error_count: usize = 0,
    capped: bool = false,
    pub fn init(allocator: std.mem.Allocator, options: BagOptions) DiagnosticBag {
        return .{ .allocator = allocator, .options = options };
    }
    pub fn add(self: *DiagnosticBag, d: Diagnostic) !void {
        if (d.severity == .err) {
            if (self.error_count >= self.max_errors) {
                self.capped = true;
                return;
            }
            self.error_count += 1;
        }
        var owned = d;
        owned.secondary = try self.allocator.dupe(Label, d.secondary);
        owned.notes = try self.allocator.dupe([]const u8, d.notes);
        owned.help = try self.allocator.dupe(Help, d.help);
        try self.diagnostics.append(self.allocator, owned);
    }
    pub fn error_at(self: *DiagnosticBag, code: []const u8, message: []const u8, span: source.Span, label: []const u8) !void {
        try self.add(.{ .severity = .err, .code = code, .message = message, .primary = .{ .span = span, .message = label }});
    }
    pub fn has_errs(self: *const DiagnosticBag) bool {
        return self.error_count > 0;
    }
};
