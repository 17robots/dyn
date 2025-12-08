const std = @import("std");

pub fn main() !void {
    std.debug.print("Hello World\n", .{});
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa.deinit();
    const alloc = gpa.allocator();
    const options = options_from_args(alloc);
    _ = options;
}
const CompilerOptions = struct {
    command: []const u8,
    args: [] [] const u8,
    config_type: enum { debug, release, release_fast, release_safe } = .debug,
    optimization_level: u32 = 0,
    verbose: bool = false,
    target: Target = undefined,
    single_threaded: bool = false,
};
const Target = struct {
    arch: enum {},
    os: enum {},
    abi: enum {},
    cpu: enum {},
    extra_features: []enum {} = undefined,
};

fn options_from_args(alloc: std.mem.Allocator) CompilerOptions {
    const argv = try std.process.argsAlloc(alloc);
    defer std.process.argsFree(alloc, argv);
    if (argv.len <= 1) @panic("Expected command argument");
    const cmd = argv[1];
    const args = argv[2..];
    if (std.mem.eql(u8, cmd, "build")) {
    } else if(std.mem.eql(u8, cmd, "check")) {
    } else if(std.mem.eql(u8, cmd, "fmt")) {
    } else if(std.mem.eql(u8, cmd, "init")) {
    } else if(std.mem.eql(u8, cmd, "new")) {
    } else if(std.mem.eql(u8, cmd, "run")) {
    } else if(std.mem.eql(u8, cmd, "test")) {
    } else @panic("Unknown command");
}
