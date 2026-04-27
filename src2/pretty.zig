const std = @import("std");
const ast = @import("ast.zig");

pub fn printExpr(allocator: std.mem.Allocator, tree: *const ast.Ast, root: ast.ExprId) ![]u8 {
    var out = std.array_list.Managed(u8).init(allocator);
    try expr(&out, tree, root, 0);
    return out.toOwnedSlice();
}
fn expr(out: *std.array_list.Managed(u8), tree: *const ast.Ast, id: ast.ExprId, parent: u8) !void {
    const e = tree.expr(id);
    switch (e.kind) {
        .err => try out.appendSlice("<err>"),
        .literal => |l| try literal(out, l),
        .identifier => try out.appendSlice("id"),
        .builtin_identifier => try out.appendSlice("$builtin"),
        .grouped => |g| {
            try out.append('(');
            try expr(out, tree, g, 0);
            try out.append(')');
        },
        .error_union_type => |eu| {
            try expr(out, tree, eu.ok, 130);
            try out.append('!');
            for (eu.errors, 0..) |er, i| {
                if (i != 0) try out.append('|');
                try expr(out, tree, er, 0);
            }
        },
        .or_fallback => |o| {
            try expr(out, tree, o.lhs, 10);
            try out.appendSlice(" or ");
            if (o.capture) |c| {
                try out.append('|');
                try out.appendSlice(c.name);
                try out.appendSlice("| ");
            }
            try expr(out, tree, o.rhs, 11);
        },
        .binary => |b| {
            const p = prec(b.op);
            const par = p < parent;
            if (par) try out.append('(');
            try expr(out, tree, b.lhs, p);
            try out.print(" {s} ", .{bin(b.op)});
            try expr(out, tree, b.rhs, p + 1);
            if (par) try out.append(')');
        },
        .unary => |u| {
            try out.print("{s}", .{un(u.op)});
            if (u.op == .comp) try out.append(' ');
            try expr(out, tree, u.operand, 130);
        },
        .call => |c| {
            try expr(out, tree, c.callee, 140);
            try out.append('(');
            for (c.args, 0..) |a, i| {
                if (i != 0) try out.appendSlice(", ");
                try expr(out, tree, a.value, 0);
            }
            try out.append(')');
        },
        .member => |m| {
            try expr(out, tree, m.object, 140);
            try out.print(".{s}", .{m.name.name});
        },
        .index => |x| {
            try expr(out, tree, x.object, 140);
            try out.append('[');
            try expr(out, tree, x.index, 0);
            try out.append(']');
        },
        .optional_unwrap => |x| {
            try expr(out, tree, x, 140);
            try out.appendSlice(".?");
        },
        .error_unwrap => |x| {
            try expr(out, tree, x, 140);
            try out.appendSlice(".!");
        },
        .deref => |x| {
            try expr(out, tree, x, 140);
            try out.appendSlice(".*");
        },
        .array_literal => |items| {
            try out.append('[');
            for (items, 0..) |it, i| {
                if (i != 0) try out.appendSlice(", ");
                try expr(out, tree, it, 0);
            }
            try out.append(']');
        },
        .tuple_literal => |items| {
            try out.appendSlice(".{");
            for (items, 0..) |it, i| {
                if (i != 0) try out.appendSlice(", ");
                try expr(out, tree, it, 0);
            }
            try out.append('}');
        },
        .typed_struct_literal => |ts| {
            try expr(out, tree, ts.ty, 140);
            try out.append('{');
            for (ts.fields, 0..) |f, i| {
                if (i != 0) try out.appendSlice(", ");
                try out.print("{s}", .{f.name.name});
                if (f.value) |v| {
                    try out.appendSlice(": ");
                    try expr(out, tree, v, 0);
                }
            }
            try out.append('}');
        },
        .struct_type => try out.appendSlice("struct {}"),
        .enum_type => try out.appendSlice("enum {}"),
        .use => try out.appendSlice("use \"path\""),
        .block => try out.appendSlice("{}"),
        .function => |f| {
            try out.appendSlice("() ");
            if (f.return_type) |r| try expr(out, tree, r, 0) else try out.appendSlice("void");
            if (f.body_kind == .arrow) {
                try out.appendSlice(" => ");
                try expr(out, tree, f.body, 0);
            } else try out.appendSlice(" {}");
        },
        .if_expr => |i| {
            try out.appendSlice("if ");
            try expr(out, tree, i.condition, 0);
            try out.append(' ');
            try expr(out, tree, i.then_branch, 0);
            if (i.else_branch) |el| {
                try out.appendSlice(" else ");
                try expr(out, tree, el, 0);
            }
        },
        .for_expr => |f| {
            try out.appendSlice("for ");
            if (f.head) |h| switch (h) {
                .while_ => |w| {
                    try expr(out, tree, w.condition, 0);
                    try out.append(' ');
                },
                .iteration => {},
            };
            try expr(out, tree, f.body, 0);
        },
        .match_expr => |m| {
            try out.appendSlice("match ");
            try expr(out, tree, m.subject, 0);
            try out.appendSlice(" {");
            for (m.arms, 0..) |arm, i| {
                if (i != 0) try out.appendSlice(", ");
                for (arm.patterns, 0..) |p, j| {
                    if (j != 0) try out.appendSlice(", ");
                    try pat(out, tree, p);
                }
                try out.appendSlice(": ");
                try expr(out, tree, arm.body, 0);
            }
            try out.append('}');
        },
        else => try out.appendSlice("id"),
    }
}
fn pat(out: *std.array_list.Managed(u8), tree: *const ast.Ast, id: ast.PatternId) !void {
    switch (tree.pattern(id).kind) {
        .wildcard => try out.append('_'),
        .identifier => try out.appendSlice("id"),
        .literal => |l| try literal(out, l),
        .literal_range => |r| {
            try literal(out, r.start);
            try out.appendSlice(if (r.inclusive) "..=" else "..");
            try literal(out, r.end);
        },
        .enum_variant => try out.appendSlice(".Variant"),
        .multi => |ps| {
            for (ps, 0..) |p, i| {
                if (i != 0) try out.appendSlice(", ");
                try pat(out, tree, p);
            }
        },
        .err => try out.appendSlice("_"),
    }
}
fn literal(out: *std.array_list.Managed(u8), l: ast.Literal) !void {
    switch (l) {
        .integer => try out.append('0'),
        .float => try out.appendSlice("0.0"),
        .string => try out.appendSlice("\"s\""),
        .char => try out.appendSlice("'a'"),
        .true => try out.appendSlice("true"),
        .false => try out.appendSlice("false"),
        .null => try out.appendSlice("null"),
    }
}
fn prec(op: ast.BinaryOp) u8 {
    return switch (op) {
        .or_else => 10,
        .range_exclusive, .range_inclusive => 20,
        .logical_or => 30,
        .logical_and => 40,
        .bit_or => 50,
        .bit_xor => 60,
        .bit_and => 70,
        .eq, .ne => 80,
        .lt, .le, .gt, .ge => 90,
        .shl, .shr => 100,
        .add, .sub => 110,
        .mul, .div, .rem => 120,
    };
}
fn bin(op: ast.BinaryOp) []const u8 {
    return switch (op) {
        .add => "+",
        .sub => "-",
        .mul => "*",
        .div => "/",
        .rem => "%",
        .bit_and => "&",
        .bit_or => "|",
        .bit_xor => "^",
        .shl => "<<",
        .shr => ">>",
        .lt => "<",
        .le => "<=",
        .gt => ">",
        .ge => ">=",
        .eq => "==",
        .ne => "!=",
        .logical_and => "&&",
        .logical_or => "||",
        .range_exclusive => "..",
        .range_inclusive => "..=",
        .or_else => "or",
    };
}
fn un(op: ast.UnaryOp) []const u8 {
    return switch (op) {
        .not => "!",
        .neg => "-",
        .bit_not => "~",
        .address_of => "&",
        .comp => "comp",
    };
}
