# Memory Management

Dyn allows you to allocate memory on either stack or heap.

## Stack

Anytime you create a variable without an allocator, that creates variable on stack.

```dyn
main := () {
    a: i32 = 1 // on stack
}
```

It is recommended to use stack whenever you can, and it is best suited for data that:

- Is smaller, more local
- Has its size known at compile time
- Is performance-critical

Variables on stack get cleared in reverse order of declaration.

## Heap

Values can also be stored on heap, which is larger than stack. This is best suited for data that:

- Is a large data structure to prevent stack overflow
- Is dynamically sized
- Is persistent beyond current scope (going from function to function for example)
- Is shared data

In order to allocate on heap, you need to use an allocator, though you can allocate data on stack like it's a heap as well, but to use heap normally also, you need to use an allocator and then allocate to it.

## Allocators

Dyn provides different allocators in standard library, there are a couple of different allocators to achieve different purposes.

### General

General allocator is a general-use allocator that checks for double-free or use-after-frees and leaks, it's designed for safety, not necessarily for performance. Things allocated here need to be freed (defer is useful for this).

### Arena

Arena allocators provide a mechanism for group freeing, so you can allocate and worry about one clean at end, but this won't check for any of things general one will. It also needs a supporting allocator.

#### Page

Page allocators grabs pages of data whenever something is allocated, so it is really inefficient, but this also needs a corresponding free like general allocator.

### Buffer

Buffer allocators are only allocators that do not allocate to heap, instead it allocates to a buffer (array) created on stack, which can be good if you do not have access to heap but still need dynamic data.
