const std = @import("std");
const Lexer = @import("lexer.zig");
const Token = @import("token.zig").TokenType;
const Error = @import("errors.zig").Error;
const Node = @import("ast.zig").Node;
const LiteralKind = @import("ast.zig").LiteralKind;
const Op = @import("ast.zig").Op;
const AssignOp = @import("ast.zig").AssignOp;
const NodeList = std.ArrayList(Node);

const Self = @This();

const LexerState = struct { tok: ?Token, literal: ?[]const u8, line: usize, col: usize, index: usize };

l: Lexer,
a: std.mem.Allocator,

pub fn init(alloc: std.mem.Allocator, buf: []const u8) Self {
    return Self{ .l = Lexer.init(buf), .a = alloc };
}

pub fn program(s: *Self) anyerror!Node {
    s.l.next_tok();
    var declarations = NodeList.init(s.a);
    try declarations.append(try s.module_declaration());
    while(s.l.tok.? != .eof) try declarations.append(try s.declaration());
    return Node{ .program = .{ .declarations = declarations }};
}
fn module_declaration(s: *Self) anyerror!Node {
    _ = try s.eat(.module);
    const name = try s.create_node_ptr(try s.identifier());
    _ = try s.eat(.semicolon);
    return Node{ .module = .{ .name = name }};
}
fn declaration(s: *Self) anyerror!Node {
    const pub_ = if(s.l.tok.? == .@"pub") blk: {
        _ = try s.eat(.@"pub");
        break :blk true;
    } else false;
    const name = try s.create_node_ptr(try s.identifier());
    const type_ = switch(s.l.tok.?) {
        .walrus => null,
        .colon => blk: {
            _ = try s.eat(.colon);
            break :blk try s.create_node_ptr(try s.non_literal_expression());
        },
        else => return Error.ParserError,
    };
    switch(s.l.tok.?) {
        .walrus, .eq => _ = try s.eat(s.l.tok.?),
        else => return Error.ParserError
    }
    const val = try s.create_node_ptr(try s.expression(0));
    _ = try s.eat(.semicolon);
    return Node{ .declaration = .{ .pub_ = pub_, .name = name, .type = type_, .val = val }};
}
fn mut_declaration(s: *Self) anyerror!Node {
    const mut = if(s.l.tok.? == .@"mut") blk: {
        _ = try s.eat(.@"mut");
        break :blk true;
    } else false;
    const name = try s.create_node_ptr(try s.identifier());
    const type_ = switch(s.l.tok.?) {
        .walrus => null,
        .colon => blk: {
            _ = try s.eat(.colon);
            break :blk try s.create_node_ptr(try s.non_literal_expression());
        },
        else => return Error.ParserError,
    };
    switch(s.l.tok.?) {
        .walrus, .eq => _ = try s.eat(s.l.tok.?),
        else => return Error.ParserError
    }
    const val = try s.create_node_ptr(try s.expression(0));
    return Node{ .mut_declaration = .{ .mut = mut, .name = name, .type = type_, .val = val }};
}
fn statement(s: *Self) anyerror!Node {
    return switch (s.l.tok.?) {
        .@"if" => try s.if_statement(),
        .@"for", .@"inline" => try s.for_statement(),
        .@"while" => try s.while_statement(),
        .@"defer" => try s.defer_statement(),
        .match => try s.match(),
        .lbrace => try s.block(),
        .mut => blk: {
            const x = try s.mut_declaration();
            _ = try s.eat(.semicolon);
            break :blk x;
        },
        else => blk: {
            const state = s.save_lexer();
            const x = s.labeled_block() catch blk2: {
                s.restore_lexer(state);
                break :blk2 s.assign_expression() catch blk3: {
                    s.restore_lexer(state);
                    break :blk3 s.mut_declaration() catch blk4: {
                        s.restore_lexer(state);
                        break :blk4 try s.expression(0);
                    };
                };
            };
            if(x != .block) _ = try s.eat(.semicolon);
            break :blk x;
        }
    };
}
fn block(s: *Self) anyerror!Node {
    var statements = NodeList.init(s.a);
    _ = try s.eat(.lbrace);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .rbrace) break;
        try statements.append(try s.statement());
        if(s.l.tok.? == .rbrace) break;
    }
    _ = try s.eat(.rbrace);
    return Node{ .block = .{ .label = null, .statements = statements } };
}
fn labeled_block(s: *Self) anyerror!Node {
    const label = if(s.l.tok.? == .identifier) blk: {
        const x = try s.create_node_ptr(try s.identifier());
        _ = try s.eat(.colon);
        break :blk x;
    } else null;
    var statements = NodeList.init(s.a);
    _ = try s.eat(.lbrace);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .rbrace) break;
        try statements.append(try s.statement());
        if(s.l.tok.? == .rbrace) break;
    }
    _ = try s.eat(.rbrace);
    return Node{ .block = .{ .label = label, .statements = statements } };
}
fn function(s: *Self) anyerror!Node {
    const inline_ = if(s.l.tok.? == .@"inline") blk: {
        _ = try s.eat(.@"inline");
        break :blk true;
    } else false;
    _ = try s.eat(.lparen);
    var parameters = NodeList.init(s.a);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .rparen) break;
        try parameters.append(try s.function_parameter());
        if(s.l.tok.? == .rparen) break;
        _ = try s.eat(.comma);
    }
    _ = try s.eat(.rparen);
    const result = try s.function_result();
    const body = switch(s.l.tok.?) {
        .arrow => try s.create_node_ptr(try s.arrow_expression()),
        .lbrace => try s.create_node_ptr(try s.block()),
        else => return Error.ParserError,
    };
    return Node{ .function = .{ .inline_ = inline_, .parameters = parameters, .result = if(result) |r| try s.create_node_ptr(r) else null, .body = body }};
}
fn function_parameter(s: *Self) anyerror!Node {
    var names = NodeList.init(s.a);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .colon) break;
        try names.append(try s.identifier());
        if(s.l.tok.? == .colon) break;
        _ = try s.eat(.comma);
    }
    _ = try s.eat(.colon);
    const t = try s.create_node_ptr(if(s.l.tok.? == .comp) try s.comp_expression() else try s.non_literal_expression());
    return Node{ .function_parameter = .{ .names = names, .type = t }};
}
fn function_result(s: *Self) anyerror!?Node {
    var expr = switch(s.l.tok.?) {
        .arrow, .bang, .lbrace => null,
        else => try s.non_literal_expression(),
    };
    if(s.l.tok.? == .bang) expr = try s.error_union_type(expr);
    return expr;
}
fn function_type(s: *Self) anyerror!Node {
    _ = try s.eat(.lparen);
    var parameters = NodeList.init(s.a);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .rparen) break;
        try parameters.append(try s.non_literal_expression());
        if(s.l.tok.? == .rparen) break;
        _ = try s.eat(.comma);
    }
    _ = try s.eat(.rparen);
    const result = try s.function_result();
    return Node{ .function_type = .{ .parameters = parameters, .result = if(result) |r| try s.create_node_ptr(r) else null }};
}
fn arrow_expression(s: *Self) anyerror!Node {
    _ = try s.eat(.arrow);
    const state = s.save_lexer();
    return Node{ .arrow_expression = .{ .expression = try s.create_node_ptr(s.assign_expression() catch blk: {
        s.restore_lexer(state);
        break :blk try s.expression(0);
    }) } };
}
fn assign_expression(s: *Self) anyerror!Node {
    const l = try s.create_node_ptr(try s.expression(0));
    const op = try s.assign_operator();
    const r = try s.create_node_ptr(try s.expression(0));
    return Node { .assign_expression = .{ .left = l, .op = op, .right = r }};
}

fn assign_operator(s: *Self) !AssignOp {
    const op: AssignOp = switch(s.l.tok.?) {
        .addeq => .addeq,
        .subeq => .subeq,
        .muleq => .muleq,
        .diveq => .diveq,
        .modeq => .modeq,
        .xoreq => .xoreq,
        .andeq => .andeq,
        .oreq => .oreq,
        .eq => .eq,
        else => return Error.ParserError,
    };
    _ = try s.eat(s.l.tok.?);
    return op;
}
fn operator(s: *Self) !Op {
    const op: Op = switch(s.l.tok.?) {
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
        else => return Error.ParserError,
    };
    _ = try s.eat(s.l.tok.?);
    return op;
}
fn if_prefix(s: *Self) anyerror!Node {
    _ = try s.eat(.@"if");
    const expr = try s.create_node_ptr(try s.expression(0));
    const cap = if(s.l.tok.? == .colon) blk: {
        _ = try s.eat(.colon);
        break :blk try s.create_node_ptr(try s.capture());
    } else null;
    return Node{ .if_prefix = .{ .expression = expr, .capture = cap }};
}
fn while_prefix(s: *Self) anyerror!Node {
    _ = try s.eat(.@"while");
    const expr = try s.create_node_ptr(try s.expression(0));
    const cap = if(s.l.tok.? == .colon) blk: {
        _ = try s.eat(.colon);
        break :blk try s.create_node_ptr(try s.capture());
    } else null;
    return Node{ .while_prefix = .{ .expression = expr, .capture = cap }};
}
fn for_prefix(s: *Self) anyerror!Node {
    _ = try s.eat(.@"for");
    var expressions = NodeList.init(s.a);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .colon) break;
        try expressions.append(try s.expression(0));
        if(s.l.tok.? == .colon) break;
        _ = try s.eat(.comma);
    }
    if(expressions.items.len == 0) return Error.ParserError;
    _ = try s.eat(.colon);
    const cap = try s.create_node_ptr(try s.capture());
    return Node{ .for_prefix = .{ .expressions = expressions, .capture = cap }};
}
fn match(s: *Self) anyerror!Node {
    _ = try s.eat(.match);
    const expr = try s.create_node_ptr(try s.expression(0));
    var arms = NodeList.init(s.a);
    _ = try s.eat(.lbrace);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .rbrace) break;
        try arms.append(try s.arm());
        if(s.l.tok.? == .rbrace) break;
    }
    _ = try s.eat(.rbrace);
    return Node{ .match = .{ .expression = expr, .arms = arms }};
}
fn arm(s: *Self) anyerror!Node {
    var expressions = NodeList.init(s.a);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .colon) break;
        try expressions.append(try s.expression(0));
        if(s.l.tok.? == .colon) break;
        _ = try s.eat(.comma);
    }
    _ = try s.eat(.colon);
    const cap = if(s.l.tok.? == .@"or") try s.create_node_ptr(try s.capture()) else null;
    const result = try s.create_node_ptr(try s.result_block_expression());
    if(s.l.tok.? != .rbrace) _ = try s.eat(.comma);
    return Node{ .arm = .{ .expressions = expressions, .capture = cap, .result = result }};
}
fn if_statement(s: *Self) anyerror!Node {
    const prefix = try s.create_node_ptr(try s.if_prefix());
    const body = try s.create_node_ptr(if(s.l.tok.? == .lbrace) try s.block() else blk: {
        const state = s.save_lexer();
        break :blk s.assign_expression() catch blk2: {
            s.restore_lexer(state);
            break :blk2 try s.expression(0);
        };
    });
    const else_body = switch(s.l.tok.?) {
        .semicolon => blk: {
            _ = try s.eat(.semicolon);
            break :blk null;
        },
        .@"else" => blk: {
            _ = try s.eat(.@"else");
            break :blk try s.create_node_ptr(try s.result_block());
        },
        else => return Error.ParserError,
    };
    return Node{ .if_statement = .{ .prefix = prefix, .body = body, .else_body = else_body }};
}
fn while_statement(s: *Self) anyerror!Node {
    const prefix = try s.create_node_ptr(try s.while_prefix());
    const body = try s.create_node_ptr(try s.result_block());
    return Node{ .while_statement = .{ .prefix = prefix, .body = body }};
}
fn for_statement(s: *Self) anyerror!Node {
    const inline_ = if(s.l.tok.? == .@"inline") blk: {
        _ = try s.eat(.@"inline");
        break :blk true;
    } else false;
    const prefix = try s.create_node_ptr(try s.for_prefix());
    const body = try s.create_node_ptr(try s.result_block());
    return Node{ .for_statement = .{ .inline_ = inline_,.prefix = prefix, .body = body }};
}
fn defer_statement(s: *Self) anyerror!Node {
    _ = try s.eat(.@"defer");
    const cap = if(s.l.tok.? == .@"or") try s.create_node_ptr(try s.capture()) else null;
    const body = try s.create_node_ptr(try s.result_block());
    return Node{ .defer_statement = .{ .capture = cap, .body = body }};
}
fn result_block(s: *Self) anyerror!Node {
    return if(s.l.tok.? == .lbrace) try s.labeled_block() else try s.statement();
}
fn result_block_expression(s: *Self) anyerror!Node {
    const state = s.save_lexer();
    return s.labeled_block() catch blk: {
        s.restore_lexer(state);
        break :blk s.assign_expression() catch blk2: {
            s.restore_lexer(state);
            break :blk2 try s.expression(0);
        };
    };
}
fn expression(s: *Self, prec: u8) anyerror!Node {
    switch(s.l.tok.?) {
        .@"return" => return try s.return_expression(),
        .@"break" => return try s.break_expression(),
        .@"continue" => return try s.continue_expression(),
        .@"for" => return try s.for_expression(),
        .@"while" => return try s.while_expression(),
        .comp => return try s.comp_expression(),
        .use => return try s.use_expression(),
        .@"if" => return try s.if_expression(),
        .underscore => {
            _ = try s.eat(.underscore);
            return Node.underscore;
        },
        else => {},
    }
    var expr = switch(s.l.tok.?) {
        .int, .float, .string, .char, .true, .false, .undefined, .null => try s.literal(),
        .bang, .flip, .sub, .@"and" => try s.unary_expression(),
        else => try s.non_literal_expression(),
    };
    while(s.l.tok.? != .eof and prec < s.precedence()) {
        if(s.l.tok.? == .dotdot) return try s.range_expression(expr);
        const new_prec = s.precedence();
        const state = s.save_lexer();
        const op = s.operator() catch {
            s.restore_lexer(state);
            return expr;
        };
        expr = Node{ .binary = .{ .a = try s.create_node_ptr(expr), .op = op, .b = try s.create_node_ptr(try s.expression(new_prec)) }};
    }
    return expr;
}
fn non_literal_expression(s: *Self) anyerror!Node {
    var expr = switch(s.l.tok.?) {
        .identifier => try s.member_chain(),
        .question => try s.optional_type(),
        .mul => try s.pointer_type(),
        .@"try" => try s.try_expression(),
        .@"if" => try s.if_expression(),
        .@"inline" => try s.function(),
        .lparen => blk: {
            const state = s.save_lexer();
            break :blk s.function() catch blk2: {
                s.restore_lexer(state);
                break :blk2 s.function_type() catch blk3: {
                    s.restore_lexer(state);
                    break :blk3 try s.grouped_expression();
                };
            };
        },
        .@"struct" => try s.struct_(),
        .@"enum" => try s.enum_(),
        .@"error" => try s.error_(),
        .match => try s.match(),
        .type => blk: {
            _ = try s.eat(.type);
            break :blk Node.@"type";
        },
        .dot => blk: {
            _ = try s.eat(.dot);
            const state = s.save_lexer();
            break :blk switch(s.l.tok.?) {
                .lbrace => try s.struct_initialization(),
                .identifier => s.struct_initialization() catch blk2: {
                    s.restore_lexer(state);
                    break :blk2 try s.enum_error_initialization();
                },
                else => return Error.ParserError,
            };
        },
        .lbrack => blk: {
            const state = s.save_lexer();
            break :blk s.array_type() catch blk2: {
                s.restore_lexer(state);
                break :blk2 try s.array_initialization();
            };
        },
        else => return Error.ParserError,
    };
    switch(expr) {
        .array_type, .array_index, .pointer_type, .optional_type, .identifier, .member_access, .pointer_dereference, .optional_dereference, .struct_, .enum_, .error_, .grouped, .if_expression, .try_, .catch_ => {
            if(s.l.tok.? == .bang) expr = try s.error_union_type(expr);
        },
        .call => {
            if(s.l.tok.? == .@"catch") expr = try s.catch_(expr);
            if(s.l.tok.? == .bang) expr = try s.error_union_type(expr);
        },
        else => {},
    }
    return expr;
}
fn member_chain(s: *Self) anyerror!Node {
    const state = s.save_lexer();
    var chain = s.labeled_block() catch blk: {
        s.restore_lexer(state);
        break :blk try s.identifier();
    };
    if(chain == .block) return chain;
    while (s.l.tok.? != .eof) {
        switch (s.l.tok.?) {
            .dot => {
                _ = try s.eat(.dot);
                chain = switch(s.l.tok.?) {
                    .identifier => try s.member_access(chain),
                    else => return Error.ParserError,
                };
            },
            .lbrack => chain = try s.array_index(chain),
            .lparen => chain = try s.call(chain),
            .pointer_deref => chain = try s.pointer_dereference(chain),
            .optional_deref => chain = try s.optional_dereference(chain),
            else => break,
        }
    }
    return chain;
}
fn precedence(s: *Self) u8 {
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
fn unary_expression(s: *Self) anyerror!Node {
    const op = try s.operator();
    const expr = try s.create_node_ptr(try s.expression(0));
    return Node{ .unary = .{ .op = op, .b = expr }};
}
fn binary_expression(s: *Self, n: Node) anyerror!Node {
    const op = try s.operator();
    const expr = try s.create_node_ptr(try s.expression(0));
    return Node{ .binary = .{ .a = try s.create_node_ptr(n), .op = op, .b = expr }};
}
fn return_expression(s: *Self) anyerror!Node {
    _ = try s.eat(.@"return");
    const val = if(s.l.tok.? == .semicolon) null else try s.create_node_ptr(try s.expression(0));
    return Node{ .return_expression = .{ .val = val }};
}
fn break_expression(s: *Self) anyerror!Node {
    _ = try s.eat(.@"break");
    const label = if(s.l.tok.? == .colon) blk: {
        _ = try s.eat(.colon);
        break :blk try s.create_node_ptr(try s.identifier());
    } else null;
    const val = if(s.l.tok.? == .semicolon) null else try s.create_node_ptr(try s.expression(0));
    return Node{ .break_expression = .{ .label = label, .val = val }};
}
fn continue_expression(s: *Self) anyerror!Node {
    _ = try s.eat(.@"continue");
    const label = if(s.l.tok.? == .colon) blk: {
        _ = try s.eat(.colon);
        break :blk try s.create_node_ptr(try s.identifier());
    } else null;
    return Node{ .continue_expression = .{ .label = label }};
}
fn nullish_expression(s: *Self) anyerror!Node {
    const a = try s.create_node_ptr(try s.expression(0));
    _ = try s.eat();
    const b = try s.create_node_ptr(try s.expression(0));
    return Node{ .nullish_expression = .{ .a = a, .b = b }};
}
fn range_expression(s: *Self, n: Node) anyerror!Node {
    _ = try s.eat(.dotdot);
    const b = try s.create_node_ptr(try s.expression(0));
    return Node{ .range_expression = .{ .a = try s.create_node_ptr(n), .b = b }};
}
fn use_expression(s: *Self) anyerror!Node {
    _ = try s.eat(.use);
    if(s.l.tok.? != .string) return Error.ParserError;
    const path = try s.create_node_ptr(try s.literal());
    return Node{ .use = .{ .path = path }};
}
fn grouped_expression(s: *Self) anyerror!Node {
   _ = try s.eat(.lparen);
    const expr = if(s.l.tok.? == .rparen) null else try s.create_node_ptr(try s.expression(0));
    _ = try s.eat(.rparen);
    return Node { .grouped = .{ .expression = expr }};
}
fn if_expression(s: *Self) anyerror!Node {
    const prefix = try s.create_node_ptr(try s.if_prefix());
    const body = try s.create_node_ptr(if(s.l.tok.? == .lbrace) try s.block() else blk: {
        const state = s.save_lexer();
        break :blk s.assign_expression() catch blk2: {
            s.restore_lexer(state);
            break :blk2 try s.expression(0);
        };
    });
    const else_body = if(s.l.tok.? == .@"else") blk: {
        _ = try s.eat(.@"else");
        break :blk try s.create_node_ptr(try s.result_block_expression());
    } else null;
    return Node{ .if_expression = .{ .prefix = prefix, .body = body, .else_body = else_body }};
}
fn while_expression(s: *Self) anyerror!Node {
    const prefix = try s.create_node_ptr(try s.while_prefix());
    const body = try s.create_node_ptr(try s.result_block());
    return Node{ .while_expression = .{ .prefix = prefix, .body = body }};
}
fn for_expression(s: *Self) anyerror!Node {
    const prefix = try s.create_node_ptr(try s.for_prefix());
    const body = try s.create_node_ptr(try s.result_block());
    return Node{ .for_expression = .{ .prefix = prefix, .body = body }};
}
fn array_initialization(s: *Self) anyerror!Node {
    _ = try s.eat(.lbrack);
    var vals = NodeList.init(s.a);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .rbrack) break;
        try vals.append(try s.expression(0));
        if(s.l.tok.? == .rbrack) break;
        _ = try s.eat(.comma);
    }
    _ = try s.eat(.rbrack);
    return Node{ .array_init = .{ .vals = vals }};
}
fn struct_initialization(s: *Self) anyerror!Node {
    const name = if(s.l.tok.? == .identifier) try s.create_node_ptr(try s.identifier()) else null;
    var inits = NodeList.init(s.a);
    _ = try s.eat(.lbrace);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .rbrace) break;
        try inits.append(try s.struct_init_member());
        if(s.l.tok.? == .rbrace) break;
        _ = try s.eat(.comma);
    }
    _ = try s.eat(.rbrace);
    return Node{ .struct_init = .{ .name = name, .inits = inits }};
}
fn struct_init_member(s: *Self) anyerror!Node {
    const name = try s.create_node_ptr(try s.identifier());
    _ = try s.eat(.colon);
    const val = try s.create_node_ptr(try s.expression(0));
    return Node{ .struct_init_member = .{ .name = name, .val = val}};
}
fn enum_error_initialization(s: *Self) anyerror!Node {
    const name = try s.create_node_ptr(try s.identifier());
    const val = if(s.l.tok.? == .lparen) blk: {
        _ = try s.eat(.lparen);
        const expr = try s.create_node_ptr(try s.expression(0));
        _ = try s.eat(.rparen);
        break :blk expr;
    } else null;
    return Node{ .enum_error_init = .{ .name = name, .val = val }};
}
fn struct_(s: *Self) anyerror!Node {
    _ = try s.eat(.@"struct");
    _ = try s.eat(.lbrace);
    var members = NodeList.init(s.a);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .rbrace) break;
        try members.append(try s.struct_member());
        if(s.l.tok.? == .rbrace) break;
    }
    _ = try s.eat(.rbrace);
    return Node{ .struct_ = .{ .members = members }};
}
fn struct_member(s: *Self) anyerror!Node {
    const state = s.save_lexer();
    return s.declaration() catch blk: {
        s.restore_lexer(state);
        var names = NodeList.init(s.a);
        while(s.l.tok.? != .eof) {
            if(s.l.tok.? == .colon) break;
            try names.append(try s.identifier());
            if(s.l.tok.? == .colon) break;
            _ = try s.eat(.comma);
        }
        _ = try s.eat(.colon);
        const t = try s.create_node_ptr(try s.non_literal_expression());
        const val = if(s.l.tok.? == .eq) blk2: {
            _ = try s.eat(.eq);
            break :blk2 try s.create_node_ptr(try s.expression(0));
        } else null;
        _ = try s.eat(.comma);
        break :blk Node{ .struct_member = .{ .names = names, .type = t, .val = val }};
    };
}
fn enum_(s: *Self) anyerror!Node {
    _ = try s.eat(.@"enum");
    _ = try s.eat(.lbrace);
    var members = NodeList.init(s.a);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .rbrace) break;
        try members.append(try s.enum_member());
        if(s.l.tok.? == .rbrace) break;
    }
    _ = try s.eat(.rbrace);
    return Node{ .enum_ = .{ .members = members }};
}
fn enum_member(s: *Self) anyerror!Node {
    const state = s.save_lexer();
    return s.declaration() catch blk: {
        s.restore_lexer(state);
        const name = try s.create_node_ptr(try s.identifier());
        const t = if(s.l.tok.? == .colon) blk2: {
            _ = try s.eat(.colon);
            break :blk2 try s.create_node_ptr(try s.non_literal_expression());
        } else null;
        _ = try s.eat(.comma);
        break :blk Node{ .enum_member = .{ .name = name, .type = t }};
    };
}
fn error_(s: *Self) anyerror!Node {
    _ = try s.eat(.@"error");
    _ = try s.eat(.lbrace);
    var members = NodeList.init(s.a);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .rbrace) break;
        try members.append(try s.error_member());
        if(s.l.tok.? == .rbrace) break;
    }
    _ = try s.eat(.rbrace);
    return Node{ .error_ = .{ .members = members }};
}
fn error_member(s: *Self) anyerror!Node {
    const state = s.save_lexer();
    return s.declaration() catch blk: {
        s.restore_lexer(state);
        const name = try s.create_node_ptr(try s.identifier());
        const t = if(s.l.tok.? == .colon) blk2: {
            _ = try s.eat(.colon);
            break :blk2 try s.create_node_ptr(try s.non_literal_expression());
        } else null;
        _ = try s.eat(.comma);
        break :blk Node{ .error_member = .{ .name = name, .type = t }};
    };
}
fn capture(s: *Self) anyerror!Node {
    _ = try s.eat(.@"or");
    var captures = NodeList.init(s.a);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .@"or") break;
        try captures.append(try s.capture_item());
        if(s.l.tok.? == .@"or") break;
        _ = try s.eat(.comma);
    }
    _ = try s.eat(.@"or");
    return Node{ .capture = .{ .captures = captures }};
}
fn capture_item(s: *Self) anyerror!Node {
    const mut = if(s.l.tok.? == .mut) blk: {
        _ = try s.eat(.mut);
        break :blk true;
    } else false;
    const val = try s.create_node_ptr(try s.identifier());
    return Node{ .capture_val = .{ .mut = mut, .val = val }};
}

fn identifier(s: *Self) anyerror!Node {
    return Node{ .identifier = .{ .value = try s.eat(.identifier) } };
}
fn try_expression(s: *Self) anyerror!Node {
    _ = try s.eat(.@"try");
    return Node{ .try_ = .{ .expression = try s.create_node_ptr(try s.non_literal_expression()) }};
}
fn catch_(s: *Self, n: Node) anyerror!Node {
    _ = try s.eat(.@"catch");
    const cap = if(s.l.tok.? == .@"or") try s.create_node_ptr(try s.capture()) else null;
    const body = try s.create_node_ptr(try s.result_block());
    return Node{ .catch_ = .{ .capture = cap, .expression = try s.create_node_ptr(n), .body = body }};
}
fn comp_expression(s: *Self) anyerror!Node {
    _ = try s.eat(.comp);
    return Node{ .comp_expression = .{ .expression = try s.create_node_ptr(try s.non_literal_expression()) }};
}
fn call(s: *Self, n: Node) anyerror!Node {
    _ = try s.eat(.lparen);
    var args = NodeList.init(s.a);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .rparen) break;
        try args.append(try s.expression(0));
        if(s.l.tok.? == .rparen) break;
        _ = try s.eat(.comma);
    }
    _ = try s.eat(.rparen);
    return Node{ .call = .{ .name = try s.create_node_ptr(n), .args = args }};
}
fn optional_dereference(s: *Self, n: Node) anyerror!Node {
    _ = try s.eat(.optional_deref);
    return Node{ .pointer_dereference = .{ .expression = try s.create_node_ptr(n) }};
}
fn optional_type(s: *Self) anyerror!Node {
    _ = try s.eat(.question);
    return Node{ .optional_type = .{ .expression = try s.create_node_ptr(try s.non_literal_expression()) }};
}
fn pointer_dereference(s: *Self, n: Node) anyerror!Node {
    _ = try s.eat(.pointer_deref);
    return Node{ .pointer_dereference = .{ .expression = try s.create_node_ptr(n) }};
}
fn pointer_type(s: *Self) anyerror!Node {
    _ = try s.eat(.mul);
    return Node{ .pointer_type = .{ .expression = try s.create_node_ptr(try s.non_literal_expression()) }};
}
fn array_index(s: *Self, n: Node) anyerror!Node {
    _ = try s.eat(.lbrack);
    const index = try s.create_node_ptr(try s.expression(0));
    _ = try s.eat(.rbrack);
    return Node{ .array_index = .{ .name = try s.create_node_ptr(n), .index = index }};
}
fn array_type(s: *Self) anyerror!Node {
    _ = try s.eat(.lbrack);
    _ = try s.eat(.rbrack);
    return Node{ .array_type = .{ .expression = try s.create_node_ptr(try s.non_literal_expression()) }};
}
fn error_union_type(s: *Self, n: ?Node) anyerror!Node {
    _ = try s.eat(.bang);
    var errors = NodeList.init(s.a);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? != .identifier) break;
        try errors.append(try s.identifier());
        if(s.l.tok.? != .bang) break;
        _ = try s.eat(.bang);
    }
    return Node { .error_union_type = .{ .name = if(n) |i| try s.create_node_ptr(i) else null, .errors = errors }};
}
fn member_access(s: *Self, n: Node) anyerror!Node {
    return Node{ .member_access = .{ .name = try s.create_node_ptr(n), .member = try s.create_node_ptr(try s.identifier()) }};
}
fn literal(s: *Self) anyerror!Node {
    return switch(s.l.tok.?) {
        .int => Node { .literal = .{ .kind = .int, .val = try s.eat(.int) }},
        .float => Node { .literal = .{ .kind = .float, .val = try s.eat(.float) }},
        .true => Node { .literal = .{ .kind = .boolean, .val = try s.eat(.true) }},
        .false => Node { .literal = .{ .kind = .boolean, .val = try s.eat(.false) }},
        .char => Node { .literal = .{ .kind = .char, .val = try s.eat(.char) }},
        .string => Node { .literal = .{ .kind = .string, .val = try s.eat(.string) }},
        .undefined => Node { .literal = .{ .kind = .undefined, .val = try s.eat(.undefined) }},
        .null => Node { .literal = .{ .kind = .null, .val = try s.eat(.null) }},
        else => return Error.ParserError,
    };
}
fn eat(s: *Self, expected: Token) ![]const u8 {
    if (s.l.tok.? != expected) return Error.ParserError;
    defer s.l.next_tok();
    return s.l.literal orelse "";
}
fn create_node_ptr(s: *Self, n: Node) !*Node {
    const x = try s.a.create(Node);
    x.* = n;
    return x;
}
fn save_lexer(s: *Self) LexerState {
    return .{ .tok = s.l.tok, .col = s.l.col, .line = s.l.line, .literal = s.l.literal, .index = s.l.index};
}
fn restore_lexer(s: *Self, l: LexerState) void {
    s.l.tok = l.tok;
    s.l.col = l.col;
    s.l.line = l.line;
    s.l.literal = l.literal;
    s.l.index = l.index;
}
