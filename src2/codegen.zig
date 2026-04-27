const std = @import("std");
const hir = @import("hir.zig");
pub fn emitObject(allocator: std.mem.Allocator, io: std.Io, module: hir.Module, obj_path: []const u8) !void {
    var tmp = std.heap.ArenaAllocator.init(allocator);
    defer tmp.deinit();
    var out = std.array_list.Managed(u8).init(tmp.allocator());
    defer out.deinit();
    var globals = std.array_list.Managed(u8).init(tmp.allocator());
    defer globals.deinit();
    var layouts = Layouts{ .map = .init(tmp.allocator()), .structs = module.structs, .out = &out, .globals = &globals };
    defer layouts.map.deinit();
    try out.appendSlice("; Dyn Step 15 LLVM IR\n");
    for (module.structs) |s| try emitStructType(&layouts, s);
    for (module.functions) |f| try emitFunction(&layouts, f);
    try out.appendSlice(globals.items);
    try std.Io.Dir.writeFile(.cwd(), io, .{ .sub_path = obj_path, .data = out.items });
}
const Ty = union(enum) { int: hir.IntType, struct_: []const u8, ptr: []const u8, enum_: []const u8, array: struct { len: u64, elem: *const Ty }, slice: *const Ty, optional: *const Ty, error_union: *const Ty };
const Slot = struct { ptr: []const u8, ty: Ty };
const Val = struct { text: []const u8, ty: Ty };
const Layouts = struct { map: std.StringHashMap(hir.StructType), structs: []hir.StructType, out: *std.array_list.Managed(u8), globals: *std.array_list.Managed(u8) };
const FnCtx = struct { layouts: *Layouts, out: *std.array_list.Managed(u8), id: usize = 0, label: usize = 0, str_id: usize = 0, vars: std.StringHashMap(Slot), terminated: bool = false };
fn toTy(t: hir.Type) Ty {
    return switch (t) {
        .int => |i| .{ .int = i },
        .struct_ => |s| .{ .struct_ = s },
        .ptr => |s| .{ .ptr = s },
        .enum_ => |s| .{ .enum_ = s },
        .array => |ar| blk: {
            const p = std.heap.page_allocator.create(Ty) catch unreachable;
            p.* = toTy(ar.elem.*);
            break :blk .{ .array = .{ .len = ar.len, .elem = p } };
        },
        .slice => |s| blk: {
            const p = std.heap.page_allocator.create(Ty) catch unreachable;
            p.* = toTy(s.*);
            break :blk .{ .slice = p };
        },
        .optional => |o| blk: {
            const p = std.heap.page_allocator.create(Ty) catch unreachable;
            p.* = toTy(o.*);
            break :blk .{ .optional = p };
        },
        .error_union => |o| blk: {
            const p = std.heap.page_allocator.create(Ty) catch unreachable;
            p.* = toTy(o.*);
            break :blk .{ .error_union = p };
        },
    };
}
fn llvmTyA(a: std.mem.Allocator, t: Ty) ![]const u8 {
    return switch (t) {
        .int => |i| try std.fmt.allocPrint(a, "i{}", .{i.bits}),
        .struct_ => |s| try std.fmt.allocPrint(a, "%{s}", .{s}),
        .ptr => "ptr",
        .enum_ => "i32",
        .array => |ar| try std.fmt.allocPrint(a, "[{} x {s}]", .{ ar.len, try llvmTyA(a, ar.elem.*) }),
        .slice => "{ ptr, i64 }",
        .optional => |o| try std.fmt.allocPrint(a, "{{ i1, {s} }}", .{try llvmTyA(a, o.*)}),
        .error_union => |o| try std.fmt.allocPrint(a, "{{ i32, {s} }}", .{try llvmTyA(a, o.*)}),
    };
}
fn llvmTy(c: *FnCtx, t: Ty) ![]const u8 {
    return llvmTyA(c.out.allocator, t);
}
fn tmpName(c: *FnCtx) ![]const u8 {
    const n = c.id;
    c.id += 1;
    return std.fmt.allocPrint(c.out.allocator, "%t{}", .{n});
}
fn labelName(c: *FnCtx, p: []const u8) ![]const u8 {
    const n = c.label;
    c.label += 1;
    return std.fmt.allocPrint(c.out.allocator, "{s}{}", .{ p, n });
}
fn findStruct(l: *Layouts, name: []const u8) ?hir.StructType {
    for (l.structs) |s| if (std.mem.eql(u8, s.name, name)) return s;
    return null;
}
fn fieldIndex(s: hir.StructType, name: []const u8) ?usize {
    for (s.fields, 0..) |f, i| if (std.mem.eql(u8, f.name, name)) return i;
    return null;
}
fn fieldTy(s: hir.StructType, name: []const u8) Ty {
    for (s.fields) |f| if (std.mem.eql(u8, f.name, name)) return toTy(f.ty);
    return .{ .int = .{} };
}
fn emitStructType(l: *Layouts, s: hir.StructType) !void {
    try l.out.print("%{s} = type {{ ", .{s.name});
    for (s.fields, 0..) |f, i| {
        if (i != 0) try l.out.appendSlice(", ");
        try l.out.print("{s}", .{try llvmTyA(l.out.allocator, toTy(f.ty))});
    }
    try l.out.appendSlice(" }\n");
}
fn cast(c: *FnCtx, v: Val, to: Ty) !Val {
    if (v.ty == .struct_ or to == .struct_ or v.ty == .ptr or to == .ptr or v.ty == .optional or to == .optional or v.ty == .error_union or to == .error_union or v.ty == .array or to == .array or v.ty == .slice or to == .slice) return v;
    if (v.ty == .enum_ and to == .enum_) return v;
    if (v.ty == .int and to == .enum_) return .{ .text = v.text, .ty = to };
    if (v.ty == .enum_ and to == .int) return .{ .text = v.text, .ty = to };
    if (v.ty.int.bits == to.int.bits) return .{ .text = v.text, .ty = to };
    const t = try tmpName(c);
    if (v.ty.int.bits < to.int.bits) try c.out.print("  {s} = {s} {s} {s} to {s}\n", .{ t, if (v.ty.int.signed) "sext" else "zext", try llvmTy(c, v.ty), v.text, try llvmTy(c, to) }) else try c.out.print("  {s} = trunc {s} {s} to {s}\n", .{ t, try llvmTy(c, v.ty), v.text, try llvmTy(c, to) });
    return .{ .text = t, .ty = to };
}
fn toI1(c: *FnCtx, v: Val) !Val {
    if (v.ty == .int and v.ty.int.bits == 1) return v;
    const t = try tmpName(c);
    try c.out.print("  {s} = icmp ne {s} {s}, 0\n", .{ t, try llvmTy(c, v.ty), v.text });
    return .{ .text = t, .ty = .{ .int = .{ .bits = 1, .signed = false } } };
}
fn emitFunction(l: *Layouts, f: hir.Function) !void {
    var ctx = FnCtx{ .layouts = l, .out = l.out, .vars = .init(l.out.allocator) };
    defer ctx.vars.deinit();
    var ret = toTy(f.ret);
    if (std.mem.eql(u8, f.name, "main") and ret == .error_union) ret = ret.error_union.*;
    try l.out.print("define {s} @\"{s}\"(", .{ try llvmTy(&ctx, ret), f.name });
    for (f.params, 0..) |p, i| {
        if (i != 0) try l.out.appendSlice(", ");
        const pt = toTy(p.ty);
        try l.out.print("{s} %{s}.arg", .{ try llvmTy(&ctx, pt), p.name });
    }
    try l.out.appendSlice(") {\nentry:\n");
    for (f.params) |p| {
        const pt = toTy(p.ty);
        const ptr = try std.fmt.allocPrint(l.out.allocator, "%{s}.addr", .{p.name});
        try l.out.print("  {s} = alloca {s}\n  store {s} %{s}.arg, ptr {s}\n", .{ ptr, try llvmTy(&ctx, pt), try llvmTy(&ctx, pt), p.name, ptr });
        try ctx.vars.put(p.name, .{ .ptr = ptr, .ty = pt });
    }
    for (f.stmts) |st| if (!ctx.terminated) try emitStmt(&ctx, st, ret);
    if (!ctx.terminated) try l.out.print("  ret {s} 0\n", .{try llvmTy(&ctx, ret)});
    try l.out.appendSlice("}\n\n");
}
fn storeStruct(c: *FnCtx, ptr: []const u8, lit: anytype) !void {
    const s = findStruct(c.layouts, lit.ty).?;
    for (lit.fields) |fv| {
        const idx = fieldIndex(s, fv.name).?;
        const ft = fieldTy(s, fv.name);
        const gep = try tmpName(c);
        try c.out.print("  {s} = getelementptr %{s}, ptr {s}, i32 0, i32 {}\n", .{ gep, lit.ty, ptr, idx });
        const v = try cast(c, try emitExpr(c, fv.value), ft);
        try c.out.print("  store {s} {s}, ptr {s}\n", .{ try llvmTy(c, ft), v.text, gep });
    }
}
fn emitStmt(c: *FnCtx, st: hir.Stmt, retTy: Ty) anyerror!void {
    switch (st) {
        .decl => |d| {
            const ty = toTy(d.ty);
            const ptr = try std.fmt.allocPrint(c.out.allocator, "%{s}.addr", .{d.name});
            try c.out.print("  {s} = alloca {s}\n", .{ ptr, try llvmTy(c, ty) });
            if (d.value == .array_lit) {
                const ar = ty.array;
                for (d.value.array_lit, 0..) |item, i| {
                    const gep = try tmpName(c);
                    try c.out.print("  {s} = getelementptr {s}, ptr {s}, i32 0, i32 {}\n", .{ gep, try llvmTy(c, ty), ptr, i });
                    const v = try cast(c, try emitExpr(c, item), ar.elem.*);
                    try c.out.print("  store {s} {s}, ptr {s}\n", .{ try llvmTy(c, ar.elem.*), v.text, gep });
                }
            } else if (d.value == .struct_lit) try storeStruct(c, ptr, d.value.struct_lit) else if (d.value == .optional_some) {
                const tagp = try tmpName(c);
                const valp = try tmpName(c);
                const inner = ty.optional.*;
                try c.out.print("  {s} = getelementptr {s}, ptr {s}, i32 0, i32 0\n  store i1 1, ptr {s}\n  {s} = getelementptr {s}, ptr {s}, i32 0, i32 1\n", .{ tagp, try llvmTy(c, ty), ptr, tagp, valp, try llvmTy(c, ty), ptr });
                const v = try cast(c, try emitExpr(c, d.value.optional_some.*), inner);
                try c.out.print("  store {s} {s}, ptr {s}\n", .{ try llvmTy(c, inner), v.text, valp });
            } else if (d.value == .optional_null) {
                const tagp = try tmpName(c);
                const valp = try tmpName(c);
                const inner = ty.optional.*;
                try c.out.print("  {s} = getelementptr {s}, ptr {s}, i32 0, i32 0\n  store i1 0, ptr {s}\n  {s} = getelementptr {s}, ptr {s}, i32 0, i32 1\n  store {s} 0, ptr {s}\n", .{ tagp, try llvmTy(c, ty), ptr, tagp, valp, try llvmTy(c, ty), ptr, try llvmTy(c, inner), valp });
            } else if (d.value == .error_some) {
                const tagp = try tmpName(c);
                const valp = try tmpName(c);
                const inner = ty.error_union.*;
                try c.out.print("  {s} = getelementptr {s}, ptr {s}, i32 0, i32 0\n  store i32 0, ptr {s}\n  {s} = getelementptr {s}, ptr {s}, i32 0, i32 1\n", .{ tagp, try llvmTy(c, ty), ptr, tagp, valp, try llvmTy(c, ty), ptr });
                const v = try cast(c, try emitExpr(c, d.value.error_some.*), inner);
                try c.out.print("  store {s} {s}, ptr {s}\n", .{ try llvmTy(c, inner), v.text, valp });
            } else {
                const v = try cast(c, try emitExpr(c, d.value), ty);
                try c.out.print("  store {s} {s}, ptr {s}\n", .{ try llvmTy(c, ty), v.text, ptr });
            }
            try c.vars.put(d.name, .{ .ptr = ptr, .ty = ty });
        },
        .assign => |a| {
            const slot = c.vars.get(a.name) orelse return error.UnknownVariable;
            const v = try cast(c, try emitExpr(c, a.value), slot.ty);
            try c.out.print("  store {s} {s}, ptr {s}\n", .{ try llvmTy(c, slot.ty), v.text, slot.ptr });
        },
        .while_ => |w| try emitWhile(c, w, retTy),
        .for_range => |fr| try emitForRange(c, fr, retTy),
        .for_indexed => |fi| try emitForIndexed(c, fi, retTy),
        .ret => |e| {
            if (e == .err_payload and retTy == .int) {
                const s = c.vars.get(e.err_payload) orelse return error.UnknownVariable;
                const inner = s.ty.error_union.*;
                const tagp = try tmpName(c);
                const tag = try tmpName(c);
                const iserr = try tmpName(c);
                const errcode = try tmpName(c);
                const valp = try tmpName(c);
                const val0 = try tmpName(c);
                const out = try tmpName(c);
                try c.out.print("  {s} = getelementptr {s}, ptr {s}, i32 0, i32 0\n  {s} = load i32, ptr {s}\n  {s} = icmp ne i32 {s}, 0\n  {s} = add i32 {s}, 1\n  {s} = getelementptr {s}, ptr {s}, i32 0, i32 1\n  {s} = load {s}, ptr {s}\n", .{ tagp, try llvmTy(c, s.ty), s.ptr, tag, tagp, iserr, tag, errcode, tag, valp, try llvmTy(c, s.ty), s.ptr, val0, try llvmTy(c, inner), valp });
                const vv = try cast(c, .{ .text = val0, .ty = inner }, retTy);
                try c.out.print("  {s} = select i1 {s}, i32 {s}, i32 {s}\n  ret i32 {s}\n", .{ out, iserr, errcode, vv.text, out });
                c.terminated = true;
                return;
            }
            var v = try emitExpr(c, e);
            if (retTy == .error_union and v.ty != .error_union) {
                const a = try tmpName(c);
                const b = try tmpName(c);
                try c.out.print("  {s} = insertvalue {s} undef, i32 0, 0\n  {s} = insertvalue {s} {s}, {s} {s}, 1\n", .{ a, try llvmTy(c, retTy), b, try llvmTy(c, retTy), a, try llvmTy(c, retTy.error_union.*), v.text });
                v = .{ .text = b, .ty = retTy };
            } else v = try cast(c, v, retTy);
            try c.out.print("  ret {s} {s}\n", .{ try llvmTy(c, retTy), v.text });
            c.terminated = true;
        },
    }
}
fn emitWhile(c: *FnCtx, w: anytype, retTy: Ty) !void {
    const cond = try labelName(c, "while.cond");
    const body = try labelName(c, "while.body");
    const end = try labelName(c, "while.end");
    try c.out.print("  br label %{s}\n{s}:\n", .{ cond, cond });
    const cv = try toI1(c, try emitExpr(c, w.cond));
    try c.out.print("  br i1 {s}, label %{s}, label %{s}\n{s}:\n", .{ cv.text, body, end, body });
    const saved = c.terminated;
    c.terminated = false;
    for (w.body) |st| if (!c.terminated) try emitStmt(c, st, retTy);
    if (!c.terminated) try c.out.print("  br label %{s}\n", .{cond});
    c.terminated = saved;
    try c.out.print("{s}:\n", .{end});
}
fn emitForRange(c: *FnCtx, fr: anytype, retTy: Ty) !void {
    const slot = try std.fmt.allocPrint(c.out.allocator, "%{s}.addr", .{fr.name});
    try c.out.print("  {s} = alloca i32\n", .{slot});
    try c.vars.put(fr.name, .{ .ptr = slot, .ty = .{ .int = .{ .bits = 32 } } });
    const sv = try cast(c, try emitExpr(c, fr.start), .{ .int = .{ .bits = 32 } });
    try c.out.print("  store i32 {s}, ptr {s}\n", .{ sv.text, slot });
    const cond = try labelName(c, "for.cond");
    const body = try labelName(c, "for.body");
    const end = try labelName(c, "for.end");
    try c.out.print("  br label %{s}\n{s}:\n", .{ cond, cond });
    const cur = try tmpName(c);
    const ev = try cast(c, try emitExpr(c, fr.end), .{ .int = .{ .bits = 32 } });
    const cmp = try tmpName(c);
    try c.out.print("  {s} = load i32, ptr {s}\n  {s} = icmp {s} i32 {s}, {s}\n  br i1 {s}, label %{s}, label %{s}\n{s}:\n", .{ cur, slot, cmp, if (fr.inclusive) "sle" else "slt", cur, ev.text, cmp, body, end, body });
    const saved = c.terminated;
    c.terminated = false;
    for (fr.body) |st| if (!c.terminated) try emitStmt(c, st, retTy);
    if (!c.terminated) {
        const nxt = try tmpName(c);
        const cur2 = try tmpName(c);
        try c.out.print("  {s} = load i32, ptr {s}\n  {s} = add i32 {s}, 1\n  store i32 {s}, ptr {s}\n  br label %{s}\n", .{ cur2, slot, nxt, cur2, nxt, slot, cond });
    }
    c.terminated = saved;
    try c.out.print("{s}:\n", .{end});
}
fn emitForIndexed(c: *FnCtx, fi: anytype, retTy: Ty) !void {
    const src = c.vars.get(fi.iterable) orelse return error.UnknownVariable;
    const elem = if (src.ty == .array) src.ty.array.elem.* else src.ty.slice.*;
    const cap = try std.fmt.allocPrint(c.out.allocator, "%{s}.addr", .{fi.name});
    const idx = try tmpName(c);
    try c.out.print("  {s} = alloca {s}\n  {s} = alloca i32\n  store i32 0, ptr {s}\n", .{ cap, try llvmTy(c, elem), idx, idx });
    try c.vars.put(fi.name, .{ .ptr = cap, .ty = elem });
    const cond = try labelName(c, "fori.cond");
    const body = try labelName(c, "fori.body");
    const end = try labelName(c, "fori.end");
    try c.out.print("  br label %{s}\n{s}:\n", .{ cond, cond });
    const cur = try tmpName(c);
    try c.out.print("  {s} = load i32, ptr {s}\n", .{ cur, idx });
    const lenv = try tmpName(c);
    if (src.ty == .array) try c.out.print("  {s} = icmp slt i32 {s}, {}\n", .{ lenv, cur, src.ty.array.len }) else {
        const lp = try tmpName(c);
        const l64 = try tmpName(c);
        const l32 = try tmpName(c);
        try c.out.print("  {s} = getelementptr {{ ptr, i64 }}, ptr {s}, i32 0, i32 1\n  {s} = load i64, ptr {s}\n  {s} = trunc i64 {s} to i32\n  {s} = icmp slt i32 {s}, {s}\n", .{ lp, src.ptr, l64, lp, l32, l64, lenv, cur, l32 });
    }
    try c.out.print("  br i1 {s}, label %{s}, label %{s}\n{s}:\n", .{ lenv, body, end, body });
    const gep = try tmpName(c);
    const val = try tmpName(c);
    if (src.ty == .array) try c.out.print("  {s} = getelementptr {s}, ptr {s}, i32 0, i32 {s}\n", .{ gep, try llvmTy(c, src.ty), src.ptr, cur }) else {
        const bp = try tmpName(c);
        const base = try tmpName(c);
        try c.out.print("  {s} = getelementptr {{ ptr, i64 }}, ptr {s}, i32 0, i32 0\n  {s} = load ptr, ptr {s}\n  {s} = getelementptr {s}, ptr {s}, i32 {s}\n", .{ bp, src.ptr, base, bp, gep, try llvmTy(c, elem), base, cur });
    }
    try c.out.print("  {s} = load {s}, ptr {s}\n  store {s} {s}, ptr {s}\n", .{ val, try llvmTy(c, elem), gep, try llvmTy(c, elem), val, cap });
    const saved = c.terminated;
    c.terminated = false;
    for (fi.body) |st| if (!c.terminated) try emitStmt(c, st, retTy);
    if (!c.terminated) {
        const n = try tmpName(c);
        const c2 = try tmpName(c);
        try c.out.print("  {s} = load i32, ptr {s}\n  {s} = add i32 {s}, 1\n  store i32 {s}, ptr {s}\n  br label %{s}\n", .{ c2, idx, n, c2, n, idx, cond });
    }
    c.terminated = saved;
    try c.out.print("{s}:\n", .{end});
}
fn emitExpr(c: *FnCtx, e: hir.Expr) anyerror!Val {
    return switch (e) {
        .int => |v| .{ .text = try std.fmt.allocPrint(c.out.allocator, "{}", .{v}), .ty = .{ .int = .{ .bits = 32 } } },
        .string => |s| blk: {
            const id = c.str_id;
            c.str_id += 1;
            const g = try std.fmt.allocPrint(c.out.allocator, "@.str{}", .{id});
            try c.layouts.globals.print("{s} = private unnamed_addr constant [{} x i8] c\"", .{ g, s.len });
            for (s) |ch| {
                if (ch == 10) try c.layouts.globals.appendSlice("\\0A") else if (ch == 13) try c.layouts.globals.appendSlice("\\0D") else if (ch == 9) try c.layouts.globals.appendSlice("\\09") else if (ch == 34) try c.layouts.globals.appendSlice("\\22") else if (ch == 92) try c.layouts.globals.appendSlice("\\5C") else try c.layouts.globals.print("{c}", .{ch});
            }
            try c.layouts.globals.appendSlice("\"\n");
            const p = try tmpName(c);
            const q = try tmpName(c);
            try c.out.print("  {s} = insertvalue {{ ptr, i64 }} undef, ptr {s}, 0\n  {s} = insertvalue {{ ptr, i64 }} {s}, i64 {}, 1\n", .{ p, g, q, p, s.len });
            break :blk .{ .text = q, .ty = .{ .slice = &.{ .int = .{ .bits = 8, .signed = false } } } };
        },
        .var_ => |n| blk: {
            const s = c.vars.get(n) orelse return error.UnknownVariable;
            const t = try tmpName(c);
            try c.out.print("  {s} = load {s}, ptr {s}\n", .{ t, try llvmTy(c, s.ty), s.ptr });
            break :blk .{ .text = t, .ty = s.ty };
        },
        .array_lit => return error.ArrayLiteralNotValue,
        .slice_from_array => |sl| blk: {
            const s = c.vars.get(sl.object) orelse return error.UnknownVariable;
            const ar = s.ty.array;
            const start = try cast(c, try emitExpr(c, sl.start.*), .{ .int = .{ .bits = 32 } });
            const end = try cast(c, try emitExpr(c, sl.end.*), .{ .int = .{ .bits = 32 } });
            const base = try tmpName(c);
            const diff = try tmpName(c);
            const len64 = try tmpName(c);
            const a = try tmpName(c);
            const out = try tmpName(c);
            try c.out.print("  {s} = getelementptr {s}, ptr {s}, i32 0, i32 {s}\n  {s} = sub i32 {s}, {s}\n  {s} = zext i32 {s} to i64\n  {s} = insertvalue {{ ptr, i64 }} undef, ptr {s}, 0\n  {s} = insertvalue {{ ptr, i64 }} {s}, i64 {s}, 1\n", .{ base, try llvmTy(c, s.ty), s.ptr, start.text, diff, end.text, start.text, len64, diff, a, base, out, a, len64 });
            break :blk .{ .text = out, .ty = .{ .slice = ar.elem } };
        },
        .index => |ix| blk: {
            const s = c.vars.get(ix.object) orelse return error.UnknownVariable;
            const iv = try cast(c, try emitExpr(c, ix.index.*), .{ .int = .{ .bits = 32 } });
            const gep = try tmpName(c);
            const t = try tmpName(c);
            if (s.ty == .array) {
                const ar = s.ty.array;
                try c.out.print("  {s} = getelementptr {s}, ptr {s}, i32 0, i32 {s}\n  {s} = load {s}, ptr {s}\n", .{ gep, try llvmTy(c, s.ty), s.ptr, iv.text, t, try llvmTy(c, ar.elem.*), gep });
                break :blk .{ .text = t, .ty = ar.elem.* };
            } else {
                const elem = s.ty.slice.*;
                const basep = try tmpName(c);
                const base = try tmpName(c);
                try c.out.print("  {s} = getelementptr {{ ptr, i64 }}, ptr {s}, i32 0, i32 0\n  {s} = load ptr, ptr {s}\n  {s} = getelementptr {s}, ptr {s}, i32 {s}\n  {s} = load {s}, ptr {s}\n", .{ basep, s.ptr, base, basep, gep, try llvmTy(c, elem), base, iv.text, t, try llvmTy(c, elem), gep });
                break :blk .{ .text = t, .ty = elem };
            }
        },
        .opt_payload => |n| blk: {
            const s = c.vars.get(n) orelse return error.UnknownVariable;
            const inner = s.ty.optional.*;
            const p = try tmpName(c);
            const t = try tmpName(c);
            try c.out.print("  {s} = getelementptr {s}, ptr {s}, i32 0, i32 1\n  {s} = load {s}, ptr {s}\n", .{ p, try llvmTy(c, s.ty), s.ptr, t, try llvmTy(c, inner), p });
            break :blk .{ .text = t, .ty = inner };
        },
        .optional_some => return error.OptionalSomeNotValue,
        .optional_null => return error.OptionalNullNotValue,
        .optional_or => |oo| blk: {
            const s = c.vars.get(oo.name) orelse return error.UnknownVariable;
            const inner = s.ty.optional.*;
            const tagp = try tmpName(c);
            const tag = try tmpName(c);
            const valp = try tmpName(c);
            const val = try tmpName(c);
            const fb = try cast(c, try emitExpr(c, oo.fallback.*), inner);
            const out = try tmpName(c);
            try c.out.print("  {s} = getelementptr {s}, ptr {s}, i32 0, i32 0\n  {s} = load i1, ptr {s}\n  {s} = getelementptr {s}, ptr {s}, i32 0, i32 1\n  {s} = load {s}, ptr {s}\n  {s} = select i1 {s}, {s} {s}, {s} {s}\n", .{ tagp, try llvmTy(c, s.ty), s.ptr, tag, tagp, valp, try llvmTy(c, s.ty), s.ptr, val, try llvmTy(c, inner), valp, out, tag, try llvmTy(c, inner), val, try llvmTy(c, inner), fb.text });
            break :blk .{ .text = out, .ty = inner };
        },
        .error_some => return error.ErrorSomeNotValue,
        .err_payload => |n| blk: {
            const s = c.vars.get(n) orelse return error.UnknownVariable;
            const inner = s.ty.error_union.*;
            const p = try tmpName(c);
            const t = try tmpName(c);
            try c.out.print("  {s} = getelementptr {s}, ptr {s}, i32 0, i32 1\n  {s} = load {s}, ptr {s}\n", .{ p, try llvmTy(c, s.ty), s.ptr, t, try llvmTy(c, inner), p });
            break :blk .{ .text = t, .ty = inner };
        },
        .field => |f| blk: {
            const slot = c.vars.get(f.object) orelse return error.UnknownVariable;
            const sname = if (slot.ty == .ptr) slot.ty.ptr else slot.ty.struct_;
            const st = findStruct(c.layouts, sname).?;
            const idx = fieldIndex(st, f.name).?;
            const ft = fieldTy(st, f.name);
            const gep = try tmpName(c);
            const t = try tmpName(c);
            if (slot.ty == .ptr) {
                const base = try tmpName(c);
                try c.out.print("  {s} = load ptr, ptr {s}\n  {s} = getelementptr %{s}, ptr {s}, i32 0, i32 {}\n  {s} = load {s}, ptr {s}\n", .{ base, slot.ptr, gep, sname, base, idx, t, try llvmTy(c, ft), gep });
            } else try c.out.print("  {s} = getelementptr %{s}, ptr {s}, i32 0, i32 {}\n  {s} = load {s}, ptr {s}\n", .{ gep, sname, slot.ptr, idx, t, try llvmTy(c, ft), gep });
            break :blk .{ .text = t, .ty = ft };
        },
        .struct_lit => return error.StructLiteralNotValue,
        .call => |call| blk: {
            const t = try tmpName(c);
            try c.out.print("  {s} = call i32 @{s}(", .{ t, call.name });
            for (call.args, 0..) |a, i| {
                if (i != 0) try c.out.appendSlice(", ");
                const av = try cast(c, try emitExpr(c, a), .{ .int = .{ .bits = 32 } });
                try c.out.print("i32 {s}", .{av.text});
            }
            try c.out.appendSlice(")\n");
            break :blk .{ .text = t, .ty = .{ .int = .{ .bits = 32 } } };
        },
        .method_call => |mc| blk: {
            const slot = c.vars.get(mc.receiver) orelse return error.UnknownVariable;
            const t = try tmpName(c);
            try c.out.print("  {s} = call i32 @\"{s}.{s}\"(ptr {s}", .{ t, mc.type_name, mc.method, slot.ptr });
            for (mc.args) |a| {
                const av = try cast(c, try emitExpr(c, a), .{ .int = .{ .bits = 32 } });
                try c.out.print(", i32 {s}", .{av.text});
            }
            try c.out.appendSlice(")\n");
            break :blk .{ .text = t, .ty = .{ .int = .{ .bits = 32 } } };
        },
        .neg => |x| blk: {
            const v = try emitExpr(c, x.*);
            const t = try tmpName(c);
            try c.out.print("  {s} = sub {s} 0, {s}\n", .{ t, try llvmTy(c, v.ty), v.text });
            break :blk .{ .text = t, .ty = v.ty };
        },
        .if_ => |i| blk: {
            const cv = try toI1(c, try emitExpr(c, i.cond.*));
            const tv = try emitExpr(c, i.then_expr.*);
            const ev = try cast(c, try emitExpr(c, i.else_expr.*), tv.ty);
            const t = try tmpName(c);
            try c.out.print("  {s} = select i1 {s}, {s} {s}, {s} {s}\n", .{ t, cv.text, try llvmTy(c, tv.ty), tv.text, try llvmTy(c, tv.ty), ev.text });
            break :blk .{ .text = t, .ty = tv.ty };
        },
        .add => |a| try emitBin(c, "add", a),
        .sub => |a| try emitBin(c, "sub", a),
        .mul => |a| try emitBin(c, "mul", a),
        .div => |a| try emitBin(c, "sdiv", a),
        .rem => |a| try emitBin(c, "srem", a),
        .eq => |a| try emitCmp(c, "eq", a),
        .ne => |a| try emitCmp(c, "ne", a),
        .lt => |a| try emitCmp(c, "slt", a),
        .le => |a| try emitCmp(c, "sle", a),
        .gt => |a| try emitCmp(c, "sgt", a),
        .ge => |a| try emitCmp(c, "sge", a),
    };
}
fn emitBin(c: *FnCtx, op: []const u8, a: hir.Expr.Bin) !Val {
    const l = try emitExpr(c, a.lhs.*);
    const r = try cast(c, try emitExpr(c, a.rhs.*), l.ty);
    const t = try tmpName(c);
    try c.out.print("  {s} = {s} {s} {s}, {s}\n", .{ t, op, try llvmTy(c, l.ty), l.text, r.text });
    return .{ .text = t, .ty = l.ty };
}
fn emitCmp(c: *FnCtx, op: []const u8, a: hir.Expr.Bin) !Val {
    const l = try emitExpr(c, a.lhs.*);
    const r = try cast(c, try emitExpr(c, a.rhs.*), l.ty);
    const t = try tmpName(c);
    try c.out.print("  {s} = icmp {s} {s} {s}, {s}\n", .{ t, op, try llvmTy(c, l.ty), l.text, r.text });
    return .{ .text = t, .ty = .{ .int = .{ .bits = 1, .signed = false } } };
}
