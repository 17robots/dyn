const std = @import("std");
const ast = @import("ast.zig");
const lexer = @import("lexer.zig");
const token = @import("token.zig");
const errors = @import("errors.zig");

const Precedence = enum(u8) { lowest, assignment, @"or", @"and", equality, comparison, term, factor, unary, call, primary };

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
        const params = try s.method_param_list();
        try s.consume(.rparen);
        const body: ast.AstNode = if (s.l.tok.? == .arrow) {
            s.expr();
        } else if (s.l.tok.? == .lbrace) {
            s.block();
        };
        return ast.AstNode{ .StructMethod = .{ .return_type = method_type, .name = name, .parameters = params, .body = body } };
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
        if (s.l.tok.? == .bang) {
            root_type = ast.AstNode{ .ErrorType = .{ .core_type = root_type, .error_type = try s.consume(.identifier) } };
        }
        return root_type;
    }
    fn method_param_list(s: *Parser) ![]ast.AstNode {
        var params = std.ArrayList(ast.AstNode).init(s.allocator);
        errdefer params.deinit();
        while (s.l.tok.? != .rparen) {
            const t = try s.type_expr();
            const name = try s.consume(.identifier);
            if (s.l.tok.? == .rparen) {
                break;
            }
            try s.consume(.comma);
            try params.append(ast.AstNode{ .Parameter = .{ .mutable = false, .isComptime = false, .paramType = t, .name = name } });
        }
        return params.toOwnedSlice();
    }
    fn enum_decl(s: *Parser) !ast.AstNode {
        try s.consume(.@"enum");
        const name = try s.consume(.identifier);
        try s.consume(.lbrack);
        var enum_members = std.ArrayList(ast.AstNode).init(s.allocator);
        while (s.l.tok.? != .rbrack) {
            if (s.l.tok.? == .identifier) {
                const first = try s.consume(.identifier);
                try enum_members.append(if (s.l.tok.? == .identifier) {
                    ast.AstNode{ .EnumVariant = .{ .variant_type = .{ .Type = .{ .type = first } }, .variant = try s.consume(.identifier) } };
                } else {
                    ast.AstNode{ .EnumVariant = .{ .variant_type = null, .variant = first } };
                });
            } else if (s.l.tok.? == .comma) {
                // we error here because there was no variant supplied
            } else {
                const enum_type = try s.type_expr();
                try enum_members.append(ast.AstNode{ .EnumVariant = .{ .variant_type = enum_type, .variant = try s.consume(.identifier) } });
            }
            if (s.l.tok.? == .rbrack) break;
            s.consume(.comma);
        }
        return ast.AstNode{ .EnumDefinition = .{ .name = name, .variants = enum_members } };
    }
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
    fn parse_precedence(s: *Parser, precedence: Precedence) !ast.AstNode {
        var left = s.prefix();
        while (precedence <= s.get_infix_precedence()) {
            left = try s.infix();
        }
        return left;
    }
    fn prefix(s: *Parser) !ast.AstNode {
        return switch (s.l.tok) {
            .integer, .float => s.literal(),
            .string => s.string_literal(),
            .true, .false => s.bool_literal(),
            .null => s.null_literal(),
            .identifier => s.variable(),
            .lparen => s.grouping(),
            .minus, .bang => s.unaryOp(),
        };
    }
    fn infix(s: *Parser, left: ast.AstNode) !ast.AstNode {
        return switch (s.l.tok) {
            .add, .sub, .mul, .div, .mod => s.binary_expr(left),
            .eqeq, .bangeq, .lt, .lte, .gt, .gte => s.binary_expr(left),
            .@"and", .@"or" => s.logical_operator(left),
            .lparen => s.function_call(left),
            .lbrack => s.index_access(left),
            .dot => s.member_access(left),
        };
    }
    fn literal(s: *Parser) !ast.AstNode {
        const val = s.l.literal;
        try s.consume(.identifer);
        return ast.AstNode{ .Literal = .{ .type = {}, .value = val } };
    }
    fn null_literal(s: *Parser) !ast.AstNode {
        try s.consume(.null);
        return ast.AstNode{};
    }
    fn variable(s: *Parser) !ast.AstNode {
        const name = try s.consume(.identifier);
        return ast.AstNode{ .Variable = .{ .name = name } };
    }
    fn grouping(s: *Parser) !ast.AstNode {
        try s.consume(.lparen);
        const expression = s.expr();
        try s.consume(.rparen);
        return ast.AstNode{ .Grouping = .{ .expr = expression } };
    }
    fn unary_op(s: *Parser) !ast.AstNode {
        const op = s.l.tok.?;
        const right = try s.parse_precedence(.unary);
        return ast.AstNode{ .Unary = .{ .operator = op, .right = right } };
    }
    fn binary_op(s: *Parser, left: ast.AstNode) !ast.AstNode {
        const op = s.l.tok.?;
        const precedence = s.get_infix_precedence();
        const right = try s.parse_precedence(precedence); // do stuff here with this
        return ast.AstNode{ .Binary = .{ .left = left, .op = op, .right = right } };
    }
    fn function_call(s: *Parser, left: ast.AstNode) !ast.AstNode {
        try s.consume(.lparen);
        var args = std.ArrayList(ast.AstNode).init(s.allocator);
        errdefer args.deinit();

        while (s.l.tok != .rparen) {
            try args.append(try s.expr());

            if (s.l.tok == .rparen) break;
            try s.consume(.comma);
        }
        try s.consume(.rparen);
        return ast.AstNode{ .FunctionCall = .{ .callee = left, .args = args } };
    }
    fn index_access(s: *Parser, left: ast.AstNode) !ast.AstNode {
        try s.consume(.lbrack);
        const idx = try s.expr();
        try s.consume(.rbrack);
        return ast.AstNode{ .IndexAccess = .{ .index = idx, .object = left } };
    }
    fn member_access(s: *Parser, left: ast.AstNode) !ast.AstNode {
        try s.consume(.dot);
        const access = ast.AstNode{ .MemberAccess = .{ .obj = left, .member = try s.consume(.identifier) } };
        return if (s.l.tok.? == .lparen) {
            s.function_call(access);
        } else {
            access;
        };
    }
    fn get_infix_precedence(s: *Parser) Precedence {
        return switch (s.l.tok.?) {
            .@"or" => .@"or",
            .@"and" => .@"and",
            .eqeq, .bangeq => .equality,
            .lt, .lte, .gt, .gte => .comparison,
            .add, .sub => .term,
            .mul, .div, .mod => .factor,
            .lparen => .call,
            .lbrack, .dot => .primary,
            else => .lowest,
        };
    }
    fn assignment(s: *Parser, left: ast.AstNode) !ast.AstNode {
        try s.consume(.eq);
        return ast.AstNode{ .Assignment = .{ .target = left, .value = try s.expr() } };
    }
    fn consume(s: *Parser, token_type: token.TokenType) ![]const u8 {
        if (s.l.tok.? != token_type) {} // error out
        const lit = s.l.literal orelse "";
        s.l.next_tok();
        return lit;
    }
    fn error_type(s: *Parser, token_type: token.TokenType) bool {}
    fn comptime_param_list(s: *Parser, token_type: token.TokenType) bool {}
};
