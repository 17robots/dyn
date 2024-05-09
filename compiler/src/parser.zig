const std = @import("std");
const lexer = @import("lexer.zig");
const CompilerError = @import("errors.zig").CompilerError;
const TokenType = @import("token.zig").TokenType;
const token = @import("token.zig");
const ast = @import("ast.zig");
const util = @import("util.zig");

const stops = [_]token.TokenType{
    .Continue,
    .Defer,
    .For,
    .If,
    .Return,
    .Match,
    .Type,
};

pub const Parser = struct {
    err: ?CompilerError,
    lexer: lexer.Lexer,
    alloc: std.mem.Allocator,

    pub fn init(alloc: std.mem.Allocator, s: []u8) Parser {
        return .{
            .err = null,
            .lexer = lexer.Lexer.init(s),
            .alloc = alloc,
        };
    }
    // assumes that .next has already been called to load the first token and that there was no error reading it
    pub fn program(s: *Parser) ast.Program {
        var p = ast.Program.init(s.alloc);
        while (s.lexer.tok.type != .Eof and s.lexer.err == null) {
            switch (s.lexer.tok.type) {
                .Pub => {
                    s.lexer.next();
                    p.decls.append(s.module_declaration(true));
                },
                else => {
                    p.decls.append(s.module_declaration(false));
                },
            }
        }
        return ast.Program.init(s.alloc);
    }
    pub fn module_declaration(s: *Parser, public: bool) ast.ModuleDeclaration {
        const md = ast.ModuleDeclaration.init(switch (s.lexer.tok.type) {
            .Struct => s.struct_declaration(),
            .Enum => {},
            .From => {},
            .Ident => {},
            else => {}, // error
        }, public);
        return md;
    }
    pub fn advance(s: *Parser, tokens: []TokenType) void {
        var stopList = std.ArrayList(token.TokenType).init(s.alloc);
        defer stopList.deinit();

        stopList.appendSlice(&stops) catch {};
        stopList.appendSlice(tokens) catch {};

        while (!util.contains(TokenType, stopList.items, s.lexer.tok.type)) {
            s.lexer.next();
            if (tokens.len == 0) {
                break;
            }
        }
    }
    pub fn expect(s: *Parser, t: TokenType) void {
        if (!s.check(t)) {
            // error out
            s.advance(&[_]TokenType{});
        }
    }
    pub fn check(s: *Parser, t: TokenType) bool {
        if (s.lexer.tok.type == t) {
            s.lexer.next();
            return true;
        }
        return false;
    }
    pub fn struct_declaration(s: *Parser) ast.StructDecl {
        s.expect(.Struct);
        // this next one should be a name
        if (!s.check(.Ident)) {} // error
        // we need to verify that the name isnt u[digits] or i[digits]
        const name = s.lexer.tok.lit;
        if (std.mem.eql(u8, name, "f32") or std.mem.eql(u8, name, "f64")) {} // error

        var str = ast.StructDecl.init(name, s.alloc);
        s.expect(.LBrace);
        // now read either fields or variables
        while (!s.check(.RBrace)) {
            switch (s.struct_member_declaration()) {
                .f => |*func| str.methods.append(func),
                .v => |*variable| str.fields.append(variable),
            }
        }
        return str;
    }
    pub fn enum_declaration(s: *Parser) ast.EnumDecl {
        s.expect(.Enum);
        if (!s.check(.Ident)) {} // error
        const name = s.lexer.tok.lit;
        // also check for i[digits] and u[digits]
        if (std.mem.eql(u8, name, "f32") or std.mem.eql(u8, name, "f64")) {} // error
        var e = ast.EnumDecl.init(name);
        s.expect(.LBrace);
        while (!s.check(.RBrace)) {
            e.members.append(s.enum_member());
        }
    }
    pub fn var_fn_declaration(s: *Parser) FieldFunc {
        _ = s;
    }
    pub fn struct_member_declaration(s: *Parser) FieldFunc {
        _ = s;
    }
    pub fn enum_member(s: *Parser) ast.EnumMember {
        s.expect(.Comma);
    }
};
const FieldFunc = union {
    f: ast.FuncDecl,
    v: ast.Field,
};
