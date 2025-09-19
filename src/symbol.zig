const std = @import("std");
const ast = @import("ast.zig");
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;

pub const Symbol = struct { };
pub const SymbolTable = std.ArrayList(Symbol);
pub const ScopeStack = std.ArrayList(Scope);
pub const Scope = struct {
    parent: ?*Scope,
    type: union(enum) {
        block: ?[]const u8,
        function: []const u8,
        global: void,
    },
};
