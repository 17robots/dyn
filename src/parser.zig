const std = @import("std");
const lexer = @import("lexer.zig");
const errors = @import("errors.zig");
const ast = @import("ast.zig");
const token = @import("token.zig");

pub const Parser = struct {
    l: lexer.Lexer,
    errors: []std.MultiArrayList(errors.Error),
    fnDepth: usize,
    exprDepth: usize,
    filename: []const u8,
    allocator: std.mem.Allocator,

    pub fn init(alloc: std.mem.Allocator, filename: []const u8, buffer: []const u8) Parser {
        return Parser{ .l = lexer.Lexer.init(buffer), .errors = .{}, .fnDept = 0, .exprDepth = 0, .filname = filename, .allocator = alloc };
    }

    pub fn file(s: *Parser) ?ast.Node {
        const root: ?ast.Node = null;
        s.l.next_tok();
        root = ast.Node.init(.program, null);

        if (s.module()) |mod| {
            root.nodes.append(s.allocator, mod);
        } else {
            // error out here because we dont want to do anything if the file is broken
        }
        while (!s.expect(.eof)) {
            const dec = s.declaration();
            if (dec) |d| {
                root.nodes.append(s.allocator, d);
            } else {
                // we error out
            }
        }
        return root;
    }

    pub fn expect(s: *Parser, t: ?token.TokenType) bool {
        if (t) |tok| {
            if (s.l.tok) |lexTok| {
                return lexTok == tok;
            } else {
                return false;
            }
        } else {
            if (s.l.tok) |_| {
                return false;
            } else {
                return true;
            }
        }
    }

    pub fn declaration(s: *Parser) ?ast.Node {
        s.l.next_tok();
        if (s.expect(.@"struct")) {} // parse struct
        else if (s.expect(.@"enum")) {} // parse enum
        else if (s.expect(.@"pub")) {} // parse pub decl
        else if (s.expect(.@"union")) {} // parse union
        else if (s.expect(.@"error")) {} // parse error
        else if (s.expect(.mut)) {} else {}
    }

    pub fn statement(s: *Parser) ?ast.Node {
        s.l.next_tok();
        if (s.expect(.@"if")) {} else if (s.expect(.loop)) {} else if (s.expect(.@"for")) {} else if (s.expect(.identifier)) {} else if (s.expect(.mut)) {} else if (s.expect(.match)) {} else if (s.expect(.@"defer")) {} else if (s.expect(.@"return")) {}
    }

    pub fn expression(s: *Parser) ?ast.Node {}

    pub fn module(s: *Parser) ?ast.Node {
        if (s.expect(.module)) {
            var mod = ast.Node.init(.moduleDeclaration, null);
            s.l.next_tok();
            if (s.expect(.string)) {
                if (std.mem.eql(u8, "", s.l.literal)) {
                    // error out
                }
                mod.nodes.append(s.allocator, ast.Node.init(.literal, ast.LiteralMetadata{ .kind = .string, .val = s.l.literal }));
                return mod;
            } else {
                // we need to error out
            }
        } else {
            return null;
        }
    }

    pub fn use_block(s: *Parser) ?ast.Node {
        // this assumes we've already read the "use" and the {
        var useBlock = ast.Node.init(.useBlock, null);
        while (!s.expect(.rbrace)) {
            const useStatement = s.use_statement();
            if (useStatement) |us| {
                useBlock.nodes.append(s.allocator, us);
            } else {
                // invalid
            }
        }
        return useBlock;
    }

    pub fn use_statement(s: *Parser) ?ast.Node {
        var useStatement = ast.Node.init(.useDeclaration, null);
        s.l.next_tok();
        if (s.expect(.identifier)) {
            useStatement.nodes.append(s.allocator, ast.Node.init(.identifier, ast.IdentifierMetadata{ .val = s.l.literal }));
            s.l.next_tok();
            if (s.expect(.string)) {
                useStatement.nodes.append(s.allocator, ast.Node.init(.literal, ast.LiteralMetadata{ .kind = .string, .val = s.l.literal }));
            } else {
                return null;
            }
        } else if (s.expect(.string)) {
            useStatement.nodes.append(s.allocator, null); // no identifier
            useStatement.nodes.append(s.allocator, ast.Node.init(.literal, ast.LiteralMetadata{ .kind = .string, .val = s.l.literal }));
        } else {
            return null;
        }
        return useStatement;
    }
};
