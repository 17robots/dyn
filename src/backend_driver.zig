const std = @import("std");
const Pipeline = @import("pipeline.zig");
const LowerIr = @import("lower_ir.zig");
const BackendCodegen = @import("backend_codegen.zig");

pub const BuildError = anyerror;

pub const BuildOptions = struct {
    codegen: BackendCodegen.Options = .{},
};

pub fn buildExecutableFromEntry(
    allocator: std.mem.Allocator,
    writer: anytype,
    entry_path: []const u8,
    asm_path: []const u8,
    out_path: []const u8,
    opts: BuildOptions,
) BuildError!void {
    var front = try Pipeline.runFrontend(allocator, writer, entry_path, .{});
    defer front.deinit();
    if (!front.canCodegen()) return error.FrontendFailed;

    var ir = try LowerIr.lowerMainProgram(allocator, &front.graph);
    defer @import("ir.zig").deinitProgram(allocator, &ir);

    try BackendCodegen.buildArtifact(allocator, ir, asm_path, out_path, opts.codegen);
}

pub fn buildObjectFromEntry(
    allocator: std.mem.Allocator,
    writer: anytype,
    entry_path: []const u8,
    asm_path: []const u8,
    out_obj_path: []const u8,
) BuildError!void {
    return buildExecutableFromEntry(
        allocator,
        writer,
        entry_path,
        asm_path,
        out_obj_path,
        .{ .codegen = .{ .kind = .object, .strategy = .direct_asm } },
    );
}

pub fn buildExecutableFromEntryViaModules(
    allocator: std.mem.Allocator,
    writer: anytype,
    entry_path: []const u8,
    work_dir: []const u8,
    out_exe_path: []const u8,
) BuildError!void {
    var front = try Pipeline.runFrontend(allocator, writer, entry_path, .{});
    defer front.deinit();
    if (!front.canCodegen()) return error.FrontendFailed;

    try BackendCodegen.buildExecutableFromGraphModules(allocator, &front.graph, work_dir, out_exe_path, .{});
}

pub fn buildExecutableFromEntryInterp(
    allocator: std.mem.Allocator,
    writer: anytype,
    entry_path: []const u8,
    asm_path: []const u8,
    out_path: []const u8,
) BuildError!void {
    return buildExecutableFromEntry(allocator, writer, entry_path, asm_path, out_path, .{ .codegen = .{ .strategy = .interp_asm } });
}

pub fn buildExecutableFromEntryDirect(
    allocator: std.mem.Allocator,
    writer: anytype,
    entry_path: []const u8,
    asm_path: []const u8,
    out_path: []const u8,
) BuildError!void {
    return buildExecutableFromEntry(allocator, writer, entry_path, asm_path, out_path, .{ .codegen = .{ .strategy = .direct_asm } });
}

test "builds executable from entry" {
    const alloc = std.testing.allocator;
    const dir = "tmp_backend_driver";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_backend_driver/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nmain := () i32 => 9 + 1\n");
    }

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);

    const asm_path = "tmp_backend_driver/out.s";
    const exe_path = "tmp_backend_driver/out";
    try buildExecutableFromEntry(alloc, w, "tmp_backend_driver/main.dyn", asm_path, exe_path, .{});

    var child = std.process.Child.init(&.{"./tmp_backend_driver/out"}, alloc);
    const term = try child.spawnAndWait();
    switch (term) {
        .Exited => |code| try std.testing.expectEqual(@as(u8, 10), code),
        else => return error.TestUnexpectedResult,
    }
}

test "builds executable from entry with match direct asm" {
    const alloc = std.testing.allocator;
    const dir = "tmp_backend_driver_direct_match";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_backend_driver_direct_match/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll(
            "module main\n" ++
                "main := () i32 => match 10 { 10: 17, _: 1 }\n",
        );
    }

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);

    {
        var front = try Pipeline.runFrontend(alloc, w, "tmp_backend_driver_direct_match/main.dyn", .{});
        defer front.deinit();
        if (!front.canCodegen()) {
            std.debug.print("frontend diagnostics:\n{s}\n", .{out.items});
            return error.FrontendFailed;
        }
    }

    const asm_path = "tmp_backend_driver_direct_match/out.s";
    const exe_path = "tmp_backend_driver_direct_match/out";
    try buildExecutableFromEntry(alloc, w, "tmp_backend_driver_direct_match/main.dyn", asm_path, exe_path, .{});

    var child = std.process.Child.init(&.{"./tmp_backend_driver_direct_match/out"}, alloc);
    const term = try child.spawnAndWait();
    switch (term) {
        .Exited => |code| try std.testing.expectEqual(@as(u8, 17), code),
        else => return error.TestUnexpectedResult,
    }
}

test "builds executable from entry direct asm" {
    const alloc = std.testing.allocator;
    const dir = "tmp_backend_driver_direct";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_backend_driver_direct/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nadd := (x: i32, y: i32) i32 => x + y\nmain := () i32 => add(3, 9)\n");
    }

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);

    const asm_path = "tmp_backend_driver_direct/out.s";
    const exe_path = "tmp_backend_driver_direct/out";
    try buildExecutableFromEntryDirect(alloc, w, "tmp_backend_driver_direct/main.dyn", asm_path, exe_path);

    var child = std.process.Child.init(&.{"./tmp_backend_driver_direct/out"}, alloc);
    const term = try child.spawnAndWait();
    switch (term) {
        .Exited => |code| try std.testing.expectEqual(@as(u8, 12), code),
        else => return error.TestUnexpectedResult,
    }
}

test "builds object from entry" {
    const alloc = std.testing.allocator;
    const dir = "tmp_backend_driver_obj";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_backend_driver_obj/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nmain := () i32 => 4\n");
    }

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);

    const asm_path = "tmp_backend_driver_obj/out.s";
    const obj_path = "tmp_backend_driver_obj/out.o";
    try buildObjectFromEntry(alloc, w, "tmp_backend_driver_obj/main.dyn", asm_path, obj_path);
    const st = try std.fs.cwd().statFile(obj_path);
    try std.testing.expect(st.size > 0);
}

test "builds executable from entry via module objects" {
    const alloc = std.testing.allocator;
    const dir = "tmp_backend_driver_modules";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_backend_driver_modules/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nL := use \"lib\"\nmain := () i32 => L.helper()\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_backend_driver_modules/lib.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module lib\npub helper := () i32 => 27\n");
    }

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);

    try buildExecutableFromEntryViaModules(
        alloc,
        w,
        "tmp_backend_driver_modules/main.dyn",
        "tmp_backend_driver_modules",
        "tmp_backend_driver_modules/out",
    );

    var child = std.process.Child.init(&.{"./tmp_backend_driver_modules/out"}, alloc);
    const term = try child.spawnAndWait();
    switch (term) {
        .Exited => |code| try std.testing.expectEqual(@as(u8, 27), code),
        else => return error.TestUnexpectedResult,
    }
}

fn runZigBuildRun(allocator: std.mem.Allocator, args: []const []const u8) !std.process.Child.Term {
    var argv = std.ArrayList([]const u8).empty;
    defer argv.deinit(allocator);
    try argv.append(allocator, "zig");
    try argv.append(allocator, "build");
    try argv.append(allocator, "run");
    try argv.append(allocator, "--");
    for (args) |a| try argv.append(allocator, a);

    var child = std.process.Child.init(argv.items, allocator);
    return try child.spawnAndWait();
}

test "cli integration build/check/clean flow" {
    const alloc = std.testing.allocator;
    const dir = "tmp_cli_integration";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_cli_integration/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nmain := () i32 => 0\n");
    }

    {
        const t = try runZigBuildRun(alloc, &.{ "check", "tmp_cli_integration/main.dyn", "--json" });
        switch (t) {
            .Exited => |code| try std.testing.expectEqual(@as(u8, 0), code),
            else => return error.TestUnexpectedResult,
        }
    }

    {
        const t = try runZigBuildRun(alloc, &.{ "build", "tmp_cli_integration/main.dyn", "--work-dir", "tmp_cli_integration/work", "-o", "tmp_cli_integration/out", "--json" });
        switch (t) {
            .Exited => |code| try std.testing.expectEqual(@as(u8, 0), code),
            else => return error.TestUnexpectedResult,
        }
    }
    _ = try std.fs.cwd().statFile("tmp_cli_integration/out");

    {
        const t = try runZigBuildRun(alloc, &.{ "clean", "--work-dir", "tmp_cli_integration/work", "--json" });
        switch (t) {
            .Exited => |code| try std.testing.expectEqual(@as(u8, 0), code),
            else => return error.TestUnexpectedResult,
        }
    }
}

test "cli integration reports invalid flag with nonzero exit" {
    const alloc = std.testing.allocator;
    const t = try runZigBuildRun(alloc, &.{ "build", "--badflag" });
    switch (t) {
        .Exited => |code| try std.testing.expect(code != 0),
        else => return error.TestUnexpectedResult,
    }
}

test "builds executable with nested module imports" {
    const alloc = std.testing.allocator;
    const dir = "tmp_backend_driver_nested_imports";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    try std.fs.cwd().makePath("tmp_backend_driver_nested_imports/pkg");
    defer std.fs.cwd().deleteTree(dir) catch {};

    {
        var f = try std.fs.cwd().createFile("tmp_backend_driver_nested_imports/main.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module main\nP := use \"pkg/math\"\nmain := () i32 => P.value()\n");
    }
    {
        var f = try std.fs.cwd().createFile("tmp_backend_driver_nested_imports/pkg/math.dyn", .{ .truncate = true });
        defer f.close();
        try f.writeAll("module math\npub value := () i32 => 44\n");
    }

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);

    try buildExecutableFromEntryViaModules(
        alloc,
        w,
        "tmp_backend_driver_nested_imports/main.dyn",
        "tmp_backend_driver_nested_imports",
        "tmp_backend_driver_nested_imports/out",
    );

    var child = std.process.Child.init(&.{"./tmp_backend_driver_nested_imports/out"}, alloc);
    const term = try child.spawnAndWait();
    switch (term) {
        .Exited => |code| try std.testing.expectEqual(@as(u8, 44), code),
        else => return error.TestUnexpectedResult,
    }
}
