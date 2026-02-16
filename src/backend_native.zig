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
    return runFunction(program, main_index, &.{}) catch return error.UnsupportedIr;
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

    for (program.functions, 0..) |f, fi| {
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
                .load_ptr => {
                    try writer.writeAll("    pop %rcx\n    mov (%rcx), %rax\n    push %rax\n");
                },
                .store_ptr => {
                    try writer.writeAll("    pop %rax\n    pop %rcx\n    mov %rax, (%rcx)\n    push %rax\n");
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

fn runFunction(program: Ir.Program, func_index: u32, args: []const i64) !i64 {
    if (func_index >= program.functions.len) return error.UnsupportedIr;
    const f = program.functions[func_index];
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
    const ptr_base: i64 = 0x4000_0000;

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
                stack[sp] = ptr_base + @as(i64, @intCast(slot));
                sp += 1;
            },
            .load_ptr => {
                if (sp == 0) return error.UnsupportedIr;
                const p = stack[sp - 1];
                if (p < ptr_base) return error.UnsupportedIr;
                const slot: usize = @intCast(p - ptr_base);
                if (slot >= f.local_count) return error.UnsupportedIr;
                stack[sp - 1] = locals[slot];
            },
            .store_ptr => {
                if (sp < 2) return error.UnsupportedIr;
                const val = stack[sp - 1];
                const p = stack[sp - 2];
                if (p < ptr_base) return error.UnsupportedIr;
                const slot: usize = @intCast(p - ptr_base);
                if (slot >= f.local_count) return error.UnsupportedIr;
                locals[slot] = val;
                sp -= 2;
                stack[sp] = val;
                sp += 1;
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
                    .internal_index => |idx| try runFunction(program, idx, call_args[0..c.arg_count]),
                    .external_symbol => return error.UnsupportedIr,
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
    var p = Ir.Program{ .functions = funcs, .rodata_strings = rods };
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
    var p = Ir.Program{ .functions = funcs, .rodata_strings = &.{} };
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
    var p = Ir.Program{ .functions = funcs, .rodata_strings = &.{} };
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
    var p = Ir.Program{ .functions = funcs, .rodata_strings = &.{} };
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
    var p = Ir.Program{ .functions = funcs, .rodata_strings = &.{} };
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
    var p = Ir.Program{ .functions = funcs, .rodata_strings = &.{} };
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
