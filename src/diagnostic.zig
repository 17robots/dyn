const std = @import("std");
pub const Severity = enum {
    info,
    warn,
    err,
    fn to_string(s: Severity) []const u8 {
        return switch (s) {
            .info => "info",
            .warn => "warn",
            .err => "error",
        };
    }
};
const Diagnostic = @This();

filename: []const u8 = "",
message: []const u8,
line: usize,
col: usize,
severity: Severity,
valid: bool = true,

pub fn format(s: Diagnostic, comptime fmt: []const u8, options: std.fmt.FormatOptions, writer: anytype) !void {
    _ = fmt;
    _ = options;
    try writer.print("{s}:{}:{}|{s}: {s}\n", .{ s.filename, s.line, s.col, s.severity.to_string(), s.message });
}
