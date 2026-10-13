package main

import "core:fmt"
import vmem "core:mem/virtual"

MAX_DEPTH :: 18

Node :: struct {
	left, right: ^Node,
}

build_tree :: proc(depth: int) -> ^Node {
	node := new(Node)
	if depth > 0 {
		node.left = build_tree(depth - 1)
		node.right = build_tree(depth - 1)
	}
	return node
}

count :: proc(node: ^Node) -> i64 {
	if node.left == nil {
		return 1
	}
	return 1 + count(node.left) + count(node.right)
}

// Each tree lives in a growing virtual-memory arena that is reset after counting.
main :: proc() {
	arena: vmem.Arena
	_ = vmem.arena_init_growing(&arena)
	defer vmem.arena_destroy(&arena)
	context.allocator = vmem.arena_allocator(&arena)
	total: i64 = 0
	for depth := 4; depth <= MAX_DEPTH; depth += 2 {
		iterations := 1 << uint(MAX_DEPTH - depth + 4)
		for _ in 0 ..< iterations {
			total += count(build_tree(depth))
			vmem.arena_free_all(&arena)
		}
	}
	fmt.println(total)
}
