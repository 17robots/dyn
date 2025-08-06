const std = @import("std");
const Lexer = @import("lexer.zig");
const Parser = @import("parser.zig");
const source = @import("source.zig");
const diagnostic = @import("diagnostic.zig");
const module = @import("module.zig");
const Compiler = @import("compiler.zig");

pub fn main() !void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const allocator = arena.allocator();
    var source_manager = source.SourceManager.init(allocator);
    var diagnostics = diagnostic.DiagnosticEmitter.init(allocator);
    var module_resolver = module.ModuleResolver.init(allocator, &source_manager, &diagnostics);
    var compiler = Compiler.init(allocator, &diagnostics, &source_manager, &module_resolver);
    try compiler.process_main(.parse);
}
