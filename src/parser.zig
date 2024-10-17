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
    pub fn parse(s: *Parser) !*const ast.AstNode {
        s.l.next_tok();
        if (s.l.err) |_| {
            // error out
        }
        return s.program();
    }
    fn program(s: *Parser) !*const ast.AstNode {
        var decls = std.ArrayList(*const ast.AstNode).init(s.allocator);
        try decls.append(try s.module_declaration());
        var pub_decls = std.ArrayList(*const ast.AstNode).init(s.allocator);
        try pub_decls.append(try s.module_declaration());

        while (s.l.tok.? != .eof) {
            if (s.l.tok.? == .@"pub") {
                _ = try s.consume(.@"pub");
                try pub_decls.append(try s.decl());
            } else {
                try decls.append(try s.decl());
            }
        }
        return &ast.AstNode{ .Program = .{ .declarations = decls.toOwnedSlice(), .pub_declarations = pub_decls.toOwnedSlice() } };
    }
    fn module_declaration(s: *Parser) !*const ast.AstNode {
        _ = try s.consume(.module);
        const name = try s.consume(.string);
        return &ast.AstNode{ .ModuleDeclaration = .{ .name = name } };
    }
    fn decl(s: *Parser) !*const ast.AstNode {
        return switch (s.l.tok.?) {
            .use => s.use(),
            .@"struct" => s.struct_decl(),
            .@"enum" => s.enum_decl(),
            .@"error" => s.error_decl(),
            .type => s.type_decl(),
            else => s.var_decl(),
        };
    }
    fn use(s: *Parser) !*const ast.AstNode {
        _ = try s.consume(.use);
        var imports = std.ArrayList(struct { import: []const u8, alias: ?[]const u8 }).init(s.allocator);
        errdefer imports.deinit();

        if (s.l.tok.? == .lbrace) {
            _ = try s.consume(.lbrace);
            while (s.l.tok.? != .rbrace) {
                const import = try s.consume(.string);
                const alias: ?[]const u8 = if (s.l.tok.? == .identifier) {
                    (try s.consume(.identifier));
                } else {
                    null;
                };
                _ = try imports.append(.{ .import = import, .alias = alias });
                if (s.l.tok.? != .rbrace) {
                    _ = try s.consume(.comma);
                }
            }
        } else if (s.l.tok.? == .string) {
            const import = try s.consume(.string);
            const alias: ?[]const u8 = if (s.l.tok.? == .identifier) {
                _ = try s.consume(.identifier);
            } else {
                null;
            };
            try imports.append(.{ .import = import, .alias = alias });
        } else {} // error out
        _ = try s.consume(.semicolon);

        return &ast.AstNode{ .UseDeclaration = .{ .modules = imports.toOwnedSlice() } };
    }
    fn struct_decl(s: *Parser) !*const ast.AstNode {
        _ = try s.consume(.@"struct");
        const name = try s.consume(.identifier);
        var members = std.ArrayList(ast.AstNode).init(s.allocator);
        errdefer members.deinit();
        _ = try s.consume(.lbrace);
        while (s.l.tok.? != .rbrace) {
            try members.append(try s.struct_member());
        }
        _ = try s.consume(.rbrace);
        return &ast.AstNode{ .StructDefinition = .{ .name = name, .genericParams = null, .members = members } };
    }
    fn struct_member(s: *Parser) !*const ast.AstNode {
        const member_type = try s.type_expr();
        const name = try s.consume(.identifier);
        const member = if (s.l.tok == .lparen) {
            try s.struct_method(member_type, name);
        } else {
            try s.struct_fields();
        };
        return &member;
    }
    fn struct_fields(s: *Parser, member_type: ast.AstNode, name: []const u8) !*const ast.AstNode {
        var fields = std.ArrayList([]const u8).init(s.allocator);
        errdefer fields.deinit();
        try fields.append(name);
        while (s.l.tok.? != .semicolon) {
            try fields.append(try s.consume(.identifier));
            _ = try s.consume(.comma);
        }
        return &ast.AstNode{ .StructField = .{ .field_type = member_type, .name = fields.toOwnedSlice() } };
    }
    fn struct_method(s: *Parser, method_type: *const ast.AstNode, name: []const u8) !*const ast.AstNode {
        _ = try s.consume(.lparen);
        const params = try s.method_param_list();
        _ = try s.consume(.rparen);
        const body: ast.AstNode = if (s.l.tok.? == .arrow) {
            try s.expr();
        } else if (s.l.tok.? == .lbrace) {
            try s.block();
        };
        return &ast.AstNode{ .StructMethod = .{ .return_type = method_type, .name = name, .parameters = params, .body = body } };
    }
    fn type_expr(s: *Parser) !*const ast.AstNode {
        var root_type = ast.AstNode{ .Type = .{ .type = try s.consume(.identifier) } };
        while (true) {
            switch (s.l.tok.?) {
                .lbrack => {
                    _ = try s.consume(.lbrack);
                    _ = try s.consume(.rbrack);
                    root_type = ast.AstNode{ .ArrayType = .{ .type = &root_type } };
                },
                .mul => {
                    _ = try s.consume(.mul);
                    root_type = ast.AstNode{ .PointerType = .{ .type = &root_type } };
                },
                .question => {
                    _ = try s.consume(.question);
                    root_type = ast.AstNode{ .NullableType = .{ .type = &root_type } };
                },
                else => break,
            }
        }
        if (s.l.tok.? == .bang) {
            root_type = ast.AstNode{ .ErrorType = .{ .core_type = &root_type, .error_type = try s.consume(.identifier) } };
        }
        return &root_type;
    }
    fn method_param_list(s: *Parser) ![]*const ast.AstNode {
        var params = std.ArrayList(*const ast.AstNode).init(s.allocator);
        errdefer params.deinit();
        while (s.l.tok.? != .rparen) {
            const t = try s.type_expr();
            const name = try s.consume(.identifier);
            if (s.l.tok.? == .rparen) {
                break;
            }
            _ = try s.consume(.comma);
            try params.append(&ast.AstNode{ .Parameter = .{ .mutable = false, .isComptime = false, .paramType = t, .name = name } });
        }
        return try params.toOwnedSlice();
    }
    fn enum_decl(s: *Parser) !*const ast.AstNode {
        _ = try s.consume(.@"enum");
        const name = try s.consume(.identifier);
        _ = try s.consume(.lbrack);
        var enum_members = std.ArrayList(*ast.AstNode).init(s.allocator);
        while (s.l.tok.? != .rbrack) {
            if (s.l.tok.? == .identifier) {
                const first = try s.consume(.identifier);
                try enum_members.append(if (s.l.tok.? == .identifier) {
                    &ast.AstNode{ .EnumVariant = .{ .variant_type = &.{ .Type = .{ .type = first } }, .variant = try s.consume(.identifier) } };
                } else {
                    &ast.AstNode{ .EnumVariant = .{ .variant_type = null, .variant = first } };
                });
            } else if (s.l.tok.? == .comma) {
                // we error here because there was no variant supplied
            } else {
                const enum_type = try s.type_expr();
                try enum_members.append(ast.AstNode{ .EnumVariant = .{ .variant_type = enum_type, .variant = try s.consume(.identifier) } });
            }
            if (s.l.tok.? == .rbrack) break;
            _ = try s.consume(.comma);
        }
        return ast.AstNode{ .EnumDefinition = .{ .name = name, .variants = enum_members } };
    }
    fn error_decl(s: *Parser) !*const ast.AstNode {
        _ = try s.consume(.@"error");
        const name = try s.consume(.identifier);
        _ = try s.consume(.lbrack);
        var error_members = std.ArrayList(ast.AstNode).init(s.allocator);
        while (s.l.tok.? != .rbrack) {
            if (s.l.tok.? == .identifier) {
                const first = try s.consume(.identifier);
                try error_members.append(if (s.l.tok.? == .identifier) {
                    &ast.AstNode{ .ErrorVariant = .{ .variant_type = &.{ .Type = .{ .type = first } }, .variant = try s.consume(.identifier) } };
                } else {
                    &ast.AstNode{ .ErrorVariant = .{ .variant_type = null, .variant = first } };
                });
            } else if (s.l.tok.? == .comma) {
                // we error here because there was no variant supplied
            } else {
                const error_variant_type = try s.type_expr();
                try error_members.append(ast.AstNode{ .ErrorVariant = .{ .variant_type = error_variant_type, .variant = try s.consume(.identifier) } });
            }
            if (s.l.tok.? == .rbrack) break;
            s.consume(.comma);
        }
        return ast.AstNode{ .errorDefinition = .{ .name = name, .variants = error_members } };
    }
    fn type_decl(s: *Parser) !*const ast.AstNode {
        _ = try s.consume(.type);
        const name = try s.consume(.identifier);
        _ = try s.consume(.eq);
        return &ast.AstNode{ .TypeDefinition = .{ .name = name, .aliasedType = try s.type_expr() } };
    }
    fn function_decl(s: *Parser, fn_type: *const ast.AstNode, name: []const u8) !*const ast.AstNode {
        var params = std.ArrayList(ast.AstNode).init(s.allocator);
        errdefer params.deinit();
        _ = try s.consume(.lparen);
        while (s.l.tok.? != .rparen) {
            const paramType = try s.type_expr();
            const param_name = try s.consume(.identifier);
            try params.append(ast.AstNode{ .Parameter = .{ .paramType = paramType, .name = param_name } });
            if (s.l.tok.? == .rparen) break;
            _ = try s.consume(.comma);
        }
        _ = try s.consume(.rparen);
        // find body here
        var body: ast.AstNode = undefined;
        if (s.l.tok.? == .arrow) {
            body = s.expr();
        } else if (s.l.tok.? == .lbrace) {
            body = s.block();
        } else {
            // error here
        }
        return ast.AstNode{ .FunctionDefinition = .{ .returnType = fn_type, .name = name, .parameters = params.toOwnedSlice(), .body = body } };
    }
    fn block(s: *Parser) !*const ast.AstNode {
        _ = try s.consume(.lparen);
        var stmts = std.ArrayList(ast.AstNode).init(s.allocator);
        errdefer stmts.deinit();
        while (s.l.tok.? != .rbrace) {
            try stmts.append(try s.stmt());
        }
        _ = try s.consume(.rparen);
        return ast.AstNode{ .Block = .{ .statements = stmts } };
    }
    fn stmt(s: *Parser) !*const ast.AstNode {
        const item = switch (s.l.tok.?) {
            .@"if" => try s.if_stmt(),
            .@"while" => try s.while_stmt(),
            .@"for" => try s.for_stmt(),
            .match => try s.match_stmt(),
            .@"inline" => try s.inline_stmt(),
            .@"struct" => try s.struct_decl(),
            .@"enum" => try s.enum_decl(),
            .@"error" => try s.error_decl(),
            .lbrace => try s.block(),
            .type => try s.type_decl(),
            else => try s.var_decl(),
        };
        _ = try s.consume(.semicolon);
        return item;
    }
    fn if_stmt(s: *Parser) !*const ast.AstNode {
        _ = try s.consume(.@"if");
        var var_capture: ?ast.AstNode = null;
        var else_branch: ?ast.AstNode = null;
        const condition = try s.expr();
        if (s.l.tok.? == .@"or") {
            var_capture = try s.capture();
        }
        const then_branch = try s.stmt();
        if (s.l.tok.? == .@"else") {
            _ = try s.consume(.@"else");
            else_branch = try s.stmt();
        }
        return ast.AstNode{ .IfStatement = .{ .condition = condition, .capture = var_capture, .thenBranch = then_branch, .elseBranch = else_branch } };
    }
    fn capture(s: *Parser) !*const ast.AstNode {
        _ = try s.consume(.@"or");
        const captured = try s.consume(.identifier);
        _ = try s.consume(.@"or");
        return ast.AstNode{ .Capture = .{ .captured_var = captured } };
    }
    fn while_stmt(s: *Parser) !*const ast.AstNode {
        var inline_while = false;
        if (s.l.tok.? == .@"inline") {
            inline_while = true;
            _ = try s.consume(.@"inline");
        }
        _ = try s.consume(.@"while");
        const while_condition = try s.condition();
        const body = try s.stmt();
        return ast.AstNode{ .WhileStatement = .{ .inlineWhile = inline_while, .condition = while_condition, .body = body } };
    }
    fn for_stmt(s: *Parser) !*const ast.AstNode {
        var inline_for = false;
        if (s.l.tok.? == .@"inline") {
            inline_for = true;
            _ = try s.consume(.@"inline");
        }
        _ = try s.consume(.@"for");
        const iterable = try s.expr();
        const loop_var = try s.capture();
        const body = try s.stmt();
        return ast.AstNode{ .ForStatement = .{ .inlineFor = inline_for, .iterable = iterable, .loopVar = loop_var, .body = body } };
    }
    fn range_expr(s: *Parser) !*const ast.AstNode {
        const start = ast.AstNode{ .Literal = .{ .type = .int, .value = try s.consume(.int) } };
        _ = try s.consume(.dotdot);
        const end = ast.AstNode{ .Literal = .{ .type = .int, .value = try s.consume(.int) } };
        return ast.AstNode{ .Range = .{ .start = start, .end = end } };
    }
    fn match_stmt(s: *Parser) !*const ast.AstNode {
        _ = try s.consume(.match);
        const value = try s.expr();
        _ = try s.consume(.lbrack);
        var arms = std.ArrayList(ast.AstNode).init(s.allocator);
        errdefer arms.deinit();
        while (s.l.tok.? != .rbrack) {
            try arms.append(try s.match_arm());
            if (s.l.tok.? == .rbrack) break;
            _ = try s.consume(.comma);
        }
        _ = try s.consume(.rbrack);
        return ast.AstNode{ .MatchStatement = .{ .value = value, .arms = arms } };
    }
    fn match_arm(s: *Parser) !*const ast.AstNode {
        var exprs = std.ArrayList(ast.AstNode).init(s.allocator);
        errdefer exprs.deinit();
        if (s.l.tok.? == .underscore) {
            _ = try s.consume(.underscore);
            if (s.l.tok.? == .@"if") {} else {}
        } else {
            while (s.l.tok.? != .colon) {
                var first = s.expr();
                if (s.l.tok.? == .dotdot) {
                    first = s.range_pattern(first);
                }
                if (s.l.tok.? == .colon) break;
                try exprs.append(first);
                _ = try s.consume(.comma);
            }
        }
        _ = try s.consume(.colon);
        const body = if (s.l.tok.? == .lbrace) {
            try s.block();
        } else {
            try s.expr();
        };
        return ast.AstNode{ .MatchArm = .{ .pattern = exprs, .body = body } };
    }
    fn range_pattern(s: *Parser, first: ast.AstNode) !*const ast.AstNode {
        _ = try s.consume(.dotdot);
        const last = try s.expr();
        return ast.AstNode{ .Range = .{ .start = first, .end = last } };
    }
    fn defer_stmt(s: *Parser) !*const ast.AstNode {
        _ = try s.consume(.@"defer");
        if (s.l.tok.? == .@"or") {} // we have an error capture
    }
    fn inline_stmt(s: *Parser) !*const ast.AstNode {
        _ = try s.consume(.@"inline");
        switch (s.l.tok.?) {
            .@"for" => {},
            .identifier => {},
            else => {
                // error out as this cannot be inlined
            },
        }
    }
    fn var_decl(s: *Parser) !*const ast.AstNode {
        var mut = false;
        if (s.l.tok.? == .mut) {
            mut = true;
            _ = try s.consume(.mut);
        }
        const var_type = try s.type_decl();
        if (s.l.tok.? == .semicolon) return &ast.AstNode{ .ExpressionStatement = .{ .expression = var_type } };
        const var_name = try s.consume(.identifier);
        var initializer: ?ast.AstNode = null;
        switch (s.l.tok.?) {
            .lparen => {
                if (mut) {
                    // error out
                }
                return try s.function_decl(var_type, var_name);
            },
            .eq => {
                _ = try s.consume(.eq);
                initializer = try s.expr();
                _ = try s.consume(.semicolon);
            },
            .semicolon => {
                if (!mut) {
                    // error out
                }
            },
            else => {
                // error out
            },
        }
        return ast.AstNode{ .VariableDeclaration = .{ .mutable = mut, .varType = var_type, .name = var_name, .initializer = initializer } };
    }
    fn expr(s: *Parser) !*const ast.AstNode {
        return try s.parse_precedence(.assignment);
    }
    fn parse_precedence(s: *Parser, precedence: Precedence) !*const ast.AstNode {
        var left = s.prefix();
        while (precedence <= s.get_infix_precedence()) {
            left = try s.infix();
        }
        return left;
    }
    fn prefix(s: *Parser) !*const ast.AstNode {
        return switch (s.l.tok.?) {
            .integer, .float => s.literal(),
            .string => s.string_literal(),
            .true, .false => s.bool_literal(),
            .null => s.null_literal(),
            .identifier => s.variable(),
            .lparen => s.grouping(),
            .minus, .bang, .mul => s.unary_op(),
            else => ast.AstNode{ .StatementExpression = .{ .statement = try s.stmt() } },
        };
    }
    fn infix(s: *Parser, left: ast.AstNode) !*const ast.AstNode {
        return switch (s.l.tok) {
            .add, .sub, .mul, .div, .mod => s.binary_expr(left),
            .eqeq, .bangeq, .lt, .lte, .gt, .gte => s.binary_expr(left),
            .@"and", .@"or" => s.logical_operator(left),
            .lparen => s.function_call(left),
            .lbrack => s.index_access(left),
            .dot => s.member_access(left),
        };
    }
    fn literal(s: *Parser) !*const ast.AstNode {
        const val = try s.consume(.identifer);
        return ast.AstNode{ .Literal = .{ .type = {}, .value = val } };
    }
    fn null_literal(s: *Parser) !*const ast.AstNode {
        _ = try s.consume(.null);
        return ast.AstNode{};
    }
    fn variable(s: *Parser) !*const ast.AstNode {
        const name = try s.consume(.identifier);
        return ast.AstNode{ .Variable = .{ .name = name } };
    }
    fn grouping(s: *Parser) !*const ast.AstNode {
        _ = try s.consume(.lparen);
        const expression = s.expr();
        _ = try s.consume(.rparen);
        return ast.AstNode{ .Grouping = .{ .expr = expression } };
    }
    fn unary_op(s: *Parser) !*const ast.AstNode {
        const op = s.l.tok.?;
        const right = try s.parse_precedence(.unary);
        return ast.AstNode{ .Unary = .{ .operator = op, .right = right } };
    }
    fn binary_op(s: *Parser, left: ast.AstNode) !*const ast.AstNode {
        const op = s.l.tok.?;
        const precedence = s.get_infix_precedence();
        const right = try s.parse_precedence(precedence); // do stuff here with this
        return ast.AstNode{ .Binary = .{ .left = left, .op = op, .right = right } };
    }
    fn function_call(s: *Parser, left: ast.AstNode) !*const ast.AstNode {
        _ = try s.consume(.lparen);
        var args = std.ArrayList(ast.AstNode).init(s.allocator);
        errdefer args.deinit();

        while (s.l.tok != .rparen) {
            try args.append(try s.expr());

            if (s.l.tok == .rparen) break;
            _ = try s.consume(.comma);
        }
        _ = try s.consume(.rparen);
        return ast.AstNode{ .FunctionCall = .{ .callee = left, .args = args } };
    }
    fn index_access(s: *Parser, left: ast.AstNode) !*const ast.AstNode {
        _ = try s.consume(.lbrack);
        const idx = try s.expr();
        _ = try s.consume(.rbrack);
        return ast.AstNode{ .IndexAccess = .{ .index = idx, .object = left } };
    }
    fn member_access(s: *Parser, left: ast.AstNode) !*const ast.AstNode {
        _ = try s.consume(.dot);
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
    fn assignment(s: *Parser, left: ast.AstNode) !*const ast.AstNode {
        _ = try s.consume(.eq);
        return ast.AstNode{ .Assignment = .{ .target = left, .value = try s.expr() } };
    }
    fn consume(s: *Parser, token_type: token.TokenType) ![]const u8 {
        if (s.l.tok.? != token_type) {} // error out
        const lit = s.l.literal orelse "";
        s.l.next_tok();
        return lit;
    }
};
