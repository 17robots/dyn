const std = @import("std");
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;
const Diagnostic = @import("diagnostic.zig").Diagnostic;
const Lexer = @import("lexer.zig");
const Node = @import("ast.zig").Node;
const Source = @import("source.zig").Source;
const SourceLocation = @import("source.zig").SourceLocation;
const TokenType = @import("token.zig").TokenType;
const Token = @import("token.zig").Token;
const LiteralKind = @import("ast.zig").LiteralKind;

const Parser = @This();
const ParserError = error{
    recoverable,
    fatal,
};

allocator: std.mem.Allocator,
diag: *DiagnosticEmitter,
lexer: Lexer,
source: *Source,
curr_tok: Token,
next_tok: Token,
peek_tok: Token,

// AND FIX RESULT BLOCKS SO THEY DONT NEED SEMICOLONS IF THERE ARE ELSES

pub fn init(allocator: std.mem.Allocator, source: *Source, diagnostics: *DiagnosticEmitter) Parser {
    var parser = Parser{ .allocator = allocator, .source = source, .lexer = Lexer.init(source, diagnostics), .diag = diagnostics, .curr_tok = undefined, .next_tok = undefined, .peek_tok = undefined };
    parser.advance();
    parser.advance();
    parser.advance();
    return parser;
}
pub fn module_declaration(s: *Parser) ParserError!Node {
    try s.expect(.module);
    return Node{ .module = .{ .name = s.create_node_ptr(try s.identifier()) } };
}
pub fn parse(s: *Parser) ?Node {
    const module_decl = s.module_declaration() catch return null;
    s.expect(.semicolon) catch return null;
    var declarations = std.ArrayList(Node).init(s.allocator);
    declarations.append(module_decl) catch |e| @panic(@errorName(e));
    blk: while (s.curr_tok.tok_type != .eof) {
        declarations.append(s.declaration(true) catch |e| switch (e) {
            error.recoverable => {
                s.sync(&[_]TokenType{.semicolon});
                continue :blk;
            },
            error.fatal => return null,
        }) catch |e| @panic(@errorName(e));
        s.expect(.semicolon) catch return null;
    }
    return Node{ .program = .{ .declarations = declarations } };
}

// private methods
fn arm(s: *Parser, expr: bool) ParserError!Node {
    var exprs = std.ArrayList(Node).init(s.allocator);
    while (s.curr_tok.tok_type != .eof) {
        if (s.curr_tok.tok_type == .colon) break;
        exprs.append(if (expr) try s.expression(0) else try s.statement()) catch |e| @panic(@errorName(e));
        if (s.curr_tok.tok_type == .colon) break;
        try s.expect(.comma);
    }
    try s.expect(.colon);
    const cap = if (s.curr_tok.tok_type == .@"or") s.create_node_ptr(try s.capture()) else null;
    return Node{ .arm = .{ .expressions = exprs, .capture = cap, .result = s.create_node_ptr(if (expr) try s.result_block_expression() else try s.result_block()) } };
}
fn assign_expression(s: *Parser, n: Node) ParserError!Node {
    const a = s.create_node_ptr(n);
    const op: Node = switch (s.curr_tok.tok_type) {
        .addeq => Node.addeq,
        .subeq => Node.subeq,
        .muleq => Node.muleq,
        .diveq => Node.diveq,
        .modeq => Node.modeq,
        .andeq => Node.andeq,
        .oreq => Node.oreq,
        .xoreq => Node.xoreq,
        .eq => Node.eq,
        else => {
            s.diag.emit(s.source.id, @intCast(s.lexer.index), .err, "Invalid assign operator {any}", .{s.curr_tok.tok_type});
            return ParserError.recoverable;
        },
    };
    try s.expect(s.curr_tok.tok_type);
    return Node{ .assign_expression = .{ .left = a, .op = s.create_node_ptr(op), .right = s.create_node_ptr(try s.expression(0)) } };
}
fn block(s: *Parser, labeled: bool) ParserError!Node {
    const label = if (labeled) blk: {
        break :blk if (s.curr_tok.tok_type == .identifier) blk2: {
            const lbl = s.create_node_ptr(try s.identifier());
            try s.expect(.colon);
            break :blk2 lbl;
        } else null;
    } else null;
    try s.expect(.lbrace);
    var stmts = std.ArrayList(Node).init(s.allocator);
    blk: while (s.curr_tok.tok_type != .eof) {
        if (s.curr_tok.tok_type == .rbrace) break;
        const stmt = s.statement() catch |e| switch (e) {
            ParserError.recoverable => {
                s.sync(&[_]TokenType{ .rbrace, .semicolon });
                continue :blk;
            },
            ParserError.fatal => return e,
        };
        if (should_read_semicolon(stmt)) try s.expect(.semicolon);
        stmts.append(stmt) catch |e| @panic(@errorName(e)); // change this to synch
        if (s.curr_tok.tok_type == .rbrace) break;
    }
    try s.expect(.rbrace);
    return Node{ .block = .{ .label = label, .statements = stmts } };
}
fn break_expression(s: *Parser) ParserError!Node {
    try s.expect(.@"break");
    const label = if (s.curr_tok.tok_type == .colon) blk: {
        try s.expect(.colon);
        break :blk s.create_node_ptr(try s.identifier());
    } else null;
    return Node{ .break_expression = .{ .label = label, .val = if (s.curr_tok.tok_type == .semicolon) null else s.create_node_ptr(try s.expression(0)) } };
}
fn catch_(s: *Parser, n: Node) ParserError!Node {
    try s.expect(.@"catch");
    const cap = if (s.curr_tok.tok_type == .@"or")  s.create_node_ptr(try s.capture()) else null;
    return Node{ .catch_ = .{ .expression = s.create_node_ptr(n), .capture = cap, .body = s.create_node_ptr(if (s.curr_tok.tok_type == .lbrace) try s.result_block() else try s.result_block_expression()) } };
}
fn capture(s: *Parser) ParserError!Node {
    try s.expect(.@"or");
    var captures = std.ArrayList(Node).init(s.allocator);
    while (s.curr_tok.tok_type != .eof) {
        if (s.curr_tok.tok_type == .@"or") break;
        captures.append(try s.capture_item()) catch |e| @panic(@errorName(e));
        if (s.curr_tok.tok_type == .@"or") break;
        try s.expect(.comma);
    }
    try s.expect(.@"or");
    return Node{ .capture = .{ .captures = captures } };
}
fn capture_item(s: *Parser) ParserError!Node {
    const mut = if (s.curr_tok.tok_type == .mut) blk: {
        try s.expect(.mut);
        break :blk true;
    } else false;
    const val = s.create_node_ptr(try s.identifier());
    return Node{ .capture_val = .{ .mut = mut, .val = val } };
}
fn comp_expression(s: *Parser) ParserError!Node {
    try s.expect(.comp);
    return Node{ .comp_expression = .{ .expression = s.create_node_ptr(try s.non_literal_expression()) } };
}
fn continue_expression(s: *Parser) ParserError!Node {
    try s.expect(.@"continue");
    return Node{ .continue_expression = .{ .label = if (s.curr_tok.tok_type == .colon) blk: {
        try s.expect(.colon);
        break :blk s.create_node_ptr(try s.identifier());
    } else null } };
}
fn declaration(s: *Parser, global_decl: bool) ParserError!Node {
    const pub_ = if (global_decl) blk: {
        break :blk if (s.curr_tok.tok_type == .@"pub") blk2: {
            try s.expect(.@"pub");
            break :blk2 true;
        } else false;
    } else false;
    const mut = if (s.curr_tok.tok_type == .mut) blk: {
        try s.expect(.mut);
        break :blk true;
    } else false;
    const name = s.create_node_ptr(try s.identifier());
    const type_ = switch (s.curr_tok.tok_type) {
        .walrus, .semicolon => null,
        .colon => blk: {
            try s.expect(.colon);
            break :blk s.create_node_ptr(try s.non_literal_expression());
        },
        else => {
            s.diag.emit(s.source.id, @intCast(s.lexer.index), .err, "Invalid declaration symbol {any}, wanted := or : [Type]", .{s.curr_tok.tok_type});
            return ParserError.recoverable;
        },
    };
    const val = switch (s.curr_tok.tok_type) {
        .walrus, .eq => blk: {
            try s.expect(s.curr_tok.tok_type);
            break :blk s.create_node_ptr(try s.expression(0));
        },
        else => null,
    };
    return Node{ .declaration = .{ .pub_ = pub_, .mut = mut, .name = name, .type = type_, .val = val } };
}
fn defer_statement(s: *Parser) ParserError!Node {
    try s.expect(.@"defer");
    const cap = if (s.curr_tok.tok_type == .@"or") s.create_node_ptr(try s.capture()) else null;
    return Node{ .defer_statement = .{ .capture = cap, .body = s.create_node_ptr(try s.result_block()) } };
}
fn enum_error_initialization(s: *Parser) ParserError!Node {
    const name = s.create_node_ptr(try s.identifier());
    const val = if (s.curr_tok.tok_type == .lparen) blk: {
        try s.expect(.lparen);
        const v = s.create_node_ptr(try s.expression(0));
        try s.expect(.rparen);
        break :blk v;
    } else null;
    return Node{ .enum_error_init = .{ .name = name, .val = val } };
}
fn error_union_type(s: *Parser, n: ?Node) ParserError!Node {
    try s.expect(.bang);
    var errs = std.ArrayList(Node).init(s.allocator);
    while (s.curr_tok.tok_type != .eof) {
        if (s.curr_tok.tok_type != .identifier) break;
        errs.append(try s.identifier()) catch |e| @panic(@errorName(e));
        if (s.curr_tok.tok_type != .bang) break;
        try s.expect(.bang);
    }
    return Node{ .error_union_type = .{ .name = if (n) |node| s.create_node_ptr(node) else null, .errors = errs } };
}
fn expression(s: *Parser, prec: u8) ParserError!Node {
    switch (s.curr_tok.tok_type) {
        .@"break" => return s.break_expression(),
        .@"continue" => return s.continue_expression(),
        .@"if" => return s.if_expression(),
        .@"return" => return s.return_expression(),
        .underscore => {
            try s.expect(.underscore);
            return Node.underscore;
        },
        .use => return s.use_expression(),
        else => {},
    }
    var expr = switch (s.curr_tok.tok_type) {
        .int, .float, .string, .char, .true, .false, .undefined, .null => try s.literal(),
        .bang, .flip, .sub, .@"and" => try s.unary_expression(),
        else => try s.non_literal_expression(),
    };
    while (s.curr_tok.tok_type != .eof and prec < s.precedence()) {
        if (s.curr_tok.tok_type == .dotdot) return try s.range_expression(expr);
        switch(s.curr_tok.tok_type) {
            .dotdot => return try s.range_expression(expr),
            .addeq, .andeq, .diveq, .flipeq, .modeq, .muleq, .subeq, .xoreq, .eq => return try s.assign_expression(expr),
            else => {},
        }
        const new_prec = s.precedence();
        switch (s.curr_tok.tok_type) {
            .add, .@"and", .andand, .bang, .bangeq, .div, .eqeq, .gt, .gteq, .lt, .lteq, .mod, .mul, .nullish, .@"or", .oror, .sub, .xor => {},
            else => return expr,
        }
        const op = s.create_node_ptr(try s.operator());
        expr = Node{ .binary = .{ .a = s.create_node_ptr(expr), .op = op, .b = s.create_node_ptr(try s.expression(new_prec)) } };
    }
    return expr;
}
fn for_prefix(s: *Parser) ParserError!Node {
    try s.expect(.@"for");
    var expressions = std.ArrayList(Node).init(s.allocator);
    while (s.curr_tok.tok_type != .eof) {
        if (s.curr_tok.tok_type == .colon) break;
        expressions.append(try s.expression(0)) catch |e| @panic(@errorName(e));
        if (s.curr_tok.tok_type == .colon) break;
        try s.expect(.comma);
    }
    try s.expect(.colon);
    const cap = s.create_node_ptr(try s.capture());
    return Node{ .for_prefix = .{ .expressions = expressions, .capture = cap } };
}
fn for_statement(s: *Parser) ParserError!Node {
    const inline_ = if (s.curr_tok.tok_type == .@"inline") blk: {
        try s.expect(.@"inline");
        break :blk true;
    } else false;
    const prefix = s.create_node_ptr(try s.for_prefix());
    return Node{ .for_statement = .{ .inline_ = inline_, .prefix = prefix, .body = s.create_node_ptr(try s.result_block()) } };
}
fn function(s: *Parser) ParserError!Node { // unfinished
    const inline_ = if (s.curr_tok.tok_type == .@"inline") blk: {
        try s.expect(.@"inline");
        break :blk true;
    } else false;
    var fn_decl = true;
    var fn_parameters = std.ArrayList(Node).init(s.allocator);
    var types = std.ArrayList(Node).init(s.allocator);
    try s.expect(.@"fn");
    try s.expect(.lparen);
    while (s.curr_tok.tok_type != .eof) {
        if (s.curr_tok.tok_type == .rparen) break;
        if (fn_decl) {
            if (s.curr_tok.tok_type == .identifier) {
                types.append(try s.identifier()) catch |e| @panic(@errorName(e));
                if (s.curr_tok.tok_type == .colon) {
                    try s.expect(.colon);
                    const the_type = s.create_node_ptr(try s.non_literal_expression());
                    fn_parameters.append(Node{ .function_parameter = .{ .names = types.clone() catch |e| @panic(@errorName(e)), .type = the_type } }) catch |e| @panic(@errorName(e));
                    types.deinit();
                    types = std.ArrayList(Node).init(s.allocator);
                }
            } else {
                fn_decl = false;
                continue;
            }
        } else {
            types.append(try s.non_literal_expression()) catch |e| @panic(@errorName(e));
            if (s.curr_tok.tok_type == .colon) {
                s.diag.emit(s.source.id, @intCast(s.lexer.index), .err, "", .{});
                return ParserError.recoverable;
            }
        }
        if (s.curr_tok.tok_type == .rparen) break;
        try s.expect(.comma);
    }
    try s.expect(.rparen);
    var return_expr = switch (s.curr_tok.tok_type) {
        .arrow, .bang, .lbrace, .rparen, .semicolon, .comma => null,
        .identifier => blk: {
            if(s.next_tok.tok_type == .colon) break :blk try s.block(true);
            var chain = try s.identifier();
            while (s.curr_tok.tok_type != .eof) switch (s.curr_tok.tok_type) {
                .dot => chain = blk2: {
                    try s.expect(.dot);
                    break :blk2 Node{ .member_access = .{ .name = s.create_node_ptr(chain), .member = s.create_node_ptr(try s.identifier()) } };
                },
                .lbrack => chain = blk2: {
                    try s.expect(.lbrack);
                    const expr = s.create_node_ptr(try s.expression(0));
                    try s.expect(.rbrack);
                    break :blk2 Node{ .array_index = .{ .name = s.create_node_ptr(chain), .index = expr } };
                },
                .lparen => chain = blk2: {
                    try s.expect(.lparen);
                    var args = std.ArrayList(Node).init(s.allocator);
                    while (s.curr_tok.tok_type != .eof) {
                        if (s.curr_tok.tok_type == .rparen) break;
                        args.append(try s.expression(0)) catch |e| @panic(@errorName(e));
                        if (s.curr_tok.tok_type == .rparen) break;
                        try s.expect(.comma);
                    }
                    try s.expect(.rparen);
                    break :blk2 Node{ .call = .{ .name = s.create_node_ptr(chain), .args = args } };
                },
                .pointer_deref => chain = blk2: {
                    try s.expect(.pointer_deref);
                    break :blk2 Node{ .pointer_dereference = .{ .expression = s.create_node_ptr(chain) } };
                },
                .optional_deref => chain = blk2: {
                    try s.expect(.optional_deref);
                    break :blk2 Node{ .optional_dereference = .{ .expression = s.create_node_ptr(chain) } };
                },
                else => break,
            };
            break :blk chain;
        },
        else => try s.non_literal_expression(),
    };
    if (s.curr_tok.tok_type == .bang) return_expr = try s.error_union_type(return_expr);
    const body = switch (s.curr_tok.tok_type) {
        .arrow => blk: {
            try s.expect(.arrow);
            break :blk s.create_node_ptr(Node{ .arrow_expression = .{ .expression = s.create_node_ptr(try s.expression(0)) } });
        },
        .lbrace => s.create_node_ptr(try s.block(false)),
        else => null,
    };
    if (fn_decl) {
        if (body) |b| {
            if (types.items.len > 0) {
                s.diag.emit(s.source.id, @intCast(s.lexer.index), .err, "Identifiers missing type in function declaration", .{});
                return ParserError.recoverable;
            }
            return Node{ .function = .{ .inline_ = inline_, .parameters = fn_parameters, .result = if (return_expr) |r| s.create_node_ptr(r) else null, .body = b } };
        }
        if (fn_parameters.items.len > 0) {
            s.diag.emit(s.source.id, @intCast(s.lexer.index), .err, "Function declaration requires a body", .{});
            return ParserError.recoverable;
        }
        if (inline_) {
            s.diag.emit(s.source.id, @intCast(s.lexer.index), .err, "Inline cannot be applied to function types", .{});
            return ParserError.recoverable;
        }
        return Node{ .function_type = .{ .parameters = types, .result = if (return_expr) |r| s.create_node_ptr(r) else null } };
    }
    if (body) |_| {
        s.diag.emit(s.source.id, @intCast(s.lexer.index), .err, "Function types should not have a body", .{});
        return ParserError.recoverable;
    }
    if (fn_parameters.items.len > 0) {
        s.diag.emit(s.source.id, @intCast(s.lexer.index), .err, "Function declaration has types without corresponding identifiers", .{}); // review this
        return ParserError.recoverable;
    }
    if (inline_) {
        s.diag.emit(s.source.id, @intCast(s.lexer.index), .err, "Inline cannot be applied to function types", .{});
        return ParserError.recoverable;
    }
    return Node{ .function_type = .{ .parameters = types, .result = if (return_expr) |r| s.create_node_ptr(r) else null } };
}
fn identifier(s: *Parser) ParserError!Node {
    const val = s.curr_tok.val.?;
    try s.expect(.identifier);
    return Node{ .identifier = val };
}
fn if_expression(s: *Parser) ParserError!Node {
    const prefix = s.create_node_ptr(try s.if_prefix());
    const body = s.create_node_ptr(try s.result_block_expression());
    return Node{ .if_expression = .{ .prefix = prefix, .body = body, .else_body = if (s.curr_tok.tok_type == .@"else") blk: {
        try s.expect(.@"else");
        break :blk s.create_node_ptr(try s.result_block_expression());
    } else null } };
}
fn if_prefix(s: *Parser) ParserError!Node {
    try s.expect(.@"if");
    const expr = s.create_node_ptr(try s.expression(0));
    try s.expect(.colon);
    const cap = if (s.curr_tok.tok_type == .@"or") s.create_node_ptr(try s.capture()) else null;
    return Node{ .if_prefix = .{ .capture = cap, .expression = expr } };
}
fn if_statement(s: *Parser) ParserError!Node {
    const prefix = s.create_node_ptr(try s.if_prefix());
    const body = s.create_node_ptr(try s.result_block());
    return Node{ .if_statement = .{ .prefix = prefix, .body = body, .else_body = if (s.curr_tok.tok_type == .@"else") blk: {
        try s.expect(.@"else");
        break :blk s.create_node_ptr(try s.result_block());
    } else null } };
}
fn literal(s: *Parser) ParserError!Node {
    const lit_kind = switch (s.curr_tok.tok_type) {
        .int => LiteralKind.int,
        .float => LiteralKind.float,
        .true, .false => LiteralKind.boolean,
        .char => LiteralKind.char,
        .string => LiteralKind.string,
        .undefined => LiteralKind.undefined,
        .null => LiteralKind.null,
        else => {
            s.diag.emit(s.source.id, @intCast(s.lexer.index), .err, "Invalid literal {any}", .{s.curr_tok.tok_type});
            return ParserError.recoverable;
        },
    };
    const val = switch (s.curr_tok.tok_type) {
        .true => "true",
        .false => "false",
        .null, .undefined => "",
        else => s.curr_tok.val.?,
    };
    try s.expect(s.curr_tok.tok_type);
    return Node{ .literal = .{ .kind = lit_kind, .val = val } };
}
fn match(s: *Parser, is_expr: bool) ParserError!Node {
    try s.expect(.match);
    const expr = s.create_node_ptr(try s.expression(0));
    try s.expect(.colon);
    try s.expect(.lbrace);
    var arms = std.ArrayList(Node).init(s.allocator);
    blk: while (s.curr_tok.tok_type != .eof) {
        if (s.curr_tok.tok_type == .rbrace) break;
        arms.append(s.arm(is_expr) catch |e| switch (e) {
            ParserError.recoverable => {
                s.sync(&[_]TokenType{ .comma, .rbrace });
                continue :blk;
            },
            ParserError.fatal => return e,
        }) catch |e| @panic(@errorName(e));
        if (s.curr_tok.tok_type == .rbrace) break;
        try s.expect(.comma);
    }
    try s.expect(.rbrace);
    return Node{ .match = .{ .expression = expr, .arms = arms } };
}
fn non_literal_expression(s: *Parser) ParserError!Node {
    var expr: Node = switch (s.curr_tok.tok_type) {
        .comp => return s.comp_expression(),
        .dot => blk: {
            try s.expect(.dot);
            break :blk try s.enum_error_initialization();
        },
        .@"enum" => blk: {
            try s.expect(.@"enum");
            try s.expect(.lbrace);
            var members = std.ArrayList(Node).init(s.allocator);
            while (s.curr_tok.tok_type != .eof) {
                if (s.curr_tok.tok_type == .rbrace) break;
                members.append(try s.member(false)) catch |e| @panic(@errorName(e));
                if (s.curr_tok.tok_type == .rbrace) break;
                try s.expect(.comma);
            }
            try s.expect(.rbrace);
            break :blk Node{ .enum_ = .{ .members = members } };
        },
        .@"error" => blk: {
            try s.expect(.@"error");
            try s.expect(.lbrace);
            var members = std.ArrayList(Node).init(s.allocator);
            while (s.curr_tok.tok_type != .eof) {
                if (s.curr_tok.tok_type == .rbrace) break;
                members.append(try s.member(false)) catch |e| @panic(@errorName(e));
                if (s.curr_tok.tok_type == .rbrace) break;
                try s.expect(.comma);
            }
            try s.expect(.rbrace);
            break :blk Node{ .error_ = .{ .members = members } };
        },
        .identifier => blk: {
            if (s.next_tok.tok_type == .lbrace) break :blk try s.struct_initialization(null);
            var chain = try s.identifier();
            while (s.curr_tok.tok_type != .eof) switch (s.curr_tok.tok_type) {
                .dot => chain = blk2: {
                    try s.expect(.dot);
                    break :blk2 Node{ .member_access = .{ .name = s.create_node_ptr(chain), .member = s.create_node_ptr(try s.identifier()) } };
                },
                .lbrack => chain = blk2: {
                    try s.expect(.lbrack);
                    const expr = s.create_node_ptr(try s.expression(0));
                    try s.expect(.rbrack);
                    break :blk2 Node{ .array_index = .{ .name = s.create_node_ptr(chain), .index = expr } };
                },
                .lparen => chain = blk2: {
                    try s.expect(.lparen);
                    var args = std.ArrayList(Node).init(s.allocator);
                    while (s.curr_tok.tok_type != .eof) {
                        if (s.curr_tok.tok_type == .rparen) break;
                        args.append(try s.expression(0)) catch |e| @panic(@errorName(e));
                        if (s.curr_tok.tok_type == .rparen) break;
                        try s.expect(.comma);
                    }
                    try s.expect(.rparen);
                    break :blk2 Node{ .call = .{ .name = s.create_node_ptr(chain), .args = args } };
                },
                .lbrace => chain = try s.struct_initialization(chain),
                .pointer_deref => chain = blk2: {
                    try s.expect(.pointer_deref);
                    break :blk2 Node{ .pointer_dereference = .{ .expression = s.create_node_ptr(chain) } };
                },
                .optional_deref => chain = blk2: {
                    try s.expect(.optional_deref);
                    break :blk2 Node{ .optional_dereference = .{ .expression = s.create_node_ptr(chain) } };
                },
                else => break,
            };
            break :blk chain;
        },
        .@"if" => try s.if_expression(),
        .@"inline", .@"fn" => blk: {
            var chain = try s.function();
            if (chain == .function_type) break :blk chain;
            if (s.curr_tok.tok_type != .lparen) break :blk chain;
            try s.expect(.lparen);
            var call_args = std.ArrayList(Node).init(s.allocator);
            while (s.curr_tok.tok_type != .eof) {
                if (s.curr_tok.tok_type == .rparen) break;
                call_args.append(try s.expression(0)) catch |e| @panic(@errorName(e));
                if (s.curr_tok.tok_type == .rparen) break;
                try s.expect(.comma);
            }
            try s.expect(.rparen);
            chain = .{ .call = .{ .name = s.create_node_ptr(chain), .args = call_args } };
            while (s.curr_tok.tok_type != .eof) switch (s.curr_tok.tok_type) {
                .dot => chain = blk2: {
                    try s.expect(.dot);
                    break :blk2 Node{ .member_access = .{ .name = s.create_node_ptr(chain), .member = s.create_node_ptr(try s.identifier()) } };
                },
                .lbrack => chain = blk2: {
                    try s.expect(.lbrack);
                    const expr = s.create_node_ptr(try s.expression(0));
                    try s.expect(.rbrack);
                    break :blk2 Node{ .array_index = .{ .name = s.create_node_ptr(chain), .index = expr } };
                },
                .lparen => chain = blk2: {
                    try s.expect(.lparen);
                    var args = std.ArrayList(Node).init(s.allocator);
                    while (s.curr_tok.tok_type != .eof) {
                        if (s.curr_tok.tok_type == .rparen) break;
                        args.append(try s.expression(0)) catch |e| @panic(@errorName(e));
                        if (s.curr_tok.tok_type == .rparen) break;
                        try s.expect(.comma);
                    }
                    try s.expect(.rparen);
                    break :blk2 Node{ .call = .{ .name = s.create_node_ptr(chain), .args = args } };
                },
                .lbrace => chain = try s.struct_initialization(chain),
                .pointer_deref => chain = blk2: {
                    try s.expect(.pointer_deref);
                    break :blk2 Node{ .pointer_dereference = .{ .expression = s.create_node_ptr(chain) } };
                },
                .optional_deref => chain = blk2: {
                    try s.expect(.optional_deref);
                    break :blk2 Node{ .optional_dereference = .{ .expression = s.create_node_ptr(chain) } };
                },
                else => break,
            };
            break :blk chain;
        },
        .lbrace => blk: {
            var chain = try s.struct_initialization(null);
            while (s.curr_tok.tok_type != .eof) switch (s.curr_tok.tok_type) {
                .dot => chain = blk2: {
                    try s.expect(.dot);
                    break :blk2 Node{ .member_access = .{ .name = s.create_node_ptr(chain), .member = s.create_node_ptr(try s.identifier()) } };
                },
                .lbrack => chain = blk2: {
                    try s.expect(.lbrack);
                    const expr = s.create_node_ptr(try s.expression(0));
                    try s.expect(.rbrack);
                    break :blk2 Node{ .array_index = .{ .name = s.create_node_ptr(chain), .index = expr } };
                },
                .lparen => chain = blk2: {
                    try s.expect(.lparen);
                    var args = std.ArrayList(Node).init(s.allocator);
                    while (s.curr_tok.tok_type != .eof) {
                        if (s.curr_tok.tok_type == .rparen) break;
                        args.append(try s.expression(0)) catch |e| @panic(@errorName(e));
                        if (s.curr_tok.tok_type == .rparen) break;
                        try s.expect(.comma);
                    }
                    try s.expect(.rparen);
                    break :blk2 Node{ .call = .{ .name = s.create_node_ptr(chain), .args = args } };
                },
                .lbrace => chain = try s.struct_initialization(chain),
                .pointer_deref => chain = blk2: {
                    try s.expect(.pointer_deref);
                    break :blk2 Node{ .pointer_dereference = .{ .expression = s.create_node_ptr(chain) } };
                },
                .optional_deref => chain = blk2: {
                    try s.expect(.optional_deref);
                    break :blk2 Node{ .optional_dereference = .{ .expression = s.create_node_ptr(chain) } };
                },
                else => break,
            };
            break :blk chain;
        },
        .lbrack => blk: {
            if (s.curr_tok.tok_type == .lbrack and s.next_tok.tok_type == .rbrack) {
                switch (s.peek_tok.tok_type) {
                    .identifier, .lbrack, .@"struct", .@"enum", .@"error", .lparen, .@"if", .mul, .question => {
                        try s.expect(.lbrack);
                        try s.expect(.rbrack);
                        break :blk Node{ .array_type = .{ .expression = s.create_node_ptr(try s.non_literal_expression()) } };
                    },
                    else => {
                        try s.expect(.lbrack);
                        var vals = std.ArrayList(Node).init(s.allocator);
                        while (s.curr_tok.tok_type != .eof) {
                            if (s.curr_tok.tok_type == .rbrack) break;
                            vals.append(try s.expression(0)) catch |e| @panic(@errorName(e));
                            if (s.curr_tok.tok_type == .rbrack) break;
                            try s.expect(.comma);
                        }
                        try s.expect(.rbrack);
                        break :blk Node{ .array_init = .{ .vals = vals } };
                    },
                }
            } else {
                try s.expect(.lbrack);
                var vals = std.ArrayList(Node).init(s.allocator);
                while (s.curr_tok.tok_type != .eof) {
                    if (s.curr_tok.tok_type == .rbrack) break;
                    vals.append(try s.expression(0)) catch |e| @panic(@errorName(e));
                    if (s.curr_tok.tok_type == .rbrack) break;
                    try s.expect(.comma);
                }
                try s.expect(.rbrack);
                break :blk Node{ .array_init = .{ .vals = vals } };
            }
        },
        .lparen => blk: {
            try s.expect(.lparen);
            const expr = switch (s.curr_tok.tok_type) {
                .identifier => switch (s.next_tok.tok_type) {
                    .colon => s.create_node_ptr(try s.block(true)),
                    else => s.create_node_ptr(try s.expression(0)),
                },
                .rparen => null,
                else => s.create_node_ptr(try s.expression(0)),
            };
            try s.expect(.rparen);
            break :blk Node{ .grouped = .{ .expression = expr } };
        },
        .match => try s.match(true),
        .mul => blk: {
            try s.expect(.mul);
            break :blk Node{ .pointer_type = .{ .expression = s.create_node_ptr(try s.non_literal_expression()) } };
        },
        .question => blk: {
            try s.expect(.question);
            break :blk Node{ .optional_type = .{ .expression = s.create_node_ptr(try s.non_literal_expression()) } };
        },
        .@"struct" => blk: {
            try s.expect(.@"struct");
            try s.expect(.lbrace);
            var members = std.ArrayList(Node).init(s.allocator);
            while (s.curr_tok.tok_type != .eof) {
                if (s.curr_tok.tok_type == .rbrace) break;
                members.append(try s.member(true)) catch |e| @panic(@errorName(e));
                if (s.curr_tok.tok_type == .rbrace) break;
                try s.expect(.comma);
            }
            try s.expect(.rbrace);
            break :blk Node{ .struct_ = .{ .members = members } };
        },
        .@"try" => blk: {
            try s.expect(.@"try");
            break :blk Node{ .try_ = .{ .expression = s.create_node_ptr(try s.non_literal_expression()) } };
        },
        .type => blk: {
            try s.expect(.type);
            break :blk Node.type;
        },
        else => {
            s.diag.emit(s.source.id, @intCast(s.lexer.index), .err, "Invalid non literal expression {any}", .{s.curr_tok.tok_type});
            return ParserError.recoverable;
        },
    };
    switch (expr) {
        .array_index, .array_type, .catch_, .enum_, .error_, .identifier, .grouped, .if_expression, .member_access, .optional_dereference, .optional_type, .pointer_dereference, .pointer_type, .struct_, .try_ => {
            if (s.curr_tok.tok_type == .bang) expr = try s.error_union_type(expr);
        },
        .block => |i| {
            if (i.label) |_| {
                if (s.curr_tok.tok_type == .bang) expr = try s.error_union_type(expr);
            } else {
                s.diag.emit(s.source.id, @intCast(s.lexer.index), .err, "Blocks must have labels to be used as expression", .{});
                return ParserError.recoverable;
            }
        },
        .call => {
            if (s.curr_tok.tok_type == .@"catch") expr = try s.catch_(expr);
            if (s.curr_tok.tok_type == .bang) expr = try s.error_union_type(expr);
        },
        else => {},
    }
    return expr;
}
fn operator(s: *Parser) ParserError!Node {
    const op: Node = switch (s.curr_tok.tok_type) {
        .add => Node.add,
        .@"and" => Node.@"and",
        .andand => Node.andand,
        .bang => Node.bang,
        .bangeq => Node.bangeq,
        .div => Node.div,
        .eqeq => Node.eqeq,
        .gt => Node.gt,
        .gteq => Node.gte,
        .lt => Node.lt,
        .lteq => Node.lte,
        .mod => Node.mod,
        .mul => Node.mul,
        .nullish => Node.nullish,
        .@"or" => Node.@"or",
        .oror => Node.oror,
        .sub => Node.sub,
        .xor => Node.xor,
        else => {
            s.diag.emit(s.source.id, @intCast(s.lexer.index), .err, "Unexpected assign op {any}", .{s.curr_tok.tok_type});
            return ParserError.recoverable;
        },
    };
    try s.expect(s.curr_tok.tok_type);
    return op;
}
fn range_expression(s: *Parser, expr: Node) ParserError!Node {
    try s.expect(.dotdot);
    return Node{ .range_expression = .{ .a = s.create_node_ptr(expr), .b = s.create_node_ptr(try s.expression(0)) } };
}
fn result_block(s: *Parser) ParserError!Node {
    return switch (s.curr_tok.tok_type) {
        .identifier => switch (s.next_tok.tok_type) {
            .colon => try s.block(true),
            else => try s.statement(),
        },
        .lbrace => try s.block(false),
        else => try s.statement(),
    };
}
fn result_block_expression(s: *Parser) ParserError!Node {
    return switch (s.curr_tok.tok_type) {
        .identifier => switch (s.next_tok.tok_type) {
            .colon => try s.block(true),
            else => try s.expression(0),
        },
        .lbrace => try s.block(false),
        else => blk: {
            var expr = try s.expression(0);
            switch (s.curr_tok.tok_type) {
                .addeq, .andeq, .diveq, .flipeq, .modeq, .muleq, .subeq, .xoreq, .eq => expr = try s.assign_expression(expr),
                else => {},
            }
            break :blk expr;
        },
    };
}
fn return_expression(s: *Parser) ParserError!Node {
    try s.expect(.@"return");
    return Node{ .return_expression = .{ .val = if (s.curr_tok.tok_type == .semicolon) null else s.create_node_ptr(try s.expression(0)) } };
}
fn statement(s: *Parser) ParserError!Node {
    if (s.curr_tok.tok_type == .identifier) {
        if (s.next_tok.tok_type == .colon) return if (s.peek_tok.tok_type == .lbrace) try s.block(true) else try s.declaration(false);
        if (s.next_tok.tok_type == .walrus) return try s.declaration(false);
    }
    return switch (s.curr_tok.tok_type) {
        .@"defer" => try s.defer_statement(),
        .@"if" => try s.if_statement(),
        .@"inline", .@"for" => try s.for_statement(),
        .lbrace => try s.block(false),
        .match => try s.match(false),
        .mut => try s.declaration(false),
        .@"while" => try s.while_statement(),
        else => blk: {
            var expr = try s.expression(0);
            switch (s.curr_tok.tok_type) {
                .addeq, .andeq, .diveq, .flipeq, .modeq, .muleq, .subeq, .xoreq, .eq => expr = try s.assign_expression(expr),
                else => {},
            }
            break :blk expr;
        },
    };
}
fn struct_initialization(s: *Parser, current_name: ?Node) ParserError!Node {
    const name = if (current_name) |n| s.create_node_ptr(n) else if (s.curr_tok.tok_type == .identifier) s.create_node_ptr(try s.identifier()) else null;
    try s.expect(.lbrace);
    var inits = std.ArrayList(Node).init(s.allocator);
    while (s.curr_tok.tok_type != .eof) {
        if (s.curr_tok.tok_type == .rbrace) break;
        inits.append(try s.struct_init_member()) catch |e| @panic(@errorName(e));
        if (s.curr_tok.tok_type == .rbrace) break;
        try s.expect(.comma);
    }
    try s.expect(.rbrace);
    return Node{ .struct_init = .{ .name = name, .inits = inits } };
}
fn struct_init_member(s: *Parser) ParserError!Node {
    const name = s.create_node_ptr(try s.identifier());
    try s.expect(.colon);
    return Node{ .struct_init_member = .{ .name = name, .val = s.create_node_ptr(try s.expression(0)) } };
}
fn member(s: *Parser, is_struct: bool) ParserError!Node {
    var names = std.ArrayList(Node).init(s.allocator);
    while (s.curr_tok.tok_type != .eof) {
        if (s.curr_tok.tok_type == .colon or s.curr_tok.tok_type == .walrus or s.curr_tok.tok_type == .rbrace) break;
        names.append(try s.identifier()) catch |e| @panic(@errorName(e));
        if (s.curr_tok.tok_type == .colon or s.curr_tok.tok_type == .walrus or s.curr_tok.tok_type == .rbrace) break;
        try s.expect(.comma);
    }
    const type_ = switch (s.curr_tok.tok_type) {
        .walrus => null,
        .colon => blk: {
            try s.expect(.colon);
            break :blk s.create_node_ptr(try s.non_literal_expression());
        },
        .rbrace => blk: {
            if (is_struct) {
                s.diag.emit(s.source.id, @intCast(s.lexer.index), .err, "Invalid declaration symbol {any}, wanted := or : [Type]", .{s.curr_tok.tok_type});
                return ParserError.recoverable;
            }
            break :blk null;
        },
        else => {
            s.diag.emit(s.source.id, @intCast(s.lexer.index), .err, "Invalid declaration symbol {any}, wanted := or : [Type]", .{s.curr_tok.tok_type});
            return ParserError.recoverable;
        },
    };
    const val = switch (s.curr_tok.tok_type) {
        .eq, .walrus => blk: {
            try s.expect(s.curr_tok.tok_type);
            break :blk s.create_node_ptr(try s.expression(0));
        },
        else => null,
    };
    return Node{ .member = .{ .names = names, .type = type_, .val = val } };
}
fn unary_expression(s: *Parser) ParserError!Node {
    const op = s.create_node_ptr(try s.operator());
    return Node{ .unary = .{ .op = op, .b = s.create_node_ptr(try s.expression(0)) } };
}
fn use_expression(s: *Parser) ParserError!Node {
    try s.expect(.use);
    if (s.curr_tok.tok_type != .string) {
        s.diag.emit(s.source.id, @intCast(s.lexer.index), .err, "String literal expected for use paths", .{});
        return ParserError.recoverable;
    }
    return Node{ .use = .{ .path = s.create_node_ptr(try s.literal()) } };
}
fn while_prefix(s: *Parser) ParserError!Node {
    try s.expect(.@"while");
    const expr = s.create_node_ptr(try s.expression(0));
    try s.expect(.colon);
    const cap = if (s.curr_tok.tok_type == .@"or") s.create_node_ptr(try s.capture()) else null;
    return Node{ .while_prefix = .{ .capture = cap, .expression = expr } };
}
fn while_statement(s: *Parser) ParserError!Node {
    const prefix = s.create_node_ptr(try s.while_prefix());
    return Node{ .while_statement = .{ .prefix = prefix, .body = s.create_node_ptr(try s.result_block()) } };
}

// helper methods
fn advance(s: *Parser) void {
    s.curr_tok = s.next_tok;
    s.next_tok = s.peek_tok;
    s.peek_tok = s.lexer.next();
}
fn should_read_semicolon(n: Node) bool {
    return switch (n) {
        .if_statement => |i| if (i.else_body) |e| should_read_semicolon(e.*) else should_read_semicolon(i.body.*),
        .for_statement => |i| should_read_semicolon(i.body.*),
        .while_statement => |i| should_read_semicolon(i.body.*),
        .block, .match => false,
        .defer_statement => |i| should_read_semicolon(i.body.*),
        else => true,
    };
}
fn create_node_ptr(s: *Parser, n: Node) *Node {
    const x = s.allocator.create(Node) catch |e| @panic(@errorName(e));
    x.* = n;
    return x;
}
fn expect(s: *Parser, expected: TokenType) ParserError!void {
    if (s.curr_tok.tok_type == .invalid) return ParserError.fatal;
    if (s.curr_tok.tok_type != expected) {
        s.diag.emit(s.source.id, @intCast(s.lexer.index), .err, "Unexpected token {any}, expected {any}", .{ s.curr_tok.tok_type, expected });
        return ParserError.recoverable;
    }
    s.advance();
}
fn precedence(s: *Parser) u8 {
    return switch (s.curr_tok.tok_type) {
        .dot, .lbrack, .lparen => 17,
        .bang, .xor => 16,
        .div, .mod, .mul => 15,
        .add, .sub => 14,
        .nullish => 13,
        .@"and", .@"or" => 12,
        .gt, .lt => 11,
        .gteq, .lteq => 10,
        .bangeq, .eqeq => 9,
        .andand => 8,
        .oror => 7,
        .dotdot => 6,
        .eq, .addeq, .subeq, .muleq, .diveq, .modeq, .andeq, .oreq, .xoreq, .flipeq, .pointer_deref, .optional_deref, .@"else" => 2,
        else => 0,
    };
}
fn sync(s: *Parser, toks: []const TokenType) void { // TODO: redo
    while (s.curr_tok.tok_type != .eof) {
        if (std.mem.indexOf(TokenType, toks, &[_]TokenType{s.curr_tok.tok_type})) |_| {
            s.advance();
            return;
        }
        s.advance();
    }
}
