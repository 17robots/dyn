const std = @import("std");
const Ast = @import("ast.zig");
const Span = @import("token.zig").Span;
const ModuleGraph = @import("module_graph.zig");
const CalleeResolve = @import("callee_resolve.zig");
const ExprKind = @import("expr_kind.zig");
const ComptimeValue = @import("comptime_value.zig");
const GraphUtil = @import("graph_util.zig");
const CallNormalize = @import("call_normalize.zig");

pub const Type = enum {
    unknown,
    void_t,
    bool_t,
    int_t,
    float_t,
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
    ptr_to_char_t,
    ptr_mut_to_char_t,
    ptr_to_optional_t,
    ptr_mut_to_optional_t,
    ptr_to_error_t,
    ptr_mut_to_error_t,
    optional_t,
    error_t,
    optional_error_t,
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
    slice_source: Ast.NodeId = Ast.NullNode,
};

const Ctx = struct {
    scope_depth: usize = 0,
    loop_depth: usize = 0,
    in_function: bool = false,
    fn_return_type: ?Type = null,
    type_arg_cache: ?*std.AutoHashMapUnmanaged(Ast.NodeId, bool) = null,
    comptime_value_cache: ?*std.AutoHashMapUnmanaged(Ast.NodeId, ComptimeValue.Value) = null,
    label_stack: ?*std.ArrayListUnmanaged(LabelCtx) = null,
};

const LabelTargetKind = enum {
    block,
    loop,
};

const LabelCtx = struct {
    name: []const u8,
    target: LabelTargetKind,
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
                        try self.collectReturnedStructMethodBindings(graph, f, file_idx, item.data.decl.init_node, &fn_bindings);
                    } else if (init_n.tag == .struct_expr) {
                        var si: u32 = 0;
                        while (si < init_n.data.aggregate.item_count) : (si += 1) {
                            const sn_id = f.list_items[init_n.data.aggregate.item_start + si];
                            const sn = f.nodes[sn_id];
                            if (sn.tag != .decl or !sn.data.decl.has_init or sn.data.decl.name_count == 0) continue;
                            const sinit = f.nodes[sn.data.decl.init_node];
                            if (sinit.tag != .fn_expr) continue;
                            const sident = f.nodes[f.decl_name_items[sn.data.decl.name_start]];
                            const sname = graph.sm.spanSlice(f.file_id, sident.span) catch continue;
                            if (fn_bindings.get(sname) == null) {
                                try fn_bindings.put(self.allocator, sname, .{ .file_index = file_idx, .node_id = sn.data.decl.init_node });
                            }
                        }
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

fn collectReturnedStructMethodBindings(
    self: *Self,
    graph: *ModuleGraph.Self,
    f: ModuleGraph.FileUnit,
    file_idx: u32,
    fn_node: Ast.NodeId,
    fn_bindings: *std.StringHashMapUnmanaged(FnBinding),
) SemError!void {
    const fn_n = f.nodes[fn_node];
    if (fn_n.tag != .fn_expr) return;
    if (!fn_n.data.fn_expr.has_body) return;
    const body = f.nodes[ExprKind.peelComptimeWrappers(f, fn_n.data.fn_expr.body)];
    if (body.tag != .struct_expr) return;
    var si: u32 = 0;
    while (si < body.data.aggregate.item_count) : (si += 1) {
        const sn_id = f.list_items[body.data.aggregate.item_start + si];
        const sn = f.nodes[sn_id];
        if (sn.tag != .decl or !sn.data.decl.has_init or sn.data.decl.name_count == 0) continue;
        const sinit = f.nodes[sn.data.decl.init_node];
        if (sinit.tag != .fn_expr) continue;
        const sident = f.nodes[f.decl_name_items[sn.data.decl.name_start]];
        const sname = graph.sm.spanSlice(f.file_id, sident.span) catch continue;
        if (fn_bindings.get(sname) == null) {
            try fn_bindings.put(self.allocator, sname, .{ .file_index = file_idx, .node_id = sn.data.decl.init_node });
        }
        try self.collectReturnedStructMethodBindings(graph, f, file_idx, sn.data.decl.init_node, fn_bindings);
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

    var type_arg_cache: std.AutoHashMapUnmanaged(Ast.NodeId, bool) = .empty;
    defer type_arg_cache.deinit(self.allocator);
    var comptime_value_cache: std.AutoHashMapUnmanaged(Ast.NodeId, ComptimeValue.Value) = .empty;
    defer comptime_value_cache.deinit(self.allocator);
    var label_stack: std.ArrayListUnmanaged(LabelCtx) = .empty;
    defer label_stack.deinit(self.allocator);
    var ctx = Ctx{ .type_arg_cache = &type_arg_cache, .comptime_value_cache = &comptime_value_cache, .label_stack = &label_stack };
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
        .bool_lit => .bool_t,
        .float_lit => .float_t,
        .string_lit => .ptr_to_int_t,
        .char_lit => .char_t,
        .type_lit => .type_t,
        .use_expr => .module_t,
        .identifier => blk: {
            try graph.sm.ensureTextLoaded(f.file_id);
            const name = graph.sm.spanSlice(f.file_id, n.span) catch break :blk .unknown;
            if (std.mem.eql(u8, name, "true") or std.mem.eql(u8, name, "false")) break :blk .bool_t;
            if (std.mem.eql(u8, name, "i32") or std.mem.eql(u8, name, "i64") or std.mem.eql(u8, name, "u32") or std.mem.eql(u8, name, "u64") or std.mem.eql(u8, name, "usize") or std.mem.eql(u8, name, "isize")) break :blk .type_t;
            if (std.mem.eql(u8, name, "f32") or std.mem.eql(u8, name, "f64")) break :blk .type_t;
            if (std.mem.eql(u8, name, "bool") or std.mem.eql(u8, name, "char") or std.mem.eql(u8, name, "type") or std.mem.eql(u8, name, "optional") or std.mem.eql(u8, name, "error")) break :blk .type_t;
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
            } else if (lhs_node.tag == .field) {
                // currently treated as a method-style receiver field update target
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
            if (!canCoerceTo(lt, rt)) try self.pushTypeMismatch(f.file_id, n.span, "assignment type mismatch", lt, rt);
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
            if (child.tag != .deref and child.tag != .field and child.tag != .index) {
                try self.pushErr(f.file_id, n.span, "'&' expects addressable expression");
            }
            _ = try self.inferNode(graph, f, n.data.one.child, env, fn_bindings, ctx);
            break :blk .ptr_to_unknown_t;
        },
        .ptr_type, .slice_type, .array_type, .optional_type, .error_type => .type_t,
        .field => .unknown,
        .call => blk: {
            const callee_t = try self.inferNode(graph, f, n.data.call.callee, env, fn_bindings, ctx);

            if (try self.resolveCalleeFnExprNode(graph, f, n.data.call.callee, fn_bindings)) |binding| {
                const fn_file = graph.files.items[binding.file_index];
                const fn_n = fn_file.nodes[binding.node_id];
                const expected = fn_n.data.fn_expr.param_count;
                const implicit_receiver = hasImplicitReceiver(graph, f, n.data.call.callee, fn_bindings, fn_file, fn_n);
                const runtime_expected: u32 = if (implicit_receiver and expected > 0) expected - 1 else expected;
                if (n.data.call.arg_count != runtime_expected) {
                    try self.pushErr(f.file_id, n.span, "function call argument count mismatch");
                } else {
                    var pi: u32 = if (implicit_receiver) 1 else 0;
                    var ai: u32 = 0;
                    while (pi < expected) : (pi += 1) {
                        const p_node = fn_file.nodes[fn_file.list_items[fn_n.data.fn_expr.param_start + pi]];
                        if (p_node.tag != .param or !p_node.data.param.has_type) continue;
                        const arg_node = f.list_items[n.data.call.arg_start + ai];
                        if (p_node.data.param.is_comp and isCompTypeAnnotation(fn_file, p_node.data.param.type_node)) {
                            const skip_strict_type_arg = isNestedFactoryFieldCall(f, n.data.call.callee);
                            if (!skip_strict_type_arg) {
                                const arg_t = try self.inferNode(graph, f, arg_node, env, fn_bindings, ctx);
                                const is_type_like = arg_t == .type_t or arg_t == .struct_t or arg_t == .enum_t or arg_t == .fn_t or arg_t == .unknown;
                                if (!is_type_like and !self.isTypeArgumentExpr(graph, f, arg_node, ctx, fn_bindings)) {
                                    try self.pushErr(f.file_id, n.span, "comptime type parameter expects type argument");
                                }
                            }
                            ai += 1;
                            continue;
                        }
                        const pt = try self.typeFromAnnotation(graph, fn_file, p_node.data.param.type_node, env, fn_bindings, ctx);
                        const arg_t = try self.inferNode(graph, f, arg_node, env, fn_bindings, ctx);
                        if (!canCoerceTo(pt, arg_t)) {
                            if (isSliceTypeAnnotation(fn_file, p_node.data.param.type_node)) {
                                try graph.sm.ensureTextLoaded(fn_file.file_id);
                                const expected_ann = graph.sm.spanSlice(fn_file.file_id, fn_file.nodes[p_node.data.param.type_node].span) catch "[]T";
                                try self.pushSliceTypeMismatch(f.file_id, n.span, expected_ann, arg_t);
                            } else {
                                try self.pushTypeMismatch(f.file_id, n.span, "function argument type mismatch", pt, arg_t);
                            }
                        }
                        ai += 1;
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
        .index => blk: {
            const ot = try self.inferNode(graph, f, n.data.index.object, env, fn_bindings, ctx);
            const it = try self.inferNode(graph, f, n.data.index.index, env, fn_bindings, ctx);
            if (it != .unknown and it != .int_t) try self.pushErr(f.file_id, n.span, "index expects integer index");
            if (!isPointerType(ot)) {
                try self.pushErr(f.file_id, n.span, "index expects pointer/slice value");
                break :blk .unknown;
            }
            break :blk pointerElementType(ot);
        },
        .slice => blk: {
            const ot = try self.inferNode(graph, f, n.data.slice.object, env, fn_bindings, ctx);
            if (!isPointerType(ot)) {
                try self.pushErr(f.file_id, n.span, "slice expects pointer/slice value");
                break :blk .unknown;
            }
            if (n.data.slice.has_start) {
                const st = try self.inferNode(graph, f, n.data.slice.start, env, fn_bindings, ctx);
                if (st != .unknown and st != .int_t) try self.pushErr(f.file_id, n.span, "slice start expects integer index");
            }
            if (n.data.slice.has_end) {
                const et = try self.inferNode(graph, f, n.data.slice.end, env, fn_bindings, ctx);
                if (et != .unknown and et != .int_t) try self.pushErr(f.file_id, n.span, "slice end expects integer index");
            }
            break :blk makePointerType(pointerElementType(ot), false);
        },
        .if_expr => blk: {
            const ct = try self.inferNode(graph, f, n.data.if_expr.cond, env, fn_bindings, ctx);
            if (ct != .unknown and ct != .bool_t) try self.pushErr(f.file_id, n.span, "if condition must be bool");
            const tt = if (n.data.if_expr.has_bind) blk_then: {
                var then_env = try cloneEnv(self.allocator, env);
                defer then_env.deinit(self.allocator);
                try graph.sm.ensureTextLoaded(f.file_id);
                const bind_name = graph.sm.spanSlice(f.file_id, n.data.if_expr.bind_span) catch "";
                if (bind_name.len != 0) {
                    const bind_t = switch (ct) {
                        .optional_t => .int_t,
                        .error_t => .int_t,
                        .optional_error_t => .error_t,
                        else => ct,
                    };
                    try then_env.put(self.allocator, bind_name, .{ .ty = bind_t, .mutable = false });
                }
                break :blk_then try self.inferNode(graph, f, n.data.if_expr.then_expr, &then_env, fn_bindings, ctx);
            } else try self.inferNode(graph, f, n.data.if_expr.then_expr, env, fn_bindings, ctx);
            if (!n.data.if_expr.has_else) break :blk .void_t;
            const et = try self.inferNode(graph, f, n.data.if_expr.else_expr, env, fn_bindings, ctx);
            const tv = self.inferComptimeValue(graph, f, n.data.if_expr.then_expr, ctx, fn_bindings);
            const ev = self.inferComptimeValue(graph, f, n.data.if_expr.else_expr, ctx, fn_bindings);
            if (!comptimeJoinCompatible(tv, ev)) {
                try self.pushErr(f.file_id, n.span, "if branches must have compatible comptime identities");
            }
            if (!joinCompatible(tt, et)) try self.pushErr(f.file_id, n.span, "if branches must have compatible types");
            break :blk mergeType(tt, et);
        },
        .match_expr => blk: {
            const subj_t = try self.inferNode(graph, f, n.data.match_expr.subject, env, fn_bindings, ctx);
            try self.checkMatchArms(graph, f, n, subj_t);
            var out: Type = .unknown;
            var out_v: ?ComptimeValue.Value = null;
            var i: u32 = 0;
            while (i < n.data.match_expr.arm_count) : (i += 1) {
                const arm = f.match_arms[n.data.match_expr.arm_start + i];
                if (arm.pat_start != Ast.NullNode) _ = try self.inferNode(graph, f, arm.pat_start, env, fn_bindings, ctx);
                if (arm.pat_end != Ast.NullNode) _ = try self.inferNode(graph, f, arm.pat_end, env, fn_bindings, ctx);
                if (arm.has_pat_payload) _ = try self.inferNode(graph, f, arm.pat_payload, env, fn_bindings, ctx);
                const bt = if (arm.has_capture) blk_cap: {
                    var arm_env = try cloneEnv(self.allocator, env);
                    defer arm_env.deinit(self.allocator);
                    try graph.sm.ensureTextLoaded(f.file_id);
                    const cap_name = graph.sm.spanSlice(f.file_id, arm.capture_span) catch "";
                    if (cap_name.len != 0) try arm_env.put(self.allocator, cap_name, .{ .ty = subj_t, .mutable = false });
                    break :blk_cap try self.inferNode(graph, f, arm.body, &arm_env, fn_bindings, ctx);
                } else try self.inferNode(graph, f, arm.body, env, fn_bindings, ctx);
                const bv = self.inferComptimeValue(graph, f, arm.body, ctx, fn_bindings);
                if (out_v) |prev| {
                    if (!comptimeJoinCompatible(prev, bv)) {
                        try self.pushErr(f.file_id, n.span, "match arms must have compatible comptime identities");
                    }
                } else {
                    out_v = bv;
                }
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
                if (item_n.tag == .labeled_block) {
                    terminated = nodeAlwaysTransfersControlLabeled(graph, f, item_n.data.labeled_block.body, item_n.data.labeled_block.label_span);
                } else if (nodeAlwaysTransfersControl(f, item_id)) {
                    terminated = true;
                }
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
            if (n.data.decl.has_type and n.data.decl.has_init and !canCoerceTo(expected, init_t)) {
                try self.pushTypeMismatch(f.file_id, n.span, "declaration type does not match initializer", expected, init_t);
            }
            const final_t = if (expected != .unknown) expected else init_t;
            const slice_source: Ast.NodeId = blk_src: {
                if (!n.data.decl.has_init) break :blk_src Ast.NullNode;
                const init_n = f.nodes[n.data.decl.init_node];
                if (init_n.tag == .slice and init_n.data.slice.has_end) break :blk_src n.data.decl.init_node;
                if (init_n.tag == .identifier) {
                    try graph.sm.ensureTextLoaded(f.file_id);
                    const init_name = graph.sm.spanSlice(f.file_id, init_n.span) catch "";
                    if (env.get(init_name)) |b| {
                        if (b.slice_source != Ast.NullNode) break :blk_src b.slice_source;
                    }
                }
                break :blk_src Ast.NullNode;
            };
            var j: u32 = 0;
            while (j < n.data.decl.name_count) : (j += 1) {
                const ident = f.nodes[f.decl_name_items[n.data.decl.name_start + j]];
                try graph.sm.ensureTextLoaded(f.file_id);
                const name = graph.sm.spanSlice(f.file_id, ident.span) catch continue;
                if (ctx.scope_depth > 0 and env.get(name) != null) {
                    try self.pushErr(f.file_id, ident.span, "declaration shadows outer name");
                }
                try env.put(self.allocator, name, .{ .ty = final_t, .mutable = n.data.decl.is_mut, .slice_source = slice_source });
            }
            break :blk .void_t;
        },
        .fn_expr => blk: {
            var fn_env = try cloneEnv(self.allocator, env);
            defer fn_env.deinit(self.allocator);
            var fn_ctx = ctx.*;
            fn_ctx.in_function = true;

            const rt: ?Type = if (n.data.fn_expr.has_ret)
                try self.typeFromAnnotation(graph, f, n.data.fn_expr.ret_node, &fn_env, fn_bindings, &fn_ctx)
            else
                null;
            fn_ctx.fn_return_type = rt;

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

            if (!n.data.fn_expr.has_body) break :blk .fn_t;

            const bt = try self.inferNode(graph, f, n.data.fn_expr.body, &fn_env, fn_bindings, &fn_ctx);
            if (rt) |want_rt| {
                const body_n = f.nodes[n.data.fn_expr.body];
                if (body_n.tag == .block) {
                    if (!nodeGuaranteesExplicitReturn(f, n.data.fn_expr.body)) {
                        try self.pushErr(f.file_id, n.span, "block-bodied function with return type must use explicit 'return' on all paths");
                    }
                } else {
                    if (!canCoerceTo(want_rt, bt)) try self.pushTypeMismatch(f.file_id, n.span, "function body type does not match return type", want_rt, bt);
                    if (!nodeGuaranteesValue(f, n.data.fn_expr.body)) {
                        try self.pushErr(f.file_id, n.span, "function with return type must return a value on all paths");
                    }
                }
            }
            break :blk .fn_t;
        },
        .param => .void_t,
        .for_stmt => blk: {
            var loop_ctx = ctx.*;
            loop_ctx.loop_depth += 1;
            if (!n.data.for_stmt.is_infinite and n.data.for_stmt.cond != Ast.NullNode) {
                const cond_n = f.nodes[n.data.for_stmt.cond];
                if (n.data.for_stmt.has_capture and cond_n.tag == .identifier) {
                    try graph.sm.ensureTextLoaded(f.file_id);
                    const nm = graph.sm.spanSlice(f.file_id, cond_n.span) catch "";
                    if (env.get(nm)) |bnd| {
                        if (bnd.slice_source != Ast.NullNode) {
                            const slice_n = f.nodes[bnd.slice_source];
                            if (slice_n.tag == .slice) {
                                const ot = try self.inferNode(graph, f, slice_n.data.slice.object, env, fn_bindings, &loop_ctx);
                                if (!isPointerType(ot) and ot != .unknown) try self.pushErr(f.file_id, n.span, "for slice iterable expects pointer/slice object");
                                if (slice_n.data.slice.has_start) {
                                    const st = try self.inferNode(graph, f, slice_n.data.slice.start, env, fn_bindings, &loop_ctx);
                                    if (st != .unknown and st != .int_t) try self.pushErr(f.file_id, n.span, "for slice start must be integer");
                                }
                                if (!slice_n.data.slice.has_end) {
                                    try self.pushErr(f.file_id, n.span, "for slice iterable requires end index");
                                } else {
                                    const et = try self.inferNode(graph, f, slice_n.data.slice.end, env, fn_bindings, &loop_ctx);
                                    if (et != .unknown and et != .int_t) try self.pushErr(f.file_id, n.span, "for slice end must be integer");
                                }

                                var body_env = try cloneEnv(self.allocator, env);
                                defer body_env.deinit(self.allocator);
                                const cap = graph.sm.spanSlice(f.file_id, n.data.for_stmt.capture_span) catch "";
                                if (cap.len != 0 and !std.mem.eql(u8, cap, "_")) {
                                    const elem_t = if (isPointerType(ot)) pointerElementType(ot) else .unknown;
                                    try body_env.put(self.allocator, cap, .{ .ty = elem_t, .mutable = false });
                                }
                                _ = try self.inferNode(graph, f, n.data.for_stmt.body, &body_env, fn_bindings, &loop_ctx);
                                break :blk .void_t;
                            }
                        }
                    }
                }
                if (cond_n.tag == .binary and (cond_n.data.binary.op == .range or cond_n.data.binary.op == .rangeq)) {
                    const st = try self.inferNode(graph, f, cond_n.data.binary.lhs, env, fn_bindings, &loop_ctx);
                    const et = try self.inferNode(graph, f, cond_n.data.binary.rhs, env, fn_bindings, &loop_ctx);
                    if (st != .unknown and st != .int_t) try self.pushErr(f.file_id, n.span, "for range start must be integer");
                    if (et != .unknown and et != .int_t) try self.pushErr(f.file_id, n.span, "for range end must be integer");

                    if (n.data.for_stmt.has_capture) {
                        var body_env = try cloneEnv(self.allocator, env);
                        defer body_env.deinit(self.allocator);
                        try graph.sm.ensureTextLoaded(f.file_id);
                        const cap = graph.sm.spanSlice(f.file_id, n.data.for_stmt.capture_span) catch "";
                        if (cap.len != 0 and !std.mem.eql(u8, cap, "_")) {
                            try body_env.put(self.allocator, cap, .{ .ty = .int_t, .mutable = false });
                        }
                        _ = try self.inferNode(graph, f, n.data.for_stmt.body, &body_env, fn_bindings, &loop_ctx);
                        break :blk .void_t;
                    }
                } else if (cond_n.tag == .slice) {
                    const ot = try self.inferNode(graph, f, cond_n.data.slice.object, env, fn_bindings, &loop_ctx);
                    if (!isPointerType(ot) and ot != .unknown) try self.pushErr(f.file_id, n.span, "for slice iterable expects pointer/slice object");

                    if (cond_n.data.slice.has_start) {
                        const st = try self.inferNode(graph, f, cond_n.data.slice.start, env, fn_bindings, &loop_ctx);
                        if (st != .unknown and st != .int_t) try self.pushErr(f.file_id, n.span, "for slice start must be integer");
                    }
                    if (!cond_n.data.slice.has_end) {
                        try self.pushErr(f.file_id, n.span, "for slice iterable requires end index");
                    } else {
                        const et = try self.inferNode(graph, f, cond_n.data.slice.end, env, fn_bindings, &loop_ctx);
                        if (et != .unknown and et != .int_t) try self.pushErr(f.file_id, n.span, "for slice end must be integer");
                    }

                    if (n.data.for_stmt.has_capture) {
                        var body_env = try cloneEnv(self.allocator, env);
                        defer body_env.deinit(self.allocator);
                        try graph.sm.ensureTextLoaded(f.file_id);
                        const cap = graph.sm.spanSlice(f.file_id, n.data.for_stmt.capture_span) catch "";
                        if (cap.len != 0 and !std.mem.eql(u8, cap, "_")) {
                            const elem_t = if (isPointerType(ot)) pointerElementType(ot) else .unknown;
                            try body_env.put(self.allocator, cap, .{ .ty = elem_t, .mutable = false });
                        }
                        _ = try self.inferNode(graph, f, n.data.for_stmt.body, &body_env, fn_bindings, &loop_ctx);
                        break :blk .void_t;
                    }
                    try self.pushErr(f.file_id, n.span, "for slice iterable requires capture");
                } else {
                    const cond_t = try self.inferNode(graph, f, n.data.for_stmt.cond, env, fn_bindings, &loop_ctx);
                    if (n.data.for_stmt.has_capture and isPointerType(cond_t)) {
                        var body_env = try cloneEnv(self.allocator, env);
                        defer body_env.deinit(self.allocator);
                        try graph.sm.ensureTextLoaded(f.file_id);
                        const cap = graph.sm.spanSlice(f.file_id, n.data.for_stmt.capture_span) catch "";
                        if (cap.len != 0 and !std.mem.eql(u8, cap, "_")) {
                            try body_env.put(self.allocator, cap, .{ .ty = pointerElementType(cond_t), .mutable = false });
                        }
                        _ = try self.inferNode(graph, f, n.data.for_stmt.body, &body_env, fn_bindings, &loop_ctx);
                        break :blk .void_t;
                    }
                    if (cond_t != .unknown and cond_t != .bool_t) {
                        try self.pushErr(f.file_id, n.span, "for condition must be bool");
                    }
                    if (n.data.for_stmt.has_capture) {
                        try self.pushErr(f.file_id, n.span, "for capture requires iterable condition");
                    }
                }
            }
            _ = try self.inferNode(graph, f, n.data.for_stmt.body, env, fn_bindings, &loop_ctx);
            break :blk .void_t;
        },
        .return_stmt => blk: {
            if (!ctx.in_function) {
                try self.pushErr(f.file_id, n.span, "'return' used outside function");
                break :blk .void_t;
            }
            const rt = ctx.fn_return_type;
            if (n.data.return_stmt.has_value) {
                const vt = try self.inferNode(graph, f, n.data.return_stmt.value, env, fn_bindings, ctx);
                if (rt) |want| {
                    if (!canCoerceTo(want, vt)) try self.pushTypeMismatch(f.file_id, n.span, "return type mismatch", want, vt);
                } else {
                    try self.pushErr(f.file_id, n.span, "void function cannot return a value");
                }
            } else if (rt != null) {
                try self.pushErr(f.file_id, n.span, "return statement requires a value for non-void function");
            }
            break :blk .void_t;
        },
        .break_stmt => blk: {
            if (n.data.break_stmt.has_label) {
                if (!hasActiveLabel(graph, f, ctx, n.data.break_stmt.label_span, false)) {
                    try self.pushErr(f.file_id, n.span, "'break' label not found");
                }
            } else if (ctx.loop_depth == 0) try self.pushErr(f.file_id, n.span, "'break' used outside loop");
            if (n.data.break_stmt.has_value) _ = try self.inferNode(graph, f, n.data.break_stmt.value, env, fn_bindings, ctx);
            break :blk .void_t;
        },
        .continue_stmt => blk: {
            if (n.data.continue_stmt.has_label) {
                if (!hasActiveLabel(graph, f, ctx, n.data.continue_stmt.label_span, true)) {
                    try self.pushErr(f.file_id, n.span, "'continue' label not found or not loop");
                }
            } else if (ctx.loop_depth == 0) try self.pushErr(f.file_id, n.span, "'continue' used outside loop");
            break :blk .void_t;
        },
        .defer_stmt => blk: {
            _ = try self.inferNode(graph, f, n.data.defer_stmt.value, env, fn_bindings, ctx);
            break :blk .void_t;
        },
        .labeled_block => blk: {
            if (ctx.label_stack) |stack| {
                try graph.sm.ensureTextLoaded(f.file_id);
                const name = graph.sm.spanSlice(f.file_id, n.data.labeled_block.label_span) catch "";
                const body_n = f.nodes[n.data.labeled_block.body];
                const save = stack.items.len;
                try stack.append(self.allocator, .{ .name = name, .target = if (body_n.tag == .for_stmt) .loop else .block });
                defer stack.shrinkRetainingCapacity(save);
                _ = try self.inferNode(graph, f, n.data.labeled_block.body, env, fn_bindings, ctx);
                break :blk .void_t;
            }
            _ = try self.inferNode(graph, f, n.data.labeled_block.body, env, fn_bindings, ctx);
            break :blk .void_t;
        },
        .inline_expr => try self.inferNode(graph, f, n.data.one.child, env, fn_bindings, ctx),
        .comp_expr => try self.inferNode(graph, f, n.data.one.child, env, fn_bindings, ctx),
        .unwrap_optional => blk: {
            const ct = try self.inferNode(graph, f, n.data.one.child, env, fn_bindings, ctx);
            if (ct == .optional_t) break :blk .int_t;
            if (ct == .optional_error_t) break :blk .error_t;
            if (ct == .unknown) break :blk .unknown;
            try self.pushErr(f.file_id, n.span, "'.?' expects optional value");
            break :blk .unknown;
        },
        .unwrap_error => blk: {
            const ct = try self.inferNode(graph, f, n.data.one.child, env, fn_bindings, ctx);
            if (ct == .error_t) break :blk .int_t;
            if (ct == .unknown) break :blk .unknown;
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
    const lv = self.inferComptimeValue(graph, f, n.data.binary.lhs, ctx, fn_bindings);
    const rv = self.inferComptimeValue(graph, f, n.data.binary.rhs, ctx, fn_bindings);
    return switch (n.data.binary.op) {
        .add, .sub, .mul, .div, .mod => if (isNumeric(lt) and isNumeric(rt)) mergeType(lt, rt) else b: {
            try self.pushErr(f.file_id, n.span, "numeric operator expects numeric operands");
            break :b .unknown;
        },
        .lt, .lte, .gt, .gte => blk: {
            if (isComptimeIdentityKind(lv) or isComptimeIdentityKind(rv)) {
                try self.pushErr(f.file_id, n.span, "ordering comparison expects runtime numeric/comparable values");
                break :blk .unknown;
            }
            if ((isNumeric(lt) and isNumeric(rt)) or compatible(lt, rt)) break :blk .bool_t;
            try self.pushErr(f.file_id, n.span, "comparison operands are not compatible");
            break :blk .unknown;
        },
        .eqeq, .neq => blk: {
            if (isComptimeIdentityKind(lv) and isComptimeIdentityKind(rv)) break :blk .bool_t;
            if (compatible(lt, rt)) break :blk .bool_t;
            try self.pushErr(f.file_id, n.span, "equality operands are not compatible");
            break :blk .unknown;
        },
        .land => if (lt == .bool_t and rt == .bool_t) .bool_t else b: {
            try self.pushErr(f.file_id, n.span, "logical operator expects bool operands");
            break :b .unknown;
        },
        .lor => blk: {
            if (lt == .bool_t and rt == .bool_t) break :blk .bool_t;
            if (lt == .optional_t) {
                if (canCoerceTo(.int_t, rt)) break :blk .int_t;
                if (rt != .unknown) try self.pushOrFallbackTypeMismatch(f.file_id, n.span, "?T", .int_t, rt);
                break :blk .unknown;
            }
            if (lt == .error_t) {
                if (canCoerceTo(.int_t, rt)) break :blk .int_t;
                if (rt != .unknown) try self.pushOrFallbackTypeMismatch(f.file_id, n.span, "T!E", .int_t, rt);
                break :blk .unknown;
            }
            if (lt == .optional_error_t) {
                if (rt == .optional_t) break :blk .optional_t;
                if (rt != .unknown) try self.pushOrFallbackTypeMismatch(f.file_id, n.span, "?T!E", .optional_t, rt);
                break :blk .unknown;
            }
            try self.pushErr(f.file_id, n.span, "'or' expects bool||bool or optional/error with fallback value");
            break :blk .unknown;
        },
        else => .unknown,
    };
}

fn isComptimeIdentityKind(v: ComptimeValue.Value) bool {
    return switch (v) {
        .type_value, .fn_value, .module_value => true,
        else => false,
    };
}

fn comptimeJoinCompatible(a: ComptimeValue.Value, b: ComptimeValue.Value) bool {
    const ka = switch (a) {
        .unknown => ComptimeValue.Kind.unknown,
        .int_value => ComptimeValue.Kind.int_value,
        .bool_value => ComptimeValue.Kind.bool_value,
        .type_value => ComptimeValue.Kind.type_value,
        .fn_value => ComptimeValue.Kind.fn_value,
        .module_value => ComptimeValue.Kind.module_value,
    };
    const kb = switch (b) {
        .unknown => ComptimeValue.Kind.unknown,
        .int_value => ComptimeValue.Kind.int_value,
        .bool_value => ComptimeValue.Kind.bool_value,
        .type_value => ComptimeValue.Kind.type_value,
        .fn_value => ComptimeValue.Kind.fn_value,
        .module_value => ComptimeValue.Kind.module_value,
    };
    return ka == .unknown or kb == .unknown or ka == kb;
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
            if (std.mem.eql(u8, name, "optional")) break :blk .optional_t;
            if (std.mem.eql(u8, name, "error")) break :blk .error_t;
            break :blk if (env.get(name)) |bnd| bnd.ty else .unknown;
        },
        .ptr_type => blk: {
            const child_t = try self.typeFromAnnotation(graph, f, n.data.ptr_type.child, env, fn_bindings, ctx);
            break :blk makePointerType(child_t, n.data.ptr_type.mutable);
        },
        .slice_type => blk: {
            const child_t = try self.typeFromAnnotation(graph, f, n.data.one.child, env, fn_bindings, ctx);
            break :blk makePointerType(child_t, false);
        },
        .array_type => blk: {
            _ = try self.inferNode(graph, f, n.data.array_type.len, env, fn_bindings, ctx);
            const child_t = try self.typeFromAnnotation(graph, f, n.data.array_type.child, env, fn_bindings, ctx);
            break :blk makePointerType(child_t, false);
        },
        .optional_type => blk: {
            const child_t = try self.typeFromAnnotation(graph, f, n.data.one.child, env, fn_bindings, ctx);
            break :blk if (child_t == .error_t) .optional_error_t else .optional_t;
        },
        .error_type => blk: {
            const child_t = try self.typeFromAnnotation(graph, f, n.data.error_type.child, env, fn_bindings, ctx);
            break :blk if (child_t == .optional_t) .optional_error_t else .error_t;
        },
        else => try self.inferNode(graph, f, node_id, env, fn_bindings, ctx),
    };
}

fn makePointerType(elem: Type, mutable: bool) Type {
    return switch (elem) {
        .int_t => if (mutable) .ptr_mut_to_int_t else .ptr_to_int_t,
        .float_t => if (mutable) .ptr_mut_to_float_t else .ptr_to_float_t,
        .bool_t => if (mutable) .ptr_mut_to_bool_t else .ptr_to_bool_t,
        .char_t => if (mutable) .ptr_mut_to_char_t else .ptr_to_char_t,
        .optional_t => if (mutable) .ptr_mut_to_optional_t else .ptr_to_optional_t,
        .optional_error_t => if (mutable) .ptr_mut_to_optional_t else .ptr_to_optional_t,
        .error_t => if (mutable) .ptr_mut_to_error_t else .ptr_to_error_t,
        else => if (mutable) .ptr_mut_to_unknown_t else .ptr_to_unknown_t,
    };
}

fn pointerElementType(t: Type) Type {
    return switch (t) {
        .ptr_to_int_t, .ptr_mut_to_int_t => .int_t,
        .ptr_to_float_t, .ptr_mut_to_float_t => .float_t,
        .ptr_to_bool_t, .ptr_mut_to_bool_t => .bool_t,
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
        .ptr_to_char_t,
        .ptr_to_optional_t,
        .ptr_to_error_t,
        => true,
        else => false,
    };
}

fn isMutablePointer(t: Type) bool {
    return isPointerType(t) and !isImmutablePointerType(t);
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
    if (n.tag == .fn_expr) return .{ .file_index = GraphUtil.findFileIndex(graph, f.file_id) orelse return null, .node_id = callee_id };
    const norm = CallNormalize.normalize(graph, f, callee_id) catch return null;
    switch (norm) {
        .identifier => |name| return fn_bindings.get(name),
        .field => |fd| {
            if (fd.object_ident) |alias| {
                if (findUseAliasTargetModule(graph, f, alias)) |target_mod| {
                    return findModuleFunctionBinding(graph, target_mod, fd.member);
                }
            }
            if (fn_bindings.get(fd.member)) |b| return b;
            return findUniqueImportedModuleFunctionBinding(graph, f, fd.member);
        },
        else => {},
    }
    return null;
}

fn findUseAliasTargetModule(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, alias: []const u8) ?u32 {
    return CalleeResolve.findUseAliasTargetModule(graph, f, alias);
}

fn findModuleFunctionBinding(graph: *ModuleGraph.Self, module_index: u32, name: []const u8) ?FnBinding {
    const ref = CalleeResolve.findModuleFunctionRef(graph, module_index, name) orelse return null;
    return .{ .file_index = ref.file_index, .node_id = ref.node_id };
}

fn findUniqueImportedModuleFunctionBinding(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, name: []const u8) ?FnBinding {
    const ref = CalleeResolve.findUniqueImportedModuleFunctionRef(graph, f, name) orelse return null;
    return .{ .file_index = ref.file_index, .node_id = ref.node_id };
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

fn pushErrOwned(self: *Self, file_id: @import("source_manager.zig").FileId, span: Span, msg: []u8) SemError!void {
    try self.errors.append(self.allocator, .{ .file_id = file_id, .span = span, .message = msg });
}

fn pushTypeMismatch(self: *Self, file_id: @import("source_manager.zig").FileId, span: Span, context: []const u8, expected: Type, actual: Type) SemError!void {
    const msg = try std.fmt.allocPrint(
        self.allocator,
        "{s}: expected `{s}`, got `{s}`",
        .{ context, typeNameForDiag(expected), typeNameForDiag(actual) },
    );
    try self.pushErrOwned(file_id, span, msg);
}

fn pushOrFallbackTypeMismatch(self: *Self, file_id: @import("source_manager.zig").FileId, span: Span, container: []const u8, expected: Type, actual: Type) SemError!void {
    const msg = try std.fmt.allocPrint(
        self.allocator,
        "'or' fallback type mismatch: left `{s}` expects fallback `{s}`, got `{s}`",
        .{ container, typeNameForDiag(expected), typeNameForDiag(actual) },
    );
    try self.pushErrOwned(file_id, span, msg);
}

fn pushSliceTypeMismatch(self: *Self, file_id: @import("source_manager.zig").FileId, span: Span, expected_slice_ann: []const u8, actual: Type) SemError!void {
    const msg = try std.fmt.allocPrint(
        self.allocator,
        "function argument type mismatch: expected `{s} (ptr,len)`, got `{s}`",
        .{ expected_slice_ann, typeNameForDiag(actual) },
    );
    try self.pushErrOwned(file_id, span, msg);
}

fn typeNameForDiag(t: Type) []const u8 {
    return switch (t) {
        .unknown => "unknown",
        .void_t => "void",
        .bool_t => "bool",
        .int_t => "i32",
        .float_t => "f32",
        .char_t => "char",
        .type_t => "type",
        .module_t => "module",
        .fn_t => "fn",
        .struct_t => "struct",
        .enum_t => "enum",
        .ptr_to_unknown_t => "*unknown",
        .ptr_mut_to_unknown_t => "*mut unknown",
        .ptr_to_int_t => "*i32",
        .ptr_mut_to_int_t => "*mut i32",
        .ptr_to_float_t => "*f32",
        .ptr_mut_to_float_t => "*mut f32",
        .ptr_to_bool_t => "*bool",
        .ptr_mut_to_bool_t => "*mut bool",
        .ptr_to_char_t => "*char",
        .ptr_mut_to_char_t => "*mut char",
        .ptr_to_optional_t => "*?T",
        .ptr_mut_to_optional_t => "*mut ?T",
        .ptr_to_error_t => "*T!E",
        .ptr_mut_to_error_t => "*mut T!E",
        .optional_t => "?T",
        .error_t => "T!E",
        .optional_error_t => "?T!E",
    };
}

fn isSliceTypeAnnotation(f: ModuleGraph.FileUnit, node_id: Ast.NodeId) bool {
    var n = f.nodes[node_id];
    while (true) {
        switch (n.tag) {
            .slice_type => return true,
            .optional_type => n = f.nodes[n.data.one.child],
            .error_type => n = f.nodes[n.data.error_type.child],
            else => return false,
        }
    }
}

fn compatible(a: Type, b: Type) bool {
    if (a == .unknown or b == .unknown) return true;
    if (a == b) return true;
    if (isPointerType(a) and isPointerType(b)) {
        const ae = pointerElementType(a);
        const be = pointerElementType(b);
        if (ae == .unknown or be == .unknown) return true;
        if (ae == be) return true;
    }
    if ((a == .type_t and (b == .struct_t or b == .enum_t)) or (b == .type_t and (a == .struct_t or a == .enum_t))) return true;
    if (isNumeric(a) and isNumeric(b)) return true;
    if ((a == .optional_error_t and b == .optional_t) or (a == .optional_t and b == .optional_error_t)) return true;
    return false;
}

fn canCoerceTo(expected: Type, actual: Type) bool {
    if (compatible(expected, actual)) return true;
    if ((expected == .optional_t and actual == .int_t) or (expected == .error_t and actual == .int_t)) return true;
    if (expected == .optional_error_t and actual == .error_t) return true;
    return false;
}

fn joinCompatible(a: Type, b: Type) bool {
    if (compatible(a, b)) return true;
    if ((a == .optional_t and b == .int_t) or (a == .int_t and b == .optional_t)) return true;
    if ((a == .error_t and b == .int_t) or (a == .int_t and b == .error_t)) return true;
    if ((a == .optional_error_t and b == .error_t) or (a == .error_t and b == .optional_error_t)) return true;
    return false;
}

fn mergeType(a: Type, b: Type) Type {
    if (a == .unknown) return b;
    if (b == .unknown) return a;
    if (a == b) return a;
    if ((a == .type_t or a == .struct_t or a == .enum_t) and (b == .type_t or b == .struct_t or b == .enum_t)) return .type_t;
    if ((a == .fn_t and b == .fn_t)) return .fn_t;
    if (isPointerType(a) and isPointerType(b)) {
        const ae = pointerElementType(a);
        const be = pointerElementType(b);
        const out_mut = isMutablePointer(a) and isMutablePointer(b);
        if (ae == be) return makePointerType(ae, out_mut);
        if (ae == .unknown) return makePointerType(be, out_mut);
        if (be == .unknown) return makePointerType(ae, out_mut);
    }
    if (isNumeric(a) and isNumeric(b)) return if (a == .float_t or b == .float_t) .float_t else .int_t;
    if (a == .optional_t and b == .int_t) return .optional_t;
    if (a == .int_t and b == .optional_t) return .optional_t;
    if (a == .error_t and b == .int_t) return .error_t;
    if (a == .int_t and b == .error_t) return .error_t;
    if (a == .optional_error_t and b == .error_t) return .optional_error_t;
    if (a == .error_t and b == .optional_error_t) return .optional_error_t;
    if (a == .optional_error_t and b == .optional_t) return .optional_t;
    if (a == .optional_t and b == .optional_error_t) return .optional_t;
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

fn isCompTypeAnnotation(f: ModuleGraph.FileUnit, node_id: Ast.NodeId) bool {
    return f.nodes[node_id].tag == .type_lit;
}

fn isTypeArgumentExpr(self: *Self, graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, node_id: Ast.NodeId, ctx: *Ctx, fn_bindings: *std.StringHashMapUnmanaged(FnBinding)) bool {
    if (ctx.type_arg_cache) |cache| {
        if (cache.get(node_id)) |v| return v;
    }

    const cval = self.inferComptimeValue(graph, f, node_id, ctx, fn_bindings);
    const ckind: ComptimeValue.Kind = switch (cval) {
        .unknown => .unknown,
        .int_value => .int_value,
        .bool_value => .bool_value,
        .type_value => .type_value,
        .fn_value => .fn_value,
        .module_value => .module_value,
    };
    const result = switch (ckind) {
        .type_value, .fn_value => true,
        .unknown => switch (ExprKind.classify(f, node_id)) {
            .runtime_value => {
                const n = f.nodes[ExprKind.peelComptimeWrappers(f, node_id)];
                return switch (n.tag) {
                    .identifier, .call, .field => true,
                    else => false,
                };
            },
            else => false,
        },
        else => false,
    };

    if (ctx.type_arg_cache) |cache| {
        cache.put(self.allocator, node_id, result) catch {};
    }
    return result;
}

fn inferComptimeValue(self: *Self, graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, node_id: Ast.NodeId, ctx: *Ctx, fn_bindings: *std.StringHashMapUnmanaged(FnBinding)) ComptimeValue.Value {
    if (ctx.comptime_value_cache) |cache| {
        if (cache.get(node_id)) |v| return v;
    }
    var v = ComptimeValue.inferValue(graph, f, node_id);
    if (v == .unknown) {
        v = self.inferComptimeValueFromCallResult(graph, f, node_id, fn_bindings) orelse v;
    }
    if (ctx.comptime_value_cache) |cache| {
        cache.put(self.allocator, node_id, v) catch {};
    }
    return v;
}

fn inferComptimeValueFromCallResult(self: *Self, graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, node_id: Ast.NodeId, fn_bindings: *std.StringHashMapUnmanaged(FnBinding)) ?ComptimeValue.Value {
    const n = f.nodes[node_id];
    if (n.tag != .call) return null;

    const maybe_binding = self.resolveCalleeFnExprNode(graph, f, n.data.call.callee, fn_bindings) catch return null;
    const binding = maybe_binding orelse return null;
    const callee_file = graph.files.items[binding.file_index];
    const fn_n = callee_file.nodes[binding.node_id];
    if (fn_n.tag != .fn_expr) return null;
    if (!fn_n.data.fn_expr.has_body) return null;

    const body_id = ExprKind.peelComptimeWrappers(callee_file, fn_n.data.fn_expr.body);
    const body = callee_file.nodes[body_id];
    const ident: ComptimeValue.Identity = .{ .file_id = callee_file.file_id, .node_id = body_id };
    return switch (body.tag) {
        .struct_expr, .enum_expr, .type_lit, .ptr_type, .slice_type, .array_type => .{ .type_value = ident },
        .fn_expr => .{ .fn_value = ident },
        .use_expr => .{ .module_value = ident },
        else => null,
    };
}

fn checkMatchArms(self: *Self, graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, n: Ast.Node, subj_t: Type) SemError!void {
    if (n.tag != .match_expr) return;
    try graph.sm.ensureTextLoaded(f.file_id);

    var saw_wildcard = false;
    var saw_true = false;
    var saw_false = false;

    var i: u32 = 0;
    while (i < n.data.match_expr.arm_count) : (i += 1) {
        const arm_i = f.match_arms[n.data.match_expr.arm_start + i];

        if (arm_i.kind == .wildcard) {
            if (saw_wildcard) try self.pushErr(f.file_id, arm_i.span, "overlapping match arm: duplicate '_' wildcard");
            saw_wildcard = true;
            if (i + 1 < n.data.match_expr.arm_count) {
                try self.pushErr(f.file_id, arm_i.span, "overlapping match arm: '_' wildcard must be last");
            }
            continue;
        }

        if (arm_i.kind == .expr) {
            const p = f.nodes[arm_i.pat_start];
            if (p.tag == .bool_lit) {
                const s = graph.sm.spanSlice(f.file_id, p.span) catch "";
                if (std.mem.eql(u8, s, "true")) saw_true = true;
                if (std.mem.eql(u8, s, "false")) saw_false = true;
            }
        }

        var j: u32 = 0;
        while (j < i) : (j += 1) {
            const arm_j = f.match_arms[n.data.match_expr.arm_start + j];
            if (matchArmsOverlap(graph, f, arm_i, arm_j)) {
                try self.pushErr(f.file_id, arm_i.span, "overlapping match arm pattern");
                break;
            }
        }
    }

    if (!saw_wildcard) {
        if (subj_t == .bool_t and saw_true and saw_false) return;
        try self.pushErr(f.file_id, n.span, "non-exhaustive match: add '_' arm");
    }
}

fn matchArmsOverlap(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, a: Ast.MatchArm, b: Ast.MatchArm) bool {
    if (a.kind == .wildcard or b.kind == .wildcard) return true;

    if (a.kind == .expr and b.kind == .expr) {
        return nodesSamePattern(graph, f, a.pat_start, b.pat_start);
    }

    const ar = armIntRange(graph, f, a);
    const br = armIntRange(graph, f, b);
    if (ar != null and br != null) {
        const x = ar.?;
        const y = br.?;
        return !(x.hi < y.lo or y.hi < x.lo);
    }

    if (ar) |x| {
        if (armIntExact(graph, f, b)) |v| return x.lo <= v and v <= x.hi;
    }
    if (br) |y| {
        if (armIntExact(graph, f, a)) |v| return y.lo <= v and v <= y.hi;
    }

    return false;
}

fn nodesSamePattern(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, a_id: Ast.NodeId, b_id: Ast.NodeId) bool {
    const a = f.nodes[a_id];
    const b = f.nodes[b_id];
    if (a.tag != b.tag) return false;
    const sa = graph.sm.spanSlice(f.file_id, a.span) catch return false;
    const sb = graph.sm.spanSlice(f.file_id, b.span) catch return false;
    return std.mem.eql(u8, sa, sb);
}

const IntRange = struct { lo: i64, hi: i64 };

fn armIntExact(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, arm: Ast.MatchArm) ?i64 {
    if (arm.kind != .expr) return null;
    return nodeIntValue(graph, f, arm.pat_start);
}

fn armIntRange(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, arm: Ast.MatchArm) ?IntRange {
    if (arm.kind == .expr) {
        const v = armIntExact(graph, f, arm) orelse return null;
        return .{ .lo = v, .hi = v };
    }
    if (arm.kind != .range) return null;
    const lo = nodeIntValue(graph, f, arm.pat_start) orelse return null;
    const end = nodeIntValue(graph, f, arm.pat_end) orelse return null;
    const hi = if (arm.inclusive) end else end - 1;
    if (hi < lo) return null;
    return .{ .lo = lo, .hi = hi };
}

fn nodeIntValue(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, id: Ast.NodeId) ?i64 {
    const n = f.nodes[id];
    if (n.tag != .int_lit) return null;
    const s = graph.sm.spanSlice(f.file_id, n.span) catch return null;
    return std.fmt.parseInt(i64, s, 10) catch null;
}

fn hasActiveLabel(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, ctx: *Ctx, label_span: Span, require_loop: bool) bool {
    graph.sm.ensureTextLoaded(f.file_id) catch return false;
    const want = graph.sm.spanSlice(f.file_id, label_span) catch return false;
    const stack = ctx.label_stack orelse return false;
    var i: usize = stack.items.len;
    while (i > 0) {
        i -= 1;
        const l = stack.items[i];
        if (!std.mem.eql(u8, l.name, want)) continue;
        if (!require_loop) return true;
        return l.target == .loop;
    }
    return false;
}

fn hasImplicitReceiver(
    graph: *ModuleGraph.Self,
    f: ModuleGraph.FileUnit,
    callee_id: Ast.NodeId,
    fn_bindings: *std.StringHashMapUnmanaged(FnBinding),
    fn_file: ModuleGraph.FileUnit,
    fn_n: Ast.Node,
) bool {
    if (fn_n.tag != .fn_expr or fn_n.data.fn_expr.param_count == 0) return false;
    const first_p = fn_file.nodes[fn_file.list_items[fn_n.data.fn_expr.param_start]];
    if (first_p.tag != .param or first_p.data.param.is_comp) return false;

    const norm = CallNormalize.normalize(graph, f, callee_id) catch return false;
    switch (norm) {
        .field => |fd| {
            if (fd.object_ident) |alias| {
                if (findUseAliasTargetModule(graph, f, alias) != null) return false;
            }
            _ = fn_bindings;
            return true;
        },
        else => return false,
    }
}

fn isNestedFactoryFieldCall(f: ModuleGraph.FileUnit, callee_id: Ast.NodeId) bool {
    const call_callee = f.nodes[callee_id];
    if (call_callee.tag != .field) return false;
    const recv = f.nodes[call_callee.data.field.object];
    return recv.tag == .call;
}

fn nodeGuaranteesValue(f: ModuleGraph.FileUnit, id: Ast.NodeId) bool {
    const n = f.nodes[id];
    return switch (n.tag) {
        .int_lit, .bool_lit, .float_lit, .string_lit, .char_lit, .identifier, .binary, .unary, .call, .index, .slice, .field, .struct_expr, .enum_expr, .fn_expr, .type_lit, .use_expr, .address_of, .deref => true,
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
        .inline_expr, .comp_expr => nodeGuaranteesValue(f, n.data.one.child),
        else => false,
    };
}

fn nodeGuaranteesExplicitReturn(f: ModuleGraph.FileUnit, id: Ast.NodeId) bool {
    const n = f.nodes[id];
    return switch (n.tag) {
        .return_stmt => true,
        .if_expr => n.data.if_expr.has_else and nodeGuaranteesExplicitReturn(f, n.data.if_expr.then_expr) and nodeGuaranteesExplicitReturn(f, n.data.if_expr.else_expr),
        .match_expr => blk: {
            if (n.data.match_expr.arm_count == 0) break :blk false;
            var i: u32 = 0;
            while (i < n.data.match_expr.arm_count) : (i += 1) {
                const arm = f.match_arms[n.data.match_expr.arm_start + i];
                if (!nodeGuaranteesExplicitReturn(f, arm.body)) break :blk false;
            }
            break :blk true;
        },
        .block => blk: {
            if (n.data.block.item_count == 0) break :blk false;
            const last_id = f.list_items[n.data.block.item_start + n.data.block.item_count - 1];
            break :blk nodeGuaranteesExplicitReturn(f, last_id);
        },
        .labeled_block => nodeGuaranteesExplicitReturn(f, n.data.labeled_block.body),
        .inline_expr, .comp_expr => nodeGuaranteesExplicitReturn(f, n.data.one.child),
        else => false,
    };
}

fn nodeAlwaysTransfersControl(f: ModuleGraph.FileUnit, id: Ast.NodeId) bool {
    const n = f.nodes[id];
    return switch (n.tag) {
        .break_stmt, .continue_stmt, .return_stmt => true,
        .if_expr => n.data.if_expr.has_else and nodeAlwaysTransfersControl(f, n.data.if_expr.then_expr) and nodeAlwaysTransfersControl(f, n.data.if_expr.else_expr),
        .match_expr => blk: {
            if (n.data.match_expr.arm_count == 0) break :blk false;
            var i: u32 = 0;
            while (i < n.data.match_expr.arm_count) : (i += 1) {
                const arm = f.match_arms[n.data.match_expr.arm_start + i];
                if (!nodeAlwaysTransfersControl(f, arm.body)) break :blk false;
            }
            break :blk true;
        },
        .block => blk: {
            if (n.data.block.item_count == 0) break :blk false;
            const last = f.list_items[n.data.block.item_start + n.data.block.item_count - 1];
            break :blk nodeAlwaysTransfersControl(f, last);
        },
        .for_stmt => n.data.for_stmt.is_infinite and !containsBreakStatement(f, n.data.for_stmt.body),
        .labeled_block => nodeAlwaysTransfersControl(f, n.data.labeled_block.body),
        .inline_expr, .comp_expr => nodeAlwaysTransfersControl(f, n.data.one.child),
        else => false,
    };
}

fn nodeAlwaysTransfersControlLabeled(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, id: Ast.NodeId, label_span: Span) bool {
    const n = f.nodes[id];
    if (n.tag == .for_stmt and n.data.for_stmt.is_infinite and containsBreakToLabel(graph, f, n.data.for_stmt.body, label_span)) {
        return false;
    }
    return nodeAlwaysTransfersControl(f, id);
}

fn containsBreakToLabel(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, id: Ast.NodeId, label_span: Span) bool {
    const n = f.nodes[id];
    return switch (n.tag) {
        .break_stmt => n.data.break_stmt.has_label and labelNamesEqual(graph, f, n.data.break_stmt.label_span, label_span),
        .if_expr => containsBreakToLabel(graph, f, n.data.if_expr.then_expr, label_span) or (n.data.if_expr.has_else and containsBreakToLabel(graph, f, n.data.if_expr.else_expr, label_span)),
        .match_expr => blk: {
            var i: u32 = 0;
            while (i < n.data.match_expr.arm_count) : (i += 1) {
                const arm = f.match_arms[n.data.match_expr.arm_start + i];
                if (containsBreakToLabel(graph, f, arm.body, label_span)) break :blk true;
            }
            break :blk false;
        },
        .block => blk: {
            var i: u32 = 0;
            while (i < n.data.block.item_count) : (i += 1) {
                if (containsBreakToLabel(graph, f, f.list_items[n.data.block.item_start + i], label_span)) break :blk true;
            }
            break :blk false;
        },
        .for_stmt => containsBreakToLabel(graph, f, n.data.for_stmt.body, label_span),
        .labeled_block => containsBreakToLabel(graph, f, n.data.labeled_block.body, label_span),
        .inline_expr, .comp_expr => containsBreakToLabel(graph, f, n.data.one.child, label_span),
        else => false,
    };
}

fn labelNamesEqual(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, a: Span, b: Span) bool {
    graph.sm.ensureTextLoaded(f.file_id) catch return false;
    const sa = graph.sm.spanSlice(f.file_id, a) catch return false;
    const sb = graph.sm.spanSlice(f.file_id, b) catch return false;
    return std.mem.eql(u8, sa, sb);
}

fn containsBreakStatement(f: ModuleGraph.FileUnit, id: Ast.NodeId) bool {
    const n = f.nodes[id];
    return switch (n.tag) {
        .break_stmt => !n.data.break_stmt.has_label,
        .if_expr => containsBreakStatement(f, n.data.if_expr.then_expr) or (n.data.if_expr.has_else and containsBreakStatement(f, n.data.if_expr.else_expr)),
        .match_expr => blk: {
            var i: u32 = 0;
            while (i < n.data.match_expr.arm_count) : (i += 1) {
                const arm = f.match_arms[n.data.match_expr.arm_start + i];
                if (containsBreakStatement(f, arm.body)) break :blk true;
            }
            break :blk false;
        },
        .block => blk: {
            var i: u32 = 0;
            while (i < n.data.block.item_count) : (i += 1) {
                if (containsBreakStatement(f, f.list_items[n.data.block.item_start + i])) break :blk true;
            }
            break :blk false;
        },
        .for_stmt => false,
        .labeled_block => containsBreakStatement(f, n.data.labeled_block.body),
        .inline_expr, .comp_expr => containsBreakStatement(f, n.data.one.child),
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

test "semantic checker accepts extern fn declaration and typed call" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_extern_fn";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_extern_fn/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "puts := extern fn(*i32) i32\n" ++
                "main := () i32 => puts(\"hi\")\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_extern_fn/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    try std.testing.expectEqual(@as(usize, 0), s.errors.items.len);
}

test "semantic checker enforces match overlap and exhaustiveness" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_match_overlap_exhaustive";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_match_overlap_exhaustive/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "a := match 1 { 1: 1, 1: 2, _: 0 }\n" ++
                "b := match true { true: 1 }\n" ++
                "main := () i32 => a + b\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_match_overlap_exhaustive/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw_overlap = false;
    var saw_exhaustive = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "overlapping match arm pattern")) saw_overlap = true;
        if (std.mem.eql(u8, e.message, "non-exhaustive match: add '_' arm")) saw_exhaustive = true;
    }
    try std.testing.expect(saw_overlap);
    try std.testing.expect(saw_exhaustive);
}

test "semantic checker supports for range capture" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_for_range_capture";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_for_range_capture/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => {\n" ++
                "  mut sum: i32 = 0\n" ++
                "  for 0..5: |i| { sum += i }\n" ++
                "  return sum\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_for_range_capture/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    var saw_for_error = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "for condition must be bool") or
            std.mem.eql(u8, e.message, "for capture requires iterable condition")) saw_for_error = true;
    }
    try std.testing.expect(!saw_for_error);
}

test "semantic checker supports for slice capture" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_for_slice_capture";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_for_slice_capture/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "sum_slice := (buf: *i32, n: i32) i32 => {\n" ++
                "  mut total: i32 = 0\n" ++
                "  for buf[0..n]: |v| { total += v }\n" ++
                "  return total\n" ++
                "}\n" ++
                "main := () i32 => 0\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_for_slice_capture/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw_for_error = false;
    for (s.errors.items) |e| {
        if (std.mem.startsWith(u8, e.message, "for slice") or
            std.mem.eql(u8, e.message, "for condition must be bool") or
            std.mem.eql(u8, e.message, "for capture requires iterable condition")) saw_for_error = true;
    }
    try std.testing.expect(!saw_for_error);
}

test "semantic checker supports for pointer sentinel capture" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_for_pointer_capture";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_for_pointer_capture/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "sum_ptr := (p: *i32) i32 => {\n" ++
                "  mut total: i32 = 0\n" ++
                "  for p: |v| { total += v }\n" ++
                "  return total\n" ++
                "}\n" ++
                "main := () i32 => 0\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_for_pointer_capture/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw_for_error = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "for condition must be bool") or
            std.mem.eql(u8, e.message, "for capture requires iterable condition")) saw_for_error = true;
    }
    try std.testing.expect(!saw_for_error);
}

test "semantic checker supports for named slice binding capture" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_for_named_slice_capture";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_for_named_slice_capture/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "sum_slice := (p: *i32) i32 => {\n" ++
                "  mut total: i32 = 0\n" ++
                "  s := p[0..3]\n" ++
                "  for s: |v| { total += v }\n" ++
                "  return total\n" ++
                "}\n" ++
                "main := () i32 => 0\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_for_named_slice_capture/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw_for_error = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "for condition must be bool") or
            std.mem.eql(u8, e.message, "for capture requires iterable condition")) saw_for_error = true;
    }
    try std.testing.expect(!saw_for_error);
}

test "semantic checker supports aliased named slice binding capture" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_for_aliased_named_slice_capture";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_for_aliased_named_slice_capture/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "sum_slice := (p: *i32) i32 => {\n" ++
                "  mut total: i32 = 0\n" ++
                "  s := p[0..3]\n" ++
                "  t := s\n" ++
                "  for t: |v| { total += v }\n" ++
                "  return total\n" ++
                "}\n" ++
                "main := () i32 => 0\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_for_aliased_named_slice_capture/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw_for_error = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "for condition must be bool") or
            std.mem.eql(u8, e.message, "for capture requires iterable condition")) saw_for_error = true;
    }
    try std.testing.expect(!saw_for_error);
}

test "semantic checker binds if and match captures in arm scopes" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_if_match_captures";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_if_match_captures/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "a := if true: |v| v else false\n" ++
                "b := match 7 { 7: |m| m, _: 0 }\n" ++
                "main := () i32 => if a b else 0\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_if_match_captures/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    try std.testing.expectEqual(@as(usize, 0), s.errors.items.len);
}

test "semantic checker resolves parameters in block-bodied functions" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_block_params";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_block_params/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "id := (size: i32, align: i32) i32 => { size + align }\n" ++
                "main := () i32 => id(1, 2)\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_block_params/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    var saw = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "block-bodied function with return type must use explicit 'return' on all paths")) saw = true;
    }
    try std.testing.expect(saw);
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
        if (std.mem.eql(u8, e.message, "block-bodied function with return type must use explicit 'return' on all paths") or
            std.mem.eql(u8, e.message, "function with return type must return a value on all paths")) saw = true;
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
        if (std.mem.startsWith(u8, e.message, "declaration type does not match initializer:")) saw_decl_mismatch = true;
        if (std.mem.eql(u8, e.message, "numeric operator expects numeric operands")) saw_numeric = true;
        if (std.mem.eql(u8, e.message, "logical operator expects bool operands")) saw_logical = true;
        if (std.mem.eql(u8, e.message, "'!' expects bool operand")) saw_unary_not = true;
        if (std.mem.eql(u8, e.message, "if condition must be bool")) saw_if_cond = true;
        if (std.mem.startsWith(u8, e.message, "assignment type mismatch:")) saw_assign = true;
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
        if (std.mem.startsWith(u8, e.message, "declaration type does not match initializer:")) saw_decl_mismatch = true;
        if (std.mem.startsWith(u8, e.message, "assignment type mismatch:")) saw_assign_mismatch = true;
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

test "semantic checker validates address-of requires addressable expression" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_address_of_lvalue";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_address_of_lvalue/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "x := 1\n" ++
                "p1 := &x\n" ++
                "p2 := &(x + 1)\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_address_of_lvalue/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "'&' expects addressable expression")) saw = true;
    }
    try std.testing.expect(saw);
}

test "semantic checker validates imported alias function call argument types" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_alias_call_args";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_alias_call_args/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "L := use \"lib\"\n" ++
                "ok := L.id(1)\n" ++
                "bad := L.id(\"x\")\n",
        );
    }
    {
        var f = try std.fs.cwd().createFile("tmp_sem_alias_call_args/lib.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module lib\n" ++
                "pub id := (x: i32) i32 => x\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_alias_call_args/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw = false;
    for (s.errors.items) |e| {
        if (std.mem.startsWith(u8, e.message, "function argument type mismatch:")) saw = true;
    }
    try std.testing.expect(saw);
}

test "semantic checker propagates optional and error across calls and control flow" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_optional_error_prop";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_optional_error_prop/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mk_opt := (x: i32) optional => if x > 0 x else 0\n" ++
                "mk_err := (x: i32) error => if x > 0 x else 0\n" ++
                "main := () i32 => mk_opt(1).? + mk_err(2).!\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_optional_error_prop/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    try std.testing.expectEqual(@as(usize, 0), s.errors.items.len);
}

test "semantic checker accepts comptime type parameter calls" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_comp_type_param";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_comp_type_param/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "id := (T: comp type, x: i32) i32 => x\n" ++
                "ok := id(i32, 5)\n" ++
                "bad := id(5, 6)\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_comp_type_param/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw_bad = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "comptime type parameter expects type argument")) saw_bad = true;
    }
    try std.testing.expect(saw_bad);
}

test "semantic checker supports ArrayList(i32) factory method style calls" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_arraylist_factory_style";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_arraylist_factory_style/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "C := use \"std/collections\"\n" ++
                "main := () i32 => {\n" ++
                "  L := C.ArrayList(i32)\n" ++
                "  L.init(2)\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntryWithOptions(alloc, "tmp_sem_arraylist_factory_style/main.dyn", .{ .std_dir = "std" });
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw_unknown = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "unknown identifier")) saw_unknown = true;
    }
    try std.testing.expect(!saw_unknown);
}

test "semantic checker accepts local type factory returning struct expression" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_local_type_factory";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_local_type_factory/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mk := (T: comp type) => struct {\n" ++
                "  id := (self: type, x: i32) i32 => x\n" ++
                "}\n" ++
                "main := () i32 => mk(i32).id(4)\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_local_type_factory/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    try std.testing.expectEqual(@as(usize, 0), s.errors.items.len);
}

test "semantic checker accepts enum expression returned from type factory as comptime type argument" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_enum_factory_type_arg";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_enum_factory_type_arg/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mkE := (T: comp type) => enum { A }\n" ++
                "id := (U: comp type, x: i32) i32 => x\n" ++
                "main := () i32 => id(mkE(i32), 7)\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_enum_factory_type_arg/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    try std.testing.expectEqual(@as(usize, 0), s.errors.items.len);
}

test "semantic checker accepts function expression returned from factory call" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_fn_factory_call";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_fn_factory_call/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mkF := (T: comp type) => (x: i32) i32 => x\n" ++
                "main := () i32 => mkF(i32)(8)\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_fn_factory_call/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    try std.testing.expectEqual(@as(usize, 0), s.errors.items.len);
}

test "semantic checker accepts nested factory member call chains" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_nested_factory_chain";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_nested_factory_chain/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mkA := (T: comp type) => struct {\n" ++
                "  mkB := (self: type, U: comp type) => struct {\n" ++
                "    id := (self: type, x: i32) i32 => x\n" ++
                "  }\n" ++
                "}\n" ++
                "main := () i32 => mkA(i32).mkB(i32).id(11)\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_nested_factory_chain/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    try std.testing.expectEqual(@as(usize, 0), s.errors.items.len);
}

test "semantic checker accepts nested factory chain that returns function" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_nested_factory_ret_fn";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_nested_factory_ret_fn/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mkFn := (T: comp type) => struct {\n" ++
                "  make := (self: type, U: comp type) => (x: i32) i32 => x + 1\n" ++
                "}\n" ++
                "main := () i32 => mkFn(i32).make(i32)(6)\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_nested_factory_ret_fn/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    try std.testing.expectEqual(@as(usize, 0), s.errors.items.len);
}

test "semantic checker accepts nested enum factory chain as comptime type argument" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_nested_enum_factory_type_arg";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_nested_enum_factory_type_arg/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mkE := (T: comp type) => struct {\n" ++
                "  make := (self: type, U: comp type) => enum { A }\n" ++
                "}\n" ++
                "id := (E: comp type, x: i32) i32 => x\n" ++
                "main := () i32 => id(mkE(i32).make(i32), 5)\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_nested_enum_factory_type_arg/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    try std.testing.expectEqual(@as(usize, 0), s.errors.items.len);
}

test "semantic checker reports unreachable after control-transfer if/match" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_unreachable_if_match_transfer";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_unreachable_if_match_transfer/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => {\n" ++
                "  for {\n" ++
                "    if true { break } else { continue }\n" ++
                "    1\n" ++
                "  }\n" ++
                "  for {\n" ++
                "    match 1 { 1 => break, _ => continue }\n" ++
                "    2\n" ++
                "  }\n" ++
                "  0\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_unreachable_if_match_transfer/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var unreachable_count: usize = 0;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "unreachable statement")) unreachable_count += 1;
    }
    try std.testing.expect(unreachable_count >= 1);
}

test "semantic checker enforces return-path through comp/inline wrappers" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_return_path_comp_inline";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_return_path_comp_inline/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "bad1 := () i32 => comp if true 1\n" ++
                "bad2 := () i32 => inline if true 1\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_return_path_comp_inline/main.dyn");
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

test "semantic checker allows pointer mutability merge in branches" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_pointer_merge_mut_const";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_pointer_merge_mut_const/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mut x: i32 = 1\n" ++
                "pm: *mut i32 = &x\n" ++
                "pc: *i32 = &x\n" ++
                "p := if x > 0 pm else pc\n" ++
                "y := p.*\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_pointer_merge_mut_const/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    try std.testing.expectEqual(@as(usize, 0), s.errors.items.len);
}

test "semantic checker supports or fallback for optional and error values" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_or_fallback";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_or_fallback/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mk_opt := (x: i32) optional => x\n" ++
                "mk_err := (x: i32) error => x\n" ++
                "a: i32 = mk_opt(0) or 7\n" ++
                "b: i32 = mk_err(0) or 9\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_or_fallback/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    try std.testing.expectEqual(@as(usize, 0), s.errors.items.len);
}

test "semantic checker requires explicit unwrap or fallback for optional and error" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_optional_error_concrete_use";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_optional_error_concrete_use/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mk_opt := (x: i32) optional => x\n" ++
                "mk_err := (x: i32) error => x\n" ++
                "a: i32 = mk_opt(1)\n" ++
                "b: i32 = mk_err(2)\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_optional_error_concrete_use/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var mismatch_count: usize = 0;
    for (s.errors.items) |e| {
        if (std.mem.startsWith(u8, e.message, "declaration type does not match initializer:")) mismatch_count += 1;
    }
    try std.testing.expect(mismatch_count >= 2);
}

test "semantic checker accepts postfix optional and error type annotations" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_postfix_optional_error_types";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_postfix_optional_error_types/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mk_opt := (x: i32) ?i32 => x\n" ++
                "mk_err := (x: i32) i32!ParseError => x\n" ++
                "a: i32 = mk_opt(1).?\n" ++
                "b: i32 = mk_err(2).!\n" ++
                "c: i32 = mk_opt(0) or 7\n" ++
                "d: i32 = mk_err(0) or 9\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_postfix_optional_error_types/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);
    try std.testing.expectEqual(@as(usize, 0), s.errors.items.len);
}

test "semantic checker types or fallback from optional error to optional" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_or_optional_error_to_optional";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_or_optional_error_to_optional/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mk_opt := (x: i32) ?i32 => x\n" ++
                "mk_opt_err := (x: i32) ?i32!ParseError => x\n" ++
                "ok: ?i32 = mk_opt_err(1) or mk_opt(2)\n" ++
                "bad: i32 = mk_opt_err(1) or mk_opt(2)\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_or_optional_error_to_optional/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw_bad = false;
    for (s.errors.items) |e| {
        if (std.mem.startsWith(u8, e.message, "declaration type does not match initializer:")) saw_bad = true;
    }
    try std.testing.expect(saw_bad);
}

test "semantic checker reports or fallback type mismatch by container kind" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_or_fallback_type_mismatch";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_or_fallback_type_mismatch/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mk_opt := (x: i32) ?i32 => x\n" ++
                "mk_err := (x: i32) i32!ParseError => x\n" ++
                "mk_opt_err := (x: i32) ?i32!ParseError => x\n" ++
                "a := mk_opt(1) or mk_opt(2)\n" ++
                "b := mk_err(1) or mk_opt(2)\n" ++
                "c := mk_opt_err(1) or 7\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_or_fallback_type_mismatch/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw_opt = false;
    var saw_err = false;
    var saw_opt_err = false;
    for (s.errors.items) |e| {
        if (std.mem.indexOf(u8, e.message, "left `?T` expects fallback `i32`, got `?T`") != null) saw_opt = true;
        if (std.mem.indexOf(u8, e.message, "left `T!E` expects fallback `i32`, got `?T`") != null) saw_err = true;
        if (std.mem.indexOf(u8, e.message, "left `?T!E` expects fallback `?T`, got `i32`") != null) saw_opt_err = true;
    }
    try std.testing.expect(saw_opt);
    try std.testing.expect(saw_err);
    try std.testing.expect(saw_opt_err);
}

test "semantic checker infers index and slice types and validates indices" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_index_slice_types";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_index_slice_types/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mut x: i32 = 1\n" ++
                "p: *mut i32 = &x\n" ++
                "a: i32 = p[0]\n" ++
                "s := p[0..1]\n" ++
                "bad1 := p[true]\n" ++
                "bad2 := 1[0]\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_index_slice_types/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw_bad_index_type = false;
    var saw_bad_index_object = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "index expects integer index")) saw_bad_index_type = true;
        if (std.mem.eql(u8, e.message, "index expects pointer/slice value")) saw_bad_index_object = true;
    }
    try std.testing.expect(saw_bad_index_type);
    try std.testing.expect(saw_bad_index_object);
}

test "semantic checker reports unreachable after infinite loop without break" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_unreachable_infinite_loop";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_unreachable_infinite_loop/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => {\n" ++
                "  for { continue }\n" ++
                "  1\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_unreachable_infinite_loop/main.dyn");
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

test "semantic checker keeps outer loop infinite when inner loop breaks" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_outer_loop_infinite_inner_break";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_outer_loop_infinite_inner_break/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => {\n" ++
                "  for {\n" ++
                "    for { break }\n" ++
                "    continue\n" ++
                "  }\n" ++
                "  1\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_outer_loop_infinite_inner_break/main.dyn");
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

test "semantic checker reports incompatible comptime identities in if branches" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_if_comptime_identity_mismatch";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_if_comptime_identity_mismatch/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "x := if true use \"std/mem\" else struct { a: i32 }\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntryWithOptions(alloc, "tmp_sem_if_comptime_identity_mismatch/main.dyn", .{ .std_dir = "std" });
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "if branches must have compatible comptime identities")) saw = true;
    }
    try std.testing.expect(saw);
}

test "semantic checker reports incompatible comptime identities in match arms" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_match_comptime_identity_mismatch";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_match_comptime_identity_mismatch/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "x := match 1 { 0: use \"std/mem\", _: struct { a: i32 } }\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntryWithOptions(alloc, "tmp_sem_match_comptime_identity_mismatch/main.dyn", .{ .std_dir = "std" });
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "match arms must have compatible comptime identities")) saw = true;
    }
    try std.testing.expect(saw);
}

test "semantic checker validates break/continue labels" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_label_validation";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_label_validation/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => {\n" ++
                "  outer: {\n" ++
                "    break:outer\n" ++
                "  }\n" ++
                "  blk: { continue:blk }\n" ++
                "  break:missing\n" ++
                "  0\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_label_validation/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw_continue = false;
    var saw_break = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "'continue' label not found or not loop")) saw_continue = true;
        if (std.mem.eql(u8, e.message, "'break' label not found")) saw_break = true;
    }
    try std.testing.expect(saw_continue);
    try std.testing.expect(saw_break);
}

test "semantic checker accepts loop labels for break and continue" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_loop_label_ok";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_loop_label_ok/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => {\n" ++
                "  L: for {\n" ++
                "    continue:L\n" ++
                "  }\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_loop_label_ok/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw_bad_label = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "'continue' label not found or not loop")) saw_bad_label = true;
        if (std.mem.eql(u8, e.message, "'break' label not found")) saw_bad_label = true;
    }
    try std.testing.expect(!saw_bad_label);
}

test "semantic checker keeps code reachable after labeled infinite loop break" {
    const alloc = std.testing.allocator;
    const dir = "tmp_sem_labeled_loop_reachability";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_sem_labeled_loop_reachability/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => {\n" ++
                "  L: for { break:L }\n" ++
                "  1\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_sem_labeled_loop_reachability/main.dyn");
    defer g.deinit();

    var s = Self.init(alloc);
    defer s.deinit();
    try s.checkGraph(&g);

    var saw_unreachable = false;
    for (s.errors.items) |e| {
        if (std.mem.eql(u8, e.message, "unreachable statement")) saw_unreachable = true;
    }
    try std.testing.expect(!saw_unreachable);
}
