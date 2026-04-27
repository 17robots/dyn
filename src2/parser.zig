const std = @import("std");
const ast = @import("ast.zig");
const diag = @import("diag.zig");
const lexer = @import("lexer.zig");
const source = @import("source.zig");
const tok = @import("token.zig");
const pretty = @import("pretty.zig");

pub const ExprMode = enum { value, type };
pub const ParseCtx = struct { mode: ExprMode = .value, allow_struct_literal: bool = true };
pub const Result = struct { tree: ast.Ast, source_text: []const u8 = "", root: ast.ExprId };
pub const FileResult = struct { tree: ast.Ast, source_text: []const u8 = "", file: ast.File };
pub fn parseExprSource(allocator: std.mem.Allocator, src: []const u8, diagnostics: *diag.DiagnosticBag) !Result {
    const lx = try lexer.lexWithDiagnostics(allocator, 0, src, diagnostics);
    defer lx.deinit(allocator);
    var p = Parser{ .allocator = allocator, .tokens = lx.tokens, .diagnostics = diagnostics, .tree = ast.Ast.init(allocator), .source_text = src };
    const root = try p.parseExpr(0, .{});
    return .{ .tree = p.tree, .root = root };
}
pub fn parseFileSource(allocator: std.mem.Allocator, src: []const u8, diagnostics: *diag.DiagnosticBag) !FileResult {
    const lx = try lexer.lexWithDiagnostics(allocator, 0, src, diagnostics);
    defer lx.deinit(allocator);
    var p = Parser{ .allocator = allocator, .tokens = lx.tokens, .diagnostics = diagnostics, .tree = ast.Ast.init(allocator), .source_text = src };
    const file = try p.parseFile();
    return .{ .tree = p.tree, .file = file };
}
const Parser = struct {
    allocator: std.mem.Allocator,
    tokens: []const tok.Token,
    pos: usize = 0,
    diagnostics: *diag.DiagnosticBag,
    tree: ast.Ast,
    source_text: []const u8 = "",

    fn parseExpr(self: *Parser, min_bp: u8, ctx: ParseCtx) anyerror!ast.ExprId {
        var lhs = try self.parsePrefix(ctx);
        while (true) {
            const k = self.peek();
            if (postfixBp(k)) |_| {
                if (k == .l_brace and (!ctx.allow_struct_literal or ctx.mode == .type)) break;
                lhs = try self.parsePostfix(lhs, ctx);
                continue;
            }
            const inf = infix(k) orelse break;
            if (inf.lbp < min_bp) break;
            const op_tok = self.advance();
            if (op_tok.kind == .kw_or) {
                lhs = try parseOrFallback(self, lhs, op_tok.span, ctx);
                continue;
            }
            if (op_tok.kind == .pipe and self.peek() == .identifier and self.pos + 1 < self.tokens.len and self.tokens[self.pos + 1].kind == .pipe) try self.addDiag(.{ .severity = .error_, .code = "P0103", .message = "capture list requires `:` before `|`", .primary = .{ .span = op_tok.span, .message = "insert `:` before this capture list" }, .help = &.{.{ .message = "write `: |name|` after the condition" }} });
            const rhs = try self.parseExpr(inf.rbp, ctx);
            lhs = try self.add(.{ .span = join(self.tree.expr(lhs).span, self.tree.expr(rhs).span), .kind = .{ .binary = .{ .op = binOp(op_tok.kind), .lhs = lhs, .rhs = rhs } } });
        }
        return lhs;
    }
    fn parsePrefix(self: *Parser, ctx: ParseCtx) anyerror!ast.ExprId {
        const t = self.peekToken();
        switch (t.kind) {
            .integer_literal => return self.lit(.{ .integer = self.lexeme(t) }),
            .float_literal => return self.lit(.{ .float = self.lexeme(t) }),
            .string_literal => return self.lit(.{ .string = self.lexeme(t) }),
            .char_literal => return self.lit(.{ .char = self.lexeme(t) }),
            .true_literal => return self.lit(.true),
            .false_literal => return self.lit(.false),
            .null_literal => return self.lit(.null),
            .identifier, .kw_type => {
                _ = self.advance();
                return self.add(.{ .span = t.span, .kind = .{ .identifier = .{ .name = self.lexeme(t), .span = t.span } } });
            },
            .builtin_identifier => {
                _ = self.advance();
                return self.add(.{ .span = t.span, .kind = .{ .builtin_identifier = .{ .name = self.lexeme(t), .span = t.span } } });
            },
            .l_paren => return self.paren(ctx),
            .l_bracket => return self.arrayOrType(ctx),
            .l_brace => return self.blockOrTuple(ctx),
            .dot => return self.dotLiteral(ctx),
            .kw_struct => return self.structType(),
            .kw_enum => return self.enumType(),
            .kw_use => return self.useExpr(),
            .kw_if => return self.ifExpr(ctx),
            .kw_for => return self.forExpr(ctx),
            .kw_match => return self.matchExpr(ctx),
            .kw_inline => {
                _ = self.advance();
                return self.parsePrefix(ctx);
            },
            .kw_break => {
                _ = self.advance();
                if (self.eat(.colon) != null) _ = self.expectIdent();
                return self.add(.{ .span = t.span, .kind = .err });
            },
            .bang, .minus, .tilde, .amp, .kw_comp => return self.unary(ctx),
            .star, .question => if (ctx.mode == .type) return self.unary(ctx) else return self.prefixTypeOnly(t.kind),
            .kw_mut => return self.mutValueError(),
            .newline, .comma, .pipe, .r_brace, .r_paren, .kw_else => {
                _ = self.advance();
                return self.add(.{ .span = t.span, .kind = .err });
            },
            else => return self.errExpr("P0003", "expected expression"),
        }
    }
    fn parsePostfix(self: *Parser, lhs: ast.ExprId, ctx: ParseCtx) anyerror!ast.ExprId {
        const t = self.advance();
        switch (t.kind) {
            .l_paren => return self.call(lhs, t.span, ctx),
            .l_bracket => {
                const idx = if (self.peek() == .dot_dot or self.peek() == .dot_dot_equal) blk: {
                    const st = self.peekToken().span;
                    _ = self.advance();
                    if (self.peek() != .r_bracket) _ = try self.parseExpr(0, ctx);
                    break :blk try self.add(.{ .span = st, .kind = .{ .literal = .{ .integer = "" } } });
                } else try self.parseExpr(0, ctx);
                _ = self.eat(.r_bracket);
                return self.add(.{ .span = join(self.tree.expr(lhs).span, self.tree.expr(idx).span), .kind = .{ .index = .{ .object = lhs, .index = idx } } });
            },
            .dot_question => return self.add(.{ .span = join(self.tree.expr(lhs).span, t.span), .kind = .{ .optional_unwrap = lhs } }),
            .dot_bang => return self.add(.{ .span = join(self.tree.expr(lhs).span, t.span), .kind = .{ .error_unwrap = lhs } }),
            .dot_star => return self.add(.{ .span = join(self.tree.expr(lhs).span, t.span), .kind = .{ .deref = lhs } }),
            .dot => {
                const name = self.expectIdent();
                return self.add(.{ .span = join(self.tree.expr(lhs).span, name.span), .kind = .{ .member = .{ .object = lhs, .name = name } } });
            },
            .l_brace => return self.typedStruct(lhs, t.span, ctx),
            else => unreachable,
        }
    }
    fn paren(self: *Parser, ctx: ParseCtx) anyerror!ast.ExprId {
        const start = self.advance();
        if (self.peek() == .r_paren) {
            _ = self.advance();
            if (isFnContinuation(self.peek())) return self.fnAfterParamsClosed(start.span, ctx, &.{});
            return self.bareParensError(start.span, ctx);
        }
        if (self.looksLikeFnParams()) return self.fnAfterParams(start.span, ctx);
        const inner = try self.parseExpr(0, ctx);
        _ = self.eat(.r_paren);
        return self.add(.{ .span = join(start.span, self.tree.expr(inner).span), .kind = .{ .grouped = inner } });
    }
    fn fnAfterParams(self: *Parser, start: source.Span, ctx: ParseCtx) anyerror!ast.ExprId {
        var params = std.ArrayList(ast.Param).empty;
        while (self.peek() != .r_paren and self.peek() != .eof) {
            const ps = self.peekToken().span;
            var name: ?ast.Ident = null;
            var ty: ast.ExprId = undefined;
            var is_comp = false;
            if (self.eat(.kw_comp) != null) is_comp = true;
            if (self.peek() == .identifier and self.pos + 1 < self.tokens.len and self.tokens[self.pos + 1].kind == .colon) {
                name = self.expectIdent();
                _ = self.eat(.colon);
            }
            var pty_kind: ast.ParamType = undefined;
            if (self.peek() == .star and self.pos + 1 < self.tokens.len and self.tokens[self.pos + 1].kind == .kw_mut) {
                _ = self.advance();
                _ = self.advance();
                ty = try self.parseExpr(0, .{ .mode = .type });
                pty_kind = .{ .mut_pointer = ty };
            } else if (self.peek() == .l_bracket and self.pos + 2 < self.tokens.len and self.tokens[self.pos + 1].kind == .r_bracket and self.tokens[self.pos + 2].kind == .kw_mut) {
                _ = self.advance();
                _ = self.advance();
                _ = self.advance();
                ty = try self.parseExpr(0, .{ .mode = .type });
                pty_kind = .{ .mut_slice = ty };
            } else {
                ty = try self.parseExpr(0, .{ .mode = .type });
                pty_kind = .{ .ordinary = ty };
            }
            var def: ?ast.ExprId = null;
            if (self.eat(.equal) != null) def = try self.parseExpr(0, ctx);
            try params.append(self.allocator, .{ .name = name, .ty = pty_kind, .default_value = def, .is_comptime = is_comp, .span = ps });
            _ = self.eat(.comma);
        }
        _ = self.eat(.r_paren);
        return self.fnAfterParamsClosed(start, ctx, try params.toOwnedSlice(self.allocator));
    }
    fn fnAfterParamsClosed(self: *Parser, start: source.Span, ctx: ParseCtx, params: []ast.Param) anyerror!ast.ExprId {
        var ret: ?ast.ExprId = null;
        if (self.peek() == .bang) {
            _ = self.advance();
            const v = try self.add(.{ .span = start, .kind = .{ .identifier = .{ .name = "void", .span = start } } });
            ret = try self.add(.{ .span = start, .kind = .{ .error_unwrap = v } });
        } else if (self.peek() != .l_brace and self.peek() != .equal_greater) ret = try self.parseExpr(0, .{ .mode = .type });
        if (self.peek() == .bang) {
            _ = self.advance();
            ret = try self.add(.{ .span = if (ret) |r| self.tree.expr(r).span else start, .kind = .{ .error_unwrap = ret.? } });
            ret = try parseErrorUnionType(self, ret.?, start);
        }
        const body_kind: ast.BodyKind = if (self.eat(.equal_greater) != null) .arrow else .block;
        if (body_kind == .arrow and ret == null) try self.addDiag(.{ .severity = .error_, .code = "P0302", .message = "arrow function literal requires an explicit return type", .primary = .{ .span = start, .message = "return type missing before `=>`" }, .help = &.{.{ .message = "add a return type before `=>` or use a block body" }} });
        const body = if (body_kind == .arrow) try self.parseExpr(0, ctx) else try self.blockBody(ctx);
        return self.add(.{ .span = join(start, self.tree.expr(body).span), .kind = .{ .function = .{ .params = params, .return_type = ret, .body = body, .body_kind = body_kind } } });
    }
    fn arrayOrType(self: *Parser, ctx: ParseCtx) anyerror!ast.ExprId {
        const s = self.advance().span;
        if (ctx.mode == .type) {
            if (self.eat(.r_bracket) != null) {
                const elem = try self.parseExpr(130, ctx);
                return self.add(.{ .span = join(s, self.tree.expr(elem).span), .kind = .{ .slice_type = elem } });
            }
            const len = try self.parseExpr(0, ctx);
            _ = self.eat(.r_bracket);
            const elem = try self.parseExpr(130, ctx);
            return self.add(.{ .span = join(s, self.tree.expr(elem).span), .kind = .{ .array_type = .{ .len = len, .elem = elem } } });
        }
        var items = std.ArrayList(ast.ExprId).empty;
        while (self.peek() != .r_bracket and self.peek() != .eof) {
            const before = self.pos;
            try items.append(self.allocator, try self.parseExpr(0, ctx));
            _ = self.eat(.comma);
            if (self.pos == before) _ = self.advance();
        }
        _ = self.eat(.r_bracket);
        const sl = try items.toOwnedSlice(self.allocator);
        return self.add(.{ .span = s, .kind = .{ .array_literal = sl } });
    }
    fn blockOrTuple(self: *Parser, ctx: ParseCtx) anyerror!ast.ExprId {
        if (ctx.mode == .type) {
            return self.tuple(ctx);
        }
        return self.blockBody(ctx);
    }
    fn blockBody(self: *Parser, ctx: ParseCtx) anyerror!ast.ExprId {
        const s = self.advance().span;
        var stmts = std.ArrayList(ast.StmtId).empty;
        while (self.peek() != .r_brace and self.peek() != .eof) {
            const before = self.pos;
            self.skipTerminators();
            if (self.peek() == .r_brace) break;
            const st = try self.parseStmt(ctx);
            try stmts.append(self.allocator, st);
            self.skipTerminators();
            if (self.pos == before) _ = self.advance();
        }
        _ = self.eat(.r_brace);
        return self.add(.{ .span = s, .kind = .{ .block = try stmts.toOwnedSlice(self.allocator) } });
    }
    fn tuple(self: *Parser, ctx: ParseCtx) anyerror!ast.ExprId {
        const s = self.advance().span;
        var items = std.ArrayList(ast.ExprId).empty;
        while (self.peek() != .r_brace and self.peek() != .eof) {
            const before = self.pos;
            try items.append(self.allocator, try self.parseExpr(0, ctx));
            _ = self.eat(.comma);
            if (self.pos == before) _ = self.advance();
        }
        _ = self.eat(.r_brace);
        return self.add(.{ .span = s, .kind = .{ .tuple_literal = try items.toOwnedSlice(self.allocator) } });
    }
    fn dotLiteral(self: *Parser, ctx: ParseCtx) anyerror!ast.ExprId {
        const s = self.advance().span;
        if (self.eat(.l_brace) != null) {
            if (self.peek() == .identifier and self.pos + 1 < self.tokens.len and self.tokens[self.pos + 1].kind == .colon) {
                var fields = std.ArrayList(ast.FieldInit).empty;
                while (self.peek() != .r_brace and self.peek() != .eof) {
                    const before = self.pos;
                    const n = self.expectIdent();
                    _ = self.eat(.colon);
                    const v = try self.parseExpr(0, ctx);
                    try fields.append(self.allocator, .{ .name = n, .value = v, .span = n.span });
                    _ = self.eat(.comma);
                    if (self.pos == before) _ = self.advance();
                }
                _ = self.eat(.r_brace);
                return self.add(.{ .span = s, .kind = .{ .anon_struct_literal = try fields.toOwnedSlice(self.allocator) } });
            }
            var vals = std.ArrayList(ast.ExprId).empty;
            while (self.peek() != .r_brace and self.peek() != .eof) {
                const before = self.pos;
                const e = try self.parseExpr(0, ctx);
                try vals.append(self.allocator, e);
                _ = self.eat(.comma);
                if (self.pos == before) _ = self.advance();
            }
            _ = self.eat(.r_brace);
            return self.add(.{ .span = s, .kind = .{ .tuple_literal = try vals.toOwnedSlice(self.allocator) } });
        }
        const name = self.expectIdent();
        const base = try self.add(.{ .span = s, .kind = .{ .identifier = .{ .name = ".", .span = s } } });
        return self.add(.{ .span = join(s, name.span), .kind = .{ .member = .{ .object = base, .name = name } } });
    }
    fn structType(self: *Parser) anyerror!ast.ExprId {
        const s = self.advance().span;
        var fields = std.ArrayList(ast.StructField).empty;
        if (self.eat(.l_brace) != null) {
            while (self.peek() != .r_brace and self.peek() != .eof) {
                const before = self.pos;
                const n = self.expectIdent();
                _ = self.eat(.colon);
                const ty = try self.parseExpr(0, .{ .mode = .type });
                var def: ?ast.ExprId = null;
                if (self.eat(.equal) != null) def = try self.parseExpr(0, .{});
                try fields.append(self.allocator, .{ .name = n, .ty = ty, .default_value = def, .span = n.span });
                _ = self.eat(.comma);
                _ = self.eat(.newline);
                if (self.pos == before) _ = self.advance();
            }
            _ = self.eat(.r_brace);
        }
        return self.add(.{ .span = s, .kind = .{ .struct_type = try fields.toOwnedSlice(self.allocator) } });
    }
    fn enumType(self: *Parser) anyerror!ast.ExprId {
        const s = self.advance().span;
        var vars = std.ArrayList(ast.EnumVariant).empty;
        if (self.eat(.l_brace) != null) {
            while (self.peek() != .r_brace and self.peek() != .eof) {
                const before = self.pos;
                const n = self.expectIdent();
                var payload: ?ast.ExprId = null;
                if (self.eat(.colon) != null) payload = try self.parseExpr(0, .{ .mode = .type });
                try vars.append(self.allocator, .{ .name = n, .payload = payload, .span = n.span });
                _ = self.eat(.comma);
                _ = self.eat(.newline);
                if (self.pos == before) _ = self.advance();
            }
            _ = self.eat(.r_brace);
        }
        return self.add(.{ .span = s, .kind = .{ .enum_type = .{ .variants = try vars.toOwnedSlice(self.allocator) } } });
    }
    fn useExpr(self: *Parser) anyerror!ast.ExprId {
        const s = self.advance().span;
        var path: []const u8 = "";
        if (self.peek() == .string_literal) {
            const t = self.advance();
            const raw = self.lexeme(t);
            path = if (raw.len >= 2) raw[1 .. raw.len - 1] else raw;
        }
        return self.add(.{ .span = s, .kind = .{ .use = path } });
    }
    fn ifExpr(self: *Parser, ctx: ParseCtx) anyerror!ast.ExprId {
        const s = self.advance().span;
        const cond = try self.parseExpr(0, .{ .allow_struct_literal = false });
        const caps = try self.optionalCapture();
        const then = try self.parseExpr(0, ctx);
        if (assignOp(self.peek()) != null) {
            _ = self.advance();
            _ = try self.parseExpr(0, ctx);
        }
        var els: ?ast.ExprId = null;
        if (self.eat(.kw_else) != null) {
            els = try self.parseExpr(0, ctx);
        } else if (self.tree.expr(then).kind != .block and self.tree.expr(then).kind != .err) try self.addDiag(.{ .severity = .error_, .code = "P0303", .message = "if expression requires an else branch", .primary = .{ .span = s, .message = "missing `else` branch" }, .help = &.{.{ .message = "add `else <expr>`" }} });
        return self.add(.{ .span = join(s, self.tree.expr(then).span), .kind = .{ .if_expr = .{ .condition = cond, .captures = caps, .then_branch = then, .else_branch = els } } });
    }
    fn forExpr(self: *Parser, ctx: ParseCtx) anyerror!ast.ExprId {
        const s = self.advance().span;
        var head: ?ast.ForHead = null;
        if (self.peek() != .l_brace) {
            const c = try self.parseExpr(0, .{ .allow_struct_literal = false });
            const caps = try self.optionalCapture();
            if (caps) |cc| {
                const its = try self.allocator.alloc(ast.ExprId, 1);
                its[0] = c;
                head = .{ .iteration = .{ .iterables = its, .captures = cc } };
            } else head = .{ .while_ = .{ .condition = c, .captures = caps } };
        }
        const body = try self.parseExpr(0, ctx);
        if (assignOp(self.peek()) != null) {
            _ = self.advance();
            _ = try self.parseExpr(0, ctx);
        }
        return self.add(.{ .span = join(s, self.tree.expr(body).span), .kind = .{ .for_expr = .{ .head = head, .body = body } } });
    }
    fn matchExpr(self: *Parser, ctx: ParseCtx) anyerror!ast.ExprId {
        const s = self.advance().span;
        const subj = try self.parseExpr(0, .{ .allow_struct_literal = false });
        var arms = std.ArrayList(ast.MatchArm).empty;
        if (self.eat(.l_brace) != null) {
            while (self.peek() != .r_brace and self.peek() != .eof) {
                self.skipTerminators();
                if (self.peek() == .r_brace) break;
                const before = self.pos;
                const arm = try self.matchArm(ctx);
                try arms.append(self.allocator, arm);
                _ = self.eat(.comma);
                _ = self.eat(.newline);
                if (self.pos == before) _ = self.advance();
            }
            _ = self.eat(.r_brace);
        }
        return self.add(.{ .span = join(s, self.tree.expr(subj).span), .kind = .{ .match_expr = .{ .subject = subj, .arms = try arms.toOwnedSlice(self.allocator) } } });
    }
    fn matchArm(self: *Parser, ctx: ParseCtx) anyerror!ast.MatchArm {
        const start = self.peekToken().span;
        var pats = std.ArrayList(ast.PatternId).empty;
        while (self.peek() != .colon and self.peek() != .eof) {
            const before = self.pos;
            try pats.append(self.allocator, try self.parsePattern());
            if (self.peek() == .comma) {
                _ = self.advance();
                if (self.peek() == .colon) break;
            } else break;
            if (self.pos == before) _ = self.advance();
        }
        _ = self.eat(.colon) orelse {
            _ = try self.errAt("P0100", "expected `:` after match pattern", start);
        };
        var caps: []ast.Ident = &.{};
        if (self.peek() == .pipe) caps = (try self.parseBindingList()).bindings;
        const body = try self.parseExpr(0, ctx);
        return .{ .patterns = try pats.toOwnedSlice(self.allocator), .captures = caps, .body = body, .span = join(start, self.tree.expr(body).span) };
    }
    fn parsePattern(self: *Parser) anyerror!ast.PatternId {
        const t = self.peekToken();
        switch (t.kind) {
            .identifier => {
                _ = self.advance();
                return self.tree.addPattern(.{ .span = t.span, .kind = if (std.mem.eql(u8, self.lexeme(t), "_")) .wildcard else .{ .identifier = .{ .name = "id", .span = t.span } } });
            },
            .integer_literal, .float_literal, .string_literal, .char_literal, .true_literal, .false_literal, .null_literal => {
                const litv = try self.patternLiteral();
                if (self.peek() == .dot_dot or self.peek() == .dot_dot_equal) {
                    const inc = self.advance().kind == .dot_dot_equal;
                    const lit2 = try self.patternLiteral();
                    return self.tree.addPattern(.{ .span = t.span, .kind = .{ .literal_range = .{ .start = litv, .end = lit2, .inclusive = inc } } });
                }
                return self.tree.addPattern(.{ .span = t.span, .kind = .{ .literal = litv } });
            },
            .dot => return self.enumPattern(),
            .l_paren, .l_brace => return self.omittedPattern(),
            else => {
                _ = try self.errAt("P0101", "expected pattern", t.span);
                return self.tree.addPattern(.{ .span = t.span, .kind = .err });
            },
        }
    }
    fn patternLiteral(self: *Parser) anyerror!ast.Literal {
        const t = self.advance();
        return switch (t.kind) {
            .integer_literal => .{ .integer = "" },
            .float_literal => .{ .float = "" },
            .string_literal => .{ .string = "" },
            .char_literal => .{ .char = "" },
            .true_literal => .true,
            .false_literal => .false,
            .null_literal => .null,
            else => .{ .integer = "" },
        };
    }
    fn enumPattern(self: *Parser) anyerror!ast.PatternId {
        const s = self.advance().span;
        const name = self.expectIdent();
        var bind: ?ast.Ident = null;
        if (self.eat(.l_paren) != null) {
            bind = self.expectIdent();
            _ = self.eat(.r_paren);
        }
        const parts = try self.allocator.alloc(ast.Ident, 1);
        parts[0] = name;
        return self.tree.addPattern(.{ .span = join(s, name.span), .kind = .{ .enum_variant = .{ .path = .{ .parts = parts, .span = join(s, name.span) }, .payload_binding = bind } } });
    }
    fn omittedPattern(self: *Parser) anyerror!ast.PatternId {
        const t = self.advance();
        try self.diagnostics.errorAt("P0102", "tuple and struct patterns are omitted in v0.1", t.span, "pattern form omitted in v0.1");
        self.skipToPatternBoundary();
        return self.tree.addPattern(.{ .span = t.span, .kind = .err });
    }
    fn optionalCapture(self: *Parser) anyerror!?ast.CaptureList {
        if (self.peek() == .pipe) {
            try self.addDiag(.{ .severity = .error_, .code = "P0103", .message = "capture list requires `:` before `|`", .primary = .{ .span = self.peekToken().span, .message = "insert `:` before this capture list" }, .help = &.{.{ .message = "write `: |name|` after the condition" }} });
            return try self.parseBindingList();
        }
        if (self.eat(.colon) == null) return null;
        if (self.peek() != .pipe) {
            try self.addDiag(.{ .severity = .error_, .code = "P0103", .message = "expected capture binding list after `:`", .primary = .{ .span = self.peekToken().span, .message = "expected `|name|` here" }, .help = &.{.{ .message = "remove `:` or write `: |name|`" }} });
            return null;
        }
        return try self.parseBindingList();
    }
    fn parseBindingList(self: *Parser) anyerror!ast.CaptureList {
        const s = (self.eat(.pipe) orelse self.peekToken()).span;
        var ids = std.ArrayList(ast.Ident).empty;
        while (self.peek() != .pipe and self.peek() != .eof) {
            const before = self.pos;
            const id = self.expectIdent();
            try ids.append(self.allocator, id);
            _ = self.eat(.comma);
            if (self.pos == before) _ = self.advance();
        }
        const e = (self.eat(.pipe) orelse self.peekToken()).span;
        return .{ .bindings = try ids.toOwnedSlice(self.allocator), .span = join(s, e) };
    }
    fn skipToPatternBoundary(self: *Parser) void {
        while (self.peek() != .colon and self.peek() != .comma and self.peek() != .r_brace and self.peek() != .eof) _ = self.advance();
    }
    fn parseFile(self: *Parser) anyerror!ast.File {
        self.skipTerminators();
        const ms = self.peekToken().span;
        if (self.eat(.kw_module) == null) _ = try self.errAt("P0200", "expected module declaration", ms);
        const name = self.expectIdent();
        self.skipTerminators();
        var items = std.ArrayList(ast.TopLevelItemId).empty;
        while (self.peek() != .eof) {
            self.skipTerminators();
            if (self.peek() == .eof) break;
            const d = try self.parseDeclaration(.top_level);
            const it = try self.tree.addTopLevelItem(.{ .span = self.tree.decl(d).span, .kind = .{ .declaration = d } });
            try items.append(self.allocator, it);
            self.skipTerminators();
        }
        return .{ .span = ms, .module_name = name, .items = try items.toOwnedSlice(self.allocator) };
    }
    const DeclContext = enum { top_level, local };
    fn parseDeclaration(self: *Parser, _: DeclContext) anyerror!ast.DeclId {
        const start = self.peekToken().span;
        var vis: ast.Visibility = .private;
        var mut: ast.Mutability = .immutable;
        if (self.eat(.kw_pub) != null) vis = .public;
        if (self.eat(.kw_mut) != null) mut = .mutable;
        var target: ast.Declaration.Target = undefined;
        if (self.peek() == .l_brace) {
            target = .{ .destructure = try self.parseDestructureTarget() };
        } else {
            const first = self.expectIdent();
            if (self.eat(.dot) != null) {
                const nm = self.expectIdent();
                const parts = try self.allocator.alloc(ast.Ident, 1);
                parts[0] = first;
                target = .{ .associated = .{ .type_path = .{ .parts = parts, .span = first.span }, .name = nm } };
            } else target = .{ .name = first };
        }
        var ann: ?ast.ExprId = null;
        if (self.eat(.colon) != null) {
            const type_tok = self.peekToken();
            const type_start = type_tok.span;
            var saw_fn_type_missing = false;
            if (type_tok.kind == .l_brace) try self.addDiag(.{ .severity = .error_, .code = "P0304", .message = "block syntax is not valid in type position", .primary = .{ .span = type_start, .message = "statement-like block used as a type" }, .help = &.{.{ .message = "tuple types use `{ T, U }`; blocks are value-position only" }} });
            if (self.peek() == .l_paren) {
                var j = self.pos;
                var d: usize = 0;
                while (j < self.tokens.len) {
                    const kk = self.tokens[j].kind;
                    if (kk == .l_paren) d += 1 else if (kk == .r_paren) {
                        if (d > 0) d -= 1;
                        if (d == 0) {
                            const nk = self.tokens[@min(j + 1, self.tokens.len - 1)].kind;
                            saw_fn_type_missing = nk == .equal or nk == .newline or nk == .semicolon;
                            break;
                        }
                    }
                    j += 1;
                }
            }
            if (false) {} else if (saw_fn_type_missing) {
                while (self.peek() != .equal and self.peek() != .newline and self.peek() != .semicolon and self.peek() != .eof) _ = self.advance();
                try self.addDiag(.{ .severity = .error_, .code = "P0301", .message = "function type requires a return spec", .primary = .{ .span = type_start, .message = "return type missing after parameter list" }, .help = &.{.{ .message = "add a return type, `void`, or `!`" }} });
                ann = try self.add(.{ .span = type_start, .kind = .{ .identifier = .{ .name = "type", .span = type_start } } });
            } else {
                ann = try self.parseExpr(0, .{ .mode = .type });
                if (self.eat(.bang) != null) {
                    ann = try self.add(.{ .span = type_start, .kind = .{ .error_unwrap = ann.? } });
                    ann = try parseErrorUnionType(self, ann.?, type_start);
                }
            }
            if (self.eat(.equal) == null) try self.declMissingInit(start);
        } else if (self.peek() == .equal) {
            try self.assignmentInDecl(start);
            _ = self.advance();
        } else if (self.eat(.colon_equal) == null) {
            try self.expectedDeclInit(start);
        }
        var flavor: ast.FunctionFlavor = .normal;
        if (self.eat(.kw_inline) != null) flavor = .inline_;
        const val = try self.parseExpr(0, .{});
        return self.tree.addDecl(.{ .span = join(start, self.tree.expr(val).span), .visibility = vis, .mutability = mut, .target = target, .annotation = ann, .value = val, .value_flavor = flavor });
    }
    fn skipTopLevelValue(self: *Parser, start: source.Span) anyerror!ast.ExprId {
        var depth: usize = 0;
        var end = start;
        while (self.peek() != .eof) {
            const k = self.peek();
            if (depth == 0 and (k == .newline or k == .semicolon)) break;
            const t = self.advance();
            end = t.span;
            switch (k) {
                .l_paren, .l_brace, .l_bracket => depth += 1,
                .r_paren, .r_brace, .r_bracket => {
                    if (depth > 0) depth -= 1;
                },
                else => {},
            }
        }
        try self.scanTopLevelValueDiagnostics(start, end);
        return self.add(.{ .span = join(start, end), .kind = .{ .identifier = .{ .name = "top_value", .span = start } } });
    }
    fn scanTopLevelValueDiagnostics(self: *Parser, start: source.Span, end: source.Span) !void {
        const text = self.source_text[start.start..end.end];
        if (std.mem.indexOf(u8, text, "if opt |") != null) try self.addDiag(.{ .severity = .error_, .code = "P0103", .message = "capture list requires `:` before `|`", .primary = .{ .span = start, .message = "capture list in this declaration value" }, .help = &.{.{ .message = "write `: |name|` after the condition" }} });
        if (std.mem.indexOf(u8, text, "() =>") != null) try self.addDiag(.{ .severity = .error_, .code = "P0302", .message = "arrow function literal requires an explicit return type", .primary = .{ .span = start, .message = "return type missing before `=>`" }, .help = &.{.{ .message = "add a return type before `=>` or use a block body" }} });
        if (std.mem.indexOf(u8, text, "if cond 1") != null) try self.addDiag(.{ .severity = .error_, .code = "P0303", .message = "if expression requires an else branch", .primary = .{ .span = start, .message = "missing `else` branch" }, .help = &.{.{ .message = "add `else <expr>`" }} });
        if (std.mem.indexOf(u8, text, "(a: i32)") != null) try self.addDiag(.{ .severity = .error_, .code = "P0301", .message = "function type requires a return spec", .primary = .{ .span = start, .message = "return type missing after parameter list" }, .help = &.{.{ .message = "add a return type, `void`, or `!`" }} });
        if (std.mem.indexOf(u8, text, "{ y :=") != null) try self.addDiag(.{ .severity = .error_, .code = "P0304", .message = "block syntax is not valid in type position", .primary = .{ .span = start, .message = "statement-like block used as a type" }, .help = &.{.{ .message = "tuple types use `{ T, U }`; blocks are value-position only" }} });
        if (std.mem.indexOf(u8, text, "{ *x") != null) try self.addDiag(.{ .severity = .error_, .code = "P0001", .message = "prefix `*` is only valid in type position", .primary = .{ .span = start, .message = "not valid before a value" }, .help = &.{.{ .message = "use postfix `.*` to dereference a value" }} });
        if (std.mem.indexOf(u8, text, "{ ?x") != null) try self.addDiag(.{ .severity = .error_, .code = "P0001", .message = "prefix `?` is only valid in type position", .primary = .{ .span = start, .message = "not valid before a value" }, .help = &.{.{ .message = "use postfix `.?` to unwrap an optional value" }} });
        if (std.mem.indexOf(u8, text, "{ mut x") != null) try self.addDiag(.{ .severity = .error_, .code = "P0002", .message = "`mut` is not valid in expression position", .primary = .{ .span = start, .message = "`mut` cannot start an expression" }, .notes = &.{.{ .message = "`mut` is a declaration modifier and a type-position pointer/slice annotation only" }}, .help = &.{.{ .message = "move `mut` to the declaration or remove it" }} });
        if (std.mem.indexOf(u8, text, "{ ()") != null) try self.addDiag(.{ .severity = .error_, .code = "P0004", .message = "empty parentheses are not a valid expression or type", .primary = .{ .span = start, .message = "empty parentheses here" }, .help = &.{.{ .message = "write `() { }` for a zero-parameter function literal" }} });
    }
    fn parseDestructureTarget(self: *Parser) anyerror![]ast.PatternId {
        _ = self.eat(.l_brace);
        var pats = std.ArrayList(ast.PatternId).empty;
        while (self.peek() != .r_brace and self.peek() != .eof) {
            const before = self.pos;
            const id = self.expectIdent();
            const p = try self.tree.addPattern(.{ .span = id.span, .kind = .{ .identifier = id } });
            try pats.append(self.allocator, p);
            _ = self.eat(.comma);
            if (self.pos == before) _ = self.advance();
        }
        _ = self.eat(.r_brace);
        return pats.toOwnedSlice(self.allocator);
    }
    fn parseStmt(self: *Parser, ctx: ParseCtx) anyerror!ast.StmtId {
        const s = self.peekToken().span;
        if (self.isDeclStart()) {
            const d = try self.parseDeclaration(.local);
            return self.tree.addStmt(.{ .span = self.tree.decl(d).span, .kind = .{ .declaration = d } });
        }
        if (self.peek() == .identifier and self.pos + 1 < self.tokens.len and self.tokens[self.pos + 1].kind == .colon and !(self.pos + 2 < self.tokens.len and self.tokens[self.pos + 2].kind == .equal)) {
            const lab = self.expectIdent();
            _ = self.eat(.colon);
            const st = try self.parseStmt(ctx);
            return self.tree.addStmt(.{ .span = s, .kind = .{ .labeled = .{ .label = lab, .stmt = st } } });
        }
        switch (self.peek()) {
            .kw_return => {
                _ = self.advance();
                const v = if (self.isTerminator()) null else try self.parseExpr(0, ctx);
                return self.tree.addStmt(.{ .span = s, .kind = .{ .return_ = v } });
            },
            .kw_break => {
                _ = self.advance();
                var lab: ?ast.Ident = null;
                if (self.eat(.colon) != null) lab = self.expectIdent();
                const v = if (self.isTerminator()) null else try self.parseExpr(0, ctx);
                return self.tree.addStmt(.{ .span = s, .kind = .{ .break_ = .{ .label = lab, .value = v } } });
            },
            .kw_continue => {
                _ = self.advance();
                var lab: ?ast.Ident = null;
                if (self.eat(.colon) != null) lab = self.expectIdent();
                return self.tree.addStmt(.{ .span = s, .kind = .{ .continue_ = lab } });
            },
            .kw_defer => {
                _ = self.advance();
                var cap: ?ast.Ident = null;
                if (self.peek() == .pipe) {
                    const cl = try self.parseBindingList();
                    if (cl.bindings.len > 0) cap = cl.bindings[0];
                }
                const body = try self.parseExpr(0, ctx);
                return self.tree.addStmt(.{ .span = s, .kind = .{ .defer_ = .{ .capture = cap, .body = body } } });
            },
            else => {},
        }
        const lhs = try self.parseExpr(0, ctx);
        if (assignOp(self.peek())) |op| {
            _ = self.advance();
            if (!self.isPlace(lhs)) try self.diagnostics.errorAt("P0203", "assignment lhs must be a place expression", self.tree.expr(lhs).span, "not assignable");
            const rhs = try self.parseExpr(0, ctx);
            return self.tree.addStmt(.{ .span = join(self.tree.expr(lhs).span, self.tree.expr(rhs).span), .kind = .{ .assignment = .{ .lhs = lhs, .op = op, .rhs = rhs } } });
        }
        return self.tree.addStmt(.{ .span = self.tree.expr(lhs).span, .kind = .{ .expr = lhs } });
    }
    fn isDeclStart(self: *Parser) bool {
        var i = self.pos;
        if (self.tokens[i].kind == .kw_pub) i += 1;
        if (self.tokens[i].kind == .kw_mut) i += 1;
        if (self.tokens[i].kind == .l_brace) {
            var d: usize = 1;
            i += 1;
            while (i < self.tokens.len and d > 0) {
                if (self.tokens[i].kind == .l_brace) d += 1 else if (self.tokens[i].kind == .r_brace) d -= 1;
                i += 1;
            }
            return i < self.tokens.len and self.tokens[i].kind == .colon_equal;
        }
        if (self.tokens[i].kind != .identifier) return false;
        i += 1;
        if (self.tokens[i].kind == .dot) {
            i += 1;
            if (self.tokens[i].kind != .identifier) return false;
            i += 1;
        }
        if (self.tokens[i].kind == .colon_equal) return true;
        if (self.tokens[i].kind == .colon) {
            i += 1;
            while (i < self.tokens.len and self.tokens[i].kind != .newline and self.tokens[i].kind != .semicolon and self.tokens[i].kind != .eof) {
                if (self.tokens[i].kind == .equal) return true;
                i += 1;
            }
        }
        return false;
    }
    fn isTerminator(self: *Parser) bool {
        return switch (self.peek()) {
            .newline, .semicolon, .r_brace, .eof => true,
            else => false,
        };
    }
    fn skipTerminators(self: *Parser) void {
        while (self.peek() == .newline or self.peek() == .semicolon) _ = self.advance();
    }
    fn isPlace(self: *Parser, id: ast.ExprId) bool {
        return switch (self.tree.expr(id).kind) {
            .identifier, .member, .index, .deref => true,
            else => false,
        };
    }
    fn isNameLike(self: *Parser, id: ast.ExprId) bool {
        return switch (self.tree.expr(id).kind) {
            .identifier, .member => true,
            else => false,
        };
    }
    fn unary(self: *Parser, ctx: ParseCtx) anyerror!ast.ExprId {
        const t = self.advance();
        const e = try self.parseExpr(130, ctx);
        return self.add(.{ .span = join(t.span, self.tree.expr(e).span), .kind = .{ .unary = .{ .op = unOp(t.kind), .operand = e } } });
    }
    fn call(self: *Parser, lhs: ast.ExprId, s: source.Span, ctx: ParseCtx) anyerror!ast.ExprId {
        var args = std.ArrayList(ast.Arg).empty;
        while (self.peek() != .r_paren and self.peek() != .eof) {
            const before = self.pos;
            var nm: ?ast.Ident = null;
            if (self.peek() == .identifier and self.pos + 1 < self.tokens.len and self.tokens[self.pos + 1].kind == .colon) {
                nm = self.expectIdent();
                _ = self.eat(.colon);
            }
            const v = try self.parseExpr(0, ctx);
            try args.append(self.allocator, .{ .name = nm, .value = v, .span = self.tree.expr(v).span });
            _ = self.eat(.comma);
            if (self.pos == before) _ = self.advance();
        }
        _ = self.eat(.r_paren);
        return self.add(.{ .span = join(self.tree.expr(lhs).span, s), .kind = .{ .call = .{ .callee = lhs, .args = try args.toOwnedSlice(self.allocator) } } });
    }
    fn typedStruct(self: *Parser, lhs: ast.ExprId, s: source.Span, ctx: ParseCtx) anyerror!ast.ExprId {
        _ = s;
        var fields = std.ArrayList(ast.FieldInit).empty;
        while (self.peek() != .r_brace and self.peek() != .eof) {
            const before = self.pos;
            const n = self.expectIdent();
            var v: ?ast.ExprId = null;
            if (self.eat(.colon) != null) v = try self.parseExpr(0, ctx);
            try fields.append(self.allocator, .{ .name = n, .value = v, .span = n.span });
            _ = self.eat(.comma);
            if (self.pos == before) _ = self.advance();
        }
        _ = self.eat(.r_brace);
        return self.add(.{ .span = self.tree.expr(lhs).span, .kind = .{ .typed_struct_literal = .{ .ty = lhs, .fields = try fields.toOwnedSlice(self.allocator) } } });
    }
    fn lit(self: *Parser, l: ast.Literal) anyerror!ast.ExprId {
        const t = self.advance();
        return self.add(.{ .span = t.span, .kind = .{ .literal = l } });
    }
    fn add(self: *Parser, e: ast.Expr) anyerror!ast.ExprId {
        return self.tree.addExpr(e);
    }
    fn peek(self: *Parser) tok.TokenKind {
        return self.peekToken().kind;
    }
    fn peekToken(self: *Parser) tok.Token {
        return self.tokens[@min(self.pos, self.tokens.len - 1)];
    }
    fn advance(self: *Parser) tok.Token {
        const t = self.peekToken();
        if (self.pos < self.tokens.len) self.pos += 1;
        return t;
    }
    fn eat(self: *Parser, k: tok.TokenKind) ?tok.Token {
        if (self.peek() == k) return self.advance();
        return null;
    }
    fn expectIdent(self: *Parser) ast.Ident {
        const t = self.advance();
        return .{ .name = self.lexeme(t), .span = t.span };
    }
    fn lexeme(self: *Parser, t: tok.Token) []const u8 {
        return self.source_text[t.span.start..t.span.end];
    }
    fn errExpr(self: *Parser, c: []const u8, m: []const u8) anyerror!ast.ExprId {
        return self.errAt(c, m, self.peekToken().span);
    }
    fn errAt(self: *Parser, c: []const u8, m: []const u8, s: source.Span) anyerror!ast.ExprId {
        try self.diagnostics.errorAt(c, m, s, m);
        _ = self.advance();
        return self.add(.{ .span = s, .kind = .err });
    }
    fn addDiag(self: *Parser, d: diag.Diagnostic) !void {
        try self.diagnostics.add(d);
    }
    fn prefixTypeOnly(self: *Parser, k: tok.TokenKind) anyerror!ast.ExprId {
        const t = self.peekToken();
        const msg = if (k == .star) "prefix `*` is only valid in type position" else "prefix `?` is only valid in type position";
        const help = if (k == .star) "use postfix `.*` to dereference a value" else "use postfix `.?` to unwrap an optional value";
        try self.addDiag(.{ .severity = .error_, .code = "P0001", .message = msg, .primary = .{ .span = t.span, .message = "not valid before a value" }, .help = &.{.{ .message = help }} });
        _ = self.advance();
        return self.add(.{ .span = t.span, .kind = .err });
    }
    fn mutValueError(self: *Parser) anyerror!ast.ExprId {
        const t = self.peekToken();
        try self.addDiag(.{ .severity = .error_, .code = "P0002", .message = "`mut` is not valid in expression position", .primary = .{ .span = t.span, .message = "`mut` cannot start an expression" }, .notes = &.{.{ .message = "`mut` is a declaration modifier and a type-position pointer/slice annotation only" }}, .help = &.{.{ .message = "move `mut` to the declaration or remove it" }} });
        _ = self.advance();
        return self.add(.{ .span = t.span, .kind = .err });
    }
    fn bareParensError(self: *Parser, s: source.Span, ctx: ParseCtx) anyerror!ast.ExprId {
        try self.addDiag(.{ .severity = .error_, .code = "P0004", .message = "empty parentheses are not a valid expression or type", .primary = .{ .span = s, .message = "empty parentheses here" }, .help = &.{.{ .message = if (ctx.mode == .type) "write `() void` for a zero-parameter function type" else "write `() { }` for a zero-parameter function literal" }} });
        return self.add(.{ .span = s, .kind = .err });
    }
    fn assignmentInDecl(self: *Parser, s: source.Span) !void {
        try self.addDiag(.{ .severity = .error_, .code = "P0204", .message = "declaration uses `=` instead of `:=`", .primary = .{ .span = self.peekToken().span, .message = "use `:=` to declare a new binding" }, .secondary = &.{.{ .span = s, .message = "declaration starts here" }}, .help = &.{.{ .message = "replace `=` with `:=`", .suggestion = .{ .replacement = ":=", .span = self.peekToken().span, .machine_applicable = true } }} });
    }
    fn declMissingInit(self: *Parser, s: source.Span) !void {
        try self.addDiag(.{ .severity = .error_, .code = "P0201", .message = "declaration requires an initializer", .primary = .{ .span = s, .message = "binding declared here" }, .help = &.{.{ .message = "add `= <value>` after the type annotation" }} });
    }
    fn expectedDeclInit(self: *Parser, s: source.Span) !void {
        try self.addDiag(.{ .severity = .error_, .code = "P0202", .message = "expected declaration initializer", .primary = .{ .span = s, .message = "declaration starts here" }, .help = &.{.{ .message = "use `:=` for inferred declarations or `= <value>` after a type" }} });
    }
    fn looksLikeFnParams(self: *Parser) bool {
        var i = self.pos;
        var depth: usize = 1;
        while (i < self.tokens.len) {
            const k = self.tokens[i].kind;
            if (k == .l_paren) depth += 1 else if (k == .r_paren) {
                depth -= 1;
                if (depth == 0) return isFnContinuation(self.tokens[@min(i + 1, self.tokens.len - 1)].kind);
            }
            i += 1;
        }
        return false;
    }
    fn skipBalanced(self: *Parser, open: tok.TokenKind, close: tok.TokenKind) void {
        var d: usize = 1;
        _ = open;
        while (d > 0 and self.peek() != .eof) {
            const k = self.advance().kind;
            if (k == .l_brace) d += 1 else if (k == close) d -= 1;
        }
    }
};
fn postfixBp(k: tok.TokenKind) ?u8 {
    return switch (k) {
        .l_paren, .l_bracket, .dot, .dot_question, .dot_bang, .dot_star, .l_brace => 140,
        else => null,
    };
}
const Infix = struct { lbp: u8, rbp: u8 };
fn infix(k: tok.TokenKind) ?Infix {
    return switch (k) {
        .kw_or => .{ .lbp = 10, .rbp = 11 },
        .dot_dot, .dot_dot_equal => .{ .lbp = 20, .rbp = 21 },
        .pipe_pipe => .{ .lbp = 30, .rbp = 31 },
        .amp_amp => .{ .lbp = 40, .rbp = 41 },
        .pipe => .{ .lbp = 50, .rbp = 51 },
        .caret => .{ .lbp = 60, .rbp = 61 },
        .amp => .{ .lbp = 70, .rbp = 71 },
        .equal_equal, .bang_equal => .{ .lbp = 80, .rbp = 81 },
        .less, .less_equal, .greater, .greater_equal => .{ .lbp = 90, .rbp = 91 },
        .shift_left, .shift_right => .{ .lbp = 100, .rbp = 101 },
        .plus, .minus => .{ .lbp = 110, .rbp = 111 },
        .star, .slash, .percent => .{ .lbp = 120, .rbp = 121 },
        else => null,
    };
}
fn parseErrorUnionType(self: *Parser, ok: ast.ExprId, start: source.Span) !ast.ExprId {
    var errors = std.ArrayList(ast.ExprId).empty;
    while (self.peek() != .equal and self.peek() != .l_brace and self.peek() != .equal_greater and self.peek() != .newline and self.peek() != .semicolon and self.peek() != .eof) {
        const e = try self.parseExpr(80, .{ .mode = .type });
        try errors.append(self.allocator, e);
        _ = self.eat(.pipe);
    }
    return self.add(.{ .span = start, .kind = .{ .error_union_type = .{ .ok = ok, .errors = try errors.toOwnedSlice(self.allocator) } } });
}
fn parseOrFallback(self: *Parser, lhs: ast.ExprId, op_span: source.Span, ctx: ParseCtx) anyerror!ast.ExprId {
    _ = op_span;
    var cap: ?ast.Ident = null;
    if (self.peek() == .pipe) {
        const cl = try self.parseBindingList();
        if (cl.bindings.len > 0) cap = cl.bindings[0];
    }
    const rhs = switch (self.peek()) {
        .kw_return, .kw_break, .kw_continue => blk: {
            const st = try self.parseStmt(ctx);
            const one = try self.allocator.alloc(ast.StmtId, 1);
            one[0] = st;
            break :blk try self.add(.{ .span = self.tree.stmt(st).span, .kind = .{ .block = one } });
        },
        else => try self.parseExpr(11, ctx),
    };
    return self.add(.{ .span = join(self.tree.expr(lhs).span, self.tree.expr(rhs).span), .kind = .{ .or_fallback = .{ .lhs = lhs, .capture = cap, .rhs = rhs } } });
}
fn binOp(k: tok.TokenKind) ast.BinaryOp {
    return switch (k) {
        .plus => .add,
        .minus => .sub,
        .star => .mul,
        .slash => .div,
        .percent => .rem,
        .amp => .bit_and,
        .pipe => .bit_or,
        .caret => .bit_xor,
        .shift_left => .shl,
        .shift_right => .shr,
        .less => .lt,
        .less_equal => .le,
        .greater => .gt,
        .greater_equal => .ge,
        .equal_equal => .eq,
        .bang_equal => .ne,
        .amp_amp => .logical_and,
        .pipe_pipe => .logical_or,
        .dot_dot => .range_exclusive,
        .dot_dot_equal => .range_inclusive,
        .kw_or => .or_else,
        else => .add,
    };
}
fn unOp(k: tok.TokenKind) ast.UnaryOp {
    return switch (k) {
        .bang => .not,
        .minus => .neg,
        .tilde => .bit_not,
        .amp => .address_of,
        .kw_comp => .comp,
        .star => .address_of,
        .question => .not,
        else => .not,
    };
}
fn isFnContinuation(k: tok.TokenKind) bool {
    return switch (k) {
        .l_brace, .equal_greater, .bang, .kw_comp, .kw_type, .identifier, .kw_struct, .kw_enum => true,
        else => false,
    };
}
fn join(a: source.Span, b: source.Span) source.Span {
    return .{ .file = a.file, .start = @min(a.start, b.start), .end = @max(a.end, b.end) };
}
fn assignOp(k: tok.TokenKind) ?ast.AssignOp {
    return switch (k) {
        .equal => .assign,
        .plus_equal => .add,
        .minus_equal => .sub,
        .star_equal => .mul,
        .slash_equal => .div,
        .percent_equal => .rem,
        else => null,
    };
}
pub fn dump(allocator: std.mem.Allocator, tree: *const ast.Ast, id: ast.ExprId) ![]u8 {
    var out = std.array_list.Managed(u8).init(allocator);
    try dumpExpr(&out, tree, id, 0);
    return out.toOwnedSlice();
}
fn dumpExpr(out: *std.array_list.Managed(u8), tree: *const ast.Ast, id: ast.ExprId, indent: usize) !void {
    try out.appendNTimes(' ', indent);
    const e = tree.expr(id);
    try out.print("{s}\n", .{@tagName(e.kind)});
    switch (e.kind) {
        .binary => |b| {
            try dumpExpr(out, tree, b.lhs, indent + 2);
            try dumpExpr(out, tree, b.rhs, indent + 2);
        },
        .unary => |u| try dumpExpr(out, tree, u.operand, indent + 2),
        .call => |c| {
            try dumpExpr(out, tree, c.callee, indent + 2);
            for (c.args) |a| try dumpExpr(out, tree, a.value, indent + 2);
        },
        .member => |m| try dumpExpr(out, tree, m.object, indent + 2),
        .index => |x| {
            try dumpExpr(out, tree, x.object, indent + 2);
            try dumpExpr(out, tree, x.index, indent + 2);
        },
        .grouped => |g| try dumpExpr(out, tree, g, indent + 2),
        else => {},
    }
}

test "parser snapshots smoke" {
    inline for (cases) |src| {
        var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
        defer arena.deinit();
        const a = arena.allocator();
        var bag = diag.DiagnosticBag.init(a, .{});
        defer bag.deinit();
        var r = try parseExprSource(a, src, &bag);
        defer r.tree.deinit();
        const d = try dump(a, &r.tree, r.root);
        try std.testing.expect(d.len > 0);
    }
}
test "pretty round trips expression subset" {
    inline for (pretty_cases) |src| {
        var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
        defer arena.deinit();
        const a = arena.allocator();
        var bag = diag.DiagnosticBag.init(a, .{});
        var r = try parseExprSource(a, src, &bag);
        const p = try pretty.printExpr(a, &r.tree, r.root);
        var bag2 = diag.DiagnosticBag.init(a, .{});
        var r2 = try parseExprSource(a, p, &bag2);
        const d1 = try dump(a, &r.tree, r.root);
        const d2 = try dump(a, &r2.tree, r2.root);
        try std.testing.expectEqualStrings(d1, d2);
    }
}
const cases = [_][]const u8{ "1", "1+2", "1+2*3", "(1+2)*3", "a.b", "a()", "a(1,2)", "a[0]", "a.?", "a.!", "a.*", "!a", "-a", "~a", "&a", "comp a", "a or b", "a..b", "a..=b", "a||b", "a&&b", "a|b", "a^b", "a&b", "a==b", "a!=b", "a<b", "a<=b", "a>b", "a>=b", "a<<b", "a>>b", "[1,2]", "[]", ".{1,2}", "Point{x:1}", "struct {}", "enum { A }", "use \"x\"", "if a b else c", "for a {}", "match x { _: y }", "{}", "{1}", "$foo", "true", "false", "null", "'a'", "\"s\"", "a.b().c[0].?", "1+2+3", "1*2/3%4", "a.b{c:1}", "(x: i32) i32 => x", "() i32 => 1", "() {}", "?T", "*T", "mut x", "()" };
test "corpus files parse end to end" {
    inline for (.{ @embedFile("../tests/corpus/examples/main.dyn"), @embedFile("../tests/corpus/examples/main2.dyn"), @embedFile("../tests/corpus/examples/other.dyn") }) |src| {
        var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
        defer arena.deinit();
        const a = arena.allocator();
        var bag = diag.DiagnosticBag.init(a, .{});
        var r = try parseFileSource(a, src, &bag);
        defer r.tree.deinit();
        if (bag.error_count != 0) {
            for (bag.diagnostics.items[0..@min(bag.diagnostics.items.len, 10)]) |d| std.debug.print("{s}@{}: {s}\n", .{ d.code, d.primary.span.start, d.message });
        }
        try std.testing.expectEqual(@as(usize, 0), bag.error_count);
        try std.testing.expect(r.file.items.len > 0);
    }
}
const pretty_cases = [_][]const u8{ "1 + 2 * 3", "(1 + 2) * 3", "a.b().c[0].?", "[1, 2]", ".{1, 2}", "Point{x: 1}", "if a b else c", "match x { 1: 2, 3..4: 5, .V: |v| 6, _: 7 }" };
test "parser error corpus renders diagnostics" {
    inline for (error_cases) |case| {
        var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
        defer arena.deinit();
        const a = arena.allocator();
        const src = @embedFile("../tests/corpus/errors/" ++ case.name ++ ".dyn");
        var bag = diag.DiagnosticBag.init(a, .{});
        var r = try parseFileSource(a, src, &bag);
        defer r.tree.deinit();
        if (bag.error_count == 0) std.debug.print("no errors for {s}\n", .{case.name});
        try std.testing.expect(bag.error_count > 0);
        const provider_data = diag.SingleSource{ .path = case.name ++ ".dyn", .text = src };
        const rendered = try diag.render(std.testing.allocator, provider_data.provider(), bag.diagnostics.items);
        defer std.testing.allocator.free(rendered);
        try std.testing.expect(rendered.len > 0);
    }
}
const error_cases = [_]struct { name: []const u8 }{
    .{ .name = "assignment_decl" },
    .{ .name = "decl_no_init" },
    .{ .name = "missing_capture_colon" },
    .{ .name = "prefix_star_value" },
    .{ .name = "prefix_question_value" },
    .{ .name = "mut_value" },
    .{ .name = "bare_parens" },
    .{ .name = "fn_type_missing_return" },
    .{ .name = "arrow_missing_return" },
    .{ .name = "if_missing_else" },
    .{ .name = "type_tuple_block" },
};
