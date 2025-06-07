const std = @import("std");
const Lexer = @import("lexer.zig");
const Token = @import("token.zig").TokenType;
const Node = @import("ast.zig").Node;
const LiteralKind = @import("ast.zig").LiteralKind;
const Op = @import("ast.zig").Op;
const AssignOp = @import("ast.zig").AssignOp;
const NodeList = std.ArrayList(Node);
const File = @import("file.zig");
const Diagnostic = @import("diagnostic.zig");

const Parser = @This();
const LexerState = struct { tok: ?Token, literal: ?[]const u8, line: usize, col: usize, index: usize };
const ParsingResult = union(enum) { node: Node, diagnostic: Diagnostic, string: []const u8, assign_op: AssignOp, op: Op, none };

l: *Lexer,
a: std.mem.Allocator,
f: *File,

pub fn init(alloc: std.mem.Allocator, f: *File, l: *Lexer) Parser {
    return Parser{ .l = l, .f = f, .a = alloc };
}
pub fn program(s: *Parser) ParsingResult {
    s.l.next_tok();
    var declarations = NodeList.init(s.a);
    append(&declarations, switch (s.module_declaration()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |n| n,
        else => unreachable,
    });
    blk: while (s.l.tok.? != .eof) {
        append(&declarations, switch (s.declaration()) {
            .diagnostic => |d| {
                s.f.diagnostics.append(d) catch |e| @panic(@errorName(e));
                s.recover(&[_]Token{ .rbrace, .semicolon });
                continue :blk;
            },
            .node => |n| n,
            else => unreachable,
        });
    }
    return node(Node{ .program = .{ .declarations = declarations } });
}
fn module_declaration(s: *Parser) ParsingResult {
    switch (s.eat(.module)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    const name = s.create_node_ptr(switch (s.identifier()) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    switch (s.eat(.semicolon)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .module = .{ .name = name } });
}
fn declaration(s: *Parser) ParsingResult {
    const pub_ = if (s.l.tok.? == .@"pub") blk: {
        switch (s.eat(.@"pub")) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => break :blk true,
        }
    } else false;
    const name = s.create_node_ptr(switch (s.identifier()) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    const type_ = switch (s.l.tok.?) {
        .walrus => null,
        .colon => blk: {
            switch (s.eat(.colon)) {
                .diagnostic => |d| return .{ .diagnostic = d },
                else => {},
            }
            break :blk s.create_node_ptr(switch (s.non_literal_expression()) {
                .node => |n| n,
                .diagnostic => |d| return .{ .diagnostic = d },
                else => unreachable,
            });
        },
        else => return s.diagnostic(.err, "Unexpected token {any}, expected : [type] or :=", .{s.l.tok.?}),
    };
    switch (s.l.tok.?) {
        .walrus, .eq => switch (s.eat(s.l.tok.?)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        },
        else => return s.diagnostic(.err, "Unexpected token {any}, wanted := or =", .{s.l.tok.?}),
    }
    const val = s.create_node_ptr(switch (s.expression(0)) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    switch (s.eat(.semicolon)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .declaration = .{ .pub_ = pub_, .name = name, .type = type_, .val = val } });
}
fn mut_declaration(s: *Parser) ParsingResult {
    const mut = if (s.l.tok.? == .mut) blk: {
        switch (s.eat(.mut)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => break :blk true,
        }
    } else false;
    const name = s.create_node_ptr(switch (s.identifier()) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    const type_ = switch (s.l.tok.?) {
        .walrus => null,
        .colon => blk: {
            switch (s.eat(.colon)) {
                .diagnostic => |d| return .{ .diagnostic = d },
                else => {},
            }
            break :blk s.create_node_ptr(switch (s.non_literal_expression()) {
                .node => |n| n,
                .diagnostic => |d| return .{ .diagnostic = d },
                else => unreachable,
            });
        },
        else => return s.diagnostic(.err, "Unexpected token {any}, expected : [type] or :=", .{s.l.tok.?}),
    };
    switch (s.l.tok.?) {
        .walrus, .eq => switch (s.eat(s.l.tok.?)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        },
        else => return s.diagnostic(.err, "Unexpected token {any}, wanted := or =", .{s.l.tok.?}),
    }
    const val = s.create_node_ptr(switch (s.expression(0)) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    return node(Node{ .mut_declaration = .{ .mut = mut, .name = name, .type = type_, .val = val } });
}
fn statement(s: *Parser) ParsingResult {
    return switch (s.l.tok.?) {
        .@"if" => s.if_statement(),
        .@"for", .@"inline" => s.for_statement(),
        .@"while" => s.while_statement(),
        .@"defer" => s.defer_statement(),
        .match => s.match(),
        .lbrace => s.block(),
        .mut => blk: {
            const x = switch (s.mut_declaration()) {
                .diagnostic => |d| return .{ .diagnostic = d },
                .node => |n| n,
                else => unreachable,
            };
            switch (s.eat(.semicolon)) {
                .diagnostic => |d| return .{ .diagnostic = d },
                else => {},
            }
            break :blk node(x);
        },
        else => blk: {
            const state = s.save_lexer();
            var result: ParsingResult = undefined;
            var max_index: usize = 0;
            switch (s.labeled_block()) {
                .diagnostic => |d| {
                    if (s.l.index > max_index) {
                        max_index = s.l.index;
                        result = .{ .diagnostic = d };
                    }
                    s.restore_lexer(state);
                    switch (s.assign_expression()) {
                        .diagnostic => |d2| {
                            if (s.l.index > max_index) {
                                max_index = s.l.index;
                                result = .{ .diagnostic = d2 };
                            }
                            s.restore_lexer(state);
                            switch (s.mut_declaration()) {
                                .diagnostic => |d3| {
                                    if (s.l.index > max_index) {
                                        max_index = s.l.index;
                                        result = .{ .diagnostic = d3 };
                                    }
                                    s.restore_lexer(state);
                                    switch (s.expression(0)) {
                                        .diagnostic => |d4| {
                                            if (s.l.index > max_index) {
                                                max_index = s.l.index;
                                                result = .{ .diagnostic = d4 };
                                            }
                                        },
                                        .node => |n| result = node(n),
                                        else => unreachable
                                    }
                                },
                                .node => |n| result = node(n),
                                else => unreachable
                            }
                        },
                        .node => |n| result = node(n),
                        else => unreachable
                    }
                },
                .node => |n| result = node(n),
                else => unreachable
            }
            switch (result) {
                .node => |n| {
                    if (n != .block) {
                        switch (s.eat(.semicolon)) {
                            .diagnostic => |d| return .{ .diagnostic = d },
                            else => {},
                        }
                    }
                },
                else => {},
            }
            break :blk result;
        }
    };
}
// error and recover
fn block(s: *Parser) ParsingResult {
    var statements = NodeList.init(s.a);
    switch (s.eat(.lbrace)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    blk: while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rbrace) break;
        switch (s.statement()) {
            .diagnostic => |d| {
                s.f.diagnostics.append(d) catch |e| @panic(@errorName(e));
                s.recover(&[_]Token{ .rbrace, .semicolon });
                continue :blk;
            },
            .node => |n| append(&statements, n),
            else => {},
        }
        if (s.l.tok.? == .rbrace) break;
    }
    switch (s.eat(.rbrace)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .block = .{ .label = null, .statements = statements } });
}
fn labeled_block(s: *Parser) ParsingResult {
    const label = if (s.l.tok.? == .identifier) blk: {
        const x = s.create_node_ptr(switch (s.identifier()) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .node => |n| n,
            else => unreachable,
        });
        switch (s.eat(.colon)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
        break :blk x;
    } else null;
    var statements = NodeList.init(s.a);
    switch (s.eat(.lbrace)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    blk: while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rbrace) break;
        switch (s.statement()) {
            .diagnostic => |d| {
                s.f.diagnostics.append(d) catch |e| @panic(@errorName(e));
                s.recover(&[_]Token{ .rbrace, .semicolon });
                continue :blk;
            },
            .node => |n| append(&statements, n),
            else => {},
        }
        if (s.l.tok.? == .rbrace) break;
    }
    switch (s.eat(.rbrace)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .block = .{ .label = label, .statements = statements } });
}
fn function(s: *Parser) ParsingResult {
    const inline_ = if (s.l.tok.? == .@"inline") blk: {
        switch (s.eat(.@"inline")) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
        break :blk true;
    } else false;
    switch (s.eat(.lparen)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    var parameters = NodeList.init(s.a);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rparen) break;
        switch (s.function_parameter()) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .node => |n| append(&parameters, n),
            else => unreachable,
        }
        if (s.l.tok.? == .rparen) break;
        switch (s.eat(.comma)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
    }
    switch (s.eat(.rparen)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    const result = s.function_result();
    const body = switch (s.l.tok.?) {
        .arrow => s.create_node_ptr(switch (s.arrow_expression()) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .node => |n| n,
            else => unreachable,
        }),
        .lbrace => s.create_node_ptr(switch (s.block()) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .node => |n| n,
            else => unreachable,
        }),
        else => return s.diagnostic(.err, "Unexpected Function Body {any}, expected => or block", .{s.l.tok.?}),
    };
    return node(Node{ .function = .{ .inline_ = inline_, .parameters = parameters, .result = switch (result) {
        .node => |n| s.create_node_ptr(n),
        .diagnostic => |d| return .{ .diagnostic = d },
        .none => null,
        else => unreachable,
    }, .body = body } });
}
fn function_parameter(s: *Parser) ParsingResult {
    var names = NodeList.init(s.a);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .colon) break;
        switch (s.identifier()) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .node => |n| append(&names, n),
            else => unreachable,
        }
        if (s.l.tok.? == .colon) break;
        switch (s.eat(.comma)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
    }
    switch (s.eat(.colon)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    const t = if (s.l.tok.? == .comp) switch (s.comp_expression()) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    } else switch (s.non_literal_expression()) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    };
    return node(Node{ .function_parameter = .{ .names = names, .type = s.create_node_ptr(t) } });
}
fn function_result(s: *Parser) ParsingResult {
    var expr = switch (s.l.tok.?) {
        .arrow, .bang, .lbrace => null,
        else => switch (s.non_literal_expression()) {
            .node => |n| n,
            .diagnostic => |d| return .{ .diagnostic = d },
            else => unreachable,
        },
    };
    if (s.l.tok.? == .bang) switch (s.error_union_type(expr)) {
        .node => |n| expr = n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    };
    return if (expr) |e| node(e) else ParsingResult.none;
}
fn function_type(s: *Parser) ParsingResult {
    switch (s.eat(.lparen)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    var parameters = NodeList.init(s.a);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rparen) break;
        switch (s.non_literal_expression()) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .node => |n| append(&parameters, n),
            else => unreachable,
        }
        if (s.l.tok.? == .rparen) break;
        switch (s.eat(.comma)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
    }
    switch (s.eat(.rparen)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    const result = s.function_result();
    return node(Node{ .function_type = .{ .parameters = parameters, .result = switch (result) {
        .node => |n| s.create_node_ptr(n),
        .diagnostic => |d| return .{ .diagnostic = d },
        .none => null,
        else => unreachable
    } } });
}
fn arrow_expression(s: *Parser) ParsingResult {
    switch (s.eat(.arrow)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    const state = s.save_lexer();
    return node(Node{ .arrow_expression = .{ .expression = s.create_node_ptr(blk: {
        var result: ParsingResult = undefined;
        var max_index: usize = 0;
        switch (s.assign_expression()) {
            .diagnostic => |d| {
                if (s.l.index > max_index) {
                    max_index = s.l.index;
                    result = .{ .diagnostic = d };
                }
                s.restore_lexer(state);
                switch (s.expression(0)) {
                    .diagnostic => |d2| {
                        if (s.l.index > max_index) {
                            max_index = s.l.index;
                            result = .{ .diagnostic = d2 };
                        }
                    },
                    .node => |n| result = node(n),
                    else => unreachable
                }
            },
            .node => |n| result = node(n),
            else => unreachable
        }
        break :blk switch (result) {
            .node => |n| n,
            .diagnostic => |d| return .{ .diagnostic = d },
            else => unreachable
        };
    }) } });
}
fn assign_expression(s: *Parser) ParsingResult {
    const l = s.create_node_ptr(switch (s.expression(0)) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    const op = switch (s.assign_operator()) {
        .assign_op => |a| a,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    };
    const r = s.create_node_ptr(switch (s.expression(0)) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    return node(Node{ .assign_expression = .{ .left = l, .op = op, .right = r } });
}

fn assign_operator(s: *Parser) ParsingResult {
    const op: AssignOp = switch (s.l.tok.?) {
        .addeq => .addeq,
        .subeq => .subeq,
        .muleq => .muleq,
        .diveq => .diveq,
        .modeq => .modeq,
        .xoreq => .xoreq,
        .andeq => .andeq,
        .oreq => .oreq,
        .eq => .eq,
        else => return s.diagnostic(.err, "Unexpected assign op {any}", .{s.l.tok.?}),
    };
    switch (s.eat(s.l.tok.?)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return .{ .assign_op = op };
}
fn operator(s: *Parser) ParsingResult {
    const op: Op = switch (s.l.tok.?) {
        .add => .add,
        .sub => .sub,
        .mul => .mul,
        .div => .div,
        .mod => .mod,
        .xor => .xor,
        .@"and" => .@"and",
        .@"or" => .@"or",
        .eqeq => .eqeq,
        .bang => .bang,
        .gt => .gt,
        .gteq => .gte,
        .lt => .lt,
        .lteq => .lte,
        .andand => .andand,
        .oror => .oror,
        .bangeq => .bangeq,
        .nullish => .nullish,
        else => return s.diagnostic(.err, "Unexpected assign op {any}", .{s.l.tok.?}),
    };
    switch (s.eat(s.l.tok.?)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return .{ .op = op };
}
fn if_prefix(s: *Parser) ParsingResult {
    switch (s.eat(.@"if")) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    const expr = s.create_node_ptr(switch (s.expression(0)) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    const cap = if (s.l.tok.? == .colon) blk: {
        switch (s.eat(.colon)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
        break :blk s.create_node_ptr(switch (s.capture()) {
            .node => |n| n,
            .diagnostic => |d| return .{ .diagnostic = d },
            else => unreachable,
        });
    } else null;
    return node(Node{ .if_prefix = .{ .expression = expr, .capture = cap } });
}
fn while_prefix(s: *Parser) ParsingResult {
    switch (s.eat(.@"while")) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    const expr = s.create_node_ptr(switch (s.expression(0)) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    const cap = if (s.l.tok.? == .colon) blk: {
        switch (s.eat(.colon)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
        break :blk s.create_node_ptr(switch (s.capture()) {
            .node => |n| n,
            .diagnostic => |d| return .{ .diagnostic = d },
            else => unreachable,
        });
    } else null;
    return node(Node{ .while_prefix = .{ .expression = expr, .capture = cap } });
}
fn for_prefix(s: *Parser) ParsingResult {
    switch (s.eat(.@"for")) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    var expressions = NodeList.init(s.a);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .colon) break;
        switch (s.expression(0)) {
            .node => |n| append(&expressions, n),
            .diagnostic => |d| return .{ .diagnostic = d },
            else => unreachable,
        }
        if (s.l.tok.? == .colon) break;
        switch (s.eat(.comma)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
    }
    if (expressions.items.len == 0) return s.diagnostic(.err, "Expected at least 1 expression in for loop, got 0", .{});
    switch (s.eat(.colon)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    const cap = s.create_node_ptr(switch (s.capture()) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    return node(Node{ .for_prefix = .{ .expressions = expressions, .capture = cap } });
}
fn match(s: *Parser) ParsingResult {
    switch (s.eat(.match)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    const expr = s.create_node_ptr(switch (s.expression(0)) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    var arms = NodeList.init(s.a);
    switch (s.eat(.lbrace)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rbrace) break;
        switch (s.arm()) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .node => |n| append(&arms, n),
            else => unreachable,
        }
        if (s.l.tok.? == .rbrace) break;
    }
    switch (s.eat(.rbrace)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .match = .{ .expression = expr, .arms = arms } });
}
fn arm(s: *Parser) ParsingResult {
    var expressions = NodeList.init(s.a);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .colon) break;
        switch (s.expression(0)) {
            .node => |n| append(&expressions, n),
            .diagnostic => |d| return .{ .diagnostic = d },
            else => unreachable,
        }
        if (s.l.tok.? == .colon) break;
        switch (s.eat(.comma)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
    }
    switch (s.eat(.colon)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    const cap = if (s.l.tok.? == .@"or") s.create_node_ptr(switch (s.capture()) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    }) else null;
    const result = s.create_node_ptr(switch (s.result_block_expression()) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    if (s.l.tok.? != .rbrace) switch (s.eat(.comma)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    };
    return node(Node{ .arm = .{ .expressions = expressions, .capture = cap, .result = result } });
}
fn if_statement(s: *Parser) ParsingResult {
    const prefix = s.create_node_ptr(switch (s.if_prefix()) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    const body = s.create_node_ptr(if (s.l.tok.? == .lbrace) switch (s.block()) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    } else blk: {
        const state = s.save_lexer();
        var result: ParsingResult = undefined;
        var max_index: usize = 0;
        switch (s.assign_expression()) {
            .node => |n| result = node(n),
            .diagnostic => |d| {
                if (s.l.index > max_index) {
                    max_index = s.l.index;
                    result = .{ .diagnostic = d };
                }
                s.restore_lexer(state);
                switch (s.expression(0)) {
                    .node => |n| result = node(n),
                    .diagnostic => |d2| {
                        if (s.l.index > max_index) {
                            max_index = s.l.index;
                            result = .{ .diagnostic = d2 };
                        }
                    },
                    else => unreachable,
                }
            },
            else => unreachable,
        }
        break :blk switch (result) {
            .node => |n| n,
            .diagnostic => |d| return .{ .diagnostic = d },
            else => unreachable
        };
    });
    const else_body = switch (s.l.tok.?) {
        .semicolon => blk: {
            switch (s.eat(.semicolon)) {
                .diagnostic => |d| return .{ .diagnostic = d },
                else => {},
            }
            break :blk null;
        },
        .@"else" => blk: {
            switch (s.eat(.@"else")) {
                .diagnostic => |d| return .{ .diagnostic = d },
                else => {},
            }
            break :blk s.create_node_ptr(switch (s.result_block()) {
                .node => |n| n,
                .diagnostic => |d| return .{ .diagnostic = d },
                else => unreachable,
            });
        },
        else => return s.diagnostic(.err, "Unexpected token {any}, expected ; or else statement", .{s.l.tok.?}),
    };
    return node(Node{ .if_statement = .{ .prefix = prefix, .body = body, .else_body = else_body } });
}
fn while_statement(s: *Parser) ParsingResult {
    const prefix = s.create_node_ptr(switch (s.while_prefix()) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    const body = s.create_node_ptr(switch (s.result_block()) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    return node(Node{ .while_statement = .{ .prefix = prefix, .body = body } });
}
fn for_statement(s: *Parser) ParsingResult {
    const inline_ = if (s.l.tok.? == .@"inline") blk: {
        switch (s.eat(.@"inline")) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
        break :blk true;
    } else false;
    const prefix = s.create_node_ptr(switch (s.for_prefix()) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    const body = s.create_node_ptr(switch (s.result_block()) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    return node(Node{ .for_statement = .{ .inline_ = inline_, .prefix = prefix, .body = body } });
}
fn defer_statement(s: *Parser) ParsingResult {
    switch (s.eat(.@"defer")) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    const cap = if (s.l.tok.? == .@"or") s.create_node_ptr(switch (s.capture()) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    }) else null;
    const body = s.create_node_ptr(switch (s.result_block()) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    return node(Node{ .defer_statement = .{ .capture = cap, .body = body } });
}
fn result_block(s: *Parser) ParsingResult {
    return if (s.l.tok.? == .lbrace) switch (s.labeled_block()) {
        .node => |n| node(n),
        .diagnostic => |d| .{ .diagnostic = d },
        else => unreachable,
    } else switch (s.statement()) {
        .node => |n| node(n),
        .diagnostic => |d| .{ .diagnostic = d },
        else => unreachable,
    };
}
fn result_block_expression(s: *Parser) ParsingResult {
    const state = s.save_lexer();
    var result: ParsingResult = undefined;
    var max_index: usize = 0;
    return switch (s.labeled_block()) {
        .node => |n| node(n),
        .diagnostic => |d| blk: {
            if (s.l.index > max_index) {
                max_index = s.l.index;
                result = .{ .diagnostic = d };
            }
            s.restore_lexer(state);
            switch (s.assign_expression()) {
                .node => |n| result = node(n),
                .diagnostic => |d2| {
                    if (s.l.index > max_index) {
                        max_index = s.l.index;
                        result = .{ .diagnostic = d2 };
                    }
                    s.restore_lexer(state);
                    switch (s.expression(0)) {
                        .node => |n| result = node(n),
                        .diagnostic => |d3| {
                            if (s.l.index > max_index) {
                                max_index = s.l.index;
                                result = .{ .diagnostic = d3 };
                            }
                        },
                        else => unreachable,
                    }
                },
                else => unreachable,
            }
            break :blk result;
        },
        else => unreachable,
    };
}
fn expression(s: *Parser, prec: u8) ParsingResult {
    switch (s.l.tok.?) {
        .@"return" => return s.return_expression(),
        .@"break" => return s.break_expression(),
        .@"continue" => return s.continue_expression(),
        .@"for" => return s.for_expression(),
        .@"while" => return s.while_expression(),
        .comp => return s.comp_expression(),
        .use => return s.use_expression(),
        .@"if" => return s.if_expression(),
        .underscore => {
            switch (s.eat(.underscore)) {
                .diagnostic => |d| return .{ .diagnostic = d },
                else => {},
            }
            return node(Node.underscore);
        },
        else => {},
    }
    var expr = switch (s.l.tok.?) {
        .int, .float, .string, .char, .true, .false, .undefined, .null => switch (s.literal()) {
            .node => |n| n,
            .diagnostic => |d| return .{ .diagnostic = d },
            else => unreachable,
        },
        .bang, .flip, .sub, .@"and" => switch (s.unary_expression()) {
            .node => |n| n,
            .diagnostic => |d| return .{ .diagnostic = d },
            else => unreachable,
        },
        else => switch (s.non_literal_expression()) {
            .node => |n| n,
            .diagnostic => |d| return .{ .diagnostic = d },
            else => unreachable,
        },
    };
    while (s.l.tok.? != .eof and prec < s.precedence()) {
        if (s.l.tok.? == .dotdot) return switch (s.range_expression(expr)) {
            .node => |n| node(n),
            .diagnostic => |d| .{ .diagnostic = d },
            else => unreachable,
        };
        const new_prec = s.precedence();
        const state = s.save_lexer();
        const op = switch (s.operator()) {
            .diagnostic => {
                s.restore_lexer(state);
                return node(expr);
            },
            .op => |o| o,
            else => unreachable
        };
        expr = Node{ .binary = .{ .a = s.create_node_ptr(expr), .op = op, .b = s.create_node_ptr(switch (s.expression(new_prec)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .node => |n| n,
            else => unreachable,
        }) } };
    }
    return node(expr);
}
fn non_literal_expression(s: *Parser) ParsingResult {
    var expr = switch (s.l.tok.?) {
        .identifier => s.member_chain(),
        .question => s.optional_type(),
        .mul => s.pointer_type(),
        .@"try" => s.try_expression(),
        .@"if" => s.if_expression(),
        .@"inline" => s.function(),
        .lparen => blk: {
            const state = s.save_lexer();
            var result: ParsingResult = undefined;
            var max_index: usize = 0;
            switch (s.function()) {
                .node => |n| result = node(n),
                .diagnostic => |d| {
                    if (s.l.index > max_index) {
                        max_index = s.l.index;
                        result = .{ .diagnostic = d };
                    }
                    s.restore_lexer(state);
                    switch (s.function_type()) {
                        .node => |n| result = node(n),
                        .diagnostic => |d2| {
                            if (s.l.index > max_index) {
                                max_index = s.l.index;
                                result = .{ .diagnostic = d2 };
                            }
                            s.restore_lexer(state);
                            switch (s.grouped_expression()) {
                                .node => |n| result = node(n),
                                .diagnostic => |d3| {
                                    if (s.l.index > max_index) {
                                        max_index = s.l.index;
                                        result = .{ .diagnostic = d3 };
                                    }
                                },
                                else => unreachable
                            }
                        },
                        else => unreachable
                    }
                },
                else => unreachable
            }
            break :blk result;
        },
        .@"struct" => s.struct_(),
        .@"enum" => s.enum_(),
        .@"error" => s.error_(),
        .match => s.match(),
        .type => blk: {
            switch (s.eat(.type)) {
                .diagnostic => |d| return .{ .diagnostic = d },
                else => {},
            }
            break :blk node(Node.type);
        },
        .dot => blk: {
            switch (s.eat(.dot)) {
                .diagnostic => |d| return .{ .diagnostic = d },
                else => {},
            }
            const state = s.save_lexer();
            break :blk switch (s.l.tok.?) {
                .lbrace => s.struct_initialization(),
                .identifier => blk2: {
                    var result: ParsingResult = undefined;
                    var max_index: usize = 0;
                    switch (s.struct_initialization()) {
                        .diagnostic => |d| {
                            if (s.l.index > max_index) {
                                max_index = s.l.index;
                                result = .{ .diagnostic = d };
                            }
                            s.restore_lexer(state);
                            switch (s.enum_error_initialization()) {
                                .diagnostic => |d2| {
                                    if (s.l.index > max_index) {
                                        max_index = s.l.index;
                                        result = .{ .diagnostic = d2 };
                                    }
                                },
                                .node => |n| result = node(n),
                                else => unreachable
                            }
                        },
                        .node => |n| result = node(n),
                        else => unreachable,
                    }
                    break :blk2 result;
                },
                else => break :blk s.diagnostic(.err, "", .{})
            };
        },
        .lbrack => blk: {
            const state = s.save_lexer();
            var result: ParsingResult = undefined;
            var max_index: usize = 0;
            switch (s.array_type()) {
                .diagnostic => |d| {
                    if (s.l.index > max_index) {
                        max_index = s.l.index;
                        result = .{ .diagnostic = d };
                    }
                    s.restore_lexer(state);
                    switch (s.array_initialization()) {
                        .diagnostic => |d2| {
                            if (s.l.index > max_index) {
                                max_index = s.l.index;
                                result = .{ .diagnostic = d2 };
                            }
                        },
                        .node => |n| result = node(n),
                        else => unreachable
                    }
                },
                .node => |n| result = node(n),
                else => unreachable
            }
            break :blk result;
        },
        else => s.diagnostic(.err, "Invalid non literal expression {any}", .{s.l.tok.?}),
    };
    switch (expr) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |n| switch (n) {
            .array_type, .array_index, .pointer_type, .optional_type, .identifier, .member_access, .pointer_dereference, .optional_dereference, .struct_, .enum_, .error_, .grouped, .if_expression, .try_, .catch_ => {
                if (s.l.tok.? == .bang) expr = s.error_union_type(n);
            },
            .call => {
                if (s.l.tok.? == .@"catch") expr = s.catch_(n);
                if (s.l.tok.? == .bang) expr = s.error_union_type(n);
            },
            else => {},
        },
        else => unreachable
    }
    return expr;
}
fn member_chain(s: *Parser) ParsingResult {
    const state = s.save_lexer();
    var chain: Node = switch (s.labeled_block()) {
        .node => |n| return node(n),
        .diagnostic => |_| blk: {
            s.restore_lexer(state);
            break :blk switch (s.identifier()) {
                .node => |n| n,
                .diagnostic => |d| return .{ .diagnostic = d },
                else => unreachable
            };
        },
        else => unreachable
    };
    while (s.l.tok.? != .eof) {
        switch (s.l.tok.?) {
            .dot => chain = switch (s.eat(.dot)) {
                .diagnostic => |d| return .{ .diagnostic = d },
                else => switch (s.l.tok.?) {
                    .identifier => switch (s.member_access(chain)) {
                        .node => |n| n,
                        .diagnostic => |d| return .{ .diagnostic = d },
                        else => unreachable
                    },
                    else => return s.diagnostic(.err, "Invalid member access value {any}, wanted identifier", .{s.l.tok.?}),
                }
            },
            .lbrack => chain = switch (s.array_index(chain)) {
                .node => |n| n,
                .diagnostic => |d| return .{ .diagnostic = d },
                else => unreachable
            },
            .lparen => chain = switch (s.call(chain)) {
                .node => |n| n,
                .diagnostic => |d| return .{ .diagnostic = d },
                else => unreachable
            },
            .pointer_deref => chain = switch (s.pointer_dereference(chain)) {
                .node => |n| n,
                .diagnostic => |d| return .{ .diagnostic = d },
                else => unreachable
            },
            .optional_deref => chain = switch (s.optional_dereference(chain)) {
                .node => |n| n,
                .diagnostic => |d| return .{ .diagnostic = d },
                else => unreachable
            },
            else => break,
        }
    }
    return node(chain);
}
fn precedence(s: *Parser) u8 {
    return switch (s.l.tok.?) {
        .lparen, .lbrack, .dot => 17,
        .bang, .xor => 16,
        .mul, .div, .mod => 15,
        .add, .sub => 14,
        .nullish => 13,
        .@"and", .@"or" => 12,
        .lt, .gt => 11,
        .lteq, .gteq => 10,
        .eqeq, .bangeq => 9,
        .andand => 8,
        .oror => 7,
        .dotdot => 6,
        .eq, .addeq, .subeq, .muleq, .diveq, .modeq, .andeq, .oreq, .xoreq, .flipeq, .pointer_deref, .optional_deref, .@"else" => 2,
        else => 0,
    };
}
fn unary_expression(s: *Parser) ParsingResult {
    const op = switch (s.operator()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .op => |o| o,
        else => unreachable
    };
    const expr = s.create_node_ptr(switch (s.expression(0)) {
        .node => |i| i,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    return node(Node{ .unary = .{ .op = op, .b = expr } });
}
fn binary_expression(s: *Parser, n: Node) ParsingResult {
    const op = switch (s.operator()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |i| i,
        else => unreachable
    };
    const expr = s.create_node_ptr(switch (s.expression(0)) {
        .node => |i| i,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    return node(Node{ .binary = .{ .a = s.create_node_ptr(n), .op = op, .b = expr } });
}
fn return_expression(s: *Parser) ParsingResult {
    switch (s.eat(.@"return")) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    const val = if (s.l.tok.? == .semicolon) null else s.create_node_ptr(switch (s.expression(0)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |i| i,
        else => unreachable,
    });
    return node(Node{ .return_expression = .{ .val = val } });
}
fn break_expression(s: *Parser) ParsingResult {
    switch (s.eat(.@"break")) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    const label = if (s.l.tok.? == .colon) blk: {
        switch (s.eat(.colon)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
        break :blk s.create_node_ptr(switch (s.identifier()) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .node => |n| n,
            else => unreachable,
        });
    } else null;
    const val = if (s.l.tok.? == .semicolon) null else s.create_node_ptr(switch (s.expression(0)) {
        .node => |n| n,
        .diagnostic => |d| return .{ .diagnostic = d },
        else => unreachable,
    });
    return node(Node{ .break_expression = .{ .label = label, .val = val } });
}
fn continue_expression(s: *Parser) ParsingResult {
    switch (s.eat(.@"continue")) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    const label = if (s.l.tok.? == .colon) blk: {
        switch (s.eat(.colon)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
        break :blk s.create_node_ptr(switch (s.identifier()) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .node => |n| n,
            else => unreachable
        });
    } else null;
    return node(Node{ .continue_expression = .{ .label = label } });
}
fn nullish_expression(s: *Parser, n: Node) ParsingResult {
    switch (s.eat(.nullish)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    const b = s.create_node_ptr(switch (s.expression(0)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |i| i,
        else => unreachable
    });
    return node(Node{ .nullish_expression = .{ .a = s.create_node_ptr(n), .b = b } });
}
fn range_expression(s: *Parser, n: Node) ParsingResult {
    switch (s.eat(.dotdot)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    const b = s.create_node_ptr(switch (s.expression(0)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |i| i,
        else => unreachable
    });
    return node(Node{ .range_expression = .{ .a = s.create_node_ptr(n), .b = b } });
}
fn use_expression(s: *Parser) ParsingResult {
    switch (s.eat(.use)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    if (s.l.tok.? != .string) return s.diagnostic(.err, "String path expected for use statements", .{});
    const path = s.create_node_ptr(switch (s.literal()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |n| n,
        else => unreachable,
    });
    return node(Node{ .use = .{ .path = path } });
}
fn grouped_expression(s: *Parser) ParsingResult {
    switch (s.eat(.lparen)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    const expr = if (s.l.tok.? == .rparen) null else s.create_node_ptr(switch (s.expression(0)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |n| n,
        else => unreachable,
    });
    switch (s.eat(.rparen)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .grouped = .{ .expression = expr } });
}
fn if_expression(s: *Parser) ParsingResult {
    const prefix = s.create_node_ptr(switch (s.if_prefix()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |n| n,
        else => unreachable,
    });
    const body = s.create_node_ptr(if (s.l.tok.? == .lbrace) switch (s.block()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |n| n,
        else => unreachable,
    } else blk: {
        const state = s.save_lexer();
        var result: ParsingResult = undefined;
        var max_index: usize = 0;
        switch (s.assign_expression()) {
            .diagnostic => |d| {
                if (s.l.index > max_index) {
                    max_index = s.l.index;
                    result = .{ .diagnostic = d };
                }
                s.restore_lexer(state);
                switch (s.expression(0)) {
                    .diagnostic => |d2| {
                        if (s.l.index > max_index) result = .{ .diagnostic = d2 };
                    },
                    .node => |n| result = node(n),
                    else => unreachable,
                }
            },
            .node => |n| result = node(n),
            else => unreachable,
        }
        break :blk switch (result) {
            .node => |n| n,
            .diagnostic => |d| return .{ .diagnostic = d },
            else => unreachable
        };
    });
    const else_body = if (s.l.tok.? == .@"else") blk: {
        switch (s.eat(.@"else")) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
        break :blk s.create_node_ptr(switch (s.result_block_expression()) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .node => |n| n,
            else => unreachable,
        });
    } else null;
    return node(Node{ .if_expression = .{ .prefix = prefix, .body = body, .else_body = else_body } });
}
fn while_expression(s: *Parser) ParsingResult {
    const prefix = s.create_node_ptr(switch (s.while_prefix()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |n| n,
        else => unreachable,
    });
    const body = s.create_node_ptr(switch (s.result_block()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |n| n,
        else => unreachable,
    });
    return node(Node{ .while_expression = .{ .prefix = prefix, .body = body } });
}
fn for_expression(s: *Parser) ParsingResult {
    const prefix = s.create_node_ptr(switch (s.for_prefix()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |n| n,
        else => unreachable,
    });
    const body = s.create_node_ptr(switch (s.result_block()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |n| n,
        else => unreachable,
    });
    return node(Node{ .for_expression = .{ .prefix = prefix, .body = body } });
}
fn array_initialization(s: *Parser) ParsingResult {
    switch (s.eat(.lbrack)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    var vals = NodeList.init(s.a);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rbrack) break;
        switch (s.expression(0)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .node => |n| append(&vals, n),
            else => unreachable,
        }
        if (s.l.tok.? == .rbrack) break;
        switch (s.eat(.comma)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
    }
    switch (s.eat(.rbrack)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .array_init = .{ .vals = vals } });
}
fn struct_initialization(s: *Parser) ParsingResult {
    const name = if (s.l.tok.? == .identifier) s.create_node_ptr(switch (s.identifier()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |n| n,
        else => unreachable,
    }) else null;
    var inits = NodeList.init(s.a);
    switch (s.eat(.lbrace)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rbrace) break;
        switch (s.struct_init_member()) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .node => |n| append(&inits, n),
            else => unreachable,
        }
        if (s.l.tok.? == .rbrace) break;
        switch (s.eat(.comma)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
    }
    switch (s.eat(.rbrace)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .struct_init = .{ .name = name, .inits = inits } });
}
fn struct_init_member(s: *Parser) ParsingResult {
    const name = s.create_node_ptr(switch (s.identifier()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |n| n,
        else => unreachable,
    });
    switch (s.eat(.colon)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    const val = s.create_node_ptr(switch (s.expression(0)) {
        .diagnostic => |d| {
            return .{ .diagnostic = d };
        },
        .node => |n| n,
        else => unreachable,
    });
    return node(Node{ .struct_init_member = .{ .name = name, .val = val } });
}
fn enum_error_initialization(s: *Parser) ParsingResult {
    const name = s.create_node_ptr(switch (s.identifier()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |n| n,
        else => unreachable,
    });
    const val = if (s.l.tok.? == .lparen) blk: {
        switch (s.eat(.lparen)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
        const expr = s.create_node_ptr(switch (s.expression(0)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .node => |n| n,
            else => unreachable,
        });
        switch (s.eat(.rparen)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
        break :blk expr;
    } else null;
    return node(Node{ .enum_error_init = .{ .name = name, .val = val } });
}
fn struct_(s: *Parser) ParsingResult {
    switch (s.eat(.@"struct")) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    switch (s.eat(.lbrace)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    var members = NodeList.init(s.a);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rbrace) break;
        switch (s.struct_member()) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .node => |n| append(&members, n),
            else => unreachable,
        }
        if (s.l.tok.? == .rbrace) break;
    }
    switch (s.eat(.rbrace)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .struct_ = .{ .members = members } });
}
fn struct_member(s: *Parser) ParsingResult {
    const state = s.save_lexer();
    return switch (s.declaration()) {
        .node => |n| node(n),
        .diagnostic => |diag| blk: {
            const max_index: usize = s.l.index;
            s.restore_lexer(state);
            var names = NodeList.init(s.a);
            while (s.l.tok.? != .eof) {
                if (s.l.tok.? == .colon) break;
                switch (s.identifier()) {
                    .diagnostic => |d| return if (s.l.index > max_index) .{ .diagnostic = d } else .{ .diagnostic = diag },
                    .node => |n| append(&names, n),
                    else => unreachable,
                }
                if (s.l.tok.? == .colon) break;
                switch (s.eat(.comma)) {
                    .diagnostic => |d| return if (s.l.index > max_index) .{ .diagnostic = d } else .{ .diagnostic = diag },
                    else => {},
                }
            }
            switch (s.eat(.colon)) {
                .diagnostic => |d| return if (s.l.index > max_index) .{ .diagnostic = d } else .{ .diagnostic = diag },
                else => {},
            }
            const t = s.create_node_ptr(switch (s.non_literal_expression()) {
                .diagnostic => |d| return if (s.l.index > max_index) .{ .diagnostic = d } else .{ .diagnostic = diag },
                .node => |n| n,
                else => unreachable,
            });
            const val = if (s.l.tok.? == .eq) blk2: {
                switch (s.eat(.eq)) {
                    .diagnostic => |d| return if (s.l.index > max_index) .{ .diagnostic = d } else .{ .diagnostic = diag },
                    else => {},
                }
                break :blk2 s.create_node_ptr(switch (s.expression(0)) {
                    .diagnostic => |d| return if (s.l.index > max_index) .{ .diagnostic = d } else .{ .diagnostic = diag },
                    .node => |n| n,
                    else => unreachable,
                });
            } else null;
            switch (s.eat(.comma)) {
                .diagnostic => |d| return if (s.l.index > max_index) .{ .diagnostic = d } else .{ .diagnostic = diag },
                else => {},
            }
            break :blk node(Node{ .struct_member = .{ .names = names, .type = t, .val = val } });
        },
        else => unreachable,
    };
}
fn enum_(s: *Parser) ParsingResult {
    switch (s.eat(.@"enum")) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    switch (s.eat(.lbrace)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    var members = NodeList.init(s.a);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rbrace) break;
        switch (s.enum_member()) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .node => |n| append(&members, n),
            else => unreachable,
        }
        if (s.l.tok.? == .rbrace) break;
    }
    switch (s.eat(.rbrace)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .enum_ = .{ .members = members } });
}
fn enum_member(s: *Parser) ParsingResult {
    const state = s.save_lexer();
    return switch (s.declaration()) {
        .node => |n| node(n),
        .diagnostic => blk: {
            s.restore_lexer(state);
            const name = s.create_node_ptr(switch (s.identifier()) {
                .diagnostic => |d| return .{ .diagnostic = d },
                .node => |n| n,
                else => unreachable,
            });
            const t = if (s.l.tok.? == .colon) blk2: {
                switch (s.eat(.colon)) {
                    .diagnostic => |d| return .{ .diagnostic = d },
                    else => {},
                }
                break :blk2 s.create_node_ptr(switch (s.non_literal_expression()) {
                    .diagnostic => |d| return .{ .diagnostic = d },
                    .node => |n| n,
                    else => unreachable,
                });
            } else null;
            switch (s.eat(.comma)) {
                .diagnostic => |d| return .{ .diagnostic = d },
                else => {},
            }
            break :blk node(Node{ .enum_member = .{ .name = name, .type = t } });
        },
        else => unreachable,
    };
}
fn error_(s: *Parser) ParsingResult {
    switch (s.eat(.@"error")) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    switch (s.eat(.lbrace)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    var members = NodeList.init(s.a);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rbrace) break;
        switch (s.error_member()) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .node => |n| append(&members, n),
            else => unreachable,
        }
        if (s.l.tok.? == .rbrace) break;
    }
    switch (s.eat(.rbrace)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .error_ = .{ .members = members } });
}
fn error_member(s: *Parser) ParsingResult {
    const state = s.save_lexer();
    return switch (s.declaration()) {
        .node => |n| node(n),
        .diagnostic => blk: {
            s.restore_lexer(state);
            const name = s.create_node_ptr(switch (s.identifier()) {
                .diagnostic => |d| return .{ .diagnostic = d },
                .node => |n| n,
                else => unreachable,
            });
            const t = if (s.l.tok.? == .colon) blk2: {
                switch (s.eat(.colon)) {
                    .diagnostic => |d| return .{ .diagnostic = d },
                    else => {},
                }
                break :blk2 s.create_node_ptr(switch (s.non_literal_expression()) {
                    .diagnostic => |d| return .{ .diagnostic = d },
                    .node => |n| n,
                    else => unreachable,
                });
            } else null;
            switch (s.eat(.comma)) {
                .diagnostic => |d| return .{ .diagnostic = d },
                else => {},
            }
            break :blk node(Node{ .error_member = .{ .name = name, .type = t } });
        },
        else => unreachable,
    };
}
fn capture(s: *Parser) ParsingResult {
    switch (s.eat(.@"or")) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    var captures = NodeList.init(s.a);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .@"or") break;
        switch (s.capture_item()) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .node => |n| append(&captures, n),
            else => unreachable,
        }
        if (s.l.tok.? == .@"or") break;
        switch (s.eat(.comma)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
    }
    switch (s.eat(.@"or")) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .capture = .{ .captures = captures } });
}
fn capture_item(s: *Parser) ParsingResult {
    const mut = if (s.l.tok.? == .mut) blk: {
        switch (s.eat(.mut)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
        break :blk true;
    } else false;
    const val = s.create_node_ptr(switch (s.identifier()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |n| n,
        else => unreachable,
    });
    return node(Node{ .capture_val = .{ .mut = mut, .val = val } });
}

fn identifier(s: *Parser) ParsingResult {
    return node(Node{ .identifier = .{ .value = switch (s.eat(.identifier)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .string => |n| n,
        else => unreachable,
    } } });
}
fn try_expression(s: *Parser) ParsingResult {
    switch (s.eat(.@"try")) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .try_ = .{ .expression = s.create_node_ptr(switch (s.non_literal_expression()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |n| n,
        else => unreachable,
    }) } });
}
fn catch_(s: *Parser, n: Node) ParsingResult {
    switch (s.eat(.@"catch")) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    const cap = if (s.l.tok.? == .@"or") s.create_node_ptr(switch (s.capture()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |i| i,
        else => unreachable,
    }) else null;
    const body = s.create_node_ptr(switch (s.result_block()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |i| i,
        else => unreachable,
    });
    return node(Node{ .catch_ = .{ .capture = cap, .expression = s.create_node_ptr(n), .body = body } });
}
fn comp_expression(s: *Parser) ParsingResult {
    switch (s.eat(.comp)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .comp_expression = .{ .expression = s.create_node_ptr(switch (s.non_literal_expression()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |n| n,
        else => unreachable,
    }) } });
}
fn call(s: *Parser, n: Node) ParsingResult {
    switch (s.eat(.lparen)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    var args = NodeList.init(s.a);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .rparen) break;
        switch (s.expression(0)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .node => |i| append(&args, i),
            else => unreachable,
        }
        if (s.l.tok.? == .rparen) break;
        switch (s.eat(.comma)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
    }
    switch (s.eat(.rparen)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .call = .{ .name = s.create_node_ptr(n), .args = args } });
}
fn optional_dereference(s: *Parser, n: Node) ParsingResult {
    switch (s.eat(.optional_deref)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .optional_dereference = .{ .expression = s.create_node_ptr(n) } });
}
fn optional_type(s: *Parser) ParsingResult {
    switch (s.eat(.question)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .optional_type = .{ .expression = s.create_node_ptr(switch (s.non_literal_expression()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |n| n,
        else => unreachable,
    }) } });
}
fn pointer_dereference(s: *Parser, n: Node) ParsingResult {
    switch (s.eat(.pointer_deref)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .pointer_dereference = .{ .expression = s.create_node_ptr(n) } });
}
fn pointer_type(s: *Parser) ParsingResult {
    switch (s.eat(.mul)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .pointer_type = .{ .expression = s.create_node_ptr(switch (s.non_literal_expression()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |n| n,
        else => unreachable,
    }) } });
}
fn array_index(s: *Parser, n: Node) ParsingResult {
    switch (s.eat(.lbrack)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    const index = s.create_node_ptr(switch (s.expression(0)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |i| i,
        else => unreachable,
    });
    switch (s.eat(.rbrack)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .array_index = .{ .name = s.create_node_ptr(n), .index = index } });
}
fn array_type(s: *Parser) ParsingResult {
    switch (s.eat(.lbrack)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    switch (s.eat(.rbrack)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    return node(Node{ .array_type = .{ .expression = s.create_node_ptr(switch (s.non_literal_expression()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |n| n,
        else => unreachable,
    }) } });
}
fn error_union_type(s: *Parser, n: ?Node) ParsingResult {
    switch (s.eat(.bang)) {
        .diagnostic => |d| return .{ .diagnostic = d },
        else => {},
    }
    var errors = NodeList.init(s.a);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? != .identifier) break;
        switch (s.identifier()) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .node => |i| append(&errors, i),
            else => unreachable,
        }
        if (s.l.tok.? != .bang) break;
        switch (s.eat(.bang)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            else => {},
        }
    }
    return node(Node{ .error_union_type = .{ .name = if (n) |i| s.create_node_ptr(i) else null, .errors = errors } });
}
fn member_access(s: *Parser, n: Node) ParsingResult {
    return node(Node{ .member_access = .{ .name = s.create_node_ptr(n), .member = s.create_node_ptr(switch (s.identifier()) {
        .diagnostic => |d| return .{ .diagnostic = d },
        .node => |i| i,
        else => unreachable,
    }) } });
}
fn literal(s: *Parser) ParsingResult {
    return node(switch (s.l.tok.?) {
        .int => Node{ .literal = .{ .kind = .int, .val = switch (s.eat(.int)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .string => |i| i,
            else => unreachable,
        } } },
        .float => Node{ .literal = .{ .kind = .float, .val = switch (s.eat(.float)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .string => |i| i,
            else => unreachable,
        } } },
        .true => Node{ .literal = .{ .kind = .boolean, .val = switch (s.eat(.true)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .string => |i| i,
            else => unreachable,
        } } },
        .false => Node{ .literal = .{ .kind = .boolean, .val = switch (s.eat(.false)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .string => |i| i,
            else => unreachable,
        } } },
        .char => Node{ .literal = .{ .kind = .char, .val = switch (s.eat(.char)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .string => |i| i,
            else => unreachable,
        } } },
        .string => Node{ .literal = .{ .kind = .string, .val = switch (s.eat(.string)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .string => |i| i,
            else => unreachable,
        } } },
        .undefined => Node{ .literal = .{ .kind = .undefined, .val = switch (s.eat(.undefined)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .string => |i| i,
            else => unreachable,
        } } },
        .null => Node{ .literal = .{ .kind = .null, .val = switch (s.eat(.null)) {
            .diagnostic => |d| return .{ .diagnostic = d },
            .string => |i| i,
            else => unreachable,
        } } },
        else => return s.diagnostic(.err, "Invalid literal {any}", .{s.l.tok.?}),
    });
}
fn eat(s: *Parser, expected: Token) ParsingResult {
    if (s.l.tok.? != expected) return s.diagnostic(.err, "Unexpected token {any}, wanted {any}", .{ s.l.tok.?, expected });
    defer s.l.next_tok();
    return ParsingResult{ .string = s.l.literal orelse "" };
}
fn create_node_ptr(s: *Parser, n: Node) *Node {
    const x = s.a.create(Node) catch |e| @panic(@errorName(e));
    x.* = n;
    return x;
}
fn append(a: *std.ArrayList(Node), n: Node) void {
    a.append(n) catch |e| @panic(@errorName(e));
}
fn save_lexer(s: *Parser) LexerState {
    return .{ .tok = s.l.tok, .col = s.l.col, .line = s.l.line, .literal = s.l.literal, .index = s.l.index };
}
fn restore_lexer(s: *Parser, l: LexerState) void {
    s.l.tok = l.tok;
    s.l.col = l.col;
    s.l.line = l.line;
    s.l.literal = l.literal;
    s.l.index = l.index;
}
fn node(n: Node) ParsingResult {
    return .{ .node = n };
}
fn diagnostic(s: Parser, severity: Diagnostic.Severity, comptime fmt: []const u8, args: anytype) ParsingResult {
    const msg = std.fmt.allocPrint(s.a, fmt, args) catch |e| @panic(@errorName(e));
    return .{ .diagnostic = Diagnostic{ .filename = s.f.path, .severity = severity, .line = s.l.line, .col = s.l.col, .message = msg } };
}
fn recover(s: *Parser, toks: []const Token) void {
    while (s.l.tok.? != .eof) {
        if (std.mem.indexOf(Token, toks, &[_]Token{s.l.tok.?})) |_| {
            s.l.next_tok();
            return;
        }
        s.l.next_tok();
    }
}
