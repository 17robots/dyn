const std = @import("std");

pub const Target = struct {
    arch: Arch,
    os: OS,
    abi: ABI,
    features: Features,
    pub const Arch = enum { x86, x86_64, arm, aarch64, riscv32, riscv64, wasm32, wasm64 };
    pub const OS = enum { linux, windows, macos, ios, android, freebsd, netbsd, openbsd, freestanding };
    pub const ABI = enum { none, gnu, gnuabin32, gnuabi64, gnueabi, gnueabihf, msvc, musl, musleabi, musleabihf };
    pub const Features = struct { sse: bool = false, sse2: bool = false, avx: bool = false, avx2: bool = false, neon: bool = false };
    pub fn native() Target {}
};
pub const CodeGen = struct {
    allocator: std.mem.Allocator,
    target: *const Target,
    vtable: *const VTable,
    pub fn init(allocator: std.mem.Allocator, target: *const Target, vtable: *const VTable) CodeGen {
        return .{ .allocator = allocator, .target = target, .vtable = vtable };
    }
    // pub fn generate(self: *CodeGen, ir_module: )
    pub const VTable = struct {};
};
pub const ObjectFile = struct {
    name: []const u8,
    data: []const u8,
    relocation: []Relocation,
    symbols: []Symbol,
    pub const Relocation = struct { offset: u64, symbol: u32, type: RelocType, append: i64 = 0 };
    pub const RelocType = enum { absolute, relative, plt, got };
};
pub const Symbol = struct {
    name: []const u8,
    value: u64,
    size: u64,
    kind: SymbolKind,
    binding: SymbolBinding,
    section: u32,
    pub const SymbolKind = enum { undefined, absolute, data, function, section, file, common, tls };
    pub const SymbolBinding = enum { local, global, weak };
};
