const std = @import("std");
const Ast = @import("ast.zig");
const Span = @import("token.zig").Span;
const ModuleGraph = @import("module_graph.zig");

pub const Type = enum {
    unknown,
    void_t,
    bool_t,
    int_t,
    float_t,
    string_t,
    char_t,
    type_t,
    module_t,
    fn_t,
    struct_t,
    enum_t,
    ptr_to_unknown_t,
    ptr_mut_to_unknown_t,
    ptr_to_int_t,
    ptr_mut_to_int_t,
    ptr_to_float_t,
    ptr_mut_to_float_t,
    ptr_to_bool_t,
    ptr_mut_to_bool_t,
    ptr_to_string_t,
    ptr_mut_to_string_t,
    ptr_to_char_t,
    ptr_mut_to_char_t,
    ptr_to_optional_t,
    ptr_mut_to_optional_t,
    ptr_to_error_t,
    ptr_mut_to_error_t,
    optional_t,
    error_t,
};

pub const SemanticError = struct {
    file_id: @import("source_manager.zig").FileId,
    span: Span,
    message: []u8,
};

pub const Self = @This();

const SemError = anyerror;

allocator: std.mem.Allocator,
errors: std.ArrayListUnmanaged(SemanticError) = .empty,

const FnBinding = struct {
    file_index: u32,
    node_id: Ast.NodeId,
};

const Binding = struct {
    ty: Type,
    mutable: bool,
};

const Ctx = struct {
    scope_depth: usize = 0,
    loop_depth: usize = 0,
};

pub fn init(allocator: std.mem.Allocator) Self {
    return .{ .allocator = allocator };
}

pub fn deinit(self: *Self) void {
    for (self.errors.items) |e| self.allocator.free(e.message);
    self.errors.deinit(self.allocator);
}

pub fn checkGraph(self: *Self, graph: *ModuleGraph.Self) SemError!void {
    var m: u32 = 0;
    while (m < graph.modules.items.len) : (m += 1) {
        try self.checkModule(graph, m);
    }
}

fn checkModule(self: *Self, graph: *ModuleGraph.Self, module_index: u32) SemError!void {
    var env: std.StringHashMapUnmanaged(Binding) = .empty;
    defer env.deinit(self.allocator);
    var fn_bindings: std.StringHashMapUnmanaged(FnBinding) = .empty;
    defer fn_bindings.deinit(self.allocator);

    const mod = graph.modules.items[module_index];
    var mf: u32 = 0;
    while (mf < mod.file_count) : (mf += 1) {
        const file_idx = graph.module_file_indices.items[mod.file_start + mf];
        const f = graph.files.items[file_idx];
        const root = f.root orelse continue;
        const rn = f.nodes[root];
        if (rn.tag != .block) continue;

        var i: u32 = 0;
        while (i < rn.data.block.item_count) : (i += 1) {
            const item = f.nodes[f.list_items[rn.data.block.item_start + i]];
            if (item.tag != .decl) continue;
            var j: u32 = 0;
            while (j < item.data.decl.name_count) : (j += 1) {
                const ident = f.nodes[f.decl_name_items[item.data.decl.name_start + j]];
                try graph.sm.ensureTextLoaded(f.file_id);
                const name = graph.sm.spanSlice(f.file_id, ident.span) catch continue;
                if (env.get(name) == null) try env.put(self.allocator, name, .{ .ty = .unknown, .mutable = false });
                if (item.data.decl.has_init) {
                    const init_n = f.nodes[item.data.decl.init_node];
                    if (init_n.tag == .fn_expr and fn_bindings.get(name) == null) {
                        try fn_bindings.put(self.allocator, name, .{ .file_index = file_idx, .node_id = item.data.decl.init_node });
                        try env.put(self.allocator, name, .{ .ty = .fn_t, .mutable = item.data.decl.is_mut });
                    }
                }
            }
        }
    }

    mf = 0;
    while (mf < mod.file_count) : (mf += 1) {
        const file_idx = graph.module_file_indices.items[mod.file_start + mf];
        try self.checkFile(graph, file_idx, &env, &fn_bindings);
    }
}

fn checkFile(
    self: *Self,
    graph: *ModuleGraph.Self,
    file_idx: u32,
    module_env: *std.StringHashMapUnmanaged(Binding),
    fn_bindings: *std.StringHashMapUnmanaged(FnBinding),
) SemError!void {
    const f = graph.files.items[file_idx];
    const root = f.root orelse return;
    const rn = f.nodes[root];
    if (rn.tag != .block) return;

    var env = try cloneEnv(self.allocator, module_env);
    defer env.deinit(self.allocator);

    var ctx = Ctx{};
    var i: u32 = 0;
    while (i < rn.data.block.item_count) : (i += 1) {
        const item_id = f.list_items[rn.data.block.item_start + i];
        _ = try self.inferNode(graph, f, item_id, &env, fn_bindings, &ctx);
    }

    var it = env.iterator();
    while (it.next()) |e| try module_env.put(self.allocator, e.key_ptr.*, e.value_ptr.*);
}

fn inferNode(
    self: *Self,
    graph: *ModuleGraph.Self,
    f: ModuleGraph.FileUnit,
    id: Ast.NodeId,
    env: *std.StringHashMapUnmanaged(Binding),
    fn_bindings: *std.StringHashMapUnmanaged(FnBinding),
    ctx: *Ctx,
) SemError!Type {
    const n = f.nodes[id];
    return switch (n.tag) {
        .int_lit => .int_t,
        .float_lit => .float_t,
        .string_lit => .string_t,
        .char_lit => .char_t,
        .type_lit => .type_t,
        .use_expr => .module_t,
        .identifier => blk: {
            try graph.sm.ensureTextLoaded(f.file_id);
            const name = graph.sm.spanSlice(f.file_id, n.span) catch break :blk .unknown;
            break :blk if (env.get(name)) |bnd| bnd.ty else b: {
                try self.pushErr(f.file_id, n.span, "unknown identifier");
                break :b .unknown;
            };
        },
        .unary => blk: {
            const rt = try self.inferNode(graph, f, n.data.unary.rhs, env, fn_bindings, ctx);
            break :blk switch (n.data.unary.op) {
                .neg => if (rt == .int_t or rt == .float_t) rt else b: {
                    try self.pushErr(f.file_id, n.span, "unary '-' expects numeric operand");
                    break :b .unknown;
                },
                .complement => if (rt == .int_t) .int_t else b: {
                    try self.pushErr(f.file_id, n.span, "'~' expects integer operand");
                    break :b .unknown;
                },
                .not => if (rt == .bool_t) .bool_t else b: {
                    try self.pushErr(f.file_id, n.span, "'!' expects bool operand");
                    break :b .unknown;
                },
            };
        },
        .binary => try self.inferBinary(graph, f, n, env, fn_bindings, ctx),
        .assign => blk: {
            const lhs_node = f.nodes[n.data.assign.lhs];
            if (lhs_node.tag == .identifier) {
                const lhs_ident = lhs_node;
                const lhs_name = graph.sm.spanSlice(f.file_id, lhs_ident.span) catch "";
                if (env.get(lhs_name)) |bnd| {
                    if (!bnd.mutable) try self.pushErr(f.file_id, lhs_ident.span, "cannot assign to immutable binding");
                }
            } else if (lhs_node.tag == .deref) {
                const ptr_ty = try self.inferNode(graph, f, lhs_node.data.one.child, env, fn_bindings, ctx);
                if (isImmutablePointerType(ptr_ty)) {
                    try self.pushErr(f.file_id, n.span, "cannot assign through immutable pointer");
                } else if (!isPointerType(ptr_ty) and ptr_ty != .unknown) {
                    try self.pushErr(f.file_id, n.span, "left-hand side dereference must be a pointer");
                }
            } else {
                try self.pushErr(f.file_id, lhs_node.span, "invalid assignment target");
            }
            const lt = try self.inferNode(graph, f, n.data.assign.lhs, env, fn_bindings, ctx);
            const rt = try self.inferNode(graph, f, n.data.assign.rhs, env, fn_bindings, ctx);
            if (!compatible(lt, rt)) try self.pushErr(f.file_id, n.span, "assignment type mismatch");
            break :blk if (lt == .unknown) rt else lt;
        },
        .address_of => blk: {
            const child = f.nodes[n.data.one.child];
            if (child.tag == .identifier) {
                const name = graph.sm.spanSlice(f.file_id, child.span) catch break :blk .ptr_to_unknown_t;
                if (env.get(name)) |bnd| {
                    break :blk makePointerType(bnd.ty, bnd.mutable);
                }
            }
            _ = try self.inferNode(graph, f, n.data.one.child, env, fn_bindings, ctx);
            break :blk .ptr_to_unknown_t;
        },
        .ptr_type => .type_t,
        .field => .unknown,
        .call => blk: {
            const callee_t = try self.inferNode(graph, f, n.data.call.callee, env, fn_bindings, ctx);
            var i: u32 = 0;
            while (i < n.data.call.arg_count) : (i += 1) {
                _ = try self.inferNode(graph, f, f.list_items[n.data.call.arg_start + i], env, fn_bindings, ctx);
            }

            if (try self.resolveCalleeFnExprNode(graph, f, n.data.call.callee, fn_bindings)) |binding| {
                const fn_file = graph.files.items[binding.file_index];
                const fn_n = fn_file.nodes[binding.node_id];
                const expected = fn_n.data.fn_expr.param_count;
                if (n.data.call.arg_count != expected) {
                    try self.pushErr(f.file_id, n.span, "function call argument count mismatch");
                } else {
                    var pi: u32 = 0;
                    while (pi < expected) : (pi += 1) {
                        const p_node = fn_file.nodes[fn_file.list_items[fn_n.data.fn_expr.param_start + pi]];
                        if (p_node.tag != .param or !p_node.data.param.has_type) continue;
                        const pt = try self.typeFromAnnotation(graph, fn_file, p_node.data.param.type_node, env, fn_bindings, ctx);
                        const arg_t = try self.inferNode(graph, f, f.list_items[n.data.call.arg_start + pi], env, fn_bindings, ctx);
                        if (!compatible(pt, arg_t)) try self.pushErr(f.file_id, n.span, "function argument type mismatch");
                    }
                }
                if (fn_n.data.fn_expr.has_ret) {
                    break :blk try self.typeFromAnnotation(graph, fn_file, fn_n.data.fn_expr.ret_node, env, fn_bindings, ctx);
                }
                break :blk .unknown;
            }
            if (callee_t != .unknown and callee_t != .fn_t) {
                try self.pushErr(f.file_id, n.span, "attempted to call non-function value");
                break :blk .unknown;
            }
            break :blk callee_t;
        },
        .index => .unknown,
        .slice => .unknown,
        .if_expr => blk: {
            const ct = try self.inferNode(graph, f, n.data.if_expr.cond, env, fn_bindings, ctx);
            if (ct != .unknown and ct != .bool_t) try self.pushErr(f.file_id, n.span, "if condition must be bool");
            const tt = try self.inferNode(graph, f, n.data.if_expr.then_expr, env, fn_bindings, ctx);
            if (!n.data.if_expr.has_else) break :blk .void_t;
            const et = try self.inferNode(graph, f, n.data.if_expr.else_expr, env, fn_bindings, ctx);
            if (!compatible(tt, et)) try self.pushErr(f.file_id, n.span, "if branches must have compatible types");
            break :blk mergeType(tt, et);
        },
        .match_expr => blk: {
            _ = try self.inferNode(graph, f, n.data.match_expr.subject, env, fn_bindings, ctx);
            var out: Type = .unknown;
            var i: u32 = 0;
            while (i < n.data.match_expr.arm_count) : (i += 1) {
                const arm = f.match_arms[n.data.match_expr.arm_start + i];
                if (arm.pat_start != Ast.NullNode) _ = try self.inferNode(graph, f, arm.pat_start, env, fn_bindings, ctx);
                if (arm.pat_end != Ast.NullNode) _ = try self.inferNode(graph, f, arm.pat_end, env, fn_bindings, ctx);
                if (arm.has_pat_payload) _ = try self.inferNode(graph, f, arm.pat_payload, env, fn_bindings, ctx);
                const bt = try self.inferNode(graph, f, arm.body, env, fn_bindings, ctx);
                out = if (out == .unknown) bt else mergeType(out, bt);
            }
            break :blk out;
        },
        .block => blk: {
            var local = try cloneEnv(self.allocator, env);
            defer local.deinit(self.allocator);
            var child_ctx = ctx.*;
            child_ctx.scope_depth += 1;
            var out: Type = .void_t;
            var terminated = false;
            var i: u32 = 0;
            while (i < n.data.block.item_count) : (i += 1) {
                const item_id = f.list_items[n.data.block.item_start + i];
                if (terminated) {
                    try self.pushErr(f.file_id, f.nodes[item_id].span, "unreachable statement");
                }
                out = try self.inferNode(graph, f, item_id, &local, fn_bindings, &child_ctx);
                const item_n = f.nodes[item_id];
                if (item_n.tag == .break_stmt or item_n.tag == .continue_stmt) terminated = true;
            }
            break :blk out;
        },
        .struct_expr => blk: {
            try self.checkAggregateDuplicates(graph, f, n, false);
            break :blk .struct_t;
        },
        .enum_expr => blk: {
            try self.checkAggregateDuplicates(graph, f, n, true);
            break :blk .enum_t;
        },
        .decl => blk: {
            const expected = if (n.data.decl.has_type) try self.typeFromAnnotation(graph, f, n.data.decl.type_node, env, fn_bindings, ctx) else .unknown;
            const init_t = if (n.data.decl.has_init) try self.inferNode(graph, f, n.data.decl.init_node, env, fn_bindings, ctx) else .unknown;
            if (n.data.decl.has_type and n.data.decl.has_init and !compatible(expected, init_t)) {
                try self.pushErr(f.file_id, n.span, "declaration type does not match initializer");
            }
            const final_t = if (expected != .unknown) expected else init_t;
            var j: u32 = 0;
            while (j < n.data.decl.name_count) : (j += 1) {
                const ident = f.nodes[f.decl_name_items[n.data.decl.name_start + j]];
                try graph.sm.ensureTextLoaded(f.file_id);
                const name = graph.sm.spanSlice(f.file_id, ident.span) catch continue;
                if (ctx.scope_depth > 0 and env.get(name) != null) {
                    try self.pushErr(f.file_id, ident.span, "declaration shadows outer name");
                }
                try env.put(self.allocator, name, .{ .ty = final_t, .mutable = n.data.decl.is_mut });
            }
            break :blk .void_t;
        },
        .fn_expr => blk: {
            var fn_env = try cloneEnv(self.allocator, env);
            defer fn_env.deinit(self.allocator);
            var fn_ctx = ctx.*;

            var i: u32 = 0;
            while (i < n.data.fn_expr.param_count) : (i += 1) {
                const p = f.nodes[f.list_items[n.data.fn_expr.param_start + i]];
                if (p.tag != .param) continue;
                const pt = if (p.data.param.has_type) try self.typeFromAnnotation(graph, f, p.data.param.type_node, &fn_env, fn_bindings, &fn_ctx) else .unknown;
                var j: u32 = 0;
                while (j < p.data.param.name_count) : (j += 1) {
                    const name_node = f.nodes[f.param_name_items[p.data.param.name_start + j]];
                    try graph.sm.ensureTextLoaded(f.file_id);
                    const name = graph.sm.spanSlice(f.file_id, name_node.span) catch continue;
                    try fn_env.put(self.allocator, name, .{ .ty = pt, .mutable = false });
                }
            }

            const bt = try self.inferNode(graph, f, n.data.fn_expr.body, &fn_env, fn_bindings, &fn_ctx);
            if (n.data.fn_expr.has_ret) {
                const rt = try self.typeFromAnnotation(graph, f, n.data.fn_expr.ret_node, &fn_env, fn_bindings, &fn_ctx);
                if (!compatible(rt, bt)) try self.pushErr(f.file_id, n.span, "function body type does not match return type");
                if (!nodeGuaranteesValue(f, n.data.fn_expr.body)) {
                    try self.pushErr(f.file_id, n.span, "function with return type must return a value on all paths");
                }
            }
            break :blk .fn_t;
        },
        .param => .void_t,
        .for_stmt => blk: {
            var loop_ctx = ctx.*;
            loop_ctx.loop_depth += 1;
            if (!n.data.for_stmt.is_infinite and n.data.for_stmt.cond != Ast.NullNode) {
                const cond_t = try self.inferNode(graph, f, n.data.for_stmt.cond, env, fn_bindings, &loop_ctx);
                if (cond_t != .unknown and cond_t != .bool_t) {
                    try self.pushErr(f.file_id, n.span, "for condition must be bool");
                }
            }
            _ = try self.inferNode(graph, f, n.data.for_stmt.body, env, fn_bindings, &loop_ctx);
            break :blk .void_t;
        },
        .break_stmt => blk: {
            if (ctx.loop_depth == 0) try self.pushErr(f.file_id, n.span, "'break' used outside loop");
            if (n.data.break_stmt.has_value) _ = try self.inferNode(graph, f, n.data.break_stmt.value, env, fn_bindings, ctx);
            break :blk .void_t;
        },
        .continue_stmt => blk: {
            if (ctx.loop_depth == 0) try self.pushErr(f.file_id, n.span, "'continue' used outside loop");
            break :blk .void_t;
        },
        .defer_stmt => blk: {
            _ = try self.inferNode(graph, f, n.data.defer_stmt.value, env, fn_bindings, ctx);
            break :blk .void_t;
        },
        .labeled_block => blk: {
            _ = try self.inferNode(graph, f, n.data.labeled_block.body, env, fn_bindings, ctx);
            break :blk .void_t;
        },
        .unwrap_optional => blk: {
            const ct = try self.inferNode(graph, f, n.data.one.child, env, fn_bindings, ctx);
            if (ct == .optional_t or ct == .unknown) break :blk .unknown;
            try self.pushErr(f.file_id, n.span, "'.?' expects optional value");
            break :blk .unknown;
        },
        .unwrap_error => blk: {
            const ct = try self.inferNode(graph, f, n.data.one.child, env, fn_bindings, ctx);
            if (ct == .error_t or ct == .unknown) break :blk .unknown;
            try self.pushErr(f.file_id, n.span, "'.!' expects error value");
            break :blk .unknown;
        },
        .deref => blk: {
            const pt = try self.inferNode(graph, f, n.data.one.child, env, fn_bindings, ctx);
            if (pt == .unknown) break :blk .unknown;
            if (isPointerType(pt)) break :blk pointerElementType(pt);
            try self.pushErr(f.file_id, n.span, "'.*' expects pointer value");
            break :blk .unknown;
        },
        .module_decl, .err => .unknown,
    };
}

fn inferBinary(
    self: *Self,
    graph: *ModuleGraph.Self,
    f: ModuleGraph.FileUnit,
    n: Ast.Node,
    env: *std.StringHashMapUnmanaged(Binding),
    fn_bindings: *std.StringHashMapUnmanaged(FnBinding),
    ctx: *Ctx,
) SemError!Type {
    const lt = try self.inferNode(graph, f, n.data.binary.lhs, env, fn_bindings, ctx);
    const rt = try self.inferNode(graph, f, n.data.binary.rhs, env, fn_bindings, ctx);
    return switch (n.data.binary.op) {
        .add, .sub, .mul, .div, .mod => if (isNumeric(lt) and isNumeric(rt)) mergeType(lt, rt) else b: {
            try self.pushErr(f.file_id, n.span, "numeric operator expects numeric operands");
            break :b .unknown;
        },
        .lt, .lte, .gt, .gte => if ((isNumeric(lt) and isNumeric(rt)) or compatible(lt, rt)) .bool_t else b: {
            try self.pushErr(f.file_id, n.span, "comparison operands are not compatible");
            break :b .unknown;
        },
        .eqeq, .neq => if (compatible(lt, rt)) .bool_t else b: {
            try self.pushErr(f.file_id, n.span, "equality operands are not compatible");
            break :b .unknown;
        },
        .land, .lor => if (lt == .bool_t and rt == .bool_t) .bool_t else b: {
            try self.pushErr(f.file_id, n.span, "logical operator expects bool operands");
            break :b .unknown;
        },
        else => .unknown,
    };
}

fn typeFromAnnotation(
    self: *Self,
    graph: *ModuleGraph.Self,
    f: ModuleGraph.FileUnit,
    node_id: Ast.NodeId,
    env: *std.StringHashMapUnmanaged(Binding),
    fn_bindings: *std.StringHashMapUnmanaged(FnBinding),
    ctx: *Ctx,
) SemError!Type {
    const n = f.nodes[node_id];
    return switch (n.tag) {
        .type_lit => .type_t,
        .identifier => blk: {
            try graph.sm.ensureTextLoaded(f.file_id);
            const name = graph.sm.spanSlice(f.file_id, n.span) catch break :blk .unknown;
            if (std.mem.eql(u8, name, "i32") or std.mem.eql(u8, name, "i64") or std.mem.eql(u8, name, "u32") or std.mem.eql(u8, name, "u64") or std.mem.eql(u8, name, "usize") or std.mem.eql(u8, name, "isize")) break :blk .int_t;
            if (std.mem.eql(u8, name, "f32") or std.mem.eql(u8, name, "f64")) break :blk .float_t;
            if (std.mem.eql(u8, name, "bool")) break :blk .bool_t;
            if (std.mem.eql(u8, name, "char")) break :blk .char_t;
            if (std.mem.eql(u8, name, "string") or std.mem.eql(u8, name, "str")) break :blk .string_t;
            if (std.mem.eql(u8, name, "optional")) break :blk .optional_t;
            if (std.mem.eql(u8, name, "error")) break :blk .error_t;
            break :blk if (env.get(name)) |bnd| bnd.ty else .unknown;
        },
        .ptr_type => blk: {
            const child_t = try self.typeFromAnnotation(graph, f, n.data.ptr_type.child, env, fn_bindings, ctx);
            break :blk makePointerType(child_t, n.data.ptr_type.mutable);
        },
        else => try self.inferNode(graph, f, node_id, env, fn_bindings, ctx),
    };
}

fn makePointerType(elem: Type, mutable: bool) Type {
    return switch (elem) {
        .int_t => if (mutable) .ptr_mut_to_int_t else .ptr_to_int_t,
        .float_t => if (mutable) .ptr_mut_to_float_t else .ptr_to_float_t,
        .bool_t => if (mutable) .ptr_mut_to_bool_t else .ptr_to_bool_t,
        .string_t => if (mutable) .ptr_mut_to_string_t else .ptr_to_string_t,
        .char_t => if (mutable) .ptr_mut_to_char_t else .ptr_to_char_t,
        .optional_t => if (mutable) .ptr_mut_to_optional_t else .ptr_to_optional_t,
        .error_t => if (mutable) .ptr_mut_to_error_t else .ptr_to_error_t,
        else => if (mutable) .ptr_mut_to_unknown_t else .ptr_to_unknown_t,
    };
}

fn pointerElementType(t: Type) Type {
    return switch (t) {
        .ptr_to_int_t, .ptr_mut_to_int_t => .int_t,
        .ptr_to_float_t, .ptr_mut_to_float_t => .float_t,
        .ptr_to_bool_t, .ptr_mut_to_bool_t => .bool_t,
        .ptr_to_string_t, .ptr_mut_to_string_t => .string_t,
        .ptr_to_char_t, .ptr_mut_to_char_t => .char_t,
        .ptr_to_optional_t, .ptr_mut_to_optional_t => .optional_t,
        .ptr_to_error_t, .ptr_mut_to_error_t => .error_t,
        else => .unknown,
    };
}

fn isImmutablePointerType(t: Type) bool {
    return switch (t) {
        .ptr_to_unknown_t,
        .ptr_to_int_t,
        .ptr_to_float_t,
        .ptr_to_bool_t,
        .ptr_to_string_t,
        .ptr_to_char_t,
        .ptr_to_optional_t,
        .ptr_to_error_t,
        => true,
        else => false,
    };
}

fn isPointerType(t: Type) bool {
    return switch (t) {
        .ptr_to_unknown_t,
        .ptr_mut_to_unknown_t,
        .ptr_to_int_t,
        .ptr_mut_to_int_t,
        .ptr_to_float_t,
        .ptr_mut_to_float_t,
        .ptr_to_bool_t,
        .ptr_mut_to_bool_t,
        .ptr_to_string_t,
        .ptr_mut_to_string_t,
        .ptr_to_char_t,
        .ptr_mut_to_char_t,
        .ptr_to_optional_t,
        .ptr_mut_to_optional_t,
        .ptr_to_error_t,
        .ptr_mut_to_error_t,
        => true,
        else => false,
    };
}

fn resolveCalleeFnExprNode(
    self: *Self,
    graph: *ModuleGraph.Self,
    f: ModuleGraph.FileUnit,
    callee_id: Ast.NodeId,
    fn_bindings: *std.StringHashMapUnmanaged(FnBinding),
) SemError!?FnBinding {
    _ = self;
    const n = f.nodes[callee_id];
    if (n.tag == .fn_expr) return .{ .file_index = findFileIndex(graph, f.file_id) orelse return null, .node_id = callee_id };
    if (n.tag != .identifier) return null;
    const name = graph.sm.spanSlice(f.file_id, n.span) catch return null;
    return fn_bindings.get(name);
}

fn findFileIndex(graph: *ModuleGraph.Self, file_id: @import("source_manager.zig").FileId) ?u32 {
    var i: u32 = 0;
    while (i < graph.files.items.len) : (i += 1) {
        if (graph.files.items[i].file_id == file_id) return i;
    }
    return null;
}

fn checkAggregateDuplicates(self: *Self, graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, n: Ast.Node, is_enum: bool) SemError!void {
    var seen: std.StringHashMapUnmanaged(void) = .empty;
    defer seen.deinit(self.allocator);

    const agg = n.data.aggregate;
    var i: u32 = 0;
    while (i < agg.item_count) : (i += 1) {
        const item = f.nodes[f.list_items[agg.item_start + i]];
        if (item.tag != .decl) continue;
        var j: u32 = 0;
        while (j < item.data.decl.name_count) : (j += 1) {
            const ident = f.nodes[f.decl_name_items[item.data.decl.name_start + j]];
            const name = graph.sm.spanSlice(f.file_id, ident.span) catch continue;
            if (seen.get(name) != null) {
                try self.pushErr(f.file_id, ident.span, if (is_enum) "duplicate enum member" else "duplicate struct member");
            } else {
                try seen.put(self.allocator, name, {});
            }
        }
    }
}

fn pushErr(self: *Self, file_id: @import("source_manager.zig").FileId, span: Span, msg: []const u8) SemError!void {
    try self.errors.append(self.allocator, .{ .file_id = file_id, .span = span, .message = try self.allocator.dupe(u8, msg) });
}

fn compatible(a: Type, b: Type) bool {
    if (a == .unknown or b == .unknown) return true;
    if (a == b) return true;
    if (isNumeric(a) and isNumeric(b)) return true;
    return false;
}

fn mergeType(a: Type, b: Type) Type {
    if (a == .unknown) return b;
    if (b == .unknown) return a;
    if (a == b) return a;
    if (isNumeric(a) and isNumeric(b)) return if (a == .float_t or b == .float_t) .float_t else .int_t;
    return .unknown;
}

fn isNumeric(t: Type) bool {
    return t == .int_t or t == .float_t;
}

fn cloneEnv(allocator: std.mem.Allocator, src: *const std.StringHashMapUnmanaged(Binding)) !std.StringHashMapUnmanaged(Binding) {
    var out: std.StringHashMapUnmanaged(Binding) = .empty;
    var it = src.iterator();
    while (it.next()) |e| {
        try out.put(allocator, e.key_ptr.*, e.value_ptr.*);
    }
    return out;
}

fn nodeGuaranteesValue(f: ModuleGraph.FileUnit, id: Ast.NodeId) bool {
    const n = f.nodes[id];
    return switch (n.tag) {
        .int_lit, .float_lit, .string_lit, .char_lit, .identifier, .binary, .unary, .call, .index, .slice, .field, .struct_expr, .enum_expr, .fn_expr, .type_lit, .use_expr, .address_of, .deref => true,
        .if_expr => n.data.if_expr.has_else and nodeGuaranteesValue(f, n.data.if_expr.then_expr) and nodeGuaranteesValue(f, n.data.if_expr.else_expr),
        .match_expr => blk: {
            if (n.data.match_expr.arm_count == 0) break :blk false;
            var i: u32 = 0;
            while (i < n.data.match_expr.arm_count) : (i += 1) {
                const arm = f.match_arms[n.data.match_expr.arm_start + i];
                if (!nodeGuaranteesValue(f, arm.body)) break :blk false;
            }
            break :blk true;
        },
        .block => blk: {
            if (n.data.block.item_count == 0) break :blk false;
            const last_id = f.list_items[n.data.block.item_start + n.data.block.item_count - 1];
            break :blk nodeGuaranteesValue(f, last_id);
        },
        .labeled_block => nodeGuaranteesValue(f, n.data.labeled_block.body),
        else => false,
    };
}

test "semantic checker accepts simple numeric program" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_ok";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_ok/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\na: i32 = 1\nb := a + 2\n");
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_ok/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    try std.testing.expectEqual(@as(usize, 0), s.errors.items.len);
}

test "semantic checker reports unknown and mismatch" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_bad";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_bad/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\na: i32 = \"x\"\nb := c + 1\n");
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_bad/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    try std.testing.expect(s.errors.items.len >= 2);
}

test "semantic checker validates function calls and loop control" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_calls_loops";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_calls_loops/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "add := (x: i32, y: i32) i32 => x + y\n" ++
                "a := add(1, 2)\n" ++
                "b := add(1)\n" ++
                "c := add(1, \"x\")\n" ++
                "break\n" ++
                "for { continue }\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_calls_loops/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    try std.testing.expect(s.errors.items.len >= 3);
}

test "semantic checker validates aggregate duplicate members" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_agg_dups";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_agg_dups/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "S := struct { a: i32 = 1, a: i32 = 2 }\n" ++
                "E := enum { A := 1, A := 2 }\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_agg_dups/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    try std.testing.expect(s.errors.items.len >= 2);
}

test "semantic checker validates mutability shadowing and return paths" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_mut_shadow_ret";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_mut_shadow_ret/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "x := 1\n" ++
                "x = 2\n" ++
                "{ x := 3 }\n" ++
                "f := () i32 => {}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_mut_shadow_ret/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    try std.testing.expect(s.errors.items.len >= 3);
}

test "semantic checker allows out-of-order global function declarations" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_out_of_order_single";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_out_of_order_single/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => a_fn()\n" ++
                "a_fn := () i32 => 42\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_out_of_order_single/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    try std.testing.expectEqual(@as(usize, 0), s.errors.items.len);
}

test "semantic checker allows cross-file same-module out-of-order call" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_out_of_order_multi";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_out_of_order_multi/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => helper()\n",
        );
    }
    {
        var f = try std.fs.cwd().createFile("tmp_sem_out_of_order_multi/helper.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "helper := () i32 => 7\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_out_of_order_multi/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    try std.testing.expectEqual(@as(usize, 0), s.errors.items.len);
}

test "semantic checker enforces function value on all paths" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_ret_all_paths";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_ret_all_paths/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "bad := (x: bool) i32 => { if x { 1 } }\n" ++
                "ok := (x: bool) i32 => { if x { 1 } else { 2 } }\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_ret_all_paths/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "function with return type must return a value on all paths")) saw = true;
    }
    try std.testing.expect(saw);
}

test "semantic checker rejects non-function calls and non-bool for conditions" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_non_fn_call_for_cond";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_non_fn_call_for_cond/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "x := 1\n" ++
                "y := x()\n" ++
                "for 1 { }\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_non_fn_call_for_cond/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw_non_fn_call = false;
    var saw_for_cond = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "attempted to call non-function value")) saw_non_fn_call = true;
        if (std.mem.eql(u8, e.message, "for condition must be bool")) saw_for_cond = true;
    }
    try std.testing.expect(saw_non_fn_call);
    try std.testing.expect(saw_for_cond);
}

test "semantic checker reports unreachable statement after loop control" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_unreachable";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_unreachable/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "for {\n" ++
                "  break\n" ++
                "  x := 1\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_unreachable/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "unreachable statement")) saw = true;
    }
    try std.testing.expect(saw);
}

test "semantic checker requires match arms to return values in typed function" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_match_ret";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_match_ret/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "bad := (x: i32) i32 => match x { 0: { }, _: 1 }\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_match_ret/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "function with return type must return a value on all paths")) saw = true;
    }
    try std.testing.expect(saw);
}

test "semantic checker reports core type mismatch classes" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_mismatch_classes";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_mismatch_classes/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "a: i32 = \"x\"\n" ++
                "b := 1 + true\n" ++
                "c := true && 1\n" ++
                "d := !1\n" ++
                "if 1 { 2 }\n" ++
                "x := 1\n" ++
                "x = \"s\"\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_mismatch_classes/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw_decl_mismatch = false;
    var saw_numeric = false;
    var saw_logical = false;
    var saw_unary_not = false;
    var saw_if_cond = false;
    var saw_assign = false;

    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "declaration type does not match initializer")) saw_decl_mismatch = true;
        if (std.mem.eql(u8, e.message, "numeric operator expects numeric operands")) saw_numeric = true;
        if (std.mem.eql(u8, e.message, "logical operator expects bool operands")) saw_logical = true;
        if (std.mem.eql(u8, e.message, "'!' expects bool operand")) saw_unary_not = true;
        if (std.mem.eql(u8, e.message, "if condition must be bool")) saw_if_cond = true;
        if (std.mem.eql(u8, e.message, "assignment type mismatch")) saw_assign = true;
    }

    try std.testing.expect(saw_decl_mismatch);
    try std.testing.expect(saw_numeric);
    try std.testing.expect(saw_logical);
    try std.testing.expect(saw_unary_not);
    try std.testing.expect(saw_if_cond);
    try std.testing.expect(saw_assign);
}

test "semantic checker enforces continue legality and allows labeled/defer forms" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_control_forms";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_control_forms/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "continue\n" ++
                "lbl: { defer 1; 2 }\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_control_forms/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw_continue_outside = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "'continue' used outside loop")) saw_continue_outside = true;
    }
    try std.testing.expect(saw_continue_outside);
}

test "semantic checker enforces pointer mutability on deref assignment" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_ptr_mut";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_ptr_mut/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mut v = 1\n" ++
                "p_ro: *i32 = &v\n" ++
                "p_rw: *mut i32 = &v\n" ++
                "p_ro.* = 2\n" ++
                "p_rw.* = 3\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_ptr_mut/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw_ptr_mut_err = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "cannot assign through immutable pointer")) saw_ptr_mut_err = true;
    }
    try std.testing.expect(saw_ptr_mut_err);
}

test "semantic checker tracks pointer element types" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_ptr_elem";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_ptr_elem/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mut i: i32 = 1\n" ++
                "mut f: f32 = 1.0\n" ++
                "pi: *mut i32 = &i\n" ++
                "bad_ptr: *mut i32 = &f\n" ++
                "pi.* = \"x\"\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_ptr_elem/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw_decl_mismatch = false;
    var saw_assign_mismatch = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "declaration type does not match initializer")) saw_decl_mismatch = true;
        if (std.mem.eql(u8, e.message, "assignment type mismatch")) saw_assign_mismatch = true;
    }
    try std.testing.expect(saw_decl_mismatch);
    try std.testing.expect(saw_assign_mismatch);
}

test "semantic checker validates assignment targets" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_assign_targets";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_assign_targets/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "(1 + 2) = 3\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_assign_targets/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "invalid assignment target")) saw = true;
    }
    try std.testing.expect(saw);
}

test "semantic checker validates unwrap and deref operators" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_unwrap_deref_ops";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_unwrap_deref_ops/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "a := 1\n" ++
                "b := a.?\n" ++
                "c := a.!\n" ++
                "d := a.*\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_unwrap_deref_ops/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw_opt = false;
    var saw_err = false;
    var saw_deref = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "'.?' expects optional value")) saw_opt = true;
        if (std.mem.eql(u8, e.message, "'.!' expects error value")) saw_err = true;
        if (std.mem.eql(u8, e.message, "'.*' expects pointer value")) saw_deref = true;
    }
    try std.testing.expect(saw_opt);
    try std.testing.expect(saw_err);
    try std.testing.expect(saw_deref);
}
