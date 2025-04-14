const std = @import("std");
const File = @import("file.zig");
const Diagnostic = @import("diagnostic.zig");
const Node = @import("ast.zig").Node;

const Symbol = struct { type: ?*Node, val: *Node, refs: usize, mut: bool, level: usize };
const SymbolTable = std.StringHashMap(Symbol);

const Checker = @This();

a: std.mem.Allocator,
f: *File,
n: *Node,
t: SymbolTable,

pub fn init(alloc: std.mem.Allocator, f: *File, n: *Node) Checker {
    return Checker{ .a = alloc, .f = f, .t = std.ArrayList(Symbol).init(alloc), .n = n };
}

pub fn run(s: *Checker) void {
    // load declaration symbols into symbol table
    if (s.n.* == .program) {
        for (s.n.program.declarations.items) |decl| {
            if (decl == .declaration) {
                s.t.put(decl.declaration.name.identifier.value, .{ .type = decl.declaration.type, .level = 0, .deps = std.ArrayList(*Node).init(s.a), .mut = false, .val = decl.declaration.val, .refs = 0 });
            } else s.diagnostic(.err, "Only declarations are allowed in global scope", .{});
        }
    } else s.diagnostic(.err, "Expected program, got {any}", .{s.n.*});
}

// steps for checking and symbol table construction
// 1. go through all members of the program declarations array, load a predefined symbol for them
// 2. go back through and fill in the details of each of them
// 3. go through and check all sub members of the program

fn diagnostic(s: *Checker, severity: Diagnostic.Severity, comptime fmt: []const u8, args: anytype) void {
    const msg = std.fmt.allocPrint(s.a, fmt, args) catch |e| @panic(@errorName(e));
    s.f.diagnostics.append(Diagnostic{ .filename = s.f.path, .severity = severity, .line = s.n.line, .col = s.n.col, .message = msg }) catch |e| @panic(@errorName(e));
}

fn append(a: *std.ArrayList(Symbol), n: Symbol) void {
    a.append(n) catch |e| @panic(@errorName(e));
}
