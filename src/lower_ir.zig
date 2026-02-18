const std = @import("std");
const Ast = @import("ast.zig");
const Ir = @import("ir.zig");
const ModuleGraph = @import("module_graph.zig");
const CalleeResolve = @import("callee_resolve.zig");
const ExprKind = @import("expr_kind.zig");
const GraphUtil = @import("graph_util.zig");
const CallNormalize = @import("call_normalize.zig");

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

const FnInstance = struct {
    lowered_name: []const u8,
    ref: FnDeclRef,
};

const SliceLocal = struct {
    ptr_slot: u32,
    rem_slot: u32,
};

const LowerFunctionCtx = struct {
    graph: *ModuleGraph.Self,
    file_index: u32,
    fn_node: Ast.NodeId,
    fn_indices: *std.StringHashMapUnmanaged(u32),
    fn_refs: *const std.StringHashMapUnmanaged(FnDeclRef),
    rodata_indices: *std.StringHashMapUnmanaged(u32),
    rodata: *std.ArrayListUnmanaged(Ir.StringConst),
    use_alias_modules: std.StringHashMapUnmanaged(u32),
    locals: std.StringHashMapUnmanaged(u32),
    slice_locals: std.StringHashMapUnmanaged(SliceLocal),
    next_slot: u32,
    max_slot: u32,
    instrs: std.ArrayListUnmanaged(Ir.Instruction),
    loop_stack: std.ArrayListUnmanaged(LoopCtx),
    comptime_cache: std.AutoHashMapUnmanaged(Ast.NodeId, i64),
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

    var instances: std.ArrayListUnmanaged(FnInstance) = .empty;
    defer {
        for (instances.items) |inst| allocator.free(inst.lowered_name);
        instances.deinit(allocator);
    }

    var it_seed = fn_refs.iterator();
    while (it_seed.next()) |e| {
        const df = graph.files.items[e.value_ptr.file_index];
        const dn = df.nodes[e.value_ptr.fn_node];
        if (dn.tag == .fn_expr and dn.data.fn_expr.is_extern) continue;
        try instances.append(allocator, .{ .lowered_name = try allocator.dupe(u8, e.key_ptr.*), .ref = e.value_ptr.* });
    }
    try collectComptimeTypeSpecializations(allocator, graph, mod_idx, &fn_refs, &instances);

    const fn_count = instances.items.len;
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
    var idx: u32 = 0;
    while (idx < fn_count) : (idx += 1) {
        try fn_indices.put(allocator, instances.items[idx].lowered_name, idx);
    }

    idx = 0;
    while (idx < fn_count) : (idx += 1) {
        const inst = instances.items[idx];
        const emitted_name = try allocator.dupe(u8, inst.lowered_name);
        errdefer allocator.free(emitted_name);
        funcs[idx] = try lowerOneFunction(allocator, graph, inst.ref.file_index, inst.ref.fn_node, emitted_name, &fn_indices, &fn_refs, &rodata_indices, &rodata);
        built_funcs += 1;
    }

    const ro_slice = try rodata.toOwnedSlice(allocator);
    return .{ .functions = funcs, .rodata_strings = ro_slice, .global_count = 0 };
}

fn collectComptimeTypeSpecializations(
    allocator: std.mem.Allocator,
    graph: *ModuleGraph.Self,
    module_index: u32,
    fn_refs: *const std.StringHashMapUnmanaged(FnDeclRef),
    instances: *std.ArrayListUnmanaged(FnInstance),
) !void {
    const m = graph.modules.items[module_index];
    var mf: u32 = 0;
    while (mf < m.file_count) : (mf += 1) {
        const file_index = graph.module_file_indices.items[m.file_start + mf];
        const f = graph.files.items[file_index];
        const root = f.root orelse continue;
        try scanNodeForSpecializations(allocator, graph, f, root, fn_refs, instances);
    }
}

fn scanNodeForSpecializations(
    allocator: std.mem.Allocator,
    graph: *ModuleGraph.Self,
    f: ModuleGraph.FileUnit,
    node_id: Ast.NodeId,
    fn_refs: *const std.StringHashMapUnmanaged(FnDeclRef),
    instances: *std.ArrayListUnmanaged(FnInstance),
) !void {
    const n = f.nodes[node_id];
    switch (n.tag) {
        .call => {
            const callee = f.nodes[n.data.call.callee];
            if (callee.tag == .identifier) {
                const fname = try sliceSpan(graph, f.file_id, callee.span);
                if (fn_refs.get(fname)) |decl_ref| {
                    const dfile = graph.files.items[decl_ref.file_index];
                    const dfn = dfile.nodes[decl_ref.fn_node];
                    if (hasComptimeTypeParam(dfile, dfn)) {
                        if (try makeSpecializedCallName(allocator, graph, f, n, dfile, dfn, fname)) |spec| {
                            defer allocator.free(spec);
                            if (!hasInstanceName(instances.items, spec)) {
                                try instances.append(allocator, .{ .lowered_name = try allocator.dupe(u8, spec), .ref = decl_ref });
                            }
                        }
                    }
                }
            }
            var i: u32 = 0;
            while (i < n.data.call.arg_count) : (i += 1) {
                try scanNodeForSpecializations(allocator, graph, f, f.list_items[n.data.call.arg_start + i], fn_refs, instances);
            }
        },
        .binary => {
            try scanNodeForSpecializations(allocator, graph, f, n.data.binary.lhs, fn_refs, instances);
            try scanNodeForSpecializations(allocator, graph, f, n.data.binary.rhs, fn_refs, instances);
        },
        .unary => try scanNodeForSpecializations(allocator, graph, f, n.data.unary.rhs, fn_refs, instances),
        .deref, .unwrap_optional, .unwrap_error, .inline_expr, .comp_expr, .address_of => try scanNodeForSpecializations(allocator, graph, f, n.data.one.child, fn_refs, instances),
        .return_stmt => if (n.data.return_stmt.has_value) try scanNodeForSpecializations(allocator, graph, f, n.data.return_stmt.value, fn_refs, instances),
        .assign => {
            try scanNodeForSpecializations(allocator, graph, f, n.data.assign.lhs, fn_refs, instances);
            try scanNodeForSpecializations(allocator, graph, f, n.data.assign.rhs, fn_refs, instances);
        },
        .if_expr => {
            try scanNodeForSpecializations(allocator, graph, f, n.data.if_expr.cond, fn_refs, instances);
            try scanNodeForSpecializations(allocator, graph, f, n.data.if_expr.then_expr, fn_refs, instances);
            if (n.data.if_expr.has_else) try scanNodeForSpecializations(allocator, graph, f, n.data.if_expr.else_expr, fn_refs, instances);
        },
        .block => {
            var bi: u32 = 0;
            while (bi < n.data.block.item_count) : (bi += 1) {
                try scanNodeForSpecializations(allocator, graph, f, f.list_items[n.data.block.item_start + bi], fn_refs, instances);
            }
        },
        .decl => {
            if (n.data.decl.has_type) try scanNodeForSpecializations(allocator, graph, f, n.data.decl.type_node, fn_refs, instances);
            if (n.data.decl.has_init) try scanNodeForSpecializations(allocator, graph, f, n.data.decl.init_node, fn_refs, instances);
        },
        .fn_expr => if (n.data.fn_expr.has_body) try scanNodeForSpecializations(allocator, graph, f, n.data.fn_expr.body, fn_refs, instances),
        .match_expr => {
            try scanNodeForSpecializations(allocator, graph, f, n.data.match_expr.subject, fn_refs, instances);
            var mi: u32 = 0;
            while (mi < n.data.match_expr.arm_count) : (mi += 1) {
                const arm = f.match_arms[n.data.match_expr.arm_start + mi];
                try scanNodeForSpecializations(allocator, graph, f, arm.body, fn_refs, instances);
            }
        },
        .for_stmt => {
            if (!n.data.for_stmt.is_infinite and n.data.for_stmt.cond != Ast.NullNode) {
                try scanNodeForSpecializations(allocator, graph, f, n.data.for_stmt.cond, fn_refs, instances);
            }
            try scanNodeForSpecializations(allocator, graph, f, n.data.for_stmt.body, fn_refs, instances);
        },
        else => {},
    }
}

fn hasComptimeTypeParam(f: ModuleGraph.FileUnit, fn_n: Ast.Node) bool {
    if (fn_n.tag != .fn_expr) return false;
    var i: u32 = 0;
    while (i < fn_n.data.fn_expr.param_count) : (i += 1) {
        const p = f.nodes[f.list_items[fn_n.data.fn_expr.param_start + i]];
        if (p.tag == .param and p.data.param.is_comp and p.data.param.has_type and f.nodes[p.data.param.type_node].tag == .type_lit) return true;
    }
    return false;
}

fn makeSpecializedCallName(
    allocator: std.mem.Allocator,
    graph: *ModuleGraph.Self,
    call_file: ModuleGraph.FileUnit,
    call_n: Ast.Node,
    decl_file: ModuleGraph.FileUnit,
    fn_decl: Ast.Node,
    base_name: []const u8,
) !?[]u8 {
    if (call_n.data.call.arg_count != fn_decl.data.fn_expr.param_count) return null;
    var buf: std.ArrayList(u8) = .empty;
    defer buf.deinit(allocator);
    try buf.writer(allocator).print("{s}$", .{base_name});
    var has = false;
    var i: u32 = 0;
    while (i < fn_decl.data.fn_expr.param_count) : (i += 1) {
        const p = decl_file.nodes[decl_file.list_items[fn_decl.data.fn_expr.param_start + i]];
        if (!(p.tag == .param and p.data.param.is_comp and p.data.param.has_type and decl_file.nodes[p.data.param.type_node].tag == .type_lit)) continue;
        const arg_id = call_file.list_items[call_n.data.call.arg_start + i];
        const a = call_file.nodes[arg_id];
        var arg_text: []const u8 = "anon";
        if (a.tag == .identifier or a.tag == .type_lit) {
            arg_text = (try sliceSpan(graph, call_file.file_id, a.span));
        }
        if (has) try buf.append(allocator, ',');
        has = true;
        try buf.writer(allocator).print("{s}", .{arg_text});
    }
    if (!has) return null;
    return try buf.toOwnedSlice(allocator);
}

fn hasInstanceName(items: []const FnInstance, name: []const u8) bool {
    for (items) |itn| {
        if (std.mem.eql(u8, itn.lowered_name, name)) return true;
    }
    return false;
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

        funcs[idx] = try lowerOneFunction(allocator, graph, ref.file_index, ref.fn_node, emitted_name, &fn_indices, &fn_refs, &rodata_indices, &rodata);
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
    fn_refs: *const std.StringHashMapUnmanaged(FnDeclRef),
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
        .fn_refs = fn_refs,
        .rodata_indices = rodata_indices,
        .rodata = rodata,
        .use_alias_modules = .empty,
        .locals = .empty,
        .slice_locals = .empty,
        .next_slot = 0,
        .max_slot = 0,
        .instrs = .empty,
        .loop_stack = .empty,
        .comptime_cache = .empty,
    };
    defer ctx.locals.deinit(allocator);
    defer ctx.slice_locals.deinit(allocator);
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
    defer ctx.comptime_cache.deinit(allocator);

    var pi: u32 = 0;
    while (pi < fn_n.data.fn_expr.param_count) : (pi += 1) {
        const p = f.nodes[f.list_items[fn_n.data.fn_expr.param_start + pi]];
        if (p.tag != .param) continue;
        if (p.data.param.is_comp) continue;
        const is_slice_param = isSliceParamType(f, p);
        var ni: u32 = 0;
        while (ni < p.data.param.name_count) : (ni += 1) {
            const name_node = f.nodes[f.param_name_items[p.data.param.name_start + ni]];
            const pname = try sliceSpan(graph, f.file_id, name_node.span);
            if (is_slice_param) {
                const ptr_slot = ctx.next_slot;
                const len_slot = ctx.next_slot + 1;
                try ctx.locals.put(allocator, pname, ptr_slot);
                try ctx.slice_locals.put(allocator, pname, .{ .ptr_slot = ptr_slot, .rem_slot = len_slot });
                ctx.next_slot += 2;
            } else {
                try ctx.locals.put(allocator, pname, ctx.next_slot);
                ctx.next_slot += 1;
            }
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
        .param_count = runtimeParamCount(f, fn_n),
        .local_count = ctx.max_slot,
        .instructions = try ctx.instrs.toOwnedSlice(allocator),
    };
}

fn runtimeParamCount(f: ModuleGraph.FileUnit, fn_n: Ast.Node) u32 {
    var out: u32 = 0;
    var i: u32 = 0;
    while (i < fn_n.data.fn_expr.param_count) : (i += 1) {
        const p = f.nodes[f.list_items[fn_n.data.fn_expr.param_start + i]];
        if (p.tag != .param) continue;
        if (p.data.param.is_comp) continue;
        const width: u32 = if (isSliceParamType(f, p)) 2 else 1;
        out += p.data.param.name_count * width;
    }
    return out;
}

fn inferParamScalarType(graph: *ModuleGraph.Self, f: ModuleGraph.FileUnit, fn_n: Ast.Node) !Ir.ScalarType {
    if (fn_n.data.fn_expr.param_count == 0) return .i64;
    var i: u32 = 0;
    while (i < fn_n.data.fn_expr.param_count) : (i += 1) {
        const p = f.nodes[f.list_items[fn_n.data.fn_expr.param_start + i]];
        if (p.tag != .param or p.data.param.is_comp) continue;
        if (!p.data.param.has_type) return .i64;
        return inferScalarTypeFromAnnotation(graph, f.file_id, p.data.param.type_node);
    }
    return .i64;
}

fn inferScalarTypeFromAnnotation(graph: *ModuleGraph.Self, file_id: @import("source_manager.zig").FileId, node_id: Ast.NodeId) !Ir.ScalarType {
    const fidx = GraphUtil.findFileIndex(graph, file_id) orelse return .i64;
    const f = graph.files.items[fidx];
    const n = f.nodes[node_id];
    if (n.tag != .identifier) return .i64;
    const name = try sliceSpan(graph, file_id, n.span);
    if (std.mem.eql(u8, name, "bool")) return .bool;
    return .i64;
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
        .bool_lit => {
            const sv = try sliceSpan(ctx.graph, f.file_id, n.span);
            try ctx.instrs.append(allocator, .{ .push_const_i64 = if (std.mem.eql(u8, sv, "true")) 1 else 0 });
        },
        .string_lit => {
            const tok = try sliceSpan(ctx.graph, f.file_id, n.span);
            if (tok.len < 2 or tok[0] != '"' or tok[tok.len - 1] != '"') return error.UnsupportedNode;
            const body = tok[1 .. tok.len - 1];
            const ridx = try internRodataString(allocator, ctx, body);
            try ctx.instrs.append(allocator, .{ .push_rodata_ptr = ridx });
        },
        .inline_expr => {
            try emitExpr(allocator, ctx, n.data.one.child);
        },
        .comp_expr => {
            if (evalComptimeConst(ctx, n.data.one.child)) |v| {
                try ctx.instrs.append(allocator, .{ .push_const_i64 = v });
            } else return error.UnsupportedComptime;
        },
        .struct_expr, .enum_expr, .fn_expr => {
            try ctx.instrs.append(allocator, .{ .push_const_i64 = 1 });
        },
        .identifier => {
            const nm = try sliceSpan(ctx.graph, f.file_id, n.span);
            const slot = ctx.locals.get(nm) orelse return error.UnknownIdentifier;
            try ctx.instrs.append(allocator, .{ .load_local = slot });
        },
        .field => {
            const obj = f.nodes[n.data.field.object];
            if (obj.tag != .identifier) return error.UnsupportedNode;
            const nm = try sliceSpan(ctx.graph, f.file_id, obj.span);
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
                const tmp_slot = ctx.next_slot;
                ctx.next_slot += 1;
                if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;

                try ctx.instrs.append(allocator, .{ .store_local = tmp_slot });
                try ctx.instrs.append(allocator, .{ .load_local = tmp_slot });

                const jf_lhs = ctx.instrs.items.len;
                try ctx.instrs.append(allocator, .{ .jump_if_false = 0 });

                try ctx.instrs.append(allocator, .{ .load_local = tmp_slot });
                const jend1 = ctx.instrs.items.len;
                try ctx.instrs.append(allocator, .{ .jump = 0 });

                const eval_rhs_ip: u32 = @intCast(ctx.instrs.items.len);
                try emitExpr(allocator, ctx, n.data.binary.rhs);
                const end_ip: u32 = @intCast(ctx.instrs.items.len);

                ctx.instrs.items[jf_lhs] = .{ .jump_if_false = eval_rhs_ip };
                ctx.instrs.items[jend1] = .{ .jump = end_ip };
                ctx.next_slot = tmp_slot;
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
            const norm = try CallNormalize.normalize(ctx.graph, f, n.data.call.callee);
            var call_ins: Ir.Instruction = undefined;
            var runtime_arg_count: u32 = 0;
            if (norm == .identifier) {
                const fname = norm.identifier;
                if (ctx.fn_refs.get(fname)) |decl_ref| {
                    const decl_file = ctx.graph.files.items[decl_ref.file_index];
                    const fn_decl = decl_file.nodes[decl_ref.fn_node];
                    runtime_arg_count = try emitCallArgsForFnDecl(allocator, ctx, n, decl_file, fn_decl);
                    if (fn_decl.tag == .fn_expr and fn_decl.data.fn_expr.is_extern) {
                        const sym = try allocator.dupe(u8, fname);
                        call_ins = .{ .call = .{ .arg_count = runtime_arg_count, .target = .{ .external_symbol = .{ .name = sym, .name_owned = true } } } };
                    } else {
                        var target_name = fname;
                        var owned_spec: ?[]u8 = null;
                        defer if (owned_spec) |s| allocator.free(s);
                        if (try makeSpecializedCallName(allocator, ctx.graph, f, n, decl_file, fn_decl, fname)) |spec_name| {
                            owned_spec = spec_name;
                            if (ctx.fn_indices.get(spec_name) != null) target_name = spec_name;
                        }
                        const fn_index = ctx.fn_indices.get(target_name) orelse return error.MissingFunction;
                        call_ins = .{ .call = .{ .arg_count = runtime_arg_count, .target = .{ .internal_index = fn_index } } };
                    }
                } else {
                    var i_emit: u32 = 0;
                    while (i_emit < n.data.call.arg_count) : (i_emit += 1) {
                        try emitExpr(allocator, ctx, f.list_items[n.data.call.arg_start + i_emit]);
                    }
                    runtime_arg_count = n.data.call.arg_count;
                    const fn_index = ctx.fn_indices.get(fname) orelse return error.MissingFunction;
                    call_ins = .{ .call = .{ .arg_count = runtime_arg_count, .target = .{ .internal_index = fn_index } } };
                }
            } else if (norm == .call_of_identifier or norm == .call_of_field) {
                const inner_callee = f.nodes[callee.data.call.callee];
                var base_name: []const u8 = undefined;
                var decl_ref: FnDeclRef = undefined;
                if (inner_callee.tag == .identifier) {
                    base_name = switch (norm) {
                        .call_of_identifier => |nname| nname,
                        else => unreachable,
                    };
                    decl_ref = ctx.fn_refs.get(base_name) orelse return error.UnsupportedNode;
                } else if (inner_callee.tag == .field) {
                    base_name = switch (norm) {
                        .call_of_field => |m| m,
                        else => unreachable,
                    };
                    if (ctx.fn_refs.get(base_name)) |dr| {
                        decl_ref = dr;
                    } else if (findUniqueImportedModuleFunction(ctx, base_name)) |resolved| {
                        decl_ref = resolved.decl;
                    } else return error.UnsupportedNode;
                } else return error.UnsupportedNode;
                const decl_file = ctx.graph.files.items[decl_ref.file_index];
                const fn_decl = decl_file.nodes[decl_ref.fn_node];
                if (fn_decl.tag != .fn_expr) return error.UnsupportedNode;
                const ret_node_id = ExprKind.peelComptimeWrappers(decl_file, fn_decl.data.fn_expr.body);
                const ret_fn = decl_file.nodes[ret_node_id];
                if (ret_fn.tag != .fn_expr) return error.UnsupportedNode;

                const ret_name = try std.fmt.allocPrint(allocator, "{s}$retfn", .{base_name});
                defer allocator.free(ret_name);
                const fn_index = ctx.fn_indices.get(ret_name) orelse return error.MissingFunction;
                runtime_arg_count = try emitCallArgsForFnDecl(allocator, ctx, n, decl_file, ret_fn);
                call_ins = .{ .call = .{ .arg_count = runtime_arg_count, .target = .{ .internal_index = fn_index } } };
            } else if (norm == .field) {
                const fd = norm.field;
                const member = fd.member;
                if (fd.object_ident) |alias| {
                    if (ctx.use_alias_modules.get(alias)) |target_mod| {
                        const mod_name = ctx.graph.modules.items[target_mod].name;
                        const sym = try std.fmt.allocPrint(allocator, "m{s}_{s}", .{ mod_name, member });
                        if (findModuleFunctionDeclRef(ctx.graph, target_mod, member)) |decl_ref| {
                            const decl_file = ctx.graph.files.items[decl_ref.file_index];
                            const fn_decl = decl_file.nodes[decl_ref.fn_node];
                            runtime_arg_count = try emitCallArgsForFnDecl(allocator, ctx, n, decl_file, fn_decl);
                        } else {
                            var i_emit: u32 = 0;
                            while (i_emit < n.data.call.arg_count) : (i_emit += 1) {
                                try emitExpr(allocator, ctx, f.list_items[n.data.call.arg_start + i_emit]);
                            }
                            runtime_arg_count = n.data.call.arg_count;
                        }
                        call_ins = .{ .call = .{ .arg_count = runtime_arg_count, .target = .{ .external_symbol = .{ .name = sym, .name_owned = true } } } };
                    } else {
                        if (ctx.fn_refs.get(member)) |decl_ref| {
                            const fn_index = ctx.fn_indices.get(member) orelse return error.MissingFunction;
                            const decl_file = ctx.graph.files.items[decl_ref.file_index];
                            const fn_decl = decl_file.nodes[decl_ref.fn_node];
                            runtime_arg_count = try emitMethodCallArgsForFnDecl(allocator, ctx, n, decl_file, fn_decl, fd.object);
                            call_ins = .{ .call = .{ .arg_count = runtime_arg_count, .target = .{ .internal_index = fn_index } } };
                        } else if (findUniqueImportedModuleFunction(ctx, member)) |resolved| {
                            const mod_name = ctx.graph.modules.items[resolved.module_index].name;
                            const sym = try std.fmt.allocPrint(allocator, "m{s}_{s}", .{ mod_name, member });
                            const decl_file = ctx.graph.files.items[resolved.decl.file_index];
                            const fn_decl = decl_file.nodes[resolved.decl.fn_node];
                            runtime_arg_count = try emitMethodCallArgsForFnDecl(allocator, ctx, n, decl_file, fn_decl, fd.object);
                            call_ins = .{ .call = .{ .arg_count = runtime_arg_count, .target = .{ .external_symbol = .{ .name = sym, .name_owned = true } } } };
                        } else {
                            try emitExpr(allocator, ctx, fd.object);
                            var i_emit: u32 = 0;
                            while (i_emit < n.data.call.arg_count) : (i_emit += 1) {
                                try emitExpr(allocator, ctx, f.list_items[n.data.call.arg_start + i_emit]);
                            }
                            runtime_arg_count = n.data.call.arg_count + 1;
                            const fn_index = ctx.fn_indices.get(member) orelse return error.MissingFunction;
                            call_ins = .{ .call = .{ .arg_count = runtime_arg_count, .target = .{ .internal_index = fn_index } } };
                        }
                    }
                } else {
                    if (ctx.fn_refs.get(member)) |decl_ref| {
                        const fn_index = ctx.fn_indices.get(member) orelse return error.MissingFunction;
                        const decl_file = ctx.graph.files.items[decl_ref.file_index];
                        const fn_decl = decl_file.nodes[decl_ref.fn_node];
                        runtime_arg_count = try emitMethodCallArgsForFnDecl(allocator, ctx, n, decl_file, fn_decl, fd.object);
                        call_ins = .{ .call = .{ .arg_count = runtime_arg_count, .target = .{ .internal_index = fn_index } } };
                    } else if (findUniqueImportedModuleFunction(ctx, member)) |resolved| {
                        const mod_name = ctx.graph.modules.items[resolved.module_index].name;
                        const sym = try std.fmt.allocPrint(allocator, "m{s}_{s}", .{ mod_name, member });
                        const decl_file = ctx.graph.files.items[resolved.decl.file_index];
                        const fn_decl = decl_file.nodes[resolved.decl.fn_node];
                        runtime_arg_count = try emitMethodCallArgsForFnDecl(allocator, ctx, n, decl_file, fn_decl, fd.object);
                        call_ins = .{ .call = .{ .arg_count = runtime_arg_count, .target = .{ .external_symbol = .{ .name = sym, .name_owned = true } } } };
                    } else {
                        try emitExpr(allocator, ctx, fd.object);
                        var i_emit: u32 = 0;
                        while (i_emit < n.data.call.arg_count) : (i_emit += 1) {
                            try emitExpr(allocator, ctx, f.list_items[n.data.call.arg_start + i_emit]);
                        }
                        runtime_arg_count = n.data.call.arg_count + 1;
                        const fn_index = ctx.fn_indices.get(member) orelse return error.MissingFunction;
                        call_ins = .{ .call = .{ .arg_count = runtime_arg_count, .target = .{ .internal_index = fn_index } } };
                    }
                }
            } else return error.UnsupportedNode;
            try ctx.instrs.append(allocator, call_ins);
        },
        .assign => {
            const lhs = f.nodes[n.data.assign.lhs];
            if (lhs.tag == .identifier or lhs.tag == .field) {
                const base_ident = if (lhs.tag == .identifier) lhs else f.nodes[lhs.data.field.object];
                if (base_ident.tag != .identifier) return error.UnsupportedNode;
                const lhs_name = try sliceSpan(ctx.graph, f.file_id, base_ident.span);
                const slot = ctx.locals.get(lhs_name) orelse return error.UnknownIdentifier;

                if (n.data.assign.op == .eq) {
                    try emitExpr(allocator, ctx, n.data.assign.rhs);
                    try ctx.instrs.append(allocator, .{ .store_local = slot });
                    try ctx.instrs.append(allocator, .{ .load_local = slot });
                } else if (n.data.assign.op == .addeq) {
                    try ctx.instrs.append(allocator, .{ .load_local = slot });
                    try emitExpr(allocator, ctx, n.data.assign.rhs);
                    try ctx.instrs.append(allocator, .{ .add = {} });
                    try ctx.instrs.append(allocator, .{ .store_local = slot });
                    try ctx.instrs.append(allocator, .{ .load_local = slot });
                } else {
                    return error.UnsupportedNode;
                }
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

                        const prev = if (arm.has_capture) blk_prev: {
                            try ctx.graph.sm.ensureTextLoaded(f.file_id);
                            const cap_name = try sliceSpan(ctx.graph, f.file_id, arm.capture_span);
                            const had = ctx.locals.get(cap_name);
                            try ctx.locals.put(allocator, cap_name, subj_slot);
                            break :blk_prev had;
                        } else null;
                        try emitExpr(allocator, ctx, arm.body);
                        if (arm.has_capture) {
                            const cap_name = try sliceSpan(ctx.graph, f.file_id, arm.capture_span);
                            if (prev) |p| {
                                try ctx.locals.put(allocator, cap_name, p);
                            } else {
                                _ = ctx.locals.remove(cap_name);
                            }
                        }
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

                        const prev = if (arm.has_capture) blk_prev: {
                            try ctx.graph.sm.ensureTextLoaded(f.file_id);
                            const cap_name = try sliceSpan(ctx.graph, f.file_id, arm.capture_span);
                            const had = ctx.locals.get(cap_name);
                            try ctx.locals.put(allocator, cap_name, subj_slot);
                            break :blk_prev had;
                        } else null;
                        try emitExpr(allocator, ctx, arm.body);
                        if (arm.has_capture) {
                            const cap_name = try sliceSpan(ctx.graph, f.file_id, arm.capture_span);
                            if (prev) |p| {
                                try ctx.locals.put(allocator, cap_name, p);
                            } else {
                                _ = ctx.locals.remove(cap_name);
                            }
                        }
                        const je = ctx.instrs.items.len;
                        try ctx.instrs.append(allocator, .{ .jump = 0 });
                        try end_jumps.append(allocator, @intCast(je));

                        const next_ip: u32 = @intCast(ctx.instrs.items.len);
                        ctx.instrs.items[jf1] = .{ .jump_if_false = next_ip };
                        ctx.instrs.items[jf2] = .{ .jump_if_false = next_ip };
                    }
                } else {
                    const prev = if (arm.has_capture) blk_prev: {
                        try ctx.graph.sm.ensureTextLoaded(f.file_id);
                        const cap_name = try sliceSpan(ctx.graph, f.file_id, arm.capture_span);
                        const had = ctx.locals.get(cap_name);
                        try ctx.locals.put(allocator, cap_name, subj_slot);
                        break :blk_prev had;
                    } else null;
                    try emitExpr(allocator, ctx, arm.body);
                    if (arm.has_capture) {
                        const cap_name = try sliceSpan(ctx.graph, f.file_id, arm.capture_span);
                        if (prev) |p| {
                            try ctx.locals.put(allocator, cap_name, p);
                        } else {
                            _ = ctx.locals.remove(cap_name);
                        }
                    }
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
            const outer_slice_locals = ctx.slice_locals;
            ctx.locals = try cloneLocals(allocator, &outer_locals);
            ctx.slice_locals = try cloneSliceLocals(allocator, &outer_slice_locals);
            defer {
                ctx.locals.deinit(allocator);
                ctx.slice_locals.deinit(allocator);
                ctx.locals = outer_locals;
                ctx.slice_locals = outer_slice_locals;
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

                if (child.tag == .decl and (child.data.decl.has_init or child.data.decl.has_type) and child.data.decl.name_count > 0) {
                    const ident = f.nodes[f.decl_name_items[child.data.decl.name_start]];
                    const name = try sliceSpan(ctx.graph, f.file_id, ident.span);
                    const slot = if (ctx.locals.get(name)) |s| s else blk: {
                        const ns = ctx.next_slot;
                        ctx.next_slot += 1;
                        if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;
                        try ctx.locals.put(allocator, name, ns);
                        break :blk ns;
                    };
                    const init_id = if (child.data.decl.has_init) child.data.decl.init_node else child.data.decl.type_node;
                    const init_n = f.nodes[init_id];
                    if (child.data.decl.has_init and init_n.tag == .slice and init_n.data.slice.has_end and child.data.decl.name_count == 1) {
                        try emitExpr(allocator, ctx, init_n.data.slice.object);
                        try ctx.instrs.append(allocator, .{ .store_local = slot });

                        if (init_n.data.slice.has_start) {
                            try emitExpr(allocator, ctx, init_n.data.slice.start);
                        } else {
                            try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
                        }
                        const start_slot = ctx.next_slot;
                        ctx.next_slot += 1;
                        if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;
                        try ctx.instrs.append(allocator, .{ .store_local = start_slot });

                        const rem_slot = ctx.next_slot;
                        ctx.next_slot += 1;
                        if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;
                        try emitExpr(allocator, ctx, init_n.data.slice.end);
                        try ctx.instrs.append(allocator, .{ .load_local = start_slot });
                        try ctx.instrs.append(allocator, .{ .sub = {} });
                        try ctx.instrs.append(allocator, .{ .store_local = rem_slot });

                        const pre_cond_ip: u32 = @intCast(ctx.instrs.items.len);
                        try ctx.instrs.append(allocator, .{ .load_local = start_slot });
                        try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
                        try ctx.instrs.append(allocator, .{ .gt = {} });
                        const pre_jif_done = ctx.instrs.items.len;
                        try ctx.instrs.append(allocator, .{ .jump_if_false = 0 });
                        try ctx.instrs.append(allocator, .{ .load_local = slot });
                        try ctx.instrs.append(allocator, .{ .ptr_offset_slots = 1 });
                        try ctx.instrs.append(allocator, .{ .store_local = slot });
                        try ctx.instrs.append(allocator, .{ .load_local = start_slot });
                        try ctx.instrs.append(allocator, .{ .push_const_i64 = 1 });
                        try ctx.instrs.append(allocator, .{ .sub = {} });
                        try ctx.instrs.append(allocator, .{ .store_local = start_slot });
                        try ctx.instrs.append(allocator, .{ .jump = pre_cond_ip });
                        const pre_done_ip: u32 = @intCast(ctx.instrs.items.len);
                        ctx.instrs.items[pre_jif_done] = .{ .jump_if_false = pre_done_ip };

                        try ctx.slice_locals.put(allocator, name, .{ .ptr_slot = slot, .rem_slot = rem_slot });
                    } else if (child.data.decl.has_init and init_n.tag == .identifier and child.data.decl.name_count == 1) {
                        const src_name = try sliceSpan(ctx.graph, f.file_id, init_n.span);
                        if (ctx.slice_locals.get(src_name)) |src| {
                            const ptr_slot = ctx.next_slot;
                            ctx.next_slot += 1;
                            if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;
                            const rem_slot = ctx.next_slot;
                            ctx.next_slot += 1;
                            if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;

                            try ctx.instrs.append(allocator, .{ .load_local = src.ptr_slot });
                            try ctx.instrs.append(allocator, .{ .store_local = ptr_slot });
                            try ctx.instrs.append(allocator, .{ .load_local = src.rem_slot });
                            try ctx.instrs.append(allocator, .{ .store_local = rem_slot });

                            try ctx.instrs.append(allocator, .{ .load_local = ptr_slot });
                            try ctx.instrs.append(allocator, .{ .store_local = slot });
                            try ctx.slice_locals.put(allocator, name, .{ .ptr_slot = ptr_slot, .rem_slot = rem_slot });
                        } else {
                            try emitExpr(allocator, ctx, init_id);
                            try ctx.instrs.append(allocator, .{ .store_local = slot });
                        }
                    } else {
                        try emitExpr(allocator, ctx, init_id);
                        try ctx.instrs.append(allocator, .{ .store_local = slot });
                    }
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
            const has_cond = !n.data.for_stmt.is_infinite and n.data.for_stmt.cond != Ast.NullNode;
            const cond_is_range = has_cond and f.nodes[n.data.for_stmt.cond].tag == .binary and (f.nodes[n.data.for_stmt.cond].data.binary.op == .range or f.nodes[n.data.for_stmt.cond].data.binary.op == .rangeq);
            const cond_is_slice = has_cond and f.nodes[n.data.for_stmt.cond].tag == .slice;
            var cond_ident_slice: ?SliceLocal = null;
            if (has_cond and n.data.for_stmt.has_capture and f.nodes[n.data.for_stmt.cond].tag == .identifier) {
                const id_name = try sliceSpan(ctx.graph, f.file_id, f.nodes[n.data.for_stmt.cond].span);
                cond_ident_slice = ctx.slice_locals.get(id_name);
            }

            if (cond_ident_slice != null) {
                const info = cond_ident_slice.?;
                const ptr_slot = info.ptr_slot;
                const rem_slot = info.rem_slot;

                const val_slot = ctx.next_slot;
                ctx.next_slot += 1;
                if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;

                var cap_name: ?[]const u8 = null;
                var cap_prev: ?u32 = null;
                const name = try sliceSpan(ctx.graph, f.file_id, n.data.for_stmt.capture_span);
                if (!std.mem.eql(u8, name, "_")) {
                    cap_prev = ctx.locals.get(name);
                    try ctx.locals.put(allocator, name, val_slot);
                    cap_name = name;
                }

                const cond_ip: u32 = @intCast(ctx.instrs.items.len);
                try ctx.instrs.append(allocator, .{ .load_local = rem_slot });
                try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
                try ctx.instrs.append(allocator, .{ .gt = {} });
                const jif_end = ctx.instrs.items.len;
                try ctx.instrs.append(allocator, .{ .jump_if_false = 0 });
                const jmp_body = ctx.instrs.items.len;
                try ctx.instrs.append(allocator, .{ .jump = 0 });

                const inc_ip: u32 = @intCast(ctx.instrs.items.len);
                try ctx.instrs.append(allocator, .{ .load_local = ptr_slot });
                try ctx.instrs.append(allocator, .{ .ptr_offset_slots = 1 });
                try ctx.instrs.append(allocator, .{ .store_local = ptr_slot });
                try ctx.instrs.append(allocator, .{ .load_local = rem_slot });
                try ctx.instrs.append(allocator, .{ .push_const_i64 = 1 });
                try ctx.instrs.append(allocator, .{ .sub = {} });
                try ctx.instrs.append(allocator, .{ .store_local = rem_slot });
                try ctx.instrs.append(allocator, .{ .jump = cond_ip });

                const body_ip: u32 = @intCast(ctx.instrs.items.len);
                ctx.instrs.items[jmp_body] = .{ .jump = body_ip };

                try ctx.loop_stack.append(allocator, .{ .continue_target = inc_ip, .break_jumps = .empty });
                const lp_idx = ctx.loop_stack.items.len - 1;

                try ctx.instrs.append(allocator, .{ .load_local = ptr_slot });
                try ctx.instrs.append(allocator, .{ .load_ptr = {} });
                try ctx.instrs.append(allocator, .{ .store_local = val_slot });

                try emitExpr(allocator, ctx, n.data.for_stmt.body);
                try ctx.instrs.append(allocator, .{ .pop = {} });
                try ctx.instrs.append(allocator, .{ .jump = inc_ip });

                const end_ip: u32 = @intCast(ctx.instrs.items.len);
                ctx.instrs.items[jif_end] = .{ .jump_if_false = end_ip };
                for (ctx.loop_stack.items[lp_idx].break_jumps.items) |bj| {
                    ctx.instrs.items[bj] = .{ .jump = end_ip };
                }
                ctx.loop_stack.items[lp_idx].break_jumps.deinit(allocator);
                _ = ctx.loop_stack.pop();

                if (cap_name) |cn| {
                    if (cap_prev) |p| {
                        try ctx.locals.put(allocator, cn, p);
                    } else {
                        _ = ctx.locals.remove(cn);
                    }
                }
            } else if (cond_is_range) {
                const cond_n = f.nodes[n.data.for_stmt.cond];
                try emitExpr(allocator, ctx, cond_n.data.binary.lhs);
                const iter_slot = ctx.next_slot;
                ctx.next_slot += 1;
                if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;
                try ctx.instrs.append(allocator, .{ .store_local = iter_slot });

                try emitExpr(allocator, ctx, cond_n.data.binary.rhs);
                const end_slot = ctx.next_slot;
                ctx.next_slot += 1;
                if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;
                try ctx.instrs.append(allocator, .{ .store_local = end_slot });

                var cap_name: ?[]const u8 = null;
                var cap_prev: ?u32 = null;
                if (n.data.for_stmt.has_capture) {
                    const name = try sliceSpan(ctx.graph, f.file_id, n.data.for_stmt.capture_span);
                    if (!std.mem.eql(u8, name, "_")) {
                        cap_prev = ctx.locals.get(name);
                        try ctx.locals.put(allocator, name, iter_slot);
                        cap_name = name;
                    }
                }

                const cond_ip: u32 = @intCast(ctx.instrs.items.len);
                try ctx.instrs.append(allocator, .{ .load_local = iter_slot });
                try ctx.instrs.append(allocator, .{ .load_local = end_slot });
                if (cond_n.data.binary.op == .rangeq) {
                    try ctx.instrs.append(allocator, .{ .lte = {} });
                } else {
                    try ctx.instrs.append(allocator, .{ .lt = {} });
                }
                const jif_end = ctx.instrs.items.len;
                try ctx.instrs.append(allocator, .{ .jump_if_false = 0 });
                const jmp_body = ctx.instrs.items.len;
                try ctx.instrs.append(allocator, .{ .jump = 0 });

                const inc_ip: u32 = @intCast(ctx.instrs.items.len);
                try ctx.instrs.append(allocator, .{ .load_local = iter_slot });
                try ctx.instrs.append(allocator, .{ .push_const_i64 = 1 });
                try ctx.instrs.append(allocator, .{ .add = {} });
                try ctx.instrs.append(allocator, .{ .store_local = iter_slot });
                try ctx.instrs.append(allocator, .{ .jump = cond_ip });

                const body_ip: u32 = @intCast(ctx.instrs.items.len);
                ctx.instrs.items[jmp_body] = .{ .jump = body_ip };

                try ctx.loop_stack.append(allocator, .{ .continue_target = inc_ip, .break_jumps = .empty });
                const lp_idx = ctx.loop_stack.items.len - 1;

                try emitExpr(allocator, ctx, n.data.for_stmt.body);
                try ctx.instrs.append(allocator, .{ .pop = {} });
                try ctx.instrs.append(allocator, .{ .jump = inc_ip });

                const end_ip: u32 = @intCast(ctx.instrs.items.len);
                ctx.instrs.items[jif_end] = .{ .jump_if_false = end_ip };
                for (ctx.loop_stack.items[lp_idx].break_jumps.items) |bj| {
                    ctx.instrs.items[bj] = .{ .jump = end_ip };
                }
                ctx.loop_stack.items[lp_idx].break_jumps.deinit(allocator);
                _ = ctx.loop_stack.pop();

                if (cap_name) |name| {
                    if (cap_prev) |p| {
                        try ctx.locals.put(allocator, name, p);
                    } else {
                        _ = ctx.locals.remove(name);
                    }
                }
            } else if (cond_is_slice) {
                const cond_n = f.nodes[n.data.for_stmt.cond];
                try emitExpr(allocator, ctx, cond_n.data.slice.object);
                const base_slot = ctx.next_slot;
                ctx.next_slot += 1;
                if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;
                try ctx.instrs.append(allocator, .{ .store_local = base_slot });

                if (cond_n.data.slice.has_start) {
                    try emitExpr(allocator, ctx, cond_n.data.slice.start);
                } else {
                    try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
                }
                const start_slot = ctx.next_slot;
                ctx.next_slot += 1;
                if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;
                try ctx.instrs.append(allocator, .{ .store_local = start_slot });

                if (!cond_n.data.slice.has_end) return error.UnsupportedNode;
                try emitExpr(allocator, ctx, cond_n.data.slice.end);
                const end_slot = ctx.next_slot;
                ctx.next_slot += 1;
                if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;
                try ctx.instrs.append(allocator, .{ .store_local = end_slot });

                const rem_slot = ctx.next_slot;
                ctx.next_slot += 1;
                if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;
                try ctx.instrs.append(allocator, .{ .load_local = end_slot });
                try ctx.instrs.append(allocator, .{ .load_local = start_slot });
                try ctx.instrs.append(allocator, .{ .sub = {} });
                try ctx.instrs.append(allocator, .{ .store_local = rem_slot });

                const val_slot = ctx.next_slot;
                ctx.next_slot += 1;
                if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;

                var cap_name: ?[]const u8 = null;
                var cap_prev: ?u32 = null;
                if (n.data.for_stmt.has_capture) {
                    const name = try sliceSpan(ctx.graph, f.file_id, n.data.for_stmt.capture_span);
                    if (!std.mem.eql(u8, name, "_")) {
                        cap_prev = ctx.locals.get(name);
                        try ctx.locals.put(allocator, name, val_slot);
                        cap_name = name;
                    }
                }

                const pre_cond_ip: u32 = @intCast(ctx.instrs.items.len);
                try ctx.instrs.append(allocator, .{ .load_local = start_slot });
                try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
                try ctx.instrs.append(allocator, .{ .gt = {} });
                const pre_jif_done = ctx.instrs.items.len;
                try ctx.instrs.append(allocator, .{ .jump_if_false = 0 });
                try ctx.instrs.append(allocator, .{ .load_local = base_slot });
                try ctx.instrs.append(allocator, .{ .ptr_offset_slots = 1 });
                try ctx.instrs.append(allocator, .{ .store_local = base_slot });
                try ctx.instrs.append(allocator, .{ .load_local = start_slot });
                try ctx.instrs.append(allocator, .{ .push_const_i64 = 1 });
                try ctx.instrs.append(allocator, .{ .sub = {} });
                try ctx.instrs.append(allocator, .{ .store_local = start_slot });
                try ctx.instrs.append(allocator, .{ .jump = pre_cond_ip });
                const pre_done_ip: u32 = @intCast(ctx.instrs.items.len);
                ctx.instrs.items[pre_jif_done] = .{ .jump_if_false = pre_done_ip };

                const cond_ip: u32 = @intCast(ctx.instrs.items.len);
                try ctx.instrs.append(allocator, .{ .load_local = rem_slot });
                try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
                try ctx.instrs.append(allocator, .{ .gt = {} });
                const jif_end = ctx.instrs.items.len;
                try ctx.instrs.append(allocator, .{ .jump_if_false = 0 });
                const jmp_body = ctx.instrs.items.len;
                try ctx.instrs.append(allocator, .{ .jump = 0 });

                const inc_ip: u32 = @intCast(ctx.instrs.items.len);
                try ctx.instrs.append(allocator, .{ .load_local = base_slot });
                try ctx.instrs.append(allocator, .{ .ptr_offset_slots = 1 });
                try ctx.instrs.append(allocator, .{ .store_local = base_slot });
                try ctx.instrs.append(allocator, .{ .load_local = rem_slot });
                try ctx.instrs.append(allocator, .{ .push_const_i64 = 1 });
                try ctx.instrs.append(allocator, .{ .sub = {} });
                try ctx.instrs.append(allocator, .{ .store_local = rem_slot });
                try ctx.instrs.append(allocator, .{ .jump = cond_ip });

                const body_ip: u32 = @intCast(ctx.instrs.items.len);
                ctx.instrs.items[jmp_body] = .{ .jump = body_ip };

                try ctx.loop_stack.append(allocator, .{ .continue_target = inc_ip, .break_jumps = .empty });
                const lp_idx = ctx.loop_stack.items.len - 1;

                try ctx.instrs.append(allocator, .{ .load_local = base_slot });
                try ctx.instrs.append(allocator, .{ .load_ptr = {} });
                try ctx.instrs.append(allocator, .{ .store_local = val_slot });

                try emitExpr(allocator, ctx, n.data.for_stmt.body);
                try ctx.instrs.append(allocator, .{ .pop = {} });
                try ctx.instrs.append(allocator, .{ .jump = inc_ip });

                const end_ip: u32 = @intCast(ctx.instrs.items.len);
                ctx.instrs.items[jif_end] = .{ .jump_if_false = end_ip };
                for (ctx.loop_stack.items[lp_idx].break_jumps.items) |bj| {
                    ctx.instrs.items[bj] = .{ .jump = end_ip };
                }
                ctx.loop_stack.items[lp_idx].break_jumps.deinit(allocator);
                _ = ctx.loop_stack.pop();

                if (cap_name) |name| {
                    if (cap_prev) |p| {
                        try ctx.locals.put(allocator, name, p);
                    } else {
                        _ = ctx.locals.remove(name);
                    }
                }
            } else if (has_cond and n.data.for_stmt.has_capture) {
                try emitExpr(allocator, ctx, n.data.for_stmt.cond);
                const ptr_slot = ctx.next_slot;
                ctx.next_slot += 1;
                if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;
                try ctx.instrs.append(allocator, .{ .store_local = ptr_slot });

                const val_slot = ctx.next_slot;
                ctx.next_slot += 1;
                if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;

                var cap_name: ?[]const u8 = null;
                var cap_prev: ?u32 = null;
                const name = try sliceSpan(ctx.graph, f.file_id, n.data.for_stmt.capture_span);
                if (!std.mem.eql(u8, name, "_")) {
                    cap_prev = ctx.locals.get(name);
                    try ctx.locals.put(allocator, name, val_slot);
                    cap_name = name;
                }

                const cond_ip: u32 = @intCast(ctx.instrs.items.len);
                try ctx.instrs.append(allocator, .{ .load_local = ptr_slot });
                try ctx.instrs.append(allocator, .{ .load_ptr = {} });
                try ctx.instrs.append(allocator, .{ .store_local = val_slot });
                try ctx.instrs.append(allocator, .{ .load_local = val_slot });
                try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
                try ctx.instrs.append(allocator, .{ .neq = {} });
                const jif_end = ctx.instrs.items.len;
                try ctx.instrs.append(allocator, .{ .jump_if_false = 0 });
                const jmp_body = ctx.instrs.items.len;
                try ctx.instrs.append(allocator, .{ .jump = 0 });

                const inc_ip: u32 = @intCast(ctx.instrs.items.len);
                try ctx.instrs.append(allocator, .{ .load_local = ptr_slot });
                try ctx.instrs.append(allocator, .{ .ptr_offset_slots = 1 });
                try ctx.instrs.append(allocator, .{ .store_local = ptr_slot });
                try ctx.instrs.append(allocator, .{ .jump = cond_ip });

                const body_ip: u32 = @intCast(ctx.instrs.items.len);
                ctx.instrs.items[jmp_body] = .{ .jump = body_ip };

                try ctx.loop_stack.append(allocator, .{ .continue_target = inc_ip, .break_jumps = .empty });
                const lp_idx = ctx.loop_stack.items.len - 1;

                try emitExpr(allocator, ctx, n.data.for_stmt.body);
                try ctx.instrs.append(allocator, .{ .pop = {} });
                try ctx.instrs.append(allocator, .{ .jump = inc_ip });

                const end_ip: u32 = @intCast(ctx.instrs.items.len);
                ctx.instrs.items[jif_end] = .{ .jump_if_false = end_ip };
                for (ctx.loop_stack.items[lp_idx].break_jumps.items) |bj| {
                    ctx.instrs.items[bj] = .{ .jump = end_ip };
                }
                ctx.loop_stack.items[lp_idx].break_jumps.deinit(allocator);
                _ = ctx.loop_stack.pop();

                if (cap_name) |cn| {
                    if (cap_prev) |p| {
                        try ctx.locals.put(allocator, cn, p);
                    } else {
                        _ = ctx.locals.remove(cn);
                    }
                }
            } else {
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
            }

            try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
            ctx.next_slot = save_next;
        },
        .return_stmt => {
            if (n.data.return_stmt.has_value) {
                try emitExpr(allocator, ctx, n.data.return_stmt.value);
            } else {
                try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
            }
            try ctx.instrs.append(allocator, .{ .ret = {} });
            try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
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
        .ptr_type, .slice_type, .array_type => return error.UnsupportedNode,
        else => return error.UnsupportedNode,
    }
}

fn evalComptimeConst(ctx: *LowerFunctionCtx, node_id: Ast.NodeId) ?i64 {
    if (ctx.comptime_cache.get(node_id)) |cached| return cached;
    const f = ctx.graph.files.items[ctx.file_index];
    const n = f.nodes[node_id];
    const out: ?i64 = switch (n.tag) {
        .int_lit => blk: {
            const sv = sliceSpan(ctx.graph, f.file_id, n.span) catch break :blk null;
            break :blk std.fmt.parseInt(i64, sv, 10) catch null;
        },
        .bool_lit => blk: {
            const sv = sliceSpan(ctx.graph, f.file_id, n.span) catch break :blk null;
            break :blk if (std.mem.eql(u8, sv, "true")) 1 else 0;
        },
        .unary => blk: {
            const rv = evalComptimeConst(ctx, n.data.unary.rhs) orelse break :blk null;
            break :blk switch (n.data.unary.op) {
                .neg => -rv,
                .not => if (rv == 0) 1 else 0,
                .complement => ~rv,
            };
        },
        .binary => blk: {
            const a = evalComptimeConst(ctx, n.data.binary.lhs) orelse break :blk null;
            const b = evalComptimeConst(ctx, n.data.binary.rhs) orelse break :blk null;
            break :blk switch (n.data.binary.op) {
                .add => a + b,
                .sub => a - b,
                .mul => a * b,
                .div => if (b == 0) null else @divTrunc(a, b),
                .mod => if (b == 0) null else @mod(a, b),
                .eqeq => if (a == b) 1 else 0,
                .neq => if (a != b) 1 else 0,
                .lt => if (a < b) 1 else 0,
                .lte => if (a <= b) 1 else 0,
                .gt => if (a > b) 1 else 0,
                .gte => if (a >= b) 1 else 0,
                .land => if (a != 0 and b != 0) 1 else 0,
                .lor => if (a != 0) a else b,
                else => null,
            };
        },
        .if_expr => blk: {
            const c = evalComptimeConst(ctx, n.data.if_expr.cond) orelse break :blk null;
            if (c != 0) break :blk evalComptimeConst(ctx, n.data.if_expr.then_expr);
            if (!n.data.if_expr.has_else) break :blk null;
            break :blk evalComptimeConst(ctx, n.data.if_expr.else_expr);
        },
        .struct_expr, .enum_expr => 1,
        .inline_expr, .comp_expr => evalComptimeConst(ctx, n.data.one.child),
        else => null,
    };
    if (out) |v| ctx.comptime_cache.put(ctx.graph.allocator, node_id, v) catch {};
    return out;
}

fn emitCallArgsForFnDecl(
    allocator: std.mem.Allocator,
    ctx: *LowerFunctionCtx,
    call_node: Ast.Node,
    decl_file: ModuleGraph.FileUnit,
    fn_decl: Ast.Node,
) anyerror!u32 {
    if (fn_decl.tag != .fn_expr) return error.UnsupportedNode;
    if (call_node.data.call.arg_count != fn_decl.data.fn_expr.param_count) return error.WrongArgCount;

    var emitted: u32 = 0;
    var i: u32 = 0;
    while (i < fn_decl.data.fn_expr.param_count) : (i += 1) {
        const p = decl_file.nodes[decl_file.list_items[fn_decl.data.fn_expr.param_start + i]];
        if (p.tag != .param) continue;
        if (!p.data.param.is_comp) {
            const arg_node = ctx.graph.files.items[ctx.file_index].list_items[call_node.data.call.arg_start + i];
            emitted += try emitArgForParam(allocator, ctx, decl_file, p, arg_node);
        }
    }
    return emitted;
}

fn emitMethodCallArgsForFnDecl(
    allocator: std.mem.Allocator,
    ctx: *LowerFunctionCtx,
    call_node: Ast.Node,
    decl_file: ModuleGraph.FileUnit,
    fn_decl: Ast.Node,
    receiver_expr: Ast.NodeId,
) anyerror!u32 {
    if (fn_decl.tag != .fn_expr) return error.UnsupportedNode;
    if (fn_decl.data.fn_expr.param_count == 0) return error.WrongArgCount;
    if (call_node.data.call.arg_count + 1 != fn_decl.data.fn_expr.param_count) return error.WrongArgCount;

    try emitExpr(allocator, ctx, receiver_expr);
    var emitted: u32 = 1;

    var pi: u32 = 1;
    var ai: u32 = 0;
    while (pi < fn_decl.data.fn_expr.param_count) : (pi += 1) {
        const p = decl_file.nodes[decl_file.list_items[fn_decl.data.fn_expr.param_start + pi]];
        if (p.tag != .param) continue;
        if (!p.data.param.is_comp) {
            const arg_node = ctx.graph.files.items[ctx.file_index].list_items[call_node.data.call.arg_start + ai];
            emitted += try emitArgForParam(allocator, ctx, decl_file, p, arg_node);
        }
        ai += 1;
    }
    return emitted;
}

fn emitArgForParam(
    allocator: std.mem.Allocator,
    ctx: *LowerFunctionCtx,
    decl_file: ModuleGraph.FileUnit,
    param_node: Ast.Node,
    arg_node: Ast.NodeId,
) !u32 {
    if (isSliceParamType(decl_file, param_node)) {
        try emitSliceArgValue(allocator, ctx, arg_node);
        return 2;
    }
    try emitExpr(allocator, ctx, arg_node);
    return 1;
}

fn emitSliceArgValue(allocator: std.mem.Allocator, ctx: *LowerFunctionCtx, arg_node: Ast.NodeId) !void {
    const f = ctx.graph.files.items[ctx.file_index];
    const a = f.nodes[arg_node];

    if (a.tag == .identifier) {
        const nm = try sliceSpan(ctx.graph, f.file_id, a.span);
        if (ctx.slice_locals.get(nm)) |sl| {
            try ctx.instrs.append(allocator, .{ .load_local = sl.ptr_slot });
            try ctx.instrs.append(allocator, .{ .load_local = sl.rem_slot });
            return;
        }
    }

    if (a.tag == .slice and a.data.slice.has_end) {
        const save_next = ctx.next_slot;

        try emitExpr(allocator, ctx, a.data.slice.object);
        const ptr_slot = ctx.next_slot;
        ctx.next_slot += 1;
        if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;
        try ctx.instrs.append(allocator, .{ .store_local = ptr_slot });

        if (a.data.slice.has_start) {
            try emitExpr(allocator, ctx, a.data.slice.start);
        } else {
            try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
        }
        const start_slot = ctx.next_slot;
        ctx.next_slot += 1;
        if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;
        try ctx.instrs.append(allocator, .{ .store_local = start_slot });

        const len_slot = ctx.next_slot;
        ctx.next_slot += 1;
        if (ctx.next_slot > ctx.max_slot) ctx.max_slot = ctx.next_slot;
        try emitExpr(allocator, ctx, a.data.slice.end);
        try ctx.instrs.append(allocator, .{ .load_local = start_slot });
        try ctx.instrs.append(allocator, .{ .sub = {} });
        try ctx.instrs.append(allocator, .{ .store_local = len_slot });

        const pre_cond_ip: u32 = @intCast(ctx.instrs.items.len);
        try ctx.instrs.append(allocator, .{ .load_local = start_slot });
        try ctx.instrs.append(allocator, .{ .push_const_i64 = 0 });
        try ctx.instrs.append(allocator, .{ .gt = {} });
        const pre_jif_done = ctx.instrs.items.len;
        try ctx.instrs.append(allocator, .{ .jump_if_false = 0 });
        try ctx.instrs.append(allocator, .{ .load_local = ptr_slot });
        try ctx.instrs.append(allocator, .{ .ptr_offset_slots = 1 });
        try ctx.instrs.append(allocator, .{ .store_local = ptr_slot });
        try ctx.instrs.append(allocator, .{ .load_local = start_slot });
        try ctx.instrs.append(allocator, .{ .push_const_i64 = 1 });
        try ctx.instrs.append(allocator, .{ .sub = {} });
        try ctx.instrs.append(allocator, .{ .store_local = start_slot });
        try ctx.instrs.append(allocator, .{ .jump = pre_cond_ip });
        const pre_done_ip: u32 = @intCast(ctx.instrs.items.len);
        ctx.instrs.items[pre_jif_done] = .{ .jump_if_false = pre_done_ip };

        try ctx.instrs.append(allocator, .{ .load_local = ptr_slot });
        try ctx.instrs.append(allocator, .{ .load_local = len_slot });
        ctx.next_slot = save_next;
        return;
    }

    return error.UnsupportedNode;
}

fn isSliceParamType(f: ModuleGraph.FileUnit, p: Ast.Node) bool {
    if (p.tag != .param or !p.data.param.has_type) return false;
    var n = f.nodes[p.data.param.type_node];
    while (true) {
        switch (n.tag) {
            .slice_type => return true,
            .optional_type => n = f.nodes[n.data.one.child],
            .error_type => n = f.nodes[n.data.error_type.child],
            else => return false,
        }
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

fn cloneSliceLocals(allocator: std.mem.Allocator, src: *const std.StringHashMapUnmanaged(SliceLocal)) !std.StringHashMapUnmanaged(SliceLocal) {
    var out: std.StringHashMapUnmanaged(SliceLocal) = .empty;
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
            if (init_n.tag == .fn_expr) {
                const ident = f.nodes[f.decl_name_items[n.data.decl.name_start]];
                const name = try sliceSpan(graph, f.file_id, ident.span);
                if (out.get(name) == null) {
                    const copy = try allocator.dupe(u8, name);
                    try out.put(allocator, copy, .{ .file_index = file_index, .fn_node = n.data.decl.init_node });
                }
                if (!init_n.data.fn_expr.is_extern and init_n.data.fn_expr.has_body) {
                    try collectFnReturnedStructMemberFunctions(allocator, f, file_index, n.data.decl.init_node, out, graph);
                    try collectFnReturnedFunction(allocator, f, file_index, name, n.data.decl.init_node, out);
                }
            } else if (init_n.tag == .struct_expr) {
                var si: u32 = 0;
                while (si < init_n.data.aggregate.item_count) : (si += 1) {
                    const sn_id = f.list_items[init_n.data.aggregate.item_start + si];
                    const sn = f.nodes[sn_id];
                    if (sn.tag != .decl or !sn.data.decl.has_init or sn.data.decl.name_count == 0) continue;
                    const sinit = f.nodes[sn.data.decl.init_node];
                    if (sinit.tag != .fn_expr) continue;
                    const sident = f.nodes[f.decl_name_items[sn.data.decl.name_start]];
                    const sname = try sliceSpan(graph, f.file_id, sident.span);
                    if (out.get(sname) == null) {
                        const copy = try allocator.dupe(u8, sname);
                        try out.put(allocator, copy, .{ .file_index = file_index, .fn_node = sn.data.decl.init_node });
                    }
                }
            }
        }
    }
}

fn collectFnReturnedFunction(
    allocator: std.mem.Allocator,
    f: ModuleGraph.FileUnit,
    file_index: u32,
    base_name: []const u8,
    fn_node: Ast.NodeId,
    out: *std.StringHashMapUnmanaged(FnDeclRef),
) !void {
    const fn_n = f.nodes[fn_node];
    if (fn_n.tag != .fn_expr) return;
    const body = f.nodes[ExprKind.peelComptimeWrappers(f, fn_n.data.fn_expr.body)];
    if (body.tag != .fn_expr) return;
    const ret_name = try std.fmt.allocPrint(allocator, "{s}$retfn", .{base_name});
    if (out.get(ret_name) == null) {
        try out.put(allocator, ret_name, .{ .file_index = file_index, .fn_node = ExprKind.peelComptimeWrappers(f, fn_n.data.fn_expr.body) });
    } else {
        allocator.free(ret_name);
    }
}

fn collectFnReturnedStructMemberFunctions(
    allocator: std.mem.Allocator,
    f: ModuleGraph.FileUnit,
    file_index: u32,
    fn_node: Ast.NodeId,
    out: *std.StringHashMapUnmanaged(FnDeclRef),
    graph: *ModuleGraph.Self,
) !void {
    const fn_n = f.nodes[fn_node];
    if (fn_n.tag != .fn_expr) return;
    const body_id = ExprKind.peelComptimeWrappers(f, fn_n.data.fn_expr.body);
    const body = f.nodes[body_id];
    if (body.tag != .struct_expr) return;

    var si: u32 = 0;
    while (si < body.data.aggregate.item_count) : (si += 1) {
        const sn_id = f.list_items[body.data.aggregate.item_start + si];
        const sn = f.nodes[sn_id];
        if (sn.tag != .decl or !sn.data.decl.has_init or sn.data.decl.name_count == 0) continue;
        const sinit = f.nodes[sn.data.decl.init_node];
        if (sinit.tag != .fn_expr) continue;
        const sident = f.nodes[f.decl_name_items[sn.data.decl.name_start]];
        const sname = try sliceSpan(graph, f.file_id, sident.span);
        if (out.get(sname) == null) {
            const copy = try allocator.dupe(u8, sname);
            try out.put(allocator, copy, .{ .file_index = file_index, .fn_node = sn.data.decl.init_node });
        }
        try collectFnReturnedStructMemberFunctions(allocator, f, file_index, sn.data.decl.init_node, out, graph);
        try collectFnReturnedFunction(allocator, f, file_index, sname, sn.data.decl.init_node, out);
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

fn findModuleFunctionDeclRef(graph: *ModuleGraph.Self, module_index: u32, name: []const u8) ?FnDeclRef {
    const ref = CalleeResolve.findModuleFunctionRef(graph, module_index, name) orelse return null;
    return .{ .file_index = ref.file_index, .fn_node = ref.node_id };
}

const ImportedFnResolution = struct {
    module_index: u32,
    decl: FnDeclRef,
};

fn findUniqueImportedModuleFunction(ctx: *LowerFunctionCtx, name: []const u8) ?ImportedFnResolution {
    const f = ctx.graph.files.items[ctx.file_index];
    const ref = CalleeResolve.findUniqueImportedModuleFunctionRef(ctx.graph, f, name) orelse return null;
    return .{ .module_index = ref.module_index, .decl = .{ .file_index = ref.file_index, .fn_node = ref.node_id } };
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

test "lower unwrap propagation through function calls" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_unwrap_calls";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_unwrap_calls/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mk_opt := () optional => 6\n" ++
                "mk_err := () error => 4\n" ++
                "main := () i32 => mk_opt().? + mk_err().!\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_unwrap_calls/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 10), code);
}

test "lower comp expression evaluates constant expression at compile time" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_comp_expr";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_comp_expr/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => comp inline (1 + 2 * 3)\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_comp_expr/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 7), code);
}

test "lower comp expression folds coalescing or to value" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_comp_or_coalesce";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_comp_or_coalesce/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => comp (0 or 7)\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_comp_or_coalesce/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 7), code);
}

test "lower drops comptime type call arguments at runtime ABI" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_comp_type_call";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_comp_type_call/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "id := (T: comp type, x: i32) i32 => x\n" ++
                "main := () i32 => id(i32, 11)\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_comp_type_call/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    var id_fn: ?Ir.Function = null;
    var id_spec_fn: ?Ir.Function = null;
    for (p.functions) |f_ir| {
        if (std.mem.eql(u8, f_ir.name, "id")) id_fn = f_ir;
        if (std.mem.eql(u8, f_ir.name, "id$i32")) id_spec_fn = f_ir;
    }
    try std.testing.expect(id_fn != null);
    try std.testing.expect(id_spec_fn != null);
    try std.testing.expectEqual(@as(u32, 1), id_fn.?.param_count);
    try std.testing.expectEqual(@as(u32, 1), id_spec_fn.?.param_count);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 11), code);
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

test "lower method sugar call to struct member function" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_struct_method";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_struct_method/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "Thing := struct {\n" ++
                "  do_thing(s: i32, b: i32) i32 => b + 1\n" ++
                "}\n" ++
                "main := () i32 => { a := 0 a.do_thing(2) }\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_struct_method/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 3), code);
}

test "lower struct field mutation method sugar pattern" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_struct_field_mut";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_struct_field_mut/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "What := struct {\n" ++
                "  i: i32\n" ++
                "  do_thing(s: What, b: i32) i32 => s.i += b\n" ++
                "}\n" ++
                "main := () i32 => {\n" ++
                "  a: What = { i: 0 }\n" ++
                "  a.do_thing(2)\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_struct_field_mut/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 2), code);
}

test "lower alias call drops comptime type runtime argument" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_alias_comp_type";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_alias_comp_type/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "L := use \"lib\"\n" ++
                "main := () i32 => L.id(i32, 7)\n",
        );
    }
    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_alias_comp_type/lib.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module lib\n" ++
                "pub id := (T: comp type, x: i32) i32 => x\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_alias_comp_type/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    var found = false;
    for (p.functions) |fn_ir| {
        if (!std.mem.eql(u8, fn_ir.name, "main")) continue;
        for (fn_ir.instructions) |ins| {
            switch (ins) {
                .call => |c| switch (c.target) {
                    .external_symbol => |es| {
                        if (std.mem.eql(u8, es.name, "mlib_id")) {
                            found = true;
                            try std.testing.expectEqual(@as(u32, 1), c.arg_count);
                        }
                    },
                    else => {},
                },
                else => {},
            }
        }
    }
    try std.testing.expect(found);
}

test "lower supports ArrayList(T) factory method sugar via imported module functions" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_arraylist_factory_method";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_arraylist_factory_method/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "C := use \"std/collections\"\n" ++
                "main := () i32 => {\n" ++
                "  L := C.ArrayList(i32)\n" ++
                "  p := L.init(2)\n" ++
                "  if p > 0 7 else 3\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntryWithOptions(alloc, "tmp_lower_ir_arraylist_factory_method/main.dyn", .{ .std_dir = "std" });
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    var found = false;
    for (p.functions) |fn_ir| {
        if (!std.mem.eql(u8, fn_ir.name, "main")) continue;
        for (fn_ir.instructions) |ins| {
            switch (ins) {
                .call => |c| switch (c.target) {
                    .external_symbol => |es| {
                        if (std.mem.eql(u8, es.name, "mcollections_init")) {
                            found = true;
                            try std.testing.expectEqual(@as(u32, 2), c.arg_count);
                        }
                    },
                    else => {},
                },
                else => {},
            }
        }
    }
    try std.testing.expect(found);
}

test "lower extern fn call as external symbol" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_extern_fn";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_extern_fn/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "puts := extern fn(*char) i32\n" ++
                "main := () i32 => puts(\"hello\")\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_extern_fn/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    var found = false;
    for (p.functions) |fn_ir| {
        if (!std.mem.eql(u8, fn_ir.name, "main")) continue;
        for (fn_ir.instructions) |ins| {
            switch (ins) {
                .call => |c| switch (c.target) {
                    .external_symbol => |es| {
                        if (std.mem.eql(u8, es.name, "puts")) {
                            found = true;
                            try std.testing.expectEqual(@as(u32, 1), c.arg_count);
                        }
                    },
                    else => {},
                },
                else => {},
            }
        }
    }
    try std.testing.expect(found);
}

test "lower supports for range capture loop" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_for_range_capture";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_for_range_capture/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => {\n" ++
                "  mut sum: i32 = 0\n" ++
                "  for 0..6: |i| { sum += i }\n" ++
                "  sum\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_for_range_capture/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 15), code);
}

test "lower for range continue still increments iterator" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_for_range_continue";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_for_range_continue/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => {\n" ++
                "  mut sum: i32 = 0\n" ++
                "  for 0..6: |i| {\n" ++
                "    if i == 3 { continue }\n" ++
                "    sum += i\n" ++
                "  }\n" ++
                "  sum\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_for_range_continue/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 12), code);
}

test "lower supports for slice capture loop" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_for_slice_capture";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_for_slice_capture/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => {\n" ++
                "  a: i32 = 1\n" ++
                "  b: i32 = 2\n" ++
                "  c: i32 = 3\n" ++
                "  p := &a\n" ++
                "  mut total: i32 = 0\n" ++
                "  for p[0..3]: |v| { total += v }\n" ++
                "  total\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_for_slice_capture/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    for (p.functions) |fn_ir| {
        if (!std.mem.eql(u8, fn_ir.name, "main")) continue;
        for (fn_ir.instructions) |ins| {
            switch (ins) {
                .load_local => |s| try std.testing.expect(s < fn_ir.local_count),
                .store_local => |s| try std.testing.expect(s < fn_ir.local_count),
                .addr_of_local => |s| try std.testing.expect(s < fn_ir.local_count),
                else => {},
            }
        }
    }

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 6), code);
}

test "lower supports for pointer sentinel capture loop" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_for_pointer_capture";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_for_pointer_capture/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => {\n" ++
                "  a: i32 = 1\n" ++
                "  b: i32 = 2\n" ++
                "  c: i32 = 0\n" ++
                "  p := &a\n" ++
                "  mut total: i32 = 0\n" ++
                "  for p: |v| { total += v }\n" ++
                "  total\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_for_pointer_capture/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 3), code);
}

test "lower supports for named slice binding capture loop" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_for_named_slice_capture";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_for_named_slice_capture/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => {\n" ++
                "  a: i32 = 1\n" ++
                "  b: i32 = 2\n" ++
                "  c: i32 = 3\n" ++
                "  p := &a\n" ++
                "  s := p[0..3]\n" ++
                "  mut total: i32 = 0\n" ++
                "  for s: |v| { total += v }\n" ++
                "  total\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_for_named_slice_capture/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 6), code);
}

test "lower supports for aliased named slice binding capture loop" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_for_aliased_named_slice_capture";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_for_aliased_named_slice_capture/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => {\n" ++
                "  a: i32 = 1\n" ++
                "  b: i32 = 2\n" ++
                "  c: i32 = 3\n" ++
                "  p := &a\n" ++
                "  s := p[0..3]\n" ++
                "  t := s\n" ++
                "  mut total: i32 = 0\n" ++
                "  for t: |v| { total += v }\n" ++
                "  total\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_for_aliased_named_slice_capture/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 6), code);
}

test "lower supports passing named slice binding to slice parameter" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_pass_named_slice_param";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_pass_named_slice_param/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "sum := (s: []i32) i32 => {\n" ++
                "  mut total: i32 = 0\n" ++
                "  for s: |v| { total += v }\n" ++
                "  return total\n" ++
                "}\n" ++
                "main := () i32 => {\n" ++
                "  a: i32 = 1\n" ++
                "  b: i32 = 2\n" ++
                "  c: i32 = 3\n" ++
                "  p := &a\n" ++
                "  s := p[0..3]\n" ++
                "  return sum(s)\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_pass_named_slice_param/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 6), code);
}

test "lower supports local type-factory method calls" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_local_type_factory";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_local_type_factory/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mk := (T: comp type) => struct {\n" ++
                "  id := (self: type, x: i32) i32 => x\n" ++
                "}\n" ++
                "main := () i32 => {\n" ++
                "  L := mk(i32)\n" ++
                "  L.id(9)\n" ++
                "}\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_local_type_factory/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 9), code);
}

test "lower accepts enum expression type factory argument for comptime type parameter" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_enum_factory_type_arg";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_enum_factory_type_arg/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mkE := (T: comp type) => enum { A }\n" ++
                "id := (U: comp type, x: i32) i32 => x\n" ++
                "main := () i32 => id(mkE(i32), 7)\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_enum_factory_type_arg/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 7), code);
}

test "lower supports function expression returned from factory call" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_fn_factory_call";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_fn_factory_call/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mkF := (T: comp type) => (x: i32) i32 => x\n" ++
                "main := () i32 => mkF(i32)(8)\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_fn_factory_call/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 8), code);
}

test "lower supports nested factory member call chains" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_nested_factory_chain";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_nested_factory_chain/main.dyn", .{ .truncate = true });
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

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_nested_factory_chain/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 11), code);
}

test "lower supports nested factory chain that returns function" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_nested_factory_ret_fn";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_nested_factory_ret_fn/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mkFn := (T: comp type) => struct {\n" ++
                "  make := (self: type, U: comp type) => (x: i32) i32 => x + 1\n" ++
                "}\n" ++
                "main := () i32 => mkFn(i32).make(i32)(6)\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_nested_factory_ret_fn/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 7), code);
}

test "lower supports nested enum factory chain as comptime type argument" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_nested_enum_factory_type_arg";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_nested_enum_factory_type_arg/main.dyn", .{ .truncate = true });
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

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_nested_enum_factory_type_arg/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 5), code);
}

test "lower supports or fallback for optional and error values" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_or_fallback";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_or_fallback/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mk_opt := (x: i32) optional => x\n" ++
                "mk_err := (x: i32) error => x\n" ++
                "main := () i32 => (mk_opt(0) or 7) + (mk_err(0) or 9)\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_or_fallback/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 16), code);
}

test "lower supports optional-error or fallback to optional then unwrap" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_or_optional_error";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_or_optional_error/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "mk_opt := (x: i32) ?i32 => x\n" ++
                "mk_opt_err := (x: i32) ?i32!ParseError => x\n" ++
                "main := () i32 => (mk_opt_err(0) or mk_opt(11)).?\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_or_optional_error/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 11), code);
}

test "lower supports match arm capture value use" {
    const alloc = std.testing.allocator;
    const dir = "tmp_lower_ir_match_capture";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_lower_ir_match_capture/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => match 7 { 7: |m| m, _: 0 }\n",
        );
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_lower_ir_match_capture/main.dyn");
    defer g.deinit();

    var p = try lowerMainProgram(alloc, &g);
    defer Ir.deinitProgram(alloc, &p);

    const code = @import("backend_native.zig").lowerMainExitCode(p) catch return error.TestUnexpectedResult;
    try std.testing.expectEqual(@as(i64, 7), code);
}
