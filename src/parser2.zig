const std = @import("std");
const ast = @import("ast2.zig");
const lexer = @import("lexer.zig");
const token = @import("token.zig");
const errors = @import("errors.zig");
pub const Parser = struct {
    l: lexer.Lexer,
    allocator: std.mem.Allocator,

    pub fn init(alloc: std.mem.Allocator, b: []const u8) Parser {
        return Parser{ .l = lexer.Lexer.init(b), .allocator = alloc };
    }
    pub fn parse(s: *Parser) !*const ast.Node {
        s.l.next_tok();
        return try s.program();
    }
    fn program(s: *Parser) !*const ast.Node {
        var decls = std.ArrayList(*ast.Node).init(s.allocator);
        errdefer decls.deinit();
        // try decls.append(try s.module_decl());
        var pub_decls = std.ArrayList(*ast.Node).init(s.allocator);
        errdefer pub_decls.deinit();
        // while (s.l.tok.? != .eof) {
        //     if (s.l.tok.? == .@"pub") {
        //         _ = try s.consume(.@"pub");
        //         try pub_decls.append(try s.decl());
        //     } else {
        //         try decls.append(try s.decl());
        //     }
        // }
        return &ast.Node{ .Program = .{ .declarations = try decls.toOwnedSlice(), .pub_declarations = try pub_decls.toOwnedSlice() } };
    }
    fn module_decl(s: *Parser) !*const ast.Node {
        _ = try s.consume(.module);
        const name = try s.consume(.identifier);
        _ = try s.consume(.semicolon);
        return &ast.Node{ .ModuleDeclaration = .{ .name = name } };
    }
    fn consume(s: *Parser, t: token.TokenType) ![]const u8 {
        if (s.l.tok.? != t) {} // error out
        const lit = s.l.literal orelse "";
        s.l.next_tok();
        return lit;
    }
};
