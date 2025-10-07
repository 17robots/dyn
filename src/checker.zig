const std = @import("std");
const Module = @import("module.zig").Module;
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;
const Symbol = @import("symbol.zig").Symbol;
const Scope = @import("symbol.zig").Scope;

m: *Module,
d: *DiagnosticEmitter,
const Checker = @This();

pub fn init(m: *Module, d: *DiagnosticEmitter) Checker {
    return .{ .m = m, .d = d };
}

pub fn check(s: *Checker) !void {
    s.m.scopes.push(s.m.allocator, Scope{ .type = .global, .symbols = .empty, .types = .empty });
    try s.load_globals();
}

fn load_globals(s: *Checker) !void {}
fn check_decl(s: *Checker, d: *DiagnosticEmitter) !void {}
