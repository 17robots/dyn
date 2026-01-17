# Builtins

Dyn provides built-in functions that are available without any imports. These are fundamental operations that compiler has special knowledge of.

## Why Built-in?

Functions are built-in when they:

- Cannot be implemented in pure Dyn code
- Need compiler intrinsics for proper behavior
- Are so fundamental that they should always be available
- Require special optimization or handling by compiler

## Type Information

Get type information at compile time or runtime.

- `$size_of(type)` - returns size in bytes of a type
- `$align_of(type)` - returns alignment requirements of a type
- `$type_of(value)` - returns type of a value

## Memory Operations

Low-level memory manipulation.

- `$copy(dst, src, count)` - copies count bytes from src to dst
- `$set(dst, value, count)` - sets count bytes at dst to value
- `$move(dst, src, count)` - moves count bytes from src to dst (handles overlap)

## Panic and Control

Control flow for exceptional situations.

- `$panic(message)` - immediately stops execution with an error message
- `$unreachable()` - marks code that should never be reached (optimization hint)

## Math Functions

Mathematical operations that are hardware-accelerated or require special handling.

- `$abs(x)` - absolute value of integer or float
- `$min(a, b)` / `$max(a, b)` - minimum/maximum of two values
- `$clamp(value, min, max)` - clamps value between min and max
- `$floor(x)` / `$ceil(x)` / `$round(x)` - float rounding operations
- `$sqrt(x)` - square root
- `$pow(base, exponent)` - exponentiation
- `$sin(x)` / `$cos(x)` / `$tan(x)` - trigonometric functions
- `$log(x)` / `$log2(x)` / `$log10(x)` - logarithm functions

## String and Bytes

Operations on byte sequences.

- `$len(slice)` - returns length of an array/slice/string
- `$cap(slice)` - returns capacity of an array/slice
- `$memcpy(dst, src, n)` - optimized memory copy

## Platform-Specific

Access to platform-specific functionality.

- `$platform` - returns current platform target
- `$arch` - returns current architecture target

## Reflection and Metaprogramming

Compile-time reflection capabilities.

- `$type_name(type)` - gets name of a type as a string literal
- `$field_names(type)` - gets field names of a struct type
- `$has_field(type, field)` - checks if a type has a field
- `$is_comptime(value)` - checks if a value is known at compile time

## Note

This is an overview of builtin concepts. For detailed function signatures, parameter types, and usage examples, see standard library reference documentation.
