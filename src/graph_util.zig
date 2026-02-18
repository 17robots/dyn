const ModuleGraph = @import("module_graph.zig");

pub fn findFileIndex(graph: *ModuleGraph.Self, file_id: @import("source_manager.zig").FileId) ?u32 {
    var i: u32 = 0;
    while (i < graph.files.items.len) : (i += 1) {
        if (graph.files.items[i].file_id == file_id) return i;
    }
    return null;
}
