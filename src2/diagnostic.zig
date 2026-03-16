const std = @import("std");

pub const Phase = enum { ModuleResolver, Lexer, Parser, Semantic, TypeChecker, Mir, Backend };
pub const Severity = enum { Error, Warning };
pub const Code = enum {
    E1001,
    E1002,
    E1003,
    E1004,
    E2001,
    E2002,
    E2003,
    E2004,
    E2005,
    E2006,
    E2007,
    E3001,
    E3002,
    E4001,
    E4002,
    E4003,
    E4004,
    E4005,
    E4006,
    E4007,
    E4008,
    E4009,
    E40010,
    E40011,
    E40012,
    E5001,
    E5002,
    E5003,
    pub fn as_str(self: Code) []const u8 {
        return switch (self) {
            .E1001 => "E1001",
            .E1002 => "E1002",
            .E1003 => "E1003",
            .E1004 => "E1004",
            .E2001 => "E2001",
            .E2002 => "E2002",
            .E2003 => "E2003",
            .E2004 => "E2004",
            .E2005 => "E2005",
            .E2006 => "E2006",
            .E2007 => "E2007",
            .E3001 => "E3001",
            .E3002 => "E3002",
            .E4001 => "E4001",
            .E4002 => "E4002",
            .E4003 => "E4003",
            .E4004 => "E4004",
            .E4005 => "E4005",
            .E4006 => "E4006",
            .E4007 => "E4007",
            .E4008 => "E4008",
            .E4009 => "E4009",
            .E40010 => "E40010",
            .E40011 => "E40011",
            .E40012 => "E40012",
            .E5001 => "E5001",
            .E5002 => "E5002",
            .E5003 => "E5003",
        };
    }
};
pub const SourceSpan = struct { start_byte: usize, end_byte: usize, start_line: usize, end_line: usize, start_col: usize, end_col: usize };
pub const Label = struct { file_path: []const u8, span: ?SourceSpan, message: []const u8, primary: bool };
pub const Diagnostic = struct {
    allocator: std.mem.Allocator,
    phase: Phase,
    severity: Severity,
    code: Code,
    message: []const u8,
    labels: std.ArrayList(Label),
    notes: std.ArrayList([]const u8),
    pub fn init(allocator: std.mem.Allocator, phase: Phase, severity: Severity, code: Code, message: []const u8) Diagnostic {
        return Diagnostic{ .allocator = allocator, .phase = phase, .severity = severity, .code = code, .message = message };
    }
    pub fn add_file_label(self: *Diagnostic, file_path: []const u8, span: ?SourceSpan, message: []const u8) void {
        self.labels.append(self.allocator, Label{ .file_path = file_path, .span = span, .message = message, .primary = true }) catch {};
    }
};
