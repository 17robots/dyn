const std = @import("std");
const Span = @import("token.zig").Span;

pub const FileId = u32;

pub const Source = struct {
    id: FileId,
    name: []const u8,
    content: []const u8,
};

pub const SourceLocation = struct {
    file_id: FileId,
    span: Span,
};

pub const SourceManager = struct {
    allocator: std.mem.Allocator,
    sources: std.ArrayList(Source),
    lookup: std.StringHashMap(FileId),
    pub fn init(allocator: std.mem.Allocator) SourceManager {
        return .{ .allocator = allocator, .sources = std.ArrayList(Source).empty, .lookup = std.StringHashMap(FileId).init(allocator) };
    }
    pub fn deinit(s: *SourceManager) void {
        s.lookup.deinit();
        for(s.sources.items) |source| {
            s.allocator.free(source.name);
            s.allocator.free(source.content);
        }
        s.sources.deinit();
    }
    pub fn load_file(s: *SourceManager, path: []const u8) !FileId {
        if(s.lookup.get(path)) |fileid| return fileid;
        const file = try std.fs.cwd().openFile(path, .{ .mode = .read_only });
        defer file.close();
        const content = try file.readToEndAlloc(s.allocator, (try file.stat()).size);
        const file_id: FileId = @intCast(s.sources.items.len);
        const owned_path = try s.allocator.dupe(u8, path);
        errdefer s.allocator.free(owned_path);
        try s.sources.append(s.allocator, .{ .id = file_id, .name = owned_path, .content = content });
        try s.lookup.put(owned_path, file_id);
        return file_id;
    }
    pub fn resolve_location(s: *SourceManager, loc: SourceLocation) struct { file_name: []const u8, line: usize, col: usize } {
        const source = &s.sources.items[loc.file_id];
        var line: usize = 1;
        var line_start_index: usize = 0;
        for (source.content[0..loc.span.start], 0..loc.span.start) |char, i| {
            if (char == '\n') {
                line += 1;
                line_start_index = i + 1;
            }
        }
        return .{ .file_name = source.name, .line = line, .col = loc.span.start - line_start_index + 1 };
    }
};
