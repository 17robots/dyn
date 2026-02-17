const std = @import("std");
const builtin = @import("builtin");
const Ir = @import("ir.zig");
const BackendNative = @import("backend_native.zig");
const LowerIr = @import("lower_ir.zig");
const ModuleGraph = @import("module_graph.zig");

pub const ArtifactKind = enum {
    executable,
    object,
};

pub const Strategy = enum {
    direct_asm,
    interp_asm,
};

pub const Options = struct {
    target: BackendNative.Target = .linux_x86_64,
    kind: ArtifactKind = .executable,
    strategy: Strategy = .direct_asm,
};

pub const CodegenError = anyerror;

const AbiSig = struct {
    call_conv: Ir.CallConv,
    param_type: Ir.ScalarType,
    ret_type: Ir.ScalarType,
    param_count: u32,
};

pub fn buildArtifact(
    allocator: std.mem.Allocator,
    program: Ir.Program,
    asm_path: []const u8,
    out_path: []const u8,
    opts: Options,
) CodegenError!void {
    switch (opts.kind) {
        .executable => switch (opts.strategy) {
            .direct_asm => try BackendNative.buildExecutableDirect(allocator, opts.target, program, asm_path, out_path),
            .interp_asm => try BackendNative.buildExecutable(allocator, opts.target, program, asm_path, out_path),
        },
        .object => switch (opts.strategy) {
            .direct_asm => try BackendNative.buildObjectDirect(allocator, opts.target, program, asm_path, out_path),
            .interp_asm => return error.UnsupportedArtifact,
        },
    }
}

pub fn linkObjects(
    allocator: std.mem.Allocator,
    out_exe_path: []const u8,
    obj_paths: []const []const u8,
) CodegenError!void {
    var argv = std.ArrayList([]const u8).empty;
    defer argv.deinit(allocator);
    try argv.append(allocator, "cc");
    try argv.append(allocator, "-nostdlib");
    try argv.append(allocator, "-Wl,-e,_start");
    try argv.append(allocator, "-o");
    try argv.append(allocator, out_exe_path);
    for (obj_paths) |p| try argv.append(allocator, p);

    var child = std.process.Child.init(argv.items, allocator);
    const term = try child.spawnAndWait();
    switch (term) {
        .Exited => |code| if (code != 0) return error.LinkFailed,
        else => return error.LinkFailed,
    }
}

pub fn buildExecutableFromProgramsViaObjects(
    allocator: std.mem.Allocator,
    programs: []const Ir.Program,
    work_dir: []const u8,
    out_exe_path: []const u8,
    opts: Options,
) CodegenError!void {
    if (programs.len == 0) return error.UnsupportedArtifact;
    if (opts.target != .linux_x86_64) return error.UnsupportedArtifact;

    var entry_program_index: ?usize = null;
    for (programs, 0..) |p, i| {
        var has_main = false;
        for (p.functions) |f| {
            if (std.mem.eql(u8, f.name, "main")) {
                has_main = true;
                break;
            }
        }
        if (has_main) {
            entry_program_index = i;
            break;
        }
    }
    if (entry_program_index == null) return error.MissingMain;

    try validateProgramsAbi(allocator, programs);

    var obj_paths = std.ArrayList([]u8).empty;
    defer {
        for (obj_paths.items) |p| allocator.free(p);
        obj_paths.deinit(allocator);
    }

    var i: usize = 0;
    while (i < programs.len) : (i += 1) {
        const asm_path = try std.fmt.allocPrint(allocator, "{s}/unit_{d}.s", .{ work_dir, i });
        defer allocator.free(asm_path);
        const obj_path = try std.fmt.allocPrint(allocator, "{s}/unit_{d}.o", .{ work_dir, i });
        try obj_paths.append(allocator, obj_path);

        const prefix = try std.fmt.allocPrint(allocator, "u{d}", .{i});
        defer allocator.free(prefix);
        try BackendNative.buildObjectDirectWithPrefix(
            allocator,
            opts.target,
            programs[i],
            asm_path,
            obj_path,
            prefix,
            i == entry_program_index.?,
        );
    }

    var obj_refs = try allocator.alloc([]const u8, obj_paths.items.len);
    defer allocator.free(obj_refs);
    for (obj_paths.items, 0..) |p, idx| obj_refs[idx] = p;
    try linkObjects(allocator, out_exe_path, obj_refs);
}

fn validateProgramsAbi(allocator: std.mem.Allocator, programs: []const Ir.Program) CodegenError!void {
    var syms: std.StringHashMapUnmanaged(AbiSig) = .empty;
    defer syms.deinit(allocator);

    try syms.put(allocator, "__dyn_os_alloc", .{ .call_conv = .stack_i64, .param_type = .i64, .ret_type = .i64, .param_count = 2 });
    try syms.put(allocator, "__dyn_os_free", .{ .call_conv = .stack_i64, .param_type = .i64, .ret_type = .i64, .param_count = 3 });
    try syms.put(allocator, "__dyn_os_realloc", .{ .call_conv = .stack_i64, .param_type = .i64, .ret_type = .i64, .param_count = 5 });

    for (programs) |p| {
        for (p.functions) |f| {
            const sig = AbiSig{ .call_conv = f.call_conv, .param_type = f.param_type, .ret_type = f.ret_type, .param_count = f.param_count };
            if (syms.get(f.name)) |prev| {
                if (prev.call_conv != sig.call_conv or prev.param_type != sig.param_type or prev.ret_type != sig.ret_type or prev.param_count != sig.param_count) {
                    return error.AbiSymbolConflict;
                }
            } else {
                try syms.put(allocator, f.name, sig);
            }
        }
    }

    for (programs) |p| {
        for (p.functions) |f| {
            for (f.instructions) |ins| {
                if (ins != .call) continue;
                const c = ins.call;
                switch (c.target) {
                    .internal_index => |idx| {
                        if (idx >= p.functions.len) return error.AbiMissingSymbol;
                        const callee = p.functions[idx];
                        if (c.arg_count != callee.param_count) return error.AbiArgCountMismatch;
                        if (f.call_conv != callee.call_conv) return error.AbiCallConvMismatch;
                        if (f.param_type != callee.param_type) return error.AbiParamTypeMismatch;
                    },
                    .external_symbol => |ex| {
                        const sig = syms.get(ex.name) orelse return error.AbiMissingSymbol;
                        if (c.arg_count != sig.param_count) return error.AbiArgCountMismatch;
                        if (f.call_conv != sig.call_conv) return error.AbiCallConvMismatch;
                        if (f.param_type != sig.param_type) return error.AbiParamTypeMismatch;
                    },
                }
            }
        }
    }
}

pub fn buildExecutableFromGraphModules(
    allocator: std.mem.Allocator,
    graph: *ModuleGraph.Self,
    work_dir: []const u8,
    out_exe_path: []const u8,
    opts: Options,
) CodegenError!void {
    if (opts.target != .linux_x86_64) return error.UnsupportedArtifact;

    const entry_module = findEntryModule(graph) orelse return error.MissingMain;
    const cache_dir = try std.fmt.allocPrint(allocator, "{s}/.dyn_cache", .{work_dir});
    defer allocator.free(cache_dir);
    std.fs.cwd().makePath(cache_dir) catch {};

    var own_fingerprints = try allocator.alloc([]u8, graph.modules.items.len);
    defer {
        for (own_fingerprints) |fp| allocator.free(fp);
        allocator.free(own_fingerprints);
    }

    var dirty = try allocator.alloc(bool, graph.modules.items.len);
    defer allocator.free(dirty);

    var mi: u32 = 0;
    while (mi < graph.modules.items.len) : (mi += 1) {
        own_fingerprints[mi] = try moduleFingerprint(allocator, graph, mi, opts);
        const obj_path_probe = try std.fmt.allocPrint(allocator, "{s}/module_{d}.o", .{ work_dir, mi });
        defer allocator.free(obj_path_probe);
        const manifest_path = try std.fmt.allocPrint(allocator, "{s}/module_{d}.fingerprint", .{ cache_dir, mi });
        defer allocator.free(manifest_path);
        dirty[mi] = !(try canReuseCachedObject(allocator, manifest_path, obj_path_probe, own_fingerprints[mi]));
    }

    try propagateDirtyReverseDeps(allocator, graph, dirty);

    var obj_paths = std.ArrayList([]u8).empty;
    defer {
        for (obj_paths.items) |p| allocator.free(p);
        obj_paths.deinit(allocator);
    }

    mi = 0;
    while (mi < graph.modules.items.len) : (mi += 1) {
        const obj_path = try std.fmt.allocPrint(allocator, "{s}/module_{d}.o", .{ work_dir, mi });
        try obj_paths.append(allocator, obj_path);

        const fingerprint = own_fingerprints[mi];
        const manifest_path = try std.fmt.allocPrint(allocator, "{s}/module_{d}.fingerprint", .{ cache_dir, mi });
        defer allocator.free(manifest_path);

        const reuse = !dirty[mi] and (try canReuseCachedObject(allocator, manifest_path, obj_path, fingerprint));
        if (!reuse) {
            const asm_path = try std.fmt.allocPrint(allocator, "{s}/module_{d}.s", .{ work_dir, mi });
            defer allocator.free(asm_path);
            const prefix = try std.fmt.allocPrint(allocator, "u{d}", .{mi});
            defer allocator.free(prefix);

            var program = try LowerIr.lowerModuleProgram(allocator, graph, mi);
            defer Ir.deinitProgram(allocator, &program);
            try BackendNative.buildObjectDirectWithPrefix(
                allocator,
                opts.target,
                program,
                asm_path,
                obj_path,
                prefix,
                mi == entry_module,
            );
            try writeFingerprint(manifest_path, fingerprint);
        }
    }

    var obj_refs = try allocator.alloc([]const u8, obj_paths.items.len);
    defer allocator.free(obj_refs);
    for (obj_paths.items, 0..) |p, i| obj_refs[i] = p;
    try linkObjects(allocator, out_exe_path, obj_refs);
}

fn findEntryModule(graph: *ModuleGraph.Self) ?u32 {
    var i: u32 = 0;
    while (i < graph.modules.items.len) : (i += 1) {
        if (std.mem.eql(u8, graph.modules.items[i].name, "main")) return i;
    }
    return null;
}

fn moduleFingerprint(allocator: std.mem.Allocator, graph: *ModuleGraph.Self, module_index: u32, opts: Options) ![]u8 {
    const m = graph.modules.items[module_index];
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try out.writer(allocator).print("mod:{s}\n", .{m.name});
    try out.writer(allocator).print("target:{s}\n", .{@tagName(opts.target)});
    try out.writer(allocator).print("kind:{s}\n", .{@tagName(opts.kind)});
    try out.writer(allocator).print("strategy:{s}\n", .{@tagName(opts.strategy)});
    try out.writer(allocator).print("zig:{d}.{d}.{d}\n", .{ builtin.zig_version.major, builtin.zig_version.minor, builtin.zig_version.patch });

    var i: u32 = 0;
    while (i < m.file_count) : (i += 1) {
        const file_index = graph.module_file_indices.items[m.file_start + i];
        const f = graph.files.items[file_index];
        const st = try std.fs.cwd().statFile(f.path);
        try out.writer(allocator).print("{s}|{d}|{d}\n", .{ f.path, st.size, @as(i128, @intCast(st.mtime)) });
    }
    return try out.toOwnedSlice(allocator);
}

fn propagateDirtyReverseDeps(allocator: std.mem.Allocator, graph: *ModuleGraph.Self, dirty: []bool) !void {
    var queue = std.ArrayList(u32).empty;
    defer queue.deinit(allocator);

    for (dirty, 0..) |d, i| {
        if (d) try queue.append(allocator, @intCast(i));
    }

    var cursor: usize = 0;
    while (cursor < queue.items.len) : (cursor += 1) {
        const changed = queue.items[cursor];
        for (graph.edges.items) |e| {
            const to = e.to_module orelse continue;
            if (to != changed) continue;
            const importer = e.from_module;
            if (!dirty[importer]) {
                dirty[importer] = true;
                try queue.append(allocator, importer);
            }
        }
    }
}

fn canReuseCachedObject(
    allocator: std.mem.Allocator,
    manifest_path: []const u8,
    obj_path: []const u8,
    fingerprint: []const u8,
) !bool {
    _ = std.fs.cwd().statFile(obj_path) catch return false;
    const old = std.fs.cwd().readFileAlloc(allocator, manifest_path, 1 << 20) catch return false;
    defer allocator.free(old);
    return std.mem.eql(u8, old, fingerprint);
}

fn writeFingerprint(manifest_path: []const u8, fingerprint: []const u8) !void {
    var f = try std.fs.cwd().createFile(manifest_path, .{ .truncate = true });
    defer f.close();
    try f.writeAll(fingerprint);
}

test "backend codegen builds executable direct" {
    const alloc = std.testing.allocator;
    var p = try Ir.makeTinyMain(alloc, 11);
    defer Ir.deinitProgram(alloc, &p);

    const dir = "tmp_backend_codegen";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    try buildArtifact(alloc, p, "tmp_backend_codegen/out.s", "tmp_backend_codegen/out", .{});
    var child = std.process.Child.init(&.{"./tmp_backend_codegen/out"}, alloc);
    const term = try child.spawnAndWait();
    switch (term) {
        .Exited => |code| try std.testing.expectEqual(@as(u8, 11), code),
        else => return error.TestUnexpectedResult,
    }
}

test "backend codegen builds object direct" {
    const alloc = std.testing.allocator;
    var p = try Ir.makeTinyMain(alloc, 1);
    defer Ir.deinitProgram(alloc, &p);

    const dir = "tmp_backend_codegen_obj";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    try buildArtifact(alloc, p, "tmp_backend_codegen_obj/out.s", "tmp_backend_codegen_obj/out.o", .{ .kind = .object, .strategy = .direct_asm });
    const st = try std.fs.cwd().statFile("tmp_backend_codegen_obj/out.o");
    try std.testing.expect(st.size > 0);
}

test "backend codegen links multiple objects" {
    const alloc = std.testing.allocator;
    const dir = "tmp_backend_codegen_link";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    var p0 = try Ir.makeTinyMain(alloc, 23);
    defer Ir.deinitProgram(alloc, &p0);
    var p1 = try Ir.makeTinyMain(alloc, 99);
    defer Ir.deinitProgram(alloc, &p1);
    p1.functions[0].name = "util_main";

    var ps = [_]Ir.Program{ p0, p1 };
    try buildExecutableFromProgramsViaObjects(
        alloc,
        &ps,
        dir,
        "tmp_backend_codegen_link/out",
        .{},
    );

    var child = std.process.Child.init(&.{"./tmp_backend_codegen_link/out"}, alloc);
    const term = try child.spawnAndWait();
    switch (term) {
        .Exited => |code| try std.testing.expectEqual(@as(u8, 23), code),
        else => return error.TestUnexpectedResult,
    }
}

test "backend codegen links modules from graph" {
    const alloc = std.testing.allocator;
    const dir = "tmp_backend_codegen_graph";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_backend_codegen_graph/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nmain := () i32 => 31\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_backend_codegen_graph/other.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module util\nhelper := () i32 => 9\n");
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_backend_codegen_graph/main.dyn");
    defer g.deinit();

    try buildExecutableFromGraphModules(alloc, &g, dir, "tmp_backend_codegen_graph/out", .{});
    var child = std.process.Child.init(&.{"./tmp_backend_codegen_graph/out"}, alloc);
    const term = try child.spawnAndWait();
    switch (term) {
        .Exited => |code| try std.testing.expectEqual(@as(u8, 31), code),
        else => return error.TestUnexpectedResult,
    }
}

test "backend codegen reuses module cache manifests" {
    const alloc = std.testing.allocator;
    const dir = "tmp_backend_codegen_cache";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_backend_codegen_cache/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nmain := () i32 => 5\n");
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_backend_codegen_cache/main.dyn");
    defer g.deinit();

    try buildExecutableFromGraphModules(alloc, &g, dir, "tmp_backend_codegen_cache/out", .{});
    try buildExecutableFromGraphModules(alloc, &g, dir, "tmp_backend_codegen_cache/out2", .{});

    _ = try std.fs.cwd().statFile("tmp_backend_codegen_cache/.dyn_cache/module_0.fingerprint");
}

test "reverse dependency invalidation marks importers dirty" {
    const alloc = std.testing.allocator;
    const dir = "tmp_backend_codegen_revdep";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_backend_codegen_revdep/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nL := use \"lib\"\nmain := () i32 => L.helper()\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_backend_codegen_revdep/lib.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module lib\npub helper := () i32 => 1\n");
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_backend_codegen_revdep/main.dyn");
    defer g.deinit();

    var main_idx: ?u32 = null;
    var lib_idx: ?u32 = null;
    for (g.modules.items, 0..) |m, i| {
        if (std.mem.eql(u8, m.name, "main")) main_idx = @intCast(i);
        if (std.mem.eql(u8, m.name, "lib")) lib_idx = @intCast(i);
    }
    try std.testing.expect(main_idx != null and lib_idx != null);

    var dirty = try alloc.alloc(bool, g.modules.items.len);
    defer alloc.free(dirty);
    @memset(dirty, false);
    dirty[lib_idx.?] = true;

    try propagateDirtyReverseDeps(alloc, &g, dirty);
    try std.testing.expect(dirty[main_idx.?]);
}

test "reverse dependency invalidation propagates transitively" {
    const alloc = std.testing.allocator;
    const dir = "tmp_backend_codegen_revdep_transitive";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_backend_codegen_revdep_transitive/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nM := use \"mid\"\nmain := () i32 => M.mid()\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_backend_codegen_revdep_transitive/mid.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module mid\nL := use \"leaf\"\npub mid := () i32 => L.leaf()\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_backend_codegen_revdep_transitive/leaf.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module leaf\npub leaf := () i32 => 9\n");
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_backend_codegen_revdep_transitive/main.dyn");
    defer g.deinit();

    var main_idx: ?u32 = null;
    var mid_idx: ?u32 = null;
    var leaf_idx: ?u32 = null;
    for (g.modules.items, 0..) |m, i| {
        if (std.mem.eql(u8, m.name, "main")) main_idx = @intCast(i);
        if (std.mem.eql(u8, m.name, "mid")) mid_idx = @intCast(i);
        if (std.mem.eql(u8, m.name, "leaf")) leaf_idx = @intCast(i);
    }
    try std.testing.expect(main_idx != null and mid_idx != null and leaf_idx != null);

    var dirty = try alloc.alloc(bool, g.modules.items.len);
    defer alloc.free(dirty);
    @memset(dirty, false);
    dirty[leaf_idx.?] = true;

    try propagateDirtyReverseDeps(alloc, &g, dirty);
    try std.testing.expect(dirty[mid_idx.?]);
    try std.testing.expect(dirty[main_idx.?]);
}

test "backend codegen detects ABI mismatch" {
    const alloc = std.testing.allocator;
    const instr_a = try alloc.alloc(Ir.Instruction, 3);
    instr_a[0] = .{ .push_const_i64 = 1 };
    instr_a[1] = .{ .push_const_i64 = 2 };
    instr_a[2] = .{ .call = .{ .arg_count = 2, .target = .{ .external_symbol = .{ .name = "foo", .name_owned = false } } } };
    const fa = try alloc.alloc(Ir.Function, 1);
    fa[0] = .{ .name = "main", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 0, .local_count = 0, .instructions = instr_a };
    var pa = Ir.Program{ .functions = fa, .rodata_strings = &.{}, .global_count = 0 };
    defer Ir.deinitProgram(alloc, &pa);

    const instr_b = try alloc.alloc(Ir.Instruction, 1);
    instr_b[0] = .{ .ret = {} };
    const fb = try alloc.alloc(Ir.Function, 1);
    fb[0] = .{ .name = "foo", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 1, .local_count = 0, .instructions = instr_b };
    var pb = Ir.Program{ .functions = fb, .rodata_strings = &.{}, .global_count = 0 };
    defer Ir.deinitProgram(alloc, &pb);

    var ps = [_]Ir.Program{ pa, pb };
    try std.testing.expectError(error.AbiArgCountMismatch, validateProgramsAbi(alloc, &ps));
}

test "backend codegen detects ABI missing symbol" {
    const alloc = std.testing.allocator;
    const instr = try alloc.alloc(Ir.Instruction, 2);
    instr[0] = .{ .push_const_i64 = 1 };
    instr[1] = .{ .call = .{ .arg_count = 1, .target = .{ .external_symbol = .{ .name = "missing", .name_owned = false } } } };
    const funcs = try alloc.alloc(Ir.Function, 1);
    funcs[0] = .{ .name = "main", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 0, .local_count = 0, .instructions = instr };
    var p = Ir.Program{ .functions = funcs, .rodata_strings = &.{}, .global_count = 0 };
    defer Ir.deinitProgram(alloc, &p);

    var ps = [_]Ir.Program{p};
    try std.testing.expectError(error.AbiMissingSymbol, validateProgramsAbi(alloc, &ps));
}

test "backend codegen detects ABI param type mismatch" {
    const alloc = std.testing.allocator;

    const instr_a = try alloc.alloc(Ir.Instruction, 2);
    instr_a[0] = .{ .push_const_i64 = 1 };
    instr_a[1] = .{ .call = .{ .arg_count = 1, .target = .{ .external_symbol = .{ .name = "foo", .name_owned = false } } } };
    const fa = try alloc.alloc(Ir.Function, 1);
    fa[0] = .{ .name = "main", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .bool, .param_count = 0, .local_count = 0, .instructions = instr_a };
    var pa = Ir.Program{ .functions = fa, .rodata_strings = &.{}, .global_count = 0 };
    defer Ir.deinitProgram(alloc, &pa);

    const instr_b = try alloc.alloc(Ir.Instruction, 1);
    instr_b[0] = .{ .ret = {} };
    const fb = try alloc.alloc(Ir.Function, 1);
    fb[0] = .{ .name = "foo", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 1, .local_count = 0, .instructions = instr_b };
    var pb = Ir.Program{ .functions = fb, .rodata_strings = &.{}, .global_count = 0 };
    defer Ir.deinitProgram(alloc, &pb);

    var ps = [_]Ir.Program{ pa, pb };
    try std.testing.expectError(error.AbiParamTypeMismatch, validateProgramsAbi(alloc, &ps));
}

test "backend codegen detects ABI symbol conflict" {
    const alloc = std.testing.allocator;

    const instr_a = try alloc.alloc(Ir.Instruction, 1);
    instr_a[0] = .{ .ret = {} };
    const fa = try alloc.alloc(Ir.Function, 1);
    fa[0] = .{ .name = "foo", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 1, .local_count = 0, .instructions = instr_a };
    var pa = Ir.Program{ .functions = fa, .rodata_strings = &.{}, .global_count = 0 };
    defer Ir.deinitProgram(alloc, &pa);

    const instr_b = try alloc.alloc(Ir.Instruction, 1);
    instr_b[0] = .{ .ret = {} };
    const fb = try alloc.alloc(Ir.Function, 1);
    fb[0] = .{ .name = "foo", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .bool, .param_count = 1, .local_count = 0, .instructions = instr_b };
    var pb = Ir.Program{ .functions = fb, .rodata_strings = &.{}, .global_count = 0 };
    defer Ir.deinitProgram(alloc, &pb);

    var ps = [_]Ir.Program{ pa, pb };
    try std.testing.expectError(error.AbiSymbolConflict, validateProgramsAbi(alloc, &ps));
}

test "module fingerprint changes on file rename" {
    const alloc = std.testing.allocator;
    const dir = "tmp_backend_codegen_fingerprint_rename";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_backend_codegen_fingerprint_rename/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nmain := () i32 => helper()\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_backend_codegen_fingerprint_rename/helper.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nhelper := () i32 => 1\n");
    }

    var g1 = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_backend_codegen_fingerprint_rename/main.dyn");
    defer g1.deinit();
    const main_idx1 = findEntryModule(&g1) orelse return error.TestUnexpectedResult;
    const fp1 = try moduleFingerprint(alloc, &g1, main_idx1, .{});
    defer alloc.free(fp1);

    try std.fs.cwd().rename("tmp_backend_codegen_fingerprint_rename/helper.dyn", "tmp_backend_codegen_fingerprint_rename/helper2.dyn");

    var g2 = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_backend_codegen_fingerprint_rename/main.dyn");
    defer g2.deinit();
    const main_idx2 = findEntryModule(&g2) orelse return error.TestUnexpectedResult;
    const fp2 = try moduleFingerprint(alloc, &g2, main_idx2, .{});
    defer alloc.free(fp2);

    try std.testing.expect(!std.mem.eql(u8, fp1, fp2));
}

test "module fingerprint changes on file delete" {
    const alloc = std.testing.allocator;
    const dir = "tmp_backend_codegen_fingerprint_delete";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_backend_codegen_fingerprint_delete/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nmain := () i32 => 1\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_backend_codegen_fingerprint_delete/extra.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nvalue := 2\n");
    }

    var g1 = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_backend_codegen_fingerprint_delete/main.dyn");
    defer g1.deinit();
    const main_idx1 = findEntryModule(&g1) orelse return error.TestUnexpectedResult;
    const fp1 = try moduleFingerprint(alloc, &g1, main_idx1, .{});
    defer alloc.free(fp1);

    try std.fs.cwd().deleteFile("tmp_backend_codegen_fingerprint_delete/extra.dyn");

    var g2 = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_backend_codegen_fingerprint_delete/main.dyn");
    defer g2.deinit();
    const main_idx2 = findEntryModule(&g2) orelse return error.TestUnexpectedResult;
    const fp2 = try moduleFingerprint(alloc, &g2, main_idx2, .{});
    defer alloc.free(fp2);

    try std.testing.expect(!std.mem.eql(u8, fp1, fp2));
}

test "module fingerprint changes on file move" {
    const alloc = std.testing.allocator;
    const dir = "tmp_backend_codegen_fingerprint_move";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    try std.fs.cwd().makePath("tmp_backend_codegen_fingerprint_move/parking");
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_backend_codegen_fingerprint_move/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nmain := () i32 => helper()\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_backend_codegen_fingerprint_move/helper.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nhelper := () i32 => 3\n");
    }

    var g1 = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_backend_codegen_fingerprint_move/main.dyn");
    defer g1.deinit();
    const main_idx1 = findEntryModule(&g1) orelse return error.TestUnexpectedResult;
    const fp1 = try moduleFingerprint(alloc, &g1, main_idx1, .{});
    defer alloc.free(fp1);

    try std.fs.cwd().rename(
        "tmp_backend_codegen_fingerprint_move/helper.dyn",
        "tmp_backend_codegen_fingerprint_move/parking/helper.dyn",
    );

    var g2 = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_backend_codegen_fingerprint_move/main.dyn");
    defer g2.deinit();
    const main_idx2 = findEntryModule(&g2) orelse return error.TestUnexpectedResult;
    const fp2 = try moduleFingerprint(alloc, &g2, main_idx2, .{});
    defer alloc.free(fp2);

    try std.testing.expect(!std.mem.eql(u8, fp1, fp2));
}

test "module fingerprint changes when codegen options change" {
    const alloc = std.testing.allocator;
    const dir = "tmp_backend_codegen_fingerprint_opts";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_backend_codegen_fingerprint_opts/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nmain := () i32 => 1\n");
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_backend_codegen_fingerprint_opts/main.dyn");
    defer g.deinit();
    const main_idx = findEntryModule(&g) orelse return error.TestUnexpectedResult;

    const fp_default = try moduleFingerprint(alloc, &g, main_idx, .{});
    defer alloc.free(fp_default);
    const fp_obj_kind = try moduleFingerprint(alloc, &g, main_idx, .{ .kind = .object });
    defer alloc.free(fp_obj_kind);

    try std.testing.expect(!std.mem.eql(u8, fp_default, fp_obj_kind));
}

test "module fingerprint includes toolchain version" {
    const alloc = std.testing.allocator;
    const dir = "tmp_backend_codegen_fingerprint_toolchain";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_backend_codegen_fingerprint_toolchain/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nmain := () i32 => 1\n");
    }

    var g = try ModuleGraph.Self.buildFromEntry(alloc, "tmp_backend_codegen_fingerprint_toolchain/main.dyn");
    defer g.deinit();
    const main_idx = findEntryModule(&g) orelse return error.TestUnexpectedResult;
    const fp = try moduleFingerprint(alloc, &g, main_idx, .{});
    defer alloc.free(fp);

    try std.testing.expect(std.mem.indexOf(u8, fp, "zig:") != null);
}

test "unsupported artifact configuration returns UnsupportedArtifact" {
    const alloc = std.testing.allocator;
    var p = try Ir.makeTinyMain(alloc, 1);
    defer Ir.deinitProgram(alloc, &p);
    try std.testing.expectError(
        error.UnsupportedArtifact,
        buildArtifact(alloc, p, "tmp_backend_codegen_unsupported/out.s", "tmp_backend_codegen_unsupported/out.o", .{ .kind = .object, .strategy = .interp_asm }),
    );
}
