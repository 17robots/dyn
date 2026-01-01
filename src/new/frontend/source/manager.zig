const std = @import("std");

pub const Pos = u32;
pub const Span = struct {
    start: Pos,
    end: Pos,
    pub fn from(start: Pos, end: Pos) Span {
        return .{ .start = start, .end = end };
    }
    pub fn length(self: Span) u32 {
        return self.end - self.start;
    }
};
pub const SourceFile = struct {
    id: u32,
    name: []const u8,
    path: []const u8,
    content: []const u8,
    line_offsets: std.ArrayList(u32),
    pub fn init(allocator: std.mem.Allocator, id: u32, name: []const u8, path: []const u8, content: []const u8) SourceFile {
        var self = SourceFile{ .id = id, .name = name, .path = path, .content = content, .line_offsets = .empty };
        self.line_offsets.append(allocator, 0) catch {};
        for (content, 0..) |c, i| {
            if (c == '\n') self.line_offsets.append(allocator, @intCast(i + 1)) catch {};
        }
        return self;
    }
    pub fn deinit(self: *SourceFile, allocator: std.mem.Allocator) void {
        self.line_offsets.deinit(allocator);
    }
    pub fn get_line_col(self: SourceFile, pos: Pos) struct { line: u32, col: u32 } {
        var line: u32 = 1;
        for (self.line_offsets.items, 0..) |offset, i| {
            if (pos < offset) {
                line = @intCast(i);
                const line_start = if (i > 0) self.line_offsets.items[i - 1] else 0;
                return .{ .line = line, .col = pos - line_start + 1 };
            }
        }
        return .{ .line = line, .col = 1 };
    }
    pub fn get_line(self: SourceFile, line_num: u32) ?[]const u8 {
        if (line_num == 0 or line_num > self.line_offsets.items.len) return null;
        const start = if (line_num > 1) self.line_offsets.items[line_num - 2] else 0;
        const end = if (line_num <= self.line_offsets.items.len) self.line_offsets.items[line_num - 1] else self.content.len;
        const slice_end = if (end > 0 and self.content[end - 1] == '\n') end - 1 else end;
        return self.content[start..slice_end];
    }
};
pub const SourceManager = struct {
    allocator: std.mem.Allocator,
    files: std.AutoArrayHashMap(u32, SourceFile),
    next_id: u32 = 1,
    pub fn init(allocator: std.mem.Allocator) SourceManager {
        return .{ .allocator = allocator, .files = std.AutoArrayHashMap(u32, SourceFile).init(allocator) };
    }
    pub fn deinit(self: *SourceManager) void {
        var it = self.files.iterator();
        while (it.next()) |n| n.value_ptr.deinit(self.allocator);
    }
    pub fn add_file(self: *SourceManager, name: []const u8, path: []const u8, content: []const u8) u32 {
        const id = self.next_id;
        self.next_id += 1;
        const file = SourceFile.init(self.allocator, id, name, path, content);
        self.files.put(id, file) catch {};
        return id;
    }
    pub fn get_file(self: SourceManager, id: u32) ?*SourceFile {
        return self.files.getPtr(id);
    }
    pub fn get_source_slice(self: *SourceManager, file_id: u32, span: Span) ?[]const u8 {
        const file = self.files.getPtr(file_id) orelse return null;
        if(span.end > file.content.len) return null;
        return file.content[span.start..span.end];
    }
};
