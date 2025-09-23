const std = @import("std");
const SourceManager = @import("source.zig").SourceManager;
const SourceLocation = @import("source.zig").SourceLocation;

pub const Severity = enum {
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

pub const Diagnostic = struct {
    severity: Severity,
    location: SourceLocation,
    message: []const u8,
};

pub const DiagnosticEmitter = struct {
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
    pub fn emit(s: *DiagnosticEmitter, file_id: u32, index: u32, severity: Severity, comptime fmt: []const u8, args: anytype) void {
        if (severity == .err) s.err_count += 1;
        const msg = std.fmt.allocPrint(s.allocator, fmt, args) catch "out of memory";
        s.diagnostics.append(s.allocator, .{ .severity = severity, .location = SourceLocation{ .file_id = file_id, .index = index }, .message = msg }) catch @panic("out of memory");
    }
    pub fn has_errors(s: DiagnosticEmitter) bool {
        return s.err_count > 0;
    }
    pub fn print_all(s: *DiagnosticEmitter, source_manager: *SourceManager) void {
        const writer = std.io.getStdErr().writer();
        for (s.diagnostics.items) |d| {
            const resolved = source_manager.resolve_location(d.location);
            writer.print("{s}:{d}:{d}: {s}: {s}\n", .{ resolved.file_name, resolved.line, resolved.col, d.severity.to_string(), d.message }) catch {};
        }
    }
};
