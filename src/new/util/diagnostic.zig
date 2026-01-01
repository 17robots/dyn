const std = @import("std");
const source = @import("../frontend/source/manager.zig");

pub const Diagnostic = struct {
    severity: Severity,
    message: []const u8,
    location: Location,
    notes: []Note = &[_]Note{},
    help: ?[]const u8 = null,
    pub const Severity = enum { err, warning, info, note };
    pub const Location = struct { file_id: u32, span: source.Span, message: ?[]const u8 = null };
    pub const Note = struct { location: Location, message: []const u8 };
};
pub const Diagnostics = struct {
    allocator: std.mem.Allocator,
    errors: std.ArrayList(Diagnostic) = .empty,
    warnings: std.ArrayList(Diagnostic) = .empty,
    source_manager: ?*source.SourceManager = null,
    pub fn init(allocator: std.mem.Allocator) Diagnostics {
        return .{ .allocator = allocator };
    }
    pub fn deinit(self: *Diagnostics) void {
        self.errors.deinit(self.allocator);
        self.warnings.deinit(self.allocator);
    }
    pub fn set_source_manager(self: *Diagnostics, sm: *source.SourceManager) void {
        self.source_manager = sm;
    }
    pub fn emit(self: *Diagnostics, location: Diagnostic.Location, severity: Diagnostic.Severity, comptime fmt: []const u8, args: anytype) void {
        const message = std.fmt.allocPrint(self.allocator, fmt, args) catch return;
        defer self.allocator.free(message);
        const diag = Diagnostic{ .severity = severity, .message = message, .location = location };
        switch (severity) {
            .err => self.errors.append(self.allocator, diag) catch {},
            .warning => self.warnings.append(self.allocator, diag) catch {},
            else => {},
        }
    }
    pub fn emit_with_notes(self: *Diagnostics, location: Diagnostic.Location, severity: Diagnostic.Severity, comptime fmt: []const u8, args: anytype, notes: []Diagnostic.Note, help: ?[]const u8) void {
        const message = std.fmt.allocPrint(self.allocator, fmt, args) catch return;
        defer self.allocator.free(message);
        const diag = Diagnostic{ .severity = severity, .message = message, .location = location, .notes = notes, .help = help };
        switch (severity) {
            .err => self.errors.append(self.allocator, diag) catch {},
            .warning => self.warnings.append(self.allocator, diag) catch {},
            else => {},
        }
    }
    pub fn print_all(self: *Diagnostics, writer: anytype) void {
        for (self.errors.items) |err| self.print_diagnostic(writer, err);
        for (self.warnings.items) |warn| self.print_diagnostic(writer, warn);
    }
    pub fn print_diagnostic(self: *Diagnostics, writer: anytype, diag: Diagnostic) void {
        const color_reset = "\x1b[0m";
        const color_red = "\x1b[31m";
        const color_yellow = "\x1b[33m";
        const color_blue = "\x1b[34m";
        const color_gray = "\x1b[90m";
        const severity_color, const severity_str = switch (diag.severity) {
            .err => .{ color_red, "error" },
            .warning => .{ color_yellow, "warning" },
            .info => .{ color_blue, "info" },
            .note => .{ color_gray, "note" },
        };
        if (self.source_manager) |sm| {
            if (sm.get_file(diag.location.file_id)) |file| {
                const line_col = file.get_line_col(diag.location.span.start);
                writer.print("{s}{s}:{d}:{d}: {s}{s}: {s}{s}\n", .{ color_gray, file.path, line_col.line, line_col.col, severity_color, severity_str, diag.message, color_reset }) catch {};
                if (file.get_line(line_col.line)) |source_line| {
                    writer.print("    {s}{s}{s}\n", .{ color_gray, source_line, color_reset }) catch {};
                    writer.writeAll("    ") catch {};
                    for (0..line_col.col - 1) |_| writer.writeAll(" ") catch {};
                    writer.print("{s}^{s}", .{ severity_color, color_reset }) catch {};
                }
            }
        }
        for (diag.notes) |note| writer.print("{s}note: {s}{s}\n", .{ color_gray, note.message, color_reset }) catch {};
        if (diag.help) |help| writer.print("{s}help: {s}{s}\n", .{ color_blue, help, color_reset }) catch {};
    }
    pub fn has_errors(self: Diagnostics) bool {
        return self.errors.items.len > 0;
    }
};
