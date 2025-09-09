const std = @import("std");
const diagnostic = @import("diagnostic.zig");
const source = @import("source.zig");
const module = @import("module.zig");

const Compiler = @This();

allocator: std.mem.Allocator,
diagnostics: *diagnostic.DiagnosticEmitter,
source_manager: *source.SourceManager,
module_resolver: *module.ModuleResolver,

pub fn init(allocator: std.mem.Allocator, diagnostics: *diagnostic.DiagnosticEmitter, source_manager: *source.SourceManager, module_resolver: *module.ModuleResolver) Compiler {
    return Compiler{ .allocator = allocator, .diagnostics = diagnostics, .source_manager = source_manager, .module_resolver = module_resolver };
}

pub fn process_main(s: *Compiler, step: enum { lex, parse, check }) !void {
    var main_module = try s.module_resolver.resolveModule(".", "main");
    switch (step) {
        .lex => {
            const toks = try main_module.lex(s.source_manager, s.diagnostics);
            for (toks.items) |t| std.debug.print("Tok: {any}\n", .{t});
        },
        .parse => {
            try main_module.parse(s.source_manager, s.diagnostics);
            if (s.diagnostics.err_count > 0) {
                s.diagnostics.print_all(s.source_manager);
                return;
            }
            std.debug.print("We have: {any} valid asts\n", .{main_module.asts.items.len});
            for (main_module.asts.items) |a| {
                for (a.type.program.declarations.items) |d| std.debug.print("Debug: {any}\n", .{d});
            }
        },
        .check => {},
    }
}
