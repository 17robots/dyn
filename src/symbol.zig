const std = @import("std");
const ast = @import("ast.zig");
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;

const Symbol = struct {
    name: []const u8,
    type: struct {},
    scope: *Scope,
    value_node: ?*ast.Node,
};

const Scope = struct {
    parent: ?*Scope,
    type: union(enum) {
        block: ?[]const u8,
        function: []const u8,
        global: void,
    },
};
