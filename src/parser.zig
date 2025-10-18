const std = @import("std");
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;
const Diagnostic = @import("diagnostic.zig").Diagnostic;
const Lexer = @import("lexer.zig");
const NodeType = @import("ast.zig").NodeType;
const Node = @import("ast.zig").Node;
const Source = @import("source.zig").Source;
const SourceLocation = @import("source.zig").SourceLocation;
const TokenType = @import("token.zig").TokenType;
const Token = @import("token.zig").Token;
const Span = @import("token.zig").Span;
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

pub fn init(allocator: std.mem.Allocator, source: *Source, diagnostics: *DiagnosticEmitter) Parser {
    var parser = Parser{ .allocator = allocator, .source = source, .lexer = Lexer.init(source, diagnostics), .diag = diagnostics, .curr_tok = undefined, .next_tok = undefined, .peek_tok = undefined };
    parser.advance();
    parser.advance();
    parser.advance();
    return parser;
}
pub fn module_declaration(s: *Parser) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
    try s.expect(.module);
    const name = s.create_node_ptr(try s.identifier());
    return node(NodeType{ .module = .{ .name = name } }, span_start.fromSpan(s.curr_tok.loc.span));
}
pub fn parse(s: *Parser) ?Node {
    const span_start = s.curr_tok.loc.span;
    const module_decl = s.module_declaration() catch return null;
    s.expect(.semicolon) catch return null;
    var declarations = std.ArrayList(Node).empty;
    declarations.append(s.allocator, module_decl) catch |e| @panic(@errorName(e));
    blk: while (s.curr_tok.tok_type != .eof) {
        declarations.append(s.allocator, s.declaration(true) catch |e| switch (e) {
            error.recoverable => {
                s.sync(&[_]TokenType{.semicolon});
                continue :blk;
            },
            error.fatal => return null,
        }) catch |e| @panic(@errorName(e));
        s.expect(.semicolon) catch return null;
    }
    return node(NodeType{ .program = .{ .declarations = declarations } }, span_start.fromSpan(s.curr_tok.loc.span));
}

fn arm(s: *Parser, expr: bool) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
    var exprs = std.ArrayList(Node).empty;
    while (s.curr_tok.tok_type != .eof) {
        if (s.curr_tok.tok_type == .colon) break;
        exprs.append(s.allocator, try s.expression(0)) catch |e| @panic(@errorName(e));
        if (s.curr_tok.tok_type == .colon) break;
        try s.expect(.comma);
    }
    try s.expect(.colon);
    const cap = if (s.curr_tok.tok_type == .@"or") s.create_node_ptr(try s.capture()) else null;
    const e = s.create_node_ptr(if (expr) try s.result_block_expression() else try s.result_block());
    return node(NodeType{ .arm = .{
        .expressions = exprs,
        .capture = cap,
        .result = e,
    } }, span_start.fromSpan(s.curr_tok.loc.span));
}
fn assign_expression(s: *Parser, n: Node) ParserError!Node {
    const a = s.create_node_ptr(n);
    const op: Node = switch (s.curr_tok.tok_type) {
        .addeq => node(NodeType.addeq, s.curr_tok.loc.span),
        .subeq => node(NodeType.subeq, s.curr_tok.loc.span),
        .muleq => node(NodeType.muleq, s.curr_tok.loc.span),
        .diveq => node(NodeType.diveq, s.curr_tok.loc.span),
        .modeq => node(NodeType.modeq, s.curr_tok.loc.span),
        .andeq => node(NodeType.andeq, s.curr_tok.loc.span),
        .oreq => node(NodeType.oreq, s.curr_tok.loc.span),
        .xoreq => node(NodeType.xoreq, s.curr_tok.loc.span),
        .eq => node(NodeType.eq, s.curr_tok.loc.span),
        else => {
            s.diag.emit(.{ .file_id = s.source.id, .span = s.curr_tok.loc.span }, .err, "Invalid assign operator {any}", .{s.curr_tok.tok_type});
            return ParserError.recoverable;
        },
    };
    try s.expect(s.curr_tok.tok_type);
    const expr = s.create_node_ptr(try s.expression(0));
    return node(NodeType{ .assign_expression = .{ .left = a, .op = s.create_node_ptr(op), .right = expr } }, n.span.fromSpan(s.curr_tok.loc.span));
}
fn block(s: *Parser, labeled: bool) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
    const label = if (labeled) blk: {
        break :blk if (s.curr_tok.tok_type == .identifier) blk2: {
            const lbl = s.create_node_ptr(try s.identifier());
            try s.expect(.colon);
            break :blk2 lbl;
        } else null;
    } else null;
    try s.expect(.lbrace);
    var stmts = std.ArrayList(Node).empty;
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
        stmts.append(s.allocator, stmt) catch |e| @panic(@errorName(e));
        if (s.curr_tok.tok_type == .rbrace) break;
    }
    try s.expect(.rbrace);
    return node(NodeType{ .block = .{ .label = label, .statements = stmts } }, span_start.fromSpan(s.curr_tok.loc.span));
}
fn catch_(s: *Parser, n: Node) ParserError!Node {
    try s.expect(.@"catch");
    const cap = if (s.curr_tok.tok_type == .@"or") s.create_node_ptr(try s.capture()) else null;
    const body = s.create_node_ptr(if (s.curr_tok.tok_type == .lbrace) try s.result_block() else try s.result_block_expression());
    return node(NodeType{ .catch_ = .{ .expression = s.create_node_ptr(n), .capture = cap, .body = body } }, n.span.fromSpan(s.curr_tok.loc.span));
}
fn capture(s: *Parser) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
    try s.expect(.@"or");
    var captures = std.ArrayList(Node).empty;
    while (s.curr_tok.tok_type != .eof) {
        if (s.curr_tok.tok_type == .@"or") break;
        captures.append(s.allocator, try s.capture_item()) catch |e| @panic(@errorName(e));
        if (s.curr_tok.tok_type == .@"or") break;
        try s.expect(.comma);
    }
    try s.expect(.@"or");
    return node(NodeType{ .capture = .{ .captures = captures } }, span_start.fromSpan(s.curr_tok.loc.span));
}
fn capture_item(s: *Parser) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
    const mut = if (s.curr_tok.tok_type == .mut) blk: {
        try s.expect(.mut);
        break :blk true;
    } else false;
    const val = s.create_node_ptr(try s.identifier());
    return node(NodeType{ .capture_val = .{ .mut = mut, .val = val } }, span_start.fromSpan(s.curr_tok.loc.span));
}
fn comp_expression(s: *Parser) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
    try s.expect(.comp);
    const expr = s.create_node_ptr(try s.non_literal_expression());
    return node(NodeType{ .comp_expression = .{ .expression = expr } }, span_start.fromSpan(s.curr_tok.loc.span));
}
fn declaration(s: *Parser, global_decl: bool) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
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
            s.diag.emit(.{ .file_id = s.source.id, .span = s.curr_tok.loc.span }, .err, "Invalid declaration symbol {any}, wanted := or : [Type]", .{s.curr_tok.tok_type});
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
    return node(NodeType{ .declaration = .{ .pub_ = pub_, .mut = mut, .name = name, .type = type_, .val = val } }, span_start.fromSpan(s.curr_tok.loc.span));
}
fn defer_statement(s: *Parser) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
    try s.expect(.@"defer");
    const cap = if (s.curr_tok.tok_type == .@"or") s.create_node_ptr(try s.capture()) else null;
    const body = s.create_node_ptr(try s.result_block());
    return node(NodeType{ .defer_statement = .{ .capture = cap, .body = body } }, span_start.fromSpan(s.curr_tok.loc.span));
}
fn enum_error_initialization(s: *Parser) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
    const name = s.create_node_ptr(try s.identifier());
    const val = if (s.curr_tok.tok_type == .lparen) blk: {
        try s.expect(.lparen);
        const v = s.create_node_ptr(try s.expression(0));
        try s.expect(.rparen);
        break :blk v;
    } else null;
    return node(NodeType{ .enum_error_init = .{ .name = name, .val = val } }, span_start.fromSpan(s.curr_tok.loc.span));
}
fn error_union_type(s: *Parser, n: Node) ParserError!Node {
    const main = s.create_node_ptr(n);
    try s.expect(.bang);
    var errs = std.ArrayList(Node).empty;
    while (s.curr_tok.tok_type != .eof) {
        if (s.curr_tok.tok_type != .identifier) break;
        errs.append(s.allocator, try s.identifier()) catch |e| @panic(@errorName(e));
        if (s.curr_tok.tok_type != .bang) break;
        try s.expect(.bang);
    }
    return node(NodeType{ .error_union_type = .{ .errs = errs, .name = main } }, n.span.fromSpan(s.curr_tok.loc.span));
}
fn expression(s: *Parser, prec: u8) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
    switch (s.curr_tok.tok_type) {
        .underscore => {
            try s.expect(.underscore);
            return node(NodeType.underscore, s.curr_tok.loc.span);
        },
        .use => return s.use_expression(),
        else => {},
    }
    var expr = switch (s.curr_tok.tok_type) {
        .int, .float, .string, .char, .true, .false, .undefined, .null => try s.literal(),
        .bang, .flip, .sub, .@"and" => try s.unary_expression(),
        else => try s.non_literal_expression(),
    };
    switch (s.curr_tok.tok_type) {
        .dotdot => return try s.range_expression(expr),
        .addeq, .andeq, .diveq, .flipeq, .modeq, .muleq, .subeq, .xoreq, .eq => return try s.assign_expression(expr),
        else => {},
    }
    while (s.curr_tok.tok_type != .eof and prec < s.precedence()) {
        if (s.curr_tok.tok_type == .dotdot) return try s.range_expression(expr);
        const new_prec = s.precedence();
        switch (s.curr_tok.tok_type) {
            .add, .@"and", .andand, .bang, .bangeq, .div, .eqeq, .gt, .gteq, .lt, .lteq, .mod, .mul, .nullish, .@"or", .oror, .sub, .xor => {},
            else => return expr,
        }
        const op = s.create_node_ptr(try s.operator());
        expr = node(NodeType{ .binary = .{ .a = s.create_node_ptr(expr), .op = op, .b = s.create_node_ptr(try s.expression(new_prec)) } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    return expr;
}
fn function(s: *Parser) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
    const inline_ = if (s.curr_tok.tok_type == .@"inline") blk: {
        try s.expect(.@"inline");
        break :blk true;
    } else false;
    var fn_decl = true;
    var fn_parameters = std.ArrayList(Node).empty;
    var types = std.ArrayList(Node).empty;
    try s.expect(.lparen);
    while (s.curr_tok.tok_type != .eof) {
        var span_start2 = s.curr_tok.loc.span;
        if (s.curr_tok.tok_type == .rparen) break;
        if (fn_decl) {
            if (s.curr_tok.tok_type == .identifier) {
                types.append(s.allocator, try s.identifier()) catch |e| @panic(@errorName(e));
                if (s.curr_tok.tok_type == .colon) {
                    try s.expect(.colon);
                    const the_type = s.create_node_ptr(try s.non_literal_expression());
                    fn_parameters.append(s.allocator, node(NodeType{ .function_parameter = .{ .names = types.clone(s.allocator) catch |e| @panic(@errorName(e)), .type = the_type } }, span_start2.fromSpan(s.curr_tok.loc.span))) catch |e| @panic(@errorName(e));
                    types.deinit(s.allocator);
                    types = std.ArrayList(Node).empty;
                    span_start2 = s.curr_tok.loc.span;
                }
            } else {
                fn_decl = false;
                continue;
            }
        } else {
            types.append(s.allocator, try s.non_literal_expression()) catch |e| @panic(@errorName(e));
            if (s.curr_tok.tok_type == .colon) {
                s.diag.emit(.{ .file_id = s.source.id, .span = span_start2 }.err, "", .{});
                return ParserError.recoverable;
            }
        }
        if (s.curr_tok.tok_type == .rparen) break;
        try s.expect(.comma);
    }
    try s.expect(.rparen);
    var return_expr = switch (s.curr_tok.tok_type) {
        .identifier => blk: {
            if (s.next_tok.tok_type == .colon) break :blk try s.block(true);
            const chain = try s.identifier();
            break :blk try s.postfix_chain(chain, false);
        },
        else => try s.non_literal_expression(),
    };
    if (s.curr_tok.tok_type == .bang) return_expr = try s.error_union_type(return_expr);
    const body = switch (s.curr_tok.tok_type) {
        .arrow => blk: {
            const span_start2 = s.curr_tok.loc.span;
            try s.expect(.arrow);
            const expr = s.create_node_ptr(try s.expression(0));
            break :blk s.create_node_ptr(node(NodeType{ .arrow_expression = .{ .expression = expr } }, span_start2.fromSpan(s.curr_tok.loc.span)));
        },
        .lbrace => s.create_node_ptr(try s.block(false)),
        else => null,
    };
    if (fn_decl) {
        if (body) |b| {
            if (types.items.len > 0) {
                s.diag.emit(.{ .file_id = s.source.id, .span = s.curr_tok.loc.span }, .err, "Identifiers missing type in function declaration", .{});
                return ParserError.recoverable;
            }
            return node(NodeType{ .function = .{ .inline_ = inline_, .parameters = fn_parameters, .result = s.create_node_ptr(return_expr), .body = b } }, span_start.fromSpan(s.curr_tok.loc.span));
        }
        if (fn_parameters.items.len > 0) {
            s.diag.emit(.{ .file_id = s.source.id, .span = span_start }, .err, "Function declaration requires a body", .{});
            return ParserError.recoverable;
        }
        if (inline_) {
            s.diag.emit(.{ .file_id = s.source.id, .span = span_start }, .err, "Inline cannot be applied to function types", .{});
            return ParserError.recoverable;
        }
        return node(NodeType{ .function_type = .{ .parameters = types, .result = s.create_node_ptr(return_expr) } }, span_start.fromSpan(s.curr_tok.loc.span));
    }
    if (body) |b| {
        s.diag.emit(.{ .file_id = s.source.id, .span = b.span }, .err, "Function types should not have a body", .{});
        return ParserError.recoverable;
    }
    if (fn_parameters.items.len > 0) {
        s.diag.emit(.{ .file_id = s.source.id, .span = span_start }, .err, "Function declaration has types without corresponding identifiers", .{});
        return ParserError.recoverable;
    }
    if (inline_) {
        s.diag.emit(.{ .file_id = s.source.id, .span = span_start }, .err, "Inline cannot be applied to function types", .{});
        return ParserError.recoverable;
    }
    return node(NodeType{ .function_type = .{ .parameters = types, .result = s.create_node_ptr(return_expr) } }, span_start.fromSpan(s.curr_tok.loc.span));
}
fn identifier(s: *Parser) ParserError!Node {
    if (s.curr_tok.val) |v| {
        const span_start = s.curr_tok.loc.span;
        const val = v;
        try s.expect(.identifier);
        return node(NodeType{ .identifier = val }, span_start.fromSpan(s.curr_tok.loc.span));
    } else return ParserError.fatal;
}
fn if_prefix(s: *Parser) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
    try s.expect(.@"if");
    const expr = s.create_node_ptr(try s.expression(0));
    try s.expect(.colon);
    const cap = if (s.curr_tok.tok_type == .@"or") s.create_node_ptr(try s.capture()) else null;
    return node(NodeType{ .if_prefix = .{ .capture = cap, .expression = expr } }, span_start.fromSpan(s.curr_tok.loc.span));
}
fn literal(s: *Parser) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
    const lit_kind = switch (s.curr_tok.tok_type) {
        .int => LiteralKind.int,
        .float => LiteralKind.float,
        .true, .false => LiteralKind.boolean,
        .char => LiteralKind.char,
        .string => LiteralKind.string,
        .undefined => LiteralKind.undefined,
        .null => LiteralKind.null,
        else => {
            s.diag.emit(.{ .file_id = s.source.id, .span = s.curr_tok.loc.span }, .err, "Invalid literal {any}", .{s.curr_tok.tok_type});
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
    return node(NodeType{ .literal = .{ .kind = lit_kind, .val = val } }, span_start.fromSpan(s.curr_tok.loc.span));
}
fn match(s: *Parser, is_expr: bool) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
    try s.expect(.match);
    const expr = s.create_node_ptr(try s.expression(0));
    try s.expect(.colon);
    try s.expect(.lbrace);
    var arms = std.ArrayList(Node).empty;
    blk: while (s.curr_tok.tok_type != .eof) {
        if (s.curr_tok.tok_type == .rbrace) break :blk;
        arms.append(s.allocator, s.arm(is_expr) catch |e| switch (e) {
            ParserError.recoverable => {
                s.sync(&[_]TokenType{ .comma, .rbrace });
                continue :blk;
            },
            ParserError.fatal => return e,
        }) catch |e| @panic(@errorName(e));
        if (s.curr_tok.tok_type == .rbrace) break :blk;
        try s.expect(.comma);
    }
    try s.expect(.rbrace);
    return node(NodeType{ .match = .{ .expression = expr, .arms = arms } }, span_start.fromSpan(s.curr_tok.loc.span));
}
fn non_literal_expression(s: *Parser) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
    var expr: Node = switch (s.curr_tok.tok_type) {
        .comp => return s.comp_expression(),
        .dot => blk: {
            try s.expect(.dot);
            break :blk try s.enum_error_initialization();
        },
        .@"enum" => blk: {
            try s.expect(.@"enum");
            try s.expect(.lbrace);
            var members = std.ArrayList(Node).empty;
            while (s.curr_tok.tok_type != .eof) {
                if (s.curr_tok.tok_type == .rbrace) break;
                members.append(s.allocator, try s.member(false)) catch |e| @panic(@errorName(e));
                if (s.curr_tok.tok_type == .rbrace) break;
                try s.expect(.comma);
            }
            try s.expect(.rbrace);
            break :blk node(NodeType{ .enum_ = .{ .members = members } }, span_start.fromSpan(s.curr_tok.loc.span));
        },
        .@"error" => blk: {
            try s.expect(.@"error");
            try s.expect(.lbrace);
            var members = std.ArrayList(Node).empty;
            while (s.curr_tok.tok_type != .eof) {
                if (s.curr_tok.tok_type == .rbrace) break;
                members.append(s.allocator, try s.member_basic()) catch |e| @panic(@errorName(e));
                if (s.curr_tok.tok_type == .rbrace) break;
                try s.expect(.comma);
            }
            try s.expect(.rbrace);
            break :blk node(NodeType{ .error_ = .{ .members = members } }, span_start.fromSpan(s.curr_tok.loc.span));
        },
        .identifier => blk: {
            if (s.next_tok.tok_type == .lbrace) break :blk try s.struct_initialization(null);
            break :blk try s.postfix_chain(try s.identifier(), true);
        },
        .@"if" => blk: {
            const prefix = s.create_node_ptr(try s.if_prefix());
            const body = s.create_node_ptr(try s.result_block_expression());
            break :blk node(NodeType{ .if_expression = .{ .prefix = prefix, .body = body, .else_body = blk2: {
                try s.expect(.@"else");
                break :blk2 s.create_node_ptr(try s.result_block_expression());
            } } }, span_start.fromSpan(s.curr_tok.loc.span));
        },
        .lbrace => blk: {
            var chain = try s.struct_initialization(null);
            if (s.curr_tok.tok_type == .dot) {
                try s.expect(.dot);
                chain = node(NodeType{ .member_access = .{ .name = s.create_node_ptr(chain), .member = s.create_node_ptr(try s.identifier()) } }, span_start.fromSpan(s.curr_tok.loc.span));
                break :blk try s.postfix_chain(chain, true);
            }
            break :blk chain;
        },
        .lbrack => blk: {
            if (s.curr_tok.tok_type == .lbrack and s.next_tok.tok_type == .rbrack) {
                switch (s.peek_tok.tok_type) {
                    .identifier, .lbrack, .@"struct", .@"enum", .@"error", .lparen, .@"if", .mul, .question => {
                        try s.expect(.lbrack);
                        try s.expect(.rbrack);
                        break :blk node(NodeType{ .array_type = .{ .expression = s.create_node_ptr(try s.non_literal_expression()) } }, span_start.fromSpan(s.curr_tok.loc.span));
                    },
                    else => {
                        try s.expect(.lbrack);
                        var vals = std.ArrayList(Node).empty;
                        while (s.curr_tok.tok_type != .eof) {
                            if (s.curr_tok.tok_type == .rbrack) break;
                            vals.append(s.allocator, try s.expression(0)) catch |e| @panic(@errorName(e));
                            if (s.curr_tok.tok_type == .rbrack) break;
                            try s.expect(.comma);
                        }
                        try s.expect(.rbrack);
                        break :blk node(NodeType{ .array_init = .{ .vals = vals } }, span_start.fromSpan(s.curr_tok.loc.span));
                    },
                }
            } else {
                try s.expect(.lbrack);
                var vals = std.ArrayList(Node).empty;
                while (s.curr_tok.tok_type != .eof) {
                    if (s.curr_tok.tok_type == .rbrack) break;
                    vals.append(s.allocator, try s.expression(0)) catch |e| @panic(@errorName(e));
                    if (s.curr_tok.tok_type == .rbrack) break;
                    try s.expect(.comma);
                }
                try s.expect(.rbrack);
                break :blk node(NodeType{ .array_init = .{ .vals = vals } }, span_start.fromSpan(s.curr_tok.loc.span));
            }
        },
        .lparen, .@"inline" => blk: {
            var chain: Node = undefined;
            const is_fn: bool = s.curr_tok.tok_type == .@"inline" or switch (s.next_tok.tok_type) {
                .comp => true,
                .identifier => s.peek_tok.tok_type == .colon or s.peek_tok.tok_type == .comma, // return fn,
                .rparen => switch (s.peek_tok.tok_type) {
                    .lparen, .mul, .identifier, .@"struct", .@"enum", .@"error", .lbrack, .question, .void, .comp, .type => true, // return
                    else => false,
                },
                else => false,
            };
            if (is_fn) {
                chain = try s.function();
                if (chain.type == .function_type) break :blk chain;
                if (s.curr_tok.tok_type != .lparen) break :blk chain;
                try s.expect(.lparen);
                var call_args = std.ArrayList(Node).empty;
                while (s.curr_tok.tok_type != .eof) {
                    if (s.curr_tok.tok_type == .rparen) break;
                    call_args.append(s.allocator, try s.expression(0)) catch |e| @panic(@errorName(e));
                    if (s.curr_tok.tok_type == .rparen) break;
                    try s.expect(.comma);
                }
                try s.expect(.rparen);
                chain = node(.{ .call = .{ .name = s.create_node_ptr(chain), .args = call_args } }, span_start.fromSpan(s.curr_tok.loc.span));
                break :blk try s.postfix_chain(chain, true);
            }
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
            chain = node(NodeType{ .grouped = .{ .expression = expr } }, span_start.fromSpan(s.curr_tok.loc.span));
            break :blk try s.postfix_chain(chain, true);
        },
        .match => try s.match(true),
        .mul => blk: {
            try s.expect(.mul);
            break :blk node(NodeType{ .pointer_type = .{ .expression = s.create_node_ptr(try s.non_literal_expression()) } }, span_start.fromSpan(s.curr_tok.loc.span));
        },
        .question => blk: {
            try s.expect(.question);
            break :blk node(NodeType{ .optional_type = .{ .expression = s.create_node_ptr(try s.non_literal_expression()) } }, span_start.fromSpan(s.curr_tok.loc.span));
        },
        .@"struct" => blk: {
            try s.expect(.@"struct");
            try s.expect(.lbrace);
            var members = std.ArrayList(Node).empty;
            while (s.curr_tok.tok_type != .eof) {
                if (s.curr_tok.tok_type == .rbrace) break;
                members.append(s.allocator, try s.member(true)) catch |e| @panic(@errorName(e));
                if (s.curr_tok.tok_type == .rbrace) break;
                try s.expect(.comma);
            }
            try s.expect(.rbrace);
            break :blk node(NodeType{ .struct_ = .{ .members = members } }, span_start.fromSpan(s.curr_tok.loc.span));
        },
        .@"try" => blk: {
            try s.expect(.@"try");
            break :blk node(NodeType{ .try_ = .{ .expression = s.create_node_ptr(try s.non_literal_expression()) } }, span_start.fromSpan(s.curr_tok.loc.span));
        },
        .type => blk: {
            try s.expect(.type);
            break :blk node(NodeType.type, span_start.fromSpan(s.curr_tok.loc.span));
        },
        .undefined => blk: {
            try s.expect(.undefined);
            break :blk node(NodeType.undefined, span_start.fromSpan(s.curr_tok.loc.span));
        },
        .void => blk: {
            try s.expect(.void);
            break :blk node(NodeType.void, span_start.fromSpan(s.curr_tok.loc.span));
        },
        else => {
            s.diag.emit(.{ .file_id = s.source.id, .span = s.curr_tok.loc.span }, .err, "Invalid non literal expression {any}", .{s.curr_tok.tok_type});
            return ParserError.recoverable;
        },
    };
    switch (expr.type) {
        .array_index, .array_type, .catch_, .enum_, .error_, .identifier, .grouped, .if_expression, .member_access, .optional_dereference, .optional_type, .pointer_dereference, .pointer_type, .struct_, .try_ => {
            if (s.curr_tok.tok_type == .bang) expr = try s.error_union_type(expr);
        },
        .block => |i| {
            if (i.label) |_| {
                if (s.curr_tok.tok_type == .bang) expr = try s.error_union_type(expr);
            } else {
                s.diag.emit(.{ .file_id = s.source.id, .span = span_start }, .err, "Blocks must have labels to be used as expression", .{});
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
        .add => node(NodeType.add, s.curr_tok.loc.span),
        .@"and" => node(NodeType.@"and", s.curr_tok.loc.span),
        .andand => node(NodeType.andand, s.curr_tok.loc.span),
        .bang => node(NodeType.bang, s.curr_tok.loc.span),
        .bangeq => node(NodeType.bangeq, s.curr_tok.loc.span),
        .div => node(NodeType.div, s.curr_tok.loc.span),
        .eqeq => node(NodeType.eqeq, s.curr_tok.loc.span),
        .gt => node(NodeType.gt, s.curr_tok.loc.span),
        .gteq => node(NodeType.gte, s.curr_tok.loc.span),
        .lt => node(NodeType.lt, s.curr_tok.loc.span),
        .lteq => node(NodeType.lte, s.curr_tok.loc.span),
        .mod => node(NodeType.mod, s.curr_tok.loc.span),
        .mul => node(NodeType.mul, s.curr_tok.loc.span),
        .nullish => node(NodeType.nullish, s.curr_tok.loc.span),
        .@"or" => node(NodeType.@"or", s.curr_tok.loc.span),
        .oror => node(NodeType.oror, s.curr_tok.loc.span),
        .sub => node(NodeType.sub, s.curr_tok.loc.span),
        .xor => node(NodeType.xor, s.curr_tok.loc.span),
        else => {
            s.diag.emit(.{ .file_id = s.source.id, .span = s.curr_tok.loc.span }, .err, "Unexpected assign op {any}", .{s.curr_tok.tok_type});
            return ParserError.recoverable;
        },
    };
    try s.expect(s.curr_tok.tok_type);
    return op;
}
fn range_expression(s: *Parser, expr: Node) ParserError!Node {
    try s.expect(.dotdot);
    return node(NodeType{ .range_expression = .{ .a = s.create_node_ptr(expr), .b = s.create_node_ptr(try s.expression(0)) } }, expr.span.fromSpan(s.curr_tok.loc.span));
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
        else => try s.expression(0),
    };
}
fn statement(s: *Parser) ParserError!Node {
    if (s.curr_tok.tok_type == .identifier) {
        if (s.next_tok.tok_type == .colon) return if (s.peek_tok.tok_type == .lbrace) try s.block(true) else try s.declaration(false);
        if (s.next_tok.tok_type == .walrus) return try s.declaration(false);
    }
    return switch (s.curr_tok.tok_type) {
        .@"break" => blk: {
            const span_start = s.curr_tok.loc.span;
            try s.expect(.@"break");
            const label = if (s.curr_tok.tok_type == .colon) blk2: {
                try s.expect(.colon);
                break :blk2 s.create_node_ptr(try s.identifier());
            } else null;
            break :blk node(NodeType{ .break_expression = .{ .label = label, .val = if (s.curr_tok.tok_type == .semicolon) null else s.create_node_ptr(try s.expression(0)) } }, span_start.fromSpan(s.curr_tok.loc.span));
        },
        .@"continue" => blk: {
            const span_start = s.curr_tok.loc.span;
            try s.expect(.@"continue");
            break :blk node(NodeType{ .continue_expression = .{ .label = if (s.curr_tok.tok_type == .colon) blk2: {
                try s.expect(.colon);
                break :blk2 s.create_node_ptr(try s.identifier());
            } else null } }, span_start.fromSpan(s.curr_tok.loc.span));
        },
        .@"defer" => try s.defer_statement(),
        .@"if" => blk: {
            const span_start = s.curr_tok.loc.span;
            const prefix = s.create_node_ptr(try s.if_prefix());
            const body = s.create_node_ptr(try s.result_block());
            break :blk node(NodeType{ .if_statement = .{ .prefix = prefix, .body = body, .else_body = if (s.curr_tok.tok_type == .@"else") blk2: {
                try s.expect(.@"else");
                break :blk2 s.create_node_ptr(try s.result_block());
            } else null } }, span_start.fromSpan(s.curr_tok.loc.span));
        },
        .@"inline", .@"for" => blk: {
            const span_start = s.curr_tok.loc.span;
            const inline_ = if (s.curr_tok.tok_type == .@"inline") blk2: {
                try s.expect(.@"inline");
                break :blk2 true;
            } else false;
            try s.expect(.@"for");
            var expressions = std.ArrayList(Node).empty;
            while (s.curr_tok.tok_type != .eof) {
                if (s.curr_tok.tok_type == .colon) break;
                expressions.append(s.allocator, try s.expression(0)) catch |e| @panic(@errorName(e));
                if (s.curr_tok.tok_type == .colon) break;
                try s.expect(.comma);
            }
            try s.expect(.colon);
            const cap = s.create_node_ptr(try s.capture());
            break :blk node(NodeType{ .for_statement = .{ .inline_ = inline_, .expressions = expressions, .capture = cap, .body = s.create_node_ptr(try s.result_block()) } }, span_start.fromSpan(s.curr_tok.loc.span));
        },
        .lbrace => try s.block(false),
        .match => try s.match(false),
        .mut => try s.declaration(false),
        .@"return" => blk: {
            const span_start = s.curr_tok.loc.span;
            try s.expect(.@"return");
            break :blk node(NodeType{ .return_expression = .{ .val = if (s.curr_tok.tok_type == .semicolon or s.curr_tok.tok_type == .comma) null else s.create_node_ptr(try s.expression(0)) } }, span_start.fromSpan(s.curr_tok.loc.span));
        },
        .@"while" => blk: {
            const span_start = s.curr_tok.loc.span;
            try s.expect(.@"while");
            const expr = s.create_node_ptr(try s.expression(0));
            try s.expect(.colon);
            const cap = if (s.curr_tok.tok_type == .@"or") s.create_node_ptr(try s.capture()) else null;
            break :blk node(NodeType{ .while_statement = .{ .capture = cap, .expression = expr, .body = s.create_node_ptr(try s.result_block()) } }, span_start.fromSpan(s.curr_tok.loc.span));
        },
        else => try s.expression(0),
    };
}
fn struct_initialization(s: *Parser, current_name: ?Node) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
    const name = if (current_name) |n| s.create_node_ptr(n) else if (s.curr_tok.tok_type == .identifier) s.create_node_ptr(try s.identifier()) else null;
    try s.expect(.lbrace);
    var inits = std.ArrayList(Node).empty;
    while (s.curr_tok.tok_type != .eof) {
        if (s.curr_tok.tok_type == .rbrace) break;
        inits.append(s.allocator, try s.struct_init_member()) catch |e| @panic(@errorName(e));
        if (s.curr_tok.tok_type == .rbrace) break;
        try s.expect(.comma);
    }
    try s.expect(.rbrace);
    return node(NodeType{ .struct_init = .{ .name = name, .inits = inits } }, span_start.fromSpan(s.curr_tok.loc.span));
}
fn struct_init_member(s: *Parser) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
    const name = s.create_node_ptr(try s.identifier());
    try s.expect(.colon);
    return node(NodeType{ .struct_init_member = .{ .name = name, .val = s.create_node_ptr(try s.expression(0)) } }, span_start.fromSpan(s.curr_tok.loc.span));
}
fn member(s: *Parser, is_struct: bool) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
    var names = std.ArrayList(Node).empty;
    while (s.curr_tok.tok_type != .eof) {
        if (s.curr_tok.tok_type == .colon or s.curr_tok.tok_type == .walrus or s.curr_tok.tok_type == .rbrace) break;
        names.append(s.allocator, try s.identifier()) catch |e| @panic(@errorName(e));
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
                s.diag.emit(.{ .file_id = s.source.id, .span = s.curr_tok.loc.span }, .err, "Invalid declaration symbol {any}, wanted := or : [Type]", .{s.curr_tok.tok_type});
                return ParserError.recoverable;
            }
            break :blk null;
        },
        else => {
            s.diag.emit(.{ .file_id = s.source.id, .span = s.curr_tok.loc.span }, .err, "Invalid declaration symbol {any}, wanted := or : [Type]", .{s.curr_tok.tok_type});
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
    return node(NodeType{ .member = .{ .names = names, .type = type_, .val = val } }, span_start.fromSpan(s.curr_tok.loc.span));
}
fn member_basic(s: *Parser) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
    var names = std.ArrayList(Node).empty;
    while (s.curr_tok.tok_type != .eof) {
        if (s.curr_tok.tok_type == .colon or s.curr_tok.tok_type == .walrus or s.curr_tok.tok_type == .rbrace) break;
        names.append(s.allocator, try s.identifier()) catch |e| @panic(@errorName(e));
        if (s.curr_tok.tok_type == .colon or s.curr_tok.tok_type == .walrus or s.curr_tok.tok_type == .rbrace) break;
        try s.expect(.comma);
    }
    const member_type = if (s.curr_tok.tok_type == .colon) blk: {
        try s.expect(.colon);
        break :blk s.create_node_ptr(try s.non_literal_expression());
    } else null;
    return node(NodeType{ .member_basic = .{ .names = names, .type = member_type } }, span_start.fromSpan(s.curr_tok.loc.span));
}
fn unary_expression(s: *Parser) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
    const op = s.create_node_ptr(try s.operator());
    return node(NodeType{ .unary = .{ .op = op, .b = s.create_node_ptr(try s.expression(0)) } }, span_start.fromSpan(s.curr_tok.loc.span));
}
fn use_expression(s: *Parser) ParserError!Node {
    const span_start = s.curr_tok.loc.span;
    try s.expect(.use);
    if (s.curr_tok.tok_type != .string) {
        s.diag.emit(.{ .file_id = s.source.id, .span = span_start }, .err, "String literal expected for use paths", .{});
        return ParserError.recoverable;
    }
    return node(NodeType{ .use = .{ .path = s.create_node_ptr(try s.literal()) } }, span_start.fromSpan(s.curr_tok.loc.span));
}
fn postfix_chain(s: *Parser, base: Node, allow_struct: bool) ParserError!Node {
    var chain = base;
    while (s.curr_tok.tok_type != .eof) switch (s.curr_tok.tok_type) {
        .dot => {
            try s.expect(.dot);
            chain = node(NodeType{ .member_access = .{ .name = s.create_node_ptr(chain), .member = s.create_node_ptr(try s.identifier()) } }, chain.span.fromSpan(s.curr_tok.loc.span));
        },
        .lbrack => {
            try s.expect(.lbrack);
            const expr = s.create_node_ptr(try s.expression(0));
            try s.expect(.rbrack);
            chain = node(NodeType{ .array_index = .{ .name = s.create_node_ptr(chain), .index = expr } }, chain.span.fromSpan(s.curr_tok.loc.span));
        },
        .lbrace => {
            if (!allow_struct) break;
            chain = try s.struct_initialization(chain);
        },
        .lparen => {
            try s.expect(.lparen);
            var args = std.ArrayList(Node).empty;
            while (s.curr_tok.tok_type != .eof) {
                if (s.curr_tok.tok_type == .rparen) break;
                args.append(s.allocator, try s.expression(0)) catch |e| @panic(@errorName(e));
                if (s.curr_tok.tok_type == .rparen) break;
                try s.expect(.comma);
            }
            try s.expect(.rparen);
            chain = node(NodeType{ .call = .{ .name = s.create_node_ptr(chain), .args = args } }, chain.span.fromSpan(s.curr_tok.loc.span));
        },
        .pointer_deref => {
            try s.expect(.pointer_deref);
            chain = node(NodeType{ .pointer_dereference = .{ .expression = s.create_node_ptr(chain) } }, chain.span.fromSpan(s.curr_tok.loc.span));
        },
        .optional_deref => {
            try s.expect(.optional_deref);
            chain = node(NodeType{ .optional_dereference = .{ .expression = s.create_node_ptr(chain) } }, chain.span.fromSpan(s.curr_tok.loc.span));
        },
        else => break,
    };
    return chain;
}

fn advance(s: *Parser) void {
    s.curr_tok = s.next_tok;
    s.next_tok = s.peek_tok;
    s.peek_tok = s.lexer.next();
}
fn create_node_ptr(s: *Parser, n: Node) *Node {
    const x = s.allocator.create(Node) catch |e| @panic(@errorName(e));
    x.* = n;
    return x;
}
fn expect(s: *Parser, expected: TokenType) ParserError!void {
    if (s.curr_tok.tok_type == .invalid) return ParserError.fatal;
    if (s.curr_tok.tok_type != expected) {
        s.diag.emit(.{ .file_id = s.source.id, .span = s.curr_tok.loc.span }, .err, "Unexpected token {any}, expected {any}", .{ s.curr_tok.tok_type, expected });
        return ParserError.recoverable;
    }
    s.advance();
}
fn node(nodeType: NodeType, span: Span) Node {
    return Node{ .type = nodeType, .span = span };
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
        else => 0,
    };
}
fn should_read_semicolon(n: Node) bool {
    return switch (n.type) {
        .if_statement => |i| if (i.else_body) |e| should_read_semicolon(e.*) else should_read_semicolon(i.body.*),
        .for_statement => |i| should_read_semicolon(i.body.*),
        .while_statement => |i| should_read_semicolon(i.body.*),
        .block, .match => false,
        .defer_statement => |i| should_read_semicolon(i.body.*),
        else => true,
    };
}
fn sync(s: *Parser, toks: []const TokenType) void {
    while (s.curr_tok.tok_type != .eof) {
        if (std.mem.indexOf(TokenType, toks, &[_]TokenType{s.curr_tok.tok_type})) |_| {
            s.advance();
            return;
        }
        s.advance();
    }
}
