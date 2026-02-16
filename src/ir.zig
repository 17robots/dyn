const std = @import("std");

pub const ValueId = u32;

pub const ScalarType = enum {
    i64,
    bool,
};

pub const CallConv = enum {
    stack_i64,
};

pub const Program = struct {
    functions: []Function,
    rodata_strings: []StringConst,
};

pub const StringConst = struct {
    bytes: []const u8,
    owned: bool,
};

pub const Function = struct {
    name: []const u8,
    name_owned: bool,
    call_conv: CallConv,
    ret_type: ScalarType,
    param_type: ScalarType,
    param_count: u32,
    local_count: u32,
    instructions: []Instruction,
};

pub const Instruction = union(enum) {
    push_const_i64: i64,
    push_rodata_ptr: u32,
    load_local: u32,
    store_local: u32,
    addr_of_local: u32,
    load_ptr: void,
    store_ptr: void,
    pop: void,
    add: void,
    sub: void,
    mul: void,
    div: void,
    mod: void,
    eq: void,
    neq: void,
    lt: void,
    lte: void,
    gt: void,
    gte: void,
    jump: u32,
    jump_if_false: u32,
    call: struct {
        arg_count: u32,
        target: union(enum) {
            internal_index: u32,
            external_symbol: struct {
                name: []const u8,
                name_owned: bool,
            },
        },
    },
    ret: void,
};

pub fn makeTinyMain(allocator: std.mem.Allocator, exit_code: i64) !Program {
    const instrs = try allocator.alloc(Instruction, 2);
    instrs[0] = .{ .push_const_i64 = exit_code };
    instrs[1] = .{ .ret = {} };

    const funcs = try allocator.alloc(Function, 1);
    funcs[0] = .{
        .name = "main",
        .name_owned = false,
        .call_conv = .stack_i64,
        .ret_type = .i64,
        .param_type = .i64,
        .param_count = 0,
        .local_count = 0,
        .instructions = instrs,
    };
    return .{ .functions = funcs, .rodata_strings = &.{} };
}

pub fn deinitProgram(allocator: std.mem.Allocator, p: *Program) void {
    for (p.functions) |f| {
        for (f.instructions) |ins| {
            switch (ins) {
                .call => |c| switch (c.target) {
                    .external_symbol => |ex| if (ex.name_owned) allocator.free(ex.name),
                    else => {},
                },
                else => {},
            }
        }
        allocator.free(f.instructions);
        if (f.name_owned) allocator.free(f.name);
    }
    if (p.functions.len > 0) allocator.free(p.functions);
    for (p.rodata_strings) |s| {
        if (s.owned) allocator.free(s.bytes);
    }
    if (p.rodata_strings.len > 0) allocator.free(p.rodata_strings);
    p.* = .{ .functions = &.{}, .rodata_strings = &.{} };
}

test "tiny ir program" {
    const alloc = std.testing.allocator;
    var p = try makeTinyMain(alloc, 7);
    defer deinitProgram(alloc, &p);
    try std.testing.expectEqual(@as(usize, 1), p.functions.len);
    try std.testing.expectEqualStrings("main", p.functions[0].name);
}
