const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    const mod = b.addModule("dyn", .{
        .root_source_file = b.path("src/root.zig"),
        .target = target,
    });
    mod.addSystemIncludePath(.{ .cwd_relative = "/usr/lib/llvm19/include" });

    const exe = b.addExecutable(.{
        .name = "dyn",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/main.zig"),
            .target = target,
            .optimize = optimize,
            .imports = &.{.{ .name = "dyn", .module = mod }},
        }),
    });
    exe.root_module.addSystemIncludePath(.{ .cwd_relative = "/usr/lib/llvm19/include" });
    b.installArtifact(exe);

    const run_step = b.step("run", "Run the compiler");
    const run_cmd = b.addRunArtifact(exe);
    run_cmd.step.dependOn(b.getInstallStep());
    if (b.args) |args| run_cmd.addArgs(args);
    run_step.dependOn(&run_cmd.step);

    const tests = b.addTest(.{ .root_module = mod });
    const run_tests = b.addRunArtifact(tests);
    const test_step = b.step("test", "Run tests");
    test_step.dependOn(&run_tests.step);

    addPassingE2E(b, exe, test_step, "assign", 42);
    addPassingE2E(b, exe, test_step, "arithmetic", 8);
    addPassingE2E(b, exe, test_step, "call", 36);
    addPassingE2E(b, exe, test_step, "locals", 36);
    addPassingE2E(b, exe, test_step, "modrem", 2);
    addPassingE2E(b, exe, test_step, "neg", 4);
    addPassingE2E(b, exe, test_step, "params", 42);
    addPassingE2E(b, exe, test_step, "ifexpr", 42);
    addPassingE2E(b, exe, test_step, "while", 5);
    addPassingE2E(b, exe, test_step, "u3", 5);
    addPassingE2E(b, exe, test_step, "struct_fields", 42);
    addPassingE2E(b, exe, test_step, "method", 42);
    addPassingE2E(b, exe, test_step, "enum_tag", 42);
    addPassingE2E(b, exe, test_step, "optional_unwrap", 42);
    addPassingE2E(b, exe, test_step, "error_or", 42);
    addPassingE2E(b, exe, test_step, "optional_or_null", 42);
    addPassingE2E(b, exe, test_step, "error_unwrap", 42);
    addPassingE2E(b, exe, test_step, "array_index", 42);
    addPassingE2E(b, exe, test_step, "slice_array", 42);
    addPassingE2E(b, exe, test_step, "slice_index", 42);
    addPassingE2E(b, exe, test_step, "string_literal", 42);
    addPassingE2E(b, exe, test_step, "for_range", 15);
    addPassingE2E(b, exe, test_step, "for_range_inclusive", 15);
    addPassingE2E(b, exe, test_step, "for_array", 42);
}

fn addPassingE2E(b: *std.Build, exe: *std.Build.Step.Compile, test_step: *std.Build.Step, name: []const u8, expected: u8) void {
    const src = b.fmt("tests/corpus/passing/{s}.dyn", .{name});
    const out = b.fmt("/tmp/dyn-e2e-{s}", .{name});
    const build_cmd = b.addRunArtifact(exe);
    build_cmd.step.dependOn(b.getInstallStep());
    build_cmd.addArgs(&.{ "build", src, "-o", out });
    const run_cmd = b.addSystemCommand(&.{out});
    run_cmd.step.dependOn(&build_cmd.step);
    run_cmd.expectExitCode(expected);
    test_step.dependOn(&run_cmd.step);
}
