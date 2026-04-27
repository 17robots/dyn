const std = @import("std");
const diag = @import("diag.zig");
const parser = @import("parser.zig");
const checker = @import("checker.zig");
const pretty = @import("pretty.zig");
const hir = @import("hir.zig");
const codegen = @import("codegen.zig");

pub fn main(init: std.process.Init) !void {
    const allocator = init.arena.allocator();
    var it = try std.process.Args.Iterator.initAllocator(init.minimal.args, allocator);
    defer it.deinit();
    const argv0 = it.next() orelse "dyn";
    const cmd = it.next() orelse return usage(argv0);
    const path = it.next() orelse return usage(argv0);
    const src = try std.Io.Dir.readFileAlloc(.cwd(), init.io, path, allocator, .limited(16 * 1024 * 1024));
    var bag = diag.DiagnosticBag.init(allocator, .{});
    defer bag.deinit();
    if (std.mem.eql(u8, cmd, "parse")) {
        const parsed = try parser.parseFileSource(allocator, src, &bag);
        if (bag.hasErrors()) return renderAndExit(allocator, path, src, &bag);
        if (parsed.file.items.len > 0) {
            const item = parsed.tree.topLevelItem(parsed.file.items[0]);
            if (item.kind == .declaration) {
                const d = parsed.tree.decl(item.kind.declaration);
                const out = try pretty.printExpr(allocator, &parsed.tree, d.value);
                defer allocator.free(out);
                std.debug.print("{s}\n", .{out});
            }
        }
    } else if (std.mem.eql(u8, cmd, "check")) {
        try checker.checkSource(allocator, src, &bag);
        if (bag.hasErrors()) return renderAndExit(allocator, path, src, &bag);
        std.debug.print("ok\n", .{});
    } else if (std.mem.eql(u8, cmd, "build")) {
        const out_path = try parseOutputPath(&it, argv0);
        try buildExecutable(allocator, init.io, path, src, out_path, &bag);
        if (bag.hasErrors()) return renderAndExit(allocator, path, src, &bag);
    } else if (std.mem.eql(u8, cmd, "run")) {
        const out_path = "/tmp/dyn-step14-run";
        try buildExecutable(allocator, init.io, path, src, out_path, &bag);
        if (bag.hasErrors()) return renderAndExit(allocator, path, src, &bag);
        const result = try std.process.run(allocator, init.io, .{ .argv = &.{out_path}, .stdout_limit = .limited(1024), .stderr_limit = .limited(1024) });
        switch (result.term) {
            .exited => |code| std.process.exit(code),
            else => std.process.exit(1),
        }
    } else return usage(argv0);
}
fn usage(argv0: []const u8) !void {
    std.debug.print("usage: {s} <parse|check|build|run> <file.dyn> [-o output]\n", .{argv0});
    std.process.exit(2);
}
fn parseOutputPath(it: *std.process.Args.Iterator, argv0: []const u8) ![]const u8 {
    const flag = it.next() orelse return "a.out";
    if (!std.mem.eql(u8, flag, "-o")) {
        try usage(argv0);
        unreachable;
    }
    return it.next() orelse {
        try usage(argv0);
        unreachable;
    };
}
fn buildExecutable(allocator: std.mem.Allocator, io: std.Io, path: []const u8, src: []const u8, out_path: []const u8, bag: *diag.DiagnosticBag) !void {
    _ = path;
    const parsed = try parser.parseFileSource(allocator, src, bag);
    if (bag.hasErrors()) return;
    var c = try checker.Checker.init(allocator, bag);
    defer c.deinit();
    try c.checkFile(&parsed.tree, parsed.file);
    if (bag.hasErrors()) return;
    const module = (try hir.lowerTrivial(allocator, &parsed.tree, parsed.file, bag)) orelse return;
    const obj_path = try std.fmt.allocPrint(allocator, "{s}.ll", .{out_path});
    defer allocator.free(obj_path);
    try codegen.emitObject(allocator, io, module, obj_path);
    const argv = &.{ "clang", obj_path, "-o", out_path };
    const result = try std.process.run(allocator, io, .{ .argv = argv, .stdout_limit = .limited(1024), .stderr_limit = .limited(4096) });
    if (result.term != .exited or result.term.exited != 0) return error.LinkFailed;
}
fn renderAndExit(allocator: std.mem.Allocator, path: []const u8, src: []const u8, bag: *diag.DiagnosticBag) !void {
    var single = diag.SingleSource{ .path = path, .text = src };
    const rendered = try diag.render(allocator, single.provider(), bag.diagnostics.items);
    defer allocator.free(rendered);
    std.debug.print("{s}", .{rendered});
    std.process.exit(1);
}
