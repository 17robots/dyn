package main

import "fmt"

const maxDepth = 18

type Node struct {
	left, right *Node
}

func buildTree(depth int) *Node {
	node := &Node{}
	if depth > 0 {
		node.left = buildTree(depth - 1)
		node.right = buildTree(depth - 1)
	}
	return node
}

func count(node *Node) int64 {
	if node.left == nil {
		return 1
	}
	return 1 + count(node.left) + count(node.right)
}

// Trees are garbage collected.
func main() {
	total := int64(0)
	for depth := 4; depth <= maxDepth; depth += 2 {
		iterations := 1 << (maxDepth - depth + 4)
		for i := 0; i < iterations; i++ {
			total += count(buildTree(depth))
		}
	}
	fmt.Println(total)
}
