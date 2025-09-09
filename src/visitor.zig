const std = @import("std");
const symbol = @import("symbol.zig");
const Node = @import("ast.zig").Node;
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;

pub const Visitor = struct {
    pub fn visit_progam(node: Node, table: *symbol.SymbolTable, diags: *DiagnosticEmitter) void {
        switch(node) {
            .program => |p| {

            },
            else => {
                diags.emit();
                return;
            },
        }
    }
};
