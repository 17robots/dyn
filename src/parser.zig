const std = @import("std");
const Tok = @import("token.zig").Tok;
const Span = @import("token.zig").Span;
const Ast = @import("ast.zig");
const Lexer = @import("lexer2.zig");

pub const ParseError = struct {
    span: Span,
    message: []const u8,
};

const ParseAllocError = std.mem.Allocator.Error;

pub const Self = @This();

allocator: std.mem.Allocator,
toks: []const Tok,
i: usize = 0,
nodes: std.ArrayListUnmanaged(Ast.Node) = .empty,
errors: std.ArrayListUnmanaged(ParseError) = .empty,
list_items: std.ArrayListUnmanaged(Ast.NodeId) = .empty,
decl_name_items: std.ArrayListUnmanaged(Ast.NodeId) = .empty,
param_name_items: std.ArrayListUnmanaged(Ast.NodeId) = .empty,
match_arms: std.ArrayListUnmanaged(Ast.MatchArm) = .empty,

pub fn init(allocator: std.mem.Allocator, toks: []const Tok) Self {
    return .{ .allocator = allocator, .toks = toks };
}

pub fn deinit(self: *Self) void {
    self.nodes.deinit(self.allocator);
    self.errors.deinit(self.allocator);
    self.list_items.deinit(self.allocator);
    self.decl_name_items.deinit(self.allocator);
    self.param_name_items.deinit(self.allocator);
    self.match_arms.deinit(self.allocator);
}

pub fn hasErrors(self: *const Self) bool {
    return self.errors.items.len > 0;
}

pub fn parseExpr(self: *Self) ParseAllocError!?Ast.NodeId {
    self.skipTrivia();
    if (self.atEnd()) return null;
    return try self.parseAssignment();
}

pub fn parseFile(self: *Self) ParseAllocError!?Ast.NodeId {
    self.skipTrivia();
    if (self.atEnd()) return null;

    var items: std.ArrayListUnmanaged(Ast.NodeId) = .empty;
    defer items.deinit(self.allocator);
    while (!self.atEnd()) {
        const n = (try self.parseItem()) orelse break;
        try items.append(self.allocator, n);
        self.skipSeparators();
    }

    const start_list = self.list_items.items.len;
    try self.list_items.appendSlice(self.allocator, items.items);
    const count = items.items.len;
    if (count == 1) return self.list_items.items[start_list];

    const start_span = if (count > 0) self.nodes.items[self.list_items.items[start_list]].span.start else 0;
    const end_span = if (count > 0) self.nodes.items[self.list_items.items[start_list + count - 1]].span.end else 0;
    return try self.pushNode(.{
        .tag = .block,
        .span = .{ .start = start_span, .end = end_span },
        .data = .{ .block = .{
            .item_start = @intCast(start_list),
            .item_count = @intCast(count),
        } },
    });
}

fn parseItem(self: *Self) ParseAllocError!?Ast.NodeId {
    self.skipTrivia();
    if (self.atEnd()) return null;

    var is_pub = false;
    if (self.currentIs(.@"pub")) {
        is_pub = true;
        self.advance();
        self.skipTrivia();
    }

    if (try self.tryParseLabeledBlock()) |lb| return lb;
    if (self.currentIs(.module)) return try self.parseModuleDecl();
    if (self.currentIs(.@"for")) return try self.parseForStmt();
    if (self.currentIs(.@"return")) return try self.parseReturnStmt();
    if (self.currentIs(.@"break")) return try self.parseBreakStmt();
    if (self.currentIs(.@"continue")) return try self.parseContinueStmt();
    if (self.currentIs(.@"defer")) return try self.parseDeferStmt();

    if (try self.tryParseDecl(is_pub)) |d| return d;

    if (is_pub) {
        const n = try self.parseExpr();
        try self.pushError(self.nodes.items[n.?].span, "'pub' currently only applies to declarations");
        return n;
    }
    return try self.parseExpr();
}

fn tryParseLabeledBlock(self: *Self) ParseAllocError!?Ast.NodeId {
    if (!self.currentIs(.identifier)) return null;
    var j = self.i + 1;
    if (j >= self.toks.len or self.toks[j].kind != .colon) return null;
    j += 1;
    while (j < self.toks.len) : (j += 1) {
        switch (self.toks[j].kind) {
            .newline, .semicolon, .line_comment, .doc_comment, .block_comment => {},
            else => break,
        }
    }
    if (j >= self.toks.len) return null;
    const body_kind = self.toks[j].kind;
    if (body_kind != .lbrace and body_kind != .@"for") return null;

    const label_tok = self.current();
    self.advance(); // ident
    _ = self.consume(.colon);
    self.skipTrivia();
    const body = if (self.currentIs(.@"for")) try self.parseForStmt() else try self.parseBlockExpr();
    return try self.pushNode(.{
        .tag = .labeled_block,
        .span = .{ .start = label_tok.span.start, .end = self.nodes.items[body].span.end },
        .data = .{ .labeled_block = .{ .label_span = label_tok.span, .body = body } },
    });
}

fn parseForStmt(self: *Self) ParseAllocError!Ast.NodeId {
    const for_tok = self.current();
    self.advance();
    self.skipTrivia();

    var is_infinite = false;
    var cond: Ast.NodeId = Ast.NullNode;

    if (self.currentIs(.lbrace)) {
        is_infinite = true;
    } else {
        cond = try self.parseAssignment();
        self.skipTrivia();
    }

    var has_capture = false;
    var capture_span: Span = .{ .start = for_tok.span.start, .end = for_tok.span.start };
    if (self.consume(.colon)) {
        self.skipTrivia();
        if (self.consume(.pipe)) {
            self.skipTrivia();
            if (!self.atEnd() and (self.current().kind == .identifier or self.current().kind == .underscore)) {
                capture_span = self.current().span;
                has_capture = true;
                self.advance();
            }
            self.skipTrivia();
            if (!self.consume(.pipe)) try self.pushError(for_tok.span, "expected closing '|' in for capture");
        }
        self.skipTrivia();
    }

    const body = try self.parseBlockOrExpr();
    const end_span = self.nodes.items[body].span.end;
    return try self.pushNode(.{
        .tag = .for_stmt,
        .span = .{ .start = for_tok.span.start, .end = end_span },
        .data = .{ .for_stmt = .{
            .cond = cond,
            .body = body,
            .capture_span = capture_span,
            .has_capture = has_capture,
            .is_infinite = is_infinite,
        } },
    });
}

fn parseBreakStmt(self: *Self) ParseAllocError!Ast.NodeId {
    const b = self.current();
    self.advance();
    self.skipTrivia();

    var has_label = false;
    var label_span: Span = .{ .start = b.span.start, .end = b.span.start };
    if (self.consume(.colon)) {
        if (!self.atEnd() and self.current().kind == .identifier) {
            has_label = true;
            label_span = self.current().span;
            self.advance();
            self.skipTrivia();
        }
    }

    var has_value = false;
    var value: Ast.NodeId = Ast.NullNode;
    if (!self.atEnd() and !isHardTerminator(self.current().kind)) {
        has_value = true;
        value = try self.parseAssignment();
    }

    const end_span = if (has_value) self.nodes.items[value].span.end else if (has_label) label_span.end else b.span.end;
    return try self.pushNode(.{
        .tag = .break_stmt,
        .span = .{ .start = b.span.start, .end = end_span },
        .data = .{ .break_stmt = .{
            .value = value,
            .has_value = has_value,
            .label_span = label_span,
            .has_label = has_label,
        } },
    });
}

fn parseReturnStmt(self: *Self) ParseAllocError!Ast.NodeId {
    const r = self.current();
    self.advance();
    self.skipTrivia();

    var has_value = false;
    var value: Ast.NodeId = Ast.NullNode;
    if (!self.atEnd() and !isHardTerminator(self.current().kind)) {
        has_value = true;
        value = try self.parseAssignment();
    }

    const end_span = if (has_value) self.nodes.items[value].span.end else r.span.end;
    return try self.pushNode(.{
        .tag = .return_stmt,
        .span = .{ .start = r.span.start, .end = end_span },
        .data = .{ .return_stmt = .{ .value = value, .has_value = has_value } },
    });
}

fn parseContinueStmt(self: *Self) ParseAllocError!Ast.NodeId {
    const c = self.current();
    self.advance();
    self.skipTrivia();

    var has_label = false;
    var label_span: Span = .{ .start = c.span.start, .end = c.span.start };
    if (self.consume(.colon)) {
        if (!self.atEnd() and self.current().kind == .identifier) {
            has_label = true;
            label_span = self.current().span;
            self.advance();
        }
    }

    const end_span = if (has_label) label_span.end else c.span.end;
    return try self.pushNode(.{
        .tag = .continue_stmt,
        .span = .{ .start = c.span.start, .end = end_span },
        .data = .{ .continue_stmt = .{ .label_span = label_span, .has_label = has_label } },
    });
}

fn parseDeferStmt(self: *Self) ParseAllocError!Ast.NodeId {
    const d = self.current();
    self.advance();
    self.skipTrivia();

    if (self.consume(.pipe)) {
        self.skipTrivia();
        if (!self.atEnd() and (self.current().kind == .identifier or self.current().kind == .underscore)) {
            self.advance();
            self.skipTrivia();
        }
        if (!self.consume(.pipe)) try self.pushError(d.span, "expected closing '|' in defer capture");
        self.skipTrivia();
    }

    const value = try self.parseBlockOrExpr();
    return try self.pushNode(.{
        .tag = .defer_stmt,
        .span = .{ .start = d.span.start, .end = self.nodes.items[value].span.end },
        .data = .{ .defer_stmt = .{ .value = value } },
    });
}

fn parseAssignment(self: *Self) ParseAllocError!Ast.NodeId {
    var lhs = try self.parseBinary(1);
    self.skipTrivia();
    if (self.atEnd()) return lhs;

    const op_kind = self.current().kind;
    const op = toAssignOp(op_kind) orelse return lhs;
    self.advance();
    const rhs = try self.parseAssignment();

    lhs = try self.pushNode(.{
        .tag = .assign,
        .span = .{ .start = self.nodes.items[lhs].span.start, .end = self.nodes.items[rhs].span.end },
        .data = .{ .assign = .{ .op = op, .lhs = lhs, .rhs = rhs } },
    });
    return lhs;
}

fn parseBinary(self: *Self, min_prec: u8) ParseAllocError!Ast.NodeId {
    var lhs = try self.parsePrefix();

    while (true) {
        self.skipTrivia();
        if (self.atEnd()) break;

        const tk = self.current().kind;
        const prec = precedence(tk) orelse break;
        if (prec < min_prec) break;

        const op = toBinaryOp(tk).?;
        self.advance();
        const rhs = try self.parseBinary(prec + 1);

        lhs = try self.pushNode(.{
            .tag = .binary,
            .span = .{ .start = self.nodes.items[lhs].span.start, .end = self.nodes.items[rhs].span.end },
            .data = .{ .binary = .{ .op = op, .lhs = lhs, .rhs = rhs } },
        });
    }

    return lhs;
}

fn parsePrefix(self: *Self) ParseAllocError!Ast.NodeId {
    self.skipTrivia();
    if (self.atEnd()) return self.pushErrorNode(.{ .start = 0, .end = 0 }, "unexpected end of input");

    const tok = self.current();
    switch (tok.kind) {
        .sub, .not, .complement => {
            const op = toUnaryOp(tok.kind).?;
            self.advance();
            const rhs = try self.parsePrefix();
            return self.pushNode(.{
                .tag = .unary,
                .span = .{ .start = tok.span.start, .end = self.nodes.items[rhs].span.end },
                .data = .{ .unary = .{ .op = op, .rhs = rhs } },
            });
        },
        .@"and" => {
            self.advance();
            const rhs = try self.parsePrefix();
            return self.pushNode(.{
                .tag = .address_of,
                .span = .{ .start = tok.span.start, .end = self.nodes.items[rhs].span.end },
                .data = .{ .one = .{ .child = rhs } },
            });
        },
        .mul => {
            self.advance();
            self.skipTrivia();
            var is_mut = false;
            if (self.currentIs(.mut)) {
                is_mut = true;
                self.advance();
                self.skipTrivia();
            }
            const rhs = try self.parsePrefix();
            return self.pushNode(.{
                .tag = .ptr_type,
                .span = .{ .start = tok.span.start, .end = self.nodes.items[rhs].span.end },
                .data = .{ .ptr_type = .{ .child = rhs, .mutable = is_mut } },
            });
        },
        .lbrack => {
            const open = tok;
            self.advance();
            self.skipTrivia();

            if (self.consume(.rbrack)) {
                self.skipTrivia();
                const elem = try self.parsePrefix();
                return self.pushNode(.{
                    .tag = .slice_type,
                    .span = .{ .start = open.span.start, .end = self.nodes.items[elem].span.end },
                    .data = .{ .one = .{ .child = elem } },
                });
            }

            const len_node = try self.parseAssignment();
            self.skipTrivia();
            if (!self.consume(.rbrack)) {
                try self.pushError(open.span, "expected ']' in array type");
            }
            self.skipTrivia();
            const elem = try self.parsePrefix();
            return self.pushNode(.{
                .tag = .array_type,
                .span = .{ .start = open.span.start, .end = self.nodes.items[elem].span.end },
                .data = .{ .array_type = .{ .len = len_node, .child = elem } },
            });
        },
        .question => {
            self.advance();
            self.skipTrivia();
            const rhs = try self.parsePrefix();
            return self.pushNode(.{
                .tag = .optional_type,
                .span = .{ .start = tok.span.start, .end = self.nodes.items[rhs].span.end },
                .data = .{ .one = .{ .child = rhs } },
            });
        },
        .@"inline" => {
            self.advance();
            self.skipTrivia();
            const child = try self.parsePrefix();
            return self.pushNode(.{
                .tag = .inline_expr,
                .span = .{ .start = tok.span.start, .end = self.nodes.items[child].span.end },
                .data = .{ .one = .{ .child = child } },
            });
        },
        .comp => {
            self.advance();
            self.skipTrivia();
            const child = try self.parseAssignment();
            return self.pushNode(.{
                .tag = .comp_expr,
                .span = .{ .start = tok.span.start, .end = self.nodes.items[child].span.end },
                .data = .{ .one = .{ .child = child } },
            });
        },
        else => {
            const base = try self.parsePrimary();
            return self.parsePostfix(base);
        },
    }
}

fn parsePrimary(self: *Self) ParseAllocError!Ast.NodeId {
    if (self.atEnd()) return self.pushErrorNode(.{ .start = 0, .end = 0 }, "expected expression");
    const tok = self.current();

    switch (tok.kind) {
        .identifier => {
            self.advance();
            return self.pushNode(.{ .tag = .identifier, .span = tok.span, .data = .{ .none = {} } });
        },
        .true, .false => {
            self.advance();
            return self.pushNode(.{ .tag = .bool_lit, .span = tok.span, .data = .{ .none = {} } });
        },
        .int => {
            self.advance();
            return self.pushNode(.{ .tag = .int_lit, .span = tok.span, .data = .{ .none = {} } });
        },
        .float => {
            self.advance();
            return self.pushNode(.{ .tag = .float_lit, .span = tok.span, .data = .{ .none = {} } });
        },
        .string => {
            self.advance();
            return self.pushNode(.{ .tag = .string_lit, .span = tok.span, .data = .{ .none = {} } });
        },
        .char => {
            self.advance();
            return self.pushNode(.{ .tag = .char_lit, .span = tok.span, .data = .{ .none = {} } });
        },
        .type => {
            self.advance();
            return self.pushNode(.{ .tag = .type_lit, .span = tok.span, .data = .{ .none = {} } });
        },
        .lparen => {
            if (try self.tryParseFnExprFromParen()) |fn_node| return fn_node;

            self.advance();
            const inner = try self.parseAssignment();
            self.skipTrivia();
            if (!self.consume(.rparen)) try self.pushError(tok.span, "expected ')' after expression");
            return inner;
        },
        .lbrace => return self.parseBlockExpr(),
        .@"if" => return self.parseIfExpr(),
        .match => return self.parseMatchExpr(),
        .@"extern" => return self.parseExternFnExpr(),
        .@"fn" => return self.parseFnExprKeyword(),
        .use => return self.parseUseExpr(),
        .@"struct" => return self.parseStructExpr(),
        .@"enum" => return self.parseEnumExpr(),
        else => {
            self.advance();
            return self.pushErrorNode(tok.span, "expected expression");
        },
    }
}

fn parseStructExpr(self: *Self) ParseAllocError!Ast.NodeId {
    return self.parseAggregateExpr(.struct_expr);
}

fn parseEnumExpr(self: *Self) ParseAllocError!Ast.NodeId {
    return self.parseAggregateExpr(.enum_expr);
}

fn parseAggregateExpr(self: *Self, tag: Ast.Node.Tag) ParseAllocError!Ast.NodeId {
    const kw = self.current();
    self.advance();
    self.skipTrivia();
    if (!self.consume(.lbrace)) {
        try self.pushError(kw.span, "expected '{' after aggregate keyword");
        return self.pushErrorNode(kw.span, "invalid aggregate expression");
    }

    var items: std.ArrayListUnmanaged(Ast.NodeId) = .empty;
    defer items.deinit(self.allocator);
    self.skipSeparators();
    while (!self.atEnd() and !self.currentIs(.rbrace)) {
        const item = (try self.parseItem()) orelse break;
        try items.append(self.allocator, item);
        self.skipSeparators();
    }

    const close = if (self.consume(.rbrace)) self.toks[self.i - 1].span else blk: {
        try self.pushError(kw.span, "expected '}' to close aggregate expression");
        break :blk kw.span;
    };

    const item_start = self.list_items.items.len;
    try self.list_items.appendSlice(self.allocator, items.items);
    const item_count = items.items.len;
    return self.pushNode(.{
        .tag = tag,
        .span = .{ .start = kw.span.start, .end = close.end },
        .data = .{ .aggregate = .{ .item_start = @intCast(item_start), .item_count = @intCast(item_count) } },
    });
}

fn parsePostfix(self: *Self, start: Ast.NodeId) ParseAllocError!Ast.NodeId {
    var node = start;
    while (true) {
        self.skipTrivia();
        if (self.atEnd()) break;

        switch (self.current().kind) {
            .dot => {
                const dot_tok = self.current();
                self.advance();
                if (self.atEnd()) {
                    try self.pushError(dot_tok.span, "expected token after '.'");
                    break;
                }
                const after = self.current();
                switch (after.kind) {
                    .identifier => {
                        self.advance();
                        node = try self.pushNode(.{
                            .tag = .field,
                            .span = .{ .start = self.nodes.items[node].span.start, .end = after.span.end },
                            .data = .{ .field = .{ .object = node, .field_span = after.span } },
                        });
                    },
                    .question => {
                        self.advance();
                        node = try self.pushNode(.{
                            .tag = .unwrap_optional,
                            .span = .{ .start = self.nodes.items[node].span.start, .end = after.span.end },
                            .data = .{ .one = .{ .child = node } },
                        });
                    },
                    .not => {
                        self.advance();
                        node = try self.pushNode(.{
                            .tag = .unwrap_error,
                            .span = .{ .start = self.nodes.items[node].span.start, .end = after.span.end },
                            .data = .{ .one = .{ .child = node } },
                        });
                    },
                    .mul => {
                        self.advance();
                        node = try self.pushNode(.{
                            .tag = .deref,
                            .span = .{ .start = self.nodes.items[node].span.start, .end = after.span.end },
                            .data = .{ .one = .{ .child = node } },
                        });
                    },
                    else => {
                        try self.pushError(after.span, "expected identifier, '?', '!' or '*' after '.'");
                        break;
                    },
                }
            },
            .lparen => {
                const start_tok = self.current();
                self.advance();
                var args: std.ArrayListUnmanaged(Ast.NodeId) = .empty;
                defer args.deinit(self.allocator);
                while (!self.atEnd() and self.current().kind != .rparen) {
                    const arg = try self.parseAssignment();
                    try args.append(self.allocator, arg);
                    self.skipTrivia();
                    if (!self.consume(.comma)) break;
                    self.skipTrivia();
                }
                const close_span = if (self.consume(.rparen)) self.toks[self.i - 1].span else blk: {
                    try self.pushError(start_tok.span, "expected ')' after call arguments");
                    break :blk self.nodes.items[node].span;
                };
                const arg_start = self.list_items.items.len;
                try self.list_items.appendSlice(self.allocator, args.items);
                const arg_count = args.items.len;
                node = try self.pushNode(.{
                    .tag = .call,
                    .span = .{ .start = self.nodes.items[node].span.start, .end = close_span.end },
                    .data = .{ .call = .{
                        .callee = node,
                        .arg_start = @intCast(arg_start),
                        .arg_count = @intCast(arg_count),
                    } },
                });
            },
            .lbrack => node = try self.parseIndexOrSlice(node),
            .not => {
                const bang_tok = self.current();
                self.advance();
                self.skipTrivia();

                var names: std.ArrayListUnmanaged(Ast.NodeId) = .empty;
                defer names.deinit(self.allocator);

                if (!self.atEnd() and self.current().kind == .identifier) {
                    while (!self.atEnd()) {
                        if (self.current().kind != .identifier) {
                            try self.pushError(self.current().span, "expected error type name after '!' or ','");
                            break;
                        }
                        const nm_tok = self.current();
                        self.advance();
                        const nm_node = try self.pushNode(.{ .tag = .identifier, .span = nm_tok.span, .data = .{ .none = {} } });
                        try names.append(self.allocator, nm_node);
                        self.skipTrivia();
                        if (!self.consume(.comma)) break;
                        self.skipTrivia();
                        if (self.atEnd() or self.current().kind != .identifier) {
                            try self.pushError(bang_tok.span, "expected error type name after ','");
                            break;
                        }
                    }
                } else if (!self.atEnd()) {
                    switch (self.current().kind) {
                        .int, .float, .string, .char => try self.pushError(self.current().span, "expected error type name after '!' or ','"),
                        else => {},
                    }
                }

                const name_start = self.list_items.items.len;
                try self.list_items.appendSlice(self.allocator, names.items);
                const end_span = if (names.items.len > 0) self.nodes.items[names.items[names.items.len - 1]].span else bang_tok.span;
                node = try self.pushNode(.{
                    .tag = .error_type,
                    .span = .{ .start = self.nodes.items[node].span.start, .end = end_span.end },
                    .data = .{ .error_type = .{ .child = node, .name_start = @intCast(name_start), .name_count = @intCast(names.items.len) } },
                });
            },
            else => break,
        }
    }
    return node;
}

fn parseIndexOrSlice(self: *Self, object: Ast.NodeId) ParseAllocError!Ast.NodeId {
    const open = self.current();
    self.advance();
    self.skipTrivia();

    var has_start = false;
    var has_end = false;
    var inclusive = false;
    var start_node: Ast.NodeId = Ast.NullNode;
    var end_node: Ast.NodeId = Ast.NullNode;

    if (self.currentIs(.range) or self.currentIs(.rangeq)) {
        inclusive = self.current().kind == .rangeq;
        self.advance();
        self.skipTrivia();
        if (!self.currentIs(.rbrack)) {
            end_node = try self.parseAssignment();
            has_end = true;
        }
    } else {
        const first = try self.parseAssignment();
        self.skipTrivia();
        const first_n = self.nodes.items[first];
        if (self.currentIs(.rbrack) and first_n.tag == .binary and (first_n.data.binary.op == .range or first_n.data.binary.op == .rangeq)) {
            has_start = true;
            has_end = true;
            start_node = first_n.data.binary.lhs;
            end_node = first_n.data.binary.rhs;
            inclusive = first_n.data.binary.op == .rangeq;
        } else if (self.currentIs(.range) or self.currentIs(.rangeq)) {
            has_start = true;
            start_node = first;
            inclusive = self.current().kind == .rangeq;
            self.advance();
            self.skipTrivia();
            if (!self.currentIs(.rbrack)) {
                end_node = try self.parseAssignment();
                has_end = true;
            }
        } else {
            if (!self.consume(.rbrack)) try self.pushError(open.span, "expected ']' after index");
            return self.pushNode(.{
                .tag = .index,
                .span = .{ .start = self.nodes.items[object].span.start, .end = self.toks[self.i - 1].span.end },
                .data = .{ .index = .{ .object = object, .index = first } },
            });
        }
    }

    const close_span = if (self.consume(.rbrack)) self.toks[self.i - 1].span else blk: {
        try self.pushError(open.span, "expected ']' after slice");
        break :blk self.nodes.items[object].span;
    };

    return self.pushNode(.{
        .tag = .slice,
        .span = .{ .start = self.nodes.items[object].span.start, .end = close_span.end },
        .data = .{ .slice = .{
            .object = object,
            .start = start_node,
            .end = end_node,
            .has_start = has_start,
            .has_end = has_end,
            .inclusive = inclusive,
        } },
    });
}

fn parseIfExpr(self: *Self) ParseAllocError!Ast.NodeId {
    const if_tok = self.current();
    self.advance();

    const cond = try self.parseAssignment();

    var has_bind = false;
    var bind_span: Span = .{ .start = if_tok.span.start, .end = if_tok.span.start };
    self.skipTrivia();
    if (self.consume(.colon)) {
        self.skipTrivia();
        if (self.consume(.pipe)) {
            self.skipTrivia();
            if (!self.atEnd() and (self.current().kind == .identifier or self.current().kind == .underscore)) {
                has_bind = true;
                bind_span = self.current().span;
                self.advance();
                self.skipTrivia();
            }
            if (!self.consume(.pipe)) try self.pushError(if_tok.span, "expected closing '|' in if binding");
        } else {
            try self.pushError(if_tok.span, "expected '|name|' after ':' in if binding");
        }
    }

    const then_expr = try self.parseBlockOrExpr();

    var has_else = false;
    var else_expr: Ast.NodeId = Ast.NullNode;
    if (self.currentIs(.@"else")) {
        has_else = true;
        self.advance();
        else_expr = try self.parseBlockOrExpr();
    }

    const end_span = if (has_else) self.nodes.items[else_expr].span.end else self.nodes.items[then_expr].span.end;
    return self.pushNode(.{
        .tag = .if_expr,
        .span = .{ .start = if_tok.span.start, .end = end_span },
        .data = .{ .if_expr = .{
            .cond = cond,
            .then_expr = then_expr,
            .else_expr = else_expr,
            .has_else = has_else,
            .bind_span = bind_span,
            .has_bind = has_bind,
        } },
    });
}

fn parseMatchExpr(self: *Self) ParseAllocError!Ast.NodeId {
    const m_tok = self.current();
    self.advance();

    const subject = try self.parseAssignment();
    self.skipTrivia();
    if (!self.consume(.lbrace)) {
        try self.pushError(m_tok.span, "expected '{' after match expression");
        return self.pushErrorNode(m_tok.span, "invalid match expression");
    }

    const arm_start = self.match_arms.items.len;
    self.skipSeparators();
    while (!self.atEnd() and !self.currentIs(.rbrace)) {
        const arm = try self.parseMatchArm();
        try self.match_arms.append(self.allocator, arm);
        self.skipSeparators();
    }

    const close_span = if (self.consume(.rbrace)) self.toks[self.i - 1].span else blk: {
        try self.pushError(m_tok.span, "expected '}' to close match");
        break :blk self.nodes.items[subject].span;
    };

    const arm_count = self.match_arms.items.len - arm_start;
    return self.pushNode(.{
        .tag = .match_expr,
        .span = .{ .start = m_tok.span.start, .end = close_span.end },
        .data = .{ .match_expr = .{
            .subject = subject,
            .arm_start = @intCast(arm_start),
            .arm_count = @intCast(arm_count),
        } },
    });
}

fn parseMatchArm(self: *Self) ParseAllocError!Ast.MatchArm {
    self.skipTrivia();
    const start_span = if (self.atEnd()) Span{ .start = 0, .end = 0 } else self.current().span;

    var kind: Ast.PatternKind = .expr;
    var pat_start: Ast.NodeId = Ast.NullNode;
    var pat_end: Ast.NodeId = Ast.NullNode;
    var pat_payload: Ast.NodeId = Ast.NullNode;
    var inclusive = false;
    var has_pat_payload = false;

    if (self.currentIs(.underscore)) {
        kind = .wildcard;
        self.advance();
    } else if (self.currentIs(.dot) and self.peekKind(1) == .identifier) {
        const dot_span = self.current().span;
        self.advance();
        const ident_span = self.current().span;
        const n = try self.pushNode(.{
            .tag = .identifier,
            .span = .{ .start = dot_span.start, .end = ident_span.end },
            .data = .{ .none = {} },
        });
        pat_start = n;
        self.advance();
        self.skipTrivia();
        if (self.consume(.lparen)) {
            self.skipTrivia();
            if (!self.currentIs(.rparen)) {
                pat_payload = try self.parseAssignment();
                has_pat_payload = true;
            }
            self.skipTrivia();
            if (!self.consume(.rparen)) try self.pushError(start_span, "expected ')' in match variant pattern");
        }
    } else {
        pat_start = try self.parseAssignment();
        self.skipTrivia();
        if (self.currentIs(.range) or self.currentIs(.rangeq)) {
            kind = .range;
            inclusive = self.current().kind == .rangeq;
            self.advance();
            pat_end = try self.parseAssignment();
        }
    }

    self.skipTrivia();
    if (!self.consume(.colon)) try self.pushError(start_span, "expected ':' in match arm");

    var has_capture = false;
    var capture_span: Span = .{ .start = start_span.start, .end = start_span.start };
    self.skipTrivia();
    if (self.consume(.pipe)) {
        self.skipTrivia();
        if (!self.atEnd() and (self.current().kind == .identifier or self.current().kind == .underscore)) {
            has_capture = true;
            capture_span = self.current().span;
            self.advance();
            self.skipTrivia();
        }
        if (!self.consume(.pipe)) try self.pushError(start_span, "expected closing '|' in match arm capture");
    }

    const body = try self.parseBlockOrExpr();
    const arm_span: Span = .{ .start = start_span.start, .end = self.nodes.items[body].span.end };
    return .{
        .kind = kind,
        .pat_start = pat_start,
        .pat_end = pat_end,
        .pat_payload = pat_payload,
        .inclusive = inclusive,
        .has_pat_payload = has_pat_payload,
        .body = body,
        .capture_span = capture_span,
        .has_capture = has_capture,
        .span = arm_span,
    };
}

fn parseBlockOrExpr(self: *Self) ParseAllocError!Ast.NodeId {
    self.skipTrivia();
    if (self.currentIs(.lbrace)) return self.parseBlockExpr();
    return self.parseAssignment();
}

fn parseBlockExpr(self: *Self) ParseAllocError!Ast.NodeId {
    const open = self.current();
    self.advance();

    var items: std.ArrayListUnmanaged(Ast.NodeId) = .empty;
    defer items.deinit(self.allocator);
    self.skipSeparators();
    while (!self.atEnd() and !self.currentIs(.rbrace)) {
        const item = (try self.parseItem()) orelse break;
        try items.append(self.allocator, item);
        self.skipSeparators();
    }

    const close_span = if (self.consume(.rbrace)) self.toks[self.i - 1].span else blk: {
        try self.pushError(open.span, "expected '}' to close block");
        break :blk open.span;
    };

    const item_start = self.list_items.items.len;
    try self.list_items.appendSlice(self.allocator, items.items);
    const item_count = items.items.len;
    return self.pushNode(.{
        .tag = .block,
        .span = .{ .start = open.span.start, .end = close_span.end },
        .data = .{ .block = .{ .item_start = @intCast(item_start), .item_count = @intCast(item_count) } },
    });
}

fn parseUseExpr(self: *Self) ParseAllocError!Ast.NodeId {
    const u = self.current();
    self.advance();
    self.skipTrivia();
    if (self.atEnd() or self.current().kind != .string) {
        return self.pushErrorNode(u.span, "expected string after 'use'");
    }
    const path_tok = self.current();
    self.advance();
    return self.pushNode(.{
        .tag = .use_expr,
        .span = .{ .start = u.span.start, .end = path_tok.span.end },
        .data = .{ .use_expr = .{ .path_span = path_tok.span } },
    });
}

fn parseModuleDecl(self: *Self) ParseAllocError!Ast.NodeId {
    const m = self.current();
    self.advance();
    self.skipTrivia();
    if (self.atEnd() or self.current().kind != .identifier) {
        return self.pushErrorNode(m.span, "expected module name after 'module'");
    }
    const name_tok = self.current();
    self.advance();
    return self.pushNode(.{
        .tag = .module_decl,
        .span = .{ .start = m.span.start, .end = name_tok.span.end },
        .data = .{ .module_decl = .{ .name_span = name_tok.span } },
    });
}

fn parseFnExprKeyword(self: *Self) ParseAllocError!Ast.NodeId {
    const fn_tok = self.current();
    self.advance();
    self.skipTrivia();

    if (!self.consume(.lparen)) return self.pushErrorNode(fn_tok.span, "expected '(' after 'fn'");
    var params: std.ArrayListUnmanaged(Ast.NodeId) = .empty;
    defer params.deinit(self.allocator);
    try self.parseParamListInto(&params);
    const param_start = self.list_items.items.len;
    try self.list_items.appendSlice(self.allocator, params.items);
    const param_count = params.items.len;

    const built = try self.finishFnExpr(fn_tok.span.start, param_start, param_count);
    return built;
}

fn parseExternFnExpr(self: *Self) ParseAllocError!Ast.NodeId {
    const ex_tok = self.current();
    self.advance();
    self.skipTrivia();

    if (!self.consume(.@"fn")) return self.pushErrorNode(ex_tok.span, "expected 'fn' after 'extern'");
    self.skipTrivia();
    if (!self.consume(.lparen)) return self.pushErrorNode(ex_tok.span, "expected '(' after 'extern fn'");

    var params: std.ArrayListUnmanaged(Ast.NodeId) = .empty;
    defer params.deinit(self.allocator);

    if (!self.consume(.rparen)) {
        while (!self.atEnd()) {
            const type_node = try self.parseAssignment();
            const p = try self.pushNode(.{ .tag = .param, .span = self.nodes.items[type_node].span, .data = .{ .param = .{
                .name_start = @intCast(self.param_name_items.items.len),
                .name_count = 0,
                .type_node = type_node,
                .default_node = Ast.NullNode,
                .has_type = true,
                .has_default = false,
                .is_comp = false,
            } } });
            try params.append(self.allocator, p);
            self.skipTrivia();
            if (self.consume(.comma)) {
                self.skipTrivia();
                if (self.currentIs(.rparen)) {
                    _ = self.consume(.rparen);
                    break;
                }
                continue;
            }
            if (!self.consume(.rparen)) try self.pushError(self.current().span, "expected ')' after extern parameter types");
            break;
        }
    }

    const param_start = self.list_items.items.len;
    try self.list_items.appendSlice(self.allocator, params.items);
    const param_count = params.items.len;

    self.skipTrivia();

    var has_ret = false;
    var ret_node: Ast.NodeId = Ast.NullNode;
    if (!self.atEnd() and !isHardTerminator(self.current().kind) and !self.currentIs(.comma) and !self.currentIs(.rbrace)) {
        has_ret = true;
        ret_node = try self.parseAssignment();
    }

    const end_off = if (has_ret) self.nodes.items[ret_node].span.end else self.toks[self.i - 1].span.end;
    return try self.pushNode(.{
        .tag = .fn_expr,
        .span = .{ .start = ex_tok.span.start, .end = end_off },
        .data = .{ .fn_expr = .{
            .param_start = @intCast(param_start),
            .param_count = @intCast(param_count),
            .ret_node = ret_node,
            .body = Ast.NullNode,
            .has_ret = has_ret,
            .has_body = false,
            .is_errorable = false,
            .is_extern = true,
            .concise = false,
        } },
    });
}

fn tryParseFnExprFromParen(self: *Self) ParseAllocError!?Ast.NodeId {
    const snap = Snapshot{
        .i = self.i,
        .nodes_len = self.nodes.items.len,
        .errors_len = self.errors.items.len,
        .list_len = self.list_items.items.len,
        .decl_name_len = self.decl_name_items.items.len,
        .param_name_len = self.param_name_items.items.len,
        .arms_len = self.match_arms.items.len,
    };

    const lparen = self.current();
    self.advance();
    var params: std.ArrayListUnmanaged(Ast.NodeId) = .empty;
    defer params.deinit(self.allocator);

    if (!self.tryParseParamListInto(&params)) {
        self.restoreSnapshot(snap);
        return null;
    }

    const param_start = self.list_items.items.len;
    try self.list_items.appendSlice(self.allocator, params.items);
    const param_count = params.items.len;

    const built = try self.tryFinishFnExpr(lparen.span.start, param_start, param_count);
    if (built == null) {
        self.restoreSnapshot(snap);
        return null;
    }
    return built;
}

fn finishFnExpr(self: *Self, start_off: usize, param_start: usize, param_count: usize) ParseAllocError!Ast.NodeId {
    return (try self.tryFinishFnExpr(start_off, param_start, param_count)) orelse unreachable;
}

fn tryFinishFnExpr(self: *Self, start_off: usize, param_start: usize, param_count: usize) ParseAllocError!?Ast.NodeId {
    self.skipTrivia();

    var is_errorable = false;
    if (self.currentIs(.not)) {
        is_errorable = true;
        self.advance();
        self.skipTrivia();
    }

    var has_ret = false;
    var ret_node: Ast.NodeId = Ast.NullNode;

    if (!self.currentIs(.lbrace) and !self.currentIs(.arrow)) {
        has_ret = true;
        ret_node = try self.parseAssignment();
        self.skipTrivia();
    }

    var concise = false;
    var body: Ast.NodeId = Ast.NullNode;
    if (self.consume(.arrow)) {
        concise = true;
        body = try self.parseAssignment();
    } else if (self.currentIs(.lbrace)) {
        body = try self.parseBlockExpr();
    } else {
        return null;
    }

    return try self.pushNode(.{
        .tag = .fn_expr,
        .span = .{ .start = start_off, .end = self.nodes.items[body].span.end },
        .data = .{ .fn_expr = .{
            .param_start = @intCast(param_start),
            .param_count = @intCast(param_count),
            .ret_node = ret_node,
            .body = body,
            .has_ret = has_ret,
            .has_body = true,
            .is_errorable = is_errorable,
            .is_extern = false,
            .concise = concise,
        } },
    });
}

fn parseParamListInto(self: *Self, params: *std.ArrayListUnmanaged(Ast.NodeId)) ParseAllocError!void {
    if (self.consume(.rparen)) return;
    while (!self.atEnd()) {
        const p = try self.parseOneParam();
        if (p != Ast.NullNode) try params.append(self.allocator, p);
        self.skipTrivia();
        if (self.consume(.comma)) {
            self.skipTrivia();
            if (self.currentIs(.rparen)) {
                _ = self.consume(.rparen);
                return;
            }
            continue;
        }
        break;
    }
    if (!self.consume(.rparen)) try self.pushError(self.current().span, "expected ')' after parameters");
}

fn tryParseParamListInto(self: *Self, params: *std.ArrayListUnmanaged(Ast.NodeId)) bool {
    if (self.consume(.rparen)) return true;
    while (!self.atEnd()) {
        const p = self.tryParseOneParam() orelse return false;
        params.append(self.allocator, p) catch return false;
        self.skipTrivia();
        if (self.consume(.comma)) {
            self.skipTrivia();
            if (self.currentIs(.rparen)) {
                _ = self.consume(.rparen);
                return true;
            }
            continue;
        }
        break;
    }
    return self.consume(.rparen);
}

fn parseOneParam(self: *Self) ParseAllocError!Ast.NodeId {
    const name_start = self.param_name_items.items.len;
    if (!self.currentIs(.identifier)) {
        _ = try self.pushErrorNode(self.current().span, "expected parameter name");
        return Ast.NullNode;
    }

    const id = try self.pushNode(.{ .tag = .identifier, .span = self.current().span, .data = .{ .none = {} } });
    try self.param_name_items.append(self.allocator, id);
    self.advance();
    self.skipTrivia();

    var has_type = false;
    var type_node: Ast.NodeId = Ast.NullNode;
    var is_comp = false;
    var has_default = false;
    var default_node: Ast.NodeId = Ast.NullNode;

    if (self.consume(.colon)) {
        has_type = true;
        self.skipTrivia();
        if (self.currentIs(.comp)) {
            is_comp = true;
            self.advance();
            self.skipTrivia();
        }
        type_node = try self.parseBinary(1);
    }

    self.skipTrivia();
    if (self.consume(.eq)) {
        has_default = true;
        default_node = try self.parseAssignment();
    }

    const count = self.param_name_items.items.len - name_start;
    const end_span = if (has_default) self.nodes.items[default_node].span.end else if (has_type) self.nodes.items[type_node].span.end else self.nodes.items[self.param_name_items.items[name_start + count - 1]].span.end;
    const p = try self.pushNode(.{
        .tag = .param,
        .span = .{ .start = self.nodes.items[self.param_name_items.items[name_start]].span.start, .end = end_span },
        .data = .{ .param = .{
            .name_start = @intCast(name_start),
            .name_count = @intCast(count),
            .type_node = type_node,
            .default_node = default_node,
            .has_type = has_type,
            .has_default = has_default,
            .is_comp = is_comp,
        } },
    });
    return p;
}

fn tryParseOneParam(self: *Self) ?Ast.NodeId {
    const snap = Snapshot{
        .i = self.i,
        .nodes_len = self.nodes.items.len,
        .errors_len = self.errors.items.len,
        .list_len = self.list_items.items.len,
        .decl_name_len = self.decl_name_items.items.len,
        .param_name_len = self.param_name_items.items.len,
        .arms_len = self.match_arms.items.len,
    };
    const p = self.parseOneParam() catch {
        self.restoreSnapshot(snap);
        return null;
    };
    if (p == Ast.NullNode) {
        self.restoreSnapshot(snap);
        return null;
    }
    return p;
}

fn tryParseDecl(self: *Self, is_pub: bool) ParseAllocError!?Ast.NodeId {
    const snap = Snapshot{
        .i = self.i,
        .nodes_len = self.nodes.items.len,
        .errors_len = self.errors.items.len,
        .list_len = self.list_items.items.len,
        .decl_name_len = self.decl_name_items.items.len,
        .param_name_len = self.param_name_items.items.len,
        .arms_len = self.match_arms.items.len,
    };

    var is_mut = false;
    if (self.currentIs(.mut)) {
        is_mut = true;
        self.advance();
        self.skipTrivia();
    }

    if (!self.currentIs(.identifier)) {
        self.restoreSnapshot(snap);
        return null;
    }

    const name_start = self.decl_name_items.items.len;
    while (true) {
        const id = try self.pushNode(.{ .tag = .identifier, .span = self.current().span, .data = .{ .none = {} } });
        try self.decl_name_items.append(self.allocator, id);
        self.advance();
        self.skipTrivia();
        if (self.consume(.comma)) {
            self.skipTrivia();
            if (!self.currentIs(.identifier)) break;
            continue;
        }
        break;
    }

    var has_type = false;
    var type_node: Ast.NodeId = Ast.NullNode;
    var has_init = false;
    var init_node: Ast.NodeId = Ast.NullNode;
    var is_define = false;

    if (self.currentIs(.lparen)) {
        var params: std.ArrayListUnmanaged(Ast.NodeId) = .empty;
        defer params.deinit(self.allocator);
        self.advance();
        try self.parseParamListInto(&params);
        const param_start = self.list_items.items.len;
        try self.list_items.appendSlice(self.allocator, params.items);
        init_node = try self.finishFnExpr(self.nodes.items[self.decl_name_items.items[name_start]].span.start, param_start, params.items.len);
        has_init = true;
        is_define = true;
    } else if (self.consume(.colon)) {
        if (self.consume(.eq)) {
            is_define = true;
            has_init = true;
            init_node = try self.parseAssignment();
        } else {
            has_type = true;
            type_node = try self.parseBinary(1);
            self.skipTrivia();
            if (self.consume(.eq)) {
                has_init = true;
                init_node = try self.parseAssignment();
            }
        }
    } else if (!has_init and is_mut and self.consume(.eq)) {
        has_init = true;
        init_node = try self.parseAssignment();
    } else if (!has_init) {
        self.restoreSnapshot(snap);
        return null;
    }

    const count = self.decl_name_items.items.len - name_start;
    const end_span = if (has_init) self.nodes.items[init_node].span.end else if (has_type) self.nodes.items[type_node].span.end else self.nodes.items[self.decl_name_items.items[name_start + count - 1]].span.end;
    return try self.pushNode(.{
        .tag = .decl,
        .span = .{ .start = self.nodes.items[self.decl_name_items.items[name_start]].span.start, .end = end_span },
        .data = .{ .decl = .{
            .name_start = @intCast(name_start),
            .name_count = @intCast(count),
            .type_node = type_node,
            .init_node = init_node,
            .is_mut = is_mut,
            .has_type = has_type,
            .has_init = has_init,
            .is_define = is_define,
            .is_pub = is_pub,
        } },
    });
}

const Snapshot = struct {
    i: usize,
    nodes_len: usize,
    errors_len: usize,
    list_len: usize,
    decl_name_len: usize,
    param_name_len: usize,
    arms_len: usize,
};

fn restoreSnapshot(self: *Self, snap: Snapshot) void {
    self.i = snap.i;
    self.nodes.items.len = snap.nodes_len;
    self.errors.items.len = snap.errors_len;
    self.list_items.items.len = snap.list_len;
    self.decl_name_items.items.len = snap.decl_name_len;
    self.param_name_items.items.len = snap.param_name_len;
    self.match_arms.items.len = snap.arms_len;
}

fn pushNode(self: *Self, node: Ast.Node) ParseAllocError!Ast.NodeId {
    try self.nodes.append(self.allocator, node);
    return @intCast(self.nodes.items.len - 1);
}

fn pushErrorNode(self: *Self, span: Span, msg: []const u8) ParseAllocError!Ast.NodeId {
    try self.pushError(span, msg);
    return self.pushNode(.{ .tag = .err, .span = span, .data = .{ .none = {} } });
}

fn pushError(self: *Self, span: Span, msg: []const u8) ParseAllocError!void {
    try self.errors.append(self.allocator, .{ .span = span, .message = msg });
}

fn precedence(kind: Tok.Kind) ?u8 {
    return switch (kind) {
        .lor, .@"or" => 1,
        .land => 2,
        .eqeq, .neq => 3,
        .lt, .lte, .gt, .gte => 4,
        .pipe => 5,
        .xor => 6,
        .@"and" => 7,
        .shl, .shr => 8,
        .range, .rangeq => 9,
        .add, .sub => 10,
        .mul, .div, .mod => 11,
        else => null,
    };
}

fn toBinaryOp(kind: Tok.Kind) ?Ast.BinaryOp {
    return switch (kind) {
        .mul => .mul,
        .div => .div,
        .mod => .mod,
        .add => .add,
        .sub => .sub,
        .shl => .shl,
        .shr => .shr,
        .@"and" => .bit_and,
        .xor => .bit_xor,
        .pipe => .bit_or,
        .lt => .lt,
        .lte => .lte,
        .gt => .gt,
        .gte => .gte,
        .eqeq => .eqeq,
        .neq => .neq,
        .land => .land,
        .lor, .@"or" => .lor,
        .range => .range,
        .rangeq => .rangeq,
        else => null,
    };
}

fn toAssignOp(kind: Tok.Kind) ?Ast.AssignOp {
    return switch (kind) {
        .eq => .eq,
        .addeq => .addeq,
        .subeq => .subeq,
        .muleq => .muleq,
        .diveq => .diveq,
        .modeq => .modeq,
        .andeq => .andeq,
        .pipeq => .pipeq,
        .xoreq => .xoreq,
        .shleq => .shleq,
        .shreq => .shreq,
        .compleq => .compleq,
        else => null,
    };
}

fn toUnaryOp(kind: Tok.Kind) ?Ast.UnaryOp {
    return switch (kind) {
        .sub => .neg,
        .not => .not,
        .complement => .complement,
        else => null,
    };
}

fn atEnd(self: *const Self) bool {
    return self.i >= self.toks.len;
}

fn current(self: *const Self) Tok {
    return self.toks[self.i];
}

fn currentIs(self: *const Self, kind: Tok.Kind) bool {
    return !self.atEnd() and self.current().kind == kind;
}

fn peekKind(self: *const Self, ahead: usize) ?Tok.Kind {
    const idx = self.i + ahead;
    if (idx >= self.toks.len) return null;
    return self.toks[idx].kind;
}

fn consume(self: *Self, kind: Tok.Kind) bool {
    if (self.currentIs(kind)) {
        self.i += 1;
        return true;
    }
    return false;
}

fn advance(self: *Self) void {
    if (!self.atEnd()) self.i += 1;
}

fn skipTrivia(self: *Self) void {
    while (!self.atEnd()) {
        switch (self.current().kind) {
            .newline, .semicolon, .line_comment, .doc_comment, .block_comment => self.advance(),
            else => return,
        }
    }
}

fn skipSeparators(self: *Self) void {
    while (!self.atEnd()) {
        switch (self.current().kind) {
            .newline, .semicolon, .comma, .line_comment, .doc_comment, .block_comment => self.advance(),
            else => return,
        }
    }
}

fn isHardTerminator(kind: Tok.Kind) bool {
    return switch (kind) {
        .newline, .semicolon, .comma, .rbrace => true,
        else => false,
    };
}

fn lexAll(allocator: std.mem.Allocator, src: []const u8) ![]Tok {
    var lx = Lexer.init(src);
    var toks: std.ArrayListUnmanaged(Tok) = .empty;
    errdefer toks.deinit(allocator);

    while (lx.next()) |tok| try toks.append(allocator, tok);
    return try toks.toOwnedSlice(allocator);
}

test "parse precedence expression" {
    const alloc = std.testing.allocator;
    const toks = try lexAll(alloc, "1 + 2 * 3");
    defer alloc.free(toks);

    var p = Self.init(alloc, toks);
    defer p.deinit();

    const root = (try p.parseExpr()).?;
    try std.testing.expect(!p.hasErrors());

    const root_node = p.nodes.items[root];
    try std.testing.expectEqual(Ast.Node.Tag.binary, root_node.tag);
    try std.testing.expectEqual(Ast.BinaryOp.add, root_node.data.binary.op);
}

test "parse postfix call and field" {
    const alloc = std.testing.allocator;
    const toks = try lexAll(alloc, "a.b(1, 2)");
    defer alloc.free(toks);

    var p = Self.init(alloc, toks);
    defer p.deinit();

    const root = (try p.parseExpr()).?;
    try std.testing.expect(!p.hasErrors());
    try std.testing.expectEqual(Ast.Node.Tag.call, p.nodes.items[root].tag);
}

test "parse if and match expression" {
    const alloc = std.testing.allocator;
    const src = "if 1 { 2 } else match x { 0..1: 3, _: 4 }";
    const toks = try lexAll(alloc, src);
    defer alloc.free(toks);

    var p = Self.init(alloc, toks);
    defer p.deinit();

    const root = (try p.parseExpr()).?;
    try std.testing.expect(!p.hasErrors());
    try std.testing.expectEqual(Ast.Node.Tag.if_expr, p.nodes.items[root].tag);
}

test "parse declarations and grouped typed names" {
    const alloc = std.testing.allocator;
    const src = "module main\nmut total = 0\nx, y: i32 = 1\nz := 3\n";
    const toks = try lexAll(alloc, src);
    defer alloc.free(toks);

    var p = Self.init(alloc, toks);
    defer p.deinit();

    const root = (try p.parseFile()).?;
    try std.testing.expect(!p.hasErrors());
    try std.testing.expectEqual(Ast.Node.Tag.block, p.nodes.items[root].tag);
}

test "parse function expression forms" {
    const alloc = std.testing.allocator;
    const src =
        "a := (x, y: i32) i32 => x + y\n" ++
        "b := fn() { 1 }\n" ++
        "puts := extern fn(*i32) i32\n";
    const toks = try lexAll(alloc, src);
    defer alloc.free(toks);

    var p = Self.init(alloc, toks);
    defer p.deinit();

    _ = (try p.parseFile()).?;
    try std.testing.expect(!p.hasErrors());
}

test "parse control flow statements" {
    const alloc = std.testing.allocator;
    const src =
        "for 0..10: |v| { break :blk 1 }\n" ++
        "for { continue }\n" ++
        "f := () i32 => { return 1 }\n" ++
        "blk: { defer |e| {} }\n" ++
        "L: for { continue:L }\n";
    const toks = try lexAll(alloc, src);
    defer alloc.free(toks);

    var p = Self.init(alloc, toks);
    defer p.deinit();

    const root = (try p.parseFile()).?;
    try std.testing.expect(!p.hasErrors());
    try std.testing.expectEqual(Ast.Node.Tag.block, p.nodes.items[root].tag);

    var saw_labeled_for = false;
    var saw_return = false;
    for (p.nodes.items) |n| {
        if (n.tag == .return_stmt) saw_return = true;
        if (n.tag == .labeled_block) {
            const body = p.nodes.items[n.data.labeled_block.body];
            if (body.tag == .for_stmt) {
                saw_labeled_for = true;
                break;
            }
        }
    }
    try std.testing.expect(saw_labeled_for);
    try std.testing.expect(saw_return);
}

test "parse if binding and match arm captures" {
    const alloc = std.testing.allocator;
    const src =
        "if q: |val| { val } else 0\n" ++
        "match res { .variant3: |i| i, _: 0 }\n";
    const toks = try lexAll(alloc, src);
    defer alloc.free(toks);

    var p = Self.init(alloc, toks);
    defer p.deinit();

    _ = (try p.parseFile()).?;
    try std.testing.expect(!p.hasErrors());
    try std.testing.expect(p.match_arms.items.len >= 2);
    try std.testing.expect(p.match_arms.items[0].has_capture);
}

test "parse pub declarations and variant payload pattern" {
    const alloc = std.testing.allocator;
    const src =
        "pub add := (x: i32) i32 => x\n" ++
        "match res { .Ok(val): |v| v, _: 0 }\n";
    const toks = try lexAll(alloc, src);
    defer alloc.free(toks);

    var p = Self.init(alloc, toks);
    defer p.deinit();

    const root = (try p.parseFile()).?;
    try std.testing.expect(!p.hasErrors());
    try std.testing.expectEqual(Ast.Node.Tag.block, p.nodes.items[root].tag);
    try std.testing.expect(p.match_arms.items.len >= 2);
    try std.testing.expect(p.match_arms.items[0].has_pat_payload);

    var found_pub_decl = false;
    for (p.nodes.items) |n| {
        if (n.tag == .decl and n.data.decl.is_pub) {
            found_pub_decl = true;
            break;
        }
    }
    try std.testing.expect(found_pub_decl);
}

test "parse struct and enum declaration bodies" {
    const alloc = std.testing.allocator;
    const src =
        "Thing := struct {\n" ++
        "  item1, item2: u32,\n" ++
        "  mk := () type => type,\n" ++
        "}\n" ++
        "Res := enum {\n" ++
        "  Ok,\n" ++
        "  Err: i32,\n" ++
        "}\n";
    const toks = try lexAll(alloc, src);
    defer alloc.free(toks);

    var p = Self.init(alloc, toks);
    defer p.deinit();

    _ = (try p.parseFile()).?;
    try std.testing.expect(!p.hasErrors());

    var saw_struct = false;
    var saw_enum = false;
    for (p.nodes.items) |n| {
        if (n.tag == .struct_expr) saw_struct = true;
        if (n.tag == .enum_expr) saw_enum = true;
    }
    try std.testing.expect(saw_struct);
    try std.testing.expect(saw_enum);
}

test "parse edge-case if/match/for bindings" {
    const alloc = std.testing.allocator;
    const src =
        "if q: |_| 1 else 2\n" ++
        "match r { .Ok(v): |x| x, .Err: |_| 0, _: 3 }\n" ++
        "for items: |_| { continue }\n";
    const toks = try lexAll(alloc, src);
    defer alloc.free(toks);

    var p = Self.init(alloc, toks);
    defer p.deinit();

    _ = (try p.parseFile()).?;
    try std.testing.expect(!p.hasErrors());
    try std.testing.expect(p.match_arms.items.len >= 3);
}

test "parse postfix unwrap and deref forms" {
    const alloc = std.testing.allocator;
    const src = "module main\na := x.?\nb := y.!\nc := p.*\n";
    const toks = try lexAll(alloc, src);
    defer alloc.free(toks);

    var p = Self.init(alloc, toks);
    defer p.deinit();

    _ = (try p.parseFile()).?;
    try std.testing.expect(!p.hasErrors());
}

test "parse slice and array type annotations" {
    const alloc = std.testing.allocator;
    const src = "module main\na: []u8 = \"x\"\nb: [4]u8 = \"test\"\n";
    const toks = try lexAll(alloc, src);
    defer alloc.free(toks);

    var p = Self.init(alloc, toks);
    defer p.deinit();

    _ = (try p.parseFile()).?;
    try std.testing.expect(!p.hasErrors());

    var saw_slice = false;
    var saw_array = false;
    for (p.nodes.items) |n| {
        if (n.tag == .slice_type) saw_slice = true;
        if (n.tag == .array_type) saw_array = true;
    }
    try std.testing.expect(saw_slice);
    try std.testing.expect(saw_array);
}

test "parse slice expression with range syntax in brackets" {
    const alloc = std.testing.allocator;
    const src = "f := () { x := p[0..n] }\n";
    const toks = try lexAll(alloc, src);
    defer alloc.free(toks);

    var p = Self.init(alloc, toks);
    defer p.deinit();

    _ = (try p.parseFile()).?;
    try std.testing.expect(!p.hasErrors());

    var saw_slice = false;
    for (p.nodes.items) |n| {
        if (n.tag == .slice) saw_slice = true;
    }
    try std.testing.expect(saw_slice);
}

test "parse optional and postfix error type annotations" {
    const alloc = std.testing.allocator;
    const src =
        "a: ?i32 = 1\n" ++
        "b: i32! = 1\n" ++
        "c: f32!DivideError1 = 1\n" ++
        "d: f32! DivideError1, DivideError2 = 1\n";

    const toks = try lexAll(alloc, src);
    defer alloc.free(toks);

    var p = Self.init(alloc, toks);
    defer p.deinit();
    const root = (try p.parseFile()).?;
    try std.testing.expect(!p.hasErrors());
    try std.testing.expectEqual(Ast.Node.Tag.block, p.nodes.items[root].tag);

    var saw_error_type = false;
    for (p.nodes.items) |n| {
        if (n.tag == .error_type) saw_error_type = true;
    }
    try std.testing.expect(saw_error_type);
}

test "parse malformed postfix error type annotations" {
    const alloc = std.testing.allocator;
    const src =
        "a: f32!DivideError1, = 1\n" ++
        "b: f32!DivideError1,,DivideError2 = 1\n" ++
        "c: f32!123 = 1\n";

    const toks = try lexAll(alloc, src);
    defer alloc.free(toks);

    var p = Self.init(alloc, toks);
    defer p.deinit();

    _ = (try p.parseFile()).?;
    try std.testing.expect(p.hasErrors());
    try std.testing.expect(p.errors.items.len >= 3);
}

test "parse inline and comp expressions" {
    const alloc = std.testing.allocator;
    const src = "module main\nmain := () i32 => comp inline (1 + 2)\n";
    const toks = try lexAll(alloc, src);
    defer alloc.free(toks);

    var p = Self.init(alloc, toks);
    defer p.deinit();

    _ = (try p.parseFile()).?;
    try std.testing.expect(!p.hasErrors());

    var saw_inline = false;
    var saw_comp = false;
    for (p.nodes.items) |n| {
        if (n.tag == .inline_expr) saw_inline = true;
        if (n.tag == .comp_expr) saw_comp = true;
    }
    try std.testing.expect(saw_inline);
    try std.testing.expect(saw_comp);
}

test "parse struct method declaration shorthand" {
    const alloc = std.testing.allocator;
    const src =
        "module main\n" ++
        "Thing := struct {\n" ++
        "  do_thing(s: i32, b: i32) i32 => b + 1\n" ++
        "}\n";
    const toks = try lexAll(alloc, src);
    defer alloc.free(toks);

    var p = Self.init(alloc, toks);
    defer p.deinit();

    _ = (try p.parseFile()).?;
    try std.testing.expect(!p.hasErrors());
}
