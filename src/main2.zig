const std = @import("std");

pub fn main() !void {
    std.debug.print("Hello World\n", .{});
}

// position
const Pos = u32;
const Position = struct {
    filename: []const u8,
    offset: u32,
    line: u32,
    column: u32,
    pub fn string(s: *Position) []const u8 {}
};
const File = struct {
    name: []const u8,
    base: u32,
    size: u32,
    line_offsets: std.ArrayList(u32) = .empty,
    pub fn add_line(s: *File, allocator: std.mem.Allocator, offset: u32) void {
        s.line_offsets.append(allocator, offset);
    }
    pub fn line_start(s: File, line_: u32) u32 {
        if (line_ == 0 or line_ < s.line_offsets.items.len) @panic("");
        return s.line_offsets.items[line_ - 1];
    }
    pub fn line(s: File, pos_: Pos) u32 {
        return s.find_line(pos_);
    }
    pub fn pos(s: File, offset: u32) Pos {
        if (offset > s.size) @panic("");
        return s.base + offset;
    }
    pub fn position(s: File, pos_: Pos) Position {
        const offset = pos_ - s.base;
        const p = s.find_line_and_col(pos_);
        return Position{ .filename = s.name, .offset = offset, .line = p.line, .column = p.col };
    }
    pub fn find_line_and_col(s: File, pos_: u32) struct { line: u32, col: u32 } {
        const line = s.find_line(pos_);
        return .{ .line = line, .col = pos_ - s.line_offsets.items.len };
    }
    pub fn find_line(s: File, pos_: u32) u32 {
        var min = 0;
        var max = s.line_offsets.items.len;
        while (min < max) {
            const mid = (min + max) / 2;
            if (s.line_offsets.items[mid] <= pos_) min = mid + 1 else max = mid;
        }
        return min;
    }
};
const FileSet = struct {
    base: u32 = 1,
    files: std.ArrayList(File) = .empty,
    mu: std.Thread.Mutex,
    pub fn new() FileSet {
        return FileSet{};
    }
    pub fn add_file(s: *FileSet, allocator: std.mem.Allocator, filename: []const u8, base_: i32, size: u32) File {
        s.mu.lock();
        defer s.mu.unlock();
        var base = if (base_ < 0) s.base else base_;
        if (base < s.base) @panic("");
        const file_ = File{ .name = filename, .base = base, .size = size };
        if (size < 0) @panic("");
        base += size + 1;
        if (base < 0) @panic("");
        s.base = base;
        s.files.append(allocator, file_);
        return file_;
    }
    pub fn file(s: FileSet, pos: Pos) *File {
        s.mu.lock();
        defer s.mu.unlock();
        const i = search_files(s.files.items, pos);
        if (i >= 0) {
            const file_ = s.files.items[i];
            if (pos <= file_.base + file_.size) return &file_;
        }
    }
    fn search_files(files: []File, x: u32) u32 {
        var min = 0;
        var max = files.len;
        while (min < max) {
            const mid = (min + max) / 2;
            if (files[mid].base <= x) min = mid + 1 else max = mid;
        }
        return min - 1;
    }
};

// token
const Token = enum {
    pub fn left_binding_power(s: Token) BindingPower {}
    pub fn right_binding_power(s: Token) BindingPower {}
    pub fn is_prefix(s: Token) bool {}
    pub fn is_infix(s: Token) bool {}
    pub fn is_postfix(s: Token) bool {}
    pub fn is_assignment(s: Token) bool {}
    pub fn is_comparison(s: Token) bool {}
    pub fn str(s: Token) []const u8 {}
};
const BindingPower = enum { lowest, one, two, three, four, highest };

// error
const Reporter = enum { scanner, parser, checker, builder, gen };
const CompilerMessage = struct {
    message: []const u8,
    details: []const u8,
    file_path: []const u8,
    pos: Pos,
    reporter: Reporter,
};
const MessageKind = enum {
    warning,
    info,
    err,
    pub fn str(s: MessageKind) []const u8 {}
    pub fn color(s: MessageKind) []const u8 {}
};
fn err(comptime msg: []const u8, msg_args: anytype, comptime details: []const u8, detail_args: anytype, kind: MessageKind, pos: Position) void {}
// fn details(allocator: std.mem.Allocator, file: *File, pos: Position, row_padding: u32) []const u8 {
//     const src = "";
//     const line_start = if (pos.line - row_padding - 1 > 0) file.line_start(pos.line - row_padding) else 0;
//     var line_end = pos.offset + 1;
//     var i = 0;
//     while (line_end < src.len) {
//         if (src[i] == '\n') {
//             i += 1;
//             if (i == row_padding + 1) break;
//         }
//         line_end += 1;
//     }
//     const lines_src = std.mem.splitScalar(u8, src[line_start..line_end], '\n');
//     const line_no_start = file.find_line_and_col(line_start);
//     var lines_src_formatted = std.ArrayList([]const u8).empty;
//     var j = 0;
//     while (lines_src.next()) |ls| {
//         const line_no = line_no_start.line + i;
//         const line_spaces = std.mem.replaceOwned(u8, allocator, ls, "\t", "    ") catch {};
//         i += 1;
//     }
// }
const Module = struct {
    name: []const u8,
    path: []const u8,
    imports: std.ArrayList(Module) = .empty,
    pub fn init(name: []const u8, path: []const u8) Module {
        return .{ .name = name, .path = path };
    }
};
const Object = struct {
    parent: ?*Scope = null,
    pos: Pos,
    mod: *Module,
    name: []const u8,
    typ: Type,
};
const Scope = struct {
    parent: ?*Scope = null,
    objects: std.StringHashMap(Object),
    start: u32 = 0,
    end: u32 = 0,
    pub fn init(allocator: std.mem.Allocator, parent: ?*Scope) Scope {
        return Scope{ .parent = parent, .objects = std.StringHashMap(Object).init(allocator) };
    }
    pub fn lookup(s: Scope, name: []const u8) ?Object {
        return s.objects.get(name);
    }
    pub fn lookup_parent(s: Scope, name: []const u8) ?Object {
        var scope_: ?Scope = s;
        while (scope_) |sc| {
            if (sc.lookup(name)) |l| return l;
            scope_ = sc.parent;
        }
        return null;
    }
    pub fn lookup_parent_with_scope(s: Scope, name: []const u8) ?struct { scope: Scope, object: Object } {
        var scope_: ?Scope = s;
        while (scope_) |sc| {
            if (sc.lookup(name)) |l| return .{ .scope = scope_, .object = l };
            scope_ = sc.parent;
        }
        return null;
    }
    pub fn insert(s: *Scope, name: []const u8, object: Object) void {
        if (s.objects.get(name) == null) s.objects.put(name, object) catch {};
    }
};
// types
const Type = union(enum) {
    array: struct {
        elem_type: Type,
    },
    enum_: struct {
        name: []const u8,
        fields: []Field,
    },
    error_: struct {},
    fn_: struct {
        params: []Parameter,
        return_type: Type,
    },
    optional: struct {
        base_type: Type,
    },
    pointer: struct {
        base_type: Type,
    },
    primitive: struct {
        kind: enum {
            boolean,
            float,
            integer,
            unsigned,
        },
        size: u8,
    },
    struct_: struct {},
    type,
    void,
    pub fn name(s: Type) []const u8 {
        switch (s) {
            .array => |i| "",
            .enum_ => |i| "",
            .error_ => |i| "",
            .fn_ => |i| "",
            .optional => |i| "",
            .pointer => |i| "",
            .primitive => |i| "",
            .struct_ => |i| "",
            .type => "type",
            .void => "void",
        }
    }
};
const Field = struct { name: []u8, typ: Type };
const Parameter = struct {
    name: []const u8,
    typ: Type,
};

// checker
const Checker = struct {
    allocator: std.mem.Allocator,
    module: *Module,
    env: *Environment,
    file_set: *FileSet,

    scope: *Scope,
    expected_type: ?Type,
    mu: std.Thread.Mutex,
    pub fn init(allocator: std.mem.Allocator, file_set: *FileSet, env: *Environment) Checker {
        // return Checker{ .module = };
    }
    pub fn get_module_scope(s: *Checker, module_name: []const u8, parent: *Scope) Scope {
        s.mu.lock();
        if (s.env.scopes.get(module_name)) |scope| return scope else {
            const scope = Scope.init(s.allocator, parent);
            s.env.scopes.put(module_name, scope);
            return scope;
        }
    }
    pub fn check_files(s: *Checker, files: []Ast.File) void {}
    pub fn check_file(s: *Checker, file: Ast.File) void {}
    pub fn preregister_scopes(s: *Checker, file: Ast.File) void {}
    pub fn preregister_all_scopes(s: *Checker, file: Ast.File) void {}
    pub fn preregister_types(s: *Checker, file: Ast.File) void {}
    pub fn preregister_all_types(s: *Checker, file: Ast.File) void {}
};
const Environment = struct {
    scopes: std.StringHashMap(Scope),
};

// ast
const Ast = union(enum) {
    const File = struct {};
};
