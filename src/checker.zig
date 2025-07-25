const std = @import("std");
const Node = @import("ast.zig").Node;
const Symbol = @import("symbol.zig");
const module = @import("module.zig");
const types = @import("types.zig");

const Checker = @This();

a: std.mem.Allocator,
resolver: module.ModuleResolver,

pub fn init() !Checker {}
pub fn check(s: *Checker, m: *module.Module) !void { // this sets the public members of a module and sets the module status to checked
    // construct symbol tables and scopes here
    _ = m;
    const scopes = std.ArrayList(std.StringHashMap(Symbol)).init(s.a);
    _ = scopes;
}
