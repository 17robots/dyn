# Interop

Dyn provides Foreign Function Interface (FFI) capabilities to interact with code written in other languages, primarily C.

## Calling C Functions

To call an external C function, declare it with `extern` keyword:

```dyn
// Declare a C function
puts := extern fn(*u8) i32

main := () {
    puts("Hello from C!")
}
```

`extern` keyword tells Dyn that function is defined elsewhere (in a C library) and will be linked at compile time.

## C Types Mapping

Dyn types map to C types as follows:

| Dyn Type      | C Type      |
|---------------|-------------|
| `i8` / `u8`   | `int8_t` / `uint8_t` |
| `i16` / `u16` | `int16_t` / `uint16_t` |
| `i32` / `u32` | `int32_t` / `uint32_t` |
| `i64` / `u64` | `int64_t` / `uint64_t` |
| `f32`         | `float`     |
| `f64`         | `double`    |
| `*T`           | `T*`        |
| `*mut T`       | `T*`        |
| `[*]T` (array) | `T*` with length separate |
| `struct`       | `struct`    |
| `enum`         | `enum`      |

## Linking C Libraries

When using external C functions, you need to link against appropriate libraries:

```dyn
puts := extern fn(*u8) i32
sqrt := extern fn(f64) f64
```

Then compile with linker flags:

```bash
dyn build program.dyn -lm  # link math library
```

Or specify in a build configuration file.

## C String Conversions

C strings are null-terminated pointers to bytes. In Dyn, strings are slices of bytes. Convert between them:

```dyn
strlen := extern fn(*u8) u64

main := () {
    // Dyn string to C string
    dyn_str := "Hello"
    c_str := &dyn_str[0] // get pointer to first byte

    // C string to Dyn string (requires knowing length)
    length := $strlen(c_str)
    dyn_slice := [length]u8{ ptr: c_str, len: length }
}
```

## Callbacks from C

You can pass Dyn functions to C code as callbacks:

```dyn
// C expects: void callback(int value)
register_callback := extern fn(fn(i32)) void

my_callback := fn(i32) {
    println("Callback received: {}", value)
}

main := () {
    register_callback(my_callback)
}
```

## Memory Management Across Boundaries

When allocating memory in C and passing it to Dyn (or vice versa), be careful about ownership:

```dyn
malloc := extern fn(u64) *mut u8
free := extern fn(*mut u8) void

main := () {
    // Allocate in C
    buffer := malloc(1024)

    // Use it in Dyn
    // ...

    // Free in C when done
    defer free(buffer)
}
```

**Important:** Never free memory allocated by one language using other language's allocator, as they may have different allocation strategies.

## Struct Compatibility

Dyn structs can be compatible with C structs when using primitive types only:

```dyn
// C:
// struct Point { double x; double y; };

Point := struct {
    x: f64,
    y: f64
}

process_point := extern fn(*mut Point) void

main := () {
    mut point := Point{ x: 1.0, y: 2.0 }
    process_point(&point)
}
```

Note: Dyn may add padding differently than C. For guaranteed compatibility, use `packed` attribute:

```dyn
Point := packed struct {
    x: f64,
    y: f64
}
```

## Common C Libraries Examples

### Using POSIX functions

```dyn
open := extern fn(*u8, i32) i32
read := extern fn(i32, *mut u8, u64) i64
close := extern fn(i32) i32

main := () ! {
    fd := open("file.txt", 0)
    defer if fd >= 0 close(fd)

    if fd < 0 {
        $panic("Failed to open file")
    }

    // ... read from file
}
```

### Using Standard Library

```dyn
printf := extern fn(*u8, ...) i32

main := () {
    printf("Value: %d\n", 42)
}
```
