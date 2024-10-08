const std = @import("std");
const ast = @import("ast.zig");
const lexer = @import("lexer.zig");
const token = @import("token.zig");
const errors = @import("errors.zig");

pub const Parser = struct {
    l: lexer.Lexer,
    allocator: std.mem.Allocator,
    prev: struct { tok: ?token.TokenType, literal: ?[]const u8 },

    pub fn init(
        alloc: std.mem.Allocator,
        b: []const u8,
    ) Parser {
        return Parser{ .l = lexer.Lexer.init(b), .allocator = alloc, .prev = .{ .tok = null, .literal = null } };
    }
    pub fn parse(s: *Parser) !ast.AstNode {
        s.l.next_tok();
        if (s.l.err) |_| {
            // error out
        }
        return s.program();
    }
    fn program(s: Parser) !ast.AstNode {
        var decls = std.ArrayList(ast.AstNode).init(s.allocator);
        try decls.append(try s.module_declaration());

        while (s.l.tok != .eof) {
            try decls.append(s.decl());
        }
        return ast.AstNode{ .Program = .{ .declarations = decls.toOwnedSlice() } };
    }
    fn module_declaration(s: *Parser) !ast.AstNode {
        try s.consume(.module);
        const name = try s.consume(.string);
        return ast.AstNode{ .ModuleDeclaration = .{ .name = name } };
    }
    fn decl(s: *Parser) !ast.AstNode {
        return switch (s.l.tok.?) {
            .use => s.use(),
            .@"struct" => s.struct_decl(),
            .@"enum" => s.enum_decl(),
            .@"union" => s.union_decl(),
            .@"error" => s.error_decl(),
            .type => s.type_decl(),
            else => s.function_decl(),
        };
    }
    fn use(s: *Parser) !ast.AstNode {
        try s.consume(.use);
        var imports = std.ArrayList(struct { import: []const u8, alias: ?[]const u8 }).init(s.allocator);
        errdefer imports.deinit();

        if (s.l.tok.? == .lbrace) {
            try s.consume(.lbrace);

            while (s.l.tok.? != .rbrace) {
                const import = try s.consume(.string);
                const alias: ?[]const u8 = if (s.l.tok.? == .identifier) {
                    try s.consume(.identifier);
                } else {
                    null;
                };
                try imports.append(.{ .import = import, .alias = alias });
                if (s.l.tok.? != .rbrace) {
                    try s.consume(.comma);
                }
            }
        } else if (s.l.tok.? == .string) {
            const import = try s.consume(.string);
            const alias: ?[]const u8 = if (s.l.tok.? == .identifier) {
                try s.consume(.identifier);
            } else {
                null;
            };
            try imports.append(.{ .import = import, .alias = alias });
        } else {} // error out
        try s.consume(.semicolon);

        return ast.AstNode{ .UseDeclaration = .{ .modules = imports.toOwnedSlice() } };
    }
    fn struct_decl(s: *Parser) !ast.AstNode {
        try s.consume(.@"struct");
        const name = try s.consume(.identifier);
        var members = std.ArrayList(ast.AstNode).init(s.allocator);
        errdefer members.deinit();
        try s.consume(.lbrace);
        while (s.l.tok.? != .rbrace) {
            try members.append(try s.struct_member());
        }
        try s.consume(.rbrace);
        return ast.AstNode{ .StructDefinition = .{ .name = name, .genericParams = null, .members = members } };
    }
    fn struct_member(s: *Parser) !ast.AstNode {
        const member_type = try s.type_expr();
        const name = try s.consume(.identifier);
        const member = if (s.l.tok == .lparen) {
            s.struct_method(member_type, name);
        } else {
            s.struct_fields();
        };
        return member;
    }
    fn struct_fields(s: *Parser, member_type: ast.AstNode, name: []const u8) !ast.AstNode {
        var fields = std.ArrayList([]const u8).init(s.allocator);
        errdefer fields.deinit();
        try fields.append(name);
        while (s.l.tok.? != .semicolon) {
            try fields.append(try s.consume(.identifier));
            try s.consume(.comma);
        }
        return ast.AstNode{ .StructField = .{ .field_type = member_type, .name = fields.toOwnedSlice() } };
    }
    fn struct_method(s: *Parser, method_type: ast.AstNode, name: []const u8) !ast.AstNode {
        try s.consume(.lparen);
        const params = s.method_param_list();
        try s.consume(.rparen);
        const body: ast.AstNode = if (s.l.tok.? == .arrow) {
            s.expr();
        } else if (s.l.tok.? == .lbrace) {
            s.block();
        };
        return ast.AstNode{};
    }
    fn type_expr(s: *Parser) !ast.AstNode {
        var root_type = ast.AstNode{ .Type = .{ .type = try s.consume(.identifier) } };
        while (true) {
            switch (s.l.tok.?) {
                .lbrack => {
                    try s.consume(.lbrack);
                    try s.consume(.rbrack);
                    root_type = ast.AstNode{ .ArrayType = .{ .type = root_type } };
                },
                .mul => {
                    try s.consume(.mul);
                    root_type = ast.AstNode{ .PointerType = .{ .type = root_type } };
                },
                .question => {
                    try s.consume(.question);
                    root_type = ast.AstNode{ .NullableType = .{ .type = root_type } };
                },
                else => break,
            }
        }
        return root_type;
    }
    fn method_param_list(s: *Parser) !ast.AstNode {}
    fn enum_decl(s: *Parser) !ast.AstNode {}
    fn union_decl(s: *Parser) !ast.AstNode {}
    fn error_decl(s: *Parser) !ast.AstNode {}
    fn type_decl(s: *Parser) !ast.AstNode {}
    fn function_decl(s: *Parser) !ast.AstNode {}
    fn return_type(s: *Parser) !ast.AstNode {}
    fn param_list(s: *Parser) !ast.AstNode {}
    fn param_type(s: *Parser) !ast.AstNode {}
    fn primitive_type(s: *Parser) !ast.AstNode {}
    fn block(s: *Parser) !ast.AstNode {}
    fn stmt(s: *Parser) !ast.AstNode {}
    fn if_stmt(s: *Parser) !ast.AstNode {}
    fn loop_stmt(s: *Parser) !ast.AstNode {}
    fn for_stmt(s: *Parser) !ast.AstNode {}
    fn range_expr(s: *Parser) !ast.AstNode {}
    fn match_stmt(s: *Parser) !ast.AstNode {}
    fn match_arm(s: *Parser) !ast.AstNode {}
    fn match_pattern(s: *Parser) !ast.AstNode {}
    fn range_pattern(s: *Parser) !ast.AstNode {}
    fn defer_stmt(s: *Parser) !ast.AstNode {}
    fn inline_stmt(s: *Parser) !ast.AstNode {}
    fn var_decl(s: *Parser) !ast.AstNode {}
    fn expr_stmt(s: *Parser) !ast.AstNode {}
    fn expr(s: *Parser) !ast.AstNode {}
    fn assignment(s: *Parser) !ast.AstNode {}
    fn or_expr(s: *Parser) !ast.AstNode {}
    fn and_expr(s: *Parser) !ast.AstNode {}
    fn eql(s: *Parser) !ast.AstNode {}
    fn cmp(s: *Parser) !ast.AstNode {}
    fn add(s: *Parser) !ast.AstNode {}
    fn mul(s: *Parser) !ast.AstNode {}
    fn unary(s: *Parser) !ast.AstNode {}
    fn primary_expr(s: *Parser) !ast.AstNode {}
    fn consume(s: *Parser, token_type: token.TokenType) ![]const u8 {
        if (s.l.tok.? != token_type) {} // error out
        const lit = s.l.literal orelse "";
        s.l.next_tok();
        return lit;
    }
    fn at_end(s: *Parser, token_type: token.TokenType) bool {}
    fn peek(s: *Parser, token_type: token.TokenType) bool {}
    fn previous(s: *Parser, token_type: token.TokenType) bool {}
    fn peek_next(s: *Parser, token_type: token.TokenType) bool {}
    fn error_type(s: *Parser, token_type: token.TokenType) bool {}
    fn comptime_param_list(s: *Parser, token_type: token.TokenType) bool {}
};
