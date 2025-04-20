const std = @import("std");
const File = @import("file.zig");
const Diagnostic = @import("diagnostic.zig");
const Node = @import("ast.zig").Node;

const Symbol = struct { type: []const u8, val: []const u8, refs: usize, mut: bool, level: usize };
const TempSymbol = struct { type: ?*Node, val: *Node, refs: usize, mut: bool, level: usize };
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
    // initial check: make sure we have a program ast root
    if(s.n.* != .program) {
        s.diagnostic(.err, "Expected program ast root, got {any}", .{s.n.*});
        return;
    }
    // phase 1: collect global symbols of the file into a temp table before resolving
    var list = std.StringHashMap(.type).init(s.a);
    blk: for(s.n.*.program.declarations.items) |d| {
        if(d == .module) continue; // skip module declaration
        if(d != .declaration) {
            s.diagnostic(.err, "Expected declaration, got {any}", .{d});
            continue;
        } else {
            if(s.t.get(d.declaration.name.*.identifier.value)) |_| {
                s.diagnostic(.err, "Duplicate symbol {s}. Already defined.", .{d.declaration.name.*.identifier.value});
                continue :blk;
            } else list.put(d.declaration.name.identifier.value, .{ .level = 0, .mut = false, .refs = 1, .type = "unresolved", .val = "unresolved" });
        }
    }
    // phase 2: resolve global modules
}

fn diagnostic(s: *Checker, severity: Diagnostic.Severity, comptime fmt: []const u8, args: anytype) void {
    const msg = std.fmt.allocPrint(s.a, fmt, args) catch |e| @panic(@errorName(e));
    s.f.diagnostics.append(Diagnostic{ .filename = s.f.path, .severity = severity, .line = s.n.line, .col = s.n.col, .message = msg }) catch |e| @panic(@errorName(e));
}

