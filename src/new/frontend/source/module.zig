const std = @import("std");
const ast = @import("../ast.zig");
const symbol = @import("../../middle/symbols.zig");

const ModuleId = u32;

pub const Module = struct {
    id: ModuleId,
    name: []const u8,
    path: []const u8,
    source_ids: std.ArrayList(u32),
    ast: ast.AST,
    dependencies: std.ArrayList(ModuleId),
    symbol_table: *symbol.SymbolTable,
    pub fn init(allocator: std.mem.Allocator, id: ModuleId, name: []const u8, path: []const u8) Module {
        const self = Module{ .id = id, .name = name, .path = path, .source_ids = .empty, .ast = ast.AST.init(allocator), .dependencies = .empty, .symbol_table = allocator.create(symbol.SymbolTable) };
        self.symbol_table.* = symbol.SymbolTable.init();
        return self;
    }
    pub fn deinit(self: *Module, allocator: std.mem.Allocator) void {
        self.source_ids.deinit(allocator);
        self.ast.deinit();
        self.dependencies.deinit(allocator);
        self.symbol_table.deinit();
        allocator.destroy(self.symbol_table);
    }
    pub fn add_source_file(self: *Module, allocator: std.mem.Allocator, source_id: u32) void {
        self.source_ids.append(allocator, source_id) catch {};
    }
    pub fn add_dependency(self: *Module, allocator: std.mem.Allocator, dep_id: ModuleId) void {
        self.dependencies.append(allocator, dep_id) catch {};
    }
};
pub const ModuleGraph = struct {
    allocator: std.mem.Allocator,
    modules: std.AutoArrayHashMap(ModuleId, Module),
    name_to_module: std.StringArrayHashMap(ModuleId),
    next_id: ModuleId = 1,
    pub fn init(allocator: std.mem.Allocator) ModuleGraph {
        return .{ .allocator = allocator, .modules = std.AutoArrayHashMap(ModuleId, Module).init(allocator), .name_to_module = std.StringArrayHashMap(ModuleId).init(allocator) };
    }
    pub fn deinit(self: *ModuleGraph) void {
        var it = self.modules.iterator();
        while (it.next()) |n| n.value_ptr.deinit(self.allocator);
        self.modules.deinit();
        self.name_to_module.deinit();
    }
    pub fn create_module(self: *ModuleGraph, name: []const u8, path: []const u8) ModuleId {
        const id = self.next_id;
        self.next_id += 1;
        const module = Module.init(self.allocator, id, name, path);
        self.modules.put(id, module) catch {};
        self.name_to_module.put(name, id) catch {};
        return id;
    }
    pub fn get_module(self: ModuleGraph, id: ModuleId) ?*Module {
        return self.modules.getPtr(id);
    }
    pub fn find_module_by_name(self: *ModuleGraph, name: []const u8) ?ModuleId {
        return self.name_to_module.get(name);
    }
    pub fn resolve_import_path(self: ModuleGraph, importer_path: []const u8, import_path: []const u8) ?ModuleId {
        _ = self;
        _ = importer_path;
        _ = import_path;
    }
};
