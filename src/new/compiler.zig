const std = @import("std");
const frontend = @import("frontend");
const middle = @import("middle");
const backend = @import("backend");
const linker = @import("linker");
const SourceManager = @import("frontend/source/manager.zig").SourceManager;
const ModuleGraph = @import("frontend/source/module.zig").ModuleGraph;

pub const Compiler = struct {
    allocator: std.mem.Allocator,
    source_manager: SourceManager,
};
