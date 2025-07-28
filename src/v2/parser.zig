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

pub fn init(allocator: std.mem.Allocator, source: *Source, diagnostics: *DiagnosticEmitter) Parser {
    const parser = Parser{ .allocator = allocator, .source = source, .lexer = Lexer.init(source, diagnostics), .diag = diagnostics, .curr_tok = undefined, .next_tok = undefined };
    parser.advance();
    parser.advance();
    return parser;
}

pub fn parse(s: *Parser) ?Node {
    const module_decl = try s.module_declaration();
    var declarations = std.ArrayList(Node).init(s.allocator);
    declarations.append(module_decl) catch |e| @panic(@errorName(e));
    blk: while (s.curr_tok.tok_type != .eof) {
        declarations.append(s.declaration(true) catch |e| switch (e) {
            error.recoverable => {
                s.sync();
                continue :blk;
            },
            error.fatal => return null,
        }) catch |e| @panic(@errorName(e));
    }
    return Node{ .program = .{ .declarations = declarations } };
}
fn module_declaration(s: *Parser) ParserError!Node {
    try s.expect(.module);
    return Node{ .module = .{ .name = s.create_node_ptr(try s.identifier()) } };
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
    const name = try s.identifier();
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
    if (s.curr_tok.tok_type != .semicolon) try s.expect(s.curr_tok.tok_type);
    const val = if (s.curr_tok.tok_type == .semicolon) null else s.create_node_ptr(try s.expression());
    try s.expect(.semicolon);
    return Node{ .declaration = .{ .pub_ = pub_, .mut = mut, .name = name, .type = type_, .val = val } };
}
fn statement(s: *Parser) ParserError!Node {}
fn block(s: *Parser, labeled: bool) ParserError!Node {
    const label = if (labeled) blk: {
        break :blk if (s.curr_tok.tok_type == .identifier) blk2: {
            break :blk2 s.create_node_ptr(s.identifier());
        } else null;
    } else null;
    try s.expect(.lbrace);
    var stmts = std.ArrayList(Node).init(s.allocator);
    while (s.curr_tok.tok_type != .eof) {
    }
    try s.expect(.rbrace);
}
fn expression(s: *Parser, prec: u8) ParserError!Node {
    switch (s.curr_tok.tok_type) {
        .@"break" => return s.break_expression(),
        .comp => return s.comp_expression(),
        .@"continue" => return s.continue_expression(),
        .@"for" => return s.for_expression(),
        .@"if" => return s.if_expression(),
        .@"return" => return s.return_expression(),
        .underscore => {
            try s.expect(.underscore);
            return Node.underscore;
        },
        .use => return s.use_expression(),
        .@"while" => return s.while_expression(),
        else => {},
    }
    var expr = switch (s.curr_tok.tok_type) {
        .int, .float, .string, .char, .true, .false, .undefined, .null => try s.literal(),
        .bang, .flip, .sub, .@"and" => try s.unary_expression(),
        else => try s.non_literal_expression(),
    };
    while (s.curr_tok.tok_type != .eof and prec < s.precedence()) {
        if (s.curr_tok.tok_type == .dotdot) return try s.range_expression(expr);
        const new_prec = s.precedence();
        const op = try s.operator();
        expr = Node{ .binary = .{ .a = s.create_node_ptr(expr), .op = s.create_node_ptr(op), .b = s.create_node_ptr(try s.expression(new_prec)) } };
    }
    return expr;
}
fn break_expression(s: *Parser) ParserError!Node {
    try s.expect(.@"break");
    const label = if (s.curr_tok.tok_type == .colon) blk: {
        try s.expect(.colon);
        break :blk s.create_node_ptr(try s.identifier());
    } else null;
    return Node{ .break_expression = .{ .label = label, .val = if (s.curr_tok.tok_type == .semicolon) null else s.create_node_ptr(try s.expression(0)) } };
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
fn for_expression(s: *Parser) ParserError!Node {
    const prefix = s.create_node_ptr(try s.for_prefix());
    return Node{ .for_expression = .{ .prefix = prefix, .body = s.create_node_ptr(try s.result_block()) } };
}
fn if_expression(s: *Parser) ParserError!Node {
    const prefix = s.create_node_ptr(try s.if_prefix());
    const body = s.create_node_ptr(if (s.curr_tok.tok_type == .lbrace) try s.block(false) else blk: { // TODO THIS
    });
    return Node{ .if_expression = .{ .prefix = prefix, .body = body, .else_body = if (s.curr_tok.tok_type == .@"else") blk: {
        try s.expect(.@"else");
        break :blk s.create_node_ptr(try s.result_block_expression());
    } else null } };
}
fn range_expression(s: *Parser, expr: Node) ParserError!Node {
    try s.expect(.dotdot);
    return Node{ .range_expression = .{ .a = s.create_node_ptr(expr), .b = s.create_node_ptr(try s.expression(0)) } };
}
fn return_expression(s: *Parser) ParserError!Node {
    try s.expect(.@"return");
    return Node{ .return_expression = .{ .val = if (s.curr_tok.tok_type == .semicolon) null else s.create_node_ptr(try s.expression(0)) } };
}
fn unary_expression(s: *Parser) ParserError!Node {
    const op = try s.operator();
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
fn while_expression(s: *Parser) ParserError!Node {}
fn non_literal_expression(s: *Parser) ParserError!Node {}
fn identifier(s: *Parser) ParserError!Node {
    try s.expect(.identifier);
    return Node{ .identifier = s.curr_tok.val.? };
}
fn literal(s: *Parser) ParserError!Node {
    const lit = Node{ .literal = .{ .kind = switch (s.curr_tok.tok_type) {
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
    }, .val = s.curr_tok.val.? } };
    try s.expect(s.curr_tok.tok_type);
    return lit;
}

// helper methods
fn advance(s: *Parser) void {
    s.curr_tok = s.next_tok;
    s.next_tok = s.lexer.next();
}
fn expect(s: *Parser, expected: TokenType) ParserError!void {
    if (s.curr_tok.tok_type == .invalid) return ParserError.fatal;
    if (s.curr_tok.tok_type != expected) {
        s.diag.emit(s.source.id, @intCast(s.lexer.index), .err, "Unexpected token {any}, expected {any}", .{ s.curr_tok.tok_type, expected });
        return ParserError.recoverable;
    }
    s.advance();
}
fn create_node_ptr(s: *Parser, n: Node) *Node {
    const x = s.a.create(Node) catch |e| @panic(@errorName(e));
    x.* = n;
    return x;
}
fn sync(s: *Parser) void {
    while (s.curr_tok.tok_type != .eof) {
        if (s.curr_tok.tok_type == .semicolon) {
            s.advance();
            return;
        }
    }
}
fn precedence(s: *Parser) u8 {}
fn operator(s: *Parser) u8 {}
