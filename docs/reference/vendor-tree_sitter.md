# vendor/tree_sitter

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/vendor-packages/abi/main.dyn](../../tests/vendor-packages/abi/main.dyn)

Reviewed behavioral fixtures: [projects/tree-sitter-example/main.dyn](../../projects/tree-sitter-example/main.dyn), [tests/vendor-packages.py](../../tests/vendor-packages.py), [tests/vendor-packages/abi/main.dyn](../../tests/vendor-packages/abi/main.dyn)

## Declarations and source contracts

## Source: compiler/vendor/tree_sitter/raw.dyn

## Source: compiler/vendor/tree_sitter/tree_sitter.dyn

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L5)

Tree-sitter C ABI. Parser/Tree are provider-owned; Node borrows its Tree.

```dyn
pub type Parser = rawptr
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L6)

```dyn
pub type Tree = rawptr
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L7)

```dyn
pub type Language = rawptr
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L8)

```dyn
pub struct Point { row: u32, column: u32 }
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L9)

```dyn
pub struct Edit { start_byte: u32, old_end_byte: u32, new_end_byte: u32, start_point: Point, old_end_point: Point, new_end_point: Point }
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L10)

```dyn
pub struct Node { context: [4]u32, id: rawptr, tree: Tree }
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L11)

```dyn
pub struct ParseResult { tree: Tree, ok: bool }
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L13)

```dyn
pub fn parser_create_owned() Parser
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L14)

```dyn
pub fn parser_destroy_owned(parser: Parser)
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L15)

```dyn
pub fn parser_language(parser: Parser, language: Language) bool
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L18)

Source borrowed only during call. Old tree remains caller-owned. Edit it first
when reparsing changed source. Syntax errors are represented in a successful tree.

```dyn
pub fn parse(parser: Parser, old_tree: Tree, source: []const u8) ParseResult
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L26)

```dyn
pub fn tree_destroy_owned(tree: Tree)
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L27)

```dyn
pub fn tree_copy_owned(tree: Tree) Tree
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L30)

Coordinates are UTF-8 byte columns, not code points. Nodes obtained before an
edit must be reacquired (this wrapper does not expose ts_node_edit).

```dyn
pub fn tree_edit(tree: Tree, edit: *const Edit) bool
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L37)

```dyn
pub fn root(tree: Tree) Node
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L38)

```dyn
pub fn node_valid(node: Node) bool
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L39)

```dyn
pub fn node_start(node: Node) u32
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L40)

```dyn
pub fn node_end(node: Node) u32
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L41)

```dyn
pub fn node_has_error(node: Node) bool
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L42)

```dyn
pub fn child_count(node: Node) u32
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L43)

```dyn
pub fn child(node: Node, index: u32) Node
```

[Source](../../compiler/vendor/tree_sitter/tree_sitter.dyn#L45)

Type name borrows grammar storage; grammar must remain loaded.

```dyn
pub fn node_type(node: Node, maximum: usize) c.BytesResult
```
