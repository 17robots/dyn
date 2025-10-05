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
pub fn process(s: *Compiler, mod: []const u8, step: enum { lex, parse, check }) !void {
    var main_module = try s.module_resolver.resolveModule(".", mod);
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
                for (a.type.program.declarations.items) |d| {
                    switch(d.type) {
                        .module => |m| std.debug.print("Module; {any}\n", .{m}),
                        .declaration => |decl| std.debug.print("Declaration; pub: {any}, mut: {any}, name: {any}, type: {any}, val: {any}\n", .{decl.pub_, decl.mut, decl.name, decl.type, decl.val}),
                        else => {}
                    }
                }
            }
        },
        .check => {
            try main_module.check(s.source_manager, s.diagnostics);
        },
    }
}
