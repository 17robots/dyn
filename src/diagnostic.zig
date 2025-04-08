const std = @import("std");
pub const Severity = enum {
    info,
    warn,
    err,
    fn format(s: Severity, comptime fmt: []const u8, options: std.fmt.FormatOptions, writer: anytype) !void {
        _ = fmt;
        _ = options;
        try writer.print("{}\n", .{switch (s) {
            .info => "info",
            .warn => "warn",
            .err => "error",
        }});
    }
};
const Diagnostic = @This();

filename: []const u8 = "",
message: []const u8,
line: usize,
col: usize,
severity: Severity,

pub fn format(s: Diagnostic, comptime fmt: []const u8, options: std.fmt.FormatOptions, writer: anytype) !void {
    _ = fmt;
    _ = options;
    try writer.print("{}:{}:{}| {}: {}\n", .{ s.filename, s.line, s.col, s.severity, s.message });
}
