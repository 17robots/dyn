const std = @import("std");

// TODO: we need to make this so that cli stuff works please and thank you future me, mainly the cli parsing into args and options so that we can determine what's what

pub fn main() !void {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa.deinit();
    const alloc = gpa.allocator();
    const argv = try std.process.argsAlloc(alloc);
    defer std.process.argsFree(alloc, argv);
    const opts = options_from_args(argv) catch |e| {
        switch (e) {
            error.NoCommand => {
                print_usage("");
                return;
            },
        }
    };
    var compiler = Compiler.init(alloc, opts);
    compiler.compile();
}
const CLI = struct {
    root: Command,
    pub fn parse(argv: [][:0]u8) void { }
};
const Command = struct {
    name: []const u8,
    description: []const u8,
    usage: []const u8,
    arguments: []Argument,
    options: []Option,
    subcommands: []*Command,
    pub fn print_usage(s: *Command) void {
        std.debug.print("{s}:\t{s:>10}\n", .{s.name});
        print_separator();
        std.debug.print("Usage:\t{s:>10}\n", .{s.usage});
        if (s.subcommands.len > 0) {
            std.debug.print("Available commands:\n", .{});
            for (s.subcommands) |subcommand| {
                std.debug.print("{s}\t{s:>10}\n", .{ subcommand.name, subcommand.description });
            }
        }
        if (s.arguments.len > 0) {
            std.debug.print("Available Flags:\n", .{});
            for (s.arguments) |a| {
                std.debug.print("{s}\t{s:>10}", .{ a.name, a.description });
            }
        }
        if (s.options.len > 0) {
            std.debug.print("Available Options:\n", .{});
            for (s.options) |o| {
                std.debug.print("--{s}", .{o.long});
                if (o.short) |short| std.debug.print(", -{s}", .{short});
                std.debug.print("\n\t{s}", .{o.description});
            }
        }
    }
};
const Argument = struct {
    name: []const u8,
    description: []const u8,
};
const Option = struct {
    long: []const u8,
    short: ?[]const u8,
    description: []const u8,
    default: []const u8,
};
const Compiler = struct {
    options: CompilerOptions,
    allocator: std.mem.Allocator,
    pub fn init(allocator: std.mem.Allocator, options: CompilerOptions) Compiler {
        return .{ .allocator = allocator, .options = options };
    }
    pub fn compile(s: *Compiler) void {
        print_usage(s.options.command);
        std.debug.print("We are compiling\n", .{});
    }
};
const CompilerOptions = struct {
    command: []const u8,
    args: [][:0]u8,
    config_type: enum { debug, release, release_fast, release_safe } = .debug,
    optimization_level: u32 = 0,
    verbose: bool = false,
    target: Target = read_target(),
    single_threaded: bool = false,
};
const Target = struct {
    arch: enum {},
    os: enum {},
    abi: enum {},
    cpu: enum {},
    extra_features: []enum {} = undefined,
};
fn print_separator() void {
    std.debug.print("---------\n", .{});
}
fn print_usage(subcommand: []const u8) void {
    if (std.mem.eql(u8, subcommand, "build")) {
        std.debug.print("Build:\t{s:>10}\n", .{"Build a project"});
        print_separator();
        std.debug.print("Usage:\tdyn build [project_dir]\n", .{});
        std.debug.print("Available Flags:\n", .{});
    } else if (std.mem.eql(u8, subcommand, "fmt")) {
        std.debug.print("Format:\t{s:>10}\n", .{"Format a project"});
        print_separator();
        std.debug.print("Usage:\tdyn fmt [project_dir]\n", .{});
        std.debug.print("Available Flags:\n", .{});
    } else if (std.mem.eql(u8, subcommand, "init")) {
        std.debug.print("Init:\t{s:>10}\n", .{"Init a project in current directory"});
        print_separator();
        std.debug.print("Usage:\tdyn init\n", .{});
        std.debug.print("Available Flags:\n", .{});
    } else if (std.mem.eql(u8, subcommand, "new")) {
        std.debug.print("New:\tCreate a project in a new directory\n", .{});
        print_separator();
        std.debug.print("Usage:\tdyn new [options]\n", .{});
        std.debug.print("Available Flags:\n", .{});
    } else if (std.mem.eql(u8, subcommand, "run")) {
        std.debug.print("Run:\t Build and run a project\n", .{});
        print_separator();
        std.debug.print("Usage:\tdyn run [options]\n", .{});
        std.debug.print("Available Flags:\n", .{});
    } else if (std.mem.eql(u8, subcommand, "test")) {
        std.debug.print("Test:\t Build and run tests for a project\n", .{});
        print_separator();
        std.debug.print("Usage:\tdyn test [options]\n", .{});
        std.debug.print("Available flags:\n", .{});
    } else {
        std.debug.print("Dyn Help\n", .{});
        print_separator();
        std.debug.print("Usage:\tdyn [command] [options]\n", .{});
        std.debug.print("Available Commands:\n", .{});
        std.debug.print("help\tshow this help\n", .{});
        std.debug.print("fmt\tformat files in directory\n", .{});
        std.debug.print("init\tcreate a new project in the current directory\n", .{});
        std.debug.print("new\tcreate a new project in a new directory\n", .{});
        std.debug.print("run\trun current project\n", .{});
        std.debug.print("test\ttest current project\n", .{});
    }
    std.debug.print("Global options:\n", .{});
    std.debug.print("- help\tshow help for given command\n", .{});
}
fn options_from_args(args: [][:0]u8) !CompilerOptions {
    if (args.len <= 1) return error.NoCommand;
    return .{
        .command = args[1],
        .args = args[2..],
    };
}

fn read_target() Target {
    return undefined;
}
