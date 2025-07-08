const std = @import("std");
const ast = @import("ast.zig");

pub const Visitor = @This();

visit_fn: *const fn (self: *Visitor, node: ast.Node) anyerror!void,

pub fn walk(self: *Visitor, node: ast.Node) !void {
    try self.visit_fn(self, node);
}

pub fn visit(self: *Visitor, node: ast.Node) !void {
    switch (node) {
        .program => |n| {
            for (n.declarations.items) |decl| {
                try self.walk(decl);
            }
        },
        .declaration => |n| {
            try self.walk(n.val.*);
            if (n.type) |t| {
                try self.walk(t.*);
            }
        },
        .if_statement => |n| {
            try self.walk(n.prefix.*);
            try self.walk(n.body.*);
            if (n.else_body) |b| {
                try self.walk(b.*);
            }
        },
        .while_statement => |n| {
            try self.walk(n.prefix.*);
            try self.walk(n.body.*);
        },
        .for_statement => |n| {
            try self.walk(n.prefix.*);
            try self.walk(n.body.*);
        },
        .block => |n| {
            for (n.statements.items) |stmt| {
                try self.walk(stmt);
            }
        },
        .binary => |n| {
            try self.walk(n.a.*);
            try self.walk(n.op.*);
            try self.walk(n.b.*);
        },
        .unary => |n| {
            try self.walk(n.op.*);
            try self.walk(n.b.*);
        },
        .call => |n| {
            try self.walk(n.name.*);
            for (n.args.items) |arg| {
                try self.walk(arg);
            }
        },
        .member_access => |n| {
            try self.walk(n.name.*);
            try self.walk(n.member.*);
        },
        else => {},
    }
}
