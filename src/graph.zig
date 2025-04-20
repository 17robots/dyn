const std = @import("std");
pub fn Graph(comptime T: type) type {
    return struct {
        const Edge = struct {
            from: T,
            to: T,
        };
        nodes: std.ArrayList(T),
        edges: std.ArrayList(Edge),
        allocator: std.mem.Allocator,
        pub fn init(allocator: *std.mem.Allocator) @This() {
            return @This(){
                .nodes = std.ArrayList(T).init(allocator),
                .edges = std.ArrayList(Edge).init(allocator),
                .allocator = allocator.*,
            };
        }
        pub fn deinit(self: *@This()) void {
            self.nodes.deinit();
            self.edges.deinit();
        }
        pub fn addNode(self: *@This(), node: T) void {
            self.nodes.append(node) catch unreachable;
        }
        pub fn addEdge(self: *@This(), from: T, to: T) void {
            self.edges.append(.{ .from = from, .to = to }) catch unreachable;
        }
        pub fn getNode(self: *@This(), index: usize) ?T {
            if (index >= self.nodes.items.len) return null;
            return self.nodes.items[index];
        }
        pub fn getEdge(self: *@This(), index: usize) ?Edge {
            if (index >= self.edges.items.len) return null;
            return self.edges.items[index];
        }
        pub fn topologicalSort(self: *@This()) ?[]T {
            var visited = std.ArrayList(bool).init(self.allocator);
            defer visited.deinit();
            var result = std.ArrayList(T).init(self.allocator);
            defer result.deinit();
            var stack = std.ArrayList(T).init(self.allocator);
            defer stack.deinit();
            for (self.nodes.items, 0..) |node, i| {
                if (!visited.items[i]) {
                    self.topologicalSortHelper(node, &visited, &stack, &result);
                }
            }
            return result.toOwnedSlice();
        }
        fn topologicalSortHelper(self: *@This(), node: T, visited: *std.ArrayList(bool), stack: *std.ArrayList(T), result: *std.ArrayList(T)) void {
            visited.items[node.index()] = true;
            for (self.edges.items) |edge| {
                if (edge.from == node) {
                    self.topologicalSortHelper(edge.to, visited, stack, result);
                }
            }
            stack.append(node) catch unreachable;
        }
    };
}
