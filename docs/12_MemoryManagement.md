# Memory Management
Dyn allows you to allocate memory on either the stack or the heap

## Stack
Anytime you create a variable without an allocator, that creates the variable on
the stack

```
main := () {
    a: i32 = 1 // on the stack
}
```
It is recommended to use the stack whenever you can, and it is best suited for
data that:
- Is smaller, more local
- Has its size known at compile time
- Is performance-critical
The variables on the stack get cleared in reverse order of declaration

## Heap
Values can also be stored on the heap, which is larger than the stack. This is
best suited for data that:
- Is a large data structure to prevent stack overflow
- Is dynamically sized
- Is persistent beyond the current scope (going from function to function for
example)
- Is shared data

In order to allocate on the heap, you need to use an allocator, though you can
allocate data on the stack like it's a heap as well, but to use the heap
normally also, you need to use an allocator and then allocate to it

## Allocators
Dyn provides different allocators in the standard library, there are a couple of
different allocators to achieve different purposes:

### General
The general allocator is a general-use allocator that checks for double-free or
use-after-frees and leaks, it's designed for safety, not necessarily for
performance. The things allocated here need to be freed (defer is useful for
this)

### Arena
Arena allocators provide a mechanism for group freeing, so you can allocate and
worry about one clean at the end, but this won't check for any of the things the
general one will. It also needs a supporting allocator

#### Page
Page allocators grabs pages of data whenever something is allocated, so it is
really inefficient, but this also needs a corresponding free like the general
allocator

### Buffer
Buffer allocators are the only allocators that do not allocate to the heap,
instead it allocates to a buffer (array) created on the stack, which can be good
if you do not have access to the heap but still need dynamic data

