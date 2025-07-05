const std = @import("std");
const module = @import("module.zig");
const Node = @import("ast.zig").Node;
const Type = @import("types.zig").Type;
const File = @import("file.zig");
const Symbol = struct {
    name: []const u8,
    type: ?Type,
    mut: bool,
    val: struct {}, // adjust this later
    status: enum { unresolved, resolving, resolved },
    kind: enum {
        variable,
        function,
        @"enum",
        @"struct",
        @"error",
    },
    node: *Node,
};
const Scope = struct {
    symbols: std.StringHashMap(Symbol),
    type: ScopeType,
    label: ?[]const u8,
    const ScopeType = enum { function, global, @"while", @"for", @"if", block };
    fn init(allocator: std.mem.Allocator, t: ScopeType, label: ?[]const u8) Scope {
        return Scope{ .symbols = std.StringHashMap(Symbol).init(allocator), .type = t, .label = label };
    }
};
const Dependency = struct {
    module: *module.Module,
    status: enum { compiling, done, errored },
};
const Checker = @This();

a: std.mem.Allocator,
scopes: std.ArrayList(Scope), // last is most recent
dependencies: std.StringHashMap(Dependency),

pub fn init(alloc: std.mem.Allocator) Checker {
    return .{ .scopes = std.ArrayList(Scope).init(alloc), .a = alloc, .dependencies = std.StringHashMap(Dependency).init(alloc) };
}
pub fn check(s: *Checker, m: *module.Module) !void {
    // check assumes files have been parsed
    var global_scope = Scope.init(s.a, .global, null);
    for (m.files.items) |f| { // first pass to load
        for (f.root.?.program.declarations.items) |decl| {
            switch (decl) {
                .module => {}, // skip module declaration
                .declaration => |d| {
                    if (global_scope.symbols.get(d.name.*.identifier.value)) {} // duplicate symbol detected
                    global_scope.symbols.put(d.name.*.identifier.value, .{ .name = d.name.*.identifier.value, .type = null, .mut = false, .val = .{}, .status = .unresolved, .kind = .variable, .node = null });
                }, // this is the important part
                else => unreachable,
            }
        }
        if (f.diagnostics.items.len > 0) {} // we have checking errors
    }
    for (m.files.items) |f| { // second pass to resolve/infer types
        for (f.root.?.program.declarations.items) |decl| {
            switch (decl) {
                .module => {}, // skip module declaration
                .declaration => {}, // this is the important part
                else => unreachable,
            }
        }
        if (f.diagnostics.items.len > 0) {} // we have checking errors
    }
}
pub fn analyze(s: *Checker, node: Node, f: *File) !void {
    _ = s;
    _ = f;
    switch (node) {}
}

// things to check
// AST & Scoping
// - all nodes that should have children have them
// - check that binary ops have 2 ops and unary ops have 1
// - ensure literals are assigned to their respective types
// - ensure keywords arent used as identifiers
// - scope checking
//   - function params get added to scope in their block
//   - global scope items get added to top level scope and their order doesnt matter
// - type aliases are distinct entries in the symbol table and are their underlying type in type checking
// - type inference on untyped items (proper default types)
// - ensure types of values are compatible with an assigned type in a declaration
// - consider implicit conversions (include checking if result is larger than given size for ints)
// - do these on assignment too not just declaration
// - define which vals are allowed to be used with which operator and ensure all ops have their required types (+ needing numbers, == being same type on both sides, etc)
// - ensure only pointer types are pointer dereferenced
// - ensure only optional types are optional dereferenced
// - ensure only array types are array indexed
// - ensure array indexes are usize (or can be cast to usize) and can be known at compile time
// - ensure array indexes are within the bounds of the array
// - ensure function signature has all required arguments
// - ensure passed function args match parameter types
// - ensure member access (or member function call) is done on struct (or struct pointer), and that the member exists on the struct
// - ensure member function call is to a member function, not abstract function
// - if abstractly calling member function, ensure that the params include an instance of the struct
// - ensure enum and error variant are valid for given enum or error
// - ensure enum/error variants have all needed args and that args are correct type
// - ensure with nullish coalescing that the first var is ?T and that the default is T
// - ensure that functions being used as a type return a type
// - ensure comp stuff is figured out (thisll be a time)
// - anything after a return, continue, etc, then below is unreachable
// - break and continue must be in a loop
// - returns must return a val that matches the return val of the fn
// - passing a label to break needs to be valid and must have value that matches the type of the assignment
// - all errors must be handled, either by a try or a catch
// - try propagates error up so the function that it's used in must also return an error union that encompasses that error
// - ensure all allocated pointers are freed at the end of their scope
// - ensure pointers are not used after they are freed
// - ensure pointers are not freed multiple times
// - ensure frees cannot be called on null or undefined
// - ensure memory is initialized before it is read
// - ensure pointers to vars in smaller scopes are not returned (dangling pointers)
// - ensure all allocators have freed their memory by the end of the given scopes
// - ensure immutable vars are never reassigned
// - ensure mutable variables are reassigned
// - ensure immutable vars are never assigned to null or undefined
// - ensure exhaustive match branches
// - ensure all declared vars are used
