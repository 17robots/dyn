const std = @import("std");
const lexer = @import("lexer.zig");
const Lexer = lexer.Lexer;
const LexerState = lexer.LexerState;
const Token = @import("token.zig").TokenType;
const Error = @import("errors.zig").Error;
const Node = @import("ast.zig").Node;

const Self = @This();

l: Lexer,
a: std.mem.Allocator,

pub fn init(alloc: std.mem.Allocator, buf: []const u8) Self {
    return Self{ .l = Lexer.init(buf), .a = alloc };
}
pub fn program(s: *Self) !Node {
    var pub_decls = try s.create_node_list();
    var decls = try s.create_node_list();
    try pub_decls.append(try s.module());
    _ = try s.eat(.semicolon);
    while (s.l.tok.? != .eof) {
        switch (s.l.tok.?) {
            .@"pub" => {
                _ = try s.eat(.@"pub");
                const x = switch (s.l.tok.?) {
                    .use => try s.use(),
                    else => try s.decl(),
                };
                switch (x) {
                    .UseStmt, .VarDecl => _ = try s.eat(.semicolon),
                    else => {},
                }
                try pub_decls.append(x);
            },
            else => {
                const x = switch (s.l.tok.?) {
                    .use => try s.use(),
                    else => try s.decl(),
                };
                switch (x) {
                    .UseStmt, .VarDecl => _ = try s.eat(.semicolon),
                    else => {},
                }
                try decls.append(x);
            },
        }
    }
}
fn module(s: *Self) !Node {
    _ = try s.eat(.module);
    const module_ = Node{ .ModuleDeclaration = .{ .name = try s.create_node_ptr(Node{ .Literal = .{ .kind = .string, .value = try s.eat(.string) } }) } };
    _ = try s.eat(.semicolon);
    return module_;
}
fn use(s: *Self) anyerror!Node {
    _ = try s.eat(.use);
    return switch (s.l.tok.?) {
        .lbrace => try s.use_block(),
        else => try s.use_stmt(),
    };
}
fn use_block(s: *Self) anyerror!Node {
    var uses = try s.create_node_list();
    try s.loop_read(.lbrace, .rbrace, .comma, struct {
        fn func(_uses: *std.ArrayList(Node), _s: *Self) !void {
            try _uses.append(try _s.use_stmt());
        }
    }.func, .{ &uses, s });
    return Node{ .UseBlock = .{ .uses = uses } };
}
fn use_stmt(s: *Self) anyerror!Node {
    const alias = switch (s.l.tok.?) {
        .identifier => try s.create_node_ptr(Node{ .Identifier = .{ .value = try s.eat(.identifier) } }),
        else => null,
    };
    const import = try s.create_node_ptr(Node{ .Literal = .{ .kind = .string, .value = try s.eat(.string) } });
    return Node{ .UseStmt = .{ .alias = alias, .value = import } };
}
fn type_expr(s: *Self) !Node {
    var type_node = switch (s.l.tok.?) {
        .lparen => blk: {
            _ = try s.eat(.lparen);
            break :blk Node{ .GroupType = .{ ._type = try s.create_node_ptr(try s.type_expr()) } };
        },
        .identifier => try s.member_chain(),
        .void => blk: {
            _ = try s.eat(.void);
            break :blk Node.Void;
        },
        .type => blk: {
            _ = try s.eat(.type);
            break :blk Node.Type;
        },
        .@"struct" => try s.struct_(),
        .@"enum" => try s.enum_(),
        .@"error" => try s.error_(),
    };
    switch (type_node) {
        .StructDecl, .EnumDecl, .ErrorDecl => return type_node,
        else => {},
    }
    while (s.l.tok.? != .eof) {
        switch (s.l.tok.?) {
            .question => {
                _ = try s.eat(.question);
                type_node = Node{ .OptionalType = .{ .type = try s.create_node_ptr(type_node) } };
            },
            .mul => {
                _ = try s.eat(.mul);
                type_node = Node{ .PointerType = .{ .type = try s.create_node_ptr(type_node) } };
            },
            .lbrack => {
                _ = try s.eat(.lbrack);
                const expr_ = switch (s.l.tok.?) {
                    .lbrack => null,
                    else => try s.create_node_ptr(try s.expr()),
                };
                _ = try s.eat(.rbrack);
                type_node = Node{ .ArrayType = .{ .type = try s.create_node_ptr(type_node), .number = expr_ } };
            },
            .lparen => {
                var args = try s.create_node_list();
                s.loop_read(.lparen, .rparen, .comma, struct {
                    fn func(_args: *std.ArrayList(Node), _s: *Self) !void {
                        try _args.append(try _s.type_expr());
                    }
                }.func, .{ &args, s });
                type_node = Node{ .FnType = .{ .type = try s.create_node_ptr(type_node), .args = args } };
            },
            .lt => {
                var errs = try s.create_node_list();
                try s.loop_read(.lt, .gt, .comma, struct {
                    fn func(_args: *std.ArrayList(Node), _s: *Self) !void {
                        try _args.append(Node{ .Identifier = .{ .value = try _s.eat(.identifier) } });
                    }
                }.func, .{ &errs, s });
                type_node = Node{ .ErrorUnionType = .{ .type = try s.create_node_ptr(type_node), .errs = errs } };
            },
        }
    }
    return type_node;
}
fn decl(s: *Self) !Node {
    const mut = switch (s.l.tok.?) {
        .mut => blk: {
            _ = try s.eat(.mut);
            break :blk true;
        },
        else => false,
    };
    const type_node = try s.type_expr();
    switch (type_node) {
        .StructDecl, .EnumDecl, .ErrorDecl => {
            if (mut) return Error.ParserError; // error
            return type_node;
        },
        else => {},
    }
    const declarator_ = Node{ .Declarator = .{ .mut = mut, .type = try s.create_node_ptr(type_node), .name = try s.create_node_ptr(Node{ .Identifier = .{ .value = try s.eat(.identifier) } }) } };
    return switch (s.l.tok.?) {
        .lparen => try s.fn_decl(try s.create_node_ptr(declarator_)),
        else => try s.var_decl(try s.create_node_ptr(declarator_)),
    };
}
fn member_chain(s: *Self) !Node {
    var member = Node{ .Identifier = .{ .value = try s.eat(.identifier) } };
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .dot) {
            _ = try s.eat(.dot);
            member = Node{ .MemberAccess = .{ .root = try s.create_node_ptr(member), .access = try s.create_node_ptr(Node{ .Identifier = .{ .value = try s.eat(.identifier) } }) } };
        } else break;
    }
    return member;
}
fn dereference_chain(s: *Self) !Node {
    var member = Node{ .Identifier = .{ .value = try s.eat(.identifier) } };
    var could_be_fn_type = true;
    var could_be_array_type = true;
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == .dot) {
            _ = try s.eat(.dot);
            switch(member) {
                .ArrayType => |d| {
                    member = Node{ .ArrayIndex = .{ .root = d.type, .expr = d.number } };
                    could_be_fn_type = false;
                    could_be_array_type = false;
                },
                .FnType => |d| {
                    member = Node{ .FnCall = .{ .callee = d.type, .args = d.args }};
                    could_be_fn_type = false;
                    could_be_array_type = false;
                },
                else => {},
            }
            switch (s.l.tok.?) {
                .identifier => member = Node{ .MemberAccess = .{ .root = try s.create_node_ptr(member), .access = try s.create_node_ptr(Node{ .Identifier = .{ .value = try s.eat(.identifier) } }) } },
                .question => {
                    _ = try s.eat(.question);
                    could_be_fn_type = false;
                    could_be_array_type = false;
                    member = Node{ .OptionalDereference = .{ .root = try s.create_node_ptr(member) } };
                },
                .mul => {
                    _ = try s.eat(.mul);
                    could_be_fn_type = false;
                    could_be_array_type = false;
                    member = Node{ .PointerDereference = .{ .root = try s.create_node_ptr(member) } };
                },
            }
        } else if (s.l.tok.? == .lbrack) {
            _ = try s.eat(.lbrack);
            const expr_ = switch (s.l.tok.?) {
                .rbrack => null,
                else => try s.create_node_ptr(try s.expr()),
            };
            member = Node{ .ArrayIndex = .{ .root = try s.create_node_ptr(member), .expr = expr_ } };
            _ = try s.eat(.rbrack);
        } else if (s.l.tok.? == .lparen) {
            var args = try s.create_node_list();
            try s.loop_read(.lparen, .rparen, .comma, struct {
                fn func(_args: *std.ArrayList(Node), _s: *Self) !void {
                    const state = _s.save_lexer();
                    try _args.append(blk: {
                    });
                }
            }.func, .{ &args, s });
            member = Node{ .FnCall = .{ .callee = try s.create_node_ptr(member), .args = args } };
        } else break;
    }
    return member;
}
fn expr(s: *Self, prec: u8) !Node {
    _ = s;
    _ = prec;
}
fn stmt(s: *Self) !Node {
    switch (s.l.tok.?) {
        .@"break" => try break_(),
        .@"for" => try for_(),
        .@"if" => try if_(),
        .match => try match_(),
        .@"while" => try while_(),
        .@"return" => try return_(),
        else => try s.decl_stmt(), // TODO: add this after
    }
}
fn decl_stmt(s: *Self) !Node {
    switch (s.l.tok.?) {
        .identifier => {
            const x = try s.dereference_chain();
        },
        .lparen => {},
        else => {},
    }
}
fn if_(s: *Self) !Node {
    _ = try s.eat(.@"if");
    const condition = try s.expr();
    const body = switch (s.l.tok.?) {
        .lbrace => try s.body(),
        else => try s.stmt(),
    };
    const else_body = switch (s.l.tok.?) {
        .@"else" => blk: {
            _ = try s.eat(.@"else");
            break :blk try s.create_node_ptr(switch (s.l.tok.?) {
                .@"if" => try s.if_(),
                .lbrace => try s.block(),
                else => try s.stmt(),
            });
        },
        else => null,
    };
    return Node{ .IfStmt = .{ .condition = try s.create_node_ptr(condition), .body = try s.create_node_ptr(body), .else_body = else_body } };
}
fn for_(s: *Self) !Node {
    _ = try s.eat(.@"for");
    const expr_ = try s.expr();
    const capture = try s.capture_();
    const body = switch (s.l.tok.?) {
        .lbrace => try s.body(),
        else => try s.stmt(),
    };
    return Node{ .ForStmt = .{ .condition = try s.create_node_ptr(expr_), .capture = try s.create_node_ptr(capture), .body = try s.create_node_ptr(body) } };
}
fn while_(s: *Self) !Node {
    _ = try s.eat(.@"while");
    const condition = try s.expr();
    const body = switch (s.l.tok.?) {
        .lbrace => try s.body(),
        else => try s.stmt(),
    };
    return Node{ .WhileStmt = .{ .condition = try s.create_node_ptr(condition), .body = try s.create_node_ptr(body) } };
}
fn match_(s: *Self) !Node {
    _ = try s.eat(.match);
    const expr_ = try s.expr();
    var arms = try s.create_node_list();
    try s.loop_read(.lbrace, .rbrace, .comma, struct {
        fn func(_arms: *std.ArrayList(Node), _s: *Self) !void {
            try _arms.append(try _s.match_arm());
        }
    }.func, .{ &arms, s });
    return Node{ .MatchStmt = .{ .expr = try s.create_node_ptr(expr_), .arms = arms } };
}
fn match_arm(s: *Self) !Node {
    var exprs = try s.create_node_list();
    try s.loop_read(null, .colon, .comma, struct {
        fn func(_exprs: *std.ArrayList(Node), _s: *Self) !void {
            try _exprs.append(try _s.expr());
        }
    }.func, .{ &exprs, s });
    const body = try s.expr();
    return Node{ .MatchArm = .{ .exprs = exprs, .body = try s.create_node_ptr(body) } };
}
fn try_(s: *Self) !Node {
    _ = try s.eat(.@"try");
}
fn break_(s: *Self) !Node {
    _ = try s.eat(.@"break");
    return Node.BreakStmt;
}
fn return_(s: *Self) !Node {
    _ = try s.eat(.@"return");
    const result = switch (s.l.tok.?) {
        .semicolon => null,
        else => try s.create_node_ptr(s.expr()),
    };
    return Node{ .ReturnStmt = .{ .result = result } };
}
fn capture_(s: *Self) !Node {
    _ = try s.eat(.@"or");
    const x = switch (s.l.tok.?) {
        .mul => blk: {
            _ = try s.eat(.mul);
            break :blk Node{ .ReferenceCapture = .{ .identifier = try s.create_node_ptr(Node{ .Identifier = .{ .value = try s.eat(.identifier) } }) } };
        },
        else => Node{ .Capture = .{ .identifier = try s.create_node_ptr(switch (s.l.tok.?) {
            .underscore => blk: {
                _ = try s.eat(.underscore);
                break :blk Node.Underscore;
            },
            else => Node{ .Identifier = .{ .value = try s.eat(.identifier) } },
        }) } },
    };
    _ = try s.eat(.@"or");
    return x;
}
fn defer_(s: *Self) !Node {
    _ = try s.eat(.@"defer");
    const capture = switch (s.l.tok.?) {
        .@"or" => try s.create_node_ptr(try s.capture_()),
        else => null,
    };
    const body = switch (s.l.tok.?) {
        .lbrace => try s.body(),
        else => try s.stmt(),
    };
    return Node{ .DeferStmt = .{ .capture = capture, .body = try s.create_node_ptr(body) } };
}
fn block(s: *Self) !Node {
    var stmts = try s.create_node_list();
    try s.loop_read(.lbrace, .rbrace, .semicolon, struct {
        fn func(_stmts: *std.ArrayList(Node), _s: *Self) !void {
            try _stmts.append(try _s.stmt());
        }
    }.func, .{ &stmts, s });
    return Node{ .BlockStmt = .{ .stmts = stmts } };
}
fn var_decl(s: *Self, declarator: *Node) !Node {
    return switch (declarator.*) {
        .Declarator => |d| blk: {
            const expr_ = switch (s.l.tok.?) {
                .eq => try s.create_node_ptr(switch (d) {
                    .Void => try s.stmt(),
                    .Type => try s.type_expr(),
                    else => try s.expr(),
                }),
                else => null,
            };
            break :blk Node{ .VarDecl = .{ .declarator = declarator, .default = expr_ } };
        },
        else => Error.ParserError,
    };
}
fn fn_decl(s: *Self, declarator: *Node) !void {
    return switch (declarator.*) {
        .Declarator => |d| blk: {
            var members = try s.create_node_list();
            try s.loop_read(.lparen, .rparen, .comma, struct {
                fn func(_members: *std.ArrayList(Node), _s: *Self) !void {
                    const member_type = try _s.type_expr();
                    const member_name = try Node{ .Identifier = .{ .value = try _s.eat(.identifier) } };
                    try _members.append(Node{ .Declarator = .{ .mut = false, .type_ = try s.create_node_ptr(member_type), .name = try s.create_node_ptr(member_name) } });
                }
            }.func, .{ &members, s });
            const body = switch (s.l.tok.?) {
                .arrow => arrow_block: {
                    _ = try s.eat(.arrow);
                    break :arrow_block switch (d.type_.*) {
                        .Void => try s.stmt(),
                        .Type => try s.type_expr(),
                        else => try s.expr(),
                    };
                },
                .lbrace => try s.block(),
            };
            break :blk Node{ .FnDecl = .{ .declarator = declarator, .body = try s.create_node_ptr(body) } };
        },
        else => Error.ParserError,
    };
}
fn struct_(s: *Self) !Node {
    _ = try s.eat(.@"struct");
    const name = switch (s.l.tok.?) {
        .identifier => Node{ .Identifier = .{ .value = try s.eat(.identifier) } },
        .lbrace => null,
        else => return Error.ParserError,
    };
    var members = try s.create_node_list();
    try s.loop_read(.lbrace, .rbrace, .comma, struct {
        fn func(_members: *std.ArrayList(Node), _s: *Self) !void {
            const member_type = try s.type_expr();
            switch (member_type) {
                .StructDeclaration, .EnumDeclaration, .ErrorDeclaration => try _members.append(member_type),
                else => {
                    const member_declarator = Node{ .Declarator = .{ .type_ = try s.create_node_ptr(member_type), .name = try s.create_node_ptr(Node{ .Identifier = .{ .value = try s.eat(.identifier) } }) } };
                    try _members.append(switch (s.l.tok.?) {
                        .lparen => try _s.fn_decl(try _s.create_node_ptr(member_declarator)),
                        else => try _s.var_decl(try _s.create_node_ptr(member_declarator)),
                    });
                },
            }
        }
    }.func, .{ &members, s });
    return if (name) |n| {
        Node{ .StructDeclaration = .{ .name = try s.create_node_ptr(n), .members = members } };
    } else {
        Node{ .StructType = .{ .members = members } };
    };
}
fn enum_(s: *Self) !Node {
    _ = try s.eat(.@"enum");
    const name = switch (s.l.tok.?) {
        .identifier => Node{ .Identifier = .{ .value = try s.eat(.identifier) } },
        .lbrace => null,
        else => return Error.ParserError,
    };
    var members = try s.create_node_list();
    try s.loop_read(.lbrace, .rbrace, .comma, struct {
        fn func(_members: *std.ArrayList(Node), _s: *Self) !void {
            var x = try _s.type_expr();
            if (_s.l.tok.? == .identifier) {
                x = Node{ .Declarator = .{ .mut = false, .type_ = try s.create_node_ptr(x), .name = Node{ .Identifier = .{ .value = try s.eat(.identifier) } } } };
            } else {
                if (x != .Identifier) return Error.ParserError;
            }
            try _members.append(x);
        }
    }.func, .{ &members, s });
    return if (name) |n| {
        Node{ .EnumDeclaration = .{ .name = try s.create_node_ptr(n), .members = members } };
    } else {
        Node{ .EnumType = .{ .members = members } };
    };
}
fn error_(s: *Self) !Node {
    _ = try s.eat(.@"error");
    const name = switch (s.l.tok.?) {
        .identifier => Node{ .Identifier = .{ .value = try s.eat(.identifier) } },
        .lbrace => null,
        else => return Error.ParserError,
    };
    var members = try s.create_node_list();
    try s.loop_read(.lbrace, .rbrace, .comma, struct {
        fn func(_members: *std.ArrayList(Node), _s: *Self) !void {
            var x = try _s.type_expr();
            if (_s.l.tok.? == .identifier) {
                x = Node{ .Declarator = .{ .mut = false, .type_ = try s.create_node_ptr(x), .name = Node{ .Identifier = .{ .value = try s.eat(.identifier) } } } };
            } else {
                if (x != .Identifier) return Error.ParserError;
            }
            try _members.append(x);
        }
    }.func, .{ &members, s });
    return if (name) |n| {
        Node{ .ErrorDeclaration = .{ .name = try s.create_node_ptr(n), .members = members } };
    } else {
        Node{ .ErrorType = .{ .members = members } };
    };
}
fn eat(s: *Self, expected: Token) ![]const u8 {
    if (s.l.tok.? != expected) return Error.ParserError;
    defer s.l.next_tok();
    return s.l.literal orelse "";
}
fn create_node_ptr(s: *Self, n: Node) *Node {
    const x = try s.a.create(Node);
    x.* = n;
    return x;
}
fn create_node_list(s: *Self) std.ArrayList(Node) {
    return std.ArrayList(Node).init(s.a);
}
fn loop_read(s: *Self, l: ?Token, r: Token, sep: ?Token, func: anytype, args: anytype) !void {
    if (l) |_l| _ = try s.eat(_l);
    while (s.l.tok.? != .eof) {
        if (s.l.tok.? == r) break;
        try @call(.auto, func, args);
        if (s.l.tok.? == r) break;
        if (sep) |_s| _ = try s.eat(_s);
    }
    _ = try s.eat(r);
}
fn save_lexer(s: *Self) LexerState {
    return LexerState{ .index = s.l.index, .tok = s.l.tok.?, .line = s.l.line, .col = s.l.col };
}
fn restore_lexer(s: *Self, pos: LexerState) void {
    s.l.index = pos.index;
    s.l.tok = pos.tok;
    s.l.line = pos.line;
    s.l.col = pos.col;
}
