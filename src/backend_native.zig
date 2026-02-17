const std = @import("std");
const Ir = @import("ir.zig");

pub const Target = enum {
    linux_x86_64,
};

pub const BackendError = error{
    MissingMain,
    UnsupportedIr,
    LinkFailed,
    AssembleFailed,
};

pub fn lowerMainExitCode(program: Ir.Program) BackendError!i64 {
    const main_index = findMainIndex(program) orelse return error.MissingMain;
    if (program.global_count > 256) return error.UnsupportedIr;
    var state = RuntimeState{};
    return runFunction(program, main_index, &.{}, &state) catch return error.UnsupportedIr;
}

pub fn emitAssembly(target: Target, program: Ir.Program, writer: anytype) !void {
    switch (target) {
        .linux_x86_64 => {
            const code = try lowerMainExitCode(program);
            try writer.writeAll(
                ".global _start\n" ++
                    ".text\n" ++
                    "_start:\n" ++
                    "    mov $60, %rax\n",
            );
            try writer.print("    mov ${d}, %rdi\n", .{code});
            try writer.writeAll("    syscall\n");
        },
    }
}

pub fn emitAssemblyDirect(target: Target, program: Ir.Program, writer: anytype) !void {
    switch (target) {
        .linux_x86_64 => try emitAssemblyDirectLinuxX64Ex(program, writer, "u0", true),
    }
}

fn emitAssemblyDirectLinuxX64(program: Ir.Program, writer: anytype) !void {
    return emitAssemblyDirectLinuxX64Ex(program, writer, "u0", true);
}

fn emitAssemblyDirectLinuxX64Ex(program: Ir.Program, writer: anytype, unit_prefix: []const u8, include_entry: bool) !void {
    const main_index = if (include_entry) (findMainIndex(program) orelse return error.MissingMain) else 0;
    try writer.writeAll(".text\n");
    if (include_entry) {
        try writer.writeAll(".global _start\n_start:\n");
        const main_name = program.functions[main_index].name;
        try writer.print("    call {s}\n", .{main_name});
        try writer.writeAll("    mov %rax, %rdi\n    mov $60, %rax\n    syscall\n");
    }

    if (program.rodata_strings.len > 0) {
        try writer.writeAll(".section .rodata\n");
        for (program.rodata_strings, 0..) |s, i| {
            try writer.print("{s}_str_{d}:\n    .asciz \"", .{ unit_prefix, i });
            for (s.bytes) |b| {
                switch (b) {
                    '"' => try writer.writeAll("\\\""),
                    '\\' => try writer.writeAll("\\\\"),
                    '\n' => try writer.writeAll("\\n"),
                    '\r' => try writer.writeAll("\\r"),
                    '\t' => try writer.writeAll("\\t"),
                    else => if (b >= 32 and b <= 126) {
                        try writer.writeByte(b);
                    } else {
                        try writer.print("\\x{X:0>2}", .{b});
                    },
                }
            }
            try writer.writeAll("\"\n");
        }
        try writer.writeAll(".text\n");
    }

    if (program.global_count > 0) {
        try writer.writeAll(".section .bss\n");
        try writer.print("{s}_globals:\n    .zero {d}\n", .{ unit_prefix, program.global_count * 8 });
        try writer.writeAll(".text\n");
    }

    try emitRuntimeAllocatorSymbols(writer);

    for (program.functions, 0..) |f, fi| {
        if (try emitStdIntrinsicFunction(writer, f.name)) continue;
        try writer.print(".global {s}\n{s}:\n", .{ f.name, f.name });
        try writer.writeAll("    push %rbp\n    mov %rsp, %rbp\n");
        if (f.local_count > 0) {
            const local_bytes = f.local_count * 8;
            const aligned_local_bytes = ((local_bytes + 15) / 16) * 16;
            try writer.print("    sub ${d}, %rsp\n", .{aligned_local_bytes});
        }

        var pi: u32 = 0;
        while (pi < f.param_count) : (pi += 1) {
            const src_off: u32 = 16 + 8 * (f.param_count - 1 - pi);
            const dst_off: u32 = (pi + 1) * 8;
            try writer.print("    mov {d}(%rbp), %rax\n", .{src_off});
            try writer.print("    mov %rax, -{d}(%rbp)\n", .{dst_off});
        }

        for (f.instructions, 0..) |ins, i| {
            try writer.print("fn_{d}_L{d}:\n", .{ fi, i });
            switch (ins) {
                .push_const_i64 => |v| {
                    try writer.print("    mov ${d}, %rax\n", .{v});
                    try writer.writeAll("    push %rax\n");
                },
                .push_rodata_ptr => |idx| {
                    if (idx >= program.rodata_strings.len) return error.UnsupportedIr;
                    try writer.print("    lea {s}_str_{d}(%rip), %rax\n", .{ unit_prefix, idx });
                    try writer.writeAll("    push %rax\n");
                },
                .load_local => |slot| {
                    const off = (slot + 1) * 8;
                    try writer.print("    mov -{d}(%rbp), %rax\n", .{off});
                    try writer.writeAll("    push %rax\n");
                },
                .store_local => |slot| {
                    const off = (slot + 1) * 8;
                    try writer.writeAll("    pop %rax\n");
                    try writer.print("    mov %rax, -{d}(%rbp)\n", .{off});
                },
                .addr_of_local => |slot| {
                    const off = (slot + 1) * 8;
                    try writer.print("    lea -{d}(%rbp), %rax\n", .{off});
                    try writer.writeAll("    push %rax\n");
                },
                .addr_of_global => |slot| {
                    if (slot >= program.global_count) return error.UnsupportedIr;
                    try writer.print("    lea {s}_globals+{d}(%rip), %rax\n", .{ unit_prefix, slot * 8 });
                    try writer.writeAll("    push %rax\n");
                },
                .ptr_offset_slots => |slots| {
                    try writer.print("    pop %rax\n    add ${d}, %rax\n    push %rax\n", .{slots * 8});
                },
                .load_ptr => {
                    try writer.writeAll("    pop %rcx\n    mov (%rcx), %rax\n    push %rax\n");
                },
                .store_ptr => {
                    try writer.writeAll("    pop %rax\n    pop %rcx\n    mov %rax, (%rcx)\n    push %rax\n");
                },
                .unwrap_optional => {
                    try writer.writeAll("    pop %rax\n    cmp $0, %rax\n");
                    try writer.print("    jne fn_{d}_L{d}_unwrap_optional_ok\n", .{ fi, i });
                    try writer.writeAll("    mov $60, %rax\n    mov $2, %rdi\n    syscall\n");
                    try writer.print("fn_{d}_L{d}_unwrap_optional_ok:\n", .{ fi, i });
                    try writer.writeAll("    push %rax\n");
                },
                .unwrap_error => {
                    try writer.writeAll("    pop %rax\n    cmp $0, %rax\n");
                    try writer.print("    jne fn_{d}_L{d}_unwrap_error_ok\n", .{ fi, i });
                    try writer.writeAll("    mov $60, %rax\n    mov $3, %rdi\n    syscall\n");
                    try writer.print("fn_{d}_L{d}_unwrap_error_ok:\n", .{ fi, i });
                    try writer.writeAll("    push %rax\n");
                },
                .pop => try writer.writeAll("    add $8, %rsp\n"),
                .add => try writer.writeAll("    pop %rcx\n    pop %rax\n    add %rcx, %rax\n    push %rax\n"),
                .sub => try writer.writeAll("    pop %rcx\n    pop %rax\n    sub %rcx, %rax\n    push %rax\n"),
                .mul => try writer.writeAll("    pop %rcx\n    pop %rax\n    imul %rcx, %rax\n    push %rax\n"),
                .div => try writer.writeAll("    pop %rcx\n    pop %rax\n    cqo\n    idiv %rcx\n    push %rax\n"),
                .mod => try writer.writeAll("    pop %rcx\n    pop %rax\n    cqo\n    idiv %rcx\n    push %rdx\n"),
                .eq => try writer.writeAll("    pop %rcx\n    pop %rax\n    cmp %rcx, %rax\n    sete %al\n    movzbq %al, %rax\n    push %rax\n"),
                .neq => try writer.writeAll("    pop %rcx\n    pop %rax\n    cmp %rcx, %rax\n    setne %al\n    movzbq %al, %rax\n    push %rax\n"),
                .lt => try writer.writeAll("    pop %rcx\n    pop %rax\n    cmp %rcx, %rax\n    setl %al\n    movzbq %al, %rax\n    push %rax\n"),
                .lte => try writer.writeAll("    pop %rcx\n    pop %rax\n    cmp %rcx, %rax\n    setle %al\n    movzbq %al, %rax\n    push %rax\n"),
                .gt => try writer.writeAll("    pop %rcx\n    pop %rax\n    cmp %rcx, %rax\n    setg %al\n    movzbq %al, %rax\n    push %rax\n"),
                .gte => try writer.writeAll("    pop %rcx\n    pop %rax\n    cmp %rcx, %rax\n    setge %al\n    movzbq %al, %rax\n    push %rax\n"),
                .jump => |t| try writer.print("    jmp fn_{d}_L{d}\n", .{ fi, t }),
                .jump_if_false => |t| {
                    try writer.writeAll("    pop %rax\n    cmp $0, %rax\n");
                    try writer.print("    je fn_{d}_L{d}\n", .{ fi, t });
                },
                .call => |c| {
                    switch (c.target) {
                        .internal_index => |idx| try writer.print("    call {s}\n", .{program.functions[idx].name}),
                        .external_symbol => |ex| try writer.print("    call {s}\n", .{ex.name}),
                    }
                    if (c.arg_count > 0) {
                        try writer.print("    add ${d}, %rsp\n", .{c.arg_count * 8});
                    }
                    try writer.writeAll("    push %rax\n");
                },
                .ret => {
                    try writer.writeAll("    pop %rax\n    mov %rbp, %rsp\n    pop %rbp\n    ret\n");
                },
            }
        }
        try writer.print("fn_{d}_L{d}:\n", .{ fi, f.instructions.len });
        try writer.writeAll("    mov $0, %rax\n    mov %rbp, %rsp\n    pop %rbp\n    ret\n");
    }
}

fn emitRuntimeAllocatorSymbols(writer: anytype) !void {
    try writer.writeAll(
        "__dyn_os_alloc:\n" ++
            "    push %rbp\n" ++
            "    mov %rsp, %rbp\n" ++
            "    mov 24(%rbp), %rsi\n" ++
            "    cmp $0, %rsi\n" ++
            "    jle .Ldyn_alloc_fail\n" ++
            "    mov $9, %rax\n" ++
            "    xor %rdi, %rdi\n" ++
            "    mov $3, %rdx\n" ++
            "    mov $34, %r10\n" ++
            "    mov $-1, %r8\n" ++
            "    xor %r9, %r9\n" ++
            "    syscall\n" ++
            "    cmp $0, %rax\n" ++
            "    jl .Ldyn_alloc_fail\n" ++
            "    pop %rbp\n" ++
            "    ret\n" ++
            ".Ldyn_alloc_fail:\n" ++
            "    xor %rax, %rax\n" ++
            "    pop %rbp\n" ++
            "    ret\n" ++
            "__dyn_os_free:\n" ++
            "    push %rbp\n" ++
            "    mov %rsp, %rbp\n" ++
            "    mov 32(%rbp), %rdi\n" ++
            "    mov 24(%rbp), %rsi\n" ++
            "    cmp $0, %rdi\n" ++
            "    je .Ldyn_free_ret\n" ++
            "    cmp $0, %rsi\n" ++
            "    jle .Ldyn_free_ret\n" ++
            "    mov $11, %rax\n" ++
            "    syscall\n" ++
            ".Ldyn_free_ret:\n" ++
            "    xor %rax, %rax\n" ++
            "    pop %rbp\n" ++
            "    ret\n" ++
            "__dyn_os_realloc:\n" ++
            "    push %rbp\n" ++
            "    mov %rsp, %rbp\n" ++
            "    sub $8, %rsp\n" ++
            "    mov 48(%rbp), %rdi\n" ++
            "    mov 40(%rbp), %r8\n" ++
            "    mov 24(%rbp), %r9\n" ++
            "    cmp $0, %r9\n" ++
            "    jle .Ldyn_realloc_new_zero\n" ++
            "    cmp $0, %rdi\n" ++
            "    je .Ldyn_realloc_alloc_only\n" ++
            "    mov $9, %rax\n" ++
            "    xor %rdi, %rdi\n" ++
            "    mov %r9, %rsi\n" ++
            "    mov $3, %rdx\n" ++
            "    mov $34, %r10\n" ++
            "    mov $-1, %r8\n" ++
            "    xor %r9, %r9\n" ++
            "    syscall\n" ++
            "    cmp $0, %rax\n" ++
            "    jl .Ldyn_realloc_fail\n" ++
            "    mov %rax, -8(%rbp)\n" ++
            "    mov 40(%rbp), %rcx\n" ++
            "    mov 24(%rbp), %rdx\n" ++
            "    cmp %rdx, %rcx\n" ++
            "    cmovg %rdx, %rcx\n" ++
            "    cmp $0, %rcx\n" ++
            "    jle .Ldyn_realloc_skip_copy\n" ++
            "    mov 48(%rbp), %rsi\n" ++
            "    mov -8(%rbp), %rdi\n" ++
            "    cld\n" ++
            "    rep movsb\n" ++
            ".Ldyn_realloc_skip_copy:\n" ++
            "    mov 40(%rbp), %rsi\n" ++
            "    cmp $0, %rsi\n" ++
            "    jle .Ldyn_realloc_ret_new\n" ++
            "    mov $11, %rax\n" ++
            "    mov 48(%rbp), %rdi\n" ++
            "    syscall\n" ++
            ".Ldyn_realloc_ret_new:\n" ++
            "    mov -8(%rbp), %rax\n" ++
            "    add $8, %rsp\n" ++
            "    pop %rbp\n" ++
            "    ret\n" ++
            ".Ldyn_realloc_alloc_only:\n" ++
            "    mov $9, %rax\n" ++
            "    xor %rdi, %rdi\n" ++
            "    mov 24(%rbp), %rsi\n" ++
            "    mov $3, %rdx\n" ++
            "    mov $34, %r10\n" ++
            "    mov $-1, %r8\n" ++
            "    xor %r9, %r9\n" ++
            "    syscall\n" ++
            "    cmp $0, %rax\n" ++
            "    jl .Ldyn_realloc_fail\n" ++
            "    add $8, %rsp\n" ++
            "    pop %rbp\n" ++
            "    ret\n" ++
            ".Ldyn_realloc_new_zero:\n" ++
            "    cmp $0, %rdi\n" ++
            "    je .Ldyn_realloc_fail\n" ++
            "    cmp $0, %r8\n" ++
            "    jle .Ldyn_realloc_fail\n" ++
            "    mov $11, %rax\n" ++
            "    mov %r8, %rsi\n" ++
            "    syscall\n" ++
            ".Ldyn_realloc_fail:\n" ++
            "    xor %rax, %rax\n" ++
            "    add $8, %rsp\n" ++
            "    pop %rbp\n" ++
            "    ret\n",
    );
}

fn emitStdIntrinsicFunction(writer: anytype, name: []const u8) !bool {
    if (std.mem.eql(u8, name, "mpage_allocator_alloc") or std.mem.eql(u8, name, "mheap_alloc") or std.mem.eql(u8, name, "mmem_alloc") or std.mem.eql(u8, name, "mallocator_alloc")) {
        try writer.print(
            ".global {s}\n{s}:\n" ++
                "    push %rbp\n" ++
                "    mov %rsp, %rbp\n" ++
                "    mov 24(%rbp), %rax\n" ++
                "    push %rax\n" ++
                "    mov 16(%rbp), %rax\n" ++
                "    push %rax\n" ++
                "    call __dyn_os_alloc\n" ++
                "    add $16, %rsp\n" ++
                "    mov %rbp, %rsp\n" ++
                "    pop %rbp\n" ++
                "    ret\n",
            .{ name, name },
        );
        return true;
    }
    if (std.mem.eql(u8, name, "mpage_allocator_free") or std.mem.eql(u8, name, "mheap_free") or std.mem.eql(u8, name, "mmem_free") or std.mem.eql(u8, name, "mallocator_free")) {
        try writer.print(
            ".global {s}\n{s}:\n" ++
                "    push %rbp\n" ++
                "    mov %rsp, %rbp\n" ++
                "    mov 32(%rbp), %rax\n" ++
                "    push %rax\n" ++
                "    mov 24(%rbp), %rax\n" ++
                "    push %rax\n" ++
                "    mov 16(%rbp), %rax\n" ++
                "    push %rax\n" ++
                "    call __dyn_os_free\n" ++
                "    add $24, %rsp\n" ++
                "    mov %rbp, %rsp\n" ++
                "    pop %rbp\n" ++
                "    ret\n",
            .{ name, name },
        );
        return true;
    }
    if (std.mem.eql(u8, name, "mpage_allocator_realloc") or std.mem.eql(u8, name, "mheap_realloc") or std.mem.eql(u8, name, "mmem_realloc") or std.mem.eql(u8, name, "mallocator_realloc")) {
        try writer.print(
            ".global {s}\n{s}:\n" ++
                "    push %rbp\n" ++
                "    mov %rsp, %rbp\n" ++
                "    mov 48(%rbp), %rax\n" ++
                "    push %rax\n" ++
                "    mov 40(%rbp), %rax\n" ++
                "    push %rax\n" ++
                "    mov 32(%rbp), %rax\n" ++
                "    push %rax\n" ++
                "    mov 24(%rbp), %rax\n" ++
                "    push %rax\n" ++
                "    mov 16(%rbp), %rax\n" ++
                "    push %rax\n" ++
                "    call __dyn_os_realloc\n" ++
                "    add $40, %rsp\n" ++
                "    mov %rbp, %rsp\n" ++
                "    pop %rbp\n" ++
                "    ret\n",
            .{ name, name },
        );
        return true;
    }
    if (std.mem.eql(u8, name, "mio_print") or std.mem.eql(u8, name, "mprint_print")) {
        try writer.print(
            ".global {s}\n{s}:\n" ++
                "    push %rbp\n" ++
                "    mov %rsp, %rbp\n" ++
                "    mov 16(%rbp), %rsi\n" ++
                "    mov %rsi, %rcx\n" ++
                "    xor %rdx, %rdx\n" ++
                "1:\n" ++
                "    cmpb $0, (%rcx)\n" ++
                "    je 2f\n" ++
                "    inc %rcx\n" ++
                "    inc %rdx\n" ++
                "    jmp 1b\n" ++
                "2:\n" ++
                "    mov $1, %rax\n" ++
                "    mov $1, %rdi\n" ++
                "    syscall\n" ++
                "    xor %rax, %rax\n" ++
                "    mov %rbp, %rsp\n" ++
                "    pop %rbp\n" ++
                "    ret\n",
            .{ name, name },
        );
        return true;
    }
    return false;
}

pub fn buildExecutableDirect(
    allocator: std.mem.Allocator,
    target: Target,
    program: Ir.Program,
    asm_path: []const u8,
    out_path: []const u8,
) !void {
    {
        var file = try std.fs.cwd().createFile(asm_path, .{ .truncate = true });
        defer file.close();
        var buf: [4096]u8 = undefined;
        var w = file.writer(&buf);
        try emitAssemblyDirect(target, program, &w.interface);
        try w.interface.flush();
    }

    var child = std.process.Child.init(&.{
        "cc",
        "-nostdlib",
        "-Wl,-e,_start",
        "-o",
        out_path,
        asm_path,
    }, allocator);
    const term = try child.spawnAndWait();
    switch (term) {
        .Exited => |code| if (code != 0) return error.LinkFailed,
        else => return error.LinkFailed,
    }
}

pub fn buildObjectDirect(
    allocator: std.mem.Allocator,
    target: Target,
    program: Ir.Program,
    asm_path: []const u8,
    out_obj_path: []const u8,
) !void {
    return buildObjectDirectWithPrefix(allocator, target, program, asm_path, out_obj_path, "u0", true);
}

pub fn buildObjectDirectWithPrefix(
    allocator: std.mem.Allocator,
    target: Target,
    program: Ir.Program,
    asm_path: []const u8,
    out_obj_path: []const u8,
    unit_prefix: []const u8,
    include_entry: bool,
) !void {
    {
        var file = try std.fs.cwd().createFile(asm_path, .{ .truncate = true });
        defer file.close();
        var buf: [4096]u8 = undefined;
        var w = file.writer(&buf);
        switch (target) {
            .linux_x86_64 => try emitAssemblyDirectLinuxX64Ex(program, &w.interface, unit_prefix, include_entry),
        }
        try w.interface.flush();
    }

    var child = std.process.Child.init(&.{
        "cc",
        "-c",
        "-o",
        out_obj_path,
        asm_path,
    }, allocator);
    const term = try child.spawnAndWait();
    switch (term) {
        .Exited => |code| if (code != 0) return error.AssembleFailed,
        else => return error.AssembleFailed,
    }
}

pub fn buildExecutable(
    allocator: std.mem.Allocator,
    target: Target,
    program: Ir.Program,
    asm_path: []const u8,
    out_path: []const u8,
) !void {
    {
        var file = try std.fs.cwd().createFile(asm_path, .{ .truncate = true });
        defer file.close();
        var buf: [4096]u8 = undefined;
        var w = file.writer(&buf);
        try emitAssembly(target, program, &w.interface);
        try w.interface.flush();
    }

    var child = std.process.Child.init(&.{
        "cc",
        "-nostdlib",
        "-Wl,-e,_start",
        "-o",
        out_path,
        asm_path,
    }, allocator);
    const term = try child.spawnAndWait();
    switch (term) {
        .Exited => |code| if (code != 0) return error.LinkFailed,
        else => return error.LinkFailed,
    }
}

fn findMainIndex(program: Ir.Program) ?u32 {
    for (program.functions, 0..) |f, i| {
        if (std.mem.eql(u8, f.name, "main")) return @intCast(i);
    }
    return null;
}

const RuntimeState = struct {
    globals: [256]i64 = [_]i64{0} ** 256,
    heap_words: [8192]i64 = [_]i64{0} ** 8192,
    alloc_start: [256]usize = [_]usize{0} ** 256,
    alloc_words: [256]usize = [_]usize{0} ** 256,
    alloc_used: [256]bool = [_]bool{false} ** 256,
    heap_next: usize = 0,
};

fn runtimeAlloc(state: *RuntimeState, size_bytes: i64, align_bytes: i64) !i64 {
    if (align_bytes <= 0 or (align_bytes & (align_bytes - 1)) != 0) return error.UnsupportedIr;
    if (size_bytes <= 0) return 0;
    const words: usize = @intCast(@divFloor(size_bytes + 7, 8));
    if (words == 0) return 0;
    if (state.heap_next + words > state.heap_words.len) return 0;

    const start = state.heap_next;
    state.heap_next += words;

    var slot: usize = 0;
    while (slot < state.alloc_used.len) : (slot += 1) {
        if (!state.alloc_used[slot]) {
            state.alloc_used[slot] = true;
            state.alloc_start[slot] = start;
            state.alloc_words[slot] = words;
            return 0x6000_0000 + @as(i64, @intCast(start));
        }
    }
    return error.UnsupportedIr;
}

fn runtimeFree(state: *RuntimeState, ptr: i64) void {
    if (ptr == 0) return;
    if (ptr < 0x6000_0000) return;
    const start: usize = @intCast(ptr - 0x6000_0000);
    var slot: usize = 0;
    while (slot < state.alloc_used.len) : (slot += 1) {
        if (state.alloc_used[slot] and state.alloc_start[slot] == start) {
            state.alloc_used[slot] = false;
            return;
        }
    }
}

fn runtimeRealloc(state: *RuntimeState, ptr: i64, old_size: i64, old_align: i64, new_size: i64, new_align: i64) !i64 {
    _ = old_align;
    if (ptr == 0) return try runtimeAlloc(state, new_size, new_align);
    if (new_size <= 0) {
        runtimeFree(state, ptr);
        return 0;
    }
    const new_ptr = try runtimeAlloc(state, new_size, new_align);
    if (new_ptr == 0) return 0;
    if (ptr < 0x6000_0000 or new_ptr < 0x6000_0000) return error.UnsupportedIr;
    const src_start: usize = @intCast(ptr - 0x6000_0000);
    const dst_start: usize = @intCast(new_ptr - 0x6000_0000);
    const copy_words: usize = @intCast(@divFloor(@min(old_size, new_size) + 7, 8));
    if (src_start + copy_words > state.heap_words.len or dst_start + copy_words > state.heap_words.len) return error.UnsupportedIr;
    var i: usize = 0;
    while (i < copy_words) : (i += 1) {
        state.heap_words[dst_start + i] = state.heap_words[src_start + i];
    }
    runtimeFree(state, ptr);
    return new_ptr;
}

fn runFunction(program: Ir.Program, func_index: u32, args: []const i64, state: *RuntimeState) !i64 {
    if (func_index >= program.functions.len) return error.UnsupportedIr;
    const f = program.functions[func_index];
    if (std.mem.eql(u8, f.name, "mpage_allocator_alloc") or std.mem.eql(u8, f.name, "mheap_alloc") or std.mem.eql(u8, f.name, "mmem_alloc") or std.mem.eql(u8, f.name, "mallocator_alloc")) {
        if (args.len != 2) return error.UnsupportedIr;
        return try runtimeAlloc(state, args[0], args[1]);
    }
    if (std.mem.eql(u8, f.name, "mpage_allocator_free") or std.mem.eql(u8, f.name, "mheap_free") or std.mem.eql(u8, f.name, "mmem_free") or std.mem.eql(u8, f.name, "mallocator_free")) {
        if (args.len != 3) return error.UnsupportedIr;
        runtimeFree(state, args[0]);
        return 0;
    }
    if (std.mem.eql(u8, f.name, "mpage_allocator_realloc") or std.mem.eql(u8, f.name, "mheap_realloc") or std.mem.eql(u8, f.name, "mmem_realloc") or std.mem.eql(u8, f.name, "mallocator_realloc")) {
        if (args.len != 5) return error.UnsupportedIr;
        return try runtimeRealloc(state, args[0], args[1], args[2], args[3], args[4]);
    }
    if (std.mem.eql(u8, f.name, "mio_print") or std.mem.eql(u8, f.name, "mprint_print")) {
        if (args.len != 1) return error.UnsupportedIr;
        const p = args[0];
        if (p < 0x1000) return error.UnsupportedIr;
        const idx: usize = @intCast(p - 0x1000);
        if (idx >= program.rodata_strings.len) return error.UnsupportedIr;
        _ = try std.posix.write(std.posix.STDOUT_FILENO, program.rodata_strings[idx].bytes);
        return 0;
    }
    if (f.call_conv != .stack_i64) return error.UnsupportedIr;
    if (f.param_type != .i64 and f.param_type != .bool) return error.UnsupportedIr;
    if (f.ret_type != .i64 and f.ret_type != .bool) return error.UnsupportedIr;
    if (args.len != f.param_count) return error.UnsupportedIr;

    var locals: [256]i64 = [_]i64{0} ** 256;
    if (f.local_count > locals.len) return error.UnsupportedIr;
    for (args, 0..) |v, i| locals[i] = v;

    var stack: [1024]i64 = undefined;
    var sp: usize = 0;
    var pc: usize = 0;
    const ptr_base_local: i64 = 0x4000_0000;
    const ptr_base_global: i64 = 0x5000_0000;
    const ptr_base_heap: i64 = 0x6000_0000;

    while (pc < f.instructions.len) : (pc += 1) {
        const ins = f.instructions[pc];
        switch (ins) {
            .push_const_i64 => |v| {
                if (sp >= stack.len) return error.UnsupportedIr;
                stack[sp] = v;
                sp += 1;
            },
            .push_rodata_ptr => |idx| {
                if (sp >= stack.len or idx >= program.rodata_strings.len) return error.UnsupportedIr;
                stack[sp] = @as(i64, idx) + 0x1000;
                sp += 1;
            },
            .load_local => |slot| {
                if (slot >= f.local_count or sp >= stack.len) return error.UnsupportedIr;
                stack[sp] = locals[slot];
                sp += 1;
            },
            .store_local => |slot| {
                if (slot >= f.local_count or sp == 0) return error.UnsupportedIr;
                sp -= 1;
                locals[slot] = stack[sp];
            },
            .addr_of_local => |slot| {
                if (slot >= f.local_count or sp >= stack.len) return error.UnsupportedIr;
                stack[sp] = ptr_base_local + @as(i64, @intCast(slot));
                sp += 1;
            },
            .addr_of_global => |slot| {
                if (slot >= program.global_count or sp >= stack.len) return error.UnsupportedIr;
                stack[sp] = ptr_base_global + @as(i64, @intCast(slot));
                sp += 1;
            },
            .ptr_offset_slots => |slots| {
                if (sp == 0) return error.UnsupportedIr;
                stack[sp - 1] += @as(i64, slots);
            },
            .load_ptr => {
                if (sp == 0) return error.UnsupportedIr;
                const p = stack[sp - 1];
                if (p >= ptr_base_heap) {
                    const slot: usize = @intCast(p - ptr_base_heap);
                    if (slot >= state.heap_words.len) return error.UnsupportedIr;
                    stack[sp - 1] = state.heap_words[slot];
                } else if (p >= ptr_base_global) {
                    const slot: usize = @intCast(p - ptr_base_global);
                    if (slot >= program.global_count) return error.UnsupportedIr;
                    stack[sp - 1] = state.globals[slot];
                } else if (p >= ptr_base_local) {
                    const slot: usize = @intCast(p - ptr_base_local);
                    if (slot >= f.local_count) return error.UnsupportedIr;
                    stack[sp - 1] = locals[slot];
                } else return error.UnsupportedIr;
            },
            .store_ptr => {
                if (sp < 2) return error.UnsupportedIr;
                const val = stack[sp - 1];
                const p = stack[sp - 2];
                if (p >= ptr_base_heap) {
                    const slot: usize = @intCast(p - ptr_base_heap);
                    if (slot >= state.heap_words.len) return error.UnsupportedIr;
                    state.heap_words[slot] = val;
                } else if (p >= ptr_base_global) {
                    const slot: usize = @intCast(p - ptr_base_global);
                    if (slot >= program.global_count) return error.UnsupportedIr;
                    state.globals[slot] = val;
                } else if (p >= ptr_base_local) {
                    const slot: usize = @intCast(p - ptr_base_local);
                    if (slot >= f.local_count) return error.UnsupportedIr;
                    locals[slot] = val;
                } else return error.UnsupportedIr;
                sp -= 2;
                stack[sp] = val;
                sp += 1;
            },
            .unwrap_optional => {
                if (sp == 0) return error.UnsupportedIr;
                if (stack[sp - 1] == 0) return error.UnsupportedIr;
            },
            .unwrap_error => {
                if (sp == 0) return error.UnsupportedIr;
                if (stack[sp - 1] == 0) return error.UnsupportedIr;
            },
            .pop => {
                if (sp == 0) return error.UnsupportedIr;
                sp -= 1;
            },
            .add => try binaryOp(&stack, &sp, opAdd),
            .sub => try binaryOp(&stack, &sp, opSub),
            .mul => try binaryOp(&stack, &sp, opMul),
            .div => try binaryOp(&stack, &sp, opDiv),
            .mod => try binaryOp(&stack, &sp, opMod),
            .eq => try binaryOp(&stack, &sp, opEq),
            .neq => try binaryOp(&stack, &sp, opNeq),
            .lt => try binaryOp(&stack, &sp, opLt),
            .lte => try binaryOp(&stack, &sp, opLte),
            .gt => try binaryOp(&stack, &sp, opGt),
            .gte => try binaryOp(&stack, &sp, opGte),
            .jump => |target| {
                if (target >= f.instructions.len) return error.UnsupportedIr;
                pc = target - 1;
            },
            .jump_if_false => |target| {
                if (sp == 0 or target >= f.instructions.len) return error.UnsupportedIr;
                sp -= 1;
                if (stack[sp] == 0) pc = target - 1;
            },
            .call => |c| {
                if (sp < c.arg_count) return error.UnsupportedIr;
                var call_args: [64]i64 = undefined;
                if (c.arg_count > call_args.len) return error.UnsupportedIr;
                const base = sp - c.arg_count;
                for (0..c.arg_count) |i| call_args[i] = stack[base + i];
                sp = base;
                const rv = switch (c.target) {
                    .internal_index => |idx| try runFunction(program, idx, call_args[0..c.arg_count], state),
                    .external_symbol => |ex| blk: {
                        if (std.mem.eql(u8, ex.name, "__dyn_os_alloc")) {
                            if (c.arg_count != 2) return error.UnsupportedIr;
                            break :blk try runtimeAlloc(state, call_args[0], call_args[1]);
                        }
                        if (std.mem.eql(u8, ex.name, "__dyn_os_free")) {
                            if (c.arg_count != 3) return error.UnsupportedIr;
                            runtimeFree(state, call_args[0]);
                            break :blk 0;
                        }
                        if (std.mem.eql(u8, ex.name, "__dyn_os_realloc")) {
                            if (c.arg_count != 5) return error.UnsupportedIr;
                            break :blk try runtimeRealloc(state, call_args[0], call_args[1], call_args[2], call_args[3], call_args[4]);
                        }
                        return error.UnsupportedIr;
                    },
                };
                if (sp >= stack.len) return error.UnsupportedIr;
                stack[sp] = rv;
                sp += 1;
            },
            .ret => {
                if (sp == 0) return 0;
                return stack[sp - 1];
            },
        }
    }
    return error.UnsupportedIr;
}

fn binaryOp(stack: *[1024]i64, sp: *usize, comptime op: fn (i64, i64) anyerror!i64) !void {
    if (sp.* < 2) return error.UnsupportedIr;
    const b = stack[sp.* - 1];
    const a = stack[sp.* - 2];
    sp.* -= 2;
    stack[sp.*] = try op(a, b);
    sp.* += 1;
}

fn opAdd(a: i64, b: i64) !i64 {
    return a + b;
}
fn opSub(a: i64, b: i64) !i64 {
    return a - b;
}
fn opMul(a: i64, b: i64) !i64 {
    return a * b;
}
fn opDiv(a: i64, b: i64) !i64 {
    if (b == 0) return error.UnsupportedIr;
    return @divTrunc(a, b);
}
fn opMod(a: i64, b: i64) !i64 {
    if (b == 0) return error.UnsupportedIr;
    return @mod(a, b);
}
fn opEq(a: i64, b: i64) !i64 {
    return if (a == b) 1 else 0;
}
fn opNeq(a: i64, b: i64) !i64 {
    return if (a != b) 1 else 0;
}
fn opLt(a: i64, b: i64) !i64 {
    return if (a < b) 1 else 0;
}
fn opLte(a: i64, b: i64) !i64 {
    return if (a <= b) 1 else 0;
}
fn opGt(a: i64, b: i64) !i64 {
    return if (a > b) 1 else 0;
}
fn opGte(a: i64, b: i64) !i64 {
    return if (a >= b) 1 else 0;
}

test "lower main return" {
    const alloc = std.testing.allocator;
    var p = try Ir.makeTinyMain(alloc, 42);
    defer Ir.deinitProgram(alloc, &p);
    const code = try lowerMainExitCode(p);
    try std.testing.expectEqual(@as(i64, 42), code);
}

test "emit x86_64 asm" {
    const alloc = std.testing.allocator;
    var p = try Ir.makeTinyMain(alloc, 5);
    defer Ir.deinitProgram(alloc, &p);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);
    try emitAssembly(.linux_x86_64, p, w);

    try std.testing.expect(std.mem.indexOf(u8, out.items, "_start") != null);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "mov $60") != null);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "mov $5") != null);
}

test "emit direct asm x86_64" {
    const alloc = std.testing.allocator;
    var p = try Ir.makeTinyMain(alloc, 12);
    defer Ir.deinitProgram(alloc, &p);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);
    try emitAssemblyDirect(.linux_x86_64, p, w);

    try std.testing.expect(std.mem.indexOf(u8, out.items, "L0:") != null);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "mov $12") != null);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "syscall") != null);
}

test "emit direct asm includes rodata" {
    const alloc = std.testing.allocator;
    const instr = try alloc.alloc(Ir.Instruction, 3);
    instr[0] = .{ .push_rodata_ptr = 0 };
    instr[1] = .{ .pop = {} };
    instr[2] = .{ .push_const_i64 = 0 };

    const funcs = try alloc.alloc(Ir.Function, 1);
    funcs[0] = .{ .name = "main", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 0, .local_count = 0, .instructions = instr };
    const rods = try alloc.alloc(Ir.StringConst, 1);
    rods[0] = .{ .bytes = "hello", .owned = false };
    var p = Ir.Program{ .functions = funcs, .rodata_strings = rods, .global_count = 0 };
    defer Ir.deinitProgram(alloc, &p);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);
    try emitAssemblyDirect(.linux_x86_64, p, w);

    try std.testing.expect(std.mem.indexOf(u8, out.items, ".section .rodata") != null);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "u0_str_0") != null);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "lea u0_str_0") != null);
}

test "build executable direct with call" {
    const alloc = std.testing.allocator;
    const instr_add = try alloc.alloc(Ir.Instruction, 4);
    instr_add[0] = .{ .load_local = 0 };
    instr_add[1] = .{ .load_local = 1 };
    instr_add[2] = .{ .add = {} };
    instr_add[3] = .{ .ret = {} };

    const instr_main = try alloc.alloc(Ir.Instruction, 4);
    instr_main[0] = .{ .push_const_i64 = 7 };
    instr_main[1] = .{ .push_const_i64 = 5 };
    instr_main[2] = .{ .call = .{ .arg_count = 2, .target = .{ .internal_index = 1 } } };
    instr_main[3] = .{ .ret = {} };

    const funcs = try alloc.alloc(Ir.Function, 2);
    funcs[0] = .{ .name = "main", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 0, .local_count = 0, .instructions = instr_main };
    funcs[1] = .{ .name = "add", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 2, .local_count = 2, .instructions = instr_add };
    var p = Ir.Program{ .functions = funcs, .rodata_strings = &.{}, .global_count = 0 };
    defer Ir.deinitProgram(alloc, &p);

    const dir = "tmp_backend_direct";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    const asm_path = "tmp_backend_direct/out.s";
    const exe_path = "tmp_backend_direct/out";
    try buildExecutableDirect(alloc, .linux_x86_64, p, asm_path, exe_path);

    var child = std.process.Child.init(&.{"./tmp_backend_direct/out"}, alloc);
    const term = try child.spawnAndWait();
    switch (term) {
        .Exited => |code| try std.testing.expectEqual(@as(u8, 12), code),
        else => return error.TestUnexpectedResult,
    }
}

test "build object direct" {
    const alloc = std.testing.allocator;
    var p = try Ir.makeTinyMain(alloc, 3);
    defer Ir.deinitProgram(alloc, &p);

    const dir = "tmp_backend_direct_obj";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    const asm_path = "tmp_backend_direct_obj/out.s";
    const obj_path = "tmp_backend_direct_obj/out.o";
    try buildObjectDirect(alloc, .linux_x86_64, p, asm_path, obj_path);

    const st = try std.fs.cwd().statFile(obj_path);
    try std.testing.expect(st.size > 0);
}

test "build executable direct with branch and loop" {
    const alloc = std.testing.allocator;

    const instr_main = try alloc.alloc(Ir.Instruction, 16);
    instr_main[0] = .{ .push_const_i64 = 0 }; // i
    instr_main[1] = .{ .store_local = 0 };
    instr_main[2] = .{ .push_const_i64 = 0 }; // sum
    instr_main[3] = .{ .store_local = 1 };
    instr_main[4] = .{ .load_local = 0 }; // Lcond: i < 5
    instr_main[5] = .{ .push_const_i64 = 5 };
    instr_main[6] = .{ .lt = {} };
    instr_main[7] = .{ .jump_if_false = 17 };
    instr_main[8] = .{ .load_local = 1 }; // sum = sum + i
    instr_main[9] = .{ .load_local = 0 };
    instr_main[10] = .{ .add = {} };
    instr_main[11] = .{ .store_local = 1 };
    instr_main[12] = .{ .load_local = 0 }; // i = i + 1
    instr_main[13] = .{ .push_const_i64 = 1 };
    instr_main[14] = .{ .add = {} };
    instr_main[15] = .{ .store_local = 0 };

    var loop_tail = try alloc.alloc(Ir.Instruction, 8);
    loop_tail[0] = .{ .jump = 4 };
    loop_tail[1] = .{ .load_local = 1 }; // if sum == 10 then 77 else 3
    loop_tail[2] = .{ .push_const_i64 = 10 };
    loop_tail[3] = .{ .eq = {} };
    loop_tail[4] = .{ .jump_if_false = 23 };
    loop_tail[5] = .{ .push_const_i64 = 77 };
    loop_tail[6] = .{ .ret = {} };
    loop_tail[7] = .{ .push_const_i64 = 3 };

    const full = try alloc.alloc(Ir.Instruction, instr_main.len + loop_tail.len + 1);
    @memcpy(full[0..instr_main.len], instr_main);
    @memcpy(full[instr_main.len .. instr_main.len + loop_tail.len], loop_tail);
    full[full.len - 1] = .{ .ret = {} };
    alloc.free(instr_main);
    alloc.free(loop_tail);

    const funcs = try alloc.alloc(Ir.Function, 1);
    funcs[0] = .{ .name = "main", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 0, .local_count = 2, .instructions = full };
    var p = Ir.Program{ .functions = funcs, .rodata_strings = &.{}, .global_count = 0 };
    defer Ir.deinitProgram(alloc, &p);

    const dir = "tmp_backend_direct_flow";
    std.fs.cwd().deleteTree(dir) catch {};
    try std.fs.cwd().makePath(dir);
    defer std.fs.cwd().deleteTree(dir) catch {};

    const asm_path = "tmp_backend_direct_flow/out.s";
    const exe_path = "tmp_backend_direct_flow/out";
    try buildExecutableDirect(alloc, .linux_x86_64, p, asm_path, exe_path);

    var child = std.process.Child.init(&.{"./tmp_backend_direct_flow/out"}, alloc);
    const term = try child.spawnAndWait();
    switch (term) {
        .Exited => |code| try std.testing.expectEqual(@as(u8, 77), code),
        else => return error.TestUnexpectedResult,
    }
}

test "direct asm avoids callee-saved rbx in generated ops" {
    const alloc = std.testing.allocator;

    const instr_main = try alloc.alloc(Ir.Instruction, 4);
    instr_main[0] = .{ .push_const_i64 = 2 };
    instr_main[1] = .{ .push_const_i64 = 3 };
    instr_main[2] = .{ .add = {} };
    instr_main[3] = .{ .ret = {} };

    const funcs = try alloc.alloc(Ir.Function, 1);
    funcs[0] = .{ .name = "main", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 0, .local_count = 0, .instructions = instr_main };
    var p = Ir.Program{ .functions = funcs, .rodata_strings = &.{}, .global_count = 0 };
    defer Ir.deinitProgram(alloc, &p);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);
    try emitAssemblyDirect(.linux_x86_64, p, w);

    try std.testing.expect(std.mem.indexOf(u8, out.items, "%rbx") == null);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "%rcx") != null);
}

test "direct asm aligns local stack frame allocation to 16 bytes" {
    const alloc = std.testing.allocator;

    const instr_main = try alloc.alloc(Ir.Instruction, 2);
    instr_main[0] = .{ .push_const_i64 = 1 };
    instr_main[1] = .{ .ret = {} };

    const funcs = try alloc.alloc(Ir.Function, 1);
    funcs[0] = .{ .name = "main", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 0, .local_count = 1, .instructions = instr_main };
    var p = Ir.Program{ .functions = funcs, .rodata_strings = &.{}, .global_count = 0 };
    defer Ir.deinitProgram(alloc, &p);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);
    try emitAssemblyDirect(.linux_x86_64, p, w);

    try std.testing.expect(std.mem.indexOf(u8, out.items, "sub $16, %rsp") != null);
}

test "direct asm and interpreter support pointer load/store ops" {
    const alloc = std.testing.allocator;

    const instr_main = try alloc.alloc(Ir.Instruction, 11);
    instr_main[0] = .{ .push_const_i64 = 1 };
    instr_main[1] = .{ .store_local = 0 };
    instr_main[2] = .{ .addr_of_local = 0 };
    instr_main[3] = .{ .store_local = 1 };
    instr_main[4] = .{ .load_local = 1 };
    instr_main[5] = .{ .push_const_i64 = 7 };
    instr_main[6] = .{ .store_ptr = {} };
    instr_main[7] = .{ .pop = {} };
    instr_main[8] = .{ .load_local = 1 };
    instr_main[9] = .{ .load_ptr = {} };
    instr_main[10] = .{ .ret = {} };

    const funcs = try alloc.alloc(Ir.Function, 1);
    funcs[0] = .{ .name = "main", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 0, .local_count = 2, .instructions = instr_main };
    var p = Ir.Program{ .functions = funcs, .rodata_strings = &.{}, .global_count = 0 };
    defer Ir.deinitProgram(alloc, &p);

    const code = try lowerMainExitCode(p);
    try std.testing.expectEqual(@as(i64, 7), code);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);
    try emitAssemblyDirect(.linux_x86_64, p, w);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "lea -8(%rbp), %rax") != null);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "mov (%rcx), %rax") != null);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "mov %rax, (%rcx)") != null);
}

test "direct asm and interpreter support pointer slot offsets" {
    const alloc = std.testing.allocator;

    const instr_main = try alloc.alloc(Ir.Instruction, 9);
    instr_main[0] = .{ .push_const_i64 = 11 };
    instr_main[1] = .{ .store_local = 0 };
    instr_main[2] = .{ .push_const_i64 = 22 };
    instr_main[3] = .{ .store_local = 1 };
    instr_main[4] = .{ .addr_of_local = 0 };
    instr_main[5] = .{ .ptr_offset_slots = 1 };
    instr_main[6] = .{ .load_ptr = {} };
    instr_main[7] = .{ .ret = {} };
    instr_main[8] = .{ .push_const_i64 = 0 };

    const funcs = try alloc.alloc(Ir.Function, 1);
    funcs[0] = .{ .name = "main", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 0, .local_count = 2, .instructions = instr_main };
    var p = Ir.Program{ .functions = funcs, .rodata_strings = &.{}, .global_count = 0 };
    defer Ir.deinitProgram(alloc, &p);

    const code = try lowerMainExitCode(p);
    try std.testing.expectEqual(@as(i64, 22), code);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);
    try emitAssemblyDirect(.linux_x86_64, p, w);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "add $8, %rax") != null);
}

test "direct asm and interpreter support global pointer storage" {
    const alloc = std.testing.allocator;

    const instr_main = try alloc.alloc(Ir.Instruction, 7);
    instr_main[0] = .{ .addr_of_global = 0 };
    instr_main[1] = .{ .push_const_i64 = 41 };
    instr_main[2] = .{ .store_ptr = {} };
    instr_main[3] = .{ .pop = {} };
    instr_main[4] = .{ .addr_of_global = 0 };
    instr_main[5] = .{ .load_ptr = {} };
    instr_main[6] = .{ .ret = {} };

    const funcs = try alloc.alloc(Ir.Function, 1);
    funcs[0] = .{ .name = "main", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 0, .local_count = 0, .instructions = instr_main };
    var p = Ir.Program{ .functions = funcs, .rodata_strings = &.{}, .global_count = 1 };
    defer Ir.deinitProgram(alloc, &p);

    const code = try lowerMainExitCode(p);
    try std.testing.expectEqual(@as(i64, 41), code);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);
    try emitAssemblyDirect(.linux_x86_64, p, w);
    try std.testing.expect(std.mem.indexOf(u8, out.items, ".section .bss") != null);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "u0_globals") != null);
}

test "runtime backing allocator symbols work via external calls" {
    const alloc = std.testing.allocator;

    const instr_main = try alloc.alloc(Ir.Instruction, 16);
    instr_main[0] = .{ .push_const_i64 = 16 };
    instr_main[1] = .{ .push_const_i64 = 8 };
    instr_main[2] = .{ .call = .{ .arg_count = 2, .target = .{ .external_symbol = .{ .name = "__dyn_os_alloc", .name_owned = false } } } };
    instr_main[3] = .{ .store_local = 0 };
    instr_main[4] = .{ .load_local = 0 };
    instr_main[5] = .{ .push_const_i64 = 123 };
    instr_main[6] = .{ .store_ptr = {} };
    instr_main[7] = .{ .pop = {} };
    instr_main[8] = .{ .load_local = 0 };
    instr_main[9] = .{ .load_ptr = {} };
    instr_main[10] = .{ .load_local = 0 };
    instr_main[11] = .{ .push_const_i64 = 16 };
    instr_main[12] = .{ .push_const_i64 = 8 };
    instr_main[13] = .{ .call = .{ .arg_count = 3, .target = .{ .external_symbol = .{ .name = "__dyn_os_free", .name_owned = false } } } };
    instr_main[14] = .{ .pop = {} };
    instr_main[15] = .{ .ret = {} };

    const funcs = try alloc.alloc(Ir.Function, 1);
    funcs[0] = .{ .name = "main", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 0, .local_count = 1, .instructions = instr_main };
    var p = Ir.Program{ .functions = funcs, .rodata_strings = &.{}, .global_count = 0 };
    defer Ir.deinitProgram(alloc, &p);

    const code = try lowerMainExitCode(p);
    try std.testing.expectEqual(@as(i64, 123), code);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);
    try emitAssemblyDirect(.linux_x86_64, p, w);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "__dyn_os_alloc:") != null);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "__dyn_os_free:") != null);
}

test "std page allocator intrinsics allocate and free" {
    const alloc = std.testing.allocator;

    const instr_main = try alloc.alloc(Ir.Instruction, 10);
    instr_main[0] = .{ .push_const_i64 = 24 };
    instr_main[1] = .{ .push_const_i64 = 8 };
    instr_main[2] = .{ .call = .{ .arg_count = 2, .target = .{ .internal_index = 1 } } };
    instr_main[3] = .{ .store_local = 0 };
    instr_main[4] = .{ .load_local = 0 };
    instr_main[5] = .{ .push_const_i64 = 24 };
    instr_main[6] = .{ .push_const_i64 = 8 };
    instr_main[7] = .{ .call = .{ .arg_count = 3, .target = .{ .internal_index = 2 } } };
    instr_main[8] = .{ .pop = {} };
    instr_main[9] = .{ .ret = {} };

    const instr_alloc = try alloc.alloc(Ir.Instruction, 2);
    instr_alloc[0] = .{ .push_const_i64 = 0 };
    instr_alloc[1] = .{ .ret = {} };
    const instr_free = try alloc.alloc(Ir.Instruction, 2);
    instr_free[0] = .{ .push_const_i64 = 0 };
    instr_free[1] = .{ .ret = {} };

    const funcs = try alloc.alloc(Ir.Function, 3);
    funcs[0] = .{ .name = "main", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 0, .local_count = 1, .instructions = instr_main };
    funcs[1] = .{ .name = "mpage_allocator_alloc", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 2, .local_count = 0, .instructions = instr_alloc };
    funcs[2] = .{ .name = "mpage_allocator_free", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 3, .local_count = 0, .instructions = instr_free };
    var p = Ir.Program{ .functions = funcs, .rodata_strings = &.{}, .global_count = 0 };
    defer Ir.deinitProgram(alloc, &p);

    try std.testing.expectEqual(@as(i64, 0), try lowerMainExitCode(p));

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);
    try emitAssemblyDirect(.linux_x86_64, p, w);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "mpage_allocator_alloc") != null);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "call __dyn_os_alloc") != null);
}

test "std io print intrinsic emits and executes" {
    const alloc = std.testing.allocator;

    const instr_main = try alloc.alloc(Ir.Instruction, 3);
    instr_main[0] = .{ .push_rodata_ptr = 0 };
    instr_main[1] = .{ .call = .{ .arg_count = 1, .target = .{ .internal_index = 1 } } };
    instr_main[2] = .{ .ret = {} };

    const instr_hello = try alloc.alloc(Ir.Instruction, 2);
    instr_hello[0] = .{ .push_const_i64 = 0 };
    instr_hello[1] = .{ .ret = {} };

    const rods = try alloc.alloc(Ir.StringConst, 1);
    rods[0] = .{ .bytes = "Hello, world!\n", .owned = false };

    const funcs = try alloc.alloc(Ir.Function, 2);
    funcs[0] = .{ .name = "main", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 0, .local_count = 0, .instructions = instr_main };
    funcs[1] = .{ .name = "mio_print", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 1, .local_count = 0, .instructions = instr_hello };
    var p = Ir.Program{ .functions = funcs, .rodata_strings = rods, .global_count = 0 };
    defer Ir.deinitProgram(alloc, &p);

    try std.testing.expectEqual(@as(i64, 0), try lowerMainExitCode(p));

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(alloc);
    const w = out.writer(alloc);
    try emitAssemblyDirect(.linux_x86_64, p, w);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "mio_print") != null);
    try std.testing.expect(std.mem.indexOf(u8, out.items, "cmpb $0, (%rcx)") != null);
}

test "runtime unwrap instructions are non-pass-through" {
    const alloc = std.testing.allocator;

    const ok_instr = try alloc.alloc(Ir.Instruction, 3);
    ok_instr[0] = .{ .push_const_i64 = 9 };
    ok_instr[1] = .{ .unwrap_optional = {} };
    ok_instr[2] = .{ .ret = {} };

    const ok_funcs = try alloc.alloc(Ir.Function, 1);
    ok_funcs[0] = .{ .name = "main", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 0, .local_count = 0, .instructions = ok_instr };
    var ok_program = Ir.Program{ .functions = ok_funcs, .rodata_strings = &.{}, .global_count = 0 };
    defer Ir.deinitProgram(alloc, &ok_program);

    try std.testing.expectEqual(@as(i64, 9), try lowerMainExitCode(ok_program));

    const fail_instr = try alloc.alloc(Ir.Instruction, 3);
    fail_instr[0] = .{ .push_const_i64 = 0 };
    fail_instr[1] = .{ .unwrap_error = {} };
    fail_instr[2] = .{ .ret = {} };

    const fail_funcs = try alloc.alloc(Ir.Function, 1);
    fail_funcs[0] = .{ .name = "main", .name_owned = false, .call_conv = .stack_i64, .ret_type = .i64, .param_type = .i64, .param_count = 0, .local_count = 0, .instructions = fail_instr };
    var fail_program = Ir.Program{ .functions = fail_funcs, .rodata_strings = &.{}, .global_count = 0 };
    defer Ir.deinitProgram(alloc, &fail_program);

    try std.testing.expectError(error.UnsupportedIr, lowerMainExitCode(fail_program));
}
