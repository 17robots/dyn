const std = @import("std");
const ast = @import("ast.zig");
const Module = @import("module.zig").Module;
const ModuleResolver = @import("module.zig").ModuleResolver;
const types = @import("types.zig");
const Visitor = @import("visitor.zig");

const Symbol = struct {
    name: []const u8,
    type: *types.Type,
    node: *ast.Node,
};

pub const Scope = struct {
    parent: ?*Scope,
    symbols: std.StringHashMap(Symbol),

    pub fn init(allocator: std.mem.Allocator, parent: ?*Scope) Scope {
        return .{
            .parent = parent,
            .symbols = std.StringHashMap(Symbol).init(allocator),
        };
    }

    pub fn lookup(self: *const Scope, name: []const u8) ?Symbol {
        if (self.symbols.get(name)) |symbol| {
            return symbol;
        }
        if (self.parent) |p| {
            return p.lookup(name);
        }
        return null;
    }
};

const Checker = @This();

const ModuleNode = struct {
    module: *Module,
    status: enum { unvisited, visiting, visited } = .unvisited,
    dependencies: std.ArrayList(*ModuleNode),
    scope: Scope,
};

allocator: std.mem.Allocator,
module_resolver: ModuleResolver,
module_graph: std.StringHashMap(*ModuleNode),
current_module: ?*ModuleNode,
current_scope: *Scope,
visitor: Visitor,

pub fn init(allocator: std.mem.Allocator) !Checker {
    var self = Checker{
        .allocator = allocator,
        .module_resolver = ModuleResolver.init(allocator),
        .module_graph = std.StringHashMap(*ModuleNode).init(allocator),
        .current_module = null,
        .current_scope = undefined,
        .visitor = Visitor{
            .visit_fn = visit,
        },
    };

    const global_scope = try self.allocator.create(Scope);
    global_scope.* = Scope.init(self.allocator, null);
    self.current_scope = global_scope;

    try self.populate_global_scope();

    return self;
}

fn populate_global_scope(self: *Checker) !void {
    try self.current_scope.symbols.put("i32", Symbol{
        .name = "i32",
        .type = try self.allocator.create(types.Type),
        .node = undefined,
    });
    if ((self.current_scope.symbols.get("i32"))) |symbol| {
        symbol.type.* = types.Type{ .Int = .{ .is_signed = true, .width = 32 } };
    }
}

pub fn check_program(self: *Checker, root_module: *Module) !void {
    _ = try self.resolve_module(root_module, ".");
    var it = self.module_graph.valueIterator();
    while (it.next()) |module_node| {
        try self.check_module(module_node.*);
    }
}

fn check_module(self: *Checker, module_node: *ModuleNode) !void {
    if (module_node.status != .unvisited) return;
    module_node.status = .visiting;

    for (module_node.dependencies.items) |dep| {
        try self.check_module(dep);
    }

    self.current_module = module_node;
    self.current_scope = &module_node.scope;

    for (module_node.module.files.items) |file| {
        if (file.root) |ast_node| {
            try self.visitor.walk(ast_node);
        }
    }

    module_node.status = .visited;
}

fn open_scope(self: *Checker) void {
    const new_scope = self.allocator.create(Scope) catch @panic("OOM");
    new_scope.* = Scope.init(self.allocator, self.current_scope);
    self.current_scope = new_scope;
}

fn close_scope(self: *Checker) void {
    self.current_scope = self.current_scope.parent orelse @panic("bad scope");
}

const UseFinder = struct {
    allocator: std.mem.Allocator,
    checker: *Checker,
    dependencies: std.ArrayList([]const u8),
    visitor: Visitor,

    fn visit(self: *Visitor, node: ast.Node) !void {
        const finder: *UseFinder = @fieldParentPtr("visitor", self);
        switch (node) {
            .use => |n| {
                try finder.dependencies.append(n.path.literal.val);
            },
            else => try finder.visitor.visit(node),
        }
    }
};

fn resolve_module(self: *Checker, module: *Module, calling_path: []const u8) !*ModuleNode {
    if (self.module_graph.get(module.name)) |node| return node;
    const module_node = try self.allocator.create(ModuleNode);
    module_node.* = .{
        .module = module,
        .dependencies = std.ArrayList(*ModuleNode).init(self.allocator),
        .scope = Scope.init(self.allocator, null),
    };
    try self.module_graph.put(module.name, module_node);

    for (module.files.items) |file| {
        if (file.root) |ast_node| {
            var use_finder = UseFinder{
                .allocator = self.allocator,
                .checker = self,
                .dependencies = std.ArrayList([]const u8).init(self.allocator),
                .visitor = Visitor{
                    .visit_fn = UseFinder.visit,
                },
            };
            try use_finder.visitor.walk(ast_node);
            for (use_finder.dependencies.items) |dep_path| {
                var dep_module = try self.module_resolver.resolveModule(calling_path, dep_path);
                const dep_node = try self.resolve_module(&dep_module, dep_path);
                try module_node.dependencies.append(dep_node);
            }
        }
    }

    return module_node;
}

fn visit(self: *Visitor, node: ast.Node) !void {
    const checker: *Checker = @fieldParentPtr("visitor", self);
    try checker.visitor.visit(node);
    switch (node) {
        .declaration => |n| {
            const name = n.name.identifier.value;
            const value_type = try checker.check_expression(n.val.*);

            var decl_type = value_type;
            if (n.type) |type_node| {
                const specified_type = try checker.resolve_type_node(type_node.*);
                if (!types.Type.eql(value_type.*, specified_type.*)) {
                    @panic("type mismatch");
                }
                decl_type = specified_type;
            }

            try checker.current_scope.symbols.put(name, Symbol{
                .name = name,
                .type = decl_type,
                .node = &node,
            });
        },
        .if_statement, .while_statement, .for_statement => {
            try checker.visitor.visit(node);
        },
        else => {
            _ = try checker.check_expression(node);
        },
    }
}

fn check_expression(self: *Checker, node: ast.Node) !*types.Type {
    return switch (node) {
        .use => |n| {
            const path = n.path.literal.val;
            var used_module = try self.module_resolver.resolveModule(".", path);
            const module_node = try self.resolve_module(&used_module, path);
            const mod_lit = try self.allocator.create(types.ModuleLit);
            mod_lit.* = .{
                .name = module_node.module.name,
                .scope = &module_node.scope,
            };
            const ptr = try self.allocator.create(types.Type);
            ptr.* = types.Type{ .Module = mod_lit };
            return ptr;
        },
        // ... (other cases from before) ...
        else => self.resolve_type_node(node),
    };
}

fn resolve_type_node(self: *Checker, node: ast.Node) !*types.Type {
    _ = self;
    _ = node;
    return error.What;
    // ... (implementation from before) ...
}
