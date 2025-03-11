const std = @import("std");
const Lexer = @import("lexer.zig");
const Token = @import("token.zig").TokenType;
const Error = @import("errors.zig").Error;
const Node = @import("ast2.zig").Node;
const LiteralKind = @import("ast.zig").LiteralKind;
const Op = @import("ast.zig").Op;
const NodeList = std.ArrayList(Node);

const Self = @This();

const LexerState = struct { tok: ?Token, literal: ?[]const u8, line: usize, col: usize, index: usize };

l: Lexer,
a: std.mem.Allocator,

pub fn init(alloc: std.mem.Allocator, buf: []const u8) Self {
    return Self{ .l = Lexer.init(buf), .a = alloc };
}

pub fn program(s: *Self) !Node {
    var declarations = NodeList.init(s.a);
    try declarations.append(try s.module());
    while(s.l.tok.? != .eof) try declarations.append(try s.declaration());
    return Node{ .program = .{ .declarations = declarations }};
}
fn module_declaration(s: *Self) !Node {
    _ = try s.eat(.module);
    return Node{ .module = .{ .name = try s.create_node_ptr(Node{.identifier = .{ .value = try s.eat(.identifier)}})}};
}
fn declaration(s: *Self) !Node {
    const pub_ = if(s.l.tok.? == .@"pub") blk: {
        _ = try s.eat(.@"pub");
        break :blk true;
    } else false;
    const name = try s.create_node_ptr(Node{ .identifier = .{ .value = try s.eat(.identifier)}});
    const type_ = switch(s.l.tok.?) {
        .walrus => null,
        .colon => blk: {
            _ = try s.eat(.colon);
            break :blk try s.create_node_ptr(try s.non_literal_expression());
        },
        else => {}, // uh oh
    };
    switch(s.l.tok.?) {
        .walrus, .eq => try s.eat(s.l.tok.?),
        else => {} // uh oh
    }
    const val = try s.create_node_ptr(try s.expression());
    _ = try s.eat(.semicolon);
    return Node{ .declaration = .{ .pub_ = pub_, .name = name, .type = type_, .val = val }};
}
fn mut_declaration(s: *Self) !Node {
    const mut = if(s.l.tok.? == .@"mut") blk: {
        _ = try s.eat(.mut);
        break :blk true;
    } else false;
    const name = try s.create_node_ptr(Node{ .identifier = .{ .value = try s.eat(.identifier)}});
    const type_ = switch(s.l.tok.?) {
        .walrus => null,
        .colon => blk: {
            _ = try s.eat(.colon);
            break :blk try s.create_node_ptr(try s.non_literal_expression());
        },
        else => {}, // uh oh cause even if the var is mut and doesnt have a val we need to know what type it is
    };
    switch(s.l.tok.?) {
        .walrus, .eq => try s.eat(s.l.tok.?),
        .semicolon => {}, // semicolon is fine here because we dont want it to error
        else => {} // uh oh
    }
    const val = if (s.l.tok.? == .semicolon) null else try s.create_node_ptr(try s.expression());
    if(val == null and !mut) {} // uh oh
    return Node{ .mut_declaration = .{ .mut = mut, .name = name, .type = type_, .val = val }};
}
fn statement(s: *Self) !Node {
    return switch (s.l.tok.?) {
        .@"if" => try s.if_statement(),
        .@"for" => try s.for_statement(),
        .@"while" => try s.while_statement(),
        .@"defer" => try s.defer_statement(),
        .match => try s.match(),
        .lbrace => try s.block(),
        .mut => try s.mut_declaration(),
        else => blk: {
            const state = s.save_lexer();
            const x = s.assign_expression() catch blk2: {
                s.restore_lexer(state);
                break :blk2 s.mut_declaration() catch blk3: {
                    s.restore_lexer(state);
                    break :blk3 try s.expression();
                };
            };
            _ = try s.eat(.semicolon);
            break :blk x;
        }
    };
}
fn block(s: *Self) !Node {
    var statements = NodeList.init(s.a);
    _ = try s.eat(.lbrace);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .rbrace) break;
        try statements.append(try s.statement());
        if(s.l.tok.? == .rbrace) break;
    }
    _ = try s.eat(.rbrace);
    return Node{ .block = .{ .statements = statements } };
}
fn function(s: *Self) !Node {
    _ = try s.eat(.lparen);
    _ = try s.eat(.rparen);
}
fn arrow_expression(s: *Self) !Node {
    _ = try s.eat(.arrow);
    return Node{ .arrow_expression = .{ .expression = try s.create_node_ptr(try s.expression()) } };
}
fn assign_expression(s: *Self) !Node {
    const l = try s.create_node_ptr(try s.expression());
    // read op here
    const r = try s.create_node_ptr(try s.expression());
}
fn if_prefix(s: *Self) !Node {
    _ = try s.eat(.@"if");
    const expr = try s.create_node_ptr(try s.expression());
    const cap = if(s.l.tok.? == .colon) blk: {
        _ = try s.eat(.colon);
        break :blk try s.create_node_ptr(try s.capture());
    } else null;
    return Node{ .if_prefix = .{ .expression = expr, .capture = cap }};
}
fn while_prefix(s: *Self) !Node {
    _ = try s.eat(.@"while");
    const expr = try s.create_node_ptr(try s.expression());
    const cap = if(s.l.tok.? == .colon) blk: {
        _ = try s.eat(.colon);
        break :blk try s.create_node_ptr(try s.capture());
    } else null;
    return Node{ .while_prefix = .{ .expression = expr, .capture = cap }};
}
fn for_prefix(s: *Self) !Node {
    _ = try s.eat(.@"for");
    var expressions = NodeList.init(s.a);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .colon) break;
        try expressions.append(try s.expression());
        if(s.l.tok.? == .colon) break;
    }
    if(expressions.items.len == 0) {} // uh oh
    _ = try s.eat(.colon);
    const cap = try s.create_node_ptr(try s.capture());
    return Node{ .for_prefix = .{ .expressions = expressions, .capture = cap }};
}
fn match(s: *Self) !Node {
    _ = try s.eat(.match);
    const expr = try s.create_node_ptr(try s.expression());
    const arms = NodeList.init(s.a);
    _ = try s.eat(.lbrace);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .colon) break;
        try arms.append(try s.arm());
        if(s.l.tok.? == .colon) break;
    }
    _ = try s.eat(.rbrace);
    return Node{ .match = .{ .expression = expr, .arms = arms }};
}
fn arm(s: *Self) !Node {
    var expressions = NodeList.init(s.a);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .colon) break;
        try expressions.append(try s.expression());
        if(s.l.tok.? == .colon) break;
    }
    _ = try s.eat(.colon);
    const cap = if(s.l.tok.? == .@"or") try s.create_node_ptr(try s.capture()) else null;
    return Node{ .arm = .{ .expressions = expressions, .capture = cap, .result = try s.create_node_ptr(try s.result_block_expression()) }};
}
fn if_statement(s: *Self) !Node {
    const prefix = try s.create_node_ptr(try s.if_prefix());
    const body = try s.create_node_ptr(if(s.l.tok.? == .lbrace) try s.block() else blk: {
        const state = s.save_lexer();
        break :blk s.assign_expression() catch blk2: {
            s.restore_lexer(state);
            break :blk2 try s.expression();
        };
    });
    const else_body = if(s.l.tok.? == .@"else") blk: {
        _ = try s.eat(.@"else");
        break :blk try s.create_node_ptr(try s.result_block());
    } else null;
    return Node{ .if_statement = .{ .prefix = prefix, .body = body, .else_body = else_body }};
}
fn while_statement(s: *Self) !Node {
    const prefix = try s.create_node_ptr(try s.while_prefix());
    const body = try s.create_node_ptr(try s.result_block());
    return Node{ .while_statement = .{ .prefix = prefix, .body = body }};
}
fn for_statement(s: *Self) !Node {
    const prefix = try s.create_node_ptr(try s.for_prefix());
    const body = try s.create_node_ptr(try s.result_block());
    return Node{ .for_statement = .{ .prefix = prefix, .body = body }};
}
fn defer_statement(s: *Self) !Node {
    _ = try s.eat(.@"defer");
    const cap = if(s.l.tok.? == .colon) blk: {
        _ = try s.eat(.colon);
        break :blk try s.create_node_ptr(try s.capture());
    } else null;
    const body = try s.create_node_ptr(try s.result_block());
    return Node{ .defer_statement = .{ .capture = cap, .body = body }};
}
fn result_block(s: *Self) !Node {
    return if(s.l.tok.? == .lbrace) try s.block() else try s.statement();
}
fn result_block_expression(s: *Self) !Node {
    return if(s.l.tok.? == .lbrace) try s.block() else blk: {
        const state = s.save_lexer();
        break :blk s.assign_expression() catch blk2: {
            s.restore_lexer(state);
            break :blk2 try s.expression();
        };
    };
}
fn expression(s: *Self) !Node {}
fn non_literal_expression(s: *Self) !Node {}
fn binary_expression(s: *Self) !Node {}
fn unary_expression(s: *Self) !Node {}
fn return_expression(s: *Self) !Node {
    _ = try s.eat(.@"return");
    const val = if(s.l.tok.? == .semicolon) null else try s.expression();
    return Node{ .return_expression = .{ .val = val }};
}
fn break_expression(s: *Self) !Node {
    _ = try s.eat(.@"break");
    const label = if(s.l.tok.? == .colon) blk: {
        _ = try s.eat(.colon);
        break :blk try s.identifier();
    } else null;
    const val = if(s.l.tok.? == .semicolon) null else try s.expression();
    return Node{ .break_expression = .{ .label = label, .val = val }};
}
fn continue_expression(s: *Self) !Node {
    _ = try s.eat(.@"continue");
    const label = if(s.l.tok.? == .colon) blk: {
        _ = try s.eat(.colon);
        break :blk try s.identifier();
    } else null;
    return Node{ .return_expression = .{ .label = label }};
}
fn nullish_expression(s: *Self) !Node {
    const a = try s.create_node_ptr(try s.expression());
    _ = try s.eat();
    const b = try s.create_node_ptr(try s.expression());
    return Node{ .nullish_expression = .{ .a = a, .b = b }};
}
fn range_expression(s: *Self) !Node {
    const a = try s.create_node_ptr(try s.expression());
    _ = try s.eat(.dotdot);
    const b = try s.create_node_ptr(try s.expression());
    return Node{ .range_expression = .{ .a = a, .b = b }};
}
fn use_expression(s: *Self) !Node {
    _ = try s.eat(.use);
}
fn grouped_expression(s: *Self) !Node {
    _ = try s.eat(.lparen);
    const expr = try s.create_node_ptr(try s.expression());
    _ = try s.eat(.lparen);
    return Node { .grouped = .{ .expression = expr }};
}
fn if_expression(s: *Self) !Node { // fix this for expressions
    const prefix = try s.create_node_ptr(try s.if_prefix());
    const body = try s.create_node_ptr(if(s.l.tok.? == .lbrace) try s.block() else blk: {
        const state = s.save_lexer();
        break :blk s.assign_expression() catch blk2: {
            s.restore_lexer(state);
            break :blk2 try s.expression();
        };
    });
    const else_body = if(s.l.tok.? == .@"else") blk: {
        _ = try s.eat(.@"else");
        break :blk try s.create_node_ptr(try s.result_block_expression());
    } else null;
    return Node{ .if_expression = .{ .prefix = prefix, .body = body, .else_body = else_body }};
}
fn while_expression(s: *Self) !Node { // fix this for expressions
    const prefix = try s.create_node_ptr(try s.while_prefix());
    const body = try s.create_node_ptr(try s.result_block());
    return Node{ .while_expression = .{ .prefix = prefix, .body = body }};
}
fn for_expression(s: *Self) !Node { // fix this for expressions
    const prefix = try s.create_node_ptr(try s.for_prefix());
    const body = try s.create_node_ptr(try s.result_block());
    return Node{ .for_expression = .{ .prefix = prefix, .body = body }};
}
fn array_initialization(s: *Self) !Node {
    _ = try s.eat(.lbrack);
    var vals = NodeList.init(s.a);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .rbrack) break;
        try vals.append(try s.expression());
        if(s.l.tok.? == .rbrack) break;
        _ = try s.eat(.comma);
    }
    _ = try s.eat(.rbrack);
    return Node{ .array_init = .{ .vals = vals }};
}
fn struct_initialization(s: *Self) !Node {
    const name = if(s.l.tok.? == .identifier) try s.create_node_ptr(try s.identifier()) else null;
    const inits = NodeList.init(s.a);
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
fn struct_init_member(s: *Self) !Node {
    const name = try s.eat(.identifier);
    _ = try s.eat(.colon);
    const val = try s.expression();
    return Node{ .struct_init_member = .{ .name = name, .val = val}};
}
fn enum_error_initialization(s: *Self) !Node {
    const name = try s.identifier();
    const val = if(s.l.tok.? == .lparen) blk: {
        _ = try s.eat(.lparen);
        const expr = try s.expression();
        _ = try s.eat(.rparen);
        break :blk expr;
    } else null;
    return Node{ .enum_error_initialization = .{ .name = name, .val = val }};
}
fn struct_(s: *Self) !Node {
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
fn struct_member(s: *Self) !Node {
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
            break :blk2 try s.create_node_ptr(try s.expression());
        } else null;
        _ = try s.eat(.comma);
        break :blk Node{ .struct_member = .{ .names = names, .type = t, .val = val }};
    };
}
fn enum_(s: *Self) !Node {
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
fn enum_member(s: *Self) !Node {
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
fn error_(s: *Self) !Node {
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
fn error_member(s: *Self) !Node {
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
fn capture(s: *Self) !Node {
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
fn capture_item(s: *Self) !Node {
    const mut = if(s.l.tok.? == .mut) blk: {
        _ = try s.eat(.mut);
        break :blk true;
    } else false;
    const val = try s.create_node_ptr(try s.identifier());
    return Node{ .capture_val = .{ .mut = mut, .val = val }};
}

fn identifier(s: *Self) !Node {
    return Node{ .identifier = .{ .value = try s.eat(.identifier) } };
}
fn try_(s: *Self) !Node {
    _ = try s.eat(.@"try");
    return Node{ .try_ = .{ .expression = try s.create_node_ptr(try s.non_literal_expression()) }};
}
fn catch_(s: *Self, n: Node) !Node {
    _ = try s.eat(.@"catch");
    const body = try s.create_node_ptr(try s.result_block());
    return Node{ .catch_ = .{ .expression = try s.create_node_ptr(n), .body = body }}; } fn comp_expression(s: *Self) !Node {
    _ = try s.eat(.comp);
    return Node{ .comp_expression = .{ .expression = try s.create_node_ptr(try s.non_literal_expression()) }};
}
fn call(s: *Self, n: Node) !Node {
    _ = try s.eat(.lparen);
    var args = NodeList.init(s.a);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? == .rparen) break;
        try args.append(try s.expression());
        if(s.l.tok.? == .rparen) break;
        _ = try s.eat(.comma);
    }
    _ = try s.eat(.rparen);
    return Node{ .call = .{ .name = try s.create_node_ptr(n), .args = args }};
}
fn optional_dereference(s: *Self, n: Node) !Node {
    _ = try s.eat(.question);
    return Node{ .pointer_dereference = .{ .expression = try s.create_node_ptr(n) }};
}
fn optional_type(s: *Self) !Node {
    _ = try s.eat(.question);
    return Node{ .optional_type = .{ .expression = try s.create_node_ptr(try s.non_literal_expression()) }};
}
fn pointer_dereference(s: *Self, n: Node) !Node {
    _ = try s.eat(.mul);
    return Node{ .optional_dereference = .{ .expression = try s.create_node_ptr(n) }};
}
fn pointer_type(s: *Self) !Node {
    _ = try s.eat(.mul);
    return Node{ .pointer_type = .{ .expression = try s.create_node_ptr(try s.non_literal_expression()) }};
}
fn array_index(s: *Self, n: Node) !Node {
    _ = try s.eat(.lbrack);
    const index = try s.create_node_ptr(try s.expression());
    _ = try s.eat(.rbrack);
    return Node{ .array_index = .{ .name = try s.create_node_ptr(n), .index = index }};
}
fn array_type(s: *Self) !Node {
    _ = try s.eat(.lbrack);
    _ = try s.eat(.rbrack);
    return Node{ .array_type = .{ .expression = try s.non_literal_expression() }};
}
fn error_union_type(s: *Self, n: Node) !Node {
    _ = try s.eat(.bang);
    var errors = NodeList.init(s.a);
    while(s.l.tok.? != .eof) {
        if(s.l.tok.? != .identifier) break;
        try errors.append(try s.identifier());
        if(s.l.tok.? != .bang) break;
        _ = try s.eat(.bang);
    }
    return Node { .error_union_type = .{ .name = try s.create_node_ptr(n), .errors = errors }};
}
fn member_access(s: *Self, n: Node) !Node {
    return Node{ .member_access = .{ .name = try s.create_node_ptr(n), .member = try s.create_node_ptr(try s.identifier()) }};
}
fn literal(s: *Self) !Node {
    return switch(s.l.tok.?) {
        .int => Node {},
    };
}
fn eat(s: *Self, expected: Token) ![]const u8 {
    if (s.l.tok.? != expected) {
        std.debug.print("Wanted {any}, got {any}, l: {}, c: {} \n", .{ expected, s.l.tok.?, s.l.line, s.l.col });
        return Error.ParserError;
    }
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
