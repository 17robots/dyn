const std = @import("std");
const ast = @import("ast.zig");
const lexer = @import("lexer.zig");
const token = @import("token.zig");
const errors = @import("errors.zig");
const AstNode: type = *const ast.Node;
pub const Parser = struct {
    l: lexer.Lexer,
    allocator: std.mem.Allocator,

    pub fn init(alloc: std.mem.Allocator, b: []const u8) Parser {
        return Parser{ .l = lexer.Lexer.init(b), .allocator = alloc };
    }
    pub fn parse(s: *Parser) !ast.Node {
        s.l.next_tok();
        return try s.program();
    }
    fn program(s: *Parser) !ast.Node {
        var decls = std.ArrayList(ast.Node).init(s.allocator);
        try decls.append(try s.module_decl());
        var pub_decls = std.ArrayList(ast.Node).init(s.allocator);
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .@"pub") {
                _ = try s.consume(.@"pub");
                try pub_decls.append(try s.decl());
            } else {
                try decls.append(try s.decl());
            }
        }
        return ast.Node{ .Program = .{ .declarations = decls, .pub_declarations = pub_decls } };
    }
    fn module_decl(s: *Parser) !ast.Node {
        var module: ast.Node = undefined;
        _ = try s.consume(.module);
        const name = try s.allocator.create(ast.Node);
        name.* = ast.Node{ .Literal = .{ .lit_type = .string, .value = try s.consume(.string) } };
        _ = try s.consume(.semicolon);
        module = ast.Node{ .ModuleDeclaration = .{ .name = name } };
        return module;
    }
    fn decl(s: *Parser) !ast.Node {
        return switch (s.l.tok.?) {
            .use => {
                _ = try s.consume(.use);
                return if (s.l.tok.? == .lbrace) {
                    return try s.use_block();
                } else {
                    return try s.use_decl(true);
                };
            },
            .@"enum" => try s.enum_decl(),
            .@"error" => try s.error_decl(),
            .identifier, .void, .mut => try s.fn_var_decl(),
            else => {
                s.l.next_tok();
                return ast.Node{ .Declaration = @as(void, undefined) };
            },
        };
    }
    fn stmt(s: *Parser) !ast.Node {
        s.l.next_tok();
        return ast.Node{ .Statement = @as(void, undefined) };
    }
    fn expr(s: *Parser) !ast.Node {
        s.l.next_tok();
        return ast.Node{ .Expression = @as(void, undefined) };
    }
    fn use_block(s: *Parser) !ast.Node {
        _ = try s.consume(.lbrace);
        var use: ast.Node = undefined;
        var uses = std.ArrayList(ast.Node).init(s.allocator);
        while (true) {
            try uses.append(try s.use_decl(false));
            if (s.l.tok.? == .rbrace or s.l.tok.? == .eof) break;
            _ = try s.consume(.comma);
            if (s.l.tok.? == .rbrace or s.l.tok.? == .eof) break; // in case theres a comma at the end before the rbrace
        }
        if (s.l.tok.? == .rbrace) {
            _ = try s.consume(.rbrace);
        }
        use = ast.Node{ .UseBlock = .{ .uses = uses } };
        return use;
    }
    fn use_decl(s: *Parser, read_decl: bool) !ast.Node {
        var use: ast.Node = undefined;
        const import = try s.allocator.create(ast.Node);
        var alias: ?*ast.Node = null;
        import.* = ast.Node{ .Literal = .{ .lit_type = .string, .value = try s.consume(.string) } };
        if (s.l.tok.? == .identifier) {
            alias = try s.allocator.create(ast.Node);
            alias.?.* = ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } };
        }
        if (read_decl) {
            _ = try s.consume(.semicolon);
        }
        use = ast.Node{ .UseDeclaration = .{ .import = import, .alias = alias } };
        return use;
    }
    fn enum_decl(s: *Parser) !ast.Node {
        _ = try s.consume(.@"enum");
        const enum_name = try s.allocator.create(ast.Node);
        enum_name.* = ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } };
        _ = try s.consume(.lbrace);
        var members = std.ArrayList(ast.Node).init(s.allocator);
        while (true) {
            try members.append(try s.enum_member());
            if (s.l.tok.? == .rbrace or s.l.tok.? == .eof) break;
            _ = try s.consume(.comma);
            if (s.l.tok.? == .rbrace or s.l.tok.? == .eof) break; // in case theres a comma at the end before the rbrace
        }
        if (s.l.tok.? == .rbrace) {
            _ = try s.consume(.rbrace);
        }
        return ast.Node{ .EnumDeclaration = .{ .name = enum_name, .members = members } };
    }
    fn enum_member(s: *Parser) !ast.Node {
        const val = try s.allocator.create(ast.Node);
        val.* = ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } };
        return ast.Node{ .EnumMember = .{ .value = val } };
    }
    fn error_decl(s: *Parser) !ast.Node {
        _ = try s.consume(.@"error");
        const error_name = try s.allocator.create(ast.Node);
        error_name.* = ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } };
        _ = try s.consume(.lbrace);
        var members = std.ArrayList(ast.Node).init(s.allocator);
        while (true) {
            try members.append(try s.error_member());
            if (s.l.tok.? == .rbrace or s.l.tok.? == .eof) break;
            _ = try s.consume(.comma);
            if (s.l.tok.? == .rbrace or s.l.tok.? == .eof) break; // in case theres a comma at the end before the rbrace
        }
        if (s.l.tok.? == .rbrace) {
            _ = try s.consume(.rbrace);
        }
        return ast.Node{ .ErrorDeclaration = .{ .name = error_name, .members = members } };
    }
    fn error_member(s: *Parser) !ast.Node {
        const val = try s.allocator.create(ast.Node);
        val.* = ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } };
        return ast.Node{ .ErrorMember = .{ .value = val } };
    }
    fn block(s: *Parser) !ast.Node {
        _ = try s.consume(.lbrace);
        var stmts = std.ArrayList(ast.Node).init(s.allocator);
        errdefer stmts.deinit();
        while (s.l.tok.? != .rbrace and s.l.tok.? != .eof) {
            try stmts.append(try s.stmt());
        }
        _ = try s.consume(.rbrace);
        return ast.Node{ .Block = .{ .stmts = stmts } };
    }
    fn struct_type(s: *Parser) !ast.Node {
        _ = s;
    }
    fn enum_type(s: *Parser) !ast.Node {
        _ = s;
    }
    fn typing(s: *Parser) !ast.Node {
        var curr_type: ast.Node = undefined;
        switch (s.l.tok.?) {
            .void => curr_type = ast.Node{ .VoidType = @as(void, undefined) },
            .@"struct" => curr_type = try s.struct_type(),
            .@"enum" => curr_type = try s.enum_type(),
            .identifier => ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } },
            .lparen => {}, // this means we have a grouping or something that we plan to have as like struct*[]
            else => {}, // this should throw an invalid type specifier
        }
        while (s.l.tok.? != .eof) {
            switch (s.l.tok.?) {
                .lbrack => {
                    _ = try s.consume(.lbrack);
                    _ = try s.consume(.rbrack);
                    const child = try s.allocator.create(ast.Node);
                    child.* = curr_type;
                    curr_type = ast.Node{ .ArrayType = .{ .value = child } };
                },
                .mul => {
                    _ = try s.consume(.mul);
                    const child = try s.allocator.create(ast.Node);
                    child.* = curr_type;
                    curr_type = ast.Node{ .PointerType = .{ .value = child } };
                },
                .question => {
                    _ = try s.consume(.question);
                    const child = try s.allocator.create(ast.Node);
                    child.* = curr_type;
                    curr_type = ast.Node{ .OptionalType = .{ .value = child } };
                },
                .lparen => {},
                .@"struct" => {},
                .@"enum" => {},
                else => break,
            }
        }
        return curr_type;
    }
    fn fn_args(s: *Parser) !std.ArrayList(ast.Node) {
        _ = try s.consume(.lparen);
        var args = std.ArrayList(ast.Node).init(s.allocator);
        errdefer args.deinit();
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .rparen) break;
            var arg_mut = false;
            if (s.l.tok.? == .mut) {
                _ = try s.consume(.mut);
                arg_mut = true;
            }
            const arg_type = try s.allocator.create(ast.Node);
            arg_type.* = try s.typing();
            const arg_name = try s.allocator.create(ast.Node);
            arg_name.* = ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } };
            const arg_default: ?*ast.Node = null;
            if (s.l.tok.? == .eq) {
                _ = try s.consume(.eq);
                // this needs to be an expression thing (which we havent made)
            }
            try args.append(ast.Node{ .FunctionArg = .{ .mut = arg_mut, .arg_name = arg_name, .arg_type = arg_type, .default_val = arg_default } });
            _ = try s.consume(.comma);
        }
        if (s.l.tok.? == .eof) {
            std.debug.print("We need ending )\n", .{}); // error out
        }
        _ = try s.consume(.rparen);
        return args;
    }
    fn fn_var_decl(s: *Parser) !ast.Node {
        var mut = false;
        if (s.l.tok.? == .mut) {
            _ = try s.consume(.mut);
            mut = true;
        }
        const fn_var_type = try s.allocator.create(ast.Node);
        fn_var_type.* = try s.typing();
        const name = try s.allocator.create(ast.Node);
        name.* = ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } };
        if (s.l.tok.? == .lparen) {
            std.debug.print("We are a fn\n", .{});
            if (mut) {} // we have issues
            const args = try s.fn_args();
            const fn_body = try s.allocator.create(ast.Node);
            if (s.l.tok.? == .lbrace) {
                fn_body.* = try s.block();
            } else if (s.l.tok.? == .arrow) {
                _ = try s.consume(.arrow);
                fn_body.* = try s.expr();
            }
            return ast.Node{ .FunctionDeclaration = .{ .args = args, .fn_type = fn_var_type, .fn_name = name, .body = fn_body } };
        } else {
            var var_val: ?*ast.Node = null;
            if (s.l.tok.? == .eq) {
                _ = try s.consume(.eq);
                var_val = try s.allocator.create(ast.Node);
                var_val.?.* = try s.expr();
            }
            if (!mut and var_val == null) {} // unassigned var has to be mut
            _ = try s.consume(.semicolon);
            return ast.Node{ .VariableDeclaration = .{ .mut = mut, .var_type = fn_var_type, .var_name = name, .default_val = var_val } };
        }
    }
    fn consume(s: *Parser, t: token.TokenType) ![]const u8 {
        if (s.l.tok.? != t) {
            std.debug.print("We had a problem, wanted {any}, got {any}\n", .{ t, s.l.tok.? });
        } // error out
        const lit = s.l.literal orelse "";
        s.l.next_tok();
        return lit;
    }
};
