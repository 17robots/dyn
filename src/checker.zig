const std = @import("std");
const Module = @import("module.zig").Module;
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;
const Symbol = @import("symbol.zig").Symbol;
const SymbolKind = @import("symbol.zig").SymbolKind;
const Scope = @import("symbol.zig").Scope;
const Type = @import("symbol.zig").Type;
const Node = @import("ast.zig").Node;

m: *Module,
d: *DiagnosticEmitter,
const Checker = @This();

pub fn init(m: *Module, d: *DiagnosticEmitter) Checker {
    return .{ .m = m, .d = d };
}
pub fn check(s: *Checker) !void {
    s.m.scopes.push(s.m.allocator, Scope{ .type = .global, .symbols = .empty, .types = .empty, .parent_scope = null });
    try s.load_globals();
    for (s.m.asts.items) |a| try s.check_node(a);
}
fn load_globals(s: *Checker) !void {
    // load them initially
    for (s.m.asts.items) |a| {
        for (a.type.program.declarations.items) |d| {
            s.m.scopes.current().?.symbols.append(s.m.allocator, Symbol{
                .name = d.type.declaration.name.type.identifier,
                .kind = if (d.type.declaration.type) |t| SymbolKind.from_node(t) else if (d.type.declaration.val) |v| SymbolKind.from_node(v) else .unknown,
                .type_id = null,
                .span = a.span,
            });
        }
    }
}
fn check_node(s: *Checker, node: Node) !void {
    switch (node.type) {
        .arm => |a| {},
        .array_index => |a| {},
        .array_init => |a| {},
        .arrow_expression => |a| {},
        .assign_expression => |a| {},
        .binary => |b| {},
        .block => |b| {},
        .break_expression => |b| {},
        .call => |c| {},
        .capture_val => |c| {},
        .catch_ => |c| {},
        .comp_expression => |c| {},
        .continue_expression => |c| {},
        .declaration => |d| {},
        .defer_statement => |d| {},
        .enum_ => |e| {},
        .enum_error_init => |e| {},
        .error_ => |e| {},
        .error_union_type => |e| {},
        .for_statement => |f| {},
        .function => |f| {},
        .function_parameter => |f| {},
        .function_type => |f| {},
        .grouped => |g| {},
        .identifier => |i| {},
        .if_expression => |i| {},
        .if_prefix => |i| {},
        .if_statement => |i| {},
        .literal => |l| {},
        .match => |m| {},
        .member => |m| {},
        .member_access => |m| {},
        .member_basic => |m| {},
        .module => |m| {},
        .nullish_expression => |n| {},
        .optional_dereference => |o| {},
        .optional_type => |o| {},
        .pointer_dereference => |p| {},
        .pointer_type => |p| {},
        .program => |p| for (p.declarations.items) |d| s.check_node(d),
        .range_expression => |r| {},
        .return_expression => |r| {},
        .struct_ => |st| {},
        .struct_init => |st| {},
        .struct_init_member => |st| {},
        .try_ => |t| {},
        .unary => |u| {},
        .use => |u| {},
        .while_statement => |w| {},
        else => {},
    }
}
fn type_from_node(s: Checker, node: Node) ?Type {
    _ = s;
    return switch (node.type) {
        else => null,
    };
}
fn get_symbol(s: Checker, name: []const u8) ?Symbol {
    for (s.m.scopes.scopes.items) |i| {
        for (i.symbols.items) |j| {
            if (std.mem.eql(u8, j.name, name)) return j;
        }
    }
    return null;
}
fn type_from_symbol(s: Checker, name: []const u8) ?Symbol {
    return if (s.get_symbol(name)) |symbol| blk: {
    } else null;
}
