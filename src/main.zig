const std = @import("std");
const BackendDriver = @import("backend_driver.zig");
const Pipeline = @import("pipeline.zig");

pub fn main() void {
    runMain() catch |err| {
        switch (err) {
            error.InvalidArgument,
            error.EntryNotFound,
            error.AmbiguousEntry,
            error.CompilationFailed,
            error.FrontendFailed,
            error.RunFailed,
            => std.process.exit(1),
            error.UnsupportedArtifact => {
                std.debug.print("error: unsupported target/artifact configuration\n", .{});
                std.process.exit(1);
            },
            else => {
                std.debug.print("error: {s}\n", .{@errorName(err)});
                std.process.exit(1);
            },
        }
    };
}

fn runMain() !void {
    var gpa_impl: std.heap.GeneralPurposeAllocator(.{}) = .init;
    defer _ = gpa_impl.deinit();
    const gpa = gpa_impl.allocator();

    var out_buf: [4096]u8 = undefined;
    var out_w = std.fs.File.stdout().writer(&out_buf);
    const out = &out_w.interface;

    var err_buf: [4096]u8 = undefined;
    var err_w = std.fs.File.stderr().writer(&err_buf);
    const err = &err_w.interface;

    var args = try std.process.argsWithAllocator(gpa);
    defer args.deinit();

    _ = args.next(); // argv[0]
    const cmd = args.next() orelse {
        try printHelp(out);
        return;
    };

    if (std.mem.eql(u8, cmd, "help") or std.mem.eql(u8, cmd, "--help") or std.mem.eql(u8, cmd, "-h")) {
        if (args.next()) |sub| {
            if (std.mem.eql(u8, sub, "check")) {
                try printCheckHelp(out);
                return;
            }
            if (std.mem.eql(u8, sub, "build")) {
                try printBuildHelp(out);
                return;
            }
            if (std.mem.eql(u8, sub, "run")) {
                try printRunHelp(out);
                return;
            }
            if (std.mem.eql(u8, sub, "clean")) {
                try printCleanHelp(out);
                return;
            }
            try err.print("unknown command: {s}\n\n", .{sub});
            try printHelp(err);
            try err.flush();
            return error.InvalidArgument;
        }
        try printHelp(out);
        return;
    }

    if (std.mem.eql(u8, cmd, "check")) {
        var entry: ?[]const u8 = null;
        var json = false;
        var std_dir: ?[]const u8 = null;
        while (args.next()) |a| {
            if (std.mem.eql(u8, a, "-h") or std.mem.eql(u8, a, "--help")) {
                try printCheckHelp(out);
                return;
            } else if (std.mem.eql(u8, a, "--json")) {
                json = true;
            } else if (std.mem.eql(u8, a, "--std-dir")) {
                std_dir = args.next() orelse {
                    try err.writeAll("missing value for --std-dir\n");
                    try err.flush();
                    return error.InvalidArgument;
                };
            } else if (std.mem.startsWith(u8, a, "-")) {
                try err.print("unknown check flag: {s}\n", .{a});
                try err.flush();
                return error.InvalidArgument;
            } else if (entry == null) {
                entry = a;
            } else {
                try err.writeAll("check accepts at most one entry path\n");
                try err.flush();
                return error.InvalidArgument;
            }
        }

        const entry_path = entry orelse try discoverEntryPathOrReport(gpa, err);
        var diag_buf: std.ArrayList(u8) = .empty;
        defer diag_buf.deinit(gpa);
        var front = if (json)
            try Pipeline.runFrontend(gpa, diag_buf.writer(gpa), entry_path, .{ .std_dir = std_dir })
        else
            try Pipeline.runFrontend(gpa, out, entry_path, .{ .std_dir = std_dir });
        defer front.deinit();
        const s = front.summary();
        if (json) {
            try out.writeAll("{\"schema\":\"dyn-cli.v1\",\"command\":\"check\",\"entry\":\"");
            try writeJsonEscaped(out, entry_path);
            try out.print(
                "\",\"graph_errors\":{d},\"scope_errors\":{d},\"resolve_errors\":{d},\"semantic_errors\":{d},\"can_codegen\":{s},\"diagnostics\":",
                .{ s.graph_errors, s.scope_errors, s.resolve_errors, s.semantic_errors, if (s.can_codegen) "true" else "false" },
            );
            try writeJsonLineArray(out, diag_buf.items);
            try out.writeAll("}\n");
        } else {
            try out.print(
                "check: graph={d} scope={d} resolve={d} semantic={d} can_codegen={any}\n",
                .{ s.graph_errors, s.scope_errors, s.resolve_errors, s.semantic_errors, s.can_codegen },
            );
        }
        try out.flush();
        if (!s.can_codegen) return error.CompilationFailed;
        return;
    }

    if (std.mem.eql(u8, cmd, "build")) {
        var entry: ?[]const u8 = null;
        var out_path: []const u8 = "a.out";
        var work_dir: []const u8 = ".dyn_build";
        var emit_obj = false;
        var emit_asm = false;
        var json = false;
        var std_dir: ?[]const u8 = null;

        while (args.next()) |a| {
            if (std.mem.eql(u8, a, "-o")) {
                out_path = args.next() orelse {
                    try err.writeAll("missing value for -o\n");
                    try err.flush();
                    return error.InvalidArgument;
                };
            } else if (std.mem.eql(u8, a, "--work-dir")) {
                work_dir = args.next() orelse {
                    try err.writeAll("missing value for --work-dir\n");
                    try err.flush();
                    return error.InvalidArgument;
                };
            } else if (std.mem.eql(u8, a, "--emit-obj")) {
                emit_obj = true;
            } else if (std.mem.eql(u8, a, "--emit-asm")) {
                emit_asm = true;
            } else if (std.mem.eql(u8, a, "--json")) {
                json = true;
            } else if (std.mem.eql(u8, a, "--std-dir")) {
                std_dir = args.next() orelse {
                    try err.writeAll("missing value for --std-dir\n");
                    try err.flush();
                    return error.InvalidArgument;
                };
            } else if (std.mem.eql(u8, a, "-h") or std.mem.eql(u8, a, "--help")) {
                try printBuildHelp(out);
                return;
            } else if (std.mem.startsWith(u8, a, "-")) {
                try err.print("unknown build flag: {s}\n", .{a});
                try err.flush();
                return error.InvalidArgument;
            } else if (entry == null) {
                entry = a;
            } else {
                try err.writeAll("build accepts at most one entry path\n");
                try err.flush();
                return error.InvalidArgument;
            }
        }

        if (emit_obj and emit_asm) {
            try err.writeAll("cannot combine --emit-obj and --emit-asm\n");
            try err.flush();
            return error.InvalidArgument;
        }

        const entry_path = entry orelse try discoverEntryPathOrReport(gpa, err);
        std.fs.cwd().makePath(work_dir) catch {};

        var log_buf: std.ArrayList(u8) = .empty;
        defer log_buf.deinit(gpa);

        if (emit_obj) {
            const asm_path = try std.fmt.allocPrint(gpa, "{s}/out.s", .{work_dir});
            defer gpa.free(asm_path);
            if (json) {
                try BackendDriver.buildObjectFromEntry(gpa, log_buf.writer(gpa), entry_path, asm_path, out_path, .{ .std_dir = std_dir });
            } else {
                try BackendDriver.buildObjectFromEntry(gpa, out, entry_path, asm_path, out_path, .{ .std_dir = std_dir });
            }
        } else if (emit_asm) {
            const asm_path = out_path;
            const obj = try std.fmt.allocPrint(gpa, "{s}/tmp.o", .{work_dir});
            defer gpa.free(obj);
            if (json) {
                try BackendDriver.buildObjectFromEntry(gpa, log_buf.writer(gpa), entry_path, asm_path, obj, .{ .std_dir = std_dir });
            } else {
                try BackendDriver.buildObjectFromEntry(gpa, out, entry_path, asm_path, obj, .{ .std_dir = std_dir });
            }
        } else {
            if (json) {
                try BackendDriver.buildExecutableFromEntryViaModules(gpa, log_buf.writer(gpa), entry_path, work_dir, out_path, .{ .std_dir = std_dir });
            } else {
                try BackendDriver.buildExecutableFromEntryViaModules(gpa, out, entry_path, work_dir, out_path, .{ .std_dir = std_dir });
            }
        }

        if (json) {
            try out.writeAll("{\"schema\":\"dyn-cli.v1\",\"command\":\"build\",\"entry\":\"");
            try writeJsonEscaped(out, entry_path);
            try out.writeAll("\",\"out\":\"");
            try writeJsonEscaped(out, out_path);
            try out.writeAll("\",\"work_dir\":\"");
            try writeJsonEscaped(out, work_dir);
            try out.print("\",\"emit\":\"{s}\",\"ok\":true,\"diagnostics\":", .{if (emit_obj) "obj" else if (emit_asm) "asm" else "exe"});
            try writeJsonLineArray(out, log_buf.items);
            try out.writeAll("}\n");
        } else {
            try out.print("built: {s}\n", .{out_path});
        }
        try out.flush();
        return;
    }

    if (std.mem.eql(u8, cmd, "run")) {
        var entry: ?[]const u8 = null;
        var work_dir: []const u8 = ".dyn_build";
        var json = false;
        var std_dir: ?[]const u8 = null;
        var program_args: std.ArrayList([]const u8) = .empty;
        defer program_args.deinit(gpa);

        while (args.next()) |a| {
            if (std.mem.eql(u8, a, "--")) {
                while (args.next()) |prog_arg| {
                    try program_args.append(gpa, prog_arg);
                }
                break;
            } else if (std.mem.eql(u8, a, "--work-dir")) {
                work_dir = args.next() orelse {
                    try err.writeAll("missing value for --work-dir\n");
                    try err.flush();
                    return error.InvalidArgument;
                };
            } else if (std.mem.eql(u8, a, "--json")) {
                json = true;
            } else if (std.mem.eql(u8, a, "--std-dir")) {
                std_dir = args.next() orelse {
                    try err.writeAll("missing value for --std-dir\n");
                    try err.flush();
                    return error.InvalidArgument;
                };
            } else if (std.mem.eql(u8, a, "-h") or std.mem.eql(u8, a, "--help")) {
                try printRunHelp(out);
                return;
            } else if (std.mem.startsWith(u8, a, "-")) {
                try err.print("unknown run flag: {s}\n", .{a});
                try err.flush();
                return error.InvalidArgument;
            } else if (entry == null) {
                entry = a;
            } else {
                try err.writeAll("run accepts at most one entry path\n");
                try err.flush();
                return error.InvalidArgument;
            }
        }

        const entry_path = entry orelse try discoverEntryPathOrReport(gpa, err);
        const exe_path = try std.fmt.allocPrint(gpa, "{s}/run.out", .{work_dir});
        defer gpa.free(exe_path);
        std.fs.cwd().makePath(work_dir) catch {};
        var build_log: std.ArrayList(u8) = .empty;
        defer build_log.deinit(gpa);
        if (json) {
            try BackendDriver.buildExecutableFromEntryViaModules(gpa, build_log.writer(gpa), entry_path, work_dir, exe_path, .{ .std_dir = std_dir });
        } else {
            try BackendDriver.buildExecutableFromEntryViaModules(gpa, out, entry_path, work_dir, exe_path, .{ .std_dir = std_dir });
        }

        const child_argv = try gpa.alloc([]const u8, program_args.items.len + 1);
        defer gpa.free(child_argv);
        child_argv[0] = exe_path;
        for (program_args.items, 0..) |prog_arg, i| child_argv[i + 1] = prog_arg;

        var child = std.process.Child.init(child_argv, gpa);
        const term = try child.spawnAndWait();
        switch (term) {
            .Exited => |code| {
                if (json) {
                    try out.writeAll("{\"schema\":\"dyn-cli.v1\",\"command\":\"run\",\"entry\":\"");
                    try writeJsonEscaped(out, entry_path);
                    try out.writeAll("\",\"work_dir\":\"");
                    try writeJsonEscaped(out, work_dir);
                    try out.writeAll("\",\"exe\":\"");
                    try writeJsonEscaped(out, exe_path);
                    try out.print("\",\"exit_code\":{d},\"ok\":true,\"build_diagnostics\":", .{code});
                    try writeJsonLineArray(out, build_log.items);
                    try out.writeAll("}\n");
                    try out.flush();
                }
                std.process.exit(code);
            },
            else => {
                if (json) {
                    try out.writeAll("{\"schema\":\"dyn-cli.v1\",\"command\":\"run\",\"entry\":\"");
                    try writeJsonEscaped(out, entry_path);
                    try out.writeAll("\",\"work_dir\":\"");
                    try writeJsonEscaped(out, work_dir);
                    try out.writeAll("\",\"exe\":\"");
                    try writeJsonEscaped(out, exe_path);
                    try out.writeAll("\",\"ok\":false,\"error\":\"RunFailed\",\"build_diagnostics\":");
                    try writeJsonLineArray(out, build_log.items);
                    try out.writeAll("}\n");
                    try out.flush();
                }
                return error.RunFailed;
            },
        }
        return;
    }

    if (std.mem.eql(u8, cmd, "clean")) {
        var work_dir: []const u8 = ".dyn_build";
        var json = false;
        while (args.next()) |a| {
            if (std.mem.eql(u8, a, "--work-dir")) {
                work_dir = args.next() orelse {
                    try err.writeAll("missing value for --work-dir\n");
                    try err.flush();
                    return error.InvalidArgument;
                };
            } else if (std.mem.eql(u8, a, "--json")) {
                json = true;
            } else if (std.mem.eql(u8, a, "-h") or std.mem.eql(u8, a, "--help")) {
                try printCleanHelp(out);
                return;
            } else {
                try err.print("unknown clean flag: {s}\n", .{a});
                try err.flush();
                return error.InvalidArgument;
            }
        }

        std.fs.cwd().deleteTree(work_dir) catch |e| switch (e) {
            error.ProcessNotFound => {
                if (json) {
                    try out.writeAll("{\"schema\":\"dyn-cli.v1\",\"command\":\"clean\",\"work_dir\":\"");
                    try writeJsonEscaped(out, work_dir);
                    try out.writeAll("\",\"removed\":false,\"diagnostics\":[]}\n");
                } else {
                    try out.print("nothing to clean: {s}\n", .{work_dir});
                }
                try out.flush();
                return;
            },
            else => return e,
        };
        if (json) {
            try out.writeAll("{\"schema\":\"dyn-cli.v1\",\"command\":\"clean\",\"work_dir\":\"");
            try writeJsonEscaped(out, work_dir);
            try out.writeAll("\",\"removed\":true,\"diagnostics\":[]}\n");
        } else {
            try out.print("cleaned: {s}\n", .{work_dir});
        }
        try out.flush();
        return;
    }

    try err.print("unknown command: {s}\n\n", .{cmd});
    try printHelp(err);
    try err.flush();
    return error.InvalidArgument;
}

fn printHelp(writer: *std.Io.Writer) !void {
    try writer.writeAll(
        "dyn commands:\n" ++
            "  check [entry.dyn] [--std-dir dir]\n" ++
            "  build [entry.dyn] [-o out] [--emit-obj|--emit-asm] [--work-dir dir] [--std-dir dir]\n" ++
            "  run [entry.dyn] [--work-dir dir] [--std-dir dir] [--json] [-- arg ...]\n" ++
            "  clean [--work-dir dir]\n" ++
            "\n" ++
            "Use 'dyn help <command>' or '<command> --help' for details.\n" ++
            "If entry is omitted, compiler tries main.dyn or a single .dyn file in cwd.\n",
    );
    try writer.flush();
}

fn printCheckHelp(writer: *std.Io.Writer) !void {
    try writer.writeAll(
        "Usage: dyn check [entry.dyn] [--std-dir dir]\n" ++
            "\n" ++
            "Runs frontend analysis (module graph, symbols, resolver, semantic checks).\n" ++
            "\n" ++
            "Examples:\n" ++
            "  dyn check\n" ++
            "  dyn check app/main.dyn\n" ++
            "  dyn check app/main.dyn --std-dir ./std\n" ++
            "  dyn check app/main.dyn --json\n",
    );
    try writer.flush();
}

fn printBuildHelp(writer: *std.Io.Writer) !void {
    try writer.writeAll(
        "Usage: dyn build [entry.dyn] [options]\n" ++
            "\n" ++
            "Options:\n" ++
            "  -o <path>            Output path (default: a.out)\n" ++
            "  --emit-obj           Build object file\n" ++
            "  --emit-asm           Emit assembly file\n" ++
            "  --work-dir <dir>     Intermediate build directory (default: .dyn_build)\n" ++
            "  --std-dir <dir>      Std module root fallback for use \"std/...\"\n" ++
            "  --json               Print machine-readable build result\n" ++
            "\n" ++
            "Examples:\n" ++
            "  dyn build\n" ++
            "  dyn build app/main.dyn -o app.out\n" ++
            "  dyn build app/main.dyn --emit-obj -o app.o\n" ++
            "  dyn build app/main.dyn --emit-asm -o app.s\n" ++
            "  dyn build app/main.dyn --std-dir ./std\n" ++
            "  dyn build app/main.dyn --json\n",
    );
    try writer.flush();
}

fn printRunHelp(writer: *std.Io.Writer) !void {
    try writer.writeAll(
        "Usage: dyn run [entry.dyn] [--work-dir dir] [--std-dir dir] [--json] [-- arg ...]\n" ++
            "\n" ++
            "Builds and runs the program.\n" ++
            "\n" ++
            "Examples:\n" ++
            "  dyn run\n" ++
            "  dyn run app/main.dyn\n" ++
            "  dyn run app/main.dyn --work-dir out/dyn\n" ++
            "  dyn run app/main.dyn --std-dir ./std\n" ++
            "  dyn run app/main.dyn --json\n" ++
            "  dyn run app/main.dyn -- --name dyn --count 3\n",
    );
    try writer.flush();
}

fn printCleanHelp(writer: *std.Io.Writer) !void {
    try writer.writeAll(
        "Usage: dyn clean [--work-dir dir]\n" ++
            "\n" ++
            "Removes compiler intermediate artifacts directory.\n" ++
            "\n" ++
            "Examples:\n" ++
            "  dyn clean\n" ++
            "  dyn clean --work-dir out/dyn\n" ++
            "  dyn clean --json\n",
    );
    try writer.flush();
}

fn discoverEntryPath(allocator: std.mem.Allocator) ![]const u8 {
    _ = std.fs.cwd().statFile("main.dyn") catch {
        var dir = try std.fs.cwd().openDir(".", .{ .iterate = true });
        defer dir.close();
        var it = dir.iterate();
        var found: ?[]u8 = null;
        while (try it.next()) |ent| {
            if (ent.kind != .file) continue;
            if (!std.mem.endsWith(u8, ent.name, ".dyn")) continue;
            if (found != null) return error.AmbiguousEntry;
            found = try allocator.dupe(u8, ent.name);
        }
        return found orelse error.EntryNotFound;
    };
    return "main.dyn";
}

fn discoverEntryPathOrReport(allocator: std.mem.Allocator, err: *std.Io.Writer) ![]const u8 {
    return discoverEntryPath(allocator) catch |e| switch (e) {
        error.EntryNotFound => {
            try err.writeAll("entry not found: pass [entry.dyn], or create main.dyn in current directory\n");
            try err.flush();
            return error.EntryNotFound;
        },
        error.AmbiguousEntry => {
            try err.writeAll("ambiguous entry: pass [entry.dyn] when multiple .dyn files exist\n");
            try err.flush();
            return error.AmbiguousEntry;
        },
        else => return e,
    };
}

fn writeJsonEscaped(writer: *std.Io.Writer, s: []const u8) !void {
    for (s) |c| {
        switch (c) {
            '"' => try writer.writeAll("\\\""),
            '\\' => try writer.writeAll("\\\\"),
            '\n' => try writer.writeAll("\\n"),
            '\r' => try writer.writeAll("\\r"),
            '\t' => try writer.writeAll("\\t"),
            else => {
                if (c < 0x20) {
                    try writer.print("\\u{X:0>4}", .{@as(u16, c)});
                } else {
                    try writer.writeByte(c);
                }
            },
        }
    }
}

fn writeJsonLineArray(writer: *std.Io.Writer, text: []const u8) !void {
    try writer.writeByte('[');
    var first = true;
    var start: usize = 0;
    while (start < text.len) {
        var end = start;
        while (end < text.len and text[end] != '\n') : (end += 1) {}
        const line = text[start..end];
        if (line.len > 0) {
            if (!first) try writer.writeByte(',');
            first = false;
            try writer.writeByte('"');
            try writeJsonEscaped(writer, line);
            try writer.writeByte('"');
        }
        start = if (end < text.len and text[end] == '\n') end + 1 else end;
    }
    try writer.writeByte(']');
}
