const std = @import("std");
const ast = @import("ast.zig");
const lexer = @import("lexer.zig");
const token = @import("token.zig");
const errors = @import("errors.zig");

const Precedence = enum(u8) {
    none,
    @"or",
    @"and",
    equals,
    compare,
    add,
    mul,
    postfix,
    primary,
};

pub const Parser = struct {
    l: lexer.Lexer,
    allocator: std.mem.Allocator,
    const ParsingState = enum {
        base,
    };
    pub fn init(alloc: std.mem.Allocator, b: []const u8) Parser {
        return Parser{ .l = lexer.Lexer.init(b), .allocator = alloc };
    }
    pub fn parse_program(s: *Parser) anyerror!ast.Node {
        s.l.next_tok();
        var pub_decls = try s.create_node_list();
        errdefer pub_decls.deinit();
        var decls = try s.create_node_list();
        errdefer decls.deinit();

        try decls.append(try s.parse_module_declaration());

        while (s.l.tok.? != .eof) {
            switch (s.l.tok.?) {
                .@"pub" => {
                    _ = try s.consume(.@"pub");
                    if (s.l.tok.? == .use) {
                        try pub_decls.append(try s.parse_use_decl());
                    } else {
                        try pub_decls.append(try s.parse_decl());
                    }
                },
                else => if (s.l.tok.? == .use) {
                    try pub_decls.append(try s.parse_use_decl());
                } else {
                    try pub_decls.append(try s.parse_decl());
                },
            }
        }
        return ast.Node{ .Program = .{ .pub_decls = pub_decls, .decls = decls } };
    }
    fn parse_module_declaration(s: *Parser) anyerror!ast.Node {
        _ = try s.consume(.module);
        const name = try s.create_node_ptr(ast.Node{ .Literal = .{ .kind = ast.LiteralKind.string, .value = try s.consume(.string) } });
        errdefer s.allocator.destroy(name);
        _ = try s.consume(.semicolon);
        return ast.Node{ .ModuleDecl = .{ .name = name } };
    }
    fn parse_use_decl(s: *Parser) anyerror!ast.Node {
        _ = try s.consume(.use);
        if (s.l.tok.? == .lbrace) {
            return try s.parse_use_block();
        } else {
            return try s.parse_use_stmt(true);
        }
    }
    fn parse_use_block(s: *Parser) anyerror!ast.Node {
        _ = try s.consume(.lbrace);
        var uses = try s.create_node_list();
        errdefer uses.deinit();
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .rbrace) break;
            try uses.append(try s.parse_use_stmt(false));
            if (s.l.tok.? == .rbrace) break;
            _ = try s.consume(.comma);
        }
        _ = try s.consume(.rbrace);
        return ast.Node{ .UseBlock = .{ .uses = uses } };
    }
    fn parse_use_stmt(s: *Parser, semicolon: bool) anyerror!ast.Node {
        var alias: ?*ast.Node = null;
        if (s.l.tok.? == .identifier) {
            alias = try s.create_node_ptr(ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } });
        }
        const import = try s.create_node_ptr(ast.Node{ .Literal = .{ .kind = .string, .value = try s.consume(.string) } });
        if (semicolon) {
            _ = try s.consume(.semicolon);
        }
        return ast.Node{ .UseStmt = .{ .alias = alias, .value = import } };
    }
    fn parse_var_decl(s: *Parser, declarator: *ast.Node) anyerror!ast.Node {
        var default: ?*ast.Node = null;
        if (s.l.tok.? == .eq) {
            _ = try s.consume(.eq);
            default = try s.create_node_ptr(try s.parse_expr(.none)); // read a value here, not just null
        } else {
            switch (declarator.*) {
                .Declarator => |d| {
                    if (!d.mut) {} // error out because var will never be mutatable
                },
                else => {}, // error out cause not declarator
            }
        }
        _ = try s.consume(.semicolon);
        return ast.Node{ .VarDecl = .{ .declarator = declarator, .default_val = default } };
    }
    fn parse_fn_decl(s: *Parser, declarator: *ast.Node) anyerror!ast.Node {
        _ = try s.consume(.lparen);
        var fn_params = try s.create_node_list();
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .rparen) break;
            try fn_params.append(try s.parse_declarator(false));
            if (s.l.tok.? == .rparen) break;
            _ = try s.consume(.comma);
        }
        _ = try s.consume(.rparen);
        var body: ast.Node = undefined;
        if (s.l.tok.? == .arrow) {
            _ = try s.consume(.arrow);
            switch (declarator.*) {
                .Declarator => |d| {
                    if (d.type.* == .Void) {
                        body = try s.parse_stmt();
                    } else {
                        body = try s.parse_expr(.none);
                        _ = try s.consume(.semicolon);
                    }
                },
                else => {}, // error out
            }
        } else if (s.l.tok.? == .lbrace) {
            body = try s.parse_block();
        } else {} // error out here
        return ast.Node{ .FnDecl = .{ .declarator = declarator, .body = try s.create_node_ptr(body), .args = fn_params } };
    }
    fn parse_fn_literal(s: *Parser) anyerror!ast.Node {
        const fn_type = try s.parse_type();
        switch (fn_type) {
            .StructDecl, .EnumDecl, .ErrorDecl => {}, // error out
            else => {},
        }
        _ = try s.consume(.lparen);
        var args = try s.create_node_list();
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .rparen) break;
            try args.append(try s.parse_declarator(false));
            if (s.l.tok.? == .rparen) break;
            _ = try s.consume(.comma);
        }
        _ = try s.consume(.rparen);
        var body: *ast.Node = undefined;
        if (s.l.tok.? == .arrow) {
            body = try s.create_node_ptr(try s.parse_expr(.none));
        } else if (s.l.tok.? == .rbrace) {
            body = try s.create_node_ptr(try s.parse_block());
        } else {} // error out
    }
    fn parse_enum(s: *Parser) anyerror!ast.Node {
        _ = try s.consume(.@"enum");
        return switch (s.l.tok.?) {
            .identifier => try s.parse_enum_decl(),
            .lbrace => try s.parse_enum_type(),
            else => errors.Error.ParserError, // error out
        };
    }
    fn parse_enum_decl(s: *Parser) anyerror!ast.Node {
        const name = try s.create_node_ptr(ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } });
        var members = try s.create_node_list();
        _ = try s.consume(.lbrace);
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .rbrace) break;
            var member = try s.parse_type();
            if (s.l.tok.? == .identifier) {
                member = ast.Node{ .Declarator = .{ .mut = false, .type = try s.create_node_ptr(member), .name = try s.create_node_ptr(ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } }) } };
            }
            try members.append(member);
            if (s.l.tok.? == .rbrace) break;
            _ = try s.consume(.comma);
        }
        _ = try s.consume(.rbrace);
        return ast.Node{ .EnumDecl = .{ .name = name, .members = members } };
    }
    fn parse_enum_type(s: *Parser) anyerror!ast.Node {
        var members = try s.create_node_list();
        _ = try s.consume(.lbrace);
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .rbrace) break;
            try members.append(try s.parse_declarator(false));
        }
        _ = try s.consume(.rbrace);
        return ast.Node{ .EnumType = .{ .members = members } };
    }
    fn parse_error(s: *Parser) anyerror!ast.Node {
        _ = try s.consume(.@"error");
        return switch (s.l.tok.?) {
            .identifier => try s.parse_error_decl(),
            .lbrace => try s.parse_error_type(),
            else => errors.Error.ParserError,
        };
    }
    fn parse_error_decl(s: *Parser) anyerror!ast.Node {
        const name = try s.create_node_ptr(ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } });
        var members = try s.create_node_list();
        _ = try s.consume(.lbrace);
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .rbrace) break;
            try members.append(try s.parse_declarator(false));
        }
        _ = try s.consume(.rbrace);
        return ast.Node{ .ErrorDecl = .{ .name = name, .members = members } };
    }
    fn parse_error_type(s: *Parser) anyerror!ast.Node {
        var members = try s.create_node_list();
        _ = try s.consume(.lbrace);
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .rbrace) break;
            try members.append(try s.parse_declarator(false));
        }
        _ = try s.consume(.rbrace);
        return ast.Node{ .ErrorType = .{ .members = members } };
    }

    fn parse_struct(s: *Parser) anyerror!ast.Node {
        _ = try s.consume(.@"struct");
        return switch (s.l.tok.?) {
            .identifier => try s.parse_struct_decl(),
            .lbrace => try s.parse_struct_type(),
            else => errors.Error.ParserError,
        };
    }
    fn parse_struct_decl(s: *Parser) anyerror!ast.Node {
        const name = try s.create_node_ptr(ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } });
        _ = try s.consume(.lbrace);
        var members = try s.create_node_list();
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .rbrace) break;
            const declarator = try s.parse_declarator(false);
            switch (declarator) {
                .Declarator => {
                    switch (s.l.tok.?) {
                        .lparen => {
                            _ = try s.consume(.lparen);
                            var args = try s.create_node_list();
                            while (s.l.tok.? != .eof) {
                                if (s.l.tok.? == .rparen) break;
                                try args.append(try s.parse_declarator(false));
                                if (s.l.tok.? == .rparen) break;
                            }
                            _ = try s.consume(.rparen);
                            var body: ast.Node = undefined;
                            if (s.l.tok.? == .arrow) {
                                _ = try s.consume(.arrow);
                                body = try s.parse_expr(.none);
                            } else if (s.l.tok.? == .lbrace) {
                                body = try s.parse_block();
                            } else {}
                            try members.append(ast.Node{ .FnDecl = .{ .declarator = try s.create_node_ptr(declarator), .args = args, .body = try s.create_node_ptr(body) } });
                        }, // function
                        .eq => {
                            _ = try s.consume(.eq);
                            try members.append(ast.Node{ .VarDecl = .{ .declarator = try s.create_node_ptr(declarator), .default_val = try s.create_node_ptr(try s.parse_expr(.none)) } });
                        }, // variable default
                        else => try members.append(declarator), // uhhhh dunno
                    }
                },
                .StructDecl, .EnumDecl, .ErrorDecl => {
                    try members.append(declarator);
                },
                else => {}, // error out
            }
            if (s.l.tok.? == .rbrace) break;
            _ = try s.consume(.comma);
        }
        _ = try s.consume(.rbrace);
        return ast.Node{ .StructDecl = .{ .name = name, .members = members } };
    }
    fn parse_struct_type(s: *Parser) anyerror!ast.Node {
        _ = try s.consume(.lbrace);
        var members = try s.create_node_list();
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .rbrace) break;
            const declarator = try s.parse_declarator(false);
            switch (declarator) {
                .Declarator => {
                    switch (s.l.tok.?) {
                        .lparen => {
                            _ = try s.consume(.lparen);
                            var args = try s.create_node_list();
                            while (s.l.tok.? != .eof) {
                                if (s.l.tok.? == .rparen) break;
                                try args.append(try s.parse_declarator(false));
                                if (s.l.tok.? == .rparen) break;
                            }
                            _ = try s.consume(.rparen);
                            var body: ast.Node = undefined;
                            if (s.l.tok.? == .arrow) {
                                _ = try s.consume(.arrow);
                                body = try s.parse_expr(.none);
                            } else if (s.l.tok.? == .lbrace) {
                                body = try s.parse_block();
                            } else {}
                            try members.append(ast.Node{ .FnDecl = .{ .declarator = try s.create_node_ptr(declarator), .args = args, .body = try s.create_node_ptr(body) } });
                        }, // function
                        .eq => {
                            _ = try s.consume(.eq);
                            try members.append(ast.Node{ .VarDecl = .{ .declarator = try s.create_node_ptr(declarator), .default_val = try s.create_node_ptr(try s.parse_expr(.none)) } });
                        }, // variable default
                        else => try members.append(declarator), // uhhhh dunno
                    }
                },
                .StructDecl, .EnumDecl, .ErrorDecl => {
                    try members.append(declarator);
                },
                else => {}, // error out
            }
            if (s.l.tok.? == .rbrace) break;
            _ = try s.consume(.comma);
        }
        _ = try s.consume(.rbrace);
        return ast.Node{ .StructType = .{ .members = members } };
    }

    fn parse_type(s: *Parser) anyerror!ast.Node {
        var base_type: ast.Node = undefined;
        switch (s.l.tok.?) {
            .@"struct" => base_type = try s.parse_struct(),
            .@"enum" => base_type = try s.parse_enum(),
            .@"error" => base_type = try s.parse_error(),
            .identifier => base_type = ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } },
            .void => {
                _ = try s.consume(.void);
                base_type = ast.Node.Void;
            },
            else => {
                std.debug.print("We had a problem at line {d}, col {d}, {any} \n", .{ s.l.line, s.l.col, s.l.tok.? });
                return errors.Error.ParserError;
            }, // error out
        }
        switch (base_type) {
            .StructDecl, .EnumDecl, .ErrorDecl, .UseStmt, .UseBlock => return base_type,
            else => {},
        }
        while (s.l.tok.? != .eof) {
            switch (s.l.tok.?) {
                .lbrack => {
                    _ = try s.consume(.lbrack);
                    _ = try s.consume(.rbrack);
                    base_type = ast.Node{ .ArrayType = .{ .type = try s.create_node_ptr(base_type) } };
                },
                .lparen => {
                    _ = try s.consume(.lparen);
                    var types = try s.create_node_list();
                    while (s.l.tok.? != .eof) {
                        if (s.l.tok.? == .rparen) break;
                        try types.append(try s.parse_type());
                        if (s.l.tok.? == .rparen) break;
                        _ = try s.consume(.comma);
                    }
                    _ = try s.consume(.rparen);
                    base_type = ast.Node{ .FnType = .{ .type = try s.create_node_ptr(base_type), .args = types } };
                },
                .mul => {
                    _ = try s.consume(.mul);
                    base_type = ast.Node{ .PointerType = .{ .type = try s.create_node_ptr(base_type) } };
                },
                .question => {
                    _ = try s.consume(.question);
                    base_type = ast.Node{ .OptionalType = .{ .type = try s.create_node_ptr(base_type) } };
                },
                else => break,
            }
        }
        return base_type;
    }
    fn parse_declarator(s: *Parser, check_mut: bool) anyerror!ast.Node {
        var mut = false;
        if (s.l.tok.? == .mut) {
            if (!check_mut) {}
            _ = try s.consume(.mut);
            mut = true;
        }
        const the_type = try s.create_node_ptr(try s.parse_type());
        switch (the_type.*) {
            .StructDecl, .EnumDecl, .ErrorDecl, .TypeDecl => {
                if (check_mut) {} // then we have error
                return the_type.*;
            },
            else => {},
        }
        const name = try s.create_node_ptr(ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } });
        return ast.Node{ .Declarator = .{ .mut = mut, .type = the_type, .name = name } };
    }

    fn parse_type_decl(s: *Parser) anyerror!ast.Node {
        _ = try s.consume(.type);
        const name = try s.create_node_ptr(ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } });
        _ = try s.consume(.eq);
        const res_type = try s.parse_type();
        switch (res_type) {
            .StructDecl, .EnumDecl, .ErrorDecl => {}, // error out
            else => {},
        }
        return ast.Node{ .TypeDecl = .{ .name = name, .type = try s.create_node_ptr(res_type) } };
    }

    fn parse_block(s: *Parser) anyerror!ast.Node {
        _ = try s.consume(.lbrace);
        var stmts = try s.create_node_list();
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .rbrace) break;
            try stmts.append(try s.parse_stmt());
        }
        _ = try s.consume(.rbrace);
        return ast.Node{ .BlockStmt = .{ .stmts = stmts } };
    }
    fn parse_decl(s: *Parser) anyerror!ast.Node {
        const declarator = try s.create_node_ptr(try s.parse_declarator(true));
        switch (declarator.*) {
            .StructDecl, .EnumDecl, .ErrorDecl, .TypeDecl, .UseStmt, .UseBlock => return declarator.*,
            else => {},
        }
        return switch (s.l.tok.?) {
            .lparen => try s.parse_fn_decl(declarator),
            else => try s.parse_var_decl(declarator),
        };
    }
    fn parse_decl_stmt(s: *Parser) anyerror!ast.Node {
        var mut = false;
        if (s.l.tok.? == .mut) {
            _ = try s.consume(.mut);
            mut = true;
        }
        var the_type: *ast.Node = undefined;
        switch (s.l.tok.?) {
            .@"struct" => the_type = try s.create_node_ptr(try s.parse_struct()),
            .@"enum" => the_type = try s.create_node_ptr(try s.parse_enum()),
            .@"error" => the_type = try s.create_node_ptr(try s.parse_error()),
            .identifier => the_type = try s.create_node_ptr(ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } }),
            .void => {
                _ = try s.consume(.void);
                the_type = try s.create_node_ptr(ast.Node.Void);
            },
            else => {
                std.debug.print("We have a bad token: {any}, line: {}, col: {}\n", .{ s.l.tok.?, s.l.line, s.l.col });
                return errors.Error.ParserError;
            },
        }
        switch (the_type.*) {
            .StructDecl, .EnumDecl, .ErrorDecl, .TypeDecl => {
                if (mut) {} // then we have error
                return the_type.*;
            },
            .Identifier => {
                while (s.l.tok.? != .eof) {
                    switch (s.l.tok.?) {
                        .dot => {
                            _ = try s.consume(.dot);
                            switch (s.l.tok.?) {
                                .question => {
                                    _ = try s.consume(.question);
                                    the_type = try s.create_node_ptr(ast.Node{ .OptionalDereferenceExpr = .{ .expr = the_type } });
                                },
                                .mul => {
                                    _ = try s.consume(.mul);
                                    the_type = try s.create_node_ptr(ast.Node{ .PointerDereferenceExpr = .{ .expr = the_type } });
                                },
                                .identifier => {
                                    the_type = try s.create_node_ptr(ast.Node{ .MemberAccess = .{ .root = the_type, .access = try s.create_node_ptr(ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } }) } });
                                },
                                .lbrack => {
                                    _ = try s.consume(.lbrack);
                                    const expr = try s.parse_expr(.none);
                                    _ = expr;
                                    _ = try s.consume(.rbrack);
                                },
                                else => break,
                            }
                        },
                        .lparen => {
                            _ = try s.consume(.lparen);
                            var args = try s.create_node_list();
                            while (s.l.tok.? != .eof) {
                                if (s.l.tok.? == .rparen) break;
                                try args.append(try s.parse_expr(.none));
                                if (s.l.tok.? == .rparen) break;
                                _ = try s.consume(.comma);
                            }
                            _ = try s.consume(.rparen);
                            the_type = try s.create_node_ptr(ast.Node{ .FnCall = .{ .callee = the_type, .args = args } });
                            break;
                        },
                        .lbrack => {
                            _ = try s.consume(.lbrack);
                            the_type = try s.create_node_ptr(ast.Node{ .ArrayIndex = .{ .callee = the_type, .index = try s.create_node_ptr(try s.parse_expr(.none)) } });
                            _ = try s.consume(.rbrack);
                        },
                        else => break,
                    }
                }
            },
            else => {},
        }
        if (the_type.* == .FnCall) {
            _ = try s.consume(.semicolon);
            return the_type.*;
        }
        switch (s.l.tok.?) {
            .eq => {
                _ = try s.consume(.eq);
                the_type = try s.create_node_ptr(ast.Node{ .Assignment = .{ .left = the_type, .assign = .normal, .right = try s.create_node_ptr(try s.parse_expr(.none)) } });
            },
            .addeq => {
                _ = try s.consume(.addeq);
                the_type = try s.create_node_ptr(ast.Node{ .Assignment = .{ .left = the_type, .assign = .add, .right = try s.create_node_ptr(try s.parse_expr(.none)) } });
            },
            .subeq => {
                _ = try s.consume(.subeq);
                the_type = try s.create_node_ptr(ast.Node{ .Assignment = .{ .left = the_type, .assign = .sub, .right = try s.create_node_ptr(try s.parse_expr(.none)) } });
            },
            .muleq => {
                _ = try s.consume(.muleq);
                the_type = try s.create_node_ptr(ast.Node{ .Assignment = .{ .left = the_type, .assign = .mul, .right = try s.create_node_ptr(try s.parse_expr(.none)) } });
            },
            .diveq => {
                _ = try s.consume(.diveq);
                the_type = try s.create_node_ptr(ast.Node{ .Assignment = .{ .left = the_type, .assign = .div, .right = try s.create_node_ptr(try s.parse_expr(.none)) } });
            },
            .modeq => {
                _ = try s.consume(.modeq);
                the_type = try s.create_node_ptr(ast.Node{ .Assignment = .{ .left = the_type, .assign = .mod, .right = try s.create_node_ptr(try s.parse_expr(.none)) } });
            },
            .xoreq => {
                _ = try s.consume(.xoreq);
                the_type = try s.create_node_ptr(ast.Node{ .Assignment = .{ .left = the_type, .assign = .xor, .right = try s.create_node_ptr(try s.parse_expr(.none)) } });
            },
            .andeq => {
                _ = try s.consume(.andeq);
                the_type = try s.create_node_ptr(ast.Node{ .Assignment = .{ .left = the_type, .assign = .@"and", .right = try s.create_node_ptr(try s.parse_expr(.none)) } });
            },
            .oreq => {
                _ = try s.consume(.oreq);
                the_type = try s.create_node_ptr(ast.Node{ .Assignment = .{ .left = the_type, .assign = .@"or", .right = try s.create_node_ptr(try s.parse_expr(.none)) } });
            },
            else => {},
        }
        switch (the_type.*) {
            .Assignment => {
                _ = try s.consume(.semicolon);
                return the_type.*;
            },
            else => {},
        }
        while (s.l.tok.? != .eof) {
            switch (s.l.tok.?) {
                .lbrack => {
                    _ = try s.consume(.lbrack);
                    _ = try s.consume(.rbrack);
                    the_type = try s.create_node_ptr(ast.Node{ .ArrayType = .{ .type = the_type } });
                },
                .lparen => {
                    _ = try s.consume(.lparen);
                    var types = try s.create_node_list();
                    while (s.l.tok.? != .eof) {
                        if (s.l.tok.? == .rparen) break;
                        try types.append(try s.parse_type());
                        if (s.l.tok.? == .rparen) break;
                        _ = try s.consume(.comma);
                    }
                    _ = try s.consume(.rparen);
                    the_type = try s.create_node_ptr(ast.Node{ .FnType = .{ .type = the_type, .args = types } });
                },
                .mul => {
                    _ = try s.consume(.mul);
                    the_type = try s.create_node_ptr(ast.Node{ .PointerType = .{ .type = the_type } });
                },
                .question => {
                    _ = try s.consume(.question);
                    the_type = try s.create_node_ptr(ast.Node{ .OptionalType = .{ .type = the_type } });
                },
                else => break,
            }
        }
        const name = try s.create_node_ptr(ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } });
        the_type = try s.create_node_ptr(ast.Node{ .Declarator = .{ .mut = mut, .type = the_type, .name = name } });
        return switch (s.l.tok.?) {
            .lparen => try s.parse_fn_decl(the_type),
            else => try s.parse_var_decl(the_type),
        };
    }
    fn parse_expr(s: *Parser, precedence: Precedence) anyerror!ast.Node {
        var base: ast.Node = undefined;
        // prefix
        switch (s.l.tok.?) {
            .int => base = ast.Node{ .Literal = .{ .kind = .int, .value = try s.consume(.int) } },
            .float => base = ast.Node{ .Literal = .{ .kind = .float, .value = try s.consume(.float) } },
            .string => base = ast.Node{ .Literal = .{ .kind = .string, .value = try s.consume(.string) } },
            .char => base = ast.Node{ .Literal = .{ .kind = .char, .value = try s.consume(.char) } },
            .identifier => base = ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } },
            .undefined => base = ast.Node{ .Literal = .{ .kind = .undefined, .value = try s.consume(.undefined) } },
            .null => base = ast.Node{ .Literal = .{ .kind = .null, .value = try s.consume(.null) } },
            .true => base = ast.Node{ .Literal = .{ .kind = .bool, .value = try s.consume(.true) } },
            .false => base = ast.Node{ .Literal = .{ .kind = .bool, .value = try s.consume(.false) } },
            .lparen => {
                _ = try s.consume(.lparen);
                base = ast.Node{ .GroupingExpr = .{ .expr = try s.create_node_ptr(try s.parse_expr(.none)) } };
                _ = try s.consume(.rparen);
            },
            .sub => {
                _ = try s.consume(.sub);
                base = ast.Node{ .NegateExpr = .{ .expr = try s.create_node_ptr(try s.parse_expr(.none)) } };
            },
            .flip => {
                _ = try s.consume(.flip);
                base = ast.Node{ .FlipExpr = .{ .expr = try s.create_node_ptr(try s.parse_expr(.none)) } };
            },
            .bang => {
                _ = try s.consume(.bang);
                base = ast.Node{ .NotExpr = .{ .expr = try s.create_node_ptr(try s.parse_expr(.none)) } };
            },
            .@"and" => {
                _ = try s.consume(.@"and");
                base = ast.Node{ .ReferenceExpr = .{ .expr = try s.create_node_ptr(try s.parse_expr(.none)) } };
            },
            .lbrace => {
                base = ast.Node{ .BlockExpr = .{ .block = try s.create_node_ptr(try s.parse_block()) } };
            },
            .lbrack => base = try s.parse_array_literal(),
            .dot => {
                _ = try s.consume(.dot);
                switch (s.l.tok.?) {
                    .identifier => base = ast.Node{ .MemberAccess = .{ .root = null, .access = try s.create_node_ptr(ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } }) } },
                    .lbrace => base = try s.parse_struct_literal(),
                    else => return errors.Error.ParserError,
                }
            },
            .@"if" => base = ast.Node{ .IfExpr = .{ .expr = try s.create_node_ptr(try s.parse_if_stmt()) } },
            .match => base = ast.Node{ .MatchExpr = .{ .expr = try s.create_node_ptr(try s.parse_match_stmt()) } },
            else => {}, // invalid prefix
        }
        // infix
        while (s.l.tok.? != .eof) {
            const prec = s.get_precedence();
            if (@intFromEnum(precedence) > prec) break;
            switch (s.l.tok.?) {
                .add, .sub, .mul, .div, .mod, .eqeq, .bangeq, .lt, .gt, .lteq, .gteq, .andand, .oror, .dotdot => {
                    const op = try s.get_operator();
                    _ = try s.consume(s.l.tok.?);
                    const new_precedence: Precedence = @enumFromInt(prec + 1);
                    base = ast.Node{ .BinaryExpr = .{ .left = try s.create_node_ptr(base), .op = op, .right = try s.create_node_ptr(try s.parse_expr(new_precedence)) } };
                },
                .lparen => {
                    _ = try s.consume(.lparen);
                    var args = try s.create_node_list();
                    while (s.l.tok.? != .eof) {
                        if (s.l.tok.? == .rparen) break;
                        try args.append(try s.parse_expr(.none));
                        if (s.l.tok.? == .rparen) break;
                        _ = try s.consume(.comma);
                    }
                    base = ast.Node{ .FnCall = .{ .callee = try s.create_node_ptr(base), .args = args } };
                    _ = try s.consume(.rparen);
                },
                .dot => {
                    _ = try s.consume(.dot);
                    switch (s.l.tok.?) {
                        .question => {
                            _ = try s.consume(.question);
                            base = ast.Node{ .OptionalDereferenceExpr = .{ .expr = try s.create_node_ptr(base) } };
                        },
                        .mul => {
                            _ = try s.consume(.mul);
                            base = ast.Node{ .PointerDereferenceExpr = .{ .expr = try s.create_node_ptr(base) } };
                        },
                        .identifier => base = ast.Node{ .MemberAccess = .{ .root = try s.create_node_ptr(base), .access = try s.create_node_ptr(ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } }) } },
                        else => break,
                    }
                },
                .lbrack => {
                    _ = try s.consume(.lbrack);
                    base = ast.Node{ .ArrayIndex = .{ .callee = try s.create_node_ptr(base), .index = try s.create_node_ptr(try s.parse_expr(.none)) } };
                    _ = try s.consume(.rbrack);
                },
                .@"else" => {
                    _ = try s.consume(.@"else");
                    if (base != .Identifier) {
                        std.debug.print("{}, {}:  Using else with identifier not allowed\n", .{ s.l.line, s.l.col });
                        return errors.Error.ParserError;
                    }
                    base = ast.Node{ .ElseIdentifier = .{ .ident = try s.create_node_ptr(base), .else_ident = try s.create_node_ptr(try s.parse_expr(.none)) } };
                    break;
                },
                else => break,
            }
        }
        return base;
    }
    fn get_precedence(s: Parser) u8 {
        return @intFromEnum(switch (s.l.tok.?) {
            .oror => Precedence.@"or",
            .andand => Precedence.@"and",
            .eqeq, .bangeq => Precedence.equals,
            .lt, .gt, .lteq, .gteq => Precedence.compare,
            .add, .sub => Precedence.add,
            .mul, .div, .mod => Precedence.mul,
            .lparen, .dot => Precedence.postfix,
            else => Precedence.none,
        });
    }
    fn get_operator(s: Parser) anyerror!ast.OperatorKind {
        return switch (s.l.tok.?) {
            .add => .add,
            .sub => .sub,
            .mul => .mul,
            .div => .div,
            .mod => .mod,
            .eqeq => .eqeq,
            .bangeq => .bangeq,
            .lt => .lt,
            .lteq => .lte,
            .gt => .gt,
            .gteq => .gte,
            .andand => .andand,
            .oror => .oror,
            .dotdot => .dotdot,
            else => errors.Error.ParserError,
        };
    }
    fn parse_struct_literal(s: *Parser) anyerror!ast.Node {
        _ = try s.consume(.lbrace);
        var initializers = try s.create_node_list();
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .rbrace) break;
            try initializers.append(try s.parse_struct_initializer());
            if (s.l.tok.? == .rbrace) break;
            _ = try s.consume(.comma);
        }
        _ = try s.consume(.rbrace);
        return ast.Node{ .StructLiteral = .{ .initializers = initializers } };
    }
    fn parse_struct_initializer(s: *Parser) anyerror!ast.Node {
        const ident = ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } };
        _ = try s.consume(.colon);
        const expr = try s.parse_expr(.none);
        return ast.Node{ .StructInitializer = .{ .ident = try s.create_node_ptr(ident), .value = try s.create_node_ptr(expr) } };
    }
    fn parse_array_literal(s: *Parser) anyerror!ast.Node {
        _ = try s.consume(.lbrack);
        var items = try s.create_node_list();
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .rbrack) break;
            try items.append(try s.parse_expr(.none));
            if (s.l.tok.? == .rbrack) break;
            _ = try s.consume(.comma);
        }
        _ = try s.consume(.rbrack);
        return ast.Node{ .ArrayLiteral = .{ .items = items } };
    }
    fn parse_stmt(s: *Parser) anyerror!ast.Node {
        return switch (s.l.tok.?) {
            .@"if" => try s.parse_if_stmt(),
            .match => try s.parse_match_stmt(),
            .@"defer" => try s.parse_defer_stmt(),
            .@"return" => try s.parse_return_stmt(),
            .@"for" => try s.parse_for_stmt(),
            .@"while" => try s.parse_while_stmt(),
            .@"break" => try s.parse_break_stmt(),
            else => try s.parse_decl_stmt(),
        };
    }
    fn parse_if_stmt(s: *Parser) anyerror!ast.Node {
        _ = try s.consume(.@"if");
        const condition = try s.create_node_ptr(try s.parse_expr(.none));
        var capture: ?*ast.Node = null;
        if (s.l.tok.? == .@"or") capture = try s.create_node_ptr(try s.parse_capture());
        var body: ast.Node = undefined;
        var else_body: ?*ast.Node = null;
        if (s.l.tok.? == .lbrace) {
            body = try s.parse_block();
        } else {
            body = try s.parse_stmt();
        }
        if (s.l.tok.? == .@"else") {
            _ = try s.consume(.@"else");
            if (s.l.tok.? == .@"if") {
                else_body = try s.create_node_ptr(try s.parse_if_stmt());
            } else if (s.l.tok.? == .lbrace) {
                else_body = try s.create_node_ptr(try s.parse_block());
            } else {
                else_body = try s.create_node_ptr(try s.parse_stmt());
            }
        }
        return ast.Node{ .IfStmt = .{ .condition = condition, .capture = capture, .body = try s.create_node_ptr(body), .else_body = else_body } };
    }
    fn parse_match_stmt(s: *Parser) anyerror!ast.Node {
        _ = try s.consume(.match);
        const to_match = ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } };
        var match_arms = try s.create_node_list();
        _ = try s.consume(.lbrace);
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .rbrace) break;
            try match_arms.append(try s.parse_match_arm());
            if (s.l.tok.? == .rbrace) break;
            _ = try s.consume(.comma);
        }
        _ = try s.consume(.rbrace);
        return ast.Node{ .MatchStmt = .{ .to_match = try s.create_node_ptr(to_match), .match_arms = match_arms } };
    }
    fn parse_match_arm(s: *Parser) anyerror!ast.Node {
        var branches = try s.create_node_list();
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .colon) break;
            if (s.l.tok.? == .underscore) {
                _ = try s.consume(.underscore);
                try branches.append(ast.Node.Underscore);
            } else {
                try branches.append(try s.parse_expr(.none));
            }
            if (s.l.tok.? == .colon) break;
            _ = try s.consume(.comma);
        }
        // verify that if underscore then nothing else
        _ = try s.consume(.colon);
        const expr = try s.parse_expr(.none);
        return ast.Node{ .MatchArm = .{ .branches = branches, .block = try s.create_node_ptr(expr) } };
    }
    fn parse_defer_stmt(s: *Parser) anyerror!ast.Node {
        _ = try s.consume(.@"defer");
        var capture: ?*ast.Node = null;
        if (s.l.tok.? == .@"or") {
            capture = try s.create_node_ptr(try s.parse_capture());
        }
        var stmt: ast.Node = undefined;
        if (s.l.tok.? == .lbrace) {
            stmt = try s.parse_block();
        } else {
            stmt = try s.parse_stmt();
        }
        return ast.Node{ .DeferStmt = .{ .capture = capture, .stmt = try s.create_node_ptr(stmt) } };
    }
    fn parse_return_stmt(s: *Parser) anyerror!ast.Node {
        _ = try s.consume(.@"return");
        const expr = try s.parse_expr(.none);
        _ = try s.consume(.semicolon);
        return ast.Node{ .ReturnStmt = .{ .expr = try s.create_node_ptr(expr) } };
    }
    fn parse_for_stmt(s: *Parser) anyerror!ast.Node {
        _ = try s.consume(.@"for");
        const expr = try s.parse_expr(.none);
        const capture = try s.parse_capture();
        var body: ast.Node = undefined;
        if (s.l.tok.? == .lbrace) {
            body = try s.parse_block();
        } else {
            body = try s.parse_stmt();
        }
        return ast.Node{ .ForStmt = .{ .expr = try s.create_node_ptr(expr), .capture = try s.create_node_ptr(capture), .body = try s.create_node_ptr(body) } };
    }
    fn parse_capture(s: *Parser) anyerror!ast.Node {
        var mut = false;
        _ = try s.consume(.@"or");
        if (s.l.tok.? == .mut) {
            _ = try s.consume(.mut);
            mut = true;
        }
        const ident = ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } };
        _ = try s.consume(.@"or");
        return ast.Node{ .Capture = .{ .mut = mut, .ident = try s.create_node_ptr(ident) } };
    }
    fn parse_while_stmt(s: *Parser) anyerror!ast.Node {
        _ = try s.consume(.@"while");
        const expr = try s.parse_expr(.none);
        var body: ast.Node = undefined;
        if (s.l.tok.? == .lbrace) {
            body = try s.parse_block();
        } else {
            body = try s.parse_stmt();
        }
        return ast.Node{ .WhileStmt = .{ .expr = try s.create_node_ptr(expr), .body = try s.create_node_ptr(body) } };
    }
    fn parse_break_stmt(s: *Parser) anyerror!ast.Node {
        _ = try s.consume(.@"break");
        _ = try s.consume(.semicolon);
        return ast.Node.BreakStmt;
    }
    fn consume(s: *Parser, t: token.TokenType) anyerror![]const u8 {
        if (s.l.tok.? != t) {
            std.debug.print("We had a problem, wanted {any}, got {any} at line {d}, col {d} \n", .{ t, s.l.tok.?, s.l.line, s.l.col });
            return errors.Error.ParserError;
        } // error out
        const lit = s.l.literal orelse "";
        s.l.next_tok();
        return lit;
    }
    fn create_node_ptr(s: *Parser, val: ast.Node) !*ast.Node {
        const x = try s.allocator.create(ast.Node);
        x.* = val;
        return x;
    }
    fn create_node_list(s: *Parser) !std.ArrayList(ast.Node) {
        return std.ArrayList(ast.Node).init(s.allocator);
    }
};
