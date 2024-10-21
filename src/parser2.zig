const std = @import("std");
const ast = @import("ast2.zig");
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
    pub fn parse(s: *Parser) !AstNode {
        s.l.next_tok();
        return try s.program();
    }
    fn program(s: *Parser) !AstNode {
        var decls = std.ArrayList(*const ast.Node).init(s.allocator);
        errdefer decls.deinit();
        // try decls.append(try s.module_decl());
        var pub_decls = std.ArrayList(*const ast.Node).init(s.allocator);
        errdefer pub_decls.deinit();
        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .@"pub") {
                _ = try s.consume(.@"pub");
                try pub_decls.append(try s.decl());
            } else {
                try decls.append(try s.decl());
            }
        }
        return &ast.Node{ .Program = .{ .declarations = try decls.toOwnedSlice(), .pub_declarations = try pub_decls.toOwnedSlice() } };
    }
    fn module_decl(s: *Parser) !AstNode {
        _ = try s.consume(.module);
        const name = try s.consume(.string);
        _ = try s.consume(.semicolon);
        return &ast.Node{ .ModuleDeclaration = .{ .name = name } };
    }
    fn consume(s: *Parser, t: token.TokenType) ![]const u8 {
        if (s.l.tok.? != t) {} // error out
        const lit = s.l.literal orelse "";
        s.l.next_tok();
        return lit;
    }
    fn decl(s: *Parser) !AstNode {
        return switch (s.l.tok.?) {
            .use => try s.use_decl(),
            else => try s.var_decl(),
        };
    }
    fn use_decl(s: *Parser) !AstNode {
        _ = try s.consume(.use);
        var imports = std.ArrayList(AstNode).init(s.allocator);
        errdefer imports.deinit();

        if (s.l.tok.? == .lbrace) {
            _ = try s.consume(.lbrace);
            while (s.l.tok.? != .rbrace) {
                const import = ast.Node{ .Literal = .{ .lit_type = .string, .value = try s.consume(.string) } };
                var alias: ?ast.Node = null;
                if (s.l.tok.? == .identifier) {
                    alias = ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } };
                }
                try imports.append(&ast.Node{ .UseDeclaration = .{ .import = &import, .alias = &alias } });
                if (s.l.tok.? == .rparen) break;
                _ = try s.consume(.comma);
            }
            return &ast.Node{ .UseBlock = .{ .uses = &imports } };
        } else {
            const import = ast.Node{ .Literal = .{ .lit_type = .string, .value = try s.consume(.string) } };
            const alias: ?*const ast.Node = if (s.l.tok.? == .identifier) {
                ast.Node{ .Identifier = .{ .value = try s.consume(.identifier) } };
            } else {
                null;
            };
            try s.consume(.semicolon);
            return &ast.Node{ .UseDeclaration = .{ .import = &import, .alias = &alias } };
        }
    }
    fn var_decl(s: *Parser) !AstNode {
        s.l.next_tok();
        return &ast.Node{ .Declaration = @as(void, undefined) };
    }
};
