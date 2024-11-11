const std = @import("std");
const ast = @import("ast2.zig");
const lexer = @import("lexer.zig");
const token = @import("token.zig");
const errors = @import("errors.zig");

pub const Parser = struct {
    l: lexer.Lexer,
    allocator: std.mem.Allocator,
    const ParsingState = enum {
        base,
    };
    pub fn init(alloc: std.mem.Allocator, b: []const u8) Parser {
        return Parser{ .l = lexer.Lexer.init(b), .allocator = alloc };
    }
    pub fn parse_program(s: *Parser) !ast.Node {
        var pub_decls = try s.create_node_list();
        errdefer pub_decls.deinit();
        var decls = try s.create_node_list();
        errdefer decls.deinit();

        try decls.append(try s.parse_module_declaration());

        while (s.l.tok.? != .eof) {
            switch (s.l.tok.?) {
                .@"pub" => {
                    _ = try s.consume(.@"pub");
                    try pub_decls.append();
                },
                else => try decls.append(),
            }
        }
        return ast.Node{ .Program = .{ .pub_decls = pub_decls, .decls = decls } };
    }
    fn parse_module_declaration(s: *Parser) !ast.Node {
        _ = try s.consume(.module);
        const name = try s.create_node_ptr(ast.Node{ .Literal = .{ .kind = ast.LiteralKind.string, .value = try s.consume(.string) } });
        errdefer s.allocator.destroy(name);
        _ = try s.consume(.semicolon);
        return ast.Node{ .ModuleDecl = .{ .name = name } };
    }
    fn parse_use_decl(s: *Parser) !ast.Node {
        _ = try s.consume(.use);
        return if (s.l.tok.? == .lbrace) {
            try s.parse_use_block();
        } else {
            try s.parse_use_stmt(true);
        };
    }
    fn parse_use_block(s: *Parser) !ast.Node {
        _ = try s.consume(.lbrace);
        var uses = try s.create_node_list();
        errdefer uses.deinit();
        while (s.l.tok.? != .eof) {
            try uses.append(try s.parse_use_stmt(false));
            if (s.l.tok.? == .rbrace) break;
            _ = try s.consume(.comma);
        }
        _ = try s.consume(.rbrace);
    }
    fn parse_use_stmt(s: *Parser, semicolon: bool) !ast.Node {
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
    fn parse_var_decl(s: *Parser, declarator: *ast.Node) !ast.Node {
        var default: ?*ast.Node = null;
        if (s.l.tok.? == .eq) {
            _ = try s.consume(.eq);
            default = null; // read a value here, not just null
        } else {
            if (declarator.* == .Declarator) |d| {
                if (!d.mut) {} // error out because var will never be mutatable
            } else {} // error out because no declarator
        }
        _ = try s.consume(.semicolon);
        return ast.Node{ .VarDecl = .{ .declarator = declarator, .default_val = default } };
    }
    fn parse_fn_decl(s: *Parser, declarator: *ast.Node) !ast.Node {
        _ = try s.consume(.lparen);
        var fn_params = try s.create_node_list();
        while (s.l.tok.? != .eof) {
            try fn_params.append(try s.parse_declarator(false));
            if (s.l.tok.? == .rparen) break;
        }
        _ = try s.consume(.rparen);
        var body: *ast.Node = undefined;
        if (s.l.tok.? == .arrow) {} else if (s.l.tok.? == .lbrace) {
            body = try s.create_node_ptr(try s.parse_block());
        } else {} // error out here
        return ast.Node{ .FnDecl = .{ .declarator = declarator, .body = body } };
    }
    fn parse_fn_literal(s: *Parser) !ast.Node {
        _ = s;
    }
    fn parse_enum(s: *Parser) !ast.Node {
        return switch (s.l.tok.?) {
            .identifier => try s.parse_enum_decl(),
            .lbrace => try s.parse_enum_type(),
            else => {}, // error out
        };
    }
    fn parse_enum_decl(s: *Parser) !ast.Node {
        _ = try s.consume(.@"enum");
        const name = try s.create_node_ptr(ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } });
        var members = try s.create_node_list();
        _ = try s.consume(.lbrace);
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .rbrace) break;
            try members.append(try s.parse_declarator(false));
        }
        _ = try s.consume(.rbrace);
        return ast.Node{ .EnumDecl = .{ .name = name, .members = members } };
    }
    fn parse_enum_type(s: *Parser) !ast.Node {
        _ = try s.consume(.@"enum");
        var members = try s.create_node_list();
        _ = try s.consume(.lbrace);
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .rbrace) break;
            try members.append(try s.parse_declarator(false));
        }
        _ = try s.consume(.rbrace);
        return ast.Node{ .EnumType = .{ .members = members } };
    }
    fn parse_error(s: *Parser) !ast.Node {
        return switch (s.l.tok.?) {
            .identifier => try s.parse_error_decl(),
            .lbrace => try s.parse_error_type(),
            else => {},
        };
    }
    fn parse_error_decl(s: *Parser) !ast.Node {
        _ = try s.consume(.@"error");
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
    fn parse_error_type(s: *Parser) !ast.Node {
        _ = try s.consume(.@"error");
        var members = try s.create_node_list();
        _ = try s.consume(.lbrace);
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .rbrace) break;
            try members.append(try s.parse_declarator(false));
        }
        _ = try s.consume(.rbrace);
        return ast.Node{ .ErrorType = .{ .members = members } };
    }

    fn parse_struct(s: *Parser) !ast.Node {
        return switch (s.l.tok.?) {
            .identifier => try s.parse_struct_decl(),
            .lbrace => try s.parse_struct_type(),
            else => {},
        };
    }
    fn parse_struct_decl(s: *Parser) !ast.Node {
        _ = s;
    }
    fn parse_struct_type(s: *Parser) !ast.Node {
        _ = s;
    }

    fn parse_type(s: *Parser) !ast.Node {
        var base_type: ast.Node = undefined;
        switch (s.l.tok.?) {
            .@"struct" => base_type = try s.parse_struct(),
            .@"enum" => base_type = try s.parse_enum(),
            .@"error" => base_type = try s.parse_error(),
            .identifier => base_type = ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } },
        }
        while (s.l.tok.? != .eof) {
            switch (s.l.tok.?) {
                .lbrack => {},
                .lparen => {},
                .mul => {},
                .question => {},
            }
        }
    }
    fn parse_declarator(s: *Parser, check_mut: bool) !ast.Node {
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

    fn parse_type_decl(s: *Parser) !ast.Node {
        _ = s;
    }

    fn parse_stmt(s: *Parser) !ast.Node {
        _ = s;
    }
    fn parse_block(s: *Parser) !ast.Node {
        _ = s;
    }
    fn parse_decl(s: *Parser) !ast.Node {
        const declarator = try s.create_node_ptr(try s.parse_declarator(true));
        switch (declarator.*) {
            .StructDecl, .EnumDecl, .ErrorDecl, .TypeDecl => return declarator.*,
            else => {},
        }
        return switch (s.l.tok.?) {
            .lparen => try s.parse_fn_decl(),
            else => try s.parse_var_decl(),
        };
    }
    fn parse_expr(s: *Parser) !ast.Node {
        _ = s;
    }
    fn consume(s: *Parser, t: token.TokenType) ![]const u8 {
        if (s.l.tok.? != t) {
            std.debug.print("We had a problem, wanted {any}, got {any}\n", .{ t, s.l.tok.? });
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
