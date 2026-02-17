const std = @import("std");
const Ast = @import("ast.zig");
const Ir = @import("ir.zig");
const ModuleGraph = @import("module_graph.zig");

pub const LowerError = error{
    MissingMainModule,
    MissingMainFunction,
    UnsupportedNode,
    UnknownIdentifier,
    MissingFunction,
    WrongArgCount,
};

const FnDeclRef = struct {
    file_index: u32,
    fn_node: Ast.NodeId,
};

const LowerFunctionCtx = struct {
    graph: *ModuleGraph.Self,
    file_index: u32,
    fn_node: Ast.NodeId,
    fn_indices: *std.StringHashMapUnmanaged(u32),
    rodata_indices: *std.StringHashMapUnmanaged(u32),
    rodata: *std.ArrayListUnmanaged(Ir.StringConst),
    use_alias_modules: std.StringHashMapUnmanaged(u32),
    locals: std.StringHashMapUnmanaged(u32),
    next_slot: u32,
    max_slot: u32,
    instrs: std.ArrayListUnmanaged(Ir.Instruction),
    loop_stack: std.ArrayListUnmanaged(LoopCtx),
};

const LoopCtx = struct {
    continue_target: u32,
    break_jumps: std.ArrayListUnmanaged(u32),
};

pub fn lowerMainProgram(allocator: std.mem.Allocator, graph: *ModuleGraph.Self) !Ir.Program {
    const mod_idx = findMainModule(graph) orelse return error.MissingMainModule;

    var fn_refs: std.StringHashMapUnmanaged(FnDeclRef) = .empty;
    defer {
        var it = fn_refs.keyIterator();
        while (it.next()) |k| allocator.free(k.*);
        fn_refs.deinit(allocator);
    }
    try collectModuleFunctions(allocator, graph, mod_idx, &fn_refs);
    if (fn_refs.get("main") == null) return error.MissingMainFunction;

    var fn_indices: std.StringHashMapUnmanaged(u32) = .empty;
    defer fn_indices.deinit(allocator);

    var rodata_indices: std.StringHashMapUnmanaged(u32) = .empty;
    defer rodata_indices.deinit(allocator);
    var rodata: std.ArrayListUnmanaged(Ir.StringConst) = .empty;
    defer {
        for (rodata.items) |s| if (s.owned) allocator.free(s.bytes);
        rodata.deinit(allocator);
    }

    const fn_count = fn_refs.count();
    const funcs = try allocator.alloc(Ir.Function, fn_count);
    var built_funcs: u32 = 0;
    errdefer {
        var i: u32 = 0;
        while (i < built_funcs) : (i += 1) {
            allocator.free(funcs[i].instructions);
            if (funcs[i].name_owned) allocator.free(funcs[i].name);
        }
        allocator.free(funcs);
    }
    var names = try allocator.alloc([]const u8, fn_count);
    defer allocator.free(names);

    var it = fn_refs.iterator();
    var idx: u32 = 0;
    while (it.next()) |e| : (idx += 1) {
        names[idx] = e.key_ptr.*;
        try fn_indices.put(allocator, names[idx], idx);
    }

    idx = 0;
    while (idx < fn_count) : (idx += 1) {
        const short_name = names[idx];
        const r = fn_refs.get(short_name).?;
        const emitted_name = try allocator.dupe(u8, short_name);
        errdefer allocator.free(emitted_name);
        funcs[idx] = try lowerOneFunction(allocator, graph, r.file_index, r.fn_node, emitted_name, &fn_indices, &rodata_indices, &rodata);
        built_funcs += 1;
    }

    const ro_slice = try rodata.toOwnedSlice(allocator);
    return .{ .functions = funcs, .rodata_strings = ro_slice, .global_count = 0 };
}

pub fn lowerModuleProgram(allocator: std.mem.Allocator, graph: *ModuleGraph.Self, module_index: u32) !Ir.Program {
    var fn_refs: std.StringHashMapUnmanaged(FnDeclRef) = .empty;
    defer {
        var it = fn_refs.keyIterator();
        while (it.next()) |k| allocator.free(k.*);
        fn_refs.deinit(allocator);
    }
    try collectModuleFunctions(allocator, graph, module_index, &fn_refs);

    const fn_count = fn_refs.count();
    const funcs = try allocator.alloc(Ir.Function, fn_count);
    var built_funcs: u32 = 0;
    errdefer {
        var i: u32 = 0;
        while (i < built_funcs) : (i += 1) {
            allocator.free(funcs[i].instructions);
            if (funcs[i].name_owned) allocator.free(funcs[i].name);
        }
        allocator.free(funcs);
    }

    var fn_indices: std.StringHashMapUnmanaged(u32) = .empty;
    defer fn_indices.deinit(allocator);

    var rodata_indices: std.StringHashMapUnmanaged(u32) = .empty;
    defer rodata_indices.deinit(allocator);
    var rodata: std.ArrayListUnmanaged(Ir.StringConst) = .empty;
    defer {
        for (rodata.items) |s| if (s.owned) allocator.free(s.bytes);
        rodata.deinit(allocator);
    }

    var names = try allocator.alloc([]const u8, fn_count);
    defer allocator.free(names);
    var it = fn_refs.iterator();
    var idx: u32 = 0;
    while (it.next()) |e| : (idx += 1) {
        names[idx] = e.key_ptr.*;
        try fn_indices.put(allocator, names[idx], idx);
    }

    idx = 0;
    while (idx < fn_count) : (idx += 1) {
        const short_name = names[idx];
        const ref = fn_refs.get(short_name).?;
        const mod_name = graph.modules.items[module_index].name;
        const emitted_name = if (std.mem.eql(u8, mod_name, "main") and std.mem.eql(u8, short_name, "main"))
            try allocator.dupe(u8, "main")
        else
            try std.fmt.allocPrint(allocator, "m{s}_{s}", .{ mod_name, short_name });
        errdefer allocator.free(emitted_name);

        funcs[idx] = try lowerOneFunction(allocator, graph, ref.file_index, ref.fn_node, emitted_name, &fn_indices, &rodata_indices, &rodata);
        built_funcs += 1;
    }

    const ro_slice = try rodata.toOwnedSlice(allocator);
    return .{ .functions = funcs, .rodata_strings = ro_slice, .global_count = 0 };
}

fn lowerOneFunction(
    allocator: std.mem.Allocator,
    graph: *ModuleGraph.Self,
    file_index: u32,
    fn_node: Ast.NodeId,
    name: []const u8,
    fn_indices: *std.StringHashMapUnmanaged(u32),
    rodata_indices: *std.StringHashMapUnmanaged(u32),
    rodata: *std.ArrayListUnmanaged(Ir.StringConst),
) !Ir.Function {
    const f = graph.files.items[file_index];
    const fn_n = f.nodes[fn_node];
    if (fn_n.tag != .fn_expr) return error.UnsupportedNode;

    var ctx = LowerFunctionCtx{
        .graph = graph,
        .file_index = file_index,
        .fn_node = fn_node,
        .fn_indices = fn_indices,
        .rodata_indices = rodata_indices,
        .rodata = rodata,
        .use_alias_modules = .empty,
        .locals = .empty,
        .next_slot = 0,
        .max_slot = 0,
        .instrs = .empty,
        .loop_stack = .empty,
    };
    defer ctx.locals.deinit(allocator);
    defer {
        var it_alias = ctx.use_alias_modules.keyIterator();
        while (it_alias.next()) |k| allocator.free(k.*);
        ctx.use_alias_modules.deinit(allocator);
    }
    defer ctx.instrs.deinit(allocator);
    defer {
        for (ctx.loop_stack.items) |*lp| lp.break_jumps.deinit(allocator);
        ctx.loop_stack.deinit(allocator);
    }

    var pi: u32 = 0;
    while (pi < fn_n.data.fn_expr.param_count) : (pi += 1) {
        const p = f.nodes[f.list_items[fn_n.data.fn_expr.param_start + pi]];
        if (p.tag != .param) continue;
        var ni: u32 = 0;
        while (ni < p.data.param.name_count) : (ni += 1) {
            const name_node = f.nodes[f.param_name_items[p.data.param.name_start + ni]];
            const pname = try sliceSpan(graph, f.file_id, name_node.span);
            try ctx.locals.put(allocator, pname, ctx.next_slot);
            ctx.next_slot += 1;
            if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;
        }
    }

    try collectUseAliasesForFile(allocator, graph, file_index, &ctx.use_alias_modules);

    try emitExpr(allocator, &ctx, fn_n.data.fn_expr.body);
    try ctx.instrs.append(allocator, .{ .ret = {} });

    return .{
        .name = name,
        .name_owned = true,
        .call_conv = .stack_i64,
        .ret_type = if (fn_n.data.fn_expr.has_ret) try inferScalarTypeFromAnnotation(graph, f.file_id, fn_n.data.fn_expr.ret_node) else .i64,
        .param_type = try inferParamScalarType(graph, f, fn_n),
        .param_count = fn_n.data.fn_expr.param_count,
        .local_count = ctx.max_slot,
        .instructions = try ctx.instrs.toOwnedSlice(allocator),
    };
}

fn inferParamScalarType(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, fn_n: Ast.Node) !Ir.ScalarType {
    if (fn_n.data.fn_expr.param_count == 0) return .i64;
    const p = f.nodes[f.list_items[fn_n.data.fn_expr.param_start]];
    if (p.tag != .param or !p.data.param.has_type) return .i64;
    return inferScalarTypeFromAnnotation(graph, f.file_id, p.data.param.type_node);
}

fn inferScalarTypeFromAnnotation(graph: *ModuleGraph.Self, file_id: @import("source_manager.zig").FileId, node_id: Ast.NodeId) !Ir.ScalarType {
    const fidx = findFileIndex(graph, file_id) orelse return .i64;
    const f = graph.files.items[fidx];
    const n = f.nodes[node_id];
    if (n.tag != .identifier) return .i64;
    const name = try sliceSpan(graph, file_id, n.span);
    if (std.mem.eql(u8, name, "bool")) return .bool;
    return .i64;
}

fn findFileIndex(graph: *ModuleGraph.Self, file_id: @import("source_manager.zig").FileId) ?u32 {
    var i: u32 = 0;
    while (i < graph.files.items.len) : (i += 1) {
        if (graph.files.items[i].file_id == file_id) return i;
    }
    return null;
}

fn emitExpr(allocator: std.mem.Allocator, ctx: *LowerFunctionCtx, node_id: Ast.NodeId) !void {
    const f = ctx.graph.files.items[ctx.file_index];
    const n = f.nodes[node_id];
    switch (n.tag) {
        .int_lit => {
            const sv = try sliceSpan(ctx.graph, f.file_id, n.span);
            const v = std.fmt.parseInt(i64, sv, 10) catch return error.UnsupportedNode;
            try ctx.instrs.append(allocator, .{ .push_const_i64 = v });
        },
        .string_lit => {
            const tok = try sliceSpan(ctx.graph, f.file_id, n.span);
            if (tok.len < 2 or tok[0] != '"' or tok[tok.len - 1] != '"') return error.UnsupportedNode;
            const body = tok[1 .. tok.len - 1];
            const ridx = try internRodataString(allocator, ctx, body);
            try ctx.instrs.append(allocator, .{ .push_rodata_ptr = ridx });
        },
        .identifier => {
            const nm = try sliceSpan(ctx.graph, f.file_id, n.span);
            const slot = ctx.locals.get(nm) orelse return error.UnknownIdentifier;
            try ctx.instrs.append(allocator, .{ .load_local = slot });
        },
        .unary => {
            try emitExpr(allocator, ctx, n.data.unary.rhs);
            switch (n.data.unary.op) {
                .neg => {
                    try ctx.instrs.append(allocator, .{ .push_const_i64 = -1 });
                    try ctx.instrs.append(allocator, .{ .mul = {} });
                },
                .not => {
                    try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
                    try ctx.instrs.append(allocator, .{ .eq = {} });
                },
                .complement => {
                    try ctx.instrs.append(allocator, .{ .push_const_i64 = -1 });
                    try ctx.instrs.append(allocator, .{ .mul = {} });
                    try ctx.instrs.append(allocator, .{ .push_const_i64 = -1 });
                    try ctx.instrs.append(allocator, .{ .add = {} });
                },
            }
        },
        .binary => {
            if (n.data.binary.op == .land) {
                try emitExpr(allocator, ctx, n.data.binary.lhs);
                const jf_lhs = ctx.instrs.items.len;
                try ctx.instrs.append(allocator, .{ .jump_if_false = 0 });

                try emitExpr(allocator, ctx, n.data.binary.rhs);
                const jf_rhs = ctx.instrs.items.len;
                try ctx.instrs.append(allocator, .{ .jump_if_false = 0 });

                try ctx.instrs.append(allocator, .{ .push_const_i64 = 1 });
                const jend = ctx.instrs.items.len;
                try ctx.instrs.append(allocator, .{ .jump = 0 });

                const false_ip: u32 = @intCast(ctx.instrs.items.len);
                try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
                const end_ip: u32 = @intCast(ctx.instrs.items.len);
                ctx.instrs.items[jf_lhs] = .{ .jump_if_false = false_ip };
                ctx.instrs.items[jf_rhs] = .{ .jump_if_false = false_ip };
                ctx.instrs.items[jend] = .{ .jump = end_ip };
                return;
            }

            if (n.data.binary.op == .lor) {
                try emitExpr(allocator, ctx, n.data.binary.lhs);
                const jf_lhs = ctx.instrs.items.len;
                try ctx.instrs.append(allocator, .{ .jump_if_false = 0 });

                try ctx.instrs.append(allocator, .{ .push_const_i64 = 1 });
                const jend1 = ctx.instrs.items.len;
                try ctx.instrs.append(allocator, .{ .jump = 0 });

                const eval_rhs_ip: u32 = @intCast(ctx.instrs.items.len);
                try emitExpr(allocator, ctx, n.data.binary.rhs);
                const jf_rhs = ctx.instrs.items.len;
                try ctx.instrs.append(allocator, .{ .jump_if_false = 0 });
                try ctx.instrs.append(allocator, .{ .push_const_i64 = 1 });
                const jend2 = ctx.instrs.items.len;
                try ctx.instrs.append(allocator, .{ .jump = 0 });

                const false_ip: u32 = @intCast(ctx.instrs.items.len);
                try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
                const end_ip: u32 = @intCast(ctx.instrs.items.len);

                ctx.instrs.items[jf_lhs] = .{ .jump_if_false = eval_rhs_ip };
                ctx.instrs.items[jf_rhs] = .{ .jump_if_false = false_ip };
                ctx.instrs.items[jend1] = .{ .jump = end_ip };
                ctx.instrs.items[jend2] = .{ .jump = end_ip };
                return;
            }

            try emitExpr(allocator, ctx, n.data.binary.lhs);
            try emitExpr(allocator, ctx, n.data.binary.rhs);
            const ins: Ir.Instruction = switch (n.data.binary.op) {
                .add => .{ .add = {} },
                .sub => .{ .sub = {} },
                .mul => .{ .mul = {} },
                .div => .{ .div = {} },
                .mod => .{ .mod = {} },
                .eqeq => .{ .eq = {} },
                .neq => .{ .neq = {} },
                .lt => .{ .lt = {} },
                .lte => .{ .lte = {} },
                .gt => .{ .gt = {} },
                .gte => .{ .gte = {} },
                else => return error.UnsupportedNode,
            };
            try ctx.instrs.append(allocator, ins);
        },
        .call => {
            const callee = f.nodes[n.data.call.callee];
            var call_ins: Ir.Instruction = undefined;
            if (callee.tag == .identifier) {
                const fname = try sliceSpan(ctx.graph, f.file_id, callee.span);
                const fn_index = ctx.fn_indices.get(fname) orelse return error.MissingFunction;
                call_ins = .{ .call = .{ .arg_count = n.data.call.arg_count, .target = .{ .internal_index = fn_index } } };
            } else if (callee.tag == .field) {
                const obj = f.nodes[callee.data.field.object];
                if (obj.tag != .identifier) return error.UnsupportedNode;
                const alias = try sliceSpan(ctx.graph, f.file_id, obj.span);
                const target_mod = ctx.use_alias_modules.get(alias) orelse return error.MissingFunction;
                const mod_name = ctx.graph.modules.items[target_mod].name;
                const member = try sliceSpan(ctx.graph, f.file_id, callee.data.field.field_span);
                const sym = try std.fmt.allocPrint(allocator, "m{s}_{s}", .{ mod_name, member });
                call_ins = .{ .call = .{ .arg_count = n.data.call.arg_count, .target = .{ .external_symbol = .{ .name = sym, .name_owned = true } } } };
            } else return error.UnsupportedNode;

            var i: u32 = 0;
            while (i < n.data.call.arg_count) : (i += 1) {
                try emitExpr(allocator, ctx, f.list_items[n.data.call.arg_start + i]);
            }
            try ctx.instrs.append(allocator, call_ins);
        },
        .assign => {
            const lhs = f.nodes[n.data.assign.lhs];
            if (lhs.tag == .identifier) {
                const lhs_name = try sliceSpan(ctx.graph, f.file_id, lhs.span);
                const slot = ctx.locals.get(lhs_name) orelse return error.UnknownIdentifier;
                try emitExpr(allocator, ctx, n.data.assign.rhs);
                try ctx.instrs.append(allocator, .{ .store_local = slot });
                try ctx.instrs.append(allocator, .{ .load_local = slot });
            } else if (lhs.tag == .deref) {
                try emitExpr(allocator, ctx, lhs.data.one.child);
                try emitExpr(allocator, ctx, n.data.assign.rhs);
                try ctx.instrs.append(allocator, .{ .store_ptr = {} });
            } else return error.UnsupportedNode;
        },
        .if_expr => {
            try emitExpr(allocator, ctx, n.data.if_expr.cond);
            const jif_i = ctx.instrs.items.len;
            try ctx.instrs.append(allocator, .{ .jump_if_false = 0 });
            try emitExpr(allocator, ctx, n.data.if_expr.then_expr);
            const jend_i = ctx.instrs.items.len;
            try ctx.instrs.append(allocator, .{ .jump = 0 });
            const else_ip: u32 = @intCast(ctx.instrs.items.len);
            if (n.data.if_expr.has_else) {
                try emitExpr(allocator, ctx, n.data.if_expr.else_expr);
            } else {
                try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
            }
            const end_ip: u32 = @intCast(ctx.instrs.items.len);
            ctx.instrs.items[jif_i] = .{ .jump_if_false = else_ip };
            ctx.instrs.items[jend_i] = .{ .jump = end_ip };
        },
        .match_expr => {
            const save_next = ctx.next_slot;
            const subj_slot = ctx.next_slot;
            ctx.next_slot += 1;
            if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;

            try emitExpr(allocator, ctx, n.data.match_expr.subject);
            try ctx.instrs.append(allocator, .{ .store_local = subj_slot });

            var end_jumps: std.ArrayListUnmanaged(u32) = .empty;
            defer end_jumps.deinit(allocator);

            var ai: u32 = 0;
            while (ai < n.data.match_expr.arm_count) : (ai += 1) {
                const arm = f.match_arms[n.data.match_expr.arm_start + ai];
                if (arm.kind != .wildcard) {
                    if (arm.kind == .expr) {
                        try ctx.instrs.append(allocator, .{ .load_local = subj_slot });
                        try emitExpr(allocator, ctx, arm.pat_start);
                        try ctx.instrs.append(allocator, .{ .eq = {} });
                        const jf = ctx.instrs.items.len;
                        try ctx.instrs.append(allocator, .{ .jump_if_false = 0 });

                        try emitExpr(allocator, ctx, arm.body);
                        const je = ctx.instrs.items.len;
                        try ctx.instrs.append(allocator, .{ .jump = 0 });
                        try end_jumps.append(allocator, @intCast(je));
                        const next_ip: u32 = @intCast(ctx.instrs.items.len);
                        ctx.instrs.items[jf] = .{ .jump_if_false = next_ip };
                    } else {
                        try ctx.instrs.append(allocator, .{ .load_local = subj_slot });
                        try emitExpr(allocator, ctx, arm.pat_start);
                        try ctx.instrs.append(allocator, .{ .gte = {} });
                        const jf1 = ctx.instrs.items.len;
                        try ctx.instrs.append(allocator, .{ .jump_if_false = 0 });

                        try ctx.instrs.append(allocator, .{ .load_local = subj_slot });
                        try emitExpr(allocator, ctx, arm.pat_end);
                        try ctx.instrs.append(allocator, if (arm.inclusive) .{ .lte = {} } else .{ .lt = {} });
                        const jf2 = ctx.instrs.items.len;
                        try ctx.instrs.append(allocator, .{ .jump_if_false = 0 });

                        try emitExpr(allocator, ctx, arm.body);
                        const je = ctx.instrs.items.len;
                        try ctx.instrs.append(allocator, .{ .jump = 0 });
                        try end_jumps.append(allocator, @intCast(je));

                        const next_ip: u32 = @intCast(ctx.instrs.items.len);
                        ctx.instrs.items[jf1] = .{ .jump_if_false = next_ip };
                        ctx.instrs.items[jf2] = .{ .jump_if_false = next_ip };
                    }
                } else {
                    try emitExpr(allocator, ctx, arm.body);
                    const je = ctx.instrs.items.len;
                    try ctx.instrs.append(allocator, .{ .jump = 0 });
                    try end_jumps.append(allocator, @intCast(je));
                }
            }

            const end_ip: u32 = @intCast(ctx.instrs.items.len);
            for (end_jumps.items) |je| ctx.instrs.items[je] = .{ .jump = end_ip };

            ctx.next_slot = save_next;
        },
        .block => {
            const outer_locals = ctx.locals;
            ctx.locals = try cloneLocals(allocator, &outer_locals);
            defer {
                ctx.locals.deinit(allocator);
                ctx.locals = outer_locals;
            }
            const saved_next = ctx.next_slot;

            if (n.data.block.item_count == 0) {
                try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
                return;
            }

            var i: u32 = 0;
            while (i < n.data.block.item_count) : (i += 1) {
                const child_id = f.list_items[n.data.block.item_start + i];
                const child = f.nodes[child_id];
                const is_last = i + 1 == n.data.block.item_count;

                if (child.tag == .decl and child.data.decl.has_init and child.data.decl.name_count > 0) {
                    const ident = f.nodes[f.decl_name_items[child.data.decl.name_start]];
                    const name = try sliceSpan(ctx.graph, f.file_id, ident.span);
                    const slot = if (ctx.locals.get(name)) |s| s else blk: {
                        const ns = ctx.next_slot;
                        ctx.next_slot += 1;
                        if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;
                        try ctx.locals.put(allocator, name, ns);
                        break :blk ns;
                    };
                    try emitExpr(allocator, ctx, child.data.decl.init_node);
                    try ctx.instrs.append(allocator, .{ .store_local = slot });
                    if (is_last) {
                        try ctx.instrs.append(allocator, .{ .load_local = slot });
                    } else {
                        try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
                        try ctx.instrs.append(allocator, .{ .pop = {} });
                    }
                } else {
                    try emitExpr(allocator, ctx, child_id);
                    if (!is_last) try ctx.instrs.append(allocator, .{ .pop = {} });
                }
            }

            ctx.next_slot = saved_next;
        },
        .for_stmt => {
            const save_next = ctx.next_slot;
            const cond_ip: u32 = @intCast(ctx.instrs.items.len);

            if (!n.data.for_stmt.is_infinite and n.data.for_stmt.cond != Ast.NullNode) {
                try emitExpr(allocator, ctx, n.data.for_stmt.cond);
            } else {
                try ctx.instrs.append(allocator, .{ .push_const_i64 = 1 });
            }
            const jif_end = ctx.instrs.items.len;
            try ctx.instrs.append(allocator, .{ .jump_if_false = 0 });

            try ctx.loop_stack.append(allocator, .{ .continue_target = cond_ip, .break_jumps = .empty });
            const lp_idx = ctx.loop_stack.items.len - 1;

            try emitExpr(allocator, ctx, n.data.for_stmt.body);
            try ctx.instrs.append(allocator, .{ .pop = {} });
            try ctx.instrs.append(allocator, .{ .jump = cond_ip });

            const end_ip: u32 = @intCast(ctx.instrs.items.len);
            ctx.instrs.items[jif_end] = .{ .jump_if_false = end_ip };
            for (ctx.loop_stack.items[lp_idx].break_jumps.items) |bj| {
                ctx.instrs.items[bj] = .{ .jump = end_ip };
            }
            ctx.loop_stack.items[lp_idx].break_jumps.deinit(allocator);
            _ = ctx.loop_stack.pop();

            try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
            ctx.next_slot = save_next;
        },
        .continue_stmt => {
            if (ctx.loop_stack.items.len == 0) return error.UnsupportedNode;
            const target = ctx.loop_stack.items[ctx.loop_stack.items.len - 1].continue_target;
            try ctx.instrs.append(allocator, .{ .jump = target });
            try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
        },
        .break_stmt => {
            if (ctx.loop_stack.items.len == 0) return error.UnsupportedNode;
            if (n.data.break_stmt.has_value) {
                try emitExpr(allocator, ctx, n.data.break_stmt.value);
                try ctx.instrs.append(allocator, .{ .pop = {} });
            }
            const j = ctx.instrs.items.len;
            try ctx.instrs.append(allocator, .{ .jump = 0 });
            try ctx.loop_stack.items[ctx.loop_stack.items.len - 1].break_jumps.append(allocator, @intCast(j));
            try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
        },
        .defer_stmt => {
            try emitExpr(allocator, ctx, n.data.defer_stmt.value);
            try ctx.instrs.append(allocator, .{ .pop = {} });
            try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
        },
        .labeled_block => {
            try emitExpr(allocator, ctx, n.data.labeled_block.body);
        },
        .unwrap_optional => {
            try emitExpr(allocator, ctx, n.data.one.child);
            try ctx.instrs.append(allocator, .{ .unwrap_optional = {} });
        },
        .unwrap_error => {
            try emitExpr(allocator, ctx, n.data.one.child);
            try ctx.instrs.append(allocator, .{ .unwrap_error = {} });
        },
        .deref => {
            try emitExpr(allocator, ctx, n.data.one.child);
            try ctx.instrs.append(allocator, .{ .load_ptr = {} });
        },
        .address_of => {
            const child = f.nodes[n.data.one.child];
            if (child.tag != .identifier) return error.UnsupportedNode;
            const nm = try sliceSpan(ctx.graph, f.file_id, child.span);
            const slot = ctx.locals.get(nm) orelse return error.UnknownIdentifier;
            try ctx.instrs.append(allocator, .{ .addr_of_local = slot });
        },
        .ptr_type => return error.UnsupportedNode,
        else => return error.UnsupportedNode,
    }
}

fn internRodataString(allocator: std.mem.Allocator, ctx: *LowerFunctionCtx, s: []const u8) !u32 {
    if (ctx.rodata_indices.get(s)) |idx| return idx;
    const copy = try allocator.dupe(u8, s);
    const idx: u32 = @intCast(ctx.rodata.items.len);
    try ctx.rodata.append(allocator, .{ .bytes = copy, .owned = true });
    try ctx.rodata_indices.put(allocator, copy, idx);
    return idx;
}

fn sliceSpan(graph: *ModuleGraph.Self, file_id: @import("source_manager.zig").FileId, span: @import("token.zig").Span) ![]const u8 {
    try graph.sm.ensureTextLoaded(file_id);
    return try graph.sm.spanSlice(file_id, span);
}

fn cloneLocals(allocator: std.mem.Allocator, src: *const std.StringHashMapUnmanaged(u32)) !std.StringHashMapUnmanaged(u32) {
    var out: std.StringHashMapUnmanaged(u32) = .empty;
    var it = src.iterator();
    while (it.next()) |e| try out.put(allocator, e.key_ptr.*, e.value_ptr.*);
    return out;
}

fn findMainModule(graph: *ModuleGraph.Self) ?u32 {
    var i: u32 = 0;
    while (i < graph.modules.items.len) : (i += 1) {
        if (std.mem.eql(u8, graph.modules.items[i].name, "main")) return i;
    }
    return null;
}

fn collectModuleFunctions(
    allocator: std.mem.Allocator,
    graph: *ModuleGraph.Self,
    module_index: u32,
    out: *std.StringHashMapUnmanaged(FnDeclRef),
) !void {
    const m = graph.modules.items[module_index];
    var mf: u32 = 0;
    while (mf < m.file_count) : (mf += 1) {
        const file_index = graph.module_file_indices.items[m.file_start + mf];
        const f = graph.files.items[file_index];
        const root = f.root orelse continue;
        const rn = f.nodes[root];
        if (rn.tag != .block) continue;

        var i: u32 = 0;
        while (i < rn.data.block.item_count) : (i += 1) {
            const n_id = f.list_items[rn.data.block.item_start + i];
            const n = f.nodes[n_id];
            if (n.tag != .decl or !n.data.decl.has_init or n.data.decl.name_count == 0) continue;
            const init_n = f.nodes[n.data.decl.init_node];
            if (init_n.tag != .fn_expr) continue;

            const ident = f.nodes[f.decl_name_items[n.data.decl.name_start]];
            const name = try sliceSpan(graph, f.file_id, ident.span);
            if (out.get(name) == null) {
                const copy = try allocator.dupe(u8, name);
                try out.put(allocator, copy, .{ .file_index = file_index, .fn_node = n.data.decl.init_node });
            }
        }
    }
}

fn collectUseAliasesForFile(
    allocator: std.mem.Allocator,
    graph: *ModuleGraph.Self,
    file_index: u32,
    out: *std.StringHashMapUnmanaged(u32),
) !void {
    const f = graph.files.items[file_index];
    const root = f.root orelse return;
    const rn = f.nodes[root];
    if (rn.tag != .block) return;

    var i: u32 = 0;
    while (i < rn.data.block.item_count) : (i += 1) {
        const n_id = f.list_items[rn.data.block.item_start + i];
        const n = f.nodes[n_id];
        if (n.tag != .decl or !n.data.decl.has_init or n.data.decl.name_count == 0) continue;
        const init_n = f.nodes[n.data.decl.init_node];
        if (init_n.tag != .use_expr) continue;

        var to_mod: ?u32 = null;
        for (graph.edges.items) |e| {
            if (e.file_id == f.file_id and e.span.start == init_n.data.use_expr.path_span.start and e.span.end == init_n.data.use_expr.path_span.end) {
                to_mod = e.to_module;
                break;
            }
        }
        if (to_mod == null) continue;

        const ident = f.nodes[f.decl_name_items[n.data.decl.name_start]];
        const alias = try sliceSpan(graph, f.file_id, ident.span);
        if (out.get(alias) == null) {
            const copy = try allocator.dupe(u8, alias);
            try out.put(allocator, copy, to_mod.?);
        }
    }
}

test "lower main from frontend module" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mul := (x: i32, y: i32) i32 => x * y\n" ++
                "main := () i32 => if 1 < 2 mul(6, 7) else 0\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 42), code);
}

test "lower for loop and match" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_loop_match";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_loop_match/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => {\n" ++
                "  i: i32 = 0\n" ++
                "  sum: i32 = 0\n" ++
                "  for i < 4 {\n" ++
                "    sum = sum + i\n" ++
                "    i = i + 1\n" ++
                "  }\n" ++
                "  match sum { 6: 99, _: sum }\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_loop_match/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 99), code);
}

test "lower logical operators and unary not" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_logic";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_logic/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => if !(0) && (1 || 0) 13 else 2\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_logic/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 13), code);
}

test "lower labeled block and defer stmt" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_misc";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_misc/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => { lbl: { defer { 999 } 21 } }\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_misc/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 21), code);
}

test "lower preserves bool return type metadata" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_bool_meta";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_bool_meta/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () bool => 1 < 2\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_bool_meta/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);
    try std.testing.expectEqual(Ir.ScalarType.bool, p.functions[0].ret_type);
    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 1), code);
}

test "lower pointer address and deref assignment" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_ptr";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_ptr/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => {\n" ++
                "  mut x = 1\n" ++
                "  p: *mut i32 = &x\n" ++
                "  p.* = 7\n" ++
                "  x\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_ptr/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 7), code);
}

test "lower unwrap operators emit runtime IR checks" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_unwrap";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_unwrap/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => {\n" ++
                "  o: optional = 9\n" ++
                "  e: error = 5\n" ++
                "  e.!\n" ++
                "  o.?\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_unwrap/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    var saw_optional = false;
    var saw_error = false;
    for (p.functions[0].instructions) |ins| {
        switch (ins) {
            .unwrap_optional => saw_optional = true,
            .unwrap_error => saw_error = true,
            else => {},
        }
    }
    try std.testing.expect(saw_optional);
    try std.testing.expect(saw_error);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 9), code);
}

test "lower unwrap optional fails at runtime for zero sentinel" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_unwrap_fail";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_unwrap_fail/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => {\n" ++
                "  o: optional = 0\n" ++
                "  o.?\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_unwrap_fail/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    try std.testing.expectError(error.UnsupportedIr, @import("backend_native.zig").lowerMainExitCode(p));
}

test "lower interns string literal into rodata" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_rodata";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_rodata/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nmain := () i32 => { tmp := \"hello\" 7 }\n");
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_rodata/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);
    try std.testing.expectEqual(@as(usize, 1), p.rodata_strings.len);
    try std.testing.expectEqualStrings("hello", p.rodata_strings[0].bytes);
}
